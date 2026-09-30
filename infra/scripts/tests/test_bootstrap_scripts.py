"""Offline tests for infra/bootstrap: the security content of each --dry-run plan.

A fake az/psql/gpg/gpgconf/ssh/scp is put first on PATH; each exits 97 and prints
FAKE-TOOL-CALLED, so any call from a dry run fails the test. Nothing reaches Azure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO_ROOT / "infra" / "bootstrap"
FAKE_BIN = Path(__file__).resolve().parent / "fake-bin"

FAKE_INPUTS = {
    "ARM_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "ARM_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "TAG_OWNER": "test-owner",
    "TAG_COST_CENTRE": "test-cc",
    "TAG_APPLICATION": "test-app",
    "TAG_DATA_CLASSIFICATION": "test-class",
    "ENVIRONMENT": "dev",
    "PG_ADMIN_USER": "babaloo-sea-lng-grp-21",
}


def _env(**overrides: str | None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ARM_", "TAG_", "ADO_"))}
    env.pop("CONNECT_AS_LOGIN", None)
    env.update(FAKE_INPUTS)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env["PATH"] = f"{FAKE_BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(script: str, *args: str, **env_overrides: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BOOTSTRAP / script), *args],
        env=_env(**env_overrides),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


# --- OCR-129: the PGP private key lives in a private-key vault only staff-api reads ------

KV_SECRETS_USER = "4633458b-17de-408a-b874-0445c86b69e6"
KV_SECRETS_OFFICER = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
RG22 = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-22"


def _role_creates(out: str) -> list[str]:
    return [line for line in out.splitlines() if "az role assignment create" in line]


# --- RBAC Administrator condition content --------------------------------------------

OWNER = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
USER_ACCESS_ADMIN = "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9"
RBAC_ADMIN = "f58310d9-a9f6-439a-9e8d-f62e7b41a168"
ENV_RUNTIME_ROLES = {
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe",  # Storage Blob Data Contributor
    "b7e6dc6d-f1e8-4753-8033-0f276bb0955b",  # Storage Blob Data Owner
    "974c5e8b-45b9-4653-ba55-5f855dd0fb88",  # Storage Queue Data Contributor
    "c6a89b2d-59bc-44d0-9896-0f6e12d7b80a",  # Storage Queue Data Message Sender
    "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3",  # Storage Table Data Contributor
    "4633458b-17de-408a-b874-0445c86b69e6",  # Key Vault Secrets User
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",  # Key Vault Secrets Officer
    "3913510d-42f4-4e42-8a64-420c390055eb",  # Monitoring Metrics Publisher
}


def _conditions(output: str) -> list[str]:
    """The --condition values of the planned role assignments, unquoted."""
    found = []
    for line in output.splitlines():
        if "--condition " not in line:
            continue
        start = line.index("--condition ") + len("--condition ")
        end = line.index(" --condition-version")
        found.append(line[start:end].strip("'").replace("'\\''", "'"))
    return found


def _assert_condition_shape(condition: str, expected_roles: set[str]) -> None:
    assert "ActionMatches{'Microsoft.Authorization/roleAssignments/write'}" in condition
    assert "ActionMatches{'Microsoft.Authorization/roleAssignments/delete'}" in condition
    for side in ("@Request", "@Resource"):
        assert (
            f"{side}[Microsoft.Authorization/roleAssignments:PrincipalType] "
            "ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'}"
        ) in condition
    role_sets = re.findall(r"RoleDefinitionId\] ForAnyOfAnyValues:GuidEquals \{([^}]*)\}", condition)
    assert len(role_sets) == 2, "one role list for write and one for delete"
    for role_set in role_sets:
        assert {role.strip() for role in role_set.split(",")} == expected_roles
    for forbidden in (OWNER, USER_ACCESS_ADMIN, RBAC_ADMIN):
        assert forbidden not in condition


def _json_blocks(output: str) -> list[dict]:
    """JSON documents printed by a dry run (lines from '{' to '}' at column 0)."""
    blocks, current = [], None
    for line in output.splitlines():
        if line == "{":
            current = [line]
        elif current is not None:
            current.append(line)
            if line == "}":
                blocks.append(json.loads("\n".join(current)))
                current = None
    return blocks


def _state_backend_dry_run_plan() -> None:
    """state-backend.sh --dry-run (AD-17, OCR-129). Covers, in order:
    plan matches AD-17 (no federated credentials, state containers in stdjtfstatesea, rg-22 deploy identities,
    Contributor only on stack groups, conditioned RBAC Administrator); OCR-129 private-key
    vaults kv-22/kv-23 created in rg-22; nobody gets a role on those vaults or rg-22 in step 1;
    no RBAC Administrator reaches rg-22; RBAC Administrator conditions allow only runtime roles
    for service principals.
    """
    out = _run("state-backend.sh", "--dry-run").stdout

    # plan matches AD-17
    # Dj, 2026-09-29: the CI VM carries the deploy identities; no federated credential exists.
    assert "federated-credential" not in out
    # State goes in Dj's existing stdjtfstatesea (Dj, 2026-09-30): containers only, the
    # account is never created or changed. Deploy identities live in the bootstrap-only rg-22.
    assert "az storage account create" not in out
    assert "az storage account update" not in out
    for owner in ("shared", "dev", "prod"):
        assert (
            f"az storage container-rm create --storage-account stdjtfstatesea "
            f"--resource-group rg-tfstate-sea --name ocrinvoicing-{owner}"
        ) in out
    assert "az identity create --name babaloo-sea-lng-id-21 --resource-group babaloo-sea-lng-rg-22" in out
    # No deploy identity gets Contributor on rg-22: Contributor goes only to the stack groups.
    contributor_scopes = re.findall(r"--role b24988ac-6180-42a0-ab88-20f7382dd24c --scope (\S+)", out)
    assert sorted(scope.rsplit("/", 1)[1] for scope in contributor_scopes) == [
        "babaloo-sea-lng-rg-01",
        "babaloo-sea-lng-rg-11",
        "babaloo-sea-lng-rg-21",
    ]
    # Conditioned RBAC Administrator for the environment identities only.
    assert out.count("--role f58310d9-a9f6-439a-9e8d-f62e7b41a168") == 2
    assert "ServicePrincipal" in out and "--condition-version 2.0" in out

    # OCR-129: the private-key vaults are created in rg-22
    for vault in ("babaloo-sea-lng-kv-22", "babaloo-sea-lng-kv-23"):
        (create,) = [line for line in out.splitlines() if f"az keyvault create --name {vault} " in line]
        assert "--resource-group babaloo-sea-lng-rg-22" in create
        assert "--enable-rbac-authorization true" in create
        assert "--enable-purge-protection true" in create and "--retention-days 7" in create
        assert "--public-network-access Enabled" in create

    # OCR-129: nobody gets a role on the private-key vaults or rg-22 in step 1
    creates = _role_creates(out)
    assert creates
    assert not any("babaloo-sea-lng-kv-22" in line or "babaloo-sea-lng-kv-23" in line for line in creates)
    # Nothing in rg-22 gets a role; the state roles are scoped to this project's containers
    # in stdjtfstatesea, never to the account or its group.
    assert not any(f"--scope {RG22}" in line for line in creates)
    state = [line for line in creates if "/resourceGroups/rg-tfstate-sea" in line]
    assert len(state) == 5  # Contributor on each own container, Reader on shared for dev and prod
    assert all(
        re.search(r"/storageAccounts/stdjtfstatesea/blobServices/default/containers/ocrinvoicing-(shared|dev|prod)(\s|$)", line)
        for line in state
    )

    # OCR-129: no RBAC Administrator reaches rg-22; the env deploy identities' conditioned
    # RBAC Administrator is on their own group only.
    scopes = _rbac_admin_scopes(out)
    assert not any("babaloo-sea-lng-rg-22" in scope for scope in scopes)
    assert sorted(scopes) == [
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01",
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-11",
    ]

    # RBAC Administrator condition allows only runtime roles for service principals
    conditions = _conditions(out)
    assert len(conditions) == 2  # dev and prod deploy identities
    for condition in conditions:
        _assert_condition_shape(condition, ENV_RUNTIME_ROLES)


def _rbac_admin_scopes(out: str) -> list[str]:
    admin = [line for line in _role_creates(out) if f"--role {RBAC_ADMIN}" in line]
    assert admin
    return [re.search(r"--scope (\S+)", line).group(1) for line in admin]


def _rbac_step3_dry_run_plan() -> None:
    """rbac-step3.sh --dry-run. Covers: conditions only on runtime roles (2 conditioned RBAC
    Administrator grants, Cognitive Services User on DI, no ACS scope until Story 5.2);
    OCR-129 no RBAC Administrator reaches rg-22; conditions allow only the DI role.
    """
    out = _run("rbac-step3.sh", "--dry-run").stdout

    # conditions only on runtime roles
    assert out.count("--role f58310d9-a9f6-439a-9e8d-f62e7b41a168") == 2
    assert "a97b65f3-24c7-4388-baec-2e87135dc908" in out  # Cognitive Services User
    assert "Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21" in out
    assert "Microsoft.Communication" not in out  # Dj, 2026-09-30: ACS comes with Story 5.2

    # OCR-129: no RBAC Administrator reaches rg-22
    assert not any("babaloo-sea-lng-rg-22" in scope for scope in _rbac_admin_scopes(out))

    # conditions allow only the DI runtime role
    conditions = _conditions(out)
    assert len(conditions) == 2  # DI for dev and prod
    for condition in conditions:
        _assert_condition_shape(condition, {"a97b65f3-24c7-4388-baec-2e87135dc908"})


PGP_ENVIRONMENTS = [
    ("dev", "babaloo-sea-lng-kv-01", "babaloo-sea-lng-kv-22", "babaloo-sea-lng-id-02", "babaloo-sea-lng-rg-01"),
    ("prod", "babaloo-sea-lng-kv-11", "babaloo-sea-lng-kv-23", "babaloo-sea-lng-id-12", "babaloo-sea-lng-rg-11"),
]


def _pgp_step4b_splits_the_pair_and_grants_only_staff_api() -> None:
    """pgp-step4b.sh --dry-run, for dev and then prod: the private key goes to the private-key
    vault first, the public key to the env vault, and only staff-api is granted, on the
    private-key secret, after its identity is looked up in the env group."""
    for environment, env_vault, pk_vault, staff_identity, env_rg in PGP_ENVIRONMENTS:
        result = _run("pgp-step4b.sh", "--dry-run", ENVIRONMENT=environment)
        assert result.returncode == 0, (environment, result.stderr)
        out = result.stdout
        sets = [line for line in out.splitlines() if "az keyvault secret set" in line]
        assert len(sets) == 2, environment
        assert f"--vault-name {pk_vault} --name pgp-private-key" in sets[0]  # private first
        assert f"--vault-name {env_vault} --name pgp-public-key" in sets[1]
        (grant,) = _role_creates(out)
        assert f"--assignee-object-id '<principalId-of-{staff_identity}>'" in grant
        assert f"--role {KV_SECRETS_USER}" in grant and "--assignee-principal-type ServicePrincipal" in grant
        assert grant.endswith(f"--scope {RG22}/providers/Microsoft.KeyVault/vaults/{pk_vault}/secrets/pgp-private-key")
        # The identity is looked up in the environment's group, before any write.
        assert f"az identity show --name {staff_identity} --resource-group {env_rg}" in result.stderr
        assert out.index("az keyvault secret set") > out.index("==> Check existing secrets")


def _database_step5_dry_run_plan() -> None:
    """database-step5.sh --dry-run. Covers: OCR-129 the dev loaders group (Dj's load-script
    login) gets two secrets and no vault-wide role; the prod run targets its own database with
    the prod logins, including its loaders group, over TLS; the loaders group is refused as the
    PostgreSQL admin."""
    # OCR-129: the loaders group gets two secrets and no vault-wide role
    result = _run("database-step5.sh", "--dry-run")
    assert result.returncode == 0, result.stderr
    vault = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/babaloo-sea-lng-rg-01"
        "/providers/Microsoft.KeyVault/vaults/babaloo-sea-lng-kv-01"
    )
    kv_grants = [line for line in _role_creates(result.stdout) if KV_SECRETS_USER in line or KV_SECRETS_OFFICER in line]
    assert sorted(line.rsplit("--scope ", 1)[1] for line in kv_grants) == [
        f"{vault}/secrets/hmac-key",
        f"{vault}/secrets/pgp-public-key",
    ]
    assert all("--assignee-principal-type Group" in line for line in kv_grants)
    assert all("--assignee-object-id '<objectId-of-babaloo-sea-lng-grp-01>'" in line for line in kv_grants)
    assert "dj_login=babaloo-sea-lng-grp-01" in result.stdout
    assert "kv-22" not in result.stdout and "kv-23" not in result.stdout

    # targets its own database (prod)
    out = _run("database-step5.sh", "--dry-run", ENVIRONMENT="prod").stdout
    assert "env_db=invoicing_prod" in out and "other_db=invoicing_dev" in out
    assert "pipeline_login=babaloo-sea-lng-id-13" in out
    assert "deploy_login=babaloo-sea-lng-id-23" in out
    assert "dj_login=babaloo-sea-lng-grp-11" in out
    assert "sslmode=require" in out

    # a separate PostgreSQL admin: the loaders group is refused
    result = _run("database-step5.sh", "--dry-run", PG_ADMIN_USER="babaloo-sea-lng-grp-01")
    assert result.returncode == 1
    assert "PG_ADMIN_USER must be a separate principal from babaloo-sea-lng-grp-01" in result.stderr
    assert "[dry-run] psql" not in result.stdout


def _verify_db_isolation_connect_mode() -> None:
    result = _run(
        "verify-db-isolation.sh",
        "--dry-run",
        CONNECT_AS_LOGIN="babaloo-sea-lng-id-22",
        TARGET_DB="invoicing_prod",
        PG_ADMIN_USER=None,
    )
    assert result.returncode == 0, result.stderr
    assert "dbname=invoicing_prod user=babaloo-sea-lng-id-22" in result.stdout


def _acs_email_sender_role_content() -> None:
    result = _run("budget-and-roles.sh", "--dry-run")
    assert result.returncode == 0, result.stderr
    role = _json_blocks(result.stdout)[0]

    assert role["Name"] == "ACS Email Sender" and role["IsCustom"] is True
    assert role["Actions"] == [
        "Microsoft.Communication/CommunicationServices/Read",
        "Microsoft.Communication/EmailServices/write",
    ]
    assert role["DataActions"] == [] and role["NotActions"] == []
    assert role["AssignableScopes"] == ["/subscriptions/00000000-0000-0000-0000-000000000000"]


# --- Story 1.2: the CI VM (AD-17 step 1c) -------------------------------------------------

CI_VM_TOKEN = "fake-ado-token-never-logged"


def test_story_1_2_ci_vm_dry_run_plan() -> None:
    """ci-vm.sh --dry-run (I/O matrix "VM bootstrap"). Covers: tagged rg-23; the NSG's only
    rule allows SSH from the operator's IP; an Ubuntu LTS B2s with SSH keys only and no
    auto-shutdown; only the shared and Dev deploy identities are attached; Jenkins goes up
    over SSH with the token on stdin, never in the output; an address range is refused."""
    scratch = REPO_ROOT / ".work" / "pytest-bootstrap" / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    try:
        (scratch / "id.pub").write_text("ssh-ed25519 AAAAfake operator@test\n")
        (scratch / "ado-pat").write_text(CI_VM_TOKEN + "\n")
        inputs = {
            "CI_SSH_SOURCE_IP": "203.0.113.7",
            "CI_SSH_PUBLIC_KEY_FILE": str(scratch / "id.pub"),
            "ADO_ORG": "test-org",
            "ADO_PROJECT": "test-project",
            "ADO_PAT_FILE": str(scratch / "ado-pat"),
        }
        result = _run("ci-vm.sh", "--dry-run", **inputs)
        assert result.returncode == 0, result.stderr
        out = result.stdout
        lines = out.splitlines()

        # Tagged rg-23, environment shared.
        (group,) = [line for line in lines if "az group create" in line]
        assert "--name babaloo-sea-lng-rg-23" in group and "environment=shared" in group

        # The only NSG rule: SSH (22) from the operator's IP, nothing else inbound.
        (rule,) = [line for line in lines if "az network nsg rule" in line]
        assert "--source-address-prefixes 203.0.113.7/32" in rule
        assert "--destination-port-ranges 22" in rule and "--access Allow" in rule
        assert not re.search(r"\b(8080|443|80)\b", " ".join(line for line in lines if "nsg" in line))

        # An Ubuntu LTS B2s with SSH keys only and no auto-shutdown.
        (vm,) = [line for line in lines if "az vm create" in line]
        assert "--size Standard_B2s" in vm and "ubuntu-24_04-lts" in vm
        assert "--authentication-type ssh" in vm and "--admin-password" not in vm
        assert "auto-shutdown" not in out

        # Only the shared and Dev deploy identities are attached.
        assigns = [line for line in lines if "az vm identity assign" in line]
        assert [re.search(r"<id-of-(\S+)>", line).group(1) for line in assigns] == [
            "babaloo-sea-lng-id-21",
            "babaloo-sea-lng-id-22",
        ]
        assert "babaloo-sea-lng-id-23" not in " ".join(assigns)

        # Jenkins over SSH; the token never appears.
        (remote,) = [line for line in lines if "ci-vm-remote.sh test-org" in line]
        assert remote.startswith("[dry-run] ssh ")
        assert re.search(r"clientId-of-babaloo-sea-lng-id-21.+clientId-of-babaloo-sea-lng-id-22", remote)
        assert CI_VM_TOKEN not in out + result.stderr

        # An address range is refused before anything is planned.
        result = _run("ci-vm.sh", "--dry-run", **{**inputs, "CI_SSH_SOURCE_IP": "0.0.0.0/0"})
        assert result.returncode == 1
        assert "must be one IPv4 address" in result.stderr
        assert "[dry-run]" not in result.stdout
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# --- lib.sh names agree with infra/modules/naming ---------------------------------------


def _lib_names_match_the_naming_module() -> None:
    """Same values as infra/modules/naming/tests and the root tests expect."""
    script = """
source "$1/lib.sh"
printf '%s\\n' \
  "$(key_vault_name dev)" "$(key_vault_name prod)" \
  "$(private_key_vault_name dev)" "$(private_key_vault_name prod)" \
  "$(env_storage_name dev)" "$(env_storage_name prod)" \
  "$(rg_name dev)" "$(rg_name prod)" "$(rg_name shared)" "$STATE_RG" "$(state_container_name dev)" \
  "$(app_identity_name dev supplier-api)" "$(app_identity_name dev accounts-sim)" \
  "$(app_identity_name prod pipeline)" \
  "$(deploy_identity_name shared)" "$(deploy_identity_name dev)" "$(deploy_identity_name prod)" \
  "$(postgres_server_name)" "$(document_intelligence_name)" \
  "$(action_group_name shared)" "$(action_group_name dev)" "$(action_group_name prod)" \
  "$(loaders_group_name dev)" "$(loaders_group_name prod)" "$(pg_admins_group_name)"
"""
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(BOOTSTRAP)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "babaloo-sea-lng-kv-01",
        "babaloo-sea-lng-kv-11",
        "babaloo-sea-lng-kv-22",
        "babaloo-sea-lng-kv-23",
        "babaloosealngst01",
        "babaloosealngst11",
        "babaloo-sea-lng-rg-01",
        "babaloo-sea-lng-rg-11",
        "babaloo-sea-lng-rg-21",
        "babaloo-sea-lng-rg-22",
        "ocrinvoicing-dev",
        "babaloo-sea-lng-id-01",
        "babaloo-sea-lng-id-04",
        "babaloo-sea-lng-id-13",
        "babaloo-sea-lng-id-21",
        "babaloo-sea-lng-id-22",
        "babaloo-sea-lng-id-23",
        "babaloo-sea-lng-psql-21",
        "babaloo-sea-lng-di-21",
        "babaloo-sea-lng-ag-21",
        "babaloo-sea-lng-ag-01",
        "babaloo-sea-lng-ag-11",
        # Entra groups (lib.sh only; not Azure resources, so not in the naming module).
        "babaloo-sea-lng-grp-01",
        "babaloo-sea-lng-grp-11",
        "babaloo-sea-lng-grp-21",
    ]


def test_story_1_1_bootstrap_dry_run_plans() -> None:
    """Story 1.1 bootstrap --dry-run plans, merged under the test cap: state-backend.sh, rbac-step3.sh,
    verify-db-isolation.sh connect mode, the ACS Email Sender role, and lib.sh names."""
    _state_backend_dry_run_plan()
    _rbac_step3_dry_run_plan()
    _verify_db_isolation_connect_mode()
    _acs_email_sender_role_content()
    _lib_names_match_the_naming_module()


def test_ocr_129_pgp_and_database_dry_run_plans() -> None:
    """OCR-129 --dry-run plans, merged under the test cap: pgp-step4b.sh and database-step5.sh."""
    _pgp_step4b_splits_the_pair_and_grants_only_staff_api()
    _database_step5_dry_run_plan()
