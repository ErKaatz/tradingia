"""Causal, event-driven Phase 5E signal families.

These functions deliberately only produce targets.  The FX engine owns the
one-bar signal-to-fill shift, costs and account policy.  No function here
loads research data or evaluates performance.
"""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar

ACTIVE_START_UTC = 1
ACTIVE_END_UTC = 20


def _active(bar: FxBar) -> bool:
    return ACTIVE_START_UTC <= bar.timestamp_utc.hour < ACTIVE_END_UTC


def _event_targets(bars: tuple[FxBar, ...], events: Callable[[int], TargetPosition], holding_bars: int) -> tuple[TargetPosition, ...]:
    """Consume one event into exactly ``holding_bars`` signal bars.

    The output is still a target stream, therefore the engine opens on the
    following bar.  A new event is ignored while the previous event's target
    is active; this is the one-event/one-position contract.
    """
    if holding_bars < 1:
        raise ValueError("holding_bars must be positive")
    result: list[TargetPosition] = []
    held_side = TargetPosition.FLAT
    remaining = 0
    for index, bar in enumerate(bars):
        if not _active(bar):
            result.append(TargetPosition.FLAT)
            held_side, remaining = TargetPosition.FLAT, 0
            continue
        if remaining:
            result.append(held_side)
            remaining -= 1
            continue
        side = events(index)
        if side not in (TargetPosition.LONG, TargetPosition.SHORT):
            result.append(TargetPosition.FLAT)
            continue
        result.append(side)
        held_side, remaining = side, holding_bars - 1
    return tuple(result)


def compression_expansion(bars: tuple[FxBar, ...], atr_lookback: int, breakout_lookback: int, compression_ratio: float, holding_bars: int = 4) -> tuple[TargetPosition, ...]:
    if atr_lookback < 2 or breakout_lookback < 2 or not 0 < compression_ratio < 1:
        raise ValueError("invalid compression-expansion parameters")
    highs = pd.Series([float(bar.high) for bar in bars])
    lows = pd.Series([float(bar.low) for bar in bars])
    closes = pd.Series([float(bar.close) for bar in bars])
    previous_close = closes.shift(1)
    true_range = pd.concat([highs - lows, (highs - previous_close).abs(), (lows - previous_close).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(atr_lookback, min_periods=atr_lookback).mean()
    compressed_range = (highs.rolling(breakout_lookback, min_periods=breakout_lookback).max() - lows.rolling(breakout_lookback, min_periods=breakout_lookback).min())
    prior_high = highs.shift(1).rolling(breakout_lookback, min_periods=breakout_lookback).max()
    prior_low = lows.shift(1).rolling(breakout_lookback, min_periods=breakout_lookback).min()

    def event(index: int) -> TargetPosition:
        if pd.isna(atr.iloc[index]) or atr.iloc[index] <= 0 or pd.isna(prior_high.iloc[index]): return TargetPosition.FLAT
        if compressed_range.iloc[index] / atr.iloc[index] > compression_ratio: return TargetPosition.FLAT
        if closes.iloc[index] > prior_high.iloc[index]: return TargetPosition.LONG
        if closes.iloc[index] < prior_low.iloc[index]: return TargetPosition.SHORT
        return TargetPosition.FLAT
    return _event_targets(bars, event, holding_bars)


def session_range_breakout(bars: tuple[FxBar, ...], range_start_hour: int, range_end_hour: int, entry_start_hour: int, entry_end_hour: int, holding_bars: int = 4) -> tuple[TargetPosition, ...]:
    if not 0 <= range_start_hour < range_end_hour < entry_start_hour < entry_end_hour <= ACTIVE_END_UTC:
        raise ValueError("invalid UTC session range/breakout parameters")
    highs: dict[object, float] = {}
    lows: dict[object, float] = {}
    consumed: set[object] = set()
    events: dict[int, TargetPosition] = {}
    for index, bar in enumerate(bars):
        day, hour = bar.timestamp_utc.date(), bar.timestamp_utc.hour
        if range_start_hour <= hour < range_end_hour:
            highs[day] = max(highs.get(day, float("-inf")), float(bar.high))
            lows[day] = min(lows.get(day, float("inf")), float(bar.low))
        if day in consumed or not entry_start_hour <= hour < entry_end_hour or day not in highs:
            continue
        if float(bar.close) > highs[day]: events[index], consumed = TargetPosition.LONG, consumed | {day}
        elif float(bar.close) < lows[day]: events[index], consumed = TargetPosition.SHORT, consumed | {day}
    return _event_targets(bars, lambda index: events.get(index, TargetPosition.FLAT), holding_bars)


def standardized_impulse(bars: tuple[FxBar, ...], normalization_lookback: int, threshold: float, holding_bars: int, contrarian: bool) -> tuple[TargetPosition, ...]:
    if normalization_lookback < 2 or threshold <= 0 or holding_bars < 1:
        raise ValueError("invalid standardized-impulse parameters")
    close = pd.Series([float(bar.close) for bar in bars])
    returns = close.pct_change()
    mean = returns.shift(1).rolling(normalization_lookback, min_periods=normalization_lookback).mean()
    std = returns.shift(1).rolling(normalization_lookback, min_periods=normalization_lookback).std().replace(0, float("nan"))
    z = (returns - mean) / std

    def event(index: int) -> TargetPosition:
        value = z.iloc[index]
        if pd.isna(value) or abs(value) < threshold: return TargetPosition.FLAT
        direction = TargetPosition.LONG if value > 0 else TargetPosition.SHORT
        if contrarian: return TargetPosition.SHORT if direction is TargetPosition.LONG else TargetPosition.LONG
        return direction
    return _event_targets(bars, event, holding_bars)


def control_flat(bars: tuple[FxBar, ...]) -> tuple[TargetPosition, ...]:
    return tuple(TargetPosition.FLAT for _ in bars)
