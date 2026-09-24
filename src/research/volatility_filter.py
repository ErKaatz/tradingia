from __future__ import annotations
import numpy as np
import pandas as pd
from src.strategies.base import FLAT, LONG
from src.strategies.state_machine import run_sequential_flat_long


def apply_realized_volatility_entry_filter(
    df: pd.DataFrame,
    signals: pd.Series,
    window: int = 24,
    min_vol: float | None = None,
    max_vol: float | None = None,
) -> pd.Series:
    """Suppress only NEW long entries when trailing realized volatility is out of range.

    Existing LONG states are allowed to remain/exit according to the base strategy;
    the filter never forces an exit. Volatility uses close-to-close log returns up to
    the current bar only, so no future information is used.
    """
    if window < 2:
        raise ValueError("volatility window must be >= 2")
    if min_vol is not None and max_vol is not None and min_vol > max_vol:
        raise ValueError("min_vol must be <= max_vol")
    logret = np.log(df["close"] / df["close"].shift(1))
    rv = logret.rolling(window, min_periods=window).std()

    def volatility_allows_entry(i: int) -> bool:
        v = rv.iloc[i]
        allowed = pd.notna(v)
        if allowed and min_vol is not None:
            allowed = v >= min_vol
        if allowed and max_vol is not None:
            allowed = v <= max_vol
        return allowed

    def transition(prev_output: int, i: int) -> int:
        # `prev_output` is the *filtered* state emitted at row i-1, not the
        # underlying strategy's raw state -- a denied entry at i-1 leaves
        # prev_output FLAT, so a still-LONG underlying signal at i is
        # correctly re-evaluated as a fresh entry attempt, not skipped.
        desired = int(signals.iloc[i])
        if prev_output == FLAT and desired == LONG and not volatility_allows_entry(i):
            return FLAT
        return desired

    out = run_sequential_flat_long(len(signals), transition)
    out.index = signals.index
    return out
