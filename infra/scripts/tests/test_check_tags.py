"""Tests for the P-17 tag gate (infra/scripts/check_tags.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_tags  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_all_tagged_plan_passes() -> None:
    assert check_tags.find_missing_tags(_load("plan_pass.json")) == []


def test_missing_and_empty_tags_are_reported_per_resource() -> None:
    findings = check_tags.find_missing_tags(_load("plan_missing.json"))
    by_address = {finding.address: finding.missing for finding in findings}
    assert by_address == {
        "azurerm_monitor_action_group.this": ("costCentre", "dataClassification"),
        "module.shared.azapi_resource.email": check_tags.REQUIRED_TAGS,
    }


@pytest.mark.parametrize(
    ("azapi_type", "expected"),
    [
        ("Microsoft.Storage/storageAccounts@2023-05-01", True),
        ("Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01", False),
        ("Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01", False),
        ("Microsoft.Communication/emailServices/domains@2025-05-01", True),
        ("microsoft.communication/EMAILSERVICES/domains@2025-05-01", True),
    ],
)
def test_azapi_taggable_types(azapi_type: str, expected: bool) -> None:
    assert check_tags._is_taggable_azapi_type(azapi_type) is expected


def test_allow_listed_child_type_is_checked_and_unknown_tags_fail() -> None:
    findings = check_tags.find_missing_tags(_load("plan_child_and_unknown.json"))
    by_address = {finding.address: finding for finding in findings}
    assert set(by_address) == {
        'module.email.module.domain["custom"].azapi_resource.this',
        "azurerm_key_vault.this",
    }
    domain = by_address['module.email.module.domain["custom"].azapi_resource.this']
    assert domain.missing == ("costCentre", "application", "dataClassification") and not domain.unknown
    assert by_address["azurerm_key_vault.this"].unknown is True


def test_cli_reports_unknown_tags_distinctly() -> None:
    result = _run_cli(str(FIXTURES / "plan_child_and_unknown.json"))
    assert result.returncode == 1
    assert "UNKNOWN TAGS azurerm_key_vault.this: tags are only known after apply" in result.stdout
    assert 'MISSING TAGS module.email.module.domain["custom"].azapi_resource.this' in result.stdout


def _run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_tags.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes() -> None:
    passing = _run_cli(str(FIXTURES / "plan_pass.json"))
    assert passing.returncode == 0, passing.stderr

    failing = _run_cli(str(FIXTURES / "plan_missing.json"))
    assert failing.returncode == 1
    assert "azurerm_monitor_action_group.this: costCentre, dataClassification" in failing.stdout

    from_stdin = _run_cli("-", stdin=(FIXTURES / "plan_missing.json").read_text(encoding="utf-8"))
    assert from_stdin.returncode == 1

    unreadable = _run_cli(str(FIXTURES / "does-not-exist.json"))
    assert unreadable.returncode == 2

    no_args = _run_cli()
    assert no_args.returncode == 2
