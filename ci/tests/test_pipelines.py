"""Story 1.2: structural tests on the Azure DevOps pipelines in pipelines/.

The deploy pipeline is compiled offline (templates and expressions resolved, see
pipeline_model.py) and checked against spine AD-17: stage order, one WIF service
connection per stack owner, approval environments, saved plans and the tag gate.
Each checker returns a list of problems; the mutation tests prove the checkers catch
a stage-order swap, a missing approval environment and an apply without a saved plan.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
from pipeline_model import PIPELINES, REPO_ROOT, compile_pipeline, depends_on, expand, load, steps_of

# AD-17 steps 2, 4, 6, 7, 9 for Dev, then Prod (story 1.2 "Stack order per AD-17").
AD17_ORDER = [
    ("apply", "shared/foundation"),
    ("apply", "dev/foundation"),
    ("migrate", "dev"),
    ("apply", "dev/app"),
    ("code", "dev"),
    ("apply", "prod/foundation"),
    ("migrate", "prod"),
    ("apply", "prod/app"),
    ("code", "prod"),
]
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


def order_problems(pipeline: dict[str, Any]) -> list[str]:
    """The stage graph is one chain of (check, gated) pairs in the AD-17 order."""
    stages = {stage["stage"]: stage for stage in pipeline["stages"]}
    starts = [name for name, stage in stages.items() if depends_on(stage) == []]
    if len(starts) != 1:
        return [f"expected exactly one first stage, found {starts}"]
    sequence, seen, check = [], set(), starts[0]
    while check:
        gated = [name for name, stage in stages.items() if depends_on(stage) == [check]]
        if len(gated) != 1:
            return [f"stage {check} must be followed by exactly one gated stage, found {gated}"]
        seen.update((check, gated[0]))
        sequence.append(_action(stages[gated[0]]))
        following = [
            name for name, stage in stages.items() if sorted(depends_on(stage)) == sorted([check, gated[0]])
        ]
        if len(following) > 1:
            return [f"the chain forks after {gated[0]}: {following}"]
        check = following[0] if following else ""
    problems = []
    if sequence != AD17_ORDER:
        problems.append(f"deploy order {sequence} is not the AD-17 order {AD17_ORDER}")
    orphans = set(stages) - seen
    if orphans:
        problems.append(f"stages outside the AD-17 chain: {sorted(orphans)}")
    return problems


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


_STAGE_OUTPUT = re.compile(r"dependencies\.(\w+)\.outputs\['(\w+)\.(\w+)\.(\w+)'\]")
_STEP_OUTPUT = re.compile(r"variables\['(\w+)\.(\w+)'\]")


def _emits(step: dict[str, Any], var: str) -> bool:
    """True when the step's script sets VAR as an output variable (ci/lib.sh set_output)."""
    if "inputs" in step:
        script = step["inputs"].get("scriptPath", "")
    else:
        script = str(step.get("bash", "")).split(" ")[0]
    path = REPO_ROOT / script
    return bool(script) and path.is_file() and re.search(rf"\bset_output {var}\b", path.read_text()) is not None


def _resolve_step(stage: dict[str, Any], job_name: str | None, step_name: str, var: str) -> str | None:
    jobs = [j for j in stage.get("jobs", []) if job_name is None or j.get("job") == job_name]
    if not jobs:
        return f"no job {job_name!r}"
    steps = [s for s in steps_of(jobs[0]) if s.get("name") == step_name]
    if len(steps) != 1:
        return f"no step named {step_name!r} in job {jobs[0].get('job')!r}"
    if not _emits(steps[0], var):
        return f"step {step_name!r} does not set output {var!r}"
    return None


def output_problems(pipeline: dict[str, Any]) -> list[str]:
    """Every output variable a condition reads resolves to a job, a named step and a script that sets it."""
    problems = []
    stages = {stage["stage"]: stage for stage in pipeline["stages"]}
    for name, stage in stages.items():
        for stage_ref, job, step, var in _STAGE_OUTPUT.findall(str(stage.get("condition", ""))):
            if stage_ref not in stages:
                problems.append(f"{name}: condition reads unknown stage {stage_ref}")
                continue
            error = _resolve_step(stages[stage_ref], job, step, var)
            if error:
                problems.append(f"{name}: {stage_ref}.outputs['{job}.{step}.{var}']: {error}")
        for job in stage.get("jobs", []):
            for s in steps_of(job):
                for step, var in _STEP_OUTPUT.findall(str(s.get("condition", ""))):
                    error = _resolve_step({"jobs": [job]}, None, step, var)
                    if error:
                        problems.append(f"{name}: variables['{step}.{var}']: {error}")
    return problems


def chain_condition(previous: str) -> str:
    return (
        f"and(not(canceled()), or(eq(dependencies.{previous}.result, 'Succeeded'), "
        f"and(eq(dependencies.{previous}_check.result, 'Succeeded'), "
        f"eq(dependencies.{previous}_check.outputs['check.check.hasWork'], 'false'))))"
    )


def chain_problems(pipeline: dict[str, Any]) -> list[str]:
    """A step starts only when the previous one deployed, or its check found nothing to do."""
    problems = []
    for stage in pipeline["stages"]:
        name, deps = stage["stage"], depends_on(stage)
        if not name.endswith("_check") or deps == []:
            continue
        if len(deps) != 2 or deps[0] != f"{deps[1]}_check":
            problems.append(f"{name}: must depend on the previous step's check and gated stages, got {deps}")
            continue
        if " ".join(str(stage.get("condition", "")).split()) != chain_condition(deps[1]):
            problems.append(f"{name}: condition must be {chain_condition(deps[1])}")
    return problems


def all_problems(pipeline: dict[str, Any]) -> list[str]:
    return (
        order_problems(pipeline)
        + gate_problems(pipeline)
        + connection_problems(pipeline)
        + saved_plan_problems(pipeline)
        + output_problems(pipeline)
        + chain_problems(pipeline)
    )


@pytest.fixture(scope="module")
def deploy() -> dict[str, Any]:
    return compile_pipeline("deploy.yml")


def _compile_raw(raw: dict[str, Any]) -> dict[str, Any]:
    return expand(raw, {}, PIPELINES)


# --- deploy pipeline ------------------------------------------------------------------


def test_story_1_2_deploy_triggers_on_merge_to_main_one_run_at_a_time() -> None:
    raw = load(PIPELINES / "deploy.yml")
    assert raw["trigger"] == {"batch": True, "branches": {"include": ["main"]}}
    assert raw["pr"] == "none"
    assert raw["lockBehavior"] == "sequential"
    assert "schedules" not in raw


def test_story_1_2_deploy_passes_every_structural_check(deploy: dict[str, Any]) -> None:
    assert all_problems(deploy) == []


def test_story_1_2_migrations_run_after_foundation_and_before_app(deploy: dict[str, Any]) -> None:
    assert order_problems(deploy) == []
    for env in ("dev", "prod"):
        assert AD17_ORDER.index(("apply", f"{env}/foundation")) < AD17_ORDER.index(("migrate", env))
        assert AD17_ORDER.index(("migrate", env)) < AD17_ORDER.index(("apply", f"{env}/app"))
        assert AD17_ORDER.index(("apply", f"{env}/app")) < AD17_ORDER.index(("code", env))


def test_story_1_2_shared_and_prod_apply_only_in_their_approval_environments(deploy: dict[str, Any]) -> None:
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


def test_story_1_2_app_stacks_are_optional_until_they_exist(deploy: dict[str, Any]) -> None:
    stages = {stage["stage"]: stage for stage in deploy["stages"]}
    for stack in ("dev_app", "prod_app"):
        (step,) = _azure_cli_steps(stages[f"{stack}_check"])
        assert step["inputs"]["arguments"].endswith("--optional")
    for stack in ("dev_foundation", "prod_foundation", "shared_foundation"):
        (step,) = _azure_cli_steps(stages[f"{stack}_check"])
        assert "--optional" not in step["inputs"]["arguments"]


# --- mutations the checkers must catch ---------------------------------------------------


def test_story_1_2_checker_fails_on_a_stage_order_swap() -> None:
    raw = load(PIPELINES / "deploy.yml")
    by_id = {stage["parameters"]["id"]: stage["parameters"] for stage in raw["stages"]}
    # Reorder to dev/foundation -> dev/app -> Dev migrations -> Dev code.
    by_id["dev_app"]["after"] = "dev_foundation"
    by_id["dev_migrate"]["after"] = "dev_app"
    by_id["dev_code"]["after"] = "dev_migrate"
    problems = order_problems(_compile_raw(raw))
    assert any("is not the AD-17 order" in p for p in problems), problems


def test_story_1_2_checker_fails_on_a_missing_approval_environment(deploy: dict[str, Any]) -> None:
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation")
    stage["jobs"][0]["environment"] = "dev"
    assert any("the approval environment" in p for p in gate_problems(mutated))

    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "shared_foundation")
    job = stage["jobs"][0]
    stage["jobs"] = [{"job": "apply", "steps": steps_of(job)}]  # a plain job: no environment, no approval
    assert any("must be one deployment job" in p for p in gate_problems(mutated))


def test_story_1_2_checker_fails_on_an_apply_without_a_saved_plan(deploy: dict[str, Any]) -> None:
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


def test_story_1_2_checker_fails_when_an_output_step_is_renamed(deploy: dict[str, Any]) -> None:
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "dev_foundation_check")
    (plan_step,) = _azure_cli_steps(stage)
    plan_step["name"] = "tf"  # the old step name: every reader of check.hasWork now dangles
    problems = output_problems(mutated)
    assert any("dev_foundation: dev_foundation_check.outputs['check.check.hasWork']" in p for p in problems), problems
    assert any("variables['check.hasWork']" in p for p in problems), problems
    assert any(p.startswith("dev_migrate_check:") for p in problems), problems


def test_story_1_2_checker_fails_when_a_step_runs_after_an_unfinished_one(deploy: dict[str, Any]) -> None:
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation_check")
    stage["condition"] = "always()"
    assert chain_problems(mutated) == [f"prod_foundation_check: condition must be {chain_condition('dev_code')}"]


def test_story_1_2_checker_fails_on_a_wrong_service_connection(deploy: dict[str, Any]) -> None:
    mutated = copy.deepcopy(deploy)
    stage = next(s for s in mutated["stages"] if s["stage"] == "prod_foundation_check")
    _azure_cli_steps(stage)[0]["inputs"]["azureSubscription"] = "azure-dev"
    assert connection_problems(mutated) == ["prod_foundation_check: uses service connection 'azure-dev', expected 'azure-prod'"]


# --- scripts behind the deploy stages ---------------------------------------------------


def test_story_1_2_no_auto_approve_and_apply_only_from_a_saved_plan() -> None:
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


def test_story_1_2_tag_gate_runs_on_the_plan_before_it_is_handed_to_apply() -> None:
    script = (REPO_ROOT / "ci" / "terraform-plan.sh").read_text(encoding="utf-8")
    plan = script.index("-out=tfplan -detailed-exitcode")
    show = script.index("show -json tfplan")
    gate = script.index("infra/scripts/check_tags.py")
    handoff = script.index('cp "$dir/tfplan"')
    assert plan < show < gate < handoff


def test_story_1_2_operator_steps_never_run_in_a_pipeline() -> None:
    operator_scripts = [p.name for p in (REPO_ROOT / "infra" / "bootstrap").glob("*.sh") if p.name != "lib.sh"]
    assert "ado-setup.sh" in operator_scripts
    # Code lines only: comments may name an operator step to explain an order.
    texts = [
        "\n".join(line for line in p.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
        for p in [*PIPELINES.rglob("*.yml"), *(REPO_ROOT / "ci").glob("*.sh")]
    ]
    for name in operator_scripts:
        assert not any(name in text for text in texts), name


def test_story_1_2_no_github_actions_and_no_secrets_in_yaml() -> None:
    assert not (REPO_ROOT / ".github" / "workflows").exists()
    guid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    for path in PIPELINES.rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert not guid.search(text), f"{path}: ids come from the service connection, not YAML"
        # Only runtime references like $(System.AccessToken) may follow a secret-like key.
        assert not re.search(r"(?i)(password|secret|pat|token)\s*:\s*(?!\$\()\S", text), path
        assert "variables:" not in text, f"{path}: no pipeline variables (nothing to store)"


# --- PR build and weekly scan ---------------------------------------------------------------


def _check_subcommands(pipeline: dict[str, Any]) -> dict[str, str]:
    found = {}
    for job in pipeline["jobs"]:
        for step in steps_of(job):
            match = re.fullmatch(r"ci/checks\.sh (\w+)", str(step.get("bash", "")))
            if match:
                found[job["job"]] = match.group(1)
    return found


def test_story_1_2_pr_build_runs_every_check_in_parallel() -> None:
    pr = compile_pipeline("pr.yml")
    assert pr["trigger"] == "none"
    assert pr["pr"] == {"branches": {"include": ["main"]}}
    subcommands = _check_subcommands(pr)
    assert sorted(subcommands.values()) == ["audit", "lint", "secrets", "terraform", "test"]
    assert all("dependsOn" not in job for job in pr["jobs"])  # parallel
    secrets = next(job for job in pr["jobs"] if job["job"] == "secrets")
    assert {"checkout": "self", "fetchDepth": 0} in secrets["steps"]
    test = next(job for job in pr["jobs"] if job["job"] == "test")
    tasks = {step.get("task") for step in test["steps"]}
    assert {"PublishTestResults@2", "PublishCodeCoverageResults@2"} <= tasks
    # The matrix tests in ci/tests need these; under TF_BUILD they fail instead of skipping.
    assert {"bash": "ci/install-tools.sh uv terraform gitleaks", "displayName": "Install uv, terraform, gitleaks"} in test[
        "steps"
    ]


def test_story_1_2_weekly_scan_audits_main_every_week() -> None:
    weekly = compile_pipeline("weekly-scan.yml")
    assert weekly["trigger"] == "none" and weekly["pr"] == "none"
    (schedule,) = weekly["schedules"]
    assert schedule["branches"] == {"include": ["main"]}
    assert schedule["always"] is True
    minute, hour, dom, month, dow = schedule["cron"].split()
    assert dom == "*" and month == "*" and dow not in ("*",)  # weekly
    assert list(_check_subcommands(weekly).values()) == ["audit"]


# --- pinned versions and thresholds ------------------------------------------------------------


def test_story_1_2_tool_versions_are_pinned_and_agree() -> None:
    setup = load(PIPELINES / "templates" / "setup-tools.yml")
    text = (PIPELINES / "templates" / "setup-tools.yml").read_text(encoding="utf-8")
    assert f"versionSpec: '{_read_lib_value('PYTHON_VERSION')}'" in text
    assert f"versionSpec: '{_read_lib_value('NODE_VERSION')}.x'" in text
    assert setup["parameters"][0]["name"] == "tools"
    terraform = _read_lib_value("TERRAFORM_VERSION")
    assert terraform == "1.16.4"
    for versions in (REPO_ROOT / "infra").glob("*/*/versions.tf"):
        if "modules" in versions.parts:
            continue
        assert f'required_version = "{terraform}"' in versions.read_text(encoding="utf-8"), versions
    for name in ("TERRAFORM_SHA256_LINUX_AMD64", "GITLEAKS_SHA256_LINUX_X64", "UV_SHA256_LINUX_X64"):
        assert re.fullmatch(r"[0-9a-f]{64}", _read_lib_value(name)), name


def test_story_1_2_coverage_floors_are_80_backend_and_60_web() -> None:
    assert _read_lib_value("BACKEND_COVERAGE_MIN") == "80"
    assert _read_lib_value("WEB_COVERAGE_MIN") == "60"
    pyproject = (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^fail_under = 80$", pyproject, re.M)


def test_story_1_2_every_template_reference_resolves() -> None:
    for name in ("pr.yml", "deploy.yml", "weekly-scan.yml"):
        compiled = compile_pipeline(name)
        assert "${{" not in str(compiled), name
    for path in (PIPELINES / "templates").glob("*.yml"):
        assert isinstance(load(path), dict), path
    assert Path(PIPELINES / "templates" / "terraform-stack.yml").exists()
