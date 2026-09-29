# DayTrading-Bot -- intraday stock/ETF bot on Alpaca

Package: `daybot/`. Read `README.md` first.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest              # ~7s, all tests
.venv/bin/python -m pytest -m "not slow"
```

The system Python is fine; a venv keeps it clean. No dependencies beyond
`tzdata` (and pytest for development). HTTP uses the standard library.

## Rules that must not be quietly reverted

Most of these come from the Kalshi bot (TV-OFF), where each was learned by
finding a real bug.

**Parsers raise on a missing field.** Never default a required field to zero.
A renamed field that reads as zero fails silently: on Kalshi, every position
parsed as flat and the exposure limits were dead. Alpaca sends money and
quantities as JSON strings.

**Parsers are tested against recorded paper responses** (2026-09-29):
`tests/fixtures/alpaca_recorded.json` (account, clock, bars, from
`daybot record`) and `alpaca_recorded_orders.json` (1-share orders: limit,
bracket, short, cancels, closes). Re-record if the API changes. What they
showed:
- `daytrade_count` is absent from the account: treat it as unknown, never zero.
- Bars are start-labelled (5Min bars rebuilt from 1Min). IEX skips minutes
  with no trades.
- Once a bracket's entry fills, the open-order listing shows only the target
  leg, without our client id; the held stop is not listed. Leg ids must be
  recorded at submit.
- Cancelling a bracket's parent cancels its legs, filled or not.
- Closing shares a resting leg holds is refused (403, `held_for_orders`).
- A short's `qty` is signed. Simple orders have `order_class: ""`. A repeat
  cancel returns 204. The listing lags a fill by at least a moment.

**No lookahead.** A strategy sees closed bars only. Its orders fill at the
next bar's open. Bars are labelled on their *start* time. If a stop and a
target share a bar, the stop wins.

**Edge means t >= 3 on held-out days' daily P&L, net of costs.** Test per day,
never per trade. Split by whole days in time order. Choose parameters on
validation only; the test split is never used for selection.

**The null test must pass.** On a random walk with zero costs, nothing may
show an edge. If it fails, stop and find the leak.

**Costs are overstated, never understated.** Fee defaults are the higher
recent values. Slippage applies to every market fill.

**Live safety:**
- A human approves every entry, and stale approvals are discarded.
- Brackets rest at the broker.
- The bot flattens by quantity and only its own shares, never "close all".
- It cancels by the order ids it recorded, plus the listing: the listing lags.
- It halts rather than guesses when broker state disagrees with its own.
- Orders are refused unless the client was built with `allow_orders`.
- Live needs separate keys, `--live --enable-live-orders`, and typing `LIVE`.

**The daily loss gate reads the account's day P&L, gains ignored.** Keep the
gate on every check as well as the trip in `record_trade`: the gate is what
survives a restart.

## Status

- Backtester, risk gate, strategies, stats: done and tested.
- Alpaca client and live loop: tested against an in-memory broker that
  mimics the recorded paper behaviour, and over the recorded payloads.
  Orders have been placed by hand on paper; **`daybot run` has not.**
- ORB and VWAP reversion swept on SPY, QQQ, IWM (SIP, 2019 to 2026-09): no
  edge. Five published tactics pre-registered and tested in docs/RESEARCH.md
  (`research/preregistered.py`): no edge in 15 tests. Nothing goes to paper.
- docs/DIRECTION.md recommends ending the intraday ETF search and, if the
  project continues, a low-turnover trend-following rebalancer. The user has
  not chosen yet.
- FINRA retired the PDT rule on 2026-06-04 and Alpaca removed it; the gate's
  `pdt_equity_threshold` now defaults to 0 (off).

## Next steps, in order

0. The user picks a direction from docs/DIRECTION.md; do not start one
   unasked.
1. No strategy goes to paper trading. A new hypothesis is pre-registered in
   docs/RESEARCH.md (rules, grid, verdict) and committed *before* it is run,
   then judged on the same data and split. The test split has now produced 39
   held-out results; a new idea should also be checked on data after
   2026-09-28, which nothing has seen.
2. During market hours, `daybot run --dry-run` to see the live loop run
   against real bars and clock without sending orders.
3. Only if something clears t >= 3 on test: paper trade it with `daybot run`,
   and compare real fills with the backtest's assumed slippage.
4. On paper, check how bracket legs behave when an entry partly fills.
