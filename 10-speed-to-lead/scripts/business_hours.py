"""Business-hours math for Slack pings.

Pings go out only Monday-Friday 09:00-17:00 America/New_York.
A reply that lands inside the window gets pings at +0 and +5 minutes.
Any ping time outside the window moves to the next window opening
(09:00 the next business day, or 09:00 today if it is before 09:00 on a weekday),
keeping the 5 minute gap. US holidays are not skipped.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
START_HOUR, END_HOUR = 9, 17
GAP = dt.timedelta(minutes=5)


def in_window(t: dt.datetime, tz: ZoneInfo = TZ) -> bool:
    local = t.astimezone(tz)
    if local.weekday() >= 5:
        return False
    start = local.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    end = local.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)
    return start <= local < end


def next_open(t: dt.datetime, tz: ZoneInfo = TZ) -> dt.datetime:
    """The next moment the window opens at or after t (returns t itself if already open)."""
    if in_window(t, tz):
        return t
    local = t.astimezone(tz)
    day = local.date()
    if local.weekday() < 5 and local.hour < START_HOUR:
        candidate = day
    else:
        candidate = day + dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += dt.timedelta(days=1)
    return dt.datetime(candidate.year, candidate.month, candidate.day, START_HOUR, 0, tzinfo=tz)


def ping_times(received: dt.datetime, count: int = 2, tz: ZoneInfo = TZ) -> list[dt.datetime]:
    """Times (aware, in tz) for up to `count` pings, 5 minutes apart, all inside the window."""
    if received.tzinfo is None:
        raise ValueError("received must be timezone-aware")
    out = []
    t = next_open(received, tz)
    for _ in range(count):
        t = next_open(t, tz)
        out.append(t.astimezone(tz))
        t = t + GAP
    return out
