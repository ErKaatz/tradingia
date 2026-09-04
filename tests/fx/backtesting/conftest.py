from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.fx.backtesting.costs import NoCommission, NoSwap, ZeroSlippage
from src.fx.backtesting.engine import FxEngineConfig
from src.fx.data.schema import FxBar


def make_bar(t: datetime, o: float, h: float, l: float, c: float, spread: int = 10) -> FxBar:
    return FxBar(
        timestamp_utc=t,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        tick_volume=Decimal("100"),
        real_volume=None,
        spread_points=spread,
    )


def make_bars(prices: list[float], start: datetime | None = None, spread: int = 10, step_hours: int = 1) -> list[FxBar]:
    """Build a chronological sequence of flat-ish bars (open==close==given
    price, tight high/low) so tests only need to reason about one price
    per bar. `high`/`low` are widened by 1 pip to keep FxBar's OHLC
    invariants satisfied without affecting execution (execution always
    uses `open`, never high/low -- see execution.py)."""
    t0 = start or datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    bars = []
    for i, price in enumerate(prices):
        t = t0 + timedelta(hours=step_hours * i)
        bars.append(make_bar(t, price, price + 0.0005, price - 0.0005, price, spread=spread))
    return bars


@pytest.fixture
def base_config_kwargs():
    return dict(
        symbol="EURUSD",
        lots=Decimal("0.01"),
        contract_size=Decimal("100000"),
        point=Decimal("0.00001"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("60"),
        volume_step=Decimal("0.01"),
        currency_profit="USD",
        account_currency="USD",
        initial_balance=Decimal("1000"),
        commission_model=NoCommission(),
        slippage_model=ZeroSlippage(),
        swap_model=NoSwap(),
        rollover_schedule=None,
    )


@pytest.fixture
def make_config(base_config_kwargs):
    def _make(**overrides):
        kwargs = dict(base_config_kwargs)
        kwargs.update(overrides)
        return FxEngineConfig(**kwargs)

    return _make
