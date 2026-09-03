"""Preregistered second-generation breakout hypotheses for forward-only testing.

These strategies were defined after diagnosing the consumed 2025-2026 holdout.
They MUST NOT be backtest-optimized on that consumed period. Validation belongs
only to data at/after the configured forward_start.
"""
from __future__ import annotations
import math
import pandas as pd
from src.strategies.base import FLAT, LONG, Strategy


class BreakoutConfirmed24h(Strategy):
    """168h Donchian breakout with a fixed 24h delayed confirmation.

    A setup is armed when close breaks the prior 168h high. Exactly 24 bars
    later, it enters only if close is still above that original breakout level.
    Failed setups are not immediately re-armed until price closes back at/below
    the current prior-high boundary. Exit remains the prior 60h low.
    """
    name = "breakout_confirmed_24h"

    def __init__(self, entry_lookback: int = 168, exit_lookback: int = 60, confirmation_bars: int = 24):
        if (entry_lookback, exit_lookback, confirmation_bars) != (168, 60, 24):
            raise ValueError("forward hypothesis is frozen at 168/60 with 24h confirmation")
        super().__init__(entry_lookback=168, exit_lookback=60, confirmation_bars=24)
        self.entry_lookback = 168
        self.exit_lookback = 60
        self.confirmation_bars = 24

    @property
    def warmup_bars(self) -> int:
        return self.entry_lookback + self.confirmation_bars

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        prior_high = df["high"].shift(1).rolling(168, min_periods=168).max()
        prior_low = df["low"].shift(1).rolling(60, min_periods=60).min()
        signal = pd.Series(FLAT, index=df.index, dtype=int)
        state = FLAT
        pending_level = None
        pending_due = None
        blocked_until_reset = False

        for i in range(len(df)):
            close = float(df["close"].iloc[i])
            ph = prior_high.iloc[i]
            pl = prior_low.iloc[i]

            if state == LONG:
                if pd.notna(pl) and close < pl:
                    state = FLAT
                    blocked_until_reset = False
                signal.iloc[i] = state
                continue

            if blocked_until_reset:
                if pd.notna(ph) and close <= ph:
                    blocked_until_reset = False
                signal.iloc[i] = FLAT
                continue

            if pending_due is not None:
                if i >= pending_due:
                    if close > float(pending_level):
                        state = LONG
                    else:
                        blocked_until_reset = True
                    pending_level = pending_due = None
                signal.iloc[i] = state
                continue

            if pd.notna(ph) and close > ph:
                pending_level = float(ph)
                pending_due = i + 24

            signal.iloc[i] = FLAT
        return signal


class BreakoutAdaptiveVolGate(Strategy):
    """168/60 breakout gated by an adaptive, non-fitted volatility regime.

    Entry is allowed only when current 168h realized volatility exceeds the
    median of the *previous* 365 days of realized-vol observations. The gate is
    adaptive and contains no threshold fitted to the consumed holdout. Exits are
    never gated.
    """
    name = "breakout_adaptive_vol_gate"

    def __init__(self, entry_lookback: int = 168, exit_lookback: int = 60, vol_lookback: int = 168, median_window: int = 8760):
        if (entry_lookback, exit_lookback, vol_lookback, median_window) != (168, 60, 168, 8760):
            raise ValueError("forward hypothesis parameters are frozen")
        super().__init__(entry_lookback=168, exit_lookback=60, vol_lookback=168, median_window=8760)

    @property
    def warmup_bars(self) -> int:
        return 8760 + 168

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"].astype(float)
        prior_high = df["high"].shift(1).rolling(168, min_periods=168).max()
        prior_low = df["low"].shift(1).rolling(60, min_periods=60).min()
        hourly = close.pct_change()
        rv = hourly.rolling(168, min_periods=168).std(ddof=0) * math.sqrt(24 * 365)
        trailing_median = rv.shift(1).rolling(8760, min_periods=8760).median()

        signal = pd.Series(FLAT, index=df.index, dtype=int)
        state = FLAT
        for i in range(len(df)):
            c = close.iloc[i]
            if state == FLAT:
                gate = pd.notna(rv.iloc[i]) and pd.notna(trailing_median.iloc[i]) and rv.iloc[i] > trailing_median.iloc[i]
                if gate and pd.notna(prior_high.iloc[i]) and c > prior_high.iloc[i]:
                    state = LONG
            elif pd.notna(prior_low.iloc[i]) and c < prior_low.iloc[i]:
                state = FLAT
            signal.iloc[i] = state
        return signal
