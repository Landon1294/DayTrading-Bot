"""The broker interface, and the order and position types it trades in.

``daybot.alpaca.AlpacaClient`` is the one implementation. Anything else
(Interactive Brokers, Tradier) plugs in by providing the same methods.

Requirements for an implementation, each learned the hard way on the Kalshi
bot this project is modelled on:

- Parse every field against the broker's *current* docs and a recorded real
  payload. A renamed field does not raise; it parses as zero or empty, and a
  position that reads as flat silently disables every exposure limit.
- Refuse to submit unless constructed with ``allow_orders=True``, and point at
  live money only through a separate, explicit switch.
- ``close`` takes a quantity. Flatten only what the bot opened: "close all
  positions" would also sell anything the account holds by hand.
- Order and position listings may lag a write by a second or more. Cancel by
  the ids the bot placed, not only by what a listing returns.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from daybot.models import Account, Clock

CLIENT_ORDER_PREFIX = "daybot-"


def new_client_order_id() -> str:
    """Every order the bot places carries this prefix, which is how it tells
    its own orders from ones placed by hand on the same account."""
    return CLIENT_ORDER_PREFIX + uuid.uuid4().hex[:24]


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str  # "buy" | "sell"
    qty: int
    client_order_id: str
    type: str = "market"
    limit_price: Decimal | None = None
    # Attached exits. Both -> bracket; one -> one-triggers-other. They rest at
    # the broker, so they still protect the position if this process dies.
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be buy or sell, not {self.side!r}")


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: int  # signed: negative is short
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    client_order_id: str
    symbol: str
    side: str
    type: str
    status: str
    qty: float | None
    filled_qty: float
    filled_avg_price: float | None
    limit_price: float | None = None
    stop_price: float | None = None
    order_class: str = "simple"
    legs: tuple["BrokerOrder", ...] = field(default_factory=tuple)

    OPEN = frozenset({"new", "partially_filled", "accepted", "pending_new", "accepted_for_bidding",
                      "held", "pending_cancel", "pending_replace", "calculated", "stopped",
                      "suspended", "done_for_day"})

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    @property
    def is_ours(self) -> bool:
        return self.client_order_id.startswith(CLIENT_ORDER_PREFIX)

    @property
    def filled_shares(self) -> int:
        """Shares actually obtained, rounded *down*: you cannot close more
        than you hold."""
        return int(math.floor(self.filled_qty + 1e-9))


class Broker(Protocol):
    allow_orders: bool

    def account(self) -> Account: ...
    def clock(self) -> Clock: ...
    def position(self, symbol: str) -> BrokerPosition | None: ...
    def order(self, order_id: str) -> BrokerOrder: ...
    def open_orders(self) -> list[BrokerOrder]: ...
    def submit(self, req: OrderRequest) -> BrokerOrder: ...
    def cancel(self, order_id: str) -> None: ...
    def close(self, symbol: str, qty: int) -> BrokerOrder: ...
