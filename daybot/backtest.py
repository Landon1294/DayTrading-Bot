"""Bar-by-bar backtester.

Three rules keep it honest, and each is the kind of thing that fails
silently -- a backtest with lookahead does not crash, it just looks great:

1. A strategy sees bar ``i`` only after it has closed, and whatever it asks
   for is filled at the *open of bar i+1*, never at the close it saw.
2. When a stop and a target are both inside one bar's range there is no way
   to know which traded first. The stop is assumed to have, always.
3. A price that gaps through a stop fills at the gap, not at the stop.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta

from daybot.config import RiskSettings
from daybot.costs import CostModel
from daybot.models import Action, Bar, Position, Side, Signal, Trade
from daybot.risk import RiskManager
from daybot.strategy.base import Strategy


@dataclass
class BacktestResult:
    trades: list[Trade]
    daily_pnl: "OrderedDict[date, float]"
    starting_equity: float
    refusals: dict[str, int] = field(default_factory=dict)

    @property
    def net(self) -> float:
        return sum(t.net for t in self.trades)

    @property
    def gross(self) -> float:
        return sum(t.gross for t in self.trades)

    @property
    def costs(self) -> float:
        return sum(t.costs for t in self.trades)


def run_backtest(
    sessions: "OrderedDict[date, list[Bar]]",
    strategy: Strategy,
    *,
    risk: RiskSettings | None = None,
    costs: CostModel | None = None,
    starting_equity: float = 10_000.0,
    apply_pdt: bool = True,
) -> BacktestResult:
    risk_settings = risk or RiskSettings()
    if not apply_pdt:
        from dataclasses import replace

        risk_settings = replace(risk_settings, pdt_equity_threshold=0.0)
    costs = costs or CostModel()
    rm = RiskManager(risk_settings)
    trades: list[Trade] = []
    daily: OrderedDict[date, float] = OrderedDict()
    refusals: dict[str, int] = {}
    equity = starting_equity

    for day, bars in sessions.items():
        strategy.reset()
        rm.start_day(day)
        day_trades = _run_session(bars, strategy, rm, costs, equity, refusals)
        trades.extend(day_trades)
        pnl = sum(t.net for t in day_trades)
        daily[day] = pnl
        equity += pnl

    return BacktestResult(trades, daily, starting_equity, refusals)


def _run_session(bars, strategy, rm: RiskManager, costs: CostModel, equity: float,
                 refusals: dict[str, int]) -> list[Trade]:
    out: list[Trade] = []
    position: Position | None = None
    pending: Signal | None = None
    bar_len = _bar_length(bars)

    def close(pos: Position, ref: float, when, reason: str, *, slip: bool = True) -> Trade:
        selling = pos.side is Side.LONG
        fill = costs.fill_price(ref, buying=not selling) if slip else ref
        exit_fees = costs.fees(fill, pos.qty, selling=selling)
        # Gross is measured between reference prices; every cost -- slippage
        # on both sides and fees on both sides -- lands in ``costs``, so the
        # report can say how much of the gross the costs ate.
        gross = pos.side.sign * (ref - pos.entry_price) * pos.qty
        cost = pos.entry_fees + abs(fill - ref) * pos.qty + exit_fees
        trade = Trade(pos.symbol, pos.side, pos.qty, pos.entry_time, pos.entry_price, when, ref,
                      reason, gross, cost)
        rm.record_trade(trade)
        out.append(trade)
        return trade

    for i, bar in enumerate(bars):
        # 1. Execute what the previous bar asked for, at this bar's open.
        if pending is not None:
            if pending.action is Action.EXIT and position is not None:
                close(position, bar.open, bar.start, pending.reason)
                position = None
            elif pending.side is not None and position is None and not rm.must_flatten(bar.start):
                decision = rm.check_entry(pending, bar.open, bar.start, equity=equity + rm.realized_today)
                if decision.ok:
                    buying = pending.side is Side.LONG
                    fill = costs.fill_price(bar.open, buying=buying)
                    # Entry costs: slippage now, plus sale fees if opening a short.
                    entry_cost = abs(fill - bar.open) * decision.qty + costs.fees(
                        fill, decision.qty, selling=not buying)
                    position = Position(bar.symbol, pending.side, decision.qty, bar.open, bar.start,
                                        stop=pending.stop, target=pending.target, entry_fees=entry_cost)
                    rm.record_entry()
                else:
                    key = decision.reason.split(":")[0]
                    refusals[key] = refusals.get(key, 0) + 1
            pending = None

        # 2. Forced flatten before the close.
        if position is not None and rm.must_flatten(bar.start):
            close(position, bar.open, bar.start, "flatten before close")
            position = None

        # 3. Stops and targets inside this bar. Stop first when both could hit.
        if position is not None:
            hit = _stop_or_target(position, bar)
            if hit is not None:
                ref, reason, slip = hit
                close(position, ref, bar.start + bar_len, reason, slip=slip)
                position = None

        # 4. The strategy sees the bar now that it has closed.
        if i < len(bars) - 1:
            pending = strategy.on_bar(bars[: i + 1], position)
            if pending is not None and pending.action is Action.EXIT and position is None:
                pending = None

    if position is not None:
        last = bars[-1]
        close(position, last.close, last.start + bar_len, "session end")
    return out


def _stop_or_target(pos: Position, bar: Bar):
    if pos.side is Side.LONG:
        if pos.stop is not None and bar.low <= pos.stop:
            return min(bar.open, pos.stop), "stop", True
        # A resting limit only fills if price trades *through* it.
        if pos.target is not None and bar.high > pos.target:
            return max(bar.open, pos.target), "target", False
    else:
        if pos.stop is not None and bar.high >= pos.stop:
            return max(bar.open, pos.stop), "stop", True
        if pos.target is not None and bar.low < pos.target:
            return min(bar.open, pos.target), "target", False
    return None


def _bar_length(bars: list[Bar]) -> timedelta:
    if len(bars) >= 2:
        return bars[1].start - bars[0].start
    return timedelta(minutes=1)
