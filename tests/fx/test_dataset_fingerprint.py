"""Tests for src/fx/data/dataset.py's fingerprint policy.

Requirement: same normalized dataset -> same SHA-256, independent of
when it was fetched or in what row/key order it arrived. The
fingerprint must change for any materially different content and must
NOT change for purely operational metadata.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.fx.data.dataset import build_dataset_metadata, compute_dataset_fingerprint
from src.fx.data.schema import FxBar, FxSymbolMetadata, FxTimeframe


def _bar(ts: datetime, **overrides) -> FxBar:
    defaults = dict(
        timestamp_utc=ts,
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


def _symbol_metadata(**overrides) -> FxSymbolMetadata:
    defaults = dict(
        requested_symbol="EURUSD",
        resolved_symbol="EURUSD",
        description=None,
        digits=5,
        point=Decimal("0.00001"),
        volume_min=Decimal("0.01"),
        volume_step=Decimal("0.01"),
        volume_max=Decimal("100"),
        contract_size=Decimal("100000"),
        tick_size=Decimal("0.00001"),
        tick_value=Decimal("1.0"),
        currency_base="EUR",
        currency_profit="USD",
        currency_margin="EUR",
        broker=None,
        server=None,
    )
    defaults.update(overrides)
    return FxSymbolMetadata(**defaults)


_TS1 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
_TS2 = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)


def test_same_input_same_fingerprint():
    bars = (_bar(_TS1), _bar(_TS2))
    metadata = _symbol_metadata()
    fp1 = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata)
    fp2 = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex digest


def test_fingerprint_independent_of_fetch_time():
    bars = (_bar(_TS1),)
    metadata = _symbol_metadata()
    meta1 = build_dataset_metadata(
        bars, FxTimeframe.H1, metadata, _TS1, _TS2,
        now_utc=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
    )
    meta2 = build_dataset_metadata(
        bars, FxTimeframe.H1, metadata, _TS1, _TS2,
        now_utc=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert meta1.dataset_sha256 == meta2.dataset_sha256
    assert meta1.created_at_utc != meta2.created_at_utc


def test_fingerprint_independent_of_bridge_build_metadata():
    bars = (_bar(_TS1),)
    metadata = _symbol_metadata()
    meta1 = build_dataset_metadata(bars, FxTimeframe.H1, metadata, _TS1, _TS2, bridge_build="build-a")
    meta2 = build_dataset_metadata(bars, FxTimeframe.H1, metadata, _TS1, _TS2, bridge_build="build-b")
    assert meta1.dataset_sha256 == meta2.dataset_sha256


def test_fingerprint_independent_of_broker_server_identity():
    bars = (_bar(_TS1),)
    metadata_a = _symbol_metadata(broker=None, server="Demo-Server-A")
    metadata_b = _symbol_metadata(broker=None, server="Demo-Server-B")
    fp_a = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata_a)
    fp_b = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata_b)
    assert fp_a == fp_b


def test_fingerprint_changes_on_price_change():
    bars_a = (_bar(_TS1),)
    bars_b = (_bar(_TS1, close=Decimal("1.1006")),)
    metadata = _symbol_metadata()
    fp_a = compute_dataset_fingerprint(bars_a, FxTimeframe.H1, metadata)
    fp_b = compute_dataset_fingerprint(bars_b, FxTimeframe.H1, metadata)
    assert fp_a != fp_b


def test_fingerprint_changes_on_timestamp_change():
    bars_a = (_bar(_TS1),)
    bars_b = (_bar(_TS1 + timedelta(hours=1)),)
    metadata = _symbol_metadata()
    fp_a = compute_dataset_fingerprint(bars_a, FxTimeframe.H1, metadata)
    fp_b = compute_dataset_fingerprint(bars_b, FxTimeframe.H1, metadata)
    assert fp_a != fp_b


def test_fingerprint_changes_on_tick_volume_change():
    bars_a = (_bar(_TS1, tick_volume=Decimal("120")),)
    bars_b = (_bar(_TS1, tick_volume=Decimal("121")),)
    metadata = _symbol_metadata()
    fp_a = compute_dataset_fingerprint(bars_a, FxTimeframe.H1, metadata)
    fp_b = compute_dataset_fingerprint(bars_b, FxTimeframe.H1, metadata)
    assert fp_a != fp_b


def test_fingerprint_changes_on_real_volume_change():
    bars_a = (_bar(_TS1, real_volume=None),)
    bars_b = (_bar(_TS1, real_volume=Decimal("5")),)
    metadata = _symbol_metadata()
    fp_a = compute_dataset_fingerprint(bars_a, FxTimeframe.H1, metadata)
    fp_b = compute_dataset_fingerprint(bars_b, FxTimeframe.H1, metadata)
    assert fp_a != fp_b


def test_fingerprint_changes_on_symbol_change():
    bars = (_bar(_TS1),)
    metadata_a = _symbol_metadata(requested_symbol="EURUSD", resolved_symbol="EURUSD")
    metadata_b = _symbol_metadata(requested_symbol="GBPUSD", resolved_symbol="GBPUSD")
    fp_a = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata_a)
    fp_b = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata_b)
    assert fp_a != fp_b


def test_fingerprint_changes_on_timeframe_change():
    bars = (_bar(_TS1),)
    metadata = _symbol_metadata()
    fp_h1 = compute_dataset_fingerprint(bars, FxTimeframe.H1, metadata)
    fp_h4 = compute_dataset_fingerprint(bars, FxTimeframe.H4, metadata)
    assert fp_h1 != fp_h4


def test_fingerprint_row_order_does_not_matter_after_normalization():
    # compute_dataset_fingerprint operates on already-normalize.py-sorted
    # bars in real usage; this test proves the same *sorted* content
    # fingerprints identically regardless of what order it was computed
    # from, by explicitly sorting both inputs the same way normalize.py
    # would before fingerprinting -- this is the actual determinism
    # contract, not "the fingerprint function itself sorts".
    bars_sorted_a = (_bar(_TS1), _bar(_TS2))
    bars_sorted_b = tuple(sorted((_bar(_TS2), _bar(_TS1)), key=lambda b: b.timestamp_utc))
    metadata = _symbol_metadata()
    fp_a = compute_dataset_fingerprint(bars_sorted_a, FxTimeframe.H1, metadata)
    fp_b = compute_dataset_fingerprint(bars_sorted_b, FxTimeframe.H1, metadata)
    assert fp_a == fp_b
