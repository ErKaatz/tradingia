"""Anti-lookahead and mechanism tests for the Phase 4A strategy families
(short momentum, short mean-reversion z-score, short breakout, extreme
move reversal, range expansion, volume shock + direction).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import FLAT, LONG
from src.strategies.short_horizon import (
    ExtremeMoveReversal,
    RangeExpansion,
    ShortBreakout,
    ShortMeanReversionZScore,
    ShortMomentum,
    VolumeShockDirection,
    rolling_zscore,
)


def make_df(n, seed=11):
    import random

    rng = random.Random(seed)
    closes = [30000.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] * (1 + rng.uniform(-0.02, 0.02))))
    highs = [c * (1 + rng.uniform(0, 0.01)) for c in closes]
    lows = [c * (1 - rng.uniform(0, 0.01)) for c in closes]
    volumes = [rng.uniform(50, 150) for _ in closes]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


ALL_STRATEGIES = [
    lambda: ShortMomentum(lookback=8, max_holding_bars=8),
    lambda: ShortMeanReversionZScore(window=24, entry_z=-1.5, exit_z=0.0, max_holding_bars=24),
    lambda: ShortBreakout(entry_lookback=16, max_holding_bars=16),
    lambda: ExtremeMoveReversal(return_lookback=12, zscore_window=48, entry_z_score=-2.0, max_holding_bars=24),
    lambda: RangeExpansion(atr_period=14, atr_multiple=1.5, close_position_threshold=0.75, max_holding_bars=8),
    lambda: VolumeShockDirection(volume_median_window=48, volume_multiple=2.0, close_position_threshold=0.75, max_holding_bars=8),
]
ALL_STRATEGY_IDS = [
    "short_momentum", "short_mean_reversion_zscore", "short_breakout",
    "extreme_move_reversal", "range_expansion", "volume_shock_direction",
]


@pytest.mark.parametrize("make_strategy", ALL_STRATEGIES, ids=ALL_STRATEGY_IDS)
def test_no_lookahead_truncation_invariance(make_strategy):
    df_full = make_df(600)
    strategy = make_strategy()
    full_signals = strategy.generate_signals(df_full)

    truncate_at = 400
    df_truncated = df_full.iloc[:truncate_at].reset_index(drop=True)
    strategy2 = make_strategy()
    truncated_signals = strategy2.generate_signals(df_truncated)

    pd.testing.assert_series_equal(
        full_signals.iloc[:truncate_at].reset_index(drop=True),
        truncated_signals.reset_index(drop=True),
        check_names=False,
    )


@pytest.mark.parametrize("make_strategy", ALL_STRATEGIES, ids=ALL_STRATEGY_IDS)
def test_signals_are_only_flat_or_long(make_strategy):
    df = make_df(300)
    signals = make_strategy().generate_signals(df)
    assert set(signals.unique()).issubset({FLAT, LONG})


def test_rolling_zscore_matches_manual_calculation():
    closes = pd.Series([100, 102, 101, 105, 103, 108, 107, 110], dtype=float)
    z = rolling_zscore(closes, window=4)
    window = closes.iloc[-4:]
    expected = (closes.iloc[-1] - window.mean()) / window.std(ddof=0)
    assert z.iloc[-1] == pytest.approx(expected)
    assert z.iloc[:3].isna().all()


def test_short_mean_reversion_enters_on_extreme_negative_zscore():
    # Flat prices then a sharp drop should push z well below -1.5.
    closes = [100.0] * 30 + [80.0]
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=len(closes), freq="15min", tz="UTC"),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [100.0] * len(closes),
        }
    )
    strat = ShortMeanReversionZScore(window=20, entry_z=-1.5, exit_z=0.0, max_holding_bars=50)
    signals = strat.generate_signals(df)
    assert signals.iloc[-1] == LONG


def test_short_mean_reversion_rejects_entry_z_above_exit_z():
    with pytest.raises(ValueError):
        ShortMeanReversionZScore(window=20, entry_z=0.5, exit_z=-0.5, max_holding_bars=10)


def test_short_breakout_excludes_current_bar_from_channel():
    """The entry channel must be computed from prior bars only (shift(1)):
    a bar that itself sets a new high must not compare against a channel
    that already includes its own high.
    """
    closes = [100.0] * 10 + [200.0]  # last bar spikes far above everything
    highs = closes.copy()
    lows = closes.copy()
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=len(closes), freq="15min", tz="UTC"),
            "open": closes, "high": highs, "low": lows, "close": closes,
            "volume": [100.0] * len(closes),
        }
    )
    strat = ShortBreakout(entry_lookback=5, max_holding_bars=5)
    signals = strat.generate_signals(df)
    # The spike bar (last) must trigger LONG: its close (200) breaks the
    # PRIOR 5-bar high (100), not a channel that already includes 200.
    assert signals.iloc[-1] == LONG


def test_extreme_move_reversal_rejects_non_negative_entry_zscore():
    with pytest.raises(ValueError):
        ExtremeMoveReversal(return_lookback=6, zscore_window=48, entry_z_score=0.0, max_holding_bars=10)


def test_extreme_move_reversal_enters_after_sharp_drop():
    # Long stable period, then a sharp trailing drop.
    closes = [100.0] * 60 + [70.0]
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=len(closes), freq="15min", tz="UTC"),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [100.0] * len(closes),
        }
    )
    strat = ExtremeMoveReversal(return_lookback=6, zscore_window=48, entry_z_score=-2.0, max_holding_bars=20)
    signals = strat.generate_signals(df)
    assert (signals == LONG).any()


def test_range_expansion_rejects_atr_multiple_at_or_below_one():
    with pytest.raises(ValueError):
        RangeExpansion(atr_period=14, atr_multiple=1.0, close_position_threshold=0.75, max_holding_bars=8)


def test_range_expansion_rejects_close_position_out_of_bounds():
    with pytest.raises(ValueError):
        RangeExpansion(atr_period=14, atr_multiple=1.5, close_position_threshold=1.0, max_holding_bars=8)
    with pytest.raises(ValueError):
        RangeExpansion(atr_period=14, atr_multiple=1.5, close_position_threshold=0.3, max_holding_bars=8)


def test_range_expansion_enters_on_wide_bar_closing_near_high():
    n = 60
    closes = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    # Last bar: wide range, closes near the high.
    closes[-1] = 110.0
    highs[-1] = 111.0
    lows[-1] = 95.0
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": [100.0] * n, "high": highs, "low": lows, "close": closes,
            "volume": [100.0] * n,
        }
    )
    strat = RangeExpansion(atr_period=14, atr_multiple=1.5, close_position_threshold=0.75, max_holding_bars=8)
    signals = strat.generate_signals(df)
    assert signals.iloc[-1] == LONG


def test_volume_shock_direction_rejects_volume_multiple_at_or_below_one():
    with pytest.raises(ValueError):
        VolumeShockDirection(volume_median_window=48, volume_multiple=1.0, close_position_threshold=0.75, max_holding_bars=8)


def test_volume_shock_uses_trailing_median_excluding_current_bar():
    """The current bar's own volume must never inflate its own comparison
    baseline -- median is computed with shift(1).
    """
    n = 60
    volumes = [100.0] * n
    volumes[-1] = 1000.0  # shock bar
    closes = [100.0 + i * 0.01 for i in range(n)]
    closes[-1] = closes[-2] + 5.0  # strong positive return on the shock bar
    highs = [c + 0.1 for c in closes]
    lows = [c - 0.1 for c in closes]
    highs[-1] = closes[-1] + 0.05  # close near the high
    lows[-1] = closes[-2]
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"),
            "open": closes, "high": highs, "low": lows, "close": closes,
            "volume": volumes,
        }
    )
    strat = VolumeShockDirection(volume_median_window=48, volume_multiple=2.0, close_position_threshold=0.75, max_holding_bars=8)
    signals = strat.generate_signals(df)
    assert signals.iloc[-1] == LONG
