"""Anti-lookahead tests for src/research/regime_features.py.

Every feature must pass truncation invariance: computing the feature on a
truncated dataframe must produce identical values (up to the truncation
point) as computing it on the full dataframe. This is the same pattern
already used in tests/test_strategies.py for Strategy.generate_signals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.regime_features import (
    FEATURE_WARMUP_BARS,
    adx,
    atr,
    atr_over_close,
    compute_regime_features,
    directional_persistence,
    distance_from_sma,
    feature_values_at,
    kaufman_efficiency_ratio,
    max_feature_warmup_bars,
    pct_positive_bars,
    range_compression_ratio,
    realized_range,
    realized_volatility,
    rolling_autocorrelation,
    sma_slope,
)


def make_df(n, seed=7):
    import random

    rng = random.Random(seed)
    closes = [30000.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] * (1 + rng.uniform(-0.03, 0.03))))
    highs = [c * (1 + rng.uniform(0, 0.01)) for c in closes]
    lows = [c * (1 - rng.uniform(0, 0.01)) for c in closes]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * n,
        }
    )


TRUNCATION_CASES = [
    ("realized_vol_24h", lambda df: realized_volatility(df["close"], 24)),
    ("realized_vol_168h", lambda df: realized_volatility(df["close"], 168)),
    ("atr_14", lambda df: atr(df, 14)),
    ("atr_over_close_14", lambda df: atr_over_close(df, 14)),
    ("adx_14", lambda df: adx(df, 14)),
    ("sma50_slope", lambda df: sma_slope(df["close"], 50)),
    ("distance_from_sma200", lambda df: distance_from_sma(df["close"], 200)),
    ("autocorr_24h", lambda df: rolling_autocorrelation(df["close"].pct_change(), 24)),
    ("efficiency_ratio_20", lambda df: kaufman_efficiency_ratio(df["close"], 20)),
    ("range_compression_24_168", lambda df: range_compression_ratio(df, 24, 168)),
    ("realized_range_24", lambda df: realized_range(df, 24)),
    ("directional_persistence_168", lambda df: directional_persistence(df["close"], 168)),
    ("pct_positive_bars_24h", lambda df: pct_positive_bars(df["close"], 24)),
]


@pytest.mark.parametrize("name,fn", TRUNCATION_CASES, ids=[c[0] for c in TRUNCATION_CASES])
def test_feature_truncation_invariance(name, fn):
    """The value at row i must not depend on any row after i: truncating
    the dataframe anywhere must leave earlier values unchanged.
    """
    df_full = make_df(1000)
    full_values = fn(df_full)

    truncate_at = 700
    df_truncated = df_full.iloc[:truncate_at].reset_index(drop=True)
    truncated_values = fn(df_truncated)

    pd.testing.assert_series_equal(
        full_values.iloc[:truncate_at].reset_index(drop=True),
        truncated_values.reset_index(drop=True),
        check_names=False,
        atol=1e-9,
    )


def test_compute_regime_features_full_table_truncation_invariance():
    """The aggregate compute_regime_features table must also be truncation
    invariant, column by column.
    """
    df_full = make_df(1000)
    full_table = compute_regime_features(df_full)

    truncate_at = 750
    df_truncated = df_full.iloc[:truncate_at].reset_index(drop=True)
    truncated_table = compute_regime_features(df_truncated)

    for col in full_table.columns:
        if col == "timestamp":
            continue
        pd.testing.assert_series_equal(
            full_table[col].iloc[:truncate_at].reset_index(drop=True),
            truncated_table[col].reset_index(drop=True),
            check_names=False,
            atol=1e-9,
        )


def test_features_respect_declared_warmup_bars():
    """Before a feature's declared warm-up bar count, its value must be
    NaN; a feature that produces a non-NaN value before its own declared
    warm-up would be silently using an incomplete window.
    """
    df = make_df(2000)
    table = compute_regime_features(df)

    for feature, warmup in FEATURE_WARMUP_BARS.items():
        # Compare against the *shorter-window* variants only for those
        # whose warmup equals exactly the base rolling window (skip the
        # Wilder-smoothed ones with a convergence margin, checked below).
        if feature in {"atr_14", "atr_over_close_14", "adx_14"}:
            continue
        first_valid = table[feature].first_valid_index()
        assert first_valid is not None, f"{feature} never produced a value"
        # first_valid_index is 0-based row position here since index is a
        # default RangeIndex.
        assert first_valid >= warmup - 1, (
            f"{feature} produced a value at row {first_valid}, "
            f"before its declared warmup of {warmup} bars"
        )


def test_wilder_smoothed_features_are_nan_before_min_periods():
    """ATR/ADX (EWM with min_periods) must be NaN strictly before their
    base period, even though full statistical convergence takes longer
    (that longer margin is the warmup bookkeeping value, not a hard NaN
    boundary).
    """
    df = make_df(200)
    table = compute_regime_features(df)
    assert table["atr_14"].iloc[:13].isna().all()
    assert table["adx_14"].iloc[:13].isna().all()


def test_max_feature_warmup_bars_matches_registry_max():
    assert max_feature_warmup_bars() == max(FEATURE_WARMUP_BARS.values())


def test_realized_volatility_matches_manual_calculation():
    closes = [100, 102, 101, 105, 103, 108, 107, 110]
    df = pd.DataFrame({"close": closes})
    vol = realized_volatility(df["close"], window=4)

    returns = pd.Series(closes).pct_change()
    expected_at_last = returns.iloc[-4:].std(ddof=0)
    assert vol.iloc[-1] == pytest.approx(expected_at_last)
    assert vol.iloc[:3].isna().all()  # window=4 needs 4 return obs -> valid from index 4


def test_kaufman_efficiency_ratio_is_one_for_straight_move():
    # Monotonically increasing by a constant step: net change == path length.
    closes = pd.Series([100 + i for i in range(30)], dtype=float)
    er = kaufman_efficiency_ratio(closes, window=10)
    assert er.iloc[-1] == pytest.approx(1.0)


def test_kaufman_efficiency_ratio_is_near_zero_for_round_trip_chop():
    # Goes up then back down to the same level within the window: net change ~ 0.
    up = [100 + i for i in range(10)]
    down = [109 - i for i in range(10)]
    closes = pd.Series(up + down[1:], dtype=float)
    er = kaufman_efficiency_ratio(closes, window=18)
    assert er.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_directional_persistence_is_one_for_strictly_monotonic_series():
    closes = pd.Series([100 + i for i in range(50)], dtype=float)
    persistence = directional_persistence(closes, window=20)
    assert persistence.iloc[-1] == pytest.approx(1.0)


def test_feature_values_at_never_uses_a_future_row():
    """feature_values_at must only match a feature row at or before the
    query timestamp -- never a row that comes after it.
    """
    df = make_df(500)
    features = compute_regime_features(df)

    # Query at a timestamp strictly between two feature rows.
    query_ts = pd.Series([df["timestamp"].iloc[300] + pd.Timedelta(minutes=30)])
    matched = feature_values_at(features, query_ts)

    assert matched["timestamp"].iloc[0] <= query_ts.iloc[0]
    # And it must match exactly the row at index 300 (the last one <= query).
    expected_row = features.iloc[300]
    for col in ["realized_vol_24h", "atr_14"]:
        if pd.isna(expected_row[col]):
            assert pd.isna(matched[col].iloc[0])
        else:
            assert matched[col].iloc[0] == pytest.approx(expected_row[col])


def test_feature_values_at_preserves_query_order():
    df = make_df(500)
    features = compute_regime_features(df)
    query_ts = pd.Series(
        [df["timestamp"].iloc[400], df["timestamp"].iloc[100], df["timestamp"].iloc[300]]
    )
    matched = feature_values_at(features, query_ts)
    assert list(matched["timestamp"]) == list(query_ts)
