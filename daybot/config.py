"""Settings. Human-facing limits are in dollars and minutes."""

from __future__ import annotations

from dataclasses import dataclass, field

from daybot.costs import CostModel


@dataclass(frozen=True)
class RiskSettings:
    # Largest single position, in dollars of notional.
    max_position_notional: float = 2_000.0
    # Dollars lost if the stop is hit. Sizes a position whose signal has a stop.
    risk_per_trade: float = 25.0
    # Realised + unrealised loss for the day at which the bot stops opening
    # positions. Enforced as a gate on every check, not just a trip, so a
    # restarted process cannot start the day with a fresh budget.
    max_daily_loss: float = 100.0
    max_trades_per_day: int = 4
    # The old FINRA pattern-day-trader rule: under the equity threshold a
    # margin account could make at most 3 day trades in 5 business days.
    # FINRA retired it on 2026-06-04 (Regulatory Notice 26-10) and Alpaca
    # removed it that day, so the check is off (threshold 0). Firms have until
    # 2027-10-20 to implement the change: for a broker that still enforces it,
    # set the threshold to 25_000 -- do not just raise the count.
    max_day_trades_per_5d: int = 3
    pdt_equity_threshold: float = 0.0
    # No new positions this close to the bell: a fill in the last minutes
    # leaves no time for the trade to work before the forced flatten.
    no_entry_minutes_before_close: int = 30
    flatten_minutes_before_close: int = 5
    allow_short: bool = False
    # Stop trading entirely below this account equity.
    min_equity: float = 500.0


@dataclass(frozen=True)
class Settings:
    symbols: tuple[str, ...] = ("SPY",)
    bar_minutes: int = 5
    strategy: str = "orb"
    strategy_params: dict = field(default_factory=dict)
    risk: RiskSettings = field(default_factory=RiskSettings)
    costs: CostModel = field(default_factory=CostModel)
    starting_equity: float = 10_000.0
    journal_path: str = "data/journal.jsonl"
