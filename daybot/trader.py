"""The live decision loop for one symbol, independent of how bars arrive.

Division of labour:

- The strategy proposes. The risk gate sizes and may refuse. A human approves
  every *entry* with a keystroke; an approval that arrives after the next bar
  has started is discarded, because the plan was priced on a stale bar.
- Exits need no approval: closing only ever reduces risk. The stop and target
  go to the broker attached to the entry (a bracket), so they keep protecting
  the position if this process crashes or loses its connection.
- The bot owns only the shares it bought. Shares the account already held
  when it started are recorded as a baseline and never touched.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from daybot.broker import Broker, BrokerOrder, OrderRequest, new_client_order_id
from daybot.config import RiskSettings
from daybot.costs import CostModel
from daybot.models import Action, Bar, Position, Side, Signal, Trade, round_to_tick
from daybot.risk import RiskManager
from daybot.sessions import to_eastern
from daybot.strategy.base import Strategy

Approver = Callable[[str], bool]


class Journal:
    """Append-only JSON lines: every proposal, refusal, approval, order and
    trade, so a session can be reconstructed after the fact."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")

    def day_trade_dates(self) -> list:
        """Dates of past day trades, so the pattern-day-trader count survives
        a restart. The broker does not report one this bot can rely on."""
        from datetime import date

        if not self.path or not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("event") == "trade" and rec.get("day_trade"):
                out.append(date.fromisoformat(rec["session_date"]))
        return out


def console_approver(plan: str) -> bool:
    print(f"\nPROPOSED  {plan}")
    return input("Send it? type y to send, anything else to skip: ").strip().lower() == "y"


class Trader:
    MISMATCH_LIMIT = 3

    def __init__(self, broker: Broker, strategy: Strategy, symbol: str, *,
                 risk: RiskSettings | None = None, costs: CostModel | None = None,
                 bar_minutes: int = 5, approver: Approver = console_approver,
                 journal: Journal | None = None, dry_run: bool = True,
                 now: Callable[[], datetime] | None = None,
                 sleep: Callable[[float], None] = time.sleep, fill_timeout: float = 20.0,
                 say: Callable[[str], None] = print):
        self.broker = broker
        self.strategy = strategy
        self.symbol = symbol
        self.rm = RiskManager(risk or RiskSettings())
        self.costs = costs or CostModel()
        self.bar_len = timedelta(minutes=bar_minutes)
        self.approver = approver
        self.journal = journal or Journal(None)
        self.dry_run = dry_run
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.fill_timeout = fill_timeout
        self.say = say

        self.position: Position | None = None
        self.entry_order_id: str | None = None
        self.our_order_ids: set[str] = set()
        self.baseline_qty = 0
        self.day = None
        self.trades: list[Trade] = []
        self._mismatches = 0

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        pos = self.broker.position(self.symbol)
        self.baseline_qty = pos.qty if pos else 0
        self.rm.day_trade_dates.extend(self.journal.day_trade_dates())
        self.journal.log("start", symbol=self.symbol, baseline_qty=self.baseline_qty,
                         dry_run=self.dry_run, strategy=self.strategy.name,
                         params=self.strategy.params())
        if self.baseline_qty:
            self.say(f"note: the account already holds {self.baseline_qty} {self.symbol}; "
                     f"the bot will leave those shares alone")

    def shutdown(self, *, flatten: bool) -> None:
        if self.dry_run:
            return
        self._cancel_ours()
        if self.position is not None and flatten:
            self.flatten("shutdown", self.now())
        elif self.position is not None:
            self.say(f"WARNING: leaving {self.position.qty} {self.symbol} open with no "
                     f"resting stop -- the bracket was cancelled")
        self.journal.log("shutdown", position=self.position and self.position.qty)

    # -- one decision per closed bar ------------------------------------------

    def step(self, bars: list[Bar], now: datetime) -> None:
        day = to_eastern(now).date()
        if day != self.day:
            self.day = day
            self.strategy.reset()
            self.rm.start_day(day)
        acct = self.broker.account()
        # The daily loss gate reads the account's own P&L for the day, with
        # gains ignored: a loss anywhere in the account tightens the limit, a
        # gain elsewhere never loosens it. It survives a restart for free.
        self.rm.realized_today = min(0.0, acct.equity - acct.last_equity)
        if acct.trading_blocked or acct.account_blocked:
            self.rm._halt("broker reports trading blocked")
        self._reconcile(now, bars[-1].close if bars else None)
        if self.rm.must_flatten(now):
            if self.position is not None:
                self.flatten("flatten before close", now)
            return
        if not bars:
            return
        sig = self.strategy.on_bar(bars, self.position)
        if sig is None:
            return
        if sig.action is Action.EXIT:
            if self.position is not None:
                self.flatten(sig.reason, now)
            return
        if self.position is None:
            self._propose(sig, bars[-1], now, acct)

    # -- entries --------------------------------------------------------------

    def _propose(self, sig: Signal, bar: Bar, now: datetime, acct) -> None:
        price = bar.close
        d = self.rm.check_entry(sig, price, now, equity=acct.equity, buying_power=acct.buying_power,
                                broker_day_trades=acct.daytrade_count)
        if not d.ok:
            self.journal.log("refused", reason=d.reason, signal=sig.reason)
            self.say(f"signal refused: {d.reason} ({sig.reason})")
            return
        long = sig.side is Side.LONG
        # Round exits toward the entry: a stop that triggers a hair early, a
        # target taken a hair early. Never the direction that adds risk.
        stop = round_to_tick(sig.stop, direction="up" if long else "down") if sig.stop else None
        target = round_to_tick(sig.target, direction="down" if long else "up") if sig.target else None
        if stop is not None and (float(stop) >= price if long else float(stop) <= price):
            self.journal.log("refused", reason="stop within a tick of the price", signal=sig.reason)
            self.say(f"signal refused: stop {stop} is within a tick of {price:.2f}")
            return
        side = "buy" if long else "sell"
        risk_txt = f"risk ~${d.qty * abs(price - float(stop)):,.2f}" if stop else "no stop"
        plan = (f"{side.upper()} {d.qty} {self.symbol} at market (last {price:.2f}), "
                f"notional ~${d.qty * price:,.2f}, stop {stop}, target {target}, {risk_txt} "
                f"-- {sig.reason}")
        self.journal.log("proposal", plan=plan, qty=d.qty, price=price, stop=stop, target=target)
        if self.dry_run:
            self.say(f"[dry-run] would propose: {plan}")
            return
        asked = self.now()
        if not self.approver(plan):
            self.journal.log("declined", plan=plan)
            return
        if self.now() - asked > self.bar_len:
            self.journal.log("stale_approval", plan=plan)
            self.say("approval arrived after the next bar began; plan discarded as stale")
            return
        req = OrderRequest(self.symbol, side, d.qty, new_client_order_id(),
                           stop_loss=stop, take_profit=target)
        order = self.broker.submit(req)
        self.our_order_ids.add(order.id)
        self.entry_order_id = order.id
        self.rm.record_entry()
        self.journal.log("submitted", order_id=order.id, client_order_id=req.client_order_id,
                         qty=d.qty, side=side)
        filled = self._await_fill(order.id)
        self.our_order_ids.update(leg.id for leg in filled.legs)
        got = filled.filled_shares
        entry_side = Side.LONG if long else Side.SHORT
        if got >= d.qty and filled.filled_avg_price is not None:
            self.position = Position(self.symbol, entry_side, got, filled.filled_avg_price, now,
                                     stop=float(stop) if stop else None,
                                     target=float(target) if target else None)
            self.journal.log("filled", qty=got, price=filled.filled_avg_price)
            self.say(f"filled {side} {got} {self.symbol} @ {filled.filled_avg_price:.2f}")
            return
        # Not filled in time. How attached exits behave on a partly filled
        # parent is not verified, so do not hold a position whose protection
        # is uncertain: cancel, and close whatever did fill.
        self.broker.cancel(order.id)
        filled = self.broker.order(order.id)
        got = filled.filled_shares
        self.journal.log("entry_incomplete", wanted=d.qty, got=got, status=filled.status)
        if got > 0 and filled.filled_avg_price is not None:
            self.position = Position(self.symbol, entry_side, got, filled.filled_avg_price, now)
            self.flatten("entry only partly filled", now)
        else:
            self.say(f"entry did not fill within {self.fill_timeout:.0f}s; cancelled")

    def _await_fill(self, order_id: str) -> BrokerOrder:
        deadline = time.monotonic() + self.fill_timeout
        while True:
            o = self.broker.order(order_id)
            if o.status == "filled" or not o.is_open or time.monotonic() >= deadline:
                return o
            self.sleep(0.5)

    # -- exits ----------------------------------------------------------------

    def _bot_qty_at_broker(self) -> int:
        pos = self.broker.position(self.symbol)
        return (pos.qty if pos else 0) - self.baseline_qty

    def _reconcile(self, now: datetime, last_price: float | None) -> None:
        """Notice exits the broker made on its own (bracket stop or target)."""
        if self.position is None or self.entry_order_id is None or self.dry_run:
            return
        entry = self.broker.order(self.entry_order_id)
        closed = [leg for leg in entry.legs if leg.filled_shares > 0 and leg.filled_avg_price]
        closed_qty = sum(leg.filled_shares for leg in closed)
        held = self.position.side.sign * self._bot_qty_at_broker()
        if closed_qty == 0:
            # Positions can lag writes by a second or more; one odd read is
            # not a reason to act. A persistent one is a reason to stop.
            if held < self.position.qty:
                self._mismatches += 1
                self.journal.log("position_mismatch", ours=self.position.qty, broker=held)
                if self._mismatches >= self.MISMATCH_LIMIT:
                    self.rm._halt(f"broker shows {held} {self.symbol} but the bot believes "
                                  f"{self.position.qty}; manual check needed")
                    self.say(f"HALTED: {self.rm.halt_reason}")
            else:
                self._mismatches = 0
            return
        self._mismatches = 0
        px = sum(leg.filled_avg_price * leg.filled_shares for leg in closed) / closed_qty
        reason = "stop" if any(leg.type in ("stop", "stop_limit") for leg in closed) else "target"
        self._record_exit(min(closed_qty, self.position.qty), px, reason, now)

    def flatten(self, reason: str, now: datetime) -> None:
        if self.position is None:
            return
        if self.dry_run:
            self.say(f"[dry-run] would close {self.position.qty} {self.symbol}: {reason}")
            self.position = None
            return
        self._cancel_ours()
        self._reconcile(now, None)  # a leg may have filled before the cancel landed
        if self.position is None:
            return
        held = max(0, self.position.side.sign * self._bot_qty_at_broker())
        qty = min(self.position.qty, held)
        if qty < self.position.qty:
            self.journal.log("flatten_short", ours=self.position.qty, broker=held)
        if qty == 0:
            self.rm._halt(f"cannot find the bot's {self.position.qty} {self.symbol} at the broker; "
                          f"manual check needed")
            self.say(f"HALTED: {self.rm.halt_reason}")
            return
        last_err = None
        for _ in range(5):
            try:
                order = self.broker.close(self.symbol, qty)
                break
            except Exception as exc:  # e.g. shares still held by a cancelling leg
                last_err = exc
                self.sleep(1.0)
        else:
            self.rm._halt(f"could not close {qty} {self.symbol}: {last_err}; manual intervention needed")
            self.say(f"HALTED: {self.rm.halt_reason}")
            return
        self.our_order_ids.add(order.id)
        filled = self._await_fill(order.id)
        if filled.filled_avg_price is None or filled.filled_shares == 0:
            self.rm._halt(f"close order {order.id} for {qty} {self.symbol} did not fill "
                          f"(status {filled.status}); manual check needed")
            self.say(f"HALTED: {self.rm.halt_reason}")
            return
        self._record_exit(filled.filled_shares, filled.filled_avg_price, reason, now)

    def _record_exit(self, qty: int, price: float, reason: str, now: datetime) -> None:
        pos = self.position
        long = pos.side is Side.LONG
        costs = (self.costs.fees(pos.entry_price, qty, selling=not long)
                 + self.costs.fees(price, qty, selling=long))
        trade = Trade(self.symbol, pos.side, qty, pos.entry_time, pos.entry_price, now, price,
                      reason, pos.side.sign * (price - pos.entry_price) * qty, costs)
        self.rm.record_trade(trade)
        self.trades.append(trade)
        self.journal.log("trade", qty=qty, entry=pos.entry_price, exit=price, reason=reason,
                         net=round(trade.net, 2), session_date=trade.session_date.isoformat(),
                         day_trade=trade.is_day_trade)
        self.say(f"closed {qty} {self.symbol} @ {price:.2f} ({reason}), net ${trade.net:,.2f}")
        pos.qty -= qty
        if pos.qty <= 0:
            self.position = None
            self.entry_order_id = None

    def _cancel_ours(self) -> None:
        """Cancel every order the bot placed for this symbol. The listing may
        not yet show an order placed a second ago, so the ids the bot recorded
        itself are cancelled too."""
        ids = set(self.our_order_ids)
        for o in self.broker.open_orders():
            if o.is_ours and o.symbol == self.symbol:
                ids.add(o.id)
                ids.update(leg.id for leg in o.legs)
        for oid in ids:
            self.broker.cancel(oid)
        self.journal.log("cancelled", ids=sorted(ids))
