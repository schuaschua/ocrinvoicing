"""I/O-matrix behaviour tests for infra/bootstrap, run for real (no --dry-run)
against stateful fakes in fake-bin-stateful/. Nothing reaches Azure or a database.

- "Bootstrap re-run": every resource already exists; the security settings are
  re-applied.
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
    "ADO_APPROVER": "dj@example.test",
    "ALERT_EMAIL": "alerts@example.test",
    "PG_ADMIN_USER": "pg-admins@example.test",
    "SP_WAIT_SECONDS": "0",
}

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


def test_state_backend_rerun_reapplies_the_security_settings(work_dir: Path) -> None:
    result, calls = _run("state-backend.sh", work_dir)
    assert result.returncode == 0, result.stderr
    assert any(_starts_with(call, ["storage", "account", "update"]) and "--allow-shared-key-access" in call for call in calls)
    # OCR-129: the private-key vaults keep their settings.
    vault_updates = [call for call in calls if _starts_with(call, ["keyvault", "update"])]
    assert [call[call.index("--name") + 1] for call in vault_updates] == ["babaloo-sea-lng-kv-22", "babaloo-sea-lng-kv-23"]
    for call in vault_updates:
        assert call[call.index("--resource-group") + 1] == "babaloo-sea-lng-rg-22"
        assert call[call.index("--enable-rbac-authorization") + 1] == "true"
        assert call[call.index("--enable-purge-protection") + 1] == "true"


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


# The dev vaults and staff-api's secret-scoped role (OCR-129).
ENV_PRIVATE = "--vault-name babaloo-sea-lng-kv-01 --name pgp-private-key"
ENV_PUBLIC = "--vault-name babaloo-sea-lng-kv-01 --name pgp-public-key"
PK_PRIVATE = "--vault-name babaloo-sea-lng-kv-22 --name pgp-private-key"
PRIVATE_SECRET_SCOPE = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-22"
    "/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-22/secrets/pgp-private-key"
)


def _assert_no_key_generation(calls: list[list[str]]) -> None:
    assert _tool_calls(calls, "gpg") == []
    assert not any(_starts_with(call, ["keyvault", "secret", "set"]) for call in calls)


def _role_creates(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if _starts_with(call, ["role", "assignment", "create"])]


def test_pgp_both_secrets_exist_does_nothing(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH=ENV_PRIVATE)
    assert result.returncode == 0, result.stderr
    assert "nothing to generate" in result.stdout
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []
    assert f"exists: role 4633458b-17de-408a-b874-0445c86b69e6 for 55555555-5555-5555-5555-555555555555 at {PRIVATE_SECRET_SCOPE}" in result.stdout


def test_pgp_rerun_after_a_missed_grant_only_grants_staff_api(work_dir: Path) -> None:
    result, calls = _run(
        "pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH=ENV_PRIVATE, FAKE_AZ_NO_ROLE_ASSIGNMENTS="1"
    )
    assert result.returncode == 0, result.stderr
    _assert_no_key_generation(calls)
    (grant,) = _role_creates(calls)
    assert grant[grant.index("--scope") + 1] == PRIVATE_SECRET_SCOPE


@pytest.mark.parametrize("absent", [ENV_PUBLIC, PK_PRIVATE])
def test_pgp_only_one_secret_exists_stops(absent: str, work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH=f"{ENV_PRIVATE}||{absent}")
    assert result.returncode == 1
    assert "only one of pgp-public-key (babaloo-sea-lng-kv-01) / pgp-private-key (babaloo-sea-lng-kv-22) exists" in result.stderr
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []


def test_pgp_secret_lookup_error_stops_without_generating(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_FAIL_MATCH="keyvault secret show")
    assert result.returncode == 1
    assert "lookup failed, and not with NotFound" in result.stderr
    _assert_no_key_generation(calls)


def test_ocr_129_pgp_new_environment_splits_the_pair_and_grants_staff_api(work_dir: Path) -> None:
    result, calls = _run(
        "pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH="keyvault secret show", FAKE_AZ_NO_ROLE_ASSIGNMENTS="1"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    sets = [call for call in calls if _starts_with(call, ["keyvault", "secret", "set"])]
    assert [(call[call.index("--vault-name") + 1], call[call.index("--name") + 1]) for call in sets] == [
        ("babaloo-sea-lng-kv-22", "pgp-private-key"),
        ("babaloo-sea-lng-kv-01", "pgp-public-key"),
    ]
    stored = {entry["args"][entry["args"].index("--vault-name") + 1]: entry["content"] for entry in _files(work_dir)}
    assert "BEGIN PGP PRIVATE KEY BLOCK" in stored["babaloo-sea-lng-kv-22"]
    assert "PRIVATE" not in stored["babaloo-sea-lng-kv-01"]
    (grant,) = _role_creates(calls)
    assert grant[grant.index("--assignee-object-id") + 1] == "55555555-5555-5555-5555-555555555555"
    assert grant[grant.index("--assignee-principal-type") + 1] == "ServicePrincipal"
    assert grant[grant.index("--role") + 1] == "4633458b-17de-408a-b874-0445c86b69e6"
    assert grant[grant.index("--scope") + 1] == PRIVATE_SECRET_SCOPE
    assert calls.index(grant) > calls.index(sets[-1])
    # The throwaway GNUPGHOME is gone.
    assert not any((REPO_ROOT / ".work" / "bootstrap").glob("tmp.*/private.asc"))


def test_ocr_129_pgp_stops_before_writing_when_staff_api_identity_is_missing(work_dir: Path) -> None:
    result, calls = _run(
        "pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH="identity show --name babaloo-sea-lng-id-02"
    )
    assert result.returncode == 1
    assert "staff-api identity babaloo-sea-lng-id-02 not found in babaloo-sea-lng-rg-01" in result.stderr
    assert "apply dev/foundation (AD-17 step 4) first" in result.stderr
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []


def test_ocr_129_pgp_stops_when_the_private_key_vault_is_missing(work_dir: Path) -> None:
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH="keyvault show --name babaloo-sea-lng-kv-22")
    assert result.returncode == 1
    assert "run state-backend.sh (AD-17 step 1) first" in result.stderr
    _assert_no_key_generation(calls)


@pytest.mark.parametrize("pk_private", ["absent", "present"])
def test_ocr_129_pgp_legacy_private_key_in_the_env_vault_stops_without_copying(pk_private: str, work_dir: Path) -> None:
    not_found = PK_PRIVATE if pk_private == "absent" else ""
    result, calls = _run("pgp-step4b.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH=not_found)
    assert result.returncode == 1
    assert "pgp-private-key is in babaloo-sea-lng-kv-01" in result.stderr
    assert "Move it to babaloo-sea-lng-kv-22, then delete and purge it" in result.stderr
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []
    assert not any(_starts_with(call, ["keyvault", "secret", "download"]) for call in calls)


# --- Step 5: Dj's load-script rights (OCR-129) -------------------------------------------------

DEV_VAULT = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
    "/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
)


def test_ocr_129_database_step5_grants_dj_two_secrets_only(work_dir: Path) -> None:
    result, calls = _run("database-step5.sh", work_dir, DJ_USER_UPN="dj@example.test", FAKE_AZ_NO_ROLE_ASSIGNMENTS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    kv = [call for call in _role_creates(calls) if "Microsoft.KeyVault" in call[call.index("--scope") + 1]]
    assert sorted(call[call.index("--scope") + 1] for call in kv) == [
        f"{DEV_VAULT}/secrets/hmac-key",
        f"{DEV_VAULT}/secrets/pgp-public-key",
    ]
    assert all(call[call.index("--role") + 1] == "4633458b-17de-408a-b874-0445c86b69e6" for call in kv)
    assert not any(_starts_with(call, ["role", "assignment", "delete"]) for call in calls)


def test_ocr_129_database_step5_removes_an_earlier_vault_wide_role(work_dir: Path) -> None:
    result, calls = _run("database-step5.sh", work_dir, DJ_USER_UPN="dj@example.test")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _role_creates(calls) == []
    (delete,) = [call for call in calls if _starts_with(call, ["role", "assignment", "delete"])]
    assert delete[delete.index("--ids") + 1].startswith(f"{DEV_VAULT}/providers/Microsoft.Authorization/roleAssignments/")


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


# --- verify-db-isolation.sh: a missing database is a failure ------------------------------------


def test_missing_database_fails_the_public_check(work_dir: Path) -> None:
    result, _ = _run("verify-db-isolation.sh", work_dir, FAKE_PSQL_MISSING_DB="invoicing_prod")
    assert result.returncode == 1
    assert "FAIL invoicing_prod does not exist" in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_prod" not in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_dev" in result.stdout
