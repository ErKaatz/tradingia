"""Property-style sanity checks for the backtest engine, expressed as plain
deterministic tests (no property-testing framework) over small synthetic
datasets. These check invariants that must hold for ANY valid input, not
just specific hand-picked numeric examples.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.strategies.base import FLAT, LONG


def make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * n,
        }
    )


def test_buy_and_sell_at_same_price_zero_cost_preserves_capital():
    # Flat price throughout, zero fees/slippage: buying and selling at the
    # same price must leave capital exactly unchanged.
    df = make_df([100, 100, 100, 100, 100])
    signals = pd.Series([FLAT, LONG, LONG, FLAT, FLAT])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert result.final_equity == pytest.approx(1000.0)
    assert np.allclose(result.equity_curve["equity"], 1000.0)


def test_increasing_fees_never_improves_result():
    df = make_df([100, 110, 90, 120, 80, 130])
    signals = pd.Series([FLAT, LONG, LONG, FLAT, LONG, LONG])

    prior_equity = None
    for fee in [0.0, 0.001, 0.005, 0.01, 0.02]:
        engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=fee, slippage=0.0))
        result = engine.run(df, signals)
        if prior_equity is not None:
            assert result.final_equity <= prior_equity + 1e-9, (
                f"increasing fee to {fee} improved final equity: "
                f"{result.final_equity} > {prior_equity}"
            )
        prior_equity = result.final_equity


def test_increasing_slippage_never_improves_result():
    df = make_df([100, 110, 90, 120, 80, 130])
    signals = pd.Series([FLAT, LONG, LONG, FLAT, LONG, LONG])

    prior_equity = None
    for slippage in [0.0, 0.0005, 0.002, 0.01, 0.03]:
        engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=slippage))
        result = engine.run(df, signals)
        if prior_equity is not None:
            assert result.final_equity <= prior_equity + 1e-9, (
                f"increasing slippage to {slippage} improved final equity: "
                f"{result.final_equity} > {prior_equity}"
            )
        prior_equity = result.final_equity


def test_always_flat_signal_produces_constant_capital():
    df = make_df([100, 150, 50, 200, 10, 300])
    signals = pd.Series([FLAT] * len(df))

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.001, slippage=0.0002))
    result = engine.run(df, signals)

    assert len(result.trades) == 0
    assert np.allclose(result.equity_curve["equity"], 1000.0)
    assert result.final_equity == pytest.approx(1000.0)


def test_buy_and_hold_strictly_increasing_prices_zero_cost_is_profitable():
    closes = [100 + i * 5 for i in range(10)]  # strictly increasing
    df = make_df(closes)
    signals = pd.Series([LONG] * len(df))

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert result.final_equity > result.initial_capital


def test_no_trade_has_exit_before_entry():
    df = make_df([100, 110, 90, 120, 80, 130, 70, 140])
    signals = pd.Series([FLAT, LONG, FLAT, LONG, FLAT, LONG, FLAT, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.001, slippage=0.0002))
    result = engine.run(df, signals)

    assert len(result.trades) > 0
    for trade in result.trades:
        assert trade.exit_time >= trade.entry_time


def test_equity_and_cash_never_nan_or_infinite():
    df = make_df([100, 110, 90, 120, 80, 130, 70, 140, 60, 150])
    signals = pd.Series([FLAT, LONG, LONG, FLAT, LONG, FLAT, LONG, LONG, FLAT, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.001, slippage=0.0002))
    result = engine.run(df, signals)

    equity = result.equity_curve["equity"]
    assert not equity.isna().any()
    assert all(math.isfinite(v) for v in equity)
    assert math.isfinite(result.final_equity)
    for trade in result.trades:
        assert math.isfinite(trade.net_pnl)
        assert math.isfinite(trade.gross_pnl)
        assert math.isfinite(trade.size_base)


def test_equity_never_negative_under_normal_fee_slippage_ranges():
    # With realistic (small) fee/slippage and a single position at a time,
    # equity should never go negative — there's no leverage to blow through
    # the account.
    df = make_df([100, 50, 25, 12, 6, 3, 1.5, 0.75])
    signals = pd.Series([LONG] * len(df))

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.001, slippage=0.0002))
    result = engine.run(df, signals)

    assert (result.equity_curve["equity"] >= 0).all()
