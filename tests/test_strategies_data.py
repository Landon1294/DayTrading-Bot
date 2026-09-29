from datetime import timedelta

import pytest

from daybot.data import load_csv, load_sessions, write_csv
from daybot.models import Action
from daybot.strategy import make_strategy
from daybot.strategy.orb import OpeningRangeBreakout
from daybot.strategy.vwap_reversion import VwapReversion, session_vwap
from daybot.synthetic import generate_sessions
from tests.helpers import make_bars


class TestOrb:
    RANGE = [(100, 101, 99, 100)] * 6  # 09:30-10:00, high 101, low 99

    def test_no_signal_while_the_range_is_forming(self):
        orb = OpeningRangeBreakout(range_minutes=30)
        bars = make_bars(self.RANGE)
        for i in range(1, 7):
            assert orb.on_bar(bars[:i], None) is None

    def test_breakout_long_with_stop_at_range_low(self):
        orb = OpeningRangeBreakout(range_minutes=30, target_r=2)
        bars = make_bars(self.RANGE + [(100, 102, 100, 102)])
        sig = orb.on_bar(bars, None)
        assert sig.action is Action.ENTER_LONG
        assert sig.stop == 99 and sig.target == pytest.approx(102 + 2 * 3)

    def test_one_entry_per_session_until_reset(self):
        orb = OpeningRangeBreakout()
        bars = make_bars(self.RANGE + [(100, 102, 100, 102), (102, 103, 102, 103)])
        assert orb.on_bar(bars[:7], None) is not None
        assert orb.on_bar(bars, None) is None
        orb.reset()
        assert orb.on_bar(bars, None) is not None

    def test_short_breakdown_only_when_allowed(self):
        bars = make_bars(self.RANGE + [(100, 100, 97, 98)])
        assert OpeningRangeBreakout().on_bar(bars, None) is None
        sig = OpeningRangeBreakout(allow_short=True).on_bar(bars, None)
        assert sig.action is Action.ENTER_SHORT and sig.stop == 101


class TestVwap:
    def test_vwap_is_volume_weighted(self):
        bars = make_bars([(10, 10, 10, 10), (20, 20, 20, 20)])
        bars[1] = type(bars[1])(**{**bars[1].__dict__, "volume": 3000.0})
        assert session_vwap(bars) == pytest.approx((10 * 1000 + 20 * 3000) / 4000)

    def test_enters_below_band_and_exits_at_vwap(self):
        v = VwapReversion(band=0.01, warmup_minutes=0)
        bars = make_bars([(100, 100, 100, 100)] * 5 + [(98, 98, 98, 98)])
        sig = v.on_bar(bars, None)
        assert sig.action is Action.ENTER_LONG and sig.target == pytest.approx(session_vwap(bars))


def test_unknown_strategy_named_in_error():
    with pytest.raises(ValueError, match="orb"):
        make_strategy("nope")


class TestCsv:
    def test_round_trip(self, tmp_path):
        s = generate_sessions(3, seed=4)
        p = tmp_path / "bars.csv"
        write_csv(p, s)
        back = load_sessions(p)
        assert list(back) == list(s)
        assert back[next(iter(s))][0].close == pytest.approx(s[next(iter(s))][0].close, abs=1e-4)

    def test_naive_timestamp_rejected(self, tmp_path):
        p = tmp_path / "b.csv"
        p.write_text("timestamp,open,high,low,close,volume\n2024-03-04T09:30:00,1,1,1,1,1\n")
        with pytest.raises(ValueError, match="no zone"):
            load_csv(p)

    def test_right_labelled_bars_are_shifted_back(self, tmp_path):
        p = tmp_path / "b.csv"
        p.write_text("timestamp,symbol,open,high,low,close,volume\n"
                     "2024-03-04T09:35:00-05:00,X,1,1,1,1,1\n")
        left, right = load_csv(p), load_csv(p, label="right")
        assert left[0].start - right[0].start == timedelta(minutes=5)

    def test_multiple_symbols_need_a_choice(self, tmp_path):
        p = tmp_path / "b.csv"
        p.write_text("timestamp,symbol,open,high,low,close,volume\n"
                     "2024-03-04T14:30:00Z,A,1,1,1,1,1\n2024-03-04T14:30:00Z,B,2,2,2,2,1\n")
        with pytest.raises(ValueError, match="pick one"):
            load_csv(p)
        assert [b.symbol for b in load_csv(p, symbol="B")] == ["B"]

    def test_inconsistent_bar_rejected(self, tmp_path):
        p = tmp_path / "b.csv"
        p.write_text("timestamp,open,high,low,close,volume\n2024-03-04T14:30:00Z,5,4,3,4,1\n")
        with pytest.raises(ValueError, match="high/low"):
            load_csv(p)
