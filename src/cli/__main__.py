"""Command-line interface.

Usage:
    python -m src.cli backtest <path/to/experiment.yaml>
    python -m src.cli compare results/<experiment_a> results/<experiment_b>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.experiments.config import ExperimentConfig
from src.experiments.runner import run_experiment, save_experiment
from src.forward.runner import preregister_forward, run_forward_eval
from src.cli.mt5_remote_cli import add_mt5_remote_subparser


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



def cmd_preregister_forward(args: argparse.Namespace) -> None:
    out = preregister_forward(args.config_path)
    print(f"Forward hypotheses preregistered at {out}")


def cmd_forward_eval(args: argparse.Namespace) -> None:
    out = run_forward_eval(args.config_path)
    print(f"Forward evaluation reports saved to {out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_backtest = subparsers.add_parser("backtest", help="Run a backtest from a config file")
    p_backtest.add_argument("config_path", help="Path to a YAML experiment config")
    p_backtest.set_defaults(func=cmd_backtest)

    p_compare = subparsers.add_parser("compare", help="Compare multiple experiment result folders")
    p_compare.add_argument("result_dirs", nargs="+", help="Paths under results/")
    p_compare.set_defaults(func=cmd_compare)

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
