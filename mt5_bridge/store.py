"""Persistent SQLite storage for idempotency, journal, and kill switch
(FX Phase 0, Step 4).

One SQLite file, three tables, opened with `check_same_thread=False` and
a single `threading.Lock` around every write -- Step 4's bridge is a
single small FastAPI process handling one demo account; this is not
designed for high concurrency, it is designed to survive a crash and
never silently duplicate an order.

Tables:

- `idempotency`: one row per `client_order_id` ever seen for a WRITE
  action (open or close). Rows transition through `OrderState` and are
  the single source of truth for "have we already done this?". See
  `IdempotencyStore` below for the state machine and crash-consistency
  rules (Step 4 sections 5-8 of the request).
- `journal`: append-only. Never updated or deleted from application
  code. Every field that could carry a secret is expected to already be
  sanitized by the caller (see `mt5_bridge/sanitize.py`) before being
  passed to `JournalStore.append` -- this module does not re-sanitize,
  it persists what it's given, so callers are the ones responsible for
  not handing it something dirty.
- `kill_switch`: single-row table holding the current state. Persisted
  so a bridge restart does not silently clear an operator's kill switch.

Design note on `request_hash`: computed by the caller (see
`compute_request_fingerprint` below) over the semantically meaningful
fields of a request (symbol, side, volume, order_type, action) --
deliberately excluding request timestamps or any field that would make
two *intentionally identical* retries hash differently. Same
`client_order_id` + same hash => idempotent replay. Same
`client_order_id` + different hash => conflict, never silently
overwritten.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class OrderState(Enum):
    RECEIVED = "received"
    SUBMITTED = "submitted"
    FILLED = "filled"
    REJECTED = "rejected"
    NEEDS_RECONCILIATION = "needs_reconciliation"


_TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.REJECTED})


class IdempotencyConflictError(Exception):
    """Same `client_order_id` was already used with a DIFFERENT request
    (different symbol/side/volume/order_type/action). The existing
    record is never overwritten -- this is a hard reject.
    """


class IdempotencyStateError(Exception):
    """A conditional state transition did not match the row's current
    state. Used for safety-sensitive transitions where proceeding after
    a concurrent/manual change could duplicate or mis-classify a write.
    """


@dataclass(frozen=True)
class IdempotencyRecord:
    client_order_id: str
    request_hash: str
    state: OrderState
    created_at: datetime
    updated_at: datetime
    broker_order_id: str | None
    deal_id: str | None
    position_id: str | None
    result_payload: dict[str, Any] | None
    error_code: str | None


def compute_request_fingerprint(**semantic_fields: Any) -> str:
    """Deterministic hash over semantically meaningful request fields
    only. Caller passes exactly the fields that must match for two
    requests with the same `client_order_id` to be considered the same
    intent (e.g. symbol, side, volume, order_type, action, position_id
    for a close) -- never a timestamp or anything that legitimately
    differs between an original request and its retry.
    """

    canonical = json.dumps(semantic_fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class BridgeStore:
    """Owns the single SQLite connection and all three tables. Pass
    `db_path=":memory:"` for tests that don't need cross-process
    persistence; pass a real file path for the actual bridge process.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    client_order_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    broker_order_id TEXT,
                    deal_id TEXT,
                    position_id TEXT,
                    result_payload TEXT,
                    error_code TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT,
                    client_order_id TEXT,
                    timestamp_utc TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kill_switch (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    status TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    reason TEXT
                )
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO kill_switch (id, status, changed_at, reason)
                VALUES (1, 'inactive', ?, NULL)
                """,
                (_iso(_utcnow()),),
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reconciliation (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    state TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    details TEXT NOT NULL
                )
                """
            )

    # ---------------------------------------------------------------- idempotency

    def get_idempotency_record(self, client_order_id: str) -> IdempotencyRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM idempotency WHERE client_order_id = ?", (client_order_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def begin_idempotent_request(self, client_order_id: str, request_hash: str) -> IdempotencyRecord:
        """Call at the very start of handling a write request, BEFORE
        touching MT5. Three outcomes:

        - No existing record: inserts a new RECEIVED row and returns it
          (caller proceeds to submit to MT5).
        - Existing record with the SAME hash: returns the existing record
          as-is (caller must NOT resubmit to MT5 -- see
          `IdempotencyRecord.state`: if terminal, replay the stored
          result; if not yet terminal, the caller is responsible for
          reconciliation rather than a blind resend).
        - Existing record with a DIFFERENT hash: raises
          `IdempotencyConflictError` -- never silently reused.
        """

        now = _utcnow()
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM idempotency WHERE client_order_id = ?", (client_order_id,)
            ).fetchone()
            if row is not None:
                existing = self._row_to_record(row)
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        f"client_order_id {client_order_id!r} was already used with a different request"
                    )
                return existing
            self._conn.execute(
                """
                INSERT INTO idempotency
                    (client_order_id, request_hash, state, created_at, updated_at,
                     broker_order_id, deal_id, position_id, result_payload, error_code)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
                """,
                (client_order_id, request_hash, OrderState.RECEIVED.value, _iso(now), _iso(now)),
            )
        return IdempotencyRecord(
            client_order_id=client_order_id,
            request_hash=request_hash,
            state=OrderState.RECEIVED,
            created_at=now,
            updated_at=now,
            broker_order_id=None,
            deal_id=None,
            position_id=None,
            result_payload=None,
            error_code=None,
        )

    def update_idempotency_state(
        self,
        client_order_id: str,
        state: OrderState,
        *,
        broker_order_id: str | None = None,
        deal_id: str | None = None,
        position_id: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        now = _utcnow()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE idempotency
                SET state = ?, updated_at = ?,
                    broker_order_id = COALESCE(?, broker_order_id),
                    deal_id = COALESCE(?, deal_id),
                    position_id = COALESCE(?, position_id),
                    result_payload = COALESCE(?, result_payload),
                    error_code = COALESCE(?, error_code)
                WHERE client_order_id = ?
                """,
                (
                    state.value,
                    _iso(now),
                    broker_order_id,
                    deal_id,
                    position_id,
                    json.dumps(result_payload) if result_payload is not None else None,
                    error_code,
                    client_order_id,
                ),
            )

    def transition_idempotency_state(
        self,
        client_order_id: str,
        *,
        expected_state: OrderState,
        new_state: OrderState,
        broker_order_id: str | None = None,
        deal_id: str | None = None,
        position_id: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        """Atomically transition one idempotency row only when it is in
        `expected_state`.

        This is intentionally stricter than `update_idempotency_state`:
        it is used at the RECEIVED->SUBMITTED safety boundary so a manual
        resolution racing with an in-flight request cannot be overwritten
        and followed by `order_send`.
        """

        now = _utcnow()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                UPDATE idempotency
                SET state = ?, updated_at = ?,
                    broker_order_id = COALESCE(?, broker_order_id),
                    deal_id = COALESCE(?, deal_id),
                    position_id = COALESCE(?, position_id),
                    result_payload = COALESCE(?, result_payload),
                    error_code = COALESCE(?, error_code)
                WHERE client_order_id = ? AND state = ?
                """,
                (
                    new_state.value,
                    _iso(now),
                    broker_order_id,
                    deal_id,
                    position_id,
                    json.dumps(result_payload) if result_payload is not None else None,
                    error_code,
                    client_order_id,
                    expected_state.value,
                ),
            )
            if cur.rowcount != 1:
                row = self._conn.execute(
                    "SELECT state FROM idempotency WHERE client_order_id = ?", (client_order_id,)
                ).fetchone()
                actual = row["state"] if row is not None else "missing"
                raise IdempotencyStateError(
                    f"client_order_id {client_order_id!r} expected state={expected_state.value}, actual={actual}"
                )

    def find_needs_reconciliation(self) -> list[IdempotencyRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM idempotency WHERE state = ?", (OrderState.NEEDS_RECONCILIATION.value,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def find_incomplete_at_startup(self) -> list[IdempotencyRecord]:
        """Records left in a non-terminal state (RECEIVED/SUBMITTED) when
        the bridge starts up -- these are exactly the crash-window rows
        Step 4 section 8 requires: never assumed failed, never blindly
        resent. Startup reconciliation must resolve them before new
        entries are allowed.
        """

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM idempotency WHERE state IN (?, ?)",
                (OrderState.RECEIVED.value, OrderState.SUBMITTED.value),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
        return IdempotencyRecord(
            client_order_id=row["client_order_id"],
            request_hash=row["request_hash"],
            state=OrderState(row["state"]),
            created_at=_parse_iso(row["created_at"]),
            updated_at=_parse_iso(row["updated_at"]),
            broker_order_id=row["broker_order_id"],
            deal_id=row["deal_id"],
            position_id=row["position_id"],
            result_payload=json.loads(row["result_payload"]) if row["result_payload"] else None,
            error_code=row["error_code"],
        )

    # ---------------------------------------------------------------- journal

    def append_journal(self, *, request_id: str | None, client_order_id: str | None, action: str, payload: dict[str, Any]) -> None:
        """Append-only. `payload` is persisted verbatim as JSON -- the
        caller is responsible for having sanitized it first (see
        `mt5_bridge/sanitize.py`); this function does not know which
        fields might be sensitive in an arbitrary journal entry shape.
        """

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO journal (request_id, client_order_id, timestamp_utc, action, payload) VALUES (?, ?, ?, ?, ?)",
                (request_id, client_order_id, _iso(_utcnow()), action, json.dumps(payload)),
            )

    def read_journal(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "request_id": r["request_id"],
                "client_order_id": r["client_order_id"],
                "timestamp": r["timestamp_utc"],
                "action": r["action"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def read_journal_for_client_order_id(self, client_order_id: str) -> list[dict[str, Any]]:
        """Return the complete append-only history for one client order,
        oldest first. Intended for reconciliation/manual-resolution proof,
        not general browsing.
        """

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM journal WHERE client_order_id = ? ORDER BY id ASC",
                (client_order_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "request_id": r["request_id"],
                "client_order_id": r["client_order_id"],
                "timestamp": r["timestamp_utc"],
                "action": r["action"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    # ---------------------------------------------------------------- kill switch

    def get_kill_switch(self) -> tuple[str, datetime, str | None]:
        with self._lock:
            row = self._conn.execute("SELECT status, changed_at, reason FROM kill_switch WHERE id = 1").fetchone()
        return row["status"], _parse_iso(row["changed_at"]), row["reason"]

    def set_kill_switch(self, status: str, reason: str | None) -> datetime:
        now = _utcnow()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE kill_switch SET status = ?, changed_at = ?, reason = ? WHERE id = 1",
                (status, _iso(now), reason),
            )
        return now

    # ---------------------------------------------------------------- reconciliation

    def get_last_reconciliation(self) -> tuple[str, datetime, list[str]] | None:
        with self._lock:
            row = self._conn.execute("SELECT state, checked_at, details FROM reconciliation WHERE id = 1").fetchone()
        if row is None:
            return None
        return row["state"], _parse_iso(row["checked_at"]), json.loads(row["details"])

    def set_last_reconciliation(self, state: str, checked_at: datetime, details: list[str]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO reconciliation (id, state, checked_at, details) VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET state = excluded.state, checked_at = excluded.checked_at, details = excluded.details
                """,
                (state, _iso(checked_at), json.dumps(details)),
            )
