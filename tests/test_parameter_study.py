"""Tests for the parameter-grid generator in src/research/parameter_study.py."""

from __future__ import annotations

import pytest

from src.research.parameter_study import generate_parameter_grid


def test_empty_parameter_study_returns_a_single_empty_combination():
    assert generate_parameter_grid("momentum", {}) == [{}]


def test_rejects_non_list_parameter_values():
    with pytest.raises(ValueError):
        generate_parameter_grid("momentum", {"lookback": 5})


def test_rejects_empty_list_parameter_values():
    with pytest.raises(ValueError):
        generate_parameter_grid("momentum", {"lookback": []})


def test_generates_full_grid_when_every_combination_is_a_valid_strategy():
    grid = generate_parameter_grid("momentum", {"lookback": [1, 2, 3]})
    assert grid == [{"lookback": 1}, {"lookback": 2}, {"lookback": 3}]


def test_generates_cartesian_product_across_multiple_parameters():
    grid = generate_parameter_grid(
        "mean_reversion", {"rsi_period": [5, 10], "oversold": [20.0]}
    )
    assert len(grid) == 2
    assert {"rsi_period": 5, "oversold": 20.0} in grid
    assert {"rsi_period": 10, "oversold": 20.0} in grid


def test_filters_out_combinations_that_fail_strategy_construction():
    # SmaCross requires fast < slow; (20, 10) and (20, 20) are invalid and
    # must be silently dropped rather than raising.
    grid = generate_parameter_grid("sma_cross", {"fast": [5, 20], "slow": [10, 20]})
    assert grid == [{"fast": 5, "slow": 10}, {"fast": 5, "slow": 20}]


def test_validator_further_restricts_the_grid():
    grid = generate_parameter_grid(
        "momentum",
        {"lookback": [1, 2, 3, 4]},
        validator=lambda params: params["lookback"] % 2 == 0,
    )
    assert grid == [{"lookback": 2}, {"lookback": 4}]


def test_unknown_strategy_name_yields_an_empty_grid_rather_than_raising():
    # generate_parameter_grid treats any exception from build_strategy as
    # "this combination is invalid", including an unknown strategy name --
    # so a typo'd strategy name silently produces zero candidates instead
    # of a clear error. Documented here as current behavior.
    grid = generate_parameter_grid("not_a_real_strategy", {"x": [1, 2]})
    assert grid == []
