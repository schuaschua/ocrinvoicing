"""Story 1.2: behaviour of the scripts behind the deploy stages, run against a fake
`terraform` (ci/tests/fake-bin) and an `az` that fails if called. Nothing reaches Azure.

Covers the I/O matrix row "Untagged resource in plan".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

INSTALL_BIN = Path(__file__).resolve().parent / "fake-bin-install"

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / "ci"
FAKE_BIN = Path(__file__).resolve().parent / "fake-bin"
FIXTURES = REPO_ROOT / "infra" / "scripts" / "tests" / "fixtures"


@pytest.fixture
def work_dir() -> Iterator[Path]:
    """Scratch dir under the gitignored .work/ folder (never /tmp)."""
    path = REPO_ROOT / ".work" / "pytest-ci" / uuid.uuid4().hex
    (path / "infra" / "dev" / "foundation").mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _fresh(work_dir: Path, name: str) -> Path:
    """A sub-folder laid out like the work_dir fixture, so each merged part keeps its own logs."""
    path = work_dir / name
    (path / "infra" / "dev" / "foundation").mkdir(parents=True)
    return path


def _run(script: str, *args: str, work_dir: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARM_", "TF_", "FAKE_"))}
    for key in ("idToken", "servicePrincipalId", "tenantId"):
        env.pop(key, None)
    env.update(
        {
            "PATH": f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}",
            "ARM_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
            "ARM_TENANT_ID": "11111111-1111-1111-1111-111111111111",
            "CI_INFRA_DIR": str(work_dir / "infra"),
            "FAKE_TF_LOG": str(work_dir / "terraform-calls.jsonl"),
        }
    )
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(CI / script), *args], env=env, capture_output=True, text=True, check=False, timeout=60
    )


def _terraform_calls(work_dir: Path) -> list[list[str]]:
    log = work_dir / "terraform-calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


# --- terraform-plan.sh -----------------------------------------------------------------


def _terraform_plan_tag_gate(work_dir: Path) -> None:
    """terraform-plan.sh. Covers: a plan with changes and tags hands the saved plan to apply
    (and deletes the plan JSON); an untagged resource stops the stack before apply; the
    Jenkinsfile's CI_OUTPUT_FILE holds exactly hasWork=true, or hasWork=false for --optional
    on a missing stack."""
    # A plan with changes and tags hands the saved plan to apply.
    out = work_dir / "plan-out"
    output_file = work_dir / "outputs" / "plan.env"
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(out), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="2", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_pass.json"),
        CI_OUTPUT_FILE=str(output_file),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "output: hasWork=true" in result.stdout
    assert output_file.read_text() == "hasWork=true\n"
    assert (out / "tfplan").is_file()
    plan_call = next(call for call in _terraform_calls(work_dir) if "plan" in call)
    assert "-out=tfplan" in plan_call and "-detailed-exitcode" in plan_call
    assert not (REPO_ROOT / ".work" / "ci" / "dev-foundation.plan.json").exists(), "plan JSON must be deleted"

    # An untagged resource stops the stack before apply.
    out = work_dir / "plan-out-untagged"
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(out), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="2", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_missing.json"),
    )
    assert result.returncode == 1
    assert "tag gate failed for infra/dev/foundation" in result.stderr
    assert "MISSING TAGS" in result.stdout
    assert "hasWork=true" not in result.stdout
    assert not (out / "tfplan").exists()

    # --optional on a missing stack: skipped, hasWork=false, no terraform call.
    output_file = work_dir / "outputs" / "optional.env"
    calls_before = len(_terraform_calls(work_dir))
    result = _run(
        "terraform-plan.sh", "dev/app", str(work_dir / "plan-out-app"), "--optional", work_dir=work_dir,
        CI_OUTPUT_FILE=str(output_file),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output_file.read_text() == "hasWork=false\n"
    assert len(_terraform_calls(work_dir)) == calls_before


def _lib_probe(work_dir: Path, body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    probe = work_dir / "probe.sh"
    probe.write_text(f'source "$1/ci/lib.sh"; {body}')
    return subprocess.run(
        ["bash", str(probe), str(REPO_ROOT)], env={"PATH": os.environ["PATH"], **env},
        capture_output=True, text=True, check=False,
    )


STALE_SIGN_IN = {
    # Leftovers that must never win over the managed identity (no OIDC, CLI or secret).
    "ARM_USE_OIDC": "true",
    "ARM_USE_CLI": "true",
    "ARM_OIDC_TOKEN": "static-id-token",
    "ARM_OIDC_REQUEST_TOKEN": "request-token",
    "ARM_OIDC_REQUEST_URL": "https://oidc.example.test/request",
    "ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID": "connection-id",
    "ARM_CLIENT_SECRET": "client-secret",
}
SIGN_IN_VARIABLES = (
    "ARM_USE_MSI ARM_CLIENT_ID ARM_SUBSCRIPTION_ID ARM_TENANT_ID "
    "ARM_USE_OIDC ARM_USE_CLI ARM_OIDC_TOKEN ARM_OIDC_REQUEST_TOKEN ARM_OIDC_REQUEST_URL "
    "ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID ARM_CLIENT_SECRET"
)


def _terraform_signs_in_only_as_the_stack_owners_managed_identity(work_dir: Path) -> None:
    """ci/lib.sh export_arm_context on the CI VM (I/O matrix "Terraform sign-in"). Covers: with
    CI_MSI_CLIENT_ID, Terraform uses the managed identity of that client id and no OIDC, CLI
    or secret variable is left; in CI without a client id the stage fails, naming it."""
    probe = f'export_arm_context; for v in {SIGN_IN_VARIABLES}; do printf "%s=%s\\n" "$v" "${{!v:-unset}}"; done'
    result = _lib_probe(
        work_dir, probe,
        {"TF_BUILD": "true", "CI_MSI_CLIENT_ID": "client-of-id-22", "ARM_SUBSCRIPTION_ID": "s", "ARM_TENANT_ID": "t",
         **STALE_SIGN_IN},
    )
    assert result.returncode == 0, result.stderr
    assert dict(line.split("=", 1) for line in result.stdout.splitlines()) == {
        "ARM_USE_MSI": "true",
        "ARM_CLIENT_ID": "client-of-id-22",
        "ARM_SUBSCRIPTION_ID": "s",
        "ARM_TENANT_ID": "t",
        **{name: "unset" for name in STALE_SIGN_IN},
    }

    # In CI without a client id: the stage fails, naming it, before Terraform runs.
    result = _lib_probe(work_dir, probe, {"TF_BUILD": "true", "ARM_SUBSCRIPTION_ID": "s", "ARM_TENANT_ID": "t"})
    assert result.returncode == 1
    assert "CI_MSI_CLIENT_ID is not set" in result.stderr
    assert "ARM_USE_MSI" not in result.stdout


# --- ado-status.sh -----------------------------------------------------------------------

ADO_BIN = Path(__file__).resolve().parent / "fake-bin-ado"
ADO_TOKEN = "fake-ado-token-never-in-argv"
BUILT = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"


def _ado_status(work_dir: Path, state: str, **env_extra: str) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    log = work_dir / f"curl-{uuid.uuid4().hex}.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ADO_", "FAKE_"))}
    env.update({
        "PATH": f"{ADO_BIN}{os.pathsep}{env.get('PATH', '')}",
        "ADO_ORG": "test-org", "ADO_PROJECT": "test-project", "ADO_PAT": ADO_TOKEN,
        "BRANCH_NAME": "feature/x", "GIT_COMMIT": BUILT, "BUILD_URL": "http://127.0.0.1:8080/job/x/1/",
        "FAKE_CURL_LOG": str(log),
    })
    env.update(env_extra)
    result = subprocess.run(
        ["bash", str(CI / "ado-status.sh"), state], env=env, capture_output=True, text=True, check=False, timeout=60
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def _ado_status_posts_on_the_built_iteration(work_dir: Path) -> None:
    """ci/ado-status.sh against a fake curl (I/O matrix "PR build"). Covers: the pull request
    is looked up from the branch into main; the status goes on the iteration of GIT_COMMIT with
    state, jenkins/checks and the iteration id; the token reaches curl only on stdin; no pull
    request, or no iteration for the commit, posts nothing and succeeds; a bad state is refused."""
    iterations = json.dumps([
        {"id": 1, "sourceRefCommit": {"commitId": "0" * 40}},
        {"id": 2, "sourceRefCommit": {"commitId": BUILT}},
        {"id": 3, "sourceRefCommit": {"commitId": "f" * 40}},
    ])
    result, calls = _ado_status(work_dir, "succeeded", FAKE_ADO_PRS='[{"pullRequestId": 42}]', FAKE_ADO_ITERATIONS=iterations)
    assert result.returncode == 0, result.stdout + result.stderr
    query, iteration_call, post = calls
    api = "https://dev.azure.com/test-org/test-project/_apis/git/repositories/test-project"
    assert query["argv"][-1].startswith(f"{api}/pullrequests?")
    assert "searchCriteria.sourceRefName=refs%2Fheads%2Ffeature%2Fx" in query["argv"][-1]
    assert "searchCriteria.targetRefName=refs%2Fheads%2Fmain" in query["argv"][-1]
    assert "searchCriteria.status=active" in query["argv"][-1]
    assert iteration_call["argv"][-1].startswith(f"{api}/pullRequests/42/iterations?")
    assert post["argv"][-1].startswith(f"{api}/pullRequests/42/statuses?")
    assert post["argv"][post["argv"].index("-X") + 1] == "POST"
    body = json.loads(post["argv"][post["argv"].index("--data") + 1])
    assert body["state"] == "succeeded" and body["iterationId"] == 2  # the built commit's iteration
    assert body["context"] == {"genre": "jenkins", "name": "checks"}
    # The token only on stdin, never in argv or output.
    for call in calls:
        assert call["stdin"] == f'user = ":{ADO_TOKEN}"\n'
        assert ADO_TOKEN not in json.dumps(call["argv"])
    assert ADO_TOKEN not in result.stdout + result.stderr

    # No pull request: nothing posted, success.
    result, calls = _ado_status(work_dir, "failed")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1 and "no active pull request" in result.stdout

    # No iteration for the built commit (a newer push): nothing posted, success.
    result, calls = _ado_status(
        work_dir, "failed", FAKE_ADO_PRS='[{"pullRequestId": 42}]',
        FAKE_ADO_ITERATIONS=json.dumps([{"id": 1, "sourceRefCommit": {"commitId": "f" * 40}}]),
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2 and not any("/statuses?" in call["argv"][-1] for call in calls)

    # A bad state is refused before any call.
    result, calls = _ado_status(work_dir, "approved")
    assert result.returncode == 1 and "state must be" in result.stderr
    assert calls == []


# --- terraform-apply.sh ----------------------------------------------------------------


def _terraform_apply_only_from_the_saved_plan(work_dir: Path) -> None:
    """terraform-apply.sh. Covers: an apply without a saved plan is refused (no terraform
    call); an apply uses only the saved plan, never auto-approve."""
    # Without a saved plan: refused.
    result = _run("terraform-apply.sh", "dev/foundation", str(work_dir / "missing"), work_dir=work_dir)
    assert result.returncode == 1
    assert "applied only from its saved plan" in result.stderr
    assert _terraform_calls(work_dir) == []

    # With the saved plan: applies only it.
    plan = work_dir / "tfplan"
    plan.write_text("saved plan\n")
    result = _run("terraform-apply.sh", "dev/foundation", str(plan), work_dir=work_dir)
    assert result.returncode == 0, result.stderr
    (apply_call,) = [call for call in _terraform_calls(work_dir) if "apply" in call]
    assert apply_call[-1] == "tfplan"
    assert not any("auto-approve" in arg for arg in apply_call)


# --- migrate.sh -------------------------------------------------------------------------


MIGRATE_ENVIRONMENTS = [
    ("dev", "babaloo-sea-lng-id-22", "babaloo-sea-lng-id-03", "babaloo-sea-lng-id-02", "babaloo-sea-lng-grp-01",
     "babaloo-sea-lng-id-04"),
    ("prod", "babaloo-sea-lng-id-23", "babaloo-sea-lng-id-13", "babaloo-sea-lng-id-12", "babaloo-sea-lng-grp-11",
     "babaloo-sea-lng-id-14"),
]


def _migrations_run_as_the_env_deploy_identity_with_an_entra_token(work_dir: Path) -> None:
    """migrate.sh, for dev and then prod: --check finds work; the run uses the env deploy
    identity's login with an Entra token over TLS, grants to the env's app logins (Story 2.1),
    asks az for one token and opens no firewall. Story 1.6: it also grants to the env's
    loaders group (Dj's load-script login), named by the naming helpers, and Story 3.1 to
    the env's accounts-sim login; a leftover
    DJ_USER_UPN is ignored (Dj, 2026-09-29: guest UPN over 63 characters). --check with no
    migrations writes exactly hasWork=false to the Jenkinsfile's CI_OUTPUT_FILE, and with
    migrations exactly hasWork=true."""
    output_file = work_dir / "outputs" / "migrate-none.env"
    check = _run("migrate.sh", "--check", "dev", work_dir=work_dir,
                 CI_MIGRATIONS_DIR=str(work_dir / "no-migrations"), CI_OUTPUT_FILE=str(output_file))
    assert check.returncode == 0, check.stderr
    assert output_file.read_text() == "hasWork=false\n"
    for env, login, pipeline_role, staff_api_role, loaders_group, accounts_sim_role in MIGRATE_ENVIRONMENTS:
        migrations = work_dir / f"migrations-{env}"
        migrations.mkdir()
        (migrations / "env.py").write_text("# fixture\n")
        output_file = work_dir / "outputs" / f"migrate-{env}.env"
        check = _run("migrate.sh", "--check", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations),
                     CI_OUTPUT_FILE=str(output_file))
        assert "output: hasWork=true" in check.stdout, (env, check.stderr)
        assert output_file.read_text() == "hasWork=true\n"

        az_log, uv_log = work_dir / f"az-{env}.log", work_dir / f"uv-{env}.jsonl"
        result = _run(
            "migrate.sh", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations),
            FAKE_AZ_TOKEN="entra-token-for-postgres", FAKE_AZ_LOG=str(az_log),
            FAKE_UV_LOG=str(uv_log), DJ_USER_UPN="$(DJ_USER_UPN)",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        (call,) = [json.loads(line) for line in uv_log.read_text().splitlines()]
        # Story 2.1: the roles the migrations grant to are the environment's app logins (AD-11);
        # Story 1.6: and the env's loaders group, the supplier load script's login.
        assert call["args"] == [
            "run", "--directory", str(REPO_ROOT / "backend"), "--locked", "--no-dev", "alembic",
            "-x", f"pipeline_role={pipeline_role}", "-x", f"staff_api_role={staff_api_role}",
            "-x", f"dj_role={loaders_group}", "-x", f"accounts_sim_role={accounts_sim_role}",
            "upgrade", "head",
        ]
        assert call["env"] == {
            "PGHOST": "babaloo-sea-lng-psql-21.postgres.database.azure.com",
            "PGPORT": "5432",
            "PGUSER": login,
            "PGDATABASE": f"invoicing_{env}",
            "PGSSLMODE": "require",
            "PGPASSWORD": "entra-token-for-postgres",
        }
        az_calls = az_log.read_text().splitlines()
        assert az_calls == ["account get-access-token --resource-type oss-rdbms --query accessToken -o tsv"]
        assert "firewall" not in result.stdout + result.stderr


# --- code-deploy.sh (Story 1.3) --------------------------------------------------------

APPS = ["supplier-api", "staff-api", "pipeline", "accounts-sim"]
PACKAGE_SRC = REPO_ROOT / "backend" / "src" / "invoicing"
VERSION = re.search(r'^__version__ = "([^"]+)"', (PACKAGE_SRC / "__init__.py").read_text(), re.M).group(1)  # type: ignore[union-attr]


def _backend_repo(work_dir: Path) -> Path:
    """A scratch git repo holding a copy of the back-end package, all of it tracked,
    plus an untracked module and a bytecode cache that must never be packaged."""
    backend = work_dir / "backend"
    shutil.copytree(PACKAGE_SRC, backend / "src" / "invoicing", ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "init", "-q", str(backend)], check=True)
    subprocess.run(["git", "-C", str(backend), "add", "src"], check=True)
    (backend / "src" / "invoicing" / "local_scratch.py").write_text("SECRET_NOTE = 'never shipped'\n")
    cache = backend / "src" / "invoicing" / "__pycache__"
    cache.mkdir()
    (cache / "stale.cpython-313.pyc").write_bytes(b"\0")
    return backend


def _deploy(work_dir: Path, *args: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    """code-deploy.sh against scratch infra/web/backend/build folders and fake uv, az
    and curl."""
    for env in ("dev", "prod"):
        (work_dir / "infra" / env / "app").mkdir(parents=True, exist_ok=True)
    if not (work_dir / "backend").exists():
        _backend_repo(work_dir)
    env = {
        "CI_WEB_DIR": str(work_dir / "web"),
        "CI_BACKEND_DIR": str(work_dir / "backend"),
        "CI_DEPLOY_BUILD_DIR": str(work_dir / "build"),
        "CI_HEALTH_ATTEMPTS": "3",
        "CI_HEALTH_WAIT": "0",
        "FAKE_UV_LOG": str(work_dir / "uv.jsonl"),
        "FAKE_AZ_LOG": str(work_dir / "az.log"),
        "FAKE_AZ_DEPLOY": "1",
        "FAKE_CURL_LOG": str(work_dir / "curl.log"),
        "FAKE_CURL_VERSION": VERSION,
        # A fresh "last deployed" record per run, so no run skips an app; the skip check
        # passes its own.
        "CI_DEPLOY_STATE_DIR": tempfile.mkdtemp(prefix="deploy-state-", dir=work_dir),
    }
    env.update(env_extra)
    return _run("code-deploy.sh", *args, work_dir=work_dir, **env)


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def test_story_1_3_code_deploy(work_dir: Path) -> None:
    """code-deploy.sh. Covers: only git-tracked package files are shipped (no untracked module,
    no bytecode); the health check retries until the app answers; an unhealthy app fails the
    deploy; an app unchanged since its last healthy deploy is skipped, a changed one and
    CI_DEPLOY_ALL=1 republish; a failed publish or health check forgets every record. Each
    run gets its own curl log."""
    # Only git-tracked package files are shipped.
    result = _deploy(work_dir, "--build-only", "dev")
    assert result.returncode == 0, result.stdout + result.stderr
    for app in APPS:
        names = _zip_names(work_dir / "build" / f"{app}.zip")
        assert "invoicing/local_scratch.py" not in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)

    # The health check retries until the app answers.
    curl_log = work_dir / "curl-retry.log"
    result = _deploy(work_dir, "dev", FAKE_CURL_FAILURES="2", FAKE_CURL_LOG=str(curl_log))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "supplier-api not healthy yet (attempt 2/3, HTTP 503)" in result.stdout
    assert len(curl_log.read_text().splitlines()) == 4

    # An unhealthy app fails the deploy.
    result = _deploy(work_dir, "dev", FAKE_CURL_FAILURES="99", FAKE_CURL_LOG=str(work_dir / "curl-unhealthy.log"))
    assert result.returncode != 0
    assert "attempt 3/3, HTTP 503" in result.stdout
    assert (
        f"supplier-api did not report healthy version {VERSION}; published: supplier-api staff-api pipeline accounts-sim"
        in result.stderr
    )

    # The four apps publish side by side; an unchanged app is not published again once a
    # deploy of it has passed the health checks, and a changed one is.
    state = str(work_dir / "state-skip")
    az_log = work_dir / "az.log"
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, FAKE_CURL_LOG=str(work_dir / "curl-skip-1.log"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "published: supplier-api staff-api pipeline accounts-sim" in result.stdout
    assert sorted(Path(state).iterdir()) == sorted(Path(state) / f"{app}.sha256" for app in APPS)
    deploys = az_log.read_text().count("config-zip")
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, FAKE_CURL_LOG=str(work_dir / "curl-skip-2.log"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert az_log.read_text().count("config-zip") == deploys
    assert all(f"{app} unchanged since its last deploy to dev: not published" in result.stdout for app in APPS)
    assert "code deploy to dev done; published: none" in result.stdout
    # Every package holds the whole back-end package, so a back-end change republishes all
    # four (only the web builds and the pipeline's thresholds differ between packages).
    (work_dir / "backend" / "src" / "invoicing" / "apps" / "pipeline" / "host.json").write_text('{"version": "2.0"}\n')
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, FAKE_CURL_LOG=str(work_dir / "curl-skip-3.log"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "code deploy to dev done; published: supplier-api staff-api pipeline accounts-sim" in result.stdout

    # CI_DEPLOY_ALL=1 (dev/app changed) republishes an unchanged app.
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, CI_DEPLOY_ALL="1", FAKE_CURL_LOG=str(work_dir / "curl-skip-4.log"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "code deploy to dev done; published: supplier-api staff-api pipeline accounts-sim" in result.stdout

    # A failed publish (reported with the ones that did publish) or a failed health check
    # forgets every record, so the next run republishes everything.
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, CI_DEPLOY_ALL="1", FAKE_AZ_FAIL_NAME="babaloo-sea-lng-func-03", FAKE_CURL_LOG=str(work_dir / "curl-skip-5.log"))
    assert result.returncode != 0
    assert "publishing pipeline failed; already published: supplier-api staff-api accounts-sim" in result.stderr
    assert not Path(state).exists()
    result = _deploy(work_dir, "dev", CI_DEPLOY_STATE_DIR=state, FAKE_CURL_FAILURES="99", FAKE_CURL_LOG=str(work_dir / "curl-skip-6.log"))
    assert result.returncode != 0
    assert not Path(state).exists()


# --- tag-sweep.sh -----------------------------------------------------------------------

SWEEP_RG = "/subscriptions/s/resourceGroups/babaloo-sea-lng-rg-01/providers"
SWEEP_GROUP_TAGS = {"application": "ocrinvoicing", "environment": "dev", "owner": "dj"}


def _tag_sweep(work_dir: Path) -> None:
    """tag-sweep.sh (I/O matrix "Untagged Azure-created resource", "Fully tagged resource
    group"). Covers: each resource gets only the group tag keys it lacks, merged, never an
    existing value overwritten (keys compared case-insensitively, as Azure does); a fully tagged group gets no update call; a foundation output
    that is not the owner's own group is refused before any az call."""
    smart = f"{SWEEP_RG}/microsoft.insights/actionGroups/Application Insights Smart Detection"
    anomalies = f"{SWEEP_RG}/microsoft.alertsManagement/smartDetectorAlertRules/Failure Anomalies - appi"
    tagged = f"{SWEEP_RG}/Microsoft.Storage/storageAccounts/babaloosealngst01"
    sweep = {"group": SWEEP_GROUP_TAGS, "resources": [
        {"id": smart, "tags": None},
        {"id": anomalies, "tags": {"Environment": "kept-as-is"}},
        {"id": tagged, "tags": SWEEP_GROUP_TAGS},
    ]}
    az_log = work_dir / "az-sweep.log"
    result = _run("tag-sweep.sh", "dev", work_dir=work_dir, FAKE_TF_OUTPUT="babaloo-sea-lng-rg-01",
                  FAKE_AZ_SWEEP=json.dumps(sweep), FAKE_AZ_LOG=str(az_log))
    assert result.returncode == 0, result.stdout + result.stderr
    assert ["-chdir=" + str(work_dir / "infra" / "dev" / "foundation"), "output", "-raw", "resource_group_name"] in _terraform_calls(work_dir)
    updates = [line for line in az_log.read_text().splitlines() if line.startswith("tag update")]
    assert updates == [
        f"tag update --resource-id {smart} --operation merge --tags application=ocrinvoicing environment=dev owner=dj --output none",
        f"tag update --resource-id {anomalies} --operation merge --tags application=ocrinvoicing owner=dj --output none",
    ]
    assert "2 resource(s) given missing tags" in result.stdout

    # A fully tagged group: no update call.
    az_log = work_dir / "az-sweep-tagged.log"
    sweep["resources"] = [{"id": tagged, "tags": SWEEP_GROUP_TAGS}]
    result = _run("tag-sweep.sh", "dev", work_dir=work_dir, FAKE_TF_OUTPUT="babaloo-sea-lng-rg-01",
                  FAKE_AZ_SWEEP=json.dumps(sweep), FAKE_AZ_LOG=str(az_log))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [line for line in az_log.read_text().splitlines() if line.startswith("tag update")]

    # Never another group (e.g. the state account's): refused before any az call.
    az_log = work_dir / "az-sweep-other.log"
    result = _run("tag-sweep.sh", "dev", work_dir=work_dir, FAKE_TF_OUTPUT="rg-tfstate-sea",
                  FAKE_AZ_SWEEP=json.dumps(sweep), FAKE_AZ_LOG=str(az_log))
    assert result.returncode == 1 and "expected 'babaloo-sea-lng-rg-01'" in result.stderr
    assert not az_log.exists()


# --- deploy-state.sh ----------------------------------------------------------------------


def _deploy_state(work_dir: Path) -> None:
    """deploy-state.sh (I/O matrix "main ahead of dev"). Covers: verify fails, naming both
    commits, when nothing is recorded or the record differs from HEAD; record writes HEAD and
    verify then prints it."""
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    state = work_dir / "deploy-state"
    seam = {"CI_DEPLOY_COMMIT_DIR": str(state)}

    result = _run("deploy-state.sh", "verify", work_dir=work_dir, **seam)
    assert result.returncode == 1 and result.stdout == ""
    assert f"main is at {head}, but the last commit the dev chain deployed is 'none recorded'" in result.stderr

    state.mkdir()
    (state / "dev-commit").write_text("0" * 40 + "\n")
    result = _run("deploy-state.sh", "verify", work_dir=work_dir, **seam)
    assert result.returncode == 1 and result.stdout == ""
    assert f"main is at {head}, but the last commit the dev chain deployed is '{'0' * 40}'" in result.stderr

    result = _run("deploy-state.sh", "record", work_dir=work_dir, **seam)
    assert result.returncode == 0, result.stderr
    assert (state / "dev-commit").read_text() == head + "\n" and not (state / "dev-commit.new").exists()
    result = _run("deploy-state.sh", "verify", work_dir=work_dir, **seam)
    assert result.returncode == 0, result.stderr
    assert result.stdout == head + "\n"


# --- install-tools.sh --------------------------------------------------------------------


def _install(work_dir: Path, *tools: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "TF_", "CI_"))}
    env.update(
        {
            "PATH": f"{INSTALL_BIN}{os.pathsep}{env.get('PATH', '')}",
            "CI_TOOLS_DIR": str(work_dir / "bin"),
            "CI_TEMP_DIR": str(work_dir / "ci-temp" / "not-created-yet"),
            "FAKE_CURL_LOG": str(work_dir / "curl.log"),
        }
    )
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(CI / "install-tools.sh"), *tools], env=env, capture_output=True, text=True, check=False, timeout=60
    )


def _install_tools_rejects_a_checksum_mismatch(work_dir: Path) -> None:
    result = _install(work_dir, "terraform", FAKE_CURL_CONTENT="TAMPERED")
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not (work_dir / "bin" / "terraform").exists()


def test_story_1_2_ci_scripts(work_dir: Path) -> None:
    """Story 1.2 deploy-stage scripts, merged under the test cap: terraform-plan.sh's tag gate,
    Terraform sign-in, ado-status.sh, terraform-apply.sh, migrate.sh, tag-sweep.sh, deploy-state.sh and install-tools.sh. Each
    part runs in its own fresh folder, as it did as a separate test."""
    _terraform_plan_tag_gate(_fresh(work_dir, "plan"))
    _terraform_signs_in_only_as_the_stack_owners_managed_identity(_fresh(work_dir, "sign-in"))
    _ado_status_posts_on_the_built_iteration(_fresh(work_dir, "ado-status"))
    _terraform_apply_only_from_the_saved_plan(_fresh(work_dir, "apply"))
    _migrations_run_as_the_env_deploy_identity_with_an_entra_token(_fresh(work_dir, "migrate"))
    _tag_sweep(_fresh(work_dir, "tag-sweep"))
    _deploy_state(_fresh(work_dir, "deploy-state"))
    _install_tools_rejects_a_checksum_mismatch(_fresh(work_dir, "install"))
