"""Startup and on-demand reconciliation (FX Phase 0, Step 4).

Compares the idempotency DB against MT5's own reported state (open
positions, working orders) and flags ambiguity rather than trying to
resolve it automatically. This module NEVER deletes or "fixes" a
mismatched idempotency row -- see `run_reconciliation`'s docstring for
exactly what it does and does not do.

Reconciliation runs:
1. At bridge startup (see `mt5_bridge/__main__.py`), before the server
   starts accepting write requests.
2. On demand via `POST /v1/reconciliation/run`.

While `ReconciliationState` is anything other than `OK`, `authorize_open`
(Step 1's policy, unchanged) already denies new entries -- this module's
job is only to compute that state honestly, not to enforce the denial
itself (that's `SafeExecutionService`'s job, reusing the same policy
function Step 1 built).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from mt5_bridge.backend import MT5Backend, MT5BackendError
from mt5_bridge.identity import build_mt5_comment
from mt5_bridge.sanitize import sanitize_message
from mt5_bridge.store import BridgeStore, IdempotencyStateError, OrderState


class ReconciliationState(Enum):
    """Mirrors `src.execution.base.ReconciliationState` exactly (same
    member names/values), but defined independently here because
    `mt5_bridge/` is deployed standalone to the Windows VM -- it must
    never import from `src.*`, which lives only in the main Linux repo
    and is NOT copied to the VM (see mt5_bridge/README.md step 4). The
    Linux-side client parses this bridge's JSON response into its own
    `src.execution.base.ReconciliationState` independently; the two
    enums are kept in sync by convention (same values: "ok", "mismatch",
    "unknown"), not by a shared import.
    """

    OK = "ok"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReconciliationReport:
    state: ReconciliationState
    checked_at: datetime
    details: tuple[str, ...] = field(default_factory=tuple)


class ReceivedResolutionError(Exception):
    """A manual resolution of a RECEIVED row could not be proven safe.

    This is intentionally narrow: SUBMITTED is never resolvable through
    this path because order_send may already have happened.
    """


def resolve_received_attempt(
    store: BridgeStore,
    backend: MT5Backend,
    client_order_id: str,
    *,
    magic: int,
    request_id: str | None = None,
) -> ReconciliationReport:
    """Manually close out one *provably pre-submission* idempotency row.

    Safety proof required before mutating anything:
    - row exists and is exactly RECEIVED;
    - no broker/deal/position/result identifiers are present;
    - journal contains no order_send boundary/submission/fill evidence;
    - current MT5 positions/orders contain no TradingIA identity matching
      this client_order_id (magic + deterministic comment tag).

    On success the row is terminalized as REJECTED with
    `aborted_before_submission`, an append-only journal event is added,
    and reconciliation is recomputed. SUBMITTED is never accepted here.
    """

    record = store.get_idempotency_record(client_order_id)
    if record is None:
        raise ReceivedResolutionError(f"client_order_id {client_order_id!r} does not exist")
    if record.state is not OrderState.RECEIVED:
        raise ReceivedResolutionError(
            f"client_order_id {client_order_id!r} is state={record.state.value}; only RECEIVED can be resolved here"
        )
    if any((record.broker_order_id, record.deal_id, record.position_id, record.result_payload)):
        raise ReceivedResolutionError(
            f"client_order_id {client_order_id!r} has broker/result identifiers; refusing pre-submission resolution"
        )

    journal = store.read_journal_for_client_order_id(client_order_id)
    unsafe_actions = {
        "place_order.submitting",
        "place_order.crash_during_send",
        "place_order.filled",
        "close_position.submitting",
        "close_position.crash_during_send",
        "close_position.filled",
    }
    seen_unsafe = sorted({e["action"] for e in journal if e["action"] in unsafe_actions})
    if seen_unsafe:
        raise ReceivedResolutionError(
            f"client_order_id {client_order_id!r} has submission/send evidence in journal: {', '.join(seen_unsafe)}"
        )

    # Re-check the live MT5 surface before changing the row. This is not
    # the primary proof (RECEIVED + no submit boundary is), but it is a
    # useful independent defense against identity confusion/manual DB edits.
    try:
        positions = backend.positions_get()
        orders = backend.orders_get()
    except MT5BackendError as exc:
        raise ReceivedResolutionError(
            f"backend unavailable; cannot safely resolve RECEIVED row: {sanitize_message(str(exc))}"
        ) from exc

    expected_comment = build_mt5_comment(client_order_id)
    matches = [
        ("position", str(p.ticket))
        for p in positions
        if p.magic == magic and p.comment == expected_comment
    ] + [
        ("order", str(o.ticket))
        for o in orders
        if o.magic == magic and o.comment == expected_comment
    ]
    if matches:
        evidence = ", ".join(f"{kind}:{ticket}" for kind, ticket in matches)
        raise ReceivedResolutionError(
            f"MT5 currently reports matching TradingIA identity for {client_order_id!r}: {evidence}"
        )

    try:
        store.transition_idempotency_state(
            client_order_id,
            expected_state=OrderState.RECEIVED,
            new_state=OrderState.REJECTED,
            error_code="aborted_before_submission",
        )
    except IdempotencyStateError as exc:
        raise ReceivedResolutionError(
            f"idempotency state changed concurrently; refusing resolution: {sanitize_message(str(exc))}"
        ) from exc

    store.append_journal(
        request_id=request_id,
        client_order_id=client_order_id,
        action="reconciliation.received_resolved",
        payload={
            "resolution": "aborted_before_submission",
            "prior_state": "received",
            "mt5_identity_matches": 0,
        },
    )
    return run_reconciliation(store, backend)


def run_reconciliation(store: BridgeStore, backend: MT5Backend) -> ReconciliationReport:
    """Recomputes reconciliation state from scratch.

    Ambiguous means: an idempotency row is stuck in RECEIVED or SUBMITTED
    (a write was in flight and never reached a terminal state -- see
    `mt5_bridge/store.py::BridgeStore.find_incomplete_at_startup`) AND
    there is no way from here to positively confirm what actually
    happened in MT5 for that specific `client_order_id` (Step 4's
    `comment` tagging, see `mt5_bridge/identity.py`, is what a future
    deeper-reconciliation pass would match against MT5's own
    positions/orders -- this function reports the ambiguity rather than
    guessing, per the explicit "no destructive auto-fix" requirement).

    Returns OK only when:
    - the backend is reachable, AND
    - no idempotency row is stuck in a non-terminal state.

    Returns MISMATCH when reachable but rows are stuck.
    Returns UNKNOWN when the backend itself cannot be queried right now.
    """

    now = datetime.now(timezone.utc)
    try:
        backend.positions_get()
        backend.orders_get()
    except MT5BackendError as exc:
        report = ReconciliationReport(
            state=ReconciliationState.UNKNOWN,
            checked_at=now,
            details=(f"backend unreachable during reconciliation: {exc}",),
        )
        _persist(store, report)
        return report

    incomplete = store.find_incomplete_at_startup()
    if incomplete:
        details = tuple(
            f"client_order_id={r.client_order_id} stuck in state={r.state.value} since {r.created_at.isoformat()}"
            for r in incomplete
        )
        report = ReconciliationReport(state=ReconciliationState.MISMATCH, checked_at=now, details=details)
        _persist(store, report)
        return report

    report = ReconciliationReport(state=ReconciliationState.OK, checked_at=now, details=())
    _persist(store, report)
    return report


def get_reconciliation_status(store: BridgeStore) -> ReconciliationReport:
    """Returns the last computed state without recomputing -- cheap,
    read-only. If reconciliation has never run, returns UNKNOWN (fail
    closed: absence of a check is not evidence of OK).
    """

    row = store.get_last_reconciliation()
    if row is None:
        return ReconciliationReport(
            state=ReconciliationState.UNKNOWN,
            checked_at=datetime.now(timezone.utc),
            details=("reconciliation has not run yet",),
        )
    state_str, checked_at, details = row
    return ReconciliationReport(state=ReconciliationState(state_str), checked_at=checked_at, details=tuple(details))


def _persist(store: BridgeStore, report: ReconciliationReport) -> None:
    store.set_last_reconciliation(report.state.value, report.checked_at, list(report.details))
