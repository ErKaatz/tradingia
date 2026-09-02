"""Tests for Phase 4A per-trade MAE/MFE and cost breakdown reporting."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine import BacktestEngine
from src.research.short_horizon_costs import SHORT_HORIZON_SCENARIO_BY_NAME
from src.research.short_horizon_mae_mfe import build_trade_level_report
from src.strategies.base import FLAT, LONG


def make_df(opens, highs=None, lows=None):
    n = len(opens)
    highs = highs or opens
    lows = lows or opens
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": opens, "high": highs, "low": lows, "close": opens, "volume": [10.0] * n,
        }
    )


def test_empty_trades_produces_empty_dataframe_with_expected_columns():
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]
    report = build_trade_level_report([], make_df([100, 100]), scenario)
    assert report.empty
    for col in ["mae_pct", "mfe_pct", "fee_cost", "spread_cost", "slippage_cost", "gross_return_pct"]:
        assert col in report.columns


def test_trade_level_report_has_required_columns():
    df = make_df([100, 100, 200, 200], highs=[100, 100, 250, 200], lows=[100, 100, 190, 200])
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)

    report = build_trade_level_report(result.trades, df, scenario)
    required = [
        "mae_pct", "mfe_pct", "hours_to_mae", "hours_to_mfe", "duration_hours",
        "net_pnl", "gross_pnl", "return_pct", "gross_return_pct",
        "fee_cost", "spread_cost", "slippage_cost", "winner",
    ]
    for col in required:
        assert col in report.columns
    assert len(report) == len(result.trades)


def test_fee_and_spread_slippage_costs_sum_to_total_cost():
    df = make_df([100, 100, 200, 200])
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["C_conservative"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)
    report = build_trade_level_report(result.trades, df, scenario)

    row = report.iloc[0]
    gross_notional_return = row["gross_return_pct"] * result.trades[0].entry_notional
    net_pnl = row["net_pnl"]
    total_cost = row["fee_cost"] + row["spread_cost"] + row["slippage_cost"]
    assert gross_notional_return - total_cost == pytest.approx(net_pnl, rel=1e-6)


def test_spread_and_slippage_split_proportional_to_scenario_components():
    df = make_df([100, 100, 200, 200])
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["D_severe"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)
    report = build_trade_level_report(result.trades, df, scenario)

    row = report.iloc[0]
    total = row["spread_cost"] + row["slippage_cost"]
    expected_spread_fraction = scenario.half_spread / (scenario.half_spread + scenario.slippage)
    assert row["spread_cost"] / total == pytest.approx(expected_spread_fraction, rel=1e-6)


def test_mae_mfe_values_are_reasonable_bounds():
    df = make_df(
        [100, 100, 100, 100],
        highs=[100, 100, 130, 100],
        lows=[100, 100, 90, 100],
    )
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]
    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)
    report = build_trade_level_report(result.trades, df, scenario)

    row = report.iloc[0]
    assert row["mfe_pct"] > 0  # the high=130 excursion happened during the trade
    assert row["mae_pct"] < 0  # the low=90 excursion happened during the trade
