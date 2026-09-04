"""Tests for the read-only FastAPI bridge (FX Phase 0, Step 3).

Uses FastAPI's `TestClient` (ASGI in-process, no real socket) with
`FakeMT5Backend` -- no MetaTrader5 import anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from mt5_bridge.app import create_app
from mt5_bridge.backend import (
    BackendAccountInfo,
    BackendBar,
    BackendOrder,
    BackendPosition,
    BackendSymbolInfo,
    BackendTerminalInfo,
    BackendTick,
    FakeMT5Backend,
)
from mt5_bridge.config import BridgeConfig

TOKEN = "bridge-test-token"


def D(x) -> Decimal:
    """Test convenience: build a `Decimal` the same way real (clean)
    backend values are constructed, so fixtures below don't reintroduce
    float literals into fields the Step 3.1 correction typed as `Decimal`.
    """

    return Decimal(str(x))


def _config(**overrides) -> BridgeConfig:
    defaults = dict(host="127.0.0.1", port=8765, api_token=TOKEN)
    defaults.update(overrides)
    return BridgeConfig(**defaults)


def _client(backend: FakeMT5Backend | None = None, config: BridgeConfig | None = None, store=None) -> TestClient:
    from mt5_bridge.store import BridgeStore

    backend = backend if backend is not None else FakeMT5Backend()
    config = config if config is not None else _config()
    store = store if store is not None else BridgeStore(":memory:")
    app = create_app(backend, config, store=store)
    return TestClient(app)


def _demo_ready_client(backend: FakeMT5Backend | None = None, config: BridgeConfig | None = None):
    """A client backed by a store that has already run reconciliation
    (state OK) and a backend with a tradable EURUSD symbol + fresh tick
    -- the common starting point for write-path tests."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from mt5_bridge.backend import BackendSymbolInfo, BackendTick
    from mt5_bridge.reconciliation import run_reconciliation
    from mt5_bridge.store import BridgeStore

    backend = backend if backend is not None else FakeMT5Backend()
    if backend.symbol_info("EURUSD") is None:
        backend.set_symbol("EURUSD", BackendSymbolInfo(
            name="EURUSD", description=None, digits=5, point=Decimal("0.00001"),
            volume_min=Decimal("0.01"), volume_step=Decimal("0.01"), volume_max=Decimal("60"),
            trade_contract_size=Decimal("100000"), trade_tick_size=Decimal("0.00001"), trade_tick_value=Decimal("1"),
            trade_enabled=True, visible=True, filling_mode=3,
        ))
    if backend.symbol_info_tick("EURUSD") is None:
        backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=Decimal("1.1000"), ask=Decimal("1.1002")))
    store = BridgeStore(":memory:")
    run_reconciliation(store, backend)
    config = config if config is not None else _config()
    client = _client(backend=backend, config=config, store=store)
    return client, backend, store


def _auth_headers(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# 1. health auth valid.
def test_health_with_valid_auth():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "1"
    assert body["bridge_alive"] is True
    assert body["terminal_connected"] is True


# 2. missing auth rejected.
def test_missing_auth_rejected():
    client = _client()
    resp = client.get("/v1/health")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# 3. invalid auth rejected.
def test_invalid_auth_rejected():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers("wrong-token"))
    assert resp.status_code == 403


# 4. token not leaked.
def test_token_not_leaked_in_error_response():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers("wrong-token"))
    assert TOKEN not in resp.text
    assert "wrong-token" not in resp.text


# 5. request id generated.
def test_request_id_generated_when_absent():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers())
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0


# 6. request id echoed.
def test_request_id_echoed_when_provided():
    client = _client()
    headers = _auth_headers()
    headers["X-Request-ID"] = "my-request-123"
    resp = client.get("/v1/health", headers=headers)
    assert resp.headers["X-Request-ID"] == "my-request-123"


# 7. backend disconnected health.
def test_backend_disconnected_health_reports_bridge_alive_but_not_connected():
    backend = FakeMT5Backend()
    backend.connected = False
    client = _client(backend=backend)
    resp = client.get("/v1/health", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["bridge_alive"] is True
    assert body["terminal_connected"] is False


# 8. backend disconnected account -> appropriate error.
def test_account_error_when_backend_raises():
    backend = FakeMT5Backend()
    backend.account = None
    client = _client(backend=backend)
    resp = client.get("/v1/account", headers=_auth_headers())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "backend_unavailable"


# 9. demo account mapping.
def test_demo_account_mapping():
    client = _client()
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert body["trade_mode"] == "demo"
    assert body["environment"] == "demo"


def test_live_account_mapping():
    backend = FakeMT5Backend()
    backend.account = BackendAccountInfo(
        login=1, trade_mode_code=2, server="Broker-Live", currency="USD", balance=D(100.0), equity=D(100.0), margin=D(0.0), margin_free=D(100.0)
    )
    client = _client(backend=backend)
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert body["trade_mode"] == "live"
    assert body["environment"] == "live"


# 10. unknown trade mode -> UNKNOWN.
def test_unknown_trade_mode_code_maps_to_unknown():
    backend = FakeMT5Backend()
    backend.account = BackendAccountInfo(
        login=1, trade_mode_code=99, server="X", currency="USD", balance=D(1.0), equity=D(1.0), margin=D(0.0), margin_free=D(1.0)
    )
    client = _client(backend=backend)
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert body["trade_mode"] == "unknown"
    assert body["environment"] == "unknown"


def test_missing_trade_mode_code_maps_to_unknown_not_demo():
    backend = FakeMT5Backend()
    backend.account = BackendAccountInfo(
        login=1, trade_mode_code=None, server="X", currency="USD", balance=D(1.0), equity=D(1.0), margin=D(0.0), margin_free=D(1.0)
    )
    client = _client(backend=backend)
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert body["trade_mode"] == "unknown"
    assert body["environment"] != "demo"


# 11. account decimal serialized deterministically.
def test_account_decimals_serialized_as_strings():
    client = _client()
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert isinstance(body["balance"], str)
    assert body["balance"] == "1000.00"
    assert isinstance(body["equity"], str)


# 12. valid symbol metadata.
def test_valid_symbol_metadata():
    backend = FakeMT5Backend()
    backend.set_symbol(
        "EURUSD",
        BackendSymbolInfo(
            name="EURUSD", description="Euro vs US Dollar", digits=5, point=D(0.00001),
            volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
            trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
        ),
    )
    client = _client(backend=backend)
    resp = client.get("/v1/symbols/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "EURUSD"
    assert body["volume_min"] == "0.01"


def test_symbol_metadata_includes_currency_fields_when_reported():
    backend = FakeMT5Backend()
    backend.set_symbol(
        "EURUSD",
        BackendSymbolInfo(
            name="EURUSD", description="Euro vs US Dollar", digits=5, point=D(0.00001),
            volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
            trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
            currency_base="EUR", currency_profit="USD", currency_margin="EUR",
        ),
    )
    client = _client(backend=backend)
    resp = client.get("/v1/symbols/EURUSD", headers=_auth_headers())
    body = resp.json()
    assert body["currency_base"] == "EUR"
    assert body["currency_profit"] == "USD"
    assert body["currency_margin"] == "EUR"


def test_symbol_metadata_currency_fields_absent_are_null_not_error():
    backend = FakeMT5Backend()
    backend.set_symbol(
        "EURUSD",
        BackendSymbolInfo(
            name="EURUSD", description=None, digits=5, point=D(0.00001),
            volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
            trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
        ),
    )
    client = _client(backend=backend)
    resp = client.get("/v1/symbols/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["currency_base"] is None
    assert body["currency_profit"] is None
    assert body["currency_margin"] is None


# 13. missing symbol.
def test_missing_symbol_returns_404():
    client = _client()
    resp = client.get("/v1/symbols/NOPE", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# GET /v1/symbols (listing) -- Step 3 correction.
def test_symbols_listing_empty_is_valid():
    client = _client()
    resp = client.get("/v1/symbols", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["symbols"] == []


def test_symbols_listing_multiple_symbols():
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description="Euro vs US Dollar", digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
        trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
    ))
    backend.set_symbol("GBPUSD", BackendSymbolInfo(
        name="GBPUSD", description="Pound vs US Dollar", digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(50.0), trade_contract_size=D(100000.0),
        trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
    ))
    client = _client(backend=backend)
    resp = client.get("/v1/symbols", headers=_auth_headers())
    body = resp.json()
    names = {s["symbol"] for s in body["symbols"]}
    assert names == {"EURUSD", "GBPUSD"}


def test_symbols_listing_reports_broker_specific_suffixed_names_verbatim():
    """Broker-specific naming conventions (EURUSDm, EURUSD.a, ...) must be
    reported exactly as the backend provides them -- no normalization or
    guessing that a suffixed name "is" the bare symbol."""
    backend = FakeMT5Backend()
    for name in ("EURUSDm", "EURUSD.a", "EURUSD_i"):
        backend.set_symbol(name, BackendSymbolInfo(
            name=name, description=None, digits=5, point=D(0.00001),
            volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
            trade_tick_size=None, trade_tick_value=None, trade_enabled=True, visible=True,
        ))
    client = _client(backend=backend)
    resp = client.get("/v1/symbols", headers=_auth_headers())
    names = {s["symbol"] for s in resp.json()["symbols"]}
    assert names == {"EURUSDm", "EURUSD.a", "EURUSD_i"}


def test_symbols_listing_entry_shape_is_lightweight():
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description="Euro vs US Dollar", digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
        trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
    ))
    client = _client(backend=backend)
    resp = client.get("/v1/symbols", headers=_auth_headers())
    entry = resp.json()["symbols"][0]
    assert set(entry.keys()) == {"symbol", "description", "visible", "trade_enabled"}
    assert "volume_min" not in entry


def test_symbols_listing_backend_error_mapped_to_502():
    backend = FakeMT5Backend()
    backend.raise_on_symbols_get = True
    client = _client(backend=backend)
    resp = client.get("/v1/symbols", headers=_auth_headers())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "backend_unavailable"


def test_symbols_listing_requires_auth():
    client = _client()
    resp = client.get("/v1/symbols")
    assert resp.status_code == 401


def test_symbols_route_does_not_shadow_single_symbol_route():
    """`/v1/symbols` (list) and `/v1/symbols/{symbol}` must resolve to
    different handlers -- a routing mistake here could make a literal
    symbol named e.g. nothing collide with the listing route."""
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description=None, digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
        trade_tick_size=None, trade_tick_value=None, trade_enabled=True, visible=True,
    ))
    client = _client(backend=backend)
    list_resp = client.get("/v1/symbols", headers=_auth_headers())
    single_resp = client.get("/v1/symbols/EURUSD", headers=_auth_headers())
    assert "symbols" in list_resp.json()
    assert list_resp.json() != single_resp.json()
    assert "volume_min" in single_resp.json()


# 14. valid quote.
def test_valid_quote():
    backend = FakeMT5Backend()
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime(2026, 9, 2, 12, tzinfo=timezone.utc), bid=D(1.1000), ask=D(1.1002)))
    client = _client(backend=backend)
    resp = client.get("/v1/quotes/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["bid"] == "1.1"
    assert body["ask"] == "1.1002"


def test_quote_missing_tick_returns_404():
    client = _client()
    resp = client.get("/v1/quotes/EURUSD", headers=_auth_headers())
    assert resp.status_code == 404


# 15. invalid bid/ask rejected.
def test_quote_zero_bid_rejected():
    backend = FakeMT5Backend()
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime(2026, 9, 2, tzinfo=timezone.utc), bid=D(0.0), ask=D(1.1)))
    client = _client(backend=backend)
    resp = client.get("/v1/quotes/EURUSD", headers=_auth_headers())
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "backend_unavailable"


def test_quote_negative_ask_rejected():
    backend = FakeMT5Backend()
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime(2026, 9, 2, tzinfo=timezone.utc), bid=D(1.1), ask=D(-1.0)))
    client = _client(backend=backend)
    resp = client.get("/v1/quotes/EURUSD", headers=_auth_headers())
    assert resp.status_code == 502


# 16. history valid.
def test_valid_history():
    backend = FakeMT5Backend()
    backend.set_bars(
        "EURUSD",
        [
            BackendBar(time_utc=datetime(2026, 9, 2, 12, tzinfo=timezone.utc), open=D(1.1), high=D(1.101), low=D(1.099), close=D(1.1005), tick_volume=D(100.0), spread=2, real_volume=None),
        ],
    )
    client = _client(backend=backend)
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    bars = resp.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["close"] == "1.1005"


# 17. invalid timeframe rejected.
def test_invalid_timeframe_rejected():
    client = _client()
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M2"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


# Step 3.1: timeframe is now a required query param, no silent M15 default.
def test_history_missing_timeframe_query_param_rejected_not_defaulted():
    client = _client()
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422  # FastAPI's own required-query-param rejection; never silently becomes M15


# 5. bridge M15 returns correct history.
def test_bridge_returns_correct_history_for_m15():
    backend = FakeMT5Backend()
    backend.set_bars("EURUSD", [
        BackendBar(time_utc=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc), open=D(1.1), high=D(1.101), low=D(1.099), close=D(1.1005), tick_volume=D(100.0), spread=2, real_volume=None),
        BackendBar(time_utc=datetime(2026, 9, 2, 12, 15, tzinfo=timezone.utc), open=D(1.1005), high=D(1.102), low=D(1.1), close=D(1.1015), tick_volume=D(90.0), spread=2, real_volume=None),
    ])
    client = _client(backend=backend)
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    bars = resp.json()["bars"]
    assert len(bars) == 2
    assert bars[0]["close"] == "1.1005"
    assert bars[1]["close"] == "1.1015"


# 6. bridge H1 returns correct history.
def test_bridge_returns_correct_history_for_h1():
    backend = FakeMT5Backend()
    backend.set_bars("EURUSD", [
        BackendBar(time_utc=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc), open=D(1.1), high=D(1.105), low=D(1.098), close=D(1.103), tick_volume=D(1000.0), spread=2, real_volume=None),
    ])
    client = _client(backend=backend)
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "H1"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    bars = resp.json()["bars"]
    assert len(bars) == 1
    assert bars[0]["close"] == "1.103"


# 10. existing history OHLC validation still works after the timeframe correction.
def test_history_ohlc_validation_still_enforced_after_timeframe_correction():
    from mt5_bridge.backend import MT5BackendError

    class BrokenOHLCBackend(FakeMT5Backend):
        def copy_rates_range(self, symbol, timeframe, start, end):
            raise MT5BackendError("simulated invalid OHLC upstream")

    client = _client(backend=BrokenOHLCBackend())
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 502


# 18. invalid date range rejected.
def test_start_after_end_rejected():
    client = _client()
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-03T00:00:00+00:00", "end": "2026-09-02T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_naive_history_timestamp_rejected():
    client = _client()
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


# 19. history backend error.
def test_history_backend_error_mapped_to_502():
    backend = FakeMT5Backend()
    backend.raise_on_rates = True
    client = _client(backend=backend)
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-03T00:00:00+00:00", "timeframe": "M15"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 502


# 20. positions parsed.
def test_positions_parsed():
    backend = FakeMT5Backend()
    backend.set_positions([BackendPosition(ticket=1, symbol="EURUSD", side="buy", volume=D(0.01), price_open=D(1.1))])
    client = _client(backend=backend)
    resp = client.get("/v1/positions", headers=_auth_headers())
    assert resp.status_code == 200
    positions = resp.json()["positions"]
    assert len(positions) == 1
    assert positions[0]["position_id"] == "1"


# 21. orders parsed.
def test_orders_parsed():
    backend = FakeMT5Backend()
    backend.set_orders([BackendOrder(ticket=99, symbol="EURUSD", side="sell", volume_initial=D(0.02), comment="manual")])
    client = _client(backend=backend)
    resp = client.get("/v1/orders", headers=_auth_headers())
    assert resp.status_code == 200
    orders = resp.json()["orders"]
    assert len(orders) == 1
    assert orders[0]["broker_order_id"] == "99"


# Step 3 correction 3.1: external MT5 order -> client_order_id is None (never synthesized).
def test_external_order_client_order_id_is_none():
    backend = FakeMT5Backend()
    backend.set_orders([BackendOrder(ticket=99, symbol="EURUSD", side="sell", volume_initial=D(0.02), comment="manual")])
    client = _client(backend=backend)
    resp = client.get("/v1/orders", headers=_auth_headers())
    orders = resp.json()["orders"]
    assert orders[0]["client_order_id"] is None


def test_order_broker_order_id_preserves_mt5_ticket():
    backend = FakeMT5Backend()
    backend.set_orders([BackendOrder(ticket=424242, symbol="GBPUSD", side="buy", volume_initial=D(0.01), comment=None)])
    client = _client(backend=backend)
    resp = client.get("/v1/orders", headers=_auth_headers())
    orders = resp.json()["orders"]
    assert orders[0]["broker_order_id"] == "424242"


def test_orders_response_never_contains_string_none_for_client_order_id():
    """A JSON `null` deserializes to Python `None`; the bug this
    correction targets is a code path that would instead produce the
    literal string "None" (e.g. via `str(None)`)."""
    backend = FakeMT5Backend()
    backend.set_orders([BackendOrder(ticket=1, symbol="EURUSD", side="buy", volume_initial=D(0.01), comment=None)])
    client = _client(backend=backend)
    resp = client.get("/v1/orders", headers=_auth_headers())
    orders = resp.json()["orders"]
    assert orders[0]["client_order_id"] != "None"
    assert orders[0]["client_order_id"] is None


# 22. unexpected backend exception sanitized.
def test_unexpected_exception_returns_sanitized_500():
    class ExplodingBackend(FakeMT5Backend):
        def account_info(self):
            raise RuntimeError("some internal detail with a secret path /home/user/.mt5/secret")

    app = create_app(ExplodingBackend(), _config())
    # raise_server_exceptions=False: TestClient's default re-raises any
    # exception that reaches an ASGI-level handler, which is meant to
    # catch bugs during development. Here the exception is deliberately
    # unexpected/simulated, and the behavior under test IS that FastAPI's
    # catch-all handler sanitizes it into a generic 500 rather than
    # letting it propagate -- so the client must be told not to re-raise
    # in order to actually observe that response.
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/v1/account", headers=_auth_headers())
    assert resp.status_code == 500
    assert "secret" not in resp.text
    assert "/home/user" not in resp.text
    assert resp.json()["error"]["code"] == "internal_error"


# 23. no filesystem path leaked in terminal response.
def test_terminal_response_has_no_path_field():
    backend = FakeMT5Backend()
    client = _client(backend=backend)
    resp = client.get("/v1/terminal", headers=_auth_headers())
    body = resp.json()
    assert "path" not in body
    assert "data_path" not in body


# 24. no secrets in response/log models.
def test_no_response_contains_token_or_password_field_names():
    client = _client()
    for path, params in [
        ("/v1/health", None),
        ("/v1/account", None),
        ("/v1/terminal", None),
        ("/v1/positions", None),
        ("/v1/orders", None),
    ]:
        resp = client.get(path, headers=_auth_headers(), params=params)
        body_text = resp.text.lower()
        assert "password" not in body_text
        assert "api_token" not in body_text
        assert TOKEN.lower() not in body_text


# 25. API version exactly "1".
def test_api_version_is_exactly_one():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers())
    assert resp.json()["api_version"] == "1"


# 26. routes match Step2 contract.
def test_routes_match_step2_contract():
    client = _client()
    openapi = client.get("/openapi.json").json()
    paths = set(openapi["paths"].keys())
    expected = {
        "/v1/health",
        "/v1/terminal",
        "/v1/account",
        "/v1/symbols",
        "/v1/symbols/{symbol}",
        "/v1/quotes/{symbol}",
        "/v1/history/{symbol}",
        "/v1/positions",
        "/v1/orders",
    }
    assert expected.issubset(paths)


def test_no_live_or_generic_write_routes_exist():
    """Step 4 correction: writes now exist, but ONLY under
    `/v1/demo/...`, `/v1/kill-switch/...`, and `/v1/reconciliation/run`
    -- never a generic `/v1/orders` POST and never anything under
    `/v1/live/...`.
    """

    client = _client()
    openapi = client.get("/openapi.json").json()
    allowed_write_prefixes = (
        "/v1/demo/",
        "/v1/kill-switch/",
        "/v1/reconciliation/run",
        "/v1/reconciliation/resolve-received/",
    )
    for path, methods in openapi["paths"].items():
        assert "/v1/live" not in path, f"a /v1/live/... route must never exist: {path}"
        if "post" in methods:
            assert path.startswith(allowed_write_prefixes), f"unexpected POST route outside allowed write prefixes: {path}"
        assert "put" not in methods, f"unexpected PUT route: {path}"
        assert "delete" not in methods, f"unexpected DELETE route: {path}"


def test_no_generic_orders_post_route_exists():
    client = _client()
    openapi = client.get("/openapi.json").json()
    assert "post" not in openapi["paths"].get("/v1/orders", {}), "a generic ambiguous POST /v1/orders must not exist"


# Additional risk-driven tests


def test_bind_host_0_0_0_0_rejected_by_config():
    with pytest.raises(Exception):
        BridgeConfig.from_env({"MT5_BRIDGE_TOKEN": "x", "MT5_BRIDGE_HOST": "0.0.0.0"})


def test_config_defaults_to_localhost(monkeypatch):
    from mt5_bridge.config import BridgeConfig, DEFAULT_HOST

    config = BridgeConfig.from_env({"MT5_BRIDGE_TOKEN": "x"})
    assert config.host == DEFAULT_HOST


def test_config_missing_token_raises():
    from mt5_bridge.config import BridgeConfigError

    with pytest.raises(BridgeConfigError):
        BridgeConfig.from_env({})


def test_config_repr_hides_token_and_password():
    config = BridgeConfig(host="127.0.0.1", port=8765, api_token="secret-token", password="secret-password")
    assert "secret-token" not in repr(config)
    assert "secret-password" not in repr(config)


def test_symbol_path_with_traversal_returns_404_not_500():
    client = _client()
    resp = client.get("/v1/symbols/..%2Fetc", headers=_auth_headers())
    assert resp.status_code in (404, 400)


def test_environment_unknown_when_trade_mode_unknown_even_if_server_name_says_demo():
    """classify_environment must not infer DEMO from a server name --
    only from the authoritative trade_mode code."""
    backend = FakeMT5Backend()
    backend.account = BackendAccountInfo(
        login=1, trade_mode_code=None, server="SomeBroker-Demo-Server", currency="USD", balance=D(1.0), equity=D(1.0), margin=D(0.0), margin_free=D(1.0)
    )
    client = _client(backend=backend)
    resp = client.get("/v1/account", headers=_auth_headers())
    body = resp.json()
    assert body["environment"] == "unknown"


# ============================================================
# Step 4: write endpoints (demo orders, kill switch, reconciliation, journal)
# ============================================================


def test_health_includes_build_and_version():
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers())
    body = resp.json()
    assert body["bridge_version"] == "1"
    assert body["bridge_build"]


def test_health_bridge_time_utc_is_timezone_aware_and_recent():
    """16. /v1/health's bridge_time_utc reflects this process's own
    clock, is timezone-aware (ISO 8601 with a UTC offset), and is close
    to wall-clock now -- not None, not naive, not some other clock."""

    from datetime import timedelta

    before = datetime.now(timezone.utc)
    client = _client()
    resp = client.get("/v1/health", headers=_auth_headers())
    after = datetime.now(timezone.utc)
    body = resp.json()
    assert body["bridge_time_utc"] is not None
    parsed = datetime.fromisoformat(body["bridge_time_utc"])
    assert parsed.tzinfo is not None
    assert before <= parsed <= after + timedelta(seconds=2)


def test_time_diagnostics_endpoint_returns_bridge_and_tick_clocks():
    backend = FakeMT5Backend()
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=D(1.1), ask=D(1.1002)))
    client = _client(backend=backend)
    resp = client.get("/v1/time-diagnostics/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "EURUSD"
    assert body["bridge_time_utc"] is not None
    assert body["mt5_tick_time_utc"] is not None
    assert abs(body["quote_age_seconds"]) < 5
    assert body["quote_future_skew_seconds"] == 0.0


def test_time_diagnostics_endpoint_reports_future_skew_without_rejecting():
    """READ-ONLY: unlike /v1/demo/orders, this endpoint must never raise
    on a future/stale quote -- it exists specifically to let a human see
    the skew even when a write would be denied."""

    from datetime import timedelta

    backend = FakeMT5Backend()
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc) + timedelta(hours=3), bid=D(1.1), ask=D(1.1002)))
    client = _client(backend=backend)
    resp = client.get("/v1/time-diagnostics/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["quote_future_skew_seconds"] == pytest.approx(10800.0, abs=2.0)


def test_time_diagnostics_endpoint_no_tick_available():
    client = _client()
    resp = client.get("/v1/time-diagnostics/EURUSD", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["mt5_tick_time_utc"] is None
    assert body["quote_age_seconds"] is None


def test_time_diagnostics_endpoint_requires_auth():
    client = _client()
    resp = client.get("/v1/time-diagnostics/EURUSD")
    assert resp.status_code == 401


def test_post_demo_order_success():
    client, backend, store = _demo_ready_client()
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "filled"
    assert body["idempotent_replay"] is False


def test_post_demo_order_idempotent_retry_returns_replay():
    client, backend, store = _demo_ready_client()
    body1 = {"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}
    resp1 = client.post("/v1/demo/orders", json=body1, headers=_auth_headers())
    resp2 = client.post("/v1/demo/orders", json=body1, headers=_auth_headers())
    assert resp2.json()["idempotent_replay"] is True
    assert resp1.json()["broker_order_id"] == resp2.json()["broker_order_id"]
    assert len(backend.positions_get()) == 1


def test_post_demo_order_conflict_returns_409():
    client, backend, store = _demo_ready_client()
    client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "sell", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_post_demo_order_kill_switch_active_returns_403():
    client, backend, store = _demo_ready_client()
    store.set_kill_switch("active", "test")
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "kill_switch_active"
    assert backend.positions_get() == []


def test_post_demo_order_live_account_rejected_server_side():
    backend = FakeMT5Backend()
    backend.account = BackendAccountInfo(login=1, trade_mode_code=2, server="Live", currency="USD", balance=D(1.0), equity=D(1.0), margin=D(0.0), margin_free=D(1.0))
    client, backend, store = _demo_ready_client(backend=backend)
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_demo"
    assert backend.positions_get() == []


def test_post_demo_order_future_quote_rejected_server_side():
    """12. Bridge server-side independently rejects a future-timestamped
    quote using ITS OWN clock -- this is the actual write-path check that
    matters (Linux's own client-side check, see
    src/execution/safe_execution.py, is only a courtesy early warning).
    """

    from datetime import timedelta

    backend = FakeMT5Backend()
    client, backend, store = _demo_ready_client(backend=backend)
    backend.set_tick("EURUSD", BackendTick(
        symbol="EURUSD", time_utc=datetime.now(timezone.utc) + timedelta(hours=3), bid=D(1.1), ask=D(1.1002),
    ))
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "stale_quote"
    assert "future" in resp.json()["error"]["message"]
    assert backend.positions_get() == []


def test_post_demo_order_never_touches_mt5_when_quote_is_future_even_if_linux_clock_is_wrong():
    """13. The bridge must be able to DENY on its own even if the
    caller's (Linux's) clock is wrong -- this endpoint doesn't receive or
    trust any client-supplied "now"; it only ever uses its own
    datetime.now(timezone.utc), so there is no way for a skewed Linux
    clock to bypass this check by claiming a different current time."""

    from datetime import timedelta

    backend = FakeMT5Backend()
    client, backend, store = _demo_ready_client(backend=backend)
    backend.set_tick("EURUSD", BackendTick(
        symbol="EURUSD", time_utc=datetime.now(timezone.utc) + timedelta(hours=1), bid=D(1.1), ask=D(1.1002),
    ))
    # No client-supplied timestamp/clock field exists anywhere in this
    # request body -- confirming there is no such channel to begin with.
    body = {"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}
    assert "now" not in body and "client_time" not in body and "timestamp" not in body
    resp = client.post("/v1/demo/orders", json=body, headers=_auth_headers())
    assert resp.status_code == 409
    assert backend.positions_get() == []


def test_post_demo_order_small_future_skew_within_tolerance_allowed():
    backend = FakeMT5Backend()
    client, backend, store = _demo_ready_client(backend=backend)
    from datetime import timedelta

    backend.set_tick("EURUSD", BackendTick(
        symbol="EURUSD", time_utc=datetime.now(timezone.utc) + timedelta(milliseconds=100), bid=D(1.1), ask=D(1.1002),
    ))
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    assert resp.status_code == 200


def test_post_demo_order_volume_above_minimum_rejected():
    client, backend, store = _demo_ready_client()
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.02"}, headers=_auth_headers())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_volume"


def test_post_demo_order_missing_fields_rejected():
    client, backend, store = _demo_ready_client()
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1"}, headers=_auth_headers())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


def test_post_demo_order_requires_auth():
    client, backend, store = _demo_ready_client()
    resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"})
    assert resp.status_code == 401


def test_post_demo_close_success():
    client, backend, store = _demo_ready_client()
    open_resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    position_id = open_resp.json()["position_id"]
    close_resp = client.post(f"/v1/demo/positions/{position_id}/close", json={"client_order_id": "close-1"}, headers=_auth_headers())
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "filled"
    assert backend.positions_get() == []


def test_post_demo_close_nonexistent_position_returns_404():
    client, backend, store = _demo_ready_client()
    resp = client.post("/v1/demo/positions/999999/close", json={"client_order_id": "close-1"}, headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "position_not_found"


def test_post_demo_close_allowed_with_kill_switch_active():
    client, backend, store = _demo_ready_client()
    open_resp = client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    position_id = open_resp.json()["position_id"]
    store.set_kill_switch("active", "test")
    close_resp = client.post(f"/v1/demo/positions/{position_id}/close", json={"client_order_id": "close-1"}, headers=_auth_headers())
    assert close_resp.status_code == 200


def test_kill_switch_get_default_inactive():
    client, backend, store = _demo_ready_client()
    resp = client.get("/v1/kill-switch", headers=_auth_headers())
    assert resp.json()["status"] == "inactive"


def test_kill_switch_activate_and_deactivate():
    client, backend, store = _demo_ready_client()
    resp1 = client.post("/v1/kill-switch/activate", json={"reason": "manual test"}, headers=_auth_headers())
    assert resp1.json()["status"] == "active"
    assert resp1.json()["reason"] == "manual test"
    resp2 = client.post("/v1/kill-switch/deactivate", headers=_auth_headers())
    assert resp2.json()["status"] == "inactive"


def test_kill_switch_requires_auth():
    client, backend, store = _demo_ready_client()
    resp = client.get("/v1/kill-switch")
    assert resp.status_code == 401


def test_reconciliation_get_and_run():
    client, backend, store = _demo_ready_client()
    resp1 = client.get("/v1/reconciliation", headers=_auth_headers())
    assert resp1.json()["state"] == "ok"
    resp2 = client.post("/v1/reconciliation/run", headers=_auth_headers())
    assert resp2.json()["state"] == "ok"


def test_journal_returns_entries_after_write():
    client, backend, store = _demo_ready_client()
    client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    resp = client.get("/v1/journal?limit=50", headers=_auth_headers())
    assert resp.status_code == 200
    assert len(resp.json()["entries"]) > 0


def test_journal_no_secrets_in_response():
    client, backend, store = _demo_ready_client()
    client.post("/v1/demo/orders", json={"client_order_id": "c1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"}, headers=_auth_headers())
    resp = client.get("/v1/journal?limit=50", headers=_auth_headers())
    assert TOKEN not in resp.text
    assert "password" not in resp.text.lower()


def test_validation_error_422_uses_standard_error_envelope():
    """Step 4 section 39: FastAPI's own 422 (e.g. malformed query) is
    unified under {"error": {code, message}}."""
    client = _client()
    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-02T00:00:00+00:00"},  # missing end + timeframe
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert "code" in body["error"]


def test_demo_write_routes_appear_in_openapi():
    client = _client()
    openapi = client.get("/openapi.json").json()
    assert "post" in openapi["paths"].get("/v1/demo/orders", {})
    assert "post" in openapi["paths"].get("/v1/demo/positions/{position_id}/close", {})


def test_resolve_received_endpoint_resolves_only_received_row():
    client, backend, store = _demo_ready_client()
    store.begin_idempotent_request("stuck-received", "hash")
    run = client.post("/v1/reconciliation/run", headers=_auth_headers())
    assert run.json()["state"] == "mismatch"

    resp = client.post(
        "/v1/reconciliation/resolve-received/stuck-received",
        json={"confirm_abort_before_submission": True},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "ok"
    record = store.get_idempotency_record("stuck-received")
    assert record.state.value == "rejected"
    assert record.error_code == "aborted_before_submission"


def test_resolve_received_endpoint_refuses_submitted_row():
    from mt5_bridge.store import OrderState

    client, backend, store = _demo_ready_client()
    store.begin_idempotent_request("stuck-submitted", "hash")
    store.update_idempotency_state("stuck-submitted", OrderState.SUBMITTED)
    resp = client.post(
        "/v1/reconciliation/resolve-received/stuck-submitted",
        json={"confirm_abort_before_submission": True},
        headers=_auth_headers(),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_resolve_received_endpoint_requires_explicit_confirmation_body():
    client, backend, store = _demo_ready_client()
    store.begin_idempotent_request("stuck-unconfirmed", "hash")
    resp = client.post(
        "/v1/reconciliation/resolve-received/stuck-unconfirmed",
        json={},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert store.get_idempotency_record("stuck-unconfirmed").state.value == "received"


def test_post_demo_order_autotrading_disabled_rejected_before_idempotency():
    client, backend, store = _demo_ready_client()
    backend.terminal = BackendTerminalInfo(
        connected=True, trade_allowed=False, dlls_allowed=False,
        name="MetaTrader 5", company="Fake Broker", build=1,
    )
    resp = client.post(
        "/v1/demo/orders",
        json={"client_order_id": "auto-off-1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "autotrading_disabled"
    assert "AutoTrading is disabled" in resp.json()["error"]["message"]
    assert backend.positions_get() == []
    record = store.get_idempotency_record("auto-off-1")
    assert record is not None
    assert record.state.value == "rejected"
    assert record.error_code == "autotrading_disabled"


def test_post_demo_order_account_expert_permission_disabled_rejected_before_idempotency():
    client, backend, store = _demo_ready_client()
    old = backend.account
    assert old is not None
    backend.account = BackendAccountInfo(
        login=old.login, trade_mode_code=old.trade_mode_code, server=old.server, currency=old.currency,
        balance=old.balance, equity=old.equity, margin=old.margin, margin_free=old.margin_free,
        trade_allowed=True, trade_expert=False,
    )
    resp = client.post(
        "/v1/demo/orders",
        json={"client_order_id": "expert-off-1", "symbol": "EURUSD", "side": "buy", "volume": "0.01"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "autotrading_disabled"
    assert "expert/algorithmic" in resp.json()["error"]["message"]
    record = store.get_idempotency_record("expert-off-1")
    assert record is not None
    assert record.state.value == "rejected"


def test_terminal_and_account_endpoints_expose_trading_permissions():
    client = _client()
    terminal = client.get("/v1/terminal", headers=_auth_headers()).json()
    account = client.get("/v1/account", headers=_auth_headers()).json()
    assert terminal["trade_allowed"] is True
    assert account["trade_allowed"] is True
    assert account["trade_expert"] is True


def test_generated_http_request_id_is_persisted_in_write_journal():
    client, backend, store = _demo_ready_client()
    resp = client.post(
        "/v1/demo/orders",
        json={"client_order_id": "rid-generated", "symbol": "EURUSD", "side": "buy", "volume": "0.01"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    request_id = resp.headers["X-Request-ID"]
    entries = store.read_journal_for_client_order_id("rid-generated")
    assert entries
    assert all(e["request_id"] == request_id for e in entries)


def test_caller_http_request_id_is_persisted_in_write_journal():
    client, backend, store = _demo_ready_client()
    headers = _auth_headers()
    headers["X-Request-ID"] = "operator-request-42"
    resp = client.post(
        "/v1/demo/orders",
        json={"client_order_id": "rid-explicit", "symbol": "EURUSD", "side": "buy", "volume": "0.01"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "operator-request-42"
    entries = store.read_journal_for_client_order_id("rid-explicit")
    assert entries
    assert all(e["request_id"] == "operator-request-42" for e in entries)


def test_close_http_request_id_is_persisted_in_write_journal():
    client, backend, store = _demo_ready_client()
    opened = client.post(
        "/v1/demo/orders",
        json={"client_order_id": "rid-open-for-close", "symbol": "EURUSD", "side": "buy", "volume": "0.01"},
        headers=_auth_headers(),
    ).json()
    headers = _auth_headers()
    headers["X-Request-ID"] = "close-http-request-7"
    resp = client.post(
        f"/v1/demo/positions/{opened['position_id']}/close",
        json={"client_order_id": "rid-close"},
        headers=headers,
    )
    assert resp.status_code == 200
    entries = store.read_journal_for_client_order_id("rid-close")
    assert entries
    assert all(e["request_id"] == "close-http-request-7" for e in entries)
