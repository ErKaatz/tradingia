from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.fx.backtesting.models import TargetPosition
from src.fx.strategies.baselines import ema_trend, session_breakout, signed_momentum, zscore_mean_reversion
from src.fx.data.schema import FxBar


def _bars(count: int) -> tuple[FxBar, ...]:
    start = datetime(2026, 1, 5, 1, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        value = Decimal("1.10000") + Decimal(index % 11) / Decimal("100000")
        result.append(FxBar(start + timedelta(minutes=15 * index), value, value + Decimal(".00001"), value - Decimal(".00001"), value, Decimal("1"), None, 10))
    return tuple(result)


@pytest.mark.parametrize("signal", [
    lambda bars: ema_trend(bars, 2, 5),
    lambda bars: zscore_mean_reversion(bars, 5, 1.0),
    lambda bars: signed_momentum(bars, 3),
    lambda bars: session_breakout(bars, 1, 3),
])
def test_baseline_signals_are_truncation_invariant(signal):
    bars = _bars(120)
    assert signal(bars)[:80] == signal(bars[:80])


def test_baselines_are_flat_outside_preregistered_active_window():
    bars = _bars(120)
    targets = signed_momentum(bars, 3)
    for bar, target in zip(bars, targets):
        if not 1 <= bar.timestamp_utc.hour < 20:
            assert target is TargetPosition.FLAT
