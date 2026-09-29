"""Descriptive, not a test: each strategy at its source paper's settings and
cost assumptions, over every year of the data, to check the implementation
reproduces the published effect where the papers' samples overlap ours.
Nothing here feeds the verdict in docs/RESEARCH.md.

    .venv/bin/python research/by_year.py
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daybot.backtest import run_backtest  # noqa: E402
from daybot.costs import CostModel  # noqa: E402
from daybot.data import load_sessions  # noqa: E402
from daybot.strategy import make_strategy  # noqa: E402

from preregistered import RISK  # noqa: E402

# (strategy, params, symbol, slippage bps approximating the paper's costs)
RUNS = [
    ("noise_mom", {"vm": 1.0, "stop": "band_vwap"}, "SPY", 0.11),  # $0.0045/sh on ~$400
    ("intraday_mom", {"window": "first30"}, "SPY", 0.0),          # Gao et al.: gross
    ("intraday_mom", {"window": "rest"}, "SPY", 0.0),             # Baltussen et al.: gross
    ("orb5", {"target_r": 10}, "QQQ", 0.0),                       # $0.0005/sh, no slippage
    ("vwap_trend", {"every": 5}, "QQQ", 0.0),                     # commission only
    ("gap_fade", {"gap": 0.005}, "SPY", 0.0),
]


def main() -> int:
    cache = {}
    for name, params, sym, bps in RUNS:
        if sym not in cache:
            cache[sym] = load_sessions(f"data/{sym}_5m.csv")
        r = run_backtest(cache[sym], make_strategy(name, **params),
                         costs=CostModel(slippage_bps=bps), risk=RISK, apply_pdt=False)
        years = defaultdict(list)
        for d, pnl in r.daily_pnl.items():
            years[d.year].append(pnl / 100_000)
        cells = []
        for y, xs in sorted(years.items()):
            m = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            cells.append(f"{y}:{m / sd * math.sqrt(252) if sd else 0:+5.2f}")
        print(f"{name:12} {str(params):38} {sym} {bps:4}bps  Sharpe by year  " + "  ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
