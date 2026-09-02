"""Phase 2.5: focused breakout plateau and robustness study.

This phase deliberately keeps FINAL_HOLDOUT locked. It narrows research to a
pre-registered neighborhood around the long-lookback breakout family and adds
local parameter-plateau, cost, walk-forward and entry-regime diagnostics.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import json
import math

import pandas as pd
import yaml

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.data.loader import dataset_hash, load_ohlcv
from src.data.validation import validate_ohlcv
from src.metrics.metrics import build_metrics_report
from src.research.annual import annual_strategy_metrics
from src.research.holdout import guard_final_holdout_evaluation, split_final_holdout
from src.research.monte_carlo import monte_carlo_trade_returns
from src.research.stress import DEFAULT_COST_SCENARIOS
from src.research.walk_forward import generate_walk_forward_windows
from src.strategies.breakout import Breakout
from src.strategies.buy_and_hold import BuyAndHold

PHASE25_ROOT = Path("research/phase25")


def _run(df: pd.DataFrame, strategy, cfg: BacktestConfig, timeframe: str):
    signals = strategy.generate_signals(df)
    result = BacktestEngine(cfg).run(df, signals)
    return result, build_metrics_report(result, timeframe)


def _year_summary(annual: dict[int, dict[str, Any]]) -> dict[str, Any]:
    vals = [m.get("total_return") for m in annual.values() if m.get("total_return") is not None]
    if not vals:
        return {"positive_years": 0, "years_evaluated": 0, "worst_year": None, "best_year": None, "median_annual_return": None}
    s = pd.Series(vals, dtype=float)
    return {
        "positive_years": int((s > 0).sum()),
        "years_evaluated": int(len(s)),
        "worst_year": float(s.min()),
        "best_year": float(s.max()),
        "median_annual_return": float(s.median()),
    }


def _local_neighbors(rows: pd.DataFrame, entry_values: list[int], exit_values: list[int], entry: int, exit_: int) -> pd.DataFrame:
    ei = entry_values.index(entry)
    xi = exit_values.index(exit_)
    allowed_e = {entry_values[i] for i in range(max(0, ei - 1), min(len(entry_values), ei + 2))}
    allowed_x = {exit_values[i] for i in range(max(0, xi - 1), min(len(exit_values), xi + 2))}
    mask = rows["entry_lookback"].isin(allowed_e) & rows["exit_lookback"].isin(allowed_x)
    # Exclude self: this is intended to answer whether the surrounding region survives.
    mask &= ~((rows["entry_lookback"] == entry) & (rows["exit_lookback"] == exit_))
    return rows.loc[mask].copy()


def add_plateau_metrics(rows: pd.DataFrame, entry_values: list[int], exit_values: list[int]) -> pd.DataFrame:
    """Add local, predeclared parameter-plateau diagnostics.

    Plateau criteria (fixed before Phase-2.5 results are inspected):
    * >= 60% immediate grid neighbors have positive total return;
    * median neighbor return is >= 50% of the candidate return when candidate > 0;
    * candidate return is not > 2.5x positive median-neighbor return.
    These are diagnostics, not proof of edge.
    """
    out = rows.copy()
    metrics: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        neigh = _local_neighbors(out, entry_values, exit_values, int(row.entry_lookback), int(row.exit_lookback))
        positive_fraction = float((neigh.total_return > 0).mean()) if len(neigh) else None
        median_return = float(neigh.total_return.median()) if len(neigh) else None
        candidate = float(row.total_return)
        median_ratio = (median_return / candidate) if candidate > 0 and median_return is not None else None
        standout_ratio = (candidate / median_return) if candidate > 0 and median_return is not None and median_return > 0 else None
        plateau = bool(
            len(neigh) >= 3
            and positive_fraction is not None and positive_fraction >= 0.60
            and median_ratio is not None and median_ratio >= 0.50
            and standout_ratio is not None and standout_ratio <= 2.50
        )
        metrics.append({
            "neighbor_count": int(len(neigh)),
            "neighbor_positive_fraction": positive_fraction,
            "neighbor_median_return": median_return,
            "neighbor_median_vs_candidate": median_ratio,
            "candidate_vs_neighbor_median": standout_ratio,
            "plateau_flag": plateau,
        })
    return pd.concat([out.reset_index(drop=True), pd.DataFrame(metrics)], axis=1)


def _trailing_regimes(df: pd.DataFrame) -> pd.DataFrame:
    """Objective entry-time regimes using only trailing information.

    Trend: trailing 90-day (2160h) close return: >+10% bull, <-10% bear, else sideways.
    Volatility: trailing 30-day (720h) realized annualized hourly vol:
      <50% low, 50-100% medium, >=100% high.
    Thresholds are predeclared and do not use future/global quantiles.
    """
    out = df[["timestamp", "close"]].copy()
    close = pd.to_numeric(out.close, errors="coerce")
    ret90 = close / close.shift(2160) - 1.0
    hourly = close.pct_change()
    vol30 = hourly.rolling(720, min_periods=720).std(ddof=0) * math.sqrt(24 * 365)
    out["trend_regime"] = "unknown"
    out.loc[ret90 > 0.10, "trend_regime"] = "bull"
    out.loc[ret90 < -0.10, "trend_regime"] = "bear"
    out.loc[(ret90 >= -0.10) & (ret90 <= 0.10), "trend_regime"] = "sideways"
    out["vol_regime"] = "unknown"
    out.loc[vol30 < 0.50, "vol_regime"] = "low"
    out.loc[(vol30 >= 0.50) & (vol30 < 1.00), "vol_regime"] = "medium"
    out.loc[vol30 >= 1.00, "vol_regime"] = "high"
    return out


def trade_regime_report(df: pd.DataFrame, trades_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["trend_regime", "vol_regime", "trades", "win_rate", "mean_trade_return", "median_trade_return", "sum_trade_return"]
    if trades_df.empty:
        return pd.DataFrame(columns=columns)
    regimes = _trailing_regimes(df)
    regimes["timestamp"] = pd.to_datetime(regimes.timestamp, utc=True)
    t = trades_df.copy()
    t["entry_time"] = pd.to_datetime(t.entry_time, utc=True)
    joined = t.merge(regimes.rename(columns={"timestamp": "entry_time"})[["entry_time", "trend_regime", "vol_regime"]], on="entry_time", how="left")
    rows = []
    for (trend, vol), g in joined.groupby(["trend_regime", "vol_regime"], dropna=False):
        returns = pd.to_numeric(g.return_pct, errors="coerce")
        rows.append({
            "trend_regime": trend,
            "vol_regime": vol,
            "trades": int(len(g)),
            "win_rate": float((returns > 0).mean()) if len(g) else None,
            "mean_trade_return": float(returns.mean()) if len(g) else None,
            "median_trade_return": float(returns.median()) if len(g) else None,
            "sum_trade_return": float(returns.sum()) if len(g) else None,
        })
    return pd.DataFrame(rows, columns=columns)


def classify_phase25(row: pd.Series, stress_e_return: float | None) -> tuple[str, str]:
    """Stricter research triage than Phase 2; never a profitability claim."""
    reasons: list[str] = []
    trades = int(row.num_trades or 0)
    years = int(row.years_evaluated or 0)
    positives = int(row.positive_years or 0)
    ret = float(row.total_return)
    dd_reduction = float(row.drawdown_reduction_vs_buy_hold)

    if ret <= 0:
        return "REJECTED", "non-positive research-period return after base costs"
    if trades < 50 or years < 5:
        reasons.append("insufficient trade count or long-horizon calendar coverage")
    if years and positives / years < 0.60:
        reasons.append("fewer than 60% of evaluated calendar years were positive")
    if not bool(row.plateau_flag):
        reasons.append("fails local parameter-plateau criterion")
    if stress_e_return is None:
        reasons.append("extreme cost stress not available")
    elif stress_e_return <= 0:
        reasons.append("non-positive under fee x2 + slippage x3")
    # A candidate need not beat B&H return, but must offer either excess return
    # or a material drawdown reduction of >= 20 percentage points.
    excess = float(row.excess_return_vs_buy_hold)
    if excess <= 0 and dd_reduction < 20.0:
        reasons.append("neither excess return nor >=20pp drawdown reduction vs Buy & Hold")

    if not reasons:
        return "PROMISING BUT UNPROVEN", "passes pre-registered Phase-2.5 triage criteria"
    hard_fail = any("fewer than 60%" in r or "non-positive under" in r or "neither excess" in r for r in reasons)
    return ("REJECTED" if hard_fail else "NEEDS MORE DATA/TESTING"), "; ".join(reasons)


def run_phase25(config_path: str | Path, raw_dir: Path = Path("data/raw"), output_root: Path = PHASE25_ROOT) -> Path:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if raw.get("allow_final_holdout_evaluation", False):
        raise PermissionError("Phase 2.5 forbids final holdout evaluation")

    symbol = raw.get("symbol", "BTCUSDT")
    timeframe = raw.get("timeframe", "1h")
    holdout_start = raw.get("final_holdout_start", "2025-01-01")
    df = load_ohlcv(symbol, timeframe, raw_dir=raw_dir)
    validation = validate_ohlcv(df, timeframe=timeframe, allow_gaps=bool(raw.get("allow_data_gaps", False)))
    validation.raise_if_invalid()
    split = split_final_holdout(df, holdout_start)
    research_df = split.research
    guard_final_holdout_evaluation(research_df, holdout_start, allow=False)

    cap = float(raw.get("capital", {}).get("initial", 10_000))
    fee = float(raw.get("fees", {}).get("trading_fee", 0.001))
    slip = float(raw.get("fees", {}).get("slippage", 0.0002))
    base_cfg = BacktestConfig(cap, fee, slip, float(raw.get("position_size_fraction", 1.0)))

    grid_cfg = raw["breakout_plateau"]
    entry_values = [int(v) for v in grid_cfg["entry_lookback"]]
    exit_values = [int(v) for v in grid_cfg["exit_lookback"]]
    combos = [(e, x) for e in entry_values for x in exit_values]

    output_root.mkdir(parents=True, exist_ok=True)
    variants_dir = output_root / "variants"; variants_dir.mkdir(exist_ok=True)
    stress_dir = output_root / "stress"; stress_dir.mkdir(exist_ok=True)
    wf_dir = output_root / "walk_forward"; wf_dir.mkdir(exist_ok=True)
    regime_dir = output_root / "regimes"; regime_dir.mkdir(exist_ok=True)
    mc_dir = output_root / "monte_carlo"; mc_dir.mkdir(exist_ok=True)

    bh_res, bh = _run(research_df, BuyAndHold(), base_cfg, timeframe)
    rows: list[dict[str, Any]] = []
    results: dict[tuple[int, int], Any] = {}
    for idx, (entry, exit_) in enumerate(combos, 1):
        strat = Breakout(entry, exit_)
        result, metrics = _run(research_df, strat, base_cfg, timeframe)
        annual = annual_strategy_metrics(research_df, lambda e=entry, x=exit_: Breakout(e, x), base_cfg, timeframe)
        results[(entry, exit_)] = result
        dd = metrics.get("max_drawdown_pct")
        bdd = bh.get("max_drawdown_pct")
        row = {
            "variant": idx, "entry_lookback": entry, "exit_lookback": exit_,
            **{k: metrics.get(k) for k in ["total_return", "annualized_return", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct", "profit_factor", "expectancy", "num_trades", "market_exposure", "total_fees"]},
            "excess_return_vs_buy_hold": metrics["total_return"] - bh["total_return"],
            "drawdown_reduction_vs_buy_hold": (dd - bdd) if dd is not None and bdd is not None else None,
            "return_over_abs_max_drawdown": metrics["total_return"] / abs(dd) if dd not in (None, 0) else None,
            **_year_summary(annual),
        }
        rows.append(row)
        vdir = variants_dir / f"variant_{idx:03d}_{entry}_{exit_}"; vdir.mkdir(exist_ok=True)
        result.trades_df().to_csv(vdir / "trades.csv", index=False)
        with open(vdir / "metrics.json", "w") as f:
            json.dump({"params": {"entry_lookback": entry, "exit_lookback": exit_}, "metrics": metrics, "annual": annual}, f, indent=2, default=str)

    table = add_plateau_metrics(pd.DataFrame(rows), entry_values, exit_values)

    # Every 2.5 variant receives the same predeclared cost scenarios; no top-pick
    # selection is used to decide who gets stress-tested.
    stress_rows = []
    stress_e: dict[tuple[int, int], float] = {}
    for entry, exit_ in combos:
        for scenario in DEFAULT_COST_SCENARIOS:
            cfg = BacktestConfig(cap, fee * scenario.fee_multiplier, slip * scenario.slippage_multiplier, base_cfg.position_size_fraction)
            _, m = _run(research_df, Breakout(entry, exit_), cfg, timeframe)
            stress_rows.append({"entry_lookback": entry, "exit_lookback": exit_, "scenario": scenario.name, "total_return": m["total_return"], "max_drawdown_pct": m["max_drawdown_pct"], "num_trades": m["num_trades"]})
            if scenario.name == "E_fee_x2_slippage_x3":
                stress_e[(entry, exit_)] = float(m["total_return"])
    pd.DataFrame(stress_rows).to_csv(stress_dir / "all_variants_cost_stress.csv", index=False)

    classifications = []
    for _, row in table.iterrows():
        key = (int(row.entry_lookback), int(row.exit_lookback))
        label, reasons = classify_phase25(row, stress_e.get(key))
        classifications.append({"entry_lookback": key[0], "exit_lookback": key[1], "classification": label, "reasons": reasons})
    class_df = pd.DataFrame(classifications)
    table = table.merge(class_df, on=["entry_lookback", "exit_lookback"], how="left")
    table.to_csv(output_root / "breakout_plateau.csv", index=False)

    # Fixed-parameter walk-forward for every plateau-passing candidate. This is
    # still not train-window optimization.
    windows = generate_walk_forward_windows(research_df, int(raw.get("walk_forward", {}).get("train_months", 24)), int(raw.get("walk_forward", {}).get("evaluation_months", 6)))
    wf_rows = []
    plateau_rows = table[table.plateau_flag == True]  # noqa: E712
    for _, row in plateau_rows.iterrows():
        entry, exit_ = int(row.entry_lookback), int(row.exit_lookback)
        warm = max(entry, exit_)
        for wi, w in enumerate(windows, 1):
            ts = pd.to_datetime(research_df.timestamp, utc=True)
            idxs = research_df.index[(ts >= w.evaluation_start) & (ts <= w.evaluation_end)]
            if len(idxs) < 2:
                continue
            start, end = int(idxs[0]), int(idxs[-1]) + 1
            warm_start = max(0, start - warm)
            ext = research_df.iloc[warm_start:end].reset_index(drop=True)
            signals = Breakout(entry, exit_).generate_signals(ext)
            res = BacktestEngine(base_cfg).run(ext, signals, evaluation_start=start - warm_start)
            m = build_metrics_report(res, timeframe)
            wf_rows.append({"entry_lookback": entry, "exit_lookback": exit_, "window": wi, "evaluation_start": w.evaluation_start, "evaluation_end": w.evaluation_end, "total_return": m["total_return"], "max_drawdown_pct": m["max_drawdown_pct"], "num_trades": m["num_trades"]})
    pd.DataFrame(wf_rows).to_csv(wf_dir / "plateau_fixed_parameter.csv", index=False)

    # Regime diagnostics and Monte Carlo for plateau candidates only. Regimes are
    # assigned from trailing info at trade entry, never used to alter trades.
    mc_summaries = []
    sims = int(raw.get("monte_carlo", {}).get("simulations", 2000))
    seed = int(raw.get("monte_carlo", {}).get("seed", 425))
    for _, row in plateau_rows.iterrows():
        entry, exit_ = int(row.entry_lookback), int(row.exit_lookback)
        result = results[(entry, exit_)]
        trades = result.trades_df()
        trade_regime_report(research_df, trades).to_csv(regime_dir / f"breakout_{entry}_{exit_}.csv", index=False)
        if len(result.trades) >= 5:
            summary, finals, dds = monte_carlo_trade_returns([t.return_pct for t in result.trades], simulations=sims, seed=seed)
            mc_summaries.append({"entry_lookback": entry, "exit_lookback": exit_, **asdict(summary)})
            pd.DataFrame({"final_return": finals, "max_drawdown": dds}).to_csv(mc_dir / f"breakout_{entry}_{exit_}.csv", index=False)
    with open(mc_dir / "summary.json", "w") as f:
        json.dump(mc_summaries, f, indent=2)

    metadata = {
        "phase": "2.5",
        "symbol": symbol,
        "timeframe": timeframe,
        "dataset_hash_full": dataset_hash(df),
        "dataset_hash_research": dataset_hash(research_df),
        "research_start": str(research_df.timestamp.iloc[0]),
        "research_end": str(research_df.timestamp.iloc[-1]),
        "research_bars": len(research_df),
        "final_holdout_start": str(split.cutoff),
        "final_holdout_bars_locked": len(split.final_holdout),
        "allow_final_holdout_evaluation": False,
        "variants_evaluated": len(combos),
        "entry_grid": entry_values,
        "exit_grid": exit_values,
        "plateau_criteria": {"neighbor_positive_fraction_min": 0.60, "neighbor_median_vs_candidate_min": 0.50, "candidate_vs_neighbor_median_max": 2.50},
        "classifier": {"min_trades": 50, "min_years": 5, "min_positive_year_fraction": 0.60, "extreme_cost_stress_must_be_positive": True, "either_excess_return_or_drawdown_reduction_pp": 20.0},
        "regime_definition": {"trend": "trailing 90d return >+10 bull, <-10 bear, else sideways", "volatility": "trailing 30d annualized hourly vol <50 low, 50-100 medium, >=100 high"},
        "benchmark": bh,
        "data_validation": {"gap_count": validation.gap_count, "gap_examples": validation.gap_examples, "warnings": validation.warnings},
    }
    with open(output_root / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    counts = class_df.classification.value_counts().to_dict()
    with open(output_root / "summary.md", "w") as f:
        f.write("# Phase 2.5 — breakout robustness\n\n")
        f.write(f"- Pre-registered variants evaluated: {len(combos)}\n")
        f.write(f"- Plateau-pass variants: {int(table.plateau_flag.sum())}\n")
        f.write(f"- Classifications: {counts}\n")
        f.write(f"- FINAL_HOLDOUT remains locked from {split.cutoff} ({len(split.final_holdout)} bars not evaluated).\n\n")
        f.write("No Phase-2.5 label means profitable, proven, safe, or guaranteed.\n")
    return output_root
