"""POST-HOC / HOLDOUT ALREADY CONSUMED — family comparison, research vs 2025-2026.

This module answers a retrospective question only: what would have happened
in 2025-2026 with the OTHER strategy families/configurations that were
already registered during Phase 2 research (2018-2024), before the final
holdout was opened for breakout?

This is explicitly NOT a new holdout and NOT an out-of-sample test:

- 2025-01-01 -> 2026-09-02 was already consumed by `run_final_holdout` for
  the two frozen breakout candidates (168/60, 168/72). Running SMA cross,
  momentum, and mean-reversion configurations against the same already-
  consumed period is a post-hoc lookback, not a fresh evaluation.
- No configuration here is new. Every SMA cross / momentum / mean-reversion
  parameter combination evaluated is read directly from the Phase-2 research
  artifacts already on disk (`research/parameter_studies/<family>.csv`) --
  this module does not regenerate a parameter grid from a YAML list, so a
  changed config file cannot silently introduce a parameter that was never
  actually part of Phase 2 research.
- Breakout is NOT re-evaluated here. Its post-hoc "recent" numbers are read
  directly from `research/final_holdout/variants/breakout_168_60` and
  `breakout_168_72`, i.e. the same already-consumed holdout run -- this
  module never re-runs Breakout against 2025-2026 under a different code
  path, and never adds a third breakout parameter set.
- No result produced here may be used to select, tune, reject, or refine
  any strategy. See RESEARCH_RULES.md's Phase 2 / Phase 2.5 / final-holdout
  / post-holdout-diagnostics rules, all of which continue to apply.
- Classification labels used here are POST-HOC descriptive states only:
  RECENTLY RESILIENT, RECENTLY DEGRADED, CONSISTENTLY WEAK,
  REGIME-SENSITIVE, INCONCLUSIVE. Never PROVEN / PROFITABLE /
  OUT-OF-SAMPLE WINNER.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import spearmanr

from src.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.data.loader import dataset_hash, load_ohlcv
from src.data.validation import validate_ohlcv
from src.metrics.metrics import build_metrics_report
from src.research.annual import annual_strategy_metrics
from src.research.holdout import split_final_holdout
from src.research.stress import DEFAULT_COST_SCENARIOS
from src.strategies.base import Strategy
from src.strategies.breakout import Breakout
from src.strategies.buy_and_hold import BuyAndHold
from src.strategies.mean_reversion import MeanReversion
from src.strategies.momentum import Momentum
from src.strategies.registry import build_strategy
from src.strategies.sma_cross import SmaCross

LABEL = "POST-HOC / HOLDOUT ALREADY CONSUMED"

DEFAULT_OUTPUT_ROOT = Path("research/post_holdout_family_comparison")
RESEARCH_PARAMETER_STUDY_DIR = Path("research/parameter_studies")
FINAL_HOLDOUT_DIR = Path("research/final_holdout")

# Recent = the already-consumed final-holdout period. Reusing the exact same
# boundary as holdout_eval.py / research_phase2.yaml so "research" and
# "recent" never overlap and never redefine what "recent" means.
RECENT_START = "2025-01-01"
RECENT_END = "2026-09-02"  # inclusive-ish: dataset does not extend past this

# Families whose Phase-2-registered configurations are re-evaluated here.
# Breakout is deliberately excluded from this list: it is read from the
# already-consumed final-holdout artifacts instead (see module docstring).
RE_EVALUATED_FAMILIES = ("sma_cross", "momentum", "mean_reversion")

STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "sma_cross": SmaCross,
    "momentum": Momentum,
    "mean_reversion": MeanReversion,
    "breakout": Breakout,
}

# The two breakout candidates already frozen and consumed by Phase 2.5 /
# final-holdout. Hardcoded here (not read from a config list) for the same
# reason holdout_eval.py hardcodes FROZEN_CANDIDATES: a config edit must not
# be able to silently add a third breakout parameter set to this report.
FROZEN_BREAKOUT_CANDIDATES = ((168, 60), (168, 72))


@dataclass(frozen=True)
class HistoricalConfig:
    """One exact, already-registered Phase-2 configuration."""

    family: str
    variant_id: str
    params: dict[str, Any]


def load_historical_configs(
    families: tuple[str, ...] = RE_EVALUATED_FAMILIES,
    parameter_study_dir: Path = RESEARCH_PARAMETER_STUDY_DIR,
) -> list[HistoricalConfig]:
    """Recover the exact configurations Phase 2 research already registered
    for the given families, reading them from the persisted per-family CSV
    (`research/parameter_studies/<family>.csv`) rather than regenerating a
    grid from any config file. This is the anti-reoptimization guarantee for
    Task 8: there is no code path here that can introduce a parameter value
    Phase 2 did not already evaluate and record.
    """
    configs: list[HistoricalConfig] = []
    for family in families:
        csv_path = parameter_study_dir / f"{family}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Expected Phase-2 research artifact not found: {csv_path}. "
                "This module only evaluates configurations that were already "
                "registered during Phase 2 research; it cannot proceed without it."
            )
        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            params = json.loads(row["params"])
            configs.append(
                HistoricalConfig(
                    family=family,
                    variant_id=f"{family}_variant_{int(row['variant']):03d}",
                    params=params,
                )
            )
    return configs


def _build_backtest_config(raw: dict[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=float(raw.get("capital", {}).get("initial", 10_000)),
        trading_fee=float(raw.get("fees", {}).get("trading_fee", 0.001)),
        slippage=float(raw.get("fees", {}).get("slippage", 0.0002)),
        position_size_fraction=float(raw.get("position_size_fraction", 1.0)),
    )


def _run_recent_with_warmup(
    research_df: pd.DataFrame,
    recent_df: pd.DataFrame,
    strategy: Strategy,
    cfg: BacktestConfig,
    timeframe: str,
) -> tuple[BacktestResult, dict[str, Any]]:
    """Evaluate `strategy` on `recent_df` starting FLAT at its boundary,
    borrowing only trailing warm-up context from `research_df` -- the exact
    same independent_split_evaluation pattern used by
    `holdout_eval._run_with_warmup`. No row of `recent_df` (2025-2026) is
    ever used to compute anything about `research_df` (2018-2024), and no
    row after the boundary influences warm-up.
    """
    warmup = int(strategy.warmup_bars)
    context = research_df.tail(warmup).copy()
    combined = pd.concat([context, recent_df], ignore_index=True)
    signals = strategy.generate_signals(combined)
    result = BacktestEngine(cfg).run(combined, signals, evaluation_start=len(context))
    return result, build_metrics_report(result, timeframe)


def _recent_annual_metrics(
    research_df: pd.DataFrame,
    recent_df: pd.DataFrame,
    strategy_factory,
    cfg: BacktestConfig,
    timeframe: str,
    recent_start: str,
) -> dict[int, dict[str, Any]]:
    """Calendar-year metrics restricted to years >= the recent-period start
    year, using only the minimal trailing research context for warm-up (same
    pattern as `holdout_eval.run_final_holdout`'s annual computation).
    """
    probe = strategy_factory()
    warmup = int(probe.warmup_bars)
    context = pd.concat([research_df.tail(warmup), recent_df], ignore_index=True)
    annual = annual_strategy_metrics(context, strategy_factory, cfg, timeframe)
    cutoff_year = pd.Timestamp(recent_start).year
    return {year: values for year, values in annual.items() if year >= cutoff_year}


def _load_frozen_breakout_recent(
    entry: int, exit_: int, holdout_dir: Path = FINAL_HOLDOUT_DIR
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Read the already-consumed final-holdout metrics for one frozen
    breakout candidate. Never re-runs the backtest against 2025-2026 --
    reuses the exact artifacts `run_final_holdout` already wrote, so this
    module cannot be accused of touching the holdout a second time under a
    different code path.
    """
    path = holdout_dir / "variants" / f"breakout_{entry}_{exit_}" / "metrics.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Expected already-consumed final-holdout artifact not found: {path}. "
            "Breakout's recent-period numbers must come from the existing "
            "final-holdout run, not a new backtest."
        )
    with open(path) as f:
        data = json.load(f)
    annual = {int(year): values for year, values in data.get("annual", {}).items()}
    return data["metrics"], annual


def _load_research_metrics(
    family: str, variant_number: int, parameter_study_dir: Path = RESEARCH_PARAMETER_STUDY_DIR
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    path = parameter_study_dir / family / f"variant_{variant_number:03d}" / "metrics.json"
    with open(path) as f:
        data = json.load(f)
    annual = {int(year): values for year, values in data.get("annual", {}).items()}
    return data["metrics"], annual


def _delta(recent: float | None, research: float | None) -> float | None:
    if recent is None or research is None:
        return None
    return recent - research


DELTA_METRIC_KEYS = [
    "total_return",
    "sharpe_ratio",
    "win_rate",
    "expectancy",
    "average_win",
    "average_loss",
    "num_trades",
    "max_drawdown_pct",
]

REPORT_METRIC_KEYS = [
    "total_return",
    "annualized_return",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown_pct",
    "profit_factor",
    "expectancy",
    "win_rate",
    "num_trades",
    "market_exposure",
    "total_fees",
    "average_win",
    "average_loss",
]


def _classify(
    research_metrics: dict[str, Any],
    recent_metrics: dict[str, Any],
    recent_bh_metrics: dict[str, Any],
) -> tuple[str, list[str]]:
    """Purely descriptive post-hoc classification. Never a validation label.

    States: RECENTLY RESILIENT, RECENTLY DEGRADED, CONSISTENTLY WEAK,
    REGIME-SENSITIVE, INCONCLUSIVE.
    """
    reasons: list[str] = []
    research_return = research_metrics.get("total_return")
    recent_return = recent_metrics.get("total_return")
    recent_trades = recent_metrics.get("num_trades", 0)
    bh_return = recent_bh_metrics.get("total_return")

    if recent_trades is not None and recent_trades < 10:
        reasons.append(f"only {recent_trades} recent trades: too few to classify confidently")
        return "INCONCLUSIVE", reasons

    research_weak = research_return is not None and research_return <= 0
    recent_weak = recent_return is not None and recent_return <= 0

    if research_weak and recent_weak:
        reasons.append("negative or flat total return in both research and recent periods")
        return "CONSISTENTLY WEAK", reasons

    if not research_weak and recent_weak:
        beat_bh = bh_return is not None and recent_return is not None and recent_return > bh_return
        if beat_bh:
            reasons.append(
                "recent total return negative but research was positive; "
                "recent return still exceeded buy-and-hold over the same period"
            )
            return "REGIME-SENSITIVE", reasons
        reasons.append("research was positive; recent total return is negative or flat")
        return "RECENTLY DEGRADED", reasons

    if not research_weak and not recent_weak:
        reasons.append("positive total return in both research and recent periods")
        return "RECENTLY RESILIENT", reasons

    if research_weak and not recent_weak:
        reasons.append(
            "research total return was negative or flat but recent total return is positive; "
            "treat as a regime difference, not evidence of a newly discovered edge"
        )
        return "REGIME-SENSITIVE", reasons

    reasons.append("insufficient signal to classify")
    return "INCONCLUSIVE", reasons


def run_post_holdout_family_comparison(
    config_path: str | Path,
    raw_dir: Path = Path("data/raw"),
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if raw.get("allow_parameter_search", False):
        raise PermissionError(
            "post-hoc family comparison must not perform parameter search; "
            "it only re-evaluates configurations already registered in Phase 2"
        )

    symbol = raw.get("symbol", "BTCUSDT")
    timeframe = raw.get("timeframe", "1h")
    recent_start = raw.get("recent_start", RECENT_START)
    recent_end = raw.get("recent_end", RECENT_END)
    if str(recent_start) != RECENT_START or str(recent_end) != RECENT_END:
        raise PermissionError(
            f"the post-hoc recent window is frozen at [{RECENT_START}, {RECENT_END}]; "
            f"got [{recent_start}, {recent_end}]. This window matches the already-"
            "consumed final holdout exactly and must not be widened or narrowed."
        )

    df = load_ohlcv(symbol, timeframe, raw_dir=raw_dir)
    validation = validate_ohlcv(df, timeframe=timeframe, allow_gaps=bool(raw.get("allow_data_gaps", True)))
    validation.raise_if_invalid()

    split = split_final_holdout(df, recent_start)
    recent_df = split.final_holdout
    recent_ts = pd.to_datetime(recent_df["timestamp"], utc=True)
    recent_df = recent_df.loc[recent_ts <= pd.Timestamp(recent_end, tz="UTC")].reset_index(drop=True)
    if recent_df.empty:
        raise ValueError("recent (post-holdout) period is empty")

    cfg = _build_backtest_config(raw)

    output_root.mkdir(parents=True, exist_ok=True)
    variants_dir = output_root / "variants"
    variants_dir.mkdir(exist_ok=True)

    # Same-period Buy & Hold benchmark for the recent window (Task 7).
    bh_recent_result, bh_recent_metrics = _run_recent_with_warmup(
        split.research, recent_df, BuyAndHold(), cfg, timeframe
    )

    rows: list[dict[str, Any]] = []
    yearly_rows: list[dict[str, Any]] = []

    historical_configs = load_historical_configs()

    for hc in historical_configs:
        variant_number = int(hc.variant_id.rsplit("_", 1)[-1])
        research_metrics, research_annual = _load_research_metrics(hc.family, variant_number)

        strategy = build_strategy(hc.family, hc.params)
        recent_result, recent_metrics = _run_recent_with_warmup(
            split.research, recent_df, strategy, cfg, timeframe
        )
        recent_annual = _recent_annual_metrics(
            split.research,
            recent_df,
            lambda f=hc.family, p=hc.params: build_strategy(f, p),
            cfg,
            timeframe,
            recent_start,
        )

        vdir = variants_dir / hc.variant_id
        vdir.mkdir(exist_ok=True)
        recent_result.trades_df().to_csv(vdir / "trades.csv", index=False)
        recent_result.equity_curve.to_csv(vdir / "equity.csv", index=False)
        with open(vdir / "metrics.json", "w") as f:
            json.dump(
                {
                    "label": LABEL,
                    "family": hc.family,
                    "params": hc.params,
                    "research_metrics": research_metrics,
                    "recent_metrics": recent_metrics,
                    "research_annual": {str(k): v for k, v in research_annual.items()},
                    "recent_annual": {str(k): v for k, v in recent_annual.items()},
                },
                f,
                indent=2,
                default=str,
            )

        classification, reasons = _classify(research_metrics, recent_metrics, bh_recent_metrics)

        row = {
            "label": LABEL,
            "family": hc.family,
            "variant_id": hc.variant_id,
            "params": json.dumps(hc.params, sort_keys=True),
            "classification": classification,
            "classification_reasons": "; ".join(reasons),
        }
        for key in REPORT_METRIC_KEYS:
            row[f"research_{key}"] = research_metrics.get(key)
            row[f"recent_{key}"] = recent_metrics.get(key)
        for key in DELTA_METRIC_KEYS:
            row[f"delta_{key}"] = _delta(recent_metrics.get(key), research_metrics.get(key))

        row["recent_excess_return_vs_buy_hold"] = _delta(
            recent_metrics.get("total_return"), bh_recent_metrics.get("total_return")
        )
        row["recent_drawdown_reduction_vs_buy_hold"] = _delta(
            bh_recent_metrics.get("max_drawdown_pct"), recent_metrics.get("max_drawdown_pct")
        )
        row["recent_exposure_reduction_vs_buy_hold"] = _delta(
            bh_recent_metrics.get("market_exposure"), recent_metrics.get("market_exposure")
        )
        rows.append(row)

        for year, values in research_annual.items():
            yearly_rows.append(
                {
                    "label": LABEL,
                    "family": hc.family,
                    "variant_id": hc.variant_id,
                    "period": "research",
                    "year": year,
                    "total_return": values.get("total_return"),
                    "sharpe_ratio": values.get("sharpe_ratio"),
                    "num_trades": values.get("num_trades"),
                    "max_drawdown_pct": values.get("max_drawdown_pct"),
                }
            )
        for year, values in recent_annual.items():
            yearly_rows.append(
                {
                    "label": LABEL,
                    "family": hc.family,
                    "variant_id": hc.variant_id,
                    "period": "recent",
                    "year": year,
                    "total_return": values.get("total_return"),
                    "sharpe_ratio": values.get("sharpe_ratio"),
                    "num_trades": values.get("num_trades"),
                    "max_drawdown_pct": values.get("max_drawdown_pct"),
                }
            )

    # Breakout: reuse the already-consumed final-holdout artifacts. Never a
    # fresh backtest against 2025-2026 under this module.
    for entry, exit_ in FROZEN_BREAKOUT_CANDIDATES:
        variant_number_lookup = {
            (24, 12): 1, (24, 24): 2, (24, 48): 3,
            (48, 12): 4, (48, 24): 5, (48, 48): 6,
            (96, 12): 7, (96, 24): 8, (96, 48): 9,
            (168, 12): 10, (168, 24): 11, (168, 48): 12,
        }
        # Phase-2 research (2018-2024) never evaluated 168/60 or 168/72
        # directly -- those came from the Phase-2.5 plateau grid. Use the
        # Phase-2.5 research artifact for the "research" side instead, and
        # say so explicitly rather than silently reusing an unrelated
        # Phase-2 entry_lookback=168 variant with a different exit.
        phase25_variant_dir = Path("research/phase25/variants")
        match = None
        for vdir in sorted(phase25_variant_dir.glob(f"variant_*_{entry}_{exit_}")):
            match = vdir
        if match is None:
            raise FileNotFoundError(
                f"Expected Phase-2.5 research artifact for breakout {entry}/{exit_} not found"
            )
        with open(match / "metrics.json") as f:
            research_data = json.load(f)
        research_metrics = research_data.get("metrics", research_data)
        research_annual = {}  # Phase-2.5 per-variant files do not carry annual breakdown.

        recent_metrics, recent_annual = _load_frozen_breakout_recent(entry, exit_)

        variant_id = f"breakout_variant_{entry}_{exit_}"
        classification, reasons = _classify(research_metrics, recent_metrics, bh_recent_metrics)
        reasons = [
            "recent metrics reused verbatim from the already-consumed final-holdout run "
            "(no new backtest against 2025-2026 for breakout)"
        ] + reasons

        row = {
            "label": LABEL,
            "family": "breakout",
            "variant_id": variant_id,
            "params": json.dumps({"entry_lookback": entry, "exit_lookback": exit_}, sort_keys=True),
            "classification": classification,
            "classification_reasons": "; ".join(reasons),
        }
        for key in REPORT_METRIC_KEYS:
            row[f"research_{key}"] = research_metrics.get(key)
            row[f"recent_{key}"] = recent_metrics.get(key)
        for key in DELTA_METRIC_KEYS:
            row[f"delta_{key}"] = _delta(recent_metrics.get(key), research_metrics.get(key))
        row["recent_excess_return_vs_buy_hold"] = _delta(
            recent_metrics.get("total_return"), bh_recent_metrics.get("total_return")
        )
        row["recent_drawdown_reduction_vs_buy_hold"] = _delta(
            bh_recent_metrics.get("max_drawdown_pct"), recent_metrics.get("max_drawdown_pct")
        )
        row["recent_exposure_reduction_vs_buy_hold"] = _delta(
            bh_recent_metrics.get("market_exposure"), recent_metrics.get("market_exposure")
        )
        rows.append(row)

        for year, values in recent_annual.items():
            yearly_rows.append(
                {
                    "label": LABEL,
                    "family": "breakout",
                    "variant_id": variant_id,
                    "period": "recent",
                    "year": year,
                    "total_return": values.get("total_return"),
                    "sharpe_ratio": values.get("sharpe_ratio"),
                    "num_trades": values.get("num_trades"),
                    "max_drawdown_pct": values.get("max_drawdown_pct"),
                }
            )

    comparison = pd.DataFrame(rows)
    comparison.to_csv(output_root / "research_vs_recent.csv", index=False)

    yearly = pd.DataFrame(yearly_rows)
    yearly.to_csv(output_root / "yearly_2025_2026.csv", index=False)

    family_summary = _build_family_summary(comparison)
    family_summary.to_csv(output_root / "family_summary.csv", index=False)

    ranking_stability = _build_ranking_stability(comparison)
    with open(output_root / "ranking_stability.json", "w") as f:
        json.dump(ranking_stability, f, indent=2, default=str)

    bh_research_bench = _load_research_buy_and_hold()
    buy_hold_comparison = {
        "label": LABEL,
        "recent_period": {"start": RECENT_START, "end": RECENT_END},
        "recent_buy_and_hold": {
            "total_return": bh_recent_metrics.get("total_return"),
            "max_drawdown_pct": bh_recent_metrics.get("max_drawdown_pct"),
            "sharpe_ratio": bh_recent_metrics.get("sharpe_ratio"),
            "volatility_annualized": bh_recent_metrics.get("volatility_annualized"),
        },
        "research_buy_and_hold": bh_research_bench,
    }
    with open(output_root / "buy_and_hold_comparison.json", "w") as f:
        json.dump(buy_hold_comparison, f, indent=2, default=str)

    metadata = {
        "status": LABEL,
        "purpose": (
            "Retrospective post-hoc comparison of Phase-2-registered configurations "
            "(sma_cross, momentum, mean_reversion) plus the two already-frozen "
            "breakout candidates against the already-consumed 2025-2026 period. "
            "NOT a new holdout. NOT out-of-sample evidence. Results must not be "
            "used to select, tune, reject, or refine any strategy."
        ),
        "symbol": symbol,
        "timeframe": timeframe,
        "recent_period": {"start": RECENT_START, "end": RECENT_END},
        "research_period": {
            "start": str(pd.to_datetime(split.research["timestamp"], utc=True).min()),
            "end": str(pd.to_datetime(split.research["timestamp"], utc=True).max()),
        },
        "dataset_hash_full": dataset_hash(df),
        "total_configurations_evaluated": len(rows),
        "configurations_by_family": comparison["family"].value_counts().to_dict(),
        "breakout_source": "reused verbatim from research/final_holdout (no new backtest)",
        "re_evaluated_families": list(RE_EVALUATED_FAMILIES),
        "forbidden": [
            "out-of-sample", "validation", "proven", "holdout success",
            "PROVEN", "PROFITABLE", "OUT-OF-SAMPLE WINNER",
        ],
        "allowed_classification_labels": [
            "RECENTLY RESILIENT", "RECENTLY DEGRADED", "CONSISTENTLY WEAK",
            "REGIME-SENSITIVE", "INCONCLUSIVE",
        ],
    }
    with open(output_root / "POST_HOC_METADATA.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    summary_md = _build_summary_md(comparison, family_summary, ranking_stability, metadata)
    with open(output_root / "summary.md", "w") as f:
        f.write(summary_md)

    return output_root


def _load_research_buy_and_hold() -> dict[str, Any] | None:
    """Research-period (2018-2024) buy-and-hold benchmark, if already
    recorded by Phase 2, for reference in the buy-and-hold comparison.
    """
    path = Path("research/reports/phase2_metadata.json")
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return data.get("benchmark")


def _build_family_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for family, group in comparison.groupby("family"):
        rows.append(
            {
                "label": LABEL,
                "family": family,
                "n_configs": len(group),
                "research_median_return": group["research_total_return"].median(),
                "recent_median_return": group["recent_total_return"].median(),
                "research_median_sharpe": group["research_sharpe_ratio"].median(),
                "recent_median_sharpe": group["recent_sharpe_ratio"].median(),
                "pct_configs_positive_research": float(
                    (group["research_total_return"] > 0).mean()
                ),
                "pct_configs_positive_recent": float(
                    (group["recent_total_return"] > 0).mean()
                ),
                "research_median_drawdown": group["research_max_drawdown_pct"].median(),
                "recent_median_drawdown": group["recent_max_drawdown_pct"].median(),
                "median_recent_trade_count": group["recent_num_trades"].median(),
                "status": _family_status(group),
            }
        )
    return pd.DataFrame(rows)


def _family_status(group: pd.DataFrame) -> str:
    """Purely descriptive family-level roll-up of the per-config
    classifications. Never a validation claim.
    """
    counts = group["classification"].value_counts()
    if counts.empty:
        return "INCONCLUSIVE"
    dominant = counts.idxmax()
    dominant_share = counts.max() / len(group)
    if dominant_share < 0.5:
        return "MIXED WITHIN FAMILY"
    return dominant


def _build_ranking_stability(comparison: pd.DataFrame) -> dict[str, Any]:
    """Spearman rank correlation between research-period and recent-period
    performance, computed per family (mixing families would compare apples
    to oranges — a weak momentum config and a strong SMA config are not
    comparable on the same rank scale) and is explicitly NOT computed when a
    family has too few configurations to be meaningful.

    This was not explicitly requested as a numeric library dependency by the
    task, but scipy.stats.spearmanr is used here (added to requirements.txt)
    rather than hand-rolling a tie-aware rank correlation, since an
    incorrect from-scratch implementation would be worse than a well-tested
    one for a statistic this task explicitly asks not to be over-interpreted.
    """
    results: dict[str, Any] = {}
    min_n_for_correlation = 5  # below this, a correlation coefficient is not meaningful

    for family, group in comparison.groupby("family"):
        n = len(group)
        entry: dict[str, Any] = {"n_configs": int(n)}
        if n < min_n_for_correlation:
            entry["note"] = (
                f"only {n} configuration(s) in this family; rank correlation is not "
                f"reported (minimum {min_n_for_correlation} needed for a remotely "
                "stable Spearman estimate, and even at n=5 this should be read as "
                "highly provisional)"
            )
            results[family] = entry
            continue

        for metric in ["total_return", "sharpe_ratio", "max_drawdown_pct", "expectancy"]:
            research_col = group[f"research_{metric}"]
            recent_col = group[f"recent_{metric}"]
            mask = research_col.notna() & recent_col.notna()
            if mask.sum() < min_n_for_correlation:
                entry[metric] = {"note": "insufficient non-null pairs for correlation"}
                continue
            rho, pvalue = spearmanr(research_col[mask], recent_col[mask])
            entry[metric] = {
                "spearman_rho": float(rho) if not np.isnan(rho) else None,
                "p_value": float(pvalue) if not np.isnan(pvalue) else None,
                "n_pairs": int(mask.sum()),
            }
        results[family] = entry

    results["_limitations"] = (
        "All family sample sizes here are small (5-12 configurations). Spearman "
        "correlations from samples this small have wide confidence intervals and "
        "can flip sign with one or two configurations changing rank. Treat any "
        "correlation reported here as a weak, provisional signal about whether "
        "research-period ranking survived into the recent period -- not as "
        "statistical proof of persistence or its absence. Breakout is excluded "
        "from this analysis (only 2 frozen configurations exist; a 2-point "
        "correlation is not meaningful)."
    )
    return results


def _df_to_markdown_table(df: pd.DataFrame) -> str:
    """Minimal GitHub-flavored markdown table renderer, avoiding an extra
    dependency (pandas' `to_markdown` requires the optional `tabulate`
    package, which is not otherwise needed by this project).
    """
    if df.empty:
        return "_(no rows)_"
    headers = list(df.columns)
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.tolist()) + " |")
    return "\n".join(lines)


def _build_summary_md(
    comparison: pd.DataFrame,
    family_summary: pd.DataFrame,
    ranking_stability: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    lines = [
        f"# {LABEL}",
        "",
        "**This is retrospective post-hoc analysis, not a new holdout or "
        "out-of-sample test.** 2025-01-01 to 2026-09-02 was already consumed "
        "by the final-holdout evaluation for the two frozen breakout "
        "candidates. This report re-evaluates OTHER already-registered Phase-2 "
        "configurations (sma_cross, momentum, mean_reversion) against that same "
        "already-consumed period, purely to understand regime change and "
        "generate forward hypotheses. No conclusion here may be used to select, "
        "tune, reject, or refine any strategy.",
        "",
        f"- Total configurations evaluated: {metadata['total_configurations_evaluated']}",
        f"- By family: {metadata['configurations_by_family']}",
        f"- Research period: {metadata['research_period']['start']} to {metadata['research_period']['end']}",
        f"- Recent (post-holdout, consumed) period: {RECENT_START} to {RECENT_END}",
        "",
        "## Family summary",
        "",
        _df_to_markdown_table(family_summary),
        "",
        "## Ranking stability (Spearman, research vs recent)",
        "",
        "```json",
        json.dumps(ranking_stability, indent=2, default=str),
        "```",
        "",
        "## Classification counts",
        "",
        _df_to_markdown_table(
            comparison["classification"].value_counts().rename_axis("classification").reset_index(name="count")
        ),
        "",
        "See `research_vs_recent.csv` for the full per-configuration comparison, "
        "`yearly_2025_2026.csv` for the 2025 vs 2026-YTD breakdown, and "
        "`buy_and_hold_comparison.json` for the same-period benchmark.",
    ]
    return "\n".join(lines)
