# Where to go from here

Written 2026-09-29, after the research in [RESEARCH.md](RESEARCH.md). This
is a recommendation, not a result: the evidence behind each line is linked
or was measured as described.

## The short version

**Stop looking for a day-trading edge in index ETFs.** Twenty-one tests of
seven published or popular tactics on SPY, QQQ and IWM found nothing, and the
code reproduces the published effects in the years the papers covered, so the
cause is decay, not bugs. The costs this repo assumes are ten times the real
spread, and even at a quarter of them nothing passes.

**The one intraday idea left fails a cost check before it is even built.**
"Stocks in play" (single stocks with unusual opening volume) is the only
intraday tactic with a documented recent edge. Its paper assumes no slippage.
Measured here, the bid-ask spread at 09:35 on the paper's own top-20 stocks
is 0.3-0.9 of its risk unit, against a claimed edge of 0.08-0.38.

**Recommended:** turn the bot into a low-turnover, rules-based portfolio
(trend-following across asset-class ETFs, rebalanced weekly or monthly),
where the evidence is a century long and costs stop mattering; keep the
intraday code as a research rig. What to do depends on the goal:

| if the goal is | then |
|---|---|
| growing money | a low-cost index fund beat every strategy tested here, after costs. Do not run this bot with real money. |
| a trading system worth running | **the recommendation:** pivot to low-turnover trend-following, validated on published long histories (below). |
| settling the day-trading question | one decisive, pre-registered replication of stocks in play on 2024-2026 data the paper never saw, with quote-based costs. Expect it to fail. |

## The options, scored

| direction | evidence | edge after retail costs | fits this bot | verdict |
|---|---|---|---|---|
| More intraday rules on index ETFs | strong in old samples, decayed since about 2021 | none found in 21 tests | yes | **stop** |
| Stocks in play, 5-minute ORB | one working paper (2016-2023), no slippage, no out-of-sample period | spreads measured at 0.3-0.9R vs a claimed 0.08-0.38R | needs a new multi-stock backtester, 1-minute data, delisted list | **one decisive test at most** |
| Overnight drift (buy close, sell open) | strong 1993-2015 ([Boyarchenko et al.](https://ideas.repec.org/a/oup/rfinst/v36y2023i9p3502-3547..html)) | weakened since publication ([Elm Wealth](https://elmwealth.com/night-moves-overnight-drift/)); Alpaca's auction orders need its Elite tier | holds overnight | **no** |
| Pre-FOMC drift | [Lucca & Moench 2015](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf) | [disappeared after 2015](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3134546) | yes | **no** |
| Post-earnings drift | classic anomaly | [gone for large stocks since 2006](https://www.nowpublishers.com/article/Details/CFR-0122) | no | **no** |
| Turn of the month | [Etula et al., RFS 2020](https://academic.oup.com/rfs/article/33/1/75/5494694) | small; few trades a month so costs are low | yes, cheaply | cheap pre-registered test, low expectations |
| Trend-following across asset classes | [a century of evidence](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026); [Moskowitz, Ooi & Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463) | costs negligible at monthly turnover; modest returns, long flat spells (2023-2025 was hard) | reuses the client and safety code | **recommended** |
| Tactical allocation (10-month average, dual momentum) | [Faber](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461), Antonacci | lagged since publication | yes | only as part of the trend test |
| Selling options premium | variance risk premium is documented | tail risk the bot cannot manage | no | **no** |

## What changed in the rules

- **The pattern-day-trader rule is gone.** FINRA retired it on 2026-06-04
  ([Regulatory Notice 26-10](https://www.finra.org/rules-guidance/notices/26-10));
  Alpaca removed it that day ([Alpaca](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/)),
  which is why the account payload has no day-trade count. The bot's gate
  now defaults to off (`pdt_equity_threshold = 0`). Intraday margin replaces
  it: a deficit not met by the fifth business day freezes the account for 90
  days, and the bot already sizes within buying power.
- Small accounts can now day trade freely. That removes a barrier, not a
  cost: it does not create an edge.

## Why the intraday search should stop

- **Tests:** 6 sweeps of ORB and VWAP reversion, then 15 pre-registered tests
  of five published tactics. Best held-out t: -0.24 at default costs, 0.88 at
  0.5 bps.
- **Gross, not just net:** intraday momentum makes about nothing before
  costs; VWAP trend loses before costs; the best (noise-area momentum) makes
  about 3 bps a trade against a 4 bps round trip.
- **Decay is visible year by year:** noise-area momentum's Sharpe goes
  +2.5, +1.6, +2.0 (2021-2023), then +0.3, -0.9 (2025-2026), matching an
  independent replication.
- **The literature agrees:** fewer than 1% of day traders are predictably
  profitable ([Barber et al.](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf));
  97% of persistent Brazilian day traders lost money
  ([Chague et al.](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)).

## Stocks in play: the cost check

Zarattini, Barbon & Aziz ([SSRN 4729284](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)):
every day, among stocks over $5 with 14-day average volume over 1M shares
and ATR over $0.50, take the 20 with the highest opening 5-minute volume
relative to their 14-day average; enter on a stop at the opening range's
high or low in its direction; stop loss 10% of ATR (= 1R); flat at the close.
Reported 2016-2023: Sharpe 2.81, net of $0.0035/share commission and **no
slippage**. Average trade: 0.08R for all stocks above 100% relative volume,
0.38R above 30x.

Rebuilt here for three recent days from Alpaca SIP data, with the NBBO spread
measured from 09:35 to 09:36 on the top 20:

| day | eligible | top-20 relative volume | median spread | 75th pct | easy to borrow |
|---|---|---|---|---|---|
| 2024-03-05 | 1,093 | 6x-38x | 0.33R (21 bps) | 0.86R | 19/20 |
| 2025-06-10 | 1,207 | 4x-38x | 0.93R (45 bps) | 2.16R | 18/20 |
| 2026-09-22 | 1,608 | 4x-32x | 0.34R (15 bps) | 0.87R | 16/20 |

A stop entry becomes a market order when triggered, and so does the stop
loss: about one full spread per round trip, before any slippage beyond the
quote. That is roughly the size of the claimed edge. Two more warnings:

- In the paper, the 5-minute version has Sharpe 2.81 and the 30- and
  60-minute versions 0.21 and 0.40. The edge sits in the first five minutes,
  when spreads are widest: the pattern a no-slippage assumption produces.
- Alpaca serves bars for delisted stocks (SIVB, FRC, TWTR, BBBY checked) but
  does not list them, so a survivorship-free universe needs an outside
  delisted list. Renamed stocks return the same history under both symbols
  (FB and META), so they must be de-duplicated.

Worth doing only as a decisive, zero-tuning replication on 2024-01 to
2026-09 (after the paper's sample), with fills from quotes. It needs a
multi-stock backtester, 1-minute bars for about 20 stocks a day, and a batch
approval for a morning's resting stop orders.

## The recommended path: low-turnover trend-following

Why: the longest evidence base of anything reviewed (positive in every
decade since 1880 in [Hurst, Ooi & Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026)),
a mechanism that does not depend on beating faster traders, and turnover so
low that the spread is irrelevant. What to expect: modest returns, long flat
periods, and its value mostly as diversification and in crises
([Man Group](https://www.man.com/insights/is-this-time-different)), not as a
way to beat the stock market.

The honesty rules still apply, with one change forced by the data:

- **Alpaca's data starts 2016-01-04.** A Sharpe-0.5 strategy has an expected
  t of about 1.6 over 10.7 years; t >= 3 would take about 36 years. So the
  *rule* must be validated on published long histories (for example
  [AQR's time-series momentum data](https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data)),
  and Alpaca data used to check the *implementation*: that the code
  reproduces the published rule's returns on the overlapping years.
- **No tuning.** Take the published rule as is (for example, 12-month
  time-series momentum, volatility-scaled, across 6-10 asset-class ETFs,
  rebalanced monthly), pre-register it, and do not adjust it after seeing
  results.

Steps:

1. Pre-register the rule and universe in a new doc before any code runs.
2. Download the published long-history returns; confirm the rule's Sharpe
   and drawdowns there.
3. Build a rebalancer on the existing client: target weights, orders by
   quantity, one human approval per rebalance, halts on any mismatch. Most
   of the live-safety code carries over; the 5-minute loop does not.
4. Check the implementation against the published returns on 2016-2026.
5. Paper trade for 3-6 months of rebalances and compare fills with the
   assumed costs.

## Either way

- The dry run of the intraday live loop is still scheduled for 09:20 ET on
  2026-09-30. It tests the safety code that any direction reuses.
- The test split (2025-03 to 2026-09) has produced 39 held-out results and
  is no longer clean for intraday ETF ideas. Data after 2026-09-28 is.
