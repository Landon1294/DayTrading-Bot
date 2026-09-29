"""US equity session times, always reasoned about in America/New_York.

Everything the exchange does is scheduled in Eastern time, including across
daylight-saving changes, so converting to UTC and comparing against fixed
hours is wrong for half the year.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def to_eastern(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError(f"naive datetime {ts!r}; every timestamp must carry a zone")
    return ts.astimezone(EASTERN)


def in_regular_session(bar_start: datetime, bar_minutes: int) -> bool:
    """True if the whole bar lies inside 09:30-16:00 ET."""
    et = to_eastern(bar_start)
    end = et + timedelta(minutes=bar_minutes)
    return et.time() >= REGULAR_OPEN and (end.time() <= REGULAR_CLOSE and end.date() == et.date())


def minutes_since_open(ts: datetime) -> float:
    et = to_eastern(ts)
    opened = datetime.combine(et.date(), REGULAR_OPEN, tzinfo=EASTERN)
    return (et - opened).total_seconds() / 60.0


def group_sessions(bars: Iterable, bar_minutes: int) -> "OrderedDict[date, list]":
    """Split bars into regular-session days, dropping pre/post-market bars.

    Days are the unit of independence for everything statistical here, the
    way events were for the Kalshi bot: bars within a day are strongly
    dependent, so anything that splits or resamples must do it by day."""
    out: OrderedDict[date, list] = OrderedDict()
    for bar in sorted(bars, key=lambda b: b.start):
        if not in_regular_session(bar.start, bar_minutes):
            continue
        out.setdefault(to_eastern(bar.start).date(), []).append(bar)
    return out
