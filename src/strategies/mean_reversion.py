"""Simple RSI-based mean reversion strategy.

Long when RSI falls below `oversold` (price presumed overextended to the
downside), exits back to flat when RSI rises back above `exit_rsi`. RSI is
computed with a standard trailing Wilder-style smoothing using only past
and current closes.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.base import FLAT, LONG, Strategy


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    # Where avg_loss is 0 and avg_gain > 0, RS is undefined/inf -> RSI = 100.
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    # Where both are 0 (flat price), RSI is conventionally 50 (neutral).
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return rsi


class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(self, rsi_period: int = 14, oversold: float = 30.0, exit_rsi: float = 50.0):
        if not (0 < oversold < exit_rsi < 100):
            raise ValueError(
                f"require 0 < oversold < exit_rsi < 100, got oversold={oversold}, exit_rsi={exit_rsi}"
            )
        super().__init__(rsi_period=rsi_period, oversold=oversold, exit_rsi=exit_rsi)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.exit_rsi = exit_rsi

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = _rsi(df["close"], self.rsi_period)

        signal = pd.Series(FLAT, index=df.index, dtype=int)
        position = FLAT
        for i in range(len(df)):
            r = rsi.iloc[i]
            if pd.isna(r):
                signal.iloc[i] = FLAT
                continue
            if position == FLAT and r < self.oversold:
                position = LONG
            elif position == LONG and r > self.exit_rsi:
                position = FLAT
            signal.iloc[i] = position
        return signal
