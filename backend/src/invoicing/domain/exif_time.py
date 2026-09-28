"""`photo_taken_at` from EXIF (AD-19): `DateTimeOriginal`, read as Singapore time
unless `OffsetTimeOriginal` gives the offset, stored as UTC."""

import re
from datetime import UTC, datetime, timedelta, timezone

# Singapore has kept UTC+8 without daylight saving since 1982, so a fixed offset is
# exact and needs no time-zone database on the host.
SINGAPORE = timezone(timedelta(hours=8), "SGT")

_DATE_TIME = re.compile(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})")
_MIN_OFFSET = timedelta(hours=-12)
_MAX_OFFSET = timedelta(hours=14)
# EXIF strings are NUL-padded; some writers also pad with spaces.
_PADDING = "\x00 "


def photo_taken_at(
    date_time_original: str | None, offset_time_original: str | None = None
) -> datetime | None:
    """The UTC instant a photo was taken, or None when `DateTimeOriginal` is absent,
    blank or malformed. A malformed offset is ignored (Singapore time is used)."""
    if date_time_original is None:
        return None
    match = _DATE_TIME.fullmatch(date_time_original.strip(_PADDING))
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    zone = _offset(offset_time_original) or SINGAPORE
    try:
        local = datetime(year, month, day, hour, minute, second, tzinfo=zone)
    except ValueError:
        # e.g. "0000:00:00 00:00:00", which cameras write for an unset clock.
        return None
    return local.astimezone(UTC)


def _offset(text: str | None) -> timezone | None:
    if text is None:
        return None
    match = _OFFSET.fullmatch(text.strip(_PADDING))
    if match is None:
        return None
    sign, hours, minutes = match.groups()
    if int(minutes) >= 60:
        return None
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    offset = -delta if sign == "-" else delta
    # Real offsets run from -12:00 to +14:00; anything else is malformed.
    if not _MIN_OFFSET <= offset <= _MAX_OFFSET:
        return None
    return timezone(offset)
