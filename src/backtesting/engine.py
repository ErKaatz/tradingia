"""Backtest engine.

Design goals, in priority order: correctness, auditability, no lookahead —
NOT speed. The loop below is an explicit bar-by-bar simulation rather than a
vectorized one-liner, specifically so every trade can be traced back to the
exact bar and price that produced it.

## Execution model (read this before trusting any result)

1. A strategy produces a signal for bar i using data available up to and
   including bar i's close (see strategies/base.py).
2. The engine NEVER executes at the price that generated the signal. The
   signal computed as of bar i's close is applied starting at bar i+1's
   OPEN. This is the single most important anti-lookahead rule in this
   codebase: a strategy cannot "buy the close that told it to buy."
3. Slippage is modeled as a fixed fractional cost applied against the
   trader on both entry and exit: buys execute at open * (1 + slippage),
   sells execute at open * (1 - slippage). This is a simplification (real
   slippage depends on order size and book depth) but it is a documented,
   conservative, deterministic assumption rather than an unstated one.
4. Fees are a percentage of notional value, charged on both entry and exit.
5. Only two states exist: FLAT (no position) and LONG (fully invested,
   position size given by `position_size_fraction` of current equity at the
   time of entry). No shorting, no leverage, no partial scaling in/out.

## What this engine deliberately does NOT do

- No shorting or leverage (explicitly out of scope for this phase).
- No partial fills, no order book simulation, no market impact beyond the
  flat slippage assumption above.
- No intrabar fills (a signal to exit does not get a better price by
  peeking at the bar's low/high).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.strategies.base import FLAT, LONG


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


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    trading_fee: float = 0.001  # fraction of notional, e.g. 0.001 = 0.1%
    slippage: float = 0.0002  # fraction of price, applied against the trader
    position_size_fraction: float = 1.0  # fraction of equity committed per trade


class BacktestEngine:
    """Runs a single-asset, long/flat-only backtest bar by bar."""

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()

    def run(self, df: pd.DataFrame, signals: pd.Series) -> BacktestResult:
        """Run the backtest.

        `df` must be OHLCV data sorted ascending by timestamp with columns
        timestamp/open/high/low/close/volume. `signals` must be the same
        length and index as `df`, containing FLAT/LONG produced by a
        Strategy using only trailing information.

        The signal at row i is applied starting at row i+1's open — this
        shift happens inside this method, not in the strategy, so it cannot
        be skipped by accident.
        """
        if len(df) != len(signals):
            raise ValueError("df and signals must have the same length")
        if len(df) < 2:
            raise ValueError("need at least 2 bars to run a backtest")

        cfg = self.config
        # Shift signals forward by one bar: the decision known at bar i's
        # close becomes the *target position* for bar i+1. Bar 0 has no
        # prior signal, so it starts flat.
        target_position = signals.shift(1).fillna(FLAT).astype(int)

        cash = cfg.initial_capital
        position_state = FLAT
        size_base = 0.0
        entry_price = 0.0
        entry_time = None
        entry_notional = 0.0
        entry_fee = 0.0

        equity_records = []
        trades: list[Trade] = []

        timestamps = df["timestamp"].to_numpy()
        opens = df["open"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        targets = target_position.to_numpy()

        for i in range(len(df)):
            want_long = targets[i] == LONG

            # Enter at this bar's open if we're flat but should be long.
            if position_state == FLAT and want_long:
                fill_price = opens[i] * (1 + cfg.slippage)
                notional = cash * cfg.position_size_fraction
                fee = notional * cfg.trading_fee
                size_base = (notional - fee) / fill_price

                position_state = LONG
                entry_price = fill_price
                entry_time = timestamps[i]
                entry_notional = notional
                entry_fee = fee
                cash -= notional

            # Exit at this bar's open if we're long but should be flat.
            elif position_state == LONG and not want_long:
                fill_price = opens[i] * (1 - cfg.slippage)
                proceeds = size_base * fill_price
                fee = proceeds * cfg.trading_fee
                net_proceeds = proceeds - fee

                gross_pnl = (fill_price - entry_price) * size_base
                net_pnl = net_proceeds - entry_notional

                trades.append(
                    Trade(
                        entry_time=pd.Timestamp(entry_time),
                        entry_price=entry_price,
                        exit_time=pd.Timestamp(timestamps[i]),
                        exit_price=fill_price,
                        size_base=size_base,
                        entry_notional=entry_notional,
                        gross_pnl=gross_pnl,
                        entry_fee=entry_fee,
                        exit_fee=fee,
                        net_pnl=net_pnl,
                    )
                )

                cash += net_proceeds
                position_state = FLAT
                size_base = 0.0
                entry_price = 0.0
                entry_time = None
                entry_notional = 0.0
                entry_fee = 0.0

            # Mark-to-market equity using this bar's close.
            mark_price = closes[i]
            position_value = size_base * mark_price if position_state == LONG else 0.0
            equity = cash + position_value

            equity_records.append(
                {
                    "timestamp": timestamps[i],
                    "equity": equity,
                    "position": position_state,
                }
            )

        # If still holding at the end of the data, force-close at the last
        # close price so PnL/equity are fully realized and auditable. This
        # is a documented end-of-backtest assumption, not a mid-run rule.
        if position_state == LONG:
            fill_price = closes[-1] * (1 - cfg.slippage)
            proceeds = size_base * fill_price
            fee = proceeds * cfg.trading_fee
            net_proceeds = proceeds - fee

            gross_pnl = (fill_price - entry_price) * size_base
            net_pnl = net_proceeds - entry_notional

            trades.append(
                Trade(
                    entry_time=pd.Timestamp(entry_time),
                    entry_price=entry_price,
                    exit_time=pd.Timestamp(timestamps[-1]),
                    exit_price=fill_price,
                    size_base=size_base,
                    entry_notional=entry_notional,
                    gross_pnl=gross_pnl,
                    entry_fee=entry_fee,
                    exit_fee=fee,
                    net_pnl=net_pnl,
                )
            )
            cash += net_proceeds
            equity_records[-1]["equity"] = cash
            equity_records[-1]["position"] = FLAT

        equity_curve = pd.DataFrame(equity_records)
        final_equity = equity_curve["equity"].iloc[-1]

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            initial_capital=cfg.initial_capital,
            final_equity=final_equity,
        )
