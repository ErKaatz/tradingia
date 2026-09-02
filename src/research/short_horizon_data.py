"""POST-HOC SHORT-HORIZON RESEARCH — dataset registration for Phase 4A.

Loads and validates the BTCUSDT datasets this phase is scoped to (15m and
1h only -- see Task 2: no 1m/3m/5m/30m/2h/4h/1d in this phase, to keep the
experimental space contained) and records the bookkeeping Task 2 asks for:
time range, gap count, duplicate count, content hash, and candle count.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.loader import dataset_hash, load_ohlcv
from src.data.validation import validate_ohlcv

SYMBOL = "BTCUSDT"
TIMEFRAMES = ("15m", "1h")  # Task 2: exactly these two, deliberately contained


@dataclass(frozen=True)
class DatasetRegistration:
    symbol: str
    timeframe: str
    num_candles: int
    start: str
    end: str
    dataset_hash: str
    duplicate_timestamps: int
    gap_count: int
    gap_examples: list[str]
    is_valid: bool
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "num_candles": self.num_candles,
            "start": self.start,
            "end": self.end,
            "dataset_hash": self.dataset_hash,
            "duplicate_timestamps": self.duplicate_timestamps,
            "gap_count": self.gap_count,
            "gap_examples": self.gap_examples,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
        }


def load_and_register(
    timeframe: str, symbol: str = SYMBOL, raw_dir: Path = Path("data/raw"), allow_gaps: bool = True
) -> tuple[pd.DataFrame, DatasetRegistration]:
    """Load a cached OHLCV dataset, run it through the project's standard
    OHLCV validation, and return both the dataframe and a registration
    record with the bookkeeping Task 2 requires. Raises if the timeframe
    is outside this phase's declared scope (Task 2's containment rule) or
    if the dataset fails validation with allow_gaps=False.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"Phase 4A is scoped to exactly {TIMEFRAMES}; '{timeframe}' is out of "
            "scope for this phase (Task 2 explicitly contains the experimental space)."
        )

    df = load_ohlcv(symbol, timeframe, raw_dir=raw_dir)
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    validation = validate_ohlcv(df, timeframe=timeframe, allow_gaps=allow_gaps)
    if not allow_gaps:
        validation.raise_if_invalid()

    registration = DatasetRegistration(
        symbol=symbol,
        timeframe=timeframe,
        num_candles=len(df),
        start=str(df["timestamp"].min()),
        end=str(df["timestamp"].max()),
        dataset_hash=dataset_hash(df),
        duplicate_timestamps=int(df["timestamp"].duplicated().sum()),
        gap_count=validation.gap_count,
        gap_examples=validation.gap_examples,
        is_valid=validation.is_valid,
        validation_errors=validation.errors,
    )
    return df, registration


def register_all_timeframes(
    symbol: str = SYMBOL, raw_dir: Path = Path("data/raw"), allow_gaps: bool = True
) -> dict[str, DatasetRegistration]:
    return {tf: load_and_register(tf, symbol=symbol, raw_dir=raw_dir, allow_gaps=allow_gaps)[1] for tf in TIMEFRAMES}
