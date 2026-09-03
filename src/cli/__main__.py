"""Command-line interface.

Usage:
    python -m src.cli download-data --symbol BTCUSDT --timeframe 1h --start 2023-01-01 --end 2024-01-01
    python -m src.cli backtest configs/sma_cross.yaml
    python -m src.cli compare results/2026-09-02_001_sma_cross results/2026-09-02_002_momentum
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.loader import download_and_cache, load_ohlcv
from src.data.providers import BinancePublicProvider
from src.experiments.config import ExperimentConfig
from src.experiments.runner import run_experiment, save_experiment
from src.research.runner import run_phase2
from src.research.phase25 import run_phase25
from src.research.holdout_eval import run_final_holdout
from src.research.diagnostics import run_holdout_diagnostics
from src.research.post_holdout_family_comparison import run_post_holdout_family_comparison
from src.research.regime_study import run_regime_study
from src.research.short_horizon_study import run_short_horizon_study
from src.research.short_horizon_phase4b import run_phase4b_diagnostics
from src.forward.runner import preregister_forward, run_forward_eval
from src.cli.mt5_remote_cli import add_mt5_remote_subparser


def cmd_download_data(args: argparse.Namespace) -> None:
    provider = BinancePublicProvider()
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)

    print(f"Downloading {args.symbol} {args.timeframe} from {start} to {end} ...")
    path = download_and_cache(provider, args.symbol, args.timeframe, start, end)
    df = load_ohlcv(args.symbol, args.timeframe)
    print(f"Cached {len(df)} candles at {path}")
    print(f"Range: {df['timestamp'].min()} -> {df['timestamp'].max()}")


def cmd_backtest(args: argparse.Namespace) -> None:
    config = ExperimentConfig.from_yaml(args.config_path)
    results = run_experiment(config)

    from src.data.loader import load_ohlcv as _load

    start = pd.Timestamp(config.start) if config.start else None
    end = pd.Timestamp(config.end) if config.end else None
    df = _load(config.symbol, config.timeframe, start=start, end=end)

    exp_dir = save_experiment(config, results, df)
    print(f"Experiment saved to {exp_dir}")
    print()
    with open(exp_dir / "summary.md") as f:
        print(f.read())


def cmd_compare(args: argparse.Namespace) -> None:
    rows = []
    for result_path in args.result_dirs:
        exp_dir = Path(result_path)
        config_path = exp_dir / "config.json"
        metrics_path = exp_dir / "metrics.json"
        if not config_path.exists() or not metrics_path.exists():
            print(f"Skipping {exp_dir}: missing config.json or metrics.json", file=sys.stderr)
            continue

        with open(config_path) as f:
            config = json.load(f)
        with open(metrics_path) as f:
            metrics = json.load(f)

        for split_name, split_metrics in metrics.items():
            rows.append(
                {
                    "experiment": exp_dir.name,
                    "strategy": config.get("strategy"),
                    "split": split_name,
                    "total_return": split_metrics.get("total_return"),
                    "num_trades": split_metrics.get("num_trades"),
                    "win_rate": split_metrics.get("win_rate"),
                    "profit_factor": split_metrics.get("profit_factor"),
                    "max_drawdown_pct": split_metrics.get("max_drawdown_pct"),
                    "sharpe_ratio": split_metrics.get("sharpe_ratio"),
                }
            )

    if not rows:
        print("No valid experiments to compare.")
        return

    df = pd.DataFrame(rows)
    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(df.to_string(index=False))



def cmd_research(args: argparse.Namespace) -> None:
    reports = run_phase2(args.config_path)
    print(f"Phase-2 research reports saved to {reports}")


def cmd_research25(args: argparse.Namespace) -> None:
    reports = run_phase25(args.config_path)
    print(f"Phase-2.5 research reports saved to {reports}")


def cmd_final_holdout(args: argparse.Namespace) -> None:
    reports = run_final_holdout(args.config_path)
    print(f"FINAL HOLDOUT consumed for frozen candidates; reports saved to {reports}")


def cmd_diagnose_holdout(args: argparse.Namespace) -> None:
    reports = run_holdout_diagnostics(args.config_path)
    print(f"Post-holdout diagnostics saved to {reports}")


def cmd_post_holdout_family_comparison(args: argparse.Namespace) -> None:
    out = run_post_holdout_family_comparison(args.config_path)
    print(f"POST-HOC / HOLDOUT ALREADY CONSUMED family comparison saved to {out}")


def cmd_regime_study(args: argparse.Namespace) -> None:
    out = run_regime_study()
    print(f"POST-HOC REGIME RESEARCH (Phase 3B) saved to {out}")


def cmd_short_horizon(args: argparse.Namespace) -> None:
    out = run_short_horizon_study(args.config_path)
    print(f"POST-HOC SHORT-HORIZON RESEARCH (Phase 4A) saved to {out}")


def cmd_preregister_forward(args: argparse.Namespace) -> None:
    out = preregister_forward(args.config_path)
    print(f"Forward hypotheses preregistered at {out}")


def cmd_phase4b(args: argparse.Namespace) -> None:
    out = run_phase4b_diagnostics(args.config_path)
    print(f"Phase-4B edge-vs-cost diagnostics saved to {out}")


def cmd_forward_eval(args: argparse.Namespace) -> None:
    out = run_forward_eval(args.config_path)
    print(f"Forward evaluation reports saved to {out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_download = subparsers.add_parser("download-data", help="Download and cache OHLCV data")
    p_download.add_argument("--symbol", default="BTCUSDT")
    p_download.add_argument("--timeframe", default="1h")
    p_download.add_argument("--start", required=True, help="ISO date, e.g. 2023-01-01")
    p_download.add_argument("--end", required=True, help="ISO date, e.g. 2024-01-01")
    p_download.set_defaults(func=cmd_download_data)

    p_backtest = subparsers.add_parser("backtest", help="Run a backtest from a config file")
    p_backtest.add_argument("config_path", help="Path to a YAML experiment config")
    p_backtest.set_defaults(func=cmd_backtest)

    p_compare = subparsers.add_parser("compare", help="Compare multiple experiment result folders")
    p_compare.add_argument("result_dirs", nargs="+", help="Paths under results/")
    p_compare.set_defaults(func=cmd_compare)

    p_research = subparsers.add_parser("research", help="Run locked-holdout Phase-2 research")
    p_research.add_argument("config_path", help="Path to Phase-2 YAML config")
    p_research.set_defaults(func=cmd_research)

    p_research25 = subparsers.add_parser("research25", help="Run locked-holdout Phase-2.5 breakout robustness study")
    p_research25.add_argument("config_path", help="Path to Phase-2.5 YAML config")
    p_research25.set_defaults(func=cmd_research25)

    p_holdout = subparsers.add_parser("final-holdout", help="One-time final holdout evaluation for frozen breakout candidates")
    p_holdout.add_argument("config_path", help="Path to frozen final-holdout YAML config")
    p_holdout.set_defaults(func=cmd_final_holdout)

    p_diag = subparsers.add_parser("diagnose-holdout", help="Diagnose consumed holdout without parameter optimization")
    p_diag.add_argument("config_path", help="Path to post-holdout diagnostic YAML config")
    p_diag.set_defaults(func=cmd_diagnose_holdout)

    p_phfc = subparsers.add_parser(
        "post-holdout-family-comparison",
        help="POST-HOC / HOLDOUT ALREADY CONSUMED: compare other Phase-2 families against the consumed 2025-2026 period",
    )
    p_phfc.add_argument("config_path", help="Path to post-holdout family comparison YAML config")
    p_phfc.set_defaults(func=cmd_post_holdout_family_comparison)

    p_regime = subparsers.add_parser(
        "regime-study",
        help="POST-HOC REGIME RESEARCH (Phase 3B): causal regime features vs the consumed 2025-2026 period",
    )
    p_regime.set_defaults(func=cmd_regime_study)

    p_short = subparsers.add_parser(
        "short-horizon",
        help="POST-HOC Phase 4A: run frozen BTCUSDT 15m/1h short-horizon strategy study",
    )
    p_short.add_argument("config_path", nargs="?", default="configs/short_horizon_phase4a.yaml", help="Path to Phase-4A YAML config")
    p_short.set_defaults(func=cmd_short_horizon)

    p_short_b = subparsers.add_parser(
        "short-horizon-diagnose",
        help="POST-HOC Phase 4B: diagnose gross signal edge vs execution costs for frozen Phase-4A families",
    )
    p_short_b.add_argument("config_path", nargs="?", default="configs/short_horizon_phase4b.yaml", help="Path to Phase-4B YAML config")
    p_short_b.set_defaults(func=cmd_phase4b)

    p_pre = subparsers.add_parser("preregister-forward", help="Freeze post-holdout forward hypotheses before new data")
    p_pre.add_argument("config_path", help="Path to forward validation YAML config")
    p_pre.set_defaults(func=cmd_preregister_forward)

    p_fwd = subparsers.add_parser("forward-eval", help="Evaluate frozen hypotheses only on forward data from 2026-09-03 onward")
    p_fwd.add_argument("config_path", help="Path to forward validation YAML config")
    p_fwd.set_defaults(func=cmd_forward_eval)

    add_mt5_remote_subparser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
