"""Structural validation of OHLCV data before it is used in a backtest.

This module catches data problems that would otherwise silently corrupt a
backtest: missing/duplicate/non-monotonic timestamps, impossible OHLC
relationships, negative prices/volume, and time gaps. It does not fix
anything — it reports problems so the caller can decide what to do (raise,
warn, or explicitly accept a documented gap).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Nominal bar duration per supported timeframe, used to detect gaps.
TIMEFRAME_TO_TIMEDELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


@dataclass
class OhlcvValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gap_count: int = 0
    gap_examples: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise ValueError(
                "OHLCV validation failed with the following errors:\n"
                + "\n".join(f"  - {e}" for e in self.errors)
            )


def validate_ohlcv(
    df: pd.DataFrame,
    timeframe: str | None = None,
    allow_gaps: bool = False,
    max_gap_examples: int = 5,
) -> OhlcvValidationResult:
    """Validate structural integrity of an OHLCV dataframe.

    Checks performed (all reported as errors, not exceptions — call
    `raise_if_invalid()` to turn them into one):
      - required columns present
      - no missing (NaN) values in required columns
      - timestamps strictly increasing (also catches duplicates)
      - open/high/low/close > 0
      - volume >= 0
      - high is the max and low is the min of (open, high, low, close)

    Time gaps (bars missing relative to `timeframe`'s nominal duration) are
    detected separately and are NOT treated as errors by default, since some
    markets/datasets legitimately have gaps (e.g. exchange downtime,
    illiquid pairs). Pass `allow_gaps=False` to instead treat any detected
    gap as a validation error — this is the recommended setting for a
    market expected to trade continuously, such as BTC/USDT spot.
    """
    result = OhlcvValidationResult()

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        result.errors.append(f"missing required columns: {missing_cols}")
        return result  # nothing else can be safely checked

    if len(df) == 0:
        result.errors.append("dataframe is empty")
        return result

    nan_counts = df[REQUIRED_COLUMNS].isna().sum()
    for col, count in nan_counts.items():
        if count > 0:
            result.errors.append(f"column '{col}' has {count} NaN value(s)")

    if df["timestamp"].isna().any():
        # Already reported above via nan_counts, but timestamp NaNs break
        # every check below, so bail out early.
        return result

    ts = df["timestamp"]
    non_increasing = (ts.diff().dropna() <= pd.Timedelta(0)).sum()
    if non_increasing > 0:
        duplicated = ts.duplicated().sum()
        result.errors.append(
            f"timestamps are not strictly increasing: {non_increasing} "
            f"non-increasing step(s) found ({duplicated} exact duplicate(s))"
        )

    for col in ["open", "high", "low", "close"]:
        n_non_positive = (df[col] <= 0).sum()
        if n_non_positive > 0:
            result.errors.append(f"column '{col}' has {n_non_positive} value(s) <= 0")

    n_negative_volume = (df["volume"] < 0).sum()
    if n_negative_volume > 0:
        result.errors.append(f"column 'volume' has {n_negative_volume} negative value(s)")

    high_ok = (
        (df["high"] >= df["open"]) & (df["high"] >= df["close"]) & (df["high"] >= df["low"])
    )
    n_bad_high = (~high_ok).sum()
    if n_bad_high > 0:
        result.errors.append(
            f"{n_bad_high} row(s) have 'high' lower than open/close/low (impossible bar)"
        )

    low_ok = (df["low"] <= df["open"]) & (df["low"] <= df["close"])
    n_bad_low = (~low_ok).sum()
    if n_bad_low > 0:
        result.errors.append(
            f"{n_bad_low} row(s) have 'low' higher than open/close (impossible bar)"
        )

    # Gap detection: only meaningful once timestamps are strictly increasing.
    if timeframe is not None and non_increasing == 0 and len(df) > 1:
        expected_step = TIMEFRAME_TO_TIMEDELTA.get(timeframe)
        if expected_step is None:
            result.warnings.append(
                f"unknown timeframe '{timeframe}': skipping time-gap detection"
            )
        else:
            deltas = ts.diff().dropna()
            gap_mask = deltas > expected_step
            result.gap_count = int(gap_mask.sum())
            if result.gap_count > 0:
                gap_positions = deltas.index[gap_mask]
                for pos in list(gap_positions)[:max_gap_examples]:
                    prev_ts = ts.loc[pos - 1]
                    curr_ts = ts.loc[pos]
                    result.gap_examples.append(
                        f"gap between {prev_ts} and {curr_ts} "
                        f"(expected step {expected_step}, actual {curr_ts - prev_ts})"
                    )
                message = (
                    f"{result.gap_count} time gap(s) detected relative to "
                    f"expected {timeframe} step (e.g. {result.gap_examples[0]})"
                )
                if allow_gaps:
                    result.warnings.append(message)
                else:
                    result.errors.append(message)

    return result
