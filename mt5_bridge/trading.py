"""Server-side write orchestration: DEMO market orders only (FX Phase 0, Step 4).

This module is the ONLY place in `mt5_bridge` that calls
`MT5Backend.order_check`/`order_send`. Every write request funnels
through `place_demo_order` or `close_demo_position`, both of which:

1. Re-verify DEMO server-side (fresh `account_info()` -- never a cached
   value) before doing anything else. `trade_mode != DEMO` is a hard
   reject here regardless of what Linux/policy already decided --
   defense in depth, not a duplicate of Step 1's policy.
2. Go through idempotency (`mt5_bridge/store.py`) BEFORE touching MT5.
3. Check a fresh quote's age against `max_quote_age_seconds`.
4. Call `order_check` before `order_send` -- a failed check means
   `order_send` is never called.
5. Journal every step (sanitized).
6. On success, mark the idempotency record FILLED with the full result
   payload so a retry can be served from storage without ever touching
   MT5 again.
7. On an exception between submitting to MT5 and recording the result
   (the crash window), the idempotency record is left in SUBMITTED --
   never silently marked REJECTED or retried blindly. Startup/on-demand
   reconciliation (`mt5_bridge/reconciliation.py`) is what surfaces this.

MARKET orders only (`TRADE_ACTION_DEAL`); no pending/stop/limit orders,
no partial closes -- Step 4's explicit scope limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from mt5_bridge.backend import (
    ORDER_TYPE_BUY,
    ORDER_TYPE_SELL,
    TRADE_RETCODE_DONE,
    MT5Backend,
    MT5BackendError,
    TradeRequest,
)
from mt5_bridge.identity import build_mt5_comment
from mt5_bridge.quote_freshness import QuoteFreshnessError, validate_quote_freshness
from mt5_bridge.sanitize import sanitize_message
from mt5_bridge.store import (
    BridgeStore,
    IdempotencyConflictError,
    IdempotencyStateError,
    OrderState,
    compute_request_fingerprint,
)


class TradingError(Exception):
    """Base class for all write-path errors raised by this module. Every
    subclass carries a `code` the HTTP layer maps to a specific status.
    """

    code = "trading_error"


class NotDemoError(TradingError):
    code = "not_demo"


class TradingPermissionError(TradingError):
    """MT5/account permissions do not currently allow automated trading.

    Kept separate from order_check/order_send failures so preflight and the
    bridge can fail before an order ever reaches MT5.
    """

    code = "autotrading_disabled"


class KillSwitchActiveError(TradingError):
    code = "kill_switch_active"


class ReconciliationRequiredError(TradingError):
    code = "reconciliation_required"


class SymbolNotTradableError(TradingError):
    code = "symbol_not_tradable"


class StaleQuoteError(TradingError):
    code = "stale_quote"


class OrderCheckFailedError(TradingError):
    code = "order_check_failed"


class OrderSendFailedError(TradingError):
    code = "order_send_failed"


class PositionNotFoundError(TradingError):
    code = "position_not_found"


class TooManyPositionsError(TradingError):
    code = "too_many_positions"


class InvalidVolumeError(TradingError):
    code = "invalid_volume"


@dataclass(frozen=True)
class DemoOrderRequest:
    client_order_id: str
    symbol: str
    side: str  # "buy" | "sell"
    volume: Decimal


@dataclass(frozen=True)
class DemoOrderResult:
    client_order_id: str
    status: str  # matches OrderStatus.value
    broker_order_id: str | None
    deal_id: str | None
    position_id: str | None
    requested_volume: Decimal
    filled_volume: Decimal | None
    observed_bid: Decimal
    observed_ask: Decimal
    reference_price: Decimal
    fill_price: Decimal | None
    slippage: Decimal | None
    mt5_retcode: int | None
    timestamp: datetime
    idempotent_replay: bool
    error_message: str | None = None


@dataclass(frozen=True)
class DemoCloseRequest:
    client_order_id: str
    position_id: str


@dataclass(frozen=True)
class DemoCloseResult:
    client_order_id: str
    position_id: str
    status: str
    closed_volume: Decimal | None
    observed_bid: Decimal
    observed_ask: Decimal
    reference_price: Decimal
    fill_price: Decimal | None
    slippage: Decimal | None
    deal_id: str | None
    mt5_retcode: int | None
    timestamp: datetime
    idempotent_replay: bool
    error_message: str | None = None


def _require_fresh_demo_account(backend: MT5Backend) -> None:
    """Re-reads account_info() right now -- never a cached/earlier value
    -- and rejects unless it is unambiguously DEMO. This is deliberately
    duplicated logic relative to Step 1's `authorize_open` (which also
    checks account trade mode) -- that check runs on the Linux side
    against data that could be stale by the time the HTTP request
    arrives; this one runs immediately before order_check/order_send on
    the actual server.
    """

    from mt5_bridge.backend import SYMBOL_TRADE_MODE_FULL  # noqa: F401 (documents intent; not used directly here)

    try:
        account = backend.account_info()
    except MT5BackendError as exc:
        raise NotDemoError(f"could not verify account is DEMO: {exc}") from exc
    if account.trade_mode_code != 0:  # MT5_TRADE_MODE_BY_CODE: 0 == demo
        raise NotDemoError("account trade_mode is not DEMO; refusing to write")
    if not backend.is_connected():
        raise NotDemoError("terminal is not connected; refusing to write")


def _require_trading_permissions(backend: MT5Backend) -> None:
    """Re-read terminal/account permission flags immediately before a write.

    MT5 retcode 10027 ("AutoTrading disabled by client") is avoidable: the
    terminal exposes `terminal_info().trade_allowed`, while the account
    exposes `trade_allowed` and `trade_expert`.  For new automated writes we
    require all three to be explicitly True. Missing/unknown flags fail
    closed rather than being treated as permission.
    """

    try:
        terminal = backend.terminal_info()
        account = backend.account_info()
    except MT5BackendError as exc:
        raise TradingPermissionError(f"could not verify MT5 trading permissions: {exc}") from exc

    if terminal.connected is not True:
        raise TradingPermissionError("MT5 terminal is not connected")
    if terminal.trade_allowed is not True:
        raise TradingPermissionError(
            "MT5 AutoTrading is disabled in the client terminal; enable Algo Trading manually in MT5"
        )
    if account.trade_allowed is not True:
        state = "unknown" if account.trade_allowed is None else "disabled"
        raise TradingPermissionError(f"MT5 account trading permission is {state}; refusing automated write")
    if account.trade_expert is not True:
        state = "unknown" if account.trade_expert is None else "disabled"
        raise TradingPermissionError(f"MT5 expert/algorithmic trading permission is {state}; refusing automated write")


def _require_symbol_tradable(backend: MT5Backend, symbol: str):
    info = backend.symbol_info(symbol)
    if info is None:
        raise SymbolNotTradableError(f"symbol {symbol!r} not found")
    if not info.visible:
        raise SymbolNotTradableError(f"symbol {symbol!r} is not visible/selected in the terminal")
    if info.trade_enabled is not True:
        raise SymbolNotTradableError(
            f"symbol {symbol!r} does not report full trading enabled (trade_enabled={info.trade_enabled})"
        )
    return info


def _require_fresh_quote(backend: MT5Backend, symbol: str, max_age_seconds: float, max_future_skew_seconds: float):
    tick = backend.symbol_info_tick(symbol)
    if tick is None:
        raise StaleQuoteError(f"no tick available for {symbol!r}")
    try:
        validate_quote_freshness(
            symbol=symbol,
            quote_timestamp=tick.time_utc,
            max_age_seconds=max_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
        )
    except QuoteFreshnessError as exc:
        raise StaleQuoteError(str(exc)) from exc
    return tick


def place_demo_order(
    backend: MT5Backend,
    store: BridgeStore,
    request: DemoOrderRequest,
    *,
    max_positions: int,
    max_quote_age_seconds: float,
    max_quote_future_skew_seconds: float,
    deviation_points: int,
    magic: int,
    request_id: str | None,
) -> DemoOrderResult:
    _require_fresh_demo_account(backend)

    # Idempotency is checked BEFORE any business-state check (kill
    # switch, reconciliation, position count, ...): a retry of an
    # already-filled order must replay the stored result even if, e.g.,
    # the position count check would now fail simply because that
    # earlier fill is itself the open position. Only a genuinely NEW
    # client_order_id proceeds to the business checks below.
    request_hash = compute_request_fingerprint(
        symbol=request.symbol, side=request.side, volume=str(request.volume), action="open"
    )
    _journal(store, request_id, request.client_order_id, "place_order.begin", {"symbol": request.symbol, "side": request.side, "volume": str(request.volume)})

    try:
        record = store.begin_idempotent_request(request.client_order_id, request_hash)
    except IdempotencyConflictError as exc:
        _journal(store, request_id, request.client_order_id, "place_order.conflict", {"error": sanitize_message(str(exc))})
        raise

    if record.state.value in ("filled", "rejected") and record.result_payload is not None:
        _journal(store, request_id, request.client_order_id, "place_order.idempotent_replay", {"state": record.state.value})
        payload = dict(record.result_payload)
        payload["idempotent_replay"] = True
        return DemoOrderResult(**_decimalize_order_payload(payload))

    if record.state is OrderState.REJECTED:
        # Terminal rejected rows (including a manually resolved
        # RECEIVED attempt) are never reusable. Some historic rejection
        # paths intentionally have no replay payload; absence of a
        # payload must not turn a terminal ID back into a fresh order.
        raise ReconciliationRequiredError(
            f"client_order_id {request.client_order_id!r} is terminal state=rejected; use a new client_order_id"
        )

    if record.state.value in ("received", "submitted") and record.updated_at != record.created_at:
        # Not a fresh RECEIVED row from this call -- it's a pre-existing
        # non-terminal row from an earlier, unresolved attempt. Refuse to
        # resubmit blindly; this needs reconciliation, not a retry.
        raise ReconciliationRequiredError(
            f"client_order_id {request.client_order_id!r} is stuck in state={record.state.value}; run reconciliation"
        )

    # Every definite failure before the SUBMITTED boundary terminalizes the
    # fresh RECEIVED row. That prevents known-safe pre-submit rejections
    # (kill switch, stale quote, permission denial, etc.) from poisoning
    # reconciliation as ambiguous attempts.
    try:
        _require_trading_permissions(backend)

        if store.get_kill_switch()[0] == "active":
            raise KillSwitchActiveError("kill switch is active; new entries are blocked")

        from mt5_bridge.reconciliation import get_reconciliation_status

        reconciliation = get_reconciliation_status(store)
        if reconciliation.state.value != "ok":
            raise ReconciliationRequiredError(
                f"reconciliation state is {reconciliation.state.value}, not OK"
            )

        positions = backend.positions_get()
        if len(positions) >= max_positions:
            raise TooManyPositionsError(
                f"{len(positions)} position(s) already open; max is {max_positions}"
            )

        symbol_info = _require_symbol_tradable(backend, request.symbol)
        if request.volume != symbol_info.volume_min:
            raise InvalidVolumeError(
                f"requested volume {request.volume} != symbol minimum {symbol_info.volume_min} "
                "(minimum-only sizing policy)"
            )

        tick = _require_fresh_quote(
            backend,
            request.symbol,
            max_quote_age_seconds,
            max_quote_future_skew_seconds,
        )
        reference_price = tick.ask if request.side == "buy" else tick.bid
        mt5_order_type = ORDER_TYPE_BUY if request.side == "buy" else ORDER_TYPE_SELL
        comment = build_mt5_comment(request.client_order_id)

        trade_request = TradeRequest(
            symbol=request.symbol,
            volume=request.volume,
            order_type=mt5_order_type,
            price=reference_price,
            deviation=deviation_points,
            magic=magic,
            comment=comment,
        )

        check = backend.order_check(trade_request)
        _journal(
            store,
            request_id,
            request.client_order_id,
            "place_order.order_check",
            {
                "symbol": request.symbol,
                "side": request.side,
                "requested_volume": str(request.volume),
                **_quote_audit_payload(tick, reference_price),
                "ok": check.ok,
                "retcode": check.retcode,
                "comment": sanitize_message(check.comment),
            },
        )
        if not check.ok:
            raise OrderCheckFailedError(
                f"order_check rejected: retcode={check.retcode} comment={sanitize_message(check.comment)}"
            )
    except TradingError as exc:
        _terminalize_pre_submission_reject(
            store,
            request_id,
            request.client_order_id,
            "place_order.pre_submit_rejected",
            exc,
        )
        raise

    try:
        store.transition_idempotency_state(
            request.client_order_id,
            expected_state=OrderState.RECEIVED,
            new_state=OrderState.SUBMITTED,
        )
    except IdempotencyStateError as exc:
        raise ReconciliationRequiredError(
            f"client_order_id state changed before submission; refusing order_send: {sanitize_message(str(exc))}"
        ) from exc
    _journal(
        store,
        request_id,
        request.client_order_id,
        "place_order.submitting",
        {
            "symbol": request.symbol,
            "side": request.side,
            "requested_volume": str(request.volume),
            **_quote_audit_payload(tick, reference_price),
        },
    )

    try:
        send_result = backend.order_send(trade_request)
    except MT5BackendError as exc:
        # Crash window: left in SUBMITTED deliberately. See module docstring.
        _journal(store, request_id, request.client_order_id, "place_order.crash_during_send", {"error": sanitize_message(str(exc))})
        raise OrderSendFailedError(f"order_send failed unexpectedly: {sanitize_message(str(exc))}") from exc

    now = datetime.now(timezone.utc)
    if send_result.retcode != TRADE_RETCODE_DONE:
        store.update_idempotency_state(request.client_order_id, OrderState.REJECTED, error_code=str(send_result.retcode))
        _journal(
            store,
            request_id,
            request.client_order_id,
            "place_order.rejected",
            {
                "symbol": request.symbol,
                "side": request.side,
                "requested_volume": str(request.volume),
                **_quote_audit_payload(tick, reference_price),
                "mt5_retcode": send_result.retcode,
                "comment": sanitize_message(send_result.comment),
            },
        )
        raise OrderSendFailedError(f"order_send did not fill: retcode={send_result.retcode} comment={sanitize_message(send_result.comment)}")

    filled_volume = send_result.volume if send_result.volume is not None else request.volume
    fill_price = send_result.price if send_result.price is not None else reference_price
    slippage = (fill_price - reference_price) if request.side == "buy" else (reference_price - fill_price)

    broker_order_id = str(send_result.order) if send_result.order is not None else None
    deal_id = str(send_result.deal) if send_result.deal is not None else None
    position_id = broker_order_id  # MT5 netting: the new position's ticket equals the filling order's ticket

    result_payload = {
        "client_order_id": request.client_order_id,
        "status": "filled",
        "broker_order_id": broker_order_id,
        "deal_id": deal_id,
        "position_id": position_id,
        "requested_volume": str(request.volume),
        "filled_volume": str(filled_volume),
        "observed_bid": str(tick.bid),
        "observed_ask": str(tick.ask),
        "reference_price": str(reference_price),
        "fill_price": str(fill_price),
        "slippage": str(slippage),
        "mt5_retcode": send_result.retcode,
        "timestamp": now.isoformat(),
        "error_message": None,
    }
    store.update_idempotency_state(
        request.client_order_id, OrderState.FILLED,
        broker_order_id=broker_order_id, deal_id=deal_id, position_id=position_id, result_payload=result_payload,
    )
    _journal(
        store,
        request_id,
        request.client_order_id,
        "place_order.filled",
        {
            "symbol": request.symbol,
            "side": request.side,
            "requested_volume": str(request.volume),
            "filled_volume": str(filled_volume),
            **_quote_audit_payload(tick, reference_price),
            "fill_price": str(fill_price),
            "slippage": str(slippage),
            "mt5_retcode": send_result.retcode,
            "broker_order_id": broker_order_id,
            "deal_id": deal_id,
            "position_id": position_id,
            "result_timestamp": now.isoformat(),
        },
    )

    return DemoOrderResult(**_decimalize_order_payload(dict(result_payload, idempotent_replay=False)))


def close_demo_position(
    backend: MT5Backend,
    store: BridgeStore,
    request: DemoCloseRequest,
    *,
    max_quote_age_seconds: float,
    max_quote_future_skew_seconds: float,
    deviation_points: int,
    magic: int,
    request_id: str | None,
) -> DemoCloseResult:
    """Full-close only, with idempotent replay before live position lookup.

    A retry of an already-filled close must replay even though the position no
    longer exists. Therefore idempotency is resolved before querying the live
    position. Kill switch never blocks closes, but DEMO/account identity is
    still re-verified server-side.
    """

    _require_fresh_demo_account(backend)

    request_hash = compute_request_fingerprint(position_id=request.position_id, action="close")
    _journal(
        store,
        request_id,
        request.client_order_id,
        "close_position.begin",
        {"position_id": request.position_id},
    )

    try:
        record = store.begin_idempotent_request(request.client_order_id, request_hash)
    except IdempotencyConflictError as exc:
        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.conflict",
            {"error": sanitize_message(str(exc))},
        )
        raise

    if record.state.value in ("filled", "rejected") and record.result_payload is not None:
        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.idempotent_replay",
            {"state": record.state.value},
        )
        payload = dict(record.result_payload)
        payload["idempotent_replay"] = True
        return DemoCloseResult(**_decimalize_close_payload(payload))

    if record.state is OrderState.REJECTED:
        raise ReconciliationRequiredError(
            f"client_order_id {request.client_order_id!r} is terminal state=rejected; use a new client_order_id"
        )

    if record.state.value in ("received", "submitted") and record.updated_at != record.created_at:
        raise ReconciliationRequiredError(
            f"client_order_id {request.client_order_id!r} is stuck in state={record.state.value}; run reconciliation"
        )

    try:
        _require_trading_permissions(backend)

        positions = backend.positions_get()
        matching = [p for p in positions if str(p.ticket) == request.position_id]
        if not matching:
            raise PositionNotFoundError(f"position {request.position_id!r} not found")
        position = matching[0]

        symbol_info = backend.symbol_info(position.symbol)
        if symbol_info is None:
            raise SymbolNotTradableError(f"symbol {position.symbol!r} metadata unavailable for close")

        tick = _require_fresh_quote(
            backend,
            position.symbol,
            max_quote_age_seconds,
            max_quote_future_skew_seconds,
        )
        # Opposite side closes the position: a long closes by selling at bid;
        # a short closes by buying at ask.
        closing_side_is_sell = position.side == "buy"
        reference_price = tick.bid if closing_side_is_sell else tick.ask
        mt5_order_type = ORDER_TYPE_SELL if closing_side_is_sell else ORDER_TYPE_BUY
        comment = build_mt5_comment(request.client_order_id)

        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.context",
            {
                "position_id": request.position_id,
                "symbol": position.symbol,
                "position_side": position.side,
                "closing_side": "sell" if closing_side_is_sell else "buy",
                "closed_volume": str(position.volume),
                "open_price": str(position.price_open),
                **_quote_audit_payload(tick, reference_price),
            },
        )

        trade_request = TradeRequest(
            symbol=position.symbol,
            volume=position.volume,
            order_type=mt5_order_type,
            price=reference_price,
            deviation=deviation_points,
            magic=magic,
            comment=comment,
            position_ticket=position.ticket,
        )

        check = backend.order_check(trade_request)
        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.order_check",
            {
                "position_id": request.position_id,
                "symbol": position.symbol,
                "position_side": position.side,
                "closing_side": "sell" if closing_side_is_sell else "buy",
                "closed_volume": str(position.volume),
                **_quote_audit_payload(tick, reference_price),
                "ok": check.ok,
                "retcode": check.retcode,
                "comment": sanitize_message(check.comment),
            },
        )
        if not check.ok:
            raise OrderCheckFailedError(
                f"order_check rejected for close: retcode={check.retcode} comment={sanitize_message(check.comment)}"
            )
    except TradingError as exc:
        _terminalize_pre_submission_reject(
            store,
            request_id,
            request.client_order_id,
            "close_position.pre_submit_rejected",
            exc,
        )
        raise

    try:
        store.transition_idempotency_state(
            request.client_order_id,
            expected_state=OrderState.RECEIVED,
            new_state=OrderState.SUBMITTED,
        )
    except IdempotencyStateError as exc:
        raise ReconciliationRequiredError(
            f"client_order_id state changed before close submission; refusing order_send: {sanitize_message(str(exc))}"
        ) from exc

    _journal(
        store,
        request_id,
        request.client_order_id,
        "close_position.submitting",
        {
            "position_id": request.position_id,
            "symbol": position.symbol,
            "position_side": position.side,
            "closing_side": "sell" if closing_side_is_sell else "buy",
            "closed_volume": str(position.volume),
            **_quote_audit_payload(tick, reference_price),
        },
    )

    try:
        send_result = backend.order_send(trade_request)
    except MT5BackendError as exc:
        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.crash_during_send",
            {"error": sanitize_message(str(exc))},
        )
        raise OrderSendFailedError(
            f"order_send failed unexpectedly during close: {sanitize_message(str(exc))}"
        ) from exc

    now = datetime.now(timezone.utc)
    if send_result.retcode != TRADE_RETCODE_DONE:
        store.update_idempotency_state(
            request.client_order_id,
            OrderState.REJECTED,
            error_code=str(send_result.retcode),
        )
        _journal(
            store,
            request_id,
            request.client_order_id,
            "close_position.rejected",
            {
                "position_id": request.position_id,
                "symbol": position.symbol,
                "position_side": position.side,
                "closing_side": "sell" if closing_side_is_sell else "buy",
                "closed_volume": str(position.volume),
                **_quote_audit_payload(tick, reference_price),
                "mt5_retcode": send_result.retcode,
                "comment": sanitize_message(send_result.comment),
            },
        )
        raise OrderSendFailedError(
            f"order_send did not complete close: retcode={send_result.retcode} comment={sanitize_message(send_result.comment)}"
        )

    fill_price = send_result.price if send_result.price is not None else reference_price
    slippage = (reference_price - fill_price) if closing_side_is_sell else (fill_price - reference_price)
    deal_id = str(send_result.deal) if send_result.deal is not None else None

    result_payload = {
        "client_order_id": request.client_order_id,
        "position_id": request.position_id,
        "status": "filled",
        "closed_volume": str(position.volume),
        "observed_bid": str(tick.bid),
        "observed_ask": str(tick.ask),
        "reference_price": str(reference_price),
        "fill_price": str(fill_price),
        "slippage": str(slippage),
        "deal_id": deal_id,
        "mt5_retcode": send_result.retcode,
        "timestamp": now.isoformat(),
        "error_message": None,
    }
    store.update_idempotency_state(
        request.client_order_id,
        OrderState.FILLED,
        deal_id=deal_id,
        position_id=request.position_id,
        result_payload=result_payload,
    )
    _journal(
        store,
        request_id,
        request.client_order_id,
        "close_position.filled",
        {
            "position_id": request.position_id,
            "symbol": position.symbol,
            "position_side": position.side,
            "closing_side": "sell" if closing_side_is_sell else "buy",
            "closed_volume": str(position.volume),
            **_quote_audit_payload(tick, reference_price),
            "fill_price": str(fill_price),
            "slippage": str(slippage),
            "mt5_retcode": send_result.retcode,
            "deal_id": deal_id,
            "result_timestamp": now.isoformat(),
        },
    )

    return DemoCloseResult(**_decimalize_close_payload(dict(result_payload, idempotent_replay=False)))


def _terminalize_pre_submission_reject(
    store: BridgeStore,
    request_id: str | None,
    client_order_id: str,
    action: str,
    exc: TradingError,
) -> None:
    """Close a fresh RECEIVED row after a definite pre-order_send rejection.

    These failures are known not to have reached MT5's submission boundary,
    so leaving them RECEIVED would create a false reconciliation mismatch.
    The transition is conditional to avoid overwriting any concurrent state
    change; failure to transition is itself treated fail-closed by callers.
    """

    error_code = getattr(exc, "code", "pre_submission_rejected")
    try:
        store.transition_idempotency_state(
            client_order_id,
            expected_state=OrderState.RECEIVED,
            new_state=OrderState.REJECTED,
            error_code=error_code,
        )
    except IdempotencyStateError as state_exc:
        raise ReconciliationRequiredError(
            f"client_order_id state changed while recording pre-submission rejection: {sanitize_message(str(state_exc))}"
        ) from state_exc
    _journal(
        store,
        request_id,
        client_order_id,
        action,
        {"error_code": error_code, "error": sanitize_message(str(exc))},
    )


def _quote_audit_payload(tick, reference_price: Decimal) -> dict[str, str]:
    """Stable, secret-free quote context persisted around a write.

    This deliberately records the quote actually used by the bridge at
    the execution boundary, not a later re-fetch. Decimal values are
    serialized as strings to preserve exactness in SQLite/JSON.
    """

    return {
        "quote_timestamp": tick.time_utc.astimezone(timezone.utc).isoformat(),
        "observed_bid": str(tick.bid),
        "observed_ask": str(tick.ask),
        "spread": str(tick.ask - tick.bid),
        "reference_price": str(reference_price),
    }


def _journal(store: BridgeStore, request_id: str | None, client_order_id: str | None, action: str, payload: dict) -> None:
    sanitized = {k: (sanitize_message(v) if isinstance(v, str) else v) for k, v in payload.items()}
    store.append_journal(request_id=request_id, client_order_id=client_order_id, action=action, payload=sanitized)


def _decimalize_order_payload(payload: dict) -> dict:
    result = dict(payload)
    for key in ("requested_volume", "filled_volume", "observed_bid", "observed_ask", "reference_price", "fill_price", "slippage"):
        if result.get(key) is not None:
            result[key] = Decimal(str(result[key]))
    result["timestamp"] = datetime.fromisoformat(result["timestamp"]) if isinstance(result["timestamp"], str) else result["timestamp"]
    return result


def _decimalize_close_payload(payload: dict) -> dict:
    result = dict(payload)
    for key in ("closed_volume", "observed_bid", "observed_ask", "reference_price", "fill_price", "slippage"):
        if result.get(key) is not None:
            result[key] = Decimal(str(result[key]))
    result["timestamp"] = datetime.fromisoformat(result["timestamp"]) if isinstance(result["timestamp"], str) else result["timestamp"]
    return result
