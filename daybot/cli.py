"""Command line.

Research (no account needed):
    daybot synthetic --days 500 --momentum 0.3 --out data/syn.csv
    daybot backtest  --csv data/spy_5min.csv --strategy orb --param range_minutes=15
    daybot sweep     --csv data/spy_5min.csv --strategy orb --grid range_minutes=15,30,60

Alpaca (paper keys in ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY):
    daybot check                        # read-only: account and market clock
    daybot fetch --symbol SPY --start 2024-01-01 --end 2025-12-31 --out data/spy_5min.csv
    daybot record --out tests/fixtures/alpaca_recorded.json
    daybot run --symbol SPY --strategy orb --dry-run   # proposes, never sends
    daybot run --symbol SPY --strategy orb             # paper orders, each one approved by you
"""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict

from daybot.backtest import run_backtest
from daybot.costs import CostModel
from daybot.data import load_sessions, write_csv
from daybot.stats import EDGE_T, Summary, paired_t, summarize, sweep
from daybot.strategy import STRATEGIES, make_strategy
from daybot.synthetic import generate_sessions


def _number(text: str):
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def _kv(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        key, _, value = item.partition("=")
        if not value:
            raise SystemExit(f"expected key=value, got {item!r}")
        out[key] = _number(value)
    return out


def _grid(items: list[str]) -> dict:
    return {k: [_number(v) for v in str(vals).split(",")] for k, vals in
            ((i.partition("=")[0], i.partition("=")[2]) for i in items or [])}


def _sessions(args) -> OrderedDict:
    if args.csv:
        sessions = load_sessions(args.csv, symbol=args.symbol, label=args.label,
                                 bar_minutes=args.bar_minutes)
    else:
        sessions = generate_sessions(args.days, momentum=args.momentum, seed=args.seed,
                                     bar_minutes=args.bar_minutes)
        print(f"(synthetic data, momentum={args.momentum}: results describe the generator, "
              f"not any market)")
    if not sessions:
        raise SystemExit("no regular-session bars found")
    return sessions


def _costs(args) -> CostModel:
    return CostModel(slippage_bps=args.slippage_bps)


def _print_summary(title: str, s: Summary) -> None:
    print(f"\n{title}")
    print(f"  days {s.days}   trades {s.trades}   win rate {s.win_rate:.1%}   "
          f"profit factor {s.profit_factor:.2f}")
    print(f"  gross ${s.gross:,.2f}   costs ${s.costs:,.2f}   net ${s.net:,.2f}"
          + (f"   (costs ate {s.cost_drag:.0%} of gross)" if s.gross > 0 else ""))
    print(f"  daily mean ${s.mean_daily:,.2f} +/- ${s.std_daily:,.2f}   t={s.t_stat:.2f}   "
          f"Sharpe {s.sharpe:.2f}   max drawdown ${s.max_drawdown:,.2f}")


def cmd_backtest(args) -> int:
    sessions = _sessions(args)
    params = _kv(args.param)
    kw = dict(costs=_costs(args), starting_equity=args.equity, apply_pdt=not args.no_pdt)
    result = run_backtest(sessions, make_strategy(args.strategy, **params), **kw)
    s = summarize(result)
    _print_summary(f"{args.strategy} {params or ''}", s)
    if result.refusals:
        print("  refused entries: " + ", ".join(f"{k} x{v}" for k, v in result.refusals.items()))
    base = run_backtest(sessions, make_strategy(args.baseline), **kw)
    _print_summary(f"baseline: {args.baseline}", summarize(base))
    t = paired_t(result.daily_pnl, base.daily_pnl)
    print(f"\n{args.strategy} minus {args.baseline}: paired t={t:.2f}")
    print("\nThis is an in-sample number: the parameters were chosen by you, possibly after "
          "seeing these days. Use `daybot sweep` for a held-out estimate.")
    return 0


def cmd_sweep(args) -> int:
    sessions = _sessions(args)
    grid = _grid(args.grid)
    if not grid:
        raise SystemExit("give at least one --grid key=v1,v2,...")
    cls = STRATEGIES[args.strategy]
    res = sweep(sessions, cls, grid, costs=_costs(args), starting_equity=args.equity,
                apply_pdt=not args.no_pdt)
    print(f"tried {res.tried} combinations, chose {res.params} on validation days")
    _print_summary("validation (used to choose -- optimistic by construction)", res.validation)
    _print_summary("test (never seen -- the only honest estimate)", res.test)
    print(f"\nverdict: {res.verdict}")
    if res.tried > 1 and not res.test.has_edge and res.validation.t_stat >= EDGE_T:
        print("validation cleared the bar and test did not: that is what overfitting a "
              "parameter grid looks like.")
    return 0


def cmd_synthetic(args) -> int:
    sessions = generate_sessions(args.days, momentum=args.momentum, seed=args.seed,
                                 bar_minutes=args.bar_minutes)
    n = write_csv(args.out, sessions)
    print(f"wrote {n} bars over {len(sessions)} days to {args.out}")
    return 0


def _client(args, *, allow_orders: bool = False):
    from daybot.alpaca import AlpacaClient

    return AlpacaClient.from_env(paper=not getattr(args, "live", False), allow_orders=allow_orders)


def cmd_check(args) -> int:
    from daybot.sessions import to_eastern

    c = _client(args)
    acct, clock = c.account(), c.clock()
    print(f"{'PAPER' if c.paper else 'LIVE'} account, status {acct.status}")
    print(f"  equity ${acct.equity:,.2f}   day P&L ${acct.equity - acct.last_equity:,.2f}   "
          f"cash ${acct.cash:,.2f}   buying power ${acct.buying_power:,.2f}")
    if acct.trading_blocked or acct.account_blocked:
        print("  TRADING BLOCKED")
    if acct.equity < 25_000:
        print("  under $25,000: the pattern-day-trader limit (3 day trades / 5 days) applies")
    state = "open" if clock.is_open else "closed"
    print(f"market {state}; next open {to_eastern(clock.next_open):%a %Y-%m-%d %H:%M} ET, "
          f"next close {to_eastern(clock.next_close):%a %H:%M} ET")
    return 0


def cmd_fetch(args) -> int:
    from datetime import date, timedelta

    from daybot.data import write_bars
    from daybot.sessions import to_eastern

    c = _client(args)
    bars = c.bars(args.symbol, args.start, args.end, timeframe=f"{args.bar_minutes}Min",
                  feed=args.feed, adjustment=args.adjustment)
    # Keep regular-session bars only, by the exchange calendar: a fixed
    # 09:30-16:00 window would keep after-hours bars on 13:00 half days.
    cal = c.calendar(args.start, args.end or date.today().isoformat())
    bar_len = timedelta(minutes=args.bar_minutes)
    kept = [b for b in bars if (day := cal.get(to_eastern(b.start).date()))
            and day[0] <= b.start and b.start + bar_len <= day[1]]
    early = sum(1 for o, cl in cal.values() if cl.hour < 16)
    n = write_bars(args.out, kept)
    print(f"wrote {n} {args.symbol} regular-session bars to {args.out} "
          f"({len(bars) - n} outside regular hours dropped; {early} early closes in range)")
    return 0


SCRUB = {"id", "account_number", "asset_id", "client_order_id", "user_id"}


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: ("<scrubbed>" if k in SCRUB and v else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def cmd_record(args) -> int:
    """Save real, scrubbed responses so the parsers can be tested against
    what Alpaca actually sends rather than what its docs say it sends."""
    import json
    from datetime import date, timedelta
    from pathlib import Path

    from daybot.alpaca import DATA_URL

    c = _client(args)
    start = (date.today() - timedelta(days=7)).isoformat()
    out = {
        "_source": f"recorded {date.today()} from the {'paper' if c.paper else 'live'} API, "
                   f"ids scrubbed",
        "account": c._call("GET", c.trading_url, "/v2/account"),
        "clock": c._call("GET", c.trading_url, "/v2/clock"),
        "calendar": c._call("GET", c.trading_url, "/v2/calendar",
                            {"start": "2019-12-20", "end": "2019-12-27"}),  # has a half day
        "positions": c._call("GET", c.trading_url, "/v2/positions"),
        "orders": c._call("GET", c.trading_url, "/v2/orders",
                          {"status": "all", "limit": 20, "nested": "true"}),
        "bars": c._call("GET", DATA_URL, "/v2/stocks/bars",
                        {"symbols": "SPY", "timeframe": "5Min", "start": start, "limit": 5,
                         "feed": "iex", "sort": "asc"}),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(_scrub(out), indent=1))
    print(f"recorded {len(out) - 1} responses to {args.out}")
    return 0


def cmd_run(args) -> int:
    from daybot.config import RiskSettings
    from daybot.live import run
    from daybot.trader import Journal, Trader

    if args.live and not args.enable_live_orders:
        raise SystemExit("--live needs --enable-live-orders as well")
    if args.live and not args.dry_run:
        print("*** LIVE TRADING: orders spend real money ***")
        if input("type LIVE to continue: ").strip() != "LIVE":
            return 1
    params = _kv(args.param)
    client = _client(args, allow_orders=not args.dry_run)
    risk = RiskSettings(max_position_notional=args.max_notional, risk_per_trade=args.risk_per_trade,
                        max_daily_loss=args.max_daily_loss, allow_short=args.allow_short)
    if args.strategy in ("orb",) and args.allow_short:
        params.setdefault("allow_short", True)
    trader = Trader(client, make_strategy(args.strategy, **params), args.symbol, risk=risk,
                    costs=CostModel(slippage_bps=0.0),  # real fills carry their own slippage
                    bar_minutes=args.bar_minutes, journal=Journal(args.journal),
                    dry_run=args.dry_run)
    mode = "DRY RUN (nothing is sent)" if args.dry_run else ("LIVE" if args.live else "PAPER")
    print(f"{mode}: {args.strategy} {params or ''} on {args.symbol}, {args.bar_minutes}-min bars. "
          f"Ctrl-C to stop.")
    run(client, trader, bar_minutes=args.bar_minutes, feed=args.feed, once=args.once)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daybot", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def data_args(sp):
        sp.add_argument("--csv", help="bars CSV (see daybot/data.py); omit for synthetic data")
        sp.add_argument("--symbol", help="symbol to select from a multi-symbol CSV")
        sp.add_argument("--label", choices=["left", "right"], default="left",
                        help="whether CSV timestamps mark the start (left) or end of each bar")
        sp.add_argument("--bar-minutes", type=int, default=5)
        sp.add_argument("--days", type=int, default=250, help="synthetic days")
        sp.add_argument("--momentum", type=float, default=0.0, help="synthetic autocorrelation")
        sp.add_argument("--seed", type=int, default=0)
        sp.add_argument("--strategy", choices=sorted(STRATEGIES), default="orb")
        sp.add_argument("--equity", type=float, default=10_000.0)
        sp.add_argument("--slippage-bps", type=float, default=CostModel().slippage_bps)
        sp.add_argument("--no-pdt", action="store_true",
                        help="ignore the pattern-day-trader limit (research only)")

    b = sub.add_parser("backtest", help="run one strategy against a baseline")
    data_args(b)
    b.add_argument("--param", action="append", help="strategy parameter key=value")
    b.add_argument("--baseline", choices=sorted(STRATEGIES), default="buy_open")
    b.set_defaults(func=cmd_backtest)

    s = sub.add_parser("sweep", help="choose parameters on validation days, report on test days")
    data_args(s)
    s.add_argument("--grid", action="append", help="key=v1,v2,... (repeatable)")
    s.set_defaults(func=cmd_sweep)

    g = sub.add_parser("synthetic", help="write synthetic bars to CSV")
    g.add_argument("--days", type=int, default=250)
    g.add_argument("--momentum", type=float, default=0.0)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--bar-minutes", type=int, default=5)
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_synthetic)

    c = sub.add_parser("check", help="read-only: show the account and the market clock")
    c.add_argument("--live", action="store_true", help="use the LIVE keys (still read-only)")
    c.set_defaults(func=cmd_check)

    f = sub.add_parser("fetch", help="download historical bars from Alpaca to CSV")
    f.add_argument("--symbol", required=True)
    f.add_argument("--start", required=True, help="YYYY-MM-DD")
    f.add_argument("--end", help="YYYY-MM-DD (default: now)")
    f.add_argument("--bar-minutes", type=int, default=5)
    f.add_argument("--feed", default="iex",
                   help="iex, or sip: all exchanges; free except the latest 15 minutes")
    f.add_argument("--adjustment", default="split", help="raw, split, dividend or all")
    f.add_argument("--out", required=True)
    f.set_defaults(func=cmd_fetch)

    r = sub.add_parser("record", help="save real API responses as test fixtures")
    r.add_argument("--out", default="tests/fixtures/alpaca_recorded.json")
    r.set_defaults(func=cmd_record)

    run_p = sub.add_parser("run", help="trade one symbol, asking you to approve every entry")
    run_p.add_argument("--symbol", required=True)
    run_p.add_argument("--strategy", choices=sorted(STRATEGIES), default="orb")
    run_p.add_argument("--param", action="append", help="strategy parameter key=value")
    run_p.add_argument("--bar-minutes", type=int, default=5)
    run_p.add_argument("--feed", default="iex")
    run_p.add_argument("--dry-run", action="store_true", help="propose only; send nothing")
    run_p.add_argument("--once", action="store_true", help="evaluate one bar and exit")
    run_p.add_argument("--max-notional", type=float, default=2_000.0)
    run_p.add_argument("--risk-per-trade", type=float, default=25.0)
    run_p.add_argument("--max-daily-loss", type=float, default=100.0)
    run_p.add_argument("--allow-short", action="store_true")
    run_p.add_argument("--journal", default="data/journal.jsonl")
    run_p.add_argument("--live", action="store_true", help="real money: also needs --enable-live-orders")
    run_p.add_argument("--enable-live-orders", action="store_true")
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
