"""Market-neutral backtest result data structures.

`Trade` and `BacktestResult` were originally defined inside
`src/backtesting/engine.py` (the crypto-era long/flat engine). They are
plain data containers with no dependency on that engine's simulation
logic, but `src/metrics/metrics.py` importing them from `engine.py`
meant metrics could never be used without dragging in a crypto-shaped
execution engine as an import-time dependency -- a problem once an
FX-specific engine (`src/fx/backtesting/engine.py`) needed to produce
results for the same metrics functions.

This module is the neutral home for those two types. `engine.py`
re-exports them unchanged (`from src.backtesting.models import Trade,
BacktestResult`) so every existing import of
`src.backtesting.engine.Trade`/`BacktestResult` keeps working exactly as
before -- this is a pure extraction, not a behavior or schema change.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    size_base: float  # quantity of the asset held (e.g. BTC)
    entry_notional: float  # quote-currency value committed at entry
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    net_pnl: float

    @property
    def total_fees(self) -> float:
        return self.entry_fee + self.exit_fee

    @property
    def return_pct(self) -> float:
        if self.entry_notional == 0:
            return 0.0
        return self.net_pnl / self.entry_notional


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame  # columns: timestamp, equity, position
    trades: list[Trade]
    initial_capital: float
    final_equity: float

    def trades_df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(
                columns=[
                    "entry_time", "entry_price", "exit_time", "exit_price",
                    "size_base", "entry_notional", "gross_pnl", "entry_fee",
                    "exit_fee", "net_pnl", "return_pct",
                ]
            )
        return pd.DataFrame(
            [
                {
                    "entry_time": t.entry_time,
                    "entry_price": t.entry_price,
                    "exit_time": t.exit_time,
                    "exit_price": t.exit_price,
                    "size_base": t.size_base,
                    "entry_notional": t.entry_notional,
                    "gross_pnl": t.gross_pnl,
                    "entry_fee": t.entry_fee,
                    "exit_fee": t.exit_fee,
                    "net_pnl": t.net_pnl,
                    "return_pct": t.return_pct,
                }
                for t in self.trades
            ]
        )
