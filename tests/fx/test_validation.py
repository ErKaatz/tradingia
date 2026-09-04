"""Tests for src/fx/data/validation.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.fx.data.schema import FxBar, FxTimeframe
from src.fx.data.sessions import GapClassification
from src.fx.data.validation import validate_fx_bars


def _bar(ts: datetime, **overrides) -> FxBar:
    defaults = dict(
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0990"),
        close=Decimal("1.1005"),
        tick_volume=Decimal("120"),
        real_volume=None,
        spread_points=10,
    )
    defaults.update(overrides)
    return FxBar(timestamp_utc=ts, **defaults)


def _hours(start: datetime, n: int) -> list[datetime]:
    return [start + timedelta(hours=i) for i in range(n)]


def test_empty_dataset_is_invalid():
    result = validate_fx_bars((), FxTimeframe.H1)
    assert not result.is_valid
    assert "empty" in result.errors[0]


def test_contiguous_h1_bars_valid_no_gaps():
    start = datetime(2026, 1, 5, 0, tzinfo=timezone.utc)  # Monday
    bars = tuple(_bar(ts) for ts in _hours(start, 5))
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert result.is_valid
    assert result.gap_counts[GapClassification.UNEXPECTED_GAP] == 0


def test_weekend_gap_does_not_produce_error():
    friday_21 = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    sunday_22 = datetime(2026, 1, 4, 22, tzinfo=timezone.utc)
    bars = (_bar(friday_21), _bar(sunday_22))
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert result.is_valid
    assert result.gap_counts[GapClassification.EXPECTED_WEEKEND] == 1
    assert result.gap_counts[GapClassification.UNEXPECTED_GAP] == 0


def test_unexpected_midweek_gap_is_warning_not_hard_error():
    # Per spec: gaps are data, never silently repaired, but also never
    # auto-rejected as "corrupt dataset" -- they are reported.
    tuesday_10 = datetime(2026, 1, 6, 10, tzinfo=timezone.utc)
    tuesday_15 = datetime(2026, 1, 6, 15, tzinfo=timezone.utc)
    bars = (_bar(tuesday_10), _bar(tuesday_15))
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert result.is_valid  # still valid -- a gap is not "corrupt"
    assert result.gap_counts[GapClassification.UNEXPECTED_GAP] == 1
    assert len(result.unexpected_gap_examples) == 1
    assert any("unexpected" in w for w in result.warnings)


def test_duplicate_timestamps_rejected():
    ts = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    bars = (_bar(ts), _bar(ts))
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert not result.is_valid
    assert "duplicate" in result.errors[0] or "increasing" in result.errors[0]


def test_non_monotonic_timestamps_rejected():
    ts1 = datetime(2026, 1, 5, 11, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)  # earlier than ts1
    bars = (_bar(ts1), _bar(ts2))
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert not result.is_valid


def test_real_volume_zero_or_none_not_rejected():
    start = datetime(2026, 1, 5, 0, tzinfo=timezone.utc)
    bars = (
        _bar(start, real_volume=None),
        _bar(start + timedelta(hours=1), real_volume=Decimal("0")),
    )
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert result.is_valid


def test_single_bar_dataset_is_valid_no_gaps_to_classify():
    bars = (_bar(datetime(2026, 1, 5, 10, tzinfo=timezone.utc)),)
    result = validate_fx_bars(bars, FxTimeframe.H1)
    assert result.is_valid
