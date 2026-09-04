"""FX backtest domain types (Phase 5B).

These types are deliberately independent of `src/backtesting/engine.py`
(the crypto-era FLAT/LONG-only engine) and of `src/strategies/base.py`'s
FLAT/LONG integers -- FX Phase 5B needs a third state (SHORT) and an
auditable bid/ask/cost trail that the crypto engine's `Trade` never
needed to carry.

Scope, per PHASE5B task spec: one symbol, one position at a time, fixed
lots, no pyramiding/averaging/partial closes/hedging/portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PositionSide(Enum):
    """A position's direction. `FLAT` is a state of the account (no open
    position), never a value stored on an actual `Position` -- see
    `Position`, which only exists while LONG or SHORT."""

    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class TargetPosition(Enum):
    """The minimal signal contract the engine accepts (Section 5).

    A strategy/signal source maps each bar to one of these three
    values. The engine enforces the causal rule itself (see
    `engine.py`): the target computed as of bar i's close becomes the
    position held starting at bar i+1's open. Nothing in this enum
    performs that shift -- it is a pure data value.
    """

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class Position:
    """An open LONG or SHORT position in exactly one symbol.

    Carries enough of the entry's price/cost context to audit the
    eventual `TradeResult` without re-deriving it from raw bars. Never
    constructed with `side=PositionSide.FLAT` -- flat is the *absence*
    of a `Position`, not a `Position` value (see `AccountState.position`
    being `Position | None`).
    """

    symbol: str
    side: PositionSide
    lots: Decimal
    contract_size: Decimal
    open_time: datetime
    entry_bid: Decimal
    entry_ask: Decimal
    entry_execution_price: Decimal
    entry_spread_points: int | None

    def __post_init__(self) -> None:
        if self.side is PositionSide.FLAT:
            raise ValueError("Position.side must be LONG or SHORT, never FLAT")
        if self.lots <= 0:
            raise ValueError(f"Position.lots must be positive, got {self.lots}")
        if self.contract_size <= 0:
            raise ValueError(f"Position.contract_size must be positive, got {self.contract_size}")
        if self.entry_bid <= 0 or self.entry_ask <= 0:
            raise ValueError("Position entry bid/ask must be positive")
        if self.entry_ask < self.entry_bid:
            raise ValueError(f"Position entry ask ({self.entry_ask}) < bid ({self.entry_bid})")

    @property
    def exposure(self) -> Decimal:
        """Notional exposure in the symbol's base currency: lots * contract_size."""
        return self.lots * self.contract_size


@dataclass(frozen=True)
class TradeResult:
    """A completed (opened-then-closed) trade, fully auditable.

    `gross_pnl` is the trade's reference/zero-cost PnL: the same price
    move, costed bid-to-bid, with zero spread and zero slippage. Actual
    execution used `entry_execution_price`/`exit_execution_price`
    (spread- and slippage-adjusted), so the accounting identity is:

        net_pnl = gross_pnl - spread_cost - slippage_cost - commission_cost - swap_cost

    Each cost term is independently derived (see `engine.py::_close`'s
    decomposition) so this identity holds exactly, with nothing counted
    twice -- see `costs.py`/`pnl.py` module docstrings.
    """

    symbol: str
    side: PositionSide
    lots: Decimal

    open_time: datetime
    close_time: datetime

    entry_execution_price: Decimal
    exit_execution_price: Decimal

    entry_bid: Decimal
    entry_ask: Decimal
    exit_bid: Decimal
    exit_ask: Decimal

    gross_pnl: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    commission_cost: Decimal
    swap_cost: Decimal
    net_pnl: Decimal

    bars_held: int

    def __post_init__(self) -> None:
        if self.side is PositionSide.FLAT:
            raise ValueError("TradeResult.side must be LONG or SHORT, never FLAT")
        if self.lots <= 0:
            raise ValueError(f"TradeResult.lots must be positive, got {self.lots}")
        if self.bars_held < 1:
            raise ValueError(f"TradeResult.bars_held must be >= 1, got {self.bars_held}")


@dataclass(frozen=True)
class AccountState:
    """Single-symbol account bookkeeping (Section 16).

    `equity` marks the open position to market using BID for LONG and
    ASK for SHORT -- the price at which the position could be closed
    right now (LONG closes at BID, SHORT closes at ASK; see
    `execution.py`). This is a documented convention, not the only
    possible one (mid-price marking is equally defensible) -- Phase 5B
    picks the "conservative liquidation value" convention and tests it.
    """

    initial_balance: Decimal
    balance: Decimal
    realized_pnl: Decimal
    position: Position | None
    equity: Decimal
