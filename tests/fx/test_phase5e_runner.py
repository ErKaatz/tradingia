from __future__ import annotations

from decimal import Decimal

import pytest

from src.fx.research.phase5e_runner import Summary, assert_permitted_split, candidate, cost_efficient, registry, year_stable


def _summary(**overrides) -> Summary:
    values = dict(insolvent=False, trade_count=30, net_pnl=Decimal("10"), expectancy=Decimal(".1"), profit_factor=Decimal("1.1"), max_drawdown=Decimal("-.20"), long_trade_count=10, short_trade_count=10, largest_trade_contribution=Decimal(".30"), gross_reference_pnl=Decimal("20"), total_costs=Decimal("15"))
    values.update(overrides)
    return Summary(**values)


def test_exact_preregistered_registry_only():
    variants = registry()
    assert [v.variant_id for v in variants] == [
        "compression-expansion-16-4", "compression-expansion-24-6", "session-range-01-08", "session-range-02-09",
        "expansion-reversal-32-2p5-2", "expansion-reversal-48-2p25-4", "impulse-continuation-32-2p5-2", "impulse-continuation-48-2p25-4", "control-flat",
    ]
    assert sum(not v.control for v in variants) == 8


def test_test_split_is_structurally_rejected_before_authorization():
    with pytest.raises(ValueError, match="structurally forbidden"):
        assert_permitted_split("test")
    assert_permitted_split("development")


def test_cost_efficiency_boundary_and_non_positive_gross_fail():
    assert cost_efficient(Decimal("20"), Decimal("15"))
    assert not cost_efficient(Decimal("20"), Decimal("15.001"))
    assert not cost_efficient(Decimal("0"), Decimal("0"))
    assert not cost_efficient(Decimal("-1"), Decimal("0"))


def test_year_concentration_uses_positive_years_only_and_requires_two():
    assert year_stable({2022: Decimal("7"), 2023: Decimal("3"), 2024: Decimal("-99")}, {2022: 10, 2023: 10, 2024: 10})
    assert not year_stable({2022: Decimal("8"), 2023: Decimal("2")}, {2022: 10, 2023: 10})
    assert not year_stable({2022: Decimal("10"), 2023: Decimal("-1")}, {2022: 10, 2023: 10})


def test_candidate_boundaries_and_insolvency_reuse():
    good = _summary()
    years = {2022: Decimal("7"), 2023: Decimal("3")}
    counts = {2022: 10, 2023: 10}
    assert candidate(good, good, good, good, years, counts)
    assert not candidate(_summary(max_drawdown=Decimal("-.2001")), good, good, good, years, counts)
    assert not candidate(_summary(insolvent=True), good, good, good, years, counts)
    assert not candidate(good, good, _summary(net_pnl=Decimal("0")), good, years, counts)
