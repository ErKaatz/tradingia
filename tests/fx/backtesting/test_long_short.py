from __future__ import annotations

from decimal import Decimal

import pytest

from src.fx.backtesting.costs import FixedPointsSlippage, PerLotPerSide, ZeroSlippage
from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.models import TargetPosition

from .conftest import make_bars


def _run(make_config, prices, signals, **overrides):
    bars = make_bars(prices)
    engine = FxBacktestEngine(make_config(**overrides))
    return engine.run(bars, signals)


class TestLong:
    def test_profitable_long(self, make_config):
        # LONG opens at bar[1].open ask, closes at bar[2].open bid; price
        # rises, so a profitable long must show positive net_pnl.
        result = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        assert len(result.trades) == 1
        assert result.trades[0].net_pnl > 0

    def test_losing_long(self, make_config):
        result = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        assert result.trades[0].net_pnl < 0

    def test_spread_only_loss_in_flat_market(self, make_config):
        # Price is IDENTICAL at entry and exit bar-open -- the only
        # possible loss is the spread crossed on open (ask) and close (bid).
        result = _run(
            make_config, [1.1000, 1.1000, 1.1000],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
            slippage_model=ZeroSlippage(),
        )
        trade = result.trades[0]
        assert trade.gross_pnl == 0
        assert trade.spread_cost > 0
        assert trade.net_pnl == -trade.spread_cost

    def test_slippage_impact(self, make_config):
        zero = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        slipped = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
            slippage_model=FixedPointsSlippage(Decimal("5")),
        )
        assert slipped.trades[0].net_pnl < zero.trades[0].net_pnl
        assert slipped.trades[0].slippage_cost > 0

    def test_commission_impact(self, make_config):
        zero = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        with_fee = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
            commission_model=PerLotPerSide(Decimal("7")),
        )
        assert with_fee.trades[0].net_pnl < zero.trades[0].net_pnl
        assert with_fee.trades[0].commission_cost == Decimal("7") * Decimal("0.01") * 2


class TestShort:
    def test_profitable_short(self, make_config):
        result = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        assert result.trades[0].net_pnl > 0

    def test_losing_short(self, make_config):
        result = _run(
            make_config, [1.1000, 1.1000, 1.1100],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        assert result.trades[0].net_pnl < 0

    def test_spread_only_loss_in_flat_market(self, make_config):
        result = _run(
            make_config, [1.1000, 1.1000, 1.1000],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        trade = result.trades[0]
        assert trade.gross_pnl == 0
        assert trade.spread_cost > 0
        assert trade.net_pnl == -trade.spread_cost

    def test_slippage_impact(self, make_config):
        zero = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        slipped = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
            slippage_model=FixedPointsSlippage(Decimal("5")),
        )
        assert slipped.trades[0].net_pnl < zero.trades[0].net_pnl
        assert slipped.trades[0].slippage_cost > 0

    def test_commission_impact(self, make_config):
        zero = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        )
        with_fee = _run(
            make_config, [1.1000, 1.1000, 1.0900],
            [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
            commission_model=PerLotPerSide(Decimal("7")),
        )
        assert with_fee.trades[0].net_pnl < zero.trades[0].net_pnl


def test_long_short_symmetry_zero_costs(make_config):
    """With zero spread, zero slippage, zero commission, zero swap, a LONG
    and a SHORT over the mirrored price move must show symmetric PnL."""
    long_result = _run(
        make_config, [1.1000, 1.1000, 1.1050],
        [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT],
        slippage_model=__import__("src.fx.backtesting.costs", fromlist=["ZeroSlippage"]).ZeroSlippage(),
    )
    short_result = _run(
        make_config, [1.1000, 1.1000, 1.0950],
        [TargetPosition.SHORT, TargetPosition.FLAT, TargetPosition.FLAT],
        slippage_model=__import__("src.fx.backtesting.costs", fromlist=["ZeroSlippage"]).ZeroSlippage(),
    )
    # Both bars carry the same spread (10 points), so both trades have the
    # identical spread_cost; the symmetric 50-pip move nets identical
    # gross_pnl in both directions.
    assert long_result.trades[0].gross_pnl == short_result.trades[0].gross_pnl
    assert long_result.trades[0].spread_cost == short_result.trades[0].spread_cost
