"""One-time final holdout evaluation for two pre-registered breakout candidates.

This module intentionally hard-codes the only allowed candidates so that the
2025+ holdout cannot become another parameter-search surface after results are
seen. The holdout is evaluated with pre-holdout history only as indicator
warm-up context and a FLAT portfolio at the holdout boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pandas as pd
import yaml

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.data.loader import dataset_hash, load_ohlcv
from src.data.validation import validate_ohlcv
from src.metrics.metrics import build_metrics_report
from src.research.annual import annual_strategy_metrics
from src.research.holdout import split_final_holdout
from src.research.stress import DEFAULT_COST_SCENARIOS
from src.strategies.breakout import Breakout
from src.strategies.buy_and_hold import BuyAndHold

HOLDOUT_ROOT = Path("research/final_holdout")
FROZEN_CANDIDATES = ((168, 60), (168, 72))
EXPECTED_HOLDOUT_START = "2025-01-01"


def _normalize_candidates(raw: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(raw, list):
        raise ValueError("candidates must be a list of exactly two breakout parameter objects")
    parsed: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each candidate must be an object")
        parsed.append((int(item["entry_lookback"]), int(item["exit_lookback"])))
    return tuple(parsed)


def validate_preregistration(raw: dict[str, Any]) -> None:
    """Reject any attempt to change the preregistered holdout experiment."""
    start = str(raw.get("final_holdout_start", EXPECTED_HOLDOUT_START))
    if start != EXPECTED_HOLDOUT_START:
        raise PermissionError(
            f"final holdout boundary is frozen at {EXPECTED_HOLDOUT_START}; got {start}"
        )
    candidates = _normalize_candidates(raw.get("candidates", []))
    if candidates != FROZEN_CANDIDATES:
        raise PermissionError(
            f"holdout candidates are frozen and ordered as {FROZEN_CANDIDATES}; got {candidates}"
        )
    if raw.get("allow_parameter_search", False):
        raise PermissionError("parameter search is forbidden during final holdout evaluation")


def _run_with_warmup(
    research_df: pd.DataFrame,
    holdout_df: pd.DataFrame,
    strategy,
    cfg: BacktestConfig,
    timeframe: str,
):
    warmup = int(strategy.warmup_bars)
    context = research_df.tail(warmup).copy()
    combined = pd.concat([context, holdout_df], ignore_index=True)
    signals = strategy.generate_signals(combined)
    result = BacktestEngine(cfg).run(combined, signals, evaluation_start=len(context))
    return result, build_metrics_report(result, timeframe)


def _serialize_annual(annual: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {str(year): metrics for year, metrics in annual.items()}


def run_final_holdout(
    config_path: str | Path,
    raw_dir: Path = Path("data/raw"),
    output_root: Path = HOLDOUT_ROOT,
) -> Path:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    validate_preregistration(raw)

    symbol = raw.get("symbol", "BTCUSDT")
    timeframe = raw.get("timeframe", "1h")
    holdout_start = raw["final_holdout_start"]
    df = load_ohlcv(symbol, timeframe, raw_dir=raw_dir)
    validation = validate_ohlcv(
        df,
        timeframe=timeframe,
        allow_gaps=bool(raw.get("allow_data_gaps", False)),
    )
    validation.raise_if_invalid()
    split = split_final_holdout(df, holdout_start)
    if split.final_holdout.empty:
        raise ValueError("final holdout is empty")

    cap = float(raw.get("capital", {}).get("initial", 10_000))
    fee = float(raw.get("fees", {}).get("trading_fee", 0.001))
    slip = float(raw.get("fees", {}).get("slippage", 0.0002))
    pos = float(raw.get("position_size_fraction", 1.0))
    base_cfg = BacktestConfig(cap, fee, slip, pos)

    output_root.mkdir(parents=True, exist_ok=True)
    variants_dir = output_root / "variants"
    variants_dir.mkdir(exist_ok=True)
    stress_dir = output_root / "cost_stress"
    stress_dir.mkdir(exist_ok=True)

    # Same-period Buy & Hold benchmark, also starting flat at the boundary.
    bh_result, bh_metrics = _run_with_warmup(
        split.research, split.final_holdout, BuyAndHold(), base_cfg, timeframe
    )
    bh_result.equity_curve.to_csv(output_root / "buy_and_hold_equity.csv", index=False)
    with open(output_root / "buy_and_hold_metrics.json", "w") as f:
        json.dump(bh_metrics, f, indent=2, default=str)

    summary_rows: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []

    for entry, exit_ in FROZEN_CANDIDATES:
        strategy = Breakout(entry, exit_)
        result, metrics = _run_with_warmup(
            split.research, split.final_holdout, strategy, base_cfg, timeframe
        )
        # Annual holdout metrics need the same pre-holdout indicator context as
        # the aggregate holdout run.  Pass only the minimum trailing research
        # context, then discard any pre-holdout calendar years from the report.
        annual_context = pd.concat(
            [split.research.tail(int(strategy.warmup_bars)), split.final_holdout],
            ignore_index=True,
        )
        annual = annual_strategy_metrics(
            annual_context,
            lambda e=entry, x=exit_: Breakout(e, x),
            base_cfg,
            timeframe,
        )
        holdout_year = pd.Timestamp(holdout_start).year
        annual = {year: values for year, values in annual.items() if year >= holdout_year}
        vdir = variants_dir / f"breakout_{entry}_{exit_}"
        vdir.mkdir(exist_ok=True)
        result.trades_df().to_csv(vdir / "trades.csv", index=False)
        result.equity_curve.to_csv(vdir / "equity.csv", index=False)
        with open(vdir / "metrics.json", "w") as f:
            json.dump(
                {
                    "params": {"entry_lookback": entry, "exit_lookback": exit_},
                    "metrics": metrics,
                    "annual": _serialize_annual(annual),
                },
                f,
                indent=2,
                default=str,
            )

        summary_rows.append(
            {
                "entry_lookback": entry,
                "exit_lookback": exit_,
                "total_return": metrics.get("total_return"),
                "annualized_return": metrics.get("annualized_return"),
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "sortino_ratio": metrics.get("sortino_ratio"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "profit_factor": metrics.get("profit_factor"),
                "win_rate": metrics.get("win_rate"),
                "num_trades": metrics.get("num_trades"),
                "market_exposure": metrics.get("market_exposure"),
                "total_fees": metrics.get("total_fees"),
                "buy_hold_total_return": bh_metrics.get("total_return"),
                "buy_hold_max_drawdown_pct": bh_metrics.get("max_drawdown_pct"),
            }
        )

        # Pre-registered robustness check only; no parameter changes are allowed.
        for scenario in DEFAULT_COST_SCENARIOS:
            cfg = BacktestConfig(
                cap,
                fee * scenario.fee_multiplier,
                slip * scenario.slippage_multiplier,
                pos,
            )
            _, sm = _run_with_warmup(
                split.research, split.final_holdout, strategy, cfg, timeframe
            )
            stress_rows.append(
                {
                    "entry_lookback": entry,
                    "exit_lookback": exit_,
                    "scenario": scenario.name,
                    "total_return": sm.get("total_return"),
                    "max_drawdown_pct": sm.get("max_drawdown_pct"),
                    "num_trades": sm.get("num_trades"),
                }
            )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output_root / "summary.csv", index=False)
    pd.DataFrame(stress_rows).to_csv(stress_dir / "cost_stress.csv", index=False)

    metadata = {
        "status": "FINAL_HOLDOUT_CONSUMED_FOR_PREREGISTERED_CANDIDATES",
        "symbol": symbol,
        "timeframe": timeframe,
        "final_holdout_start": str(pd.Timestamp(holdout_start).date()),
        "final_holdout_end": str(pd.to_datetime(split.final_holdout["timestamp"], utc=True).max()),
        "holdout_bars": int(len(split.final_holdout)),
        "research_bars_used_only_as_warmup_source": int(len(split.research)),
        "dataset_hash": dataset_hash(df),
        "frozen_candidates": [
            {"entry_lookback": e, "exit_lookback": x} for e, x in FROZEN_CANDIDATES
        ],
        "portfolio_boundary_semantics": "FLAT at holdout start; pre-2025 rows are indicator warm-up only",
        "selection_rule": "no third candidate and no parameter search after holdout inspection",
        "base_costs": {"trading_fee": fee, "slippage": slip},
    }
    with open(output_root / "HOLDOUT_CONSUMED.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    with open(output_root / "PREREGISTRATION.md", "w") as f:
        f.write(
            "# Final holdout preregistration\n\n"
            "This file records the decision made before inspecting 2025+ results.\n\n"
            "- Holdout boundary: 2025-01-01 UTC\n"
            "- Candidate 1: Breakout 168/60\n"
            "- Candidate 2: Breakout 168/72\n"
            "- No third breakout variant may be evaluated against this holdout.\n"
            "- No parameter search or tuning may use this holdout.\n"
            "- Both candidates are evaluated independently, starting FLAT at the boundary.\n"
            "- Pre-2025 bars may be used only as trailing indicator warm-up.\n"
            "- Cost scenarios A-E are robustness diagnostics, not a tuning surface.\n"
            "- After this run, 2025+ is considered consumed for both candidates.\n"
        )

    return output_root
