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


def test_story_2_7_me(
    get_me: Callable[[dict[str, str]], func.HttpResponse],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """GET /api/me. Covers: returns the name and roles only, with the security headers and no
    object id or email in the answer or the logs; without a valid principal (none; not base64)
    it is 401."""
    # Returns name and roles only.
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

    # Without a valid principal: 401.
    headers: dict[str, str]
    for headers in [{}, {PRINCIPAL_HEADER: "%%%not-base64%%%"}]:
        response = get_me(headers)
        assert response.status_code == 401, headers
        assert json.loads(response.get_body())["code"] == "UNAUTHENTICATED"
