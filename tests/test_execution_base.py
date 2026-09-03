"""Tests for the broker-agnostic execution domain types (FX Phase 0, Step 1)."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal

from src.execution.base import (
    AccountSummary,
    AccountTradeMode,
    ActionKind,
    CloseRequest,
    CloseResult,
    Environment,
    ExecutionTimeframe,
    ExecutionClient,
    ExecutionResult,
    HealthStatus,
    HistoryBar,
    HistoryRequest,
    HistoryResult,
    KillSwitchState,
    KillSwitchStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    ReconciliationReport,
    ReconciliationState,
    Side,
    SymbolMetadata,
    SymbolSummary,
    TimeDiagnostics,
)


def _symbol_metadata(**overrides) -> SymbolMetadata:
    defaults = dict(
        symbol="EURUSD",
        volume_min=Decimal("0.01"),
        volume_step=Decimal("0.01"),
        volume_max=Decimal("100"),
        contract_size=Decimal("100000"),
        digits=5,
        point=Decimal("0.00001"),
    )
    defaults.update(overrides)
    return SymbolMetadata(**defaults)


def test_environment_has_explicit_unknown_member():
    assert Environment.UNKNOWN is not Environment.DEMO
    assert Environment.UNKNOWN is not Environment.LIVE


def test_account_trade_mode_has_explicit_unknown_member():
    assert AccountTradeMode.UNKNOWN is not AccountTradeMode.DEMO
    assert AccountTradeMode.UNKNOWN is not AccountTradeMode.LIVE


def test_reconciliation_state_has_explicit_unknown_member():
    assert ReconciliationState.UNKNOWN is not ReconciliationState.OK


def test_symbol_metadata_fields_use_decimal_not_float():
    meta = _symbol_metadata()
    for f in fields(meta):
        value = getattr(meta, f.name)
        if f.name in {"volume_min", "volume_step", "volume_max", "contract_size", "point"}:
            assert isinstance(value, Decimal), f"{f.name} should be Decimal, got {type(value)}"


def test_quote_fields_use_decimal():
    q = Quote(symbol="EURUSD", bid=Decimal("1.10001"), ask=Decimal("1.10003"), timestamp=datetime.now(timezone.utc))
    assert isinstance(q.bid, Decimal)
    assert isinstance(q.ask, Decimal)


def test_order_request_requires_client_order_id():
    req = OrderRequest(
        client_order_id="abc-123",
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume=Decimal("0.01"),
        action_kind=ActionKind.OPEN,
    )
    assert req.client_order_id == "abc-123"


def test_order_request_is_frozen_immutable():
    req = OrderRequest(
        client_order_id="abc-123",
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume=Decimal("0.01"),
        action_kind=ActionKind.OPEN,
    )
    try:
        req.volume = Decimal("0.02")  # type: ignore[misc]
        assert False, "OrderRequest should be immutable"
    except Exception:
        pass


def test_execution_result_carries_no_secret_fields():
    result = ExecutionResult(
        client_order_id="abc-123",
        status=OrderStatus.FILLED,
        broker_order_id="B-1",
        deal_id="D-1",
        position_id="P-1",
        fill_price=Decimal("1.10002"),
        filled_volume=Decimal("0.01"),
        requested_volume=Decimal("0.01"),
        observed_bid=Decimal("1.09998"),
        observed_ask=Decimal("1.10002"),
        reference_price=Decimal("1.10002"),
        slippage=Decimal("0"),
        mt5_retcode=10009,
        timestamp=datetime.now(timezone.utc),
    )
    field_names = {f.name for f in fields(result)}
    forbidden_substrings = ("password", "secret", "token", "api_key", "credential")
    for name in field_names:
        lowered = name.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in lowered, f"ExecutionResult field {name!r} looks like a credential"


def test_no_domain_type_introduces_credential_concepts():
    """Sweep every dataclass defined in base.py for field names that look
    like secrets/credentials -- these types should never need to carry
    authentication material, that is strictly a transport concern.
    """
    import src.execution.base as base_module

    forbidden_substrings = ("password", "secret", "token", "api_key", "credential")
    for name in dir(base_module):
        obj = getattr(base_module, name)
        if isinstance(obj, type) and hasattr(obj, "__dataclass_fields__"):
            for field_name in obj.__dataclass_fields__:
                lowered = field_name.lower()
                for forbidden in forbidden_substrings:
                    assert forbidden not in lowered, f"{obj.__name__}.{field_name} looks like a credential"


def test_history_result_defaults_to_empty_tuple():
    result = HistoryResult(symbol="EURUSD")
    assert result.bars == ()


def test_history_request_and_bar_roundtrip_shapes():
    req = HistoryRequest(
        symbol="EURUSD",
        timeframe=ExecutionTimeframe.M15,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    bar = HistoryBar(
        symbol="EURUSD",
        timestamp=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        open=Decimal("1.1"),
        high=Decimal("1.2"),
        low=Decimal("1.0"),
        close=Decimal("1.15"),
        volume=Decimal("100"),
    )
    result = HistoryResult(symbol="EURUSD", bars=(bar,))
    assert result.symbol == req.symbol
    assert len(result.bars) == 1


def test_health_status_broker_name_optional():
    status = HealthStatus(bridge_alive=True, terminal_connected=False, server_time=None)
    assert status.broker_name is None


class _FakeExecutionClient:
    """Minimal structural implementation used to verify the Protocol is
    satisfiable without inheritance, and does not require MetaTrader5.
    """

    def health(self) -> HealthStatus:
        return HealthStatus(bridge_alive=True, terminal_connected=True, server_time=None)

    def account(self) -> AccountSummary:
        return AccountSummary(
            account_id="1",
            trade_mode=AccountTradeMode.DEMO,
            balance=Decimal("1000"),
            equity=Decimal("1000"),
            currency="USD",
        )

    def symbols(self) -> tuple[SymbolSummary, ...]:
        return ()

    def symbol_metadata(self, symbol: str) -> SymbolMetadata:
        return _symbol_metadata(symbol=symbol)

    def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, bid=Decimal("1.1"), ask=Decimal("1.1002"), timestamp=datetime.now(timezone.utc))

    def positions(self) -> tuple[Position, ...]:
        return ()

    def orders(self) -> tuple:
        return ()

    def history(self, request: HistoryRequest) -> HistoryResult:
        return HistoryResult(symbol=request.symbol)

    def place_order(self, request: OrderRequest) -> ExecutionResult:
        return ExecutionResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.FILLED,
            broker_order_id="B-1",
            deal_id="D-1",
            position_id="P-1",
            fill_price=Decimal("1.1"),
            filled_volume=request.volume,
            requested_volume=request.volume,
            observed_bid=Decimal("1.0998"),
            observed_ask=Decimal("1.1"),
            reference_price=Decimal("1.1"),
            slippage=Decimal("0"),
            mt5_retcode=10009,
            timestamp=datetime.now(timezone.utc),
        )

    def close_position(self, request: CloseRequest) -> CloseResult:
        return CloseResult(
            client_order_id=request.client_order_id,
            position_id=request.position_id,
            status=OrderStatus.FILLED,
            closed_volume=Decimal("0.01"),
            observed_bid=Decimal("1.0998"),
            observed_ask=Decimal("1.1"),
            reference_price=Decimal("1.0998"),
            fill_price=Decimal("1.0998"),
            slippage=Decimal("0"),
            deal_id="D-2",
            mt5_retcode=10009,
            timestamp=datetime.now(timezone.utc),
        )

    def kill_switch_status(self) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.INACTIVE, changed_at=None)

    def activate_kill_switch(self, reason: str | None = None) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.ACTIVE, changed_at=datetime.now(timezone.utc), reason=reason)

    def deactivate_kill_switch(self) -> KillSwitchState:
        return KillSwitchState(status=KillSwitchStatus.INACTIVE, changed_at=datetime.now(timezone.utc))

    def reconciliation_status(self) -> ReconciliationReport:
        return ReconciliationReport(state=ReconciliationState.OK, checked_at=datetime.now(timezone.utc))

    def run_reconciliation(self) -> ReconciliationReport:
        return ReconciliationReport(state=ReconciliationState.OK, checked_at=datetime.now(timezone.utc))

    def time_diagnostics(self, symbol: str) -> TimeDiagnostics:
        now = datetime.now(timezone.utc)
        return TimeDiagnostics(
            symbol=symbol,
            linux_client_utc=now,
            bridge_time_utc=now,
            mt5_tick_time_utc=now,
            bridge_client_skew_seconds=0.0,
            tick_client_skew_seconds=0.0,
            tick_bridge_skew_seconds=0.0,
            quote_age_seconds_per_client=0.0,
            quote_age_seconds_per_bridge=0.0,
        )


def test_fake_client_satisfies_execution_client_protocol():
    client: ExecutionClient = _FakeExecutionClient()
    assert isinstance(client, ExecutionClient)
