from __future__ import annotations
from itertools import product
from typing import Any, Callable
from src.strategies.registry import STRATEGY_REGISTRY, build_strategy


def generate_parameter_grid(strategy: str, parameter_study: dict[str, list[Any]], validator: Callable[[dict[str, Any]], bool] | None = None) -> list[dict[str, Any]]:
    if strategy not in STRATEGY_REGISTRY:
        # Fail fast on a bad strategy name. Without this check, every
        # combination below would raise the same ValueError from
        # build_strategy() and get silently swallowed by the per-combination
        # except clause, leaving a typo'd name indistinguishable from a
        # legitimately empty grid.
        raise ValueError(f"Unknown strategy '{strategy}'. Available: {sorted(STRATEGY_REGISTRY)}")
    if not parameter_study:
        return [{}]
    keys = list(parameter_study)
    if any(not isinstance(parameter_study[k], list) or not parameter_study[k] for k in keys):
        raise ValueError("each parameter_study entry must be a non-empty list")
    valid: list[dict[str, Any]] = []
    for vals in product(*(parameter_study[k] for k in keys)):
        params = dict(zip(keys, vals))
        try:
            build_strategy(strategy, params)
        except (TypeError, ValueError):
            continue
        if validator is None or validator(params):
            valid.append(params)
    return valid
