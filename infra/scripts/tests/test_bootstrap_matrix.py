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
    "PG_ADMIN_USER": "babaloo-sea-lng-grp-21",
    "SP_WAIT_SECONDS": "0",
}

@pytest.fixture
def work_dir() -> Path:
    """Scratch dir under the gitignored .work/ folder (never /tmp)."""
    path = REPO_ROOT / ".work" / "pytest-bootstrap" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _case(work_dir: Path, name: str) -> Path:
    """A fresh sub-folder per run inside one merged test, so each run has its own call log."""
    path = work_dir / name
    path.mkdir()
    return path


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


def _files(work_dir: Path) -> list[dict]:
    path = work_dir / "az-calls.jsonl.files"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _tool_calls(calls: list[list[str]], tool: str) -> list[list[str]]:
    return [call for call in calls if call[:1] == [f"__{tool}__"]]


# --- state-backend.sh re-run ---------------------------------------------------------------------


def test_story_1_1_state_backend_rerun(work_dir: Path) -> None:
    """state-backend.sh re-run where everything exists. Covers: the security settings are
    re-applied (OCR-129 private-key vaults keep RBAC and purge protection);
    no federated credential is looked up or made (Dj, 2026-09-29); the state account
    stdjtfstatesea is only checked, and one allowing shared keys stops the run."""
    # Bootstrap re-run re-applies the security settings.
    result, calls = _run("state-backend.sh", _case(work_dir, "rerun"))
    assert result.returncode == 0, result.stderr
    # The state account is Dj's (stdjtfstatesea, Dj 2026-09-30): checked, never changed.
    assert not any(_starts_with(call, ["storage", "account", "update"]) for call in calls)
    assert not any(_starts_with(call, ["storage", "container-rm", "create"]) for call in calls)
    # OCR-129: the private-key vaults keep their settings.
    vault_updates = [call for call in calls if _starts_with(call, ["keyvault", "update"])]
    assert [call[call.index("--name") + 1] for call in vault_updates] == ["babaloo-sea-lng-kv-22", "babaloo-sea-lng-kv-23"]
    for call in vault_updates:
        assert call[call.index("--resource-group") + 1] == "babaloo-sea-lng-rg-22"
        assert call[call.index("--enable-rbac-authorization") + 1] == "true"
        assert call[call.index("--enable-purge-protection") + 1] == "true"
    assert not any(_starts_with(call, ["identity", "federated-credential"]) for call in calls)
    # Existing deploy identities are re-tagged with a command the az CLI has ("identity update" does not exist).
    assert not any(_starts_with(call, ["identity", "update"]) for call in calls)
    retagged = [call for call in calls if _starts_with(call, ["resource", "tag"]) and "Microsoft.ManagedIdentity/userAssignedIdentities" in call]
    assert [call[call.index("--name") + 1] for call in retagged] == [f"babaloo-sea-lng-id-2{n}" for n in (1, 2, 3)]
    # A state account that allows shared keys stops the run before any container is made.
    result, calls = _run("state-backend.sh", _case(work_dir, "shared-key"), FAKE_AZ_SHARED_KEY="true")
    assert result.returncode != 0 and "shared-key access" in result.stderr
    assert not any(_starts_with(call, ["storage", "container-rm"]) for call in calls)


# --- ci-vm.sh (Story 1.2, AD-17 step 1c) ------------------------------------------------------

CI_VM_TOKEN = "fake-ado-token-never-logged"
FAKE_GUID = "55555555-5555-5555-5555-555555555555"  # what the fake az reports for ids
PROD_ON_VM = "/subscriptions/x/resourceGroups/babaloo-sea-lng-rg-22/providers/Microsoft.ManagedIdentity/userAssignedIdentities/babaloo-sea-lng-id-23"
DEV_ON_VM = PROD_ON_VM.replace("id-23", "id-22")


def _ci_vm(work_dir: Path, **extra_env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    (work_dir / "id.pub").write_text("ssh-ed25519 AAAAfake operator@test\n")
    (work_dir / "ado-pat").write_text(CI_VM_TOKEN + "\n")
    inputs = {
        "CI_SSH_SOURCE_IP": "203.0.113.7",
        "CI_SSH_PUBLIC_KEY_FILE": str(work_dir / "id.pub"),
        "ADO_ORG": "test-org",
        "ADO_PROJECT": "test-project",
        "ADO_PAT_FILE": str(work_dir / "ado-pat"),
    }
    return _run("ci-vm.sh", work_dir, **{**inputs, **extra_env})


def test_story_1_2_ci_vm_matrix(work_dir: Path) -> None:
    """ci-vm.sh against the stateful fakes (I/O matrix rows "Re-run", "Identities not there
    yet", "VM bootstrap" errors). Covers: a re-run makes no create call and re-applies the SSH
    rule, tags and identities, takes a hand-attached Prod identity off, and hands the token to
    the VM on stdin only; a deallocated VM is started before the SSH steps; absent deploy identities are skipped with a warning naming
    state-backend.sh while the VM and Jenkins still go up; a missing input or token file stops
    before any Azure call."""
    # Re-run: everything exists.
    run_dir = _case(work_dir, "rerun")
    result, calls = _ci_vm(run_dir, FAKE_AZ_VM_IDENTITIES=f"{DEV_ON_VM}||{PROD_ON_VM}")
    assert result.returncode == 0, result.stdout + result.stderr
    az_calls = [call for call in calls if not call[0].startswith("__")]
    assert not [call for call in az_calls if "create" in call[:4]], "a re-run creates nothing"
    (rule,) = [call for call in az_calls if _starts_with(call, ["network", "nsg", "rule", "update"])]
    assert rule[rule.index("--source-address-prefixes") + 1] == "203.0.113.7/32"
    assert rule[rule.index("--destination-port-ranges") + 1] == "22"
    assert any(_starts_with(call, ["group", "update"]) and "babaloo-sea-lng-rg-23" in call for call in az_calls)
    assert len([call for call in az_calls if _starts_with(call, ["vm", "identity", "assign"])]) == 2
    (removed,) = [call for call in az_calls if _starts_with(call, ["vm", "identity", "remove"])]
    assert removed[removed.index("--identities") + 1] == PROD_ON_VM
    # Jenkins over SSH; the token only on the remote step's stdin.
    (remote,) = [call for call in _tool_calls(calls, "ssh") if "ci-vm-remote.sh" in call[-1]]
    assert remote[-1].endswith("ci-vm-remote.sh test-org test-project test-project " + " ".join([FAKE_GUID] * 2))
    assert (run_dir / "az-calls.jsonl.stdin").read_text() == CI_VM_TOKEN + "\n"
    assert CI_VM_TOKEN not in json.dumps(calls) + result.stdout + result.stderr
    assert not any(_starts_with(call, ["vm", "start"]) for call in az_calls), "a running VM is not started"
    # cloud-init's "done with recoverable errors" (exit 2) is accepted.
    (wait,) = [call for call in _tool_calls(calls, "ssh") if "cloud-init status --wait" in call[-1]]
    assert "[ $rc -eq 2 ]" in wait[-1]

    # A deallocated VM is started before the SSH steps.
    result, calls = _ci_vm(_case(work_dir, "deallocated"), FAKE_AZ_VM_POWER="PowerState/deallocated")
    assert result.returncode == 0, result.stdout + result.stderr
    start = next(i for i, call in enumerate(calls) if _starts_with(call, ["vm", "start"]))
    assert start < next(i for i, call in enumerate(calls) if call[0] == "__ssh__")

    # Identities not there yet: skipped with a warning; the VM and Jenkins still go up.
    result, calls = _ci_vm(
        _case(work_dir, "no-identities"),
        FAKE_AZ_NOT_FOUND_MATCH="identity show --name babaloo-sea-lng-id-21||identity show --name babaloo-sea-lng-id-22",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr.count("run state-backend.sh, then re-run ci-vm.sh") == 2
    assert not any(_starts_with(call, ["vm", "identity", "assign"]) for call in calls)
    (remote,) = [call for call in _tool_calls(calls, "ssh") if "ci-vm-remote.sh" in call[-1]]
    assert remote[-1].endswith(" none none")

    # A missing input or token file stops before any Azure call.
    for name, overrides in {
        "no-token": {"ADO_PAT_FILE": str(work_dir / "absent")},
        "no-ip": {"CI_SSH_SOURCE_IP": ""},
        "range": {"CI_SSH_SOURCE_IP": "10.0.0.0/8"},
    }.items():
        result, calls = _ci_vm(_case(work_dir, name), **overrides)
        assert result.returncode == 1, name
        assert calls == [], name


# --- verify-db-isolation.sh ----------------------------------------------------------------------


def test_story_1_1_verify_db_isolation(work_dir: Path) -> None:
    """verify-db-isolation.sh. Covers: cross-env connection refused reports PASS; allowed
    reports FAIL; privilege check passes when isolated; fails when dev can reach prod; a
    missing database fails the PUBLIC check."""
    cross_env = {"CONNECT_AS_LOGIN": "babaloo-sea-lng-id-22", "TARGET_DB": "invoicing_prod"}

    # Cross-env connection refused reports PASS.
    result, _ = _run("verify-db-isolation.sh", _case(work_dir, "cross-refuse"), **cross_env, FAKE_PSQL_CROSS_ENV="refuse")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS babaloo-sea-lng-id-22 refused by invoicing_prod" in result.stdout
    assert "FAIL" not in result.stdout

    # Cross-env connection allowed reports FAIL.
    result, _ = _run("verify-db-isolation.sh", _case(work_dir, "cross-allow"), **cross_env, FAKE_PSQL_CROSS_ENV="allow")
    assert result.returncode != 0
    assert "FAIL babaloo-sea-lng-id-22 connected to invoicing_prod" in result.stdout

    # Privilege check passes when isolated.
    result, _ = _run("verify-db-isolation.sh", _case(work_dir, "priv-refuse"), FAKE_PSQL_CROSS_ENV="refuse")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS babaloo-sea-lng-id-03 refused on invoicing_prod" in result.stdout
    assert "PASS babaloo-sea-lng-id-13 refused on invoicing_dev" in result.stdout
    # The per-environment loaders groups (the load-script logins) are checked too.
    assert "PASS babaloo-sea-lng-grp-01 refused on invoicing_prod" in result.stdout
    assert "PASS babaloo-sea-lng-grp-11 refused on invoicing_dev" in result.stdout
    assert "All isolation checks passed." in result.stdout

    # Privilege check fails when dev can reach prod.
    result, _ = _run("verify-db-isolation.sh", _case(work_dir, "priv-allow"), FAKE_PSQL_CROSS_ENV="allow")
    assert result.returncode == 1
    assert "FAIL babaloo-sea-lng-id-03 can CONNECT to invoicing_prod" in result.stdout

    # A missing database fails the PUBLIC check.
    result, _ = _run("verify-db-isolation.sh", _case(work_dir, "missing-db"), FAKE_PSQL_MISSING_DB="invoicing_prod")
    assert result.returncode == 1
    assert "FAIL invoicing_prod does not exist" in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_prod" not in result.stdout
    assert "PASS PUBLIC has no CONNECT on invoicing_dev" in result.stdout


# --- PGP key pair (step 4b) ----------------------------------------------------------------------


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


def test_ocr_129_pgp_step4b_runs(work_dir: Path) -> None:
    """pgp-step4b.sh runs that succeed. Covers: both secrets exist (nothing to generate, the
    staff-api grant exists); a re-run after a missed grant only grants staff-api; a new
    environment splits the pair across the vaults and then grants staff-api, and leaves no
    private key behind."""
    # Both secrets exist: nothing is generated or granted.
    run_dir = _case(work_dir, "both-exist")
    result, calls = _run("pgp-step4b.sh", run_dir, FAKE_AZ_NOT_FOUND_MATCH=ENV_PRIVATE)
    assert result.returncode == 0, result.stderr
    assert "nothing to generate" in result.stdout
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []
    assert f"exists: role 4633458b-17de-408a-b874-0445c86b69e6 for 55555555-5555-5555-5555-555555555555 at {PRIVATE_SECRET_SCOPE}" in result.stdout

    # A re-run after a missed grant only grants staff-api.
    result, calls = _run(
        "pgp-step4b.sh", _case(work_dir, "missed-grant"), FAKE_AZ_NOT_FOUND_MATCH=ENV_PRIVATE, FAKE_AZ_NO_ROLE_ASSIGNMENTS="1"
    )
    assert result.returncode == 0, result.stderr
    _assert_no_key_generation(calls)
    (grant,) = _role_creates(calls)
    assert grant[grant.index("--scope") + 1] == PRIVATE_SECRET_SCOPE

    # A new environment: split the pair, then grant staff-api.
    run_dir = _case(work_dir, "new-env")
    result, calls = _run(
        "pgp-step4b.sh", run_dir, FAKE_AZ_NOT_FOUND_MATCH="keyvault secret show", FAKE_AZ_NO_ROLE_ASSIGNMENTS="1"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    sets = [call for call in calls if _starts_with(call, ["keyvault", "secret", "set"])]
    assert [(call[call.index("--vault-name") + 1], call[call.index("--name") + 1]) for call in sets] == [
        ("babaloo-sea-lng-kv-22", "pgp-private-key"),
        ("babaloo-sea-lng-kv-01", "pgp-public-key"),
    ]
    stored = {entry["args"][entry["args"].index("--vault-name") + 1]: entry["content"] for entry in _files(run_dir)}
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


def test_ocr_129_pgp_step4b_guards(work_dir: Path) -> None:
    """pgp-step4b.sh runs that must stop without generating a key or granting a role.
    Covers: only one secret of the pair exists (public absent; private absent); a secret
    lookup error other than NotFound; the staff-api identity is missing; the private-key vault
    is missing; a legacy private key in the env vault (kv-22 copy absent; present), never
    copied."""
    # Only one secret of the pair exists.
    for label, absent in (("public-absent", ENV_PUBLIC), ("private-absent", PK_PRIVATE)):
        result, calls = _run("pgp-step4b.sh", _case(work_dir, label), FAKE_AZ_NOT_FOUND_MATCH=f"{ENV_PRIVATE}||{absent}")
        assert result.returncode == 1, label
        assert "only one of pgp-public-key (babaloo-sea-lng-kv-01) / pgp-private-key (babaloo-sea-lng-kv-22) exists" in result.stderr
        _assert_no_key_generation(calls)
        assert _role_creates(calls) == []

    # A secret lookup error (not NotFound) stops without generating.
    result, calls = _run("pgp-step4b.sh", _case(work_dir, "lookup-error"), FAKE_AZ_FAIL_MATCH="keyvault secret show")
    assert result.returncode == 1
    assert "lookup failed, and not with NotFound" in result.stderr
    _assert_no_key_generation(calls)

    # The staff-api identity is missing: stop before writing.
    result, calls = _run(
        "pgp-step4b.sh", _case(work_dir, "no-identity"), FAKE_AZ_NOT_FOUND_MATCH="identity show --name babaloo-sea-lng-id-02"
    )
    assert result.returncode == 1
    assert "staff-api identity babaloo-sea-lng-id-02 not found in babaloo-sea-lng-rg-01" in result.stderr
    assert "apply dev/foundation (AD-17 step 4) first" in result.stderr
    _assert_no_key_generation(calls)
    assert _role_creates(calls) == []

    # The private-key vault is missing.
    result, calls = _run(
        "pgp-step4b.sh", _case(work_dir, "no-pk-vault"), FAKE_AZ_NOT_FOUND_MATCH="keyvault show --name babaloo-sea-lng-kv-22"
    )
    assert result.returncode == 1
    assert "run state-backend.sh (AD-17 step 1) first" in result.stderr
    _assert_no_key_generation(calls)

    # A legacy private key in the env vault stops without copying, whether or not kv-22 has one.
    for pk_private in ("absent", "present"):
        not_found = PK_PRIVATE if pk_private == "absent" else ""
        result, calls = _run("pgp-step4b.sh", _case(work_dir, f"legacy-{pk_private}"), FAKE_AZ_NOT_FOUND_MATCH=not_found)
        assert result.returncode == 1, pk_private
        assert "pgp-private-key is in babaloo-sea-lng-kv-01" in result.stderr
        assert "Move it to babaloo-sea-lng-kv-22, then delete and purge it" in result.stderr
        _assert_no_key_generation(calls)
        assert _role_creates(calls) == []
        assert not any(_starts_with(call, ["keyvault", "secret", "download"]) for call in calls)


# --- Step 5: the loaders group's load-script rights (OCR-129) -----------------------------------

DEV_VAULT = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
    "/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
)


def test_ocr_129_database_step5_dj_rights(work_dir: Path) -> None:
    """database-step5.sh. Covers: the dev loaders group (Dj's load-script login; Dj, 2026-09-29:
    guest UPN over 63 characters) is looked up before any change and granted the two secrets
    only (hmac-key and pgp-public-key, Secrets User, as a Group), nothing deleted; an earlier
    vault-wide role is removed."""
    # Grants the loaders group two secrets only.
    result, calls = _run("database-step5.sh", _case(work_dir, "grant"), FAKE_AZ_NO_ROLE_ASSIGNMENTS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    lookup = calls.index(["ad", "group", "show", "--group", "babaloo-sea-lng-grp-01", "--query", "id", "-o", "tsv"])
    assert lookup < calls.index(["account", "get-access-token", "--resource-type", "oss-rdbms", "--query", "accessToken", "-o", "tsv"])
    assert "-v dj_login=babaloo-sea-lng-grp-01 " in result.stdout  # the psql call
    kv = [call for call in _role_creates(calls) if "Microsoft.KeyVault" in call[call.index("--scope") + 1]]
    assert sorted(call[call.index("--scope") + 1] for call in kv) == [
        f"{DEV_VAULT}/secrets/hmac-key",
        f"{DEV_VAULT}/secrets/pgp-public-key",
    ]
    assert all(call[call.index("--role") + 1] == "4633458b-17de-408a-b874-0445c86b69e6" for call in kv)
    assert all(call[call.index("--assignee-principal-type") + 1] == "Group" for call in _role_creates(calls))
    assert not any(_starts_with(call, ["role", "assignment", "delete"]) for call in calls)

    # Removes an earlier vault-wide role.
    result, calls = _run("database-step5.sh", _case(work_dir, "vault-wide"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _role_creates(calls) == []
    (delete,) = [call for call in calls if _starts_with(call, ["role", "assignment", "delete"])]
    assert delete[delete.index("--ids") + 1].startswith(f"{DEV_VAULT}/providers/Microsoft.Authorization/roleAssignments/")


# --- App registrations ----------------------------------------------------------------------------


def test_story_1_1_app_registrations(work_dir: Path) -> None:
    """app-registrations.sh. Covers: a missing app role is added keeping the existing role ids;
    existing Entra groups (loaders grp-01/grp-11, pg-admins grp-21) are kept and a member is not
    re-added; missing groups are created with the operator added; duplicate app registrations
    stop the script before any update."""
    # A missing app role is added, keeping existing ids.
    run_dir = _case(work_dir, "missing-role")
    result, calls = _run("app-registrations.sh", run_dir, FAKE_AZ_STAFF_ROLES="4")
    assert result.returncode == 0, result.stderr
    role_updates = [call for call in calls if _starts_with(call, ["ad", "app", "update"]) and "--app-roles" in call]
    assert len(role_updates) == 2  # exactly one per environment's staff-api registration
    role_files = [entry for entry in _files(run_dir) if "--app-roles" in entry["args"]]
    assert len(role_files) == 2
    for entry in role_files:
        roles = json.loads(entry["content"])
        existing = [role for role in roles if role["value"] != "goods_in"]
        added = [role for role in roles if role["value"] == "goods_in"]
        assert [role["value"] for role in existing] == ["admin", "finance", "procurement", "management"]
        assert all(role["id"] == "55555555-5555-5555-5555-555555555555" for role in existing)
        assert len(added) == 1 and added[0]["id"] != "55555555-5555-5555-5555-555555555555"
        assert added[0]["allowedMemberTypes"] == ["User"] and added[0]["isEnabled"] is True
    # Existing groups are kept, and the operator, already a member, is not re-added.
    assert not any(_starts_with(call, ["ad", "group", "create"]) for call in calls)
    assert not any(_starts_with(call, ["ad", "group", "member", "add"]) for call in calls)
    assert "postgres_entra_admin_principal_name = \"babaloo-sea-lng-grp-21\"" in result.stdout

    # Missing groups are created (security groups named by lib.sh), each with the operator
    # as a member; the pg-admins group's id and name are printed for the shared tfvars.
    result, calls = _run("app-registrations.sh", _case(work_dir, "new-groups"), FAKE_AZ_NO_GROUPS="1")
    assert result.returncode == 0, result.stderr
    creates = [call for call in calls if _starts_with(call, ["ad", "group", "create"])]
    assert [call[call.index("--display-name") + 1] for call in creates] == [
        "babaloo-sea-lng-grp-01",
        "babaloo-sea-lng-grp-11",
        "babaloo-sea-lng-grp-21",
    ]
    adds = [call for call in calls if _starts_with(call, ["ad", "group", "member", "add"])]
    assert adds == [
        ["ad", "group", "member", "add", "--group", "99999999-9999-9999-9999-999999999999",
         "--member-id", "88888888-8888-8888-8888-888888888888"]
    ] * 3
    assert 'postgres_entra_admin_object_id      = "99999999-9999-9999-9999-999999999999"' in result.stdout
    assert 'postgres_entra_admin_principal_type = "Group"' in result.stdout

    # Duplicate app registrations stop the script.
    result, calls = _run("app-registrations.sh", _case(work_dir, "duplicates"), FAKE_AZ_DUPLICATE_APPS="1")
    assert result.returncode == 1
    assert "matches 2 app registrations" in result.stderr
    assert not any(_starts_with(call, ["ad", "app", "update"]) for call in calls)
