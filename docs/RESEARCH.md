# Intraday strategy research

Status: **pre-registered 2026-09-29 (commit 96c6a4f), before any of the
strategies below was run; results added the same day.** Sections 2 and 3 are
unchanged since that commit. Section 4 is the result.

**Verdict: none of the 15 pre-registered tests shows an edge.** The best
held-out t at the default costs is -0.24; at the optimistic 0.5 bps it is
0.88. Run `research/preregistered.py` to reproduce.

## 1. What the literature says

### Who makes money day trading

- Barber, Lee, Liu & Odean, [*Do Individual Day Traders Make Money? Evidence
  from Taiwan*](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf)
  and [*The Cross-Section of Speculator Skill*](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf):
  on the Taiwan exchange 1992-2006, fewer than 1% of day traders earned
  predictably positive returns net of fees; more than eight in ten lost money.
- Chague, De-Losso & Giovannetti, [*Day Trading for a Living?*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)
  (Brazil, futures): 97% of those who persisted more than 300 days lost money;
  1.1% earned more than the minimum wage.
- Park & Irwin, [*What Do We Know About the Profitability of Technical
  Analysis?*](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-6419.2007.00519.x)
  (J. Econ. Surveys 2007): rules looked profitable in many markets until the
  early 1990s, but most studies suffer from data snooping, ex post rule
  selection, and understated costs.
- Sullivan, Timmermann & White, [*Data-Snooping, Technical Trading Rule
  Performance, and the Bootstrap*](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00163)
  (J. Finance 1999): once the whole universe of rules searched is accounted
  for, the best rule's apparent edge largely disappears, and it did not hold
  out of sample.

The prior, then, is that a simple rule on a liquid ETF has no edge after
costs. The tactics below are the ones with the best evidence of being
exceptions.

### Tactics with published evidence on liquid index ETFs

**Market intraday momentum.** Gao, Han, Li & Zhou, [*Market Intraday
Momentum*](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351)
(J. Financial Economics 2018): on SPY 1993-2013, the return from the previous
close to 10:00 predicts the return over the last half hour; stronger on
volatile, high-volume and news days; also in ten other ETFs. Baltussen, Da,
Lammers & Martens, [*Hedging Demand and Market Intraday
Momentum*](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21001598)
(JFE 2021): across 60+ futures 1974-2020, the return up to 30 minutes before
the close predicts the last 30 minutes; the mechanism is gamma hedging by
option market makers and leveraged-ETF rebalancing, which must trade in the
direction of the day's move near the close.

**Noise-area intraday momentum.** Zarattini, Aziz & Barbon, [*Beat the
Market: An Effective Intraday Momentum Strategy for
SPY*](https://dx.doi.org/10.2139/ssrn.4824172) (SFI working paper 2024).
Bands around the open from the average absolute move from the open at each
time of day over the last 14 days, widened for overnight gaps; trade breakouts
at HH:00 and HH:30 only; trailing stop at max(band, VWAP). Reported 2007-2024:
Sharpe 1.24 at constant size (1.33 volatility-targeted), costs $0.0035/share
commission plus $0.001/share slippage. An [independent
replication](https://github.com/codecat-ops/zarattini-2024-momentum-spy)
found Sharpe about 1.1 in 2020-2024 and **about 0 in 2025-2026**, on both SPY
and ES.

**5-minute opening range breakout.** Zarattini & Aziz, [*Can Day Trading
Really Be Profitable?*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622)
(2023): on QQQ 2016-2023, trade in the direction of the first 5-minute candle
from 09:35, stop at that candle's far extreme, target 10R, flat at the close.
Reported Sharpe about 1.1 with 4x leverage, but assumed $0.0005/share
commission and **no slippage**, with no separate validation period
([summary](https://danfin.net/opening-range-breakout-research)). Their
follow-up on single stocks found the edge came from "stocks in play" with
abnormal opening volume, not from the breakout itself.

**VWAP trend.** Zarattini & Aziz, [*VWAP: The Holy Grail for Day Trading
Systems*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4631351) (2023):
long above VWAP, short below, on 1-minute QQQ bars 2018-2023; reported Sharpe
2.1 net of commission. Trades many times a day, so it is the most sensitive
to costs of the set.

**Overnight versus intraday.** Lou, Polk & Skouras, [*A Tug of
War*](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) (JFE 2019):
overnight and intraday returns tend to reverse each other, strongly in the
cross-section of stocks at monthly horizons. Evidence for fading a single
index ETF's opening gap within the day is weak; it is tested here as a common
retail tactic ("gap fill") with a weak prior.

### Why a recent test period matters

Several sources say these effects have weakened since about 2021, which
overlaps the test period here (about March 2025 to September 2026):

- Dim, Eraker & Vilkov, [*0DTEs: Trading, Gamma Risk and Volatility
  Propagation*](https://papers.ssrn.com/sol3/Delivery.cfm/4692190.pdf?abstractid=4692190)
  (2023): option market makers' net gamma is on average *positive*, which
  strengthens intraday reversal rather than momentum.
- The independent replication of the noise-area strategy above: edge about
  zero in 2025-2026.
- Two lower-quality sources (a [blog
  post](https://dev.to/firmtape/intraday-momentum-is-dead-in-the-0dte-era-we-measured-it-on-1085-spx-sessions-43g0)
  and an [unreviewed preprint](https://arxiv.org/abs/2605.04004)) report no
  last-half-hour momentum on SPX 2022-2026 and no OHLCV momentum signal
  surviving walk-forward tests on Nasdaq futures 2021-2025.

Reviewed but not tested: Heston, Korajczyk & Sadka, [*Intraday Patterns in
the Cross-Section of Stock Returns*](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2010.01573.x)
(J. Finance 2010), is a cross-sectional effect across many stocks, not a
timing rule for one ETF.

### Costs, measured

Half-spreads from Alpaca SIP quotes, sampled at six times of day on ten days
between April 2025 and September 2026 (about 11,500 quotes per symbol):

| | median | 90th pct | 99th pct |
|---|---|---|---|
| SPY | 0.13 bps | 0.22 bps | 0.70 bps |
| QQQ | 0.14 bps | 0.40 bps | 0.71 bps |
| IWM | 0.20 bps | 0.56 bps | 0.98 bps |

The SEC fee is $20.60 per million from 2026-04-04 ([SEC fee rate
advisory](https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2));
`CostModel` uses $27.80, which overstates it.

## 2. Hypotheses and rules

All strategies see closed 5-minute bars only and fill at the next bar's open.
A signal "at HH:MM" is computed from the bar that closes at HH:MM, and fills
at the open of the bar that starts at HH:MM. All positions are flat by 15:55
(the live flatten rule).

| id | name | source | rule | grid |
|---|---|---|---|---|
| H1 | `intraday_mom` | Gao et al. 2018; Baltussen et al. 2021 | At 15:30, take the sign of the return from the previous close to the end of the signal window; if its size is at least `threshold`, enter in that direction; exit at the 15:55 flatten. `window`: `first30` = previous close to 10:00 (Gao), `rest` = previous close to 15:30 (Baltussen). | `window=first30,rest` × `threshold=0,0.002` (4) |
| H2 | `noise_mom` | Zarattini, Aziz & Barbon 2024 | Bands from the 14-day average absolute move from the open at each time of day, times `vm`, around max/min(open, previous close). At HH:00 and HH:30 only: above the upper band go long, below the lower go short; exit (and reverse if across the other band) when the price is back past the trailing stop: `band` = the current band; `band_vwap` = max(band, VWAP) for longs, min for shorts. | `vm=1,1.5,2` × `stop=band,band_vwap` (6) |
| H3 | `orb5` | Zarattini & Aziz 2023 | At 09:35, trade in the direction of the first 5-minute candle (none if open = close); stop at that candle's opposite extreme; target `target_r` times the risk; flat at 15:55. | `target_r=2,5,10` (3) |
| H4 | `vwap_trend` | Zarattini & Aziz 2023 (VWAP) | Every `every` minutes from 09:35: long if the close is above the session VWAP, short if below; reverse on a cross. | `every=5,15,30` (3) |
| H5 | `gap_fade` | common retail tactic; weak prior from Lou, Polk & Skouras | If the open gaps from the previous close by at least `gap`, at 09:35 enter against the gap; target the previous close; stop one gap-size beyond the entry; flat at 15:55. | `gap=0.0025,0.005,0.01` (3) |

Parameters outside these grids are fixed at the sources' values (14-day
lookback in H2; H1's 15:30 entry). No other variant will be run and reported
as a result.

## 3. Test protocol

- **Data:** SIP 5-minute bars, SPY, QQQ, IWM, 2019-01-02 to 2026-09-28
  (1,945 days each), cut to the exchange calendar.
- **Split:** by whole days in time order, 60/20/20. The first 60% is unused.
  Validation is about Aug 2023 to Feb 2025; test is about Mar 2025 to Sep 2026
  (389 days). Strategies needing history start each split without it; their
  first 14 days of each split are warm-up (no trades).
- **Selection:** the combination with the highest validation t is the only
  one run on test.
- **Sizing:** a fixed $100,000 notional per trade, whole shares; no
  risk-based sizing, no daily loss limit, no trade-count limit, no PDT rule.
  Shorts allowed. This measures the strategy, not the account's risk limits.
- **Costs:** the `CostModel` defaults (2 bps slippage per fill plus fees) for
  the verdict. Also reported at 0.5 bps slippage, about the 99th-percentile
  measured half-spread.
- **Verdict:** an edge is t >= 3 on test-period daily P&L at default costs.
  With 15 tests (5 hypotheses x 3 symbols), the chance of a false pass is
  about 2%. A result that passes only at 0.5 bps is reported as
  cost-dependent: paper fills would settle it.
- **Null test first:** each strategy must show no edge on a driftless random
  walk at zero costs before it is run on real data.

## 4. Results

Reproduce with `.venv/bin/python research/preregistered.py` (about 10 s on 4
cores; full numbers in `research/results.json`).

### At the default costs (the verdict)

Test days are 2025-03 to 2026-09 (389 days); each trade is $100,000.

| hypothesis | sym | chosen on validation | val t | test t | test gross | test costs | test net | trades |
|---|---|---|---|---|---|---|---|---|
| intraday_mom | SPY | window=first30, threshold=0.002 | -3.03 | -3.27 | -$271 | $10,709 | -$10,980 | 251 |
| intraday_mom | QQQ | window=first30, threshold=0.002 | -3.24 | -2.88 | +$712 | $13,021 | -$12,309 | 305 |
| intraday_mom | IWM | window=first30, threshold=0.002 | -3.33 | -3.29 | +$841 | $13,270 | -$12,429 | 310 |
| noise_mom | SPY | vm=2.0, stop=band | -0.49 | -0.24 | +$3,283 | $4,523 | -$1,240 | 106 |
| noise_mom | QQQ | vm=2.0, stop=band | 0.52 | -0.47 | +$1,807 | $5,039 | -$3,232 | 118 |
| noise_mom | IWM | vm=2.0, stop=band_vwap | 0.23 | -1.51 | -$4,191 | $5,222 | -$9,413 | 122 |
| orb5 | SPY | target_r=10 | -2.65 | -2.07 | +$1,879 | $16,358 | -$14,479 | 387 |
| orb5 | QQQ | target_r=10 | -0.06 | -1.62 | -$265 | $16,342 | -$16,607 | 388 |
| orb5 | IWM | target_r=10 | -2.88 | -1.01 | +$3,626 | $16,380 | -$12,754 | 386 |
| vwap_trend | SPY | every=30 | -2.97 | -3.81 | -$12,025 | $47,796 | -$59,821 | 1,120 |
| vwap_trend | QQQ | every=30 | -1.63 | -2.75 | -$6,022 | $46,530 | -$52,552 | 1,090 |
| vwap_trend | IWM | every=30 | -2.62 | -3.32 | -$22,406 | $46,700 | -$69,106 | 1,091 |
| gap_fade | SPY | gap=0.0025 | -0.73 | -0.44 | +$1,721 | $4,430 | -$2,709 | 121 |
| gap_fade | QQQ | gap=0.005 | -0.13 | -0.40 | +$389 | $3,607 | -$3,219 | 97 |
| gap_fade | IWM | gap=0.0025 | 1.16 | -0.93 | -$2,227 | $5,278 | -$7,505 | 147 |

### At 0.5 bps slippage (sensitivity)

Selection re-run at this cost level, so the chosen parameters can differ.

| hypothesis | sym | chosen on validation | val t | test t | test net |
|---|---|---|---|---|---|
| intraday_mom | SPY | window=first30, threshold=0 | -0.51 | -1.17 | -$4,186 |
| intraday_mom | QQQ | window=first30, threshold=0.002 | -1.09 | -0.75 | -$3,186 |
| intraday_mom | IWM | window=first30, threshold=0.002 | -0.82 | -0.83 | -$3,140 |
| noise_mom | SPY | vm=1.5, stop=band_vwap | 0.71 | -0.34 | -$2,129 |
| noise_mom | QQQ | vm=1.0, stop=band_vwap | 1.50 | **0.88** | +$10,728 |
| noise_mom | IWM | vm=2.0, stop=band_vwap | 0.85 | -0.93 | -$5,757 |
| orb5 | SPY | target_r=10 | -0.81 | -0.43 | -$3,025 |
| orb5 | QQQ | target_r=10 | 1.07 | -0.51 | -$5,168 |
| orb5 | IWM | target_r=10 | -1.91 | -0.10 | -$1,295 |
| vwap_trend | SPY | every=30 | 0.27 | -1.73 | -$26,331 |
| vwap_trend | QQQ | every=30 | 0.56 | -1.07 | -$19,950 |
| vwap_trend | IWM | every=30 | -0.63 | -1.80 | -$36,416 |
| gap_fade | SPY | gap=0.0025 | -0.12 | 0.06 | +$358 |
| gap_fade | QQQ | gap=0.005 | 0.23 | -0.09 | -$717 |
| gap_fade | IWM | gap=0.0025 | 1.63 | -0.48 | -$3,861 |

Nothing passes even here. The one positive t (noise_mom on QQQ, 0.88) is
what one would expect as the best of 15 draws of noise.

### Where the losses come from

- **intraday_mom:** gross P&L is about zero on all three (-$271 to +$841 over
  250-310 trades of $100,000). The strongly negative t is the costs alone:
  there is no last-half-hour momentum left to pay them.
- **vwap_trend:** loses *before* costs on all three, and trades about three
  times a day.
- **orb5:** gross is small and mixed; trading every day at about 4 bps round
  trip cost about $16,000 per $100,000 over the 19-month test.
- **noise_mom:** gross about +3 bps per trade on SPY (+$31 per $100,000),
  close to the independent replication's +2.6 bps, but less than the round
  trip cost at 2 bps.
- **gap_fade:** small gross either way; no sign of a gap-fill tendency.

### Descriptive check: do the implementations reproduce the papers?

Not a test and not used for any decision: each strategy at its paper's
settings and approximate costs, annualised Sharpe of daily P&L by calendar
year, over all data (`research/by_year.py`). Where the samples overlap the
papers', the effects appear; in the test period they are gone.

| strategy (settings, costs) | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| noise_mom (vm 1, band+VWAP, SPY, 0.11 bps = paper) | -0.06 | -0.06 | +2.50 | +1.61 | +1.95 | +0.88 | +0.30 | -0.89 |
| intraday_mom (Baltussen "rest", SPY, gross) | -0.29 | +1.62 | +1.05 | +1.11 | -1.08 | -2.12 | -0.29 | -0.49 |
| intraday_mom (Gao "first30", SPY, gross) | +0.16 | +0.80 | -1.75 | -0.44 | +0.95 | +0.15 | +0.15 | +1.15 |
| orb5 (10R, QQQ, gross) | +0.86 | +0.02 | +1.21 | +1.18 | -0.28 | +1.12 | +0.35 | -0.51 |
| vwap_trend (every 5, QQQ, gross) | +0.09 | -0.24 | +1.37 | +1.10 | -0.67 | +0.36 | +0.82 | -0.23 |
| gap_fade (0.5%, SPY, gross) | -1.57 | -1.19 | -2.23 | +0.05 | -0.50 | -0.12 | +0.86 | +0.11 |

The noise-area row matches both the paper (strong through 2023) and the
independent replication (about zero in 2025-2026). The Baltussen row turns
negative from 2023, consistent with the 0DTE-era evidence in section 1. These
are single-year Sharpes of about 250 days each: a Sharpe of 1 in one year is
a t of about 1.

### Deviations from the sources

- 5-minute bars throughout; the VWAP paper used 1-minute bars, the noise-area
  paper 1-minute data checked every 30 minutes.
- A reversal is flat for one bar (exit, then entry at the next open).
- Positions are flat by 15:55, as the live bot must be; the papers exit at
  16:00. intraday_mom therefore holds 25 of the last 30 minutes.
- Constant $100,000 notional; the noise-area paper's best result also
  targeted volatility and used up to 4x leverage. Leverage scales P&L and
  costs alike and does not change t.

### A bug found while running

`RiskSettings.min_equity` ($500) is an account floor, not part of the
registered protocol, and it stopped one validation combination (vwap_trend,
every=5, QQQ and IWM at 2 bps) partway through after it had lost its
$100,000. That combination was never the chosen one, so no verdict changed;
the runner now sets the floor off, and the table above is from the corrected
run. The by-year script had the same problem at its $10,000 default and
showed zeros from 2021; it is fixed too.

A separate, earlier bug affected the first ORB sweep in the README: `sweep`
and `backtest` used the live gate's default of no shorts, so `allow_short=true`
entries were silently refused. Fixed in 28cd441; the README table is
corrected.

### What this means

Every tactic here had published evidence, and on this data the code
reproduces most of that evidence in the years the papers covered. None of
it survives in the last 19 months at costs this repo is willing to assume,
and most of it does not survive at a quarter of those costs either. That is
consistent with the literature on day-trader outcomes and on technical rules
decaying once published.

Nothing here goes to paper trading. Directions that would need new data or
infrastructure rather than new parameters, each with its own
pre-registration:

- **Stocks in play:** Zarattini, Barbon & Aziz found the ORB edge came from
  single stocks with abnormal opening volume, not ETFs. That needs a stock
  universe, relative volume, and much larger spreads in the cost model.
- **Gamma-conditioned momentum:** the one surviving signal reported for the
  0DTE era conditions on dealer gamma, which needs options positioning data.
- **Cheaper instruments:** futures (ES, NQ) cost less per unit of risk than
  ETFs, but Alpaca does not offer them.
