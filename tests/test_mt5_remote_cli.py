"""Tests for `src/cli/mt5_remote_cli.py`'s output formatting (FX Phase 0).

These tests never talk to a real bridge: `_build_client` is monkeypatched
to return a fake client carrying a fixed `HealthStatus`/etc, so we can
assert on exactly what `tia mt5 status` prints without any network or
process boundary.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import src.cli.mt5_remote_cli as mt5_remote_cli
from src.execution.base import (
    AccountSummary,
    AccountTradeMode,
    HealthStatus,
    KillSwitchState,
    KillSwitchStatus,
    Quote,
    ReconciliationReport,
    ReconciliationState,
    Side,
    SymbolMetadata,
    TerminalStatus,
)
from src.execution.safe_execution import SafeExecutionQuoteFreshnessError, SafeExecutionService
from src.execution.policy import RealMoneyPolicy


class _FakeStatusClient:
    def __init__(self, health: HealthStatus) -> None:
        self._health = health

    def health(self) -> HealthStatus:
        return self._health

    def terminal(self) -> TerminalStatus:
        return TerminalStatus(connected=True, trade_allowed=True, dlls_allowed=False, name="MetaTrader 5", company="Fake Broker", build=1)

    def account(self) -> AccountSummary:
        return AccountSummary(
            account_id="12345",
            trade_mode=AccountTradeMode.DEMO,
            balance=Decimal("100.00"),
            equity=Decimal("100.00"),
            currency="USD",
            trade_allowed=True,
            trade_expert=True,
        )

    def kill_switch_status(self) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.INACTIVE, changed_at=None)

    def reconciliation_status(self) -> ReconciliationReport:
        return ReconciliationReport(state=ReconciliationState.OK, checked_at=datetime(2026, 9, 3, tzinfo=timezone.utc))


def test_cmd_status_prints_bridge_version_and_build(monkeypatch, capsys):
    health = HealthStatus(
        bridge_alive=True,
        terminal_connected=True,
        server_time=None,
        broker_name="HF Markets (SV) Ltd.",
        api_version="1",
        bridge_version="1",
        bridge_build="step4-2026-09-03",
    )
    monkeypatch.setattr(mt5_remote_cli, "_build_client", lambda: _FakeStatusClient(health))

    mt5_remote_cli.cmd_status(argparse.Namespace())

    out = capsys.readouterr().out
    assert "api_version:         1" in out
    assert "bridge_version:      1" in out
    assert "bridge_build:        step4-2026-09-03" in out


def test_cmd_status_missing_bridge_build_prints_none_not_fabricated(monkeypatch, capsys):
    """If the bridge does not send bridge_build, the CLI must show that
    honestly (None) -- never invent a build id on the Linux side."""

    health = HealthStatus(
        bridge_alive=True,
        terminal_connected=True,
        server_time=None,
        broker_name="HF Markets (SV) Ltd.",
        api_version="1",
        bridge_version=None,
        bridge_build=None,
    )
    monkeypatch.setattr(mt5_remote_cli, "_build_client", lambda: _FakeStatusClient(health))

    mt5_remote_cli.cmd_status(argparse.Namespace())

    out = capsys.readouterr().out
    assert "bridge_build:        None" in out
    assert "bridge_version:      None" in out
    assert "step4-2026-09-03" not in out


# --------------------------------------------------------------------------
# preflight/safe_open temporal-consistency (FX Phase 0, "preflight said OK,
# demo-open immediately failed on a timestamp check" incident)
# --------------------------------------------------------------------------


class _FakePreflightClient:
    """Everything preflight and SafeExecutionService need, with a
    controllable quote timestamp so we can force the exact scenario that
    caused the incident: a quote whose timestamp fails freshness
    validation."""

    def __init__(self, quote_timestamp: datetime) -> None:
        self._quote_timestamp = quote_timestamp

    def health(self):
        return HealthStatus(bridge_alive=True, terminal_connected=True, server_time=None)

    def terminal(self) -> TerminalStatus:
        return TerminalStatus(connected=True, trade_allowed=True, dlls_allowed=False, name="MetaTrader 5", company="Fake Broker", build=1)

    def account(self) -> AccountSummary:
        return AccountSummary(account_id="1", trade_mode=AccountTradeMode.DEMO, balance=Decimal("100"), equity=Decimal("100"), currency="USD", trade_allowed=True, trade_expert=True)

    def kill_switch_status(self) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.INACTIVE, changed_at=None)

    def reconciliation_status(self) -> ReconciliationReport:
        return ReconciliationReport(state=ReconciliationState.OK, checked_at=datetime.now(timezone.utc))

    def positions(self):
        return ()

    def symbol_metadata(self, symbol: str) -> SymbolMetadata:
        return SymbolMetadata(
            symbol=symbol, volume_min=Decimal("0.01"), volume_step=Decimal("0.01"), volume_max=Decimal("60"),
            contract_size=Decimal("100000"), digits=5, point=Decimal("0.00001"),
        )

    def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=Decimal("1.0998"), ask=Decimal("1.1"), timestamp=self._quote_timestamp)


def _frozen_policy() -> RealMoneyPolicy:
    return RealMoneyPolicy(
        live_trading_enabled=False, max_initial_capital_usd=Decimal("10"), max_additional_funding_usd=Decimal("0"),
        max_simultaneous_positions=1, minimum_volume_only=True, martingale_forbidden=True,
        averaging_down_forbidden=True, recovery_grid_forbidden=True, automatic_size_increase_forbidden=True,
        compounding_forbidden=True,
    )


def test_preflight_fails_when_quote_is_future_same_as_safe_open_would(monkeypatch, capsys):
    """10. Reproduces the exact incident: a quote timestamp that fails
    the shared freshness check must make BOTH preflight and safe_open
    disagree with "OK" -- they must never diverge again."""

    future_ts = datetime.now(timezone.utc) + timedelta(seconds=5)
    client = _FakePreflightClient(quote_timestamp=future_ts)
    monkeypatch.setattr(mt5_remote_cli, "_build_client", lambda: client)

    with pytest.raises(SystemExit):
        mt5_remote_cli.cmd_preflight(argparse.Namespace(symbol="EURUSD"))
    out = capsys.readouterr().out
    assert "PREFLIGHT FAILED" in out
    assert "future" in out

    # Same quote, same helper, through SafeExecutionService.safe_open --
    # must also deny, for the same reason.
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionQuoteFreshnessError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))


def test_preflight_passes_when_quote_is_fresh(monkeypatch, capsys):
    client = _FakePreflightClient(quote_timestamp=datetime.now(timezone.utc))
    monkeypatch.setattr(mt5_remote_cli, "_build_client", lambda: client)

    mt5_remote_cli.cmd_preflight(argparse.Namespace(symbol="EURUSD"))
    out = capsys.readouterr().out
    assert "PREFLIGHT OK" in out


def test_preflight_fails_before_write_when_autotrading_disabled(monkeypatch, capsys):
    client = _FakePreflightClient(quote_timestamp=datetime.now(timezone.utc))
    client.terminal = lambda: TerminalStatus(connected=True, trade_allowed=False, dlls_allowed=False, name="MetaTrader 5", company="Fake Broker", build=1)
    monkeypatch.setattr(mt5_remote_cli, "_build_client", lambda: client)

    with pytest.raises(SystemExit):
        mt5_remote_cli.cmd_preflight(argparse.Namespace(symbol="EURUSD"))
    out = capsys.readouterr().out
    assert "PREFLIGHT FAILED" in out
    assert "AutoTrading is disabled" in out
