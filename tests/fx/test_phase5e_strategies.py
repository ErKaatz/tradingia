from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar
from src.fx.strategies.phase5e_events import _event_targets, compression_expansion, session_range_breakout, standardized_impulse


def _bars(count: int, start: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc)) -> tuple[FxBar, ...]:
    values = []
    for i in range(count):
        price = Decimal("1.10000") + Decimal((i * 7) % 19 - 9) / Decimal("100000")
        values.append(FxBar(start + timedelta(minutes=15 * i), price, price + Decimal(".00005"), price - Decimal(".00005"), price, Decimal("1"), None, 10))
    return tuple(values)


@pytest.mark.parametrize("signal", [
    lambda bars: compression_expansion(bars, 16, 4, .75, 4),
    lambda bars: session_range_breakout(bars, 1, 5, 8, 11, 4),
    lambda bars: standardized_impulse(bars, 32, 2.5, 2, True),
    lambda bars: standardized_impulse(bars, 48, 2.25, 4, False),
])
def test_phase5e_signals_are_truncation_invariant_and_deterministic(signal):
    bars = _bars(240)
    full = signal(bars)
    assert full[:160] == signal(bars[:160])
    assert full == signal(bars)


def test_event_target_holding_and_one_position_semantics():
    bars = _bars(12, datetime(2024, 1, 1, 8, tzinfo=timezone.utc))
    events = {0: TargetPosition.LONG, 1: TargetPosition.SHORT, 2: TargetPosition.SHORT, 4: TargetPosition.SHORT}
    targets = _event_targets(bars, lambda i: events.get(i, TargetPosition.FLAT), holding_bars=3)
    assert targets[:5] == (TargetPosition.LONG, TargetPosition.LONG, TargetPosition.LONG, TargetPosition.FLAT, TargetPosition.SHORT)
    assert TargetPosition.SHORT not in targets[:3]


def test_active_window_is_flat_and_resets_holding():
    bars = _bars(8, datetime(2024, 1, 1, 19, 30, tzinfo=timezone.utc))
    targets = _event_targets(bars, lambda i: TargetPosition.LONG, holding_bars=4)
    for bar, target in zip(bars, targets):
        if not 1 <= bar.timestamp_utc.hour < 20:
            assert target is TargetPosition.FLAT


def test_session_rule_consumes_at_most_one_event_per_day():
    bars = list(_bars(96, datetime(2024, 1, 1, tzinfo=timezone.utc)))
    adjusted = []
    for bar in bars:
        close = Decimal("1.20000") if bar.timestamp_utc.hour in (8, 9, 10) else bar.close
        high = max(bar.high, close)
        adjusted.append(FxBar(bar.timestamp_utc, bar.open, high, bar.low, close, bar.tick_volume, bar.real_volume, bar.spread_points))
    targets = session_range_breakout(tuple(adjusted), 1, 5, 8, 11, 4)
    starts = [i for i, target in enumerate(targets) if target is TargetPosition.LONG and (i == 0 or targets[i - 1] is TargetPosition.FLAT)]
    assert len(starts) <= 1


def test_invalid_parameters_fail_closed():
    bars = _bars(10)
    with pytest.raises(ValueError): compression_expansion(bars, 1, 4, .75)
    with pytest.raises(ValueError): session_range_breakout(bars, 2, 1, 8, 11)
    with pytest.raises(ValueError): standardized_impulse(bars, 1, 2, 2, True)
