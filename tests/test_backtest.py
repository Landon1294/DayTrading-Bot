"""The backtester's honesty rules, each checked on hand-built bars where the
right answer can be worked out on paper."""

import pytest

from daybot.backtest import run_backtest
from daybot.config import RiskSettings
from daybot.costs import CostModel
from daybot.models import Action, Signal
from daybot.strategy.base import Strategy
from tests.helpers import make_bars, sessions_of

FREE = CostModel(slippage_bps=0, sec_fee_rate=0, finra_taf_per_share=0)
WIDE = RiskSettings(risk_per_trade=1_000, max_position_notional=10_000, pdt_equity_threshold=0)


class Scripted(Strategy):
    """Emits a given signal after seeing bar ``at`` (0-based), and records how
    many bars it was shown each time -- which is how lookahead is caught."""

    def __init__(self, at: int, signal: Signal, exit_at: int | None = None):
        self.at, self.signal, self.exit_at = at, signal, exit_at
        self.seen: list[int] = []

    def on_bar(self, bars, position):
        self.seen.append(len(bars))
        i = len(bars) - 1
        if i == self.at and position is None:
            return self.signal
        if self.exit_at is not None and i == self.exit_at and position is not None:
            return Signal(Action.EXIT, "scripted exit")
        return None


def pad(ohlc, n=78, price=None):
    """Fill the rest of the session with flat bars at the last close."""
    last = price if price is not None else ohlc[-1][3]
    return ohlc + [(last, last, last, last)] * (n - len(ohlc))


def run(bars, strat, **kw):
    kw.setdefault("costs", FREE)
    kw.setdefault("risk", WIDE)
    return run_backtest(sessions_of(bars), strat, **kw)


def test_signal_fills_at_next_open_not_at_close():
    bars = make_bars(pad([(100, 100, 100, 100), (100, 101, 100, 101), (105, 106, 105, 106)]))
    strat = Scripted(1, Signal(Action.ENTER_LONG, "go"))
    r = run(bars, strat)
    assert r.trades[0].entry_price == 105  # bar 2's open, not bar 1's 101 close
    assert r.trades[0].entry_time == bars[2].start


def test_strategy_only_ever_sees_closed_bars():
    bars = make_bars(pad([(100, 100, 100, 100)]))
    strat = Scripted(-1, Signal(Action.ENTER_LONG, "never"))
    run(bars, strat)
    assert strat.seen == list(range(1, len(bars)))  # 1, 2, ..., n-1: never the future


def test_stop_wins_when_stop_and_target_share_a_bar():
    bars = make_bars(pad([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 97, 100)]))
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go", stop=98, target=102)))
    t = r.trades[0]
    assert (t.exit_reason, t.exit_price) == ("stop", 98)


def test_gap_through_stop_fills_at_the_gap():
    bars = make_bars(pad([(100, 100, 100, 100), (100, 100, 100, 100), (95, 96, 94, 95)]))
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go", stop=98)))
    assert r.trades[0].exit_price == 95


def test_target_needs_price_to_trade_through():
    touch = make_bars(pad([(100, 100, 100, 100), (100, 102, 100, 101)]))
    r = run(touch, Scripted(0, Signal(Action.ENTER_LONG, "go", target=102)))
    assert r.trades[0].exit_reason != "target"
    through = make_bars(pad([(100, 100, 100, 100), (100, 102.5, 100, 101)]))
    r = run(through, Scripted(0, Signal(Action.ENTER_LONG, "go", target=102)))
    assert (r.trades[0].exit_reason, r.trades[0].exit_price) == ("target", 102)


def test_forced_flatten_before_close():
    bars = make_bars(pad([(100, 100, 100, 100)]))
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go")))
    t = r.trades[0]
    assert t.exit_reason == "flatten before close"
    assert (t.exit_time.hour, t.exit_time.minute) == (15, 55)


def test_session_that_ends_early_still_closes_out():
    bars = make_bars([(100, 100, 100, 100)] * 10)  # a half day, or missing data
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go")))
    assert r.trades[0].exit_reason == "session end"


def test_strategy_exit_executes_next_open():
    bars = make_bars(pad([(100, 100, 100, 100), (100, 100, 100, 100), (100, 101, 100, 101),
                          (103, 103, 103, 103)]))
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go"), exit_at=2))
    assert (r.trades[0].exit_reason, r.trades[0].exit_price) == ("scripted exit", 103)


def test_costs_are_accounted_exactly():
    costs = CostModel(slippage_bps=10, sec_fee_rate=0, finra_taf_per_share=0)
    bars = make_bars(pad([(100, 100, 100, 100), (100, 100, 100, 100), (110, 110, 110, 110)]))
    r = run(bars, Scripted(0, Signal(Action.ENTER_LONG, "go"), exit_at=1), costs=costs)
    t = r.trades[0]
    qty = t.qty
    # Bought at 100 +10bps, sold at 110 -10bps: 0.10 + 0.11 per share of slippage.
    assert t.gross == pytest.approx(10 * qty)
    assert t.costs == pytest.approx(0.21 * qty)
    assert r.daily_pnl[bars[0].session_date] == pytest.approx(t.net)


def test_daily_loss_limit_binds_in_backtest():
    # Each day loses $2 per share on a stop; the limit allows one such loss.
    risk = RiskSettings(risk_per_trade=100, max_position_notional=10_000, max_daily_loss=100,
                        pdt_equity_threshold=0, max_trades_per_day=10)

    class Twice(Strategy):
        def on_bar(self, bars, position):
            if position is None and len(bars) in (1, 4):
                return Signal(Action.ENTER_LONG, "go", stop=bars[-1].close - 2)
            return None

    bars = make_bars(pad([(100, 100, 100, 100), (100, 100, 100, 100), (98, 98, 98, 98),
                          (98, 98, 98, 98), (98, 98, 98, 98), (96, 96, 96, 96)], price=96))
    r = run(bars, Twice(), risk=risk)
    assert len(r.trades) == 1
    assert "halted" in r.refusals
