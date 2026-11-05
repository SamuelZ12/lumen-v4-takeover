"""Fake-clock timestamps: UTC, minute-or-better precision, ISO 8601 with a Z suffix."""

import re
from datetime import datetime, timedelta, timezone

_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_RELATIVE = re.compile(r"^(?P<sign>[-+])(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?$")


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, _FORMAT).replace(tzinfo=timezone.utc)


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(_FORMAT)


def parse_offset(value: str) -> timedelta:
    """Parse a spec-relative offset such as ``-7h`` or ``-5h20m``."""
    match = _RELATIVE.match(value)
    if not match or not (match["h"] or match["m"]):
        raise ValueError(f"invalid relative time {value!r}; expected e.g. -5h20m")
    delta = timedelta(hours=int(match["h"] or 0), minutes=int(match["m"] or 0))
    return -delta if match["sign"] == "-" else delta
