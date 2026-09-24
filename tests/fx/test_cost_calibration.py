from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.fx.backtesting.costs import NoCommission, PerLotPerSide, SideAwareFixedSwapModel
from src.fx.backtesting.models import PositionSide
from src.fx.cost_calibration import (
    FrozenNonSpreadCosts,
    calibrate_spread_by_hour,
    mt5_rollover_day_to_python_weekday,
    swap_points_cost_per_lot,
)
from src.fx.data.schema import FxBar


def _bar(hour: int, spread: int | None) -> FxBar:
    return FxBar(datetime(2026, 1, 5, hour, tzinfo=timezone.utc), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), None, spread)


def test_spread_calibration_is_conservative_and_preserves_missing_values():
    profile = calibrate_spread_by_hour((_bar(9, 10), _bar(9, 20), _bar(9, None), _bar(10, 5)), "dataset", minimum_observations_per_hour=2)
    nine = profile.buckets[9]
    assert (nine.observations, nine.missing, nine.median_points, nine.p95_points) == (2, 1, Decimal("15"), Decimal("20"))
    assert profile.overall_p95_points == Decimal("20")
    assert (profile.overall_observations, profile.overall_missing) == (3, 1)
    assert profile.to_json_dict()["buckets"][9]["p95"] == "20"
    assert profile.fingerprint() == calibrate_spread_by_hour((_bar(9, 10), _bar(9, 20), _bar(9, None), _bar(10, 5)), "dataset", minimum_observations_per_hour=2).fingerprint()


def test_mt5_points_swap_conversion_rejects_unknown_units():
    assert swap_points_cost_per_lot(swap_value=Decimal("-8.3"), swap_mode=1, point=Decimal("0.00001"), contract_size=Decimal("100000"), currency_profit="USD", account_currency="USD") == Decimal("8.3")
    with pytest.raises(ValueError, match="unsupported"):
        swap_points_cost_per_lot(swap_value=Decimal("1"), swap_mode=4, point=Decimal(".00001"), contract_size=Decimal("100000"), currency_profit="USD", account_currency="USD")


def test_calibration_fails_closed_when_the_sample_is_too_small():
    profile = calibrate_spread_by_hour((_bar(9, 10),), "dataset", minimum_observations_per_hour=2)
    assert profile.buckets[9].p95_points is None
    assert profile.overall_p95_points is None
    with pytest.raises(ValueError, match="minimum_observations"):
        calibrate_spread_by_hour((), "dataset", minimum_observations_per_hour=0)


def test_side_aware_swap_preserves_credit_and_verified_triple_day():
    model = SideAwareFixedSwapModel(Decimal("8.3"), Decimal("-1.2"), triple_swap_weekday=2)
    wednesday = datetime(2026, 1, 7, tzinfo=timezone.utc)
    assert model.charge_for_crossing(PositionSide.LONG, Decimal("0.01"), wednesday) == Decimal("0.249")
    assert model.charge_for_crossing(PositionSide.SHORT, Decimal("0.01"), wednesday) == Decimal("-0.036")


def test_frozen_non_spread_terms_are_explicit_and_reproducible():
    terms = FrozenNonSpreadCosts(
        symbol="EURUSD", account_currency="USD", commission_per_lot_per_side=Decimal("0"),
        long_swap_per_lot=Decimal("8.3"), short_swap_per_lot=Decimal("0"),
        triple_swap_weekday=mt5_rollover_day_to_python_weekday(3), source="MT5 metadata",
    )
    assert isinstance(terms.commission_model(), NoCommission)
    assert terms.swap_model().triple_swap_weekday == 2
    assert terms.to_json_dict()["long_swap_per_lot"] == "8.3"
    assert terms.fingerprint() == terms.fingerprint()
    charged = FrozenNonSpreadCosts("EURUSD", "USD", Decimal("2"), Decimal("0"), Decimal("0"), None, "test")
    assert isinstance(charged.commission_model(), PerLotPerSide)
    with pytest.raises(ValueError, match="invalid MT5 rollover"):
        mt5_rollover_day_to_python_weekday(7)
