"""Phase 4B — POST-HOC short-horizon edge-vs-cost diagnostics.

This phase does NOT search new strategy parameters.  It takes only the frozen
Phase-4A variants from the three families that showed some positive *gross*
expectancy and asks a narrower question: is there a real causal signal whose
magnitude is simply too small to monetize under the execution assumptions?

All history through 2026-09-02 has already been observed.  Outputs are
therefore diagnostic/post-hoc and may only motivate future forward tests.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import json
import math

import numpy as np
import pandas as pd
import yaml

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.metrics.metrics import build_metrics_report
from src.research.phase3_guard import assert_phase3_intact
from src.research.short_horizon_costs import SHORT_HORIZON_SCENARIO_BY_NAME
from src.research.short_horizon_data import TIMEFRAMES, load_and_register
from src.research.short_horizon_study import (
    FROZEN_VARIANTS,
    RESEARCH_CUTOFF,
    RECENT_END,
    build_strategy,
)
from src.research.regime_features import atr, true_range

POSTHOC_LABEL = "POST-HOC PHASE 4B EDGE-VS-COST DIAGNOSTICS / NOT OUT-OF-SAMPLE VALIDATION"
OUTPUT_ROOT = Path("research/short_horizon_phase4b")
TARGET_FAMILIES = ("volume_shock_direction", "range_expansion", "extreme_move_reversal")
BASE_SCENARIO_NAME = "B_base"
FOLLOW_THROUGH_MINUTES = (15, 30, 60, 120, 240)
MAX_BREAK_EVEN_MULTIPLIER = 4.0


def frozen_phase4b_variants() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return only Phase-4A-frozen params for the three diagnostic families."""
    return {
        tf: {family: [dict(p) for p in FROZEN_VARIANTS[tf][family]] for family in TARGET_FAMILIES}
        for tf in TIMEFRAMES
    }


def frozen_phase4b_variant_count() -> int:
    return sum(len(v) for fams in frozen_phase4b_variants().values() for v in fams.values())


def _safe(v: Any) -> Any:
    if isinstance(v, (np.floating, np.integer)):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _run_same_signals(df: pd.DataFrame, signals: pd.Series, *, fee: float, slippage: float):
    cfg = BacktestConfig(initial_capital=10_000.0, trading_fee=fee, slippage=slippage)
    return BacktestEngine(cfg).run(df, signals)


def break_even_base_cost_multiplier_from_zero_trades(
    zero_trades,
    *,
    base_fee: float,
    base_slippage: float,
    max_multiplier: float = MAX_BREAK_EVEN_MULTIPLIER,
    iterations: int = 48,
) -> float | None:
    """Exact break-even multiplier of BASE fee+effective-slippage using the
    already-observed zero-cost trade path, without re-running the engine.

    Phase 4A uses an all-in LONG/FLAT engine. For one zero-cost trade with raw
    open-price ratio R=exit/entry, scaling both fee ``f`` and slippage ``s``
    by k changes capital by exactly::

        R * (1-f*k)^2 * (1-s*k)/(1+s*k)

    The full terminal-capital ratio is the product over trades. Signals and
    entry/exit timestamps are cost-independent, so this is algebraically the
    same path as repeatedly re-running the engine, but orders of magnitude
    faster.
    """
    trades = list(zero_trades)
    if not trades:
        return 0.0

    ratios = np.array([float(t.exit_price) / float(t.entry_price) for t in trades], dtype=float)

    def log_terminal_ratio(k: float) -> float:
        fk = base_fee * k
        sk = base_slippage * k
        if fk >= 1.0 or sk >= 1.0:
            return -math.inf
        per_trade_log = np.log(ratios) + 2.0 * math.log1p(-fk) + math.log1p(-sk) - math.log1p(sk)
        return float(np.sum(per_trade_log))

    if log_terminal_ratio(0.0) <= 0.0:
        return 0.0
    if log_terminal_ratio(max_multiplier) >= 0.0:
        return float(max_multiplier)

    lo, hi = 0.0, float(max_multiplier)
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if log_terminal_ratio(mid) >= 0.0:
            lo = mid
        else:
            hi = mid
    return float(lo)


def _lookup_15m_index(master_15m: pd.DataFrame) -> pd.Series:
    ts = pd.to_datetime(master_15m["timestamp"], utc=True)
    return pd.Series(np.arange(len(master_15m), dtype=int), index=ts)


def build_follow_through_rows(
    trades_df: pd.DataFrame,
    master_15m: pd.DataFrame,
    *,
    timeframe: str,
    family: str,
    variant_id: str,
) -> pd.DataFrame:
    """Measure raw post-entry path on the 15m master tape for both 15m and 1h trades.

    Using one 15m tape makes 15m/30m/1h/2h/4h diagnostics comparable even for
    strategies whose decision timeframe is 1h.  Entry timestamps are execution
    opens produced by the already-causal engine; no value here feeds back into
    a trading decision.
    """
    cols = [
        "label", "timeframe", "family", "variant_id", "entry_time", "period",
        "horizon_minutes", "close_return", "mfe_pct", "mae_pct",
    ]
    if trades_df.empty:
        return pd.DataFrame(columns=cols)

    m = master_15m.copy()
    m["timestamp"] = pd.to_datetime(m["timestamp"], utc=True)
    m = m.sort_values("timestamp").reset_index(drop=True)
    idx_map = _lookup_15m_index(m)
    opens = m["open"].to_numpy(float)
    highs = m["high"].to_numpy(float)
    lows = m["low"].to_numpy(float)
    closes = m["close"].to_numpy(float)

    rows: list[dict[str, Any]] = []
    for _, t in trades_df.iterrows():
        entry_time = pd.Timestamp(t["entry_time"])
        if entry_time.tzinfo is None:
            entry_time = entry_time.tz_localize("UTC")
        else:
            entry_time = entry_time.tz_convert("UTC")
        if entry_time not in idx_map.index:
            continue
        i = int(idx_map.loc[entry_time])
        raw_entry = float(opens[i])
        period = "research_2018_2024" if entry_time < RESEARCH_CUTOFF else "recent_2025_2026"
        for minutes in FOLLOW_THROUGH_MINUTES:
            bars = minutes // 15
            j = i + bars
            if j >= len(m):
                continue
            path_hi = highs[i : j + 1]
            path_lo = lows[i : j + 1]
            rows.append({
                "label": POSTHOC_LABEL,
                "timeframe": timeframe,
                "family": family,
                "variant_id": variant_id,
                "entry_time": str(entry_time),
                "period": period,
                "horizon_minutes": minutes,
                "close_return": float(closes[j] / raw_entry - 1.0),
                "mfe_pct": float(np.max(path_hi) / raw_entry - 1.0),
                "mae_pct": float(np.min(path_lo) / raw_entry - 1.0),
            })
    return pd.DataFrame(rows, columns=cols)


def summarize_follow_through(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    out = []
    keys = ["timeframe", "family", "variant_id", "period", "horizon_minutes"]
    for key, g in rows.groupby(keys, dropna=False):
        r = pd.to_numeric(g["close_return"], errors="coerce").dropna()
        mfe = pd.to_numeric(g["mfe_pct"], errors="coerce").dropna()
        mae = pd.to_numeric(g["mae_pct"], errors="coerce").dropna()
        out.append({
            "label": POSTHOC_LABEL,
            **dict(zip(keys, key)),
            "observations": int(len(r)),
            "mean_close_return": float(r.mean()) if len(r) else None,
            "median_close_return": float(r.median()) if len(r) else None,
            "pct_positive_close_return": float((r > 0).mean()) if len(r) else None,
            "mean_mfe_pct": float(mfe.mean()) if len(mfe) else None,
            "mean_mae_pct": float(mae.mean()) if len(mae) else None,
        })
    return pd.DataFrame(out)


def reentry_diagnostics(trades_df: pd.DataFrame, raw_entry_condition: pd.Series, timestamps: pd.Series) -> dict[str, Any]:
    cond = raw_entry_condition.fillna(False).astype(bool).to_numpy()
    raw_triggers = int(cond.sum())
    runs = []
    current = 0
    for x in cond:
        if x:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)

    t = trades_df.copy()
    if not t.empty:
        t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
        t["exit_time"] = pd.to_datetime(t["exit_time"], utc=True)
        t = t.sort_values("entry_time")
    reentry = {}
    for hours in (1, 4, 12):
        count = 0
        if len(t) > 1:
            prev_exit = t["exit_time"].iloc[:-1].reset_index(drop=True)
            next_entry = t["entry_time"].iloc[1:].reset_index(drop=True)
            count = int(((next_entry - prev_exit) <= pd.Timedelta(hours=hours)).sum())
        reentry[f"reentries_within_{hours}h"] = count
        reentry[f"reentry_fraction_within_{hours}h"] = count / max(len(t) - 1, 1) if len(t) > 1 else 0.0

    return {
        "raw_entry_condition_true_bars": raw_triggers,
        "raw_trigger_runs": int(len(runs)),
        "median_trigger_run_bars": float(np.median(runs)) if runs else 0.0,
        "max_trigger_run_bars": int(max(runs)) if runs else 0,
        "executed_trades": int(len(t)),
        "raw_trigger_bars_per_trade": raw_triggers / len(t) if len(t) else None,
        **reentry,
    }


def signal_strength_series(strategy, df: pd.DataFrame, family: str) -> pd.Series:
    """Continuous causal strength measure already implied by each frozen mechanism.

    Used only for descriptive quartiles; no cutoff is selected from these data.
    """
    if family == "volume_shock_direction":
        med = df["volume"].shift(1).rolling(strategy.volume_median_window, min_periods=strategy.volume_median_window).median()
        return df["volume"] / med
    if family == "range_expansion":
        a = atr(df, strategy.atr_period)
        return true_range(df) / a
    if family == "extreme_move_reversal":
        return -strategy._return_zscore(df)  # larger = more extreme adverse move
    raise ValueError(f"unsupported Phase 4B family: {family}")


def signal_strength_quartiles(
    df: pd.DataFrame,
    strategy,
    trades_df: pd.DataFrame,
    family: str,
    timeframe: str,
    variant_id: str,
    follow_rows: pd.DataFrame,
) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()
    ts = pd.to_datetime(df["timestamp"], utc=True)
    strength = signal_strength_series(strategy, df, family)
    strength_by_time = pd.Series(strength.to_numpy(), index=ts)

    t = trades_df.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    # Signal was generated on the prior strategy bar; engine executes next open.
    step = pd.Timedelta(minutes=15 if timeframe == "15m" else 60)
    t["signal_time"] = t["entry_time"] - step
    t["strength"] = t["signal_time"].map(strength_by_time)
    t = t.dropna(subset=["strength"])
    if len(t) < 8 or t["strength"].nunique() < 4:
        return pd.DataFrame()
    t["quartile"] = pd.qcut(t["strength"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")

    f4 = follow_rows[follow_rows["horizon_minutes"] == 240].copy()
    if not f4.empty:
        f4["entry_time"] = pd.to_datetime(f4["entry_time"], utc=True)
        f4 = f4[["entry_time", "close_return"]]
        t = t.merge(f4, on="entry_time", how="left")
    else:
        t["close_return"] = np.nan

    rows = []
    for q, g in t.groupby("quartile", observed=True):
        rows.append({
            "label": POSTHOC_LABEL,
            "timeframe": timeframe,
            "family": family,
            "variant_id": variant_id,
            "quartile": str(q),
            "trades": int(len(g)),
            "mean_strength": float(g["strength"].mean()),
            "mean_trade_net_return": float(pd.to_numeric(g["return_pct"], errors="coerce").mean()),
            "win_rate": float((pd.to_numeric(g["return_pct"], errors="coerce") > 0).mean()),
            "mean_4h_close_return": float(pd.to_numeric(g["close_return"], errors="coerce").mean()),
        })
    return pd.DataFrame(rows)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def run_phase4b_diagnostics(
    config_path: str | Path = "configs/short_horizon_phase4b.yaml",
    *,
    output_root: Path = OUTPUT_ROOT,
    raw_dir: Path = Path("data/raw"),
    data_by_timeframe: dict[str, pd.DataFrame] | None = None,
) -> Path:
    phase3_before = assert_phase3_intact()
    cfg = yaml.safe_load(Path(config_path).read_text()) if Path(config_path).exists() else {}
    cfg = cfg or {}
    if cfg.get("allow_parameter_search", False):
        raise PermissionError("Phase 4B forbids parameter/threshold search")
    if tuple(cfg.get("families", list(TARGET_FAMILIES))) != TARGET_FAMILIES:
        raise ValueError(f"Phase 4B families are frozen to {TARGET_FAMILIES}")

    datasets: dict[str, pd.DataFrame] = {}
    registrations = {}
    for tf in TIMEFRAMES:
        if data_by_timeframe is not None:
            df = data_by_timeframe[tf].copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            datasets[tf] = df.sort_values("timestamp").reset_index(drop=True)
            registrations[tf] = {"timeframe": tf, "num_candles": len(df), "dataset_hash": "synthetic/injected"}
        else:
            df, reg = load_and_register(tf, raw_dir=raw_dir, allow_gaps=True)
            datasets[tf] = df
            registrations[tf] = reg.to_dict()

    master15 = datasets["15m"]
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    break_even_rows = []
    follow_all = []
    reentry_rows = []
    quartile_all = []

    base_scenario = SHORT_HORIZON_SCENARIO_BY_NAME[BASE_SCENARIO_NAME]

    for tf, fams in frozen_phase4b_variants().items():
        df = datasets[tf]
        for family, variants in fams.items():
            for i, params in enumerate(variants, 1):
                variant_id = f"{family}__{i:02d}"
                strategy = build_strategy(family, params)
                signals = strategy.generate_signals(df)
                base = _run_same_signals(
                    df, signals,
                    fee=base_scenario.trading_fee,
                    slippage=base_scenario.effective_slippage,
                )
                zero = _run_same_signals(df, signals, fee=0.0, slippage=0.0)
                bm = build_metrics_report(base, tf)
                zm = build_metrics_report(zero, tf)

                same_trade_times = [
                    (pd.Timestamp(a.entry_time), pd.Timestamp(a.exit_time))
                    for a in base.trades
                ] == [
                    (pd.Timestamp(a.entry_time), pd.Timestamp(a.exit_time))
                    for a in zero.trades
                ]
                if not same_trade_times:
                    raise RuntimeError(f"cost counterfactual changed trade path for {tf}/{variant_id}")

                base_df = base.trades_df()
                zero_df = zero.trades_df()
                base_exp = float(base_df["return_pct"].mean()) if len(base_df) else 0.0
                zero_exp = float(zero_df["return_pct"].mean()) if len(zero_df) else 0.0

                multiplier = break_even_base_cost_multiplier_from_zero_trades(
                    zero.trades,
                    base_fee=base_scenario.trading_fee,
                    base_slippage=base_scenario.effective_slippage,
                )
                break_even_rows.append({
                    "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
                    "variant_id": variant_id, "params": json.dumps(params, sort_keys=True),
                    "break_even_base_cost_multiplier": multiplier,
                    "base_round_trip_nominal_bps": 2 * (base_scenario.trading_fee + base_scenario.effective_slippage) * 10_000,
                    "break_even_round_trip_equivalent_bps": None if multiplier is None else multiplier * 2 * (base_scenario.trading_fee + base_scenario.effective_slippage) * 10_000,
                })

                summary_rows.append({
                    "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
                    "variant_id": variant_id, "params": json.dumps(params, sort_keys=True),
                    "num_trades": len(base.trades), "same_trade_path_base_vs_zero": same_trade_times,
                    "base_total_return": _safe(bm.get("total_return")),
                    "zero_cost_total_return": _safe(zm.get("total_return")),
                    "base_sharpe": _safe(bm.get("sharpe_ratio")),
                    "zero_cost_sharpe": _safe(zm.get("sharpe_ratio")),
                    "base_expectancy_pct": base_exp,
                    "zero_cost_expectancy_pct": zero_exp,
                    "expectancy_lost_to_cost_pct": zero_exp - base_exp,
                    "base_max_drawdown_pct": _safe(bm.get("max_drawdown_pct")),
                    "zero_cost_max_drawdown_pct": _safe(zm.get("max_drawdown_pct")),
                })

                follow = build_follow_through_rows(
                    base_df, master15, timeframe=tf, family=family, variant_id=variant_id
                )
                follow_all.append(follow)

                raw_condition = strategy.entry_condition(df)
                red = reentry_diagnostics(base_df, raw_condition, df["timestamp"])
                reentry_rows.append({
                    "label": POSTHOC_LABEL, "timeframe": tf, "family": family,
                    "variant_id": variant_id, "params": json.dumps(params, sort_keys=True), **red,
                })

                quart = signal_strength_quartiles(
                    df, strategy, base_df, family, tf, variant_id, follow
                )
                if not quart.empty:
                    quartile_all.append(quart)

    summary = pd.DataFrame(summary_rows)
    be = pd.DataFrame(break_even_rows)
    follow_rows = pd.concat(follow_all, ignore_index=True) if follow_all else pd.DataFrame()
    follow_summary = summarize_follow_through(follow_rows)
    reentry = pd.DataFrame(reentry_rows)
    quartiles = pd.concat(quartile_all, ignore_index=True) if quartile_all else pd.DataFrame()

    summary.to_csv(output_root / "zero_cost_counterfactual.csv", index=False)
    be.to_csv(output_root / "break_even_costs.csv", index=False)
    follow_rows.to_csv(output_root / "follow_through_trades.csv", index=False)
    follow_summary.to_csv(output_root / "follow_through_summary.csv", index=False)
    reentry.to_csv(output_root / "reentry_diagnostics.csv", index=False)
    quartiles.to_csv(output_root / "signal_strength_quartiles.csv", index=False)

    # No automatic candidate selection.  A compact diagnostic ranking is okay,
    # but it is descriptive and cannot create a new threshold or strategy.
    merged = summary.merge(be[["timeframe", "variant_id", "break_even_base_cost_multiplier"]], on=["timeframe", "variant_id"], how="left")
    merged["zero_cost_positive"] = pd.to_numeric(merged["zero_cost_expectancy_pct"], errors="coerce") > 0
    merged = merged.sort_values(["zero_cost_positive", "break_even_base_cost_multiplier", "zero_cost_expectancy_pct"], ascending=[False, False, False])
    merged.to_csv(output_root / "diagnostic_ranking.csv", index=False)

    _write_json(output_root / "metadata.json", {
        "label": POSTHOC_LABEL,
        "purpose": "diagnose gross signal magnitude vs execution cost; no parameter search",
        "families": list(TARGET_FAMILIES),
        "frozen_variants": frozen_phase4b_variants(),
        "variant_count": frozen_phase4b_variant_count(),
        "follow_through_minutes": list(FOLLOW_THROUGH_MINUTES),
        "base_cost_scenario": asdict(base_scenario),
        "datasets": registrations,
        "phase3_fingerprint_before": phase3_before,
    })

    readme = f"""# Phase 4B — Edge vs Cost Diagnostics\n\n{POSTHOC_LABEL}\n\nThis phase evaluates exactly **{frozen_phase4b_variant_count()}** Phase-4A-frozen variants from {', '.join(TARGET_FAMILIES)}.\n\nIt does **not** optimize parameters, thresholds, exits, cooldowns, maker fills, or execution assumptions. It asks whether the signal path has positive zero-cost behavior, how much of the BASE execution-cost budget it can tolerate, how price follows through after entries, whether repeated entry conditions cause churn, and whether stronger versions of the *existing causal signal* show monotonic behavior by quartile. Quartiles are descriptive only and do not define a new trading rule.\n\n`break_even_base_cost_multiplier=1.0` means the historical signal could just afford the full Phase-4A BASE fee+spread+slippage model. Values below 1 mean the observed gross edge was too small for BASE execution.\n\nAny new rule inspired by this report is post-hoc and must be preregistered for future forward validation.\n"""
    (output_root / "README.md").write_text(readme)

    phase3_after = assert_phase3_intact(phase3_before)
    meta_path = output_root / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["phase3_fingerprint_after"] = phase3_after
    _write_json(meta_path, meta)
    return output_root
