"""Story 2.5: the AD-18 current-value rule and the AD-19 validation checks, pure.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row it covers is a block of assertions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from uuid import UUID

from rapidfuzz import fuzz

from invoicing.domain.current_values import (
    CurrentValues,
    FieldValue,
    LineValue,
    RunRow,
    current_values,
)
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.transitions import AdminReason
from invoicing.domain.validation import (
    PoCheck,
    PoLineRef,
    PoRef,
    check_confidence,
    check_po,
    check_printed_supplier,
    expected_amount,
    money,
    normalise_name,
    normalise_tax_id,
    printed_po_number,
    within_tolerance,
)

T0 = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
OLD_RUN = UUID("0192f0c1-0000-7000-8000-00000000a001")
RUN = UUID("0192f0c1-0000-7000-8000-00000000a002")
SUPPLIER = UUID("0192f0c1-0000-7000-8000-000000000001")
OTHER_SUPPLIER = UUID("0192f0c1-0000-7000-8000-000000000002")
PO_LINE_1 = UUID("0192f0c1-0000-7000-8000-00000000b001")
PO_LINE_2 = UUID("0192f0c1-0000-7000-8000-00000000b002")
MATERIAL = UUID("0192f0c1-0000-7000-8000-00000000c001")


# Row ids in creation order, like UUIDv7s; a test passes `row_id` to pin a tie.
_ROW_IDS = count(1_000_000)


def _similarity(first: str, second: str) -> float:
    return float(fuzz.token_set_ratio(first, second))


def _field(
    field_id: str,
    value: str | Decimal | None,
    confidence: float | None = 0.99,
    *,
    run: UUID = RUN,
    source: str = "di",
    at: datetime = T0,
    row_id: int | None = None,
) -> FieldValue:
    return FieldValue(
        id=UUID(int=next(_ROW_IDS) if row_id is None else row_id),
        field_id=field_id,
        run_id=run,
        source=source,
        created_at=at,
        confidence=confidence,
        value_text=value if isinstance(value, str) else None,
        value_number=value if isinstance(value, Decimal) else None,
    )


def _line(
    line_no: int,
    code: str | None,
    quantity: str | None,
    price: str = "7.80",
    confidence: float = 0.99,
    *,
    run: UUID = RUN,
    source: str = "di",
    at: datetime = T0,
) -> LineValue:
    qty = None if quantity is None else Decimal(quantity)
    return LineValue(
        id=UUID(int=line_no + (1000 if source == "admin" else 0)),
        line_no=line_no,
        run_id=run,
        source=source,
        created_at=at,
        confidence=confidence,
        product_code=code,
        quantity=qty,
        unit_price=Decimal(price),
        amount=(qty or Decimal(1)) * Decimal(price),
    )


HEADER = ("vendor_name", "invoice_number", "invoice_date", "sub_total", "invoice_total")


def test_story_2_5_validation_rules() -> None:
    # --- Current values (AD-18): latest run only, the newest admin row wins -----------
    later = T0 + timedelta(minutes=5)
    runs = [RunRow(OLD_RUN, T0 - timedelta(days=1)), RunRow(RUN, T0)]
    rows = [
        _field("vendor_name", "Old Run Name", run=OLD_RUN),
        _field("vendor_name", "Admin On Old Run", 1.0, run=OLD_RUN, source="admin"),
        _field("invoice_number", "INV-1A", 1.0, source="admin", row_id=20),
        _field("invoice_number", "INV-1", 0.5, row_id=10),
        _field("invoice_date", "later id", row_id=31),
        _field("invoice_date", "earlier id", row_id=30),
        _field("invoice_total", "1", 1.0, source="admin", at=later),
        _field("invoice_total", "2", 1.0, source="admin"),
    ]
    values = current_values(
        runs,
        rows,
        [
            _line(1, "ALP-CEM-50", "10"),
            _line(1, "ALP-CEM-50", "12", 1.0, source="admin", at=later),
            _line(2, "ALP-RB-12", "5"),
            _line(3, "OLD", "1", run=OLD_RUN),
        ],
    )
    assert values is not None and values.run_id == RUN
    # Rows of an earlier run are never current, corrections on it included.
    assert "vendor_name" not in values.fields
    # Same `created_at` (one transaction): the later row id wins, whatever the order
    # the rows arrive in.
    assert values.fields["invoice_number"].source == "admin"
    assert values.fields["invoice_date"].value_text == "later id"
    reordered = current_values(runs, reversed(rows), [])
    assert reordered is not None and reordered.fields == values.fields
    assert values.fields["invoice_total"].value_text == "1"
    assert [(line.line_no, line.quantity) for line in values.lines] == [
        (1, Decimal(12)),
        (2, Decimal(5)),
    ]
    assert current_values([], [], []) is None

    # --- Confidence: exactly the low checked fields; bank and others ignored ----------
    confident = [_field(f, "x") for f in HEADER]
    values = current_values(
        [RunRow(RUN, T0)],
        [
            *[f for f in confident if f.field_id != "invoice_date"],
            _field("invoice_date", "2026-09-28", 0.89),
            _field("purchase_order", "PO-1", 0.5),
            _field("payment[0].iban", None, 0.1),
            _field("customer_name", "Anyone", 0.1),
        ],
        [_line(1, "A", "1"), _line(2, "B", None, confidence=0.0)],
    )
    assert values is not None
    low = check_confidence(values, supplier_upload=True)
    assert low is not None and low.reason is ReasonCode.LOW_CONFIDENCE
    assert low.field_ids == ("invoice_date", "purchase_order", "line[2].quantity")
    assert low.run_id == RUN
    # A goods-in scan never checks `purchase_order`.
    scan = check_confidence(values, supplier_upload=False)
    assert scan is not None
    assert scan.field_ids == ("invoice_date", "line[2].quantity")
    # `vendor_tax_id` only when DI returned it; admin rows count 1.0; 0.90 passes; a
    # line whose lowest confidence is under 0.90 names all its checked fields.
    values = current_values(
        [RunRow(RUN, T0)],
        [
            *confident[:4],
            _field("invoice_total", "x", 0.90),
            _field("vendor_tax_id", "T1", 0.4),
            _field("vendor_tax_id", "T1", 0.4, source="admin", at=later),
        ],
        # An admin line counts 1.0, even with a checked field left empty.
        [
            _line(1, "A", "1", confidence=0.89),
            _line(2, None, None, confidence=0.0, source="admin"),
        ],
    )
    assert values is not None
    low = check_confidence(values, supplier_upload=False)
    assert low is not None and low.field_ids == (
        "line[1].product_code",
        "line[1].quantity",
        "line[1].unit_price",
        "line[1].amount",
    )
    # A checked field with no row at all is missing: confidence 0.
    values = current_values([RunRow(RUN, T0)], confident[1:], [])
    assert values is not None
    missing = check_confidence(values, supplier_upload=False)
    assert missing is not None and missing.field_ids == ("vendor_name",)

    # --- Tolerance: max(1 %, 1.00), amounts to 0.01 half up ---------------------------
    assert money(Decimal("10.005")) == Decimal("10.01")
    assert within_tolerance(Decimal("101.00"), Decimal("100.00"))
    assert not within_tolerance(Decimal("101.01"), Decimal("100.00"))
    assert within_tolerance(
        Decimal("98.995"), Decimal("100.00")
    )  # 99.00 after rounding
    assert within_tolerance(Decimal("1010.00"), Decimal("1000.00"))
    assert not within_tolerance(Decimal("1010.01"), Decimal("1000.00"))
    assert not within_tolerance(Decimal("989.99"), Decimal("1000.00"))
    # Expected: each matched PO line once, received less invoiced elsewhere, never < 0.
    lines = {
        PO_LINE_1: PoLineRef(PO_LINE_1, MATERIAL, "ALP-CEM-50", Decimal("7.80")),
        PO_LINE_2: PoLineRef(PO_LINE_2, MATERIAL, "ALP-RB-12", Decimal("18.50")),
    }
    received = {PO_LINE_1: Decimal(100), PO_LINE_2: Decimal(50)}
    assert expected_amount(lines, received, {}) == Decimal("1705.00")
    assert expected_amount(
        lines, received, {PO_LINE_1: Decimal(30), PO_LINE_2: Decimal(80)}
    ) == Decimal("546.00")

    # --- PO match: edge passes, 0.01 beyond fails with expected and actual ------------
    po = PoRef("PO-1", SUPPLIER, tuple(lines.values()))

    def invoice(sub_total: str, *codes: str | None) -> CurrentValues:
        found = current_values(
            [RunRow(RUN, T0)],
            [_field("sub_total", Decimal(sub_total))],
            [_line(n, code, "1") for n, code in enumerate(codes, start=1)],
        )
        assert found is not None
        return found

    def po_check(
        values: CurrentValues,
        *,
        po_number: str | None = "PO-1",
        order: PoRef | None = po,
        no_receipt: bool = False,
        upload: bool = True,
    ) -> PoCheck:
        return check_po(
            values,
            po_number=po_number,
            po=order,
            supplier_id=SUPPLIER,
            received=None if no_receipt else {PO_LINE_1: Decimal(100)},
            invoiced_elsewhere={PO_LINE_1: Decimal(40)},
            supplier_upload=upload,
        )

    def reason_of(check: PoCheck) -> AdminReason:
        assert check.reason is not None
        return check.reason

    passed = po_check(invoice("472.68", "ALP-CEM-50"))  # 468.00 + 4.68 (1 %)
    assert passed.reason is None and passed.po_number == "PO-1"
    assert passed.matches[UUID(int=1)].po_line_id == PO_LINE_1
    # Product codes match whatever OCR's case and spacing.
    spaced = po_check(invoice("468.00", " alp-cem-50\t"))
    assert spaced.reason is None and spaced.matches[UUID(int=1)].po_line_id == PO_LINE_1
    failed = reason_of(po_check(invoice("472.69", "ALP-CEM-50")))
    assert failed.reason is ReasonCode.PO_MISMATCH
    assert failed.field_ids == ("sub_total",)
    assert dict(failed.detail) == {
        "expected": "468.00",
        "actual": "472.69",
        "problems": ["AMOUNT_OUTSIDE_TOLERANCE"],
    }
    # A goods-in scan does not deduct other invoices: its delivery's receipt is all.
    assert po_check(invoice("780.00", "ALP-CEM-50"), upload=False).reason is None
    # PO problems: missing, unknown, another supplier's, no receipt, an unmatched line.
    base = invoice("468.00", "ALP-CEM-50")
    for check, problem in [
        (po_check(base, po_number=None, order=None), "PO_MISSING"),
        (po_check(base, order=None), "PO_UNKNOWN"),
        (
            po_check(base, order=PoRef("PO-1", OTHER_SUPPLIER, po.lines)),
            "PO_OTHER_SUPPLIER",
        ),
        (po_check(base, no_receipt=True), "NO_RECEIPT"),
    ]:
        assert reason_of(check).detail["problems"] == [problem], problem
        assert check.po_number == (None if problem.startswith("PO_") else "PO-1")
    unmatched = reason_of(po_check(invoice("468.00", "ALP-CEM-50", "NOPE")))
    assert unmatched.field_ids == ("line[2].product_code",)
    assert unmatched.detail["problems"] == ["LINE_UNMATCHED"]
    # Two PO lines share a code: the line is never guessed, so nothing matches.
    twice = PoRef(
        "PO-1",
        SUPPLIER,
        (
            lines[PO_LINE_1],
            PoLineRef(PO_LINE_2, MATERIAL, "alp-cem-50 ", Decimal("7.80")),
        ),
    )
    ambiguous = po_check(base, order=twice)
    assert ambiguous.matches == {}
    assert reason_of(ambiguous).field_ids == ("line[1].product_code", "sub_total")
    assert reason_of(ambiguous).detail["problems"] == [
        "AMBIGUOUS_PRODUCT_CODE",
        "AMOUNT_OUTSIDE_TOLERANCE",
    ]
    # No lines at all: a PO problem even when sub_total is within 1.00 of nothing.
    empty = reason_of(po_check(invoice("0.50")))
    assert empty.detail["problems"] == ["NO_LINES"]
    # No sub_total read, with a receipt: expected is still reported.
    no_total = current_values([RunRow(RUN, T0)], [], [_line(1, "ALP-CEM-50", "1")])
    assert no_total is not None
    no_sub = reason_of(po_check(no_total))
    assert no_sub.detail == {
        "expected": "468.00",
        "actual": None,
        "problems": ["SUB_TOTAL_MISSING"],
    }
    assert no_sub.field_ids == ("sub_total",)
    # The printed PO number is looked up and saved normalised.
    printed_po = current_values(
        [RunRow(RUN, T0)], [_field("purchase_order", "  po-45012 ")], []
    )
    assert printed_po is not None and printed_po_number(printed_po) == "PO-45012"

    # --- Printed supplier: tax id first, else the normalised name ---------------------
    assert normalise_tax_id(" 2019-12345.k ") == "201912345K"
    assert normalise_name("Synthetic Alpha Co. Pte. Ltd.") == "synthetic alpha"
    assert normalise_name("ACME Private Limited") == "acme"
    assert normalise_name("Beta Sdn. Bhd.") == "beta"
    assert normalise_name("Gamma, Inc.") == "gamma"

    def printed(
        name: str | None, tax: str | None, master_tax: str | None
    ) -> AdminReason | None:
        fields = [] if name is None else [_field("vendor_name", name)]
        if tax is not None:
            fields.append(_field("vendor_tax_id", tax))
        found = current_values([RunRow(RUN, T0)], fields, [])
        assert found is not None
        return check_printed_supplier(
            found,
            master_name="Synthetic Alpha Building Supplies",
            master_tax_id=master_tax,
            similarity=_similarity,
        )

    # Tax ids equal after normalising: the name is not consulted.
    assert printed("Someone Else Entirely", "2019-12345-k", "201912345K") is None
    by_tax = printed("Synthetic Alpha Building Supplies", "999", "201912345K")
    assert by_tax is not None and by_tax.field_ids == ("vendor_tax_id",)
    assert by_tax.detail == {"basis": "tax_id"}
    # No tax id pair: the name decides at 85.
    assert printed("SYNTHETIC ALPHA BUILDING SUPPLIES PTE. LTD.", "999", None) is None
    assert printed("Synthetic Alpha Building", None, "201912345K") is None
    by_name = printed("Synthetic Beta Hardware", None, None)
    assert by_name is not None and by_name.reason is ReasonCode.SUPPLIER_ID_MISMATCH
    assert by_name.field_ids == ("vendor_name",)
    assert isinstance(score := by_name.detail["score"], int) and score < 85
    no_name = printed(None, None, None)
    assert no_name is not None and no_name.detail["score"] == 0
