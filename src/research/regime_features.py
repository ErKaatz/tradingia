"""Causal (trailing-only) market regime features.

Every feature in this module is computed using ONLY information available
at or before the current bar's close: rolling windows, `.shift()`, and
cumulative statistics over strictly past data. None of them may be used to
generate a trading signal directly -- they exist purely to *describe* the
market condition at a point in time, for diagnostic/research purposes
(Phase 3B regime research). Do not wire any of these into a Strategy's
generate_signals without going through the same preregistration discipline
as everything else in this project.

## Anti-lookahead contract

For every feature function `f(df) -> pd.Series`, the value at row `i` must
depend only on `df.iloc[:i+1]`. This is verified by
`tests/test_regime_features.py` via truncation invariance (the standard
test pattern already used for strategies in `tests/test_strategies.py`):
truncating the dataframe must never change a previously computed value.

## Design choices (documented, not implicit)

- All "trailing N" features use `min_periods=N` (or the tightest achievable
  approximation for multi-stage indicators like ADX), so a feature is NaN
  until it has a full window of real history -- never partially computed
  on padding.
- Windows are expressed in bars, matching the project's 1h BTCUSDT
  timeframe (24 = 1 day, 168 = 1 week, 720 = 30 days).
- No feature here performs any kind of look-back-then-forward smoothing
  (e.g. centered rolling windows) -- every rolling/ewm call is trailing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def bar_returns(close: pd.Series) -> pd.Series:
    """Simple bar-over-bar percentage return. return[i] uses close[i] and
    close[i-1] only -- both already known at bar i's close.
    """
    return close.pct_change()


def realized_volatility(close: pd.Series, window: int, annualize: bool = False) -> pd.Series:
    """Trailing realized volatility of bar returns over `window` bars.

    Uses `min_periods=window` so the first `window-1` values are NaN rather
    than computed on a partial window. `annualize=True` scales to an annual
    figure assuming 24 bars/day * 365 days/year, matching the convention
    already used in `src/strategies/breakout_forward.py`'s adaptive vol gate.
    """
    returns = bar_returns(close)
    vol = returns.rolling(window=window, min_periods=window).std(ddof=0)
    if annualize:
        vol = vol * np.sqrt(24 * 365)
    return vol


def true_range(df: pd.DataFrame) -> pd.Series:
    """Wilder's True Range using only the prior bar's close (shift(1)) and
    the current bar's high/low -- standard causal definition.
    """
    prior_close = df["close"].shift(1)
    a = df["high"] - df["low"]
    b = (df["high"] - prior_close).abs()
    c = (df["low"] - prior_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range, Wilder-smoothed (EWM alpha=1/period), the same
    smoothing family already used by `MeanReversion`'s RSI in
    `src/strategies/mean_reversion.py` for internal consistency.
    """
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def atr_over_close(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR normalized by price level, making it comparable across BTC's
    very different price regimes (e.g. $3k in 2018 vs $100k in 2025).
    """
    return atr(df, period) / df["close"]


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder), a standard trend-strength
    indicator: high ADX means a strong directional move is underway
    (either direction), low ADX means a choppy/range-bound market.
    Fully causal -- every term is trailing True Range / directional
    movement, Wilder-smoothed.
    """
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    tr = true_range(df)
    atr_smoothed = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_smoothed
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_smoothed

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def sma_slope(close: pd.Series, window: int, slope_lookback: int = 1) -> pd.Series:
    """Normalized slope of a trailing SMA: (SMA[i] - SMA[i - slope_lookback])
    / SMA[i - slope_lookback], expressed as a fractional change per
    `slope_lookback` bars. Uses only trailing SMA values (each of which is
    itself trailing-only), so the slope itself introduces no lookahead.
    """
    sma = close.rolling(window=window, min_periods=window).mean()
    return sma.pct_change(periods=slope_lookback)


def distance_from_sma(close: pd.Series, window: int) -> pd.Series:
    """(close - SMA) / SMA -- how far price currently sits from its own
    trailing moving average, as a fraction. Positive = above the average.
    """
    sma = close.rolling(window=window, min_periods=window).mean()
    return (close - sma) / sma


def rolling_autocorrelation(returns: pd.Series, window: int, lag: int = 1) -> pd.Series:
    """Trailing lag-`lag` autocorrelation of bar returns over `window` bars.

    Positive autocorrelation suggests trending/persistent behavior (a
    positive return bar tends to be followed by another positive one);
    autocorrelation near zero or negative suggests mean-reverting/choppy
    behavior. Computed with pandas' rolling `.apply`, which by construction
    only ever sees the trailing window ending at the current bar.
    """

    def _autocorr(window_values: np.ndarray) -> float:
        if len(window_values) <= lag:
            return np.nan
        a = window_values[:-lag]
        b = window_values[lag:]
        if np.std(a) == 0 or np.std(b) == 0:
            return np.nan
        return float(np.corrcoef(a, b)[0, 1])

    return returns.rolling(window=window, min_periods=window).apply(_autocorr, raw=True)


def kaufman_efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    """Kaufman's Efficiency Ratio: net directional displacement over
    `window` bars divided by the sum of absolute bar-to-bar movements over
    the same window. Ranges from 0 (pure noise / round-trip chop) to 1
    (a straight, uninterrupted move). A standard, well-known trend-quality
    measure (Kaufman, "Trading Systems and Methods") -- not an invented
    metric for this project.
    """
    net_change = (close - close.shift(window)).abs()
    path_length = close.diff().abs().rolling(window=window, min_periods=window).sum()
    return net_change / path_length


def realized_range(df: pd.DataFrame, window: int) -> pd.Series:
    """Trailing realized range: (max(high) - min(low)) over `window` bars,
    normalized by the window's starting close so it is comparable across
    BTC's price history. Distinct from realized volatility (std of returns)
    -- range captures the total excursion, not the bar-to-bar noisiness.
    """
    rolling_high = df["high"].rolling(window=window, min_periods=window).max()
    rolling_low = df["low"].rolling(window=window, min_periods=window).min()
    reference_close = df["close"].shift(window - 1)
    return (rolling_high - rolling_low) / reference_close


def range_compression_ratio(df: pd.DataFrame, short_window: int = 24, long_window: int = 168) -> pd.Series:
    """Ratio of short-horizon realized range to long-horizon realized
    range. A value well below 1 indicates the recent short-term range is
    compressed relative to the longer-term range -- i.e. volatility/range
    contraction. Both numerator and denominator are independently
    trailing-only.
    """
    short_range = realized_range(df, short_window)
    long_range = realized_range(df, long_window)
    return short_range / long_range


def directional_persistence(close: pd.Series, window: int) -> pd.Series:
    """Fraction of bars within the trailing window whose return has the
    SAME sign as the window's net return -- a simple, interpretable measure
    of how "one-directional" recent price action has been (distinct from,
    but related in spirit to, the efficiency ratio).
    """
    returns = bar_returns(close)
    net_sign = np.sign(close - close.shift(window))

    def _persistence(window_returns: np.ndarray, sign: float) -> float:
        if np.isnan(sign) or sign == 0:
            return np.nan
        same_sign = np.sign(window_returns) == sign
        return float(np.mean(same_sign))

    out = pd.Series(np.nan, index=close.index)
    ret_values = returns.to_numpy()
    sign_values = net_sign.to_numpy()
    for i in range(window, len(close)):
        window_slice = ret_values[i - window + 1 : i + 1]
        if np.isnan(window_slice).any():
            continue
        out.iloc[i] = _persistence(window_slice, sign_values[i])
    return out


def pct_positive_bars(close: pd.Series, window: int) -> pd.Series:
    """Fraction of the trailing `window` bars with a positive return."""
    returns = bar_returns(close)
    is_positive = (returns > 0).astype(float)
    return is_positive.rolling(window=window, min_periods=window).mean()


# ---------------------------------------------------------------------------
# Feature registry: one row per bar, one column per feature.
# ---------------------------------------------------------------------------

# Kept intentionally smaller than every feature suggested in the task
# prompt: several suggested features are redundant transformations of each
# other (e.g. "distance close vs SMA 200" and "slope of SMA 200" both
# capture trend state; "realized range 24h/168h" and "range compression
# ratio" are the same computation). Task 1 explicitly allows dropping
# redundant features in favor of interpretability, and Task 6's "not a
# duplicated transformation of another feature" criterion argues against
# carrying near-duplicates into the hypothesis stage.
FEATURE_WARMUP_BARS: dict[str, int] = {
    "realized_vol_24h": 24,
    "realized_vol_168h": 168,
    "realized_vol_720h": 720,
    "atr_14": 14 * 4,  # Wilder EWM: min_periods=14 plus margin for convergence, same convention as MeanReversion's RSI warmup (period*4)
    "atr_over_close_14": 14 * 4,
    "adx_14": 14 * 4,
    "sma50_slope": 50,
    "sma200_slope": 200,
    "distance_from_sma200": 200,
    "autocorr_24h": 24,
    "autocorr_168h": 168,
    "efficiency_ratio_20": 20,
    "range_compression_24_168": 168,
    "directional_persistence_168": 168,
    "pct_positive_bars_24h": 24,
    "pct_positive_bars_72h": 72,
    "pct_positive_bars_168h": 168,
}


def compute_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the full causal regime-feature table for an OHLCV dataframe.

    Returns a dataframe indexed identically to `df` (same length, same
    `timestamp` column carried through) with one column per feature. Rows
    before a feature's warm-up requirement are NaN for that feature --
    callers must not treat NaN as zero or drop rows globally without
    checking which features they actually need.
    """
    close = df["close"]

    out = pd.DataFrame({"timestamp": df["timestamp"]})
    out["realized_vol_24h"] = realized_volatility(close, 24)
    out["realized_vol_168h"] = realized_volatility(close, 168)
    out["realized_vol_720h"] = realized_volatility(close, 720)
    out["atr_14"] = atr(df, 14)
    out["atr_over_close_14"] = atr_over_close(df, 14)
    out["adx_14"] = adx(df, 14)
    out["sma50_slope"] = sma_slope(close, 50)
    out["sma200_slope"] = sma_slope(close, 200)
    out["distance_from_sma200"] = distance_from_sma(close, 200)
    out["autocorr_24h"] = rolling_autocorrelation(bar_returns(close), 24)
    out["autocorr_168h"] = rolling_autocorrelation(bar_returns(close), 168)
    out["efficiency_ratio_20"] = kaufman_efficiency_ratio(close, 20)
    out["range_compression_24_168"] = range_compression_ratio(df, 24, 168)
    out["directional_persistence_168"] = directional_persistence(close, 168)
    out["pct_positive_bars_24h"] = pct_positive_bars(close, 24)
    out["pct_positive_bars_72h"] = pct_positive_bars(close, 72)
    out["pct_positive_bars_168h"] = pct_positive_bars(close, 168)
    return out


def max_feature_warmup_bars() -> int:
    """Warm-up bars needed before every feature in the registry is valid
    (i.e. the longest individual warm-up requirement). Callers computing
    features for a specific window of interest should prepend at least this
    many trailing bars of context.
    """
    return max(FEATURE_WARMUP_BARS.values())


def feature_values_at(features: pd.DataFrame, timestamps: pd.Series) -> pd.DataFrame:
    """Look up feature rows at (or immediately at-or-before) a set of
    timestamps -- used to capture "regime at entry" for a list of trade
    entry times. Uses `merge_asof` with direction='backward', which by
    construction can only match a feature row at or before each timestamp,
    never after it -- this is the causal-lookup analog of the trailing
    features themselves.
    """
    lookup = features.sort_values("timestamp").reset_index(drop=True)
    queries = pd.DataFrame({"timestamp": pd.to_datetime(timestamps, utc=True)})
    queries_sorted = queries.sort_values("timestamp")
    matched = pd.merge_asof(
        queries_sorted,
        lookup,
        on="timestamp",
        direction="backward",
    )
    # merge_asof requires sorted input and returns a fresh RangeIndex in
    # sorted order; reattach the original (pre-sort) query index positions
    # so callers can zip results back against their original trade list in
    # the order they passed timestamps in.
    matched.index = queries_sorted.index
    return matched.sort_index()
