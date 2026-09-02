"""Tests proving that warm-up context works correctly: a signal near the
start of validation/test must match the signal that would be produced by
running the strategy on the full continuous history up to that point — not
a cold/degenerate signal from treating the split in isolation, and not a
signal influenced by anything after that point either.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.splitter import SplitBounds, chronological_split, slice_with_warmup
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import Momentum
from src.strategies.sma_cross import SmaCross


def make_df(n, seed=1):
    # Deterministic pseudo-random-looking walk so SMA/RSI/momentum actually
    # vary instead of staying flat.
    import random

    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] + rng.uniform(-2, 2))
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1.0] * n,
        }
    )


STRATEGIES = [
    lambda: SmaCross(fast=5, slow=20),
    lambda: Momentum(lookback=10),
    lambda: MeanReversion(rsi_period=7, oversold=30, exit_rsi=50),
]


@pytest.mark.parametrize("make_strategy", STRATEGIES)
def test_warmup_signal_matches_continuous_history(make_strategy):
    """The signal at validation's first bar (and a few bars into it) must
    equal the signal computed by running the strategy on the full
    continuous dataset up to that same point in time.
    """
    df = make_df(300)
    strategy_for_bounds = make_strategy()
    split = chronological_split(df, train_frac=0.5, validation_frac=0.25, test_frac=0.25)

    warmup = strategy_for_bounds.warmup_bars
    extended_df, eval_start = slice_with_warmup(df, split.validation_bounds, warmup)

    strategy = make_strategy()
    signals_from_extended = strategy.generate_signals(extended_df)

    # Reference: run the SAME strategy on the full continuous history from
    # bar 0 up to the end of validation, then look at the same absolute
    # timestamps.
    reference_df = df.iloc[: split.validation_bounds.end].reset_index(drop=True)
    reference_strategy = make_strategy()
    reference_signals = reference_strategy.generate_signals(reference_df)

    # Compare the first 5 bars of validation (indices eval_start..eval_start+5
    # in the extended series) against the corresponding absolute positions in
    # the reference run.
    for offset in range(5):
        extended_idx = eval_start + offset
        absolute_idx = split.validation_bounds.start + offset
        extended_ts = extended_df["timestamp"].iloc[extended_idx]
        reference_ts = reference_df["timestamp"].iloc[absolute_idx]
        assert extended_ts == reference_ts

        assert signals_from_extended.iloc[extended_idx] == reference_signals.iloc[absolute_idx], (
            f"signal mismatch at validation offset {offset}: "
            f"warm-up-fed={signals_from_extended.iloc[extended_idx]} "
            f"vs continuous-history={reference_signals.iloc[absolute_idx]}"
        )


@pytest.mark.parametrize("make_strategy", STRATEGIES)
def test_warmup_signal_matches_continuous_history_for_test_split(make_strategy):
    df = make_df(300)
    strategy_for_bounds = make_strategy()
    split = chronological_split(df, train_frac=0.5, validation_frac=0.25, test_frac=0.25)

    warmup = strategy_for_bounds.warmup_bars
    extended_df, eval_start = slice_with_warmup(df, split.test_bounds, warmup)

    strategy = make_strategy()
    signals_from_extended = strategy.generate_signals(extended_df)

    reference_df = df.iloc[: split.test_bounds.end].reset_index(drop=True)
    reference_strategy = make_strategy()
    reference_signals = reference_strategy.generate_signals(reference_df)

    for offset in range(5):
        extended_idx = eval_start + offset
        absolute_idx = split.test_bounds.start + offset
        assert (
            extended_df["timestamp"].iloc[extended_idx]
            == reference_df["timestamp"].iloc[absolute_idx]
        )
        assert signals_from_extended.iloc[extended_idx] == reference_signals.iloc[absolute_idx]


def test_slice_with_warmup_never_includes_future_rows():
    df = make_df(50)
    bounds = SplitBounds(start=20, end=30)
    extended_df, eval_start = slice_with_warmup(df, bounds, warmup_bars=15)

    assert len(extended_df) == eval_start + len(bounds)
    assert extended_df["timestamp"].max() == df["timestamp"].iloc[bounds.end - 1]
    # No row beyond bounds.end - 1 leaked in.
    assert (extended_df["timestamp"] <= df["timestamp"].iloc[bounds.end - 1]).all()


def test_slice_with_warmup_clips_at_dataset_start():
    df = make_df(50)
    bounds = SplitBounds(start=5, end=15)
    # Requesting more warm-up than exists before the split's start.
    extended_df, eval_start = slice_with_warmup(df, bounds, warmup_bars=100)

    assert eval_start == 5  # only 5 rows of history exist before bounds.start
    assert extended_df["timestamp"].iloc[0] == df["timestamp"].iloc[0]


def test_slice_with_warmup_zero_warmup_is_identity():
    df = make_df(50)
    bounds = SplitBounds(start=20, end=30)
    extended_df, eval_start = slice_with_warmup(df, bounds, warmup_bars=0)

    assert eval_start == 0
    pd.testing.assert_frame_equal(
        extended_df.reset_index(drop=True),
        df.iloc[bounds.start : bounds.end].reset_index(drop=True),
    )


def test_engine_result_excludes_warmup_from_equity_and_trades():
    from src.backtesting.engine import BacktestConfig, BacktestEngine
    from src.strategies.base import FLAT, LONG

    df = make_df(30)
    # Force a simple deterministic signal: flat during "warmup" (first 10
    # bars), long afterwards.
    signals = pd.Series([FLAT] * 10 + [LONG] * 20)

    engine = BacktestEngine(BacktestConfig(initial_capital=1000, trading_fee=0.0, slippage=0.0))
    result = engine.run(df, signals, evaluation_start=10)

    assert len(result.equity_curve) == 20
    assert result.equity_curve["timestamp"].iloc[0] == df["timestamp"].iloc[10]
    for trade in result.trades:
        assert trade.entry_time >= df["timestamp"].iloc[10]
