"""FX single-symbol backtest engine (Phase 5B).

## Causality (Section 5)

The signal (`TargetPosition`) known as of bar i's close is applied
starting at bar i+1's OPEN -- identical in spirit to
`src/backtesting/engine.py`'s anti-lookahead rule, re-implemented here
independently because this engine's position model (LONG/SHORT/FLAT,
bid/ask fills, per-trade cost decomposition) is different enough that
bolting FX semantics onto the crypto engine via `if fx:` branches would
have produced exactly the unreadable hybrid the task explicitly warns
against.

`run()` takes `bars` (chronological `FxBar`s) and `signals` (a
same-length sequence of `TargetPosition`, one per bar, computed by the
caller using only `bars[:i+1]`). The engine itself enforces the one-bar
shift; a caller cannot skip it by construction, since the engine -- not
the caller -- decides which bar a signal fires on.

## Scope (Section 4)

FLAT/LONG/SHORT, one symbol, one position at a time, fixed lots. A
signal that asks to flip directly from LONG to SHORT (or vice versa) is
executed as an explicit close-then-open at the same bar's open price --
not a single netted fill -- so both legs are individually auditable as
ordinary `TradeResult`s.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.fx.backtesting.costs import (
    CommissionModel,
    NoSwap,
    RolloverSchedule,
    SlippageModel,
    SwapModel,
    SwapRequiredError,
)
from src.fx.backtesting.execution import compute_fill, reconstruct_bid_ask
from src.fx.backtesting.models import AccountState, Position, PositionSide, TargetPosition, TradeResult
from src.fx.backtesting.pnl import GrossPnlInputs, compute_gross_pnl
from src.fx.data.schema import FxBar


class InvalidLotsError(Exception):
    """Raised when configured lots violate the symbol's own
    volume_min/volume_max/volume_step (Section 9) -- never silently
    clamped."""


@dataclass(frozen=True)
class FxEngineConfig:
    symbol: str
    lots: Decimal
    contract_size: Decimal
    point: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    currency_profit: str | None
    account_currency: str | None
    initial_balance: Decimal
    commission_model: CommissionModel
    slippage_model: SlippageModel
    swap_model: SwapModel | None
    rollover_schedule: RolloverSchedule | None

    def __post_init__(self) -> None:
        if self.lots <= 0:
            raise InvalidLotsError(f"lots must be positive, got {self.lots}")
        if self.lots < self.volume_min or self.lots > self.volume_max:
            raise InvalidLotsError(
                f"lots ({self.lots}) outside [volume_min={self.volume_min}, volume_max={self.volume_max}]"
            )
        # Step conformance: (lots - volume_min) must be an integer multiple
        # of volume_step, within Decimal-exact arithmetic (no float epsilon
        # issues -- see src/execution/base.py's rationale for Decimal use).
        remainder = (self.lots - self.volume_min) % self.volume_step
        if remainder != 0:
            raise InvalidLotsError(
                f"lots ({self.lots}) does not conform to volume_step ({self.volume_step}) "
                f"from volume_min ({self.volume_min})"
            )
        if self.swap_model is None:
            raise ValueError(
                "swap_model must be configured explicitly -- pass NoSwap() to make 'zero overnight "
                "financing' a deliberate research assumption rather than a silent omission (Section 14)"
            )


@dataclass
class FxBacktestResult:
    trades: list[TradeResult]
    final_account: AccountState
    equity_curve: list[tuple[object, Decimal]]  # (timestamp_utc, equity)


class FxBacktestEngine:
    def __init__(self, config: FxEngineConfig) -> None:
        self.config = config

    def run(self, bars: Sequence[FxBar], signals: Sequence[TargetPosition]) -> FxBacktestResult:
        if len(bars) != len(signals):
            raise ValueError(f"bars length ({len(bars)}) must equal signals length ({len(signals)})")
        if len(bars) < 2:
            raise ValueError("need at least 2 bars to run a backtest (signal needs a next bar to execute on)")

        cfg = self.config
        balance = cfg.initial_balance
        realized_pnl = Decimal("0")
        position: Position | None = None
        accrued_swap = Decimal("0")
        trades: list[TradeResult] = []
        equity_curve: list[tuple[object, Decimal]] = []

        # Causal shift: the target position known as of bar i's close
        # becomes the position to hold starting at bar i+1's open. Bar 0
        # has no prior signal, so it starts FLAT -- identical rationale to
        # src/backtesting/engine.py's `signals.shift(1)`.
        shifted_targets: list[TargetPosition] = [TargetPosition.FLAT] + list(signals[:-1])

        open_bar_index: int | None = None

        for i in range(len(bars)):
            bar = bars[i]
            target = shifted_targets[i]

            if position is not None:
                prev_bar_time = bars[i - 1].timestamp_utc
                if cfg.rollover_schedule is not None:
                    crossings = cfg.rollover_schedule.crossings_between(prev_bar_time, bar.timestamp_utc)
                    for crossing in crossings:
                        accrued_swap += cfg.swap_model.charge_for_crossing(position.side, position.lots, crossing)
                elif not isinstance(cfg.swap_model, NoSwap) and bar.timestamp_utc.date() != prev_bar_time.date():
                    # A non-NoSwap model with no rollover_schedule cannot know
                    # WHEN to charge -- that combination is a configuration
                    # bug (Section 14), not a valid "no swap" research choice.
                    # NoSwap is exempt because it charges nothing regardless
                    # of when crossings occur.
                    raise SwapRequiredError(
                        f"position open across a day boundary ({prev_bar_time} -> {bar.timestamp_utc}) "
                        f"with swap_model={cfg.swap_model!r} but no rollover_schedule configured -- "
                        "either provide a RolloverSchedule or use NoSwap() explicitly"
                    )

            desired_side = {
                TargetPosition.LONG: PositionSide.LONG,
                TargetPosition.SHORT: PositionSide.SHORT,
                TargetPosition.FLAT: PositionSide.FLAT,
            }[target]

            current_side = position.side if position is not None else PositionSide.FLAT

            if current_side != desired_side:
                if position is not None:
                    trade = self._close(position, bar, i - (open_bar_index or i), accrued_swap)
                    trades.append(trade)
                    balance += trade.net_pnl
                    realized_pnl += trade.net_pnl
                    position = None
                    accrued_swap = Decimal("0")

                if desired_side is not PositionSide.FLAT:
                    position = self._open(desired_side, bar)
                    open_bar_index = i

            equity = balance
            if position is not None:
                equity = balance + self._unrealized_pnl(position, bar) - accrued_swap
            equity_curve.append((bar.timestamp_utc, equity))

        if position is not None:
            trade = self._close(
                position, bars[-1], len(bars) - 1 - (open_bar_index or len(bars) - 1), accrued_swap
            )
            trades.append(trade)
            balance += trade.net_pnl
            realized_pnl += trade.net_pnl
            position = None
            equity_curve[-1] = (bars[-1].timestamp_utc, balance)

        final_account = AccountState(
            initial_balance=cfg.initial_balance,
            balance=balance,
            realized_pnl=realized_pnl,
            position=position,
            equity=balance,
        )
        return FxBacktestResult(trades=trades, final_account=final_account, equity_curve=equity_curve)

    def _open(self, side: PositionSide, bar: FxBar) -> Position:
        cfg = self.config
        fill = compute_fill(side, True, bar.open, bar.spread_points, cfg.point, cfg.slippage_model)
        return Position(
            symbol=cfg.symbol,
            side=side,
            lots=cfg.lots,
            contract_size=cfg.contract_size,
            open_time=bar.timestamp_utc,
            entry_bid=fill.bid,
            entry_ask=fill.ask,
            entry_execution_price=fill.execution_price,
            entry_spread_points=bar.spread_points,
        )

    def _close(self, position: Position, bar: FxBar, bars_held: int, swap_cost: Decimal) -> TradeResult:
        cfg = self.config
        fill = compute_fill(position.side, False, bar.open, bar.spread_points, cfg.point, cfg.slippage_model)

        # Three PnL points along the same price move, from least to most
        # cost-adjusted, so spread/slippage fall out as exact differences
        # with nothing counted twice:
        #
        #   reference_pnl:    bid-to-bid, zero spread, zero slippage.
        #                     This is TradeResult.gross_pnl.
        #   spread_only_pnl:  correct bid/ask side (ask for LONG open /
        #                     SHORT close, bid otherwise), zero slippage.
        #   execution_pnl:    correct bid/ask side, WITH slippage applied
        #                     -- i.e. computed from the trade's actual fills.
        #
        # spread_cost    = reference_pnl - spread_only_pnl
        # slippage_cost  = spread_only_pnl - execution_pnl
        # net_pnl        = execution_pnl - commission_cost - swap already
        #                  deducted from balance mid-trade (see run())
        #                = reference_pnl - spread_cost - slippage_cost - commission_cost
        execution_pnl = compute_gross_pnl(
            GrossPnlInputs(
                side=position.side,
                entry_execution_price=position.entry_execution_price,
                exit_execution_price=fill.execution_price,
                lots=position.lots,
                contract_size=position.contract_size,
                currency_profit=cfg.currency_profit,
                account_currency=cfg.account_currency,
            )
        )

        entry_no_slip = reconstruct_bid_ask(position.entry_bid, position.entry_spread_points, cfg.point)
        exit_no_slip = reconstruct_bid_ask(fill.bid, bar.spread_points, cfg.point)
        entry_spread_only_price = entry_no_slip.ask if position.side is PositionSide.LONG else entry_no_slip.bid
        exit_spread_only_price = exit_no_slip.bid if position.side is PositionSide.LONG else exit_no_slip.ask

        reference_pnl = compute_gross_pnl(
            GrossPnlInputs(
                side=position.side,
                entry_execution_price=position.entry_bid,
                exit_execution_price=fill.bid,
                lots=position.lots,
                contract_size=position.contract_size,
                currency_profit=cfg.currency_profit,
                account_currency=cfg.account_currency,
            )
        )
        spread_only_pnl = compute_gross_pnl(
            GrossPnlInputs(
                side=position.side,
                entry_execution_price=entry_spread_only_price,
                exit_execution_price=exit_spread_only_price,
                lots=position.lots,
                contract_size=position.contract_size,
                currency_profit=cfg.currency_profit,
                account_currency=cfg.account_currency,
            )
        )
        spread_cost = reference_pnl - spread_only_pnl
        slippage_cost = spread_only_pnl - execution_pnl

        entry_commission = cfg.commission_model.cost_for_side(position.lots)
        exit_commission = cfg.commission_model.cost_for_side(position.lots)
        commission_cost = entry_commission + exit_commission

        net_pnl = reference_pnl - spread_cost - slippage_cost - commission_cost - swap_cost

        return TradeResult(
            symbol=position.symbol,
            side=position.side,
            lots=position.lots,
            open_time=position.open_time,
            close_time=bar.timestamp_utc,
            entry_execution_price=position.entry_execution_price,
            exit_execution_price=fill.execution_price,
            entry_bid=position.entry_bid,
            entry_ask=position.entry_ask,
            exit_bid=fill.bid,
            exit_ask=fill.ask,
            gross_pnl=reference_pnl,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            commission_cost=commission_cost,
            swap_cost=swap_cost,
            net_pnl=net_pnl,
            bars_held=max(bars_held, 1),
        )

    def _unrealized_pnl(self, position: Position, bar: FxBar) -> Decimal:
        """Mark-to-market using the conservative liquidation convention
        (Section 16): LONG marks at BID, SHORT marks at ASK -- the price
        at which the position could be closed on this bar, with no
        slippage applied (slippage is a fill-time cost, not a valuation
        convention)."""
        cfg = self.config
        bid_ask = reconstruct_bid_ask(bar.close, bar.spread_points, cfg.point)
        mark_price = bid_ask.bid if position.side is PositionSide.LONG else bid_ask.ask
        return compute_gross_pnl(
            GrossPnlInputs(
                side=position.side,
                entry_execution_price=position.entry_execution_price,
                exit_execution_price=mark_price,
                lots=position.lots,
                contract_size=position.contract_size,
                currency_profit=cfg.currency_profit,
                account_currency=cfg.account_currency,
            )
        )
