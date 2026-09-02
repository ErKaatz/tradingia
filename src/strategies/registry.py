"""Maps config `strategy` names to Strategy classes."""

from __future__ import annotations

from typing import Any

from src.strategies.base import Strategy
from src.strategies.buy_and_hold import BuyAndHold
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import Momentum
from src.strategies.sma_cross import SmaCross

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "buy_and_hold": BuyAndHold,
    "sma_cross": SmaCross,
    "momentum": Momentum,
    "mean_reversion": MeanReversion,
}


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {sorted(STRATEGY_REGISTRY)}"
        )
    params = params or {}
    return STRATEGY_REGISTRY[name](**params)
