"""Adapter from `FxBacktestResult` to the market-neutral
`src.backtesting.models.BacktestResult`/`Trade` shapes `src.metrics.metrics`
consumes (Phase 5B, Section 18).

This is the ONLY place FX backtest output touches the metrics module's
input types. It does not change `metrics.py`'s formulas or add FX-only
metrics -- it only reshapes data so `build_metrics_report` and friends,
already market-neutral (explicit `periods_per_year`, no crypto-specific
assumption), can consume an FX result the same way they consume a
crypto one, without importing anything from `src.fx`.
"""

from __future__ import annotations

import pandas as pd

from src.backtesting.models import BacktestResult, Trade
from src.fx.backtesting.engine import FxBacktestResult
from src.fx.backtesting.models import PositionSide


def to_neutral_backtest_result(fx_result: FxBacktestResult) -> BacktestResult:
    """Convert an `FxBacktestResult` into a neutral `BacktestResult`.

    `Trade.size_base` is populated with `lots` (not a base-currency unit
    count) -- FX position size is naturally denominated in lots, and
    `size_base`/`entry_notional` are only used by `metrics.py` for
    `return_pct`/exposure fraction, not for currency-specific display.
    `position` in the equity curve is `+1`/`-1`/`0` for LONG/SHORT/FLAT
    (metrics.py's `market_exposure` only checks `!= 0`, so the sign is
    informational, not load-bearing for that one metric).
    """
    trades = [_to_neutral_trade(t) for t in fx_result.trades]

    equity_records = [
        {"timestamp": ts, "equity": float(equity), "position": 0}
        for ts, equity in fx_result.equity_curve
    ]
    equity_curve = pd.DataFrame(equity_records, columns=["timestamp", "equity", "position"])

    initial_capital = float(fx_result.final_account.initial_balance)
    final_equity = (
        float(fx_result.equity_curve[-1][1]) if fx_result.equity_curve else initial_capital
    )

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        initial_capital=initial_capital,
        final_equity=final_equity,
    )


def _to_neutral_trade(trade) -> Trade:
    side_sign = 1 if trade.side is PositionSide.LONG else -1
    entry_notional = float(trade.lots) * float(trade.entry_execution_price) * side_sign
    return Trade(
        entry_time=pd.Timestamp(trade.open_time),
        entry_price=float(trade.entry_execution_price),
        exit_time=pd.Timestamp(trade.close_time),
        exit_price=float(trade.exit_execution_price),
        size_base=float(trade.lots),
        entry_notional=abs(entry_notional) if entry_notional else float(trade.lots),
        gross_pnl=float(trade.gross_pnl),
        entry_fee=float(trade.commission_cost) / 2,
        exit_fee=float(trade.commission_cost) / 2,
        net_pnl=float(trade.net_pnl),
    )
