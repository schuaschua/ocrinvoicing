"""Story 1.3: the spine's layering rules, matrix row "Domain import rule".

domain imports only the standard library and itself; ports -> domain; adapters ->
ports, domain; apps -> all. Checked by scanning every module's imports (AST).
"""

import ast
import sys
from pathlib import Path

import pytest

import invoicing

PACKAGE_DIR = Path(invoicing.__file__).parent
LAYERS = ["domain", "ports", "adapters", "apps"]
# The invoicing layers each layer may import (beyond the package root's __version__).
ALLOWED_LAYERS = {
    "domain": {"domain"},
    "ports": {"domain", "ports"},
    "adapters": {"domain", "ports", "adapters"},
    "apps": {"domain", "ports", "adapters", "apps"},
}


def _imports(source: str, module: str) -> list[str]:
    """Absolute names of every import in `source`, the code of `module`."""
    names: list[str] = []
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(
                    parts[: len(parts) - node.level + 1] + ([base] if base else [])
                )
            names.append(base)
    return names


def violations(source: str, module: str) -> list[str]:
    """Imports in `module` that break the layering rules."""
    layer = module.split(".")[1]
    problems: list[str] = []
    for name in _imports(source, module):
        top = name.split(".")[0]
        if top == "invoicing":
            parts = name.split(".")
            target = parts[1] if len(parts) > 1 else None
            if target is not None and target not in ALLOWED_LAYERS[layer]:
                problems.append(f"{module} imports {name}")
        elif (
            layer == "domain"
            and top not in sys.stdlib_module_names
            and top != "__future__"
        ):
            problems.append(
                f"{module} imports {name} (domain may use the standard library only)"
            )
    return problems


def _modules() -> list[tuple[str, Path]]:
    found = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR.parent).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        if len(parts) > 1:
            found.append((".".join(parts), path))
    return found


def test_story_1_3_the_package_follows_the_layering_rules() -> None:
    modules = _modules()
    assert {name.split(".")[1] for name, _ in modules} == set(LAYERS)
    problems = [p for name, path in modules for p in violations(path.read_text(), name)]
    assert problems == []


@pytest.mark.parametrize(
    "statement",
    [
        "import azure.functions as func",
        "from pydantic import BaseModel",
        "import sqlalchemy",
        "from requests import get",
        "import httpx",
        "import psycopg",
        "from invoicing.adapters.http import json_response",
        "from invoicing.ports.queue import QueueName",
        "from ..apps import common",
    ],
)
def test_story_1_3_domain_importing_a_framework_or_outer_layer_fails(
    statement: str,
) -> None:
    assert violations(statement, "invoicing.domain.rules") != []


def test_story_1_3_domain_may_import_the_standard_library_and_itself() -> None:
    source = "import re\nfrom decimal import Decimal\nfrom invoicing.domain.errors import ErrorCode\nfrom . import ids\n"
    assert violations(source, "invoicing.domain.rules") == []


@pytest.mark.parametrize(
    ("module", "statement"),
    [
        (
            "invoicing.ports.queue",
            "from invoicing.adapters.queue import StorageQueueSender",
        ),
        ("invoicing.ports.queue", "from invoicing.apps.common import AppSettings"),
        ("invoicing.adapters.queue", "from invoicing.apps.common import AppSettings"),
        ("invoicing.adapters.queue", "from ..apps.common import AppSettings"),
    ],
)
def test_story_1_3_inner_layers_never_import_outer_ones(
    module: str, statement: str
) -> None:
    assert violations(statement, module) != []
