"""Story 1.4: web/staff and web/supplier share their base (tokens, lint rules, API
client, a11y check, build config) as copies. This keeps the copies byte-identical, so
a fix in one app can't silently miss the other; change both, then this passes."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAFF = REPO_ROOT / "web" / "staff"
SUPPLIER = REPO_ROOT / "web" / "supplier"

# Files that must be the same in both apps. App-specific: package.json, the lock file
# (name), playwright.config.ts (port), e2e/screens.ts (each app's screens),
# src/App*.tsx, src/strings*.ts, src/main.tsx, and each app's own screens and API
# calls (e.g. the supplier page's other src/screens/, src/link*.ts, src/api/link*.ts;
# src/upload.test.ts; each app's own src/api/upload*.ts; the staff app's
# src/api/me*.ts, src/api/queue*.ts, src/api/goodsIn.ts, src/surfaces*.ts,
# src/router*.ts, src/shell/, its other screens, and the shadcn table, badge and alert
# only it uses so far, Story 2.8). Story 4.1: src/upload.ts, src/deviceCheck.ts,
# src/screens/capture.ts and src/test/fakeXhr.ts are shared (below).
# vitest.config.ts differs too: only web/supplier runs shared/quality's tests, though
# both apps use it.
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
    # Story 2.7: the staff app now uses these too.
    "src/components/ui/skeleton.tsx",
    "src/screens/usePageHeading.ts",
    "src/lib/utils.ts",
    "src/test/setup.ts",
    # Story 4.1: goods-in reuses the supplier page's file rules, device check and
    # capture button (each app keeps its own src/api/upload.ts).
    "src/upload.ts",
    "src/deviceCheck.ts",
    "src/screens/capture.ts",
    "src/test/fakeXhr.ts",
]


def test_story_1_4_web_apps_share_their_base_files_and_dependencies() -> None:
    for name in SHARED_FILES:
        staff, supplier = STAFF / name, SUPPLIER / name
        assert staff.is_file() and supplier.is_file(), f"{name} is missing from an app"
        assert staff.read_bytes() == supplier.read_bytes(), (
            f"web/staff/{name} and web/supplier/{name} differ; make the same change in both"
        )

    def deps(app: Path) -> tuple[object, object]:
        data = json.loads((app / "package.json").read_text(encoding="utf-8"))
        return data.get("dependencies"), data.get("devDependencies")

    assert deps(STAFF) == deps(SUPPLIER)
