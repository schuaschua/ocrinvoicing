"""Story 2.4, AD-10: only the purchasing simulation touches its schema, and only the
composition code imports it. `lint-imports` (ci/checks.sh lint) enforces the imports;
these tests pin the contract, prove it fails on a violation, and check that no other
source file names the schema."""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import invoicing
from conftest import BACKEND_DIR

PACKAGE_DIR = Path(invoicing.__file__).parent
SIMULATION_DIR = PACKAGE_DIR / "adapters" / "purchasing_sim"
SCHEMA_NAME = "sim_purchasing"
CONTRACT = {
    "id": "purchasing-sim-is-private",
    "type": "protected",
    "protected_modules": ["invoicing.adapters.purchasing_sim"],
    "allowed_importers": [
        "invoicing.adapters.purchasing_factory",
        "invoicing.tools.seed_purchasing",
    ],
}


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text())


def test_story_2_4_the_import_contract_is_pinned() -> None:
    pyproject = _pyproject()
    config = pyproject["tool"]["importlinter"]
    assert config["root_package"] == "invoicing"
    (contract,) = config["contracts"]
    assert {key: contract[key] for key in CONTRACT} == CONTRACT
    # Pinned exactly, like every check tool (Story 1.2).
    dev = pyproject["dependency-groups"]["dev"]
    assert [pin for pin in dev if pin.startswith("import-linter")] == [
        "import-linter==2.15"
    ]


def test_story_2_4_no_other_source_file_names_the_schema() -> None:
    offenders = [
        str(path.relative_to(PACKAGE_DIR))
        for path in sorted(PACKAGE_DIR.rglob("*"))
        if path.is_file()
        and path.suffix != ".pyc"
        and SIMULATION_DIR not in path.parents
        and SCHEMA_NAME in path.read_text(errors="ignore")
    ]
    assert offenders == []


def _lint_imports(root: Path) -> subprocess.CompletedProcess[str]:
    lint_imports = Path(sys.executable).parent / "lint-imports"
    return subprocess.run(  # noqa: S603  # our own virtualenv's lint-imports
        [str(lint_imports), "--config", str(root / "pyproject.toml"), "--no-cache"],
        cwd=root,
        env={"PYTHONPATH": str(root), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _copy_package(tmp_path: Path) -> Path:
    shutil.copytree(
        PACKAGE_DIR,
        tmp_path / "invoicing",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(BACKEND_DIR / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def test_story_2_4_lint_imports_passes_on_the_package(tmp_path: Path) -> None:
    result = _lint_imports(_copy_package(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 kept, 0 broken" in result.stdout


def test_story_2_4_lint_imports_fails_when_another_module_imports_the_simulation(
    tmp_path: Path,
) -> None:
    root = _copy_package(tmp_path)
    (root / "invoicing" / "apps" / "sneaky.py").write_text(
        "from invoicing.adapters.purchasing_sim.adapter import PurchasingSimAdapter\n"
    )
    result = _lint_imports(root)
    assert result.returncode != 0
    assert "BROKEN" in result.stdout
    assert "invoicing.apps.sneaky" in result.stdout
