"""Simple momentum strategy.

Long when price has risen over the last `lookback` bars (close today above
close `lookback` bars ago), flat otherwise. A minimal, easily audited
momentum rule used to validate the engine — not tuned for performance.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.base import FLAT, LONG, Strategy


class Momentum(Strategy):
    name = "momentum"

    def __init__(self, lookback: int = 24):
        if lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {lookback}")
        super().__init__(lookback=lookback)
        self.lookback = lookback

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        past_close = df["close"].shift(self.lookback)
        signal = pd.Series(FLAT, index=df.index, dtype=int)
        valid = past_close.notna()
        signal[valid & (df["close"] > past_close)] = LONG
        return signal
