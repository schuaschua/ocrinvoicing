"""Story 3.1: the accounts XML contract, `adapters/accounts_xml/invoice-v1.xsd` (AD-10).
Pure: no database. Synthetic data only (security.md rule 1)."""

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from invoicing.adapters.accounts_xml.contract import (
    NAMESPACE,
    AccountsInvoice,
    AccountsInvoiceLine,
    build_invoice_xml,
    parse_invoice,
    result_xml,
)
from invoicing.domain.errors import XmlInvalidError

INVOICE = AccountsInvoice(
    invoice_id=UUID("0192f0c1-7a2b-7c3d-8e4f-000000003101"),
    supplier_id=UUID("0192f0c1-7a2b-7c3d-8e4f-000000003102"),
    invoice_number="SYN-INV-0001",
    invoice_date=date(2026, 9, 1),
    currency="SGD",
    po_number="SYN-PO-0001",
    sub_total=Decimal(100),
    total_tax=Decimal("9.00"),
    invoice_total=Decimal("109.00"),
    lines=(
        AccountsInvoiceLine(
            line_no=1,
            material_id=UUID("0192f0c1-7a2b-7c3d-8e4f-000000003103"),
            description="Synthetic bolts & nuts <M8>",
            quantity=Decimal(4),
            unit_price=Decimal("25.00"),
            amount=Decimal("100.00"),
        ),
    ),
)


def test_story_3_1_invoice_xml_round_trips_through_the_xsd() -> None:
    """build_invoice_xml writes a document valid against the XSD, with 2-decimal money
    and escaped text, which parse_invoice reads back as Decimals; a value the XSD
    refuses, has too many decimals, is not finite, holds an XML-illegal character or is
    a reference that isn't whitespace-normalised is never built; a prefixed document
    parses the same, and a timezone date is refused; result_xml carries the
    accounts_ref."""
    document = build_invoice_xml(INVOICE)
    assert document.startswith(b'<?xml version="1.0" encoding="utf-8"?>')
    assert f'<invoice xmlns="{NAMESPACE}">'.encode() in document
    assert b"<sub_total>100.00</sub_total>" in document
    assert b"<quantity>4.000</quantity>" in document
    assert b"Synthetic bolts &amp; nuts &lt;M8&gt;" in document
    # No bank data in the contract (AD-11).
    assert b"bank" not in document.lower() and b"iban" not in document.lower()

    parsed = parse_invoice(document)
    assert parsed == replace(INVOICE, sub_total=Decimal("100.00"))
    assert isinstance(parsed.invoice_total, Decimal)
    assert parsed.lines[0].quantity == Decimal("4.000")

    # A namespace prefix instead of the default namespace is the same document.
    prefixed = re.sub(r"<(/?)(?!\?)(\w+)", r"<\1inv:\2", document.decode()).replace(
        f'xmlns="{NAMESPACE}"', f'xmlns:inv="{NAMESPACE}"'
    )
    assert "<inv:invoice xmlns:inv=" in prefixed
    assert parse_invoice(prefixed.encode()) == parsed
    # A date with a timezone is refused by the schema, not half-read.
    with pytest.raises(XmlInvalidError):
        parse_invoice(document.replace(b"2026-09-01<", b"2026-09-01+08:00<"))

    line = INVOICE.lines[0]
    for broken in (
        replace(INVOICE, currency="sgd"),
        replace(INVOICE, invoice_number=""),
        replace(INVOICE, lines=()),
        replace(INVOICE, invoice_total=Decimal(-1)),
        # Never rounded: more decimals than the wire carries are refused.
        replace(INVOICE, invoice_total=Decimal("109.005")),
        replace(INVOICE, lines=(replace(line, quantity=Decimal("4.0005")),)),
        # Not finite, or too large to scale.
        replace(INVOICE, sub_total=Decimal("Infinity")),
        replace(INVOICE, total_tax=Decimal("NaN")),
        replace(INVOICE, invoice_total=Decimal("1E+30")),
        # Characters XML can't carry.
        replace(INVOICE, lines=(replace(line, description="Bolts\x01"),)),
        # References must already be whitespace-normalised (xs:token).
        replace(INVOICE, invoice_number="SYN-INV-0001 "),
        replace(INVOICE, invoice_number="SYN  INV-0001"),
        replace(INVOICE, po_number="SYN-PO\t0001"),
    ):
        with pytest.raises(XmlInvalidError):
            build_invoice_xml(broken)

    # Story 3.2: no tax total and no line description are both optional, left out.
    bare = replace(INVOICE, total_tax=None, lines=(replace(line, description=None),))
    bare_document = build_invoice_xml(bare)
    assert b"total_tax" not in bare_document and b"description" not in bare_document
    assert parse_invoice(bare_document) == replace(bare, sub_total=Decimal("100.00"))

    assert result_xml("SIM-000123") == (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<result><accounts_ref>SIM-000123</accounts_ref></result>"
    )
