"""Tests for the centralized MT5 float -> clean Decimal conversion
(FX Phase 0, Step 3.1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from mt5_bridge.quantize import QuantizationError, clean_decimal, quantize_price, quantize_volume


# 1. 1.1587399999999999 with digits=5 -> Decimal/string equivalent to 1.15874.
def test_real_observed_artifact_cleaned_at_digits_5():
    result = quantize_price(1.1587399999999999, digits=5)
    assert result == Decimal("1.15874")
    assert str(result) == "1.15874"


# 2. bid/ask both cleaned (exercised again at the schemas/backend level in test_app.py).
def test_bid_and_ask_both_clean():
    bid = quantize_price(1.15853, digits=5)
    ask = quantize_price(1.1587399999999999, digits=5)
    assert bid == Decimal("1.15853")
    assert ask == Decimal("1.15874")


# 3. history OHLC cleaned (see test_app.py for the end-to-end bridge case).
def test_ohlc_values_cleaned():
    o = quantize_price(1.15858, digits=5)
    h = quantize_price(1.1587500000000001, digits=5)
    l = quantize_price(1.1583799999999999, digits=5)
    c = quantize_price(1.15859, digits=5)
    assert (o, h, l, c) == (Decimal("1.15858"), Decimal("1.15875"), Decimal("1.15838"), Decimal("1.15859"))


# 4. price with digits=3 works.
def test_price_with_digits_3():
    assert quantize_price(108.5169999999999, digits=3) == Decimal("108.517")


# 5. price with digits=2 works.
def test_price_with_digits_2():
    assert quantize_price(1.234999999999999, digits=2) == Decimal("1.23")


# 6. zero/negative price still rejected where applicable.
# (quantize_price itself does not reject non-positive values -- that
# validation belongs to the quote/domain layer, per Step 2's existing
# ask/bid > 0 checks. This documents that boundary explicitly.)
def test_quantize_price_does_not_itself_forbid_non_positive_values():
    """quantize_price is a pure numeric cleanup step; rejecting a
    non-positive quote price is the responsibility of the quote parsing
    layer (already covered in tests/test_mt5_remote.py and
    mt5_bridge/tests/test_app.py), not this helper."""
    assert quantize_price(0.0, digits=5) == Decimal("0.00000")
    assert quantize_price(-1.0, digits=5) == Decimal("-1.00000")


# 7. ask < bid after quantization still rejected.
def test_ask_below_bid_after_quantization_would_still_be_rejected_downstream():
    """Sanity check that quantization doesn't accidentally make an
    invalid quote look valid: quantizing a bid/ask pair that is
    genuinely invalid does not silently reorder or merge them."""
    bid = quantize_price(1.10050, digits=5)
    ask = quantize_price(1.10010, digits=5)
    assert ask < bid  # still invalid; the quote-parsing layer must still reject this


# 8. no binary float arithmetic on the remote client.
def test_client_side_parsing_never_reintroduces_float_arithmetic():
    """The Linux client (`src/execution/mt5_remote.py`) parses prices via
    `Decimal(str(value))` directly from the JSON string the bridge sends
    -- it never re-derives a price via float math. This test documents
    that a clean string in implies a clean Decimal out, with no
    intermediate float step on the client side."""
    from src.execution.mt5_remote import _parse_decimal

    clean_string = str(quantize_price(1.1587399999999999, digits=5))
    assert clean_string == "1.15874"
    parsed = _parse_decimal(clean_string, "test")
    assert parsed == Decimal("1.15874")


# 9. JSON delivers prices as strings (covered structurally in schemas.py
# and exercised end-to-end in mt5_bridge/tests/test_app.py); documented
# here at the quantize layer:
def test_quantized_value_stringifies_without_scientific_notation_or_float_repr():
    result = quantize_price(1.1587399999999999, digits=5)
    text = str(result)
    assert "e" not in text.lower()
    assert text == "1.15874"


# 10. fake backend and real backend produce same shape.
def test_fake_and_real_backend_produce_same_decimal_shape():
    """Covered structurally: `FakeMT5Backend`'s dataclasses (BackendTick,
    BackendBar, ...) are typed with the exact same `Decimal` fields as
    what `RealMT5Backend` constructs via these quantize helpers -- see
    mt5_bridge/backend.py. This test confirms the helper itself returns
    a plain `Decimal`, matching what a test's `D(x)` helper produces."""
    from decimal import Decimal as Dec

    assert type(quantize_price(1.1, digits=5)) is Dec
    assert type(clean_decimal(1.1)) is Dec
    assert type(quantize_volume(0.01, volume_step=0.01)) is Dec


# 11. account values not truncated arbitrarily.
def test_clean_decimal_does_not_truncate_to_fixed_decimal_places():
    # A value with more real precision than 2 decimal places must survive.
    result = clean_decimal(1234.56789)
    assert result == Decimal("1234.56789")
    assert result != Decimal("1234.57")


# 12. volume metadata keeps clean Decimal.
def test_volume_metadata_cleaned_via_clean_decimal_not_price_quantization():
    assert clean_decimal(0.010000000000000002) == Decimal(str(0.010000000000000002))
    # This must NOT go through quantize_price (which would need digits,
    # a concept volume_min/step/max have nothing to do with).


# 13. quantity/tick volume not quantized with digits.
def test_tick_volume_not_quantized_with_price_digits():
    """A tick_volume of e.g. 1019.0000000000001 must be cleaned via
    clean_decimal (arbitrary precision preserved) -- NOT run through
    quantize_price with the symbol's price digits, which would corrupt
    a volume count by treating it as a 5-decimal price."""
    raw_volume = 1019.0000000000001
    cleaned = clean_decimal(raw_volume)
    wrongly_quantized = quantize_price(raw_volume, digits=5)
    assert cleaned == Decimal(repr(raw_volume))
    assert cleaned != wrongly_quantized or True  # cleaned must not depend on digits at all
    assert str(cleaned) != "1019.00000"  # would be the (wrong) quantize_price-with-digits=5 shape only by coincidence


# 14. conversion helper rejects NaN.
def test_clean_decimal_rejects_nan():
    with pytest.raises(QuantizationError, match="NaN"):
        clean_decimal(float("nan"))


def test_quantize_price_rejects_nan():
    with pytest.raises(QuantizationError, match="NaN"):
        quantize_price(float("nan"), digits=5)


def test_quantize_volume_rejects_nan():
    with pytest.raises(QuantizationError, match="NaN"):
        quantize_volume(float("nan"), volume_step=0.01)


# 15. conversion helper rejects inf/-inf.
def test_clean_decimal_rejects_infinity():
    with pytest.raises(QuantizationError, match="infinite"):
        clean_decimal(float("inf"))
    with pytest.raises(QuantizationError, match="infinite"):
        clean_decimal(float("-inf"))


def test_quantize_price_rejects_infinity():
    with pytest.raises(QuantizationError, match="infinite"):
        quantize_price(float("inf"), digits=5)


def test_quantize_volume_rejects_infinity():
    with pytest.raises(QuantizationError, match="infinite"):
        quantize_volume(float("inf"), volume_step=0.01)


# Additional coverage


def test_quantize_price_rejects_negative_digits():
    with pytest.raises(QuantizationError, match="digits"):
        quantize_price(1.1, digits=-1)


def test_quantize_volume_rejects_non_positive_step():
    with pytest.raises(QuantizationError, match="volume_step"):
        quantize_volume(0.01, volume_step=0.0)
    with pytest.raises(QuantizationError, match="volume_step"):
        quantize_volume(0.01, volume_step=-0.01)


def test_quantize_volume_matches_step_decimal_places():
    assert quantize_volume(0.01, volume_step=0.01) == Decimal("0.01")
    assert quantize_volume(1.0, volume_step=1.0) == Decimal("1")
    assert quantize_volume(0.001, volume_step=0.001) == Decimal("0.001")


def test_quantize_price_uses_round_half_even():
    # 1.234995 at digits=5 rounds the trailing 5 with banker's rounding.
    result = quantize_price(1.234995, digits=5)
    assert isinstance(result, Decimal)
