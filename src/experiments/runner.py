"""Experiment orchestration: load data, split chronologically, run the
backtest engine on each split, compute metrics, and persist everything
needed to reproduce the run later.

IMPORTANT methodological note: this runner executes the SAME strategy with
the SAME fixed parameters on train, validation, and test. It does not search
over parameters. Any workflow that inspects validation or test metrics and
then changes strategy_params in the config is, from that point on, no longer
producing an out-of-sample result for that data — see RESEARCH_RULES.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.data.loader import dataset_hash, load_ohlcv
from src.data.splitter import chronological_split
from src.experiments.config import ExperimentConfig
from src.metrics.metrics import build_metrics_report
from src.strategies.registry import build_strategy

RESULTS_DIR = Path("results")


@dataclass
class SplitRunResult:
    split_name: str
    result: BacktestResult
    metrics: dict


def run_experiment(
    config: ExperimentConfig,
    raw_dir: Path = Path("data/raw"),
) -> dict[str, SplitRunResult]:
    """Run the configured strategy on train/validation/test splits.

    Returns a dict keyed by split name ("train", "validation", "test").
    """
    start = pd.Timestamp(config.start) if config.start else None
    end = pd.Timestamp(config.end) if config.end else None

    df = load_ohlcv(config.symbol, config.timeframe, start=start, end=end, raw_dir=raw_dir)
    if len(df) < 10:
        raise ValueError(
            f"Only {len(df)} candles available for {config.symbol} {config.timeframe}; "
            "need more data to run a meaningful backtest with train/validation/test splits."
        )

    split = chronological_split(
        df,
        train_frac=config.data_split.get("train", 0.6),
        validation_frac=config.data_split.get("validation", 0.2),
        test_frac=config.data_split.get("test", 0.2),
    )

    backtest_config = BacktestConfig(
        initial_capital=config.capital_initial,
        trading_fee=config.trading_fee,
        slippage=config.slippage,
        position_size_fraction=config.position_size_fraction,
    )
    engine = BacktestEngine(backtest_config)

    results: dict[str, SplitRunResult] = {}
    for split_name, split_df in [
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ]:
        if len(split_df) < 2:
            continue
        strategy = build_strategy(config.strategy, config.strategy_params)
        signals = strategy.generate_signals(split_df)
        result = engine.run(split_df, signals)
        metrics = build_metrics_report(result, config.timeframe)
        results[split_name] = SplitRunResult(split_name=split_name, result=result, metrics=metrics)

    return results


def save_experiment(
    config: ExperimentConfig,
    results: dict[str, SplitRunResult],
    dataset_df: pd.DataFrame,
    results_dir: Path = RESULTS_DIR,
) -> Path:
    """Persist config, metrics, trades, equity, and a summary for every
    split into a timestamped, numbered experiment folder.
    """
    results_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = sorted(results_dir.glob(f"{today}_*"))
    next_num = len(existing) + 1
    folder_name = f"{today}_{next_num:03d}_{config.strategy}"
    exp_dir = results_dir / folder_name
    exp_dir.mkdir(parents=True, exist_ok=False)

    full_config = config.to_dict()
    full_config["dataset_hash"] = dataset_hash(dataset_df)
    full_config["data_period"] = {
        "start": str(dataset_df["timestamp"].iloc[0]),
        "end": str(dataset_df["timestamp"].iloc[-1]),
        "num_candles": len(dataset_df),
    }
    full_config["generated_at_utc"] = datetime.now(timezone.utc).isoformat()

    with open(exp_dir / "config.json", "w") as f:
        json.dump(full_config, f, indent=2, default=str)

    all_metrics = {}
    for split_name, split_result in results.items():
        split_dir = exp_dir / split_name
        split_dir.mkdir(exist_ok=True)

        split_result.result.trades_df().to_csv(split_dir / "trades.csv", index=False)
        split_result.result.equity_curve.to_csv(split_dir / "equity.csv", index=False)

        with open(split_dir / "metrics.json", "w") as f:
            json.dump(split_result.metrics, f, indent=2, default=str)

        all_metrics[split_name] = split_result.metrics

    with open(exp_dir / "metrics.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)

    summary = _build_summary_md(config, results, folder_name)
    with open(exp_dir / "summary.md", "w") as f:
        f.write(summary)

    return exp_dir


def _build_summary_md(
    config: ExperimentConfig, results: dict[str, SplitRunResult], folder_name: str
) -> str:
    lines = [
        f"# Experiment: {folder_name}",
        "",
        f"- Strategy: `{config.strategy}` with params `{config.strategy_params}`",
        f"- Symbol: {config.symbol}, Timeframe: {config.timeframe}",
        f"- Initial capital: {config.capital_initial}",
        f"- Trading fee: {config.trading_fee}, Slippage: {config.slippage}",
        f"- Data split: {config.data_split}",
        "",
        "## Results by split",
        "",
    ]
    for split_name in ["train", "validation", "test"]:
        if split_name not in results:
            continue
        m = results[split_name].metrics
        lines.append(f"### {split_name}")
        lines.append("")
        lines.append(f"- Total return: {m['total_return']:.4%}")
        lines.append(f"- Annualized return: {m['annualized_return']}")
        lines.append(f"- Num trades: {m['num_trades']}")
        lines.append(f"- Win rate: {m['win_rate']}")
        lines.append(f"- Profit factor: {m['profit_factor']}")
        lines.append(f"- Max drawdown: {m['max_drawdown_pct']:.4%}")
        lines.append(f"- Sharpe ratio: {m['sharpe_ratio']}")
        lines.append(f"- Sortino ratio: {m['sortino_ratio']}")
        lines.append(f"- Market exposure: {m['market_exposure']:.4%}")
        lines.append(f"- Total fees: {m['total_fees']:.4f}")
        if m["notes"]:
            lines.append("- Notes:")
            for note in m["notes"]:
                lines.append(f"  - {note}")
        lines.append("")

    lines.append(
        "**Reminder:** validation and test results are reported for reference only. "
        "Do not tune strategy_params based on test metrics and then re-report test as "
        "out-of-sample — see RESEARCH_RULES.md."
    )
    return "\n".join(lines)
