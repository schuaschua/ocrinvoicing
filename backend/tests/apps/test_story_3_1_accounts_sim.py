"""Story 3.1: `POST /api/invoices` on accounts-sim (AD-10, AD-11), against a real
PostgreSQL 18 written as the accounts-sim login (so the test also proves the
0009_sim_accounts grants). Synthetic data only (security.md rule 1).

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row is a block of assertions, in order."""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from types import ModuleType
from uuid import UUID

import azure.functions as func
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError

from adapters.test_story_3_1_accounts_xml import INVOICE
from conftest import PostgresServer, login_engine
from invoicing.adapters.accounts_xml.contract import (
    MAX_DOCUMENT_BYTES,
    build_invoice_xml,
)
from invoicing.adapters.postgres.sim_accounts import PostgresSimAccounts
from invoicing.apps.accounts_sim.invoices import PRINCIPAL_ID_HEADER, invoices_endpoint

pytestmark = pytest.mark.app("accounts_sim")

# conftest APP_ONLY_SETTINGS: this environment's pipeline identity.
PIPELINE = UUID("10000000-0000-0000-0000-000000000003")
STAFF_API = UUID("10000000-0000-0000-0000-000000000002")
PROD_PIPELINE = UUID("10000000-0000-0000-0000-000000000013")
HUMAN = UUID("40000000-0000-0000-0000-0000000000d1")
REF = re.compile(rb"<result><accounts_ref>(SIM-\d{6,})</accounts_ref></result>$")
NS = "urn:ocrinvoicing:accounts:invoice:v1"


def _invoice(n: int, total: str = "109.00") -> bytes:
    return build_invoice_xml(
        replace(
            INVOICE,
            invoice_id=UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}"),
            invoice_total=Decimal(total),
        )
    )


def _rows(owner: Engine) -> list[tuple[str, UUID, Decimal, str]]:
    with owner.connect() as connection:
        return [
            (row[0], row[1], row[2], row[3])
            for row in connection.execute(
                text(
                    "SELECT accounts_ref, invoice_id, invoice_total, document"
                    " FROM sim_accounts.invoice ORDER BY accounts_ref"
                )
            )
        ]


def test_story_3_1_accounts_sim_posts_once_per_invoice_for_the_pipeline_only(
    postgres_server: PostgresServer,
    intake_database: str,
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /api/invoices. Covers: the one route, POST only; 401 AUTH_DISABLED through
    the registered handler when built-in auth is off in Azure; post (201, stored as
    the accounts-sim login); repeat (200, same ref, one row), also when two calls race;
    invalid XML, XSD breaks, DTD/entity payloads and non-UTF-8 (400 XML_INVALID,
    nothing stored); over 256 KB (413); no principal (401); wrong principal (403); the
    failure mode (N calls fail with its status, Retry-After on 429/503, before the body
    is read, then normal); auth.disabled logged once; a BOM is not stored; refs widen
    past SIM-999999; no other login reaches
    sim_accounts and no one changes a posted row; no field value is logged."""
    # --- Wiring: one route, api/invoices (host.json's default api/ prefix), POST only.
    module = load_app("accounts_sim")
    functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
    assert list(functions) == ["invoices"]
    (trigger,) = [
        b.get_dict_repr()
        for b in functions["invoices"].get_bindings()
        if b.get_dict_repr()["type"] == "httpTrigger"
    ]
    assert trigger["route"] == "invoices"
    assert [getattr(m, "value", m) for m in trigger["methods"]] == ["POST"]  # type: ignore[attr-defined]  # a list here

    # --- Auth off in Azure: the registered handler fails closed, even for the pipeline.
    with (
        monkeypatch.context() as env,
        caplog.at_level(logging.ERROR, logger="invoicing.auth"),
    ):
        env.setenv("WEBSITE_SITE_NAME", "babaloo-sea-lng-func-04")
        env.setenv("WEBSITE_AUTH_ENABLED", "False")
        caplog.clear()
        handler = next(
            fn
            for fn in load_app("accounts_sim").app.get_functions()
            if fn.get_function_name() == "invoices"
        ).get_user_function()
        # Logged once, at start-up, by code only.
        (disabled,) = [
            r for r in caplog.records if r.getMessage().startswith("auth.disabled")
        ]
        assert disabled.levelno == logging.ERROR
        assert str(disabled.code) == "AUTH_DISABLED"
        response = asyncio.run(
            handler(
                func.HttpRequest(
                    method="POST",
                    url="/api/invoices",
                    headers={PRINCIPAL_ID_HEADER: str(PIPELINE)},
                    body=_invoice(1),
                )
            )
        )
        assert response.status_code == 401
        assert json.loads(response.get_body())["code"] == "AUTH_DISABLED"

    owner = create_engine(
        postgres_server.url(postgres_server.deployer, intake_database)
    )
    with owner.begin() as connection:
        connection.execute(text("TRUNCATE sim_accounts.invoice"))
        connection.execute(
            text("UPDATE sim_accounts.failure_mode SET fail_next = 0, status = 503")
        )
    sim = login_engine(postgres_server, postgres_server.accounts_sim, intake_database)
    endpoint = invoices_endpoint(
        PostgresSimAccounts(sim),
        pipeline_principal_id=PIPELINE,
        platform_auth_trusted=True,
    )

    def request(body: bytes, caller: UUID | None = PIPELINE) -> func.HttpRequest:
        headers = {PRINCIPAL_ID_HEADER: str(caller)} if caller else {}
        return func.HttpRequest(
            method="POST", url="/api/invoices", headers=headers, body=body
        )

    def call(body: bytes, caller: UUID | None = PIPELINE) -> func.HttpResponse:
        return asyncio.run(endpoint(request(body, caller)))

    def code(response: func.HttpResponse) -> str:
        return str(json.loads(response.get_body())["code"])

    try:
        with caplog.at_level(logging.DEBUG):
            # --- Post: 201 with the XML result, stored as received.
            first = _invoice(1)
            response = call(first)
            assert response.status_code == 201
            assert response.mimetype == "application/xml"
            match = REF.search(response.get_body())
            assert match is not None
            ref = match.group(1).decode()
            assert _rows(owner) == [
                (ref, UUID(int=0x0192F0C17A2B7C3D8E4F000000000001), Decimal("109.00"),
                 first.decode())
            ]  # fmt: skip

            # --- Repeat: any body with the same invoice_id gets the same ref, no row.
            response = call(_invoice(1, total="999.99"))
            assert response.status_code == 200
            assert REF.search(response.get_body()).group(1).decode() == ref  # type: ignore[union-attr]  # asserted by the regex
            assert len(_rows(owner)) == 1

            # --- Race: two posts of a new invoice at once store one row and agree.
            async def race() -> list[func.HttpResponse]:
                second = _invoice(2)
                return list(
                    await asyncio.gather(
                        endpoint(request(second)), endpoint(request(second))
                    )
                )

            raced = asyncio.run(race())
            assert sorted(r.status_code for r in raced) == [200, 201]
            refs = {REF.search(r.get_body()).group(1) for r in raced}  # type: ignore[union-attr]  # asserted below
            assert len(refs) == 1 and len(_rows(owner)) == 2

            # --- Invalid XML or schema: 400 XML_INVALID, nothing stored.
            valid = _invoice(3).decode()
            invalid = {
                "malformed": b"<invoice xmlns=",
                "wrong namespace": valid.replace(NS, "urn:other").encode(),
                "missing field": re.sub(
                    r"\s*<po_number>[^<]*</po_number>", "", valid
                ).encode(),
                "bad decimal": valid.replace("109.00", "109.001").encode(),
                "not a number": valid.replace("109.00", "1e2").encode(),
                "external entity": (
                    b'<?xml version="1.0"?><!DOCTYPE invoice [<!ENTITY x SYSTEM'
                    b' "file:///etc/passwd">]><invoice xmlns="' + NS.encode() + b'">'
                    b"<invoice_id>&x;</invoice_id></invoice>"
                ),
                "billion laughs": (
                    b'<?xml version="1.0"?><!DOCTYPE invoice [<!ENTITY a "aaaaaaaaaa">'
                    b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                    + valid.split("?>", 1)[1].replace("SYN-PO-0001", "&b;").encode()
                ),
                "not UTF-8": valid.replace('encoding="utf-8"', 'encoding="latin-1"')
                .replace("Synthetic bolts", "Synth\xe9tic bolts")
                .encode("latin-1"),
                "empty": b"",
            }
            for name, body in invalid.items():
                response = call(body)
                assert (response.status_code, code(response)) == (400, "XML_INVALID"), (
                    name
                )
                assert (
                    b"passwd" not in response.get_body()
                    and b"1e2" not in response.get_body()
                )
            assert len(_rows(owner)) == 2

            # --- Too large: 413 before the document is read.
            response = call(b" " * (MAX_DOCUMENT_BYTES + 1))
            assert (response.status_code, code(response)) == (413, "PAYLOAD_TOO_LARGE")

            # --- No principal: 401. Anyone but this environment's pipeline: 403.
            response = call(_invoice(4), caller=None)
            assert (response.status_code, code(response)) == (401, "UNAUTHENTICATED")
            for caller in (STAFF_API, PROD_PIPELINE, HUMAN):
                response = call(_invoice(4), caller=caller)
                assert (response.status_code, code(response)) == (403, "FORBIDDEN")
            assert len(_rows(owner)) == 2

            # --- Failure mode: the next 2 calls answer its status, then normal again.
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sim_accounts.failure_mode SET fail_next = 2,"
                        " status = 503"
                    )
                )
            for _ in range(2):
                response = call(_invoice(5))
                assert (response.status_code, code(response)) == (
                    503,
                    "SIMULATED_FAILURE",
                )
                assert response.headers["Retry-After"] == "5"
            assert len(_rows(owner)) == 2
            assert call(_invoice(5)).status_code == 201
            with owner.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT fail_next FROM sim_accounts.failure_mode")
                    ).scalar_one()
                    == 0
                )
            # A refused caller never uses up a failure.
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sim_accounts.failure_mode SET fail_next = 1, status = 500"
                    )
                )
            assert call(_invoice(6), caller=HUMAN).status_code == 403
            response = call(_invoice(6))
            assert response.status_code == 500 and "Retry-After" not in response.headers
            assert call(_invoice(6)).status_code == 201
            # The failure mode answers before the body is read: even a malformed one.
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sim_accounts.failure_mode SET fail_next = 1, status = 429"
                    )
                )
            response = call(b"<invoice xmlns=")
            assert (response.status_code, code(response)) == (429, "SIMULATED_FAILURE")
            assert response.headers["Retry-After"] == "5"
            with owner.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT fail_next FROM sim_accounts.failure_mode")
                    ).scalar_one()
                    == 0
                )

            # --- A byte-order mark is not stored; past 999999 the ref widens.
            with owner.begin() as connection:
                connection.execute(
                    text("SELECT setval('sim_accounts.accounts_ref_seq', 999999)")
                )
            seventh = _invoice(7)
            response = call(b"\xef\xbb\xbf" + seventh)
            assert response.status_code == 201
            assert REF.search(response.get_body()).group(1) == b"SIM-1000000"  # type: ignore[union-attr]  # None fails the test
            assert _rows(owner)[-1][0] == "SIM-1000000"
            assert [row[3] for row in _rows(owner) if row[0] == "SIM-1000000"] == [
                seventh.decode()
            ]

        # --- No field value is logged: ids and codes only.
        logged = caplog.text + " ".join(str(vars(r)) for r in caplog.records)
        for value in ("SYN-INV-0001", "SYN-PO-0001", "109.00", "Synthetic bolts",
                      str(STAFF_API), str(HUMAN)):  # fmt: skip
            assert value not in logged, value

        # --- AD-11: only accounts-sim reaches sim_accounts, and a posted row is final.
        for login in (postgres_server.pipeline, postgres_server.staff_api):
            other = login_engine(postgres_server, login, intake_database)
            try:
                with (
                    other.connect() as connection,
                    pytest.raises(
                        ProgrammingError,
                        match="permission denied for schema sim_accounts",
                    ),
                ):
                    connection.execute(
                        text("SELECT count(*) FROM sim_accounts.invoice")
                    )
            finally:
                other.dispose()
        for statement in (
            "UPDATE sim_accounts.invoice SET invoice_total = 0",
            "DELETE FROM sim_accounts.invoice",
            "INSERT INTO sim_accounts.failure_mode (id) VALUES (2)",
        ):
            with (
                sim.connect() as connection,
                pytest.raises(ProgrammingError, match="permission denied"),
            ):
                connection.execute(text(statement))
    finally:
        sim.dispose()
        owner.dispose()
