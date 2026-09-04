"""Tests for src/fx/data/schema.py."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.fx.data.schema import FxBar


def _bar(**overrides):
    defaults = dict(
        timestamp_utc=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0990"),
        close=Decimal("1.1005"),
        tick_volume=Decimal("120"),
        real_volume=None,
        spread_points=10,
    )
    defaults.update(overrides)
    return FxBar(**defaults)


def test_valid_bar_constructs():
    bar = _bar()
    assert bar.close == Decimal("1.1005")


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        _bar(timestamp_utc=datetime(2026, 1, 5, 10, 0))


def test_non_utc_timestamp_rejected():
    from datetime import timedelta, timezone as tz

    offset_tz = tz(timedelta(hours=3))
    with pytest.raises(ValueError, match="UTC"):
        _bar(timestamp_utc=datetime(2026, 1, 5, 10, 0, tzinfo=offset_tz))


def test_invalid_ohlc_high_too_low_rejected():
    with pytest.raises(ValueError, match="high"):
        _bar(high=Decimal("1.0995"))  # below close


def test_invalid_ohlc_low_too_high_rejected():
    with pytest.raises(ValueError, match="low"):
        _bar(low=Decimal("1.1002"))  # above open


def test_non_positive_price_rejected():
    with pytest.raises(ValueError, match="open"):
        _bar(open=Decimal("0"))


def test_negative_tick_volume_rejected():
    with pytest.raises(ValueError, match="tick_volume"):
        _bar(tick_volume=Decimal("-1"))


def test_negative_real_volume_rejected():
    with pytest.raises(ValueError, match="real_volume"):
        _bar(real_volume=Decimal("-1"))


def test_real_volume_none_is_valid():
    bar = _bar(real_volume=None)
    assert bar.real_volume is None


def test_negative_spread_rejected():
    with pytest.raises(ValueError, match="spread_points"):
        _bar(spread_points=-1)


def test_spread_none_is_valid():
    bar = _bar(spread_points=None)
    assert bar.spread_points is None
