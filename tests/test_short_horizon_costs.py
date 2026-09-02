"""Tests for the Phase 4A short-horizon cost/execution model."""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine import BacktestEngine
from src.research.short_horizon_costs import (
    SHORT_HORIZON_COST_SCENARIOS,
    SHORT_HORIZON_SCENARIO_BY_NAME,
    ShortHorizonCostScenario,
    build_cost_report,
)
from src.strategies.base import FLAT, LONG


def make_df(opens):
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": opens,
            "high": opens,
            "low": opens,
            "close": opens,
            "volume": [1.0] * n,
        }
    )


def test_four_scenarios_named_optimistic_base_conservative_severe():
    names = [s.name for s in SHORT_HORIZON_COST_SCENARIOS]
    assert names == [
        "A_optimistic_but_realistic",
        "B_base",
        "C_conservative",
        "D_severe",
    ]


def test_scenarios_strictly_increasing_in_cost():
    """Each scenario must cost at least as much as the previous one on
    every cost dimension -- Task 1's ordering (optimistic < base <
    conservative < severe) must actually hold in the numbers, not just the
    names.
    """
    scenarios = SHORT_HORIZON_COST_SCENARIOS
    for prev, curr in zip(scenarios, scenarios[1:]):
        assert curr.trading_fee >= prev.trading_fee
        assert curr.half_spread >= prev.half_spread
        assert curr.slippage >= prev.slippage
        assert curr.effective_slippage > prev.effective_slippage


def test_effective_slippage_combines_spread_and_slippage():
    scenario = ShortHorizonCostScenario(name="test", trading_fee=0.001, half_spread=0.0003, slippage=0.0002)
    assert scenario.effective_slippage == pytest.approx(0.0005)


def test_to_backtest_config_uses_effective_slippage():
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]
    cfg = scenario.to_backtest_config(initial_capital=5000)
    assert cfg.trading_fee == scenario.trading_fee
    assert cfg.slippage == pytest.approx(scenario.effective_slippage)
    assert cfg.initial_capital == 5000


def test_gross_return_exceeds_net_return_when_costs_positive():
    df = make_df([100, 100, 200, 200])
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)

    report = build_cost_report(scenario, result, years_evaluated=1.0)
    assert report.gross_return > report.net_return
    assert report.cost_drag == pytest.approx(report.gross_return - report.net_return)
    assert report.cost_drag > 0


def test_cost_report_recovers_raw_price_algebraically():
    """With zero trading fee and known slippage, gross_pnl computed by the
    cost report must match a hand-calculated raw-price PnL exactly.
    """
    df = make_df([100, 100, 100, 200])
    signals = pd.Series([FLAT, LONG, LONG, FLAT])
    # target_position = signals.shift(1) -> [FLAT, FLAT, LONG, LONG]
    # Enter at bar2's open (100), force-closed at bar3's open (200) since
    # target flips to FLAT there... actually exits at bar3 open per engine.
    scenario = ShortHorizonCostScenario(name="zero_fee", trading_fee=0.0, half_spread=0.0, slippage=0.01)

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)

    report = build_cost_report(scenario, result, years_evaluated=1.0)
    trade = result.trades[0]
    # Entry at bar2's open=100 with 1% slippage -> fill=101; raw open=100.
    # Exit at bar3's open=200 with 1% slippage -> fill=198; raw open=200.
    assert trade.entry_price == pytest.approx(101.0)
    assert trade.exit_price == pytest.approx(198.0)
    expected_raw_gross_pnl = (200 - 100) * trade.size_base
    assert report.gross_expectancy == pytest.approx(expected_raw_gross_pnl)


def test_cost_report_zero_trades_does_not_divide_by_zero():
    df = make_df([100, 100, 100, 100])
    signals = pd.Series([FLAT, FLAT, FLAT, FLAT])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)
    report = build_cost_report(scenario, result, years_evaluated=1.0)

    assert report.num_trades == 0
    assert report.cost_per_trade == 0.0
    assert report.gross_expectancy == 0.0
    assert report.net_expectancy == 0.0


def test_trades_per_year_and_month_scale_correctly():
    df = make_df([100, 100, 200, 200, 100, 100, 200, 200])
    signals = pd.Series([FLAT, LONG, FLAT, LONG, FLAT, LONG, FLAT, LONG])
    scenario = SHORT_HORIZON_SCENARIO_BY_NAME["B_base"]

    engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
    result = engine.run(df, signals)
    report = build_cost_report(scenario, result, years_evaluated=2.0)

    assert report.trades_per_year == pytest.approx(report.num_trades / 2.0)
    assert report.trades_per_month == pytest.approx(report.trades_per_year / 12.0)


def test_severe_scenario_reduces_net_return_relative_to_optimistic():
    """The same signal sequence must do worse (or no better) net of costs
    under D_severe than under A_optimistic_but_realistic."""
    df = make_df([100, 105, 95, 110, 90, 115, 85, 120])
    signals = pd.Series([FLAT, LONG, FLAT, LONG, FLAT, LONG, FLAT, LONG])

    returns = {}
    for scenario in [SHORT_HORIZON_SCENARIO_BY_NAME["A_optimistic_but_realistic"], SHORT_HORIZON_SCENARIO_BY_NAME["D_severe"]]:
        engine = BacktestEngine(scenario.to_backtest_config(initial_capital=1000))
        result = engine.run(df, signals)
        returns[scenario.name] = result.final_equity

    assert returns["D_severe"] <= returns["A_optimistic_but_realistic"]
