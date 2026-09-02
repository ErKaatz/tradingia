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


# ---------------------------------------------------------------------------
# Task 9: VWAP intraday mean reversion -- implemented as a marked-weak
# experiment, not a mechanism the project endorses as economically sound.
# ---------------------------------------------------------------------------


class VwapIntradayMeanReversion(TimeoutExitStrategy):
    """EXPERIMENTAL / METHODOLOGICALLY WEAK. See the module-level docstring
    section "VWAP session-definition limitations" before using any result
    from this strategy for anything beyond curiosity.

    Mechanism (as usually stated for traditional, single-exchange, session-
    based markets): price trading far below the session's volume-weighted
    average price may revert back toward VWAP as the session progresses,
    because VWAP is a reference many participants (especially execution
    algorithms) are known to trade around.

    Implementation: VWAP is computed causally within an explicit UTC daily
    session (00:00:00 UTC session boundary, matching the project's existing
    UTC-everywhere convention), resetting cumulative price*volume and
    volume sums at each session start -- the sums up to and including bar i
    depend only on bars from that session's start through i, never on a
    future bar or a future session. Distance is measured as
    (close - session_vwap) / session_vwap. Enter LONG when this distance is
    below `entry_distance` (a fixed negative threshold); exit at/above
    `exit_distance` (typically 0, "back to VWAP"), after `max_holding_bars`,
    or on the FIRST bar of the next session (detected causally via
    shift(1), i.e. one bar after the actual boundary -- not shift(-1),
    which would require knowing the boundary in advance and would violate
    the project's anti-lookahead rule) -- so a position is never carried
    meaningfully across the arbitrary session reset, since doing so would
    silently smuggle in a second, undocumented assumption about session
    continuity.

    ## VWAP session-definition limitations (documented per Task 9)

    BTC/USDT trades continuously 24/7 with no open, close, or official
    session of its own -- unlike the equities/futures markets VWAP mean-
    reversion is traditionally studied in, where session boundaries
    correspond to a real halt in trading and a real reset of order flow.
    Defining a "session" as UTC midnight-to-midnight is an arbitrary
    convention with NO economic anchor: no material fraction of BTC market
    participants is known to treat 00:00 UTC as special, so a VWAP reset at
    that instant does not correspond to any actual change in market
    structure or participant behavior. Any reversion effect this strategy
    finds could easily be an artifact of the arbitrary reset point rather
    than a genuine "distance from a reference price" mechanism -- e.g. a
    reset shortly after a real intraday extreme would mechanically produce
    a large "distance from VWAP" reading having nothing to do with mean-
    reversion behavior. This is why the strategy is retained as a MARKED
    WEAK experiment rather than promoted alongside Families A-F: it is
    included so its (likely weak) results are visible and documented,
    exactly as `RESEARCH_RULES.md` requires failed/dubious experiments to
    remain visible rather than be silently omitted.
    """

    name = "vwap_intraday_mean_reversion_experimental"

    def __init__(self, entry_distance: float, exit_distance: float, max_holding_bars: int):
        if entry_distance >= exit_distance:
            raise ValueError("entry_distance must be < exit_distance (enter below, exit above)")
        super().__init__(
            max_holding_bars=max_holding_bars, entry_distance=entry_distance, exit_distance=exit_distance
        )
        self.entry_distance = entry_distance
        self.exit_distance = exit_distance

    @property
    def warmup_bars(self) -> int:
        return 0  # each UTC session resets independently; no cross-session warm-up needed

    def _session_vwap_distance(self, df: pd.DataFrame) -> pd.Series:
        ts = pd.to_datetime(df["timestamp"], utc=True)
        session_id = ts.dt.floor("D")

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        pv = typical_price * df["volume"]

        # Cumulative sums WITHIN each session only: groupby().cumsum() over
        # a session id computed purely from each row's own timestamp is
        # causal by construction -- session_id at row i depends only on
        # row i's own timestamp, and the cumulative sum up to row i depends
        # only on rows <= i within the same session.
        cum_pv = pv.groupby(session_id).cumsum()
        cum_volume = df["volume"].groupby(session_id).cumsum()
        session_vwap = cum_pv / cum_volume.replace(0.0, pd.NA)

        return (df["close"] - session_vwap) / session_vwap

    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        distance = self._session_vwap_distance(df)
        return distance.notna() & (distance < self.entry_distance)

    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        distance = self._session_vwap_distance(df)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        session_id = ts.dt.floor("D")
        # Exit as soon as the CURRENT bar's session differs from the PRIOR
        # bar's session (i.e. this bar is the first bar of a new session,
        # so the position must already have been closed by the end of the
        # previous one). Uses shift(1) -- strictly backward-looking -- not
        # shift(-1), which would require knowing the future boundary and
        # would violate the project's anti-lookahead rule.
        session_changed = session_id != session_id.shift(1)
        return (distance.notna() & (distance >= self.exit_distance)) | session_changed.fillna(False)
