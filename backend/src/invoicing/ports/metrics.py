"""Custom metrics the alerts are built on (AD-17), and the port every emitter uses.

Application Insights keeps each metric's dimensions only because alerting on custom
metric dimensions is on (infra/modules/env-foundation). The alert rules themselves
arrive with the stories that emit the metrics (2.2, 2.3).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol


class MetricName(StrEnum):
    """The only metric names (AD-17 Alerts)."""

    # Emitted by each poison-queue trigger; alert when more than 0 in an hour.
    POISON_MESSAGE = "poison_message"
    # Emitted by the sweeper; alert when more than 0.
    STUCK_INVOICES = "stuck_invoices"
    # Emitted by the extract stage; alert at 80% of the environment's page cap.
    DI_PAGES_USED_PCT = "di_pages_used_pct"


# The dimensions each metric may carry. Anything else is dropped before export, so a
# field value can never become a dimension (security.md rule 31).
ALLOWED_DIMENSIONS: Mapping[MetricName, frozenset[str]] = {
    MetricName.POISON_MESSAGE: frozenset({"queue"}),
    MetricName.STUCK_INVOICES: frozenset(),
    MetricName.DI_PAGES_USED_PCT: frozenset(),
}


class MetricsPort(Protocol):
    """Records one value of an allow-listed custom metric."""

    def emit_metric(
        self,
        name: str,
        value: float,
        dimensions: Mapping[str, object] | None = None,
    ) -> None:
        """Record `value` for `name`. An unknown name raises ValueError; an unknown
        dimension key or an unsafe dimension value is dropped, never raised."""
        ...
