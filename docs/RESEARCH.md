# Intraday strategy research

Status: **pre-registered 2026-09-29, before any of the strategies below was
run.** The hypotheses, rules, grids, settings and verdict rule in sections 2
and 3 are fixed here and committed first, so the results cannot shape them.
Section 4 is filled in afterwards.

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

Not yet run.
