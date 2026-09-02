"""Tests for the backtest engine using small synthetic datasets where the
expected outcome is known by hand-calculation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.strategies.base import FLAT, LONG


def make_df(opens, highs, lows, closes, volumes=None):
    n = len(opens)
    volumes = volumes or [1.0] * n
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_signal_executes_next_bar_open_no_lookahead():
    # Signal flips to LONG at bar 1's close. Entry must happen at bar 2's
    # open, NOT bar 1's close and NOT bar 2's close.
    df = make_df(
        opens=[100, 100, 110, 130],
        highs=[100, 100, 120, 130],
        lows=[100, 100, 110, 130],
        closes=[100, 100, 120, 130],
    )
    signals = pd.Series([FLAT, LONG, LONG, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 110  # bar index 2's open, not bar 1's close (100) or bar 2's close (120)


def test_no_fees_no_slippage_pnl_matches_price_move():
    df = make_df(
        opens=[100, 100, 200],
        highs=[100, 100, 200],
        lows=[100, 100, 200],
        closes=[100, 100, 200],
    )
    signals = pd.Series([LONG, LONG, LONG])
    # target_position = signals.shift(1) -> [FLAT, LONG, LONG]
    # Enter at bar1 open=100, held through bar2, force-closed at bar2 close=200.

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == 100
    assert trade.exit_price == 200
    # Bought with full 1000 capital at 100 -> 10 units. Sold at 200 -> 2000.
    assert trade.size_base == pytest.approx(10.0)
    assert trade.gross_pnl == pytest.approx(1000.0)
    assert trade.net_pnl == pytest.approx(1000.0)
    assert result.final_equity == pytest.approx(2000.0)


def test_fees_reduce_net_pnl_correctly():
    df = make_df(
        opens=[100, 100, 200],
        highs=[100, 100, 200],
        lows=[100, 100, 200],
        closes=[100, 100, 200],
    )
    signals = pd.Series([LONG, LONG, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.01, slippage=0.0))
    result = engine.run(df, signals)

    trade = result.trades[0]
    # Entry: notional=1000, fee=10, size_base=(1000-10)/100=9.9
    assert trade.size_base == pytest.approx(9.9)
    assert trade.entry_fee == pytest.approx(10.0)
    # Exit: proceeds = 9.9 * 200 = 1980, fee = 19.8
    assert trade.exit_fee == pytest.approx(19.8)
    net_proceeds = 1980 - 19.8
    expected_net_pnl = net_proceeds - 1000  # entry_notional was 1000
    assert trade.net_pnl == pytest.approx(expected_net_pnl)
    assert result.final_equity == pytest.approx(net_proceeds)


def test_slippage_worsens_entry_and_exit_price():
    df = make_df(
        opens=[100, 100, 200],
        highs=[100, 100, 200],
        lows=[100, 100, 200],
        closes=[100, 100, 200],
    )
    signals = pd.Series([LONG, LONG, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.01))
    result = engine.run(df, signals)

    trade = result.trades[0]
    # Buy fill worse (higher) than raw open: 100 * 1.01 = 101
    assert trade.entry_price == pytest.approx(101.0)
    # Sell fill worse (lower) than raw open at force-close on last close: 200 * 0.99 = 198
    assert trade.exit_price == pytest.approx(198.0)


def test_open_position_force_closed_at_end():
    df = make_df(
        opens=[100, 100, 150],
        highs=[100, 100, 150],
        lows=[100, 100, 150],
        closes=[100, 100, 150],
    )
    signals = pd.Series([LONG, LONG, LONG])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert len(result.trades) == 1
    assert result.trades[0].exit_time == df["timestamp"].iloc[-1]
    assert result.equity_curve["position"].iloc[-1] == FLAT


def test_flat_the_whole_time_produces_no_trades_and_flat_equity():
    df = make_df(
        opens=[100, 105, 95],
        highs=[100, 105, 95],
        lows=[100, 105, 95],
        closes=[100, 105, 95],
    )
    signals = pd.Series([FLAT, FLAT, FLAT])

    engine = BacktestEngine(BacktestConfig(initial_capital=1000))
    result = engine.run(df, signals)

    assert len(result.trades) == 0
    assert (result.equity_curve["equity"] == 1000).all()
    assert result.final_equity == 1000


def test_multiple_round_trips_produce_multiple_trades():
    # LONG, then FLAT, then LONG again, then FLAT.
    df = make_df(
        opens=[100, 110, 120, 90, 80, 100],
        highs=[100, 110, 120, 90, 80, 100],
        lows=[100, 110, 120, 90, 80, 100],
        closes=[100, 110, 120, 90, 80, 100],
    )
    signals = pd.Series([LONG, LONG, FLAT, FLAT, LONG, LONG])
    # shift(1) target: [FLAT, LONG, LONG, FLAT, FLAT, LONG]
    # bar1: enter at open=110
    # bar3: exit at open=90
    # bar5: enter at open=100, then force-closed at close=100 (no move)

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals)

    assert len(result.trades) == 2
    assert result.trades[0].entry_price == 110
    assert result.trades[0].exit_price == 90
    assert result.trades[1].entry_price == 100
    assert result.trades[1].exit_price == 100


def test_mismatched_lengths_raise():
    df = make_df(opens=[100, 100], highs=[100, 100], lows=[100, 100], closes=[100, 100])
    signals = pd.Series([LONG, LONG, LONG])
    engine = BacktestEngine()
    with pytest.raises(ValueError):
        engine.run(df, signals)


def test_too_short_dataframe_raises():
    df = make_df(opens=[100], highs=[100], lows=[100], closes=[100])
    signals = pd.Series([LONG])
    engine = BacktestEngine()
    with pytest.raises(ValueError):
        engine.run(df, signals)
