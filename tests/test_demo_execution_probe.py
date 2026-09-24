from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.base import (
    AccountSummary, AccountTradeMode, CloseResult, Environment, ExecutionResult,
    KillSwitchState, KillSwitchStatus, OrderStatus, Position, Quote,
    ReconciliationReport, ReconciliationState, Side, SymbolMetadata, TerminalStatus,
)
from src.execution.policy import RealMoneyPolicy
from src.runtime.demo_execution_test import DemoExecutionProbe, DemoExecutionTestConfig, DemoExecutionTestError


class Client:
    def __init__(self):
        self.position = None
        self.place_calls = 0
        self.close_calls = 0
        self.kill = KillSwitchStatus.INACTIVE
        self.mode = AccountTradeMode.DEMO
        self.reconciliation = ReconciliationState.OK
        self.fail_open = False

    def account(self):
        return AccountSummary("a", self.mode, Decimal("100"), Decimal("100"), "USD", True, True)

    def terminal(self):
        return TerminalStatus(True, True)

    def symbol_metadata(self, symbol):
        return SymbolMetadata(symbol, Decimal("0.01"), Decimal("0.01"), Decimal("1"), Decimal("100000"), 5, Decimal("0.00001"))

    def quote(self, symbol):
        return Quote(symbol, Decimal("1.1"), Decimal("1.1001"), datetime.now(timezone.utc))

    def positions(self):
        return () if self.position is None else (self.position,)

    def orders(self):
        return ()

    def kill_switch_status(self):
        return KillSwitchState(self.kill, None)

    def reconciliation_status(self):
        return ReconciliationReport(self.reconciliation, datetime.now(timezone.utc))

    def run_reconciliation(self):
        return self.reconciliation_status()

    def place_order(self, request):
        self.place_calls += 1
        if self.fail_open:
            raise TimeoutError("response lost")
        self.position = Position("p1", request.symbol, request.side, request.volume, Decimal("1.1001"))
        return ExecutionResult(request.client_order_id, OrderStatus.FILLED, "o1", "d1", "p1", Decimal("1.1001"), request.volume,
                               request.volume, Decimal("1.1"), Decimal("1.1001"), Decimal("1.1001"), Decimal("0"), None,
                               datetime.now(timezone.utc))

    def close_position(self, request):
        self.close_calls += 1
        self.position = None
        return CloseResult(request.client_order_id, request.position_id, OrderStatus.FILLED, Decimal("0.01"), Decimal("1.1"),
                           Decimal("1.1001"), Decimal("1.1"), Decimal("1.1"), Decimal("0"), "d2", None, datetime.now(timezone.utc))


def policy():
    return RealMoneyPolicy(False, Decimal("10"), Decimal("0"), 1, True, True, True, True, True, True)


def config(tmp_path, side=Side.BUY):
    return DemoExecutionTestConfig("EURUSD", side, tmp_path / "state.json", "run-fixed", True)


def test_successful_single_use_open_close_cycle_expires(tmp_path):
    client = Client()
    probe = DemoExecutionProbe(client, policy(), config(tmp_path))
    result = probe.run()
    assert client.place_calls == 1 and client.close_calls == 1
    assert result["state"] == "CLOSED"
    assert result["test_authorization"] == "EXPIRED"
    with pytest.raises(DemoExecutionTestError, match="single-use"):
        probe.run()


def test_live_mode_is_refused_before_place_order(tmp_path):
    client = Client()
    client.mode = AccountTradeMode.LIVE
    with pytest.raises(DemoExecutionTestError, match="DEMO"):
        DemoExecutionProbe(client, policy(), config(tmp_path)).run()
    assert client.place_calls == 0


def test_live_runtime_mode_is_refused_before_any_write(monkeypatch):
    monkeypatch.setenv("TRADINGIA_MODE", "LIVE")
    monkeypatch.setenv("TRADINGIA_DEMO_EXECUTION_TEST", "ENABLED")
    with pytest.raises(DemoExecutionTestError, match="must be DEMO"):
        DemoExecutionTestConfig.from_env(side="buy")


def test_kill_switch_and_foreign_position_refuse_open(tmp_path):
    client = Client()
    client.kill = KillSwitchStatus.ACTIVE
    with pytest.raises(DemoExecutionTestError, match="kill switch"):
        DemoExecutionProbe(client, policy(), config(tmp_path)).run()
    assert client.place_calls == 0
    client = Client()
    client.position = Position("foreign", "GBPUSD", Side.BUY, Decimal("0.01"), Decimal("1"))
    with pytest.raises(DemoExecutionTestError, match="foreign"):
        DemoExecutionProbe(client, policy(), config(tmp_path)).run()
    assert client.place_calls == 0


def test_ambiguous_open_is_never_retried_and_requires_reconciliation(tmp_path):
    client = Client()
    client.fail_open = True
    with pytest.raises(DemoExecutionTestError, match="ambiguous"):
        DemoExecutionProbe(client, policy(), config(tmp_path)).run()
    assert client.place_calls == 1
    assert client.close_calls == 0
    assert DemoExecutionProbe(client, policy(), config(tmp_path)).state.load()["state"] == "AMBIGUOUS"


def test_reconciliation_failure_refuses_before_open(tmp_path):
    client = Client()
    client.reconciliation = ReconciliationState.MISMATCH
    with pytest.raises(DemoExecutionTestError, match="reconciliation"):
        DemoExecutionProbe(client, policy(), config(tmp_path)).run()
    assert client.place_calls == 0
