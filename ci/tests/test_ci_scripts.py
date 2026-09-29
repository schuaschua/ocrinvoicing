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


def test_story_1_2_terraform_plan_tag_gate(work_dir: Path) -> None:
    """terraform-plan.sh. Covers: a plan with changes and tags hands the saved plan to apply
    (and deletes the plan JSON); an untagged resource stops the stack before apply."""
    # A plan with changes and tags hands the saved plan to apply.
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


# --- terraform-apply.sh ----------------------------------------------------------------


def test_story_1_2_terraform_apply_only_from_the_saved_plan(work_dir: Path) -> None:
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
    ("dev", "babaloo-sea-lng-id-22", "babaloo-sea-lng-id-03", "babaloo-sea-lng-id-02"),
    ("prod", "babaloo-sea-lng-id-23", "babaloo-sea-lng-id-13", "babaloo-sea-lng-id-12"),
]


def test_story_1_2_migrations_run_as_the_env_deploy_identity_with_an_entra_token(work_dir: Path) -> None:
    """migrate.sh, for dev and then prod: --check finds work; the run uses the env deploy
    identity's login with an Entra token over TLS, grants to the env's app logins (Story 2.1),
    asks az for one token and opens no firewall."""
    for env, login, pipeline_role, staff_api_role in MIGRATE_ENVIRONMENTS:
        migrations = work_dir / f"migrations-{env}"
        migrations.mkdir()
        (migrations / "env.py").write_text("# fixture\n")
        check = _run("migrate.sh", "--check", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations))
        assert "output: hasWork=true" in check.stdout, (env, check.stderr)

        az_log, uv_log = work_dir / f"az-{env}.log", work_dir / f"uv-{env}.jsonl"
        result = _run(
            "migrate.sh", env, work_dir=work_dir, CI_MIGRATIONS_DIR=str(migrations),
            FAKE_AZ_TOKEN="entra-token-for-postgres", FAKE_AZ_LOG=str(az_log),
            FAKE_UV_LOG=str(uv_log),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        (call,) = [json.loads(line) for line in uv_log.read_text().splitlines()]
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
    }
    env.update(env_extra)
    return _run("code-deploy.sh", *args, work_dir=work_dir, **env)


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def test_story_1_3_code_deploy(work_dir: Path) -> None:
    """code-deploy.sh. Covers: only git-tracked package files are shipped (no untracked module,
    no bytecode); the health check retries until the app answers; an unhealthy app fails the
    deploy. Each run gets its own curl log."""
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


def test_story_1_2_install_tools_rejects_a_checksum_mismatch(work_dir: Path) -> None:
    result = _install(work_dir, "terraform", FAKE_CURL_CONTENT="TAMPERED")
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not (work_dir / "bin" / "terraform").exists()
