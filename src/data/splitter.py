"""Chronological train/validation/test splitting.

Splits must NEVER be random: shuffling time series data leaks future
information into training (a model or rule "tuned" on shuffled data has
implicitly seen the future). All splits here are contiguous slices ordered
by time.

## Warm-up context across splits

`chronological_split` only computes the *boundaries* (as positional indices
into the full dataframe) — it does not, by itself, decide how much history
before a split's start a strategy is allowed to see. That is handled by
`slice_with_warmup`, which returns a split's target rows PLUS up to
`warmup_bars` rows immediately preceding them, still drawn from the same
full dataframe (so validation can borrow trailing history from train, and
test can borrow trailing history from train+validation) — but never from
rows that lie chronologically after the target's end. See
`src/strategies/base.py` for how a strategy declares how much warm-up it
needs, and `src/experiments/runner.py` for how the extended slice is used
to compute signals and then trimmed back to the target period only.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SplitBounds:
    """Positional (0-indexed, end-exclusive) boundaries of a split within
    the full chronological dataframe it was computed from.
    """

    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class DataSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_bounds: SplitBounds
    validation_bounds: SplitBounds
    test_bounds: SplitBounds


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

    train_bounds = SplitBounds(0, train_end)
    validation_bounds = SplitBounds(train_end, validation_end)
    test_bounds = SplitBounds(validation_end, n)

    train = df.iloc[train_bounds.start : train_bounds.end].reset_index(drop=True)
    validation = df.iloc[validation_bounds.start : validation_bounds.end].reset_index(drop=True)
    test = df.iloc[test_bounds.start : test_bounds.end].reset_index(drop=True)

    return DataSplit(
        train=train,
        validation=validation,
        test=test,
        train_bounds=train_bounds,
        validation_bounds=validation_bounds,
        test_bounds=test_bounds,
    )


def slice_with_warmup(
    full_df: pd.DataFrame, bounds: SplitBounds, warmup_bars: int
) -> tuple[pd.DataFrame, int]:
    """Return (extended_df, target_start_offset) for a split.

    `extended_df` contains up to `warmup_bars` rows immediately preceding
    `bounds.start` (clipped at 0 if not enough history exists — e.g. for
    `train`, which has no prior split to borrow from) followed by the
    split's own target rows (`bounds.start` to `bounds.end`). It never
    includes any row at or after `bounds.end`, so no future information
    (relative to the split) can leak in.

    `target_start_offset` is the positional index within `extended_df`
    where the split's own target rows begin (i.e. `extended_df.iloc[
    target_start_offset:]` is exactly the original split, and
    `extended_df.iloc[:target_start_offset]` is warm-up-only context that
    must not be counted in that split's trades/metrics).
    """
    if warmup_bars < 0:
        raise ValueError(f"warmup_bars must be >= 0, got {warmup_bars}")

    warmup_start = max(0, bounds.start - warmup_bars)
    extended_df = full_df.iloc[warmup_start : bounds.end].reset_index(drop=True)
    target_start_offset = bounds.start - warmup_start
    return extended_df, target_start_offset
