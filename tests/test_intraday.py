"""The pre-registered strategies (docs/RESEARCH.md), each rule checked on
hand-built bars where the right answer can be worked out on paper."""

from datetime import timedelta

import pytest

from daybot.backtest import run_backtest
from daybot.config import RiskSettings
from daybot.costs import CostModel
from daybot.models import Action, Position, Side
from daybot.strategy.intraday import (GapFade, IntradayMomentum, NoiseAreaMomentum,
                                      OpeningRange5, VwapTrend)
from tests.helpers import DAY, et, flat_day, make_bars, sessions_of

FREE = CostModel(slippage_bps=0, sec_fee_rate=0, finra_taf_per_share=0)
OPEN_RISK = RiskSettings(max_position_notional=10_000, risk_per_trade=1e9, max_daily_loss=1e9,
                         max_trades_per_day=100, pdt_equity_threshold=0, allow_short=True)


def pos(side, price=100.0):
    return Position("TST", side, 10, price, et(DAY, 10, 0))


def feed(strategy, bars, position=None):
    """Show the strategy each closed bar in turn; return {bar index: signal}."""
    out = {}
    for i in range(len(bars)):
        s = strategy.on_bar(bars[: i + 1], position)
        if s is not None:
            out[i] = s
    return out


class TestIntradayMomentum:
    def day(self, at_ten=100.0, at_1530=100.0):
        # 78 bars; bar 5 ends at 10:00, bar 71 ends at 15:30.
        ohlc = [(100, 100, 100, 100)] * 78
        ohlc[5] = (at_ten, at_ten, at_ten, at_ten)
        ohlc[71] = (at_1530, at_1530, at_1530, at_1530)
        return make_bars(ohlc)

    def test_enters_once_at_1530_in_the_direction_of_the_first_half_hour(self):
        s = IntradayMomentum(window="first30")
        s.end_session(flat_day(99.0))  # previous close 99
        sig = feed(s, self.day(at_ten=100.5, at_1530=98.0))
        assert list(sig) == [71] and sig[71].action is Action.ENTER_LONG

    def test_rest_window_uses_the_move_to_1530(self):
        s = IntradayMomentum(window="rest")
        s.end_session(flat_day(99.0))
        sig = feed(s, self.day(at_ten=100.5, at_1530=98.0))
        assert sig[71].action is Action.ENTER_SHORT

    def test_threshold_and_missing_history(self):
        s = IntradayMomentum(window="first30", threshold=0.02)
        s.end_session(flat_day(99.0))
        assert feed(s, self.day(at_ten=100.5)) == {}  # +1.5% < 2%
        assert feed(IntradayMomentum(), self.day(at_ten=101.0)) == {}  # no previous close


class TestNoiseAreaMomentum:
    def history(self, s, days=14, swing=0.01):
        """Days whose close is always ``swing`` from the open: sigma = swing."""
        for n in range(days):
            d = DAY - timedelta(days=30 - n)
            s.end_session(make_bars([(100, 101, 99, 100 * (1 + swing))] * 78, day=d))

    def test_needs_the_full_lookback(self):
        s = NoiseAreaMomentum(vm=1.0, stop="band")
        self.history(s, days=13)
        assert feed(s, make_bars([(100, 103, 100, 103)] * 20)) == {}

    def test_breakout_is_acted_on_only_at_the_half_hour(self):
        s = NoiseAreaMomentum(vm=1.0, stop="band")
        self.history(s)  # previous close 101, so the upper band is 101 * 1.01 = 102.01
        bars = make_bars([(100, 100, 100, 100)] * 3 + [(102.5, 102.5, 102.5, 102.5)] * 5)
        sig = feed(s, bars)
        # Above the band from bar 3 (ends 09:50), but the first check is 10:00 (bar 5).
        assert list(sig) == [5] and sig[5].action is Action.ENTER_LONG

    def test_gap_down_moves_the_upper_band_up(self):
        s = NoiseAreaMomentum(vm=1.0, stop="band")
        self.history(s)  # previous close 101.0
        # Opens at 98 after the gap: 101.5 is 3.6% above the open but still
        # inside max(98, 101) * 1.01 = 102.01.
        bars = make_bars([(98, 101.5, 98, 101.5)] * 6)
        assert feed(s, bars) == {}

    def test_trailing_stop_and_reversal(self):
        s = NoiseAreaMomentum(vm=1.0, stop="band")
        self.history(s)
        # Bands at 10:00: upper 102.01, lower 100 * 0.99 = 99.00.
        drop = make_bars([(100, 100, 100, 100)] * 5 + [(98.5, 98.5, 98.5, 98.5)])
        exit_ = s.on_bar(drop, pos(Side.LONG, 102.5))
        assert exit_.action is Action.EXIT
        # Below the lower band too: the next bar reverses, whatever the time.
        nxt = make_bars([(100, 100, 100, 100)] * 5 + [(98.5, 98.5, 98.5, 98.5)] * 2)
        assert s.on_bar(nxt, None).action is Action.ENTER_SHORT

    def test_vwap_stop_is_tighter_than_the_band(self):
        s = NoiseAreaMomentum(vm=1.0, stop="band_vwap")
        self.history(s)
        # VWAP well above the band after a big rally: a close under VWAP exits
        # even though it is still above the upper band.
        # VWAP (100 + 4 * 110 + 103.5) / 6 = 107.25; upper band 102.01.
        bars = make_bars([(100, 100, 100, 100)] + [(110, 110, 110, 110)] * 4
                         + [(103.5, 103.5, 103.5, 103.5)])
        assert s.on_bar(bars, pos(Side.LONG, 103)).action is Action.EXIT
        plain = NoiseAreaMomentum(vm=1.0, stop="band")
        self.history(plain)
        assert plain.on_bar(bars, pos(Side.LONG, 103)) is None


class TestOpeningRange5:
    def test_long_after_an_up_candle_with_stop_and_target(self):
        s = OpeningRange5(target_r=10)
        sig = feed(s, make_bars([(100, 100.6, 99.8, 100.4)] + [(100.4,) * 4] * 5))
        assert list(sig) == [0]
        assert sig[0].action is Action.ENTER_LONG
        assert sig[0].stop == 99.8 and sig[0].target == pytest.approx(100.4 + 10 * 0.6)

    def test_short_after_a_down_candle_and_nothing_on_a_doji(self):
        sig = feed(OpeningRange5(target_r=2), make_bars([(100, 100.2, 99.5, 99.7)]))
        assert sig[0].action is Action.ENTER_SHORT and sig[0].stop == 100.2
        assert feed(OpeningRange5(), make_bars([(100, 100.5, 99.5, 100)] * 3)) == {}


class TestVwapTrend:
    def test_follows_vwap_and_reverses_on_a_cross(self):
        s = VwapTrend(every=5)
        up = make_bars([(100, 100, 100, 100), (101, 101, 101, 101)])
        assert s.on_bar(up, None).action is Action.ENTER_LONG
        cross = make_bars([(100, 100, 100, 100), (101, 101, 101, 101), (99, 99, 99, 99)])
        assert s.on_bar(cross, pos(Side.LONG)).action is Action.EXIT
        assert s.on_bar(cross, None).action is Action.ENTER_SHORT

    def test_checks_only_every_n_minutes(self):
        s = VwapTrend(every=30)
        bars = make_bars([(100, 100, 100, 100)] + [(101, 101, 101, 101)] * 6)
        assert list(feed(s, bars)) == [5]  # the bar ending 10:00


class TestGapFade:
    def test_fades_a_gap_up_to_the_previous_close(self):
        s = GapFade(gap=0.005)
        s.end_session(flat_day(100.0))
        sig = feed(s, make_bars([(101, 101.2, 100.8, 100.9)] * 3))
        assert list(sig) == [0] and sig[0].action is Action.ENTER_SHORT
        assert sig[0].target == 100.0 and sig[0].stop == pytest.approx(100.9 + 1.0)

    def test_small_gap_or_already_filled_is_no_trade(self):
        s = GapFade(gap=0.005)
        s.end_session(flat_day(100.0))
        assert feed(s, make_bars([(100.3, 100.4, 100.2, 100.3)])) == {}
        s = GapFade(gap=0.005)
        s.end_session(flat_day(100.0))
        assert feed(s, make_bars([(101, 101, 99.9, 99.95)])) == {}


def test_backtest_hands_each_day_to_the_next():
    # The previous close only reaches a strategy through end_session.
    day1 = flat_day(100.0)
    day2 = make_bars([(101, 101.2, 100.8, 100.9)] + [(100.9,) * 4] * 77, day=DAY + timedelta(days=1))
    r = run_backtest(sessions_of(day1, day2), GapFade(gap=0.005), risk=OPEN_RISK, costs=FREE)
    (t,) = r.trades
    assert t.side is Side.SHORT and t.entry_time.date() == DAY + timedelta(days=1)
