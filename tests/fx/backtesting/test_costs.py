from __future__ import annotations

from decimal import Decimal

from src.fx.backtesting.costs import FixedPointsSlippage, PerLotPerSide
from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.models import TargetPosition

from .conftest import make_bars


def test_no_double_counting_spread(make_config):
    """spread_cost must be derived once, not embedded in gross_pnl AND
    subtracted again -- the accounting identity below must hold exactly."""
    bars = make_bars([1.1000, 1.1000, 1.1050])
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT])
    trade = result.trades[0]

    assert trade.gross_pnl - trade.spread_cost - trade.slippage_cost - trade.commission_cost - trade.swap_cost == trade.net_pnl


def test_cost_decomposition_identity_with_all_costs(make_config):
    bars = make_bars([1.1000, 1.1000, 1.1050])
    engine = FxBacktestEngine(
        make_config(
            slippage_model=FixedPointsSlippage(Decimal("3")),
            commission_model=PerLotPerSide(Decimal("7")),
        )
    )
    result = engine.run(bars, [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT])
    trade = result.trades[0]

    identity = trade.gross_pnl - trade.spread_cost - trade.slippage_cost - trade.commission_cost - trade.swap_cost
    assert identity == trade.net_pnl
    assert trade.spread_cost > 0
    assert trade.slippage_cost > 0
    assert trade.commission_cost > 0


def test_adding_adverse_cost_cannot_improve_net_pnl(make_config):
    bars = make_bars([1.1000, 1.1000, 1.1050])
    signals = [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT]

    baseline = FxBacktestEngine(make_config()).run(bars, signals).trades[0].net_pnl
    with_slippage = FxBacktestEngine(
        make_config(slippage_model=FixedPointsSlippage(Decimal("5")))
    ).run(bars, signals).trades[0].net_pnl
    with_commission = FxBacktestEngine(
        make_config(commission_model=PerLotPerSide(Decimal("10")))
    ).run(bars, signals).trades[0].net_pnl

    assert with_slippage <= baseline
    assert with_commission <= baseline
