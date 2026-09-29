"""A small, offline expander for the Azure DevOps YAML in pipelines/ (Story 1.2 tests).

It resolves `- template:` references and the template expressions these pipelines use
(`${{ parameters.x }}`, `${{ if eq(...) }}`/`${{ else }}`, `ne(length(...), 0)`,
`join(sep, ...)`), so the tests can check the compiled stage graph the way ADO would
see it. It supports only what pipelines/ uses and fails loudly on anything else.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINES = REPO_ROOT / "pipelines"

_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _split_args(text: str) -> list[str]:
    args, depth, current, quoted = [], 0, "", False
    for char in text:
        if char == "'" and depth == 0:
            quoted = not quoted
        if char == "," and depth == 0 and not quoted:
            args.append(current.strip())
            current = ""
            continue
        if not quoted:
            depth += char == "("
            depth -= char == ")"
        current += char
    if current.strip():
        args.append(current.strip())
    return args


def evaluate(expr: str, params: dict[str, Any]) -> Any:
    expr = expr.strip()
    if expr.startswith("parameters."):
        name = expr.removeprefix("parameters.")
        if name not in params:
            raise KeyError(f"unknown parameter {name}")
        return params[name]
    if expr.startswith("'") and expr.endswith("'"):
        return expr[1:-1]
    if expr in ("true", "false"):
        return expr == "true"
    if re.fullmatch(r"-?\d+", expr):
        return int(expr)
    match = re.fullmatch(r"(\w+)\((.*)\)", expr, re.S)
    if not match:
        raise ValueError(f"unsupported expression: {expr}")
    func, args = match.group(1), [evaluate(arg, params) for arg in _split_args(match.group(2))]
    if func == "eq":
        return _norm(args[0]) == _norm(args[1])
    if func == "ne":
        return _norm(args[0]) != _norm(args[1])
    if func == "length":
        return len(args[0])
    if func == "join":
        return args[0].join(str(item) for item in args[1])
    raise ValueError(f"unsupported function: {func}")


def _norm(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _substitute(text: str, params: dict[str, Any]) -> Any:
    whole = _EXPR.fullmatch(text)
    if whole:
        return evaluate(whole.group(1), params)
    return _EXPR.sub(lambda m: str(evaluate(m.group(1), params)), text)


def _conditional(key: str) -> tuple[str, str] | None:
    match = _EXPR.fullmatch(key)
    if not match:
        return None
    body = match.group(1)
    if body == "else":
        return ("else", "")
    if body.startswith("if "):
        return ("if", body[3:])
    if body.startswith("elseif "):
        return ("elseif", body[7:])
    return None


def expand(node: Any, params: dict[str, Any], base: Path) -> Any:
    """Expand template expressions and `template:` references below NODE."""
    if isinstance(node, str):
        return _substitute(node, params)
    if isinstance(node, list):
        out: list[Any] = []
        taken = False
        for item in node:
            if isinstance(item, dict) and len(item) == 1:
                (key, value), = item.items()
                cond = _conditional(key)
                if cond:
                    kind, test = cond
                    if kind == "if":
                        taken = bool(evaluate(test, params))
                        if taken:
                            out.extend(expand(value, params, base))
                    elif kind == "elseif":
                        if not taken and evaluate(test, params):
                            taken = True
                            out.extend(expand(value, params, base))
                    elif not taken:
                        out.extend(expand(value, params, base))
                    continue
            if isinstance(item, dict) and "template" in item:
                out.extend(_include(item, params, base))
                continue
            out.append(expand(item, params, base))
        return out
    if isinstance(node, dict):
        result: dict[str, Any] = {}
        taken = False
        for key, value in node.items():
            cond = _conditional(key)
            if cond:
                kind, test = cond
                branch = None
                if kind == "if":
                    taken = bool(evaluate(test, params))
                    branch = value if taken else None
                elif kind == "elseif":
                    if not taken and evaluate(test, params):
                        taken, branch = True, value
                elif not taken:
                    branch = value
                if branch is not None:
                    result.update(expand(branch, params, base))
                continue
            result[_substitute(key, params)] = expand(value, params, base)
        return result
    return node


def _include(item: dict[str, Any], params: dict[str, Any], base: Path) -> list[Any]:
    path = (base / _substitute(item["template"], params)).resolve()
    template = load(path)
    given = expand(item.get("parameters", {}) or {}, params, base)
    declared = {p["name"]: p for p in template.get("parameters", [])}
    unknown = set(given) - set(declared)
    if unknown:
        raise KeyError(f"{path.name}: unknown parameters {sorted(unknown)}")
    values = {}
    for name, spec in declared.items():
        if name in given:
            values[name] = given[name]
        elif "default" in spec:
            values[name] = spec["default"]
        else:
            raise KeyError(f"{path.name}: missing parameter {name}")
    body_key = next(key for key in ("stages", "jobs", "steps") if key in template)
    return expand(template[body_key], values, path.parent)


def compile_pipeline(name: str) -> dict[str, Any]:
    """The pipeline with every template and expression resolved."""
    path = PIPELINES / name
    return expand(load(path), {}, path.parent)


def steps_of(job: dict[str, Any]) -> list[dict[str, Any]]:
    if "strategy" in job:
        return job["strategy"]["runOnce"]["deploy"]["steps"]
    return job.get("steps", [])
