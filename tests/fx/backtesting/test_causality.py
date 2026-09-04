from __future__ import annotations

from decimal import Decimal

from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.models import TargetPosition

from .conftest import make_bars


def test_signal_at_bar_i_executes_at_bar_i_plus_1_open(make_config):
    # LONG signal fires at bar 0's close; the engine must NOT fill at bar
    # 0's own price -- it must fill at bar 1's open.
    bars = make_bars([1.1000, 1.1100, 1.1200])
    signals = [TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.FLAT]

    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    # Entry executes at bar[1].open (1.1100), not bar[0]'s 1.1000.
    assert trade.open_time == bars[1].timestamp_utc
    assert trade.entry_bid == Decimal("1.1100")


def test_no_same_bar_lookahead_execution(make_config):
    # A LONG signal on the LAST bar has no next bar to execute on -- it
    # must never fill using that same bar's own price.
    bars = make_bars([1.1000, 1.1100, 1.1200])
    signals = [TargetPosition.FLAT, TargetPosition.FLAT, TargetPosition.LONG]

    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)

    # The LONG signal on bar 2 has no bar 3 to execute on -- no trade opens.
    assert result.trades == []
    assert result.final_account.position is None


def test_flat_signal_never_opens_a_position(make_config):
    bars = make_bars([1.1000, 1.1100, 1.1200, 1.1300])
    signals = [TargetPosition.FLAT] * 4

    engine = FxBacktestEngine(make_config())
    result = engine.run(bars, signals)

    assert result.trades == []
    assert result.final_account.balance == result.final_account.initial_balance
