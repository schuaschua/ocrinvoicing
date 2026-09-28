"""Story 2.7: the built-in auth principal header (AD-14), rows "No principal",
"Malformed principal" and "Role guard", and the staff endpoint wrapper."""

import asyncio
import base64
import json
import logging
from uuid import UUID

import azure.functions as func
import pytest

from invoicing.adapters import principal as principal_module
from invoicing.adapters.http import CORRELATION_HEADER, json_response
from invoicing.adapters.logging import event_fields
from invoicing.adapters.principal import (
    MAX_HEADER_LENGTH,
    PRINCIPAL_HEADER,
    MalformedPrincipalError,
    parse_principal,
    staff_endpoint,
)
from invoicing.domain.roles import Role, StaffPrincipal, Surface

ROLE_TYP = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
NAME_TYP = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
# Synthetic identities only.
OID = "7f1c2d3e-0000-4000-8000-00000000abcd"
EMAIL = "priya@babaloo.example"


def encode(claims: list[dict[str, str]], **extra: object) -> str:
    body = {"auth_typ": "aad", "name_typ": NAME_TYP, "role_typ": "roles", **extra}
    body["claims"] = claims
    return base64.b64encode(json.dumps(body).encode()).decode()


def principal_header(name: str = "Priya Tan", *roles: str) -> str:
    claims = [
        {"typ": "name", "val": name},
        {
            "typ": "http://schemas.microsoft.com/identity/claims/objectidentifier",
            "val": OID,
        },
        {"typ": "preferred_username", "val": EMAIL},
    ]
    claims += [{"typ": "roles", "val": role} for role in roles]
    return encode(claims)


def test_story_2_7_parses_name_and_roles_in_landing_order() -> None:
    principal = parse_principal(principal_header("Priya Tan", "finance", "admin"))
    assert principal == StaffPrincipal("Priya Tan", (Role.ADMIN, Role.FINANCE))


def test_story_2_7_reads_roles_under_role_typ_and_name_under_name_typ() -> None:
    header = encode(
        [
            {"typ": NAME_TYP, "val": "Wei Ling"},
            {"typ": ROLE_TYP, "val": "procurement"},
            {"typ": "roles", "val": "management"},
            # Not a role claim: never grants anything.
            {"typ": "groups", "val": "admin"},
        ],
        role_typ=ROLE_TYP,
    )
    principal = parse_principal(header)
    assert principal == StaffPrincipal("Wei Ling", (Role.PROCUREMENT, Role.MANAGEMENT))


def test_story_2_7_no_known_role_and_no_name() -> None:
    principal = parse_principal(encode([{"typ": "roles", "val": "auditor"}]))
    assert principal == StaffPrincipal("", ())


@pytest.mark.parametrize("header", [None, "", "   "])
def test_story_2_7_no_header_is_no_principal(header: str | None) -> None:
    assert parse_principal(header) is None


@pytest.mark.parametrize(
    "header",
    [
        "not base64 !!!",
        base64.b64encode(b"\xff\xfe").decode(),
        base64.b64encode(b"not json").decode(),
        base64.b64encode(b"[1, 2]").decode(),
        base64.b64encode(b'{"claims": "admin"}').decode(),
        base64.b64encode(b'{"claims": ["admin"]}').decode(),
        base64.b64encode(b'{"claims": [{"typ": "roles", "val": 1}]}').decode(),
        "A" * (MAX_HEADER_LENGTH + 4),
        # Not an Entra principal: missing, or another provider's.
        base64.b64encode(b'{"claims": []}').decode(),
        base64.b64encode(b'{"auth_typ": "github", "claims": []}').decode(),
        # Nested past the parser's recursion limit.
        base64.b64encode(
            b'{"auth_typ": "aad", "claims": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
        ).decode(),
    ],
)
def test_story_2_7_malformed_header_is_refused(header: str) -> None:
    with pytest.raises(MalformedPrincipalError) as raised:
        parse_principal(header)
    assert header not in str(raised.value)


# --- the endpoint wrapper ---------------------------------------------------------------


async def whoami(
    req: func.HttpRequest, correlation_id: UUID, principal: StaffPrincipal
) -> func.HttpResponse:
    return json_response(
        {"name": principal.name}, status=200, correlation_id=correlation_id
    )


def call(endpoint: object, headers: dict[str, str]) -> func.HttpResponse:
    request = func.HttpRequest(method="GET", url="/api/x", headers=headers, body=b"")
    return asyncio.run(endpoint(request))  # type: ignore[operator]  # an Endpoint


def test_story_2_7_no_principal_is_401_unauthenticated() -> None:
    response = call(staff_endpoint(whoami, surface=None), {})
    assert response.status_code == 401
    body = json.loads(response.get_body())
    assert body["code"] == "UNAUTHENTICATED"
    assert body["message"] == "Your session ended. Sign in again to continue."
    # A cookie session, not a bearer scheme: no WWW-Authenticate challenge.
    assert "WWW-Authenticate" not in response.headers


def test_story_2_7_malformed_principal_is_401_logged_by_code_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = base64.b64encode(f"not json {EMAIL}".encode()).decode()
    with caplog.at_level(logging.INFO):
        response = call(
            staff_endpoint(whoami, surface=None), {PRINCIPAL_HEADER: secret}
        )
    assert response.status_code == 401
    assert json.loads(response.get_body())["code"] == "UNAUTHENTICATED"
    (record,) = [r for r in caplog.records if r.name == "invoicing.auth"]
    assert record.getMessage().startswith("auth.principal_malformed ")
    assert event_fields(record)["code"] == "UNAUTHENTICATED"
    for leak in (secret, EMAIL):
        assert leak not in caplog.text


def test_story_2_7_role_guard_403_for_a_role_the_route_does_not_allow() -> None:
    admin_only = staff_endpoint(whoami, surface=Surface.ADMIN_QUEUE)
    response = call(admin_only, {PRINCIPAL_HEADER: principal_header("Siti", "finance")})
    assert response.status_code == 403
    assert json.loads(response.get_body())["code"] == "FORBIDDEN"
    # Nor does a user with no app role get in.
    response = call(admin_only, {PRINCIPAL_HEADER: principal_header("New")})
    assert response.status_code == 403


def test_story_2_7_allowed_role_reaches_the_handler_with_the_callers_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caller = "0192f0c1-7a2b-7c3d-8e4f-0123456789ab"
    endpoint = staff_endpoint(whoami, surface=Surface.INVOICES)
    with caplog.at_level(logging.DEBUG):
        response = call(
            endpoint,
            {
                PRINCIPAL_HEADER: principal_header("Siti", "finance"),
                CORRELATION_HEADER: caller,
            },
        )
    assert response.status_code == 200
    assert json.loads(response.get_body()) == {"name": "Siti"}
    assert response.headers[CORRELATION_HEADER] == caller
    assert endpoint.__name__ == "whoami"
    # Neither the header nor any claim reaches the logs.
    for leak in (OID, EMAIL, "Siti"):
        assert leak not in caplog.text


def test_story_2_7_a_large_realistic_principal_is_accepted() -> None:
    # Group claims are off (app-registrations.sh), but a long-lived account can still
    # carry many claims: about 40 KB of them must not lock the user out.
    claims = [{"typ": "name", "val": "Priya Tan"}]
    claims += [
        {
            "typ": "http://schemas.microsoft.com/claims/authnmethodsreferences",
            "val": f"m{n}-" + "x" * 300,
        }
        for n in range(90)
    ]
    claims += [{"typ": "roles", "val": role} for role in ("admin", "goods_in")]
    header = encode(claims)
    assert 30 * 1024 < len(header) <= MAX_HEADER_LENGTH == 64 * 1024
    assert parse_principal(header) == StaffPrincipal(
        "Priya Tan", (Role.ADMIN, Role.GOODS_IN)
    )


def test_story_2_7_auth_disabled_in_azure_fails_every_call_closed() -> None:
    endpoint = staff_endpoint(whoami, surface=None, platform_auth_trusted=False)
    # Even a well-formed (forgeable) principal is refused.
    response = call(endpoint, {PRINCIPAL_HEADER: principal_header("Priya", "admin")})
    assert response.status_code == 401
    assert json.loads(response.get_body())["code"] == "AUTH_DISABLED"


def test_story_2_7_a_surface_with_no_role_is_refused_at_wiring_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        principal_module, "SURFACE_ROLES", {Surface.ADMIN_QUEUE: frozenset()}
    )
    with pytest.raises(ValueError, match="allows no role"):
        staff_endpoint(whoami, surface=Surface.ADMIN_QUEUE)
