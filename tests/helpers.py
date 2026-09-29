from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta

from daybot.models import Bar
from daybot.sessions import EASTERN

DAY = date(2024, 3, 4)  # a Monday


def et(day: date, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=EASTERN)


def make_bars(ohlc: list[tuple[float, float, float, float]], *, day: date = DAY,
              start: tuple[int, int] = (9, 30), minutes: int = 5, symbol: str = "TST") -> list[Bar]:
    t0 = et(day, *start)
    return [Bar(symbol, t0 + timedelta(minutes=minutes * i), o, h, l, c, 1000.0)
            for i, (o, h, l, c) in enumerate(ohlc)]


def flat_day(price: float = 100.0, n: int = 78, **kw) -> list[Bar]:
    return make_bars([(price, price, price, price)] * n, **kw)


def sessions_of(*days: list[Bar]) -> "OrderedDict[date, list[Bar]]":
    from daybot.sessions import to_eastern

    return OrderedDict((to_eastern(b[0].start).date(), b) for b in days)
