"""Time parsing and formatting helpers.

All times are integer milliseconds.  LRC output uses ``mm:ss.mmm``.  Minutes
are allowed to exceed 99 for unusually long tracks.
"""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"^\s*(\d{1,4})\s*:\s*(\d{1,2})(?:\s*[.:]\s*(\d{1,3}))?\s*$")


def time_to_ms(minutes: int | str, seconds: int | str, fraction: int | str | None = None) -> int:
    """Convert LRC time components to milliseconds.

    A two-digit fraction is interpreted as centiseconds (``.50`` -> 500 ms),
    as required by the LRC specification; one digit is tenths and three digits
    are milliseconds.
    """
    minutes_i = int(minutes)
    seconds_i = int(seconds)
    if fraction is None or fraction == "":
        ms = 0
    else:
        frac = str(fraction).strip()
        if len(frac) == 1:
            ms = int(frac) * 100
        elif len(frac) == 2:
            ms = int(frac) * 10
        else:
            ms = int(frac[:3])
    return (minutes_i * 60 + seconds_i) * 1000 + ms


def parse_timestamp(value: str) -> int | None:
    """Parse ``mm:ss``, ``mm:ss.xx``, ``mm:ss.xxx`` or ``mm:ss:xx``."""
    match = _TIME_RE.match(value)
    if not match:
        return None
    return time_to_ms(*match.groups())


def format_timestamp(ms: int, digits: int = 3) -> str:
    """Format milliseconds as ``mm:ss.mmm`` (or ``mm:ss.xx``)."""
    if ms < 0:
        ms = 0
    total_seconds, millis = divmod(int(ms), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    if digits == 2:
        return f"{minutes:02d}:{seconds:02d}.{millis // 10:02d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_lrc_tag(ms: int, digits: int = 3) -> str:
    return f"[{format_timestamp(ms, digits)}]"


def clamp_time(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, int(value))
