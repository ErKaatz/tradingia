"""Tests for Phase 4A dataset scoping and registration."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.research.short_horizon_data import (
    TIMEFRAMES,
    load_and_register,
    register_all_timeframes,
)


def test_scope_is_exactly_15m_and_1h():
    assert TIMEFRAMES == ("15m", "1h")


def test_out_of_scope_timeframe_rejected():
    for tf in ["1m", "3m", "5m", "30m", "2h", "4h", "1d"]:
        with pytest.raises(ValueError, match="out of scope"):
            load_and_register(tf)


@pytest.mark.skipif(
    not Path("data/raw/BTCUSDT_1h.parquet").exists(),
    reason="requires the real downloaded 1h dataset",
)
def test_1h_registration_matches_real_dataset():
    df, registration = load_and_register("1h")
    assert registration.timeframe == "1h"
    assert registration.num_candles == len(df)
    assert registration.duplicate_timestamps == 0
    assert registration.is_valid  # allow_gaps=True default
    assert len(registration.dataset_hash) > 0


@pytest.mark.skipif(
    not Path("data/raw/BTCUSDT_15m.parquet").exists(),
    reason="requires the real downloaded 15m dataset",
)
def test_15m_registration_matches_real_dataset():
    df, registration = load_and_register("15m")
    assert registration.timeframe == "15m"
    assert registration.num_candles == len(df)
    assert registration.duplicate_timestamps == 0
    assert registration.gap_count >= 0


@pytest.mark.skipif(
    not (Path("data/raw/BTCUSDT_1h.parquet").exists() and Path("data/raw/BTCUSDT_15m.parquet").exists()),
    reason="requires both real downloaded datasets",
)
def test_15m_has_more_candles_than_1h_over_same_range():
    df_15m, reg_15m = load_and_register("15m")
    df_1h, reg_1h = load_and_register("1h")
    assert reg_15m.num_candles > reg_1h.num_candles


@pytest.mark.skipif(
    not (Path("data/raw/BTCUSDT_1h.parquet").exists() and Path("data/raw/BTCUSDT_15m.parquet").exists()),
    reason="requires both real downloaded datasets",
)
def test_register_all_timeframes_returns_both():
    registrations = register_all_timeframes()
    assert set(registrations.keys()) == {"15m", "1h"}
    for tf, reg in registrations.items():
        assert reg.timeframe == tf
        assert reg.num_candles > 0


def test_rejects_invalid_data_when_gaps_disallowed(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    n = 20
    df = pd.DataFrame(
        {
            "timestamp": list(pd.date_range("2024-01-01", periods=10, freq="15min", tz="UTC"))
            + list(pd.date_range("2024-01-01 05:00", periods=10, freq="15min", tz="UTC")),  # gap
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1.0] * n,
        }
    )
    df.to_parquet(raw_dir / "BTCUSDT_15m.parquet", index=False)

    with pytest.raises(ValueError):
        load_and_register("15m", raw_dir=raw_dir, allow_gaps=False)
