"""Linux-side HTTP client for the future Windows `mt5_bridge` (FX Phase 0, Step 2).

This module implements `MT5RemoteExecutionClient`, an `ExecutionClient`
(see `src/execution/base.py`) that talks to a small versioned HTTP
contract. Nothing here imports `MetaTrader5` or runs on Windows — the
actual bridge server does not exist yet (a later step). Step 2 freezes
the HTTP contract and the client's parsing/error-handling behavior
against an injectable fake transport, so the contract can be reviewed and
tested before any real server is written.

Read-only for now: `health`, `terminal`, `account`, `symbols`,
`symbol_metadata`, `quote`, `history`, `positions`, `orders`. The
`ExecutionClient.place_order` method raises `NotImplementedError`
unconditionally — there is no code path in this client that can reach a
network call for placing an order. That is deliberate: nothing here
should be able to accidentally send a write.

Design principles carried over from Step 1 and applied to the transport
boundary specifically:

- Fail closed on ambiguity. A remote response that is missing a field
  needed to *positively* identify DEMO, or that omits sizing/OHLC data
  needed to trust a value, is parsed as `UNKNOWN`/rejected — never
  defaulted to something that looks safe (see `_parse_environment`,
  `_parse_trade_mode`, `_parse_symbol_metadata`).
- Small number of clearly distinguished domain exceptions instead of
  letting `requests` exceptions or bare `KeyError`/`ValueError` leak
  through the client boundary (see the exception hierarchy below).
- The API token never appears in a URL, a header dump, a `repr()`, or an
  exception message. It is stored in the client only long enough to
  build the `Authorization` header for a single request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote as urlquote
from urllib.parse import urlsplit

from src.execution.base import (
    AccountSummary,
    AccountTradeMode,
    CloseRequest,
    CloseResult,
    Environment,
    ExecutionResult,
    ExecutionTimeframe,
    HealthStatus,
    HistoryBar,
    HistoryRequest,
    HistoryResult,
    JournalEntry,
    KillSwitchState,
    KillSwitchStatus,
    Order,
    OrderRequest,
    OrderStatus,
    Position,
    Quote,
    ReconciliationReport,
    ReconciliationState,
    Side,
    SymbolMetadata,
    SymbolSummary,
    TerminalStatus,
    TimeDiagnostics,
)

EXPECTED_API_VERSION = "1"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 5_000_000  # generous cap for a small-payload local-LAN API

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


# --------------------------------------------------------------------------
# Domain exceptions
# --------------------------------------------------------------------------


class ExecutionClientError(Exception):
    """Base class for every error this client can raise."""


class ExecutionTransportError(ExecutionClientError):
    """The request could not reach the bridge at all (DNS, connection
    refused, TLS failure, etc.) — distinct from a timeout."""


class ExecutionTimeoutError(ExecutionClientError):
    """The bridge did not respond within `RemoteConfig.timeout_seconds`."""


class ExecutionAuthenticationError(ExecutionClientError):
    """The bridge rejected the request as unauthenticated/unauthorized
    (HTTP 401/403). Never includes the token that was sent."""


class ExecutionRequestError(ExecutionClientError):
    """The bridge rejected the request as malformed/invalid on its own
    terms (HTTP 4xx other than 401/403)."""


class ExecutionRemoteError(ExecutionClientError):
    """The bridge/terminal reported an internal failure (HTTP 5xx)."""


class ExecutionProtocolError(ExecutionClientError):
    """The response could not be trusted: invalid JSON, a missing
    required field, an incompatible API version, or a value that fails a
    domain invariant (e.g. ask < bid, invalid OHLC, unordered history)."""


class ExecutionWriteRejectedError(ExecutionClientError):
    """The bridge refused a WRITE request (place_order/close_position)
    for a specific, named safety reason -- kill switch active, account
    not confirmed DEMO, reconciliation not OK, too many positions,
    symbol not tradable, stale quote, order_check failed, idempotency
    conflict, position not found, invalid volume. `error_code` carries
    the bridge's own `error.code` from its structured response body
    (see `mt5_bridge/errors.py`) so callers can branch on the specific
    reason rather than treating every write rejection identically.
    """

    def __init__(self, error_code: str, message: str, http_status: int) -> None:
        self.error_code = error_code
        self.http_status = http_status
        super().__init__(message)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteConfig:
    """Connection settings for the bridge.

    The token is read from an environment variable, never from a YAML
    file, and this dataclass's `__repr__` is overridden so the token
    cannot leak through logging a config object or an assertion failure
    in a test.
    """

    bridge_url: str
    api_token: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    expected_api_version: str = EXPECTED_API_VERSION

    def __post_init__(self) -> None:
        parsed = urlsplit(self.bridge_url)
        if parsed.scheme not in _ALLOWED_URL_SCHEMES:
            raise ValueError(
                f"bridge_url scheme must be one of {sorted(_ALLOWED_URL_SCHEMES)}, got {parsed.scheme!r}"
            )
        if not parsed.hostname:
            raise ValueError("bridge_url must include a host")
        if parsed.username or parsed.password:
            raise ValueError("bridge_url must not embed credentials")
        if not self.api_token:
            raise ValueError("api_token must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def __repr__(self) -> str:
        return f"RemoteConfig(bridge_url={self.bridge_url!r}, api_token=***, timeout_seconds={self.timeout_seconds!r})"

    @staticmethod
    def from_env(
        bridge_url: str,
        token_env_var: str = "MT5_REMOTE_TOKEN",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        expected_api_version: str = EXPECTED_API_VERSION,
    ) -> "RemoteConfig":
        token = os.environ.get(token_env_var)
        if not token:
            raise ValueError(f"environment variable {token_env_var} is not set")
        return RemoteConfig(
            bridge_url=bridge_url,
            api_token=token,
            timeout_seconds=timeout_seconds,
            expected_api_version=expected_api_version,
        )


# --------------------------------------------------------------------------
# Injectable HTTP transport (kept tiny and structural so tests never need
# a real socket or a third-party mocking library)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    text: str
    content_length: int | None = None


class HttpTransport(Protocol):
    """Structural interface the client needs from an HTTP library.

    `requests.Session` satisfies this shape closely enough via a thin
    adapter (`RequestsTransport` below); tests inject a fake instead.
    """

    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse: ...

    def post(self, url: str, headers: dict[str, str], timeout: float, json_body: dict) -> HttpResponse: ...


class RequestsTransport:
    """Thin adapter over `requests.Session` satisfying `HttpTransport`.

    Translates `requests` exceptions into this module's own transport
    exceptions immediately, so nothing downstream ever has to know
    `requests` exists.
    """

    def __init__(self) -> None:
        import requests  # local import: keep `requests` an implementation detail

        self._session = requests.Session()
        self._requests = requests

    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        try:
            response = self._session.get(
                url, headers=headers, timeout=timeout, allow_redirects=False
            )
        except self._requests.exceptions.Timeout as exc:
            raise ExecutionTimeoutError(f"request to bridge timed out after {timeout}s") from exc
        except self._requests.exceptions.RequestException as exc:
            raise ExecutionTransportError("failed to reach bridge") from exc

        content_length = len(response.content) if response.content is not None else None
        return HttpResponse(status_code=response.status_code, text=response.text, content_length=content_length)

    def post(self, url: str, headers: dict[str, str], timeout: float, json_body: dict) -> HttpResponse:
        try:
            response = self._session.post(
                url, headers=headers, timeout=timeout, allow_redirects=False, json=json_body
            )
        except self._requests.exceptions.Timeout as exc:
            raise ExecutionTimeoutError(f"request to bridge timed out after {timeout}s") from exc
        except self._requests.exceptions.RequestException as exc:
            raise ExecutionTransportError("failed to reach bridge") from exc

        content_length = len(response.content) if response.content is not None else None
        return HttpResponse(status_code=response.status_code, text=response.text, content_length=content_length)


# --------------------------------------------------------------------------
# Parsing helpers -- all fail closed
# --------------------------------------------------------------------------


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionProtocolError(f"{context}: expected a JSON object, got {type(value).__name__}")
    return value


def _require_field(payload: dict[str, Any], key: str, context: str) -> Any:
    if key not in payload:
        raise ExecutionProtocolError(f"{context}: missing required field {key!r}")
    return payload[key]


def _parse_decimal(value: Any, context: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ExecutionProtocolError(f"{context}: expected a numeric value, got {value!r}")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExecutionProtocolError(f"{context}: invalid decimal value {value!r}") from exc


def _parse_optional_decimal(value: Any, context: str) -> Decimal | None:
    if value is None:
        return None
    return _parse_decimal(value, context)


def _parse_utc_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str):
        raise ExecutionProtocolError(f"{context}: expected an ISO-8601 timestamp string, got {value!r}")
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ExecutionProtocolError(f"{context}: invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ExecutionProtocolError(f"{context}: timestamp {value!r} is missing UTC offset")
    return parsed.astimezone(timezone.utc)


def _parse_environment(value: Any) -> Environment:
    if value == "demo":
        return Environment.DEMO
    if value == "live":
        return Environment.LIVE
    return Environment.UNKNOWN


def _parse_trade_mode(value: Any) -> AccountTradeMode:
    if value == "demo":
        return AccountTradeMode.DEMO
    if value == "live":
        return AccountTradeMode.LIVE
    if value == "contest":
        return AccountTradeMode.CONTEST
    return AccountTradeMode.UNKNOWN


def _parse_side(value: Any, context: str) -> Side:
    if value == "buy":
        return Side.BUY
    if value == "sell":
        return Side.SELL
    raise ExecutionProtocolError(f"{context}: unrecognized side {value!r}")


def _parse_order_status(value: Any) -> OrderStatus:
    mapping = {
        "accepted": OrderStatus.ACCEPTED,
        "filled": OrderStatus.FILLED,
        "rejected": OrderStatus.REJECTED,
        "error": OrderStatus.ERROR,
    }
    return mapping.get(value, OrderStatus.ERROR)


def _validate_symbol_for_path(symbol: str) -> str:
    """Percent-encode a symbol for safe inclusion in a URL path segment.

    Rejects empty/whitespace-only symbols and anything containing a path
    separator, which would otherwise let a caller escape the intended
    `/v1/symbols/{symbol}`-style path (e.g. `symbol="../orders"`).
    `urlquote` alone is not sufficient because it happily encodes `/` by
    default only if `safe=""`; the explicit rejection below makes the
    intent obvious rather than relying solely on encoding.
    """

    if not symbol or not symbol.strip():
        raise ValueError("symbol must not be empty")
    if "/" in symbol or "\\" in symbol or ".." in symbol:
        raise ValueError(f"symbol {symbol!r} is not a valid path segment")
    return urlquote(symbol, safe="")


# --------------------------------------------------------------------------
# Response -> domain model mapping
# --------------------------------------------------------------------------


def _parse_health(payload: dict[str, Any]) -> HealthStatus:
    api_version = _require_field(payload, "api_version", "health")
    bridge_alive = _require_field(payload, "bridge_alive", "health")
    terminal_connected = _require_field(payload, "terminal_connected", "health")
    if not isinstance(bridge_alive, bool) or not isinstance(terminal_connected, bool):
        raise ExecutionProtocolError("health: bridge_alive/terminal_connected must be booleans")
    server_time_raw = payload.get("server_time")
    server_time = _parse_utc_timestamp(server_time_raw, "health.server_time") if server_time_raw is not None else None
    broker_name = payload.get("broker_name")
    if broker_name is not None and not isinstance(broker_name, str):
        raise ExecutionProtocolError("health.broker_name must be a string if present")
    bridge_version = payload.get("bridge_version")
    if bridge_version is not None and not isinstance(bridge_version, str):
        raise ExecutionProtocolError("health.bridge_version must be a string if present")
    bridge_build = payload.get("bridge_build")
    if bridge_build is not None and not isinstance(bridge_build, str):
        raise ExecutionProtocolError("health.bridge_build must be a string if present")
    bridge_time_raw = payload.get("bridge_time_utc")
    bridge_time_utc = (
        _parse_utc_timestamp(bridge_time_raw, "health.bridge_time_utc") if bridge_time_raw is not None else None
    )
    return HealthStatus(
        bridge_alive=bridge_alive,
        terminal_connected=terminal_connected,
        server_time=server_time,
        broker_name=broker_name,
        api_version=str(api_version),
        bridge_version=bridge_version,
        bridge_build=bridge_build,
        bridge_time_utc=bridge_time_utc,
    ), str(api_version)



def _parse_optional_bool(payload: dict[str, Any], key: str, context: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ExecutionProtocolError(f"{context}.{key} must be a boolean if present")
    return value


def _parse_terminal(payload: dict[str, Any]) -> TerminalStatus:
    connected = _require_field(payload, "connected", "terminal")
    trade_allowed = _require_field(payload, "trade_allowed", "terminal")
    if not isinstance(connected, bool) or not isinstance(trade_allowed, bool):
        raise ExecutionProtocolError("terminal.connected/trade_allowed must be booleans")
    dlls_allowed = _parse_optional_bool(payload, "dlls_allowed", "terminal")
    name = payload.get("name")
    company = payload.get("company")
    build = payload.get("build")
    if name is not None and not isinstance(name, str):
        raise ExecutionProtocolError("terminal.name must be a string if present")
    if company is not None and not isinstance(company, str):
        raise ExecutionProtocolError("terminal.company must be a string if present")
    if build is not None and (not isinstance(build, int) or isinstance(build, bool)):
        raise ExecutionProtocolError("terminal.build must be an integer if present")
    return TerminalStatus(
        connected=connected, trade_allowed=trade_allowed, dlls_allowed=dlls_allowed,
        name=name, company=company, build=build,
    )


def _parse_account(payload: dict[str, Any]) -> AccountSummary:
    account_id = _require_field(payload, "account_id", "account")
    if not isinstance(account_id, str) or not account_id:
        raise ExecutionProtocolError("account.account_id must be a non-empty string")
    currency = _require_field(payload, "currency", "account")
    if not isinstance(currency, str) or not currency:
        raise ExecutionProtocolError("account.currency must be a non-empty string")
    trade_mode = _parse_trade_mode(payload.get("trade_mode"))
    balance = _parse_decimal(_require_field(payload, "balance", "account"), "account.balance")
    equity = _parse_decimal(_require_field(payload, "equity", "account"), "account.equity")
    server = payload.get("server")
    if server is not None and not isinstance(server, str):
        raise ExecutionProtocolError("account.server must be a string if present")
    return AccountSummary(
        account_id=account_id,
        trade_mode=trade_mode,
        balance=balance,
        equity=equity,
        currency=currency,
        trade_allowed=_parse_optional_bool(payload, "trade_allowed", "account"),
        trade_expert=_parse_optional_bool(payload, "trade_expert", "account"),
        server=server,
    )


def _parse_symbol_metadata(payload: dict[str, Any], requested_symbol: str) -> SymbolMetadata:
    symbol = payload.get("symbol", requested_symbol)
    if symbol != requested_symbol:
        raise ExecutionProtocolError(
            f"symbol metadata: response symbol {symbol!r} does not match requested {requested_symbol!r}"
        )
    volume_min = _parse_decimal(_require_field(payload, "volume_min", "symbol_metadata"), "symbol_metadata.volume_min")
    volume_step = _parse_decimal(_require_field(payload, "volume_step", "symbol_metadata"), "symbol_metadata.volume_step")
    volume_max = _parse_decimal(_require_field(payload, "volume_max", "symbol_metadata"), "symbol_metadata.volume_max")
    contract_size = _parse_decimal(
        _require_field(payload, "trade_contract_size", "symbol_metadata"), "symbol_metadata.trade_contract_size"
    )
    digits = _require_field(payload, "digits", "symbol_metadata")
    if not isinstance(digits, int) or isinstance(digits, bool):
        raise ExecutionProtocolError("symbol_metadata.digits must be an integer")
    point = _parse_decimal(_require_field(payload, "point", "symbol_metadata"), "symbol_metadata.point")
    if volume_min <= 0 or volume_step <= 0 or volume_max <= 0:
        raise ExecutionProtocolError("symbol_metadata: volume_min/volume_step/volume_max must be positive")
    if volume_min > volume_max:
        raise ExecutionProtocolError("symbol_metadata: volume_min must be <= volume_max")
    tick_size = _parse_optional_decimal(payload.get("trade_tick_size"), "symbol_metadata.trade_tick_size")
    tick_value = _parse_optional_decimal(payload.get("trade_tick_value"), "symbol_metadata.trade_tick_value")
    currency_base = payload.get("currency_base")
    currency_profit = payload.get("currency_profit")
    currency_margin = payload.get("currency_margin")
    for name, value in [
        ("currency_base", currency_base),
        ("currency_profit", currency_profit),
        ("currency_margin", currency_margin),
    ]:
        if value is not None and not isinstance(value, str):
            raise ExecutionProtocolError(f"symbol_metadata.{name} must be a string if present")
    return SymbolMetadata(
        symbol=symbol,
        volume_min=volume_min,
        volume_step=volume_step,
        volume_max=volume_max,
        contract_size=contract_size,
        digits=digits,
        point=point,
        tick_size=tick_size,
        tick_value=tick_value,
        currency_base=currency_base,
        currency_profit=currency_profit,
        currency_margin=currency_margin,
    )


def _parse_symbol_summary(payload: dict[str, Any]) -> SymbolSummary:
    symbol = _require_field(payload, "symbol", "symbol_summary")
    if not isinstance(symbol, str) or not symbol:
        raise ExecutionProtocolError("symbol_summary.symbol must be a non-empty string")
    description = payload.get("description")
    if description is not None and not isinstance(description, str):
        raise ExecutionProtocolError("symbol_summary.description must be a string if present")
    visible = _require_field(payload, "visible", "symbol_summary")
    if not isinstance(visible, bool):
        raise ExecutionProtocolError("symbol_summary.visible must be a boolean")
    trade_enabled = payload.get("trade_enabled")
    if trade_enabled is not None and not isinstance(trade_enabled, bool):
        raise ExecutionProtocolError("symbol_summary.trade_enabled must be a boolean if present")
    return SymbolSummary(symbol=symbol, description=description, visible=visible, trade_enabled=trade_enabled)


def _parse_symbols(payload: dict[str, Any]) -> tuple[SymbolSummary, ...]:
    items = _require_field(payload, "symbols", "symbols")
    if not isinstance(items, list):
        raise ExecutionProtocolError("symbols.symbols must be a list")
    return tuple(_parse_symbol_summary(_require_mapping(s, "symbol_summary")) for s in items)


def _parse_quote(payload: dict[str, Any], requested_symbol: str) -> Quote:
    symbol = payload.get("symbol", requested_symbol)
    if symbol != requested_symbol:
        raise ExecutionProtocolError(
            f"quote: response symbol {symbol!r} does not match requested {requested_symbol!r}"
        )
    bid = _parse_decimal(_require_field(payload, "bid", "quote"), "quote.bid")
    ask = _parse_decimal(_require_field(payload, "ask", "quote"), "quote.ask")
    timestamp = _parse_utc_timestamp(_require_field(payload, "timestamp", "quote"), "quote.timestamp")
    if bid <= 0:
        raise ExecutionProtocolError(f"quote: bid must be positive, got {bid}")
    if ask <= 0:
        raise ExecutionProtocolError(f"quote: ask must be positive, got {ask}")
    if ask < bid:
        raise ExecutionProtocolError(f"quote: ask ({ask}) is less than bid ({bid})")
    return Quote(symbol=symbol, bid=bid, ask=ask, timestamp=timestamp)


def _parse_history_bar(payload: dict[str, Any], symbol: str) -> HistoryBar:
    """`tick_volume` and `real_volume` are parsed as distinct, honestly
    named fields -- never merged into one generic `volume`. `tick_volume`
    is required (the bridge always sends it); `real_volume` legitimately
    stays `None` for FX OTC symbols that do not report broker-side
    traded volume, which is not an error condition."""
    timestamp = _parse_utc_timestamp(_require_field(payload, "timestamp", "history_bar"), "history_bar.timestamp")
    open_ = _parse_decimal(_require_field(payload, "open", "history_bar"), "history_bar.open")
    high = _parse_decimal(_require_field(payload, "high", "history_bar"), "history_bar.high")
    low = _parse_decimal(_require_field(payload, "low", "history_bar"), "history_bar.low")
    close = _parse_decimal(_require_field(payload, "close", "history_bar"), "history_bar.close")
    tick_volume = _parse_decimal(_require_field(payload, "tick_volume", "history_bar"), "history_bar.tick_volume")
    real_volume_raw = payload.get("real_volume")
    real_volume = _parse_decimal(real_volume_raw, "history_bar.real_volume") if real_volume_raw is not None else None
    spread_raw = payload.get("spread")
    if spread_raw is not None and (not isinstance(spread_raw, int) or isinstance(spread_raw, bool)):
        raise ExecutionProtocolError("history_bar.spread must be an integer if present")
    if high < max(open_, close, low):
        raise ExecutionProtocolError(
            f"history_bar at {timestamp}: high ({high}) must be >= max(open, close, low)"
        )
    if low > min(open_, close, high):
        raise ExecutionProtocolError(
            f"history_bar at {timestamp}: low ({low}) must be <= min(open, close, high)"
        )
    return HistoryBar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_volume=tick_volume,
        real_volume=real_volume,
        spread_points=spread_raw,
    )


def _parse_history(payload: dict[str, Any], requested_symbol: str) -> HistoryResult:
    bars_raw = _require_field(payload, "bars", "history")
    if not isinstance(bars_raw, list):
        raise ExecutionProtocolError("history.bars must be a list")
    bars = tuple(_parse_history_bar(_require_mapping(b, "history_bar"), requested_symbol) for b in bars_raw)
    for earlier, later in zip(bars, bars[1:]):
        if later.timestamp <= earlier.timestamp:
            raise ExecutionProtocolError(
                f"history.bars is not strictly increasing in time: {earlier.timestamp} then {later.timestamp}"
            )
    return HistoryResult(symbol=requested_symbol, bars=bars)


def _parse_position(payload: dict[str, Any]) -> Position:
    position_id = _require_field(payload, "position_id", "position")
    symbol = _require_field(payload, "symbol", "position")
    side = _parse_side(_require_field(payload, "side", "position"), "position.side")
    volume = _parse_decimal(_require_field(payload, "volume", "position"), "position.volume")
    open_price = _parse_decimal(_require_field(payload, "open_price", "position"), "position.open_price")
    if volume <= 0:
        raise ExecutionProtocolError(f"position {position_id}: volume must be positive, got {volume}")
    return Position(position_id=str(position_id), symbol=str(symbol), side=side, volume=volume, open_price=open_price)


def _parse_positions(payload: dict[str, Any]) -> tuple[Position, ...]:
    items = _require_field(payload, "positions", "positions")
    if not isinstance(items, list):
        raise ExecutionProtocolError("positions.positions must be a list")
    return tuple(_parse_position(_require_mapping(p, "position")) for p in items)


def _parse_order(payload: dict[str, Any]) -> Order:
    """`client_order_id` is optional and stays `None` when absent/null --
    it distinguishes a TradingIA-originated order (has a real
    client_order_id) from a manual/external/other-EA order (does not).
    Never coerced to the string `"None"`, and never synthesized from the
    MT5 ticket -- see `Order.client_order_id`'s docstring in base.py and
    `mt5_bridge/schemas.py::order_response`.
    """

    if "client_order_id" not in payload:
        raise ExecutionProtocolError("order: missing required field 'client_order_id' (use null for external orders)")
    client_order_id_raw = payload["client_order_id"]
    if client_order_id_raw is not None and not isinstance(client_order_id_raw, str):
        raise ExecutionProtocolError(f"order.client_order_id must be a string or null, got {client_order_id_raw!r}")
    symbol = _require_field(payload, "symbol", "order")
    side = _parse_side(_require_field(payload, "side", "order"), "order.side")
    volume = _parse_decimal(_require_field(payload, "volume", "order"), "order.volume")
    status = _parse_order_status(payload.get("status"))
    broker_order_id = payload.get("broker_order_id")
    return Order(
        client_order_id=client_order_id_raw,
        symbol=str(symbol),
        side=side,
        volume=volume,
        status=status,
        broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
    )


def _parse_orders(payload: dict[str, Any]) -> tuple[Order, ...]:
    items = _require_field(payload, "orders", "orders")
    if not isinstance(items, list):
        raise ExecutionProtocolError("orders.orders must be a list")
    return tuple(_parse_order(_require_mapping(o, "order")) for o in items)




def _parse_journal(payload: dict[str, Any]) -> tuple[JournalEntry, ...]:
    items = _require_field(payload, "entries", "journal")
    if not isinstance(items, list):
        raise ExecutionProtocolError("journal.entries must be a list")

    parsed: list[JournalEntry] = []
    for raw in items:
        item = _require_mapping(raw, "journal_entry")
        entry_id = _require_field(item, "id", "journal_entry")
        if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
            raise ExecutionProtocolError("journal_entry.id must be a positive integer")
        request_id = item.get("request_id")
        client_order_id = item.get("client_order_id")
        if request_id is not None and not isinstance(request_id, str):
            raise ExecutionProtocolError("journal_entry.request_id must be a string or null")
        if client_order_id is not None and not isinstance(client_order_id, str):
            raise ExecutionProtocolError("journal_entry.client_order_id must be a string or null")
        action = _require_field(item, "action", "journal_entry")
        if not isinstance(action, str) or not action:
            raise ExecutionProtocolError("journal_entry.action must be a non-empty string")
        timestamp = _parse_utc_timestamp(_require_field(item, "timestamp", "journal_entry"), "journal_entry.timestamp")
        payload_obj = _require_mapping(_require_field(item, "payload", "journal_entry"), "journal_entry.payload")
        parsed.append(JournalEntry(
            entry_id=entry_id,
            request_id=request_id,
            client_order_id=client_order_id,
            timestamp=timestamp,
            action=action,
            payload=dict(payload_obj),
        ))
    return tuple(parsed)


def _parse_order_result(payload: dict[str, Any]) -> ExecutionResult:
    client_order_id = _require_field(payload, "client_order_id", "demo_order")
    status = _parse_order_status(payload.get("status"))
    return ExecutionResult(
        client_order_id=str(client_order_id),
        status=status,
        broker_order_id=payload.get("broker_order_id"),
        deal_id=payload.get("deal_id"),
        position_id=payload.get("position_id"),
        fill_price=_parse_optional_decimal(payload.get("fill_price"), "demo_order.fill_price"),
        filled_volume=_parse_optional_decimal(payload.get("filled_volume"), "demo_order.filled_volume"),
        requested_volume=_parse_optional_decimal(payload.get("requested_volume"), "demo_order.requested_volume"),
        observed_bid=_parse_optional_decimal(payload.get("observed_bid"), "demo_order.observed_bid"),
        observed_ask=_parse_optional_decimal(payload.get("observed_ask"), "demo_order.observed_ask"),
        reference_price=_parse_optional_decimal(payload.get("reference_price"), "demo_order.reference_price"),
        slippage=_parse_optional_decimal(payload.get("slippage"), "demo_order.slippage"),
        mt5_retcode=payload.get("mt5_retcode"),
        timestamp=_parse_utc_timestamp(_require_field(payload, "timestamp", "demo_order"), "demo_order.timestamp"),
        idempotent_replay=bool(payload.get("idempotent_replay", False)),
        error_message=payload.get("error_message"),
    )


def _parse_close_result(payload: dict[str, Any]) -> CloseResult:
    client_order_id = _require_field(payload, "client_order_id", "demo_close")
    position_id = _require_field(payload, "position_id", "demo_close")
    status = _parse_order_status(payload.get("status"))
    return CloseResult(
        client_order_id=str(client_order_id),
        position_id=str(position_id),
        status=status,
        closed_volume=_parse_optional_decimal(payload.get("closed_volume"), "demo_close.closed_volume"),
        observed_bid=_parse_optional_decimal(payload.get("observed_bid"), "demo_close.observed_bid"),
        observed_ask=_parse_optional_decimal(payload.get("observed_ask"), "demo_close.observed_ask"),
        reference_price=_parse_optional_decimal(payload.get("reference_price"), "demo_close.reference_price"),
        fill_price=_parse_optional_decimal(payload.get("fill_price"), "demo_close.fill_price"),
        slippage=_parse_optional_decimal(payload.get("slippage"), "demo_close.slippage"),
        deal_id=payload.get("deal_id"),
        mt5_retcode=payload.get("mt5_retcode"),
        timestamp=_parse_utc_timestamp(_require_field(payload, "timestamp", "demo_close"), "demo_close.timestamp"),
        idempotent_replay=bool(payload.get("idempotent_replay", False)),
        error_message=payload.get("error_message"),
    )


def _parse_kill_switch_state(payload: dict[str, Any]) -> KillSwitchState:
    status_raw = _require_field(payload, "status", "kill_switch")
    if status_raw == "active":
        status = KillSwitchStatus.ACTIVE
    elif status_raw == "inactive":
        status = KillSwitchStatus.INACTIVE
    else:
        raise ExecutionProtocolError(f"kill_switch: unrecognized status {status_raw!r}")
    changed_at_raw = payload.get("changed_at")
    changed_at = _parse_utc_timestamp(changed_at_raw, "kill_switch.changed_at") if changed_at_raw is not None else None
    return KillSwitchState(status=status, changed_at=changed_at, reason=payload.get("reason"))


def _parse_reconciliation_report(payload: dict[str, Any]) -> ReconciliationReport:
    state_raw = _require_field(payload, "state", "reconciliation")
    try:
        state = ReconciliationState(state_raw)
    except ValueError:
        state = ReconciliationState.UNKNOWN
    checked_at = _parse_utc_timestamp(_require_field(payload, "checked_at", "reconciliation"), "reconciliation.checked_at")
    details = payload.get("details", [])
    if not isinstance(details, list):
        raise ExecutionProtocolError("reconciliation.details must be a list")
    return ReconciliationReport(state=state, checked_at=checked_at, details=tuple(str(d) for d in details))


def _parse_time_diagnostics(payload: dict[str, Any], requested_symbol: str, linux_client_utc: datetime) -> TimeDiagnostics:
    symbol = payload.get("symbol", requested_symbol)
    bridge_time_utc = _parse_utc_timestamp(_require_field(payload, "bridge_time_utc", "time_diagnostics"), "time_diagnostics.bridge_time_utc")
    tick_raw = payload.get("mt5_tick_time_utc")
    mt5_tick_time_utc = _parse_utc_timestamp(tick_raw, "time_diagnostics.mt5_tick_time_utc") if tick_raw is not None else None
    server_clock_offset_raw = payload.get("server_clock_offset_seconds")
    if server_clock_offset_raw is not None and not isinstance(server_clock_offset_raw, (int, float)):
        raise ExecutionProtocolError("time_diagnostics.server_clock_offset_seconds must be a number if present")
    server_clock_offset_seconds = float(server_clock_offset_raw) if server_clock_offset_raw is not None else None

    bridge_client_skew_seconds = (bridge_time_utc - linux_client_utc).total_seconds()
    tick_client_skew_seconds = (mt5_tick_time_utc - linux_client_utc).total_seconds() if mt5_tick_time_utc is not None else None
    tick_bridge_skew_seconds = (mt5_tick_time_utc - bridge_time_utc).total_seconds() if mt5_tick_time_utc is not None else None
    quote_age_seconds_per_client = (linux_client_utc - mt5_tick_time_utc).total_seconds() if mt5_tick_time_utc is not None else None
    quote_age_seconds_per_bridge = (bridge_time_utc - mt5_tick_time_utc).total_seconds() if mt5_tick_time_utc is not None else None

    return TimeDiagnostics(
        symbol=str(symbol),
        linux_client_utc=linux_client_utc,
        bridge_time_utc=bridge_time_utc,
        mt5_tick_time_utc=mt5_tick_time_utc,
        bridge_client_skew_seconds=bridge_client_skew_seconds,
        tick_client_skew_seconds=tick_client_skew_seconds,
        tick_bridge_skew_seconds=tick_bridge_skew_seconds,
        quote_age_seconds_per_client=quote_age_seconds_per_client,
        quote_age_seconds_per_bridge=quote_age_seconds_per_bridge,
        server_clock_offset_seconds=server_clock_offset_seconds,
    )


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class MT5RemoteExecutionClient:
    """HTTP client for the (not-yet-built) Windows `mt5_bridge`.

    Implements the read-only surface of `ExecutionClient`. `place_order`
    raises `NotImplementedError` unconditionally in Step 2 -- there is no
    order-placement HTTP call implemented, by design.
    """

    def __init__(self, config: RemoteConfig, transport: HttpTransport | None = None) -> None:
        self._config = config
        self._transport = transport if transport is not None else RequestsTransport()

    def __repr__(self) -> str:
        return f"MT5RemoteExecutionClient(config={self._config!r})"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.api_token}", "Accept": "application/json"}

    def _url(self, path: str) -> str:
        return self._config.bridge_url.rstrip("/") + path

    def _get_json(self, path: str, context: str) -> dict[str, Any]:
        response = self._transport.get(self._url(path), headers=self._headers(), timeout=self._config.timeout_seconds)

        if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
            raise ExecutionProtocolError(f"{context}: response exceeded maximum allowed size")

        if response.status_code in (401, 403):
            raise ExecutionAuthenticationError(f"{context}: bridge rejected authentication (HTTP {response.status_code})")
        if 400 <= response.status_code < 500:
            raise ExecutionRequestError(f"{context}: bridge rejected request (HTTP {response.status_code})")
        if response.status_code >= 500:
            raise ExecutionRemoteError(f"{context}: bridge reported a server error (HTTP {response.status_code})")

        import json

        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ExecutionProtocolError(f"{context}: response body is not valid JSON") from exc

        return _require_mapping(payload, context)

    def _post_json(self, path: str, body: dict[str, Any], context: str) -> dict[str, Any]:
        response = self._transport.post(
            self._url(path), headers=self._headers(), timeout=self._config.timeout_seconds, json_body=body
        )

        if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
            raise ExecutionProtocolError(f"{context}: response exceeded maximum allowed size")

        import json

        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            payload = None

        if response.status_code in (401, 403) and (payload is None or "error" not in payload):
            raise ExecutionAuthenticationError(f"{context}: bridge rejected authentication (HTTP {response.status_code})")

        if response.status_code >= 400:
            error_code = "unknown"
            message = f"{context}: bridge rejected request (HTTP {response.status_code})"
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                error_body = payload["error"]
                error_code = str(error_body.get("code", "unknown"))
                message = str(error_body.get("message", message))
            if response.status_code == 401 or error_code == "unauthorized":
                raise ExecutionAuthenticationError(f"{context}: {message}")
            if response.status_code >= 500:
                raise ExecutionRemoteError(f"{context}: {message}")
            raise ExecutionWriteRejectedError(error_code, f"{context}: {message}", response.status_code)

        if payload is None:
            raise ExecutionProtocolError(f"{context}: response body is not valid JSON")

        return _require_mapping(payload, context)

    def _check_api_version(self, api_version: str, context: str) -> None:
        if api_version != self._config.expected_api_version:
            raise ExecutionProtocolError(
                f"{context}: bridge api_version {api_version!r} is incompatible with "
                f"expected {self._config.expected_api_version!r}"
            )

    def health(self) -> HealthStatus:
        payload = self._get_json("/v1/health", "health")
        status, api_version = _parse_health(payload)
        self._check_api_version(api_version, "health")
        return status

    def terminal(self) -> TerminalStatus:
        payload = self._get_json("/v1/terminal", "terminal")
        return _parse_terminal(payload)

    def account(self) -> AccountSummary:
        payload = self._get_json("/v1/account", "account")
        return _parse_account(payload)

    def symbols(self) -> tuple[SymbolSummary, ...]:
        payload = self._get_json("/v1/symbols", "symbols")
        return _parse_symbols(payload)

    def symbol_metadata(self, symbol: str) -> SymbolMetadata:
        safe_symbol = _validate_symbol_for_path(symbol)
        payload = self._get_json(f"/v1/symbols/{safe_symbol}", "symbol_metadata")
        return _parse_symbol_metadata(payload, symbol)

    def quote(self, symbol: str) -> Quote:
        safe_symbol = _validate_symbol_for_path(symbol)
        payload = self._get_json(f"/v1/quotes/{safe_symbol}", "quote")
        return _parse_quote(payload, symbol)

    def positions(self) -> tuple[Position, ...]:
        payload = self._get_json("/v1/positions", "positions")
        return _parse_positions(payload)

    def orders(self) -> tuple[Order, ...]:
        payload = self._get_json("/v1/orders", "orders")
        return _parse_orders(payload)

    def history(self, request: HistoryRequest) -> HistoryResult:
        safe_symbol = _validate_symbol_for_path(request.symbol)
        start = request.start.astimezone(timezone.utc).isoformat()
        end = request.end.astimezone(timezone.utc).isoformat()
        timeframe = request.timeframe.value
        path = (
            f"/v1/history/{safe_symbol}?start={urlquote(start, safe='')}"
            f"&end={urlquote(end, safe='')}&timeframe={urlquote(timeframe, safe='')}"
        )
        payload = self._get_json(path, "history")
        return _parse_history(payload, request.symbol)

    def place_order(self, request: OrderRequest) -> ExecutionResult:
        """POSTs to `/v1/demo/orders` -- the only write endpoint for
        opening/increasing risk. There is no `/v1/live/...` anything for
        this client to ever call; `bridge_url` is entirely the caller's
        responsibility, but the path here is hardcoded to `/v1/demo/...`
        regardless of what `request` contains.
        """

        body = {
            "client_order_id": request.client_order_id,
            "symbol": request.symbol,
            "side": request.side.value,
            "volume": str(request.volume),
        }
        payload = self._post_json("/v1/demo/orders", body, "place_order")
        return _parse_order_result(payload)

    def close_position(self, request: CloseRequest) -> CloseResult:
        safe_position_id = _validate_symbol_for_path(request.position_id)
        body = {"client_order_id": request.client_order_id}
        payload = self._post_json(f"/v1/demo/positions/{safe_position_id}/close", body, "close_position")
        return _parse_close_result(payload)

    def kill_switch_status(self) -> KillSwitchState:
        payload = self._get_json("/v1/kill-switch", "kill_switch_status")
        return _parse_kill_switch_state(payload)

    def activate_kill_switch(self, reason: str | None = None) -> KillSwitchState:
        body = {"reason": reason} if reason is not None else {}
        payload = self._post_json("/v1/kill-switch/activate", body, "activate_kill_switch")
        return _parse_kill_switch_state(payload)

    def deactivate_kill_switch(self) -> KillSwitchState:
        payload = self._post_json("/v1/kill-switch/deactivate", {}, "deactivate_kill_switch")
        return _parse_kill_switch_state(payload)

    def reconciliation_status(self) -> ReconciliationReport:
        payload = self._get_json("/v1/reconciliation", "reconciliation_status")
        return _parse_reconciliation_report(payload)

    def run_reconciliation(self) -> ReconciliationReport:
        payload = self._post_json("/v1/reconciliation/run", {}, "run_reconciliation")
        return _parse_reconciliation_report(payload)

    def resolve_received_attempt(self, client_order_id: str) -> ReconciliationReport:
        if not client_order_id or len(client_order_id) > 128:
            raise ExecutionRequestError("client_order_id is missing or too long")
        safe_id = urlquote(client_order_id, safe="")
        payload = self._post_json(
            f"/v1/reconciliation/resolve-received/{safe_id}",
            {"confirm_abort_before_submission": True},
            "resolve_received_attempt",
        )
        return _parse_reconciliation_report(payload)


    def journal(self, limit: int = 20) -> tuple[JournalEntry, ...]:
        """READ-ONLY operator view of the append-only bridge journal."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("journal limit must be an integer between 1 and 1000")
        payload = self._get_json(f"/v1/journal?limit={limit}", "journal")
        return _parse_journal(payload)

    def profit_calc(
        self, symbol: str, side: Side, volume: Decimal, price_open: Decimal, price_close: Decimal
    ) -> Decimal:
        """READ-ONLY MT5 PnL oracle (Phase 5B, Section 11): calls the
        bridge's `/v1/profit-calc/{symbol}` diagnostic, itself a wrapper
        over `MetaTrader5.order_calc_profit()` -- a pure calculation, not
        an order. Used to compare this project's own PnL formula
        (`src/fx/backtesting/pnl.py`) against MT5's for synthetic
        scenarios; never called from any order-placement path."""
        if volume <= 0:
            raise ValueError(f"volume must be positive, got {volume}")
        if price_open <= 0 or price_close <= 0:
            raise ValueError("price_open/price_close must be positive")
        safe_symbol = _validate_symbol_for_path(symbol)
        path = (
            f"/v1/profit-calc/{safe_symbol}?side={urlquote(side.value, safe='')}"
            f"&volume={urlquote(str(volume), safe='')}"
            f"&price_open={urlquote(str(price_open), safe='')}"
            f"&price_close={urlquote(str(price_close), safe='')}"
        )
        payload = self._get_json(path, "profit_calc")
        return _parse_decimal(_require_field(payload, "profit", "profit_calc"), "profit_calc.profit")

    def time_diagnostics(self, symbol: str) -> TimeDiagnostics:
        """READ-ONLY. Never calls order_check/order_send. Captures this
        process's own clock as close as possible to the HTTP call, so the
        reported skew reflects actual clock difference rather than
        request/parsing overhead."""

        linux_client_utc = datetime.now(timezone.utc)
        payload = self._get_json(f"/v1/time-diagnostics/{symbol}", "time_diagnostics")
        return _parse_time_diagnostics(payload, symbol, linux_client_utc)
