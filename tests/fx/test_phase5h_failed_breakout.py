from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar
from src.fx.strategies.phase5h_failed_breakout import HOLDING_BARS, VARIANTS, daily_range_failed_breakout


UTC = timezone.utc


def _bar(hour: int, close: str, day: int = 1) -> FxBar:
    value = Decimal(close)
    return FxBar(datetime(2025, 1, day, hour, tzinfo=UTC), value, value + Decimal("0.1"), value - Decimal("0.1"), value, Decimal("1"), None, 1)


def _history(confirm: str, direction: str):
    prior = tuple(_bar(h, "10", 1) for h in range(24))
    trigger = _bar(1, "8" if direction == "long" else "12", 2)
    return prior + (trigger, _bar(2, confirm, 2), _bar(3, "10", 2), _bar(4, "10", 2), _bar(5, "10", 2))


def test_exact_registry_completed_day_and_directional_confirmation():
    assert VARIANTS == ("daily-range-failed-breakout-long", "daily-range-failed-breakout-short", "control-flat")
    long_targets = daily_range_failed_breakout(_history("10", "long"), "daily-range-failed-breakout-long")
    short_targets = daily_range_failed_breakout(_history("10", "short"), "daily-range-failed-breakout-short")
    assert long_targets[25] is TargetPosition.LONG
    assert short_targets[25] is TargetPosition.SHORT
    assert all(x is TargetPosition.FLAT for x in long_targets[:25])


def test_failed_immediate_confirmation_and_strict_boundary_do_not_signal():
    assert all(x is TargetPosition.FLAT for x in daily_range_failed_breakout(_history("8", "long"), "daily-range-failed-breakout-long"))
    assert all(x is TargetPosition.FLAT for x in daily_range_failed_breakout(_history("9.9", "long"), "daily-range-failed-breakout-long"))


def test_hold_is_fixed_and_truncation_does_not_change_prior_targets():
    bars = _history("10", "long") + tuple(_bar(h, "10", 3) for h in range(8))
    targets = daily_range_failed_breakout(bars, "daily-range-failed-breakout-long")
    assert targets[25:25 + HOLDING_BARS] == (TargetPosition.LONG,) * HOLDING_BARS
    assert daily_range_failed_breakout(bars[:-2], "daily-range-failed-breakout-long") == targets[:-2]


def test_delayed_confirmation_boundary_and_daily_expiry_are_rejected():
    prior = tuple(_bar(h, "10", 1) for h in range(24))
    delayed = prior + (_bar(1, "8", 2), _bar(2, "8", 2), _bar(3, "10", 2))
    boundary = prior + (_bar(1, "8", 2), _bar(2, "9.9", 2))
    across_day = prior + (_bar(23, "8", 2), _bar(0, "10", 3))
    for bars in (delayed, boundary, across_day):
        assert all(x is TargetPosition.FLAT for x in daily_range_failed_breakout(bars, "daily-range-failed-breakout-long"))


def test_new_event_while_first_position_is_owned_is_ignored():
    prior = tuple(_bar(h, "10", 1) for h in range(24))
    # B0/B1 create the first long.  B2/B3 would otherwise form another
    # downside-break/inside pair, but B2--B5 are owned by the first event.
    day_two = (_bar(0, "10", 2), _bar(1, "8", 2), _bar(2, "10", 2), _bar(3, "8", 2), _bar(4, "10", 2), _bar(5, "10", 2), _bar(6, "10", 2), _bar(7, "10", 2))
    targets = daily_range_failed_breakout(prior + day_two, "daily-range-failed-breakout-long")
    assert targets[26:30] == (TargetPosition.LONG,) * HOLDING_BARS
    assert all(x is TargetPosition.FLAT for x in targets[30:])


def _dated_bar(when: datetime, close: str) -> FxBar:
    value = Decimal(close)
    return FxBar(when, value, value + Decimal(".1"), value - Decimal(".1"), value, Decimal("1"), None, 1)


def test_friday_to_monday_does_not_carry_forward_friday_range():
    friday = tuple(_dated_bar(datetime(2022, 9, 23, hour, tzinfo=UTC), "10") for hour in (0, 1))
    # Monday's values would make a valid Friday-range break/confirmation if
    # the old previous-observed-day lookup were used. Sunday is absent, so
    # Monday's exact prior UTC date has no range and must stay FLAT.
    monday = (_dated_bar(datetime(2022, 9, 26, 0, tzinfo=UTC), "8"), _dated_bar(datetime(2022, 9, 26, 1, tzinfo=UTC), "10"))
    assert daily_range_failed_breakout(friday + monday, "daily-range-failed-breakout-long") == (TargetPosition.FLAT,) * 4


def test_consecutive_calendar_day_uses_exact_prior_date_even_when_partial():
    monday = tuple(_dated_bar(datetime(2022, 9, 26, hour, tzinfo=UTC), "10") for hour in (0, 1))
    tuesday = (_dated_bar(datetime(2022, 9, 27, 0, tzinfo=UTC), "8"), _dated_bar(datetime(2022, 9, 27, 1, tzinfo=UTC), "10"))
    targets = daily_range_failed_breakout(monday + tuesday, "daily-range-failed-breakout-long")
    assert targets[-1] is TargetPosition.LONG


def test_multiple_missing_dates_never_search_backward_or_keep_pending_state():
    friday = tuple(_dated_bar(datetime(2022, 9, 23, hour, tzinfo=UTC), "10") for hour in (0, 1))
    tuesday = (_dated_bar(datetime(2022, 9, 27, 0, tzinfo=UTC), "8"), _dated_bar(datetime(2022, 9, 27, 1, tzinfo=UTC), "10"))
    assert daily_range_failed_breakout(friday + tuesday, "daily-range-failed-breakout-long") == (TargetPosition.FLAT,) * 4


def test_month_and_year_boundaries_query_exact_previous_utc_date():
    dec31 = tuple(_dated_bar(datetime(2022, 12, 31, hour, tzinfo=UTC), "10") for hour in (0, 1))
    jan1 = (_dated_bar(datetime(2023, 1, 1, 0, tzinfo=UTC), "8"), _dated_bar(datetime(2023, 1, 1, 1, tzinfo=UTC), "10"))
    assert daily_range_failed_breakout(dec31 + jan1, "daily-range-failed-breakout-long")[-1] is TargetPosition.LONG
    jan30 = tuple(_dated_bar(datetime(2023, 1, 30, hour, tzinfo=UTC), "10") for hour in (0, 1))
    feb1 = (_dated_bar(datetime(2023, 2, 1, 0, tzinfo=UTC), "8"), _dated_bar(datetime(2023, 2, 1, 1, tzinfo=UTC), "10"))
    # Jan 31 is absent, so Jan 30 may not be used as a fallback for Feb 1.
    assert daily_range_failed_breakout(jan30 + feb1, "daily-range-failed-breakout-long") == (TargetPosition.FLAT,) * 4
