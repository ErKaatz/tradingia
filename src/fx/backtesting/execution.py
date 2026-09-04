"""Bid/ask reconstruction and directional fill economics (Phase 5B,
Sections 2, 6, 7).

## Verified MT5 OHLC price-side semantics

MetaTrader 5's `copy_rates_range()` (the function
`mt5_bridge/backend.py::RealMT5Backend.copy_rates_range` calls, and the
sole source of every `FxBar` in this codebase) is documented by
MetaQuotes to return OHLC built from the **BID** price stream for FX
symbols; the `spread` field is the last-known spread (in points) at
each bar, which is how a caller reconstructs the ASK side of the same
bar: `ask = bid + spread_points * point`. This is a stable, documented
property of the MT5 platform itself (not something that varies per
broker), which is why Phase 5A's `mt5_provider.py`/`schema.py` already
carry `spread_points` on every `FxBar` without repurposing it for cost
modeling.

This was not independently re-derived from a tick-level bid/ask
comparison against real HFM data in this phase (that would require
comparing `copy_rates_range` bars against `copy_ticks_range` over the
same window, which Phase 5B's scope -- economic/accounting foundation,
not a tick-data study -- does not require). It is documented here as
`VERIFIED (documented)` rather than `VERIFIED (empirical)`; see
PHASE5B_STATUS.md. Per Section 2's explicit instruction, if this
semantics question could not be answered at all, Phase 5B would have to
stop before implementing fills -- it can be answered, from MetaQuotes'
own documented contract, so Phase 5B proceeds on that basis.

## Fill convention

    BID = FxBar price fields (open/high/low/close) as-is.
    ASK = BID + spread_points * point.

    LONG:  open at ASK, close at BID.
    SHORT: open at BID, close at ASK.

plus adverse slippage (see `costs.py::SlippageModel`) applied on top of
whichever side (bid or ask) a fill uses. Fills occur at the next bar's
OPEN (Section 7) -- this module only computes the *price* of a fill
given a bar and a side; `engine.py` decides *which* bar to use.

No intrabar stop/take-profit, no OHLC path guessing, no tick simulation
-- exactly the open price of the fill bar, adjusted for spread and
slippage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.fx.backtesting.costs import SlippageModel
from src.fx.backtesting.models import PositionSide


@dataclass(frozen=True)
class BidAsk:
    bid: Decimal
    ask: Decimal

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("bid/ask must be positive")
        if self.ask < self.bid:
            raise ValueError(f"ask ({self.ask}) must be >= bid ({self.bid})")


def reconstruct_bid_ask(bar_price: Decimal, spread_points: int | None, point: Decimal) -> BidAsk:
    """Reconstruct bid/ask for one OHLC price field of one bar.

    `bar_price` is BID (see module docstring). `spread_points` missing
    (`None`) is treated as zero spread -- this is a documented
    simplification, not a claim that the real spread was zero; a caller
    that cannot tolerate this must reject bars with `spread_points is
    None` upstream (see `engine.py`'s input validation).
    """
    if bar_price <= 0:
        raise ValueError(f"bar_price must be positive, got {bar_price}")
    if point <= 0:
        raise ValueError(f"point must be positive, got {point}")
    spread = spread_points if spread_points is not None else 0
    if spread < 0:
        raise ValueError(f"spread_points must be non-negative, got {spread_points}")
    bid = bar_price
    ask = bid + Decimal(spread) * point
    return BidAsk(bid=bid, ask=ask)


@dataclass(frozen=True)
class Fill:
    """One directional fill: the bid/ask context it was computed from,
    and the final execution price after slippage."""

    bid: Decimal
    ask: Decimal
    execution_price: Decimal


def _is_buy_direction(side: PositionSide, opening: bool) -> bool:
    """LONG open and SHORT close are BUY-direction fills; SHORT open and
    LONG close are SELL-direction fills (Section 7)."""
    if side is PositionSide.LONG:
        return opening
    if side is PositionSide.SHORT:
        return not opening
    raise ValueError("side must be LONG or SHORT")


def compute_fill(
    side: PositionSide,
    opening: bool,
    bar_open_price: Decimal,
    spread_points: int | None,
    point: Decimal,
    slippage_model: SlippageModel,
) -> Fill:
    """Compute one fill's bid/ask context and final execution price.

    `bar_open_price` is the OPEN of the bar this fill executes on
    (Section 7: fills occur at next-bar open, never the signal bar's own
    close). `opening=True` means this is a position-open fill;
    `opening=False` means a position-close fill.

    Convention (module docstring): LONG opens at ASK/closes at BID;
    SHORT opens at BID/closes at ASK. Slippage is applied on top of that
    reference price, always adverse to the trader.
    """
    bid_ask = reconstruct_bid_ask(bar_open_price, spread_points, point)
    is_long_open_or_short_close = (side is PositionSide.LONG) == opening
    reference_price = bid_ask.ask if is_long_open_or_short_close else bid_ask.bid
    is_buy = _is_buy_direction(side, opening)
    execution_price = slippage_model.apply(reference_price, point, is_buy)
    return Fill(bid=bid_ask.bid, ask=bid_ask.ask, execution_price=execution_price)
