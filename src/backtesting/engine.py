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

## Warm-up rows and `evaluation_start`

`df`/`signals` passed to `run()` may include leading rows that exist only
to let a strategy's indicators warm up (see `strategies/base.py`'s
`warmup_bars` and `experiments/runner.py`). Pass the index where the actual
evaluated period begins as `evaluation_start`. Rows before it:

- still have signals computed on them and still affect `target_position`
  (via the one-bar shift), so a signal born in the last warm-up bar can
  still trigger a real entry at `evaluation_start`'s open — this is correct
  and intended, not a bug;
- can NEVER themselves hold an open position, be entered, or be exited: the
  engine forces FLAT for the entire warm-up region regardless of what the
  (shifted) signal says, so the "independent split evaluation" semantics
  (each split starts flat with its own initial capital — see
  experiments/runner.py) hold exactly at `evaluation_start`;
- are excluded from the returned equity curve and trade log entirely.

With the default `evaluation_start=0` there is no warm-up region and this
reduces to the original behavior.

## What this engine deliberately does NOT do

- No shorting or leverage (explicitly out of scope for this phase).
- No partial fills, no order book simulation, no market impact beyond the
  flat slippage assumption above.
- No intrabar fills (a signal to exit does not get a better price by
  peeking at the bar's low/high).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.data.validation import validate_ohlcv
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

    def run(
        self, df: pd.DataFrame, signals: pd.Series, evaluation_start: int = 0
    ) -> BacktestResult:
        """Run the backtest.

        `df` must be OHLCV data sorted ascending by timestamp with columns
        timestamp/open/high/low/close/volume. `signals` must be the same
        length and index as `df`, containing FLAT/LONG produced by a
        Strategy using only trailing information.

        The signal at row i is applied starting at row i+1's open — this
        shift happens inside this method, not in the strategy, so it cannot
        be skipped by accident.

        `evaluation_start` marks the first row that counts as the actual
        evaluated period; rows before it are warm-up-only context (see the
        module docstring's "Warm-up rows and evaluation_start" section).
        """
        _validate_ohlcv_for_engine(df)
        _validate_signals(signals, expected_len=len(df))

        if len(df) < 2:
            raise ValueError("need at least 2 bars to run a backtest")
        if not (0 <= evaluation_start < len(df)):
            raise ValueError(
                f"evaluation_start ({evaluation_start}) must be within [0, {len(df) - 1}]"
            )

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
            # During warm-up, the position is forced flat regardless of the
            # (shifted) signal: warm-up bars exist only so indicators have
            # enough trailing history by `evaluation_start`, not to trade on.
            want_long = targets[i] == LONG and i >= evaluation_start

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
        # Warm-up bars are context for indicators only; they never held a
        # position (enforced above) and must not appear in the reported
        # equity curve, exposure, or drawdown for this split.
        equity_curve = equity_curve.iloc[evaluation_start:].reset_index(drop=True)
        final_equity = equity_curve["equity"].iloc[-1]

        # By construction no trade can open before evaluation_start (want_long
        # is forced False there), so every trade's entry_time already falls
        # within the evaluated period — nothing to filter here, but assert it
        # to fail loudly if that invariant is ever broken by a future change.
        if trades:
            eval_start_time = df["timestamp"].iloc[evaluation_start]
            assert all(t.entry_time >= eval_start_time for t in trades), (
                "internal invariant violated: a trade opened during warm-up"
            )

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            initial_capital=cfg.initial_capital,
            final_equity=final_equity,
        )


def _validate_ohlcv_for_engine(df: pd.DataFrame) -> None:
    """Structural OHLCV validation the engine always performs, regardless of
    caller. Time-gap policy is deliberately NOT enforced here (the engine
    doesn't know the intended timeframe or whether gaps are acceptable for
    this dataset) — that is `src/data/validation.py`'s `validate_ohlcv`
    with an explicit `timeframe`/`allow_gaps`, run upstream by the
    experiment runner. This call only catches structurally impossible data
    (NaNs, non-monotonic timestamps, negative prices, high < low, ...) that
    would silently corrupt any backtest.
    """
    result = validate_ohlcv(df, timeframe=None, allow_gaps=True)
    result.raise_if_invalid()


def _validate_signals(signals: pd.Series, expected_len: int) -> None:
    if len(signals) != expected_len:
        raise ValueError(
            f"signals length ({len(signals)}) does not match data length ({expected_len})"
        )
    if signals.isna().any():
        n_nan = int(signals.isna().sum())
        raise ValueError(f"signals contain {n_nan} NaN value(s); expected only FLAT/LONG")

    values = signals.to_numpy()
    if not np.issubdtype(values.dtype, np.integer):
        # Allow float series that hold only whole FLAT/LONG values (e.g.
        # produced by arithmetic on an int series), but reject anything with
        # a fractional part — that's not a valid position state.
        if not np.all(np.equal(np.mod(values, 1), 0)):
            raise ValueError("signals must contain only integer FLAT/LONG values, found fractional values")

    allowed = {FLAT, LONG}
    invalid_values = set(int(v) for v in values) - allowed
    if invalid_values:
        raise ValueError(
            f"signals contain values outside {{FLAT={FLAT}, LONG={LONG}}}: {sorted(invalid_values)}"
        )
