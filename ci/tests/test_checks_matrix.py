"""Story 1.2 I/O-matrix rows for ci/checks.sh, run for real against throwaway fixture
trees under .work/ (CHECKS_ROOT points checks.sh at them). No Azure or ADO call.

Rows: lint/format failure, coverage below threshold, secret committed.
Needs uv and gitleaks on PATH, as ci/checks.sh does.
"""

from __future__ import annotations

import os
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


# --- Lint/format failure ---------------------------------------------------------------


def test_story_1_2_badly_formatted_python_fails_lint_naming_ruff(root: Path) -> None:
    _require("uv")
    backend = _backend(root)
    (backend / "src" / "invoicing" / "badly_formatted.py").write_text("def f( x ):\n    return  x\n")
    result = _checks(root, "lint")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAILED: ruff format (backend)" in result.stderr


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
