from __future__ import annotations

from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.models import PositionSide, TargetPosition

from .conftest import make_bars


def test_no_second_position_opened_while_one_is_active(make_config):
    # LONG held across multiple bars -- must never open a second position
    # while the first is still active; only one trade results.
    bars = make_bars([1.1000, 1.1010, 1.1020, 1.1030, 1.1000])
    signals = [
        TargetPosition.LONG,
        TargetPosition.LONG,
        TargetPosition.LONG,
        TargetPosition.LONG,
        TargetPosition.FLAT,
    ]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)
    assert len(result.trades) == 1
    assert result.trades[0].bars_held == 3


def test_close_when_already_flat_is_a_noop(make_config):
    bars = make_bars([1.1000, 1.1010, 1.1020])
    signals = [TargetPosition.FLAT, TargetPosition.FLAT, TargetPosition.FLAT]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)
    assert result.trades == []
    assert result.final_account.position is None


def test_long_to_short_transition_closes_then_opens(make_config):
    bars = make_bars([1.1000, 1.1010, 1.1020, 1.1000])
    signals = [
        TargetPosition.LONG,
        TargetPosition.SHORT,
        TargetPosition.SHORT,
        TargetPosition.FLAT,
    ]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)

    # LONG opened at bar[1].open, immediately closed at bar[2].open (the
    # bar the SHORT signal, shifted, takes effect on), then SHORT opened
    # at that same bar[2].open and closed at bar[3].open.
    assert len(result.trades) == 2
    assert result.trades[0].side is PositionSide.LONG
    assert result.trades[1].side is PositionSide.SHORT
    assert result.trades[0].close_time == result.trades[1].open_time


def test_short_to_long_transition_closes_then_opens(make_config):
    bars = make_bars([1.1000, 1.1010, 1.1020, 1.1000])
    signals = [
        TargetPosition.SHORT,
        TargetPosition.LONG,
        TargetPosition.LONG,
        TargetPosition.FLAT,
    ]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)

    assert len(result.trades) == 2
    assert result.trades[0].side is PositionSide.SHORT
    assert result.trades[1].side is PositionSide.LONG
    assert result.trades[0].close_time == result.trades[1].open_time


def test_position_flat_at_end_of_data_leaves_no_open_position(make_config):
    bars = make_bars([1.1000, 1.1010, 1.1020])
    signals = [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)
    assert result.final_account.position is None


def test_position_still_open_at_end_of_data_is_force_closed(make_config):
    bars = make_bars([1.1000, 1.1010, 1.1020])
    signals = [TargetPosition.LONG, TargetPosition.LONG, TargetPosition.LONG]
    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)
    assert len(result.trades) == 1
    assert result.final_account.position is None
    assert result.trades[0].close_time == bars[-1].timestamp_utc
