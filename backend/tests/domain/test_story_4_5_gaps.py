"""Story 4.5 (CAP-19): the delivery gaps in days, computed in the domain. One test
(the 200-case cap, coding-style.md rule 20 exception): each plan matrix gap row is an
assertion."""

from datetime import date

from invoicing.domain.deliveries import DeliveryGaps, delivery_gaps


def test_story_4_5_gaps() -> None:
    """Late and received; early; not received (gaps with a missing date are None)."""
    # Late, received: promised 1 Sep, delivered 4 Sep, received 5 Sep.
    assert delivery_gaps(
        date(2026, 9, 1), date(2026, 9, 4), date(2026, 9, 5)
    ) == DeliveryGaps(days_late=3, days_to_receive=1, days_overall=4)
    # Early: promised 10 Sep, delivered 8 Sep, received the same day.
    assert delivery_gaps(
        date(2026, 9, 10), date(2026, 9, 8), date(2026, 9, 8)
    ) == DeliveryGaps(days_late=-2, days_to_receive=0, days_overall=-2)
    # Not received: no goods receipt yet.
    assert delivery_gaps(date(2026, 9, 1), date(2026, 9, 1), None) == DeliveryGaps(
        days_late=0, days_to_receive=None, days_overall=None
    )
