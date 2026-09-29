from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from daybot.costs import CostModel
from daybot.models import round_to_tick, tick_size
from daybot.sessions import group_sessions, in_regular_session, minutes_since_open, to_eastern
from tests.helpers import make_bars


class TestTicks:
    def test_penny_tick_at_and_above_one_dollar(self):
        assert tick_size(1.00) == Decimal("0.01")
        assert tick_size(0.9999) == Decimal("0.0001")

    def test_rounding_direction_is_explicit(self):
        assert round_to_tick(10.237, direction="down") == Decimal("10.23")
        assert round_to_tick(10.231, direction="up") == Decimal("10.24")
        assert round_to_tick(0.51237, direction="down") == Decimal("0.5123")

    def test_exact_prices_do_not_move(self):
        # 0.1 + 0.2 style float noise must not push an on-tick price a tick.
        assert round_to_tick(10.23, direction="up") == Decimal("10.23")
        assert round_to_tick(10.23, direction="down") == Decimal("10.23")

    def test_direction_is_required(self):
        with pytest.raises(TypeError):
            round_to_tick(10.0)  # type: ignore[call-arg]


class TestCosts:
    def test_slippage_always_hurts(self):
        c = CostModel(slippage_bps=10)
        assert c.fill_price(100.0, buying=True) == pytest.approx(100.10)
        assert c.fill_price(100.0, buying=False) == pytest.approx(99.90)

    def test_regulatory_fees_only_on_sales(self):
        c = CostModel()
        assert c.fees(100.0, 100, selling=False) == 0.0
        # SEC: 10,000 * 27.80e-6 = 0.278 -> 0.28; TAF: 100 * 0.000166 = 0.0166 -> 0.02
        assert c.fees(100.0, 100, selling=True) == pytest.approx(0.30)

    def test_taf_is_capped(self):
        c = CostModel(sec_fee_rate=0.0)
        assert c.fees(1.0, 1_000_000, selling=True) == pytest.approx(8.30)

    def test_commission_applies_both_sides(self):
        c = CostModel(sec_fee_rate=0, finra_taf_per_share=0, commission_per_share=0.005)
        assert c.fees(50.0, 200, selling=False) == pytest.approx(1.0)
        assert c.fees(50.0, 200, selling=True) == pytest.approx(1.0)


class TestSessions:
    def test_open_is_eastern_across_daylight_saving(self):
        winter = datetime(2024, 1, 10, 14, 30, tzinfo=timezone.utc)
        summer = datetime(2024, 7, 10, 13, 30, tzinfo=timezone.utc)
        assert minutes_since_open(winter) == 0
        assert minutes_since_open(summer) == 0

    def test_naive_timestamps_are_refused(self):
        with pytest.raises(ValueError):
            to_eastern(datetime(2024, 1, 10, 9, 30))

    def test_premarket_and_last_partial_bar_excluded(self):
        pre = make_bars([(1, 1, 1, 1)], start=(9, 25))[0]
        last = make_bars([(1, 1, 1, 1)], start=(15, 55))[0]
        after = make_bars([(1, 1, 1, 1)], start=(16, 0))[0]
        assert not in_regular_session(pre.start, 5)
        assert in_regular_session(last.start, 5)
        assert not in_regular_session(after.start, 5)

    def test_group_sessions_by_eastern_date(self):
        a = make_bars([(1, 1, 1, 1)] * 3, day=date(2024, 3, 4))
        b = make_bars([(1, 1, 1, 1)] * 2, day=date(2024, 3, 5))
        pre = make_bars([(1, 1, 1, 1)], day=date(2024, 3, 5), start=(8, 0))
        g = group_sessions(b + pre + a, 5)
        assert list(g) == [date(2024, 3, 4), date(2024, 3, 5)]
        assert [len(v) for v in g.values()] == [3, 2]
