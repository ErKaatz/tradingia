"""Chronological train/validation/test splitting.

Splits must NEVER be random: shuffling time series data leaks future
information into training (a model or rule "tuned" on shuffled data has
implicitly seen the future). All splits here are contiguous slices ordered
by time.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame


def chronological_split(
    df: pd.DataFrame,
    train_frac: float = 0.6,
    validation_frac: float = 0.2,
    test_frac: float = 0.2,
) -> DataSplit:
    """Split an OHLCV dataframe (assumed sorted ascending by timestamp) into
    three contiguous, non-overlapping chronological blocks.

    train_frac + validation_frac + test_frac must sum to 1.0 (within a small
    tolerance). The split is purely positional/time-based — no shuffling.
    """
    total_frac = train_frac + validation_frac + test_frac
    if abs(total_frac - 1.0) > 1e-6:
        raise ValueError(
            f"train/validation/test fractions must sum to 1.0, got {total_frac}"
        )
    for name, frac in [
        ("train_frac", train_frac),
        ("validation_frac", validation_frac),
        ("test_frac", test_frac),
    ]:
        if frac < 0:
            raise ValueError(f"{name} must be non-negative, got {frac}")

    n = len(df)
    if n == 0:
        raise ValueError("Cannot split an empty dataframe")

    train_end = int(n * train_frac)
    validation_end = train_end + int(n * validation_frac)

    train = df.iloc[:train_end].reset_index(drop=True)
    validation = df.iloc[train_end:validation_end].reset_index(drop=True)
    test = df.iloc[validation_end:].reset_index(drop=True)

    return DataSplit(train=train, validation=validation, test=test)
