"""Deciding whether a backtest shows an edge.

The unit of observation is the *trading day*, not the trade. Trades on one
day share that day's market and are not independent, so testing per trade
overstates significance the same way splitting a mutually exclusive event's
legs across train and test did in the Kalshi bot. Every test here runs on the
daily P&L series, and every split is by whole days in time order.

The bar for "edge" is t >= 3 on held-out days, net of costs. A lower bar
passes noise: run enough parameter combinations and some will clear t = 2.
"""

from __future__ import annotations

import itertools
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Sequence

from daybot.backtest import BacktestResult, run_backtest
from daybot.strategy.base import Strategy

EDGE_T = 3.0


@dataclass(frozen=True)
class Summary:
    days: int
    trades: int
    net: float
    gross: float
    costs: float
    mean_daily: float
    std_daily: float
    t_stat: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    profit_factor: float

    @property
    def cost_drag(self) -> float:
        """Share of the gross result eaten by costs."""
        return self.costs / self.gross if self.gross > 0 else float("nan")

    @property
    def has_edge(self) -> bool:
        return self.t_stat >= EDGE_T and self.net > 0


def t_stat(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    if var <= 0:
        return 0.0 if mean == 0 else math.copysign(math.inf, mean)
    return mean / math.sqrt(var / n)


def summarize(result: BacktestResult) -> Summary:
    daily = list(result.daily_pnl.values())
    n = len(daily)
    mean = sum(daily) / n if n else 0.0
    std = math.sqrt(sum((d - mean) ** 2 for d in daily) / (n - 1)) if n > 1 else 0.0
    wins = [t.net for t in result.trades if t.net > 0]
    losses = [-t.net for t in result.trades if t.net < 0]
    peak = dd = cum = 0.0
    for d in daily:
        cum += d
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return Summary(
        days=n,
        trades=len(result.trades),
        net=result.net,
        gross=result.gross,
        costs=result.costs,
        mean_daily=mean,
        std_daily=std,
        t_stat=t_stat(daily),
        sharpe=(mean / std * math.sqrt(252)) if std > 0 else 0.0,
        max_drawdown=dd,
        win_rate=len(wins) / len(result.trades) if result.trades else 0.0,
        profit_factor=(sum(wins) / sum(losses)) if losses else (math.inf if wins else 0.0),
    )


def paired_t(a: "OrderedDict[date, float]", b: "OrderedDict[date, float]") -> float:
    """t-stat of the daily difference a - b over the days both cover. Used to
    ask whether a strategy beats a baseline, rather than whether it made
    money on a market that went up."""
    days = [d for d in a if d in b]
    return t_stat([a[d] - b[d] for d in days])


def split_days(sessions: OrderedDict, fractions=(0.6, 0.2, 0.2)):
    """Chronological train/validation/test split by whole days."""
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must sum to 1")
    days = list(sessions)
    n = len(days)
    a = int(n * fractions[0])
    b = a + int(n * fractions[1])
    pick = lambda ds: OrderedDict((d, sessions[d]) for d in ds)  # noqa: E731
    return pick(days[:a]), pick(days[a:b]), pick(days[b:])


@dataclass(frozen=True)
class SweepResult:
    params: dict
    validation: Summary
    test: Summary
    tried: int
    test_refusals: dict = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        if self.test.has_edge:
            return f"EDGE on held-out days (t={self.test.t_stat:.2f})"
        return (f"no edge: held-out t={self.test.t_stat:.2f} (need >= {EDGE_T}), "
                f"net ${self.test.net:,.2f}")


def sweep(
    sessions: OrderedDict,
    factory: Callable[..., Strategy],
    grid: dict[str, Sequence],
    **backtest_kwargs,
) -> SweepResult:
    """Try every parameter combination, choose on validation days only, and
    report the choice on test days it never saw.

    Selecting on test would turn the held-out split into a training signal;
    the test result below is the only number that estimates live performance.
    Train days are deliberately unused here: nothing is fitted, so the
    earliest days are kept out rather than spent, and remain available for a
    strategy that does fit something."""
    _, val, test = split_days(sessions)
    if not val or not test:
        raise ValueError(f"need more days to split: have {len(sessions)}")
    keys = list(grid)
    best = None
    tried = 0
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        tried += 1
        s = summarize(run_backtest(val, factory(**params), **backtest_kwargs))
        if best is None or s.t_stat > best[1].t_stat:
            best = (params, s)
    params, val_summary = best
    test_run = run_backtest(test, factory(**params), **backtest_kwargs)
    return SweepResult(params, val_summary, summarize(test_run), tried, dict(test_run.refusals))
