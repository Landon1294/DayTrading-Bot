from datetime import date

import pytest

from daybot.config import RiskSettings
from daybot.models import Action, Side, Signal, Trade
from daybot.risk import RiskManager
from tests.helpers import DAY, et

LONG = Signal(Action.ENTER_LONG, "t", stop=99.0)
NOON = et(DAY, 12, 0)


def rm(**kw) -> RiskManager:
    m = RiskManager(RiskSettings(**kw))
    m.start_day(DAY)
    return m


def trade(net: float, day: date = DAY) -> Trade:
    return Trade("X", Side.LONG, 1, et(day, 10, 0), 100.0, et(day, 11, 0), 100.0, "t", net, 0.0)


class TestSizing:
    def test_sized_by_risk_to_stop(self):
        # $25 at risk, $1 per share to the stop -> 25 shares.
        assert rm(risk_per_trade=25, max_position_notional=10_000).size(LONG, 100.0) == 25

    def test_capped_by_notional_and_buying_power(self):
        m = rm(risk_per_trade=1_000, max_position_notional=2_000)
        assert m.size(LONG, 100.0) == 20
        assert m.size(LONG, 100.0, buying_power=500) == 5

    def test_zero_distance_stop_sizes_to_zero(self):
        assert rm().size(Signal(Action.ENTER_LONG, "t", stop=100.0), 100.0) == 0


class TestGate:
    def test_accepts_a_normal_entry(self):
        d = rm().check_entry(LONG, 100.0, NOON, equity=50_000)
        # Risk allows 25 shares; the default $2,000 notional cap binds first.
        assert d.ok and d.qty == 20

    def test_stop_on_wrong_side_refused(self):
        # A gap open below the stop: entering would be stopped out instantly.
        d = rm().check_entry(LONG, 98.5, NOON, equity=50_000)
        assert not d.ok and "wrong side" in d.reason

    def test_short_refused_unless_enabled(self):
        short = Signal(Action.ENTER_SHORT, "t", stop=101.0)
        assert not rm().check_entry(short, 100.0, NOON, equity=50_000).ok
        assert rm(allow_short=True).check_entry(short, 100.0, NOON, equity=50_000).ok

    def test_no_entry_near_close(self):
        assert not rm().check_entry(LONG, 100.0, et(DAY, 15, 35), equity=50_000).ok
        assert rm().check_entry(LONG, 100.0, et(DAY, 15, 25), equity=50_000).ok

    def test_flatten_window(self):
        m = rm(flatten_minutes_before_close=5)
        assert not m.must_flatten(et(DAY, 15, 50))
        assert m.must_flatten(et(DAY, 15, 55))

    def test_max_trades_per_day(self):
        m = rm(max_trades_per_day=2)
        m.record_entry()
        m.record_entry()
        assert "trades/day" in m.check_entry(LONG, 100.0, NOON, equity=50_000).reason

    def test_equity_floor(self):
        assert not rm(min_equity=1_000).check_entry(LONG, 100.0, NOON, equity=900).ok


class TestDailyLoss:
    def test_trip_halts_mid_day(self):
        m = rm(max_daily_loss=100)
        m.record_trade(trade(-60))
        assert m.check_entry(LONG, 100.0, NOON, equity=50_000).ok
        m.record_trade(trade(-50))
        assert m.halted
        assert "halted" in m.check_entry(LONG, 100.0, NOON, equity=50_000).reason

    def test_gate_survives_a_restart(self):
        # A fresh process seeded with the day's realised loss must refuse,
        # even though nothing tripped the halt flag in this process.
        m = RiskManager(RiskSettings(max_daily_loss=100))
        m.start_day(DAY, realized=-120)
        assert not m.halted
        assert not m.check_entry(LONG, 100.0, NOON, equity=50_000).ok

    def test_unrealized_counts(self):
        m = rm(max_daily_loss=100)
        m.record_trade(trade(-40))
        assert not m.check_entry(LONG, 100.0, NOON, equity=50_000, unrealized=-70).ok


class TestPatternDayTrader:
    def test_off_by_default_since_finra_retired_it(self):
        m = rm()
        for _ in range(3):
            m.record_trade(trade(1.0))
        assert m.check_entry(LONG, 100.0, NOON, equity=10_000).ok

    def test_fourth_day_trade_blocked_under_threshold(self):
        m = rm(pdt_equity_threshold=25_000)
        for _ in range(3):
            m.record_trade(trade(1.0))
        d = m.check_entry(LONG, 100.0, NOON, equity=10_000)
        assert not d.ok and "pattern-day-trader" in d.reason

    def test_not_applied_above_threshold_or_when_disabled(self):
        m = rm(pdt_equity_threshold=25_000)
        for _ in range(3):
            m.record_trade(trade(1.0))
        assert m.check_entry(LONG, 100.0, NOON, equity=30_000).ok
        m2 = rm(pdt_equity_threshold=0)
        for _ in range(3):
            m2.record_trade(trade(1.0))
        assert m2.check_entry(LONG, 100.0, NOON, equity=10_000).ok

    @pytest.mark.parametrize("prior, counted", [
        (date(2024, 2, 26), True),   # Monday a week earlier: 6th weekday back
        (date(2024, 2, 23), False),  # the Friday before that: 7th
    ])
    def test_window_is_six_weekdays(self, prior, counted):
        m = rm()
        m.day_trade_dates.append(prior)
        assert m.day_trades_in_window(DAY) == (1 if counted else 0)

    def test_overnight_hold_is_not_a_day_trade(self):
        t = Trade("X", Side.LONG, 1, et(date(2024, 3, 1), 10, 0), 1, et(DAY, 10, 0), 1, "t", 0, 0)
        assert not t.is_day_trade
