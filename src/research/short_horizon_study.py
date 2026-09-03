"""Phase 4A — POST-HOC SHORT-HORIZON RESEARCH orchestrator.

This phase studies a deliberately small, frozen set of short-horizon LONG/FLAT
mechanisms on BTCUSDT 15m and 1h.  All historical results are exploratory:
2018-2024, 2025-2026 and the full sample have already been observed by earlier
work in this repository, so none of them is a fresh holdout.

Hard rules enforced here:
* only the frozen variants declared in FROZEN_VARIANTS are run;
* no threshold search/optimizer/ML is present;
* every variant is run under the same four execution-cost scenarios;
* Phase 3's existing forward preregistration is fingerprinted before and after;
* outputs are labelled POST-HOC / NOT OUT-OF-SAMPLE VALIDATION;
* candidate labels are descriptive research triage, never profitability claims.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
import json
import math

import numpy as np
import pandas as pd
import yaml

from src.backtesting.engine import BacktestEngine
from src.metrics.metrics import build_metrics_report
from src.research.block_bootstrap import block_bootstrap_trade_returns
from src.research.monte_carlo import monte_carlo_trade_returns
from src.research.phase3_guard import assert_phase3_intact
from src.research.short_horizon_costs import (
    SHORT_HORIZON_COST_SCENARIOS,
    SHORT_HORIZON_SCENARIO_BY_NAME,
    ShortHorizonCostScenario,
    build_cost_report,
)
from src.research.short_horizon_data import TIMEFRAMES, load_and_register
from src.research.short_horizon_mae_mfe import build_trade_level_report
from src.research.time_of_day import build_time_of_day_report, report_to_dict
from src.strategies.short_horizon import (
    ExtremeMoveReversal,
    RangeExpansion,
    ShortBreakout,
    ShortMeanReversionZScore,
    ShortMomentum,
    VolumeShockDirection,
    VwapIntradayMeanReversion,
)

POSTHOC_LABEL = "POST-HOC SHORT-HORIZON RESEARCH / NOT OUT-OF-SAMPLE VALIDATION"
OUTPUT_ROOT = Path("research/short_horizon")
RESEARCH_CUTOFF = pd.Timestamp("2025-01-01T00:00:00Z")
RECENT_END = pd.Timestamp("2026-09-02T23:59:59.999999999Z")
BASE_SCENARIO = "B_base"
CONSERVATIVE_SCENARIO = "C_conservative"
MONTE_CARLO_SIMULATIONS = 2000
MONTE_CARLO_SEED = 42
BLOCK_BOOTSTRAP_SIZE = 5

# Frozen before Phase-4A result inspection. Parameters are deliberately sparse.
# 15m and 1h versions use approximately matched CLOCK-TIME horizons where that
# is intrinsic to the mechanism, so cross-timeframe comparison asks whether the
# mechanism generalizes rather than whether one arbitrary bar count wins.
FROZEN_VARIANTS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "15m": {
        "short_momentum": [
            {"lookback": 8, "max_holding_bars": 8},      # 2h / 2h
            {"lookback": 16, "max_holding_bars": 16},   # 4h / 4h
            {"lookback": 32, "max_holding_bars": 32},   # 8h / 8h
        ],
        "short_mean_reversion_zscore": [
            {"window": 48, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 16},
            {"window": 48, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 16},
            {"window": 96, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 32},
            {"window": 96, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 32},
            {"window": 192, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 48},
            {"window": 192, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 48},
        ],
        "short_breakout": [
            {"entry_lookback": 16, "max_holding_bars": 8},
            {"entry_lookback": 32, "max_holding_bars": 16},
            {"entry_lookback": 48, "max_holding_bars": 24},
        ],
        "extreme_move_reversal": [
            {"return_lookback": 12, "zscore_window": 2880, "entry_z_score": -2.0, "max_holding_bars": 8},
            {"return_lookback": 24, "zscore_window": 2880, "entry_z_score": -2.0, "max_holding_bars": 16},
            {"return_lookback": 48, "zscore_window": 2880, "entry_z_score": -2.0, "max_holding_bars": 24},
        ],
        "range_expansion": [
            {"atr_period": 56, "atr_multiple": 1.5, "close_position_threshold": 0.75, "max_holding_bars": 8},
            {"atr_period": 56, "atr_multiple": 2.0, "close_position_threshold": 0.75, "max_holding_bars": 8},
        ],
        "volume_shock_direction": [
            {"volume_median_window": 96, "volume_multiple": 2.0, "close_position_threshold": 0.75, "max_holding_bars": 8},
            {"volume_median_window": 96, "volume_multiple": 3.0, "close_position_threshold": 0.75, "max_holding_bars": 8},
        ],
        "vwap_intraday_mean_reversion_experimental": [
            {"entry_distance": -0.015, "exit_distance": 0.0, "max_holding_bars": 16},
        ],
    },
    "1h": {
        "short_momentum": [
            {"lookback": 2, "max_holding_bars": 2},
            {"lookback": 4, "max_holding_bars": 4},
            {"lookback": 8, "max_holding_bars": 8},
        ],
        "short_mean_reversion_zscore": [
            {"window": 12, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 4},
            {"window": 12, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 4},
            {"window": 24, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 8},
            {"window": 24, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 8},
            {"window": 48, "entry_z": -1.5, "exit_z": 0.0, "max_holding_bars": 12},
            {"window": 48, "entry_z": -2.0, "exit_z": 0.0, "max_holding_bars": 12},
        ],
        "short_breakout": [
            {"entry_lookback": 4, "max_holding_bars": 2},
            {"entry_lookback": 8, "max_holding_bars": 4},
            {"entry_lookback": 12, "max_holding_bars": 6},
        ],
        "extreme_move_reversal": [
            {"return_lookback": 3, "zscore_window": 720, "entry_z_score": -2.0, "max_holding_bars": 2},
            {"return_lookback": 6, "zscore_window": 720, "entry_z_score": -2.0, "max_holding_bars": 4},
            {"return_lookback": 12, "zscore_window": 720, "entry_z_score": -2.0, "max_holding_bars": 6},
        ],
        "range_expansion": [
            {"atr_period": 14, "atr_multiple": 1.5, "close_position_threshold": 0.75, "max_holding_bars": 2},
            {"atr_period": 14, "atr_multiple": 2.0, "close_position_threshold": 0.75, "max_holding_bars": 2},
        ],
        "volume_shock_direction": [
            {"volume_median_window": 24, "volume_multiple": 2.0, "close_position_threshold": 0.75, "max_holding_bars": 2},
            {"volume_median_window": 24, "volume_multiple": 3.0, "close_position_threshold": 0.75, "max_holding_bars": 2},
        ],
        "vwap_intraday_mean_reversion_experimental": [
            {"entry_distance": -0.015, "exit_distance": 0.0, "max_holding_bars": 4},
        ],
    },
}

ALLOWED_CLASSIFICATIONS = {
    "REJECTED",
    "INTERESTING POST-HOC",
    "COST-SENSITIVE",
    "REGIME-SENSITIVE",
    "INSUFFICIENT EVIDENCE",
}


def build_strategy(name: str, params: dict[str, Any]):
    factories = {
        "short_momentum": ShortMomentum,
        "short_mean_reversion_zscore": ShortMeanReversionZScore,
        "short_breakout": ShortBreakout,
        "extreme_move_reversal": ExtremeMoveReversal,
        "range_expansion": RangeExpansion,
        "volume_shock_direction": VolumeShockDirection,
        "vwap_intraday_mean_reversion_experimental": VwapIntradayMeanReversion,
    }
    if name not in factories:
        raise ValueError(f"Unknown/frozen-out Phase 4A family: {name}")
    return factories[name](**params)


def frozen_variant_count() -> int:
    return sum(len(vs) for tf in FROZEN_VARIANTS.values() for vs in tf.values())


def _period_slice_with_warmup(
    df: pd.DataFrame, strategy, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.DataFrame, int] | None:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    mask = (ts >= start) & (ts <= end)
    idx = np.flatnonzero(mask.to_numpy())
    if len(idx) < 2:
        return None
    first, last = int(idx[0]), int(idx[-1])
    warm_start = max(0, first - int(strategy.warmup_bars))
    ext = df.iloc[warm_start : last + 1].copy().reset_index(drop=True)
    return ext, first - warm_start


def _run_period(
    df: pd.DataFrame,
    timeframe: str,
    family: str,
    params: dict[str, Any],
    scenario: ShortHorizonCostScenario,
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    strategy = build_strategy(family, params)
    sliced = _period_slice_with_warmup(df, strategy, start, end)
    if sliced is None:
        return None
    ext, eval_start = sliced
    signals = strategy.generate_signals(ext)
    result = BacktestEngine(scenario.to_backtest_config()).run(ext, signals, evaluation_start=eval_start)
    metrics = build_metrics_report(result, timeframe)
    years = max((end - start).total_seconds() / (365 * 24 * 3600), 1 / 365)
    costs = build_cost_report(scenario, result, years)
    return result, metrics, costs, ext


def _safe(v: Any) -> Any:
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _period_metrics_row(
    *, timeframe: str, family: str, variant_id: str, params: dict[str, Any], period: str,
    scenario: ShortHorizonCostScenario, metrics: dict[str, Any], costs,
) -> dict[str, Any]:
    return {
        "label": POSTHOC_LABEL,
        "timeframe": timeframe,
        "family": family,
        "variant_id": variant_id,
        "params": json.dumps(params, sort_keys=True),
        "period": period,
        "scenario": scenario.name,
        **{k: _safe(metrics.get(k)) for k in [
            "total_return", "annualized_return", "sharpe_ratio", "sortino_ratio",
            "max_drawdown_pct", "profit_factor", "expectancy", "win_rate",
            "average_win", "average_loss", "num_trades", "market_exposure", "total_fees",
        ]},
        "trades_per_year": costs.trades_per_year,
        "trades_per_month": costs.trades_per_month,
        "gross_expectancy": costs.gross_expectancy,
        "net_expectancy": costs.net_expectancy,
        "gross_return_additive": costs.gross_return,
        "cost_drag_additive": costs.cost_drag,
        "total_slippage_cost": costs.total_slippage_cost,
        "total_execution_cost": costs.total_cost,
        "cost_per_trade": costs.cost_per_trade,
    }


def _classify_variant(base_full: pd.Series, conservative_full: pd.Series, base_research: pd.Series, base_recent: pd.Series) -> tuple[str, str]:
    trades = int(base_full.get("num_trades", 0) or 0)
    base_exp = base_full.get("net_expectancy")
    cons_exp = conservative_full.get("net_expectancy")
    if trades < 50:
        return "INSUFFICIENT EVIDENCE", "fewer than 50 full-sample trades"
    if base_exp is None or float(base_exp) <= 0:
        return "REJECTED", "net expectancy is non-positive under BASE costs"
    if cons_exp is None or float(cons_exp) <= 0:
        return "COST-SENSITIVE", "positive under BASE but non-positive under CONSERVATIVE costs"

    research_ret = base_research.get("total_return")
    recent_ret = base_recent.get("total_return")
    if research_ret is not None and recent_ret is not None and float(research_ret) * float(recent_ret) < 0:
        return "REGIME-SENSITIVE", "research and recent periods have opposite return signs"
    return "INTERESTING POST-HOC", "positive net expectancy under BASE and CONSERVATIVE costs; descriptive only"


def _parameter_plateau_table(base_full: pd.DataFrame) -> pd.DataFrame:
    """Family-level robustness diagnostic without inventing new parameter points.

    A family is a plateau when at least half of its frozen variants have positive
    net expectancy under BASE and the best expectancy is <=3x the median positive
    expectancy.  Otherwise results are labelled cliff/chaotic/negative.
    """
    rows: list[dict[str, Any]] = []
    for (tf, family), g in base_full.groupby(["timeframe", "family"]):
        vals = pd.to_numeric(g["net_expectancy"], errors="coerce")
        pos = vals[vals > 0]
        positive_fraction = float((vals > 0).mean()) if len(vals) else 0.0
        med_pos = float(pos.median()) if len(pos) else None
        best = float(pos.max()) if len(pos) else None
        ratio = (best / med_pos) if med_pos and med_pos > 0 else None
        if not len(pos):
            shape = "negative_region"
        elif positive_fraction >= 0.5 and ratio is not None and ratio <= 3.0:
            shape = "plateau"
        elif positive_fraction < 0.5:
            shape = "chaotic_or_sparse"
        else:
            shape = "parameter_cliff"
        rows.append({
            "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
            "variants": int(len(g)), "positive_expectancy_fraction": positive_fraction,
            "median_positive_expectancy": med_pos, "best_positive_expectancy": best,
            "best_to_median_positive_ratio": ratio, "shape": shape,
        })
    return pd.DataFrame(rows)


def _family_summary(all_rows: pd.DataFrame, classes: pd.DataFrame, plateau: pd.DataFrame) -> pd.DataFrame:
    base = all_rows[(all_rows["scenario"] == BASE_SCENARIO) & (all_rows["period"] == "full")].copy()
    out = []
    for (tf, family), g in base.groupby(["timeframe", "family"]):
        c = classes[(classes.timeframe == tf) & (classes.family == family)]
        p = plateau[(plateau.timeframe == tf) & (plateau.family == family)]
        out.append({
            "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
            "variants": int(len(g)),
            "median_total_return": float(pd.to_numeric(g.total_return, errors="coerce").median()),
            "median_sharpe": float(pd.to_numeric(g.sharpe_ratio, errors="coerce").median()),
            "median_max_drawdown": float(pd.to_numeric(g.max_drawdown_pct, errors="coerce").median()),
            "median_net_expectancy": float(pd.to_numeric(g.net_expectancy, errors="coerce").median()),
            "median_trades": float(pd.to_numeric(g.num_trades, errors="coerce").median()),
            "pct_interesting": float((c.classification == "INTERESTING POST-HOC").mean()) if len(c) else 0.0,
            "parameter_shape": p.iloc[0].shape if False else (p.iloc[0]["shape"] if len(p) else None),
        })
    return pd.DataFrame(out)


def _trade_cohort_summary(trades_df: pd.DataFrame, period_freq: str) -> pd.DataFrame:
    """Summarize executed BASE trades by ENTRY calendar period.

    `period_freq` is ``Y`` or ``Q``.  The total return is the compounded
    product of each trade's net `return_pct` within the cohort.  A trade is
    assigned wholly to the period where it was entered; this is deliberate
    and avoids inventing an intratrade mark-to-market split at a calendar
    boundary.  Phase-4A trades are short by design, so boundary-spanning
    trades should be rare and remain visible in the underlying MAE/MFE CSV.
    """
    cols = ["period", "num_trades", "win_rate", "mean_trade_return", "median_trade_return", "compounded_trade_return", "total_fees"]
    if trades_df.empty:
        return pd.DataFrame(columns=cols)
    t = trades_df.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    if period_freq == "Y":
        t["period"] = t["entry_time"].dt.year.astype(str)
    elif period_freq == "Q":
        # Avoid pandas Period timezone warning; construct quarter label directly.
        quarter = ((t["entry_time"].dt.month - 1) // 3 + 1).astype(int)
        t["period"] = t["entry_time"].dt.year.astype(str) + "Q" + quarter.astype(str)
    else:
        raise ValueError("period_freq must be 'Y' or 'Q'")
    rows = []
    for period, g in t.groupby("period", sort=True):
        r = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        rows.append({
            "period": str(period),
            "num_trades": int(len(r)),
            "win_rate": float((r > 0).mean()) if len(r) else None,
            "mean_trade_return": float(r.mean()) if len(r) else None,
            "median_trade_return": float(r.median()) if len(r) else None,
            "compounded_trade_return": float(np.prod(1.0 + r.to_numpy()) - 1.0) if len(r) else 0.0,
            "total_fees": float(pd.to_numeric(g.get("entry_fee", 0), errors="coerce").fillna(0).sum() + pd.to_numeric(g.get("exit_fee", 0), errors="coerce").fillna(0).sum()),
        })
    return pd.DataFrame(rows, columns=cols)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str, sort_keys=True) + "\n")


def run_short_horizon_study(
    config_path: str | Path = Path("configs/short_horizon_phase4a.yaml"),
    *,
    output_root: Path = OUTPUT_ROOT,
    raw_dir: Path = Path("data/raw"),
    data_by_timeframe: dict[str, pd.DataFrame] | None = None,
) -> Path:
    baseline_phase3 = assert_phase3_intact()

    cfg = {}
    p = Path(config_path)
    if p.exists():
        with open(p) as f:
            cfg = yaml.safe_load(f) or {}
    configured_tfs = tuple(cfg.get("timeframes", list(TIMEFRAMES)))
    if configured_tfs != tuple(TIMEFRAMES):
        raise ValueError(f"Phase 4A timeframes are frozen to {TIMEFRAMES}; got {configured_tfs}")
    if cfg.get("allow_parameter_search", False):
        raise PermissionError("Phase 4A forbids parameter search/optimization")

    output_root.mkdir(parents=True, exist_ok=True)
    for sub in ["annual", "quarterly", "time_of_day", "mae_mfe", "parameter_sensitivity", "monte_carlo"]:
        (output_root / sub).mkdir(parents=True, exist_ok=True)

    datasets: dict[str, pd.DataFrame] = {}
    registrations: dict[str, Any] = {}
    for tf in TIMEFRAMES:
        if data_by_timeframe is not None:
            if tf not in data_by_timeframe:
                raise ValueError(f"missing injected dataset for {tf}")
            df = data_by_timeframe[tf].copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.sort_values("timestamp").reset_index(drop=True)
            datasets[tf] = df
            registrations[tf] = {
                "symbol": "BTCUSDT", "timeframe": tf, "num_candles": len(df),
                "start": str(df.timestamp.min()), "end": str(df.timestamp.max()),
                "dataset_hash": "synthetic/injected", "duplicate_timestamps": int(df.timestamp.duplicated().sum()),
                "gap_count": None, "gap_examples": [], "is_valid": True, "validation_errors": [],
            }
        else:
            df, reg = load_and_register(tf, raw_dir=raw_dir, allow_gaps=True)
            datasets[tf] = df
            registrations[tf] = reg.to_dict()

    # Descriptive time-of-day analysis: no strategy or signal is created.
    for tf, df in datasets.items():
        tod = build_time_of_day_report(df)
        tod.per_hour.to_csv(output_root / "time_of_day" / f"{tf}_per_hour.csv", index=False)
        _write_json(output_root / "time_of_day" / f"{tf}_summary.json", {"label": POSTHOC_LABEL, **report_to_dict(tod)})

    all_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    quarterly_rows: list[dict[str, Any]] = []
    variant_results: dict[tuple[str, str, str], Any] = {}

    for tf, family_map in FROZEN_VARIANTS.items():
        df = datasets[tf]
        data_start = pd.Timestamp(df.timestamp.iloc[0])
        data_end = pd.Timestamp(df.timestamp.iloc[-1])
        periods = {
            "research_2018_2024": (data_start, min(data_end, RESEARCH_CUTOFF - pd.Timedelta(nanoseconds=1))),
            "recent_2025_2026": (max(data_start, RESEARCH_CUTOFF), min(data_end, RECENT_END)),
            "full": (data_start, min(data_end, RECENT_END)),
        }
        for family, variants in family_map.items():
            for vi, params in enumerate(variants, start=1):
                variant_id = f"{family}__{vi:02d}"
                # Same exact signal/params under all four cost scenarios.
                for scenario in SHORT_HORIZON_COST_SCENARIOS:
                    for period_name, (start, end) in periods.items():
                        if end <= start:
                            continue
                        run = _run_period(df, tf, family, params, scenario, start, end)
                        if run is None:
                            continue
                        result, metrics, costs, ext = run
                        all_rows.append(_period_metrics_row(
                            timeframe=tf, family=family, variant_id=variant_id, params=params,
                            period=period_name, scenario=scenario, metrics=metrics, costs=costs,
                        ))
                        if scenario.name == BASE_SCENARIO and period_name == "full":
                            variant_results[(tf, family, variant_id)] = (result, ext, params)
                            trade_report = build_trade_level_report(result.trades, ext, scenario)
                            trade_report.insert(0, "variant_id", variant_id)
                            trade_report.insert(0, "family", family)
                            trade_report.insert(0, "timeframe", tf)
                            trade_report.insert(0, "label", POSTHOC_LABEL)
                            trade_report.to_csv(output_root / "mae_mfe" / f"{tf}__{variant_id}.csv", index=False)


                # Annual/quarterly summaries are derived later from the single
                # full-sample BASE trade log. Re-running every calendar slice
                # independently would multiply the 303k-bar 15m workload by ~45
                # per variant while adding little information for a short-horizon
                # diagnostic. We therefore report trade cohorts by ENTRY period:
                # compounded net trade return, counts, win rate, median/mean trade
                # return and fees. This preserves the exact executed trades from
                # the audited full BASE run and makes the boundary convention
                # explicit instead of pretending a position can be split mid-trade.

    all_df = pd.DataFrame(all_rows)

    # Derive annual/quarterly BASE trade-cohort summaries from each variant's
    # already-executed full-sample trade log (see helper docstring above).
    for (tf, family, variant_id), (result, _ext, params) in variant_results.items():
        trades_df = result.trades_df()
        for _, row in _trade_cohort_summary(trades_df, "Y").iterrows():
            annual_rows.append({
                "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
                "variant_id": variant_id, "params": json.dumps(params, sort_keys=True),
                **row.to_dict(),
            })
        for _, row in _trade_cohort_summary(trades_df, "Q").iterrows():
            quarterly_rows.append({
                "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
                "variant_id": variant_id, "params": json.dumps(params, sort_keys=True),
                **row.to_dict(),
            })

    annual_df = pd.DataFrame(annual_rows)
    quarterly_df = pd.DataFrame(quarterly_rows)
    all_df.to_csv(output_root / "all_variants.csv", index=False)
    annual_df.to_csv(output_root / "annual" / "all_variants_annual.csv", index=False)
    quarterly_df.to_csv(output_root / "quarterly" / "all_variants_quarterly.csv", index=False)

    # Descriptive classification from frozen criteria.
    classes = []
    for tf, family_map in FROZEN_VARIANTS.items():
        for family, variants in family_map.items():
            for vi, params in enumerate(variants, start=1):
                vid = f"{family}__{vi:02d}"
                pick = lambda scenario, period: all_df[(all_df.timeframe == tf) & (all_df.family == family) & (all_df.variant_id == vid) & (all_df.scenario == scenario) & (all_df.period == period)]
                bf, cf, br, brec = pick(BASE_SCENARIO, "full"), pick(CONSERVATIVE_SCENARIO, "full"), pick(BASE_SCENARIO, "research_2018_2024"), pick(BASE_SCENARIO, "recent_2025_2026")
                if any(x.empty for x in [bf, cf, br, brec]):
                    label, reason = "INSUFFICIENT EVIDENCE", "missing one or more required period/scenario results"
                else:
                    label, reason = _classify_variant(bf.iloc[0], cf.iloc[0], br.iloc[0], brec.iloc[0])
                classes.append({"label": POSTHOC_LABEL, "timeframe": tf, "family": family, "variant_id": vid, "params": json.dumps(params, sort_keys=True), "classification": label, "reason": reason})
    class_df = pd.DataFrame(classes)
    if not set(class_df.classification).issubset(ALLOWED_CLASSIFICATIONS):
        raise AssertionError("unexpected classification label")
    class_df.to_csv(output_root / "classifications.csv", index=False)

    base_full = all_df[(all_df.scenario == BASE_SCENARIO) & (all_df.period == "full")]
    plateau = _parameter_plateau_table(base_full)
    plateau.to_csv(output_root / "parameter_sensitivity" / "family_plateau_cliff.csv", index=False)
    fam_summary = _family_summary(all_df, class_df, plateau)
    fam_summary.to_csv(output_root / "family_summary.csv", index=False)

    # Cost analysis: every frozen variant, every scenario, full sample.
    cost_cols = ["label", "timeframe", "family", "variant_id", "params", "scenario", "total_return", "net_expectancy", "gross_expectancy", "cost_drag_additive", "total_fees", "total_slippage_cost", "total_execution_cost", "cost_per_trade", "num_trades", "trades_per_year"]
    all_df[all_df.period == "full"][cost_cols].to_csv(output_root / "cost_analysis.csv", index=False)

    # Monte Carlo + moving-block bootstrap only for INTERESTING POST-HOC or
    # COST-SENSITIVE variants with enough trades. No parameter selection occurs.
    mc_summary_rows = []
    eligible = class_df[class_df.classification.isin(["INTERESTING POST-HOC", "COST-SENSITIVE", "REGIME-SENSITIVE"])]
    for _, c in eligible.iterrows():
        key = (c.timeframe, c.family, c.variant_id)
        if key not in variant_results:
            continue
        result, _, params = variant_results[key]
        returns = [t.return_pct for t in result.trades]
        if len(returns) < 20:
            continue
        mc, finals, dds = monte_carlo_trade_returns(returns, simulations=MONTE_CARLO_SIMULATIONS, seed=MONTE_CARLO_SEED)
        pd.DataFrame({"final_return": finals, "max_drawdown": dds}).to_csv(output_root / "monte_carlo" / f"{c.timeframe}__{c.variant_id}__iid.csv", index=False)
        row = {"label": POSTHOC_LABEL, "method": "iid_trade_bootstrap", "timeframe": c.timeframe, "family": c.family, "variant_id": c.variant_id, "params": json.dumps(params, sort_keys=True), **asdict(mc)}
        mc_summary_rows.append(row)
        if len(returns) >= BLOCK_BOOTSTRAP_SIZE:
            bmc, bfinals, bdds = block_bootstrap_trade_returns(returns, block_size=BLOCK_BOOTSTRAP_SIZE, simulations=MONTE_CARLO_SIMULATIONS, seed=MONTE_CARLO_SEED)
            pd.DataFrame({"final_return": bfinals, "max_drawdown": bdds}).to_csv(output_root / "monte_carlo" / f"{c.timeframe}__{c.variant_id}__block{BLOCK_BOOTSTRAP_SIZE}.csv", index=False)
            mc_summary_rows.append({"label": POSTHOC_LABEL, "method": f"moving_block_bootstrap_{BLOCK_BOOTSTRAP_SIZE}", "timeframe": c.timeframe, "family": c.family, "variant_id": c.variant_id, "params": json.dumps(params, sort_keys=True), **asdict(bmc)})
    pd.DataFrame(mc_summary_rows).to_csv(output_root / "monte_carlo" / "summary.csv", index=False)

    # Cross-timeframe family comparison, explicitly mechanism-level.
    cross_rows = []
    for family in sorted(set(FROZEN_VARIANTS["15m"]) & set(FROZEN_VARIANTS["1h"])):
        row: dict[str, Any] = {"label": POSTHOC_LABEL, "family": family}
        for tf in TIMEFRAMES:
            g = base_full[(base_full.timeframe == tf) & (base_full.family == family)]
            row[f"{tf}_median_net_expectancy"] = float(pd.to_numeric(g.net_expectancy, errors="coerce").median()) if len(g) else None
            row[f"{tf}_positive_expectancy_fraction"] = float((pd.to_numeric(g.net_expectancy, errors="coerce") > 0).mean()) if len(g) else None
            row[f"{tf}_median_total_return"] = float(pd.to_numeric(g.total_return, errors="coerce").median()) if len(g) else None
        signs_match = (row["15m_median_net_expectancy"] is not None and row["1h_median_net_expectancy"] is not None and np.sign(row["15m_median_net_expectancy"]) == np.sign(row["1h_median_net_expectancy"]))
        row["mechanism_direction_consistent"] = bool(signs_match)
        cross_rows.append(row)
    pd.DataFrame(cross_rows).to_csv(output_root / "cross_timeframe_family_summary.csv", index=False)

    total_variants = frozen_variant_count()
    total_backtests = len(all_df)
    metadata = {
        "label": POSTHOC_LABEL,
        "symbol": "BTCUSDT",
        "timeframes": list(TIMEFRAMES),
        "datasets": registrations,
        "research_period": "2018-01-01 through 2024-12-31 (post-hoc)",
        "recent_period": "2025-01-01 through 2026-09-02 (already consumed, post-hoc)",
        "full_period": "2018-01-01 through 2026-09-02 (post-hoc)",
        "frozen_variants": FROZEN_VARIANTS,
        "families_including_experimental_vwap": sorted(set(f for tf in FROZEN_VARIANTS.values() for f in tf)),
        "total_frozen_variants": total_variants,
        "cost_scenarios": [asdict(s) for s in SHORT_HORIZON_COST_SCENARIOS],
        "backtests_recorded_period_x_cost": total_backtests,
        "metrics_observed_per_backtest": 23,
        "multiple_testing_warning": "Every family/variant/scenario/period is counted; standout results must be interpreted in that context and require future forward validation.",
        "monte_carlo_simulations": MONTE_CARLO_SIMULATIONS,
        "monte_carlo_seed": MONTE_CARLO_SEED,
        "block_bootstrap_size": BLOCK_BOOTSTRAP_SIZE,
        "classification_labels": sorted(ALLOWED_CLASSIFICATIONS),
        "phase3_fingerprint_before": baseline_phase3,
    }

    # Candidate shortlist: maximum 3, selected descriptively from already-frozen
    # variants. This does not create or preregister a forward phase.
    candidate_pool = base_full.merge(class_df[["timeframe", "family", "variant_id", "classification"]], on=["timeframe", "family", "variant_id"], how="left")
    candidate_pool = candidate_pool[candidate_pool.classification == "INTERESTING POST-HOC"].copy()
    if not candidate_pool.empty:
        candidate_pool["rank_key"] = pd.to_numeric(candidate_pool.net_expectancy, errors="coerce") / pd.to_numeric(candidate_pool.max_drawdown_pct, errors="coerce").abs().replace(0, np.nan)
        candidates = candidate_pool.sort_values(["rank_key", "num_trades"], ascending=[False, False]).head(3)
    else:
        candidates = candidate_pool
    hypotheses = []
    for _, r in candidates.iterrows():
        hypotheses.append({
            "family": r.family, "timeframe": r.timeframe, "variant_id": r.variant_id,
            "params": json.loads(r.params),
            "mechanism": "Frozen Phase-4A short-horizon mechanism; see strategy class docstring.",
            "why_selected": "Positive BASE and CONSERVATIVE net expectancy with adequate trade count; ranked only for a maximum-three post-hoc shortlist.",
            "risks": "Selected on already-observed history; multiple testing, execution-model simplification, and regime dependence remain.",
            "falsification": "A future preregistered forward run has non-positive net expectancy under the same BASE costs or fails materially under CONSERVATIVE costs.",
            "suggested_forward_duration": "At least 6 months and preferably >=100 trades before strong conclusions; longer if trade frequency is lower.",
        })
    _write_json(output_root / "hypotheses.json", {"label": POSTHOC_LABEL, "maximum_candidates": 3, "candidates": hypotheses})

    final_phase3 = assert_phase3_intact(baseline_phase3)
    metadata["phase3_fingerprint_after"] = final_phase3
    metadata["phase3_unchanged"] = baseline_phase3 == final_phase3
    _write_json(output_root / "metadata.json", metadata)
    _write_json(output_root / "multiple_testing.json", {
        "label": POSTHOC_LABEL,
        "families": len(metadata["families_including_experimental_vwap"]),
        "frozen_variants": total_variants,
        "cost_scenarios_per_variant": len(SHORT_HORIZON_COST_SCENARIOS),
        "periods_per_variant": 3,
        "period_x_cost_backtests_recorded": total_backtests,
        "annual_and_quarterly_base_cost_reports": len(annual_df) + len(quarterly_df),
        "warning": metadata["multiple_testing_warning"],
    })

    counts = class_df.classification.value_counts().to_dict()
    with open(output_root / "README.md", "w") as f:
        f.write("# Phase 4A — Short-Horizon Strategy Research\n\n")
        f.write(f"**{POSTHOC_LABEL}**\n\n")
        f.write("This report does not validate profitability. All historical periods used here are already-observed data. Any candidate requires a separately preregistered forward/paper test.\n\n")
        f.write(f"- Timeframes: {', '.join(TIMEFRAMES)}\n")
        f.write(f"- Frozen variants: {total_variants}\n")
        f.write(f"- Period × cost backtests recorded: {total_backtests}\n")
        f.write(f"- Classifications: {counts}\n")
        f.write(f"- Forward candidates proposed: {len(hypotheses)} (maximum 3)\n")
        f.write(f"- Phase 3 preregistration unchanged: {metadata['phase3_unchanged']}\n\n")
        f.write("VWAP is retained as an explicitly methodologically weak experiment because UTC sessions are arbitrary in a 24/7 crypto market.\n")

    return output_root
