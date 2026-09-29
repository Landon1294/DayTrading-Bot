"""Alpaca parsers and request building.

The fixtures are Alpaca's *documented* examples, not recorded responses (see
the ``_source`` note in the file). They catch a parser that disagrees with
the docs; only a recorded payload catches docs that disagree with the API.
"""

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from daybot.alpaca import (AlpacaClient, AlpacaSchemaError, OrdersDisabled, order_body,
                           parse_account, parse_bar, parse_clock, parse_order, parse_position)
from daybot.broker import OrderRequest, new_client_order_id

FX = json.loads((Path(__file__).parent / "fixtures" / "alpaca_doc_examples.json").read_text())


class TestParsers:
    def test_account_numbers_come_from_strings(self):
        a = parse_account(FX["account"])
        assert a.equity == 123346.11
        assert a.last_equity == pytest.approx(122011.0975)
        assert a.buying_power == 245432.61
        assert a.status == "ACTIVE" and not a.trading_blocked
        assert a.daytrade_count is None  # absent means unknown, not zero

    def test_missing_field_raises_instead_of_reading_zero(self):
        broken = {k: v for k, v in FX["account"].items() if k != "equity"}
        with pytest.raises(AlpacaSchemaError, match="equity"):
            parse_account(broken)

    def test_renamed_field_raises(self):
        # The Kalshi failure mode: the API renames a field and the old name
        # silently reads as zero. Here it must stop the bot.
        renamed = dict(FX["position"])
        renamed["qty_fp"] = renamed.pop("qty")
        with pytest.raises(AlpacaSchemaError, match="qty"):
            parse_position(renamed)

    def test_clock_keeps_its_zone(self):
        c = parse_clock(FX["clock"])
        assert c.is_open and c.next_close.utcoffset().total_seconds() == -4 * 3600

    def test_position_sign_comes_from_side(self):
        p = parse_position(FX["position"])
        assert (p.symbol, p.qty, p.avg_entry_price) == ("SPY", 10, 512.34)
        short = dict(FX["position"], side="short")  # qty unsigned in the payload
        assert parse_position(short).qty == -10
        short_signed = dict(FX["position"], side="short", qty="-10")
        assert parse_position(short_signed).qty == -10

    def test_fractional_position_rounds_away_from_zero(self):
        assert parse_position(dict(FX["position"], qty="0.4")).qty == 1

    def test_bracket_order_with_legs(self):
        o = parse_order(FX["order_bracket_filled"])
        assert o.status == "filled" and o.filled_shares == 10 and o.filled_avg_price == 512.34
        assert o.is_ours
        assert [(leg.type, leg.limit_price, leg.stop_price) for leg in o.legs] == [
            ("limit", 516.0, None), ("stop", None, 510.5)]
        assert all(leg.is_open for leg in o.legs)

    def test_filled_shares_round_down(self):
        o = parse_order(dict(FX["order_bracket_filled"], filled_qty="9.7"))
        assert o.filled_shares == 9

    def test_bar_is_left_labelled_utc(self):
        b = parse_bar("SPY", FX["bars"]["bars"]["SPY"][0])
        assert b.start.isoformat() == "2026-09-29T13:30:00+00:00"
        assert (b.close, b.vwap, b.trades) == (512.50, 512.41, 1402)


class TestOrderBody:
    def req(self, **kw):
        base = dict(symbol="SPY", side="buy", qty=10, client_order_id="daybot-x")
        return OrderRequest(**{**base, **kw})

    def test_market_numbers_are_strings(self):
        b = order_body(self.req())
        assert b == {"symbol": "SPY", "qty": "10", "side": "buy", "type": "market",
                     "time_in_force": "day", "client_order_id": "daybot-x"}

    def test_bracket_when_both_exits(self):
        b = order_body(self.req(stop_loss=Decimal("510.50"), take_profit=Decimal("516.00")))
        assert b["order_class"] == "bracket"
        assert b["stop_loss"] == {"stop_price": "510.50"}
        assert b["take_profit"] == {"limit_price": "516.00"}

    def test_oto_with_a_stop_only(self):
        b = order_body(self.req(stop_loss=Decimal("510.50")))
        assert b["order_class"] == "oto" and "take_profit" not in b

    def test_bad_requests_refused(self):
        with pytest.raises(ValueError):
            order_body(self.req(qty=0))
        with pytest.raises(ValueError):
            order_body(self.req(type="limit"))
        with pytest.raises(ValueError):
            self.req(side="long")

    def test_client_ids_are_tagged(self):
        a, b = new_client_order_id(), new_client_order_id()
        assert a.startswith("daybot-") and a != b and len(a) <= 128


class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode()


class TestClient:
    def test_orders_refused_without_permission(self):
        t = Recorder([])
        c = AlpacaClient("k", "s", transport=t)
        with pytest.raises(OrdersDisabled):
            c.submit(OrderRequest("SPY", "buy", 1, "daybot-x"))
        with pytest.raises(OrdersDisabled):
            c.close("SPY", 1)
        assert t.calls == []  # nothing left the process

    def test_paper_by_default_and_keys_in_headers(self):
        t = Recorder([(200, FX["clock"])])
        c = AlpacaClient("KEY", "SECRET", transport=t)
        c.clock()
        method, url, headers, _ = t.calls[0]
        assert url == "https://paper-api.alpaca.markets/v2/clock"
        assert headers["APCA-API-KEY-ID"] == "KEY" and headers["APCA-API-SECRET-KEY"] == "SECRET"

    def test_live_keys_are_separate_variables(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY_ID", "paper")
        monkeypatch.setenv("ALPACA_API_SECRET_KEY", "paper")
        monkeypatch.delenv("ALPACA_LIVE_API_KEY_ID", raising=False)
        monkeypatch.delenv("ALPACA_LIVE_API_SECRET_KEY", raising=False)
        assert AlpacaClient.from_env().paper
        with pytest.raises(SystemExit, match="LIVE"):
            AlpacaClient.from_env(paper=False)

    def test_close_is_by_quantity(self):
        t = Recorder([(200, FX["order_bracket_filled"])])
        AlpacaClient("k", "s", allow_orders=True, transport=t).close("SPY", 7)
        method, url, _, _ = t.calls[0]
        assert method == "DELETE" and urlparse(url).path == "/v2/positions/SPY"
        assert parse_qs(urlparse(url).query) == {"qty": ["7"]}

    def test_missing_position_is_none(self):
        t = Recorder([(404, {"code": 40410000, "message": "position does not exist"})])
        assert AlpacaClient("k", "s", transport=t).position("SPY") is None

    def test_cancel_tolerates_already_done(self):
        t = Recorder([(422, {"message": "order is already in filled state"})])
        AlpacaClient("k", "s", allow_orders=True, transport=t).cancel("abc")

    def test_bars_follow_page_tokens(self):
        page1 = {"bars": {"SPY": [FX["bars"]["bars"]["SPY"][0]]}, "next_page_token": "tok"}
        page2 = {"bars": {"SPY": [FX["bars"]["bars"]["SPY"][1]]}, "next_page_token": None}
        t = Recorder([(200, page1), (200, page2)])
        bars = AlpacaClient("k", "s", transport=t).bars("SPY", "2026-09-29")
        assert [b.close for b in bars] == [512.50, 513.05]
        q1, q2 = (parse_qs(urlparse(c[1]).query) for c in t.calls)
        assert q1["symbols"] == ["SPY"] and q1["feed"] == ["iex"] and "page_token" not in q1
        assert q2["page_token"] == ["tok"]
        assert urlparse(t.calls[0][1]).netloc == "data.alpaca.markets"


REC = json.loads((Path(__file__).parent / "fixtures" / "alpaca_recorded.json").read_text())


class TestRecordedPaper:
    """Over ``alpaca_recorded.json``: real paper-API responses from
    ``daybot record``. Where these disagree with the doc examples, these win.

    Positions and orders were empty when recorded (a fresh account), so their
    parsers are still checked only against the docs."""

    def test_account_parses_and_money_is_strings(self):
        raw = REC["account"]
        for key in ("equity", "last_equity", "cash", "buying_power"):
            assert isinstance(raw[key], str), key
        a = parse_account(raw)
        assert (a.equity, a.last_equity, a.cash, a.buying_power) == (
            100000.0, 100000.0, 100000.0, 400000.0)
        assert a.status == "ACTIVE" and not a.trading_blocked and not a.account_blocked

    def test_account_has_no_daytrade_count(self):
        # The live API matches the spec: no day-trade count. If this starts
        # failing, the field has appeared; check its meaning before using it.
        assert "daytrade_count" not in REC["account"]
        assert parse_account(REC["account"]).daytrade_count is None

    def test_clock_timestamp_has_nanoseconds(self):
        # The doc example has whole seconds; the API sends nine digits.
        assert REC["clock"]["timestamp"].count(".") == 1
        c = parse_clock(REC["clock"])
        assert c.is_open and c.timestamp.utcoffset().total_seconds() == -4 * 3600
        assert c.next_close.isoformat() == "2026-09-29T16:00:00-04:00"

    def test_empty_lists_are_lists(self):
        assert REC["positions"] == [] and REC["orders"] == []

    def test_bars_parse_with_numeric_fields(self):
        raw = REC["bars"]["bars"]["SPY"]
        assert isinstance(raw[0]["v"], int) and isinstance(raw[0]["o"], float)
        bars = [parse_bar("SPY", b) for b in raw]
        assert bars[0].start.isoformat() == "2026-09-22T12:05:00+00:00"
        assert (bars[0].open, bars[0].close, bars[0].volume, bars[0].trades) == (
            774.17, 774.04, 240.0, 3)
        assert all(b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)
                   for b in bars)

    def test_iex_premarket_bars_are_sparse_and_dropped(self):
        # IEX sends pre-market bars and skips minutes with no trades
        # (12:20 and 12:25 are missing). None of these is a session bar.
        from daybot.sessions import group_sessions

        bars = [parse_bar("SPY", b) for b in REC["bars"]["bars"]["SPY"]]
        gaps = {(b.start - a.start).total_seconds() / 60 for a, b in zip(bars, bars[1:])}
        assert gaps == {5.0, 15.0, 25.0}
        assert group_sessions(bars, 5) == {}
        assert REC["bars"]["next_page_token"]  # limit=5 was hit; more pages exist

    def test_ids_are_scrubbed(self):
        assert REC["account"]["id"] == "<scrubbed>"
        assert REC["account"]["account_number"] == "<scrubbed>"


ORD = json.loads((Path(__file__).parent / "fixtures" / "alpaca_recorded_orders.json").read_text())


def rec(step, method=None, n=-1):
    """The ``n``th recorded exchange of a step (the last by default)."""
    hits = [e for e in ORD["exchanges"] if e["step"] == step
            and (method is None or e["method"] == method)]
    assert hits, step
    return hits[n]


class TestRecordedOrders:
    """Over ``alpaca_recorded_orders.json``: 1-share paper orders placed,
    listed, cancelled and closed, every exchange kept in order."""

    def test_simple_order_class_is_empty_string(self):
        raw = rec("limit_submit")["response"]
        assert raw["order_class"] == "" and raw["status"] == "pending_new"
        o = parse_order(raw)
        assert o.order_class == "simple" and o.is_ours and o.is_open
        assert (o.type, o.limit_price, o.qty, o.filled_qty) == ("limit", 400.0, 1.0, 0.0)

    def test_cancel_is_204_even_when_repeated(self):
        assert rec("limit_cancel")["status"] == 204
        again = rec("limit_cancel_again")
        assert again["status"] == 204 and again["response"] is None
        assert parse_order(rec("limit_after_cancel")["response"]).status == "canceled"

    def test_bracket_legs_are_held_and_not_tagged_ours(self):
        o = parse_order(rec("bracket_submit")["response"])
        assert o.order_class == "bracket" and o.is_ours
        assert [(leg.type, leg.status) for leg in o.legs] == [("limit", "held"), ("stop", "held")]
        assert all(leg.is_open and not leg.is_ours for leg in o.legs)

    def test_filled_bracket(self):
        o = parse_order(rec("bracket_filled")["response"])
        assert o.status == "filled" and o.filled_shares == 1 and o.filled_avg_price == 762.69
        assert [(leg.type, leg.status) for leg in o.legs] == [("limit", "new"), ("stop", "held")]
        assert (o.legs[0].limit_price, o.legs[1].stop_price) == (770.41, 755.15)

    def test_listing_after_fill_shows_only_the_target_leg(self):
        # Once the parent fills, the nested listing drops it and the held
        # stop, and lists the target leg flat with Alpaca's client id.
        # Only the ids recorded at submit find both legs.
        listed = [parse_order(o) for o in rec("bracket_open_listing")["response"]]
        assert [(o.type, o.status, o.is_ours) for o in listed] == [("limit", "new", False)]
        parent = parse_order(rec("bracket_filled")["response"])
        assert listed[0].id == parent.legs[0].id

    def test_open_parent_is_listed_with_nested_legs(self):
        (o,) = [parse_order(x) for x in rec("unfilled_bracket_listing")["response"]]
        assert o.is_ours and o.status == "new" and len(o.legs) == 2

    def test_close_refused_while_a_leg_holds_the_shares(self):
        e = rec("close_while_legs_rest")
        assert e["status"] == 403
        assert (e["response"]["held_for_orders"], e["response"]["available"]) == ("1", "0")
        # Right after cancelling both legs, the close went through first time.
        assert rec("close_right_after_cancel")["status"] == 200

    def test_cancelling_a_filled_parent_cancels_its_legs(self):
        assert rec("filled_bracket_cancel_parent")["status"] == 204
        o = parse_order(rec("filled_bracket_after")["response"])
        assert o.status == "filled"
        assert [leg.status for leg in o.legs] == ["canceled", "canceled"]

    def test_cancelling_an_unfilled_parent_cancels_its_legs(self):
        o = parse_order(rec("unfilled_bracket_after")["response"])
        assert o.status == "canceled"
        assert [leg.status for leg in o.legs] == ["canceled", "canceled"]

    def test_long_position(self):
        raw = rec("bracket_positions", "GET", n=-1)["response"]
        assert (raw["qty"], raw["side"]) == ("1", "long")
        p = parse_position(raw)
        assert (p.symbol, p.qty, p.avg_entry_price) == ("SPY", 1, 762.69)

    def test_short_qty_is_signed(self):
        raw = rec("short_position")["response"]
        assert (raw["qty"], raw["side"]) == ("-1", "short")
        p = parse_position(raw)
        assert p.qty == -1 and p.market_value < 0

    def test_close_returns_an_order_on_the_opposite_side(self):
        o = parse_order(rec("short_close")["response"])
        assert (o.symbol, o.side, o.qty, o.status) == ("QQQ", "buy", 1.0, "pending_new")
        assert not o.is_ours  # Alpaca picks the client id for a position close

    def test_missing_position_404_through_the_client(self):
        e = rec("position_404")
        assert e["response"]["code"] == 40410000
        t = Recorder([(e["status"], e["response"])])
        assert AlpacaClient("k", "s", transport=t).position("SPY") is None

    def test_listing_lags_a_fill(self):
        # The close read 'filled' by id, then the listing still said 'new'.
        assert parse_order(rec("short_close_filled")["response"]).status == "filled"
        listing = next(e for e in ORD["exchanges"]
                       if e["step"] == "final" and e["url"].startswith("/v2/orders"))
        (listed,) = [parse_order(o) for o in listing["response"]]
        assert (listed.symbol, listed.side, listed.status) == ("QQQ", "buy", "new")
