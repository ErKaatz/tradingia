from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.execution.base import (
    AccountSummary, AccountTradeMode, HealthStatus, KillSwitchState,
    KillSwitchStatus, Position, Quote, ReconciliationReport,
    ReconciliationState, Side, SymbolMetadata, TerminalStatus,
)
from src.runtime.operational import (
    DecisionReason, JsonlDecisionJournal, OperationalRuntime, RuntimeConfig, RuntimeLock,
    RuntimeMode,
)


class FakeClient:
    def __init__(self, quote_timestamp=None):
        self.quote_timestamp = quote_timestamp or datetime.now(timezone.utc)
        self._positions = ()
        self._kill = KillSwitchStatus.INACTIVE
        self._reconciliation = ReconciliationState.OK
        self._connected = True

    def health(self):
        return HealthStatus(bridge_alive=self._connected, terminal_connected=self._connected, server_time=None)

    def terminal(self):
        return TerminalStatus(connected=self._connected, trade_allowed=True)

    def account(self):
        return AccountSummary("secret-account-id", AccountTradeMode.DEMO, Decimal("100"), Decimal("100"), "USD")

    def symbol_metadata(self, symbol):
        return SymbolMetadata(symbol, Decimal("0.01"), Decimal("0.01"), Decimal("1"), Decimal("100000"), 5, Decimal("0.00001"))

    def quote(self, symbol):
        return Quote(symbol, Decimal("1.1"), Decimal("1.1001"), self.quote_timestamp)

    def positions(self):
        return self._positions

    def orders(self):
        return ()

    def kill_switch_status(self):
        return KillSwitchState(self._kill, None)

    def reconciliation_status(self):
        return ReconciliationReport(self._reconciliation, datetime.now(timezone.utc))


def config(tmp_path, **changes):
    values = dict(mode=RuntimeMode.READ_ONLY, symbol="EURUSD", strategy_id="NONE", journal_path=tmp_path / "journal.jsonl")
    values.update(changes)
    return RuntimeConfig(**values)


def test_no_strategy_cycle_is_no_action_and_never_exposes_write_executor(tmp_path):
    runtime = OperationalRuntime(FakeClient(), config(tmp_path))
    result = runtime.run_cycle()
    assert result.decision == "NO_ACTION"
    assert result.reason == DecisionReason.NO_AUTHORIZED_STRATEGY.value
    assert result.execution_allowed is False
    assert result.execution_denial_reason == DecisionReason.NO_AUTHORIZED_STRATEGY.value
    assert result.preflight_passed is True
    assert not hasattr(runtime.executor, "place_order")
    assert JsonlDecisionJournal(runtime.config.journal_path).last()["decision"] == "NO_ACTION"


def test_stale_quote_fails_closed_and_is_journaled(tmp_path):
    client = FakeClient(datetime.now(timezone.utc) - timedelta(seconds=60))
    result = OperationalRuntime(client, config(tmp_path)).run_cycle()
    assert result.reason == DecisionReason.QUOTE_STALE.value
    assert result.connectivity == "STALE"
    assert result.execution_allowed is False


def test_unknown_existing_position_blocks_new_exposure(tmp_path):
    client = FakeClient()
    client._positions = (Position("manual-1", "EURUSD", Side.BUY, Decimal("0.01"), Decimal("1.1")),)
    result = OperationalRuntime(client, config(tmp_path)).run_cycle()
    assert result.reason == DecisionReason.UNKNOWN_BROKER_POSITION.value
    assert result.execution_allowed is False


def test_kill_switch_and_reconciliation_fail_closed(tmp_path):
    client = FakeClient()
    client._kill = KillSwitchStatus.ACTIVE
    result = OperationalRuntime(client, config(tmp_path)).run_cycle()
    assert result.reason == DecisionReason.KILL_SWITCH_ACTIVE.value
    client = FakeClient()
    client._reconciliation = ReconciliationState.MISMATCH
    result = OperationalRuntime(client, config(tmp_path)).run_cycle()
    assert result.reason == DecisionReason.RECONCILIATION_FAILED.value


def test_restart_recovers_last_journal_without_account_id(tmp_path):
    cfg = config(tmp_path)
    OperationalRuntime(FakeClient(), cfg).run_cycle()
    record = JsonlDecisionJournal(cfg.journal_path).last()
    assert record is not None
    assert record["account_identity"] != "secret-account-id"
    assert len(record["account_identity"]) == 16


def test_live_mode_remains_hard_denied_even_with_healthy_reads(tmp_path):
    result = OperationalRuntime(FakeClient(), config(tmp_path, mode=RuntimeMode.LIVE)).run_cycle()
    assert result.decision == "NO_ACTION"
    assert result.reason == DecisionReason.LIVE_DISABLED.value
    assert result.execution_allowed is False


def test_runtime_config_refuses_non_none_strategy(monkeypatch):
    monkeypatch.setenv("TRADINGIA_STRATEGY", "anything")
    with pytest.raises(ValueError, match="must be NONE"):
        RuntimeConfig.from_env()


def test_single_instance_lock_refuses_second_runtime(tmp_path):
    path = tmp_path / "runtime.lock"
    with RuntimeLock(path):
        with pytest.raises(RuntimeError, match="already active"):
            with RuntimeLock(path):
                pass


def test_no_trade_soak_has_no_execution_capability_or_growth(tmp_path):
    runtime = OperationalRuntime(FakeClient(), config(tmp_path))
    for _ in range(1000):
        result = runtime.run_cycle()
        assert result.decision == "NO_ACTION"
    assert runtime._cycle_count == 1000
    assert not hasattr(runtime.executor, "place_order")
    assert runtime.heartbeat_path.exists()


def test_backoff_escalates_on_degraded_cycles_and_caps_at_max():
    next_backoff = OperationalRuntime._next_backoff
    backoff = 30.0  # config.cycle_seconds
    for expected in (60.0, 120.0, 240.0, 300.0, 300.0):
        backoff = next_backoff(backoff, cycle_seconds=30.0, max_backoff_seconds=300.0, healthy=False)
        assert backoff == expected


def test_backoff_resets_to_cycle_seconds_as_soon_as_a_cycle_is_healthy():
    next_backoff = OperationalRuntime._next_backoff
    escalated = next_backoff(30.0, cycle_seconds=30.0, max_backoff_seconds=300.0, healthy=False)
    assert escalated > 30.0
    recovered = next_backoff(escalated, cycle_seconds=30.0, max_backoff_seconds=300.0, healthy=True)
    assert recovered == 30.0


def test_run_forever_stops_promptly_when_stop_requested_during_a_long_backoff(tmp_path):
    # Regression test: a plain time.sleep(backoff) is NOT interrupted by
    # request_stop() (PEP 475 means an unhandled-exception signal handler
    # just lets sleep() continue for its full remaining duration) -- without
    # _sleep_interruptibly, this test would take the full cycle_seconds
    # (here deliberately large relative to the assertion's tolerance) to
    # return instead of stopping within about a second of the request.
    cfg = config(tmp_path, cycle_seconds=5.0, max_backoff_seconds=5.0)
    runtime = OperationalRuntime(FakeClient(), cfg)

    def request_stop_soon():
        time.sleep(0.2)
        runtime.request_stop()

    threading.Thread(target=request_stop_soon, daemon=True).start()
    started = time.monotonic()
    runtime.run_forever()
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
