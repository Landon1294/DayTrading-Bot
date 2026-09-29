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

**Positions and orders are not yet verified against a live response.**
`tests/fixtures/alpaca_recorded.json` (from `daybot record` on paper,
2026-09-29) covers account, clock and bars; its positions and orders were
empty. `tests/fixtures/alpaca_doc_examples.json` is built from the docs and
is all the order and position parsers have been checked against.
`daytrade_count` is absent from the live account payload: treat it as
unknown, never as zero. Alpaca bars are start-labelled (checked on paper by
rebuilding 5Min bars from 1Min bars). IEX bars skip minutes with no trades.

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
- Alpaca client and live loop: tested against an in-memory broker and the
  documented examples. Paper keys work: `daybot check` and `daybot record`
  ran; account, clock and bar parsers pass on the recorded payload.
  **No order has been placed on Alpaca yet.**
- No strategy has been tested on real market data yet.

## Next steps, in order

1. Place and cancel a paper order (and hold a position) so `daybot record`
   captures real order and position payloads; add tests over them.
2. `daybot fetch` two or more years of SPY (and a few liquid ETFs) at 5 minutes.
3. `daybot sweep` each strategy. Expect no edge; believe it if that's the result.
4. Only if something clears t >= 3 on test: paper trade it with `daybot run`,
   and compare real fills with the backtest's assumed slippage.
5. On paper, check how bracket legs behave when an entry partly fills.
