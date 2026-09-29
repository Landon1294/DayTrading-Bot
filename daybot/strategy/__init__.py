from daybot.strategy.base import Strategy
from daybot.strategy.baselines import BuyOpen, RandomEntry
from daybot.strategy.intraday import (GapFade, IntradayMomentum, NoiseAreaMomentum,
                                      OpeningRange5, VwapTrend)
from daybot.strategy.orb import OpeningRangeBreakout
from daybot.strategy.vwap_reversion import VwapReversion

STRATEGIES: dict[str, type[Strategy]] = {
    "orb": OpeningRangeBreakout,
    "vwap": VwapReversion,
    "buy_open": BuyOpen,
    "random": RandomEntry,
    # Pre-registered in docs/RESEARCH.md.
    "intraday_mom": IntradayMomentum,
    "noise_mom": NoiseAreaMomentum,
    "orb5": OpeningRange5,
    "vwap_trend": VwapTrend,
    "gap_fade": GapFade,
}


def make_strategy(name: str, **params) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}") from None
    return cls(**params)


__all__ = ["Strategy", "STRATEGIES", "make_strategy", "OpeningRangeBreakout", "VwapReversion",
           "BuyOpen", "RandomEntry", "IntradayMomentum", "NoiseAreaMomentum", "OpeningRange5",
           "VwapTrend", "GapFade"]
