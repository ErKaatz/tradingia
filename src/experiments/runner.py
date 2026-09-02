"""Experiment orchestration: load data, split chronologically, run the
backtest engine on each split, compute metrics, and persist everything
needed to reproduce the run later.

IMPORTANT methodological note: this runner executes the SAME strategy with
the SAME fixed parameters on train, validation, and test. It does not search
over parameters. Any workflow that inspects validation or test metrics and
then changes strategy_params in the config is, from that point on, no longer
producing an out-of-sample result for that data — see RESEARCH_RULES.md.

## Split evaluation mode: `independent_split_evaluation`

This is the ONLY mode implemented so far. Each split (train/validation/test)
is evaluated as its own self-contained backtest:

- starts FLAT with the full configured initial capital, regardless of what
  the strategy or portfolio was doing right before the split started;
- may use OHLCV history from strictly before the split's start purely to
  warm up indicators (see `warmup_bars` below) — that history affects what
  signal the strategy produces at the split's first bars, but can never
  itself be traded on, and never contributes to the split's equity curve,
  trades, or metrics;
- force-closes any open position at the split's own last bar.

This deliberately does NOT simulate a portfolio that carries capital and
open positions continuously from train through validation through test. It
answers "how does this fixed strategy behave, independently, in each of
these three periods" — not "what would one continuous run from start to
finish have done." The latter is a different, currently unimplemented mode:

## Future mode (not implemented): `continuous_walk_forward`

A future mode where capital and position state carry over continuously
across split boundaries (so validation starts wherever train's simulation
left off, not flat with fresh capital). This is materially different from
independent_split_evaluation — e.g. a position opened near the end of train
could still be open when validation begins — and must not be silently
conflated with it. When implemented, it should be a distinct, explicitly
selected mode (e.g. an `evaluation_mode` config field), not a variant
hidden inside `independent_split_evaluation`'s code path.

## Warm-up bars

A strategy declares how many leading bars of history it needs to produce a
non-degenerate signal via `Strategy.warmup_bars` (e.g. an SMA(100) crossover
needs 99 bars before the slow SMA is defined). For validation and test,
those warm-up bars are borrowed from the chronologically preceding data
(train, or train+validation respectively) via `slice_with_warmup` — never
from data after the split's end. `train` has no earlier split to borrow
from, so its own leading `warmup_bars` rows are simply cold (indicators
degrade to their `min_periods`/NaN behavior there, same as before this
change), which is inherent to it being the first period in the dataset.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from src.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.data.loader import dataset_hash, load_ohlcv
from src.data.splitter import chronological_split, slice_with_warmup
from src.data.validation import validate_ohlcv
from src.experiments.config import ExperimentConfig
from src.metrics.metrics import build_metrics_report
from src.strategies.registry import build_strategy

RESULTS_DIR = Path("results")

EVALUATION_MODE = "independent_split_evaluation"

TRACKED_PACKAGES = ["pandas", "numpy", "pyyaml", "pyarrow", "requests"]


@dataclass
class SplitRunResult:
    split_name: str
    result: BacktestResult
    metrics: dict
    warmup_bars_requested: int
    warmup_bars_available: int


def run_experiment(
    config: ExperimentConfig,
    raw_dir: Path = Path("data/raw"),
) -> dict[str, SplitRunResult]:
    """Run the configured strategy on train/validation/test splits, using
    `independent_split_evaluation` semantics (see module docstring).

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

    # Validate the FULL dataset once, up front, with the timeframe-specific
    # gap policy from the config. BTC/USDT spot at 1h is expected to trade
    # continuously, so allow_data_gaps defaults to False; a market/dataset
    # known to have legitimate gaps can opt in via config.
    ohlcv_validation = validate_ohlcv(
        df, timeframe=config.timeframe, allow_gaps=config.allow_data_gaps
    )
    ohlcv_validation.raise_if_invalid()

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

    # warmup_bars is a property of the strategy+params, not of the data, so
    # build one throwaway instance up front just to read it.
    warmup_bars = build_strategy(config.strategy, config.strategy_params).warmup_bars

    results: dict[str, SplitRunResult] = {}
    for split_name, bounds in [
        ("train", split.train_bounds),
        ("validation", split.validation_bounds),
        ("test", split.test_bounds),
    ]:
        if len(bounds) < 2:
            continue

        extended_df, evaluation_start = slice_with_warmup(df, bounds, warmup_bars)
        # evaluation_start equals how many warm-up rows were actually
        # available/borrowed; it is < warmup_bars only near the very start
        # of the whole dataset (i.e. within train), where there is no prior
        # history left to borrow.
        warmup_bars_available = evaluation_start

        strategy = build_strategy(config.strategy, config.strategy_params)
        signals = strategy.generate_signals(extended_df)
        result = engine.run(extended_df, signals, evaluation_start=evaluation_start)
        metrics = build_metrics_report(result, config.timeframe)
        results[split_name] = SplitRunResult(
            split_name=split_name,
            result=result,
            metrics=metrics,
            warmup_bars_requested=warmup_bars,
            warmup_bars_available=warmup_bars_available,
        )

    return results


def _get_package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for pkg in TRACKED_PACKAGES:
        try:
            versions[pkg] = version(pkg)
        except PackageNotFoundError:
            versions[pkg] = None
    return versions


def _get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _build_reproducibility_info(config: ExperimentConfig) -> dict:
    return {
        "python_version": platform.python_version(),
        "package_versions": _get_package_versions(),
        "git_commit": _get_git_commit(),
        "evaluation_mode": EVALUATION_MODE,
        "backtest_engine_config": {
            "initial_capital": config.capital_initial,
            "trading_fee": config.trading_fee,
            "slippage": config.slippage,
            "position_size_fraction": config.position_size_fraction,
        },
    }


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
    full_config["reproducibility"] = _build_reproducibility_info(config)
    full_config["warmup_bars_by_split"] = {
        split_name: {
            "requested": split_result.warmup_bars_requested,
            "available": split_result.warmup_bars_available,
        }
        for split_name, split_result in results.items()
    }

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
        f"- Evaluation mode: `{EVALUATION_MODE}` (each split starts flat with fresh "
        "initial capital; indicator warm-up may borrow prior-split history, "
        "trading/metrics never do)",
        "",
        "## Results by split",
        "",
    ]
    for split_name in ["train", "validation", "test"]:
        if split_name not in results:
            continue
        split_result = results[split_name]
        m = split_result.metrics
        lines.append(f"### {split_name}")
        lines.append("")
        lines.append(
            f"- Warm-up bars: {split_result.warmup_bars_available} available "
            f"of {split_result.warmup_bars_requested} requested by the strategy"
        )
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
