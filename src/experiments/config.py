"""Experiment configuration schema and loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExperimentConfig:
    strategy: str
    symbol: str
    timeframe: str
    capital_initial: float
    trading_fee: float
    slippage: float
    strategy_params: dict[str, Any]
    data_split: dict[str, float]
    position_size_fraction: float = 1.0
    start: str | None = None
    end: str | None = None
    allow_data_gaps: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_yaml(path: str | Path) -> "ExperimentConfig":
        with open(path) as f:
            raw = yaml.safe_load(f)
        return ExperimentConfig.from_dict(raw)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ExperimentConfig":
        capital = raw.get("capital", {})
        fees = raw.get("fees", {})
        data_split = raw.get(
            "data_split", {"train": 0.6, "validation": 0.2, "test": 0.2}
        )
        return ExperimentConfig(
            strategy=raw["strategy"],
            symbol=raw["symbol"],
            timeframe=raw["timeframe"],
            capital_initial=float(capital.get("initial", 10_000.0)),
            trading_fee=float(fees.get("trading_fee", 0.001)),
            slippage=float(fees.get("slippage", 0.0002)),
            strategy_params=raw.get("strategy_params", {}) or {},
            data_split=data_split,
            position_size_fraction=float(raw.get("position_size_fraction", 1.0)),
            start=raw.get("start"),
            end=raw.get("end"),
            allow_data_gaps=bool(raw.get("allow_data_gaps", False)),
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "capital": {"initial": self.capital_initial},
            "fees": {"trading_fee": self.trading_fee, "slippage": self.slippage},
            "strategy_params": self.strategy_params,
            "data_split": self.data_split,
            "position_size_fraction": self.position_size_fraction,
            "start": self.start,
            "end": self.end,
            "allow_data_gaps": self.allow_data_gaps,
        }
