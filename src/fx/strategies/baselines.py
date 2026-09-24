"""Preregistered, causal EURUSD/M15 baseline signals for Phase 5D."""

from __future__ import annotations

import pandas as pd

from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar

_ACTIVE_START_UTC = 1
_ACTIVE_END_UTC = 20


def _active(bar: FxBar) -> bool:
    return _ACTIVE_START_UTC <= bar.timestamp_utc.hour < _ACTIVE_END_UTC


def _targets(bars: tuple[FxBar, ...], values: pd.Series) -> tuple[TargetPosition, ...]:
    result = []
    for bar, value in zip(bars, values):
        if not _active(bar) or pd.isna(value):
            result.append(TargetPosition.FLAT)
        elif value > 0:
            result.append(TargetPosition.LONG)
        elif value < 0:
            result.append(TargetPosition.SHORT)
        else:
            result.append(TargetPosition.FLAT)
    return tuple(result)


def ema_trend(bars: tuple[FxBar, ...], fast: int, slow: int) -> tuple[TargetPosition, ...]:
    if fast >= slow:
        raise ValueError("fast must be less than slow")
    close = pd.Series([float(bar.close) for bar in bars])
    return _targets(bars, close.ewm(span=fast, min_periods=fast, adjust=False).mean() - close.ewm(span=slow, min_periods=slow, adjust=False).mean())


def zscore_mean_reversion(bars: tuple[FxBar, ...], window: int, threshold: float) -> tuple[TargetPosition, ...]:
    close = pd.Series([float(bar.close) for bar in bars])
    mean = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std()
    z = (close - mean) / std.replace(0, float("nan"))
    # Negative z enters LONG; positive z enters SHORT.
    return _targets(bars, -z.where(z.abs() >= threshold, 0.0))


def signed_momentum(bars: tuple[FxBar, ...], lookback: int) -> tuple[TargetPosition, ...]:
    close = pd.Series([float(bar.close) for bar in bars])
    return _targets(bars, close - close.shift(lookback))


def session_breakout(bars: tuple[FxBar, ...], range_start_hour: int, trade_start_hour: int) -> tuple[TargetPosition, ...]:
    """Trade post-range close breakouts, with a numeric UTC definition."""
    if not 0 <= range_start_hour < trade_start_hour < _ACTIVE_END_UTC:
        raise ValueError("require 0 <= range_start < trade_start < 20")
    highs: dict[object, float] = {}
    lows: dict[object, float] = {}
    result = []
    for bar in bars:
        day = bar.timestamp_utc.date()
        hour = bar.timestamp_utc.hour
        if range_start_hour <= hour < trade_start_hour:
            highs[day] = max(highs.get(day, float("-inf")), float(bar.high))
            lows[day] = min(lows.get(day, float("inf")), float(bar.low))
        if not _active(bar) or hour < trade_start_hour or day not in highs:
            result.append(TargetPosition.FLAT)
        elif bar.close > highs[day]:
            result.append(TargetPosition.LONG)
        elif bar.close < lows[day]:
            result.append(TargetPosition.SHORT)
        else:
            result.append(TargetPosition.FLAT)
    return tuple(result)


def directional_control(bars: tuple[FxBar, ...], side: TargetPosition) -> tuple[TargetPosition, ...]:
    if side not in (TargetPosition.LONG, TargetPosition.SHORT, TargetPosition.FLAT):
        raise ValueError("invalid control target")
    return tuple(side if _active(bar) else TargetPosition.FLAT for bar in bars)
