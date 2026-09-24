from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from src.fx.research.policy_events import (
    BoJRegime, ChangeDirection, PolicyRateDecisionEvent, ProvenanceStatus, fingerprint,
    boj_regime, build_boj_v2, differential_change, parse_boj_release_time, regime_safe_differential_direction, signal_ready, signed_change, strict_json, utc_from_local,
)


def test_fed_edst_and_est_convert_with_iana_rules():
    assert utc_from_local(datetime(2024, 3, 20, 14), "America/New_York") == datetime(2024, 3, 20, 18, tzinfo=timezone.utc)
    assert utc_from_local(datetime(2024, 12, 18, 14), "America/New_York") == datetime(2024, 12, 18, 19, tzinfo=timezone.utc)


def test_boj_jst_conversion_has_no_dst():
    assert utc_from_local(datetime(2024, 7, 31, 12, 30), "Asia/Tokyo") == datetime(2024, 7, 31, 3, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(("old", "new", "direction"), [("1.0", "1.25", ChangeDirection.WIDENS), ("1.25", "1.0", ChangeDirection.NARROWS), ("1.0", "1.0", ChangeDirection.UNCHANGED)])
def test_signed_rate_change(old, new, direction):
    change, actual = signed_change(Decimal(old), Decimal(new))
    assert actual is direction and change == Decimal(new) - Decimal(old)


def test_differential_computation_is_signed():
    assert differential_change(Decimal("5.0"), Decimal("-0.1"), Decimal("5.25"), Decimal("-0.1")) == (Decimal("5.1"), Decimal("5.35"), Decimal("0.25"), ChangeDirection.WIDENS)


def test_regime_separated_policy_scalar_never_splices_march_2024():
    assert boj_regime("2024-03-18") is BoJRegime.NEGATIVE_RATE
    assert boj_regime("2024-03-19") is BoJRegime.TRANSITION
    assert boj_regime("2024-03-20") is BoJRegime.OVERNIGHT_GUIDELINE
    assert regime_safe_differential_direction(BoJRegime.NEGATIVE_RATE, BoJRegime.OVERNIGHT_GUIDELINE, Decimal("5"), Decimal("-.1"), Decimal("5"), Decimal(".05")) is BoJRegime.TRANSITION


def _event(status=ProvenanceStatus.VERIFIED, scheduled=True):
    verified = status is ProvenanceStatus.VERIFIED
    return PolicyRateDecisionEvent("FED", "fed-test", "2024-03-19", "2024-03-20", scheduled, "2024-03-20T14:00:00", "America/New_York", datetime(2024, 3, 20, 18, tzinfo=timezone.utc) if verified else None, "https://www.federalreserve.gov/example", "statement", "2024-03-20", datetime(2026, 9, 8, tzinfo=timezone.utc), "target-range-midpoint", Decimal("5.375") if verified else None, Decimal("5.375") if verified else None, Decimal("0") if verified else None, ChangeDirection.UNCHANGED if verified else None, None, "public release is information availability", "a" * 64, status)


def test_missing_official_time_fails_closed():
    assert not signal_ready(_event(ProvenanceStatus.MISSING_OFFICIAL_TIME))


def test_missing_rate_fails_closed():
    assert not signal_ready(_event(ProvenanceStatus.MISSING_POLICY_VALUE))


def test_unscheduled_is_out_of_hypothesis_scope():
    assert not signal_ready(_event(ProvenanceStatus.UNSCHEDULED_OUT_OF_SCOPE, scheduled=False))


def test_event_fingerprint_and_strict_json_are_deterministic():
    value = _event().to_dict()
    assert fingerprint(value) == fingerprint(value)
    assert strict_json(value) == strict_json(value)


def test_phase5k_machine_readable_feed_is_strict_and_fail_closed():
    root = Path("data/fx/research/events/policy_rates")
    fed = json.loads((root / "fed_policy_events.json").read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    boj = json.loads((root / "boj_policy_events.json").read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    differential = json.loads((root / "fed_boj_differential_events.json").read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert len(fed["events"]) == 24
    assert len(boj["events"]) == 24
    assert boj["per_event_provenance_status"] == "MISSING_OFFICIAL_TIME"
    assert differential["events"] == [] and differential["status"].startswith("BLOCKED")


def test_boj_html_parser_extracts_statement_release_time_and_alternative_title():
    source = b'<dt>Release dates and times:</dt><dd>Changes in the Monetary Policy Framework -- Tuesday, March 19 at 12:35</dd></dl>'
    assert parse_boj_release_time(source) == ("Changes in the Monetary Policy Framework", "12:35")


def test_boj_html_parser_fails_closed_when_missing_or_ambiguous():
    with pytest.raises(ValueError, match="MISSING_OFFICIAL_TIME"):
        parse_boj_release_time(b"<html></html>")
    ambiguous = b'<dt>Release dates and times:</dt>\n<dd>Statement on Monetary Policy -- Tuesday at 12:00</dd>\n<dd>Statement on Monetary Policy -- Tuesday at 12:01</dd></dl>'
    with pytest.raises(ValueError, match="AMBIGUOUS_OFFICIAL_TIME"):
        parse_boj_release_time(ambiguous)


@pytest.mark.parametrize(("filename", "expected"), [
    ("k220922a.htm", ("Statement on Monetary Policy", "11:51")),
    ("k230118a.htm", ("Statement on Monetary Policy", "11:40")),
    ("k240319a.htm", ("Changes in the Monetary Policy Framework", "12:35")),
    ("k241031a.htm", ("Statement on Monetary Policy", "11:48")),
])
def test_archived_official_boj_html_fixtures_extract_exact_release_times(filename, expected):
    source = Path("data/fx/research/events/policy_rates/phase5k_policy_events_v2/boj_sources") / filename
    assert parse_boj_release_time(source.read_bytes()) == expected
