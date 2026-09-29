"""The strategies pre-registered in docs/RESEARCH.md, one class per hypothesis.

Each follows its published source as closely as closed 5-minute bars and a
next-bar-open fill allow. Times are minutes after 09:30 ET at which a bar
*ends*: the signal "at 15:30" is computed from the bar ending at 15:30 and
fills at the open of the bar starting then.

One deviation applies to every strategy that reverses: the backtest holds one
position at a time, so a reversal is an exit at the next open and an entry one
bar later, flat for five minutes in between.
"""

from __future__ import annotations

from collections import deque

from daybot.models import Action, Bar, Position, Side, Signal
from daybot.sessions import minutes_since_open
from daybot.strategy.base import Strategy
from daybot.strategy.vwap_reversion import session_vwap


def _end_minute(bars: list[Bar]) -> float:
    """Minutes after 09:30 at which the last bar ends."""
    length = (bars[1].start - bars[0].start).total_seconds() / 60.0 if len(bars) >= 2 else 5.0
    return minutes_since_open(bars[-1].start) + length


def _enter(side: Side, reason: str, **kw) -> Signal:
    return Signal(Action.ENTER_LONG if side is Side.LONG else Action.ENTER_SHORT, reason, **kw)


class IntradayMomentum(Strategy):
    """H1. Gao, Han, Li & Zhou (2018); Baltussen, Da, Lammers & Martens (2021).

    At 15:30, trade in the direction of the return from the previous close to
    10:00 (``window='first30'``) or to 15:30 (``window='rest'``), if it is at
    least ``threshold``. The position is held to the forced flatten."""

    name = "intraday_mom"
    ENTRY_MINUTE = 360  # 15:30

    def __init__(self, window: str = "first30", threshold: float = 0.0):
        if window not in ("first30", "rest"):
            raise ValueError("window must be 'first30' or 'rest'")
        self.window = window
        self.threshold = threshold
        self.prev_close: float | None = None
        self._done = False

    def params(self) -> dict:
        return {"window": self.window, "threshold": self.threshold}

    def reset(self) -> None:
        self._done = False

    def end_session(self, bars: list[Bar]) -> None:
        self.prev_close = bars[-1].close

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if position is not None or self._done or self.prev_close is None or not bars:
            return None
        if _end_minute(bars) != self.ENTRY_MINUTE:
            return None
        self._done = True
        if self.window == "first30":
            at_ten = [b for b in bars if minutes_since_open(b.start) == 25]
            if not at_ten:
                return None  # the 09:55 bar is missing; no signal rather than a guess
            ref = at_ten[0].close
        else:
            ref = bars[-1].close
        ret = ref / self.prev_close - 1
        if ret == 0 or abs(ret) < self.threshold:
            return None
        side = Side.LONG if ret > 0 else Side.SHORT
        return _enter(side, f"{self.window} return {ret:+.3%} since the previous close")


class NoiseAreaMomentum(Strategy):
    """H2. Zarattini, Aziz & Barbon (2024), "Beat the Market".

    The noise area at each time of day is the average absolute move from the
    open over the last ``lookback`` days, times ``vm``, around
    max/min(open, previous close). Checked at HH:00 and HH:30 only: a close
    above it goes long, below it short. The trailing stop is the current band
    (``stop='band'``) or max(band, VWAP) for longs, min for shorts
    (``stop='band_vwap'``); a close past the opposite band also reverses."""

    name = "noise_mom"

    def __init__(self, vm: float = 1.0, stop: str = "band_vwap", lookback: int = 14):
        if stop not in ("band", "band_vwap"):
            raise ValueError("stop must be 'band' or 'band_vwap'")
        if vm <= 0 or lookback < 1:
            raise ValueError("vm and lookback must be positive")
        self.vm = vm
        self.stop = stop
        self.lookback = lookback
        self.moves: deque[dict[float, float]] = deque(maxlen=lookback)
        self.prev_close: float | None = None
        self._reverse: Side | None = None

    def params(self) -> dict:
        return {"vm": self.vm, "stop": self.stop}

    def reset(self) -> None:
        self._reverse = None

    def end_session(self, bars: list[Bar]) -> None:
        opened = bars[0].open
        length = _end_minute(bars) - minutes_since_open(bars[-1].start)
        self.moves.append({minutes_since_open(b.start) + length: abs(b.close / opened - 1)
                           for b in bars})
        self.prev_close = bars[-1].close

    def sigma(self, minute: float) -> float | None:
        vals = [d[minute] for d in self.moves if minute in d]
        if len(self.moves) < self.lookback or len(vals) < self.lookback // 2 + 1:
            return None
        return sum(vals) / len(vals)

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if not bars or self.prev_close is None:
            return None
        if position is None and self._reverse is not None:
            side, self._reverse = self._reverse, None
            return _enter(side, "reversal across the noise area")
        minute = _end_minute(bars)
        if minute % 30 != 0:
            return None
        sig = self.sigma(minute)
        if sig is None:
            return None
        opened, close = bars[0].open, bars[-1].close
        upper = max(opened, self.prev_close) * (1 + self.vm * sig)
        lower = min(opened, self.prev_close) * (1 - self.vm * sig)
        if position is None:
            if close > upper:
                return _enter(Side.LONG, f"close {close:.2f} above noise area {upper:.2f}")
            if close < lower:
                return _enter(Side.SHORT, f"close {close:.2f} below noise area {lower:.2f}")
            return None
        vwap = session_vwap(bars) if self.stop == "band_vwap" else None
        if position.side is Side.LONG:
            stop = upper if vwap is None else max(upper, vwap)
            if close < stop:
                self._reverse = Side.SHORT if close < lower else None
                return Signal(Action.EXIT, f"close {close:.2f} under trailing stop {stop:.2f}")
        else:
            stop = lower if vwap is None else min(lower, vwap)
            if close > stop:
                self._reverse = Side.LONG if close > upper else None
                return Signal(Action.EXIT, f"close {close:.2f} over trailing stop {stop:.2f}")
        return None


class OpeningRange5(Strategy):
    """H3. Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?".

    At 09:35, trade in the direction of the first 5-minute candle (none if it
    closed where it opened), stop at its opposite extreme, target
    ``target_r`` times the risk."""

    name = "orb5"

    def __init__(self, target_r: float = 10.0):
        if target_r <= 0:
            raise ValueError("target_r must be positive")
        self.target_r = target_r
        self._done = False

    def params(self) -> dict:
        return {"target_r": self.target_r}

    def reset(self) -> None:
        self._done = False

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if self._done or position is not None or not bars:
            return None
        self._done = True
        first = bars[0]
        if len(bars) != 1 or minutes_since_open(first.start) != 0 or first.close == first.open:
            return None
        ref = first.close  # the next open is the fill; the close is the best estimate of it
        if first.close > first.open:
            risk = ref - first.low
            if risk <= 0:
                return None
            return _enter(Side.LONG, "first candle up", stop=first.low,
                          target=ref + self.target_r * risk)
        risk = first.high - ref
        if risk <= 0:
            return None
        return _enter(Side.SHORT, "first candle down", stop=first.high,
                      target=ref - self.target_r * risk)


class VwapTrend(Strategy):
    """H4. Zarattini & Aziz (2023), "VWAP: The Holy Grail".

    Every ``every`` minutes from 09:35: long above the session VWAP, short
    below; a cross reverses the position."""

    name = "vwap_trend"

    def __init__(self, every: int = 5):
        if every <= 0 or every % 5:
            raise ValueError("every must be a positive multiple of 5 minutes")
        self.every = every
        self._reverse: Side | None = None

    def params(self) -> dict:
        return {"every": self.every}

    def reset(self) -> None:
        self._reverse = None

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if not bars:
            return None
        if position is None and self._reverse is not None:
            side, self._reverse = self._reverse, None
            return _enter(side, "VWAP cross: reversing")
        if _end_minute(bars) % self.every != 0:
            return None
        vwap = session_vwap(bars)
        close = bars[-1].close
        if vwap is None or close == vwap:
            return None
        want = Side.LONG if close > vwap else Side.SHORT
        if position is None:
            return _enter(want, f"close {close:.2f} {'above' if want is Side.LONG else 'below'} "
                                f"VWAP {vwap:.2f}")
        if position.side is not want:
            self._reverse = want
            return Signal(Action.EXIT, f"close {close:.2f} crossed VWAP {vwap:.2f}")
        return None


class GapFade(Strategy):
    """H5. The retail "gap fill": if the open gaps at least ``gap`` from the
    previous close, at 09:35 trade against it, target the previous close,
    stop one gap-size beyond the entry."""

    name = "gap_fade"

    def __init__(self, gap: float = 0.005):
        if gap <= 0:
            raise ValueError("gap must be positive")
        self.gap = gap
        self.prev_close: float | None = None
        self._done = False

    def params(self) -> dict:
        return {"gap": self.gap}

    def reset(self) -> None:
        self._done = False

    def end_session(self, bars: list[Bar]) -> None:
        self.prev_close = bars[-1].close

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if self._done or position is not None or not bars or self.prev_close is None:
            return None
        self._done = True
        first = bars[0]
        if len(bars) != 1 or minutes_since_open(first.start) != 0:
            return None
        size = first.open - self.prev_close
        if abs(size) < self.gap * self.prev_close:
            return None
        ref = first.close
        if size > 0 and ref > self.prev_close:
            return _enter(Side.SHORT, f"fading a {size / self.prev_close:+.2%} gap",
                          stop=ref + size, target=self.prev_close)
        if size < 0 and ref < self.prev_close:
            return _enter(Side.LONG, f"fading a {size / self.prev_close:+.2%} gap",
                          stop=ref - size, target=self.prev_close)
        return None  # the first candle already filled the gap
