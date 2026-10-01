"""Story 4.4: `GET /api/suppliers` and `GET /api/suppliers/{supplier_id}` on staff-api
(Flow 5, AD-11, AD-14), against a real PostgreSQL 18 read as the staff-api login (so
the test also proves its grants). Synthetic data only (security.md rule 1).

The master is shared with other tests, so this one's suppliers carry a marker in their
names, are found through the search, and are removed afterwards.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text

from apps.test_staff_me import header
from conftest import PostgresServer, login_engine
from invoicing.adapters.postgres.suppliers import PostgresSupplierDirectory
from invoicing.adapters.principal import PRINCIPAL_HEADER
from invoicing.adapters.purchasing_factory import purchasing_port
from invoicing.apps.staff_api.suppliers import suppliers_endpoints
from invoicing.ports.suppliers import SupplierEntry

pytestmark = pytest.mark.app("staff_api")

MARK = "Zq44"
ALLOWED_KEYS = {"items", "page", "page_size", "total", "supplier_id", "name"}


def _id(n: int) -> UUID:
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-44{n:010x}")


class _Spy:
    """The real directory, counting reads (a refused call must read nothing)."""

    def __init__(self, directory: PostgresSupplierDirectory) -> None:
        self.directory = directory
        self.reads = 0

    async def names(self, supplier_ids: Any) -> dict[UUID, str]:
        self.reads += 1
        return await self.directory.names(supplier_ids)

    async def matching(self, text: str) -> dict[UUID, str]:
        self.reads += 1
        return await self.directory.matching(text)

    async def page(
        self, text: str | None, page: int
    ) -> tuple[Sequence[SupplierEntry], int]:
        self.reads += 1
        return await self.directory.page(text, page)

    async def get_name(self, supplier_id: UUID) -> str | None:
        self.reads += 1
        return await self.directory.get_name(supplier_id)


def _remove(owner: Engine, ids: list[UUID]) -> None:
    """Delete this test's suppliers (and their bank row), as the deployer."""
    with owner.begin() as connection:
        connection.execute(
            text("DELETE FROM master.supplier_bank WHERE supplier_id = ANY(:ids)"),
            {"ids": ids},
        )
        connection.execute(
            text("DELETE FROM master.supplier WHERE id = ANY(:ids)"), {"ids": ids}
        )


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_story_4_4_suppliers_api(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
) -> None:
    """Both routes wired, GET only, before the SPA catch-all; by name in any case
    then id, 50 a page with the total; `q` contains in any case with `%` and `_`
    literal; only supplier_id and name, never tax id, phone or bank fields; 400 for a
    bad page or q naming no value; one supplier by id, 404 unknown or malformed;
    procurement, finance and management allowed; admin and goods_in 403 on the list
    and 404 on one supplier with nothing read; 401 signed out."""
    # --- Wiring.
    module = load_app("staff_api")
    functions = list(module.app.get_functions())
    names = [fn.get_function_name() for fn in functions]
    assert names[-1] == "web_app"
    for name, route in (
        ("supplier_list", "api/suppliers"),
        ("supplier_detail", "api/suppliers/{supplier_id}"),
    ):
        (trigger,) = [
            b.get_dict_repr()
            for b in functions[names.index(name)].get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        assert trigger["route"] == route
        assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    staff = login_engine(postgres_server, postgres_server.staff_api, intake_database)
    # 52 "Zq44 Supplier NN" (inserted in reverse, so order comes from the query), one
    # lower-case name to prove the case-insensitive sort, and two wildcard traps.
    seeded = {_id(n): f"{MARK} Supplier {n:02d}" for n in range(1, 53)}
    seeded[_id(60)] = f"{MARK} supplier 00 lower"
    seeded[_id(61)] = f"{MARK} 100% Soles"
    seeded[_id(62)] = f"{MARK} 100x Soles_Co"
    spy = _Spy(PostgresSupplierDirectory(staff))
    listing, one, _ = suppliers_endpoints(
        spy, purchasing_port("sim", staff), platform_auth_trusted=True
    )

    def call(
        endpoint: Any, url: str, params: dict[str, str], *roles: str, **route: str
    ) -> tuple[int, Any]:
        headers = {PRINCIPAL_HEADER: header(*roles)} if roles else {}
        request = func.HttpRequest(
            method="GET",
            url=url,
            headers=headers,
            params=params,
            route_params=route,
            body=b"",
        )
        response = asyncio.run(endpoint(request))
        return response.status_code, json.loads(response.get_body())

    def search(params: dict[str, str], role: str = "procurement") -> Any:
        status, body = call(listing, "/api/suppliers", params, role)
        assert status == 200, body
        assert _keys(body) <= ALLOWED_KEYS
        return body

    def open_(supplier_id: str, *roles: str) -> tuple[int, Any]:
        return call(
            one,
            f"/api/suppliers/{supplier_id}",
            {},
            *roles,
            supplier_id=supplier_id,
        )

    try:
        # A run that died before its clean-up must not break this one.
        _remove(owner, list(seeded))
        with owner.begin() as connection:
            for supplier_id, supplier_name in reversed(list(seeded.items())):
                connection.execute(
                    text(
                        "INSERT INTO master.supplier (id, name, tax_id, phone)"
                        " VALUES (:id, :name, 'T-SYN-1', '+65 9000 0000')"
                    ),
                    {"id": supplier_id, "name": supplier_name},
                )
            connection.execute(
                text(
                    "INSERT INTO master.supplier_bank (supplier_id, field_id, ciphertext,"
                    " fingerprint) VALUES (:id, 'iban', :ct, :fp)"
                ),
                {"id": _id(1), "ct": b"\x01\x02", "fp": "ab" * 32},
            )

        # --- List: page 1, 50 by name (any case) then id, with the total; only ids
        # and names, never tax id, phone or bank fields.
        body = search({})
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert len(body["items"]) == 50
        assert body["total"] >= len(seeded)

        # --- Search, paged: contains, any case; the lower-case name sorts first.
        body = search({"q": f"  {MARK.lower()} SUPPLIER "})
        assert body["total"] == 53
        assert [item["name"] for item in body["items"][:2]] == [
            f"{MARK} supplier 00 lower",
            f"{MARK} Supplier 01",
        ]
        assert body["items"][1] == {"supplier_id": str(_id(1)), "name": seeded[_id(1)]}
        body = search({"q": f"{MARK} supplier", "page": "2"}, role="finance")
        assert body["page"] == 2
        assert [item["name"] for item in body["items"]] == [
            f"{MARK} Supplier 50",
            f"{MARK} Supplier 51",
            f"{MARK} Supplier 52",
        ]
        assert search({"q": f"{MARK} supplier", "page": "9"})["items"] == []

        # --- Wildcards are literal.
        def names_for(q: str) -> list[str]:
            return [item["name"] for item in search({"q": q})["items"]]

        assert names_for(f"{MARK} 100%") == [f"{MARK} 100% Soles"]
        assert names_for(f"{MARK} 100x soles_") == [f"{MARK} 100x Soles_Co"]
        assert names_for(f"{MARK} 100_") == []
        assert names_for("zzz-no-such-supplier") == []

        # --- Bad query: 400, the value never echoed, nothing read.
        too_long = "y" * 65
        reads = spy.reads
        for params in (
            {"page": "0"},
            {"page": "-3"},
            {"page": "abc7"},
            {"q": "   "},
            {"q": too_long},
            {"q": "so\x00les"},
        ):
            status, body = call(listing, "/api/suppliers", params, "management")
            assert (status, body["code"]) == (400, "VALIDATION_FAILED"), params
            for value in params.values():
                if value.strip():
                    assert value not in body["message"]
        assert spy.reads == reads

        # --- One supplier: id and name only; unknown or malformed 404.
        status, body = open_(str(_id(1)), "management")
        assert (status, body) == (
            200,
            {"supplier_id": str(_id(1)), "name": f"{MARK} Supplier 01"},
        )
        for role in ("procurement", "finance"):
            assert open_(str(_id(2)), role) == (
                200,
                {"supplier_id": str(_id(2)), "name": f"{MARK} Supplier 02"},
            )
        for missing in (str(_id(999)), "not-a-uuid"):
            status, body = open_(missing, "procurement")
            assert (status, body["code"]) == (404, "NOT_FOUND")

        # --- Wrong role: 403 on the list, 404 on one supplier, nothing read.
        reads = spy.reads
        for role in ("admin", "goods_in"):
            status, body = call(listing, "/api/suppliers", {}, role)
            assert (status, body["code"]) == (403, "FORBIDDEN")
            status, body = open_(str(_id(1)), role)
            assert (status, body["code"]) == (404, "NOT_FOUND")
        # --- Signed out: 401.
        status, body = call(listing, "/api/suppliers", {})
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        status, body = open_(str(_id(1)))
        assert (status, body["code"]) == (401, "UNAUTHENTICATED")
        assert spy.reads == reads
    finally:
        try:
            _remove(owner, list(seeded))
        finally:
            staff.dispose()
            owner.dispose()
