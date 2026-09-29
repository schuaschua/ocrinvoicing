"""Story 2.6: the AD-9 duplicate check, the AD-19 photo-date and bank checks, pure.

One merged test (the 200-case cap, coding-style.md rule 20 exception): each plan
matrix row it covers is a block of assertions."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from invoicing.domain.current_values import CurrentValues, FieldValue
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.suppliers import bank_fingerprint
from invoicing.domain.validation import (
    DuplicateFacts,
    check_bank,
    check_duplicate,
    check_photo_date,
    duplicate_facts,
    normalise_invoice_number,
)

T0 = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
RUN = UUID("0192f0c1-0000-7000-8000-00000000a002")
HMAC_KEY = "synthetic-hmac-key"
RECEIVED = date(2026, 9, 15)


def _invoice(n: int) -> UUID:
    # UUIDv7-shaped ids whose order is `n`'s.
    return UUID(f"0192f0c1-7a2b-7c3d-8e4f-{n:012x}")


def _facts(
    n: int,
    number: str | None = "INV-001",
    total: str | None = "100.00",
    on: str | None = "2026-09-20",
    *,
    phash: int | None = None,
    rejected: bool = False,
) -> DuplicateFacts:
    return DuplicateFacts(
        invoice_id=_invoice(n),
        rejected=rejected,
        invoice_number=number,
        invoice_total=None if total is None else Decimal(total),
        invoice_date=on,
        phash=phash,
        run_id=RUN,
    )


def _values(
    fields: Mapping[str, tuple[str | Decimal | date | None, str | None]],
) -> CurrentValues:
    """Current values from `{field_id: (value, bank fingerprint)}`."""
    rows = {
        field_id: FieldValue(
            id=UUID(int=n + 1),
            field_id=field_id,
            run_id=RUN,
            source="di",
            created_at=T0,
            confidence=0.99,
            value_text=value if isinstance(value, str) else None,
            value_number=value if isinstance(value, Decimal) else None,
            value_date=value if isinstance(value, date) else None,
            bank_fingerprint=fingerprint,
        )
        for n, (field_id, (value, fingerprint)) in enumerate(fields.items())
    }
    return CurrentValues(run_id=RUN, fields=rows, lines=())


def _at_singapore(day: date, hour: int = 12) -> datetime:
    # Singapore is UTC+8: noon there is 04:00 UTC the same day.
    return datetime(day.year, day.month, day.day, hour - 8, tzinfo=UTC)


def test_story_2_6_validation_rules() -> None:
    # --- Fingerprint duplicate: number normalised, total to 0.01, date ---------------
    assert normalise_invoice_number(" inv-001/a ") == "INV001A"
    own = _facts(5, "inv 001", "100.004")
    reason = check_duplicate(own, [_facts(2, "INV-001", "100.00")])
    assert reason is not None and reason.reason is ReasonCode.DUPLICATE
    assert reason.detail == {"invoice_id": str(_invoice(2)), "basis": "fingerprint"}
    assert reason.field_ids == ("invoice_number", "invoice_total", "invoice_date")
    assert reason.run_id == RUN
    # The earliest match is named, whatever order the candidates come in.
    reason = check_duplicate(own, [_facts(3), _facts(1), _facts(4)])
    assert reason is not None and reason.detail["invoice_id"] == str(_invoice(1))
    # Every part must match, and a missing part never makes two invoices equal.
    for other in (
        _facts(2, "INV-002"),
        _facts(2, total="100.01"),
        _facts(2, on="2026-09-21"),
    ):
        assert check_duplicate(own, [other]) is None
    no_date = _facts(5, on=None)
    assert check_duplicate(no_date, [_facts(2, on=None)]) is None
    assert check_duplicate(_facts(5, number="--"), [_facts(2, number="//")]) is None
    # Built from current values: a DI date and an admin's typed date agree.
    built = duplicate_facts(
        _invoice(6),
        _values(
            {
                "invoice_number": ("INV-001", None),
                "invoice_total": (Decimal("100.00"), None),
                "invoice_date": (date(2026, 9, 20), None),
            }
        ),
        phash=7,
    )
    assert built.fingerprint == ("INV001", Decimal("100.00"), "2026-09-20")
    assert (built.phash, built.run_id) == (7, RUN)
    assert duplicate_facts(_invoice(6), None).fingerprint is None

    # --- Phash duplicate: Hamming distance 8 flags, 9 does not -----------------------
    base = 0xF0F0_F0F0_F0F0_F0F0
    eight, nine = base ^ 0xFF, base ^ 0x1FF
    photo = _facts(5, "OTHER", phash=base)
    reason = check_duplicate(photo, [_facts(2, phash=eight)])
    assert reason is not None
    assert reason.detail == {"invoice_id": str(_invoice(2)), "basis": "phash"}
    assert reason.field_ids == ()
    assert check_duplicate(photo, [_facts(2, phash=nine)]) is None
    # Unsigned 64-bit values: the top bit set is one differing bit, not a sign.
    high = _facts(5, "OTHER", phash=1 << 63)
    assert check_duplicate(high, [_facts(2, phash=0)]) is not None
    assert check_duplicate(_facts(5, "OTHER"), [_facts(2, phash=base)]) is None

    # --- Self, later and rejected invoices never match -------------------------------
    assert check_duplicate(own, [_facts(5)]) is None
    assert check_duplicate(own, [_facts(9), _facts(6, phash=0)]) is None
    assert check_duplicate(own, [_facts(2, rejected=True)]) is None
    # Concurrent copies: the earlier never looks at the later, the later is flagged.
    first, second = _facts(1), _facts(2)
    assert check_duplicate(first, [second]) is None
    assert check_duplicate(second, [first]) is not None

    # --- Photo date: 0..30 days after the latest receipt, in Singapore time ----------
    assert check_photo_date(_at_singapore(RECEIVED), RECEIVED) is None
    assert check_photo_date(_at_singapore(date(2026, 10, 15)), RECEIVED) is None
    late = check_photo_date(_at_singapore(date(2026, 10, 16)), RECEIVED, run_id=RUN)
    assert late is not None and late.reason is ReasonCode.DATE_MISMATCH
    assert (late.detail, late.run_id) == ({"days": 31}, RUN)
    early = check_photo_date(_at_singapore(date(2026, 9, 14)), RECEIVED)
    assert early is not None and early.detail == {"days": -1}
    # 2026-09-14 20:00 UTC is 2026-09-15 04:00 in Singapore: the receipt day.
    assert check_photo_date(datetime(2026, 9, 14, 20, tzinfo=UTC), RECEIVED) is None
    assert check_photo_date(datetime(2026, 9, 14, 15, 59, tzinfo=UTC), RECEIVED)
    # No photo date (a PDF or scan): NO_PHOTO_DATE; no receipt: skipped.
    missing = check_photo_date(None, RECEIVED)
    assert missing is not None and missing.reason is ReasonCode.NO_PHOTO_DATE
    assert check_photo_date(None, None) is None
    assert check_photo_date(_at_singapore(date(2020, 1, 1)), None) is None

    # --- Bank: by fingerprint per bare field id --------------------------------------
    # Normalised before fingerprinting: spaces, hyphens and case never differ.
    printed_iban = "GB82 WEST-1234 5698 7654 32"
    iban = bank_fingerprint(HMAC_KEY, printed_iban)
    compact = printed_iban.replace(" ", "").replace("-", "").lower()
    assert iban == bank_fingerprint(HMAC_KEY, compact)
    swift = bank_fingerprint(HMAC_KEY, "WESTGB2L")
    account = bank_fingerprint(HMAC_KEY, "12345678")
    master = {"iban": iban, "swift": swift, "bank_account_number": account}
    same = _values({"payment[0].iban": (None, iban), "payment[1].swift": (None, swift)})
    assert check_bank(same, master) is None
    # A found field with no value has no fingerprint and is not compared.
    assert check_bank(_values({"payment[0].iban": (None, None)}), master) is None
    # A SWIFT holding the master's account number's fingerprint is still changed.
    moved = _values(
        {
            "payment[0].swift": (None, account),
            "payment[0].bank_account_number": (None, account),
        }
    )
    changed = check_bank(moved, master)
    assert changed is not None and changed.reason is ReasonCode.BANK_CHANGED
    assert changed.field_ids == ("payment[0].swift",)
    assert changed.run_id == RUN
    # A field the master has no value for is changed; non-bank fields are ignored.
    unknown = _values(
        {
            "payment[0].iban": (None, iban),
            "payment[0].bank_account_number": (None, account),
            "vendor_name": ("Synthetic Alpha", None),
        }
    )
    changed = check_bank(unknown, {"iban": iban})
    assert changed is not None
    assert changed.field_ids == ("payment[0].bank_account_number",)
    # Nothing but field ids is recorded: no fingerprint reaches the admin item.
    assert changed.detail == {}
