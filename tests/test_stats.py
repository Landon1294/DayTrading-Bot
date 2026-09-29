"""The statistics that decide "edge", and the two tests that matter most:
nothing is found where nothing exists, and something is found where it does."""

import math

from collections import OrderedDict

import pytest

from daybot.backtest import run_backtest
from daybot.config import RiskSettings
from daybot.cli import main
from daybot.costs import CostModel
from daybot.stats import EDGE_T, split_days, summarize, sweep, t_stat
from daybot.strategy import make_strategy
from daybot.strategy.orb import OpeningRangeBreakout
from daybot.synthetic import generate_sessions

FREE = CostModel(slippage_bps=0, sec_fee_rate=0, finra_taf_per_share=0)


def test_t_stat_basics():
    assert t_stat([1.0]) == 0.0
    assert t_stat([1.0, 1.0]) == math.inf
    assert t_stat([1, 2, 3, 4]) == pytest.approx(2.5 / (math.sqrt(5 / 3) / 2))


def test_split_is_chronological_and_disjoint():
    s = generate_sessions(20)
    tr, va, te = split_days(s)
    assert (len(tr), len(va), len(te)) == (12, 4, 4)
    assert max(tr) < min(va) and max(va) < min(te)


def test_sweep_never_shows_test_days_to_selection():
    sessions = generate_sessions(30)
    _, val, test = split_days(sessions)
    made = []

    def factory(**p):
        strat = OpeningRangeBreakout(**p)
        strat.days = set()
        orig = strat.on_bar

        def spy(bars, position):
            strat.days.add(bars[0].session_date)
            return orig(bars, position)

        strat.on_bar = spy
        made.append(strat)
        return strat

    res = sweep(sessions, factory, {"range_minutes": [15, 30], "target_r": [1, 2]}, costs=FREE,
                apply_pdt=False)
    *selection, final = made
    assert res.tried == 4 and len(selection) == 4
    assert all(s.days <= set(val) for s in selection)
    assert final.days <= set(test)


def test_summary_accounting():
    s = summarize(run_backtest(generate_sessions(40, momentum=0.2), make_strategy("orb"),
                               apply_pdt=False))
    assert s.net == pytest.approx(s.gross - s.costs)
    assert s.days == 40
    assert s.max_drawdown >= 0


@pytest.mark.slow
@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("name", ["orb", "vwap", "random", "buy_open", "intraday_mom",
                                  "noise_mom", "orb5", "vwap_trend", "gap_fade"])
def test_null_market_shows_no_edge(name, seed):
    """THE most important test. On a driftless random walk nothing can be
    predicted, so even with zero costs no strategy may clear the bar. If this
    starts failing, find out why before trusting any other result."""
    s = summarize(run_backtest(generate_sessions(400, seed=seed), make_strategy(name),
                               costs=FREE, risk=RiskSettings(allow_short=True), apply_pdt=False))
    assert s.t_stat < EDGE_T, f"{name} found an 'edge' in pure noise: t={s.t_stat:.2f}"


@pytest.mark.slow
def test_null_sweep_does_not_pass_its_held_out_days():
    for seed in range(3):
        res = sweep(generate_sessions(400, seed=seed), OpeningRangeBreakout,
                    {"range_minutes": [15, 30, 60], "target_r": [1, 2, 3]}, costs=FREE,
                    apply_pdt=False)
        assert not res.test.has_edge


@pytest.mark.slow
def test_known_momentum_is_detected_and_reversion_is_punished():
    """The other half of the null test: when a real effect is placed in the
    data, the machinery must find it -- and the opposite hypothesis must lose."""
    sessions = generate_sessions(1000, momentum=0.4, seed=7)
    orb = summarize(run_backtest(sessions, make_strategy("orb"), costs=FREE, apply_pdt=False))
    vwap = summarize(run_backtest(sessions, make_strategy("vwap"), costs=FREE, apply_pdt=False))
    assert orb.t_stat >= EDGE_T
    assert vwap.t_stat < 0


def trend_days(n, strength, seed):
    """A random walk plus, on each day, a drift drawn once and held all day:
    the "trend day" that intraday momentum strategies claim to catch."""
    import math
    import random
    from dataclasses import replace as _replace

    rng = random.Random(seed + 1)
    out = OrderedDict()
    for day, bars in generate_sessions(n, seed=seed).items():
        mu = rng.gauss(0, strength)
        k = lambda i: math.exp(mu * i / len(bars))  # noqa: E731
        out[day] = [_replace(b, open=b.open * k(i), high=b.high * k(i + 1) if mu > 0 else b.high * k(i),
                             low=b.low * k(i) if mu > 0 else b.low * k(i + 1), close=b.close * k(i + 1))
                    for i, b in enumerate(bars)]
    return out


@pytest.mark.slow
@pytest.mark.parametrize("name", ["vwap_trend"])
def test_trend_strategies_find_planted_momentum(name):
    s = summarize(run_backtest(generate_sessions(400, momentum=0.4, seed=7), make_strategy(name),
                               costs=FREE, risk=RiskSettings(allow_short=True, max_trades_per_day=100),
                               apply_pdt=False))
    assert s.t_stat >= EDGE_T, f"{name} missed a planted effect: t={s.t_stat:.2f}"


@pytest.mark.slow
@pytest.mark.parametrize("name,params", [("noise_mom", {}), ("intraday_mom", {"window": "rest"}),
                                         ("vwap_trend", {"every": 30})])
def test_trend_strategies_find_planted_trend_days(name, params):
    # intraday_mom holds 25 of 390 minutes, so it sees ~6% of the drift; 1.5% a day is
    # enough for all three.
    s = summarize(run_backtest(trend_days(400, 0.015, seed=5), make_strategy(name, **params),
                               costs=FREE, risk=RiskSettings(allow_short=True, max_trades_per_day=100),
                               apply_pdt=False))
    assert s.t_stat >= EDGE_T, f"{name} missed planted trend days: t={s.t_stat:.2f}"


def test_cli_backtest_and_sweep_run(capsys):
    assert main(["backtest", "--days", "15", "--momentum", "0.2"]) == 0
    assert "paired t=" in capsys.readouterr().out
    assert main(["sweep", "--days", "30", "--grid", "range_minutes=15,30", "--no-pdt"]) == 0
    assert "verdict:" in capsys.readouterr().out
