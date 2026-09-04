"""Tests for src/fx/data/sessions.py gap classification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.fx.data.sessions import GapClassification, classify_gap, is_expected_weekend_gap


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_h1_contiguous_gap():
    report = classify_gap(_dt(2026, 1, 5, 10), _dt(2026, 1, 5, 11), timedelta(hours=1))
    assert report.classification == GapClassification.CONTIGUOUS


def test_friday_to_sunday_gap_is_expected_weekend():
    # Friday 21:00 UTC -> Sunday 22:00 UTC (typical FX weekend close/open)
    friday = _dt(2026, 1, 2, 21)  # 2026-01-02 is a Friday
    sunday = _dt(2026, 1, 4, 22)
    assert friday.weekday() == 4
    assert sunday.weekday() == 6
    report = classify_gap(friday, sunday, timedelta(hours=1))
    assert report.classification == GapClassification.EXPECTED_WEEKEND


def test_friday_to_monday_gap_is_expected_weekend():
    friday = _dt(2026, 1, 2, 21)
    monday = _dt(2026, 1, 5, 0)
    report = classify_gap(friday, monday, timedelta(hours=1))
    assert report.classification == GapClassification.EXPECTED_WEEKEND


def test_missing_tuesday_h1_bar_is_unexpected_gap():
    tuesday_10 = _dt(2026, 1, 6, 10)
    tuesday_12 = _dt(2026, 1, 6, 12)  # missing the 11:00 bar
    assert tuesday_10.weekday() == 1
    report = classify_gap(tuesday_10, tuesday_12, timedelta(hours=1))
    assert report.classification == GapClassification.UNEXPECTED_GAP


def test_multi_hour_unexpected_gap_midweek():
    wed_morning = _dt(2026, 1, 7, 8)
    wed_evening = _dt(2026, 1, 7, 20)
    report = classify_gap(wed_morning, wed_evening, timedelta(hours=1))
    assert report.classification == GapClassification.UNEXPECTED_GAP


def test_gap_starting_before_friday_is_not_weekend_even_if_long():
    thursday = _dt(2026, 1, 1, 10)
    sunday = _dt(2026, 1, 4, 22)
    report = classify_gap(thursday, sunday, timedelta(hours=1))
    assert report.classification == GapClassification.UNEXPECTED_GAP


def test_gap_ending_before_sunday_is_not_weekend_even_if_friday_start():
    friday = _dt(2026, 1, 2, 10)
    saturday = _dt(2026, 1, 3, 10)
    report = classify_gap(friday, saturday, timedelta(hours=1))
    assert report.classification == GapClassification.UNEXPECTED_GAP


def test_exact_boundary_no_gap():
    report = classify_gap(_dt(2026, 1, 5, 10), _dt(2026, 1, 5, 11), timedelta(hours=1))
    assert report.classification == GapClassification.CONTIGUOUS
    assert report.actual_step == report.expected_step


def test_is_expected_weekend_gap_helper_matches_classify_gap():
    friday = _dt(2026, 1, 2, 21)
    sunday = _dt(2026, 1, 4, 22)
    assert is_expected_weekend_gap(friday, sunday) is True
    assert is_expected_weekend_gap(_dt(2026, 1, 1, 10), sunday) is False


def test_h4_contiguous_gap():
    report = classify_gap(_dt(2026, 1, 5, 8), _dt(2026, 1, 5, 12), timedelta(hours=4))
    assert report.classification == GapClassification.CONTIGUOUS


def test_d1_friday_to_monday_is_expected_weekend():
    friday = _dt(2026, 1, 2, 0)
    monday = _dt(2026, 1, 5, 0)
    report = classify_gap(friday, monday, timedelta(days=1))
    assert report.classification == GapClassification.EXPECTED_WEEKEND
