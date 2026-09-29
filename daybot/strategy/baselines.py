"""Strategies with no skill, which every real strategy is measured against.

A strategy that cannot beat these after costs has no edge, however good its
equity curve looks on its own.
"""

from __future__ import annotations

import random

from daybot.models import Action, Bar, Position, Signal
from daybot.strategy.base import Strategy


class BuyOpen(Strategy):
    """Long at the open, flat at the forced close. Captures the intraday drift
    and nothing else, so beating it means beating simply being long."""

    name = "buy_open"

    def __init__(self):
        self._done = False

    def reset(self) -> None:
        self._done = False

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if self._done or position is not None:
            return None
        self._done = True
        return Signal(Action.ENTER_LONG, "baseline: long from the open")


class RandomEntry(Strategy):
    """Enters at a random bar with a symmetric stop and target. Its expected
    result is minus the costs, which makes it the null a real signal has to
    separate from."""

    name = "random"

    def __init__(self, seed: int = 0, probability: float = 0.05, width: float = 0.003):
        self._rng = random.Random(seed)
        self.probability = probability
        self.width = width
        self._done = False

    def reset(self) -> None:
        self._done = False

    def on_bar(self, bars: list[Bar], position: Position | None) -> Signal | None:
        if self._done or position is not None or self._rng.random() > self.probability:
            return None
        self._done = True
        px = bars[-1].close
        return Signal(Action.ENTER_LONG, "baseline: random entry",
                      stop=px * (1 - self.width), target=px * (1 + self.width))
