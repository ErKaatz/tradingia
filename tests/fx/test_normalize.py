"""Tests for src/fx/data/normalize.py: determinism, sorting, timezone
handling, duplicate policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.execution.base import AccountSummary, AccountTradeMode, HistoryBar, SymbolMetadata
from src.fx.data.normalize import normalize_bar, normalize_bars, normalize_symbol_metadata


def _history_bar(ts: datetime, **overrides) -> HistoryBar:
    defaults = dict(
        symbol="EURUSD",
        timestamp=ts,
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0990"),
        close=Decimal("1.1005"),
        tick_volume=Decimal("120"),
        real_volume=None,
        spread_points=10,
    )
    defaults.update(overrides)
    return HistoryBar(**defaults)


def test_normalize_bar_preserves_values():
    ts = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bar = normalize_bar(_history_bar(ts))
    assert bar.timestamp_utc == ts
    assert bar.close == Decimal("1.1005")
    assert bar.tick_volume == Decimal("120")
    assert bar.real_volume is None
    assert bar.spread_points == 10


def test_normalize_bar_converts_non_utc_to_utc():
    offset_tz = timezone(timedelta(hours=3))
    ts_offset = datetime(2026, 1, 5, 13, 0, tzinfo=offset_tz)  # == 10:00 UTC
    bar = normalize_bar(_history_bar(ts_offset))
    assert bar.timestamp_utc == datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    assert bar.timestamp_utc.utcoffset() == timedelta(0)


def test_normalize_bars_is_deterministic():
    ts1 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)
    bars_in_order = (_history_bar(ts1), _history_bar(ts2))
    bars_reversed = (_history_bar(ts2), _history_bar(ts1))

    result_a = normalize_bars(bars_in_order)
    result_b = normalize_bars(bars_reversed)

    assert [b.timestamp_utc for b in result_a] == [b.timestamp_utc for b in result_b]
    assert result_a == result_b


def test_normalize_bars_sorts_ascending():
    ts1 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 5, 11, 0, tzinfo=timezone.utc)
    ts3 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    bars = (_history_bar(ts2), _history_bar(ts3), _history_bar(ts1))
    result = normalize_bars(bars)
    assert [b.timestamp_utc for b in result] == [ts1, ts2, ts3]


def test_normalize_bars_keeps_duplicates_for_validation_to_catch():
    ts = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bars = (_history_bar(ts), _history_bar(ts))
    result = normalize_bars(bars)
    assert len(result) == 2


def _symbol_metadata(**overrides) -> SymbolMetadata:
    defaults = dict(
        symbol="EURUSD",
        volume_min=Decimal("0.01"),
        volume_step=Decimal("0.01"),
        volume_max=Decimal("100"),
        contract_size=Decimal("100000"),
        digits=5,
        point=Decimal("0.00001"),
    )
    defaults.update(overrides)
    return SymbolMetadata(**defaults)


def test_normalize_symbol_metadata_full():
    metadata = _symbol_metadata(
        tick_size=Decimal("0.00001"),
        tick_value=Decimal("1.0"),
        currency_base="EUR",
        currency_profit="USD",
        currency_margin="EUR",
    )
    account = AccountSummary(
        account_id="1", trade_mode=AccountTradeMode.DEMO, balance=Decimal("100"),
        equity=Decimal("100"), currency="USD", server="HFMarkets-Demo",
    )
    result = normalize_symbol_metadata("EURUSD", metadata, account, broker=None)
    assert result.resolved_symbol == "EURUSD"
    assert result.currency_base == "EUR"
    assert result.server == "HFMarkets-Demo"


def test_normalize_symbol_metadata_none_produces_mostly_null_record():
    result = normalize_symbol_metadata("EURUSD", None, None, broker=None)
    assert result.requested_symbol == "EURUSD"
    assert result.resolved_symbol == "EURUSD"
    assert result.digits is None
    assert result.server is None


def test_normalize_symbol_metadata_missing_account_leaves_server_none():
    metadata = _symbol_metadata()
    result = normalize_symbol_metadata("EURUSD", metadata, account=None, broker=None)
    assert result.server is None
    assert result.resolved_symbol == "EURUSD"
