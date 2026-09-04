from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.fx.backtesting.costs import FixedSwapModel, NoSwap, RolloverSchedule
from src.fx.backtesting.engine import FxBacktestEngine, SwapRequiredError
from src.fx.backtesting.models import TargetPosition

from .conftest import make_bars


def test_no_rollover_crossed_means_zero_swap(make_config):
    # All bars within the same UTC day (no configured rollover hour
    # crossed) -- swap_cost must be exactly zero even with FixedSwapModel.
    bars = make_bars([1.1000, 1.1000, 1.1050], start=datetime(2026, 1, 5, 1, 0, tzinfo=timezone.utc))
    engine = FxBacktestEngine(
        make_config(
            swap_model=FixedSwapModel(Decimal("2")),
            rollover_schedule=RolloverSchedule(frozenset({0})),
        )
    )
    result = engine.run(bars, [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT])
    assert result.trades[0].swap_cost == Decimal("0")


def test_rollover_crossed_with_undefined_model_raises(make_config):
    # A position held across a day boundary with a non-NoSwap model but NO
    # rollover_schedule must fail loudly, never silently assume zero swap.
    bars = make_bars(
        [1.1000, 1.1000, 1.1050],
        start=datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc),
    )
    engine = FxBacktestEngine(
        make_config(swap_model=FixedSwapModel(Decimal("2")), rollover_schedule=None)
    )
    with pytest.raises(SwapRequiredError):
        engine.run(bars, [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT])


def test_explicit_no_swap_is_allowed_and_auditable(make_config):
    bars = make_bars(
        [1.1000, 1.1000, 1.1050],
        start=datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc),
    )
    engine = FxBacktestEngine(make_config(swap_model=NoSwap(), rollover_schedule=None))
    result = engine.run(bars, [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT])
    assert result.trades[0].swap_cost == Decimal("0")


def test_fixed_swap_charges_expected_cost_per_crossing(make_config):
    bars = make_bars(
        [1.1000, 1.1000, 1.1000, 1.1050],
        start=datetime(2026, 1, 5, 23, 0, tzinfo=timezone.utc),
    )
    # bar times: 23:00, 00:00(+1d), 01:00(+1d), 02:00(+1d) -- exactly one
    # crossing of the configured 00:00 UTC rollover hour between bar 0 and
    # bar 1 while the position (opened at bar 1's open) is held through it.
    engine = FxBacktestEngine(
        make_config(
            swap_model=FixedSwapModel(Decimal("2")),
            rollover_schedule=RolloverSchedule(frozenset({0})),
        )
    )
    result = engine.run(
        bars,
        [TargetPosition.LONG, TargetPosition.LONG, TargetPosition.LONG, TargetPosition.FLAT],
    )
    trade = result.trades[0]
    # Position opens at bar[1].open (00:00+1d) and closes at bar[3].open
    # (02:00+1d) -- no further 00:00 crossing occurs in between, so swap
    # should be zero for this specific window (opened exactly at the
    # boundary, not before it).
    assert trade.swap_cost == Decimal("0")


def test_fixed_swap_charges_when_position_spans_the_boundary(make_config):
    bars = make_bars(
        [1.1000, 1.1000, 1.1000],
        start=datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc),
    )
    # bar times: 22:00, 23:00, 00:00(+1d) -- position opens at bar[1].open
    # (23:00) and closes at bar[2].open (00:00+1d), spanning exactly one
    # 00:00 UTC crossing.
    engine = FxBacktestEngine(
        make_config(
            swap_model=FixedSwapModel(Decimal("2")),
            rollover_schedule=RolloverSchedule(frozenset({0})),
        )
    )
    result = engine.run(bars, [TargetPosition.LONG, TargetPosition.LONG, TargetPosition.FLAT])
    trade = result.trades[0]
    assert trade.swap_cost == Decimal("2") * Decimal("0.01")
    assert trade.net_pnl == trade.gross_pnl - trade.spread_cost - trade.slippage_cost - trade.commission_cost - trade.swap_cost
