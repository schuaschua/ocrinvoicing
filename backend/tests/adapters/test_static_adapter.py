"""Story 1.4: the SPA route, matrix rows "SPA route" and "Static asset"."""

import asyncio
import json
from pathlib import Path

import azure.functions as func
import pytest

from invoicing.adapters.http import SECURITY_HEADERS
from invoicing.adapters.static import spa_endpoint

INDEX_HTML = b'<!doctype html><html lang="en"><script type="module" src="/assets/index-abc123.js"></script></html>'
RULE_25 = {
    name: value for name, value in SECURITY_HEADERS.items() if name != "Cache-Control"
}


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    """A built SPA as Vite lays it out, plus a secret beside the static folder."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_bytes(INDEX_HTML)
    (static / "assets" / "index-abc123.js").write_bytes(b"console.log(1);")
    (static / "assets" / "index-abc123.css").write_bytes(b"body{}")
    (static / "assets" / "logo-abc123.svg").write_bytes(b"<svg/>")
    (static / "assets" / "font-abc123.woff2").write_bytes(b"\x00font")
    (static / "assets" / "blob-abc123.bin").write_bytes(b"\x00\x01")
    (static / "robots.txt").write_bytes(b"User-agent: *")
    (tmp_path / "secret.py").write_text("PASSWORD = 'synthetic'\n")
    return static


def _get(static_dir: Path, path: str | None) -> func.HttpResponse:
    params = {} if path is None else {"path": path}
    request = func.HttpRequest(
        method="GET", url=f"/{path or ''}", headers={}, body=b"", route_params=params
    )
    return asyncio.run(spa_endpoint(static_dir)(request))


def _assert_rule_25(response: func.HttpResponse) -> None:
    for name, value in RULE_25.items():
        assert response.headers[name] == value, name
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "path",
    ["assets/../../secret.py"],
)
def test_story_1_4_path_traversal_is_a_404(static_dir: Path, path: str) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 404
    assert b"synthetic" not in response.get_body()
    assert json.loads(response.get_body())["code"] == "NOT_FOUND"
    _assert_rule_25(response)
