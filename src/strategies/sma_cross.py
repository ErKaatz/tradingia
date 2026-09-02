"""Simple Moving Average crossover strategy.

Long when the fast SMA is above the slow SMA, flat otherwise. Both SMAs at
row i are computed using only `close` prices up to and including row i
(pandas `.rolling()` is trailing by construction, so this is safe), and the
resulting signal is not shifted here — the engine is responsible for
applying it starting at the next bar.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.base import FLAT, LONG, Strategy


class SmaCross(Strategy):
    name = "sma_cross"

    def __init__(self, fast: int = 20, slow: int = 100):
        if fast >= slow:
            raise ValueError(f"fast period ({fast}) must be < slow period ({slow})")
        super().__init__(fast=fast, slow=slow)
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_sma = df["close"].rolling(window=self.fast, min_periods=self.fast).mean()
        slow_sma = df["close"].rolling(window=self.slow, min_periods=self.slow).mean()

        signal = pd.Series(FLAT, index=df.index, dtype=int)
        valid = fast_sma.notna() & slow_sma.notna()
        signal[valid & (fast_sma > slow_sma)] = LONG
        return signal
