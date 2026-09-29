"""The accounts XML contract (AD-10, Story 3.1): the only code that builds or parses
accounts XML, against `invoice-v1.xsd` next to this file.

Parsing is defused (security.md rule 20): xmlschema's `defuse="always"` refuses any
DTD, so no entity is ever expanded (XXE, billion laughs), and `allow="none"` stops the
document from loading anything, local or remote. Documents are size-capped before
they are read. Errors never carry the document's values, and nothing here logs.

accounts-sim validates and parses requests with `parse_invoice` and answers with
`result_xml`; the pipeline's post stage (Story 3.2) builds requests with
`build_invoice_xml`.
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import xmlschema

from invoicing.domain.errors import XmlInvalidError

NAMESPACE = "urn:ocrinvoicing:accounts:invoice:v1"
XSD_PATH = Path(__file__).resolve().parent / "invoice-v1.xsd"
# An invoice of the most lines the XSD allows (500) is well under this.
MAX_DOCUMENT_BYTES = 256 * 1024

# Built once per process; the schema file is local and imports nothing.
_SCHEMA = xmlschema.XMLSchema(XSD_PATH)


@dataclass(frozen=True)
class AccountsInvoiceLine:
    """One invoice line as the accounts system receives it."""

    line_no: int
    material_id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class AccountsInvoice:
    """One invoice as the accounts system receives it (AD-10). No bank data: the
    accounts system pays from its own supplier master (AD-11)."""

    invoice_id: UUID
    supplier_id: UUID
    invoice_number: str
    invoice_date: date
    currency: str
    po_number: str
    sub_total: Decimal
    total_tax: Decimal
    invoice_total: Decimal
    lines: tuple[AccountsInvoiceLine, ...]


def _resource(document: bytes) -> xmlschema.XMLResource:
    if len(document) > MAX_DOCUMENT_BYTES:
        raise XmlInvalidError()
    try:
        return xmlschema.XMLResource(
            io.BytesIO(document), allow="none", defuse="always"
        )
    # Malformed XML, a DTD or an entity: all refused alike, never echoed.
    except (xmlschema.XMLSchemaException, SyntaxError, ValueError):
        raise XmlInvalidError() from None


def _decode(document: bytes, schema: xmlschema.XMLSchema) -> dict[str, Any]:
    resource = _resource(document)
    try:
        # Keys without prefixes, whatever prefix (or none) the document binds to the
        # namespace; validation still requires the contract's namespace.
        data = schema.decode(resource, decimal_type=Decimal, strip_namespaces=True)
    except (xmlschema.XMLSchemaException, ValueError):
        # The validator's message quotes the offending value: dropped.
        raise XmlInvalidError() from None
    if not isinstance(data, dict):
        raise XmlInvalidError()
    return data


def parse_invoice(document: bytes) -> AccountsInvoice:
    """The invoice in `document`, validated against invoice-v1.xsd; `XmlInvalidError`
    when it is too large, malformed, carries a DTD or breaks the schema."""
    data = _decode(document, _SCHEMA)
    try:
        return AccountsInvoice(
            invoice_id=UUID(data["invoice_id"]),
            supplier_id=UUID(data["supplier_id"]),
            invoice_number=data["invoice_number"],
            invoice_date=date.fromisoformat(data["invoice_date"]),
            currency=data["currency"],
            po_number=data["po_number"],
            sub_total=data["sub_total"],
            total_tax=data["total_tax"],
            invoice_total=data["invoice_total"],
            lines=tuple(
                AccountsInvoiceLine(
                    line_no=line["line_no"],
                    material_id=UUID(line["material_id"]),
                    description=line["description"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                    amount=line["amount"],
                )
                for line in data["lines"]["line"]
            ),
        )
    # The schema allows only what the fields hold, so this is a safety net.
    except (KeyError, TypeError, ValueError):
        raise XmlInvalidError() from None


# Characters XML 1.0 can't carry (C0 controls but tab, LF and CR; surrogates; FFFE/FFFF).
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _fixed(value: Decimal, places: int) -> Decimal:
    """`value` with exactly `places` decimals, never rounded: a value with more
    decimals, or not finite, or too large to scale, is refused (coding-style.md rule 4:
    the accounts system must receive the amount the pipeline holds)."""
    try:
        scaled = value.quantize(Decimal(1).scaleb(-places))
    except InvalidOperation:
        raise XmlInvalidError() from None
    if scaled != value:
        raise XmlInvalidError()
    return scaled


def _text(value: str, *, token: bool = False) -> str:
    """`value` unchanged, or refused: XML-illegal characters never reach the encoder,
    and a token field must already be whitespace-normalised, since xs:token would
    collapse it on the other side and the two references would silently differ."""
    if _XML_ILLEGAL.search(value) or (token and " ".join(value.split()) != value):
        raise XmlInvalidError()
    return value


def _money(value: Decimal) -> Decimal:
    # Spine conventions: 2 decimals on the wire.
    return _fixed(value, 2)


def build_invoice_xml(invoice: AccountsInvoice) -> bytes:
    """`invoice` as a UTF-8 document valid against invoice-v1.xsd; `XmlInvalidError`
    when a value breaks the schema (the encoder validates as it builds), has more
    decimals than the wire allows (never rounded), is not finite, holds a character XML
    can't carry, or is a reference that isn't whitespace-normalised."""
    data = {
        "@xmlns": NAMESPACE,
        "invoice_id": str(invoice.invoice_id),
        "supplier_id": str(invoice.supplier_id),
        "invoice_number": _text(invoice.invoice_number, token=True),
        "invoice_date": invoice.invoice_date.isoformat(),
        "currency": _text(invoice.currency, token=True),
        "po_number": _text(invoice.po_number, token=True),
        "sub_total": _money(invoice.sub_total),
        "total_tax": _money(invoice.total_tax),
        "invoice_total": _money(invoice.invoice_total),
        "lines": {
            "line": [
                {
                    "line_no": line.line_no,
                    "material_id": str(line.material_id),
                    "description": _text(line.description),
                    "quantity": _fixed(line.quantity, 3),
                    "unit_price": _money(line.unit_price),
                    "amount": _money(line.amount),
                }
                for line in invoice.lines
            ]
        },
    }
    try:
        # Strict validation (the default): an Element, or an exception.
        element: Any = _SCHEMA.encode(data, namespaces={"": NAMESPACE})
    except (xmlschema.XMLSchemaException, ValueError):
        raise XmlInvalidError() from None
    document = xmlschema.etree_tostring(
        element, namespaces={"": NAMESPACE}, xml_declaration=True, encoding="utf-8"
    )
    return document if isinstance(document, bytes) else document.encode("utf-8")


# The answer to a stored invoice: <result><accounts_ref>SIM-000123</accounts_ref></result>.
# The reference is escaped, though accounts-sim only ever sends SIM-<digits>.
def result_xml(accounts_ref: str) -> bytes:
    """accounts-sim's answer carrying `accounts_ref`."""
    escaped = (
        accounts_ref.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<result><accounts_ref>{escaped}</accounts_ref></result>"
    ).encode()
