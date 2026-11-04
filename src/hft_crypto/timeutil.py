"""UTC time helpers. Internally, instants are integer microseconds since the Unix epoch."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator

UTC = dt.UTC
MICROS_PER_SECOND = 1_000_000
MICROS_PER_MINUTE = 60 * MICROS_PER_SECOND
MICROS_PER_DAY = 86_400 * MICROS_PER_SECOND
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")
_DURATION_UNITS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def to_us(moment: dt.datetime) -> int:
    """Convert an aware datetime to integer microseconds without going through a float."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime refused: all project time is UTC")
    delta = moment - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * MICROS_PER_SECOND + delta.microseconds


def from_us(value: int) -> dt.datetime:
    return _EPOCH + dt.timedelta(microseconds=value)


def day_start_us(day: dt.date) -> int:
    return to_us(dt.datetime(day.year, day.month, day.day, tzinfo=UTC))


def date_of_us(value: int) -> dt.date:
    return from_us(value).date()


def iso(moment: dt.datetime) -> str:
    """Render as ISO 8601 UTC with a Z suffix."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def iso_us(value: int) -> str:
    return iso(from_us(value))


def parse_iso(text: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without a timezone: {text}")
    return parsed.astimezone(UTC)


def parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def date_range(first: dt.date, last: dt.date) -> Iterator[dt.date]:
    """Yield each date from first to last, both included."""
    current = first
    while current <= last:
        yield current
        current += dt.timedelta(days=1)


def month_starts(first: dt.date, last: dt.date) -> Iterator[dt.date]:
    """Yield the first day of each month touching the range, both ends included."""
    current = first.replace(day=1)
    while current <= last:
        yield current
        current = next_month(current)


def next_month(month_start: dt.date) -> dt.date:
    if month_start.month == 12:
        return dt.date(month_start.year + 1, 1, 1)
    return dt.date(month_start.year, month_start.month + 1, 1)


def month_key(day: dt.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def parse_duration(text: str) -> float:
    """Parse a duration such as 90, 90s, 50m or 1.5h into seconds."""
    match = _DURATION.match(text)
    if match is None:
        raise ValueError(f"cannot read duration: {text!r}")
    return float(match.group(1)) * _DURATION_UNITS[match.group(2)]


def decimal_seconds_to_us(text: str) -> int:
    """Convert a decimal seconds string such as 1700000000.1234 to microseconds, flooring.

    Done on the digits, because a binary float cannot hold this many significant digits exactly and a
    rounding error near a minute boundary would move a trade into the wrong bar.
    """
    negative = text.startswith("-")
    body = text[1:] if negative else text
    whole, _, fraction = body.partition(".")
    if not whole.isdigit() or (fraction and not fraction.isdigit()):
        raise ValueError(f"not a decimal seconds value: {text!r}")
    micros = int(whole) * MICROS_PER_SECOND + int((fraction + "000000")[:6])
    return -micros if negative else micros
