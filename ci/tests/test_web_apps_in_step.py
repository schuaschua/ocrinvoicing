"""Story 1.4: web/staff and web/supplier share their base (tokens, lint rules, API
client, a11y check, build config) as copies. This keeps the copies byte-identical, so
a fix in one app can't silently miss the other; change both, then this passes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STAFF = REPO_ROOT / "web" / "staff"
SUPPLIER = REPO_ROOT / "web" / "supplier"

# Files that must be the same in both apps. App-specific: package.json, the lock file
# (name), playwright.config.ts (port), e2e/screens.ts (each app's screens),
# src/App*.tsx, src/strings*.ts, src/main.tsx, and each app's own screens and API
# calls (e.g. the supplier page's src/screens/, src/link*.ts, src/api/link*.ts and
# src/components/ui/skeleton.tsx, which only the supplier page uses so far).
SHARED_FILES = [
    ".npmrc",
    ".prettierignore",
    "components.json",
    "index.html",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "tsconfig.test.json",
    "vite.config.ts",
    "vite.config.test.ts",
    "vitest.config.ts",
    "eslint.config.js",
    "eslint.config.test.ts",
    "e2e/checks.ts",
    "e2e/checks.spec.ts",
    "e2e/a11y.spec.ts",
    "src/index.css",
    "src/tokens.test.ts",
    "src/api/client.ts",
    "src/api/client.test.ts",
    "src/api/index.ts",
    "src/components/ui/button.tsx",
    "src/components/ui/button.test.tsx",
    "src/lib/utils.ts",
    "src/test/setup.ts",
]


@pytest.mark.parametrize("name", SHARED_FILES)
def test_story_1_4_shared_web_files_are_identical_in_both_apps(name: str) -> None:
    staff, supplier = STAFF / name, SUPPLIER / name
    assert staff.is_file() and supplier.is_file(), f"{name} is missing from an app"
    assert staff.read_bytes() == supplier.read_bytes(), (
        f"web/staff/{name} and web/supplier/{name} differ; make the same change in both"
    )


def test_story_1_4_both_apps_pin_the_same_dependencies() -> None:
    def deps(app: Path) -> tuple[object, object]:
        data = json.loads((app / "package.json").read_text(encoding="utf-8"))
        return data.get("dependencies"), data.get("devDependencies")

    assert deps(STAFF) == deps(SUPPLIER)
