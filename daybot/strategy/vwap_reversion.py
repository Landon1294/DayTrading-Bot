"""VWAP reversion: the opposite hypothesis to the breakout.

If intraday moves mean-revert, a price stretched below the session VWAP
should drift back toward it. Enter long when the close is ``band`` below
VWAP, target VWAP itself, stop a further ``stop_mult`` bands away.

Having both a momentum and a reversion strategy is intentional: on a market
with no structure they should both fail, and a backtest that makes both look
good at once is a sign of a bug, not of two edges.
"""

from __future__ import annotations

from daybot.models import Action, Bar, Position, Signal
from daybot.sessions import minutes_since_open
from daybot.strategy.base import Strategy


def session_vwap(bars: list[Bar]) -> float | None:
    num = den = 0.0
    for b in bars:
        typical = b.vwap if b.vwap is not None else (b.high + b.low + b.close) / 3.0
        num += typical * b.volume
        den += b.volume
    return num / den if den > 0 else None


class VwapReversion(Strategy):
    name = "vwap"

    def __init__(self, band: float = 0.004, stop_mult: float = 1.0, warmup_minutes: int = 30,
                 max_entries: int = 2):
        self.band = band
        self.stop_mult = stop_mult
        self.warmup_minutes = warmup_minutes
        self.max_entries = max_entries
        self._entries = 0

    def params(self) -> dict:
        return {"band": self.band, "stop_mult": self.stop_mult, "warmup_minutes": self.warmup_minutes}

    def reset(self) -> None:
        self._entries = 0

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if not bars:
            return None
        last = bars[-1]
        vwap = session_vwap(bars)
        if vwap is None:
            return None
        if position is not None:
            if last.close >= vwap:
                return Signal(Action.EXIT, f"reverted to VWAP {vwap:.2f}")
            return None
        if self._entries >= self.max_entries or minutes_since_open(last.start) < self.warmup_minutes:
            return None
        if last.close < vwap * (1 - self.band):
            self._entries += 1
            stop = last.close * (1 - self.band * self.stop_mult)
            return Signal(Action.ENTER_LONG, f"close {last.close:.2f} is {self.band:.2%} under VWAP {vwap:.2f}",
                          stop=stop, target=vwap)
        return None
