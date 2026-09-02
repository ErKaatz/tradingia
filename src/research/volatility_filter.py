from __future__ import annotations
import numpy as np
import pandas as pd
from src.strategies.base import FLAT, LONG


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
    out = signals.copy().astype(int)
    prev = FLAT
    for i in range(len(out)):
        desired = int(signals.iloc[i])
        if prev == FLAT and desired == LONG:
            v = rv.iloc[i]
            allowed = pd.notna(v)
            if allowed and min_vol is not None:
                allowed = v >= min_vol
            if allowed and max_vol is not None:
                allowed = v <= max_vol
            if not allowed:
                desired = FLAT
        out.iloc[i] = desired
        prev = desired
    return out
