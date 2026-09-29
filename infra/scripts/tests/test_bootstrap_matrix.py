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
    "ADO_APPROVER": "dj@example.test",
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
    ["keyvault", "create"],
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
    # OCR-129: the private-key vaults keep their settings and get their tags re-applied.
    vault_updates = [call for call in calls if _starts_with(call, ["keyvault", "update"])]
    assert [call[call.index("--name") + 1] for call in vault_updates] == ["babaloo-sea-lng-kv-22", "babaloo-sea-lng-kv-23"]
    for call in vault_updates:
        assert call[call.index("--resource-group") + 1] == "babaloo-sea-lng-rg-22"
        assert call[call.index("--enable-rbac-authorization") + 1] == "true"
        assert call[call.index("--enable-purge-protection") + 1] == "true"
    tags = [call for call in calls if _starts_with(call, ["resource", "tag"])]
    assert [call[call.index("--name") + 1] for call in tags] == ["babaloo-sea-lng-kv-22", "babaloo-sea-lng-kv-23"]
    assert "environment=dev" in tags[0] and "environment=prod" in tags[1]


def test_app_registrations_rerun_keeps_existing_roles(work_dir: Path) -> None:
    result, calls = _run("app-registrations.sh", work_dir)
    assert result.returncode == 0, result.stderr
    assert "app roles up to date" in result.stdout
    assert not any(_starts_with(call, ["ad", "app", "update"]) and "--app-roles" in call for call in calls)


def test_app_registrations_turn_group_claims_off_on_staff_api(work_dir: Path) -> None:
    # Story 2.7: no group claims, so the built-in auth principal stays small.
    result, calls = _run("app-registrations.sh", work_dir)
    assert result.returncode == 0, result.stderr
    updates = [
        call
        for call in calls
        if _starts_with(call, ["ad", "app", "update"]) and "groupMembershipClaims=None" in call
    ]
    assert len(updates) == 2  # one per environment's staff-api registration


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


# --- Story 1.5: attaching ag-21 to an existing subscription budget ------------------------------

SHARED_AG_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-21"
    "/providers/Microsoft.Insights/actionGroups/babaloo-sea-lng-ag-21"
)


def _budget_puts(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[:1] == ["rest"] and "put" in call and "Consumption/budgets" in " ".join(call)]


def test_story_1_5_existing_budget_gets_the_action_group_and_keeps_the_rest(work_dir: Path) -> None:
    result, calls = _run("budget-and-roles.sh", work_dir, SHARED_ACTION_GROUP_ID=SHARED_AG_ID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_budget_puts(calls)) == 1
    (entry,) = [e for e in _files(work_dir) if e["args"][:1] == ["rest"] and "put" in e["args"]]
    update = json.loads(entry["content"])
    properties = update["properties"]
    assert properties["timePeriod"] == {"startDate": "2026-09-01T00:00:00Z"}
    assert properties["amount"] == 8
    (notification,) = properties["notifications"].values()
    assert notification["contactGroups"] == [SHARED_AG_ID]
    assert notification["contactEmails"] == ["alerts@example.test"]
    assert "currentSpend" not in properties and "id" not in update
    assert update["eTag"] == '"1d34d016a593709"'


def test_story_1_5_budget_already_notifying_the_group_is_left_unchanged(work_dir: Path) -> None:
    result, calls = _run(
        "budget-and-roles.sh",
        work_dir,
        SHARED_ACTION_GROUP_ID=SHARED_AG_ID,
        FAKE_AZ_BUDGET_GROUPS=SHARED_AG_ID.lower(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _budget_puts(calls) == []
    assert "already notifies babaloo-sea-lng-ag-21" in result.stdout


def test_story_1_5_alert_test_sends_through_every_existing_action_group(work_dir: Path) -> None:
    result, calls = _run("test-alerts.sh", work_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    sent = [call for call in calls if call[:4] == ["monitor", "action-group", "test-notifications", "create"]]
    assert [call[call.index("--action-group-name") + 1] for call in sent] == [
        "babaloo-sea-lng-ag-21",
        "babaloo-sea-lng-ag-01",
        "babaloo-sea-lng-ag-11",
    ]
    assert "Sent 3 test notification(s)" in result.stdout
    for call in sent:
        # Sent to the receiver stored on the group.
        assert call[call.index("--add-action") :][:5] == [
            "--add-action",
            "email",
            "owner",
            "alerts@example.test",
            "usecommonalertschema",
        ]


def _sent(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[:4] == ["monitor", "action-group", "test-notifications", "create"]]


def test_story_1_5_alert_test_stops_before_sending_when_an_action_group_is_missing(work_dir: Path) -> None:
    result, calls = _run("test-alerts.sh", work_dir, FAKE_AZ_NOT_FOUND_MATCH="babaloo-sea-lng-ag-11")
    assert result.returncode == 1
    assert "action group babaloo-sea-lng-ag-11 does not exist" in result.stderr
    assert _sent(calls) == [], "nothing may be sent when any requested group is missing"


def test_story_1_5_alert_test_fails_for_a_group_without_receivers(work_dir: Path) -> None:
    result, calls = _run("test-alerts.sh", work_dir, FAKE_AZ_NO_RECEIVERS="1")
    assert result.returncode == 1
    assert "has no email receiver" in result.stderr
    assert _sent(calls) == []


def test_story_1_5_existing_budget_without_notifications_stops_without_a_put(work_dir: Path) -> None:
    result, calls = _run(
        "budget-and-roles.sh",
        work_dir,
        SHARED_ACTION_GROUP_ID=SHARED_AG_ID,
        FAKE_AZ_BUDGET_NO_NOTIFICATIONS="1",
    )
    assert result.returncode == 1
    assert "the existing budget has no notifications" in result.stderr
    assert "could not add the action group to the existing budget babaloo-sea-lng-budget-22" in result.stderr
    assert _budget_puts(calls) == []
