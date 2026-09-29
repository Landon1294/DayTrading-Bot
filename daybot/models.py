"""Plain data types shared by the backtester, the risk gate and the live loop.

Prices are floats in dollars. That is deliberate and different from an
arbitrage bot: nothing here depends on an exact sum of prices, and every
price that leaves the process is rounded onto the exchange tick by
``round_to_tick`` first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. ``start`` is the *beginning* of the bar, so a 5-minute
    bar stamped 09:30 is not known until 09:35. Most vendors label bars this
    way, but not all: data labelled on the right edge must be shifted back on
    load, or every bar is seen five minutes before it happened."""

    symbol: str
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trades: int | None = None

    @property
    def session_date(self) -> date:
        from daybot.sessions import to_eastern

        return to_eastern(self.start).date()


class Action(str, Enum):
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    EXIT = "exit"


@dataclass(frozen=True)
class Signal:
    """What a strategy wants. It is a request, not an order: the risk gate
    sizes it and may refuse it, and a human approves it before it is sent."""

    action: Action
    reason: str
    stop: float | None = None
    target: float | None = None

    @property
    def side(self) -> Side | None:
        if self.action is Action.ENTER_LONG:
            return Side.LONG
        if self.action is Action.ENTER_SHORT:
            return Side.SHORT
        return None


@dataclass
class Position:
    symbol: str
    side: Side
    qty: int
    entry_price: float
    entry_time: datetime
    stop: float | None = None
    target: float | None = None
    # Everything paid to open: entry slippage, plus sale fees on a short.
    entry_fees: float = 0.0

    def unrealized(self, price: float) -> float:
        return self.side.sign * (price - self.entry_price) * self.qty


@dataclass(frozen=True)
class Trade:
    """A completed round trip. ``net`` is after slippage and fees."""

    symbol: str
    side: Side
    qty: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: str
    gross: float
    costs: float

    @property
    def net(self) -> float:
        return self.gross - self.costs

    @property
    def session_date(self) -> date:
        from daybot.sessions import to_eastern

        return to_eastern(self.entry_time).date()

    @property
    def is_day_trade(self) -> bool:
        from daybot.sessions import to_eastern

        return to_eastern(self.entry_time).date() == to_eastern(self.exit_time).date()


@dataclass
class Account:
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    trading_blocked: bool = False
    account_blocked: bool = False
    status: str = "ACTIVE"
    # Not in Alpaca's current spec. None means unknown, never zero.
    daytrade_count: int | None = None
    raw: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Clock:
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime


def tick_size(price: float) -> Decimal:
    """Reg NMS sub-penny rule: $0.01 at or above $1.00, $0.0001 below."""
    return Decimal("0.01") if price >= 1.0 else Decimal("0.0001")


def round_to_tick(price: float, *, direction: str) -> Decimal:
    """Round onto the legal tick. ``direction`` must be stated because the
    safe rounding differs by use: a buy limit rounds down (never pay more
    than intended), a protective sell stop rounds up (never give back more
    than intended). There is no default so the choice cannot be skipped."""
    tick = tick_size(price)
    rounding = {"down": ROUND_FLOOR, "up": ROUND_CEILING}[direction]
    return (Decimal(str(price)) / tick).to_integral_value(rounding=rounding) * tick
