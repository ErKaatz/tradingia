"""Tests for server-side write orchestration (FX Phase 0, Step 4).

Exercises `mt5_bridge.trading` directly against `FakeMT5Backend` and an
in-memory `BridgeStore` -- no HTTP layer here (see test_app.py for the
HTTP-level equivalents and test_integration_socket.py for real-socket
coverage).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mt5_bridge.backend import (
    BackendAccountInfo,
    BackendPosition,
    BackendSymbolInfo,
    BackendTick,
    FakeMT5Backend,
    MT5BackendError,
)
from mt5_bridge.reconciliation import get_reconciliation_status, run_reconciliation
from mt5_bridge.store import BridgeStore, IdempotencyConflictError, OrderState
from mt5_bridge.trading import (
    DemoCloseRequest,
    DemoOrderRequest,
    KillSwitchActiveError,
    NotDemoError,
    OrderCheckFailedError,
    OrderSendFailedError,
    PositionNotFoundError,
    ReconciliationRequiredError,
    StaleQuoteError,
    SymbolNotTradableError,
    TooManyPositionsError,
    close_demo_position,
    place_demo_order,
)


def _tradable_symbol(**overrides) -> BackendSymbolInfo:
    defaults = dict(
        name="EURUSD", description=None, digits=5, point=Decimal("0.00001"),
        volume_min=Decimal("0.01"), volume_step=Decimal("0.01"), volume_max=Decimal("60"),
        trade_contract_size=Decimal("100000"), trade_tick_size=Decimal("0.00001"), trade_tick_value=Decimal("1"),
        trade_enabled=True, visible=True, filling_mode=3,
    )
    defaults.update(overrides)
    return BackendSymbolInfo(**defaults)


@pytest.fixture
def ready_backend() -> FakeMT5Backend:
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", _tradable_symbol())
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=Decimal("1.1000"), ask=Decimal("1.1002")))
    return backend


@pytest.fixture
def store() -> BridgeStore:
    s = BridgeStore(":memory:")
    return s


def _run_reconciliation(store: BridgeStore, backend: FakeMT5Backend) -> None:
    run_reconciliation(store, backend)


def _open_kwargs(**overrides) -> dict:
    defaults = dict(
        max_positions=1, max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0,
        deviation_points=20, magic=999, request_id="r1",
    )
    defaults.update(overrides)
    return defaults


# 1. valid demo entry -> allowed.
def test_valid_demo_entry_fills(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    result = place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert result.status == "filled"
    assert result.idempotent_replay is False


# 2. live account -> no HTTP write (here: no MT5 write / hard reject).
def test_live_account_rejected_before_any_mt5_write(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.account = BackendAccountInfo(
        login=1, trade_mode_code=2, server="Live", currency="USD", balance=Decimal("100"), equity=Decimal("100"), margin=Decimal("0"), margin_free=Decimal("100")
    )
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(NotDemoError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


# 3. unknown account -> no write.
def test_unknown_account_trade_mode_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.account = BackendAccountInfo(
        login=1, trade_mode_code=None, server="X", currency="USD", balance=Decimal("100"), equity=Decimal("100"), margin=Decimal("0"), margin_free=Decimal("100")
    )
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(NotDemoError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


# 4. kill switch active -> no write.
def test_kill_switch_active_blocks_new_entry(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    store.set_kill_switch("active", "test")
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(KillSwitchActiveError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


# 5. reconciliation mismatch -> no write.
def test_reconciliation_mismatch_blocks_new_entry(ready_backend, store):
    # Never run reconciliation -> status is UNKNOWN, which also blocks.
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(ReconciliationRequiredError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


# 6. one existing position -> no write.
def test_existing_position_blocks_new_entry(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.set_positions([BackendPosition(ticket=1, symbol="EURUSD", side="buy", volume=Decimal("0.01"), price_open=Decimal("1.1"))])
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(TooManyPositionsError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())


# 7. requested > min -> rejected.
def test_requested_volume_above_minimum_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.02"))
    from mt5_bridge.trading import InvalidVolumeError

    with pytest.raises(InvalidVolumeError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())


# 8. stale quote -> rejected.
def test_stale_quote_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc) - timedelta(seconds=30), bid=Decimal("1.1"), ask=Decimal("1.1002")))
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(StaleQuoteError):
        place_demo_order(ready_backend, store, request, **_open_kwargs(max_quote_age_seconds=5.0))


# 9. trade disabled symbol -> rejected.
def test_trade_disabled_symbol_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.set_symbol("EURUSD", _tradable_symbol(trade_enabled=False))
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(SymbolNotTradableError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())


# 10. disconnected terminal -> rejected.
def test_disconnected_terminal_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.connected = False
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(NotDemoError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())


# 11. same client_order_id retry -> one MT5 submission.
def test_same_client_order_id_retry_does_not_resubmit(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    r1 = place_demo_order(ready_backend, store, request, **_open_kwargs())
    r2 = place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert r2.idempotent_replay is True
    assert r1.broker_order_id == r2.broker_order_id
    assert len(ready_backend.positions_get()) == 1


# 12. same ID different request -> conflict.
def test_same_client_order_id_different_request_conflicts(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request1 = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    place_demo_order(ready_backend, store, request1, **_open_kwargs())
    request2 = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="sell", volume=Decimal("0.01"))
    with pytest.raises(IdempotencyConflictError):
        place_demo_order(ready_backend, store, request2, **_open_kwargs())


# 13. crash after MT5 send -> reconciliation required, no blind resend.
def test_crash_during_order_send_leaves_submitted_state(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.order_send_should_raise = True
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(OrderSendFailedError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    record = store.get_idempotency_record("c1")
    assert record.state == OrderState.SUBMITTED

    # Now retry with a fresh backend call (send would succeed) -- must
    # NOT blindly resend; the stuck SUBMITTED row requires reconciliation.
    ready_backend.order_send_should_raise = False
    with pytest.raises(ReconciliationRequiredError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


# 14. external/manual position blocks new entry.
def test_external_manual_position_blocks_new_entry(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    # A position with no TradingIA magic/comment -- still counts.
    ready_backend.set_positions([BackendPosition(ticket=42, symbol="EURUSD", side="sell", volume=Decimal("0.05"), price_open=Decimal("1.2"), magic=None, comment="manual")])
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(TooManyPositionsError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())


# 15. kill switch allows close.
def test_kill_switch_active_does_not_block_close(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    open_result = place_demo_order(ready_backend, store, request, **_open_kwargs())

    store.set_kill_switch("active", "test")
    close_request = DemoCloseRequest(client_order_id="close-1", position_id=open_result.position_id)
    close_result = close_demo_position(ready_backend, store, close_request, max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0, deviation_points=20, magic=999, request_id="r2")
    assert close_result.status == "filled"
    assert ready_backend.positions_get() == []


# 16. close wrong/nonexistent position rejected.
def test_close_nonexistent_position_rejected(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    close_request = DemoCloseRequest(client_order_id="close-1", position_id="999999")
    with pytest.raises(PositionNotFoundError):
        close_demo_position(ready_backend, store, close_request, max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0, deviation_points=20, magic=999, request_id="r1")


# 17. non-demo account rejects close too (server-side check applies to close as well).
def test_close_rejected_when_account_not_demo(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    open_result = place_demo_order(ready_backend, store, request, **_open_kwargs())

    ready_backend.account = BackendAccountInfo(login=1, trade_mode_code=2, server="Live", currency="USD", balance=Decimal("1"), equity=Decimal("1"), margin=Decimal("0"), margin_free=Decimal("1"))
    close_request = DemoCloseRequest(client_order_id="close-1", position_id=open_result.position_id)
    with pytest.raises(NotDemoError):
        close_demo_position(ready_backend, store, close_request, max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0, deviation_points=20, magic=999, request_id="r2")


# 18. order_check fail -> order_send never called.
def test_order_check_failure_prevents_order_send(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.order_check_should_fail = True
    original_send = ready_backend.order_send
    calls = []
    ready_backend.order_send = lambda req: (calls.append(req), original_send(req))[1]

    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(OrderCheckFailedError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert calls == []


# 19. MT5 order_send failure (non-DONE retcode) persisted/journaled.
def test_order_send_non_done_retcode_persisted_and_journaled(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.order_send_retcode = 10004  # some rejection code
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(OrderSendFailedError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    record = store.get_idempotency_record("c1")
    assert record.state == OrderState.REJECTED
    journal = store.read_journal(20)
    actions = [e["action"] for e in journal]
    assert "place_order.rejected" in actions


# 20. successful fill fields mapped correctly.
def test_successful_fill_fields_mapped_correctly(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    result = place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert result.reference_price == Decimal("1.1002")  # ask, for BUY
    assert result.observed_bid == Decimal("1.1000")
    assert result.observed_ask == Decimal("1.1002")
    assert result.filled_volume == Decimal("0.01")
    assert result.mt5_retcode == 10009


# 21. slippage Decimal clean.
def test_slippage_is_clean_decimal(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    result = place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert isinstance(result.slippage, Decimal)
    assert "e" not in str(result.slippage).lower()


# 22. journal no secrets.
def test_journal_entries_have_no_secret_looking_fields(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    place_demo_order(ready_backend, store, request, **_open_kwargs())
    journal_text = str(store.read_journal(50))
    assert "password" not in journal_text.lower()
    assert "bearer" not in journal_text.lower()


# 27. malformed MT5 result sanitized (MT5BackendError message with a path/secret-looking string).
def test_malformed_mt5_error_sanitized_in_journal_and_exception(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    ready_backend.order_send_should_raise = True

    class LeakySymbolInfo(FakeMT5Backend):
        pass

    # Monkeypatch order_send to raise with a secret-looking message.
    def raising_send(req):
        raise MT5BackendError("failed: Authorization: Bearer sekrit123 at /home/user/.mt5/secret")

    ready_backend.order_send = raising_send
    request = DemoOrderRequest(client_order_id="c1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(OrderSendFailedError) as excinfo:
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert "sekrit123" not in str(excinfo.value)
    journal_text = str(store.read_journal(50))
    assert "sekrit123" not in journal_text


# 29. duplicate HTTP request does not duplicate order (same as #11, phrased at the trading layer).
def test_duplicate_request_never_creates_two_positions(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="dup-1", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    for _ in range(3):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert len(ready_backend.positions_get()) == 1


# Additional: close uses the position's live volume, not a caller-supplied one.
def test_close_uses_position_live_volume():
    backend = FakeMT5Backend()
    backend.set_symbol("EURUSD", _tradable_symbol())
    backend.set_tick("EURUSD", BackendTick(symbol="EURUSD", time_utc=datetime.now(timezone.utc), bid=Decimal("1.1"), ask=Decimal("1.1002")))
    backend.set_positions([BackendPosition(ticket=7, symbol="EURUSD", side="buy", volume=Decimal("0.03"), price_open=Decimal("1.09"))])
    store = BridgeStore(":memory:")
    run_reconciliation(store, backend)
    close_request = DemoCloseRequest(client_order_id="close-1", position_id="7")
    result = close_demo_position(backend, store, close_request, max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0, deviation_points=20, magic=999, request_id="r1")
    assert result.closed_volume == Decimal("0.03")


def test_terminal_rejected_client_order_id_is_never_reused_for_new_send(ready_backend, store):
    from mt5_bridge.store import compute_request_fingerprint

    _run_reconciliation(store, ready_backend)
    request_hash = compute_request_fingerprint(
        symbol="EURUSD", side="buy", volume="0.01", action="open"
    )
    store.begin_idempotent_request("resolved-id", request_hash)
    store.update_idempotency_state(
        "resolved-id", OrderState.REJECTED, error_code="aborted_before_submission"
    )

    request = DemoOrderRequest(
        client_order_id="resolved-id", symbol="EURUSD", side="buy", volume=Decimal("0.01")
    )
    with pytest.raises(ReconciliationRequiredError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    assert ready_backend.positions_get() == []


def test_successful_open_journal_has_full_audit_context_and_request_id(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoOrderRequest(client_order_id="audit-open", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    result = place_demo_order(ready_backend, store, request, **_open_kwargs(request_id="req-audit-open"))

    entries = store.read_journal_for_client_order_id("audit-open")
    filled = next(e for e in entries if e["action"] == "place_order.filled")
    payload = filled["payload"]
    assert filled["request_id"] == "req-audit-open"
    assert payload["symbol"] == "EURUSD"
    assert payload["side"] == "buy"
    assert payload["requested_volume"] == "0.01"
    assert payload["filled_volume"] == "0.01"
    assert payload["quote_timestamp"].endswith("+00:00")
    assert payload["observed_bid"] == "1.1000"
    assert payload["observed_ask"] == "1.1002"
    assert payload["spread"] == "0.0002"
    assert payload["reference_price"] == "1.1002"
    assert payload["fill_price"] == str(result.fill_price)
    assert payload["slippage"] == str(result.slippage)
    assert payload["mt5_retcode"] == 10009
    assert payload["broker_order_id"] == result.broker_order_id
    assert payload["deal_id"] == result.deal_id
    assert payload["position_id"] == result.position_id
    assert payload["result_timestamp"].endswith("+00:00")


def test_successful_close_journal_has_full_audit_context_and_request_id(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    opened = place_demo_order(
        ready_backend,
        store,
        DemoOrderRequest(client_order_id="audit-open-2", symbol="EURUSD", side="buy", volume=Decimal("0.01")),
        **_open_kwargs(request_id="req-open-2"),
    )
    closed = close_demo_position(
        ready_backend,
        store,
        DemoCloseRequest(client_order_id="audit-close", position_id=opened.position_id),
        max_quote_age_seconds=5.0,
        max_quote_future_skew_seconds=1.0,
        deviation_points=20,
        magic=999,
        request_id="req-audit-close",
    )

    entries = store.read_journal_for_client_order_id("audit-close")
    filled = next(e for e in entries if e["action"] == "close_position.filled")
    payload = filled["payload"]
    assert filled["request_id"] == "req-audit-close"
    assert payload["position_id"] == opened.position_id
    assert payload["symbol"] == "EURUSD"
    assert payload["position_side"] == "buy"
    assert payload["closing_side"] == "sell"
    assert payload["closed_volume"] == "0.01"
    assert payload["quote_timestamp"].endswith("+00:00")
    assert payload["observed_bid"] == "1.1000"
    assert payload["observed_ask"] == "1.1002"
    assert payload["spread"] == "0.0002"
    assert payload["reference_price"] == "1.1000"
    assert payload["fill_price"] == str(closed.fill_price)
    assert payload["slippage"] == str(closed.slippage)
    assert payload["mt5_retcode"] == 10009
    assert payload["deal_id"] == closed.deal_id
    assert payload["result_timestamp"].endswith("+00:00")


def test_close_retry_replays_after_position_is_gone(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    opened = place_demo_order(
        ready_backend,
        store,
        DemoOrderRequest(client_order_id="open-for-retry", symbol="EURUSD", side="buy", volume=Decimal("0.01")),
        **_open_kwargs(),
    )
    request = DemoCloseRequest(client_order_id="close-retry", position_id=opened.position_id)
    first = close_demo_position(
        ready_backend, store, request,
        max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0,
        deviation_points=20, magic=999, request_id="req-close-1",
    )
    assert ready_backend.positions_get() == []
    second = close_demo_position(
        ready_backend, store, request,
        max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0,
        deviation_points=20, magic=999, request_id="req-close-2",
    )
    assert second.idempotent_replay is True
    assert second.deal_id == first.deal_id
    assert ready_backend.positions_get() == []


def test_pre_submission_reject_does_not_poison_reconciliation(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    store.set_kill_switch("active", "test")
    request = DemoOrderRequest(client_order_id="known-reject", symbol="EURUSD", side="buy", volume=Decimal("0.01"))
    with pytest.raises(KillSwitchActiveError):
        place_demo_order(ready_backend, store, request, **_open_kwargs())
    record = store.get_idempotency_record("known-reject")
    assert record is not None and record.state is OrderState.REJECTED
    report = run_reconciliation(store, ready_backend)
    assert report.state.value == "ok"


def test_close_missing_position_is_terminal_pre_submission_reject(ready_backend, store):
    _run_reconciliation(store, ready_backend)
    request = DemoCloseRequest(client_order_id="missing-close", position_id="999999")
    with pytest.raises(PositionNotFoundError):
        close_demo_position(
            ready_backend, store, request,
            max_quote_age_seconds=5.0, max_quote_future_skew_seconds=1.0,
            deviation_points=20, magic=999, request_id="req-missing",
        )
    record = store.get_idempotency_record("missing-close")
    assert record is not None and record.state is OrderState.REJECTED
    report = run_reconciliation(store, ready_backend)
    assert report.state.value == "ok"
