"""FastAPI bridge application (FX Phase 0, Steps 3 + 4).

Read-only routes (Step 3) plus DEMO-only write routes (Step 4).
`create_app(backend, config, store=None)` takes an already-constructed
`MT5Backend` (real or fake) and `BridgeConfig`; `store` is an optional
`BridgeStore` (defaults to one backed by `config.db_path`) so tests can
inject an in-memory store.

Read-only endpoints (unchanged from Step 3):

    GET /v1/health
    GET /v1/terminal
    GET /v1/account
    GET /v1/symbols
    GET /v1/symbols/{symbol}
    GET /v1/quotes/{symbol}
    GET /v1/time-diagnostics/{symbol}
    GET /v1/history/{symbol}?start=...&end=...&timeframe=...
    GET /v1/profit-calc/{symbol}?side=...&volume=...&price_open=...&price_close=...
    GET /v1/positions
    GET /v1/orders

Write endpoints (Step 4), ALL under `/v1/demo/...` -- there is no
`/v1/live/...` anything, anywhere, and no generic ambiguous `POST
/orders`:

    POST /v1/demo/orders
    POST /v1/demo/positions/{position_id}/close

Kill switch / reconciliation / journal (Step 4):

    GET  /v1/kill-switch
    POST /v1/kill-switch/activate
    POST /v1/kill-switch/deactivate
    GET  /v1/reconciliation
    POST /v1/reconciliation/run
    GET  /v1/journal?limit=N

Every write request is re-verified server-side (fresh `account_info()`,
never a cached value) to be DEMO before touching MT5 at all -- see
`mt5_bridge/trading.py`'s `_require_fresh_demo_account`. This is
independent of and in addition to whatever the Linux-side caller already
checked via Step 1's `authorize_open`/`authorize_close` -- defense in
depth, not a single point of trust.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mt5_bridge.auth import check_bearer_token
from mt5_bridge.backend import (
    MT5Backend,
    MT5BackendError,
    MT5_TIMEFRAME_ATTR_BY_NAME,
    ORDER_TYPE_BUY,
    ORDER_TYPE_SELL,
    ProfitCalcRequest,
)
from mt5_bridge.config import BRIDGE_BUILD, BridgeConfig
from mt5_bridge.errors import (
    BackendUnavailableError,
    BadRequestError,
    BridgeError,
    ConflictError,
    NotFoundError,
    TradingWriteError,
    to_error_body,
)
from mt5_bridge.reconciliation import (
    ReceivedResolutionError,
    get_reconciliation_status,
    resolve_received_attempt,
    run_reconciliation,
)
from mt5_bridge.schemas import (
    account_response,
    demo_close_result_response,
    demo_order_result_response,
    health_response,
    history_response,
    journal_response,
    kill_switch_response,
    orders_response,
    positions_response,
    profit_calc_response,
    quote_response,
    reconciliation_response,
    symbol_response,
    symbols_response,
    terminal_response,
    time_diagnostics_response,
)
from mt5_bridge.quote_freshness import validate_quote_freshness, QuoteFreshnessError
from mt5_bridge.sanitize import sanitize_message
from mt5_bridge.store import BridgeStore, IdempotencyConflictError
from mt5_bridge.trading import (
    DemoCloseRequest,
    DemoOrderRequest,
    KillSwitchActiveError,
    NotDemoError,
    OrderCheckFailedError,
    OrderSendFailedError,
    PositionNotFoundError,
    ReconciliationRequiredError,
    StaleQuoteError,
    SymbolNotTradableError,
    TooManyPositionsError,
    TradingPermissionError,
    InvalidVolumeError,
    close_demo_position,
    place_demo_order,
)

logger = logging.getLogger("mt5_bridge")

ALLOWED_TIMEFRAMES = tuple(MT5_TIMEFRAME_ATTR_BY_NAME.keys())
MAX_HISTORY_BARS = 20_000
MAX_CLIENT_ORDER_ID_LENGTH = 128

_TRADING_ERROR_STATUS = {
    "not_demo": 403,
    "autotrading_disabled": 403,
    "kill_switch_active": 403,
    "reconciliation_required": 409,
    "symbol_not_tradable": 403,
    "stale_quote": 409,
    "order_check_failed": 422,
    "order_send_failed": 502,
    "position_not_found": 404,
    "too_many_positions": 403,
    "invalid_volume": 400,
}


def create_app(backend: MT5Backend, config: BridgeConfig, store: BridgeStore | None = None) -> FastAPI:
    app = FastAPI(title="mt5_bridge", version="1")
    app.state.backend = backend
    app.state.config = config
    app.state.store = store if store is not None else BridgeStore(config.db_path)
    store = app.state.store

    # A raw ASGI middleware, not `@app.middleware("http")` (which wraps
    # `BaseHTTPMiddleware`): that wrapper re-raises exceptions from
    # `call_next()` in a way that fights with FastAPI's own exception
    # handlers (registered below), which is exactly what must sanitize
    # any unexpected backend exception before it reaches the client. A
    # plain ASGI middleware runs alongside routing/exception handling
    # instead of wrapping it, so it never intercepts an exception meant
    # for `handle_unexpected_error`.
    class RequestContextMiddleware:
        def __init__(self, inner_app) -> None:
            self.app = inner_app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = dict(scope.get("headers") or [])
            request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
            scope.setdefault("state", {})
            scope["state"]["request_id"] = request_id

            start = time.monotonic()
            status_holder = {"status": None}

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    status_holder["status"] = message["status"]
                    raw_headers = list(message.get("headers", []))
                    raw_headers.append((b"x-request-id", request_id.encode()))
                    message = {**message, "headers": raw_headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)

            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "request_id=%s method=%s path=%s status=%s latency_ms=%.2f backend_connected=%s",
                request_id,
                scope.get("method"),
                scope.get("path"),
                status_holder["status"],
                latency_ms,
                _safe_is_connected(backend),
            )

    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(BridgeError)
    async def handle_bridge_error(request: Request, exc: BridgeError):
        return JSONResponse(status_code=exc.status_code, content=to_error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # Unifies FastAPI's own 422 (e.g. a required query/body field
        # missing) under the same {"error": {code, message}} envelope
        # every other error uses -- Step 4 section 39. Still 422, still
        # fail-closed (a missing required field is never defaulted), just
        # a consistent body shape for the Linux client to parse.
        return JSONResponse(status_code=422, content=to_error_body("validation_error", "request validation failed"))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        return JSONResponse(status_code=500, content=to_error_body("internal_error", "an unexpected error occurred"))

    def _authenticate(authorization: str | None) -> None:
        result = check_bearer_token(authorization, config.api_token)
        if result.authenticated:
            return
        if result.failure_reason == "missing_authorization_header":
            raise _AuthError(401, "missing authorization header")
        raise _AuthError(403, "invalid or malformed authorization")

    @app.get("/v1/health")
    def get_health(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        connected = _safe_is_connected(backend)
        broker_name = None
        server_time = backend.server_time_utc()
        if connected:
            try:
                terminal = backend.terminal_info()
                broker_name = terminal.company or terminal.name
            except MT5BackendError:
                connected = False
        return health_response(
            bridge_alive=True, terminal_connected=connected, server_time_utc=server_time, broker_name=broker_name,
            bridge_version="1", bridge_build=BRIDGE_BUILD, bridge_time_utc=datetime.now(timezone.utc),
        )

    @app.get("/v1/terminal")
    def get_terminal(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            info = backend.terminal_info()
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return terminal_response(info)

    @app.get("/v1/account")
    def get_account(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            info = backend.account_info()
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return account_response(info)

    @app.get("/v1/symbols")
    def get_symbols(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            infos = backend.symbols_get()
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return symbols_response(infos)

    @app.get("/v1/symbols/{symbol}")
    def get_symbol(symbol: str, authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        info = backend.symbol_info(symbol)
        if info is None:
            raise NotFoundError(f"symbol {symbol!r} not found")
        return symbol_response(info)

    @app.get("/v1/quotes/{symbol}")
    def get_quote(symbol: str, authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            tick = backend.symbol_info_tick(symbol)
        except MT5BackendError as exc:
            # A stale/off-market tick can fail clock normalization.  That is
            # an upstream MT5 availability condition, not an application bug
            # and must retain the bridge's safe 502 error envelope.
            raise BackendUnavailableError(str(exc)) from exc
        if tick is None:
            raise NotFoundError(f"no tick available for symbol {symbol!r}")
        if tick.bid <= 0 or tick.ask <= 0:
            raise BackendUnavailableError(f"symbol {symbol!r} returned an invalid tick (bid/ask <= 0)")
        return quote_response(tick)

    @app.get("/v1/time-diagnostics/{symbol}")
    def get_time_diagnostics(symbol: str, authorization: str | None = Header(default=None)):
        """READ-ONLY clock diagnostics. Never calls order_check/order_send
        and never touches the write path -- see mt5_bridge/quote_freshness.py
        and FX_PHASE0_STATUS.md's "quote has a timestamp in the future"
        investigation for why this exists.
        """

        _authenticate(authorization)
        bridge_now = datetime.now(timezone.utc)
        try:
            tick = backend.symbol_info_tick(symbol)
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        server_clock_offset_seconds = backend.server_clock_offset_seconds()
        if tick is None:
            return time_diagnostics_response(
                symbol=symbol, bridge_time_utc=bridge_now, mt5_tick_time_utc=None,
                quote_age_seconds=None, quote_future_skew_seconds=None,
                server_clock_offset_seconds=server_clock_offset_seconds,
            )
        try:
            result = validate_quote_freshness(
                symbol=symbol,
                quote_timestamp=tick.time_utc,
                now_utc=bridge_now,
                max_age_seconds=config.max_quote_age_seconds,
                max_future_skew_seconds=config.max_quote_future_skew_seconds,
            )
            age_seconds = result.age_seconds
            future_skew_seconds = result.future_skew_seconds
        except QuoteFreshnessError as exc:
            age_seconds = exc.age_seconds
            future_skew_seconds = -exc.age_seconds if exc.age_seconds < 0 else 0.0
        return time_diagnostics_response(
            symbol=symbol, bridge_time_utc=bridge_now, mt5_tick_time_utc=tick.time_utc,
            quote_age_seconds=age_seconds, quote_future_skew_seconds=future_skew_seconds,
            server_clock_offset_seconds=server_clock_offset_seconds,
        )

    @app.get("/v1/history/{symbol}")
    def get_history(
        symbol: str,
        start: str = Query(...),
        end: str = Query(...),
        timeframe: str = Query(...),
        authorization: str | None = Header(default=None),
    ):
        _authenticate(authorization)
        if timeframe not in ALLOWED_TIMEFRAMES:
            raise BadRequestError(f"timeframe must be one of {ALLOWED_TIMEFRAMES}, got {timeframe!r}")
        start_dt = _parse_query_timestamp(start, "start")
        end_dt = _parse_query_timestamp(end, "end")
        if start_dt >= end_dt:
            raise BadRequestError("start must be strictly before end")
        try:
            bars = backend.copy_rates_range(symbol, timeframe, start_dt, end_dt)
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        if len(bars) > MAX_HISTORY_BARS:
            raise BadRequestError(f"requested range would return {len(bars)} bars, exceeding the maximum of {MAX_HISTORY_BARS}")
        return history_response(bars)

    @app.get("/v1/profit-calc/{symbol}")
    def get_profit_calc(
        symbol: str,
        side: str = Query(...),
        volume: str = Query(...),
        price_open: str = Query(...),
        price_close: str = Query(...),
        authorization: str | None = Header(default=None),
    ):
        """READ-ONLY: MT5's `order_calc_profit()` as a diagnostic oracle
        (Phase 5B, Section 11). Computes profit for a hypothetical
        open/close price pair -- creates no order, no deal, no position,
        and never calls into `mt5_bridge.trading`. Exists purely so
        TradingIA's own PnL formula can be checked against MT5's, for
        synthetic scenarios, without ever touching `/v1/demo/...`.
        """
        _authenticate(authorization)
        if side not in ("buy", "sell"):
            raise BadRequestError("side must be 'buy' or 'sell'")
        try:
            volume_dec = Decimal(volume)
            price_open_dec = Decimal(price_open)
            price_close_dec = Decimal(price_close)
        except InvalidOperation:
            raise BadRequestError("volume/price_open/price_close must be decimal numbers")
        if volume_dec <= 0:
            raise BadRequestError("volume must be positive")
        if price_open_dec <= 0 or price_close_dec <= 0:
            raise BadRequestError("price_open/price_close must be positive")

        order_type = ORDER_TYPE_BUY if side == "buy" else ORDER_TYPE_SELL
        request = ProfitCalcRequest(
            symbol=symbol,
            order_type=order_type,
            volume=volume_dec,
            price_open=price_open_dec,
            price_close=price_close_dec,
        )
        try:
            profit = backend.order_calc_profit(request)
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return profit_calc_response(symbol, side, volume_dec, price_open_dec, price_close_dec, profit)

    @app.get("/v1/positions")
    def get_positions(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            positions = backend.positions_get()
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return positions_response(positions)

    @app.get("/v1/orders")
    def get_orders(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        try:
            orders = backend.orders_get()
        except MT5BackendError as exc:
            raise BackendUnavailableError(str(exc)) from exc
        return orders_response(orders)

    # ---------------------------------------------------------------- Step 4: writes

    def _map_trading_error(exc: Exception) -> BridgeError:
        code = getattr(exc, "code", "trading_error")
        status = _TRADING_ERROR_STATUS.get(code, 403)
        return TradingWriteError(status, code, str(exc))

    @app.post("/v1/demo/orders")
    def post_demo_order(http_request: Request, payload: dict = Body(...), authorization: str | None = Header(default=None)):
        request_id = getattr(http_request.state, "request_id", None)
        _authenticate(authorization)
        client_order_id = payload.get("client_order_id")
        symbol = payload.get("symbol")
        side = payload.get("side")
        volume_raw = payload.get("volume")

        if not isinstance(client_order_id, str) or not client_order_id or len(client_order_id) > MAX_CLIENT_ORDER_ID_LENGTH:
            raise BadRequestError("client_order_id must be a non-empty string")
        if not isinstance(symbol, str) or not symbol:
            raise BadRequestError("symbol must be a non-empty string")
        if side not in ("buy", "sell"):
            raise BadRequestError("side must be 'buy' or 'sell'")
        try:
            volume = Decimal(str(volume_raw))
        except (InvalidOperation, TypeError):
            raise BadRequestError(f"volume must be a decimal number, got {volume_raw!r}")

        request = DemoOrderRequest(client_order_id=client_order_id, symbol=symbol, side=side, volume=volume)
        try:
            result = place_demo_order(
                backend, store, request,
                max_positions=1,
                max_quote_age_seconds=config.max_quote_age_seconds,
                max_quote_future_skew_seconds=config.max_quote_future_skew_seconds,
                deviation_points=config.deviation_points,
                magic=config.magic,
                request_id=request_id,
            )
        except IdempotencyConflictError as exc:
            raise ConflictError(str(exc)) from exc
        except (
            NotDemoError, KillSwitchActiveError, ReconciliationRequiredError, SymbolNotTradableError,
            StaleQuoteError, OrderCheckFailedError, OrderSendFailedError, TooManyPositionsError, TradingPermissionError, InvalidVolumeError,
        ) as exc:
            raise _map_trading_error(exc) from exc
        return demo_order_result_response(result)

    @app.post("/v1/demo/positions/{position_id}/close")
    def post_demo_close(http_request: Request, position_id: str, payload: dict = Body(...), authorization: str | None = Header(default=None)):
        request_id = getattr(http_request.state, "request_id", None)
        _authenticate(authorization)
        client_order_id = payload.get("client_order_id")
        if not isinstance(client_order_id, str) or not client_order_id or len(client_order_id) > MAX_CLIENT_ORDER_ID_LENGTH:
            raise BadRequestError("client_order_id must be a non-empty string")

        request = DemoCloseRequest(client_order_id=client_order_id, position_id=position_id)
        try:
            result = close_demo_position(
                backend, store, request,
                max_quote_age_seconds=config.max_quote_age_seconds,
                max_quote_future_skew_seconds=config.max_quote_future_skew_seconds,
                deviation_points=config.deviation_points,
                magic=config.magic,
                request_id=request_id,
            )
        except IdempotencyConflictError as exc:
            raise ConflictError(str(exc)) from exc
        except (NotDemoError, TradingPermissionError, PositionNotFoundError, StaleQuoteError, OrderCheckFailedError, OrderSendFailedError, SymbolNotTradableError) as exc:
            raise _map_trading_error(exc) from exc
        return demo_close_result_response(result)

    # ---------------------------------------------------------------- Step 4: kill switch

    @app.get("/v1/kill-switch")
    def get_kill_switch(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        status, changed_at, reason = store.get_kill_switch()
        return kill_switch_response(status, changed_at, reason)

    @app.post("/v1/kill-switch/activate")
    def activate_kill_switch(payload: dict | None = Body(default=None), authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        reason = (payload or {}).get("reason")
        changed_at = store.set_kill_switch("active", reason if isinstance(reason, str) else None)
        return kill_switch_response("active", changed_at, reason if isinstance(reason, str) else None)

    @app.post("/v1/kill-switch/deactivate")
    def deactivate_kill_switch(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        changed_at = store.set_kill_switch("inactive", None)
        return kill_switch_response("inactive", changed_at, None)

    # ---------------------------------------------------------------- Step 4: reconciliation

    @app.get("/v1/reconciliation")
    def get_reconciliation(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        report = get_reconciliation_status(store)
        return reconciliation_response(report)

    @app.post("/v1/reconciliation/run")
    def post_reconciliation_run(authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        report = run_reconciliation(store, backend)
        return reconciliation_response(report)

    @app.post("/v1/reconciliation/resolve-received/{client_order_id}")
    def post_reconciliation_resolve_received(
        http_request: Request,
        client_order_id: str,
        body: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        """Explicit, narrow operator action for a row that is provably
        still PRE-SUBMISSION (RECEIVED). Never accepts SUBMITTED.
        """

        _authenticate(authorization)
        if not client_order_id or len(client_order_id) > MAX_CLIENT_ORDER_ID_LENGTH:
            raise BadRequestError("client_order_id is missing or too long")
        if body.get("confirm_abort_before_submission") is not True:
            raise BadRequestError("confirm_abort_before_submission=true is required")
        request_id = getattr(http_request.state, "request_id", None)
        try:
            report = resolve_received_attempt(
                store,
                backend,
                client_order_id,
                magic=config.magic,
                request_id=request_id,
            )
        except ReceivedResolutionError as exc:
            raise ConflictError(sanitize_message(str(exc))) from exc
        return reconciliation_response(report)

    # ---------------------------------------------------------------- Step 4: journal

    @app.get("/v1/journal")
    def get_journal(limit: int = Query(default=100, ge=1, le=1000), authorization: str | None = Header(default=None)):
        _authenticate(authorization)
        entries = store.read_journal(limit)
        return journal_response(entries)

    return app


class _AuthError(BridgeError):
    code = "unauthorized"

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


def _safe_is_connected(backend: MT5Backend) -> bool:
    try:
        return backend.is_connected()
    except Exception:
        return False


def _parse_query_timestamp(value: str, field_name: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BadRequestError(f"{field_name} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BadRequestError(f"{field_name} must include a UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)
