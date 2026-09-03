"""Centralized MT5 float -> clean Decimal conversion (FX Phase 0, Step 3.1).

Observed in real HFM demo testing (2026-09-03): a raw MT5 float for
EURUSD ask arrived as `1.1587399999999999` -- an IEEE-754 binary
artifact from MT5's own float representation, not a real economic value.
The symbol's `digits=5` means the true tradeable quantum is 0.00001, so
the economically correct value is `Decimal("1.15874")`. Before this
correction, that raw float was converted with `str(float(...))`
(`RealMT5Backend`) and then `str()`'d again into JSON (`schemas.py`),
carrying the binary noise all the way to the Linux client's `Decimal`
constructor -- `Decimal(str(1.1587399999999999))` faithfully preserves
every one of those spurious 9s, because by that point the artifact is
indistinguishable from a real 16-significant-digit price.

The fix has to happen here, in `RealMT5Backend`, at the moment a value
first leaves MetaTrader5 -- not downstream in `schemas.py` (which no
longer knows how many digits are real) and not on the Linux client side
(which only ever sees a string and has no way to know it should have
been shorter). See `RealMT5Backend`'s conversion methods in `backend.py`
for where these helpers are actually called.

Three distinct quantizations, deliberately NOT sharing one function:

- `quantize_price`: uses the symbol's `digits` (number of decimal places
  MT5 itself displays/trades this symbol at). Right for bid/ask and OHLC.
- `quantize_volume`: uses `volume_step` (the lot-size granularity), which
  has nothing to do with a symbol's price digits -- an instrument could
  have digits=5 and volume_step=0.01 simultaneously, and conflating the
  two would silently misround one of them.
- `clean_decimal`: for values with no natural "number of digits" of their
  own (account balance/equity/margin, tick_value, contract_size) --
  removes binary float noise via `Decimal(repr(value))` (Python's `repr`
  for a float already gives the shortest decimal string that round-trips
  to that exact float, which is the standard way to recover the "real"
  decimal a binary float was probably meant to represent) without
  imposing an arbitrary fixed number of decimal places.

None of these ever touch `tick_volume`/`real_volume` -- those are counts,
not prices, and quantizing them with a symbol's price digits would be a
category error (see `mt5_bridge/backend.py`'s bar/tick conversion, which
calls `clean_decimal` for volume fields, never `quantize_price`).
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation


class QuantizationError(ValueError):
    pass


def _reject_non_finite(value: float, context: str) -> None:
    if math.isnan(value):
        raise QuantizationError(f"{context}: value is NaN")
    if math.isinf(value):
        raise QuantizationError(f"{context}: value is infinite")


def clean_decimal(value: float, context: str = "value") -> Decimal:
    """Recovers the shortest decimal that round-trips to this exact
    float, removing binary representation noise without assuming any
    particular number of significant digits. Use for account
    balance/equity/margin, tick_value, contract_size -- anything without
    a symbol-specific digits/volume_step to quantize against.
    """

    _reject_non_finite(value, context)
    try:
        return Decimal(repr(value))
    except InvalidOperation as exc:
        raise QuantizationError(f"{context}: could not convert {value!r} to Decimal") from exc


def quantize_price(value: float, digits: int, context: str = "price") -> Decimal:
    """Quantizes a price to the symbol's `digits` decimal places.

    `digits=5` -> quantum `Decimal("0.00001")`. Starts from
    `clean_decimal` (not straight `Decimal(value)`, which would still
    carry the float's own binary noise into the quantize step) so
    rounding operates on the economically real value, not on artifacts.
    """

    if digits < 0:
        raise QuantizationError(f"{context}: digits must be >= 0, got {digits}")
    _reject_non_finite(value, context)
    raw = clean_decimal(value, context)
    quantum = Decimal(1).scaleb(-digits)
    return raw.quantize(quantum, rounding=ROUND_HALF_EVEN)


def quantize_volume(value: float, volume_step: float, context: str = "volume") -> Decimal:
    """Quantizes a volume/lot size to the symbol's `volume_step`
    granularity -- deliberately independent of `quantize_price`/digits,
    since lot-size granularity and price precision are unrelated
    properties of a symbol (see module docstring).
    """

    _reject_non_finite(value, context)
    _reject_non_finite(volume_step, f"{context}.volume_step")
    if volume_step <= 0:
        raise QuantizationError(f"{context}: volume_step must be positive, got {volume_step}")
    raw = clean_decimal(value, context)
    step = clean_decimal(volume_step, f"{context}.volume_step")
    # Quantize to the same number of decimal places as volume_step itself
    # (e.g. step=0.01 -> 2 decimal places), not by dividing/rounding to
    # a step multiple -- MT5 volumes are already step-aligned in
    # practice, and this only needs to strip float noise, not enforce
    # alignment (that belongs to order-placement validation, not here).
    exponent = step.normalize().as_tuple().exponent
    decimal_places = max(0, -exponent) if isinstance(exponent, int) else 0
    quantum = Decimal(1).scaleb(-decimal_places)
    return raw.quantize(quantum, rounding=ROUND_HALF_EVEN)
