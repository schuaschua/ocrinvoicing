"""Offline tests for infra/bootstrap: syntax, shellcheck, --dry-run and input checks.

A fake az/psql/gpg/gpgconf is put first on PATH; each exits 97 and prints
FAKE-TOOL-CALLED, so any call from a dry run fails the test. Nothing reaches Azure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO_ROOT / "infra" / "bootstrap"
FAKE_BIN = Path(__file__).resolve().parent / "fake-bin"

# macOS ships bash 3.2 as /bin/bash; the scripts must work there and on bash 5.
SHELLS = sorted({"bash", *(["/bin/bash"] if Path("/bin/bash").exists() else [])})

SCRIPTS = sorted(path.name for path in BOOTSTRAP.glob("*.sh") if path.name != "lib.sh")

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
    "ENVIRONMENT": "dev",
    "DJ_USER_UPN": "dj@example.test",
    "PG_ADMIN_USER": "pg-admins@example.test",
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


def _run(
    script: str, *args: str, shell: str = "bash", **env_overrides: str | None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shell, str(BOOTSTRAP / script), *args],
        env=_env(**env_overrides),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.parametrize("script", [*SCRIPTS, "lib.sh"])
def test_bash_syntax(script: str) -> None:
    result = subprocess.run(["bash", "-n", str(BOOTSTRAP / script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_clean() -> None:
    result = subprocess.run(
        ["shellcheck", "--external-sources", *[str(BOOTSTRAP / name) for name in [*SCRIPTS, "lib.sh"]]],
        cwd=BOOTSTRAP,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("script", SCRIPTS)
def test_dry_run_prints_plan_without_calling_tools(script: str, shell: str) -> None:
    result = _run(script, "--dry-run", shell=shell)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "FAKE-TOOL-CALLED" not in output
    assert "[dry-run]" in output


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_exits_zero(script: str) -> None:
    result = _run(script, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout


@pytest.mark.parametrize("script", SCRIPTS)
def test_unknown_argument_fails(script: str) -> None:
    result = _run(script, "--apply-everything")
    assert result.returncode == 1
    assert "unknown argument" in result.stderr


@pytest.mark.parametrize(
    ("script", "variable"),
    [
        ("state-backend.sh", "ARM_SUBSCRIPTION_ID"),
        ("state-backend.sh", "ADO_ORG"),
        ("state-backend.sh", "TAG_COST_CENTRE"),
        ("app-registrations.sh", "ARM_TENANT_ID"),
        ("budget-and-roles.sh", "ALERT_EMAIL"),
        ("rbac-step3.sh", "ARM_SUBSCRIPTION_ID"),
        ("pgp-step4b.sh", "ENVIRONMENT"),
        ("database-step5.sh", "DJ_USER_UPN"),
        ("database-step5.sh", "PG_ADMIN_USER"),
        ("verify-db-isolation.sh", "PG_ADMIN_USER"),
    ],
)
def test_missing_input_stops_before_any_change(script: str, variable: str) -> None:
    result = _run(script, "--dry-run", **{variable: None})
    assert result.returncode == 1
    assert variable in result.stderr
    assert "[dry-run] az" not in result.stdout
    assert "FAKE-TOOL-CALLED" not in result.stderr


def test_environment_must_be_dev_or_prod() -> None:
    result = _run("pgp-step4b.sh", "--dry-run", ENVIRONMENT="shared")
    assert result.returncode == 1
    assert "ENVIRONMENT must be one of: dev prod" in result.stderr


def test_state_backend_plan_matches_ad17() -> None:
    out = _run("state-backend.sh", "--dry-run").stdout
    for group in ("babaloo-sea-lng-rg-21", "babaloo-sea-lng-rg-01", "babaloo-sea-lng-rg-11", "babaloo-sea-lng-rg-22"):
        assert f"az group create --name {group} --location southeastasia" in out
    assert "environment=shared" in out and "environment=dev" in out and "environment=prod" in out
    assert "--allow-shared-key-access false" in out
    assert "--enable-versioning true" in out
    for identity in ("babaloo-sea-lng-id-21", "babaloo-sea-lng-id-22", "babaloo-sea-lng-id-23"):
        assert f"az identity create --name {identity}" in out
    assert "sc://test-org/test-project/azure-dev" in out
    assert "https://vstoken.dev.azure.com/44444444-4444-4444-4444-444444444444" in out
    # State and deploy identities live in the bootstrap-only rg-22.
    assert "az storage account create --name babaloosealngst21 --resource-group babaloo-sea-lng-rg-22" in out
    assert "az identity create --name babaloo-sea-lng-id-21 --resource-group babaloo-sea-lng-rg-22" in out
    assert "az provider register --namespace Microsoft.Storage --wait" in out
    # No deploy identity gets Contributor on rg-22: Contributor goes only to the stack groups.
    contributor_scopes = re.findall(r"--role b24988ac-6180-42a0-ab88-20f7382dd24c --scope (\S+)", out)
    assert sorted(scope.rsplit("/", 1)[1] for scope in contributor_scopes) == [
        "babaloo-sea-lng-rg-01",
        "babaloo-sea-lng-rg-11",
        "babaloo-sea-lng-rg-21",
    ]
    rg22_roles = [line for line in out.splitlines() if "role assignment create" in line and "resourceGroups/babaloo-sea-lng-rg-22" in line]
    assert rg22_roles and all("/blobServices/default/containers/" in line for line in rg22_roles)
    # Conditioned RBAC Administrator for the environment identities only.
    assert out.count("--role f58310d9-a9f6-439a-9e8d-f62e7b41a168") == 2
    assert "ServicePrincipal" in out and "--condition-version 2.0" in out


def test_rbac_step3_conditions_only_runtime_roles() -> None:
    out = _run("rbac-step3.sh", "--dry-run").stdout
    assert out.count("--role f58310d9-a9f6-439a-9e8d-f62e7b41a168") == 4
    assert "a97b65f3-24c7-4388-baec-2e87135dc908" in out  # Cognitive Services User
    assert "Microsoft.CognitiveServices/accounts/babaloo-sea-lng-di-21" in out
    assert "Microsoft.Communication/communicationServices/babaloo-sea-lng-acs-21" in out


def test_database_step5_targets_own_database() -> None:
    out = _run("database-step5.sh", "--dry-run", ENVIRONMENT="prod").stdout
    assert "env_db=invoicing_prod" in out and "other_db=invoicing_dev" in out
    assert "pipeline_login=babaloo-sea-lng-id-13" in out
    assert "deploy_login=babaloo-sea-lng-id-23" in out
    assert "sslmode=require" in out


def test_verify_db_isolation_connect_mode() -> None:
    result = _run(
        "verify-db-isolation.sh",
        "--dry-run",
        CONNECT_AS_LOGIN="babaloo-sea-lng-id-22",
        TARGET_DB="invoicing_prod",
        PG_ADMIN_USER=None,
    )
    assert result.returncode == 0, result.stderr
    assert "dbname=invoicing_prod user=babaloo-sea-lng-id-22" in result.stdout


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


def test_state_backend_rbac_condition_allows_only_runtime_roles_for_service_principals() -> None:
    conditions = _conditions(_run("state-backend.sh", "--dry-run").stdout)
    assert len(conditions) == 2  # dev and prod deploy identities
    for condition in conditions:
        _assert_condition_shape(condition, ENV_RUNTIME_ROLES)


def test_rbac_step3_conditions_allow_only_the_shared_resource_roles() -> None:
    conditions = _conditions(_run("rbac-step3.sh", "--dry-run").stdout)
    assert len(conditions) == 4  # DI and ACS for dev and prod
    di_conditions = [c for c in conditions if "a97b65f3-24c7-4388-baec-2e87135dc908" in c]
    acs_conditions = [c for c in conditions if "<roleId-of-ACS Email Sender>" in c]
    assert len(di_conditions) == 2 and len(acs_conditions) == 2
    for condition in di_conditions:
        _assert_condition_shape(condition, {"a97b65f3-24c7-4388-baec-2e87135dc908"})
    for condition in acs_conditions:
        _assert_condition_shape(condition, {"<roleId-of-ACS Email Sender>"})


# --- Subscription budget and ACS Email Sender content ----------------------------------


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


def test_budget_and_role_content() -> None:
    result = _run("budget-and-roles.sh", "--dry-run")
    assert result.returncode == 0, result.stderr
    role, budget = _json_blocks(result.stdout)

    assert role["Name"] == "ACS Email Sender" and role["IsCustom"] is True
    assert role["Actions"] == [
        "Microsoft.Communication/CommunicationServices/Read",
        "Microsoft.Communication/EmailServices/write",
    ]
    assert role["DataActions"] == [] and role["NotActions"] == []
    assert role["AssignableScopes"] == ["/subscriptions/00000000-0000-0000-0000-000000000000"]

    properties = budget["properties"]
    assert properties["amount"] == 8 and properties["timeGrain"] == "Monthly" and properties["category"] == "Cost"
    assert re.fullmatch(r"\d{4}-\d{2}-01T00:00:00Z", properties["timePeriod"]["startDate"])
    (notification,) = properties["notifications"].values()
    assert notification["contactEmails"] == ["alerts@example.test"]
    assert notification["threshold"] == 100 and notification["thresholdType"] == "Actual"
    assert "Microsoft.Consumption/budgets/babaloo-sea-lng-budget-22?" in result.stdout


# --- Separate PostgreSQL admin ---------------------------------------------------------


def test_database_step5_refuses_the_load_script_user_as_admin() -> None:
    result = _run("database-step5.sh", "--dry-run", PG_ADMIN_USER="dj@example.test")
    assert result.returncode == 1
    assert "PG_ADMIN_USER must be a separate principal from DJ_USER_UPN" in result.stderr
    assert "[dry-run] psql" not in result.stdout


# --- lib.sh names agree with infra/modules/naming ---------------------------------------


def test_lib_names_match_the_naming_module() -> None:
    """Same values as infra/modules/naming/tests and the root tests expect."""
    script = """
source "$1/lib.sh"
printf '%s\\n' \
  "$(key_vault_name dev)" "$(key_vault_name prod)" \
  "$(env_storage_name dev)" "$(env_storage_name prod)" \
  "$(rg_name dev)" "$(rg_name prod)" "$(rg_name shared)" "$STATE_RG" "$STATE_ACCOUNT" \
  "$(app_identity_name dev supplier-api)" "$(app_identity_name dev accounts-sim)" \
  "$(app_identity_name prod pipeline)" \
  "$(deploy_identity_name shared)" "$(deploy_identity_name dev)" "$(deploy_identity_name prod)" \
  "$(postgres_server_name)" "$(document_intelligence_name)" "$(communication_service_name)"
"""
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(BOOTSTRAP)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "babaloo-sea-lng-kv-01",
        "babaloo-sea-lng-kv-11",
        "babaloosealngst01",
        "babaloosealngst11",
        "babaloo-sea-lng-rg-01",
        "babaloo-sea-lng-rg-11",
        "babaloo-sea-lng-rg-21",
        "babaloo-sea-lng-rg-22",
        "babaloosealngst21",
        "babaloo-sea-lng-id-01",
        "babaloo-sea-lng-id-04",
        "babaloo-sea-lng-id-13",
        "babaloo-sea-lng-id-21",
        "babaloo-sea-lng-id-22",
        "babaloo-sea-lng-id-23",
        "babaloo-sea-lng-psql-21",
        "babaloo-sea-lng-di-21",
        "babaloo-sea-lng-acs-21",
    ]
