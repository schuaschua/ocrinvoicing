"""Story 1.7: `GET /api/link` on supplier-api, every row of the I/O matrix. A fake
registry stands in for the `supplierlinks` table (coding-style.md rule 23)."""

import asyncio
import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import azure.functions as func
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from invoicing.adapters.http import CORRELATION_HEADER, SECURITY_HEADERS
from invoicing.adapters.table_links import TableSupplierLinkRegistry
from invoicing.domain.errors import ServiceUnavailableError
from invoicing.domain.links import token_hash
from invoicing.ports.links import SupplierLink, SupplierLinkRegistry

# Synthetic tokens, never real links.
VALID = base64.urlsafe_b64encode(b"\x11" * 32).rstrip(b"=").decode()
REVOKED = base64.urlsafe_b64encode(b"\x22" * 32).rstrip(b"=").decode()
UNKNOWN = base64.urlsafe_b64encode(b"\x33" * 32).rstrip(b"=").decode()
SUPPLIER_ID = UUID("0192f0c1-7a2b-7c3d-8e4f-0123456789ab")
ISSUED = datetime(2026, 9, 1, tzinfo=UTC)
LINK_NOT_WORKING = "This link isn't working. Please contact your buyer at Babaloo."


class FakeRegistry:
    """The registry port over a dict of token hash -> link; counts lookups."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.lookups: list[str] = []
        self.links = {
            token_hash(VALID): SupplierLink(
                SUPPLIER_ID, "Lim Leather Trading", ISSUED, None
            ),
            token_hash(REVOKED): SupplierLink(
                SUPPLIER_ID, "Lim Leather Trading", ISSUED, datetime.now(UTC)
            ),
        }

    async def resolve(self, token_hash: str) -> SupplierLink | None:
        self.lookups.append(token_hash)
        if self.error is not None:
            raise self.error
        return self.links.get(token_hash)


@pytest.fixture
def supplier_api(
    app_settings: dict[str, str],
    load_app: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[SupplierLinkRegistry], Callable[..., func.HttpResponse]]:
    """Load supplier-api as the host does, with `registry` in place of the table."""

    def with_registry(
        registry: SupplierLinkRegistry,
    ) -> Callable[..., func.HttpResponse]:
        built: list[tuple[str, str]] = []

        def build(cls: object, account: str, client_id: str) -> SupplierLinkRegistry:
            built.append((account, client_id))
            return registry

        monkeypatch.setattr(
            TableSupplierLinkRegistry, "with_managed_identity", classmethod(build)
        )
        module = load_app("supplier_api")
        # The environment's storage account, signed in as the app's own identity.
        assert built == [
            (app_settings["STORAGE_ACCOUNT_NAME"], app_settings["AZURE_CLIENT_ID"])
        ]
        functions = {fn.get_function_name(): fn for fn in module.app.get_functions()}
        link = functions["link"]
        (trigger,) = [
            b.get_dict_repr()
            for b in link.get_bindings()
            if b.get_dict_repr()["type"] == "httpTrigger"
        ]
        assert trigger["route"] == "api/link"
        assert [getattr(m, "value", m) for m in trigger["methods"]] == ["GET"]  # type: ignore[attr-defined]  # a list here
        assert getattr(trigger["authLevel"], "value", None) == "anonymous"

        def call(headers: dict[str, str] | None = None) -> func.HttpResponse:
            request = func.HttpRequest(
                method="GET", url="/api/link", headers=headers or {}, body=b""
            )
            return asyncio.run(link.get_user_function()(request))

        return call

    return with_registry


def _body(response: func.HttpResponse) -> dict[str, Any]:
    body = json.loads(response.get_body())
    assert isinstance(body, dict)
    return body


def _token(token: str) -> dict[str, str]:
    return {"X-Upload-Token": token}


def _not_valid(response: func.HttpResponse) -> dict[str, Any]:
    assert response.status_code == 401
    body = _body(response)
    assert body["code"] == "LINK_NOT_VALID"
    assert body["message"] == LINK_NOT_WORKING
    assert body["correlation_id"] == response.headers[CORRELATION_HEADER]
    # Identical apart from the per-request correlation id.
    return {key: value for key, value in body.items() if key != "correlation_id"}


def test_story_1_7_the_link_check_names_a_valid_supplier_and_401s_the_rest_alike(
    supplier_api: Callable[[SupplierLinkRegistry], Callable[..., func.HttpResponse]],
) -> None:
    # --- Story 1.7: a valid link returns the supplier name only
    registry = FakeRegistry()
    response = supplier_api(registry)(_token(VALID))
    assert response.status_code == 200
    # The supplier id stays on the server.
    assert _body(response) == {"supplier_name": "Lim Leather Trading"}
    assert str(SUPPLIER_ID) not in response.get_body().decode()
    assert registry.lookups == [token_hash(VALID)]
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value

    # --- Story 1.7: revoked and unknown links get the identical 401
    registry = FakeRegistry()
    call = supplier_api(registry)
    revoked = call(_token(REVOKED))
    unknown = call(_token(UNKNOWN))
    assert _not_valid(revoked) == _not_valid(unknown)
    assert revoked.headers["WWW-Authenticate"] == "UploadToken"
    assert unknown.headers["WWW-Authenticate"] == "UploadToken"
    assert dict(revoked.headers).keys() == dict(unknown.headers).keys()
    # The same work for both: one lookup each, so neither answers faster.
    assert registry.lookups == [token_hash(REVOKED), token_hash(UNKNOWN)]

    # --- Story 1.7: a missing token gets the same 401 without a lookup
    registry = FakeRegistry()
    call = supplier_api(registry)
    expected = _not_valid(call(_token(UNKNOWN)))
    registry.lookups.clear()
    assert _not_valid(call({})) == expected
    assert registry.lookups == []


@pytest.mark.parametrize("token", [VALID])
@pytest.mark.parametrize("outage", [True])
def test_story_1_7_no_log_or_span_holds_the_token_its_hash_or_the_header(
    token: str,
    outage: bool,
    supplier_api: Callable[[SupplierLinkRegistry], Callable[..., func.HttpResponse]],
    spans: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = FakeRegistry(error=ServiceUnavailableError() if outage else None)
    call = supplier_api(registry)
    spans.clear()
    with caplog.at_level(logging.DEBUG):
        call(_token(token))
    secrets = [token, token_hash(token), "X-Upload-Token", "x-upload-token"]
    records = [
        f"{record.getMessage()} {vars(record)}"
        for record in caplog.records
        if record.name.startswith("invoicing")
    ]
    finished = spans.get_finished_spans()
    assert finished, "the request span was recorded"
    recorded = records + [
        f"{span.name} {dict(span.attributes or {})} {[e.attributes for e in span.events]}"
        for span in finished
    ]
    for text in recorded:
        for secret in secrets:
            assert secret not in text
