"""Linux-side orchestrator combining a remote client with Step 1's
fail-closed policy (FX Phase 0, Step 4).

`SafeExecutionService.safe_open`/`safe_close` are the only entry points a
caller (a manual script, a future CLI command, eventually a strategy)
should use to place or close a demo order. They exist specifically so no
caller has to remember, on every call site, to fetch account/quote/
positions/kill-switch/reconciliation state and build a `PolicyContext`
before calling `authorize_open`/`authorize_close` -- get that assembly
wrong once and a write could bypass the Linux-side check (the bridge's
own server-side checks in `mt5_bridge/trading.py` are what actually
prevent a bad write; this class is the client-side half of defense in
depth, not the only line of defense).

This module does not add new policy logic -- it reuses
`src.execution.policy.authorize_open`/`authorize_close` byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.execution.base import (
    ActionKind,
    CloseRequest,
    CloseResult,
    Environment,
    ExecutionResult,
    OrderRequest,
    OrderType,
    ReconciliationState,
    Side,
)
from src.execution.mt5_remote import MT5RemoteExecutionClient
from src.execution.policy import PolicyContext, PolicyDecision, RealMoneyPolicy, authorize_close, authorize_open
from src.execution.quote_freshness import (
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
    QuoteFreshnessError,
    validate_quote_freshness,
)


class SafeExecutionDeniedError(Exception):
    """Raised by `safe_open`/`safe_close` when policy denies the action.
    Carries the full `PolicyDecision` so a caller can see every reason,
    not just the first one.
    """

    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        super().__init__("; ".join(decision.reasons) or "denied")


class SafeExecutionQuoteFreshnessError(Exception):
    """Raised by `SafeExecutionService` when the quote it just fetched
    fails the shared freshness/future-skew check -- see
    `_check_quote_freshness`. Distinct from `SafeExecutionDeniedError`
    (a `PolicyDecision` denial) because this is a data-quality/clock
    problem, not a policy decision.
    """


@dataclass(frozen=True)
class SafeExecutionService:
    client: MT5RemoteExecutionClient
    policy: RealMoneyPolicy
    local_environment: Environment = Environment.DEMO

    def _build_open_context(self, symbol: str) -> PolicyContext:
        account = self.client.account()
        symbol_metadata = self.client.symbol_metadata(symbol)
        positions = self.client.positions()
        kill_switch = self.client.kill_switch_status()
        reconciliation = self.client.reconciliation_status()

        remote_environment = Environment.DEMO if account.trade_mode.value == "demo" else (
            Environment.LIVE if account.trade_mode.value == "live" else Environment.UNKNOWN
        )

        return PolicyContext(
            local_environment=self.local_environment,
            remote_environment=remote_environment,
            account_trade_mode=account.trade_mode,
            reconciliation_state=reconciliation.state,
            kill_switch_active=(kill_switch.status.value == "active"),
            current_position_count=len(positions),
            symbol_metadata=symbol_metadata,
            account_known=True,
        )

    def _check_quote_freshness(self, symbol: str) -> None:
        """Early, client-side-only sanity check: fetch a fresh quote and
        validate it before even calling the bridge's write endpoint. This
        is a courtesy fail-fast, NOT a security boundary -- a wrong Linux
        clock can only make this reject something the bridge would have
        allowed, never let something through the bridge would have
        refused, because `mt5_bridge/trading.py` independently re-validates
        the tick's freshness against its own clock before `order_send`
        regardless of what happens here (see FX Phase 0's "quote has a
        timestamp in the future" investigation and
        `src.execution.quote_freshness`).
        """

        quote = self.client.quote(symbol)
        try:
            validate_quote_freshness(
                symbol=symbol,
                quote_timestamp=quote.timestamp,
                max_age_seconds=DEFAULT_MAX_QUOTE_AGE_SECONDS,
                max_future_skew_seconds=DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
            )
        except QuoteFreshnessError as exc:
            raise SafeExecutionQuoteFreshnessError(str(exc)) from exc

    def safe_open(self, client_order_id: str, symbol: str, side: Side, volume: Decimal) -> ExecutionResult:
        """Fetches account/symbol/positions/kill-switch/reconciliation,
        builds a `PolicyContext`, and calls `authorize_open`. Only if
        `decision.allowed` does this proceed to `client.place_order` --
        no write leaves this process otherwise. This does NOT replace
        the bridge's own server-side checks (see module docstring).
        """

        self._check_quote_freshness(symbol)
        context = self._build_open_context(symbol)
        request = OrderRequest(
            client_order_id=client_order_id, symbol=symbol, side=side, order_type=OrderType.MARKET,
            volume=volume, action_kind=ActionKind.OPEN,
        )
        decision = authorize_open(context, request, self.policy)
        if not decision.allowed:
            raise SafeExecutionDeniedError(decision)
        return self.client.place_order(request)

    def safe_close(self, client_order_id: str, position_id: str, symbol: str, side: Side, volume: Decimal) -> CloseResult:
        """Equivalent to `safe_open` but for closing -- uses
        `authorize_close`, which (per Step 1's design) is not blocked by
        an active kill switch.
        """

        context = self._build_open_context(symbol)
        request = OrderRequest(
            client_order_id=client_order_id, symbol=symbol, side=side, order_type=OrderType.MARKET,
            volume=volume, action_kind=ActionKind.CLOSE, position_id=position_id,
        )
        decision = authorize_close(context, request, self.policy)
        if not decision.allowed:
            raise SafeExecutionDeniedError(decision)
        return self.client.close_position(CloseRequest(client_order_id=client_order_id, position_id=position_id))
