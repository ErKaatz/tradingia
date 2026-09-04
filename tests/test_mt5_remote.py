"""Tests for the Linux-side HTTP bridge client (FX Phase 0, Step 2).

No real network, no MetaTrader5, no third-party HTTP mocking library --
`_FakeTransport` is a tiny structural stand-in for `HttpTransport`
(satisfies the same shape `MT5RemoteExecutionClient` needs), and is
injected directly into the client under test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.base import AccountTradeMode, Environment, ExecutionTimeframe, HistoryRequest, Side
from src.execution.mt5_remote import (
    EXPECTED_API_VERSION,
    ExecutionAuthenticationError,
    ExecutionProtocolError,
    ExecutionRemoteError,
    ExecutionRequestError,
    ExecutionTimeoutError,
    ExecutionTransportError,
    HttpResponse,
    MT5RemoteExecutionClient,
    RemoteConfig,
)

TOKEN = "super-secret-token-value"
BRIDGE_URL = "http://192.168.56.10:8765"


@dataclass
class _FakeTransport:
    """Records every call and returns canned responses by path, or raises
    a preconfigured exception (simulating a transport-level failure)."""

    responses_by_path: dict[str, HttpResponse] = field(default_factory=dict)
    raise_for_path: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str], float]] = field(default_factory=list)
    post_calls: list[tuple[str, dict[str, str], float, dict]] = field(default_factory=list)

    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, headers, timeout))
        for path, exc in self.raise_for_path.items():
            if path in url:
                raise exc
        for path, response in self.responses_by_path.items():
            if path in url:
                return response
        raise AssertionError(f"no fake response configured for URL {url}")

    def post(self, url: str, headers: dict[str, str], timeout: float, json_body: dict) -> HttpResponse:
        self.post_calls.append((url, headers, timeout, json_body))
        self.calls.append((url, headers, timeout))
        for path, exc in self.raise_for_path.items():
            if path in url:
                raise exc
        for path, response in self.responses_by_path.items():
            if path in url:
                return response
        raise AssertionError(f"no fake response configured for URL {url}")


def _json_response(status_code: int, payload: dict) -> HttpResponse:
    text = json.dumps(payload)
    return HttpResponse(status_code=status_code, text=text, content_length=len(text.encode("utf-8")))


def _config(transport_timeout: float = 5.0) -> RemoteConfig:
    return RemoteConfig(bridge_url=BRIDGE_URL, api_token=TOKEN, timeout_seconds=transport_timeout)


VALID_HEALTH = {
    "api_version": "1",
    "bridge_alive": True,
    "terminal_connected": True,
    "server_time": "2026-09-02T12:00:00+00:00",
    "broker_name": "TestBroker",
}

VALID_TERMINAL = {
    "connected": True,
    "trade_allowed": True,
    "dlls_allowed": False,
    "name": "MetaTrader 5",
    "company": "TestBroker",
    "build": 6159,
}

VALID_ACCOUNT = {
    "account_id": "12345",
    "trade_mode": "demo",
    "balance": "1000.00",
    "equity": "1000.00",
    "currency": "USD",
    "trade_allowed": True,
    "trade_expert": True,
}

VALID_SYMBOL_METADATA = {
    "symbol": "EURUSD",
    "digits": 5,
    "point": "0.00001",
    "volume_min": "0.01",
    "volume_step": "0.01",
    "volume_max": "100",
    "trade_contract_size": "100000",
}

VALID_QUOTE = {
    "symbol": "EURUSD",
    "timestamp": "2026-09-02T12:00:00+00:00",
    "bid": "1.10001",
    "ask": "1.10003",
}

VALID_HISTORY_BAR = {
    "timestamp": "2026-09-02T12:00:00+00:00",
    "open": "1.10000",
    "high": "1.10010",
    "low": "1.09990",
    "close": "1.10005",
    "tick_volume": "120",
}


# 1. health válido.
def test_health_valid_response_parsed():
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, VALID_HEALTH)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    status = client.health()
    assert status.bridge_alive is True
    assert status.terminal_connected is True
    assert status.broker_name == "TestBroker"


# 2. API version correcta.
def test_health_accepts_matching_api_version():
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, VALID_HEALTH)})
    client = MT5RemoteExecutionClient(RemoteConfig(bridge_url=BRIDGE_URL, api_token=TOKEN, expected_api_version="1"), transport=transport)
    client.health()  # must not raise


# 3. API version incompatible rechazado.
def test_health_rejects_incompatible_api_version():
    payload = dict(VALID_HEALTH, api_version="2")
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(RemoteConfig(bridge_url=BRIDGE_URL, api_token=TOKEN, expected_api_version="1"), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="incompatible"):
        client.health()


# 3b. HealthStatus preserves api_version/bridge_version/bridge_build when present.
def test_health_preserves_version_and_build_fields():
    payload = dict(VALID_HEALTH, bridge_version="1", bridge_build="step4-2026-09-03")
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    status = client.health()
    assert status.api_version == "1"
    assert status.bridge_version == "1"
    assert status.bridge_build == "step4-2026-09-03"


# 3c. Missing bridge_build in the bridge's response must stay None -- never
# a fabricated/guessed value on the Linux side.
def test_health_missing_bridge_build_is_none_not_fabricated():
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, VALID_HEALTH)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    status = client.health()
    assert status.bridge_build is None
    assert status.bridge_version is None


# 4. auth header enviado.
def test_auth_header_sent_as_bearer_token():
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, VALID_HEALTH)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    client.health()
    assert len(transport.calls) == 1
    _, headers, _ = transport.calls[0]
    assert headers["Authorization"] == f"Bearer {TOKEN}"


# 5. token no aparece en repr.
def test_token_not_in_client_repr():
    transport = _FakeTransport()
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    assert TOKEN not in repr(client)


def test_token_not_in_config_repr():
    config = _config()
    assert TOKEN not in repr(config)
    assert "***" in repr(config)


# 6. timeout -> domain timeout error.
def test_timeout_raises_domain_timeout_error():
    transport = _FakeTransport(raise_for_path={"/v1/health": ExecutionTimeoutError("timed out")})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionTimeoutError):
        client.health()


# 7. connection failure -> domain transport error.
def test_connection_failure_raises_domain_transport_error():
    transport = _FakeTransport(raise_for_path={"/v1/health": ExecutionTransportError("connection refused")})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionTransportError):
        client.health()


# 8. 401/403 -> auth error.
@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_rejected_raises_domain_auth_error(status_code):
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=status_code, text="{}", content_length=2)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionAuthenticationError):
        client.health()


# 9. 400 -> remote/request error.
def test_400_raises_domain_request_error():
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=400, text="{}", content_length=2)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionRequestError):
        client.health()


# 10. 500 -> remote/server error.
def test_500_raises_domain_remote_error():
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=500, text="{}", content_length=2)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionRemoteError):
        client.health()


# 11. invalid JSON -> protocol error.
def test_invalid_json_raises_protocol_error():
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=200, text="{not json", content_length=9)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.health()


# 12. malformed health response -> protocol error.
@pytest.mark.parametrize(
    "broken_payload",
    [
        {},
        {"api_version": "1"},
        {"api_version": "1", "bridge_alive": "yes", "terminal_connected": True},
        {"api_version": "1", "bridge_alive": True, "terminal_connected": "no"},
    ],
)
def test_malformed_health_response_raises_protocol_error(broken_payload):
    transport = _FakeTransport(responses_by_path={"/v1/health": _json_response(200, broken_payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.health()


# 13. valid demo account parsed.
def test_valid_demo_account_parsed():
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, VALID_ACCOUNT)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.trade_mode is AccountTradeMode.DEMO
    assert account.balance == Decimal("1000.00")
    assert isinstance(account.balance, Decimal)


# 14. unknown trade_mode stays UNKNOWN.
def test_unknown_trade_mode_string_stays_unknown():
    payload = dict(VALID_ACCOUNT, trade_mode="something_new")
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.trade_mode is AccountTradeMode.UNKNOWN


# 15. missing trade_mode never becomes DEMO.
def test_missing_trade_mode_never_becomes_demo():
    payload = {k: v for k, v in VALID_ACCOUNT.items() if k != "trade_mode"}
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.trade_mode is AccountTradeMode.UNKNOWN
    assert account.trade_mode is not AccountTradeMode.DEMO


# 16. quote valid parsed with Decimal.
def test_valid_quote_parsed_with_decimal():
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, VALID_QUOTE)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    quote = client.quote("EURUSD")
    assert isinstance(quote.bid, Decimal)
    assert isinstance(quote.ask, Decimal)
    assert quote.bid == Decimal("1.10001")
    assert quote.timestamp.tzinfo is not None


# 17. ask < bid rejected.
def test_quote_ask_less_than_bid_rejected():
    payload = dict(VALID_QUOTE, bid="1.2000", ask="1.1000")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="ask"):
        client.quote("EURUSD")


# 18. zero/negative bid rejected.
@pytest.mark.parametrize("bad_bid", ["0", "-1.0"])
def test_quote_zero_or_negative_bid_rejected(bad_bid):
    payload = dict(VALID_QUOTE, bid=bad_bid, ask="1.2")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="bid"):
        client.quote("EURUSD")


def test_quote_zero_or_negative_ask_rejected():
    payload = dict(VALID_QUOTE, bid="1.0", ask="0")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="ask"):
        client.quote("EURUSD")


# 19. invalid timestamp rejected.
@pytest.mark.parametrize("bad_ts", ["not-a-timestamp", "2026-09-02", "2026-09-02T12:00:00"])
def test_quote_invalid_or_non_utc_timestamp_rejected(bad_ts):
    payload = dict(VALID_QUOTE, timestamp=bad_ts)
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.quote("EURUSD")


# GET /v1/symbols listing (Step 3 correction) -- client-side `symbols()`.
def test_symbols_listing_empty_is_valid():
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, {"symbols": []})})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    assert client.symbols() == ()


def test_symbols_listing_multiple_symbols_parsed():
    payload = {
        "symbols": [
            {"symbol": "EURUSD", "description": "Euro vs US Dollar", "visible": True, "trade_enabled": True},
            {"symbol": "GBPUSD", "description": None, "visible": False, "trade_enabled": None},
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    symbols = client.symbols()
    assert len(symbols) == 2
    assert symbols[0].symbol == "EURUSD"
    assert symbols[1].visible is False


@pytest.mark.parametrize("suffixed_name", ["EURUSDm", "EURUSD.a", "EURUSD_i"])
def test_symbols_listing_preserves_broker_specific_suffixed_names(suffixed_name):
    payload = {"symbols": [{"symbol": suffixed_name, "description": None, "visible": True, "trade_enabled": True}]}
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    symbols = client.symbols()
    assert symbols[0].symbol == suffixed_name


def test_symbols_listing_malformed_response_rejected():
    payload = {"symbols": [{"description": "missing symbol field", "visible": True}]}
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="symbol"):
        client.symbols()


def test_symbols_listing_missing_visible_field_rejected():
    payload = {"symbols": [{"symbol": "EURUSD", "description": None}]}
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="visible"):
        client.symbols()


def test_symbols_listing_not_a_list_rejected():
    payload = {"symbols": "not-a-list"}
    transport = _FakeTransport(responses_by_path={"/v1/symbols": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="list"):
        client.symbols()


def test_symbols_listing_backend_disconnected_raises_remote_error():
    transport = _FakeTransport(responses_by_path={"/v1/symbols": HttpResponse(status_code=502, text="{}", content_length=2)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionRemoteError):
        client.symbols()


# 20. symbol metadata Decimal parsing.
def test_symbol_metadata_decimal_parsing():
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, VALID_SYMBOL_METADATA)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    meta = client.symbol_metadata("EURUSD")
    assert isinstance(meta.volume_min, Decimal)
    assert meta.volume_min == Decimal("0.01")
    assert meta.digits == 5


# 21. missing volume_min handled fail-closed.
def test_symbol_metadata_missing_volume_min_fails_closed():
    payload = {k: v for k, v in VALID_SYMBOL_METADATA.items() if k != "volume_min"}
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="volume_min"):
        client.symbol_metadata("EURUSD")


def test_symbol_metadata_zero_volume_min_rejected():
    payload = dict(VALID_SYMBOL_METADATA, volume_min="0")
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.symbol_metadata("EURUSD")


def test_symbol_metadata_volume_min_greater_than_max_rejected():
    payload = dict(VALID_SYMBOL_METADATA, volume_min="200", volume_max="100")
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.symbol_metadata("EURUSD")


def test_symbol_metadata_response_symbol_mismatch_rejected():
    payload = dict(VALID_SYMBOL_METADATA, symbol="GBPUSD")
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="does not match"):
        client.symbol_metadata("EURUSD")


# 22. history valid parsed.
def test_history_valid_parsed():
    payload = {"bars": [VALID_HISTORY_BAR]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    result = client.history(request)
    assert len(result.bars) == 1
    assert isinstance(result.bars[0].close, Decimal)


# Step 3.1 correction: timeframe is now required and explicitly sent.


# 1. HistoryRequest M15 serializes `timeframe=M15`.
def test_history_request_m15_serializes_timeframe_query_param():
    payload = {"bars": []}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(
        symbol="EURUSD", timeframe=ExecutionTimeframe.M15,
        start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    client.history(request)
    called_url = transport.calls[0][0]
    assert "timeframe=M15" in called_url


# 2. H1 serializes `timeframe=H1`.
def test_history_request_h1_serializes_timeframe_query_param():
    payload = {"bars": []}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(
        symbol="EURUSD", timeframe=ExecutionTimeframe.H1,
        start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    client.history(request)
    called_url = transport.calls[0][0]
    assert "timeframe=H1" in called_url


# 3. Each allowed enum member has a valid MT5 mapping (bridge side).
def test_every_execution_timeframe_has_mt5_mapping():
    from mt5_bridge.backend import MT5_TIMEFRAME_ATTR_BY_NAME

    for tf in ExecutionTimeframe:
        assert tf.value in MT5_TIMEFRAME_ATTR_BY_NAME, f"{tf.value} has no MT5 mapping"


# 4. Unknown/invalid timeframe rejected (constructing the enum itself).
def test_unknown_timeframe_value_rejected():
    with pytest.raises(ValueError):
        ExecutionTimeframe("M2")


# 8. No silent fallback from unknown timeframe to M15 (HistoryRequest has no default).
def test_history_request_has_no_implicit_timeframe_default():
    import inspect

    sig = inspect.signature(HistoryRequest)
    assert sig.parameters["timeframe"].default is inspect.Parameter.empty


def test_history_request_requires_timeframe_positional_or_keyword():
    with pytest.raises(TypeError):
        HistoryRequest(symbol="EURUSD", start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))


# 9. history result keeps UTC timestamps regardless of timeframe.
def test_history_result_timestamps_stay_utc_for_h1():
    bar = dict(VALID_HISTORY_BAR, timestamp="2026-09-02T13:00:00+00:00")
    payload = {"bars": [bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.H1, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 3, tzinfo=timezone.utc))
    result = client.history(request)
    assert result.bars[0].timestamp.tzinfo == timezone.utc


# 23. invalid OHLC rejected.
def test_history_invalid_ohlc_rejected():
    bad_bar = dict(VALID_HISTORY_BAR, high="1.09000")  # high below open/close
    payload = {"bars": [bad_bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="high"):
        client.history(request)


def test_history_low_above_others_rejected():
    bad_bar = dict(VALID_HISTORY_BAR, low="1.20000")
    payload = {"bars": [bad_bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="low"):
        client.history(request)


# 24. unordered history rejected.
def test_history_unordered_bars_rejected():
    bar_later = dict(VALID_HISTORY_BAR, timestamp="2026-09-02T12:00:00+00:00")
    bar_earlier = dict(VALID_HISTORY_BAR, timestamp="2026-09-02T11:00:00+00:00")
    payload = {"bars": [bar_later, bar_earlier]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="not strictly increasing"):
        client.history(request)


def test_history_duplicate_timestamp_rejected():
    bar = dict(VALID_HISTORY_BAR)
    payload = {"bars": [bar, dict(bar)]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="not strictly increasing"):
        client.history(request)


def test_history_missing_volume_rejected():
    bad_bar = {k: v for k, v in VALID_HISTORY_BAR.items() if k != "tick_volume"}
    payload = {"bars": [bad_bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="volume"):
        client.history(request)


# 25. positions parsing.
def test_positions_parsing():
    payload = {
        "positions": [
            {"position_id": "P1", "symbol": "EURUSD", "side": "buy", "volume": "0.01", "open_price": "1.1000"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/positions": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    positions = client.positions()
    assert len(positions) == 1
    assert positions[0].volume == Decimal("0.01")


def test_positions_zero_volume_rejected():
    payload = {
        "positions": [
            {"position_id": "P1", "symbol": "EURUSD", "side": "buy", "volume": "0", "open_price": "1.1000"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/positions": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="volume"):
        client.positions()


def test_positions_invalid_side_rejected():
    payload = {
        "positions": [
            {"position_id": "P1", "symbol": "EURUSD", "side": "long", "volume": "0.01", "open_price": "1.1000"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/positions": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="side"):
        client.positions()


# 26. orders parsing.
def test_orders_parsing():
    payload = {
        "orders": [
            {"client_order_id": "C1", "symbol": "EURUSD", "side": "buy", "volume": "0.01", "status": "accepted"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert len(orders) == 1
    assert orders[0].status.value == "accepted"


def test_orders_unknown_status_maps_to_error_not_crash():
    payload = {
        "orders": [
            {"client_order_id": "C1", "symbol": "EURUSD", "side": "buy", "volume": "0.01", "status": "something_weird"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert orders[0].status.value == "error"


# Step 3 correction 3.1: external MT5 order -> client_order_id is None.
def test_external_order_client_order_id_null_parses_to_none():
    payload = {
        "orders": [
            {"client_order_id": None, "symbol": "EURUSD", "side": "sell", "volume": "0.02", "status": "accepted", "broker_order_id": "99"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert orders[0].client_order_id is None


# broker_order_id preserves the MT5 ticket regardless of client_order_id.
def test_broker_order_id_preserved_for_external_order():
    payload = {
        "orders": [
            {"client_order_id": None, "symbol": "EURUSD", "side": "sell", "volume": "0.02", "status": "accepted", "broker_order_id": "424242"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert orders[0].broker_order_id == "424242"


# TradingIA-originated order can carry a real client_order_id.
def test_tradingia_owned_order_keeps_real_client_order_id():
    payload = {
        "orders": [
            {"client_order_id": "tia-abc-123", "symbol": "EURUSD", "side": "buy", "volume": "0.01", "status": "accepted", "broker_order_id": "55"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert orders[0].client_order_id == "tia-abc-123"


# missing client_order_id must never become the string "None".
def test_missing_client_order_id_field_raises_not_defaults():
    payload = {
        "orders": [
            {"symbol": "EURUSD", "side": "buy", "volume": "0.01", "status": "accepted"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="client_order_id"):
        client.orders()


def test_client_order_id_wrong_type_rejected():
    payload = {
        "orders": [
            {"client_order_id": 12345, "symbol": "EURUSD", "side": "buy", "volume": "0.01", "status": "accepted"}
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="client_order_id"):
        client.orders()


# orders parser distinguishes external vs owned within the same listing.
def test_orders_parser_distinguishes_external_and_owned_in_same_listing():
    payload = {
        "orders": [
            {"client_order_id": None, "symbol": "EURUSD", "side": "sell", "volume": "0.02", "status": "accepted", "broker_order_id": "1"},
            {"client_order_id": "tia-xyz", "symbol": "GBPUSD", "side": "buy", "volume": "0.01", "status": "accepted", "broker_order_id": "2"},
        ]
    }
    transport = _FakeTransport(responses_by_path={"/v1/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    orders = client.orders()
    assert orders[0].client_order_id is None
    assert orders[1].client_order_id == "tia-xyz"


# 27. token not leaked in raised exceptions.
def test_token_not_leaked_in_transport_error_message():
    transport = _FakeTransport(raise_for_path={"/v1/health": ExecutionTransportError("failed to reach bridge")})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionTransportError) as excinfo:
        client.health()
    assert TOKEN not in str(excinfo.value)


def test_token_not_leaked_in_auth_error_message():
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=401, text="{}", content_length=2)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionAuthenticationError) as excinfo:
        client.health()
    assert TOKEN not in str(excinfo.value)


# 28. URL building cannot inject symbol path traversal.
@pytest.mark.parametrize("bad_symbol", ["../orders", "..%2Forders", "a/b", "a\\b", "", "   "])
def test_symbol_path_traversal_rejected(bad_symbol):
    transport = _FakeTransport()
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ValueError):
        client.quote(bad_symbol)
    assert transport.calls == []  # must fail before any request is sent


def test_symbol_with_special_characters_is_percent_encoded():
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EUR%23USD": _json_response(200, dict(VALID_QUOTE, symbol="EUR#USD"))})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    quote = client.quote("EUR#USD")
    assert quote.symbol == "EUR#USD"


# 29. non-UTC timestamps normalized/rejected deterministically.
def test_naive_timestamp_rejected_not_silently_assumed_utc():
    payload = dict(VALID_QUOTE, timestamp="2026-09-02T12:00:00")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="UTC offset"):
        client.quote("EURUSD")


def test_non_utc_offset_timestamp_normalized_to_utc():
    payload = dict(VALID_QUOTE, timestamp="2026-09-02T09:00:00-03:00")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    quote = client.quote("EURUSD")
    assert quote.timestamp == datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def test_zulu_suffix_timestamp_parsed_as_utc():
    payload = dict(VALID_QUOTE, timestamp="2026-09-02T12:00:00Z")
    transport = _FakeTransport(responses_by_path={"/v1/quotes/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    quote = client.quote("EURUSD")
    assert quote.timestamp.tzinfo == timezone.utc


# 30. unknown/unexpected enum values map to UNKNOWN rather than crashing.
def test_unknown_broker_provided_trade_mode_does_not_crash():
    payload = dict(VALID_ACCOUNT, trade_mode=None)
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.trade_mode is AccountTradeMode.UNKNOWN


# Additional risk-driven tests


def test_response_over_max_size_rejected():
    huge_len = 10_000_000
    transport = _FakeTransport(
        responses_by_path={"/v1/health": HttpResponse(status_code=200, text=json.dumps(VALID_HEALTH), content_length=huge_len)}
    )
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="size"):
        client.health()


def test_place_order_posts_to_demo_orders_endpoint_only():
    """Step 4: place_order is now implemented, but must POST exclusively
    to /v1/demo/orders -- never a /v1/live/... path."""
    from src.execution.base import ActionKind, OrderRequest, OrderType, Side

    payload = {
        "client_order_id": "c1", "status": "filled", "broker_order_id": "1", "deal_id": "1", "position_id": "1",
        "requested_volume": "0.01", "filled_volume": "0.01", "observed_bid": "1.09998", "observed_ask": "1.10002",
        "reference_price": "1.10002", "fill_price": "1.10002", "slippage": "0",
        "mt5_retcode": 10009, "timestamp": "2026-09-03T00:00:00+00:00", "idempotent_replay": False, "error_message": None,
    }
    transport = _FakeTransport(responses_by_path={"/v1/demo/orders": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = OrderRequest(
        client_order_id="c1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
    )
    result = client.place_order(request)
    assert result.client_order_id == "c1"
    assert result.status.value == "filled"
    called_url = transport.post_calls[0][0]
    assert called_url.endswith("/v1/demo/orders")
    assert "/v1/live" not in called_url
    body = transport.post_calls[0][3]
    assert body == {"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}


def test_remote_config_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="scheme"):
        RemoteConfig(bridge_url="file:///etc/passwd", api_token=TOKEN)


def test_remote_config_rejects_embedded_credentials_in_url():
    with pytest.raises(ValueError, match="credentials"):
        RemoteConfig(bridge_url="http://user:pass@192.168.1.5:8765", api_token=TOKEN)


def test_remote_config_rejects_empty_token():
    with pytest.raises(ValueError, match="api_token"):
        RemoteConfig(bridge_url=BRIDGE_URL, api_token="")


def test_remote_config_rejects_non_positive_timeout():
    with pytest.raises(ValueError, match="timeout"):
        RemoteConfig(bridge_url=BRIDGE_URL, api_token=TOKEN, timeout_seconds=0)


def test_remote_config_from_env_reads_token(monkeypatch):
    monkeypatch.setenv("MT5_REMOTE_TOKEN", TOKEN)
    config = RemoteConfig.from_env(bridge_url=BRIDGE_URL)
    assert config.api_token == TOKEN


def test_remote_config_from_env_missing_token_raises(monkeypatch):
    monkeypatch.delenv("MT5_REMOTE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="MT5_REMOTE_TOKEN"):
        RemoteConfig.from_env(bridge_url=BRIDGE_URL)


def test_history_bar_missing_tick_volume_rejected_not_defaulted_from_generic_volume():
    # tick_volume must never be silently backfilled from a generic
    # "volume" key -- that key does not honestly mean the same thing
    # (see HistoryBar's docstring). A bar missing tick_volume is rejected.
    bar = {k: v for k, v in VALID_HISTORY_BAR.items() if k != "tick_volume"}
    bar["volume"] = "50"
    payload = {"bars": [bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="tick_volume"):
        client.history(request)


def test_history_bar_tick_volume_and_real_volume_kept_distinct():
    bar = dict(VALID_HISTORY_BAR, real_volume="7", spread=12)
    payload = {"bars": [bar]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    result = client.history(request)
    bar_out = result.bars[0]
    assert bar_out.tick_volume == Decimal("120")
    assert bar_out.real_volume == Decimal("7")
    assert bar_out.spread_points == 12


def test_history_bar_real_volume_absent_is_none_not_an_error():
    # FX OTC symbols routinely report no real_volume; this must not be
    # treated as a data error.
    payload = {"bars": [VALID_HISTORY_BAR]}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    result = client.history(request)
    assert result.bars[0].real_volume is None


def test_history_bars_not_a_list_rejected():
    payload = {"bars": "not-a-list"}
    transport = _FakeTransport(responses_by_path={"/v1/history/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    request = HistoryRequest(symbol="EURUSD", timeframe=ExecutionTimeframe.M15, start=datetime(2026, 9, 1, tzinfo=timezone.utc), end=datetime(2026, 9, 2, tzinfo=timezone.utc))
    with pytest.raises(ExecutionProtocolError, match="list"):
        client.history(request)


def test_top_level_response_not_a_json_object_rejected():
    transport = _FakeTransport(responses_by_path={"/v1/health": HttpResponse(status_code=200, text="[1, 2, 3]", content_length=9)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError, match="JSON object"):
        client.health()


# --------------------------------------------------------------------------
# time_diagnostics (FX Phase 0, "quote has a timestamp in the future")
# --------------------------------------------------------------------------

VALID_TIME_DIAGNOSTICS = {
    "symbol": "EURUSD",
    "bridge_time_utc": "2026-09-03T12:00:00+00:00",
    "mt5_tick_time_utc": "2026-09-03T12:00:00+00:00",
    "quote_age_seconds": 0.0,
    "quote_future_skew_seconds": 0.0,
}


def test_time_diagnostics_parses_all_three_clocks():
    transport = _FakeTransport(responses_by_path={"/v1/time-diagnostics/EURUSD": _json_response(200, VALID_TIME_DIAGNOSTICS)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    diag = client.time_diagnostics("EURUSD")
    assert diag.symbol == "EURUSD"
    assert diag.bridge_time_utc == datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    assert diag.mt5_tick_time_utc == datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
    assert diag.linux_client_utc is not None


def test_time_diagnostics_computes_skews_from_raw_clocks():
    payload = dict(
        VALID_TIME_DIAGNOSTICS,
        bridge_time_utc="2026-09-03T12:00:05+00:00",
        mt5_tick_time_utc="2026-09-03T12:00:08+00:00",
    )
    transport = _FakeTransport(responses_by_path={"/v1/time-diagnostics/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    diag = client.time_diagnostics("EURUSD")
    # tick is 3s ahead of bridge, regardless of what linux_client_utc is.
    assert diag.tick_bridge_skew_seconds == pytest.approx(3.0)


def test_time_diagnostics_no_tick_available_fields_are_none():
    payload = dict(VALID_TIME_DIAGNOSTICS, mt5_tick_time_utc=None, quote_age_seconds=None, quote_future_skew_seconds=None)
    transport = _FakeTransport(responses_by_path={"/v1/time-diagnostics/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    diag = client.time_diagnostics("EURUSD")
    assert diag.mt5_tick_time_utc is None
    assert diag.tick_client_skew_seconds is None
    assert diag.tick_bridge_skew_seconds is None
    assert diag.quote_age_seconds_per_client is None
    assert diag.quote_age_seconds_per_bridge is None


def test_time_diagnostics_missing_bridge_time_utc_rejected():
    payload = {k: v for k, v in VALID_TIME_DIAGNOSTICS.items() if k != "bridge_time_utc"}
    transport = _FakeTransport(responses_by_path={"/v1/time-diagnostics/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionProtocolError):
        client.time_diagnostics("EURUSD")


def test_resolve_received_attempt_posts_to_narrow_reconciliation_endpoint():
    payload = {
        "state": "ok",
        "checked_at": "2026-09-03T14:10:00+00:00",
        "details": [],
    }
    transport = _FakeTransport(
        responses_by_path={
            "/v1/reconciliation/resolve-received/abc-123": _json_response(200, payload)
        }
    )
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    report = client.resolve_received_attempt("abc-123")
    assert report.state.value == "ok"
    assert len(transport.post_calls) == 1
    assert transport.post_calls[0][0].endswith("/v1/reconciliation/resolve-received/abc-123")
    assert transport.post_calls[0][3] == {"confirm_abort_before_submission": True}


def test_resolve_received_attempt_rejects_empty_client_order_id_without_http():
    transport = _FakeTransport()
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ExecutionRequestError):
        client.resolve_received_attempt("")
    assert transport.post_calls == []


def test_terminal_permissions_parsed():
    transport = _FakeTransport(responses_by_path={"/v1/terminal": _json_response(200, VALID_TERMINAL)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    terminal = client.terminal()
    assert terminal.connected is True
    assert terminal.trade_allowed is True
    assert terminal.build == 6159


def test_account_permission_flags_parsed():
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, VALID_ACCOUNT)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.trade_allowed is True
    assert account.trade_expert is True


def test_account_server_parsed_when_present():
    payload = dict(VALID_ACCOUNT, server="HFMarketsGlobal-Demo2")
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.server == "HFMarketsGlobal-Demo2"


def test_account_server_absent_is_none_not_error():
    transport = _FakeTransport(responses_by_path={"/v1/account": _json_response(200, VALID_ACCOUNT)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    account = client.account()
    assert account.server is None


def test_symbol_metadata_currency_and_tick_fields_parsed_when_present():
    payload = dict(
        VALID_SYMBOL_METADATA,
        trade_tick_size="0.00001",
        trade_tick_value="1.0",
        currency_base="EUR",
        currency_profit="USD",
        currency_margin="EUR",
    )
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    metadata = client.symbol_metadata("EURUSD")
    assert metadata.tick_size == Decimal("0.00001")
    assert metadata.tick_value == Decimal("1.0")
    assert metadata.currency_base == "EUR"
    assert metadata.currency_profit == "USD"
    assert metadata.currency_margin == "EUR"


def test_symbol_metadata_currency_and_tick_fields_absent_are_none_not_error():
    transport = _FakeTransport(responses_by_path={"/v1/symbols/EURUSD": _json_response(200, VALID_SYMBOL_METADATA)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    metadata = client.symbol_metadata("EURUSD")
    assert metadata.tick_size is None
    assert metadata.tick_value is None
    assert metadata.currency_base is None
    assert metadata.currency_profit is None
    assert metadata.currency_margin is None


def test_profit_calc_valid_parsed():
    payload = {"symbol": "EURUSD", "side": "buy", "volume": "0.01", "price_open": "1.1000", "price_close": "1.1050", "profit": "5.0"}
    transport = _FakeTransport(responses_by_path={"/v1/profit-calc/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    profit = client.profit_calc("EURUSD", Side.BUY, Decimal("0.01"), Decimal("1.1000"), Decimal("1.1050"))
    assert profit == Decimal("5.0")


def test_profit_calc_serializes_query_params():
    payload = {"profit": "5.0"}
    transport = _FakeTransport(responses_by_path={"/v1/profit-calc/EURUSD": _json_response(200, payload)})
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    client.profit_calc("EURUSD", Side.SELL, Decimal("0.02"), Decimal("1.2000"), Decimal("1.1950"))
    url = transport.calls[-1][0]
    assert "side=sell" in url
    assert "volume=0.02" in url
    assert "price_open=1.2000" in url
    assert "price_close=1.1950" in url


def test_profit_calc_rejects_non_positive_volume():
    transport = _FakeTransport()
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ValueError):
        client.profit_calc("EURUSD", Side.BUY, Decimal("0"), Decimal("1.1000"), Decimal("1.1050"))


def test_profit_calc_rejects_non_positive_prices():
    transport = _FakeTransport()
    client = MT5RemoteExecutionClient(_config(), transport=transport)
    with pytest.raises(ValueError):
        client.profit_calc("EURUSD", Side.BUY, Decimal("0.01"), Decimal("-1.1000"), Decimal("1.1050"))
