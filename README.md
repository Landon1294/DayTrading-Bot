# DayTrading-Bot

An intraday trading bot for US stocks and ETFs, built on Alpaca. It is built
around one idea: **prove an edge before risking money, and assume there isn't
one until the evidence says otherwise.** Most day-trading strategies lose
after costs. The bot's first job is to tell you whether yours does.

It is a sibling of [TV-OFF](https://github.com/Landon1294/TV-OFF), a Kalshi
bot, and inherits that project's hard-won rules: strict parsers, a human
approval on every trade, and statistics that refuse to call noise an edge.

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest              # ~7s
```

Alpaca keys go in environment variables, never in the repo:

| variable | used for |
| --- | --- |
| `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | **paper** trading and market data |
| `ALPACA_LIVE_API_KEY_ID`, `ALPACA_LIVE_API_SECRET_KEY` | live trading -- leave unset |

Paper and live keys are read from different variables on purpose, so no
single flag can point a paper setup at real money.

## The workflow, in order

**1. Get data.** `daybot fetch --symbol SPY --start 2019-01-01 --feed sip --out data/spy.csv`
downloads 5-minute bars, cut to the exchange calendar (half days end at
13:00). The `sip` feed is every exchange and is free for history older than
15 minutes; the default `iex` is one exchange, with a small slice of the
volume and gaps where it saw no trade. Any CSV with `timestamp,open,high,low,close,volume`
(zone-aware timestamps) also works; see `daybot/data.py`.

**2. Backtest against a baseline.**

```bash
daybot backtest --csv data/spy.csv --strategy orb --param range_minutes=30
```

This reports the strategy next to `buy_open` (long at the open, flat at the
close) and a paired t-stat between them. Beating the baseline matters more
than making money: in a rising market everything long makes money.

**3. Get a held-out estimate.**

```bash
daybot sweep --csv data/spy.csv --strategy orb \
  --grid range_minutes=15,30,60 --grid target_r=1,2,3
```

The days are split in time order: the first 60% set aside, then 20% validation and 20% test.
Parameters are **chosen on validation and reported on test**. The test number
is the only one that estimates live performance. In one run on pure random
data the sweep picked a combination with a validation Sharpe of 1.49 that then
lost money on test. That gap is what overfitting looks like, and it is why
the tool reports both.

**4. Paper trade.** `daybot check` verifies the keys (read-only). Then:

```bash
daybot run --symbol SPY --strategy orb --dry-run   # proposes, sends nothing
daybot run --symbol SPY --strategy orb             # paper orders, you approve each
```

**5. Live.** Only after the strategy has an edge on held-out days *and* has
paper traded long enough to compare fills with the backtest. It needs
`--live --enable-live-orders`, live keys, and typing `LIVE` at a prompt.

## Results so far

On 2026-09-29, with SIP 5-minute bars from 2019-01-02 to 2026-09-28 (1,945
days each), default costs, and `--equity 100000`, nothing has an edge.
Each row chose among 18 combinations on 389 validation days and was tested
on the following 389 days:

| symbol | strategy | chosen on validation | test t | test net |
|---|---|---|---|---|
| SPY | orb  | range 15, target 2R, shorts | -0.53 | -$54 |
| QQQ | orb  | range 30, target 1R, shorts |  0.86 | +$111 |
| IWM | orb  | range 30, target 1R, long only |  0.79 | +$133 |
| SPY | vwap | band 0.4%, stop 2x, warmup 30 | -0.07 | -$7 |
| QQQ | vwap | band 0.4%, stop 1x, warmup 60 | -0.66 | -$80 |
| IWM | vwap | band 0.4%, stop 2x, warmup 60 | -0.85 | -$132 |

No validation t reached 1 either. Costs took 55% to over 100% of the gross.
Grids: orb `range_minutes=15,30,60 target_r=1,2,3 allow_short=false,true`;
vwap `band=0.002,0.004,0.008 stop_mult=0.5,1,2 warmup_minutes=30,60`.

## What counts as an edge

`t >= 3` on the daily P&L of held-out days, **net of costs**. Not per trade:
trades on the same day share that day's market and are not independent.
t = 2 is not enough when many parameter combinations have been tried.

Two tests guard the machinery itself:

- **Null test.** On a driftless random walk, no strategy (breakout, reversion,
  random, buy-at-open) may show an edge, even with zero costs. If it starts
  failing, the backtester is leaking the future. Find out why before trusting
  anything else.
- **Known effect.** With momentum planted in synthetic data, the breakout
  strategy must find it, and the opposite hypothesis (VWAP reversion) must
  lose. This shows the pipeline can detect something real.

Synthetic results say nothing about any market. Every effect in them was put
there by a parameter.

## How the backtester avoids lying

- A strategy sees a bar only after it has closed, and its order fills at the
  **next bar's open**, never at the close it just saw.
- When a stop and a target both fall inside one bar, the **stop is assumed**
  to have hit first.
- A gap through a stop fills at the gap, not at the stop.
- A resting target only fills if price trades **through** it.
- Every fill pays slippage (default 2 bps a side) and sales pay SEC and FINRA
  fees. The default fee rates are the higher recent published ones: overstated
  costs make a strategy look worse, understated ones manufacture edge.
- Positions are forced flat before the close. It is a day-trading bot.

## Risk limits (same code in backtest and live)

| limit | default |
| --- | --- |
| max position | $2,000 notional |
| risk per trade | $25 to the stop |
| daily loss stop | $100 (account day P&L; gains elsewhere never loosen it) |
| trades per day | 4 |
| pattern-day-trader | 3 day trades per rolling window under $25k equity |
| no new entries | last 30 minutes |
| forced flat | last 5 minutes |
| shorting | off |

The daily loss stop reads the account's own day P&L, so a restart cannot hand
the bot a fresh loss budget. The day-trade count is rebuilt from the journal
on start for the same reason: Alpaca's current API does not report one.

## Live safety

- **Every entry needs a keystroke.** An approval given after the next bar has
  started is discarded, because the plan was priced on a stale bar.
- **Stops live at the broker.** Entries go out as bracket orders, so the stop
  and target keep protecting the position if the bot crashes.
- **The bot owns only what it bought.** Shares the account already held are
  recorded at start and never sold. Positions are closed by quantity, never
  with "close all".
- **The bot halts when it can't be sure.** If a close fails five times, or the
  broker's position disagrees with the bot's for three bars in a row, it stops
  and asks for a human. It doesn't guess.
- **Parsers are strict.** A missing or renamed field raises instead of
  reading as zero. On the Kalshi bot, a renamed position field made every
  position read as flat, which silently disabled the exposure limits.

## Not verified yet

The Alpaca parsers were written against Alpaca's published OpenAPI spec
(fetched 2026-09-29) and tested on its documented examples. **None of that is
a real response.** The first thing to do with paper keys is:

```bash
daybot check
daybot record          # saves scrubbed real responses to tests/fixtures/
```

Then add tests over the recorded file. On the Kalshi bot, recorded payloads
were the only thing that caught field renames.

Also unverified: how Alpaca handles bracket legs on a *partly* filled entry.
Until that is checked on paper, the bot cancels a partial entry and closes
whatever did fill.

## Layout

```
daybot/
  models.py      bars, signals, positions, trades, tick rounding
  sessions.py    US market hours in America/New_York
  costs.py       slippage, commission, SEC/FINRA fees
  risk.py        the risk gate, shared by backtest and live
  backtest.py    bar-by-bar backtester
  stats.py       day-clustered t-stats, time-ordered splits, sweeps
  synthetic.py   random-walk and momentum data for testing the machinery
  strategy/      orb (breakout), vwap (reversion), buy_open and random baselines
  data.py        CSV in and out
  broker.py      broker interface and order types
  alpaca.py      Alpaca REST client
  trader.py      the live decision loop, journal and approval
  live.py        drives the trader from Alpaca's clock
  cli.py         the daybot command
```
