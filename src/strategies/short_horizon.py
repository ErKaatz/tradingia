"""Phase 4A — POST-HOC SHORT-HORIZON RESEARCH strategy families A-F.

Six small, mechanism-driven strategy families, each with a FEW frozen
parameter variants (never a grid expanded after seeing results -- see
`SHORT_HORIZON_GRIDS` in `src/research/short_horizon_study.py`). All are
LONG/FLAT only (Task 23), causal (row i depends only on df.iloc[:i+1]), and
built on `TimeoutExitStrategy` where a timeout exit is part of the
mechanism.

Every threshold here is either a fixed round number decided BEFORE seeing
any Phase 4A result (a z-score cutoff, a volatility multiple) or derived
from a strategy's own trailing statistics (a rolling median/std) -- never a
number chosen because it happened to perform well on this dataset (Task 8
/ Task 14's "no post-hoc numeric thresholds" rule, extended from Phase 3B
to this phase).
"""

from __future__ import annotations

import math

import pandas as pd

from src.research.regime_features import atr, bar_returns, true_range
from src.strategies.base import FLAT, LONG, Strategy
from src.strategies.short_horizon_base import TimeoutExitStrategy

# ---------------------------------------------------------------------------
# Family A: Short Momentum
# ---------------------------------------------------------------------------


class ShortMomentum(TimeoutExitStrategy):
    """Mechanism: a recent directional move may persist for a FEW bars
    before reverting. Enter LONG when trailing return over `lookback` bars
    is positive; exit on a fixed holding timeout (a short-horizon momentum
    trade is, by construction, meant to be brief) or when the trailing
    return turns negative (momentum reversing), whichever comes first.
    """

    name = "short_momentum"

    def __init__(self, lookback: int, max_holding_bars: int):
        if lookback < 1:
            raise ValueError("lookback must be >= 1")
        super().__init__(max_holding_bars=max_holding_bars, lookback=lookback)
        self.lookback = lookback

    @property
    def warmup_bars(self) -> int:
        return self.lookback

    def _trailing_return(self, df: pd.DataFrame) -> pd.Series:
        return df["close"] / df["close"].shift(self.lookback) - 1.0

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        r = self._trailing_return(df)
        return r.notna() & (r > 0)

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        r = self._trailing_return(df)
        return r.notna() & (r <= 0)


# ---------------------------------------------------------------------------
# Family B: Short Mean Reversion (z-score)
# ---------------------------------------------------------------------------


def rolling_zscore(close: pd.Series, window: int) -> pd.Series:
    """z = (close - rolling_mean) / rolling_std, both trailing over
    `window` bars ending at the current bar (min_periods=window, so no
    partial-window value is produced).
    """
    mean = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    return (close - mean) / std


class ShortMeanReversionZScore(TimeoutExitStrategy):
    """Mechanism: price far below its own recent trailing mean (in std-dev
    units) may revert back toward that mean. Enter LONG when the rolling
    z-score drops below `entry_z` (a fixed, pre-decided negative threshold,
    e.g. -1.5 or -2.0 -- NOT chosen by scanning for the best value on this
    data). Exit when z recovers to/above `exit_z` (typically 0, "back to
    the mean") or after `max_holding_bars`, whichever comes first.
    """

    name = "short_mean_reversion_zscore"

    def __init__(self, window: int, entry_z: float, exit_z: float, max_holding_bars: int):
        if entry_z >= exit_z:
            raise ValueError("entry_z must be < exit_z (enter below, exit above)")
        super().__init__(
            max_holding_bars=max_holding_bars, window=window, entry_z=entry_z, exit_z=exit_z
        )
        self.window = window
        self.entry_z = entry_z
        self.exit_z = exit_z

    @property
    def warmup_bars(self) -> int:
        return self.window

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        z = rolling_zscore(df["close"], self.window)
        return z.notna() & (z < self.entry_z)

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        z = rolling_zscore(df["close"], self.window)
        return z.notna() & (z >= self.exit_z)


# ---------------------------------------------------------------------------
# Family C: Short Breakout (fast Donchian, distinct from the slow Phase-2
# Breakout strategy: short lookback, short holding period).
# ---------------------------------------------------------------------------


class ShortBreakout(TimeoutExitStrategy):
    """Mechanism: does the edge from breaking a recent range high exist
    IMMEDIATELY after the break, even if it disappears over a multi-day
    hold? Enter LONG when close breaks the prior `entry_lookback`-bar high
    (channel excludes the current bar via shift(1), same anti-lookahead
    convention as the slow Breakout strategy). Exit on a short timeout, or
    if price falls back below the prior `entry_lookback`-bar low (a fast
    failed-breakout exit), whichever comes first.
    """

    name = "short_breakout"

    def __init__(self, entry_lookback: int, max_holding_bars: int):
        if entry_lookback < 2:
            raise ValueError("entry_lookback must be >= 2")
        super().__init__(max_holding_bars=max_holding_bars, entry_lookback=entry_lookback)
        self.entry_lookback = entry_lookback

    @property
    def warmup_bars(self) -> int:
        return self.entry_lookback

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        prior_high = df["high"].shift(1).rolling(self.entry_lookback, min_periods=self.entry_lookback).max()
        return prior_high.notna() & (df["close"] > prior_high)

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        prior_low = df["low"].shift(1).rolling(self.entry_lookback, min_periods=self.entry_lookback).min()
        return prior_low.notna() & (df["close"] < prior_low)


# ---------------------------------------------------------------------------
# Family D: Extreme Move Reversal
# ---------------------------------------------------------------------------


class ExtremeMoveReversal(TimeoutExitStrategy):
    """Mechanism: an unusually large adverse move in a short window may
    reflect exhaustion, producing a bounce. Enter LONG only after an
    EXTREME trailing drop, measured in standardized units (a z-score of the
    trailing return against its own trailing distribution of such returns,
    NOT a raw percentage picked to fit this dataset) below `entry_z_score`
    (a fixed, pre-decided negative threshold). Exit after `max_holding_bars`
    (this is explicitly a short bounce-trade mechanism, not a new trend
    thesis) or if the trailing return recovers back to non-negative,
    whichever comes first.
    """

    name = "extreme_move_reversal"

    def __init__(self, return_lookback: int, zscore_window: int, entry_z_score: float, max_holding_bars: int):
        if entry_z_score >= 0:
            raise ValueError("entry_z_score must be negative (an extreme DROP)")
        super().__init__(
            max_holding_bars=max_holding_bars,
            return_lookback=return_lookback,
            zscore_window=zscore_window,
            entry_z_score=entry_z_score,
        )
        self.return_lookback = return_lookback
        self.zscore_window = zscore_window
        self.entry_z_score = entry_z_score

    @property
    def warmup_bars(self) -> int:
        return self.return_lookback + self.zscore_window

    def _trailing_return(self, df: pd.DataFrame) -> pd.Series:
        return df["close"] / df["close"].shift(self.return_lookback) - 1.0

    def _return_zscore(self, df: pd.DataFrame) -> pd.Series:
        r = self._trailing_return(df)
        mean = r.rolling(window=self.zscore_window, min_periods=self.zscore_window).mean()
        std = r.rolling(window=self.zscore_window, min_periods=self.zscore_window).std(ddof=0)
        return (r - mean) / std

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        z = self._return_zscore(df)
        return z.notna() & (z < self.entry_z_score)

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        r = self._trailing_return(df)
        return r.notna() & (r >= 0)


# ---------------------------------------------------------------------------
# Family E: Range/Volatility Expansion
# ---------------------------------------------------------------------------


class RangeExpansion(TimeoutExitStrategy):
    """Mechanism: a sudden expansion in a single bar's range relative to
    its own recent ATR, closing near the bar's high, may precede a short
    directional continuation. Enter LONG when the current bar's true range
    exceeds `atr_multiple` times its trailing ATR AND the close sits in the
    top `close_position_threshold` fraction of the bar's own range (e.g.
    close in the top 25% of [low, high]). Exit after `max_holding_bars`
    (this looks for an immediate continuation, not a new trend).
    """

    name = "range_expansion"

    def __init__(
        self,
        atr_period: int,
        atr_multiple: float,
        close_position_threshold: float,
        max_holding_bars: int,
    ):
        if atr_multiple <= 1.0:
            raise ValueError("atr_multiple must be > 1.0 (an EXPANSION relative to normal range)")
        if not (0.5 <= close_position_threshold < 1.0):
            raise ValueError("close_position_threshold must be in [0.5, 1.0) (top portion of the bar's range)")
        super().__init__(
            max_holding_bars=max_holding_bars,
            atr_period=atr_period,
            atr_multiple=atr_multiple,
            close_position_threshold=close_position_threshold,
        )
        self.atr_period = atr_period
        self.atr_multiple = atr_multiple
        self.close_position_threshold = close_position_threshold

    @property
    def warmup_bars(self) -> int:
        return self.atr_period * 4  # Wilder EWM convergence margin, same convention as elsewhere

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        tr = true_range(df)
        trailing_atr = atr(df, self.atr_period)
        bar_range = df["high"] - df["low"]
        close_position = (df["close"] - df["low"]) / bar_range.replace(0.0, pd.NA)

        expanded = trailing_atr.notna() & (tr > self.atr_multiple * trailing_atr)
        near_high = close_position.notna() & (close_position >= self.close_position_threshold)
        return expanded & near_high

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(False, index=df.index)  # timeout-only exit, per the mechanism


# ---------------------------------------------------------------------------
# Family F: Volume Shock + Price Direction
# ---------------------------------------------------------------------------


class VolumeShockDirection(TimeoutExitStrategy):
    """Mechanism: unusually high relative volume accompanied by a positive
    return and a close near the bar's high may indicate genuine
    participation behind the move (as far as OHLCV alone can indicate --
    this uses ONLY volume/price already in the candle, never inferred
    buyer/seller aggression or order flow). Enter LONG when relative volume
    (current volume / trailing median volume) exceeds `volume_multiple`,
    the bar's return is positive, and close sits in the top
    `close_position_threshold` fraction of the bar's range. Exit after
    `max_holding_bars` (a short reaction trade, not a new trend thesis).
    """

    name = "volume_shock_direction"

    def __init__(
        self,
        volume_median_window: int,
        volume_multiple: float,
        close_position_threshold: float,
        max_holding_bars: int,
    ):
        if volume_multiple <= 1.0:
            raise ValueError("volume_multiple must be > 1.0 (a volume SHOCK relative to normal)")
        if not (0.5 <= close_position_threshold < 1.0):
            raise ValueError("close_position_threshold must be in [0.5, 1.0)")
        super().__init__(
            max_holding_bars=max_holding_bars,
            volume_median_window=volume_median_window,
            volume_multiple=volume_multiple,
            close_position_threshold=close_position_threshold,
        )
        self.volume_median_window = volume_median_window
        self.volume_multiple = volume_multiple
        self.close_position_threshold = close_position_threshold

    @property
    def warmup_bars(self) -> int:
        return self.volume_median_window

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        # Trailing median EXCLUDING the current bar (shift(1)), so the
        # current bar's own volume can never inflate its own comparison
        # baseline -- the same anti-self-reference discipline used by
        # Breakout's shift(1) channel.
        trailing_median_volume = df["volume"].shift(1).rolling(
            self.volume_median_window, min_periods=self.volume_median_window
        ).median()
        relative_volume = df["volume"] / trailing_median_volume.replace(0.0, pd.NA)

        bar_return = bar_returns(df["close"])
        bar_range = df["high"] - df["low"]
        close_position = (df["close"] - df["low"]) / bar_range.replace(0.0, pd.NA)

        shock = relative_volume.notna() & (relative_volume > self.volume_multiple)
        positive = bar_return.notna() & (bar_return > 0)
        near_high = close_position.notna() & (close_position >= self.close_position_threshold)
        return shock & positive & near_high

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(False, index=df.index)  # timeout-only exit, per the mechanism
