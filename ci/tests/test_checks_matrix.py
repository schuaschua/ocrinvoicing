"""Story 1.2 I/O-matrix rows for ci/checks.sh, run for real against throwaway fixture
trees under .work/ (CHECKS_ROOT points checks.sh at them). No Azure or ADO call.

Rows: lint/format failure, coverage below threshold, not scaffolded yet, secret committed.
Story 1.4 rows: web coverage floor, supplier bundle size, a11y check wiring.
Needs uv, terraform, gitleaks and npm on PATH, as ci/checks.sh does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS = REPO_ROOT / "ci" / "checks.sh"


@pytest.fixture
def root() -> Iterator[Path]:
    """An empty fixture repo root under the gitignored .work/ folder, removed afterwards."""
    path = REPO_ROOT / ".work" / "pytest-checks" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _require(tool: str) -> None:
    """Skip locally when a tool is missing; in the PR build (TF_BUILD) that is a failure."""
    if shutil.which(tool) is None:
        if os.environ.get("TF_BUILD"):
            pytest.fail(f"{tool} is not installed on the build agent (pipelines/pr.yml test job)")
        pytest.skip(f"{tool} not installed")


def _checks(root: Path, subcommand: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("TF_BUILD", "VIRTUAL_ENV")}
    env["CHECKS_ROOT"] = str(root)
    env.update(extra_env)
    return subprocess.run(
        ["bash", str(CHECKS), subcommand], env=env, capture_output=True, text=True, check=False, timeout=300
    )


def _backend(root: Path) -> Path:
    """The real backend project (pinned tools, lock file) with only its package markers
    (the __init__.py files), no other code and no tests, so each case adds its own."""
    backend = root / "backend"
    backend.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(REPO_ROOT / "backend" / name, backend / name)
    source = REPO_ROOT / "backend" / "src"
    for marker in source.rglob("__init__.py"):
        target = backend / "src" / marker.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(marker, target)
    (backend / "tests").mkdir()
    return backend


def _web_stub(root: Path) -> None:
    app = root / "web" / "staff"
    app.mkdir(parents=True)
    (app / "package.json").write_text('{ "name": "fixture-staff", "version": "0.0.0", "private": true }\n')


# --- Lint/format failure ---------------------------------------------------------------


def test_story_1_2_badly_formatted_python_fails_lint_naming_ruff(root: Path) -> None:
    _require("uv")
    backend = _backend(root)
    (backend / "src" / "invoicing" / "badly_formatted.py").write_text("def f( x ):\n    return  x\n")
    result = _checks(root, "lint")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAILED: ruff format (backend)" in result.stderr


def test_story_1_2_badly_formatted_terraform_fails_naming_terraform_fmt(root: Path) -> None:
    _require("terraform")
    stack = root / "infra" / "dev" / "foundation"
    stack.mkdir(parents=True)
    (stack / "main.tf").write_text('locals {\nname="x"\n    other =   "y"\n}\n')
    result = _checks(root, "terraform")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAILED: terraform fmt -check" in result.stderr


# --- Coverage below threshold (also: once a test file exists, the floor applies) ----------


def test_story_1_2_passing_tests_below_80_percent_coverage_fail_with_the_measured_percent(root: Path) -> None:
    _require("uv")
    backend = _backend(root)
    (backend / "src" / "invoicing" / "partly_tested.py").write_text(
        "def covered() -> int:\n    return 1\n\n\n"
        "def uncovered(x: int) -> int:\n    if x > 1:\n        return x * 2\n    if x < 0:\n        return -x\n"
        "    return 0\n"
    )
    (backend / "tests" / "test_partly_tested.py").write_text(
        "from invoicing.partly_tested import covered\n\n\ndef test_covered() -> None:\n    assert covered() == 1\n"
    )
    result = _checks(root, "test")
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "1 passed" in output
    # 4 of 13 statements and branches: the helper's 1 covered line plus invoicing/__init__.py's
    # __version__ (read by pyproject's dynamic version since Story 1.3).
    assert "Required test coverage of 80% not reached. Total coverage: 30.77%" in output
    assert "FAILED: pytest with coverage >= 80% (backend)" in result.stderr


# --- Not scaffolded yet -------------------------------------------------------------------


def test_story_1_2_no_test_files_yet_skips_the_test_checks_and_passes(root: Path) -> None:
    _backend(root)
    _web_stub(root)
    result = _checks(root, "test")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "==> pytest (backend)\nskipped: no tests yet" in result.stdout
    assert "==> vitest (web/staff)\nskipped: no tests yet" in result.stdout
    assert "FAILED" not in result.stderr


def test_story_1_2_backend_code_without_tests_fails_instead_of_skipping(root: Path) -> None:
    backend = _backend(root)
    (backend / "src" / "invoicing" / "untested.py").write_text("def f() -> int:\n    return 1\n")
    result = _checks(root, "test")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "backend/src has code but backend/tests has no test files; the 80% coverage floor applies" in result.stderr
    assert "FAILED: pytest (backend)" in result.stderr


def test_story_1_2_scaffolded_web_app_without_tests_fails_instead_of_skipping(root: Path) -> None:
    app = root / "web" / "staff"
    app.mkdir(parents=True)
    (app / "package.json").write_text('{ "name": "fixture-staff", "private": true, "scripts": { "lint": "eslint ." } }\n')
    result = _checks(root, "test")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "web/staff is scaffolded but has no test files; the 60% coverage floor applies" in result.stderr
    assert "FAILED: vitest (web/staff)" in result.stderr


# --- Secret committed -------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.test", *args],
        cwd=root, check=True, capture_output=True, text=True,
    )


def _repo_with(root: Path, content: str) -> None:
    shutil.copy2(REPO_ROOT / ".gitleaks.toml", root / ".gitleaks.toml")
    (root / "settings.py").write_text(content)
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")


def test_story_1_2_committed_secret_fails_the_secret_scan(root: Path) -> None:
    _require("gitleaks")
    # Built at run time so this test file itself holds no secret-shaped string.
    fake_token = "ghp_" + "4Rk9TzQm2LxW8vNp3HsYb7JcDf6GtUe1Aa0Z"
    _repo_with(root, f'GITHUB_TOKEN = "{fake_token}"\n')
    result = _checks(root, "secrets")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAILED: gitleaks (git history)" in result.stderr


def test_story_1_2_clean_repo_passes_the_secret_scan(root: Path) -> None:
    _require("gitleaks")
    _repo_with(root, 'GREETING = "hello"\n')
    result = _checks(root, "secrets")
    assert result.returncode == 0, result.stdout + result.stderr


# --- Story 1.4: web coverage floor, supplier bundle size, a11y wiring ---------------------

# A web app with no dependencies whose build writes DIST_JS_BYTES of incompressible
# JavaScript, so the bundle-size check runs without installing anything.
BUILD_SCRIPT = """
import { mkdirSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
mkdirSync("dist/assets", { recursive: true });
writeFileSync("dist/index.html", "<!doctype html><html lang=en></html>");
const size = Number(process.env.DIST_JS_BYTES);
writeFileSync("dist/assets/index-abc.js", "const x = '" + randomBytes(size).toString("base64") + "';");
"""


def _web_fixture(root: Path, name: str, scripts: dict[str, str], *, chromium: bool = False) -> Path:
    """With `chromium`, a local stand-in for @playwright/test whose Chromium "exists", so
    checks.sh runs the app's a11y script without a browser."""
    app = root / "web" / name
    app.mkdir(parents=True)
    package: dict[str, object] = {"name": f"fixture-{name}", "version": "0.0.0", "private": True, "scripts": scripts}
    lock: dict[str, object] = {
        "name": package["name"],
        "version": "0.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": {"name": package["name"], "version": "0.0.0"}},
    }
    if chromium:
        fake = app / "fake-playwright"
        fake.mkdir()
        (fake / "package.json").write_text('{"name": "@playwright/test", "version": "0.0.0", "main": "index.js"}\n')
        (fake / "index.js").write_text("module.exports = { chromium: { executablePath: () => __filename } };\n")
        dependencies = {"@playwright/test": "file:fake-playwright"}
        package["devDependencies"] = dependencies
        lock["packages"] = {
            "": {"name": package["name"], "version": "0.0.0", "devDependencies": dependencies},
            "fake-playwright": {"name": "@playwright/test", "version": "0.0.0", "dev": True},
            "node_modules/@playwright/test": {"resolved": "fake-playwright", "link": True},
        }
    (app / "package.json").write_text(json.dumps(package) + "\n")
    (app / "package-lock.json").write_text(json.dumps(lock) + "\n")
    (app / "build.mjs").write_text(BUILD_SCRIPT)
    return app


def test_story_1_4_web_coverage_below_60_percent_fails_naming_the_percent(root: Path) -> None:
    _require("npm")
    app = root / "web" / "staff"
    shutil.copytree(
        REPO_ROOT / "web" / "staff",
        app,
        ignore=shutil.ignore_patterns("node_modules", "dist", "coverage", "test-results", "playwright-report"),
    )
    shutil.copytree(REPO_ROOT / "shared", root / "shared")  # the @shared alias target
    # 60 functions no test calls: coverage falls well under the floor.
    (app / "src" / "untested.ts").write_text(
        "".join(
            f"export function untested{i}(x: number): number {{\n  if (x > {i}) {{\n    return x * 2;\n  }}\n  return x;\n}}\n"
            for i in range(60)
        )
    )
    result = _checks(root, "test")
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert re.search(r"Coverage for lines \(\d+(\.\d+)?%\) does not meet global threshold \(60%\)", output), output
    assert "FAILED: vitest with coverage >= 60% (web/staff)" in result.stderr


def test_story_1_4_supplier_js_over_150_kb_gzipped_fails_naming_the_size(root: Path) -> None:
    _require("npm")
    _require("uv")
    _web_fixture(root, "supplier", {"build": "node build.mjs"})
    result = _checks(root, "test", DIST_JS_BYTES=str(160 * 1024))
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    match = re.search(r"ERROR: web/supplier JavaScript is (\d+\.\d) KB gzipped, over the 150 KB limit \(UX-DR22\)", output)
    assert match and float(match.group(1)) > 150, output
    assert "FAILED: JS <= 150 KB gzipped (web/supplier)" in result.stderr


def test_story_1_4_supplier_js_within_150_kb_passes_the_size_check(root: Path) -> None:
    _require("npm")
    _require("uv")
    _web_fixture(root, "supplier", {"build": "node build.mjs"})
    result = _checks(root, "test", DIST_JS_BYTES=str(60 * 1024))
    output = result.stdout + result.stderr
    assert re.search(r"web/supplier: 1 JS file\(s\), \d+\.\d KB gzipped \(limit 150 KB\)", result.stdout), output
    assert "FAILED: JS <= 150 KB" not in result.stderr


def test_story_1_4_only_the_supplier_app_has_a_bundle_limit(root: Path) -> None:
    _require("npm")
    _web_fixture(root, "staff", {"build": "node build.mjs"})
    result = _checks(root, "test", DIST_JS_BYTES=str(400 * 1024))
    assert "KB gzipped" not in result.stdout + result.stderr


def test_story_1_4_a_web_app_without_an_a11y_script_fails(root: Path) -> None:
    _require("npm")
    _web_fixture(root, "staff", {"build": "node build.mjs"})
    result = _checks(root, "test", DIST_JS_BYTES="10")
    assert result.returncode == 1
    assert 'web/staff/package.json has no "a11y" script' in result.stderr
    assert "FAILED: a11y (web/staff)" in result.stderr


def test_story_1_4_a11y_skips_locally_without_chromium_but_never_under_tf_build(root: Path) -> None:
    _require("npm")
    # No Playwright installed in the fixture: Chromium counts as missing.
    _web_fixture(root, "staff", {"build": "node build.mjs", "a11y": "exit 0"})
    local = _checks(root, "test", DIST_JS_BYTES="10")
    assert "==> a11y (web/staff)\nskipped: Playwright's Chromium is not installed" in local.stdout
    assert "a11y" not in local.stderr

    pipeline = _checks(root, "test", DIST_JS_BYTES="10", TF_BUILD="True")
    assert pipeline.returncode == 1
    assert "FAILED: playwright install chromium (web/staff)" in pipeline.stderr


def test_story_1_4_a_failing_a11y_script_fails_the_test_check(root: Path) -> None:
    _require("npm")
    _web_fixture(root, "staff", {"build": "node build.mjs", "a11y": "echo axe found 1 violation && exit 1"}, chromium=True)
    result = _checks(root, "test", DIST_JS_BYTES="10")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "axe found 1 violation" in result.stdout
    assert "FAILED: a11y: axe WCAG 2.2 AA, 320px reflow, 48px targets (web/staff)" in result.stderr


def test_story_1_4_a_failed_npm_ci_stops_the_later_web_steps(root: Path) -> None:
    _require("npm")
    app = _web_fixture(root, "staff", {"build": "node build.mjs", "a11y": "exit 0"})
    (app / "package-lock.json").unlink()  # npm ci refuses to run without a lock file
    result = _checks(root, "test", DIST_JS_BYTES="10")
    assert result.returncode == 1
    assert "FAILED: npm ci (web/staff)" in result.stderr
    assert "vitest, build, bundle size and a11y (web/staff) not run: npm ci failed" in result.stdout
    assert "==> npm run build (web/staff)" not in result.stdout
