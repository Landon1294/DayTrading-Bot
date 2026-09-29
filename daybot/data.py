"""Loading bars from CSV, so any data source works without a broker account.

Expected columns (header row required, extra columns ignored):

    timestamp,symbol,open,high,low,close,volume[,vwap]

``timestamp`` must be ISO 8601 *with* a zone (``2024-03-01T14:30:00Z`` or
``2024-03-01T09:30:00-05:00``). Naive timestamps are rejected rather than
guessed at: a wrong zone shifts every session by hours and silently puts
pre-market bars inside the regular session.
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path

from daybot.models import Bar
from daybot.sessions import group_sessions

REQUIRED = ("timestamp", "open", "high", "low", "close", "volume")


def parse_timestamp(text: str) -> datetime:
    ts = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError(f"timestamp {text!r} has no zone; add Z or an offset")
    return ts


def load_csv(path: str | Path, *, symbol: str | None = None, label: str = "left",
             bar_minutes: int = 5) -> list[Bar]:
    """Read bars. ``label='right'`` is for vendors that stamp a bar with its
    *end* time; those are shifted back one bar so ``Bar.start`` is honest."""
    if label not in ("left", "right"):
        raise ValueError("label must be 'left' or 'right'")
    shift = timedelta(minutes=bar_minutes) if label == "right" else timedelta(0)
    bars: list[Bar] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")
        for n, row in enumerate(reader, start=2):
            sym = (row.get("symbol") or symbol or "UNKNOWN").strip()
            if symbol is not None and sym != symbol:
                continue
            try:
                o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
                bar = Bar(sym, parse_timestamp(row["timestamp"]) - shift, o, h, lo, c,
                          float(row["volume"]),
                          vwap=float(row["vwap"]) if row.get("vwap") else None)
            except (ValueError, KeyError) as exc:
                raise ValueError(f"{path}:{n}: {exc}") from None
            if not (lo <= min(o, c) and h >= max(o, c)):
                raise ValueError(f"{path}:{n}: high/low do not contain open/close")
            bars.append(bar)
    symbols = {b.symbol for b in bars}
    if len(symbols) > 1:
        raise ValueError(f"{path} holds {sorted(symbols)}; pick one with symbol=")
    return bars


def load_sessions(path: str | Path, *, symbol: str | None = None, label: str = "left",
                  bar_minutes: int = 5) -> "OrderedDict[date, list[Bar]]":
    return group_sessions(load_csv(path, symbol=symbol, label=label, bar_minutes=bar_minutes),
                          bar_minutes)


def write_bars(path: str | Path, bars: list[Bar]) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume", "vwap"])
        for b in bars:
            w.writerow([b.start.isoformat(), b.symbol, f"{b.open:.4f}", f"{b.high:.4f}",
                        f"{b.low:.4f}", f"{b.close:.4f}", f"{b.volume:.0f}",
                        "" if b.vwap is None else f"{b.vwap:.4f}"])
    return len(bars)


def write_csv(path: str | Path, sessions: "OrderedDict[date, list[Bar]]") -> int:
    return write_bars(path, [b for bars in sessions.values() for b in bars])
