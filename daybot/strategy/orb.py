"""Opening-range breakout: a momentum hypothesis.

Record the high and low of the first ``range_minutes`` of the session. A
close outside that range is taken as the start of a trend: enter in its
direction, stop on the far side of the range, target a multiple of the risk.
At most one entry per session.
"""

from __future__ import annotations

from daybot.models import Action, Bar, Position, Signal
from daybot.sessions import minutes_since_open
from daybot.strategy.base import Strategy


class OpeningRangeBreakout(Strategy):
    name = "orb"

    def __init__(self, range_minutes: int = 30, target_r: float = 2.0, allow_short: bool = False):
        if range_minutes <= 0 or target_r <= 0:
            raise ValueError("range_minutes and target_r must be positive")
        self.range_minutes = range_minutes
        self.target_r = target_r
        self.allow_short = allow_short
        self._traded = False

    def params(self) -> dict:
        return {"range_minutes": self.range_minutes, "target_r": self.target_r}

    def reset(self) -> None:
        self._traded = False

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if position is not None or self._traded or not bars:
            return None
        last = bars[-1]
        bar_len = _bar_minutes(bars)
        # The range is complete once a bar *ending* at or after range_minutes
        # has closed; the first bar outside it is the earliest a breakout can
        # be observed.
        in_range = [b for b in bars if minutes_since_open(b.start) + bar_len <= self.range_minutes]
        if len(in_range) == len(bars) or not in_range:
            return None
        hi = max(b.high for b in in_range)
        lo = min(b.low for b in in_range)
        risk = hi - lo
        if risk <= 0:
            return None
        if last.close > hi:
            self._traded = True
            return Signal(Action.ENTER_LONG, f"close {last.close:.2f} broke range high {hi:.2f}",
                          stop=lo, target=last.close + self.target_r * (last.close - lo))
        if self.allow_short and last.close < lo:
            self._traded = True
            return Signal(Action.ENTER_SHORT, f"close {last.close:.2f} broke range low {lo:.2f}",
                          stop=hi, target=last.close - self.target_r * (hi - last.close))
        return None


def _bar_minutes(bars: list[Bar]) -> float:
    if len(bars) >= 2:
        return (bars[1].start - bars[0].start).total_seconds() / 60.0
    return 1.0
