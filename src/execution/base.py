"""Broker-agnostic execution domain types (FX Phase 0, Step 1).

This module defines the *contract* for talking to any execution venue
(MetaTrader 5 today, potentially something else later) without leaking
broker-specific concepts into strategy or policy code. Nothing in this
file imports or references the `MetaTrader5` package, and nothing here
performs I/O — it is pure data modeling plus a Protocol describing what an
execution client must be able to do.

Design decisions (see FX_PHASE0_STATUS.md for the broader rationale):

- Money, price, and volume fields use `Decimal`, not `float`. Volume in
  particular is compared against broker-supplied step/min/max values
  (see `SymbolMetadata` and `policy.py`), and float comparisons of
  quantities like 0.01 vs 0.010000000000000002 are exactly the kind of
  fragile bug this project has repeatedly gone out of its way to avoid
  elsewhere (e.g. causal-only signal tests, exact-hash dataset
  registration). Decimal is the standard fix for this class of bug at an
  execution boundary and costs little here since these values come from
  strings/config/API responses, not from hot numerical loops.
- `Environment` and `AccountTradeMode` are separate enums. `Environment`
  is what *this client/config* believes it is talking to; `AccountTradeMode`
  is what the *remote account itself* reports. Policy (Step 1's other
  half) requires both to independently say DEMO before allowing any
  order — this file only defines the vocabulary, it does not decide.
- Both enums include an explicit `UNKNOWN` member. A missing or
  unparseable value must become `UNKNOWN`, never silently default to
  `DEMO` — an execution client that cannot positively identify an
  environment must say so, not guess.
- `ExecutionClient` is a `Protocol` (structural typing), not an ABC. Step 1
  has no concrete implementation yet (no HTTP client, no MT5 bridge); a
  Protocol lets tests construct minimal fakes without inheriting from
  anything, and lets the future `mt5_remote.py` implementation satisfy the
  interface without a base-class import chain.
- No credentials, tokens, or passwords appear anywhere in these types.
  Authentication is a transport concern for a later step, not a domain
  concept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class Environment(Enum):
    """What this execution client/config believes it is talking to.

    This is a *local* claim, not a verified fact. Policy must not trust
    `Environment.DEMO` alone — it must be corroborated by the remote
    account's own `AccountTradeMode` (see policy.py's defense-in-depth
    checks).
    """

    DEMO = "demo"
    LIVE = "live"
    UNKNOWN = "unknown"


class AccountTradeMode(Enum):
    """What the remote broker/terminal reports the account to be.

    Kept distinct from `Environment` deliberately: a config can *say*
    demo while a misconfigured or reused terminal is actually pointed at
    a live account. Both must agree before any order is authorized.
    """

    DEMO = "demo"
    LIVE = "live"
    CONTEST = "contest"
    UNKNOWN = "unknown"


class ReconciliationState(Enum):
    """Whether locally-expected state matches the remote venue's state.

    Step 1 does not implement reconciliation logic (that is a later
    step), but policy must be able to deny new entries when this is
    anything other than OK, so the vocabulary is defined now.
    """

    OK = "ok"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    ACCEPTED = "accepted"
    FILLED = "filled"
    REJECTED = "rejected"
    ERROR = "error"


class ExecutionTimeframe(Enum):
    """Bar timeframe for `HistoryRequest`. Deliberately closed to the set
    the bridge actually supports (Step 3.1) -- adding a new member here
    must be a conscious decision, not free-text passed through to MT5.
    """

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


class ActionKind(Enum):
    """Coarse classification of what a requested action does to risk.

    Used by policy to implement "kill switch blocks new/increased risk
    but never blocks closing/reducing risk" (see policy.py).
    """

    OPEN = "open"
    INCREASE = "increase"
    CLOSE = "close"
    REDUCE = "reduce"


@dataclass(frozen=True)
class SymbolMetadata:
    """Broker/symbol-reported trading constraints for one instrument.

    All quantities are `Decimal`. `volume_min`/`volume_step`/`volume_max`
    exist specifically so policy never hardcodes a lot size (e.g. 0.01) —
    the frozen sizing rule is "use the broker's minimum", which requires
    knowing what that minimum actually is per symbol.
    """

    symbol: str
    volume_min: Decimal
    volume_step: Decimal
    volume_max: Decimal
    contract_size: Decimal
    digits: int
    point: Decimal


@dataclass(frozen=True)
class SymbolSummary:
    """A lightweight listing entry from `GET /v1/symbols` -- discovery of
    what names the broker actually exposes (e.g. `EURUSDm`, `EURUSD.a`),
    NOT the full trading metadata `SymbolMetadata` carries. Deliberately
    does not reuse `SymbolMetadata`: forcing volume_min/step/max/digits
    onto every listed symbol would mean inventing values the bridge's
    listing call was never asked to provide. Fetch `SymbolMetadata` via
    `symbol_metadata(symbol)` once a specific symbol name is confirmed.
    """

    symbol: str
    description: str | None
    visible: bool
    trade_enabled: bool | None


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class TerminalStatus:
    connected: bool
    trade_allowed: bool
    dlls_allowed: bool | None = None
    name: str | None = None
    company: str | None = None
    build: int | None = None


@dataclass(frozen=True)
class AccountSummary:
    account_id: str
    trade_mode: AccountTradeMode
    balance: Decimal
    equity: Decimal
    currency: str
    trade_allowed: bool | None = None
    trade_expert: bool | None = None


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    side: Side
    volume: Decimal
    open_price: Decimal


@dataclass(frozen=True)
class OrderRequest:
    """A caller's request to open or close exposure.

    `client_order_id` is required (not optional) because idempotency is
    a first-class concern of this whole subsystem (see
    RESEARCH_RULES.md-equivalent for execution: LIVE_TRADING_RULES.md).
    Step 1 does not implement idempotent *storage*, but every type that
    will eventually flow through that storage carries the key from the
    start, so later steps don't need a breaking schema change.
    """

    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    volume: Decimal
    action_kind: ActionKind
    limit_price: Decimal | None = None
    position_id: str | None = None


@dataclass(frozen=True)
class Order:
    """A broker-side working/completed order as reported by `GET
    /v1/orders` (read-only view; not the same type as `OrderRequest`,
    which is a caller's *request* to place one). Added in Step 2 because
    the read-only `orders()` listing needs a return type that Step 1 did
    not yet define.

    `client_order_id` is `str | None` -- deliberately different from
    `OrderRequest.client_order_id` (still required `str`, unchanged).
    An order visible through `GET /v1/orders` may have been placed
    manually, by another EA, or by TradingIA itself. Only the last case
    has an honest `client_order_id` to report; a manual/external order's
    MT5 ticket is NOT a TradingIA client_order_id and must never be
    reported as if it were one (see `mt5_bridge/schemas.py::order_response`
    for how the bridge distinguishes the two). `broker_order_id` always
    carries the real MT5 ticket/ID regardless of who placed the order.
    """

    client_order_id: str | None
    symbol: str
    side: Side
    volume: Decimal
    status: OrderStatus
    broker_order_id: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a `place_order` call (Step 4).

    Carries the full audit trail a market order needs to be judged later:
    the quote actually observed, the reference price derived from it
    (ask for BUY, bid for SELL -- see `SafeExecutionService`), the actual
    fill, and the resulting slippage -- all `Decimal`, never a raw MT5
    object repr. `idempotent_replay=True` means this result was NOT
    produced by a new MT5 submission -- it is the stored result of an
    earlier request with the same `client_order_id` and identical
    parameters (see Step 4's idempotency design in `mt5_bridge/store.py`).
    """

    client_order_id: str
    status: OrderStatus
    broker_order_id: str | None
    deal_id: str | None
    position_id: str | None
    fill_price: Decimal | None
    filled_volume: Decimal | None
    requested_volume: Decimal | None
    observed_bid: Decimal | None
    observed_ask: Decimal | None
    reference_price: Decimal | None
    slippage: Decimal | None
    mt5_retcode: int | None
    timestamp: datetime
    idempotent_replay: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class HistoryRequest:
    """`timeframe` is required with no default -- Step 3.1 correction.

    Before this correction, `HistoryRequest` had no timeframe field at
    all, so every real request from TradingIA silently fell through to
    the bridge's own `Query("M15")` default regardless of what the
    caller actually wanted. Requiring it here, with no default value on
    this dataclass, forces the caller to decide -- see
    `MT5RemoteExecutionClient.history`, which sends it as
    `?timeframe=<value>` and does not choose one on the caller's behalf.
    """

    symbol: str
    timeframe: ExecutionTimeframe
    start: datetime
    end: datetime


@dataclass(frozen=True)
class HistoryBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class HistoryResult:
    symbol: str
    bars: tuple[HistoryBar, ...] = field(default_factory=tuple)




@dataclass(frozen=True)
class JournalEntry:
    """One append-only bridge journal entry (Step 4 operator view).

    The bridge sanitizes payloads before persistence; the Linux client still
    treats the payload as opaque structured data rather than interpreting it
    as trading state.
    """

    entry_id: int
    request_id: str | None
    client_order_id: str | None
    timestamp: datetime
    action: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class HealthStatus:
    """Bridge/terminal reachability, independent of account identity."""

    bridge_alive: bool
    terminal_connected: bool
    server_time: datetime | None
    broker_name: str | None = None
    api_version: str | None = None
    bridge_version: str | None = None
    bridge_build: str | None = None
    bridge_time_utc: datetime | None = None


@dataclass(frozen=True)
class CloseRequest:
    """A caller's request to fully close one existing position (Step 4).

    Deliberately separate from `OrderRequest`: a close targets a
    `position_id`, not a symbol/side/volume the caller chooses -- the
    bridge determines the opposite-side volume from the position's own
    current state at execution time (see Step 4's "close uses the
    position's live volume, not a client-supplied one" rule). Step 4
    supports full-close only; there is no `volume` field to request a
    partial close with.
    """

    client_order_id: str
    position_id: str


@dataclass(frozen=True)
class CloseResult:
    client_order_id: str
    position_id: str
    status: OrderStatus
    closed_volume: Decimal | None
    observed_bid: Decimal | None
    observed_ask: Decimal | None
    reference_price: Decimal | None
    fill_price: Decimal | None
    slippage: Decimal | None
    deal_id: str | None
    mt5_retcode: int | None
    timestamp: datetime
    idempotent_replay: bool = False
    error_message: str | None = None


class KillSwitchStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class KillSwitchState:
    status: KillSwitchStatus
    changed_at: datetime | None
    reason: str | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    state: ReconciliationState
    checked_at: datetime
    details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TimeDiagnostics:
    """Read-only clock diagnostic (FX Phase 0) -- lets a human distinguish
    Linux/bridge/MT5-tick clock skew from a code bug. Three clocks, kept
    deliberately distinct (never conflated -- that conflation is exactly
    what caused the original "quote has a timestamp in the future" bug):

    - `linux_client_utc`: this process's own clock, captured immediately
      before calling the bridge.
    - `bridge_time_utc`: the Windows bridge process's own clock, from its
      `/v1/time-diagnostics/{symbol}` response.
    - `mt5_tick_time_utc`: the requested symbol's own last-tick timestamp,
      as reported by MT5 via the bridge (`None` if no tick is available).

    `bridge_client_skew_seconds`, `tick_client_skew_seconds`, and
    `tick_bridge_skew_seconds` are `bridge - linux`, `tick - linux`, and
    `tick - bridge` respectively (positive means the second clock is
    ahead). `quote_age_seconds_per_client`/`quote_age_seconds_per_bridge`
    are the same tick's age computed against each clock, so a stale-vs-
    future disagreement between the two immediately shows which clock is
    the outlier.
    """

    symbol: str
    linux_client_utc: datetime
    bridge_time_utc: datetime
    mt5_tick_time_utc: datetime | None
    bridge_client_skew_seconds: float
    tick_client_skew_seconds: float | None
    tick_bridge_skew_seconds: float | None
    quote_age_seconds_per_client: float | None
    quote_age_seconds_per_bridge: float | None
    server_clock_offset_seconds: float | None = None


@runtime_checkable
class ExecutionClient(Protocol):
    """Structural interface every execution backend must satisfy.

    No implementation exists yet in Step 1 — this is the contract that
    `src/execution/mt5_remote.py` (a future step) will implement over
    HTTP against the Windows-side bridge. Defined as a `Protocol` so
    tests can supply minimal fakes without inheriting from anything.
    """

    def health(self) -> HealthStatus: ...

    def account(self) -> AccountSummary:
        ...

    def symbols(self) -> tuple[SymbolSummary, ...]: ...

    def symbol_metadata(self, symbol: str) -> SymbolMetadata: ...

    def quote(self, symbol: str) -> Quote: ...

    def positions(self) -> tuple[Position, ...]: ...

    def orders(self) -> tuple[Order, ...]: ...

    def history(self, request: HistoryRequest) -> HistoryResult: ...

    def place_order(self, request: OrderRequest) -> ExecutionResult: ...

    def close_position(self, request: CloseRequest) -> CloseResult: ...

    def kill_switch_status(self) -> KillSwitchState: ...

    def activate_kill_switch(self, reason: str | None = None) -> KillSwitchState: ...

    def deactivate_kill_switch(self) -> KillSwitchState: ...

    def reconciliation_status(self) -> ReconciliationReport: ...

    def run_reconciliation(self) -> ReconciliationReport: ...

    def time_diagnostics(self, symbol: str) -> TimeDiagnostics: ...
