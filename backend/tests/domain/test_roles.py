"""Story 2.7: the staff role model (AD-14), EXPERIENCE.md's staff surface table and
the route guard, rows "Role guard", "No known role" and "Sidebar union"."""

import re
from pathlib import Path

import pytest

from invoicing.domain.errors import (
    ErrorCode,
    ForbiddenError,
    UnauthenticatedError,
)
from invoicing.domain.roles import (
    LANDING_SURFACE,
    ROLE_ORDER,
    SURFACE_ROLES,
    Role,
    StaffPrincipal,
    Surface,
    known_roles,
    landing_surface,
    require_role,
    require_signed_in,
    require_surface,
    surfaces_for,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAFF_SURFACES_TS = REPO_ROOT / "web" / "staff" / "src" / "surfaces.ts"

A, F, P, M, G = (
    Role.ADMIN,
    Role.FINANCE,
    Role.PROCUREMENT,
    Role.MANAGEMENT,
    Role.GOODS_IN,
)


def test_story_2_7_roles_are_the_five_app_roles_in_landing_order() -> None:
    assert [r.value for r in ROLE_ORDER] == [
        "admin",
        "finance",
        "procurement",
        "management",
        "goods_in",
    ]


def test_story_2_7_surface_roles_follow_the_experience_table() -> None:
    assert SURFACE_ROLES == {
        Surface.ADMIN_QUEUE: {A},
        Surface.ADMIN_ITEM: {A},
        Surface.GOODS_IN_SCAN: {G},
        Surface.INVOICES: {A, F},
        Surface.OVERDUE_POS: {A, P, F},
        Surface.SUPPLIERS: {P, F, M},
        Surface.SUPPLIER_SCORECARD: {P, F, M},
        Surface.PRICE_COMPARISON: {P, F},
        Surface.WATCHLIST: {P, M},
        Surface.FINANCE_MONTH: {F, M},
    }
    # Every role's landing page is one of its own surfaces.
    for role, surface in LANDING_SURFACE.items():
        assert role in SURFACE_ROLES[surface]


def test_story_2_7_the_staff_app_uses_the_same_surface_map() -> None:
    # web/staff/src/surfaces.ts drives the sidebar; it must grant what the API grants.
    source = STAFF_SURFACES_TS.read_text(encoding="utf-8")
    found = {
        match.group(1): set(re.findall(r'"(\w+)"', match.group(2)))
        for match in re.finditer(
            r'id:\s*"(\w+)",[^}]*?roles:\s*\[([^\]]*)\]', source, re.DOTALL
        )
    }
    assert found == {
        surface.value: {role.value for role in roles}
        for surface, roles in SURFACE_ROLES.items()
    }
    landing = dict(re.findall(r'^\s*(\w+):\s*"(\w+)",\s*$', source, re.MULTILINE))
    for role, surface in LANDING_SURFACE.items():
        assert landing[role.value] == surface.value


def test_story_2_7_known_roles_drops_unknown_values_and_orders_them() -> None:
    assert known_roles(["goods_in", "Admin", "admin", "auditor", "admin"]) == (
        A,
        G,
    )
    assert known_roles([]) == ()


@pytest.mark.parametrize(
    ("roles", "surfaces", "landing"),
    [
        ((), (), None),
        # Sidebar union: both roles' surfaces, landing on the admin home.
        (
            (G, A),
            (
                Surface.ADMIN_QUEUE,
                Surface.ADMIN_ITEM,
                Surface.GOODS_IN_SCAN,
                Surface.INVOICES,
                Surface.OVERDUE_POS,
            ),
            Surface.ADMIN_QUEUE,
        ),
        ((G,), (Surface.GOODS_IN_SCAN,), Surface.GOODS_IN_SCAN),
        (
            (M, P),
            (
                Surface.OVERDUE_POS,
                Surface.SUPPLIERS,
                Surface.SUPPLIER_SCORECARD,
                Surface.PRICE_COMPARISON,
                Surface.WATCHLIST,
                Surface.FINANCE_MONTH,
            ),
            Surface.SUPPLIERS,
        ),
        (
            (M,),
            (
                Surface.SUPPLIERS,
                Surface.SUPPLIER_SCORECARD,
                Surface.WATCHLIST,
                Surface.FINANCE_MONTH,
            ),
            Surface.WATCHLIST,
        ),
        ((F, M), surfaces_for((F, M)), Surface.FINANCE_MONTH),
    ],
)
def test_story_2_7_surfaces_are_the_union_and_landing_is_the_first_role(
    roles: tuple[Role, ...],
    surfaces: tuple[Surface, ...],
    landing: Surface | None,
) -> None:
    assert surfaces_for(roles) == surfaces
    assert landing_surface(roles) == landing


def test_story_2_7_guard_401_without_a_principal() -> None:
    with pytest.raises(UnauthenticatedError) as raised:
        require_signed_in(None)
    assert raised.value.code is ErrorCode.UNAUTHENTICATED
    assert raised.value.message == "Your session ended. Sign in again to continue."
    with pytest.raises(UnauthenticatedError):
        require_role(None, [A])


def test_story_2_7_guard_403_for_a_role_the_route_does_not_allow() -> None:
    finance = StaffPrincipal("Siti", (F,))
    with pytest.raises(ForbiddenError) as raised:
        require_surface(finance, Surface.ADMIN_QUEUE)
    assert raised.value.code is ErrorCode.FORBIDDEN
    assert raised.value.message == "You don't have access to that page."
    # No known role: signed in, but no surface is open.
    nobody = StaffPrincipal("New Starter", ())
    assert require_signed_in(nobody) is nobody
    for surface in Surface:
        with pytest.raises(ForbiddenError):
            require_surface(nobody, surface)


def test_story_2_7_guard_admits_any_allowed_role() -> None:
    both = StaffPrincipal("Priya", (A, G))
    assert require_surface(both, Surface.GOODS_IN_SCAN) is both
    assert require_surface(both, Surface.INVOICES) is both
    assert require_role(both, [M, G]) is both
