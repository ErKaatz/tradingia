"""MT5 backend boundary (FX Phase 0, Step 3).

This is the ONLY place in `mt5_bridge` allowed to import the real
`MetaTrader5` package, and it does so lazily (inside `RealMT5Backend`,
not at module import time) so that importing this module on Linux (for
tests, or for `mt5_bridge`'s own unit tests) never requires MetaTrader5
to be installed.

`MT5Backend` is a `Protocol` describing exactly the read-only MT5 calls
the bridge needs. `FakeMT5Backend` is a fully in-memory implementation
used by every test in this package except the (separately gated,
Windows-only) smoke script. `RealMT5Backend` wraps the actual
`MetaTrader5` module.

All values returned by backend methods are plain Python
types/dataclasses defined here -- NOT raw `MetaTrader5` named tuples --
so the FastAPI layer (`app.py`) never has to know whether it's talking
to the real terminal or a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from mt5_bridge.quantize import clean_decimal, quantize_price, quantize_volume
from mt5_bridge.server_clock import ServerClockCalibrationError, ServerClockOffset


# --------------------------------------------------------------------------
# trade_mode mapping -- single source of truth
# --------------------------------------------------------------------------

# MetaTrader5's ACCOUNT_TRADE_MODE_* constants are plain integers:
#   ACCOUNT_TRADE_MODE_DEMO = 0
#   ACCOUNT_TRADE_MODE_CONTEST = 1
#   ACCOUNT_TRADE_MODE_REAL = 2
# Documented here (not guessed inline at the call site) specifically so
# there is exactly one place this mapping can be audited or corrected.
# Any value not in this table maps to "unknown", never to "demo".
MT5_TRADE_MODE_BY_CODE: dict[int, str] = {
    0: "demo",
    1: "contest",
    2: "live",
}


def trade_mode_code_to_string(code: int | None) -> str:
    if code is None:
        return "unknown"
    return MT5_TRADE_MODE_BY_CODE.get(code, "unknown")


# --------------------------------------------------------------------------
# Backend-level plain data types (already backend-agnostic)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendTerminalInfo:
    connected: bool
    trade_allowed: bool
    dlls_allowed: bool | None
    name: str | None
    company: str | None
    build: int | None


@dataclass(frozen=True)
class BackendAccountInfo:
    """`balance`/`equity`/`margin`/`margin_free` are `Decimal`, cleaned of
    binary float noise via `clean_decimal` at construction time (no fixed
    number of decimal places imposed -- see `mt5_bridge/quantize.py`).
    """

    login: int
    trade_mode_code: int | None
    server: str | None
    currency: str | None
    balance: Decimal | None
    equity: Decimal | None
    margin: Decimal | None
    margin_free: Decimal | None
    trade_allowed: bool | None = None
    trade_expert: bool | None = None


@dataclass(frozen=True)
class BackendSymbolInfo:
    """`point`/`volume_min`/`volume_step`/`volume_max`/`trade_contract_size`/
    `trade_tick_size`/`trade_tick_value` are `Decimal`, cleaned via
    `clean_decimal` at construction time.

    `trade_enabled` reflects MT5's `SymbolInfo.trade_mode` correctly
    (Step 4 correction -- see `SYMBOL_TRADE_MODE_FULL` below): a symbol
    is tradeable only when `trade_mode == SYMBOL_TRADE_MODE_FULL` (4).
    The earlier Step 3 code treated any nonzero `trade_mode` as
    "enabled", which is wrong -- `trade_mode` values 1 (long-only) and 2
    (short-only) are also nonzero but restrict trading, and 3
    (close-only) forbids new entries entirely. `filling_mode` is MT5's
    own bitmask of which order-filling policies (FOK/IOC/RETURN) the
    symbol supports; Step 4's order construction reads it directly
    rather than hardcoding one filling policy for every symbol/broker.
    """

    name: str
    description: str | None
    digits: int
    point: Decimal
    volume_min: Decimal
    volume_step: Decimal
    volume_max: Decimal
    trade_contract_size: Decimal
    trade_tick_size: Decimal | None
    trade_tick_value: Decimal | None
    trade_enabled: bool | None
    visible: bool
    filling_mode: int | None = None
    currency_base: str | None = None
    currency_profit: str | None = None
    currency_margin: str | None = None


@dataclass(frozen=True)
class BackendTick:
    """`bid`/`ask` are `Decimal`, already quantized to the symbol's
    `digits` at construction time (see `RealMT5Backend.symbol_info_tick`,
    which is the only place with both the raw MT5 tick and the symbol's
    digits available at the same time).
    """

    symbol: str
    time_utc: datetime
    bid: Decimal
    ask: Decimal


@dataclass(frozen=True)
class BackendBar:
    """`open`/`high`/`low`/`close` are `Decimal`, quantized to the
    symbol's digits. `tick_volume`/`real_volume` are `Decimal` too but
    cleaned via `clean_decimal` only -- they are counts, not prices, and
    must never be quantized with a symbol's price digits (see
    `mt5_bridge/quantize.py` module docstring).
    """

    time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: Decimal
    spread: int | None
    real_volume: Decimal | None


@dataclass(frozen=True)
class BackendPosition:
    ticket: int
    symbol: str
    side: str  # "buy" | "sell"
    volume: Decimal
    price_open: Decimal
    magic: int | None = None
    comment: str | None = None


@dataclass(frozen=True)
class BackendOrder:
    ticket: int
    symbol: str
    side: str  # "buy" | "sell"
    volume_initial: Decimal
    comment: str | None
    magic: int | None = None


# --------------------------------------------------------------------------
# Trading (Step 4) -- MARKET orders only, no pending/stop/limit orders
# --------------------------------------------------------------------------

# MT5 constants documented here (not guessed inline) so this is the one
# place to audit/correct them. These are stable, publicly documented
# values from the MetaTrader5 Python package's own module-level
# constants (mt5.TRADE_ACTION_DEAL, mt5.ORDER_TYPE_BUY, etc.) -- the
# integers below are only used for the *fake* backend and for
# documentation; `RealMT5Backend` always reads the real constant off the
# `MetaTrader5` module itself (e.g. `self._mt5.TRADE_ACTION_DEAL`),
# never a hardcoded integer, so a version difference in the real package
# cannot silently desync from what's documented here.
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TIME_GTC = 0
# SymbolInfo.trade_mode (0=disabled,1=long-only,2=short-only,3=close-only,4=full)
SYMBOL_TRADE_MODE_DISABLED = 0
SYMBOL_TRADE_MODE_LONGONLY = 1
SYMBOL_TRADE_MODE_SHORTONLY = 2
SYMBOL_TRADE_MODE_CLOSEONLY = 3
SYMBOL_TRADE_MODE_FULL = 4
# SymbolInfo.filling_mode bitmask (SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2)
SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
# ORDER_FILLING_* values used in the actual trade request
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
# TRADE_RETCODE_DONE -- the only retcode this bridge treats as a genuine fill
TRADE_RETCODE_DONE = 10009


def resolve_order_filling_mode(symbol_filling_mode: int | None) -> int:
    """Maps a symbol's `filling_mode` bitmask to the single filling
    policy to put in a trade request. FOK is preferred when the symbol
    supports it (most conservative: fill completely or not at all, no
    partial fills to reconcile); IOC next; ORDER_FILLING_RETURN only if
    neither bit is set (some brokers report 0 and only support RETURN).
    Never guesses past what the symbol itself reports.
    """

    if symbol_filling_mode is None:
        raise MT5BackendError("symbol filling_mode is unknown; cannot safely choose an order filling policy")
    if symbol_filling_mode & SYMBOL_FILLING_FOK:
        return ORDER_FILLING_FOK
    if symbol_filling_mode & SYMBOL_FILLING_IOC:
        return ORDER_FILLING_IOC
    return ORDER_FILLING_RETURN


@dataclass(frozen=True)
class TradeRequest:
    """The fields Step 4 actually needs for a MARKET order -- a small,
    explicit subset of MT5's full `TradeRequest` structure (no pending
    orders, no stop/limit, no partial-fill bracket logic).
    """

    symbol: str
    volume: Decimal
    order_type: int  # ORDER_TYPE_BUY or ORDER_TYPE_SELL
    price: Decimal
    deviation: int
    magic: int
    comment: str
    position_ticket: int | None = None  # set when closing a specific position


@dataclass(frozen=True)
class TradeCheckResult:
    ok: bool
    retcode: int | None
    comment: str | None


@dataclass(frozen=True)
class TradeSendResult:
    retcode: int
    deal: int | None
    order: int | None
    volume: Decimal | None
    price: Decimal | None
    comment: str | None


class MT5BackendError(Exception):
    """Raised by a backend when MT5 itself reports failure for a call
    that should otherwise have succeeded (e.g. `symbol_info` returns
    `None`, `copy_rates_range` returns `None`). Never wraps a raw
    MetaTrader5 exception type so callers don't need that import either.
    """


class MT5Backend(Protocol):
    """Structural interface the bridge's HTTP layer depends on. Both
    `RealMT5Backend` (imports MetaTrader5) and `FakeMT5Backend` (pure
    Python, for tests) satisfy this shape.
    """

    def is_connected(self) -> bool: ...

    def terminal_info(self) -> BackendTerminalInfo: ...

    def account_info(self) -> BackendAccountInfo: ...

    def server_time_utc(self) -> datetime | None: ...

    def symbols_get(self) -> list[BackendSymbolInfo]: ...

    def symbol_info(self, symbol: str) -> BackendSymbolInfo | None: ...

    def symbol_info_tick(self, symbol: str) -> BackendTick | None: ...

    def copy_rates_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[BackendBar]: ...

    def positions_get(self) -> list[BackendPosition]: ...

    def orders_get(self) -> list[BackendOrder]: ...

    def server_clock_offset_seconds(self) -> float | None: ...

    def order_check(self, request: TradeRequest) -> TradeCheckResult: ...

    def order_send(self, request: TradeRequest) -> TradeSendResult: ...


# --------------------------------------------------------------------------
# Fake backend (Linux-safe, used by nearly every test in this package)
# --------------------------------------------------------------------------


class FakeMT5Backend:
    """In-memory `MT5Backend` for tests. Every field is settable directly
    so a test can construct exactly the scenario it needs (disconnected
    terminal, missing tick, malformed symbol, ...).
    """

    def __init__(self) -> None:
        self.connected: bool = True
        self.terminal: BackendTerminalInfo | None = BackendTerminalInfo(
            connected=True, trade_allowed=True, dlls_allowed=False, name="MetaTrader 5", company="Fake Broker", build=1
        )
        self.account: BackendAccountInfo | None = BackendAccountInfo(
            login=12345,
            trade_mode_code=0,
            server="FakeBroker-Demo",
            currency="USD",
            balance=Decimal("1000.00"),
            equity=Decimal("1000.00"),
            margin=Decimal("0"),
            margin_free=Decimal("1000.00"),
            trade_allowed=True,
            trade_expert=True,
        )
        self._server_time: datetime | None = None
        self._symbols: dict[str, BackendSymbolInfo] = {}
        self._ticks: dict[str, BackendTick] = {}
        self._bars: dict[str, list[BackendBar]] = {}
        self._positions: list[BackendPosition] = []
        self._orders: list[BackendOrder] = []
        self.raise_on_rates: bool = False
        self.raise_on_symbols_get: bool = False
        self.__post_init_trading__()

    def is_connected(self) -> bool:
        return self.connected

    def terminal_info(self) -> BackendTerminalInfo:
        if self.terminal is None:
            raise MT5BackendError("terminal_info unavailable")
        return self.terminal

    def account_info(self) -> BackendAccountInfo:
        if self.account is None:
            raise MT5BackendError("account_info unavailable")
        return self.account

    def server_time_utc(self) -> datetime | None:
        return self._server_time

    def set_server_time(self, value: datetime | None) -> None:
        self._server_time = value

    def set_symbol(self, symbol: str, info: BackendSymbolInfo) -> None:
        self._symbols[symbol] = info

    def symbol_info(self, symbol: str) -> BackendSymbolInfo | None:
        return self._symbols.get(symbol)

    def symbols_get(self) -> list[BackendSymbolInfo]:
        if self.raise_on_symbols_get:
            raise MT5BackendError("symbols_get failed")
        return list(self._symbols.values())

    def set_tick(self, symbol: str, tick: BackendTick) -> None:
        self._ticks[symbol] = tick

    def symbol_info_tick(self, symbol: str) -> BackendTick | None:
        return self._ticks.get(symbol)

    def set_bars(self, symbol: str, bars: list[BackendBar]) -> None:
        self._bars[symbol] = bars

    def copy_rates_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[BackendBar]:
        if self.raise_on_rates:
            raise MT5BackendError("copy_rates_range failed")
        bars = self._bars.get(symbol, [])
        return [b for b in bars if start <= b.time_utc <= end]

    def set_positions(self, positions: list[BackendPosition]) -> None:
        self._positions = positions

    def positions_get(self) -> list[BackendPosition]:
        return list(self._positions)

    def set_orders(self, orders: list[BackendOrder]) -> None:
        self._orders = orders

    def orders_get(self) -> list[BackendOrder]:
        return list(self._orders)

    def server_clock_offset_seconds(self) -> float | None:
        # FakeMT5Backend's ticks are constructed with correct UTC
        # timestamps directly (see BackendTick usages across tests) --
        # there is no server-local-time mislabeling to correct here.
        return 0.0

    # ---------------------------------------------------------------- trading (Step 4)
    #
    # Controllable via plain attributes so a test can simulate exactly one
    # scenario per instance:
    #   order_check_should_fail   -> order_check() returns ok=False
    #   order_send_retcode        -> the retcode order_send() reports
    #   order_send_should_raise   -> order_send() raises (simulates a
    #                                 network/process crash between send
    #                                 and the bridge recording FILLED)
    #   next_ticket / next_deal   -> deterministic IDs for assertions

    def __post_init_trading__(self) -> None:
        self.order_check_should_fail: bool = False
        self.order_check_retcode: int | None = None
        self.order_send_should_raise: bool = False
        self.order_send_retcode: int = TRADE_RETCODE_DONE
        self.next_ticket: int = 1000
        self.next_deal: int = 5000

    def order_check(self, request: TradeRequest) -> TradeCheckResult:
        if self.order_check_should_fail:
            return TradeCheckResult(ok=False, retcode=self.order_check_retcode or 10004, comment="fake: order_check rejected")
        return TradeCheckResult(ok=True, retcode=0, comment="fake: order_check passed")

    def order_send(self, request: TradeRequest) -> TradeSendResult:
        if self.order_send_should_raise:
            raise MT5BackendError("fake: simulated crash during order_send")
        if self.order_send_retcode != TRADE_RETCODE_DONE:
            return TradeSendResult(
                retcode=self.order_send_retcode, deal=None, order=None, volume=None, price=None,
                comment="fake: order_send did not complete",
            )
        ticket = self.next_ticket
        deal = self.next_deal
        self.next_ticket += 1
        self.next_deal += 1
        side = "buy" if request.order_type == ORDER_TYPE_BUY else "sell"
        if request.position_ticket is None:
            # opening a new position
            self._positions.append(
                BackendPosition(
                    ticket=ticket, symbol=request.symbol, side=side, volume=request.volume,
                    price_open=request.price, magic=request.magic, comment=request.comment,
                )
            )
        else:
            # closing: remove the matching position
            self._positions = [p for p in self._positions if p.ticket != request.position_ticket]
        return TradeSendResult(
            retcode=TRADE_RETCODE_DONE, deal=deal, order=ticket, volume=request.volume, price=request.price,
            comment="fake: order_send filled",
        )


# --------------------------------------------------------------------------
# Real backend -- imports MetaTrader5 lazily, Windows-only in practice
# --------------------------------------------------------------------------


class RealMT5Backend:
    """Wraps the actual `MetaTrader5` package. Only usable where that
    package is installed (the Windows VM). Import is deferred to
    `__init__`/`connect` so this module stays importable on Linux.
    """

    def __init__(self, terminal_path: str | None = None) -> None:
        import MetaTrader5 as mt5  # noqa: N813 -- matches the package's own convention

        self._mt5 = mt5
        self._terminal_path = terminal_path
        self._connected = False
        # Ticks/bars carry the trade server's own clock, not UTC (see
        # mt5_bridge/server_clock.py) -- one offset for the whole
        # terminal session, auto-calibrated from the first tick read and
        # re-calibrated if it drifts (e.g. a DST transition).
        self._server_clock = ServerClockOffset()

    def connect(self) -> bool:
        if self._terminal_path:
            self._connected = bool(self._mt5.initialize(path=self._terminal_path))
        else:
            self._connected = bool(self._mt5.initialize())
        return self._connected

    def shutdown(self) -> None:
        self._mt5.shutdown()
        self._connected = False

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        return self._mt5.terminal_info() is not None

    def terminal_info(self) -> BackendTerminalInfo:
        info = self._mt5.terminal_info()
        if info is None:
            raise MT5BackendError("MetaTrader5.terminal_info() returned None")
        return BackendTerminalInfo(
            connected=bool(info.connected),
            trade_allowed=bool(info.trade_allowed),
            dlls_allowed=bool(getattr(info, "dlls_allowed", False)),
            name=getattr(info, "name", None),
            company=getattr(info, "company", None),
            build=getattr(info, "build", None),
        )

    def account_info(self) -> BackendAccountInfo:
        info = self._mt5.account_info()
        if info is None:
            raise MT5BackendError("MetaTrader5.account_info() returned None")

        def _clean_or_none(value) -> Decimal | None:
            return clean_decimal(float(value)) if value is not None else None

        return BackendAccountInfo(
            login=int(info.login),
            trade_mode_code=getattr(info, "trade_mode", None),
            server=getattr(info, "server", None),
            currency=getattr(info, "currency", None),
            balance=_clean_or_none(getattr(info, "balance", None)),
            equity=_clean_or_none(getattr(info, "equity", None)),
            margin=_clean_or_none(getattr(info, "margin", None)),
            margin_free=_clean_or_none(getattr(info, "margin_free", None)),
            trade_allowed=(bool(info.trade_allowed) if hasattr(info, "trade_allowed") else None),
            trade_expert=(bool(info.trade_expert) if hasattr(info, "trade_expert") else None),
        )

    def server_time_utc(self) -> datetime | None:
        # MetaTrader5's terminal_info()/account_info() carry no server-clock
        # field; the only server-time signal available is a tick's own
        # `time`, which is symbol-specific, not a terminal-wide clock.
        # Left None deliberately rather than approximating with the local
        # machine's clock -- see mt5_bridge/README.md.
        return None

    def symbol_info(self, symbol: str) -> BackendSymbolInfo | None:
        info = self._mt5.symbol_info(symbol)
        if info is None:
            return None
        return _mt5_symbol_info_to_backend(info)

    def symbols_get(self) -> list[BackendSymbolInfo]:
        infos = self._mt5.symbols_get()
        if infos is None:
            raise MT5BackendError("MetaTrader5.symbols_get() returned None")
        return [_mt5_symbol_info_to_backend(info) for info in infos]

    def _symbol_digits(self, symbol: str) -> int:
        info = self._mt5.symbol_info(symbol)
        if info is None:
            raise MT5BackendError(f"MetaTrader5.symbol_info({symbol!r}) returned None; cannot determine price digits")
        return int(info.digits)

    def symbol_info_tick(self, symbol: str) -> BackendTick | None:
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        digits = self._symbol_digits(symbol)
        raw_time = datetime.fromtimestamp(tick.time, tz=_utc())
        try:
            time_utc = self._server_clock.to_utc(raw_time)
        except ServerClockCalibrationError as exc:
            raise MT5BackendError(str(exc)) from exc
        return BackendTick(
            symbol=symbol,
            time_utc=time_utc,
            bid=quantize_price(float(tick.bid), digits, context=f"{symbol} tick.bid"),
            ask=quantize_price(float(tick.ask), digits, context=f"{symbol} tick.ask"),
        )

    def copy_rates_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[BackendBar]:
        mt5_timeframe = MT5_TIMEFRAME_ATTR_BY_NAME.get(timeframe)
        if mt5_timeframe is None:
            raise MT5BackendError(f"unsupported timeframe {timeframe!r}")
        tf_value = getattr(self._mt5, mt5_timeframe)
        rates = self._mt5.copy_rates_range(symbol, tf_value, start, end)
        if rates is None:
            raise MT5BackendError(f"MetaTrader5.copy_rates_range returned None for {symbol}")
        digits = self._symbol_digits(symbol)
        # MetaQuotes documents copy_rates_range() timestamps as UTC.  Do NOT
        # apply the live tick-clock calibration here: today's offset can differ
        # from a historical bar's offset across DST/server-time changes, which
        # would silently corrupt research timestamps.  HFM history semantics
        # will be validated independently before any broker-specific correction.
        bars = []
        for r in rates:
            time_utc = datetime.fromtimestamp(r["time"], tz=_utc())
            bars.append(
                BackendBar(
                    time_utc=time_utc,
                    open=quantize_price(float(r["open"]), digits, context=f"{symbol} bar.open"),
                    high=quantize_price(float(r["high"]), digits, context=f"{symbol} bar.high"),
                    low=quantize_price(float(r["low"]), digits, context=f"{symbol} bar.low"),
                    close=quantize_price(float(r["close"]), digits, context=f"{symbol} bar.close"),
                    tick_volume=clean_decimal(float(r["tick_volume"])),
                    spread=int(r["spread"]) if "spread" in r.dtype.names else None,
                    real_volume=clean_decimal(float(r["real_volume"])) if "real_volume" in r.dtype.names else None,
                )
            )
        return bars

    def positions_get(self) -> list[BackendPosition]:
        positions = self._mt5.positions_get()
        if positions is None:
            return []
        result = []
        for p in positions:
            side = "buy" if p.type == 0 else "sell"
            digits = self._symbol_digits(p.symbol)
            result.append(
                BackendPosition(
                    ticket=int(p.ticket),
                    symbol=p.symbol,
                    side=side,
                    volume=clean_decimal(float(p.volume)),
                    price_open=quantize_price(float(p.price_open), digits, context=f"{p.symbol} position.price_open"),
                )
            )
        return result

    def orders_get(self) -> list[BackendOrder]:
        orders = self._mt5.orders_get()
        if orders is None:
            return []
        result = []
        for o in orders:
            side = "buy" if o.type in (0, 2, 4) else "sell"
            result.append(
                BackendOrder(
                    ticket=int(o.ticket),
                    symbol=o.symbol,
                    side=side,
                    volume_initial=clean_decimal(float(o.volume_initial)),
                    comment=getattr(o, "comment", None),
                )
            )
        return result

    def server_clock_offset_seconds(self) -> float | None:
        """The currently calibrated broker-server-clock offset (seconds
        to SUBTRACT from a raw MT5 timestamp to get true UTC), or `None`
        if no tick has been read yet to calibrate it. Exposed purely for
        diagnostics (`GET /v1/time-diagnostics/{symbol}`) -- see
        mt5_bridge/server_clock.py.
        """

        offset = self._server_clock.current_offset()
        return offset.total_seconds() if offset is not None else None

    def _build_mt5_request(self, request: TradeRequest) -> dict:
        """Builds MT5's `order_send`/`order_check` request dict, reading
        every enum-like value off the real `MetaTrader5` module (never a
        hardcoded integer) so a version difference in the installed
        package cannot silently desync from what this bridge sends.
        """

        mt5_order_type = self._mt5.ORDER_TYPE_BUY if request.order_type == ORDER_TYPE_BUY else self._mt5.ORDER_TYPE_SELL
        symbol_info = self._mt5.symbol_info(request.symbol)
        if symbol_info is None:
            raise MT5BackendError(f"symbol_info({request.symbol!r}) returned None; cannot build trade request")
        filling_choice = resolve_order_filling_mode(getattr(symbol_info, "filling_mode", None))
        mt5_filling = {
            ORDER_FILLING_FOK: self._mt5.ORDER_FILLING_FOK,
            ORDER_FILLING_IOC: self._mt5.ORDER_FILLING_IOC,
            ORDER_FILLING_RETURN: self._mt5.ORDER_FILLING_RETURN,
        }[filling_choice]

        req = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": request.symbol,
            "volume": float(request.volume),
            "type": mt5_order_type,
            "price": float(request.price),
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": mt5_filling,
        }
        if request.position_ticket is not None:
            req["position"] = request.position_ticket
        return req

    def order_check(self, request: TradeRequest) -> TradeCheckResult:
        mt5_request = self._build_mt5_request(request)
        result = self._mt5.order_check(mt5_request)
        if result is None:
            raise MT5BackendError("MetaTrader5.order_check() returned None")
        retcode = int(result.retcode)
        ok = retcode == self._mt5.TRADE_RETCODE_DONE or retcode == 0
        return TradeCheckResult(ok=ok, retcode=retcode, comment=str(getattr(result, "comment", None)))

    def order_send(self, request: TradeRequest) -> TradeSendResult:
        mt5_request = self._build_mt5_request(request)
        result = self._mt5.order_send(mt5_request)
        if result is None:
            raise MT5BackendError("MetaTrader5.order_send() returned None")
        retcode = int(result.retcode)
        if retcode != self._mt5.TRADE_RETCODE_DONE:
            return TradeSendResult(retcode=retcode, deal=None, order=None, volume=None, price=None, comment=str(getattr(result, "comment", None)))
        return TradeSendResult(
            retcode=retcode,
            deal=int(result.deal),
            order=int(result.order),
            volume=clean_decimal(float(result.volume)),
            price=clean_decimal(float(result.price)),
            comment=str(getattr(result, "comment", None)),
        )


def _mt5_symbol_info_to_backend(info) -> BackendSymbolInfo:
    """Shared conversion for both `RealMT5Backend.symbol_info` (single
    symbol) and `symbols_get` (listing) -- one place to keep the mapping
    from MT5's `SymbolInfo` named tuple consistent between the two.

    All numeric fields go through `clean_decimal` (not `quantize_price`):
    these are the symbol's own declared metadata (point size, volume
    granularity, contract size, tick value), not a quoted price to round
    to a certain number of displayed digits -- they need binary-noise
    cleanup only, not a digits-based quantum.
    """

    tick_size = getattr(info, "trade_tick_size", None)
    tick_value = getattr(info, "trade_tick_value", None)
    trade_mode = getattr(info, "trade_mode", None)
    return BackendSymbolInfo(
        name=info.name,
        description=getattr(info, "description", None),
        digits=int(info.digits),
        point=clean_decimal(float(info.point)),
        volume_min=clean_decimal(float(info.volume_min)),
        volume_step=clean_decimal(float(info.volume_step)),
        volume_max=clean_decimal(float(info.volume_max)),
        trade_contract_size=clean_decimal(float(info.trade_contract_size)),
        trade_tick_size=clean_decimal(float(tick_size)) if tick_size is not None else None,
        trade_tick_value=clean_decimal(float(tick_value)) if tick_value is not None else None,
        trade_enabled=(trade_mode == SYMBOL_TRADE_MODE_FULL) if trade_mode is not None else None,
        visible=bool(info.visible),
        filling_mode=getattr(info, "filling_mode", None),
        currency_base=getattr(info, "currency_base", None),
        currency_profit=getattr(info, "currency_profit", None),
        currency_margin=getattr(info, "currency_margin", None),
    )


MT5_TIMEFRAME_ATTR_BY_NAME = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def _utc():
    from datetime import timezone

    return timezone.utc
