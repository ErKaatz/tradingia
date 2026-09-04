from __future__ import annotations

from decimal import Decimal

import pytest

from src.fx.backtesting.engine import FxEngineConfig, InvalidLotsError


def test_valid_lots_at_minimum(make_config):
    make_config(lots=Decimal("0.01"))  # must not raise


def test_valid_lots_on_step(make_config):
    make_config(lots=Decimal("0.05"))  # must not raise


def test_below_minimum_rejected(make_config):
    with pytest.raises(InvalidLotsError):
        make_config(lots=Decimal("0.001"))


def test_invalid_step_rejected(make_config):
    with pytest.raises(InvalidLotsError):
        make_config(lots=Decimal("0.015"))


def test_above_maximum_rejected(make_config):
    with pytest.raises(InvalidLotsError):
        make_config(lots=Decimal("100"))


def test_zero_or_negative_lots_rejected(make_config):
    with pytest.raises(InvalidLotsError):
        make_config(lots=Decimal("0"))
    with pytest.raises(InvalidLotsError):
        make_config(lots=Decimal("-0.01"))
