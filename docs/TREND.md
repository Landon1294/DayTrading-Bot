# Trend-following rebalancer: pre-registration

Status: **pre-registered 2026-09-29, before any of it was run or any return
data was looked at.** The rule, benchmarks, stages and gates below are fixed
by this commit. Results go in section 6 afterwards; nothing above it changes.

Why this direction: see [DIRECTION.md](DIRECTION.md). In short, 21 intraday
tests found no edge, and trend-following has the longest evidence base of
anything reviewed, with turnover low enough that costs stop mattering.

What this can and cannot show: the decision to use a trend rule rests on
published evidence (a century of it). Alpaca's data starts in 2016, too short
to confirm an edge: a strategy with a Sharpe ratio of 0.5 has an expected t
of about 1.6 over ten years. So stage 1 checks the signal on 100 years of
external data; stage 2 checks that *this* implementation behaves as the
literature says and has no bugs; stage 3 checks real fills on paper. None of
them is allowed to change the rule.

## 1. Sources

- Moskowitz, Ooi & Pedersen, [*Time Series Momentum*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463)
  (JFE 2012): the sign of an asset's past 12-month excess return predicts its
  next month, across 58 futures markets; ex-ante volatility from an
  exponentially weighted average with a 60-day centre of mass.
- Hurst, Ooi & Pedersen, [*A Century of Evidence on Trend-Following
  Investing*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026):
  positive in every decade since 1880; strong in most major crises.
- Clare, Seaton, Smith & Thomas, [*The Trend is Our Friend: Risk Parity,
  Momentum and Trend Following in Global Asset
  Allocation*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2126478)
  (J. Behav. Exp. Finance 2016): inverse-volatility weights across asset
  classes with a trend filter improve risk-adjusted returns and drawdowns
  over buy-and-hold and over risk parity alone.
- Faber, [*A Quantitative Approach to Tactical Asset
  Allocation*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461):
  the long-or-cash version for asset-class funds; reduced drawdowns, and
  lagged buy-and-hold in several years after publication.

## 2. The rule (`trend_ra`)

- **Universe:** six asset-class ETFs, with T-bills as cash:

  | sleeve | ETF |
  |---|---|
  | US equities | SPY |
  | developed ex-US equities | EFA |
  | emerging equities | EEM |
  | 7-10 year Treasuries | IEF |
  | gold | GLD |
  | broad commodities | DBC |
  | cash | BIL (1-3 month T-bills) |

- **Data:** Alpaca SIP daily bars, `adjustment=all` (splits and dividends,
  so returns are total returns).
- **Signal**, on the last trading day of each month, from closes up to and
  including that day: sleeve *i* is **on** if its total return over the last
  12 months (month-end to month-end) exceeds BIL's over the same 12 months;
  otherwise **off**. (Moskowitz et al.'s excess-return sign; long or cash
  instead of long or short, because the account is a cash account.)
- **Volatility:** Moskowitz et al.'s ex-ante estimate: exponentially weighted
  variance of daily returns with delta / (1 - delta) = 60 (delta = 60/61),
  annualised by 261.
- **Weights:** base weight = (1 / vol_i) / sum over all six of (1 / vol_j),
  so the six sum to 1. Target weight = base weight if on, 0 if off. Whatever
  is off goes to BIL. No leverage, no shorts.
- **Trading:** at the open of the first trading day of the next month, trade
  every sleeve to its target. No bands, no partial rebalancing.
- **Costs:** the `CostModel` defaults on every fill: 2 bps slippage plus SEC
  and FINRA fees on sales.

Deviations from the sources, all fixed now: ETFs instead of futures; long or
cash instead of long or short; inverse-volatility weights normalised to sum
to 1 instead of a 40% volatility target per instrument; six sleeves rather
than 58 markets. Each is a simplification forced by the account or the
instruments, and none was chosen by looking at results.

Fixed, never varied: the 12-month lookback, the 60-day volatility centre of
mass, the universe, the monthly schedule, no bands.

## 3. Benchmarks

- **B1, same sleeves without the filter:** the same inverse-volatility
  weights, always invested, rebalanced monthly. Isolates what the trend
  filter adds.
- **B2, SPY buy and hold:** the realistic alternative.
- **B3, 60/40:** 60% SPY, 40% IEF, rebalanced monthly.

## 4. Stages and gates

### Stage 1: the signal on 100 years of US equity data

Kenneth French's monthly market and T-bill returns, July 1926 to August
2026 ([data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)).
Market total return = Mkt-RF + RF.

- **Rule:** hold the market in month m+1 if its compounded return over months
  m-11..m exceeds the compounded T-bill return over the same months;
  otherwise hold T-bills. 10 bps of cost each time it switches.
- **Compared with:** buying and holding the market.
- **Reported:** annualised return, volatility, Sharpe (excess of T-bills),
  maximum drawdown, number of switches; for the full sample and for each
  half (1926-07 to 1976-06, 1976-07 to 2026-08).
- **Gate S1 (signal validated):** in the full sample *and* in both halves,
  the rule's Sharpe is at least buy-and-hold's *and* its maximum drawdown is
  smaller. If it fails, stop: the signal does not do on this data what the
  literature says, and the rest is not built.

### Stage 2: this implementation on Alpaca data

Alpaca daily bars 2016-01-04 to 2026-09-28. The first signal needs 12
months, so the rule trades from January 2017 (about 116 months).

Gates, all required before paper trading:

- **G1, no lookahead:** unit tests that the month-end signal reads no bar
  after that day's close and trades at the next open.
- **G2, null test:** on synthetic driftless random walks for the six sleeves
  (3 seeds, 50 years each), the rule's monthly returns minus B1's show no
  edge (t < 3). A pass means the machinery is not leaking the future.
- **G3, costs:** average annual cost of rebalancing under 0.25% of equity at
  the default costs.
- **G4, the literature's main claim:** the rule's maximum drawdown is smaller
  than B1's over 2017-2026.

Reported, not gated (there is too little data to decide on them): annualised
return, volatility, Sharpe and maximum drawdown for the rule and all three
benchmarks; the t of monthly returns of the rule minus B1 and minus B2; the
share of months each sleeve was on.

If G4 fails, the rule does not go to paper, and it is not rescued by changing
a parameter.

### Stage 3: paper trading

A `daybot rebalance` command on the existing client:

- One plan per month-end: target weights, current holdings, and the orders to
  get from one to the other, shown for a single human approval. A plan
  approved after the next open has passed is discarded.
- Orders by quantity, sells before buys, for this bot's holdings only.
- Halts on any disagreement between broker positions and the bot's record.

Run on the paper account for at least three month-ends. Report each fill
against the next-open price the backtest assumed. Gate P1: the average
shortfall per fill is within the 2 bps assumed; if not, the cost model is
raised to what was measured and stage 2 is re-reported with it (the rule
still does not change).

Real money is the user's decision after stage 3, and not below about $2,000:
under that, Alpaca's per-day fee rounding (one cent each for SEC and FINRA
on any day with a sale) costs more than the rule is expected to earn.

## 5. What would change the plan

- S1 fails: stop; report; nothing further is built on this signal.
- G1 or G2 fails: a bug; fix it and re-run, with the fix recorded here.
- G4 fails: stop before paper; report.
- P1 fails: raise the costs, re-report stage 2, continue only if G3 still
  passes.

## 6. Results

Not yet run.
