"""`AccountsPort` over the accounts XML API (Story 3.2, AD-10): the one accounts
adapter. It maps the AD-18 current values to the contract, builds the document with
`build_invoice_xml` and sends it with `POST {ACCOUNTS_BASE_URL}/invoices`.

- A managed-identity token for `{ACCOUNTS_AUDIENCE}/.default` (accounts-sim's own app
  registration, AD-17), sent only to `ACCOUNTS_BASE_URL`'s origin and never through a
  redirect (the transport does not follow them).
- It never retries (AD-10): every failure is one `AccountsError`, and the post stage
  backs off (AD-3). A value the contract refuses (missing, rounded, not finite) is
  `XML_INVALID`, an accounts-side failure like any other: never a crash, never rounded.
- Errors carry codes only. The answer's body is never logged or raised, and no field
  value ever is (security.md rule 31).
"""

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import aiohttp
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import AzureError

from invoicing.adapters.accounts_xml.contract import (
    AccountsInvoice,
    AccountsInvoiceLine,
    build_invoice_xml,
    parse_result,
)
from invoicing.adapters.document_intelligence import (
    AiohttpTransport,
    HttpResponse,
    HttpTransport,
)
from invoicing.adapters.logging import log_event
from invoicing.domain.current_values import CurrentValues, FieldValue
from invoicing.domain.errors import XmlInvalidError
from invoicing.ports.accounts import AccountsError, InvoiceToPost

# The accounts system answers within this, or the try counts as failed (AD-3 backoff).
REQUEST_TIMEOUT_SECONDS = 30
# The managed-identity token must come within this; otherwise the try counts as failed.
TOKEN_TIMEOUT_SECONDS = 30
XML_INVALID = "XML_INVALID"
TIMEOUT = "TIMEOUT"
UNREACHABLE = "UNREACHABLE"
BAD_RESULT = "BAD_RESULT"
# The accounts system's own error code (accounts-sim's `{code}`), kept only when it
# looks like a code: never free text.
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

_logger = logging.getLogger("invoicing.accounts")


def _field(values: CurrentValues, field_id: str) -> FieldValue:
    found = values.fields.get(field_id)
    if found is None:
        raise XmlInvalidError()
    return found


def _text(values: CurrentValues, field_id: str) -> str:
    text = _field(values, field_id).value_text
    if text is None:
        raise XmlInvalidError()
    return text


def _amount(values: CurrentValues, field_id: str) -> Decimal:
    number = _field(values, field_id).value_number
    if number is None:
        raise XmlInvalidError()
    return number


def _field_or_none(values: CurrentValues, field_id: str) -> Decimal | None:
    found = values.fields.get(field_id)
    return None if found is None else found.value_number


def _date(values: CurrentValues, field_id: str) -> date:
    held = _field(values, field_id)
    if held.value_date is not None:
        return held.value_date
    try:
        # An admin may have typed the date as text (YYYY-MM-DD, spine conventions).
        return date.fromisoformat(held.value_text or "")
    except ValueError:
        raise XmlInvalidError() from None


def _required[T](value: T | None) -> T:
    if value is None:
        raise XmlInvalidError()
    return value


def accounts_invoice(invoice: InvoiceToPost) -> AccountsInvoice:
    """`invoice` as the contract's invoice, from its AD-18 current values exactly as
    held; `XmlInvalidError` when a value the contract needs is missing."""
    values = invoice.values
    return AccountsInvoice(
        invoice_id=invoice.invoice_id,
        supplier_id=invoice.supplier_id,
        invoice_number=_text(values, "invoice_number"),
        invoice_date=_date(values, "invoice_date"),
        currency=invoice.currency,
        po_number=_required(invoice.po_number),
        sub_total=_amount(values, "sub_total"),
        # Optional in the contract: many invoices print no tax total.
        total_tax=_field_or_none(values, "total_tax"),
        invoice_total=_amount(values, "invoice_total"),
        lines=tuple(
            AccountsInvoiceLine(
                line_no=line.line_no,
                material_id=_required(line.material_id),
                description=line.description,
                quantity=_required(line.quantity),
                unit_price=_required(line.unit_price),
                amount=_required(line.amount),
            )
            for line in values.lines
        ),
    )


def _error_code(response: HttpResponse) -> str:
    try:
        body = json.loads(response.body)
    # Deeply nested JSON raises RecursionError: an unreadable body like any other.
    except (ValueError, RecursionError):
        body = None
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(code, str) and _CODE.fullmatch(code):
        return code
    return f"HTTP_{response.status}"


class AccountsXmlClient:
    """`AccountsPort` over HTTPS with a managed-identity token."""

    def __init__(
        self,
        *,
        base_url: str,
        audience: str,
        credential: AsyncTokenCredential,
        transport: HttpTransport | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "https" or not parts.netloc or parts.query:
            raise ValueError("base_url must be an https URL without a query")
        # The one URL the token is ever sent to: built from the setting's origin and
        # path only, and the transport never follows a redirect.
        self._url = f"https://{parts.netloc}{parts.path.rstrip('/')}/invoices"
        self._scope = f"{audience.rstrip('/')}/.default"
        self._credential = credential
        self._transport = transport or AiohttpTransport(REQUEST_TIMEOUT_SECONDS)

    async def post_invoice(self, invoice: InvoiceToPost) -> str:
        try:
            document = build_invoice_xml(accounts_invoice(invoice))
        except XmlInvalidError:
            raise self._failed(invoice, None, XML_INVALID) from None
        try:
            async with asyncio.timeout(TOKEN_TIMEOUT_SECONDS):
                token = await self._credential.get_token(self._scope)
        # No token, no call: an accounts-side failure that backs off like any other.
        except (AzureError, TimeoutError, OSError, aiohttp.ClientError):
            raise self._failed(invoice, None, UNREACHABLE) from None
        try:
            response = await self._transport.request(
                "POST",
                self._url,
                {
                    "content-type": "application/xml; charset=utf-8",
                    "accept": "application/xml",
                    "authorization": f"Bearer {token.token}",
                },
                document,
            )
        except TimeoutError:
            raise self._failed(invoice, None, TIMEOUT) from None
        except (aiohttp.ClientError, OSError):
            raise self._failed(invoice, None, UNREACHABLE) from None
        if response.status not in (200, 201):
            raise self._failed(invoice, response.status, _error_code(response))
        try:
            return parse_result(response.body)
        except XmlInvalidError:
            raise self._failed(invoice, response.status, BAD_RESULT) from None

    @staticmethod
    def _failed(invoice: InvoiceToPost, status: int | None, code: str) -> AccountsError:
        details: Mapping[str, object] = {
            "invoice_id": invoice.invoice_id,
            "code": code,
            **({} if status is None else {"http_status": status}),
        }
        log_event(_logger, "accounts.failed", level=logging.WARNING, **details)
        return AccountsError(status, code)
