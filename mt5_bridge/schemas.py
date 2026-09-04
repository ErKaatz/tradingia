"""JSON response shaping for the bridge (FX Phase 0, Step 3).

These functions build plain dicts matching exactly what
`src/execution/mt5_remote.py` (Step 2) parses. All monetary/price/volume
values are emitted as strings (never JSON floats) to preserve precision
across the wire, matching Step 2's `_parse_decimal(str(value))` pattern.

`environment` here is a bridge-computed, best-effort classification --
NOT the same authority as Step 1's policy checks. See
`classify_environment` for exactly what evidence is required before this
module will say "demo", and note that even this bridge-level DEMO claim
still has to independently pass through Step 1's `authorize_open`, which
also requires the remote-confirmed account trade mode to say demo. This
bridge computing "demo" is one input to that decision, not a bypass of it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mt5_bridge.backend import (
    BackendAccountInfo,
    BackendBar,
    BackendOrder,
    BackendPosition,
    BackendSymbolInfo,
    BackendTerminalInfo,
    BackendTick,
    trade_mode_code_to_string,
)

API_VERSION = "1"


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def classify_environment(account: BackendAccountInfo) -> str:
    """Best-effort environment classification from account fields alone.

    Only `trade_mode_code == 0` (MT5's ACCOUNT_TRADE_MODE_DEMO) is
    treated as a positive, reportable "demo" signal here -- this is the
    same authoritative field `trade_mode` itself is derived from, not an
    independent confirmation, so this function intentionally does NOT
    also report "demo" for e.g. a server name containing "Demo": that
    would be a second claim built on the same weak signal, giving a
    false sense of two independent checks agreeing. If MT5 does not
    report a recognized trade_mode code, this returns "unknown" -- never
    "demo" by default.
    """

    trade_mode = trade_mode_code_to_string(account.trade_mode_code)
    if trade_mode == "demo":
        return "demo"
    if trade_mode == "live":
        return "live"
    return "unknown"


def health_response(
    *,
    bridge_alive: bool,
    terminal_connected: bool,
    server_time_utc: datetime | None,
    broker_name: str | None,
    bridge_version: str | None = None,
    bridge_build: str | None = None,
    bridge_time_utc: datetime | None = None,
) -> dict:
    """`bridge_version`/`bridge_build` exist specifically so a quick
    `GET /v1/health` can confirm the VM is actually running the code you
    think it is -- see FX_PHASE0_STATUS.md's Step 3.1 follow-up, where a
    stale `mt5_bridge/` deployment on the VM looked exactly like a code
    bug until this was added.

    `bridge_time_utc` is this Windows process's own
    `datetime.now(timezone.utc)` at response time -- the bridge machine's
    wall clock, nothing else. It is deliberately named and documented
    apart from `server_time` (MT5's own reported trade-server time, which
    the FakeMT5Backend/RealMT5Backend `server_time_utc()` populates and
    which is `None` on the real backend today -- see backend.py) and apart
    from a tick's own timestamp (`mt5_tick_time_utc`, symbol-specific,
    reported by /v1/quotes/{symbol}). Conflating these three clocks is
    exactly what caused the original "quote has a timestamp in the
    future" investigation -- keep them named distinctly everywhere.
    """

    return {
        "api_version": API_VERSION,
        "bridge_alive": bridge_alive,
        "terminal_connected": terminal_connected,
        "server_time": _iso_utc(server_time_utc) if server_time_utc is not None else None,
        "broker_name": broker_name,
        "bridge_version": bridge_version,
        "bridge_build": bridge_build,
        "bridge_time_utc": _iso_utc(bridge_time_utc) if bridge_time_utc is not None else None,
    }


def terminal_response(info: BackendTerminalInfo) -> dict:
    return {
        "connected": info.connected,
        "trade_allowed": info.trade_allowed,
        "dlls_allowed": info.dlls_allowed,
        "name": info.name,
        "company": info.company,
        "build": info.build,
    }


def account_response(info: BackendAccountInfo) -> dict:
    """`balance`/`equity`/`margin`/`margin_free` are emitted as `str(Decimal)`
    with no imposed decimal-place count. `info.*` are already clean
    `Decimal` values by the time they reach here (see
    `RealMT5Backend.account_info`, which runs them through
    `clean_decimal`) -- this used to `format(value, ".2f")`, which both
    reintroduced float rounding on top of an already-float value AND
    arbitrarily truncated any real precision MT5 provided beyond 2
    decimal places. Neither is done anymore.
    """

    trade_mode = trade_mode_code_to_string(info.trade_mode_code)
    environment = classify_environment(info)
    return {
        "account_id": str(info.login),
        "trade_mode": trade_mode,
        "environment": environment,
        "server": info.server,
        "currency": info.currency,
        "balance": str(info.balance) if info.balance is not None else None,
        "equity": str(info.equity) if info.equity is not None else None,
        "margin": str(info.margin) if info.margin is not None else None,
        "free_margin": str(info.margin_free) if info.margin_free is not None else None,
        "trade_allowed": info.trade_allowed,
        "trade_expert": info.trade_expert,
    }


def symbol_response(info: BackendSymbolInfo) -> dict:
    return {
        "symbol": info.name,
        "description": info.description,
        "digits": info.digits,
        "point": str(info.point),
        "volume_min": str(info.volume_min),
        "volume_step": str(info.volume_step),
        "volume_max": str(info.volume_max),
        "trade_contract_size": str(info.trade_contract_size),
        "trade_tick_size": str(info.trade_tick_size) if info.trade_tick_size is not None else None,
        "trade_tick_value": str(info.trade_tick_value) if info.trade_tick_value is not None else None,
        "trade_enabled": info.trade_enabled,
        "visible": info.visible,
        "currency_base": info.currency_base,
        "currency_profit": info.currency_profit,
        "currency_margin": info.currency_margin,
    }


def symbol_summary_response(info: BackendSymbolInfo) -> dict:
    """Lightweight listing entry for `GET /v1/symbols` -- deliberately
    just `symbol`, `description`, `visible`, `trade_enabled`. The full
    `symbol_response` above (with volume_min/step/max, digits, point,
    etc.) stays behind `GET /v1/symbols/{symbol}`, requested once a
    caller already knows the exact name to trade -- listing all symbols
    with that much per-symbol detail would be a heavier call than this
    endpoint's discovery purpose needs.
    """

    return {
        "symbol": info.name,
        "description": info.description,
        "visible": info.visible,
        "trade_enabled": info.trade_enabled,
    }


def symbols_response(infos: list[BackendSymbolInfo]) -> dict:
    return {"symbols": [symbol_summary_response(info) for info in infos]}


def quote_response(tick: BackendTick) -> dict:
    return {
        "symbol": tick.symbol,
        "timestamp": _iso_utc(tick.time_utc),
        "bid": str(tick.bid),
        "ask": str(tick.ask),
    }


def time_diagnostics_response(
    *,
    symbol: str,
    bridge_time_utc: datetime,
    mt5_tick_time_utc: datetime | None,
    quote_age_seconds: float | None,
    quote_future_skew_seconds: float | None,
    server_clock_offset_seconds: float | None = None,
) -> dict:
    """Read-only clock-diagnostic payload -- no order_check, no
    order_send, never touches MT5's write path. Exists specifically to
    let a human distinguish clock skew (Linux vs bridge vs MT5 tick) from
    a code bug, per the FX Phase 0 "quote has a timestamp in the future"
    investigation -- see mt5_bridge/quote_freshness.py.

    `server_clock_offset_seconds` is the auto-calibrated broker-server-
    clock correction currently being subtracted from every raw MT5 tick/
    bar timestamp (see mt5_bridge/server_clock.py) -- `None` if not yet
    calibrated (no tick read yet). `mt5_tick_time_utc` here is already
    the CORRECTED value (post-offset), so once calibrated this should
    show a near-zero `quote_age_seconds`/`quote_future_skew_seconds` even
    though the broker's raw clock is offset by hours.
    """

    return {
        "symbol": symbol,
        "bridge_time_utc": _iso_utc(bridge_time_utc),
        "mt5_tick_time_utc": _iso_utc(mt5_tick_time_utc) if mt5_tick_time_utc is not None else None,
        "quote_age_seconds": quote_age_seconds,
        "quote_future_skew_seconds": quote_future_skew_seconds,
        "server_clock_offset_seconds": server_clock_offset_seconds,
    }


def history_bar_response(bar: BackendBar) -> dict:
    return {
        "timestamp": _iso_utc(bar.time_utc),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "tick_volume": str(bar.tick_volume),
        "spread": bar.spread,
        "real_volume": str(bar.real_volume) if bar.real_volume is not None else None,
    }


def history_response(bars: list[BackendBar]) -> dict:
    return {"bars": [history_bar_response(b) for b in bars]}


def profit_calc_response(symbol: str, side: str, volume, price_open, price_close, profit) -> dict:
    """`side` is the human-readable `"buy"`/`"sell"` string (never MT5's
    raw integer order_type) -- consistent with every other side field
    this bridge already exposes (see `position_response`/`order_response`)."""
    return {
        "symbol": symbol,
        "side": side,
        "volume": str(volume),
        "price_open": str(price_open),
        "price_close": str(price_close),
        "profit": str(profit),
    }


def position_response(position: BackendPosition) -> dict:
    return {
        "position_id": str(position.ticket),
        "symbol": position.symbol,
        "side": position.side,
        "volume": str(position.volume),
        "open_price": str(position.price_open),
    }


def positions_response(positions: list[BackendPosition]) -> dict:
    return {"positions": [position_response(p) for p in positions]}


def order_response(order: BackendOrder) -> dict:
    """Maps a bridge-visible MT5 order to the Step-2 `Order` shape.

    `Order.client_order_id` is `str | None` specifically for this case:
    Step 3 never places orders (read-only), so EVERY order this bridge
    can currently see was placed manually or by another EA -- none of
    them can honestly carry a TradingIA client_order_id. This always
    reports `None` here, never a synthesized value derived from the MT5
    ticket (that was an earlier, incorrect design -- see
    src/execution/base.py::Order's docstring). `broker_order_id` still
    carries the real MT5 ticket.

    A future write-enabled step that places orders with our own
    client_order_id encoded in MT5's `comment` field (the only per-order
    field MT5 lets a caller set freely) could recover it from
    `order.comment` here -- deliberately not attempted yet, since no
    code path writes that comment today and guessing at a convention
    that doesn't exist yet would be exactly the kind of invented-identity
    this correction was about avoiding.
    """

    return {
        "client_order_id": None,
        "symbol": order.symbol,
        "side": order.side,
        "volume": str(order.volume_initial),
        "status": "accepted",
        "broker_order_id": str(order.ticket),
    }


def orders_response(orders: list[BackendOrder]) -> dict:
    return {"orders": [order_response(o) for o in orders]}


def demo_order_result_response(result) -> dict:
    """`result` is a `mt5_bridge.trading.DemoOrderResult`. All Decimal
    fields as strings; `timestamp` as ISO-8601 UTC.
    """

    return {
        "client_order_id": result.client_order_id,
        "status": result.status,
        "broker_order_id": result.broker_order_id,
        "deal_id": result.deal_id,
        "position_id": result.position_id,
        "requested_volume": str(result.requested_volume),
        "filled_volume": str(result.filled_volume) if result.filled_volume is not None else None,
        "observed_bid": str(result.observed_bid),
        "observed_ask": str(result.observed_ask),
        "reference_price": str(result.reference_price),
        "fill_price": str(result.fill_price) if result.fill_price is not None else None,
        "slippage": str(result.slippage) if result.slippage is not None else None,
        "mt5_retcode": result.mt5_retcode,
        "timestamp": _iso_utc(result.timestamp),
        "idempotent_replay": result.idempotent_replay,
        "error_message": result.error_message,
    }


def demo_close_result_response(result) -> dict:
    """`result` is a `mt5_bridge.trading.DemoCloseResult`."""

    return {
        "client_order_id": result.client_order_id,
        "position_id": result.position_id,
        "status": result.status,
        "closed_volume": str(result.closed_volume) if result.closed_volume is not None else None,
        "observed_bid": str(result.observed_bid),
        "observed_ask": str(result.observed_ask),
        "reference_price": str(result.reference_price),
        "fill_price": str(result.fill_price) if result.fill_price is not None else None,
        "slippage": str(result.slippage) if result.slippage is not None else None,
        "deal_id": result.deal_id,
        "mt5_retcode": result.mt5_retcode,
        "timestamp": _iso_utc(result.timestamp),
        "idempotent_replay": result.idempotent_replay,
        "error_message": result.error_message,
    }


def kill_switch_response(status: str, changed_at, reason: str | None) -> dict:
    return {"status": status, "changed_at": _iso_utc(changed_at), "reason": reason}


def reconciliation_response(report) -> dict:
    return {
        "state": report.state.value,
        "checked_at": _iso_utc(report.checked_at),
        "details": list(report.details),
    }


def journal_response(entries: list[dict]) -> dict:
    return {"entries": entries}
