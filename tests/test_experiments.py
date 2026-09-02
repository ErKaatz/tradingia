"""Integration-style tests for the experiment runner: given a small cached
synthetic dataset, running an experiment should produce train/validation/test
results and a reproducible results folder.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.experiments.config import ExperimentConfig
from src.experiments.runner import run_experiment, save_experiment


@pytest.fixture
def synthetic_raw_dir(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    n = 200
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": [100 + i * 0.1 for i in range(n)],
            "high": [100 + i * 0.1 + 0.5 for i in range(n)],
            "low": [100 + i * 0.1 - 0.5 for i in range(n)],
            "close": [100 + i * 0.1 for i in range(n)],
            "volume": [1.0] * n,
        }
    )
    df.to_parquet(raw_dir / "BTCUSDT_1h.parquet", index=False)
    return raw_dir


def make_config(strategy="sma_cross", params=None):
    return ExperimentConfig.from_dict(
        {
            "strategy": strategy,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "capital": {"initial": 10000},
            "fees": {"trading_fee": 0.001, "slippage": 0.0002},
            "strategy_params": params or {"fast": 5, "slow": 20},
            "data_split": {"train": 0.6, "validation": 0.2, "test": 0.2},
        }
    )


def test_run_experiment_produces_all_splits(synthetic_raw_dir):
    config = make_config()
    results = run_experiment(config, raw_dir=synthetic_raw_dir)
    assert set(results.keys()) == {"train", "validation", "test"}
    for split_result in results.values():
        assert split_result.result.final_equity > 0
        assert "total_return" in split_result.metrics


def test_run_experiment_is_deterministic(synthetic_raw_dir):
    config = make_config()
    results1 = run_experiment(config, raw_dir=synthetic_raw_dir)
    results2 = run_experiment(config, raw_dir=synthetic_raw_dir)
    for split in ["train", "validation", "test"]:
        assert results1[split].metrics["total_return"] == results2[split].metrics["total_return"]
        assert results1[split].metrics["num_trades"] == results2[split].metrics["num_trades"]


def test_save_experiment_creates_expected_files(tmp_path, synthetic_raw_dir):
    config = make_config()
    results = run_experiment(config, raw_dir=synthetic_raw_dir)
    df = pd.read_parquet(synthetic_raw_dir / "BTCUSDT_1h.parquet")

    exp_dir = save_experiment(config, results, df, results_dir=tmp_path / "results")

    assert (exp_dir / "config.json").exists()
    assert (exp_dir / "metrics.json").exists()
    assert (exp_dir / "summary.md").exists()
    for split in ["train", "validation", "test"]:
        assert (exp_dir / split / "trades.csv").exists()
        assert (exp_dir / split / "equity.csv").exists()
        assert (exp_dir / split / "metrics.json").exists()

    with open(exp_dir / "config.json") as f:
        saved_config = json.load(f)
    assert saved_config["strategy"] == "sma_cross"
    assert "dataset_hash" in saved_config
    assert saved_config["data_period"]["num_candles"] == len(df)


def test_train_validation_test_are_non_overlapping_periods(synthetic_raw_dir):
    config = make_config()
    results = run_experiment(config, raw_dir=synthetic_raw_dir)

    train_end = results["train"].result.equity_curve["timestamp"].max()
    val_start = results["validation"].result.equity_curve["timestamp"].min()
    val_end = results["validation"].result.equity_curve["timestamp"].max()
    test_start = results["test"].result.equity_curve["timestamp"].min()

    assert train_end < val_start
    assert val_end < test_start
