"""The live loop against an in-memory broker: approval, brackets, owned-only
flattening, and the failure paths that should halt rather than guess."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import timedelta

import pytest

from daybot.broker import BrokerOrder, BrokerPosition, OrderRequest
from daybot.config import RiskSettings
from daybot.models import Account, Action, Clock, Signal
from daybot.strategy.base import Strategy
from daybot.trader import Trader
from tests.helpers import DAY, et, make_bars


class FakeBroker:
    def __init__(self, price=100.0, held=0, equity=50_000.0, last_equity=50_000.0):
        self.price = price
        self.qty = held
        self.equity, self.last_equity = equity, last_equity
        self.allow_orders = True
        self.orders: dict[str, BrokerOrder] = {}
        self.submitted: list[OrderRequest] = []
        self.closes: list[int] = []
        self.cancelled: set[str] = set()
        self.fill_entries = True
        self.close_failures = 0
        self.close_at = et(DAY, 16, 0)
        self.is_open = True
        self._ids = (f"o{i}" for i in itertools.count())

    def account(self):
        return Account(self.equity, self.last_equity, self.equity, self.equity * 2)

    def clock(self):
        now = et(DAY, 12, 0)
        return Clock(now, self.is_open, et(DAY + timedelta(days=1), 9, 30), self.close_at)

    def position(self, symbol):
        if self.qty == 0:
            return None
        return BrokerPosition(symbol, self.qty, self.price, self.qty * self.price, 0.0)

    def order(self, oid):
        return self.orders[oid]

    def open_orders(self):
        # As recorded on Alpaca paper: an open parent is listed with its legs
        # nested; once it fills, only the unheld legs are listed, on their own.
        leg_ids = {leg.id for o in self.orders.values() for leg in o.legs}
        out = []
        for o in self.orders.values():
            if o.id in leg_ids:
                continue
            if o.is_open:
                out.append(o)
            else:
                out.extend(leg for leg in o.legs if leg.is_open and leg.status != "held")
        return out

    def _new(self, **kw):
        oid = next(self._ids)
        # Alpaca gives legs and position closes its own ids, not ours.
        o = BrokerOrder(id=oid, client_order_id=kw.pop("client_order_id", "alpaca-" + oid),
                        symbol="TST", **kw)
        self.orders[oid] = o
        return o

    def submit(self, req: OrderRequest):
        self.submitted.append(req)
        legs = []
        if req.take_profit is not None:
            legs.append(self._new(side="sell" if req.side == "buy" else "buy", type="limit",
                                  status="new", qty=req.qty, filled_qty=0, filled_avg_price=None,
                                  limit_price=float(req.take_profit)))
        if req.stop_loss is not None:
            legs.append(self._new(side="sell" if req.side == "buy" else "buy", type="stop",
                                  status="held", qty=req.qty, filled_qty=0, filled_avg_price=None,
                                  stop_price=float(req.stop_loss)))
        if self.fill_entries:
            o = self._new(side=req.side, type="market", status="filled", qty=req.qty,
                          filled_qty=req.qty, filled_avg_price=self.price, legs=tuple(legs),
                          client_order_id=req.client_order_id)
            self.qty += req.qty if req.side == "buy" else -req.qty
        else:
            o = self._new(side=req.side, type="market", status="new", qty=req.qty, filled_qty=0,
                          filled_avg_price=None, legs=tuple(legs),
                          client_order_id=req.client_order_id)
        return o

    def cancel(self, oid):
        self.cancelled.add(oid)
        o = self.orders.get(oid)
        if o and o.is_open:
            self.orders[oid] = replace(o, status="canceled")
        if o and o.legs:  # Alpaca cancels a parent's legs with it, filled or not
            for leg in o.legs:
                self.cancel(leg.id)
            return
        for pid, parent in self.orders.items():
            if any(leg.id == oid for leg in parent.legs):
                legs = tuple(replace(leg, status="canceled") if leg.id == oid and leg.is_open else leg
                             for leg in parent.legs)
                self.orders[pid] = replace(parent, legs=legs)

    def close(self, symbol, qty):
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError("insufficient qty available")
        # Alpaca refuses (403) to close shares a resting bracket leg holds.
        held = sum(int(o.legs[0].qty) for o in self.orders.values()
                   if o.legs and any(leg.is_open for leg in o.legs))
        if qty > abs(self.qty) - held:
            raise RuntimeError(f"insufficient qty available (held_for_orders {held})")
        self.closes.append(qty)
        self.qty -= qty if self.qty > 0 else -qty
        return self._new(side="sell", type="market", status="filled", qty=qty, filled_qty=qty,
                         filled_avg_price=self.price)

    def fill_leg(self, parent_id, leg_type, price):
        parent = self.orders[parent_id]
        legs = []
        for leg in parent.legs:
            if leg.type == leg_type:
                leg = replace(leg, status="filled", filled_qty=leg.qty, filled_avg_price=price)
                self.qty -= int(leg.qty)
            elif leg.is_open:
                leg = replace(leg, status="canceled")
            legs.append(leg)
        self.orders[parent_id] = replace(parent, legs=tuple(legs))


class Once(Strategy):
    """Enters long on the first bar it sees, with a stop and target."""
    name = "once"

    def __init__(self, stop=99.0, target=103.0, exit_on=None):
        self.stop, self.target, self.exit_on = stop, target, exit_on
        self.done = False

    def reset(self):
        self.done = False

    def on_bar(self, bars, position):
        if position is not None and self.exit_on and len(bars) >= self.exit_on:
            return Signal(Action.EXIT, "strategy exit")
        if position is None and not self.done:
            self.done = True
            return Signal(Action.ENTER_LONG, "test entry", stop=self.stop, target=self.target)
        return None


BARS = make_bars([(100, 100, 100, 100)] * 6)
NOON = et(DAY, 12, 0)
RISK = RiskSettings(pdt_equity_threshold=0, max_position_notional=10_000, risk_per_trade=100)


def trader(broker, *, approve=True, strategy=None, dry_run=False, clock=None, **kw):
    said = []
    t = Trader(broker, strategy or Once(), "TST", risk=kw.pop("risk", RISK),
               approver=lambda plan: approve, dry_run=dry_run,
               now=clock or (lambda: NOON), sleep=lambda s: None, fill_timeout=0.0,
               say=said.append, **kw)
    t.said = said
    t.start()
    return t


def test_dry_run_never_submits():
    b = FakeBroker()
    t = trader(b, dry_run=True)
    t.step(BARS, NOON)
    assert b.submitted == [] and any("[dry-run]" in s for s in t.said)


def test_declined_plan_sends_nothing():
    b = FakeBroker()
    trader(b, approve=False).step(BARS, NOON)
    assert b.submitted == []


def test_approved_entry_goes_out_as_a_bracket_rounded_toward_safety():
    b = FakeBroker()
    t = trader(b, strategy=Once(stop=98.994, target=103.006))
    t.step(BARS, NOON)
    (req,) = b.submitted
    assert (req.side, req.qty) == ("buy", 99)  # $100 risk / $1.006 to the stop
    assert str(req.stop_loss) == "99.00"    # long stop rounds up: triggers no later
    assert str(req.take_profit) == "103.00"  # long target rounds down: fills no later
    assert t.position.qty == 99 and t.position.entry_price == 100.0


def test_stale_approval_is_discarded():
    b = FakeBroker()
    times = iter([NOON, NOON + timedelta(minutes=6)])
    trader(b, clock=lambda: next(times)).step(BARS, NOON)
    assert b.submitted == []


def test_broker_side_stop_is_noticed_and_booked():
    b = FakeBroker()
    t = trader(b)
    t.step(BARS, NOON)
    b.fill_leg(t.entry_order_id, "stop", 99.0)
    t.step(BARS, NOON + timedelta(minutes=5))
    assert t.position is None
    (tr,) = t.trades
    assert tr.exit_reason == "stop" and tr.gross == pytest.approx(-100.0)


def test_flatten_only_touches_the_bots_own_shares():
    b = FakeBroker(held=500)  # the user's own long-term holding
    t = trader(b, strategy=Once(exit_on=2))
    t.step(BARS[:1], NOON)
    assert b.qty == 600
    t.step(BARS[:2], NOON + timedelta(minutes=5))
    assert b.closes == [100] and b.qty == 500
    assert t.position is None


def test_flatten_cancels_the_bracket_legs_first():
    b = FakeBroker()
    t = trader(b, strategy=Once(exit_on=2))
    t.step(BARS[:1], NOON)
    legs = {leg.id for leg in b.orders[t.entry_order_id].legs}
    t.step(BARS[:2], NOON + timedelta(minutes=5))
    assert legs <= b.cancelled


def test_legs_are_recorded_at_submit():
    # Alpaca's listing never shows a filled bracket's legs as ours, so their
    # ids must be known before anything else can go wrong.
    b = FakeBroker()
    t = trader(b)

    def lost(oid):
        raise ConnectionError("network down")
    b.order = lost
    with pytest.raises(ConnectionError):
        t.step(BARS[:1], NOON)
    (entry,) = [o for o in b.orders.values() if o.legs]
    assert {entry.id, *(leg.id for leg in entry.legs)} <= t.our_order_ids


def test_forced_flatten_before_the_close():
    b = FakeBroker()
    t = trader(b)
    t.step(BARS, NOON)
    t.step(BARS, et(DAY, 15, 56))
    assert b.closes == [100] and t.position is None


def test_early_close_comes_from_the_broker_clock():
    # 13:00 ET closes: entries stop at 12:30 and the position goes by 12:55,
    # before the bracket's day orders expire with the session.
    b = FakeBroker()
    b.close_at = et(DAY, 13, 0)
    t = trader(b)
    t.step(BARS[:1], NOON)
    assert t.position is not None
    t.step(BARS[:2], et(DAY, 12, 55))
    assert b.closes == [100] and t.position is None
    assert t.rm.check_entry(Signal(Action.ENTER_LONG, "x", stop=99.0), 100.0, et(DAY, 12, 31),
                            equity=50_000).reason == "too close to the close for a new entry"


def test_unreadable_close_halts():
    b = FakeBroker()
    b.close_at = et(DAY + timedelta(days=1), 16, 0)  # a clock that is not about today
    t = trader(b)
    t.step(BARS[:1], NOON)
    assert t.rm.halted and "close" in t.rm.halt_reason and b.submitted == []


def test_close_retried_then_halts_with_manual_intervention():
    b = FakeBroker()
    t = trader(b, strategy=Once(exit_on=2))
    t.step(BARS[:1], NOON)
    b.close_failures = 99
    t.step(BARS[:2], NOON + timedelta(minutes=5))
    assert t.rm.halted and "manual intervention" in t.rm.halt_reason


def test_unfilled_entry_is_cancelled():
    b = FakeBroker()
    b.fill_entries = False
    t = trader(b)
    t.step(BARS, NOON)
    assert t.position is None and b.submitted and b.cancelled


def test_persistent_position_mismatch_halts():
    b = FakeBroker()
    t = trader(b, strategy=Once(stop=None, target=None))
    t.step(BARS, NOON)
    b.qty = 0  # shares vanished with no leg fill to explain it
    for i in range(1, 4):
        t.step(BARS, NOON + timedelta(minutes=5 * i))
    assert t.rm.halted and "manual check" in t.rm.halt_reason


def test_account_losses_gate_entries_even_after_restart():
    b = FakeBroker(equity=49_850, last_equity=50_000)  # down $150 today already
    t = trader(b, risk=replace(RISK, max_daily_loss=100))
    t.step(BARS, NOON)
    assert b.submitted == [] and any("daily loss" in s for s in t.said)


def test_gains_elsewhere_do_not_loosen_the_limit():
    b = FakeBroker(equity=51_000, last_equity=50_000)
    t = trader(b)
    t.step(BARS, NOON)
    assert t.rm.realized_today == 0.0


def test_shutdown_cancels_and_flattens():
    b = FakeBroker()
    t = trader(b)
    t.step(BARS, NOON)
    t.shutdown(flatten=True)
    assert b.closes == [100] and t.position is None


def test_day_trade_count_survives_a_restart(tmp_path):
    from daybot.trader import Journal

    path = tmp_path / "journal.jsonl"
    for _ in range(3):
        b = FakeBroker()
        t = trader(b, strategy=Once(exit_on=2), journal=Journal(path),
                   risk=replace(RISK, pdt_equity_threshold=25_000))
        t.step(BARS[:1], NOON)
        t.step(BARS[:2], NOON + timedelta(minutes=5))
    # A fresh process with a sub-$25k account must refuse the fourth.
    b = FakeBroker(equity=10_000, last_equity=10_000)
    t = trader(b, journal=Journal(path), risk=replace(RISK, pdt_equity_threshold=25_000))
    t.step(BARS, NOON)
    assert b.submitted == [] and any("pattern-day-trader" in s for s in t.said)
