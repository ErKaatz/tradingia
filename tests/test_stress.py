"""Tests for the cost-stress scenario catalog in src/research/stress.py."""

from __future__ import annotations

import dataclasses

import pytest

from src.research.stress import CostScenario, DEFAULT_COST_SCENARIOS


def test_default_scenarios_have_unique_names():
    names = [s.name for s in DEFAULT_COST_SCENARIOS]
    assert len(names) == len(set(names))


def test_default_scenarios_never_reduce_costs_below_base():
    # A stress scenario must never be gentler than reality -- every
    # multiplier is >= 1.0.
    for scenario in DEFAULT_COST_SCENARIOS:
        assert scenario.fee_multiplier >= 1.0
        assert scenario.slippage_multiplier >= 1.0


def test_base_scenario_applies_no_stress():
    base = next(s for s in DEFAULT_COST_SCENARIOS if s.name == "A_base")
    assert base.fee_multiplier == 1.0
    assert base.slippage_multiplier == 1.0


def test_cost_scenario_is_frozen():
    scenario = CostScenario("custom", 1.5, 2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        scenario.fee_multiplier = 2.0
