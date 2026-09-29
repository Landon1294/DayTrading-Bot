"""Synthetic intraday bars with a *known* amount of structure.

These exist to test the machinery, never to estimate profits:

- ``momentum=0``: a driftless random walk. Nothing can be predicted, so every
  strategy must come out with no edge. If one does, the backtester is broken.
- ``momentum>0``: bar returns are positively autocorrelated, so trends
  persist. A breakout strategy should find that, which shows the pipeline can
  detect an effect when one is really there.

Any profit on synthetic data was put there by the parameters.
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from datetime import date, datetime, timedelta

from daybot.models import Bar
from daybot.sessions import EASTERN, REGULAR_OPEN


def trading_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def generate_sessions(
    days: int,
    *,
    symbol: str = "SYN",
    bar_minutes: int = 5,
    start_price: float = 100.0,
    daily_vol: float = 0.012,
    momentum: float = 0.0,
    seed: int = 0,
    start: date = date(2024, 1, 2),
) -> "OrderedDict[date, list[Bar]]":
    if not 0 <= momentum < 1:
        raise ValueError("momentum must be in [0, 1)")
    rng = random.Random(seed)
    bars_per_day = 390 // bar_minutes
    steps = 5  # sub-steps per bar, for a realistic high/low
    # Scale innovations so the unconditional per-bar variance is unchanged by
    # momentum: an AR(1) with coefficient m has variance s^2 / (1 - m^2).
    bar_sigma = daily_vol / math.sqrt(bars_per_day) * math.sqrt(1 - momentum ** 2)
    step_sigma = bar_sigma / math.sqrt(steps)
    price = start_price
    out: OrderedDict[date, list[Bar]] = OrderedDict()
    for day in trading_days(start, days):
        price *= math.exp(rng.gauss(0, daily_vol * 0.3))  # overnight gap
        prev = 0.0
        bars = []
        t0 = datetime.combine(day, REGULAR_OPEN, tzinfo=EASTERN)
        for i in range(bars_per_day):
            drift = momentum * prev
            o = price
            hi = lo = price
            p = price
            for _ in range(steps):
                p *= math.exp(drift / steps + rng.gauss(0, step_sigma))
                hi, lo = max(hi, p), min(lo, p)
            prev = math.log(p / o)
            price = p
            bars.append(Bar(symbol, t0 + timedelta(minutes=bar_minutes * i), o, hi, lo, p,
                            volume=rng.uniform(5e4, 2e5)))
        out[day] = bars
    return out
