"""Command-line interface.

Usage:
    python -m src.cli compare results/<experiment_a> results/<experiment_b>
    python -m src.cli mt5-remote --help
    python -m src.cli fx-history --help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.cli.fx_cli import add_fx_subparser
from src.cli.mt5_remote_cli import add_mt5_remote_subparser
from src.cli.runtime_cli import add_runtime_subparser


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_compare = subparsers.add_parser("compare", help="Compare multiple experiment result folders")
    p_compare.add_argument("result_dirs", nargs="+", help="Paths under results/")
    p_compare.set_defaults(func=cmd_compare)

    add_mt5_remote_subparser(subparsers)
    add_runtime_subparser(subparsers)
    add_fx_subparser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
