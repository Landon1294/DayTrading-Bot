"""Trading costs: slippage, commission, and the US regulatory fees charged
on sales. Commission defaults to zero, as at most US retail brokers; set
``commission_per_share`` for a broker that charges one.

The fee rates change (the SEC resets its Section 31 rate at least yearly),
and neither was verifiable from this repo. The defaults are deliberately the
*higher* recent published values: overstating a cost only makes a strategy
look worse than it is, while understating it manufactures edge.
Check them against the current schedules before trusting a small result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    # Paid on every fill, each side, as a fraction of price. Covers half the
    # spread plus market impact. 2 bps is optimistic for anything but the most
    # liquid ETFs; raise it for single stocks.
    slippage_bps: float = 2.0
    # SEC Section 31: dollars per dollar of *sale proceeds*.
    sec_fee_rate: float = 27.80 / 1_000_000
    # FINRA Trading Activity Fee: per share *sold*, capped per trade.
    finra_taf_per_share: float = 0.000166
    finra_taf_cap: float = 8.30
    commission_per_share: float = 0.0

    def fill_price(self, reference: float, *, buying: bool) -> float:
        """Price actually obtained: worse than the reference in the direction
        of the trade, always."""
        adj = reference * self.slippage_bps / 10_000.0
        return reference + adj if buying else reference - adj

    def fees(self, price: float, qty: int, *, selling: bool) -> float:
        """Fees in dollars, each component rounded up to the cent the way
        brokers pass them through."""
        total = self.commission_per_share * qty
        if selling:
            total += _ceil_cent(price * qty * self.sec_fee_rate)
            total += _ceil_cent(min(self.finra_taf_per_share * qty, self.finra_taf_cap))
        return total


def _ceil_cent(x: float) -> float:
    # The epsilon stops float noise (0.1 + 0.2) from rounding a whole cent up.
    return math.ceil(x * 100 - 1e-9) / 100 if x > 0 else 0.0
