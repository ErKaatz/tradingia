"""POST-HOC REGIME RESEARCH — exploratory, limited simulation only.

Tests whether a causal regime gate (computed with trailing information
only) would have suppressed NEW entries during periods a candidate
hypothesis flags as unfavorable, for exactly one variant per hypothesis --
no grid, no threshold search, no iterating toward a better result. This
exists solely to check whether a conceptual rule is even directionally
sane; it does not validate anything and must never be described as
out-of-sample evidence.

Threshold policy (Task 8): every gate here uses a trailing, self-relative
threshold (a trailing median/percentile of the feature's OWN history),
never a fixed numeric value fit to make 2025-2026 look better. See each
gate function's docstring for the exact policy and its source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from src.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.metrics.metrics import build_metrics_report
from src.strategies.base import FLAT, LONG, Strategy
from src.strategies.breakout import Breakout
from src.strategies.buy_and_hold import BuyAndHold
from src.strategies.sma_cross import SmaCross

TRAILING_MEDIAN_WINDOW_BARS = 8760  # 365 days of 1h bars, same convention as
# src/strategies/breakout_forward.py's adaptive-vol gate (already-frozen
# Phase 3 hypothesis) -- reusing the same trailing-year convention for
# consistency, but this is an independent, separately-computed gate that
# does not touch or import that module.

ADX_STANDARD_TREND_THRESHOLD = 20.0
# Wilder's own published convention (New Concepts in Technical Trading
# Systems, 1978): ADX above ~20-25 indicates a directional/trending market;
# below indicates a non-trending/range-bound one. 20 is the more permissive
# (lower) end of that standard range, chosen here specifically to avoid
# tuning the threshold to whatever value happens to separate our own
# recent winners/losers best.


def volatility_compression_gate(
    df: pd.DataFrame, realized_vol_168h: pd.Series, signals: pd.Series
) -> pd.Series:
    """Suppress new LONG entries when trailing 168h realized volatility is
    BELOW its own trailing 365-day median (i.e. volatility is compressed
    relative to its own recent history). Existing positions are never
    force-closed by this gate -- only new entries are blocked.

    Threshold policy: trailing median of the feature's own past 365 days
    (8760 bars), shifted by one bar so the threshold at bar i never
    includes bar i's own volatility reading. This is a self-relative,
    causal threshold -- not a fixed number chosen to fit 2025-2026.
    """
    trailing_median = realized_vol_168h.shift(1).rolling(
        TRAILING_MEDIAN_WINDOW_BARS, min_periods=TRAILING_MEDIAN_WINDOW_BARS
    ).median()

    out = signals.copy().astype(int)
    prev = FLAT
    for i in range(len(out)):
        desired = int(signals.iloc[i])
        if prev == FLAT and desired == LONG:
            current_vol = realized_vol_168h.iloc[i]
            median = trailing_median.iloc[i]
            allowed = pd.notna(current_vol) and pd.notna(median) and current_vol >= median
            if not allowed:
                desired = FLAT
        out.iloc[i] = desired
        prev = desired
    return out


def adx_minimum_gate(df: pd.DataFrame, adx_14: pd.Series, signals: pd.Series) -> pd.Series:
    """Suppress new LONG entries when trailing ADX(14) is below Wilder's
    standard trending-market threshold (see ADX_STANDARD_TREND_THRESHOLD).
    Existing positions are never force-closed by this gate.
    """
    out = signals.copy().astype(int)
    prev = FLAT
    for i in range(len(out)):
        desired = int(signals.iloc[i])
        if prev == FLAT and desired == LONG:
            current_adx = adx_14.iloc[i]
            allowed = pd.notna(current_adx) and current_adx >= ADX_STANDARD_TREND_THRESHOLD
            if not allowed:
                desired = FLAT
        out.iloc[i] = desired
        prev = desired
    return out


@dataclass
class GateImpact:
    pct_time_blocked: float
    n_baseline_entries: int
    n_gated_entries: int
    n_trades_avoided: int
    n_winners_avoided: int
    n_losers_avoided: int
    baseline_exposure: float
    gated_exposure: float


def _entry_bars(signals: pd.Series) -> set[int]:
    """Indices where a new LONG entry begins (transition FLAT -> LONG)."""
    entries = set()
    prev = FLAT
    for i in range(len(signals)):
        current = int(signals.iloc[i])
        if prev == FLAT and current == LONG:
            entries.add(i)
        prev = current
    return entries


def measure_gate_impact(
    baseline_signals: pd.Series,
    gated_signals: pd.Series,
    baseline_result: BacktestResult,
    gated_result: BacktestResult,
) -> GateImpact:
    """Task 10: quantify what a gate blocks, not just what it "improves".

    A gate that blocks nearly everything can look good on paper while
    providing no real signal -- this measures exactly how much trading
    activity, and how many actual winners vs losers, were avoided.
    """
    baseline_entries = _entry_bars(baseline_signals)
    gated_entries = _entry_bars(gated_signals)

    blocked_bars = int((baseline_signals.astype(int) != gated_signals.astype(int)).sum())
    pct_time_blocked = blocked_bars / len(baseline_signals) if len(baseline_signals) else 0.0

    baseline_trades = baseline_result.trades
    baseline_trade_entry_times = pd.to_datetime([t.entry_time for t in baseline_trades], utc=True)
    gated_trade_entry_times = set(
        pd.to_datetime([t.entry_time for t in gated_result.trades], utc=True)
    )
    winners_avoided = 0
    losers_avoided = 0
    for trade, entry_time in zip(baseline_trades, baseline_trade_entry_times):
        if entry_time not in gated_trade_entry_times:
            if trade.net_pnl > 0:
                winners_avoided += 1
            else:
                losers_avoided += 1

    baseline_exposure = build_metrics_report(baseline_result, "1h").get("market_exposure", 0.0)
    gated_exposure = build_metrics_report(gated_result, "1h").get("market_exposure", 0.0)

    return GateImpact(
        pct_time_blocked=pct_time_blocked,
        n_baseline_entries=len(baseline_entries),
        n_gated_entries=len(gated_entries),
        n_trades_avoided=winners_avoided + losers_avoided,
        n_winners_avoided=winners_avoided,
        n_losers_avoided=losers_avoided,
        baseline_exposure=baseline_exposure,
        gated_exposure=gated_exposure,
    )


def run_exploratory_gate_simulation(
    hypothesis_id: str,
    strategy_factory: Callable[[], Strategy],
    df: pd.DataFrame,
    gate_fn: Callable[[pd.DataFrame, pd.Series, pd.Series], pd.Series],
    gate_feature: pd.Series,
    backtest_config: BacktestConfig,
    timeframe: str,
    output_dir: Path,
) -> dict:
    """Run exactly ONE gated variant against the baseline (ungated)
    strategy and Buy & Hold, over the full 2018-2026 dataset (both research
    and post-hoc recent periods included, since this is explicitly
    exploratory and not a new holdout evaluation of anything -- it is a
    sanity check of a conceptual rule across all available history).

    Writes trades/equity/metrics for baseline and gated runs, plus an
    impact summary (Task 10) and per-year breakdown (Task 11).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    strategy = strategy_factory()
    warmup = strategy.warmup_bars
    baseline_signals = strategy.generate_signals(df)
    gated_signals = gate_fn(df, gate_feature, baseline_signals)

    engine = BacktestEngine(backtest_config)
    baseline_result = engine.run(df, baseline_signals, evaluation_start=warmup)
    gated_result = engine.run(df, gated_signals, evaluation_start=warmup)

    bh_result = engine.run(df, BuyAndHold().generate_signals(df), evaluation_start=0)

    baseline_metrics = build_metrics_report(baseline_result, timeframe)
    gated_metrics = build_metrics_report(gated_result, timeframe)
    bh_metrics = build_metrics_report(bh_result, timeframe)

    impact = measure_gate_impact(baseline_signals, gated_signals, baseline_result, gated_result)

    for name, result in [("baseline", baseline_result), ("gated", gated_result)]:
        result.trades_df().to_csv(output_dir / f"{name}_trades.csv", index=False)
        result.equity_curve.to_csv(output_dir / f"{name}_equity.csv", index=False)

    yearly = _yearly_breakdown(baseline_result, gated_result)
    yearly.to_csv(output_dir / "yearly_breakdown.csv", index=False)

    report = {
        "label": "POST-HOC REGIME RESEARCH / NOT OUT-OF-SAMPLE VALIDATION",
        "hypothesis_id": hypothesis_id,
        "note": (
            "Exploratory, single-variant simulation over the FULL available "
            "history (2018-2026), including the already-consumed post-hoc "
            "2025-2026 period. This checks directional plausibility only. "
            "It is not a new holdout, not out-of-sample evidence, and must "
            "not be used to declare the hypothesis validated."
        ),
        "baseline_metrics": baseline_metrics,
        "gated_metrics": gated_metrics,
        "buy_and_hold_metrics": bh_metrics,
        "gate_impact": {
            "pct_time_blocked": impact.pct_time_blocked,
            "n_baseline_entries": impact.n_baseline_entries,
            "n_gated_entries": impact.n_gated_entries,
            "n_trades_avoided": impact.n_trades_avoided,
            "n_winners_avoided": impact.n_winners_avoided,
            "n_losers_avoided": impact.n_losers_avoided,
            "baseline_exposure": impact.baseline_exposure,
            "gated_exposure": impact.gated_exposure,
        },
    }
    with open(output_dir / "report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    return report


def _yearly_breakdown(baseline_result: BacktestResult, gated_result: BacktestResult) -> pd.DataFrame:
    rows = []
    for name, result in [("baseline", baseline_result), ("gated", gated_result)]:
        equity = result.equity_curve.copy()
        equity["year"] = pd.to_datetime(equity["timestamp"], utc=True).dt.year
        trades_df = result.trades_df()
        if not trades_df.empty:
            trades_df["year"] = pd.to_datetime(trades_df["entry_time"], utc=True).dt.year
        for year in sorted(equity["year"].unique()):
            year_equity = equity[equity["year"] == year]
            year_trades = trades_df[trades_df["year"] == year] if not trades_df.empty else trades_df
            start_equity = year_equity["equity"].iloc[0]
            end_equity = year_equity["equity"].iloc[-1]
            rows.append(
                {
                    "variant": name,
                    "year": int(year),
                    "period_label": "research" if year < 2025 else "recent (post-hoc)",
                    "year_return_approx": (end_equity / start_equity) - 1 if start_equity else None,
                    "num_trades": len(year_trades) if year_trades is not None else 0,
                    "win_rate": (
                        float((year_trades["net_pnl"] > 0).mean())
                        if year_trades is not None and len(year_trades) > 0
                        else None
                    ),
                }
            )
    return pd.DataFrame(rows)
