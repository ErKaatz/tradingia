"""Phase-2 research orchestration with a hard-locked final holdout."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Any
import json
import pandas as pd
import yaml

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.data.loader import dataset_hash, load_ohlcv
from src.data.validation import validate_ohlcv
from src.metrics.metrics import build_metrics_report, max_drawdown
from src.research.annual import annual_strategy_metrics
from src.research.holdout import split_final_holdout, guard_final_holdout_evaluation
from src.research.monte_carlo import monte_carlo_trade_returns
from src.research.parameter_study import generate_parameter_grid
from src.research.stress import DEFAULT_COST_SCENARIOS
from src.research.volatility_filter import apply_realized_volatility_entry_filter
from src.research.walk_forward import generate_walk_forward_windows
from src.strategies.registry import build_strategy

RESEARCH_ROOT = Path("research")


def _run_fixed(df: pd.DataFrame, strategy_name: str, params: dict[str, Any], cfg: BacktestConfig, timeframe: str, volatility_filter: dict | None = None):
    strategy = build_strategy(strategy_name, params)
    signals = strategy.generate_signals(df)
    if volatility_filter:
        signals = apply_realized_volatility_entry_filter(df, signals, **volatility_filter)
    result = BacktestEngine(cfg).run(df, signals)
    return result, build_metrics_report(result, timeframe)


def _benchmark(df: pd.DataFrame, cfg: BacktestConfig, timeframe: str) -> dict[str, Any]:
    _, metrics = _run_fixed(df, "buy_and_hold", {}, cfg, timeframe)
    return metrics


def _comparative(metrics: dict, benchmark: dict) -> dict:
    dd = metrics.get("max_drawdown_pct")
    bdd = benchmark.get("max_drawdown_pct")
    return {
        "excess_return_vs_buy_hold": metrics.get("total_return") - benchmark.get("total_return"),
        "drawdown_reduction_vs_buy_hold": (dd - bdd) if dd is not None and bdd is not None else None,
        "return_over_abs_max_drawdown": (metrics.get("total_return") / abs(dd)) if dd not in (None, 0) else None,
        "time_in_market": metrics.get("market_exposure"),
    }


def _year_summary(annual: dict[int, dict]) -> dict[str, Any]:
    vals = [m["total_return"] for m in annual.values() if m.get("total_return") is not None]
    if not vals:
        return {"positive_years": 0, "years_evaluated": 0, "worst_year": None, "best_year": None, "median_annual_return": None, "annual_return_std": None}
    s = pd.Series(vals)
    return {
        "positive_years": int((s > 0).sum()),
        "years_evaluated": len(vals),
        "worst_year": float(s.min()),
        "best_year": float(s.max()),
        "median_annual_return": float(s.median()),
        "annual_return_std": float(s.std(ddof=0)),
    }


def _parameter_cliff(rows: list[dict], metric: str = "total_return") -> dict[str, Any]:
    vals = [r[metric] for r in rows if r.get(metric) is not None]
    if len(vals) < 3:
        return {"parameter_cliff_flag": False, "dispersion": None}
    s = pd.Series(vals)
    median = float(s.median())
    best = float(s.max())
    # Heuristic only: flag a lone standout if best exceeds median by > 2 std
    std = float(s.std(ddof=0))
    return {"parameter_cliff_flag": bool(std > 0 and (best - median) > 2 * std), "dispersion": std}


def run_phase2(config_path: str | Path, raw_dir: Path = Path("data/raw"), research_root: Path = RESEARCH_ROOT) -> Path:
    with open(config_path) as f:
        cfgraw = yaml.safe_load(f)
    symbol = cfgraw.get("symbol", "BTCUSDT")
    timeframe = cfgraw.get("timeframe", "1h")
    holdout_start = cfgraw.get("final_holdout_start", "2025-01-01")
    if cfgraw.get("allow_final_holdout_evaluation", False):
        raise PermissionError("Phase 2 forbids final holdout evaluation; keep allow_final_holdout_evaluation=false")

    df = load_ohlcv(symbol, timeframe, raw_dir=raw_dir)
    validation = validate_ohlcv(df, timeframe=timeframe, allow_gaps=bool(cfgraw.get("allow_data_gaps", False)))
    validation.raise_if_invalid()
    split = split_final_holdout(df, holdout_start)
    research_df = split.research
    guard_final_holdout_evaluation(research_df, holdout_start, allow=False)

    capital = float(cfgraw.get("capital", {}).get("initial", 10_000))
    base_fee = float(cfgraw.get("fees", {}).get("trading_fee", 0.001))
    base_slippage = float(cfgraw.get("fees", {}).get("slippage", 0.0002))
    base_cfg = BacktestConfig(capital, base_fee, base_slippage, float(cfgraw.get("position_size_fraction", 1.0)))

    research_root.mkdir(parents=True, exist_ok=True)
    reports = research_root / "reports"; reports.mkdir(exist_ok=True)
    studies_dir = research_root / "parameter_studies"; studies_dir.mkdir(exist_ok=True)
    wf_dir = research_root / "walk_forward"; wf_dir.mkdir(exist_ok=True)
    mc_dir = research_root / "monte_carlo"; mc_dir.mkdir(exist_ok=True)

    benchmark = _benchmark(research_df, base_cfg, timeframe)
    families = cfgraw.get("families", {})
    all_rows: list[dict[str, Any]] = []
    total_variants = 0
    family_summaries: dict[str, Any] = {}

    for strategy_name, spec in families.items():
        grid = generate_parameter_grid(strategy_name, spec.get("parameter_study", {}))
        total_variants += len(grid)
        family_rows = []
        for idx, params in enumerate(grid, 1):
            result, metrics = _run_fixed(research_df, strategy_name, params, base_cfg, timeframe, spec.get("volatility_filter"))
            annual = annual_strategy_metrics(research_df, lambda n=strategy_name, p=params: build_strategy(n, p), base_cfg, timeframe)
            row = {
                "strategy": strategy_name,
                "variant": idx,
                "params": json.dumps(params, sort_keys=True),
                **{k: metrics.get(k) for k in ["total_return","annualized_return","sharpe_ratio","sortino_ratio","max_drawdown_pct","profit_factor","expectancy","num_trades","market_exposure","total_fees"]},
                **_comparative(metrics, benchmark),
                **_year_summary(annual),
            }
            family_rows.append(row); all_rows.append(row)
            variant_dir = studies_dir / strategy_name / f"variant_{idx:03d}"
            variant_dir.mkdir(parents=True, exist_ok=True)
            result.trades_df().to_csv(variant_dir / "trades.csv", index=False)
            result.equity_curve.to_csv(variant_dir / "equity.csv", index=False)
            with open(variant_dir / "metrics.json", "w") as f: json.dump({"params": params, "metrics": metrics, "annual": annual}, f, indent=2, default=str)
        pd.DataFrame(family_rows).to_csv(studies_dir / f"{strategy_name}.csv", index=False)
        family_summaries[strategy_name] = {"variants": len(grid), **_parameter_cliff(family_rows)}

    all_df = pd.DataFrame(all_rows)
    all_df.to_csv(reports / "all_variants.csv", index=False)

    # Cost stress for the top two variants per family by return/drawdown ratio,
    # but this is reporting, not parameter mutation or re-optimization.
    stress_rows = []
    for strategy_name in families:
        fam = all_df[all_df.strategy == strategy_name].copy()
        if fam.empty: continue
        fam["rank_metric"] = fam["return_over_abs_max_drawdown"].fillna(-1e99)
        for _, picked in fam.nlargest(min(2, len(fam)), "rank_metric").iterrows():
            params = json.loads(picked["params"])
            for scenario in DEFAULT_COST_SCENARIOS:
                scfg = BacktestConfig(capital, base_fee * scenario.fee_multiplier, base_slippage * scenario.slippage_multiplier, base_cfg.position_size_fraction)
                _, m = _run_fixed(research_df, strategy_name, params, scfg, timeframe, families[strategy_name].get("volatility_filter"))
                stress_rows.append({"strategy": strategy_name, "params": json.dumps(params, sort_keys=True), "scenario": scenario.name, "fee": scfg.trading_fee, "slippage": scfg.slippage, "total_return": m["total_return"], "max_drawdown_pct": m["max_drawdown_pct"], "num_trades": m["num_trades"]})
    stress_df = pd.DataFrame(stress_rows)
    stress_df.to_csv(reports / "cost_stress.csv", index=False)

    # Pre-registered Phase-2 classification. These labels are research triage,
    # never claims of profitability. Cost stress can downgrade a candidate.
    classifications = []
    for _, row in all_df.iterrows():
        strategy_name = row["strategy"]
        family_info = family_summaries[strategy_name]
        years = int(row.get("years_evaluated", 0) or 0)
        trades = int(row.get("num_trades", 0) or 0)
        label = "PROMISING BUT UNPROVEN"
        reasons = []
        if trades < 30 or years < 3:
            label = "NEEDS MORE DATA/TESTING"
            reasons.append("insufficient trade count or calendar-year coverage")
        if row.get("total_return") is None or row["total_return"] <= 0:
            label = "REJECTED"
            reasons.append("non-positive research-period return after base costs")
        if years and int(row.get("positive_years", 0) or 0) * 2 < years:
            label = "REJECTED"
            reasons.append("fewer than half of evaluated years were positive")
        if family_info.get("parameter_cliff_flag"):
            if label == "PROMISING BUT UNPROVEN":
                label = "NEEDS MORE DATA/TESTING"
            reasons.append("family-level parameter-cliff warning")
        params_text = row["params"]
        stressed = stress_df[(stress_df.strategy == strategy_name) & (stress_df.params == params_text)] if not stress_df.empty else pd.DataFrame()
        worst = stressed[stressed.scenario == "E_fee_x2_slippage_x3"] if not stressed.empty else pd.DataFrame()
        if not worst.empty and float(worst.iloc[0].total_return) <= 0:
            if label == "PROMISING BUT UNPROVEN":
                label = "NEEDS MORE DATA/TESTING"
            reasons.append("selected stress test loses edge under fee x2 + slippage x3")
        classifications.append({"strategy": strategy_name, "variant": int(row["variant"]), "params": params_text, "classification": label, "reasons": "; ".join(reasons) or "passes pre-registered Phase-2 triage criteria"})
    class_df = pd.DataFrame(classifications)
    class_df.to_csv(reports / "classifications.csv", index=False)

    # Fixed-parameter walk-forward: best-by-predeclared rank metric is used only
    # for reporting candidates within research data; no in-window optimization occurs.
    wf_rows = []
    wf_windows = generate_walk_forward_windows(research_df, int(cfgraw.get("walk_forward", {}).get("train_months", 24)), int(cfgraw.get("walk_forward", {}).get("evaluation_months", 6)))
    for strategy_name in families:
        fam = all_df[all_df.strategy == strategy_name].copy()
        if fam.empty: continue
        fam["rank_metric"] = fam["return_over_abs_max_drawdown"].fillna(-1e99)
        picked = fam.nlargest(1, "rank_metric").iloc[0]
        params = json.loads(picked["params"])
        strategy = build_strategy(strategy_name, params)
        for wi, w in enumerate(wf_windows, 1):
            eval_mask = (pd.to_datetime(research_df.timestamp, utc=True) >= w.evaluation_start) & (pd.to_datetime(research_df.timestamp, utc=True) <= w.evaluation_end)
            eval_indices = research_df.index[eval_mask]
            if len(eval_indices) < 2: continue
            start = int(eval_indices[0]); end = int(eval_indices[-1]) + 1
            warm_start = max(0, start - strategy.warmup_bars)
            ext = research_df.iloc[warm_start:end].reset_index(drop=True)
            eval_start_idx = start - warm_start
            sig = build_strategy(strategy_name, params).generate_signals(ext)
            if families[strategy_name].get("volatility_filter"):
                sig = apply_realized_volatility_entry_filter(ext, sig, **families[strategy_name]["volatility_filter"])
            res = BacktestEngine(base_cfg).run(ext, sig, evaluation_start=eval_start_idx)
            m = build_metrics_report(res, timeframe)
            wf_rows.append({"strategy": strategy_name, "params": json.dumps(params, sort_keys=True), "window": wi, "train_start": w.train_start, "train_end": w.train_end, "evaluation_start": w.evaluation_start, "evaluation_end": w.evaluation_end, "total_return": m["total_return"], "max_drawdown_pct": m["max_drawdown_pct"], "num_trades": m["num_trades"]})
    pd.DataFrame(wf_rows).to_csv(wf_dir / "fixed_parameter_walk_forward.csv", index=False)

    # Monte Carlo only for one representative per family with >= 5 trades.
    mc_summaries = []
    for strategy_name in families:
        fam = all_df[(all_df.strategy == strategy_name) & (all_df.num_trades >= 5)].copy()
        if fam.empty: continue
        fam["rank_metric"] = fam["return_over_abs_max_drawdown"].fillna(-1e99)
        picked = fam.nlargest(1, "rank_metric").iloc[0]
        params = json.loads(picked["params"])
        res, _ = _run_fixed(research_df, strategy_name, params, base_cfg, timeframe, families[strategy_name].get("volatility_filter"))
        trade_returns = [t.return_pct for t in res.trades]
        summary, finals, dds = monte_carlo_trade_returns(trade_returns, simulations=int(cfgraw.get("monte_carlo", {}).get("simulations", 1000)), seed=int(cfgraw.get("monte_carlo", {}).get("seed", 42)))
        payload = {"strategy": strategy_name, "params": params, **asdict(summary)}
        mc_summaries.append(payload)
        pd.DataFrame({"final_return": finals, "max_drawdown": dds}).to_csv(mc_dir / f"{strategy_name}.csv", index=False)
    with open(mc_dir / "summary.json", "w") as f: json.dump(mc_summaries, f, indent=2)

    metadata = {
        "symbol": symbol, "timeframe": timeframe,
        "dataset_hash_full": dataset_hash(df), "dataset_hash_research": dataset_hash(research_df),
        "full_start": str(df.timestamp.iloc[0]), "full_end": str(df.timestamp.iloc[-1]), "full_bars": len(df),
        "research_start": str(research_df.timestamp.iloc[0]), "research_end": str(research_df.timestamp.iloc[-1]), "research_bars": len(research_df),
        "final_holdout_start": str(split.cutoff), "final_holdout_bars_locked": len(split.final_holdout),
        "allow_final_holdout_evaluation": False,
        "total_variants_evaluated": total_variants,
        "hypothesis_families": len(families),
        "benchmark": benchmark,
        "data_validation": {"gap_count": validation.gap_count, "gap_examples": validation.gap_examples, "warnings": validation.warnings},
        "family_summaries": family_summaries,
    }
    with open(reports / "phase2_metadata.json", "w") as f: json.dump(metadata, f, indent=2, default=str)

    counts = class_df["classification"].value_counts().to_dict() if not class_df.empty else {}
    with open(reports / "summary.md", "w") as f:
        f.write("# Phase 2 research summary\n\n")
        f.write(f"- Symbol/timeframe: {symbol} {timeframe}\n")
        f.write(f"- Research period: {research_df.timestamp.iloc[0]} -> {research_df.timestamp.iloc[-1]}\n")
        f.write(f"- FINAL_HOLDOUT locked from: {split.cutoff} ({len(split.final_holdout)} bars not evaluated)\n")
        f.write(f"- Hypothesis families: {len(families)}\n")
        f.write(f"- Parameter variants evaluated: {total_variants}\n")
        f.write(f"- Classifications: {counts}\n\n")
        f.write("No label in this report means profitable, proven, safe, or guaranteed.\n")
    return reports
