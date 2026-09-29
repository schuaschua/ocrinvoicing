"""Story 1.2: infra/bootstrap/ado-setup.sh, offline.

--dry-run runs against an `az` that fails if called (infra/scripts/tests/fake-bin);
the binding tests use the stateful fake where everything already exists. Nothing
reaches Azure or Azure DevOps.
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

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "infra" / "bootstrap" / "ado-setup.sh"
FAKE_BIN = REPO_ROOT / "infra" / "scripts" / "tests" / "fake-bin"
STATEFUL_BIN = REPO_ROOT / "infra" / "scripts" / "tests" / "fake-bin-stateful"

FAKE_INPUTS = {
    "ARM_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "ARM_TENANT_ID": "11111111-1111-1111-1111-111111111111",
    "ADO_ORG": "test-org",
    "ADO_PROJECT": "test-project",
    "ADO_APPROVER": "dj@example.test",
}
FAKE_GUID = "55555555-5555-5555-5555-555555555555"


def _env(bin_dir: Path, **overrides: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARM_", "ADO_", "FAKE_"))}
    env.update(FAKE_INPUTS)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def _dry_run(**overrides: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"], env=_env(FAKE_BIN, **overrides),
        capture_output=True, text=True, check=False, timeout=60,
    )


@pytest.fixture
def work_dir() -> Iterator[Path]:
    path = REPO_ROOT / ".work" / "pytest-ado" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _json_blocks(output: str) -> list[dict]:
    """JSON bodies printed by the dry run: one-line objects, or '{' ... '}' at column 0."""
    blocks, current = [], None
    for line in output.splitlines():
        if line.startswith("{ ") and line.endswith(" }"):
            blocks.append(json.loads(line.replace("<pipelineId-of-ocrinvoicing-deploy>", "0")))
        elif line == "{":
            current = [line]
        elif current is not None:
            current.append(line)
            if line == "}":
                blocks.append(json.loads("\n".join(current)))
                current = None
    return blocks


def test_story_1_2_service_connections_are_wif_bound_to_the_deploy_identities() -> None:
    blocks = _json_blocks(_dry_run().stdout)
    endpoints = [b for b in blocks if b.get("type") == "azurerm"]
    assert [e["name"] for e in endpoints] == ["azure-shared", "azure-dev", "azure-prod"]
    for endpoint, identity in zip(endpoints, ["id-21", "id-22", "id-23"]):
        assert endpoint["authorization"]["scheme"] == "WorkloadIdentityFederation"
        assert endpoint["authorization"]["parameters"] == {
            "tenantid": FAKE_INPUTS["ARM_TENANT_ID"],
            "serviceprincipalid": f"<clientId-of-babaloo-sea-lng-{identity}>",
        }
        assert "serviceprincipalkey" not in json.dumps(endpoint).lower()
        assert endpoint["data"]["subscriptionId"] == FAKE_INPUTS["ARM_SUBSCRIPTION_ID"]
    out = _dry_run().stdout
    for name in ("azure-shared", "azure-dev", "azure-prod"):
        assert f"subject sc://test-org/test-project/{name}" in out  # as state-backend.sh set it


def _checks_by_resource(output: str) -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    for check in (b for b in _json_blocks(output) if "resource" in b):
        kind = check["settings"].get("displayName") or check["type"]["name"]
        found.setdefault((check["resource"]["type"], check["resource"]["name"]), set()).add(kind)
    return found


def test_story_1_2_approval_on_shared_and_prod_and_exclusive_lock_on_all() -> None:
    output = _dry_run().stdout
    by_env = {name: kinds for (kind, name), kinds in _checks_by_resource(output).items() if kind == "environment"}
    assert by_env == {
        "shared": {"ExclusiveLock", "Approval", "Branch control"},
        "dev": {"ExclusiveLock", "Branch control"},
        "prod": {"ExclusiveLock", "Approval", "Branch control"},
    }
    checks = [b for b in _json_blocks(output) if "resource" in b and b["resource"]["type"] == "environment"]
    approvals = [c for c in checks if c["type"]["name"] == "Approval"]
    for approval in approvals:
        assert approval["settings"]["approvers"] == [{"id": "<identityId-of-dj@example.test>"}]
        assert approval["settings"]["requesterCannotBeApprover"] is False  # Dj merges and approves


def test_story_1_2_branch_control_allows_only_main_on_every_connection_and_environment() -> None:
    output = _dry_run().stdout
    assert {key for key, kinds in _checks_by_resource(output).items() if "Branch control" in kinds} == {
        ("endpoint", "azure-shared"), ("endpoint", "azure-dev"), ("endpoint", "azure-prod"),
        ("environment", "shared"), ("environment", "dev"), ("environment", "prod"),
    }
    for check in _json_blocks(output):
        if check.get("settings", {}).get("displayName") == "Branch control":
            assert check["type"] == {"id": "fe1de3ee-a436-41b4-bb20-f6eb4cb879a7", "name": "Task Check"}
            assert check["settings"]["definitionRef"]["id"] == "86b05a0c-73e6-4f7d-b3cf-e38f3b39a75b"
            assert check["settings"]["inputs"] == {
                "allowedBranches": "refs/heads/main",
                "ensureProtectionOfBranch": "true",
                "allowUnknownStatusBranch": "false",
            }


def _real_run(work_dir: Path, **overrides: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    log = work_dir / "az-calls.jsonl"
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=_env(STATEFUL_BIN, FAKE_AZ_LOG=str(log), **overrides),
        capture_output=True, text=True, check=False, timeout=60,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def test_story_1_2_federation_subject_other_than_the_trusted_one_stops(work_dir: Path) -> None:
    result, calls = _real_run(
        work_dir, FAKE_AZ_SC_FEDERATION="https://login.microsoftonline.com/t/v2.0|/eid1/c/pub/t/x/a/y/sc/z/azure-shared"
    )
    assert result.returncode == 1
    assert "has federation subject '/eid1/c/pub/t/x/a/y/sc/z/azure-shared'" in result.stderr
    assert "trusts 'sc://test-org/test-project/azure-shared'" in result.stderr
    assert not any(call[:2] == ["pipelines", "create"] for call in calls)


def test_story_1_2_existing_connection_with_another_binding_stops(work_dir: Path) -> None:
    result, calls = _real_run(work_dir, FAKE_AZ_SC_BINDING=f"ServicePrincipal|{FAKE_GUID}")
    assert result.returncode == 1
    assert "not WorkloadIdentityFederation" in result.stderr
    assert not any(call[:2] == ["pipelines", "create"] for call in calls)
