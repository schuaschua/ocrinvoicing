"""Story 2.7: `GET /api/me` on staff-api (AD-14), every API row of the I/O matrix,
through the app as the Functions host loads it."""

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from types import ModuleType

import azure.functions as func
import pytest

from invoicing.adapters.http import SECURITY_HEADERS
from invoicing.adapters.principal import PRINCIPAL_HEADER

pytestmark = pytest.mark.app("staff_api")

OID = "7f1c2d3e-0000-4000-8000-00000000abcd"
EMAIL = "priya@babaloo.example"


def header(*roles: str, name: str = "Priya Tan") -> str:
    claims = [
        {"typ": "name", "val": name},
        {
            "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
            "val": OID,
        },
        {"typ": "preferred_username", "val": EMAIL},
        *({"typ": "roles", "val": role} for role in roles),
    ]
    body = {"auth_typ": "aad", "role_typ": "roles", "claims": claims}
    return base64.b64encode(json.dumps(body).encode()).decode()


@pytest.fixture
def get_me(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> Callable[[dict[str, str]], func.HttpResponse]:
    module = load_app("staff_api")
    functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
    (trigger,) = [
        b.get_dict_repr()
        for b in functions["me"].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "api/me"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here
    handler = functions["me"].get_user_function()

    def call(headers: dict[str, str]) -> func.HttpResponse:
        request = func.HttpRequest(
            method="GET", url="/api/me", headers=headers, body=b""
        )
        return asyncio.run(handler(request))

    return call


def test_story_2_7_me_returns_name_and_roles_only(
    get_me: Callable[[dict[str, str]], func.HttpResponse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = get_me({PRINCIPAL_HEADER: header("finance", "admin")})
    assert response.status_code == 200
    body = json.loads(response.get_body())
    assert body == {"name": "Priya Tan", "roles": ["admin", "finance"]}
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    # No object id or email in the answer or the logs.
    for leak in (OID, EMAIL):
        assert leak not in response.get_body().decode()
        assert leak not in caplog.text


def test_story_2_7_me_with_no_known_role_returns_empty_roles(
    get_me: Callable[[dict[str, str]], func.HttpResponse],
) -> None:
    response = get_me({PRINCIPAL_HEADER: header("auditor", name="New Starter")})
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {"name": "New Starter", "roles": []}


@pytest.mark.parametrize("headers", [{}, {PRINCIPAL_HEADER: "%%%not-base64%%%"}])
def test_story_2_7_me_without_a_valid_principal_is_401(
    get_me: Callable[[dict[str, str]], func.HttpResponse], headers: dict[str, str]
) -> None:
    response = get_me(headers)
    assert response.status_code == 401
    assert json.loads(response.get_body())["code"] == "UNAUTHENTICATED"


def test_story_2_7_health_needs_no_principal(
    app_settings: dict[str, str], load_app: Callable[[str], ModuleType]
) -> None:
    module = load_app("staff_api")
    functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
    request = func.HttpRequest(method="GET", url="/api/health", headers={}, body=b"")
    response = asyncio.run(functions["health"].get_user_function()(request))
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("site", "enabled", "trusted"),
    [
        (None, None, True),  # local: no platform
        ("babaloo-sea-lng-func-02", "True", True),
        ("babaloo-sea-lng-func-02", "true", True),
        ("babaloo-sea-lng-func-02", None, False),
        ("babaloo-sea-lng-func-02", "False", False),
    ],
)
def test_story_2_7_in_azure_without_built_in_auth_every_staff_route_is_401(
    site: str | None,
    enabled: str | None,
    trusted: bool,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name, value in (("WEBSITE_SITE_NAME", site), ("WEBSITE_AUTH_ENABLED", enabled)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with caplog.at_level(logging.INFO, logger="invoicing.auth"):
        module = load_app("staff_api")
    assert module.settings.platform_auth_trusted is trusted
    disabled_logs = [
        r for r in caplog.records if r.getMessage().startswith("auth.disabled ")
    ]
    assert len(disabled_logs) == (0 if trusted else 1)
    functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
    request = func.HttpRequest(
        method="GET",
        url="/api/me",
        headers={PRINCIPAL_HEADER: header("admin")},
        body=b"",
    )
    response = asyncio.run(functions["me"].get_user_function()(request))
    if trusted:
        assert response.status_code == 200
    else:
        assert response.status_code == 401
        assert json.loads(response.get_body())["code"] == "AUTH_DISABLED"
    # Liveness stays anonymous either way.
    health = func.HttpRequest(method="GET", url="/api/health", headers={}, body=b"")
    assert (
        asyncio.run(functions["health"].get_user_function()(health)).status_code == 200
    )
