"""Tests for strategy signal generation, including explicit lookahead
checks: truncating the dataframe must not change past signal values.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import FLAT, LONG
from src.strategies.buy_and_hold import BuyAndHold
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import Momentum
from src.strategies.sma_cross import SmaCross


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


ALL_STRATEGIES = [
    lambda: BuyAndHold(),
    lambda: SmaCross(fast=3, slow=5),
    lambda: Momentum(lookback=3),
    lambda: MeanReversion(rsi_period=5, oversold=30, exit_rsi=50),
]


@pytest.mark.parametrize("make_strategy", ALL_STRATEGIES)
def test_no_lookahead_truncation_invariance(make_strategy):
    """The signal at row i must not depend on rows after i. We verify this
    by truncating the dataframe and checking earlier signals are unchanged.
    """
    closes = [100, 102, 101, 105, 110, 108, 95, 90, 92, 100, 115, 120, 118, 116, 130]
    df_full = make_df(closes)

    strategy = make_strategy()
    full_signals = strategy.generate_signals(df_full)

    truncate_at = 10
    df_truncated = df_full.iloc[:truncate_at].reset_index(drop=True)
    strategy2 = make_strategy()
    truncated_signals = strategy2.generate_signals(df_truncated)

    pd.testing.assert_series_equal(
        full_signals.iloc[:truncate_at].reset_index(drop=True),
        truncated_signals.reset_index(drop=True),
        check_names=False,
    )


def test_buy_and_hold_always_long():
    df = make_df([100, 90, 110, 105])
    signals = BuyAndHold().generate_signals(df)
    assert (signals == LONG).all()


def test_sma_cross_requires_fast_less_than_slow():
    with pytest.raises(ValueError):
        SmaCross(fast=10, slow=5)


def test_sma_cross_flat_until_warmup_complete():
    closes = [100, 100, 100, 100]  # slow=5 never warms up with 4 bars
    df = make_df(closes)
    signals = SmaCross(fast=2, slow=5).generate_signals(df)
    assert (signals == FLAT).all()


def test_sma_cross_goes_long_when_fast_above_slow():
    # Rising prices: fast SMA should exceed slow SMA after warmup.
    closes = [100, 101, 102, 103, 104, 105, 106, 107]
    df = make_df(closes)
    signals = SmaCross(fast=2, slow=4).generate_signals(df)
    assert signals.iloc[3] in (FLAT, LONG)  # warmup boundary, just check no crash
    assert signals.iloc[-1] == LONG


def test_momentum_long_when_price_above_lookback():
    closes = [100, 100, 100, 150]  # lookback=3: close[3]=150 > close[0]=100
    df = make_df(closes)
    signals = Momentum(lookback=3).generate_signals(df)
    assert signals.iloc[3] == LONG


def test_momentum_flat_when_price_below_lookback():
    closes = [150, 150, 150, 100]
    df = make_df(closes)
    signals = Momentum(lookback=3).generate_signals(df)
    assert signals.iloc[3] == FLAT


def test_mean_reversion_enters_on_oversold_and_exits_on_recovery():
    # Sharp decline then recovery to trigger oversold entry and RSI exit.
    closes = [100, 95, 90, 85, 80, 75, 70, 80, 90, 100, 110, 120]
    df = make_df(closes)
    signals = MeanReversion(rsi_period=5, oversold=30, exit_rsi=50).generate_signals(df)
    # At some point during the decline the strategy should go long...
    assert (signals == LONG).any()
    # ...and eventually exit back to flat during the recovery.
    long_idx = signals[signals == LONG].index
    assert long_idx.max() < len(signals) - 1 or signals.iloc[-1] == FLAT
