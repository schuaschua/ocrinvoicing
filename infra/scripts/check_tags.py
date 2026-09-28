#!/usr/bin/env python3
"""P-17 tag gate: fail a Terraform plan whose taggable Azure resources lack a required tag.

Usage:
    terraform plan -out=tfplan
    terraform show -json tfplan > plan.json
    python3 infra/scripts/check_tags.py plan.json      # or: ... | check_tags.py -

Exit codes: 0 all taggable resources carry the five tags, 1 at least one is missing
a tag or has tags only known after apply, 2 the input could not be read.

A resource is taggable when:
- it comes from the azurerm provider and its planned values have a `tags` attribute
  (azurerm only exposes `tags` on resources that Azure lets you tag), or
- it is an `azapi_resource` for a top-level ARM type (`Microsoft.X/type@version`), or
  for a child type on the TAGGABLE_AZAPI_CHILD_TYPES allow-list. Other child types
  (containers, queues, tables...) reject tags and are skipped.
Tags that are unknown until apply fail the gate: they cannot be checked.
Data sources, deletions and non-Azure providers (random, time, modtm) are skipped.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Iterable

REQUIRED_TAGS: tuple[str, ...] = (
    "owner",
    "costCentre",
    "environment",
    "application",
    "dataClassification",
)

AZURERM_PROVIDERS = {"registry.terraform.io/hashicorp/azurerm"}
AZAPI_PROVIDERS = {"registry.terraform.io/azure/azapi"}

# azapi child resource types that Azure lets you tag (compared case-insensitively).
TAGGABLE_AZAPI_CHILD_TYPES = frozenset(
    {
        "microsoft.communication/emailservices/domains",
    }
)


@dataclass(frozen=True)
class Finding:
    address: str
    missing: tuple[str, ...]
    unknown: bool = False


def _is_taggable_azapi_type(azapi_type: str) -> bool:
    """Top-level types (`Microsoft.X/type@ver`) and allow-listed child types are taggable."""
    resource_type = azapi_type.split("@", 1)[0]
    return resource_type.count("/") == 1 or resource_type.lower() in TAGGABLE_AZAPI_CHILD_TYPES


def _is_taggable(change: dict[str, Any], after: dict[str, Any]) -> bool:
    provider = str(change.get("provider_name", "")).lower()
    if provider in AZURERM_PROVIDERS:
        return "tags" in after
    if provider in AZAPI_PROVIDERS and change.get("type") == "azapi_resource":
        return _is_taggable_azapi_type(str(after.get("type", "")))
    return False


def find_missing_tags(plan: dict[str, Any]) -> list[Finding]:
    """Return one finding per taggable resource that lacks a required tag."""
    findings: list[Finding] = []
    for change in plan.get("resource_changes", []) or []:
        if change.get("mode") != "managed":
            continue
        details = change.get("change") or {}
        actions = details.get("actions") or []
        if actions == ["delete"]:
            continue
        after = details.get("after")
        if not isinstance(after, dict):
            continue
        if not _is_taggable(change, after):
            continue
        after_unknown = details.get("after_unknown") or {}
        if after_unknown.get("tags") is True:
            # Tags computed at apply time cannot be checked, so the gate fails; our
            # tags are plan-time constants (local.tags).
            findings.append(Finding(address=str(change.get("address")), missing=REQUIRED_TAGS, unknown=True))
            continue
        tags = after.get("tags") or {}
        missing = tuple(key for key in REQUIRED_TAGS if not str(tags.get(key) or "").strip())
        if missing:
            findings.append(Finding(address=str(change.get("address")), missing=missing))
    return findings


def _load(source: str) -> dict[str, Any]:
    if source == "-":
        return json.load(sys.stdin)
    with open(source, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Iterable[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] in {"-h", "--help"}:
        print("usage: check_tags.py <plan.json | ->", file=sys.stderr)
        return 2
    try:
        plan = _load(args[0])
    except (OSError, json.JSONDecodeError) as error:
        print(f"check_tags: cannot read plan JSON: {error}", file=sys.stderr)
        return 2
    findings = find_missing_tags(plan)
    for finding in findings:
        if finding.unknown:
            print(f"UNKNOWN TAGS {finding.address}: tags are only known after apply, so they cannot be checked")
        else:
            print(f"MISSING TAGS {finding.address}: {', '.join(finding.missing)}")
    if findings:
        print(f"check_tags: {len(findings)} resource(s) fail the P-17 tag gate", file=sys.stderr)
        return 1
    print("check_tags: all taggable resources carry the 5 P-17 tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
