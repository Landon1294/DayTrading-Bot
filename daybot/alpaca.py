"""Alpaca REST client: trading (paper or live) and historical bars.

Field names follow Alpaca's published OpenAPI spec as fetched 2026-09-29.
Every money and quantity field arrives as a JSON *string* ("512.34"), and the
parsers below read them as such.

Parsers are strict on purpose. The Kalshi bot this project descends from lost
weeks to renamed fields that parsed as zero: a position that reads as flat
silently disables every exposure limit. Here a missing required field raises
``AlpacaSchemaError`` naming the field, so a rename stops the bot instead of
quietly blinding it.

Nothing is verified against a live response yet. When paper keys exist, run
``daybot record`` and add the output to the fixtures.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable

from daybot.broker import BrokerOrder, BrokerPosition, OrderRequest
from daybot.models import Account, Bar, Clock

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

# (method, url, headers, body bytes or None) -> (status, response bytes)
Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


class AlpacaError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} from {url}: {body[:300]}")
        self.status = status
        self.body = body


class AlpacaSchemaError(ValueError):
    """A response was missing a field the parser needs. Treat as a stop-the-
    bot condition: the API has probably changed underneath us."""


class OrdersDisabled(RuntimeError):
    pass


# -- parsing -------------------------------------------------------------


def _req(d: dict, key: str, what: str):
    if key not in d or d[key] is None:
        raise AlpacaSchemaError(f"{what}: missing required field {key!r}; got keys {sorted(d)}")
    return d[key]


def _num(d: dict, key: str, what: str) -> float:
    try:
        return float(_req(d, key, what))
    except (TypeError, ValueError):
        raise AlpacaSchemaError(f"{what}: field {key!r} is not numeric: {d.get(key)!r}") from None


def _opt_num(d: dict, key: str) -> float | None:
    v = d.get(key)
    return None if v in (None, "") else float(v)


def _ts(text: str) -> datetime:
    ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise AlpacaSchemaError(f"timestamp without zone: {text!r}")
    return ts


def parse_account(d: dict) -> Account:
    w = "account"
    return Account(
        equity=_num(d, "equity", w),
        last_equity=_num(d, "last_equity", w),
        cash=_num(d, "cash", w),
        buying_power=_num(d, "buying_power", w),
        trading_blocked=bool(d.get("trading_blocked", False)),
        account_blocked=bool(d.get("account_blocked", False)),
        status=str(_req(d, "status", w)),
        # Not in the current spec; read if it ever appears, never assumed.
        daytrade_count=int(d["daytrade_count"]) if d.get("daytrade_count") is not None else None,
        raw=d,
    )


def parse_clock(d: dict) -> Clock:
    w = "clock"
    return Clock(_ts(_req(d, "timestamp", w)), bool(_req(d, "is_open", w)),
                 _ts(_req(d, "next_open", w)), _ts(_req(d, "next_close", w)))


def _shares_away_from_zero(x: float) -> int:
    """A fractional holding is real exposure; never round it away to nothing."""
    return int(math.copysign(math.ceil(abs(x) - 1e-9), x)) if x else 0


def parse_position(d: dict) -> BrokerPosition:
    w = "position"
    qty = _num(d, "qty", w)
    side = _req(d, "side", w)
    if side not in ("long", "short"):
        raise AlpacaSchemaError(f"position: unknown side {side!r}")
    # Paper sends a short's qty signed ("-1"); the docs do not say so. Use the
    # side field as the authority either way.
    signed = abs(qty) if side == "long" else -abs(qty)
    return BrokerPosition(
        symbol=_req(d, "symbol", w),
        qty=_shares_away_from_zero(signed),
        avg_entry_price=_num(d, "avg_entry_price", w),
        market_value=_num(d, "market_value", w),
        unrealized_pl=_num(d, "unrealized_pl", w),
    )


def parse_order(d: dict) -> BrokerOrder:
    w = "order"
    status = _req(d, "status", w)
    return BrokerOrder(
        id=_req(d, "id", w),
        client_order_id=d.get("client_order_id") or "",
        symbol=_req(d, "symbol", w),
        side=_req(d, "side", w),
        type=d.get("type") or d.get("order_type") or "",
        status=status,
        qty=_opt_num(d, "qty"),
        filled_qty=_num(d, "filled_qty", w),
        filled_avg_price=_opt_num(d, "filled_avg_price"),
        limit_price=_opt_num(d, "limit_price"),
        stop_price=_opt_num(d, "stop_price"),
        order_class=d.get("order_class") or "simple",
        legs=tuple(parse_order(leg) for leg in (d.get("legs") or [])),
    )


def parse_bar(symbol: str, d: dict) -> Bar:
    w = "bar"
    return Bar(symbol, _ts(_req(d, "t", w)), _num(d, "o", w), _num(d, "h", w), _num(d, "l", w),
               _num(d, "c", w), _num(d, "v", w), vwap=_opt_num(d, "vw"),
               trades=int(d["n"]) if d.get("n") is not None else None)


def order_body(req: OrderRequest) -> dict:
    """Build the POST /v2/orders body. Numbers are sent as strings, as the
    spec types them, and prices must already be on the tick (Decimal)."""
    if req.qty < 1:
        raise ValueError("qty must be a positive whole number of shares")
    body: dict = {
        "symbol": req.symbol,
        "qty": str(req.qty),
        "side": req.side,
        "type": req.type,
        "time_in_force": "day",
        "client_order_id": req.client_order_id,
    }
    if req.type == "limit":
        if req.limit_price is None:
            raise ValueError("limit order without a limit price")
        body["limit_price"] = str(req.limit_price)
    if req.stop_loss is not None and req.take_profit is not None:
        body["order_class"] = "bracket"
    elif req.stop_loss is not None or req.take_profit is not None:
        body["order_class"] = "oto"
    if req.stop_loss is not None:
        body["stop_loss"] = {"stop_price": str(req.stop_loss)}
    if req.take_profit is not None:
        body["take_profit"] = {"limit_price": str(req.take_profit)}
    return body


# -- the client ----------------------------------------------------------


def _urllib_transport(timeout: float) -> Transport:
    def send(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    return send


class AlpacaClient:
    def __init__(self, key_id: str, secret_key: str, *, paper: bool = True,
                 allow_orders: bool = False, transport: Transport | None = None,
                 timeout: float = 15.0):
        if not key_id or not secret_key:
            raise ValueError("Alpaca key id and secret are required")
        self.paper = paper
        self.allow_orders = allow_orders
        self.trading_url = PAPER_URL if paper else LIVE_URL
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key,
                         "Accept": "application/json"}
        self._send = transport or _urllib_transport(timeout)

    @classmethod
    def from_env(cls, *, paper: bool = True, allow_orders: bool = False, **kw) -> "AlpacaClient":
        """Paper and live keys live in *different* variables, so a paper key
        can never end up pointed at live money by a flag flip alone."""
        prefix = "ALPACA_" if paper else "ALPACA_LIVE_"
        key, secret = os.environ.get(prefix + "API_KEY_ID"), os.environ.get(prefix + "API_SECRET_KEY")
        if not key or not secret:
            raise SystemExit(f"set {prefix}API_KEY_ID and {prefix}API_SECRET_KEY "
                             f"({'paper' if paper else 'LIVE'} keys)")
        return cls(key, secret, paper=paper, allow_orders=allow_orders, **kw)

    def _call(self, method: str, base: str, path: str, params: dict | None = None,
              body: dict | None = None):
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = dict(self._headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, raw = self._send(method, url, headers, data)
        text = raw.decode("utf-8", "replace") if raw else ""
        if status >= 400:
            raise AlpacaError(status, text, url)
        return json.loads(text) if text else None

    # read-only ------------------------------------------------------------

    def account(self) -> Account:
        return parse_account(self._call("GET", self.trading_url, "/v2/account"))

    def clock(self) -> Clock:
        return parse_clock(self._call("GET", self.trading_url, "/v2/clock"))

    def positions(self) -> list[BrokerPosition]:
        return [parse_position(p) for p in self._call("GET", self.trading_url, "/v2/positions")]

    def position(self, symbol: str) -> BrokerPosition | None:
        try:
            return parse_position(self._call("GET", self.trading_url, f"/v2/positions/{symbol}"))
        except AlpacaError as e:
            if e.status == 404:
                return None
            raise

    def order(self, order_id: str) -> BrokerOrder:
        return parse_order(self._call("GET", self.trading_url, f"/v2/orders/{order_id}",
                                      {"nested": "true"}))

    def open_orders(self) -> list[BrokerOrder]:
        rows = self._call("GET", self.trading_url, "/v2/orders",
                          {"status": "open", "limit": 500, "nested": "true"})
        return [parse_order(o) for o in rows]

    def bars(self, symbol: str, start: datetime | str, end: datetime | str | None = None, *,
             timeframe: str = "5Min", feed: str = "iex", adjustment: str = "split") -> list[Bar]:
        """Historical bars, following ``next_page_token`` to the end.

        ``feed='iex'`` is what the free plan serves in real time. IEX is one
        exchange: its volume, and so any VWAP computed from it, is a small
        slice of the whole market."""
        out: list[Bar] = []
        token = None
        while True:
            page = self._call("GET", DATA_URL, "/v2/stocks/bars", {
                "symbols": symbol, "timeframe": timeframe,
                "start": start.isoformat() if isinstance(start, datetime) else start,
                "end": end.isoformat() if isinstance(end, datetime) else end,
                "limit": 10000, "feed": feed, "adjustment": adjustment, "sort": "asc",
                "page_token": token,
            })
            bars = _req(page, "bars", "bars response")
            out.extend(parse_bar(symbol, b) for b in (bars.get(symbol) or []))
            token = page.get("next_page_token")
            if not token:
                return out

    # writes -----------------------------------------------------------------

    def _guard(self) -> None:
        if not self.allow_orders:
            raise OrdersDisabled("this client was built without allow_orders; refusing to trade")

    def submit(self, req: OrderRequest) -> BrokerOrder:
        self._guard()
        return parse_order(self._call("POST", self.trading_url, "/v2/orders", body=order_body(req)))

    def cancel(self, order_id: str) -> None:
        self._guard()
        try:
            self._call("DELETE", self.trading_url, f"/v2/orders/{order_id}")
        except AlpacaError as e:
            # Paper returns 204 when cancelling an order already cancelled or
            # filled; 422 may still mean the same. Either way it is not resting.
            if e.status not in (404, 422):
                raise

    def close(self, symbol: str, qty: int) -> BrokerOrder:
        """Close ``qty`` shares of ``symbol`` at market. Always by quantity:
        the account may hold shares the bot did not buy."""
        self._guard()
        if qty < 1:
            raise ValueError("qty must be positive")
        return parse_order(self._call("DELETE", self.trading_url, f"/v2/positions/{symbol}",
                                      {"qty": str(qty)}))

