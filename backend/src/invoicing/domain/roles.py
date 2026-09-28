"""Staff roles, the surfaces each role may use, and the route guard (AD-14, UX-DR8).

EXPERIENCE.md's staff surface table is the source: a user sees the union of their
roles' surfaces and lands on the landing surface of their first role in the order
admin, finance, procurement, management, goods_in. Every staff-api route checks its
roles here, never in the adapter or the app.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from invoicing.domain.errors import ForbiddenError, UnauthenticatedError


class Role(StrEnum):
    """The staff-api app registration's app roles (AD-14), in landing order."""

    ADMIN = "admin"
    FINANCE = "finance"
    PROCUREMENT = "procurement"
    MANAGEMENT = "management"
    GOODS_IN = "goods_in"


# UX-DR8: a user with several roles lands on the first role's landing surface.
ROLE_ORDER: tuple[Role, ...] = tuple(Role)


class Surface(StrEnum):
    """The staff app's surfaces (EXPERIENCE.md Information Architecture)."""

    ADMIN_QUEUE = "admin_queue"
    ADMIN_ITEM = "admin_item"
    GOODS_IN_SCAN = "goods_in_scan"
    INVOICES = "invoices"
    OVERDUE_POS = "overdue_pos"
    SUPPLIERS = "suppliers"
    SUPPLIER_SCORECARD = "supplier_scorecard"
    PRICE_COMPARISON = "price_comparison"
    WATCHLIST = "watchlist"
    FINANCE_MONTH = "finance_month"


_A, _F, _P, _M, _G = ROLE_ORDER

# EXPERIENCE.md staff surface table, column "Roles". web/staff/src/surfaces.ts holds
# the same map for navigation; tests keep the two equal.
SURFACE_ROLES: Mapping[Surface, frozenset[Role]] = {
    Surface.ADMIN_QUEUE: frozenset({_A}),
    Surface.ADMIN_ITEM: frozenset({_A}),
    Surface.GOODS_IN_SCAN: frozenset({_G}),
    Surface.INVOICES: frozenset({_A, _F}),
    Surface.OVERDUE_POS: frozenset({_A, _P, _F}),
    Surface.SUPPLIERS: frozenset({_P, _F, _M}),
    Surface.SUPPLIER_SCORECARD: frozenset({_P, _F, _M}),
    Surface.PRICE_COMPARISON: frozenset({_P, _F}),
    Surface.WATCHLIST: frozenset({_P, _M}),
    Surface.FINANCE_MONTH: frozenset({_F, _M}),
}

# EXPERIENCE.md "Reached from": each role's landing page.
LANDING_SURFACE: Mapping[Role, Surface] = {
    Role.ADMIN: Surface.ADMIN_QUEUE,
    Role.FINANCE: Surface.FINANCE_MONTH,
    Role.PROCUREMENT: Surface.SUPPLIERS,
    Role.MANAGEMENT: Surface.WATCHLIST,
    Role.GOODS_IN: Surface.GOODS_IN_SCAN,
}


def known_roles(claims: Iterable[str]) -> tuple[Role, ...]:
    """The app roles among `claims`, once each, in landing order. Any other value
    (a role this build doesn't know, a typo) grants nothing."""
    values = set(claims)
    return tuple(role for role in ROLE_ORDER if role.value in values)


@dataclass(frozen=True)
class StaffPrincipal:
    """The signed-in staff user as built-in auth vouches for them: a display name and
    their app roles (in landing order). No object id or email: nothing else is used."""

    name: str
    roles: tuple[Role, ...]

    def has_any(self, allowed: Iterable[Role]) -> bool:
        return not set(self.roles).isdisjoint(allowed)


def surfaces_for(roles: Iterable[Role]) -> tuple[Surface, ...]:
    """The union of `roles`' surfaces, in the table's order."""
    held = set(roles)
    return tuple(s for s in Surface if not SURFACE_ROLES[s].isdisjoint(held))


def landing_surface(roles: Iterable[Role]) -> Surface | None:
    """The landing surface of the first held role in ROLE_ORDER; None with no role."""
    held = set(roles)
    for role in ROLE_ORDER:
        if role in held:
            return LANDING_SURFACE[role]
    return None


def require_signed_in(principal: StaffPrincipal | None) -> StaffPrincipal:
    """The principal, or UnauthenticatedError (401) when there is none."""
    if principal is None:
        raise UnauthenticatedError()
    return principal


def require_role(
    principal: StaffPrincipal | None, allowed: Iterable[Role]
) -> StaffPrincipal:
    """The principal when it holds one of `allowed`: 401 with no principal, 403
    (ForbiddenError) when it holds none of them."""
    signed_in = require_signed_in(principal)
    if not signed_in.has_any(allowed):
        raise ForbiddenError()
    return signed_in


def require_surface(
    principal: StaffPrincipal | None, surface: Surface
) -> StaffPrincipal:
    """The route guard for a surface's API: its roles from SURFACE_ROLES."""
    return require_role(principal, SURFACE_ROLES[surface])
