"""Serves a built single-page app from the Function app's `static/` folder (AD-14):
the page and its API share one origin, so there is no CORS (security.md rule 23)."""

import asyncio
from pathlib import Path
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import (
    SECURITY_HEADERS,
    Endpoint,
    http_endpoint,
)
from invoicing.domain.errors import NotFoundError

INDEX = "index.html"
# Vite writes content-hashed files here, so a file's bytes never change under its name.
HASHED_ASSETS = "assets/"

# The SPA shell may be cached only with revalidation, so a deploy is seen at once;
# hashed assets may be cached for good. API responses stay no-store (http.py).
REVALIDATE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"

# Explicit types: with nosniff (security.md rule 25) a wrong type breaks the page.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

NOT_FOUND_MESSAGE = "Not found."

# security.md rule 25 headers without the API's no-store; the handler sets
# Cache-Control per file instead.
STATIC_HEADERS = {
    name: value for name, value in SECURITY_HEADERS.items() if name != "Cache-Control"
}


# First path segments the SPA never serves. `api` is this app's API: an unknown API
# path must stay a JSON 404, or a client would parse index.html as an API answer.
# `admin` and `runtime` are reserved by the Functions host, which answers them before
# any function once routePrefix is "" (host.json), so SPA client routes must never
# start with admin/ or runtime/. Host routing ignores case, so this does too.
RESERVED_PREFIXES = frozenset({"api", "admin", "runtime"})


def _is_reserved(path: str) -> bool:
    return path.split("/", 1)[0].lower() in RESERVED_PREFIXES


def _safe_parts(path: str) -> tuple[str, ...] | None:
    """The path's segments, or None when it could leave the static folder."""
    if "\\" in path or "\x00" in path:
        return None
    parts = tuple(part for part in path.split("/") if part)
    if any(part in ("..", ".") for part in parts):
        return None
    return parts


async def _file_response(file: Path, cache_control: str) -> func.HttpResponse:
    content_type = CONTENT_TYPES.get(file.suffix.lower(), DEFAULT_CONTENT_TYPE)
    # Off the event loop (coding-style.md rule 11).
    body = await asyncio.to_thread(file.read_bytes)
    return func.HttpResponse(
        body,
        status_code=200,
        headers={"Content-Type": content_type, "Cache-Control": cache_control},
    )


def spa_endpoint(
    static_dir: Path, *, trust_caller_correlation_id: bool = True
) -> Endpoint:
    """GET handler for the catch-all route: a file under `static_dir`, or `index.html`
    for a client-side path. `/api/*`, traversal and missing assets are 404s, never the
    SPA, and so are the host-reserved `admin/*` and `runtime/*` (never use them as
    client routes). Every response carries the security headers."""

    async def spa(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        path = (req.route_params.get("path") or "").strip("/")
        if _is_reserved(path):
            raise NotFoundError(NOT_FOUND_MESSAGE)
        parts = _safe_parts(path)
        if parts is None:
            raise NotFoundError(NOT_FOUND_MESSAGE)

        root = static_dir.resolve()
        if parts:
            candidate = root.joinpath(*parts).resolve()
            # Belt and braces: symlinks must not lead out of the static folder either.
            if not candidate.is_relative_to(root):
                raise NotFoundError(NOT_FOUND_MESSAGE)
            if candidate.is_file():
                cache = (
                    IMMUTABLE
                    if path.startswith(HASHED_ASSETS) and candidate.name != INDEX
                    else REVALIDATE
                )
                return await _file_response(candidate, cache)
            # A folder, or a missing file (under assets/ or with a known static-file
            # suffix), is a 404. Any other path is a client-side route and gets the
            # shell, even with a dot in it (invoices/INV-1.2).
            if (
                candidate.is_dir()
                or path.startswith(HASHED_ASSETS)
                or Path(parts[-1]).suffix.lower() in CONTENT_TYPES
            ):
                raise NotFoundError(NOT_FOUND_MESSAGE)

        index = root / INDEX
        if not index.is_file():
            # This app was deployed without its SPA.
            raise NotFoundError(NOT_FOUND_MESSAGE)
        return await _file_response(index, REVALIDATE)

    return http_endpoint(
        spa,
        enforced_headers=STATIC_HEADERS,
        trust_caller_correlation_id=trust_caller_correlation_id,
    )
