"""Tests for the engine's input validation: rejecting malformed OHLCV data
and malformed signals before any simulation happens.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.strategies.base import FLAT, LONG


def make_df(n=5):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1.0] * n,
        }
    )


def test_rejects_invalid_ohlcv():
    df = make_df()
    df.loc[1, "high"] = 10.0  # impossible: high below open/close/low
    signals = pd.Series([FLAT] * len(df))
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="high"):
        engine.run(df, signals)


def test_rejects_signal_values_outside_flat_long():
    df = make_df()
    signals = pd.Series([FLAT, LONG, 2, FLAT, LONG])  # 2 is not a valid state
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="outside"):
        engine.run(df, signals)


def test_rejects_negative_signal_value():
    df = make_df()
    signals = pd.Series([FLAT, -1, LONG, FLAT, LONG])
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="outside"):
        engine.run(df, signals)


def test_rejects_nan_signal():
    df = make_df()
    signals = pd.Series([FLAT, LONG, np.nan, FLAT, LONG])
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="NaN"):
        engine.run(df, signals)


def test_rejects_mismatched_signal_length():
    df = make_df(n=5)
    signals = pd.Series([FLAT, LONG, FLAT])
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="length"):
        engine.run(df, signals)


def test_rejects_fractional_signal_value():
    df = make_df()
    signals = pd.Series([FLAT, 0.5, LONG, FLAT, LONG])
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="fractional"):
        engine.run(df, signals)


def test_accepts_float_series_with_only_whole_flat_long_values():
    df = make_df()
    signals = pd.Series([0.0, 1.0, 1.0, 0.0, 1.0])
    engine = BacktestEngine(BacktestConfig(trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)  # must not raise
    assert result.final_equity > 0


def test_rejects_out_of_range_evaluation_start():
    df = make_df(n=5)
    signals = pd.Series([FLAT] * 5)
    engine = BacktestEngine()
    with pytest.raises(ValueError, match="evaluation_start"):
        engine.run(df, signals, evaluation_start=10)
