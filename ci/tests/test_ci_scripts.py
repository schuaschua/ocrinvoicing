"""Story 1.2: behaviour of the scripts behind the deploy stages, run against a fake
`terraform` (ci/tests/fake-bin) and an `az` that fails if called. Nothing reaches Azure.

Covers the I/O matrix rows "No infra change", "Untagged resource in plan" and
"No migrations yet".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def test_story_1_2_plan_with_changes_and_tags_hands_the_saved_plan_to_apply(work_dir: Path) -> None:
    out = work_dir / "plan-out"
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(out), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="2", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_pass.json"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "output: hasWork=true" in result.stdout
    assert (out / "tfplan").is_file()
    plan_call = next(call for call in _terraform_calls(work_dir) if "plan" in call)
    assert "-out=tfplan" in plan_call and "-detailed-exitcode" in plan_call
    assert not (REPO_ROOT / ".work" / "ci" / "dev-foundation.plan.json").exists(), "plan JSON must be deleted"


def test_story_1_2_no_infra_change_skips_apply(work_dir: Path) -> None:
    out = work_dir / "plan-out"
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(out), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="0", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_pass.json"),
    )
    assert result.returncode == 0, result.stderr
    assert "output: hasWork=false" in result.stdout
    assert not (out / "tfplan").exists()


def test_story_1_2_untagged_resource_stops_the_stack_before_apply(work_dir: Path) -> None:
    out = work_dir / "plan-out"
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(out), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="2", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_missing.json"),
    )
    assert result.returncode == 1
    assert "tag gate failed for infra/dev/foundation" in result.stderr
    assert "MISSING TAGS" in result.stdout
    assert "hasWork=true" not in result.stdout
    assert not (out / "tfplan").exists()


def test_story_1_2_failed_plan_fails_the_stage(work_dir: Path) -> None:
    result = _run(
        "terraform-plan.sh", "dev/foundation", str(work_dir / "out"), work_dir=work_dir,
        FAKE_TF_PLAN_EXIT="1", FAKE_TF_PLAN_JSON=str(FIXTURES / "plan_pass.json"),
    )
    assert result.returncode == 1
    assert "terraform plan failed" in result.stderr


def test_story_1_2_missing_app_stack_is_skipped_only_when_optional(work_dir: Path) -> None:
    result = _run("terraform-plan.sh", "dev/app", str(work_dir / "out"), "--optional", work_dir=work_dir)
    assert result.returncode == 0, result.stderr
    assert "skipped: infra/dev/app does not exist yet" in result.stdout
    assert "output: hasWork=false" in result.stdout
    assert _terraform_calls(work_dir) == []

    result = _run("terraform-plan.sh", "dev/app", str(work_dir / "out"), work_dir=work_dir)
    assert result.returncode == 1


def _lib_probe(work_dir: Path, body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    probe = work_dir / "probe.sh"
    probe.write_text(f'source "$1/ci/lib.sh"; {body}')
    return subprocess.run(
        ["bash", str(probe), str(REPO_ROOT)], env={"PATH": os.environ["PATH"], **env},
        capture_output=True, text=True, check=False,
    )


ADO_TASK_ENV = {
    "TF_BUILD": "True",
    "ARM_SUBSCRIPTION_ID": "s",
    "AZURESUBSCRIPTION_SERVICE_CONNECTION_ID": "connection-id",
    "AZURESUBSCRIPTION_CLIENT_ID": "client-id",
    "AZURESUBSCRIPTION_TENANT_ID": "tenant-id",
    "SYSTEM_ACCESSTOKEN": "system-access-token",
    "SYSTEM_OIDCREQUESTURI": "https://oidc.example.test/request",
    "idToken": "static-id-token",
}


def test_story_1_2_terraform_uses_the_refreshing_ado_oidc_of_the_service_connection(work_dir: Path) -> None:
    result = _lib_probe(
        work_dir,
        'export_arm_context; printf "%s\\n" "$ARM_USE_OIDC" "$ARM_USE_CLI" "$ARM_CLIENT_ID" "$ARM_TENANT_ID" '
        '"$ARM_ADO_PIPELINE_SERVICE_CONNECTION_ID" "$ARM_OIDC_REQUEST_TOKEN" "$ARM_OIDC_REQUEST_URL" '
        '"${ARM_OIDC_TOKEN:-unset}"',
        ADO_TASK_ENV,
    )
    assert result.stdout.split("\n")[:8] == [
        "true", "false", "client-id", "tenant-id", "connection-id", "system-access-token",
        "https://oidc.example.test/request", "unset",  # no static token that could expire mid-apply
    ], result.stderr


@pytest.mark.parametrize("missing", ["AZURESUBSCRIPTION_SERVICE_CONNECTION_ID", "SYSTEM_ACCESSTOKEN", "SYSTEM_OIDCREQUESTURI"])
def test_story_1_2_pipeline_run_without_the_oidc_inputs_stops(missing: str, work_dir: Path) -> None:
    env = {k: v for k, v in ADO_TASK_ENV.items() if k != missing}
    result = _lib_probe(work_dir, "export_arm_context", env)
    assert result.returncode == 1
    assert f"{missing} is not set" in result.stderr


def test_story_1_2_set_output_writes_the_ado_logging_command(work_dir: Path) -> None:
    result = _lib_probe(work_dir, "set_output hasWork true", {"TF_BUILD": "True"})
    assert result.stdout == "##vso[task.setvariable variable=hasWork;isOutput=true]true\n"
    local = _lib_probe(work_dir, "set_output hasWork true", {})
    assert local.stdout == "output: hasWork=true\n"


# --- terraform-apply.sh ----------------------------------------------------------------


def test_story_1_2_apply_uses_only_the_saved_plan(work_dir: Path) -> None:
    plan = work_dir / "tfplan"
    plan.write_text("saved plan\n")
    result = _run("terraform-apply.sh", "dev/foundation", str(plan), work_dir=work_dir)
    assert result.returncode == 0, result.stderr
    (apply_call,) = [call for call in _terraform_calls(work_dir) if "apply" in call]
    assert apply_call[-1] == "tfplan"
    assert not any("auto-approve" in arg for arg in apply_call)


def test_story_1_2_apply_without_a_saved_plan_is_refused(work_dir: Path) -> None:
    result = _run("terraform-apply.sh", "dev/foundation", str(work_dir / "missing"), work_dir=work_dir)
    assert result.returncode == 1
    assert "applied only from its saved plan" in result.stderr
    assert _terraform_calls(work_dir) == []


# --- migrate.sh and code-deploy.sh -----------------------------------------------------


@pytest.mark.parametrize("args", [["dev"], ["--check", "prod"]])
def test_story_1_2_no_migrations_yet_passes_without_azure(args: list[str], work_dir: Path) -> None:
    result = _run("migrate.sh", *args, work_dir=work_dir, CI_MIGRATIONS_DIR=str(work_dir / "migrations"))
    assert result.returncode == 0, result.stderr
    assert "no migrations" in result.stdout
    assert "FAKE-TOOL-CALLED" not in result.stderr
    if args[0] == "--check":
        assert "output: hasWork=false" in result.stdout


@pytest.mark.parametrize(
    ("env", "login", "pipeline_role", "staff_api_role"),
    [
        ("dev", "babaloo-sea-lng-id-22", "babaloo-sea-lng-id-03", "babaloo-sea-lng-id-02"),
        ("prod", "babaloo-sea-lng-id-23", "babaloo-sea-lng-id-13", "babaloo-sea-lng-id-12"),
    ],
)
def test_story_1_2_migrations_run_as_the_env_deploy_identity_with_an_entra_token(
    env: str, login: str, pipeline_role: str, staff_api_role: str, work_dir: Path
) -> None:
    migrations = work_dir / "migrations"
    migrations.mkdir()
    (migrations / "env.py").write_text("# fixture\n")
    check = _run("migrate.sh", "--check", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations))
    assert "output: hasWork=true" in check.stdout, check.stderr

    result = _run(
        "migrate.sh", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations),
        FAKE_AZ_TOKEN="entra-token-for-postgres", FAKE_AZ_LOG=str(work_dir / "az.log"),
        FAKE_UV_LOG=str(work_dir / "uv.jsonl"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (call,) = [json.loads(line) for line in (work_dir / "uv.jsonl").read_text().splitlines()]
    # Story 2.1: the roles the migrations grant to are the environment's app logins (AD-11).
    assert call["args"] == [
        "run", "--directory", str(REPO_ROOT / "backend"), "--locked", "--no-dev", "alembic",
        "-x", f"pipeline_role={pipeline_role}", "-x", f"staff_api_role={staff_api_role}", "upgrade", "head",
    ]
    assert call["env"] == {
        "PGHOST": "babaloo-sea-lng-psql-21.postgres.database.azure.com",
        "PGPORT": "5432",
        "PGUSER": login,
        "PGDATABASE": f"invoicing_{env}",
        "PGSSLMODE": "require",
        "PGPASSWORD": "entra-token-for-postgres",
    }
    az_calls = (work_dir / "az.log").read_text().splitlines()
    assert az_calls == ["account get-access-token --resource-type oss-rdbms --query accessToken -o tsv"]
    assert "firewall" not in result.stdout + result.stderr


def test_story_1_2_migrations_only_for_dev_or_prod(work_dir: Path) -> None:
    result = _run("migrate.sh", "shared", work_dir=work_dir)
    assert result.returncode == 1
    assert "environment must be dev or prod" in result.stderr


def test_story_1_2_code_deploy_is_a_no_op_until_the_app_stack_exists(work_dir: Path) -> None:
    result = _run("code-deploy.sh", "--check", "dev", work_dir=work_dir)
    assert result.returncode == 0, result.stderr
    assert "output: hasWork=false" in result.stdout
    assert "FAKE-TOOL-CALLED" not in result.stderr


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
    """code-deploy.sh against scratch infra/web/backend/build folders and fake uv, npm,
    az and curl."""
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
        "FAKE_NPM_LOG": str(work_dir / "npm.jsonl"),
        "FAKE_AZ_LOG": str(work_dir / "az.log"),
        "FAKE_AZ_DEPLOY": "1",
        "FAKE_CURL_LOG": str(work_dir / "curl.log"),
        "FAKE_CURL_VERSION": VERSION,
    }
    env.update(env_extra)
    return _run("code-deploy.sh", *args, work_dir=work_dir, **env)


def _scaffold_web(work_dir: Path, name: str, package_json: str | None = None) -> Path:
    app = work_dir / "web" / name
    app.mkdir(parents=True)
    (app / "package.json").write_text(
        package_json or '{"name": "fixture", "private": true, "scripts": {"build": "vite build"}}\n'
    )
    return app


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def test_story_1_3_code_deploy_has_work_once_the_app_stack_exists(work_dir: Path) -> None:
    result = _deploy(work_dir, "--check", "prod")
    assert result.returncode == 0, result.stderr
    assert "output: hasWork=true" in result.stdout
    assert not (work_dir / "uv.jsonl").exists() and not (work_dir / "az.log").exists()


@pytest.mark.parametrize(("env", "base"), [("dev", 1), ("prod", 11)])
def test_story_1_3_code_deploy_builds_one_flat_zip_per_app_publishes_it_and_checks_health(
    env: str, base: int, work_dir: Path
) -> None:
    _scaffold_web(work_dir, "staff")
    result = _deploy(work_dir, env)
    assert result.returncode == 0, result.stdout + result.stderr

    (export,) = [json.loads(line)["args"] for line in (work_dir / "uv.jsonl").read_text().splitlines()]
    assert export[:3] == ["export", "--directory", str(work_dir / "backend")]
    assert {"--locked", "--no-dev", "--no-emit-project"} <= set(export)

    build = work_dir / "build"
    for app in APPS:
        module = app.replace("-", "_")
        names = _zip_names(build / f"{app}.zip")
        assert {"function_app.py", "host.json", "requirements.txt", "invoicing/__init__.py"} <= names
        # Story 1.4: http.py reads the security headers from here.
        assert "shared/security-headers.json" in names
        # Story 2.1: the quality stage reads the page's thresholds file (AD-6).
        assert ("shared/quality-thresholds.json" in names) == (app == "pipeline")
        if app == "pipeline":
            with zipfile.ZipFile(build / f"{app}.zip") as archive:
                assert archive.read("shared/quality-thresholds.json") == (
                    REPO_ROOT / "shared" / "quality-thresholds.json"
                ).read_bytes()
        assert f"invoicing/apps/{module}/function_app.py" in names
        with zipfile.ZipFile(build / f"{app}.zip") as archive:
            assert archive.read("function_app.py") == (PACKAGE_SRC / "apps" / module / "function_app.py").read_bytes()
            assert archive.read("host.json") == (PACKAGE_SRC / "apps" / module / "host.json").read_bytes()
            assert archive.read("requirements.txt").startswith(b"azure-functions==2.3.0")
        # Only a scaffolded SPA is packaged, and only into the API that serves it (AD-14).
        assert ("static/index.html" in names) == (app == "staff-api")

    npm_calls = [json.loads(line) for line in (work_dir / "npm.jsonl").read_text().splitlines()]
    staff = str(work_dir / "web" / "staff")
    assert npm_calls == [["ci", "--prefix", staff, "--no-audit", "--no-fund"], ["run", "--prefix", staff, "build"]]

    rg = f"babaloo-sea-lng-rg-{base:02d}"
    func = {app: f"babaloo-sea-lng-func-{base + i:02d}" for i, app in enumerate(APPS)}
    assert (work_dir / "az.log").read_text().splitlines() == [
        f"functionapp deployment source config-zip --resource-group {rg} --name {func[app]}"
        f" --src {build / app}.zip --build-remote true"
        for app in APPS
    ] + [
        f"functionapp show --resource-group {rg} --name {func[app]} --query defaultHostName -o tsv"
        for app in ("supplier-api", "staff-api")
    ]
    for app in APPS:
        assert f"published {app} ({func[app]})" in result.stdout
    assert (work_dir / "curl.log").read_text().splitlines() == [
        f"https://{func['supplier-api']}.azurewebsites.net/api/health",
        f"https://{func['staff-api']}.azurewebsites.net/api/health",
    ]


def test_story_1_3_only_git_tracked_package_files_are_shipped(work_dir: Path) -> None:
    result = _deploy(work_dir, "--build-only", "dev")
    assert result.returncode == 0, result.stdout + result.stderr
    for app in APPS:
        names = _zip_names(work_dir / "build" / f"{app}.zip")
        assert "invoicing/local_scratch.py" not in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)


def test_story_1_3_health_check_retries_until_the_app_answers(work_dir: Path) -> None:
    result = _deploy(work_dir, "dev", FAKE_CURL_FAILURES="2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "supplier-api not healthy yet (attempt 2/3, HTTP 503)" in result.stdout
    assert len((work_dir / "curl.log").read_text().splitlines()) == 4


@pytest.mark.parametrize(("extra", "reason"), [({"FAKE_CURL_FAILURES": "99"}, "HTTP 503"), ({"FAKE_CURL_VERSION": "0.0.0-old"}, "HTTP 200")])
def test_story_1_3_an_unhealthy_or_stale_app_fails_the_deploy(extra: dict[str, str], reason: str, work_dir: Path) -> None:
    result = _deploy(work_dir, "dev", **extra)
    assert result.returncode != 0
    assert f"attempt 3/3, {reason}" in result.stdout
    assert (
        f"supplier-api did not report healthy version {VERSION}; published: supplier-api staff-api pipeline accounts-sim"
        in result.stderr
    )


def test_story_1_3_build_only_publishes_nothing(work_dir: Path) -> None:
    result = _deploy(work_dir, "--build-only", "dev")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no SPA packaged" in result.stdout
    assert sorted(path.name for path in (work_dir / "build").glob("*.zip")) == sorted(f"{app}.zip" for app in APPS)
    assert not (work_dir / "az.log").exists() and not (work_dir / "npm.jsonl").exists()


def test_story_1_3_a_spa_build_without_output_stops_the_deploy(work_dir: Path) -> None:
    _scaffold_web(work_dir, "supplier")
    result = _deploy(work_dir, "dev", FAKE_NPM_NO_DIST="1")
    assert result.returncode != 0
    assert "npm run build produced no dist/index.html" in result.stderr
    assert not (work_dir / "az.log").exists()


def test_story_1_3_a_stale_dist_is_never_packaged(work_dir: Path) -> None:
    app = _scaffold_web(work_dir, "supplier")
    (app / "dist").mkdir()
    (app / "dist" / "index.html").write_text("stale build\n")
    (app / "dist" / "old-chunk.js").write_text("stale\n")
    result = _deploy(work_dir, "dev", FAKE_NPM_NO_DIST="1")
    assert result.returncode != 0
    assert "npm run build produced no dist/index.html" in result.stderr

    fresh = _deploy(work_dir, "--build-only", "dev")
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    names = _zip_names(work_dir / "build" / "supplier-api.zip")
    assert "static/index.html" in names and "static/old-chunk.js" not in names


def test_story_1_3_a_malformed_package_json_stops_the_deploy(work_dir: Path) -> None:
    _scaffold_web(work_dir, "staff", package_json='{"name": "fixture", "scripts": {\n')
    result = _deploy(work_dir, "dev")
    assert result.returncode != 0
    assert "package.json is not valid JSON" in result.stderr
    assert not (work_dir / "az.log").exists()


def test_story_1_3_a_failed_publish_fails_the_stage_and_lists_what_was_published(work_dir: Path) -> None:
    result = _deploy(work_dir, "dev", FAKE_AZ_DEPLOY="")
    assert result.returncode != 0
    assert "FAKE-TOOL-CALLED: az functionapp deployment source config-zip" in result.stderr
    assert "publishing supplier-api failed; already published: none" in result.stderr
    assert len((work_dir / "az.log").read_text().splitlines()) == 1


def test_story_1_3_a_publish_failing_mid_way_lists_the_apps_already_published(work_dir: Path) -> None:
    result = _deploy(work_dir, "dev", FAKE_AZ_FAIL_NAME="babaloo-sea-lng-func-03")
    assert result.returncode != 0
    assert "published supplier-api (babaloo-sea-lng-func-01)" in result.stdout
    assert "publishing pipeline failed; already published: supplier-api staff-api" in result.stderr
    assert not (work_dir / "curl.log").exists()


def test_story_1_3_code_deploy_only_for_dev_or_prod(work_dir: Path) -> None:
    result = _deploy(work_dir, "shared")
    assert result.returncode == 1
    assert "environment must be dev or prod" in result.stderr


# --- checks.sh ---------------------------------------------------------------------------


def test_story_1_2_checks_rejects_an_unknown_subcommand(work_dir: Path) -> None:
    result = _run("checks.sh", "deploy", work_dir=work_dir)
    assert result.returncode == 1
    assert "unknown subcommand: deploy" in result.stderr
    assert _run("checks.sh", work_dir=work_dir).returncode == 2
    help_result = _run("checks.sh", "--help", work_dir=work_dir)
    assert help_result.returncode == 0 and "Usage:" in help_result.stdout


# --- install-tools.sh --------------------------------------------------------------------


def _install(work_dir: Path, *tools: str, **env_extra: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "TF_", "AGENT_"))}
    env.update(
        {
            "PATH": f"{INSTALL_BIN}{os.pathsep}{env.get('PATH', '')}",
            "CI_TOOLS_DIR": str(work_dir / "bin"),
            "AGENT_TEMPDIRECTORY": str(work_dir / "agent-temp" / "not-created-yet"),
            "FAKE_CURL_LOG": str(work_dir / "curl.log"),
        }
    )
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(CI / "install-tools.sh"), *tools], env=env, capture_output=True, text=True, check=False, timeout=60
    )


def test_story_1_2_install_tools_verifies_and_installs_the_pinned_downloads(work_dir: Path) -> None:
    result = _install(work_dir, "terraform", "gitleaks", "uv", TF_BUILD="True")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(p.name for p in (work_dir / "bin").iterdir()) == ["gitleaks", "terraform", "uv", "uvx"]
    assert f"##vso[task.prependpath]{work_dir / 'bin'}" in result.stdout.splitlines()
    urls = (work_dir / "curl.log").read_text().splitlines()
    assert urls == [
        "https://releases.hashicorp.com/terraform/1.16.4/terraform_1.16.4_linux_amd64.zip",
        "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
        "https://github.com/astral-sh/uv/releases/download/0.11.8/uv-x86_64-unknown-linux-gnu.tar.gz",
    ]


def test_story_1_2_install_tools_rejects_a_checksum_mismatch(work_dir: Path) -> None:
    result = _install(work_dir, "terraform", FAKE_CURL_CONTENT="TAMPERED")
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not (work_dir / "bin" / "terraform").exists()


def test_story_1_2_install_tools_rejects_an_unknown_tool(work_dir: Path) -> None:
    result = _install(work_dir, "kubectl")
    assert result.returncode == 1
    assert "unknown tool: kubectl" in result.stderr


@pytest.mark.parametrize(("system", "machine"), [("Darwin", "arm64"), ("Linux", "aarch64")])
def test_story_1_2_install_tools_runs_only_on_linux_x86_64(system: str, machine: str, work_dir: Path) -> None:
    result = _install(work_dir, "uv", FAKE_UNAME_S=system, FAKE_UNAME_M=machine)
    assert result.returncode == 1
    assert "Linux x86_64 agents only" in result.stderr
    assert not (work_dir / "curl.log").exists()
