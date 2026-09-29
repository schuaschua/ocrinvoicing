"""The signed-in staff user from built-in auth (AD-14), and the endpoint wrapper every
staff-api route but `/api/health` uses.

App Service built-in auth validates the Entra session and injects
`X-MS-CLIENT-PRINCIPAL`: base64 of `{auth_typ, name_typ, role_typ, claims: [{typ, val}]}`.
The platform strips that header from client requests, so it is the only identity the
API trusts; roles come only from its `roles` claims. Neither the header nor any claim
is ever logged (spine Logging): a rejected header is logged by code only.
"""

import base64
import binascii
import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import azure.functions as func

from invoicing.adapters.http import Endpoint, http_endpoint
from invoicing.adapters.logging import log_event
from invoicing.domain.errors import (
    AuthDisabledError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from invoicing.domain.roles import (
    SURFACE_ROLES,
    StaffPrincipal,
    Surface,
    known_roles,
    require_signed_in,
    require_surface,
)

PRINCIPAL_HEADER = "X-MS-CLIENT-PRINCIPAL"

# Entra ID tokens carry app roles as `roles`; built-in auth names its role claim type
# in `role_typ` (for Entra, also `roles`). Both are read, nothing else.
ROLES_CLAIM = "roles"
NAME_CLAIM = "name"
# The Entra object id: built-in auth sends the long claim type, a token the short one.
OID_CLAIMS = ("http://schemas.microsoft.com/identity/claims/objectidentifier", "oid")

# security.md rule 24: every non-GET staff call must carry the custom header the staff
# app always sends; a cross-site form can't set it.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "XMLHttpRequest"
SAFE_METHODS = frozenset({"GET", "HEAD"})

# The only provider staff-api's built-in auth has (Entra, AD-14).
AUTH_TYPE = "aad"

# Group claims are off on the app registration (app-registrations.sh), so a principal
# is a few KB; 64 KB leaves room for many roles and long names. Larger is refused unread.
MAX_HEADER_LENGTH = 64 * 1024

_logger = logging.getLogger("invoicing.auth")


class MalformedPrincipalError(ValueError):
    """The principal header is present but not base64 JSON of the expected shape."""


def _claims(data: dict[str, object]) -> list[tuple[str, str]]:
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise MalformedPrincipalError("no claims list")
    pairs: list[tuple[str, str]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise MalformedPrincipalError("claim is not an object")
        typ, val = claim.get("typ"), claim.get("val")
        if not isinstance(typ, str) or not isinstance(val, str):
            raise MalformedPrincipalError("claim typ or val is not text")
        pairs.append((typ, val))
    return pairs


def parse_principal(header: str | None) -> StaffPrincipal | None:
    """The principal in the header value, or None when there is none.

    Raises MalformedPrincipalError for a value that is not base64 JSON with a claims
    list (the message never echoes the value)."""
    if header is None or header.strip() == "":
        return None
    if len(header) > MAX_HEADER_LENGTH:
        raise MalformedPrincipalError("too long")
    try:
        raw = base64.b64decode(header.strip(), validate=True)
        data: object = json.loads(raw.decode("utf-8"))
    # RecursionError: deeply nested JSON is refused like any other malformed value.
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise MalformedPrincipalError("not base64 JSON") from None
    if not isinstance(data, dict):
        raise MalformedPrincipalError("not an object")
    if data.get("auth_typ") != AUTH_TYPE:
        raise MalformedPrincipalError("not an Entra principal")
    pairs = _claims(data)
    role_types = {ROLES_CLAIM}
    role_typ = data.get("role_typ")
    if isinstance(role_typ, str) and role_typ:
        role_types.add(role_typ)
    name_types = [NAME_CLAIM]
    name_typ = data.get("name_typ")
    if isinstance(name_typ, str) and name_typ:
        name_types.append(name_typ)

    roles = known_roles(val for typ, val in pairs if typ in role_types)
    name = next(
        (val for want in name_types for typ, val in pairs if typ == want and val),
        "",
    )
    oid = next(
        (val for want in OID_CLAIMS for typ, val in pairs if typ == want and val),
        None,
    )
    return StaffPrincipal(name=name, roles=roles, oid=oid)


def principal_from(req: func.HttpRequest) -> StaffPrincipal | None:
    """The request's principal; None when absent or malformed (logged by code only)."""
    try:
        return parse_principal(req.headers.get(PRINCIPAL_HEADER))
    except MalformedPrincipalError:
        log_event(
            _logger,
            "auth.principal_malformed",
            level=logging.WARNING,
            code=ErrorCode.UNAUTHENTICATED,
        )
        return None


type StaffHandler = Callable[
    [func.HttpRequest, UUID, StaffPrincipal], Awaitable[func.HttpResponse]
]


NOT_FOUND_MESSAGE = "Not found."


def staff_endpoint(
    handler: StaffHandler,
    *,
    surface: Surface | None,
    platform_auth_trusted: bool = True,
    hide_from_others: bool = False,
) -> Endpoint:
    """Wrap a staff-api handler: 401 `UNAUTHENTICATED` without a valid principal, 403
    `FORBIDDEN` when the user holds none of `surface`'s roles (the domain guard,
    SURFACE_ROLES), 403 for a non-GET call without `X-Requested-With: XMLHttpRequest`
    (security.md rule 24), else `handler(req, correlation_id, principal)`.

    `surface=None` admits any signed-in user, whatever their roles (only `/api/me`).
    `hide_from_others=True` answers a user without the roles 404 `NOT_FOUND` instead,
    so a record's existence isn't revealed (security.md rule 5; the admin item).
    `platform_auth_trusted=False` (in Azure with built-in auth off, when the header
    could be forged) fails every call closed with 401 `AUTH_DISABLED`."""
    if surface is not None and not SURFACE_ROLES.get(surface):
        # Would refuse every user: a wiring mistake, caught at start-up.
        raise ValueError(f"surface {surface} allows no role")

    async def guarded(req: func.HttpRequest, correlation_id: UUID) -> func.HttpResponse:
        if not platform_auth_trusted:
            raise AuthDisabledError()
        principal = principal_from(req)
        if surface is None:
            signed_in = require_signed_in(principal)
        else:
            try:
                signed_in = require_surface(principal, surface)
            except ForbiddenError:
                if hide_from_others:
                    raise NotFoundError(NOT_FOUND_MESSAGE) from None
                raise
        if (req.method or "GET").upper() not in SAFE_METHODS and (
            req.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            raise ForbiddenError()
        return await handler(req, correlation_id, signed_in)

    guarded.__name__ = handler.__name__
    guarded.__qualname__ = handler.__qualname__
    guarded.__doc__ = handler.__doc__
    # Signed in at the platform: the caller's X-Correlation-Id is honoured (Story 1.5).
    return http_endpoint(guarded)
