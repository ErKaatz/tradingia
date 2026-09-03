"""Tests for the Linux-side SafeExecutionService orchestrator (FX Phase 0, Step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.execution.base import (
    AccountSummary,
    AccountTradeMode,
    CloseResult,
    ExecutionResult,
    KillSwitchState,
    KillSwitchStatus,
    OrderStatus,
    Position,
    Quote,
    ReconciliationReport,
    ReconciliationState,
    Side,
    SymbolMetadata,
)
from src.execution.policy import RealMoneyPolicy
from src.execution.safe_execution import SafeExecutionDeniedError, SafeExecutionQuoteFreshnessError, SafeExecutionService


def _frozen_policy(**overrides) -> RealMoneyPolicy:
    defaults = dict(
        live_trading_enabled=False,
        max_initial_capital_usd=Decimal("10"),
        max_additional_funding_usd=Decimal("0"),
        max_simultaneous_positions=1,
        minimum_volume_only=True,
        martingale_forbidden=True,
        averaging_down_forbidden=True,
        recovery_grid_forbidden=True,
        automatic_size_increase_forbidden=True,
        compounding_forbidden=True,
    )
    defaults.update(overrides)
    return RealMoneyPolicy(**defaults)


def _symbol_metadata() -> SymbolMetadata:
    return SymbolMetadata(
        symbol="EURUSD", volume_min=Decimal("0.01"), volume_step=Decimal("0.01"), volume_max=Decimal("60"),
        contract_size=Decimal("100000"), digits=5, point=Decimal("0.00001"),
    )


@dataclass
class _FakeRemoteClient:
    trade_mode: AccountTradeMode = AccountTradeMode.DEMO
    kill_switch_active: bool = False
    reconciliation_state: ReconciliationState = ReconciliationState.OK
    positions_list: tuple = ()
    place_order_calls: list = None
    close_position_calls: list = None
    quote_timestamp: datetime | None = None

    def __post_init__(self):
        self.place_order_calls = []
        self.close_position_calls = []

    def account(self) -> AccountSummary:
        return AccountSummary(account_id="1", trade_mode=self.trade_mode, balance=Decimal("1000"), equity=Decimal("1000"), currency="USD")

    def symbol_metadata(self, symbol: str) -> SymbolMetadata:
        return _symbol_metadata()

    def quote(self, symbol: str) -> Quote:
        timestamp = self.quote_timestamp if self.quote_timestamp is not None else datetime.now(timezone.utc)
        return Quote(symbol=symbol, bid=Decimal("1.0998"), ask=Decimal("1.1"), timestamp=timestamp)

    def positions(self):
        return self.positions_list

    def kill_switch_status(self) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.ACTIVE if self.kill_switch_active else KillSwitchStatus.INACTIVE, changed_at=None)

    def reconciliation_status(self) -> ReconciliationReport:
        return ReconciliationReport(state=self.reconciliation_state, checked_at=datetime.now(timezone.utc))

    def place_order(self, request):
        self.place_order_calls.append(request)
        return ExecutionResult(
            client_order_id=request.client_order_id, status=OrderStatus.FILLED, broker_order_id="1", deal_id="1",
            position_id="1", fill_price=Decimal("1.1"), filled_volume=request.volume, requested_volume=request.volume,
            observed_bid=Decimal("1.0998"), observed_ask=Decimal("1.1"), reference_price=Decimal("1.1"),
            slippage=Decimal("0"), mt5_retcode=10009, timestamp=datetime.now(timezone.utc),
        )

    def close_position(self, request):
        self.close_position_calls.append(request)
        return CloseResult(
            client_order_id=request.client_order_id, position_id=request.position_id, status=OrderStatus.FILLED,
            closed_volume=Decimal("0.01"), observed_bid=Decimal("1.0998"), observed_ask=Decimal("1.1"),
            reference_price=Decimal("1.0998"), fill_price=Decimal("1.0998"), slippage=Decimal("0"), deal_id="2",
            mt5_retcode=10009, timestamp=datetime.now(timezone.utc),
        )


def test_safe_open_allows_and_calls_place_order():
    client = _FakeRemoteClient()
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    result = service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert result.status == OrderStatus.FILLED
    assert len(client.place_order_calls) == 1


# 30. Phase0 config with live=true prevents startup/write.
def test_safe_open_denied_when_policy_live_trading_enabled_never_calls_client():
    client = _FakeRemoteClient()
    policy = _frozen_policy(live_trading_enabled=True)
    service = SafeExecutionService(client=client, policy=policy)
    with pytest.raises(SafeExecutionDeniedError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_safe_open_denied_when_kill_switch_active_never_calls_client():
    client = _FakeRemoteClient(kill_switch_active=True)
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionDeniedError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_safe_open_denied_when_account_not_demo_never_calls_client():
    client = _FakeRemoteClient(trade_mode=AccountTradeMode.LIVE)
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionDeniedError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_safe_open_denied_when_position_already_open():
    client = _FakeRemoteClient(positions_list=(
        Position(position_id="1", symbol="EURUSD", side=Side.BUY, volume=Decimal("0.01"), open_price=Decimal("1.1")),
    ))
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionDeniedError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_safe_close_allowed_even_with_kill_switch_active():
    client = _FakeRemoteClient(kill_switch_active=True)
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    result = service.safe_close("close-1", "1", "EURUSD", Side.SELL, Decimal("0.01"))
    assert result.status == OrderStatus.FILLED
    assert len(client.close_position_calls) == 1


def test_safe_close_denied_when_account_not_demo():
    client = _FakeRemoteClient(trade_mode=AccountTradeMode.LIVE)
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionDeniedError):
        service.safe_close("close-1", "1", "EURUSD", Side.SELL, Decimal("0.01"))
    assert client.close_position_calls == []


def test_safe_open_denied_when_quote_is_stale():
    from datetime import timedelta

    client = _FakeRemoteClient(quote_timestamp=datetime.now(timezone.utc) - timedelta(seconds=30))
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionQuoteFreshnessError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_safe_open_denied_when_quote_is_in_the_future():
    from datetime import timedelta

    client = _FakeRemoteClient(quote_timestamp=datetime.now(timezone.utc) + timedelta(seconds=10))
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionQuoteFreshnessError):
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert client.place_order_calls == []


def test_denied_error_carries_all_reasons():
    client = _FakeRemoteClient(kill_switch_active=True, trade_mode=AccountTradeMode.UNKNOWN)
    service = SafeExecutionService(client=client, policy=_frozen_policy())
    with pytest.raises(SafeExecutionDeniedError) as excinfo:
        service.safe_open("c1", "EURUSD", Side.BUY, Decimal("0.01"))
    assert len(excinfo.value.decision.reasons) >= 2
