"""Tests for mt5_bridge/quote_freshness.py -- the bridge server-side
quote freshness/future-skew validation (FX Phase 0, "quote has a
timestamp in the future" investigation).

These test the bridge's own clock as the source of truth: `now_utc` is
always passed explicitly here so tests are deterministic and never
depend on wall-clock timing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mt5_bridge.quote_freshness import QuoteFreshnessError, validate_quote_freshness

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


# 1. quote UTC normal reciente -> allowed.
def test_recent_utc_quote_allowed():
    result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=NOW - timedelta(seconds=1), now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert result.age_seconds == pytest.approx(1.0)
    assert result.future_skew_seconds == 0.0


# 2. quote stale -> denied.
def test_stale_quote_denied():
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW - timedelta(seconds=30), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.reason == "stale"


# 3. quote 500ms future con tolerance 1s -> allowed.
def test_small_future_skew_within_tolerance_allowed():
    result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=NOW + timedelta(milliseconds=500), now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert result.future_skew_seconds == pytest.approx(0.5)


# 4. quote 2s future con tolerance 1s -> denied.
def test_future_skew_beyond_tolerance_denied():
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW + timedelta(seconds=2), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.reason == "future"
    assert "2.000s in the future" in str(excinfo.value)


# 5. naive timestamp -> denied.
def test_naive_timestamp_denied():
    naive = datetime(2026, 9, 3, 12, 0, 0)
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=naive, now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.reason == "naive_timestamp"


# 6. timestamp con offset != UTC -> normalizado correctamente.
def test_non_utc_offset_normalized_correctly():
    # 14:00+02:00 == 12:00 UTC == NOW exactly.
    offset_ts = datetime(2026, 9, 3, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=offset_ts, now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert result.age_seconds == pytest.approx(0.0, abs=1e-6)


# 6b. This is the actual bug class: a broker-server-local time (e.g.
# EEST, UTC+3) mislabeled as UTC looks like it's ~3h in the future.
# Confirms the helper correctly rejects that once it's given a properly
# tz-aware timestamp with the WRONG offset still attached would in fact
# fail differently -- this test instead demonstrates the failure mode
# this whole investigation was about: a naive value that SHOULD have
# carried +03:00 but was labeled +00:00 arrives here already wrong by
# construction (the caller's bug, not this validator's) and is correctly
# flagged as far-future.
def test_mislabeled_broker_server_time_flagged_as_future():
    mislabeled_as_utc = NOW + timedelta(hours=3)  # what backend.py would have produced pre-fix
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=mislabeled_as_utc, now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.reason == "future"
    assert excinfo.value.age_seconds == pytest.approx(-10800.0)


# 15. pathological timestamp year/far future -> denied.
def test_pathological_far_future_timestamp_denied():
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=datetime(2099, 1, 1, tzinfo=timezone.utc), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.reason == "future"


# 17. quote_age calculation no da signo invertido.
def test_age_sign_convention_stale_is_positive_future_is_negative():
    stale_result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=NOW - timedelta(seconds=2), now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert stale_result.age_seconds > 0

    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW + timedelta(seconds=2), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    assert excinfo.value.age_seconds < 0


# 18. exact boundary cases.
def test_exact_max_age_boundary_allowed():
    result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=NOW - timedelta(seconds=5), now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert result.age_seconds == pytest.approx(5.0)


def test_just_past_max_age_boundary_denied():
    with pytest.raises(QuoteFreshnessError):
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW - timedelta(seconds=5, milliseconds=1), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )


def test_exact_max_future_skew_boundary_allowed():
    result = validate_quote_freshness(
        symbol="EURUSD", quote_timestamp=NOW + timedelta(seconds=1), now_utc=NOW,
        max_age_seconds=5.0, max_future_skew_seconds=1.0,
    )
    assert result.future_skew_seconds == pytest.approx(1.0)


def test_just_past_max_future_skew_boundary_denied():
    with pytest.raises(QuoteFreshnessError):
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW + timedelta(seconds=1, milliseconds=1), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )


def test_error_message_contains_useful_fields_no_secrets():
    with pytest.raises(QuoteFreshnessError) as excinfo:
        validate_quote_freshness(
            symbol="EURUSD", quote_timestamp=NOW + timedelta(seconds=2), now_utc=NOW,
            max_age_seconds=5.0, max_future_skew_seconds=1.0,
        )
    message = str(excinfo.value)
    assert "EURUSD" in message
    assert "quote_timestamp=" in message
    assert "now_utc=" in message
    assert "allowed_future_skew_seconds=" in message
    assert "token" not in message.lower()
    assert "authorization" not in message.lower()
