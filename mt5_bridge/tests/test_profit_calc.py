"""Tests for the read-only `/v1/profit-calc/{symbol}` diagnostic endpoint
(Phase 5B, Section 11) -- a pure calculation oracle, never an order.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from mt5_bridge.app import create_app
from mt5_bridge.backend import BackendSymbolInfo, FakeMT5Backend
from mt5_bridge.config import BridgeConfig

TOKEN = "bridge-test-token"


def D(x) -> Decimal:
    return Decimal(str(x))


def _client(backend: FakeMT5Backend | None = None) -> TestClient:
    from mt5_bridge.store import BridgeStore

    backend = backend if backend is not None else FakeMT5Backend()
    config = BridgeConfig(host="127.0.0.1", port=8765, api_token=TOKEN)
    app = create_app(backend, config, store=BridgeStore(":memory:"))
    return TestClient(app)


def _eurusd_backend() -> FakeMT5Backend:
    backend = FakeMT5Backend()
    backend.set_symbol(
        "EURUSD",
        BackendSymbolInfo(
            name="EURUSD", description="Euro vs US Dollar", digits=5, point=D("0.00001"),
            volume_min=D("0.01"), volume_step=D("0.01"), volume_max=D("60"),
            trade_contract_size=D("100000"), trade_tick_size=D("0.00001"), trade_tick_value=D("1.0"),
            trade_enabled=True, visible=True, currency_base="EUR", currency_profit="USD", currency_margin="EUR",
            filling_mode=1,
        ),
    )
    return backend


def test_profit_calc_buy_gain_requires_auth():
    client = _client(_eurusd_backend())
    response = client.get("/v1/profit-calc/EURUSD?side=buy&volume=0.01&price_open=1.1000&price_close=1.1050")
    assert response.status_code == 401


def test_profit_calc_buy_gain():
    client = _client(_eurusd_backend())
    response = client.get(
        "/v1/profit-calc/EURUSD?side=buy&volume=0.01&price_open=1.1000&price_close=1.1050",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "EURUSD"
    assert body["side"] == "buy"
    assert Decimal(body["profit"]) == D("5.0")  # (1.1050-1.1000)*0.01*100000


def test_profit_calc_sell_gain():
    client = _client(_eurusd_backend())
    response = client.get(
        "/v1/profit-calc/EURUSD?side=sell&volume=0.01&price_open=1.1000&price_close=1.0950",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert Decimal(response.json()["profit"]) == D("5.0")


def test_profit_calc_buy_loss():
    client = _client(_eurusd_backend())
    response = client.get(
        "/v1/profit-calc/EURUSD?side=buy&volume=0.01&price_open=1.1000&price_close=1.0950",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert Decimal(response.json()["profit"]) == D("-5.0")


def test_profit_calc_invalid_side_rejected():
    client = _client(_eurusd_backend())
    response = client.get(
        "/v1/profit-calc/EURUSD?side=up&volume=0.01&price_open=1.1000&price_close=1.1050",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 400


def test_profit_calc_never_touches_positions_or_orders():
    backend = _eurusd_backend()
    client = _client(backend)
    client.get(
        "/v1/profit-calc/EURUSD?side=buy&volume=0.01&price_open=1.1000&price_close=1.1050",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert backend.positions_get() == []
    assert backend.orders_get() == []
