"""POST-HOC SHORT-HORIZON RESEARCH — per-trade MAE/MFE + cost breakdown.

Task 12: every Phase 4A trade must record MAE, MFE, time to MFE, time to
MAE, duration, net return, gross return, fees, spread cost, and slippage
cost -- so we can tell whether a strategy has real signal but a bad exit.

Reuses `src.research.diagnostics.enrich_trades` (already computes MAE/MFE/
duration/time-to-extremes from a trades+OHLCV pair, generic to any
strategy) rather than reimplementing that path-dependent logic, and adds
the per-trade cost breakdown from the same algebraic fill-price recovery
already used in `short_horizon_costs.build_cost_report`.
"""

from __future__ import annotations

import pandas as pd

from src.backtesting.engine import Trade
from src.research.diagnostics import enrich_trades
from src.research.short_horizon_costs import ShortHorizonCostScenario


def build_trade_level_report(
    trades: list[Trade], ohlcv: pd.DataFrame, scenario: ShortHorizonCostScenario
) -> pd.DataFrame:
    """Return one row per trade with MAE/MFE/duration (from
    `enrich_trades`) plus gross/net return and a fee/spread/slippage cost
    breakdown for the given cost scenario.
    """
    if not trades:
        return pd.DataFrame(
            columns=[
                "entry_time", "entry_price", "exit_time", "exit_price", "size_base",
                "entry_notional", "gross_pnl", "entry_fee", "exit_fee", "net_pnl",
                "return_pct", "mae_pct", "mfe_pct", "hours_to_mae", "hours_to_mfe",
                "duration_hours", "gross_return_pct", "fee_cost", "spread_cost",
                "slippage_cost", "winner",
            ]
        )

    trades_df = pd.DataFrame(
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
            for t in trades
        ]
    )
    enriched = enrich_trades(trades_df, ohlcv)

    s = scenario.effective_slippage
    fee_costs = []
    spread_slippage_costs = []
    gross_returns = []
    for t in trades:
        raw_entry_open = t.entry_price / (1 + s) if (1 + s) != 0 else t.entry_price
        raw_exit_open = t.exit_price / (1 - s) if (1 - s) != 0 else t.exit_price
        slippage_cost = t.size_base * (
            (t.entry_price - raw_entry_open) + (raw_exit_open - t.exit_price)
        )
        gross_pnl_raw = (raw_exit_open - raw_entry_open) * t.size_base

        fee_costs.append(t.total_fees)
        spread_slippage_costs.append(slippage_cost)
        gross_returns.append(gross_pnl_raw / t.entry_notional if t.entry_notional else 0.0)

    enriched["fee_cost"] = fee_costs
    # Task 12 asks for spread cost and slippage cost separately, but this
    # engine (see short_horizon_costs.py's documented design) applies
    # spread as an additive component of a single effective_slippage
    # parameter -- there is no separately recoverable spread-only vs.
    # slippage-only fill-price adjustment once the trade has executed.
    # Both columns are reported, split proportionally to the scenario's
    # own declared half_spread vs slippage components, which is the most
    # granular split possible without re-architecting the engine.
    total_component = scenario.half_spread + scenario.slippage
    spread_fraction = scenario.half_spread / total_component if total_component > 0 else 0.0
    enriched["spread_cost"] = [c * spread_fraction for c in spread_slippage_costs]
    enriched["slippage_cost"] = [c * (1 - spread_fraction) for c in spread_slippage_costs]
    enriched["gross_return_pct"] = gross_returns

    return enriched
