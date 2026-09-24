"""Simple RSI-based mean reversion strategy.

Long when RSI falls below `oversold` (price presumed overextended to the
downside), exits back to flat when RSI rises back above `exit_rsi`. RSI is
computed with a standard trailing Wilder-style smoothing using only past
and current closes.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy
from src.strategies.state_machine import run_entry_exit_state_machine


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

    @property
    def warmup_bars(self) -> int:
        # `_rsi` requires `rsi_period` bars before avg_gain/avg_loss even
        # produce a first value (min_periods=rsi_period on the ewm mean).
        # Beyond that, Wilder's EWM smoothing (alpha=1/period) has a long
        # tail: it never fully "forgets" the arbitrary seed, but by
        # convention ~4x the period is enough for the seed's influence to
        # become negligible for signal purposes. This is a documented
        # approximation, not an exact convergence bound.
        return self.rsi_period * 4

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = _rsi(df["close"], self.rsi_period)

        def should_enter(i: int) -> bool:
            r = rsi.iloc[i]
            return pd.notna(r) and r < self.oversold

        def should_exit(i: int) -> bool:
            r = rsi.iloc[i]
            return pd.notna(r) and r > self.exit_rsi

        signal = run_entry_exit_state_machine(len(df), should_enter, should_exit)
        signal.index = df.index
        return signal
