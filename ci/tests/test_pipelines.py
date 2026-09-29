"""Story 1.2: structural tests on the Azure DevOps pipelines in pipelines/.

The deploy pipeline is compiled offline (templates and expressions resolved, see
pipeline_model.py) and checked against spine AD-17: one WIF service connection per
stack owner, approval environments and saved plans. Each checker returns a list of
problems; the mutation tests prove the checkers catch a missing approval environment,
an apply without a saved plan and a wrong service connection.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from pipeline_model import PIPELINES, REPO_ROOT, compile_pipeline, load, steps_of

SERVICE_CONNECTIONS = {"shared": "azure-shared", "dev": "azure-dev", "prod": "azure-prod"}
APPROVAL_ENVIRONMENTS = {"shared", "prod"}  # approval checks set by infra/bootstrap/ado-setup.sh
SCRIPT_ACTIONS = {"ci/terraform-apply.sh": "apply", "ci/migrate.sh": "migrate", "ci/code-deploy.sh": "code"}


def _read_lib_value(name: str) -> str:
    match = re.search(rf'^readonly {name}="?([^"\n]+)"?$', (REPO_ROOT / "ci" / "lib.sh").read_text(), re.M)
    assert match, f"{name} not found in ci/lib.sh"
    return match.group(1)


def _owner(target: str) -> str:
    return target.split("/", 1)[0]


def _azure_cli_steps(stage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in stage.get("jobs", [])
        for step in steps_of(job)
        if str(step.get("task", "")).startswith("AzureCLI@")
    ]


def _action(stage: dict[str, Any]) -> tuple[str, str] | None:
    for step in _azure_cli_steps(stage):
        kind = SCRIPT_ACTIONS.get(step["inputs"].get("scriptPath"))
        if kind:
            return kind, str(step["inputs"].get("arguments", "")).split()[0]
    return None


# --- checkers -------------------------------------------------------------------------


def gate_problems(pipeline: dict[str, Any]) -> list[str]:
    """Every gated stage deploys through its ADO environment; check stages never do."""
    problems = []
    for stage in pipeline["stages"]:
        name, jobs = stage["stage"], stage.get("jobs", [])
        deployments = [job for job in jobs if "deployment" in job]
        action = _action(stage)
        if name.endswith("_check"):
            if deployments:
                problems.append(f"{name}: a check stage must not use an environment (it would ask for approval)")
            continue
        if action is None:
            problems.append(f"{name}: no apply, migrate or code-deploy step")
            continue
        owner = _owner(action[1])
        if len(jobs) != 1 or len(deployments) != 1:
            problems.append(f"{name}: must be one deployment job in environment {owner}")
            continue
        if deployments[0].get("environment") != owner:
            problems.append(
                f"{name}: runs in environment {deployments[0].get('environment')!r}, expected {owner!r}"
                + (" (the approval environment)" if owner in APPROVAL_ENVIRONMENTS else "")
            )
        condition = str(stage.get("condition", ""))
        if "succeeded()" not in condition or f"dependencies.{name}_check.outputs[" not in condition:
            problems.append(f"{name}: must run only when {name}_check succeeded and found work")
    return problems


def connection_problems(pipeline: dict[str, Any]) -> list[str]:
    """Each stage signs in only with its stack owner's WIF service connection."""
    problems = []
    stages = {stage["stage"]: stage for stage in pipeline["stages"]}
    for name, stage in stages.items():
        gated = stages.get(name.removesuffix("_check"), stage)
        action = _action(gated)
        if action is None:
            continue
        expected = SERVICE_CONNECTIONS[_owner(action[1])]
        for step in _azure_cli_steps(stage):
            used = step["inputs"].get("azureSubscription")
            if used != expected:
                problems.append(f"{name}: uses service connection {used!r}, expected {expected!r}")
    return problems


def saved_plan_problems(pipeline: dict[str, Any]) -> list[str]:
    """Every apply uses the saved plan that its own check stage produced and tag-gated."""
    problems = []
    stages = {stage["stage"]: stage for stage in pipeline["stages"]}
    for name, stage in stages.items():
        action = _action(stage)
        if name.endswith("_check") or not action or action[0] != "apply":
            continue
        check = stages.get(f"{name}_check")
        if check is None:
            problems.append(f"{name}: no plan stage")
            continue
        plan_steps = [
            s for s in _azure_cli_steps(check) if s["inputs"].get("scriptPath") == "ci/terraform-plan.sh"
        ]
        if len(plan_steps) != 1 or str(plan_steps[0]["inputs"]["arguments"]).split()[0] != action[1]:
            problems.append(f"{name}: its check stage must run ci/terraform-plan.sh {action[1]}")
            continue
        published = [s for job in check["jobs"] for s in steps_of(job) if "publish" in s]
        artifacts = {s.get("artifact") for s in published}
        if len(artifacts) != 1 or "hasWork" not in str(published[0].get("condition", "")):
            problems.append(f"{name}: the plan stage must publish one saved-plan artifact, only when it has changes")
            continue
        (artifact,) = artifacts
        steps = [s for job in stage["jobs"] for s in steps_of(job)]
        if not any(s.get("download") == "current" and s.get("artifact") == artifact for s in steps):
            problems.append(f"{name}: does not download the saved plan {artifact}")
        apply_steps = [
            s for s in _azure_cli_steps(stage) if s["inputs"].get("scriptPath") == "ci/terraform-apply.sh"
        ]
        args = str(apply_steps[0]["inputs"].get("arguments", "")).split()
        if len(args) != 2 or not args[1].endswith(f"/{artifact}/tfplan"):
            problems.append(f"{name}: applies {args[1:] or 'no plan'}, not the saved plan from {artifact}")
        if "hasWork" not in str(stage.get("condition", "")):
            problems.append(f"{name}: must be skipped when the plan has no changes")
        for step in [*plan_steps, *apply_steps]:
            if step.get("env", {}).get("SYSTEM_ACCESSTOKEN") != "$(System.AccessToken)":
                problems.append(f"{name}: Terraform needs SYSTEM_ACCESSTOKEN to refresh its OIDC token (ci/lib.sh)")
    return problems


def all_problems(pipeline: dict[str, Any]) -> list[str]:
    return gate_problems(pipeline) + connection_problems(pipeline) + saved_plan_problems(pipeline)


@pytest.fixture(scope="module")
def deploy() -> dict[str, Any]:
    return compile_pipeline("deploy.yml")


# --- deploy pipeline ------------------------------------------------------------------


def test_story_1_2_deploy_pipeline_structure(deploy: dict[str, Any]) -> None:
    """The compiled deploy pipeline. Covers: triggers only on merge to main; passes every
    structural check (gates, service connections, saved plans); shared and prod apply only in
    their approval environments."""
    # Triggers only on merge to main.
    raw = load(PIPELINES / "deploy.yml")
    assert raw["trigger"] == {"batch": True, "branches": {"include": ["main"]}}
    assert raw["pr"] == "none"

    # Passes every structural check.
    assert all_problems(deploy) == []

    # Shared and prod apply only in their approval environments.
    environments = {
        _action(stage): job["environment"]
        for stage in deploy["stages"]
        for job in stage["jobs"]
        if "deployment" in job
    }
    assert environments[("apply", "shared/foundation")] == "shared"
    assert environments[("apply", "prod/foundation")] == "prod"
    assert environments[("apply", "prod/app")] == "prod"
    assert environments[("migrate", "prod")] == "prod"
    assert environments[("code", "prod")] == "prod"
    assert environments[("apply", "dev/foundation")] == "dev"


# --- mutations the checkers must catch ---------------------------------------------------


def test_story_1_2_checkers_catch_mutations(deploy: dict[str, Any]) -> None:
    """Mutations of the deploy pipeline the checkers must catch. Covers: a missing approval
    environment (wrong environment; plain job); an apply without a saved plan (no plan
    argument; no download); a wrong service connection."""
    # A missing approval environment.
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation")
    stage["jobs"][0]["environment"] = "dev"
    assert any("the approval environment" in p for p in gate_problems(mutated))

    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "shared_foundation")
    job = stage["jobs"][0]
    stage["jobs"] = [{"job": "apply", "steps": steps_of(job)}]  # a plain job: no environment, no approval
    assert any("must be one deployment job" in p for p in gate_problems(mutated))

    # An apply without a saved plan.
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "dev_foundation")
    (apply_step,) = _azure_cli_steps(stage)
    apply_step["inputs"]["arguments"] = "dev/foundation"
    assert any("not the saved plan" in p for p in saved_plan_problems(mutated))

    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation")
    steps = steps_of(stage["jobs"][0])
    steps[:] = [s for s in steps if "download" not in s]
    assert any("does not download the saved plan" in p for p in saved_plan_problems(mutated))

    # A wrong service connection.
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation_check")
    _azure_cli_steps(stage)[0]["inputs"]["azureSubscription"] = "azure-dev"
    assert connection_problems(mutated) == ["prod_foundation_check: uses service connection 'azure-dev', expected 'azure-prod'"]


# --- repo-wide guards: scripts behind the deploy stages, YAML, pinned downloads -----------


def test_story_1_2_repo_guards() -> None:
    """Repo-wide scans of pipelines/ and ci/. Covers: no auto-approve and apply only from a saved
    plan; operator steps never run in a pipeline; no GitHub Actions and no secrets, ids or
    variables in YAML; tool downloads are pinned by checksum."""
    # No auto-approve; apply only from a saved plan.
    files = [*PIPELINES.rglob("*.yml"), *(REPO_ROOT / "ci").glob("*.sh")]
    for path in files:
        assert "auto-approve" not in path.read_text(encoding="utf-8"), path
    applies = [
        (path.name, line.strip())
        for path in (REPO_ROOT / "ci").glob("*.sh")
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*terraform\b.*\bapply\b", line)
    ]
    assert applies == [("terraform-apply.sh", 'terraform -chdir="$dir" apply -input=false -lock-timeout=5m tfplan')]

    # Operator steps never run in a pipeline.
    operator_scripts = [p.name for p in (REPO_ROOT / "infra" / "bootstrap").glob("*.sh") if p.name != "lib.sh"]
    assert "ado-setup.sh" in operator_scripts
    # Code lines only: comments may name an operator step to explain an order.
    texts = [
        "\n".join(line for line in p.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
        for p in [*PIPELINES.rglob("*.yml"), *(REPO_ROOT / "ci").glob("*.sh")]
    ]
    for name in operator_scripts:
        assert not any(name in text for text in texts), name

    # No GitHub Actions and no secrets in YAML.
    assert not (REPO_ROOT / ".github" / "workflows").exists()
    guid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    for path in PIPELINES.rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert not guid.search(text), f"{path}: ids come from the service connection, not YAML"
        # Only runtime references like $(System.AccessToken) may follow a secret-like key.
        assert not re.search(r"(?i)(password|secret|pat|token)\s*:\s*(?!\$\()\S", text), path
        assert "variables:" not in text, f"{path}: no pipeline variables (nothing to store)"

    # Tool downloads are pinned by checksum.
    for name in ("TERRAFORM_SHA256_LINUX_AMD64", "GITLEAKS_SHA256_LINUX_X64", "UV_SHA256_LINUX_X64"):
        assert re.fullmatch(r"[0-9a-f]{64}", _read_lib_value(name)), name


# --- PR build and weekly scan ---------------------------------------------------------------


def _check_subcommands(pipeline: dict[str, Any]) -> dict[str, str]:
    found = {}
    for job in pipeline["jobs"]:
        for step in steps_of(job):
            match = re.fullmatch(r"ci/checks\.sh (\w+)", str(step.get("bash", "")))
            if match:
                found[job["job"]] = match.group(1)
    return found


def test_story_1_2_pr_build_and_weekly_scan() -> None:
    """Covers: the PR build runs every check and scans the whole history; the weekly scan audits
    main every week."""
    # The PR build runs every check and scans the whole history.
    pr = compile_pipeline("pr.yml")
    assert pr["trigger"] == "none"
    assert pr["pr"] == {"branches": {"include": ["main"]}}
    subcommands = _check_subcommands(pr)
    assert sorted(subcommands.values()) == ["audit", "lint", "secrets", "terraform", "test"]
    secrets = next(job for job in pr["jobs"] if job["job"] == "secrets")
    assert {"checkout": "self", "fetchDepth": 0} in secrets["steps"]  # gitleaks scans the whole history

    # The weekly scan audits main every week.
    weekly = compile_pipeline("weekly-scan.yml")
    assert weekly["trigger"] == "none" and weekly["pr"] == "none"
    (schedule,) = weekly["schedules"]
    assert schedule["branches"] == {"include": ["main"]}
    assert schedule["always"] is True
    minute, hour, dom, month, dow = schedule["cron"].split()
    assert dom == "*" and month == "*" and dow not in ("*",)  # weekly
    assert list(_check_subcommands(weekly).values()) == ["audit"]
