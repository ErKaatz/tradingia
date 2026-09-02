"""Tests for OHLCV structural validation."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.validation import validate_ohlcv


def make_df(n=5, freq="h"):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC"),
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [10.0] * n,
        }
    )


def test_valid_dataframe_passes():
    df = make_df()
    result = validate_ohlcv(df, timeframe="1h")
    assert result.is_valid
    assert result.errors == []


def test_missing_column_is_error():
    df = make_df().drop(columns=["volume"])
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("volume" in e for e in result.errors)


def test_nan_in_required_field_is_error():
    df = make_df()
    df.loc[2, "close"] = float("nan")
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("close" in e and "NaN" in e for e in result.errors)


def test_non_increasing_timestamps_is_error():
    df = make_df()
    df.loc[2, "timestamp"] = df.loc[1, "timestamp"]  # duplicate, not increasing
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("increasing" in e for e in result.errors)


def test_duplicate_timestamps_is_error():
    df = make_df()
    df.loc[3, "timestamp"] = df.loc[1, "timestamp"]
    df = df.sort_values("timestamp").reset_index(drop=True)
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("increasing" in e for e in result.errors)


def test_non_positive_price_is_error():
    df = make_df()
    df.loc[1, "open"] = 0.0
    df.loc[2, "close"] = -5.0
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("open" in e for e in result.errors)
    assert any("close" in e for e in result.errors)


def test_negative_volume_is_error():
    df = make_df()
    df.loc[1, "volume"] = -1.0
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("volume" in e for e in result.errors)


def test_high_below_open_close_low_is_error():
    df = make_df()
    df.loc[1, "high"] = 50.0  # far below open/close/low
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("high" in e for e in result.errors)


def test_low_above_open_close_is_error():
    df = make_df()
    df.loc[1, "low"] = 500.0  # far above open/close
    result = validate_ohlcv(df)
    assert not result.is_valid
    assert any("low" in e for e in result.errors)


def test_gap_detected_but_allowed_by_default_flag():
    df = make_df(n=5)
    # Introduce a 3-hour jump instead of the expected 1-hour step.
    df.loc[3:, "timestamp"] = df.loc[3:, "timestamp"] + pd.Timedelta(hours=3)
    result = validate_ohlcv(df, timeframe="1h", allow_gaps=True)
    assert result.is_valid
    assert result.gap_count == 1
    assert any("gap" in w for w in result.warnings)


def test_gap_rejected_when_not_allowed():
    df = make_df(n=5)
    df.loc[3:, "timestamp"] = df.loc[3:, "timestamp"] + pd.Timedelta(hours=3)
    result = validate_ohlcv(df, timeframe="1h", allow_gaps=False)
    assert not result.is_valid
    assert any("gap" in e for e in result.errors)


def test_no_gap_with_continuous_hourly_data():
    df = make_df(n=10, freq="h")
    result = validate_ohlcv(df, timeframe="1h", allow_gaps=False)
    assert result.is_valid
    assert result.gap_count == 0


def test_empty_dataframe_is_error():
    df = make_df(n=0)
    result = validate_ohlcv(df)
    assert not result.is_valid


def test_raise_if_invalid_raises_with_message():
    df = make_df()
    df.loc[1, "volume"] = -1.0
    result = validate_ohlcv(df)
    with pytest.raises(ValueError, match="volume"):
        result.raise_if_invalid()


def test_raise_if_invalid_noop_when_valid():
    df = make_df()
    result = validate_ohlcv(df)
    result.raise_if_invalid()  # must not raise
