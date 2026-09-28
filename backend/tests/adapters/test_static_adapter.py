"""Story 1.4: the SPA route, matrix rows "SPA route" and "Static asset"."""

import asyncio
import json
from pathlib import Path

import azure.functions as func
import pytest

from invoicing.adapters.http import CORRELATION_HEADER, SECURITY_HEADERS
from invoicing.adapters.static import IMMUTABLE, REVALIDATE, spa_endpoint

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
    "path", [None, "", "u", "queue/123", "invoices/0199a1b2/", "invoices/INV-1.2"]
)
def test_story_1_4_root_and_client_paths_serve_index_html_with_security_headers(
    static_dir: Path, path: str | None
) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 200
    assert response.get_body() == INDEX_HTML
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    # The shell may be cached only with revalidation, so a deploy shows at once.
    assert response.headers["Cache-Control"] == REVALIDATE == "no-cache"
    _assert_rule_25(response)
    assert CORRELATION_HEADER in response.headers


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("assets/index-abc123.js", "text/javascript; charset=utf-8"),
        ("assets/index-abc123.css", "text/css; charset=utf-8"),
        ("assets/logo-abc123.svg", "image/svg+xml"),
        ("assets/font-abc123.woff2", "font/woff2"),
        ("assets/blob-abc123.bin", "application/octet-stream"),
    ],
)
def test_story_1_4_hashed_assets_are_served_with_their_content_type(
    static_dir: Path, path: str, content_type: str
) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 200
    assert response.get_body() == (static_dir / path).read_bytes()
    assert response.headers["Content-Type"] == content_type
    assert response.headers["Cache-Control"] == IMMUTABLE
    _assert_rule_25(response)


def test_story_1_4_unhashed_files_revalidate(static_dir: Path) -> None:
    response = _get(static_dir, "robots.txt")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.headers["Cache-Control"] == REVALIDATE


@pytest.mark.parametrize(
    "path",
    [
        "../secret.py",
        "assets/../../secret.py",
        "..",
        "./index.html",
        "assets\\..\\..\\secret.py",
        "assets/%00.js",
        "index.html\x00.js",
    ],
)
def test_story_1_4_path_traversal_is_a_404(static_dir: Path, path: str) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 404
    assert b"synthetic" not in response.get_body()
    assert json.loads(response.get_body())["code"] == "NOT_FOUND"
    _assert_rule_25(response)


def test_story_1_4_a_symlink_out_of_the_static_folder_is_a_404(
    static_dir: Path,
) -> None:
    (static_dir / "assets" / "link.js").symlink_to(static_dir.parent / "secret.py")
    response = _get(static_dir, "assets/link.js")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "api",
        "api/",
        "api/unknown",
        "api/health/extra",
        "API/unknown",
        "Api/unknown",
        # Reserved by the Functions host: never SPA client routes.
        "admin",
        "admin/queue",
        "Admin/queue",
        "runtime/webhooks",
        "RUNTIME",
    ],
)
def test_story_1_4_api_and_host_reserved_paths_never_fall_through_to_the_spa(
    static_dir: Path, path: str
) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 404
    assert response.mimetype == "application/json"
    body = json.loads(response.get_body())
    assert body["code"] == "NOT_FOUND" and body["correlation_id"]
    assert response.headers["Cache-Control"] == "no-store"
    _assert_rule_25(response)


@pytest.mark.parametrize(
    "path", ["assets/missing-abc123.js", "favicon.ico", "deep/missing.png"]
)
def test_story_1_4_a_missing_file_or_a_folder_is_a_404_not_the_shell(
    static_dir: Path, path: str
) -> None:
    response = _get(static_dir, path)
    assert response.status_code == 404
    assert response.get_body() != INDEX_HTML


def test_story_1_4_an_app_deployed_without_its_spa_answers_404(tmp_path: Path) -> None:
    response = _get(tmp_path / "static", "")
    assert response.status_code == 404
    assert json.loads(response.get_body())["code"] == "NOT_FOUND"
    _assert_rule_25(response)
