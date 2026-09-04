"""Real-bridge MT5 PnL oracle validation (Phase 5B, Section 21).

Read-only: `/v1/profit-calc/{symbol}` wraps `MetaTrader5.order_calc_profit()`,
which computes a hypothetical profit and creates no order, deal, or
position. Marked `requires_real_mt5` and self-skipping, exactly like
`tests/fx/test_time_diagnostics_integration.py` -- see that module's
docstring for the run instructions this one shares.

NOTE: this endpoint was added to `mt5_bridge/app.py` in the same change
as this test. `mt5_bridge/` is deployed to the Windows VM by manual
copy (see README/FX_PHASE0_STATUS.md) -- until the updated package is
copied there and the bridge restarted, the real bridge will 404 on this
path (it predates the endpoint), which surfaces here as an
`ExecutionRequestError`, not a skip. See PHASE5B_STATUS.md's MT5 oracle
section for the current deployment status of this specific endpoint.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.requires_real_mt5


def _real_client():
    bridge_url = os.environ.get("MT5_REMOTE_URL")
    token = os.environ.get("MT5_REMOTE_TOKEN")
    if not bridge_url or not token:
        pytest.skip("MT5_REMOTE_URL/MT5_REMOTE_TOKEN not set")

    from src.execution.mt5_remote import ExecutionClientError, MT5RemoteExecutionClient, RemoteConfig

    config = RemoteConfig(bridge_url=bridge_url, api_token=token, timeout_seconds=10.0)
    client = MT5RemoteExecutionClient(config)
    try:
        client.health()
    except ExecutionClientError as exc:
        pytest.skip(f"bridge configured but unreachable: {exc}")
    return client


@pytest.mark.parametrize(
    "side_name,price_open,price_close",
    [
        ("BUY", "1.10000", "1.10500"),  # LONG gain
        ("BUY", "1.10000", "1.09500"),  # LONG loss
        ("SELL", "1.10000", "1.09500"),  # SHORT gain
        ("SELL", "1.10000", "1.10500"),  # SHORT loss
    ],
)
def test_real_eurusd_profit_calc_matches_local_pnl_formula(side_name, price_open, price_close):
    """Compare this project's own gross-PnL formula
    (`src.fx.backtesting.pnl.compute_gross_pnl`) against MT5's own
    `order_calc_profit` oracle for a deterministic 0.01-lot EURUSD
    scenario. No order is placed -- both sides are pure calculations."""
    from src.execution.base import Side
    from src.fx.backtesting.models import PositionSide
    from src.fx.backtesting.pnl import GrossPnlInputs, compute_gross_pnl

    client = _real_client()
    side = Side.BUY if side_name == "BUY" else Side.SELL
    position_side = PositionSide.LONG if side_name == "BUY" else PositionSide.SHORT
    volume = Decimal("0.01")

    oracle_profit = client.profit_calc(
        "EURUSD", side, volume, Decimal(price_open), Decimal(price_close)
    )
    local_profit = compute_gross_pnl(
        GrossPnlInputs(
            side=position_side,
            entry_execution_price=Decimal(price_open),
            exit_execution_price=Decimal(price_close),
            lots=volume,
            contract_size=Decimal("100000"),
            currency_profit="USD",
            account_currency="USD",
        )
    )
    print(f"\n{side_name} {price_open}->{price_close}: oracle={oracle_profit} local={local_profit}")
    assert abs(oracle_profit - local_profit) < Decimal("0.01")
