"""Tests for startup/on-demand reconciliation (FX Phase 0, Step 4)."""

from __future__ import annotations

from mt5_bridge.backend import FakeMT5Backend, MT5BackendError
from mt5_bridge.reconciliation import ReconciliationState, get_reconciliation_status, run_reconciliation
from mt5_bridge.store import BridgeStore


def test_status_before_any_run_is_unknown():
    store = BridgeStore(":memory:")
    report = get_reconciliation_status(store)
    assert report.state == ReconciliationState.UNKNOWN


def test_run_with_clean_state_reports_ok():
    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    report = run_reconciliation(store, backend)
    assert report.state == ReconciliationState.OK
    assert report.details == ()


def test_run_reports_mismatch_for_stuck_idempotency_row():
    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    store.begin_idempotent_request("stuck-1", "hash-1")
    report = run_reconciliation(store, backend)
    assert report.state == ReconciliationState.MISMATCH
    assert any("stuck-1" in d for d in report.details)


def test_run_reports_unknown_when_backend_unreachable():
    store = BridgeStore(":memory:")

    class BrokenBackend(FakeMT5Backend):
        def positions_get(self):
            raise MT5BackendError("simulated disconnect")

    report = run_reconciliation(store, BrokenBackend())
    assert report.state == ReconciliationState.UNKNOWN


def test_get_status_after_run_returns_persisted_value():
    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    run_reconciliation(store, backend)
    status = get_reconciliation_status(store)
    assert status.state == ReconciliationState.OK


def test_run_does_not_delete_or_mutate_idempotency_rows():
    """Reconciliation must never destructively 'fix' a stuck row --
    only report on it."""
    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    store.begin_idempotent_request("stuck-1", "hash-1")
    run_reconciliation(store, backend)
    record = store.get_idempotency_record("stuck-1")
    assert record is not None
    from mt5_bridge.store import OrderState

    assert record.state == OrderState.RECEIVED  # untouched


def test_resolve_received_attempt_terminalizes_and_reconciliation_becomes_ok():
    from mt5_bridge.reconciliation import resolve_received_attempt
    from mt5_bridge.store import OrderState

    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    store.begin_idempotent_request("stuck-1", "hash-1")
    store.append_journal(
        request_id="req-1",
        client_order_id="stuck-1",
        action="place_order.begin",
        payload={"symbol": "EURUSD"},
    )
    run_reconciliation(store, backend)
    report = resolve_received_attempt(store, backend, "stuck-1", magic=20260903, request_id="resolve-1")
    assert report.state == ReconciliationState.OK
    record = store.get_idempotency_record("stuck-1")
    assert record is not None
    assert record.state == OrderState.REJECTED
    assert record.error_code == "aborted_before_submission"
    actions = [e["action"] for e in store.read_journal_for_client_order_id("stuck-1")]
    assert "reconciliation.received_resolved" in actions


def test_resolve_received_attempt_refuses_submitted():
    import pytest
    from mt5_bridge.reconciliation import ReceivedResolutionError, resolve_received_attempt
    from mt5_bridge.store import OrderState

    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    store.begin_idempotent_request("submitted-1", "hash-1")
    store.update_idempotency_state("submitted-1", OrderState.SUBMITTED)
    with pytest.raises(ReceivedResolutionError):
        resolve_received_attempt(store, backend, "submitted-1", magic=20260903)


def test_resolve_received_attempt_refuses_submission_evidence_in_journal():
    import pytest
    from mt5_bridge.reconciliation import ReceivedResolutionError, resolve_received_attempt

    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    store.begin_idempotent_request("unsafe-1", "hash-1")
    store.append_journal(
        request_id="r",
        client_order_id="unsafe-1",
        action="place_order.submitting",
        payload={},
    )
    with pytest.raises(ReceivedResolutionError):
        resolve_received_attempt(store, backend, "unsafe-1", magic=20260903)


def test_resolve_received_attempt_refuses_matching_mt5_identity():
    import pytest
    from decimal import Decimal
    from mt5_bridge.backend import BackendPosition
    from mt5_bridge.identity import build_mt5_comment
    from mt5_bridge.reconciliation import ReceivedResolutionError, resolve_received_attempt

    store = BridgeStore(":memory:")
    backend = FakeMT5Backend()
    client_order_id = "identity-1"
    store.begin_idempotent_request(client_order_id, "hash-1")
    backend.set_positions([
        BackendPosition(
            ticket=77,
            symbol="EURUSD",
            side="buy",
            volume=Decimal("0.01"),
            price_open=Decimal("1.1"),
            magic=20260903,
            comment=build_mt5_comment(client_order_id),
        )
    ])
    with pytest.raises(ReceivedResolutionError):
        resolve_received_attempt(store, backend, client_order_id, magic=20260903)
