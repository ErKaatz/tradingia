"""Tests for the IID trade-return Monte Carlo bootstrap in
src/research/monte_carlo.py."""

from __future__ import annotations

import numpy as np
import pytest

from src.research.monte_carlo import monte_carlo_trade_returns


def test_reproducible_with_same_seed():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.04]
    summary1, finals1, dds1 = monte_carlo_trade_returns(returns, simulations=500, seed=7)
    summary2, finals2, dds2 = monte_carlo_trade_returns(returns, simulations=500, seed=7)
    assert summary1 == summary2
    np.testing.assert_array_equal(finals1, finals2)
    np.testing.assert_array_equal(dds1, dds2)


def test_different_seed_gives_different_result():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.04]
    _, finals1, _ = monte_carlo_trade_returns(returns, simulations=500, seed=1)
    _, finals2, _ = monte_carlo_trade_returns(returns, simulations=500, seed=2)
    assert not np.array_equal(finals1, finals2)


def test_rejects_zero_or_negative_simulations():
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([0.01, 0.02], simulations=0, seed=1)


def test_rejects_empty_trade_returns():
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([], simulations=100, seed=1)


def test_rejects_non_finite_returns():
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([0.01, float("nan")], simulations=100, seed=1)
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([0.01, float("inf")], simulations=100, seed=1)


def test_rejects_impossible_loss_at_or_below_total_wipeout():
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([0.01, -1.0], simulations=100, seed=1)
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([0.01, -1.5], simulations=100, seed=1)


def test_output_shapes_and_num_trades():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02]
    summary, finals, dds = monte_carlo_trade_returns(returns, simulations=300, seed=3)
    assert summary.num_trades == len(returns)
    assert summary.simulations == 300
    assert len(finals) == 300
    assert len(dds) == 300


def test_all_positive_returns_never_produce_a_negative_outcome():
    returns = [0.01, 0.02, 0.03, 0.015]
    summary, finals, dds = monte_carlo_trade_returns(returns, simulations=500, seed=11)
    assert summary.probability_negative == 0.0
    assert (finals > 0).all()
    assert (dds <= 0).all()  # drawdown is <= 0 by construction, even without losses


def test_single_trade_return_bootstraps_to_itself():
    # With only one possible value to draw, every simulated path's final
    # return must equal that single trade's return exactly.
    summary, finals, dds = monte_carlo_trade_returns([0.05], simulations=200, seed=9)
    assert np.allclose(finals, 0.05)
    assert np.allclose(dds, 0.0)  # a single up-move never dips below its start


def test_all_zero_returns_are_flat():
    summary, finals, dds = monte_carlo_trade_returns([0.0] * 6, simulations=100, seed=4)
    assert np.allclose(finals, 0.0)
    assert np.allclose(dds, 0.0)
    assert summary.probability_negative == 0.0
