"""Gross PnL with explicit currency semantics (Phase 5B, Sections 9/10).

## The currency problem this module refuses to paper over

For a symbol like EURUSD, `currency_profit == "USD"`. If the account
currency is also USD (true for this project's HFM demo account -- see
PHASE5A_STATUS.md), then:

    gross_pnl_quote_ccy = (exit_price - entry_price) * lots * contract_size   [LONG]
    gross_pnl_quote_ccy = (entry_price - exit_price) * lots * contract_size  [SHORT]

is already denominated in the account currency and needs no conversion.
This is the *only* case Phase 5B actually supports end to end. A symbol
whose `currency_profit` differs from the account currency (e.g. a
EUR-account trading USDJPY) would need a conversion rate this module
does not have and must not guess -- `compute_gross_pnl` raises
`UnsupportedCurrencyConversionError` rather than silently computing a
wrong number in the wrong currency. This is a documented `NOT YET
SUPPORTED`, not a bug: EURUSD/USD-account is Phase 5B's fully verified
target (Section 10).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.fx.backtesting.models import PositionSide


class UnsupportedCurrencyConversionError(Exception):
    """Raised when `currency_profit` differs from `account_currency` and
    no conversion rate is available. Phase 5B has no cross-currency
    conversion mechanism -- this must fail loudly, never silently
    compute PnL as if the currencies matched (Section 10)."""


@dataclass(frozen=True)
class GrossPnlInputs:
    side: PositionSide
    entry_execution_price: Decimal
    exit_execution_price: Decimal
    lots: Decimal
    contract_size: Decimal
    currency_profit: str | None
    account_currency: str | None


def compute_gross_pnl(inputs: GrossPnlInputs) -> Decimal:
    """Gross PnL in the account's currency, for a fully closed trade.

    `entry_execution_price`/`exit_execution_price` already embed spread
    and slippage (see `execution.py::compute_fill`) -- this function
    computes the reference/gross PnL of the trade *as actually filled*,
    not a fictitious zero-cost mid-price PnL. Commission and swap are
    NOT subtracted here; see `models.py::TradeResult` for the exact
    `net_pnl = gross_pnl - commission_cost - swap_cost` identity this
    value feeds into.

    Raises `UnsupportedCurrencyConversionError` if `currency_profit` and
    `account_currency` are both known and differ -- see module
    docstring. If either is `None` (metadata unavailable), this function
    proceeds under the caller's responsibility rather than blocking on
    missing enrichment data that Phase 5A already documents as
    sometimes absent (e.g. `broker` field) -- the accounting math itself
    is currency-agnostic; only the *conversion* step is unsupported.
    """
    if (
        inputs.currency_profit is not None
        and inputs.account_currency is not None
        and inputs.currency_profit != inputs.account_currency
    ):
        raise UnsupportedCurrencyConversionError(
            f"symbol currency_profit={inputs.currency_profit!r} differs from "
            f"account_currency={inputs.account_currency!r}; Phase 5B has no "
            "conversion mechanism -- refusing to compute a silently wrong PnL"
        )

    exposure = inputs.lots * inputs.contract_size
    if inputs.side is PositionSide.LONG:
        price_diff = inputs.exit_execution_price - inputs.entry_execution_price
    elif inputs.side is PositionSide.SHORT:
        price_diff = inputs.entry_execution_price - inputs.exit_execution_price
    else:
        raise ValueError("side must be LONG or SHORT")

    return price_diff * exposure
