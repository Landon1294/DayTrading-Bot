"""Drive a Trader from Alpaca's clock and bars: one step per closed bar."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

from daybot.alpaca import AlpacaClient
from daybot.sessions import EASTERN, REGULAR_OPEN, in_regular_session, to_eastern
from daybot.trader import Trader


def closed_session_bars(bars, now: datetime, bar_minutes: int):
    """Only bars that have *finished* and lie inside the regular session. The
    bar in progress is dropped: acting on it is acting on a price that has
    not settled."""
    length = timedelta(minutes=bar_minutes)
    return [b for b in bars if b.start + length <= now and in_regular_session(b.start, bar_minutes)]


def next_boundary(now: datetime, bar_minutes: int) -> datetime:
    step = bar_minutes * 60
    ts = math.floor(now.timestamp() / step + 1) * step
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def run(client: AlpacaClient, trader: Trader, *, bar_minutes: int, feed: str = "iex",
        settle_seconds: float = 8.0, once: bool = False, flatten_on_exit: bool = True) -> None:
    trader.start()
    try:
        while True:
            clock = client.clock()
            if not clock.is_open:
                if once:
                    trader.say(f"market closed; next open {to_eastern(clock.next_open):%a %H:%M} ET")
                    return
                wait = (clock.next_open - clock.timestamp).total_seconds()
                trader.say(f"market closed; sleeping until {to_eastern(clock.next_open):%a %H:%M} ET")
                time.sleep(max(30.0, min(wait, 3600.0)))
                continue
            if not once:
                # Wait for the bar to close, plus a few seconds for the data
                # feed to publish it.
                target = next_boundary(clock.timestamp, bar_minutes) + timedelta(seconds=settle_seconds)
                time.sleep(max(0.0, (target - clock.timestamp).total_seconds()))
            now = datetime.now(timezone.utc)
            day = to_eastern(now).date()
            opened = datetime.combine(day, REGULAR_OPEN, tzinfo=EASTERN)
            bars = client.bars(trader.symbol, opened, now, timeframe=f"{bar_minutes}Min",
                               feed=feed, adjustment="raw")
            trader.step(closed_session_bars(bars, now, bar_minutes), now)
            if once:
                return
    except KeyboardInterrupt:
        if trader.dry_run:
            trader.say("\ninterrupted: dry run, so there are no orders or position to close")
        else:
            trader.say("\ninterrupted: cancelling the bot's orders"
                       + (" and closing its position" if flatten_on_exit else ""))
        trader.shutdown(flatten=flatten_on_exit)
