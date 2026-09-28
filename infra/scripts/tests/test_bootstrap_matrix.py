"""I/O-matrix behaviour tests for infra/bootstrap, run for real (no --dry-run)
against stateful fakes in fake-bin-stateful/. Nothing reaches Azure or a database.

- "Bootstrap re-run": every resource already exists, so each script must only
  skip or update, never create, and exit 0.
- "Cross-env DB": verify-db-isolation.sh reports PASS when a Dev login is refused
  on invoicing_prod, and FAIL (non-zero exit) when it gets in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO_ROOT / "infra" / "bootstrap"
STATEFUL_BIN = Path(__file__).resolve().parent / "fake-bin-stateful"

FAKE_INPUTS = {
    "ARM_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "ARM_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "TAG_OWNER": "test-owner",
    "TAG_COST_CENTRE": "test-cc",
    "TAG_APPLICATION": "test-app",
    "TAG_DATA_CLASSIFICATION": "test-class",
    "ADO_ORG": "test-org",
    "ADO_ORG_ID": "44444444-4444-4444-4444-444444444444",
    "ADO_PROJECT": "test-project",
    "ALERT_EMAIL": "alerts@example.test",
    "PG_ADMIN_USER": "pg-admins@example.test",
    "SP_WAIT_SECONDS": "0",
}

# Calls that would create something that the fake says already exists.
CREATE_CALLS = [
    ["group", "create"],
    ["storage", "account", "create"],
    ["storage", "container-rm", "create"],
    ["identity", "create"],
    ["identity", "federated-credential", "create"],
    ["role", "assignment", "create"],
    ["role", "definition", "create"],
    ["ad", "app", "create"],
    ["ad", "sp", "create"],
]


@pytest.fixture
def work_dir() -> Path:
    """Scratch dir under the gitignored .work/ folder (never /tmp)."""
    path = REPO_ROOT / ".work" / "pytest-bootstrap" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _run(script: str, work_dir: Path, **extra_env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    log = work_dir / "az-calls.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARM_", "TAG_", "ADO_", "FAKE_"))}
    env.pop("CONNECT_AS_LOGIN", None)
    env.update(FAKE_INPUTS)
    env.update(extra_env)
    env["FAKE_AZ_LOG"] = str(log)
    env["PATH"] = f"{STATEFUL_BIN}{os.pathsep}{env.get('PATH', '')}"
    env["ENVIRONMENT"] = extra_env.get("ENVIRONMENT", "dev")
    result = subprocess.run(
        ["bash", str(BOOTSTRAP / script)], env=env, capture_output=True, text=True, check=False, timeout=120
    )
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    return result, calls


def _starts_with(call: list[str], prefix: list[str]) -> bool:
    return call[: len(prefix)] == prefix


@pytest.mark.parametrize("script", ["state-backend.sh", "app-registrations.sh", "budget-and-roles.sh", "rbac-step3.sh"])
def test_rerun_with_everything_existing_only_skips_or_updates(script: str, work_dir: Path) -> None:
    result, calls = _run(script, work_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls, "the script made no az calls"
    creates = [call for call in calls if any(_starts_with(call, prefix) for prefix in CREATE_CALLS)]
    assert creates == [], f"create calls on existing resources: {creates}"
    budget_puts = [call for call in calls if call[:1] == ["rest"] and "put" in call]
    assert budget_puts == [], "an existing subscription budget must be left unchanged"


def test_state_backend_rerun_updates_tags_and_settings(work_dir: Path) -> None:
    result, calls = _run("state-backend.sh", work_dir)
    assert result.returncode == 0, result.stderr
    group_updates = [call for call in calls if _starts_with(call, ["group", "update"])]
    assert [call[call.index("--name") + 1] for call in group_updates] == [
        "babaloo-sea-lng-rg-21",
        "babaloo-sea-lng-rg-01",
        "babaloo-sea-lng-rg-11",
        "babaloo-sea-lng-rg-22",
    ]
    assert all(
        "environment=" + env in " ".join(call) for call, env in zip(group_updates, ["shared", "dev", "prod", "shared"])
    )
    assert all(call[-1] == "--wait" for call in calls if _starts_with(call, ["provider", "register"]))
    assert not any(_starts_with(call, ["identity", "federated-credential", "update"]) for call in calls)
    assert any(_starts_with(call, ["storage", "account", "update"]) and "--allow-shared-key-access" in call for call in calls)
    assert sum(_starts_with(call, ["identity", "update"]) for call in calls) == 3
    assert "exists: container dev" in result.stdout


def test_app_registrations_rerun_keeps_existing_roles(work_dir: Path) -> None:
    result, calls = _run("app-registrations.sh", work_dir)
    assert result.returncode == 0, result.stderr
    assert "app roles up to date" in result.stdout
    assert not any(_starts_with(call, ["ad", "app", "update"]) and "--app-roles" in call for call in calls)


def test_cross_env_connection_refused_reports_pass(work_dir: Path) -> None:
    result, _ = _run(
        "verify-db-isolation.sh",
        work_dir,
        CONNECT_AS_LOGIN="babaloo-sea-lng-id-22",
        TARGET_DB="invoicing_prod",
        FAKE_PSQL_CROSS_ENV="refuse",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS babaloo-sea-lng-id-22 refused by invoicing_prod" in result.stdout
    assert "FAIL" not in result.stdout


def test_cross_env_connection_allowed_reports_fail(work_dir: Path) -> None:
    result, _ = _run(
        "verify-db-isolation.sh",
        work_dir,
        CONNECT_AS_LOGIN="babaloo-sea-lng-id-22",
        TARGET_DB="invoicing_prod",
        FAKE_PSQL_CROSS_ENV="allow",
    )
    assert result.returncode != 0
    assert "FAIL babaloo-sea-lng-id-22 connected to invoicing_prod" in result.stdout


def test_privilege_check_passes_when_isolated(work_dir: Path) -> None:
    result, _ = _run("verify-db-isolation.sh", work_dir, FAKE_PSQL_CROSS_ENV="refuse")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS babaloo-sea-lng-id-03 refused on invoicing_prod" in result.stdout
    assert "PASS babaloo-sea-lng-id-13 refused on invoicing_dev" in result.stdout
    assert "All isolation checks passed." in result.stdout


def test_privilege_check_fails_when_dev_can_reach_prod(work_dir: Path) -> None:
    result, _ = _run("verify-db-isolation.sh", work_dir, FAKE_PSQL_CROSS_ENV="allow")
    assert result.returncode == 1
    assert "FAIL babaloo-sea-lng-id-03 can CONNECT to invoicing_prod" in result.stdout


def _files(work_dir: Path) -> list[dict]:
    path = work_dir / "az-calls.jsonl.files"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _tool_calls(calls: list[list[str]], tool: str) -> list[list[str]]:
    return [call for call in calls if call[:1] == [f"__{tool}__"]]


# --- Lookup errors other than NotFound stop the script -----------------------------------


def test_lookup_failure_that_is_not_not_found_stops_the_script(work_dir: Path) -> None:
    result, calls = _run("state-backend.sh", work_dir, FAKE_AZ_FAIL_MATCH="group show")
    assert result.returncode == 1
    assert "lookup failed, and not with NotFound" in result.stderr
    assert "AuthorizationFailed" in result.stderr
    assert not any(_starts_with(call, prefix) for call in calls for prefix in CREATE_CALLS)
    assert not any(_starts_with(call, ["group", "update"]) for call in calls)


# --- Federated credentials follow changed ADO inputs ------------------------------------------


def test_stale_federated_credentials_are_updated(work_dir: Path) -> None:
    result, calls = _run("state-backend.sh", work_dir, FAKE_AZ_FED_STALE="1")
    assert result.returncode == 0, result.stderr
    updates = [call for call in calls if _starts_with(call, ["identity", "federated-credential", "update"])]
    assert len(updates) == 3
    for call, owner in zip(updates, ["shared", "dev", "prod"]):
        assert call[call.index("--issuer") + 1] == "https://vstoken.dev.azure.com/44444444-4444-4444-4444-444444444444"
        assert call[call.index("--subject") + 1] == f"sc://test-org/test-project/azure-{owner}"
    assert not any(_starts_with(call, ["identity", "federated-credential", "create"]) for call in calls)


# --- PGP key pair guards (step 4b) ---------------------------------------------------------------


def _assert_no_key_generation(calls: list[list[str]]) -> None:
    assert _tool_calls(calls, "gpg") == []
    assert not any(_starts_with(call, ["keyvault", "secret", "set"]) for call in calls)


def test_pgp_both_secrets_exist_does_nothing(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir)
    assert result.returncode == 0, result.stderr
    assert "nothing to do" in result.stdout
    _assert_no_key_generation(calls)


def test_pgp_only_one_secret_exists_stops(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH="--name pgp-public-key")
    assert result.returncode == 1
    assert "only one of pgp-public-key / pgp-private-key exists" in result.stderr
    _assert_no_key_generation(calls)


def test_pgp_secret_lookup_error_stops_without_generating(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_FAIL_MATCH="keyvault secret show")
    assert result.returncode == 1
    assert "lookup failed, and not with NotFound" in result.stderr
    _assert_no_key_generation(calls)


# --- App registrations ----------------------------------------------------------------------------


def test_missing_app_role_is_added_keeping_existing_ids(work_dir: Path) -> None:
    result, calls = _run("app-registrations.sh", work_dir, FAKE_AZ_STAFF_ROLES="4")
    assert result.returncode == 0, result.stderr
    role_updates = [call for call in calls if _starts_with(call, ["ad", "app", "update"]) and "--app-roles" in call]
    assert len(role_updates) == 2  # exactly one per environment's staff-api registration
    role_files = [entry for entry in _files(work_dir) if "--app-roles" in entry["args"]]
    assert len(role_files) == 2
    for entry in role_files:
        roles = json.loads(entry["content"])
        existing = [role for role in roles if role["value"] != "goods_in"]
        added = [role for role in roles if role["value"] == "goods_in"]
        assert [role["value"] for role in existing] == ["admin", "finance", "procurement", "management"]
        assert all(role["id"] == "55555555-5555-5555-5555-555555555555" for role in existing)
        assert len(added) == 1 and added[0]["id"] != "55555555-5555-5555-5555-555555555555"
        assert added[0]["allowedMemberTypes"] == ["User"] and added[0]["isEnabled"] is True


def test_duplicate_app_registrations_stop_the_script(work_dir: Path) -> None:
    result, calls = _run("app-registrations.sh", work_dir, FAKE_AZ_DUPLICATE_APPS="1")
    assert result.returncode == 1
    assert "matches 2 app registrations" in result.stderr
    assert not any(_starts_with(call, ["ad", "app", "update"]) for call in calls)


# --- ACS Email Sender role update injects the existing id ---------------------------------------


def test_existing_custom_role_is_updated_with_its_id(work_dir: Path) -> None:
    result, calls = _run("budget-and-roles.sh", work_dir)
    assert result.returncode == 0, result.stderr
    (entry,) = [e for e in _files(work_dir) if e["args"][:3] == ["role", "definition", "update"]]
    role = json.loads(entry["content"])
    assert role["Id"] == "55555555-5555-5555-5555-555555555555"
    assert role["Name"] == "ACS Email Sender"
    assert role["Actions"] == [
        "Microsoft.Communication/CommunicationServices/Read",
        "Microsoft.Communication/EmailServices/write",
    ]
    assert role["AssignableScopes"] == ["/subscriptions/00000000-0000-0000-0000-000000000000"]


# --- verify-db-isolation.sh: a missing database is a failure ------------------------------------


def test_missing_database_fails_the_public_check(work_dir: Path) -> None:
    result, _ = _run("verify-db-isolation.sh", work_dir, FAKE_PSQL_MISSING_DB="invoicing_prod")
    assert result.returncode == 1
    assert "FAIL invoicing_prod does not exist" in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_prod" not in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_dev" in result.stdout
