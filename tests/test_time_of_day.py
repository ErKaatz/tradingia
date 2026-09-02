"""Tests for the time-of-day descriptive analysis and its multiple-testing
correction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.time_of_day import (
    N_HOURS,
    build_time_of_day_report,
    flag_significant_hours,
    report_to_dict,
)


def make_df(n_days=60, seed=3):
    import random

    rng = random.Random(seed)
    n = n_days * 24
    closes = [30000.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] * (1 + rng.uniform(-0.01, 0.01))))
    highs = [c * 1.002 for c in closes]
    lows = [c * 0.998 for c in closes]
    volumes = [rng.uniform(50, 150) for _ in closes]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": closes, "high": highs, "low": lows, "close": closes, "volume": volumes,
        }
    )


def test_per_hour_table_has_24_rows():
    df = make_df()
    report = build_time_of_day_report(df)
    assert len(report.per_hour) == N_HOURS
    assert set(report.per_hour["hour_utc"]) == set(range(24))


def test_per_hour_stats_are_descriptive_only_no_signal_column():
    df = make_df()
    report = build_time_of_day_report(df)
    forbidden_cols = {"signal", "entry", "exit", "position", "strategy"}
    assert forbidden_cols.isdisjoint(set(report.per_hour.columns))


def test_bonferroni_alpha_is_target_over_24():
    df = make_df()
    report = build_time_of_day_report(df, target_alpha=0.05)
    assert report.bonferroni_alpha == pytest.approx(0.05 / 24)


def test_no_significant_hours_on_pure_noise_data():
    """With genuinely random (i.i.d.) hourly returns, the Bonferroni-
    corrected test should essentially never flag a hour as significant --
    this guards against the module being too liberal.
    """
    import random

    rng = random.Random(42)
    n = 24 * 300  # 300 days, i.i.d. returns regardless of hour
    closes = [30000.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] * (1 + rng.gauss(0, 0.01))))
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
            "open": closes, "high": [c * 1.002 for c in closes], "low": [c * 0.998 for c in closes],
            "close": closes, "volume": [100.0] * n,
        }
    )
    report = build_time_of_day_report(df)
    assert len(report.significant_hours) == 0


def test_uncorrected_scan_would_flag_more_than_corrected_scan():
    """Sanity check that the Bonferroni correction actually does something:
    using target_alpha directly (uncorrected) as the flagging threshold
    should never flag FEWER hours than the corrected version.
    """
    df = make_df(n_days=120, seed=7)
    corrected_report = build_time_of_day_report(df, target_alpha=0.05)

    # Recompute with no correction (alpha divided by 1 instead of 24) by
    # calling the internal flagging function directly.
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["hour"] = work["timestamp"].dt.hour
    work["bar_return"] = work["close"].pct_change()
    return_groups = {h: work[work["hour"] == h]["bar_return"].dropna() for h in range(24)}
    uncorrected_significant = flag_significant_hours(work, return_groups, bonferroni_alpha=0.05)

    assert len(uncorrected_significant) >= len(corrected_report.significant_hours)


def test_kruskal_wallis_reported_when_enough_data():
    df = make_df(n_days=60)
    report = build_time_of_day_report(df)
    assert report.kruskal_wallis_statistic is not None
    assert report.kruskal_wallis_pvalue is not None
    assert 0.0 <= report.kruskal_wallis_pvalue <= 1.0


def test_kruskal_wallis_none_with_insufficient_data():
    n = 10  # far too few bars to populate 24 hourly groups with >=30 each
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
            "close": [100.0] * n, "volume": [10.0] * n,
        }
    )
    report = build_time_of_day_report(df)
    assert report.kruskal_wallis_statistic is None
    assert report.kruskal_wallis_pvalue is None


def test_report_to_dict_carries_multiple_testing_note():
    df = make_df()
    report = build_time_of_day_report(df)
    d = report_to_dict(report)
    assert "multiple-testing" in d["note"] or "Bonferroni" in d["note"]
    assert d["bonferroni_alpha"] == report.bonferroni_alpha
