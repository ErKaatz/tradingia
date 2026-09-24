"""Causal completed-daily-range failed-breakout targets for Phase 5H."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar


VARIANTS = ("daily-range-failed-breakout-long", "daily-range-failed-breakout-short", "control-flat")
HOLDING_BARS = 4


def daily_range_failed_breakout(bars: tuple[FxBar, ...], variant_id: str) -> tuple[TargetPosition, ...]:
    if variant_id not in VARIANTS:
        raise ValueError("unknown Phase 5H variant")
    if variant_id == "control-flat":
        return tuple(TargetPosition.FLAT for _ in bars)
    side = TargetPosition.LONG if variant_id.endswith("-long") else TargetPosition.SHORT
    out: list[TargetPosition] = []
    completed_day_ranges: dict[object, tuple[Decimal, Decimal]] = {}
    current_day = None
    day_low: Decimal | None = None
    day_high: Decimal | None = None
    pending = False
    held = 0
    for bar in bars:
        day = bar.timestamp_utc.date()
        if current_day != day:
            if current_day is not None and day_low is not None and day_high is not None:
                completed_day_ranges[current_day] = (day_low, day_high)
            current_day, day_low, day_high = day, bar.low, bar.high
            pending = False  # an unconfirmed break never survives a UTC day boundary
        else:
            day_low, day_high = min(day_low, bar.low), max(day_high, bar.high)
        if held:
            out.append(side)
            held -= 1
            continue
        # Reference only D - 1 by UTC calendar identity. Missing calendar
        # dates are unavailable; the last observed day must never be carried
        # forward across a weekend or any other gap.
        prior = completed_day_ranges.get(day - timedelta(days=1))
        if prior is None:
            out.append(TargetPosition.FLAT)
            continue
        low, high = prior
        inside = low < bar.close < high
        if pending:
            pending = False
            if inside:
                out.append(side)
                held = HOLDING_BARS - 1
            else:
                out.append(TargetPosition.FLAT)
            continue
        broken = bar.close < low if side is TargetPosition.LONG else bar.close > high
        pending = broken
        out.append(TargetPosition.FLAT)
    return tuple(out)
