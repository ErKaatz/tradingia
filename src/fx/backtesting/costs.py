"""Cost model interfaces: commission, slippage, swap (Phase 5B, Sections
8/13/14/15).

Each model is a small `Protocol`-free explicit class hierarchy (an ABC,
not a `Protocol`, because every implementation here lives in this repo
-- there is no need for structural typing across a package boundary).
Every backtest configuration must pick one of each explicitly; there is
no implicit "zero cost" default anywhere in this module or in
`engine.py` -- see `NoCommission`/`NoSwap`, which exist specifically so
"no cost" is a recorded, deliberate choice rather than an omission
(Section 14's critical safety rule).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.fx.backtesting.models import PositionSide

# --------------------------------------------------------------------------
# Slippage
# --------------------------------------------------------------------------


class SlippageModel(ABC):
    """Deterministic adverse slippage, applied to one side of one fill.

    "Adverse" is fixed by definition, not by sign convention the caller
    could get backwards: a BUY-direction fill (LONG entry, SHORT exit)
    always becomes worse by moving the price UP; a SELL-direction fill
    (SHORT entry, LONG exit) always becomes worse by moving the price
    DOWN. `apply` takes the *un-slipped* execution price and the side of
    the fill (`is_buy`) and returns the slipped price -- callers never
    add/subtract the sign themselves.
    """

    @abstractmethod
    def points(self) -> Decimal:
        """Adverse slippage magnitude, in the symbol's own points (same
        unit as `spread_points` / `SymbolMetadata.point`). Always >= 0."""
        raise NotImplementedError

    def apply(self, price: Decimal, point: Decimal, is_buy: bool) -> Decimal:
        offset = self.points() * point
        return price + offset if is_buy else price - offset


@dataclass(frozen=True)
class ZeroSlippage(SlippageModel):
    def points(self) -> Decimal:
        return Decimal("0")


@dataclass(frozen=True)
class FixedPointsSlippage(SlippageModel):
    """A fixed number of adverse points applied to every fill."""

    slippage_points: Decimal

    def __post_init__(self) -> None:
        if self.slippage_points < 0:
            raise ValueError(f"slippage_points must be non-negative, got {self.slippage_points}")

    def points(self) -> Decimal:
        return self.slippage_points


# --------------------------------------------------------------------------
# Commission
# --------------------------------------------------------------------------


class CommissionModel(ABC):
    """Commission for one side (open or close) of one trade.

    `NoCommission` records the explicit research assumption "this
    backtest assumes zero commission" -- it does NOT mean the real
    broker charges none (Section 13). Every `TradeResult.commission_cost`
    traces back to exactly one `CommissionModel`, so a report can always
    say which assumption produced it.
    """

    @abstractmethod
    def cost_for_side(self, lots: Decimal) -> Decimal:
        """Commission charged for opening OR closing `lots` lots (charge
        this once per side; the engine calls it twice per round-turn
        trade unless the model itself represents a round-turn charge --
        see `PerLotRoundTurn`, which returns half its rate here so two
        calls sum to the full round-turn charge)."""
        raise NotImplementedError


@dataclass(frozen=True)
class NoCommission(CommissionModel):
    def cost_for_side(self, lots: Decimal) -> Decimal:
        return Decimal("0")


@dataclass(frozen=True)
class PerLotPerSide(CommissionModel):
    """A fixed charge per lot, applied independently on entry and on exit."""

    rate_per_lot: Decimal

    def __post_init__(self) -> None:
        if self.rate_per_lot < 0:
            raise ValueError(f"rate_per_lot must be non-negative, got {self.rate_per_lot}")

    def cost_for_side(self, lots: Decimal) -> Decimal:
        return self.rate_per_lot * lots


@dataclass(frozen=True)
class PerLotRoundTurn(CommissionModel):
    """A fixed charge per lot for the full round turn (open + close
    together). Half of `rate_per_lot` is charged on each side so the sum
    of the two `cost_for_side` calls the engine makes equals the full
    round-turn rate -- never the full rate charged twice."""

    rate_per_lot: Decimal

    def __post_init__(self) -> None:
        if self.rate_per_lot < 0:
            raise ValueError(f"rate_per_lot must be non-negative, got {self.rate_per_lot}")

    def cost_for_side(self, lots: Decimal) -> Decimal:
        return (self.rate_per_lot * lots) / 2


# --------------------------------------------------------------------------
# Swap / rollover
# --------------------------------------------------------------------------


class SwapRequiredError(Exception):
    """Raised when a position crosses a configured rollover boundary and
    no swap model was explicitly configured (Section 14's critical
    safety rule). This must never be silently treated as zero swap --
    `NoSwap` is the only way to explicitly opt into a zero-swap research
    assumption; the *absence* of any swap model is a configuration bug,
    not a research choice, and must fail loudly."""


class SwapModel(ABC):
    """Overnight financing charged when a position crosses a configured
    rollover boundary (see `RolloverSchedule`).

    `charge_for_crossing` is called once per rollover boundary crossed
    while a position is open (a position held over N rollovers is
    charged N times). Sign convention: a positive return value is a
    cost (subtracted from `net_pnl`); a negative value is a credit
    (e.g. a rate differential paying the position).
    """

    @abstractmethod
    def charge_for_crossing(self, side: PositionSide, lots: Decimal, crossing_time: datetime) -> Decimal:
        raise NotImplementedError


@dataclass(frozen=True)
class NoSwap(SwapModel):
    """Explicit research assumption: overnight financing is zero.

    Choosing this is a deliberate modeling decision the report must
    record -- it is not the same state as "forgot to configure swap",
    which the engine refuses to run under at all (see
    `RolloverSchedule`/`SwapRequiredError` in `engine.py`).
    """

    def charge_for_crossing(self, side: PositionSide, lots: Decimal, crossing_time: datetime) -> Decimal:
        return Decimal("0")


@dataclass(frozen=True)
class FixedSwapModel(SwapModel):
    """A fixed per-lot-per-crossing charge, independent of side (no
    long/short rate differential modeling in Phase 5B -- see
    PHASE5B_STATUS.md limitations). Triple-swap (a broker's 3x weekend
    rollover charge) is representable by the caller supplying a
    `RolloverSchedule` whose Wednesday (or broker-specific) boundary
    already carries the 3x rate baked into `rate_per_lot_per_crossing`;
    this model does not detect "is this a triple-swap day" itself."""

    rate_per_lot_per_crossing: Decimal

    def charge_for_crossing(self, side: PositionSide, lots: Decimal, crossing_time: datetime) -> Decimal:
        return self.rate_per_lot_per_crossing * lots


@dataclass(frozen=True)
class SideAwareFixedSwapModel(SwapModel):
    """Broker-observed per-lot swap rates for long and short positions.

    Rates follow the engine convention: a positive number is a debit and a
    negative number is a credit.  ``triple_swap_weekday`` uses Python's
    ``datetime.weekday`` convention (Monday=0, Wednesday=2), deliberately
    stated here instead of relying on MT5 enum numeric values at runtime.
    ``None`` means that no triple-day multiplier has been verified.
    """

    long_rate_per_lot: Decimal
    short_rate_per_lot: Decimal
    triple_swap_weekday: int | None = None

    def __post_init__(self) -> None:
        if self.triple_swap_weekday is not None and not 0 <= self.triple_swap_weekday <= 6:
            raise ValueError("triple_swap_weekday must be in [0, 6] (Monday=0)")

    def charge_for_crossing(self, side: PositionSide, lots: Decimal, crossing_time: datetime) -> Decimal:
        rate = self.long_rate_per_lot if side is PositionSide.LONG else self.short_rate_per_lot
        multiplier = Decimal("3") if self.triple_swap_weekday == crossing_time.weekday() else Decimal("1")
        return rate * lots * multiplier


@dataclass(frozen=True)
class RolloverSchedule:
    """An explicit, configured set of daily rollover boundaries (Section
    15): the engine does not assume a New York close or any other
    broker-specific rollover rule -- it only knows whether a bar
    boundary crosses one of these caller-supplied UTC hours.

    `hours_utc` are hour-of-day values (0-23) at which a rollover is
    considered to occur once per day. Whether this actually matches
    HFM's real rollover time (broker-specific, unverified in Phase 5A)
    is the caller's documented assumption, not this class's claim.
    """

    hours_utc: frozenset[int]

    def __post_init__(self) -> None:
        for h in self.hours_utc:
            if not (0 <= h <= 23):
                raise ValueError(f"RolloverSchedule hour {h} out of range [0, 23]")

    def crossings_between(self, start: datetime, end: datetime) -> list[datetime]:
        """Every configured rollover instant in (start, end], in order.
        `start`/`end` must be UTC-aware; a position open from `start`
        (exclusive) to `end` (inclusive) crosses each of these."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("RolloverSchedule.crossings_between requires timezone-aware datetimes")
        if end < start:
            raise ValueError("end must not be before start")
        crossings: list[datetime] = []
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= end:
            for hour in sorted(self.hours_utc):
                candidate = day.replace(hour=hour)
                if start < candidate <= end:
                    crossings.append(candidate)
            day = day.replace(hour=0) + timedelta(days=1)
        return sorted(crossings)
