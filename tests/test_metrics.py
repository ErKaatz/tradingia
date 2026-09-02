"""Tests for metrics computed from a BacktestResult, using hand-verifiable
synthetic equity curves and trade lists.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine import BacktestResult, Trade
from src.metrics.metrics import (
    max_drawdown,
    market_exposure,
    total_return,
    trade_stats,
)


def make_result(equity_values, positions, trades=None, initial_capital=1000.0):
    n = len(equity_values)
    equity_curve = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "equity": equity_values,
            "position": positions,
        }
    )
    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades or [],
        initial_capital=initial_capital,
        final_equity=equity_values[-1],
    )


def test_total_return_simple():
    result = make_result([1000, 1100, 1200], [0, 1, 1])
    assert total_return(result) == pytest.approx(0.2)


def test_max_drawdown_known_sequence():
    # Peak at 1200 (bar index 2), trough at 900 (bar index 4) -> -25% dd.
    equity = [1000, 1200, 1100, 1000, 900, 950]
    result = make_result(equity, [1] * len(equity))
    dd = max_drawdown(result)
    assert dd.max_drawdown_pct == pytest.approx((900 - 1200) / 1200)
    # In drawdown (below running peak of 1200) at indices 2,3,4,5 -> duration 4
    assert dd.max_drawdown_duration_bars == 4


def test_max_drawdown_zero_when_monotonic_increase():
    equity = [1000, 1100, 1200, 1300]
    result = make_result(equity, [1] * len(equity))
    dd = max_drawdown(result)
    assert dd.max_drawdown_pct == pytest.approx(0.0)
    assert dd.max_drawdown_duration_bars == 0


def test_market_exposure_half_the_time():
    result = make_result([1000, 1000, 1000, 1000], [0, 0, 1, 1])
    assert market_exposure(result) == pytest.approx(0.5)


def test_market_exposure_zero_trades():
    result = make_result([1000, 1000], [0, 0])
    assert market_exposure(result) == pytest.approx(0.0)


def _trade(net_pnl):
    ts = pd.Timestamp("2024-01-01", tz="UTC")
    return Trade(
        entry_time=ts,
        entry_price=100.0,
        exit_time=ts,
        exit_price=100.0,
        size_base=1.0,
        entry_notional=100.0,
        gross_pnl=net_pnl,
        entry_fee=0.0,
        exit_fee=0.0,
        net_pnl=net_pnl,
    )


def test_trade_stats_known_wins_and_losses():
    trades = [_trade(100), _trade(-50), _trade(50), _trade(-50)]
    result = make_result([1000, 1000], [0, 0], trades=trades)
    stats = trade_stats(result)

    assert stats.num_trades == 4
    assert stats.win_rate == pytest.approx(0.5)
    assert stats.average_win == pytest.approx(75.0)  # (100+50)/2
    assert stats.average_loss == pytest.approx(-50.0)  # (-50-50)/2
    assert stats.expectancy == pytest.approx((100 - 50 + 50 - 50) / 4)
    # gross_profit=150, gross_loss=100 -> profit_factor=1.5
    assert stats.profit_factor == pytest.approx(1.5)


def test_trade_stats_zero_trades_returns_none_fields():
    result = make_result([1000, 1000], [0, 0], trades=[])
    stats = trade_stats(result)
    assert stats.num_trades == 0
    assert stats.win_rate is None
    assert stats.average_win is None
    assert stats.average_loss is None
    assert stats.expectancy is None
    assert stats.profit_factor is None


def test_trade_stats_no_losses_profit_factor_none():
    trades = [_trade(100), _trade(50)]
    result = make_result([1000, 1000], [0, 0], trades=trades)
    stats = trade_stats(result)
    assert stats.profit_factor is None  # division by zero gross_loss avoided
