"""`POST /api/invoices` on accounts-sim (Story 3.1, AD-10): validate an invoice XML
document against invoice-v1.xsd, store it once per `invoice_id` and answer its
`accounts_ref` as XML.

Only this environment's `pipeline` identity may call it. Built-in auth refuses
everyone else at the platform (`allowedPrincipals.identities`); here the caller's
`X-MS-CLIENT-PRINCIPAL-ID`, which the platform sets and strips from client requests,
must be that identity's principal id, and in Azure with built-in auth off every call
fails closed. Nothing about the document is logged but the invoice id and a code.
"""

import logging
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

import azure.functions as func

from invoicing.adapters.accounts_xml.contract import (
    MAX_DOCUMENT_BYTES,
    AccountsInvoice,
    parse_invoice,
    result_xml,
)
from invoicing.adapters.http import Endpoint, http_endpoint, json_response
from invoicing.adapters.logging import log_event
from invoicing.domain.errors import (
    AuthDisabledError,
    ErrorCode,
    ForbiddenError,
    PayloadTooLargeError,
    UnauthenticatedError,
    XmlInvalidError,
)
from invoicing.domain.ids import parse_uuid

PRINCIPAL_ID_HEADER = "X-MS-CLIENT-PRINCIPAL-ID"
XML_MIMETYPE = "application/xml"
# A simulated 429 or 503 says when to retry, as the real ones do.
RETRY_AFTER_STATUSES = frozenset({429, 503})
RETRY_AFTER_SECONDS = "5"
SIMULATED_FAILURE_MESSAGE = "The accounts system is failing on purpose (failure mode)."

_logger = logging.getLogger("invoicing.accounts_sim")


class SimAccountsStore(Protocol):
    """What the endpoint needs of the store (adapters/postgres/sim_accounts.py)."""

    def take_failure(self) -> Awaitable[int | None]: ...

    def store(
        self, invoice: AccountsInvoice, document: str
    ) -> Awaitable[tuple[str, bool]]: ...


def _check_caller(req: func.HttpRequest, pipeline_principal_id: UUID) -> None:
    caller = parse_uuid(req.headers.get(PRINCIPAL_ID_HEADER))
    if caller is None:
        raise UnauthenticatedError()
    if caller != pipeline_principal_id:
        # Logged by code only: never the caller's id (security.md rule 31).
        log_event(
            _logger,
            "accounts_sim.caller_refused",
            level=logging.WARNING,
            code=ErrorCode.FORBIDDEN,
        )
        raise ForbiddenError()


def invoices_endpoint(
    store: SimAccountsStore,
    *,
    pipeline_principal_id: UUID,
    platform_auth_trusted: bool,
) -> Endpoint:
    """The `POST /api/invoices` endpoint: 201 with `<result><accounts_ref/></result>`
    when stored, 200 with the same reference for a repeat `invoice_id`, 400
    `XML_INVALID`, 401 (`UNAUTHENTICATED`, or `AUTH_DISABLED` when built-in auth is off
    in Azure), 403 for any other caller, 413 over 256 KB, or the failure mode's status.
    `platform_auth_trusted` is required: there is no default that trusts the header."""

    async def post_invoice(
        req: func.HttpRequest, correlation_id: UUID
    ) -> func.HttpResponse:
        if not platform_auth_trusted:
            raise AuthDisabledError()
        _check_caller(req, pipeline_principal_id)

        # The failure mode answers before the document is read, so the pipeline sees
        # the error whatever it sends; nothing is stored.
        failing = await store.take_failure()
        if failing is not None:
            log_event(
                _logger,
                "accounts_sim.failure_mode",
                level=logging.WARNING,
                code=ErrorCode.SIMULATED_FAILURE,
                http_status=failing,
            )
            body = {
                "code": ErrorCode.SIMULATED_FAILURE.value,
                "message": SIMULATED_FAILURE_MESSAGE,
                "correlation_id": str(correlation_id),
            }
            response = json_response(
                body, status=failing, correlation_id=correlation_id
            )
            # Like a real busy service (adapters/http.py HEADERS_BY_CODE).
            if failing in RETRY_AFTER_STATUSES:
                response.headers["Retry-After"] = RETRY_AFTER_SECONDS
            return response

        document = req.get_body() or b""
        if len(document) > MAX_DOCUMENT_BYTES:
            raise PayloadTooLargeError("The invoice XML is over 256 KB.")
        invoice = parse_invoice(document)
        try:
            # A byte-order mark is not part of the document: never stored.
            text = document.decode("utf-8-sig")
        # The contract's documents are UTF-8 (adapters/accounts_xml).
        except UnicodeDecodeError:
            raise XmlInvalidError() from None

        accounts_ref, created = await store.store(invoice, text)
        log_event(
            _logger,
            "accounts_sim.stored",
            invoice_id=invoice.invoice_id,
            code="CREATED" if created else "REPEAT",
        )
        return func.HttpResponse(
            result_xml(accounts_ref),
            status_code=201 if created else 200,
            mimetype=XML_MIMETYPE,
            charset="utf-8",
        )

    return http_endpoint(post_invoice)
