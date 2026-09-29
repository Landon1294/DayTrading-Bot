"""Run the sweeps pre-registered in docs/RESEARCH.md, exactly as registered.

    .venv/bin/python research/preregistered.py            # needs data/{SPY,QQQ,IWM}_5m.csv
    .venv/bin/python research/preregistered.py --out research/results.json

Nothing here is tuned: the grids, split, sizing, costs and verdict are the
registered ones, and each (hypothesis, symbol, cost) runs once.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daybot.config import RiskSettings  # noqa: E402
from daybot.costs import CostModel  # noqa: E402
from daybot.data import load_sessions  # noqa: E402
from daybot.stats import sweep  # noqa: E402
from daybot.strategy import STRATEGIES  # noqa: E402

SYMBOLS = ("SPY", "QQQ", "IWM")
GRIDS = {
    "intraday_mom": {"window": ["first30", "rest"], "threshold": [0.0, 0.002]},
    "noise_mom": {"vm": [1.0, 1.5, 2.0], "stop": ["band", "band_vwap"]},
    "orb5": {"target_r": [2, 5, 10]},
    "vwap_trend": {"every": [5, 15, 30]},
    "gap_fade": {"gap": [0.0025, 0.005, 0.01]},
}
COSTS_BPS = (2.0, 0.5)  # the default (verdict), and about the 99th-pct measured half-spread
# A fixed $100,000 per trade; no risk sizing, loss limit, trade limit, PDT rule or
# equity floor (min_equity would otherwise stop a losing run partway through).
RISK = RiskSettings(max_position_notional=100_000, risk_per_trade=1e12, max_daily_loss=1e12,
                    max_trades_per_day=1_000, pdt_equity_threshold=0, allow_short=True,
                    min_equity=-1e18)

_sessions = {}


def _load(symbol: str, data_dir: str):
    if symbol not in _sessions:
        _sessions[symbol] = load_sessions(f"{data_dir}/{symbol}_5m.csv")
    return _sessions[symbol]


def run_one(job):
    name, symbol, bps, data_dir = job
    res = sweep(_load(symbol, data_dir), STRATEGIES[name], GRIDS[name],
                costs=CostModel(slippage_bps=bps), risk=RISK, starting_equity=100_000,
                apply_pdt=False)
    return {"hypothesis": name, "symbol": symbol, "slippage_bps": bps, "params": res.params,
            "tried": res.tried, "validation": asdict(res.validation), "test": asdict(res.test),
            "test_refusals": res.test_refusals, "edge": res.test.has_edge}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="research/results.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    jobs = [(n, s, c, args.data) for c in COSTS_BPS for n in GRIDS for s in SYMBOLS]
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(run_one, jobs))
    Path(args.out).write_text(json.dumps(results, indent=1, default=str) + "\n")
    for bps in COSTS_BPS:
        print(f"\nslippage {bps} bps per fill")
        print(f"{'hypothesis':13} {'sym':4} {'val t':>6} {'test t':>7} {'test net':>11} "
              f"{'trades':>6}  chosen")
        for r in (r for r in results if r["slippage_bps"] == bps):
            v, t = r["validation"], r["test"]
            print(f"{r['hypothesis']:13} {r['symbol']:4} {v['t_stat']:6.2f} {t['t_stat']:7.2f} "
                  f"{t['net']:11,.0f} {t['trades']:6d}  {r['params']}"
                  + ("   <-- EDGE" if r["edge"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
