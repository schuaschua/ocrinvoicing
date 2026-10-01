"""Delivery gaps (Story 4.5, CAP-19, FR19): where a supplier's delays come from,
in whole days between a delivery's promised, delivered and received dates. Computed
here, never in the browser."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DeliveryGaps:
    """`days_late` is delivered − promised (positive: late, negative: early),
    `days_to_receive` received − delivered, `days_overall` received − promised; each
    None when one of its dates is missing."""

    days_late: int | None
    days_to_receive: int | None
    days_overall: int | None


def _days(later: date | None, earlier: date | None) -> int | None:
    if later is None or earlier is None:
        return None
    return (later - earlier).days


def delivery_gaps(
    promised: date | None, delivered: date | None, received: date | None
) -> DeliveryGaps:
    """The three gaps in days between a delivery's dates."""
    return DeliveryGaps(
        days_late=_days(delivered, promised),
        days_to_receive=_days(received, delivered),
        days_overall=_days(received, promised),
    )
