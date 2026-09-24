"""Donchian-style breakout using only prior completed bars."""
from __future__ import annotations
import pandas as pd
from src.strategies.base import Strategy
from src.strategies.state_machine import run_entry_exit_state_machine

class Breakout(Strategy):
    name = "breakout"
    def __init__(self, entry_lookback: int = 48, exit_lookback: int = 24):
        if entry_lookback < 2 or exit_lookback < 1:
            raise ValueError("entry_lookback >= 2 and exit_lookback >= 1 required")
        super().__init__(entry_lookback=entry_lookback, exit_lookback=exit_lookback)
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback

    @property
    def warmup_bars(self) -> int:
        return max(self.entry_lookback, self.exit_lookback)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # shift(1) is essential: today's close may be compared only with highs/lows
        # of bars that were already complete before today's close.
        prior_high = df["high"].shift(1).rolling(self.entry_lookback, min_periods=self.entry_lookback).max()
        prior_low = df["low"].shift(1).rolling(self.exit_lookback, min_periods=self.exit_lookback).min()
        close = df["close"]

        def should_enter(i: int) -> bool:
            return pd.notna(prior_high.iloc[i]) and close.iloc[i] > prior_high.iloc[i]

        def should_exit(i: int) -> bool:
            return pd.notna(prior_low.iloc[i]) and close.iloc[i] < prior_low.iloc[i]

        signal = run_entry_exit_state_machine(len(df), should_enter, should_exit)
        signal.index = df.index
        return signal
