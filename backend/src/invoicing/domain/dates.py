"""The business day (spine: Dates): "today" is the Singapore date, whatever the
server's or the timer's time zone."""

from datetime import date, datetime

from invoicing.domain.exif_time import SINGAPORE


def singapore_date(now: datetime) -> date:
    """The Singapore date at the aware instant `now`."""
    return now.astimezone(SINGAPORE).date()
