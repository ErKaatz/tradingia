"""Tests for time-aware annualized return (correct under data gaps) and the
explicit MAR-based Sortino ratio definition.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.backtesting.engine import BacktestResult
from src.metrics.metrics import (
    TRADING_PERIODS_PER_YEAR,
    annualized_return,
    elapsed_years,
    sharpe_ratio,
    sortino_ratio,
    volatility,
)


def make_result(timestamps, equity_values, positions=None):
    n = len(timestamps)
    positions = positions or [1] * n
    equity_curve = pd.DataFrame(
        {"timestamp": timestamps, "equity": equity_values, "position": positions}
    )
    return BacktestResult(
        equity_curve=equity_curve,
        trades=[],
        initial_capital=equity_values[0],
        final_equity=equity_values[-1],
    )


def test_elapsed_years_matches_wall_clock_span():
    timestamps = pd.date_range("2024-01-01", periods=366 * 24, freq="h", tz="UTC")  # exactly 1 year of hours (leap)
    result = make_result(timestamps, [1000.0] * len(timestamps))
    years = elapsed_years(result)
    expected = (timestamps[-1] - timestamps[0]).total_seconds() / (365 * 24 * 3600)
    assert years == pytest.approx(expected)


def test_annualized_return_unaffected_by_missing_bars_when_time_span_is_same():
    # Same start/end timestamps and same total return, but one series has
    # bars removed from the middle (a gap). Annualized return must be
    # identical because it's driven by elapsed wall-clock time, not bar
    # count.
    full_timestamps = pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC")
    full_equity = [1000.0 + i for i in range(100)]
    full_result = make_result(full_timestamps, full_equity)

    # Remove interior bars but keep first/last timestamp and total return
    # identical.
    gappy_idx = [0, 1, 2, 50, 98, 99]
    gappy_timestamps = full_timestamps[gappy_idx]
    gappy_equity = [full_equity[i] for i in gappy_idx]
    gappy_result = make_result(gappy_timestamps, gappy_equity)

    full_ann = annualized_return(full_result, "1h")
    gappy_ann = annualized_return(gappy_result, "1h")

    assert full_ann == pytest.approx(gappy_ann)


def test_annualized_return_known_value_one_year_doubling():
    timestamps = [pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")]
    result = make_result(timestamps, [1000.0, 2000.0])
    ann = annualized_return(result, "1d")
    # ~1 year elapsed, doubled capital -> annualized return ~= 100%
    assert ann == pytest.approx(1.0, rel=0.01)


def test_annualized_return_none_with_single_bar():
    timestamps = [pd.Timestamp("2024-01-01", tz="UTC")]
    result = make_result(timestamps, [1000.0])
    assert annualized_return(result, "1h") is None


def test_annualized_return_total_wipeout_is_negative_one():
    timestamps = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
    result = make_result(timestamps, [1000.0] * 9 + [0.0])
    assert annualized_return(result, "1h") == -1.0


def _manual_sortino(returns, mar_period, periods_per_year):
    excess = [r - mar_period for r in returns]
    downside = [min(e, 0.0) for e in excess]
    downside_dev = math.sqrt(sum(d**2 for d in downside) / len(downside))
    mean_excess = sum(excess) / len(excess)
    return (mean_excess / downside_dev) * math.sqrt(periods_per_year)


def test_sortino_matches_manual_calculation():
    # Hand-constructed equity curve with known bar returns.
    equity = [1000.0, 1010.0, 1000.0, 1030.0, 1000.0, 1050.0]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, equity)

    returns = pd.Series(equity).pct_change().dropna().tolist()
    expected = _manual_sortino(returns, mar_period=0.0, periods_per_year=365 * 24)

    actual = sortino_ratio(result, "1h", minimum_acceptable_return=0.0)
    assert actual == pytest.approx(expected)


def test_sortino_uses_full_sample_size_not_just_losing_bars():
    # Mostly winning bars with one loss: the "std of negative returns only"
    # (buggy) formula would divide by 1; the correct RMS-over-N formula
    # divides by the full count of return observations. This test would
    # pass under either formula for the ratio's SIGN, but distinguishes
    # magnitude — verified against the manual reference implementation.
    equity = [1000, 1010, 1020, 1030, 1015, 1040, 1055]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, [float(e) for e in equity])

    returns = pd.Series(equity).pct_change().dropna().tolist()
    expected = _manual_sortino(returns, mar_period=0.0, periods_per_year=365 * 24)
    actual = sortino_ratio(result, "1h")
    assert actual == pytest.approx(expected)


def test_sortino_none_when_no_downside_relative_to_mar():
    # Strictly increasing equity with MAR=0: every bar beats the MAR, so
    # downside deviation is 0 -> ratio undefined (None), not infinite.
    equity = [1000.0 * (1.01**i) for i in range(10)]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, equity)
    assert sortino_ratio(result, "1h") is None


def test_sortino_respects_custom_mar():
    # A gently rising equity curve beats MAR=0 every bar (Sortino undefined)
    # but should show downside once MAR is raised above its actual growth
    # rate.
    equity = [1000.0 * (1.0001**i) for i in range(20)]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, equity)

    assert sortino_ratio(result, "1h", minimum_acceptable_return=0.0) is None
    high_mar_sortino = sortino_ratio(result, "1h", minimum_acceptable_return=10.0)
    assert high_mar_sortino is not None


def test_periods_per_year_override_bypasses_crypto_table_for_unknown_timeframe():
    # An FX-shaped timeframe with no entry in TRADING_PERIODS_PER_YEAR must
    # not silently fall back to a crypto (24/7) assumption: without an
    # explicit override it returns None, and with one it uses exactly that
    # value instead of guessing.
    equity = [1000, 1010, 1020, 1030, 1015, 1040, 1055]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, [float(e) for e in equity])

    assert volatility(result, "fx_1h") is None
    assert sharpe_ratio(result, "fx_1h") is None
    assert sortino_ratio(result, "fx_1h") is None

    fx_periods_per_year = 252 * 24  # illustrative FX trading-day convention
    assert volatility(result, "fx_1h", periods_per_year=fx_periods_per_year) is not None
    assert sharpe_ratio(result, "fx_1h", periods_per_year=fx_periods_per_year) is not None
    assert sortino_ratio(result, "fx_1h", periods_per_year=fx_periods_per_year) is not None


def test_periods_per_year_override_matches_explicit_crypto_table_lookup():
    # For a known crypto timeframe, passing the table's own value explicitly
    # must reproduce the default (no-override) result exactly.
    equity = [1000, 1010, 1020, 1030, 1015, 1040, 1055]
    timestamps = pd.date_range("2024-01-01", periods=len(equity), freq="h", tz="UTC")
    result = make_result(timestamps, [float(e) for e in equity])

    default_sortino = sortino_ratio(result, "1h")
    overridden_sortino = sortino_ratio(
        result, "1h", periods_per_year=TRADING_PERIODS_PER_YEAR["1h"]
    )
    assert overridden_sortino == pytest.approx(default_sortino)
