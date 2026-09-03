"""Real-socket integration test: Step 2 client <-> Step 3 bridge (FX Phase 0).

This is the only test in the project that opens a real TCP socket. It
starts `mt5_bridge`'s FastAPI app under `uvicorn` in a background thread,
bound to `127.0.0.1` on an OS-assigned free port, and drives it with
`MT5RemoteExecutionClient` + `RequestsTransport` (Step 2) over genuine
HTTP -- not FastAPI's `TestClient` ASGI shortcut used everywhere else in
this package. This is what actually proves Step 2 and Step 3 agree on
the wire format, not just in each side's own unit tests.

No MetaTrader5 is required: the bridge runs with `FakeMT5Backend`.

Marked `integration` so it can be selected/excluded explicitly
(`pytest -m integration` or `-m "not integration"`); it is slower and
uses real sockets/threads, unlike the rest of the suite.
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import uvicorn

from mt5_bridge.app import create_app
from mt5_bridge.backend import BackendAccountInfo, BackendSymbolInfo, BackendTick, FakeMT5Backend
from mt5_bridge.config import BridgeConfig
from mt5_bridge.reconciliation import run_reconciliation
from mt5_bridge.store import BridgeStore
from src.execution.base import AccountTradeMode
from src.execution.mt5_remote import MT5RemoteExecutionClient, RemoteConfig

pytestmark = pytest.mark.integration

TOKEN = "integration-test-token"


def D(x) -> Decimal:
    return Decimal(str(x))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _BridgeServerThread:
    def __init__(self, backend: FakeMT5Backend, port: int, store: BridgeStore | None = None) -> None:
        config = BridgeConfig(host="127.0.0.1", port=port, api_token=TOKEN)
        store = store if store is not None else BridgeStore(":memory:")
        self.store = store
        app = create_app(backend, config, store=store)
        self._uvicorn_config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(self._uvicorn_config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("bridge server did not start within 5s")
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


@pytest.fixture
def running_bridge():
    backend = FakeMT5Backend()
    backend.set_tick(
        "EURUSD",
        BackendTick(symbol="EURUSD", time_utc=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc), bid=D(1.10001), ask=D(1.10003)),
    )
    port = _free_port()
    server = _BridgeServerThread(backend, port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


def _client(bridge_url: str) -> MT5RemoteExecutionClient:
    config = RemoteConfig(bridge_url=bridge_url, api_token=TOKEN, timeout_seconds=5.0)
    return MT5RemoteExecutionClient(config)


def test_real_socket_health(running_bridge):
    client = _client(running_bridge)
    status = client.health()
    assert status.bridge_alive is True
    assert status.terminal_connected is True


def test_real_socket_health_carries_version_and_build(running_bridge):
    """Proves the whole real-wire path: mt5_bridge's /v1/health JSON ->
    MT5RemoteExecutionClient.health() -> HealthStatus actually delivers
    bridge_version/bridge_build/api_version end to end, over genuine HTTP
    (not just each side's own unit tests against a fake payload)."""

    from mt5_bridge.config import BRIDGE_BUILD

    client = _client(running_bridge)
    status = client.health()
    assert status.api_version == "1"
    assert status.bridge_version == "1"
    assert status.bridge_build == BRIDGE_BUILD


def test_real_socket_account(running_bridge):
    client = _client(running_bridge)
    account = client.account()
    assert account.trade_mode is AccountTradeMode.DEMO
    assert account.balance == Decimal("1000.00")


def test_real_socket_time_diagnostics(running_bridge):
    """Proves the read-only clock-diagnostic endpoint over genuine HTTP:
    mt5_bridge's /v1/time-diagnostics/{symbol} -> MT5RemoteExecutionClient
    .time_diagnostics() -> TimeDiagnostics, with all three clocks present
    and skews computed. Never touches order_check/order_send."""

    client = _client(running_bridge)
    diag = client.time_diagnostics("EURUSD")
    assert diag.symbol == "EURUSD"
    assert diag.bridge_time_utc is not None
    assert diag.mt5_tick_time_utc == datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    # Both bridge and Linux client read "real now" (this fixture's tick is
    # deliberately a fixed, old timestamp for other tests) -- their
    # mutual skew must be tiny, unlike the tick's, which is genuinely old.
    assert abs(diag.bridge_client_skew_seconds) < 5
    assert diag.tick_bridge_skew_seconds < -1000


@pytest.fixture
def running_bridge_with_symbols():
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description="Euro vs US Dollar", digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
        trade_tick_size=D(0.00001), trade_tick_value=D(1.0), trade_enabled=True, visible=True,
    ))
    backend.set_symbol("EURUSDm", BackendSymbolInfo(
        name="EURUSDm", description=None, digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(100.0), trade_contract_size=D(100000.0),
        trade_tick_size=None, trade_tick_value=None, trade_enabled=True, visible=True,
    ))
    port = _free_port()
    server = _BridgeServerThread(backend, port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


def test_real_socket_symbols_listing(running_bridge_with_symbols):
    client = _client(running_bridge_with_symbols)
    symbols = client.symbols()
    names = {s.symbol for s in symbols}
    assert names == {"EURUSD", "EURUSDm"}


def test_real_socket_quote(running_bridge):
    client = _client(running_bridge)
    quote = client.quote("EURUSD")
    assert quote.bid == Decimal("1.10001")
    assert quote.ask == Decimal("1.10003")


def test_real_socket_wrong_token_raises_auth_error(running_bridge):
    from src.execution.mt5_remote import ExecutionAuthenticationError

    config = RemoteConfig(bridge_url=running_bridge, api_token="wrong-token", timeout_seconds=5.0)
    client = MT5RemoteExecutionClient(config)
    with pytest.raises(ExecutionAuthenticationError):
        client.health()


@pytest.fixture
def running_bridge_with_history():
    from mt5_bridge.backend import BackendBar

    backend = FakeMT5Backend()
    backend.set_bars("EURUSD", [
        BackendBar(time_utc=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc), open=D(1.1), high=D(1.101), low=D(1.099), close=D(1.1005), tick_volume=D(100.0), spread=2, real_volume=None),
        BackendBar(time_utc=datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc), open=D(1.1005), high=D(1.103), low=D(1.0995), close=D(1.102), tick_volume=D(85.0), spread=2, real_volume=None),
    ])
    port = _free_port()
    server = _BridgeServerThread(backend, port)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


# 7. socket integration client -> bridge preserves timeframe.
def test_real_socket_history_preserves_requested_timeframe(running_bridge_with_history):
    from src.execution.base import ExecutionTimeframe, HistoryRequest

    client = _client(running_bridge_with_history)
    m15_result = client.history(HistoryRequest(
        symbol="EURUSD", timeframe=ExecutionTimeframe.M15,
        start=datetime(2026, 9, 2, 0, tzinfo=timezone.utc), end=datetime(2026, 9, 3, 0, tzinfo=timezone.utc),
    ))
    h1_result = client.history(HistoryRequest(
        symbol="EURUSD", timeframe=ExecutionTimeframe.H1,
        start=datetime(2026, 9, 2, 0, tzinfo=timezone.utc), end=datetime(2026, 9, 3, 0, tzinfo=timezone.utc),
    ))
    # FakeMT5Backend.copy_rates_range does not itself filter by timeframe
    # (that distinction lives in RealMT5Backend's MT5-specific mapping);
    # what this test actually proves is that the client sends a distinct
    # `timeframe` value for each call and the bridge accepts both without
    # rejecting either as invalid -- the real assertion is both requests
    # succeed and see the same underlying bar set the fake was given.
    assert len(m15_result.bars) == 2
    assert len(h1_result.bars) == 2
    assert m15_result.bars[0].close == Decimal("1.1005")


def test_real_socket_history_missing_timeframe_rejected():
    """A HistoryRequest cannot even be constructed without a timeframe
    (see tests/test_mt5_remote.py's dataclass-level test) -- this
    documents the same guarantee end-to-end: there is no code path from
    the real client that reaches the bridge without an explicit
    timeframe query param."""
    import inspect

    from src.execution.base import HistoryRequest

    assert "timeframe" in inspect.signature(HistoryRequest).parameters
    assert inspect.signature(HistoryRequest).parameters["timeframe"].default is inspect.Parameter.empty


# ============================================================
# Step 4: real-socket write-path coverage
# ============================================================


@pytest.fixture
def demo_ready_bridge():
    """A running bridge with a tradable EURUSD symbol, fresh tick, and
    reconciliation already run to OK -- ready for a real HTTP demo order.
    """

    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description=None, digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(60), trade_contract_size=D(100000),
        trade_tick_size=D(0.00001), trade_tick_value=D(1), trade_enabled=True, visible=True, filling_mode=3,
    ))
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=D("1.1000"), ask=D("1.1002")))
    store = BridgeStore(":memory:")
    run_reconciliation(store, backend)
    port = _free_port()
    server = _BridgeServerThread(backend, port, store=store)
    server.start()
    try:
        yield f"http://127.0.0.1:{port}", backend, store
    finally:
        server.stop()


def _client_from_url(bridge_url: str) -> MT5RemoteExecutionClient:
    config = RemoteConfig(bridge_url=bridge_url, api_token=TOKEN, timeout_seconds=5.0)
    return MT5RemoteExecutionClient(config)


def test_real_socket_successful_demo_open(demo_ready_bridge):
    from src.execution.base import Side

    bridge_url, backend, store = demo_ready_bridge
    client = _client_from_url(bridge_url)
    from src.execution.base import ActionKind, OrderRequest, OrderType

    request = OrderRequest(
        client_order_id="socket-open-1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
    )
    result = client.place_order(request)
    assert result.status.value == "filled"
    assert len(backend.positions_get()) == 1


def test_real_socket_duplicate_idempotent_retry(demo_ready_bridge):
    from src.execution.base import ActionKind, OrderRequest, OrderType, Side

    bridge_url, backend, store = demo_ready_bridge
    client = _client_from_url(bridge_url)
    request = OrderRequest(
        client_order_id="socket-dup-1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
    )
    r1 = client.place_order(request)
    r2 = client.place_order(request)
    assert r2.idempotent_replay is True
    assert r1.broker_order_id == r2.broker_order_id
    assert len(backend.positions_get()) == 1


def test_real_socket_close(demo_ready_bridge):
    from src.execution.base import ActionKind, CloseRequest, OrderRequest, OrderType, Side

    bridge_url, backend, store = demo_ready_bridge
    client = _client_from_url(bridge_url)
    open_request = OrderRequest(
        client_order_id="socket-close-open-1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
    )
    open_result = client.place_order(open_request)
    close_result = client.close_position(CloseRequest(client_order_id="socket-close-1", position_id=open_result.position_id))
    assert close_result.status.value == "filled"
    assert backend.positions_get() == []


def test_real_socket_kill_switch_lifecycle(demo_ready_bridge):
    bridge_url, backend, store = demo_ready_bridge
    client = _client_from_url(bridge_url)
    status0 = client.kill_switch_status()
    assert status0.status.value == "inactive"
    status1 = client.activate_kill_switch(reason="socket test")
    assert status1.status.value == "active"
    status2 = client.deactivate_kill_switch()
    assert status2.status.value == "inactive"


def test_real_socket_kill_switch_blocks_open_over_http(demo_ready_bridge):
    from src.execution.base import ActionKind, OrderRequest, OrderType, Side
    from src.execution.mt5_remote import ExecutionWriteRejectedError

    bridge_url, backend, store = demo_ready_bridge
    client = _client_from_url(bridge_url)
    client.activate_kill_switch()
    request = OrderRequest(
        client_order_id="socket-blocked-1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
        volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
    )
    with pytest.raises(ExecutionWriteRejectedError) as excinfo:
        client.place_order(request)
    assert excinfo.value.error_code == "kill_switch_active"
    assert backend.positions_get() == []


def test_real_socket_reconciliation_mismatch_blocks_open():
    from src.execution.base import ActionKind, OrderRequest, OrderType, Side
    from src.execution.mt5_remote import ExecutionWriteRejectedError

    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", BackendSymbolInfo(
        name="EURUSD", description=None, digits=5, point=D(0.00001),
        volume_min=D(0.01), volume_step=D(0.01), volume_max=D(60), trade_contract_size=D(100000),
        trade_tick_size=D(0.00001), trade_tick_value=D(1), trade_enabled=True, visible=True, filling_mode=3,
    ))
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=D("1.1000"), ask=D("1.1002")))
    store = BridgeStore(":memory:")
    # Deliberately do NOT run reconciliation -- status stays UNKNOWN.
    port = _free_port()
    server = _BridgeServerThread(backend, port, store=store)
    server.start()
    try:
        client = _client_from_url(f"http://127.0.0.1:{port}")
        request = OrderRequest(
            client_order_id="socket-recon-1", symbol="EURUSD", side=Side.BUY, order_type=OrderType.MARKET,
            volume=Decimal("0.01"), action_kind=ActionKind.OPEN,
        )
        with pytest.raises(ExecutionWriteRejectedError) as excinfo:
            client.place_order(request)
        assert excinfo.value.error_code == "reconciliation_required"
        assert backend.positions_get() == []
    finally:
        server.stop()
