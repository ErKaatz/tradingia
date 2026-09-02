"""POST-HOC SHORT-HORIZON RESEARCH — cost/execution model for Phase 4A.

Short-horizon strategies (15m/1h, higher turnover) are far more sensitive
to execution costs than the slow strategies studied so far: the same
fixed per-trade cost is amortized over a much smaller expected move. This
module does not change `BacktestEngine` (its execution model -- signal at
bar i executed at bar i+1's open, no intrabar fills, no lookahead -- is
already correct and used by every prior phase). It adds an explicit,
conservative cost-scenario layer on top of it, appropriate for the higher
trade frequency this phase investigates.

## How spread is modeled

`BacktestEngine.run()` has exactly one execution-cost parameter besides the
fee: `slippage`, a fractional cost applied against the trader at the open
of execution (buys at `open*(1+slippage)`, sells at `open*(1-slippage)`).
The engine does not have a separate "spread" concept, and this phase does
NOT modify the engine to add one -- that would risk destabilizing every
already-frozen phase built on top of it (Phase 2 through Phase 3B).

Economically, a bid-ask spread and price slippage have an IDENTICAL effect
on a market order's realized execution price: both push the fill away from
the reference price in the trader's disfavor. This module therefore models
spread as an ADDITIVE component of the single `slippage` parameter passed
to `BacktestConfig`: `effective_slippage = slippage + half_spread_fraction`
(half the round-trip spread, since the engine already applies the fee/
slippage cost independently on both entry and exit). This is a
documented, deliberately conservative simplification -- not a claim that
spread and slippage are the same underlying market phenomenon, only that
their effect on this engine's single execution-price adjustment is
equivalent and can be combined without changing engine code.

## Maker/taker

This phase assumes taker (market) execution throughout -- the engine's
"execute at next bar's open" model IS a market order, definitionally. A
maker (resting limit order) model would need to simulate whether a limit
order would have filled at all within the bar, which requires either
intrabar path data this project does not have, or speculative assumptions
about fill probability -- both of which the project's stated principle of
"no market impact modeling without order-book data" (see README) rules
out. So maker execution is NOT modeled as a lower-cost alternative here;
every scenario below assumes taker-only fees, which is the conservative
(higher-cost) assumption for a strategy that always crosses the spread.

## Minimum latency

Every strategy in this phase inherits the engine's structural one-bar
latency (signal known at bar i's close, executed at bar i+1's open) unless
a strategy causally defines something slower (e.g. a confirmation delay).
No strategy in this phase may execute faster than that -- there is no
"same-bar" execution path in `BacktestEngine`, and this phase does not add
one.

## Turnover penalty

Fee and slippage are already charged per round-trip trade (once on entry,
once on exit) proportional to notional, which is inherently a turnover
penalty: a strategy with N trades pays roughly N times the round-trip
cost of a strategy with 1 trade, all else equal. This module does not add
a SEPARATE turnover penalty on top of that (which would double-count), but
`build_cost_report` (see below) surfaces `total_fees`, `total_slippage_cost`,
`cost_drag`, and `trades_per_year` so a high-turnover strategy's cost burden
is always visible and comparable across scenarios (Task 13).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backtesting.engine import BacktestConfig, BacktestResult


@dataclass(frozen=True)
class ShortHorizonCostScenario:
    name: str
    trading_fee: float
    half_spread: float
    slippage: float

    @property
    def effective_slippage(self) -> float:
        """The single fractional cost passed to BacktestConfig.slippage:
        half the round-trip spread plus the modeled slippage, since fee and
        this effective_slippage are each charged independently on both
        entry and exit by the engine.
        """
        return self.half_spread + self.slippage

    def to_backtest_config(self, initial_capital: float = 10_000.0, position_size_fraction: float = 1.0) -> BacktestConfig:
        return BacktestConfig(
            initial_capital=initial_capital,
            trading_fee=self.trading_fee,
            slippage=self.effective_slippage,
            position_size_fraction=position_size_fraction,
        )


# Four cost scenarios, calibrated to be conservative for a liquid spot pair
# (BTC/USDT) at 15m/1h -- not fit to make any Phase-4A strategy look good.
#
# Basis for the numbers (documented, not invented ad hoc):
# - BTC/USDT spot taker fee on major venues commonly ranges ~0.02%-0.10%
#   depending on volume tier; this project has used 0.10% (0.001) as its
#   fee assumption since Phase 1, so scenarios keep that as the BASE fee
#   and vary it up/down around that anchor rather than introducing a new
#   unrelated number.
# - BTC/USDT spot spread on major venues is typically a very small
#   fraction of a percent in normal conditions but widens materially in
#   stress; the half-spread values below span "tight/normal" to "wide"
#   conditions.
# - Slippage beyond spread (price impact of the order itself, latency
#   drift) is modeled as a small additional fractional cost, consistent
#   with this project's existing 0.0002 baseline slippage assumption
#   (Phase 1 README), scaled up for the SEVERE scenario.
SHORT_HORIZON_COST_SCENARIOS = [
    ShortHorizonCostScenario(
        name="A_optimistic_but_realistic",
        trading_fee=0.0005,   # 0.05%: bottom of typical taker fee tiers
        half_spread=0.0001,   # 0.01%: tight spread, calm/liquid conditions
        slippage=0.0001,      # 0.01%: minimal additional impact/latency drift
    ),
    ShortHorizonCostScenario(
        name="B_base",
        trading_fee=0.001,    # 0.10%: this project's baseline fee since Phase 1
        half_spread=0.0002,   # 0.02%: normal spread conditions
        slippage=0.0002,      # 0.02%: this project's baseline slippage since Phase 1
    ),
    ShortHorizonCostScenario(
        name="C_conservative",
        trading_fee=0.0015,   # 0.15%: above-tier fee or less favorable venue
        half_spread=0.0005,   # 0.05%: wider spread, moderate stress
        slippage=0.0005,      # 0.05%: more noticeable impact/latency drift
    ),
    ShortHorizonCostScenario(
        name="D_severe",
        trading_fee=0.002,    # 0.20%: retail/unfavorable fee tier
        half_spread=0.0015,   # 0.15%: stressed/thin liquidity spread
        slippage=0.001,       # 0.10%: material adverse execution drift
    ),
]

SHORT_HORIZON_SCENARIO_BY_NAME = {s.name: s for s in SHORT_HORIZON_COST_SCENARIOS}


@dataclass(frozen=True)
class CostReport:
    scenario: str
    num_trades: int
    years_evaluated: float
    trades_per_year: float
    trades_per_month: float
    total_fees: float
    total_slippage_cost: float
    total_cost: float
    cost_per_trade: float
    gross_expectancy: float
    net_expectancy: float
    cost_drag: float
    gross_return: float
    net_return: float


def build_cost_report(
    scenario: ShortHorizonCostScenario, result: BacktestResult, years_evaluated: float
) -> CostReport:
    """Task 13: turnover and cost-drag reporting for one backtest result
    under one named cost scenario.

    `Trade.entry_price`/`exit_price` are already-adjusted fill prices
    (`raw_open * (1 +/- effective_slippage)`), so the raw (zero-slippage)
    open is recovered algebraically from the scenario's own
    `effective_slippage` -- this does not re-run the backtest at zero cost,
    which avoids any risk of a "gross" run following a different signal
    path than the "net" one (a strategy's own signal never depends on
    price, only on the OHLCV series, so this algebraic recovery is exact,
    not an approximation).
    """
    trades = result.trades
    num_trades = len(trades)
    s = scenario.effective_slippage

    total_fees = sum(t.total_fees for t in trades)

    total_slippage_cost = 0.0
    gross_pnl_total = 0.0
    for t in trades:
        raw_entry_open = t.entry_price / (1 + s) if (1 + s) != 0 else t.entry_price
        raw_exit_open = t.exit_price / (1 - s) if (1 - s) != 0 else t.exit_price
        entry_slippage_cost = t.size_base * (t.entry_price - raw_entry_open)
        exit_slippage_cost = t.size_base * (raw_exit_open - t.exit_price)
        total_slippage_cost += entry_slippage_cost + exit_slippage_cost
        # Gross of BOTH fees and slippage: PnL at raw (unadjusted) prices.
        gross_pnl_total += (raw_exit_open - raw_entry_open) * t.size_base

    net_pnl_total = sum(t.net_pnl for t in trades)
    total_cost = total_fees + total_slippage_cost

    cost_per_trade = total_cost / num_trades if num_trades else 0.0
    gross_expectancy = gross_pnl_total / num_trades if num_trades else 0.0
    net_expectancy = net_pnl_total / num_trades if num_trades else 0.0

    gross_return = gross_pnl_total / result.initial_capital
    net_return = (result.final_equity / result.initial_capital) - 1.0
    cost_drag = gross_return - net_return

    trades_per_year = num_trades / years_evaluated if years_evaluated > 0 else 0.0
    trades_per_month = trades_per_year / 12.0

    return CostReport(
        scenario=scenario.name,
        num_trades=num_trades,
        years_evaluated=years_evaluated,
        trades_per_year=trades_per_year,
        trades_per_month=trades_per_month,
        total_fees=total_fees,
        total_slippage_cost=total_slippage_cost,
        total_cost=total_cost,
        cost_per_trade=cost_per_trade,
        gross_expectancy=gross_expectancy,
        net_expectancy=net_expectancy,
        cost_drag=cost_drag,
        gross_return=gross_return,
        net_return=net_return,
    )
