"""The risk gate. Shared verbatim by the backtester and the live loop, so a
limit that binds in simulation binds identically with real money."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from daybot.config import RiskSettings
from daybot.models import Signal, Side, Trade
from daybot.sessions import REGULAR_CLOSE, EASTERN, to_eastern


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str
    qty: int = 0


@dataclass
class RiskManager:
    settings: RiskSettings
    day: date | None = None
    realized_today: float = 0.0
    trades_today: int = 0
    halted: bool = False
    halt_reason: str = ""
    day_trade_dates: list[date] = field(default_factory=list)
    # Today's close. None means 16:00 ET; early closes (13:00) must be set.
    session_close: datetime | None = None

    def start_day(self, d: date, *, realized: float = 0.0,
                  close: datetime | None = None) -> None:
        """Reset the per-day counters. ``realized`` seeds the day's P&L from
        an outside source (the broker's equity change) so a restart does not
        forget losses already taken. ``close`` is the day's scheduled close
        when it is not 16:00 ET."""
        self.day = d
        self.session_close = close
        self.realized_today = realized
        self.trades_today = 0
        self.halted = False
        self.halt_reason = ""

    # -- sizing ---------------------------------------------------------

    def size(self, signal: Signal, price: float, *, buying_power: float | None = None) -> int:
        s = self.settings
        caps = [math.floor(s.max_position_notional / price)]
        if signal.stop is not None:
            per_share = abs(price - signal.stop)
            if per_share <= 0:
                return 0
            caps.append(math.floor(s.risk_per_trade / per_share))
        if buying_power is not None:
            caps.append(math.floor(buying_power / price))
        return max(0, min(caps))

    # -- the gate -------------------------------------------------------

    def check_entry(
        self,
        signal: Signal,
        price: float,
        now: datetime,
        *,
        equity: float,
        unrealized: float = 0.0,
        buying_power: float | None = None,
        broker_day_trades: int | None = None,
    ) -> Decision:
        s = self.settings
        if self.halted:
            return Decision(False, f"halted: {self.halt_reason}")
        if signal.side is None:
            return Decision(False, "not an entry signal")
        if signal.side is Side.SHORT and not s.allow_short:
            return Decision(False, "shorting disabled")
        if equity < s.min_equity:
            return Decision(False, f"equity ${equity:,.2f} below floor ${s.min_equity:,.2f}")
        # Gate on the accumulated figure, not only on the halt flag.
        day_pnl = self.realized_today + unrealized
        if day_pnl <= -s.max_daily_loss:
            self._halt(f"daily loss ${-day_pnl:,.2f} reached limit ${s.max_daily_loss:,.2f}")
            return Decision(False, f"halted: {self.halt_reason}")
        if self.trades_today >= s.max_trades_per_day:
            return Decision(False, f"max {s.max_trades_per_day} trades/day reached")
        if self._minutes_to_close(now) < s.no_entry_minutes_before_close:
            return Decision(False, "too close to the close for a new entry")
        if s.pdt_equity_threshold > 0 and equity < s.pdt_equity_threshold:
            # The broker's own count, when it reports one, can only raise ours:
            # it sees trades this process never made.
            used = max(self.day_trades_in_window(to_eastern(now).date()), broker_day_trades or 0)
            if used >= s.max_day_trades_per_5d:
                return Decision(
                    False,
                    f"pattern-day-trader limit: {used} day trades in window, equity under "
                    f"${s.pdt_equity_threshold:,.0f}",
                )
        if signal.stop is not None:
            wrong_side = (signal.side is Side.LONG and signal.stop >= price) or (
                signal.side is Side.SHORT and signal.stop <= price
            )
            if wrong_side:
                return Decision(False, f"stop {signal.stop:.4f} is on the wrong side of {price:.4f}")
        qty = self.size(signal, price, buying_power=buying_power)
        if qty < 1:
            return Decision(False, "size rounds to zero shares")
        return Decision(True, "ok", qty)

    def must_flatten(self, now: datetime) -> bool:
        return self._minutes_to_close(now) <= self.settings.flatten_minutes_before_close

    # -- bookkeeping ----------------------------------------------------

    def record_entry(self) -> None:
        self.trades_today += 1

    def record_trade(self, trade: Trade) -> None:
        self.realized_today += trade.net
        if trade.is_day_trade:
            self.day_trade_dates.append(trade.session_date)
        if self.realized_today <= -self.settings.max_daily_loss:
            self._halt(
                f"daily loss ${-self.realized_today:,.2f} reached limit "
                f"${self.settings.max_daily_loss:,.2f}"
            )

    def day_trades_in_window(self, today: date) -> int:
        """Day trades in the rolling window ending today.

        The rule counts five *business* days. Holidays are not modelled, so
        the window looks back six weekdays: it can only over-count, which
        blocks a trade that was allowed, never the reverse."""
        start = today
        weekdays = 1
        while weekdays < 6:
            start -= timedelta(days=1)
            if start.weekday() < 5:
                weekdays += 1
        return sum(1 for d in self.day_trade_dates if start <= d <= today)

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason

    def _minutes_to_close(self, now: datetime) -> float:
        et = to_eastern(now)
        close = datetime.combine(et.date(), REGULAR_CLOSE, tzinfo=EASTERN)
        if self.session_close is not None and to_eastern(self.session_close).date() == et.date():
            close = min(close, to_eastern(self.session_close))
        return (close - et).total_seconds() / 60.0
