"""Story 2.10: the admin action guard and the Correct plan (domain/actions.py), pure.

One test (the 200-case cap, coding-style.md rule 20 exception): the multi-reason
matrix on open reasons, with `accounts_ref` and the quality stage's completion, then
the Correct plan's field and line rules."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from invoicing.domain.actions import AdminAction, addable_fields, plan_correction
from invoicing.domain.actions import allowed_actions as guard
from invoicing.domain.current_values import (
    CurrentValues,
    FieldValue,
    LineValue,
)
from invoicing.domain.errors import ValidationFailedError

C, X, I, R = (
    AdminAction.CORRECT,
    AdminAction.REEXTRACT,
    AdminAction.RETRY_INTAKE,
    AdminAction.REJECT,
)
RUN = UUID(int=7)
T0 = datetime(2026, 9, 30, tzinfo=UTC)


def test_story_2_10_action_guard_and_correction_plan() -> None:
    """Covers: Correct if any reason allows it; Re-extract only if every reason does;
    Retry intake in its place for PROCESSING_FAILED before quality completed; Reject
    always, but nothing once `accounts_ref` exists; an unknown code allows only
    Reject. Correct: bank fields and unknown fields refused, a missing checked field
    added, values typed by their column, a line written whole."""
    # --- The guard (EXPERIENCE.md "Allowed actions by reason").
    matrix: list[tuple[list[str], bool, bool, tuple[AdminAction, ...]]] = [
        (["UNREADABLE"], False, False, (R,)),
        (["UNSUPPORTED_DOCUMENT"], False, True, (R,)),
        (["EXTRACTION_QUOTA"], False, True, (X, R)),
        (["PROCESSING_FAILED"], False, True, (X, R)),
        (["PROCESSING_FAILED"], False, False, (I, R)),
        (["LOW_CONFIDENCE"], False, True, (C, R)),
        (["DUPLICATE"], False, True, (R,)),
        (["BANK_CHANGED"], False, True, (R,)),
        (["ACCOUNTS_API_ERROR"], False, True, (R,)),
        # Several reasons: Correct if any allows it, Re-extract only if all do.
        (["BANK_CHANGED", "PO_MISMATCH"], False, True, (C, R)),
        (["EXTRACTION_QUOTA", "PROCESSING_FAILED"], False, True, (X, R)),
        (["EXTRACTION_QUOTA", "LOW_CONFIDENCE"], False, True, (C, R)),
        (["NEW_REASON"], False, True, (R,)),
        ([], False, True, (R,)),
        # In the accounts system: only Approve (Story 3.3), so nothing here.
        (["ACCOUNTS_API_ERROR"], True, True, ()),
        (["LOW_CONFIDENCE"], True, True, ()),
    ]
    for reasons, accounts_ref, quality_done, expected in matrix:
        got = guard(reasons, accounts_ref=accounts_ref, quality_done=quality_done)
        assert got == expected, (reasons, accounts_ref, quality_done)

    # --- Correct: the rows it writes.
    line_row = LineValue(
        id=UUID(int=1),
        line_no=1,
        run_id=RUN,
        source="di",
        created_at=T0,
        confidence=0.4,
        product_code="EVA-0l",
        description="EVA soles",
        quantity=Decimal(10),
        unit_price=Decimal("10.90"),
        amount=Decimal("109.00"),
        po_line_id=UUID(int=11),
        unit="pair",
        tax=Decimal("8.72"),
        material_id=UUID(int=12),
    )
    total = FieldValue(
        id=UUID(int=2),
        field_id="invoice_total",
        run_id=RUN,
        source="di",
        created_at=T0,
        confidence=0.9,
        value_number=Decimal("190.00"),
        currency="SGD",
        page=1,
        polygon=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
    )
    current = CurrentValues(RUN, {"invoice_total": total}, (line_row,))
    plan = plan_correction(
        current,
        {"invoice_total": " 109.00 ", "invoice_date": "2026-09-28"},
        {1: {"product_code": "EVA-01"}},
        currency="SGD",
    )
    assert plan.run_id == RUN
    by_id = {f.field_id: f for f in plan.fields}
    # The current row's column, currency and box; a missing checked date as a date.
    assert (by_id["invoice_total"].value_number, by_id["invoice_total"].currency) == (
        Decimal("109.00"),
        "SGD",
    )
    assert by_id["invoice_total"].polygon == total.polygon
    assert by_id["invoice_date"].value_date == date(2026, 9, 28)
    (line,) = plan.lines
    # A complete row: the edit, and every other column copied.
    assert (line.product_code, line.description, line.quantity, line.amount) == (
        "EVA-01",
        "EVA soles",
        Decimal(10),
        Decimal("109.00"),
    )
    assert (line.unit, line.tax, line.po_line_id, line.material_id) == (
        "pair",
        Decimal("8.72"),
        UUID(int=11),
        UUID(int=12),
    )
    # A flagged value confirmed unchanged is kept exactly as read, even where it
    # would not pass as typed input (an exponent here).
    odd = FieldValue(
        id=UUID(int=3),
        field_id="sub_total",
        run_id=RUN,
        source="di",
        created_at=T0,
        confidence=0.5,
        value_number=Decimal("1.9E+2"),
        currency="SGD",
    )
    as_read = CurrentValues(RUN, {"sub_total": odd}, ())
    (kept,) = plan_correction(
        as_read, {"sub_total": "1.9E+2"}, {}, currency="SGD"
    ).fields
    assert (kept.value_number, kept.currency) == (Decimal("1.9E+2"), "SGD")
    assert addable_fields(as_read) == (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "invoice_total",
        "purchase_order",
        "vendor_tax_id",
    )
    assert addable_fields(None) == ()
    # Refused, naming no value: a bank field, an unknown field, a bad value, an
    # unknown line or column, and nothing to save.
    for fields, lines in (
        ({"payment[0].iban": "SG00"}, {}),
        ({"customer_name": "x"}, {}),
        ({"invoice_total": "12,50"}, {}),
        ({"invoice_date": "30/09/2026"}, {}),
        ({"invoice_total": "  "}, {}),
        ({}, {2: {"amount": "1"}}),
        ({}, {1: {"tax": "1"}}),
        ({}, {}),
    ):
        with pytest.raises(ValidationFailedError) as refused:
            plan_correction(current, fields, lines, currency="SGD")
        assert "SG00" not in refused.value.message
