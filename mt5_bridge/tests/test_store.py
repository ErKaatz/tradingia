"""Tests for SQLite idempotency/journal/kill-switch/reconciliation
storage (FX Phase 0, Step 4)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mt5_bridge.store import BridgeStore, IdempotencyConflictError, OrderState, compute_request_fingerprint


@pytest.fixture
def store():
    s = BridgeStore(":memory:")
    yield s
    s.close()


def test_fingerprint_deterministic_for_same_semantic_fields():
    h1 = compute_request_fingerprint(symbol="EURUSD", side="buy", volume="0.01")
    h2 = compute_request_fingerprint(symbol="EURUSD", side="buy", volume="0.01")
    assert h1 == h2


def test_fingerprint_differs_for_different_fields():
    h1 = compute_request_fingerprint(symbol="EURUSD", side="buy", volume="0.01")
    h2 = compute_request_fingerprint(symbol="EURUSD", side="sell", volume="0.01")
    assert h1 != h2


def test_begin_idempotent_request_new_id_creates_received_row(store):
    record = store.begin_idempotent_request("id-1", "hash-1")
    assert record.state == OrderState.RECEIVED


def test_begin_idempotent_request_same_id_same_hash_returns_existing(store):
    r1 = store.begin_idempotent_request("id-1", "hash-1")
    r2 = store.begin_idempotent_request("id-1", "hash-1")
    assert r1.created_at == r2.created_at


def test_begin_idempotent_request_same_id_different_hash_conflicts(store):
    store.begin_idempotent_request("id-1", "hash-1")
    with pytest.raises(IdempotencyConflictError):
        store.begin_idempotent_request("id-1", "hash-2")


def test_update_idempotency_state_persists_fields(store):
    store.begin_idempotent_request("id-1", "hash-1")
    store.update_idempotency_state("id-1", OrderState.FILLED, broker_order_id="99", deal_id="55", result_payload={"a": 1})
    record = store.get_idempotency_record("id-1")
    assert record.state == OrderState.FILLED
    assert record.broker_order_id == "99"
    assert record.deal_id == "55"
    assert record.result_payload == {"a": 1}


def test_find_incomplete_at_startup_only_returns_non_terminal(store):
    store.begin_idempotent_request("stuck-1", "h1")
    store.begin_idempotent_request("done-1", "h2")
    store.update_idempotency_state("done-1", OrderState.FILLED, result_payload={})
    incomplete = store.find_incomplete_at_startup()
    ids = {r.client_order_id for r in incomplete}
    assert ids == {"stuck-1"}


def test_journal_is_append_only_and_ordered(store):
    store.append_journal(request_id="r1", client_order_id="c1", action="a1", payload={"x": 1})
    store.append_journal(request_id="r2", client_order_id="c1", action="a2", payload={"x": 2})
    entries = store.read_journal(limit=10)
    assert len(entries) == 2
    assert entries[0]["action"] == "a2"  # most recent first
    assert entries[1]["action"] == "a1"


def test_journal_limit_is_bounded(store):
    for i in range(5):
        store.append_journal(request_id=None, client_order_id=None, action=f"a{i}", payload={})
    entries = store.read_journal(limit=2)
    assert len(entries) == 2


def test_journal_no_secrets_field_names_by_convention():
    """The store persists whatever payload it's given -- this test
    documents that callers (mt5_bridge.trading) are responsible for
    sanitizing before calling append_journal; see test_trading.py for
    the actual sanitization guarantee."""
    store = BridgeStore(":memory:")
    store.append_journal(request_id="r1", client_order_id="c1", action="test", payload={"note": "no secrets here"})
    entries = store.read_journal()
    assert "password" not in str(entries)
    assert "token" not in str(entries).lower() or "no secrets here" in str(entries)


def test_kill_switch_defaults_inactive(store):
    status, changed_at, reason = store.get_kill_switch()
    assert status == "inactive"
    assert reason is None


def test_kill_switch_set_and_get(store):
    store.set_kill_switch("active", "manual test")
    status, changed_at, reason = store.get_kill_switch()
    assert status == "active"
    assert reason == "manual test"


def test_kill_switch_survives_reopening_file_backed_store():
    """Persistence survives a restart -- opens a real file, closes,
    reopens, confirms the state is still there."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.sqlite3"
        store1 = BridgeStore(db_path)
        store1.set_kill_switch("active", "before restart")
        store1.close()

        store2 = BridgeStore(db_path)
        status, changed_at, reason = store2.get_kill_switch()
        assert status == "active"
        assert reason == "before restart"
        store2.close()


def test_idempotency_survives_reopening_file_backed_store():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.sqlite3"
        store1 = BridgeStore(db_path)
        store1.begin_idempotent_request("id-1", "hash-1")
        store1.update_idempotency_state("id-1", OrderState.FILLED, result_payload={"ok": True})
        store1.close()

        store2 = BridgeStore(db_path)
        record = store2.get_idempotency_record("id-1")
        assert record is not None
        assert record.state == OrderState.FILLED
        assert record.result_payload == {"ok": True}
        store2.close()


def test_reconciliation_state_survives_reopening_file_backed_store():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.sqlite3"
        store1 = BridgeStore(db_path)
        from datetime import datetime, timezone

        store1.set_last_reconciliation("ok", datetime.now(timezone.utc), [])
        store1.close()

        store2 = BridgeStore(db_path)
        state, checked_at, details = store2.get_last_reconciliation()
        assert state == "ok"
        store2.close()


def test_get_last_reconciliation_none_before_ever_run(store):
    assert store.get_last_reconciliation() is None


def test_transition_idempotency_state_requires_expected_state(store):
    from mt5_bridge.store import IdempotencyStateError

    store.begin_idempotent_request("id-transition", "h")
    store.transition_idempotency_state(
        "id-transition",
        expected_state=OrderState.RECEIVED,
        new_state=OrderState.REJECTED,
        error_code="aborted_before_submission",
    )
    record = store.get_idempotency_record("id-transition")
    assert record is not None
    assert record.state == OrderState.REJECTED
    assert record.error_code == "aborted_before_submission"

    with pytest.raises(IdempotencyStateError):
        store.transition_idempotency_state(
            "id-transition",
            expected_state=OrderState.RECEIVED,
            new_state=OrderState.SUBMITTED,
        )


def test_read_journal_for_client_order_id_filters_and_orders_oldest_first(store):
    store.append_journal(request_id="r1", client_order_id="c1", action="first", payload={})
    store.append_journal(request_id="r2", client_order_id="other", action="ignore", payload={})
    store.append_journal(request_id="r3", client_order_id="c1", action="second", payload={})
    entries = store.read_journal_for_client_order_id("c1")
    assert [e["action"] for e in entries] == ["first", "second"]
