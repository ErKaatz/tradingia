"""Tests for src/fx/data/mt5_provider.py using a mock ExecutionClient.

No real MT5/bridge access required -- see tests/fx/test_time_diagnostics.py
and PHASE5A_STATUS.md for the separately marked real-MT5 integration tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.base import (
    AccountSummary,
    AccountTradeMode,
    ExecutionTimeframe,
    HealthStatus,
    HistoryBar,
    HistoryResult,
    SymbolMetadata,
)
from src.fx.data.mt5_provider import FxProviderError, build_metadata_for_fetch, fetch_history


class _MockClient:
    def __init__(self, bars=(), symbol_metadata=None, account=None, bridge_build=None, raise_on_history=None):
        self._bars = bars
        self._symbol_metadata = symbol_metadata
        self._account = account
        self._bridge_build = bridge_build
        self._raise_on_history = raise_on_history

    def history(self, request):
        if self._raise_on_history is not None:
            raise self._raise_on_history
        return HistoryResult(symbol=request.symbol, bars=self._bars)

    def symbol_metadata(self, symbol):
        if self._symbol_metadata is None:
            raise ValueError("no metadata configured")
        return self._symbol_metadata

    def account(self):
        if self._account is None:
            raise ValueError("no account configured")
        return self._account

    def health(self):
        return HealthStatus(bridge_alive=True, terminal_connected=True, server_time=None, bridge_build=self._bridge_build)


def _bar(ts, **overrides):
    defaults = dict(
        symbol="EURUSD", timestamp=ts,
        open=Decimal("1.1000"), high=Decimal("1.1010"), low=Decimal("1.0990"), close=Decimal("1.1005"),
        tick_volume=Decimal("120"), real_volume=None, spread_points=10,
    )
    defaults.update(overrides)
    return HistoryBar(**defaults)


_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_fetch_history_normal_response():
    ts = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    client = _MockClient(bars=(_bar(ts),))
    fetch = fetch_history(client, "EURUSD", ExecutionTimeframe.H1, _START, _END, fetch_symbol_metadata=False, fetch_account=False)
    assert len(fetch.bars) == 1
    assert fetch.bars[0].timestamp_utc == ts


def test_fetch_history_empty_response_is_not_an_error():
    client = _MockClient(bars=())
    fetch = fetch_history(client, "EURUSD", ExecutionTimeframe.H1, _START, _END, fetch_symbol_metadata=False, fetch_account=False)
    assert fetch.bars == ()


def test_fetch_history_bridge_error_propagates():
    client = _MockClient(raise_on_history=ConnectionError("bridge unreachable"))
    with pytest.raises(ConnectionError):
        fetch_history(client, "EURUSD", ExecutionTimeframe.H1, _START, _END)


def test_fetch_history_invalid_timeframe_rejected_before_any_call():
    # ExecutionTimeframe is an enum; passing something not in it would
    # fail at the caller before construction, so this test instead
    # verifies start >= end is rejected without ever calling the client.
    class _ExplodingClient:
        def history(self, request):
            raise AssertionError("must not be called for an invalid range")

    with pytest.raises(FxProviderError, match="before"):
        fetch_history(_ExplodingClient(), "EURUSD", ExecutionTimeframe.H1, _END, _START)


def test_fetch_history_empty_symbol_rejected():
    class _ExplodingClient:
        def history(self, request):
            raise AssertionError("must not be called for an empty symbol")

    with pytest.raises(FxProviderError, match="symbol"):
        fetch_history(_ExplodingClient(), "  ", ExecutionTimeframe.H1, _START, _END)


def test_fetch_history_naive_datetime_rejected():
    class _ExplodingClient:
        def history(self, request):
            raise AssertionError("must not be called for a naive datetime")

    with pytest.raises(FxProviderError, match="timezone-aware"):
        fetch_history(_ExplodingClient(), "EURUSD", ExecutionTimeframe.H1, datetime(2026, 1, 1), _END)


def test_fetch_history_metadata_failure_does_not_fail_the_fetch():
    ts = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    client = _MockClient(bars=(_bar(ts),), symbol_metadata=None)  # metadata() raises
    fetch = fetch_history(client, "EURUSD", ExecutionTimeframe.H1, _START, _END, fetch_symbol_metadata=True, fetch_account=False)
    assert len(fetch.bars) == 1
    assert fetch.symbol_metadata_raw is None


def test_build_metadata_for_fetch_uses_symbol_metadata_and_account():
    ts = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    metadata = SymbolMetadata(
        symbol="EURUSD", volume_min=Decimal("0.01"), volume_step=Decimal("0.01"),
        volume_max=Decimal("100"), contract_size=Decimal("100000"), digits=5, point=Decimal("0.00001"),
        currency_base="EUR", currency_profit="USD",
    )
    account = AccountSummary(
        account_id="1", trade_mode=AccountTradeMode.DEMO, balance=Decimal("100"),
        equity=Decimal("100"), currency="USD", server="HFMarkets-Demo",
    )
    client = _MockClient(bars=(_bar(ts),), symbol_metadata=metadata, account=account, bridge_build="build-x")
    fetch = fetch_history(client, "EURUSD", ExecutionTimeframe.H1, _START, _END)
    dataset_metadata = build_metadata_for_fetch(fetch)
    assert dataset_metadata.resolved_symbol == "EURUSD"
    assert dataset_metadata.server == "HFMarkets-Demo"
    assert dataset_metadata.bridge_build == "build-x"
    assert dataset_metadata.volume_kind == "tick_volume"
    assert dataset_metadata.bar_count == 1
    assert len(dataset_metadata.dataset_sha256) == 64
