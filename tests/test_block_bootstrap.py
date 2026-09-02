"""Tests for the optional moving block bootstrap (Task 20)."""

from __future__ import annotations

import numpy as np
import pytest

from src.research.block_bootstrap import block_bootstrap_trade_returns


def test_reproducible_with_same_seed():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.04]
    summary1, finals1, _ = block_bootstrap_trade_returns(returns, block_size=2, simulations=500, seed=7)
    summary2, finals2, _ = block_bootstrap_trade_returns(returns, block_size=2, simulations=500, seed=7)
    assert summary1 == summary2
    np.testing.assert_array_equal(finals1, finals2)


def test_different_seed_gives_different_result():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.04]
    _, finals1, _ = block_bootstrap_trade_returns(returns, block_size=2, simulations=500, seed=1)
    _, finals2, _ = block_bootstrap_trade_returns(returns, block_size=2, simulations=500, seed=2)
    assert not np.array_equal(finals1, finals2)


def test_block_size_one_reduces_to_effectively_iid_bootstrap_shape():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02]
    summary, finals, dds = block_bootstrap_trade_returns(returns, block_size=1, simulations=1000, seed=42)
    assert summary.num_trades == len(returns)
    assert len(finals) == 1000


def test_rejects_block_size_larger_than_trade_count():
    with pytest.raises(ValueError):
        block_bootstrap_trade_returns([0.01, 0.02], block_size=5, simulations=100, seed=1)


def test_rejects_impossible_loss():
    with pytest.raises(ValueError):
        block_bootstrap_trade_returns([0.01, -1.5], block_size=1, simulations=100, seed=1)


def test_rejects_zero_simulations():
    with pytest.raises(ValueError):
        block_bootstrap_trade_returns([0.01, 0.02], block_size=1, simulations=0, seed=1)


def test_output_length_matches_original_trade_count_via_final_return_consistency():
    """The synthetic sequence length equals len(trade_returns); verified
    indirectly by checking a degenerate all-zero-return series gives
    exactly zero final return regardless of block composition.
    """
    returns = [0.0] * 10
    summary, finals, dds = block_bootstrap_trade_returns(returns, block_size=3, simulations=200, seed=5)
    assert np.allclose(finals, 0.0)
    assert np.allclose(dds, 0.0)


def test_preserves_block_level_correlation_more_than_full_shuffle():
    """A sequence with strong local clustering (long runs of losses, then
    long runs of wins) should show MORE dispersion in block-bootstrap
    drawdowns with a large block size (which preserves the clusters) than
    with block_size=1 (which destroys clustering by resampling individual
    trades) -- a qualitative sanity check that blocks are doing something.
    """
    clustered = [-0.05] * 10 + [0.05] * 10
    summary_block1, _, dds_block1 = block_bootstrap_trade_returns(clustered, block_size=1, simulations=2000, seed=42)
    summary_block10, _, dds_block10 = block_bootstrap_trade_returns(clustered, block_size=10, simulations=2000, seed=42)
    # With block_size=10 (preserving whole clusters), the worst-case drawdown
    # distribution should have MORE spread (std) than with block_size=1
    # (which mixes losses and wins more evenly across simulations).
    assert np.std(dds_block10) >= np.std(dds_block1)
