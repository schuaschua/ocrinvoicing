"""Story 1.2: behaviour of the scripts behind the deploy stages, run against a fake
`terraform` (ci/tests/fake-bin) and an `az` that fails if called. Nothing reaches Azure.

Covers the I/O matrix rows "No infra change", "Untagged resource in plan" and
"No migrations yet".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
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


@pytest.mark.parametrize(("env", "login"), [("dev", "babaloo-sea-lng-id-22"), ("prod", "babaloo-sea-lng-id-23")])
def test_story_1_2_migrations_run_as_the_env_deploy_identity_with_an_entra_token(
    env: str, login: str, work_dir: Path
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
    assert call["args"] == [
        "run", "--directory", str(REPO_ROOT / "backend"), "--locked", "--no-dev", "alembic", "upgrade", "head",
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


@pytest.mark.skipif((REPO_ROOT / "infra" / "dev" / "app").exists(), reason="infra/dev/app exists (Story 1.3)")
def test_story_1_2_code_deploy_is_a_no_op_until_the_app_stack_exists(work_dir: Path) -> None:
    result = _run("code-deploy.sh", "--check", "dev", work_dir=work_dir)
    assert result.returncode == 0, result.stderr
    assert "output: hasWork=false" in result.stdout


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
