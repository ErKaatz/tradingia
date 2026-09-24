"""Fail-closed runner for the frozen Phase 5H EURUSD/H1 evaluation.

This module deliberately has no MT5 client dependency: it consumes only the
already captured Phase 5G H1 JSON.  ``run_phase5h`` is the single historical
performance entry point and verifies every frozen input before generating a
signal or opening the local backtest engine.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.fx.backtesting.costs import FixedPointsSlippage, NoCommission, RolloverSchedule, SideAwareFixedSwapModel
from src.fx.backtesting.engine import FxBacktestEngine, FxEngineConfig
from src.fx.backtesting.metrics_adapter import to_neutral_backtest_result
from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar
from src.fx.research.contracts import ExperimentManifest, ResearchTradeRecord, write_bundle
from src.fx.research.fingerprints import verify_canonical_document_fingerprint
from src.fx.strategies.phase5h_failed_breakout import HOLDING_BARS, daily_range_failed_breakout
from src.metrics.metrics import build_metrics_report

COST_PREREG_SHA = "a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c"
PREREG_SHA = "212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709"
COST_PROFILE_SHA = "b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7"
CAPTURE_SHA = "96025369147c81ce9c10df34b1505f263c3622085100502ec8ff238ecd44912e"
RAW_CAPTURE_SHA = "099e120c0c92062056961139fd08e207f82d4368caf7e9952a69c59584f1b738"
METADATA_SHA = "9cb69f172b716b878957ecc1ee4267cdf0d3c37d8a613ceca5d88356e6ce3267"
RUN_ID = "phase5h_run4_preregistered_failed_breakout"
VARIANTS = ("daily-range-failed-breakout-long", "daily-range-failed-breakout-short")
SPLITS = {
    "development_inner_a": ("2022-09-01T00:00:00+00:00", "2023-09-01T00:00:00+00:00"),
    "development_inner_b": ("2023-09-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
    "development": ("2022-09-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
    "validation": ("2024-09-01T00:00:00+00:00", "2025-08-30T00:00:00+00:00"),
}


def _decimal(value: Any) -> Decimal: return Decimal(str(value))


def _sha_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integrity_gate(cost_path: Path = Path("data/fx/EURUSD/H1/phase5h_cost_report.json")) -> dict[str, str]:
    """Verify immutable inputs.  It raises before strategy code can run."""
    root = Path(__file__).resolve().parents[3]
    verify_canonical_document_fingerprint(root / "PHASE5H_COST_PREREGISTRATION.md", COST_PREREG_SHA)
    verify_canonical_document_fingerprint(root / "PHASE5H_PREREGISTRATION.md", PREREG_SHA)
    report = json.loads(cost_path.read_text())
    frozen = report["fingerprints"]
    expected = {"cost_profile_sha256": COST_PROFILE_SHA, "capture_dataset_sha256": CAPTURE_SHA,
                "raw_capture_sha256": RAW_CAPTURE_SHA, "metadata_sha256": METADATA_SHA}
    if {k: frozen.get(k) for k in expected} != expected:
        raise ValueError("Phase 5H frozen cost fingerprint mismatch")
    if report.get("gate", {}).get("verdict") != "PASS":
        raise ValueError("Phase 5H cost calibration gate did not pass")
    return {"cost_preregistration_sha256": COST_PREREG_SHA, "preregistration_sha256": PREREG_SHA, **expected}


def _load_bars(path: Path) -> tuple[FxBar, ...]:
    rows = json.loads(path.read_text())
    bars = tuple(FxBar(datetime.fromisoformat(r["timestamp"]), _decimal(r["open"]), _decimal(r["high"]), _decimal(r["low"]), _decimal(r["close"]), _decimal(r["tick_volume"]), _decimal(r["real_volume"]) if r["real_volume"] is not None else None, r["spread"]) for r in rows)
    if any(b.timestamp_utc.tzinfo is None for b in bars) or tuple(sorted(bars, key=lambda b: b.timestamp_utc)) != bars:
        raise ValueError("captured bars must be chronological UTC bars")
    return bars


def _costed(bars: tuple[FxBar, ...], report: dict[str, Any]) -> tuple[FxBar, ...]:
    by_hour = {int(x["hour_utc"]): x["p95_points"] for x in report["spread_profile"]["buckets"]}
    result = []
    for b in bars:
        p95 = by_hour.get(b.timestamp_utc.hour)
        if p95 is None:
            raise ValueError("missing required hourly P95 cost bucket")
        result.append(FxBar(b.timestamp_utc, b.open, b.high, b.low, b.close, b.tick_volume, b.real_volume, int(Decimal(p95))))
    return tuple(result)


def _completed_targets(targets: tuple[TargetPosition, ...]) -> tuple[TargetPosition, ...]:
    """Remove only tail events lacking an entry plus four complete held bars.

    The decision is an execution-data-boundary rule, not a signal rule; it
    never changes a target earlier in the supplied sequence.
    """
    original_length = len(targets)
    output = list(targets)
    for i, target in enumerate(targets):
        # A target block represents one event.  The generic engine shifts
        # target[i] to the entry at i+1, retains the four targets i..i+3,
        # and closes at i+5.  It is crucial to decide the boundary once at
        # the block's first target; masking target[i+1:] independently would
        # turn a valid four-bar block into a one-bar position.
        is_block_start = target is not TargetPosition.FLAT and (i == 0 or targets[i - 1] is TargetPosition.FLAT)
        if is_block_start and i + HOLDING_BARS + 1 >= len(targets):
            # Assign only extant indexes.  Assigning a four-item list to a
            # shorter tail slice would grow ``output`` in Python and violate
            # the one-bar/one-target contract before the engine sees it.
            for j in range(i, min(i + HOLDING_BARS, original_length)):
                output[j] = TargetPosition.FLAT
    if len(output) != original_length:
        raise RuntimeError("Phase 5H target cleanup changed sequence length")
    return tuple(output)


def _validate_pre_engine_targets(bars: tuple[FxBar, ...], signals: tuple[TargetPosition, ...], split: str, variant: str) -> None:
    """Fail closed on a malformed target sequence before engine execution."""
    if len(bars) != len(signals):
        raise ValueError(f"Phase 5H pre-engine length mismatch split={split} variant={variant} bars={len(bars)} signals={len(signals)}")
    for i, target in enumerate(signals):
        is_block_start = target is not TargetPosition.FLAT and (i == 0 or signals[i - 1] is TargetPosition.FLAT)
        if not is_block_start:
            continue
        complete_targets = i + HOLDING_BARS < len(signals) and all(signals[j] is target for j in range(i, i + HOLDING_BARS)) and signals[i + HOLDING_BARS] is TargetPosition.FLAT
        complete_execution = i + HOLDING_BARS + 1 < len(bars)
        if not complete_targets or not complete_execution:
            raise ValueError(f"Phase 5H incomplete event block split={split} variant={variant} signal_index={i}")


def _config(report: dict[str, Any]) -> FxEngineConfig:
    m, swap = report["metadata"], report["swap"]
    return FxEngineConfig("EURUSD", Decimal(".01"), _decimal(m["trade_contract_size"]), _decimal(m["point"]), _decimal(m["volume_min"]), _decimal(m["volume_max"]), _decimal(m["volume_step"]), m["currency_profit"], m["account_currency"], Decimal("100"), NoCommission(), FixedPointsSlippage(Decimal("1")), SideAwareFixedSwapModel(_decimal(swap["long_debit_per_lot"]), _decimal(swap["short_debit_per_lot"]), 2), RolloverSchedule(frozenset({0})), True)


def _revision() -> tuple[str, str]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True).stdout.strip() or "DETACHED"
    return commit, branch


def _trade_records(result, bars: tuple[FxBar, ...], targets: tuple[TargetPosition, ...], variant: str, split: str) -> list[ResearchTradeRecord]:
    index = {b.timestamp_utc: i for i, b in enumerate(bars)}
    records = []
    for trade in result.trades:
        entry_i, exit_i = index[trade.open_time], index[trade.close_time]
        signal_i = entry_i - 1
        if signal_i < 0 or targets[signal_i] is TargetPosition.FLAT or trade.bars_held != HOLDING_BARS:
            raise RuntimeError("Phase 5H signal/holding semantics error")
        entry_ref, exit_ref = bars[entry_i].open, bars[exit_i].open
        records.append(ResearchTradeRecord("phase5h", RUN_ID, variant, split, "EURUSD", "H1", trade.side.value, trade.lots, bars[signal_i].timestamp_utc, trade.open_time, trade.close_time, entry_ref, trade.entry_bid, trade.entry_ask, trade.entry_execution_price, exit_ref, trade.exit_bid, trade.exit_ask, trade.exit_execution_price, trade.gross_pnl, trade.spread_cost, trade.slippage_cost, trade.commission_cost, trade.swap_cost, trade.net_pnl, trade.bars_held, int((trade.close_time - trade.open_time).total_seconds()), result.insolvent))
    return records


def _sum(rows, name: str) -> Decimal: return sum((getattr(r, name) for r in rows), Decimal("0"))


def _attribution(rows: list[ResearchTradeRecord], key) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ResearchTradeRecord]] = defaultdict(list)
    for row in rows: groups[key(row)].append(row)
    return {name: {"trade_count": len(items), "net_pnl": str(_sum(items, "net_pnl"))} for name, items in sorted(groups.items())}


def _summary(records: list[ResearchTradeRecord], result) -> dict[str, Any]:
    gross = _sum(records, "gross_reference_pnl")
    costs = {name: _sum(records, name) for name in ("spread_cost", "slippage_cost", "commission_cost", "swap_cost")}
    total = sum(costs.values(), Decimal("0")); net = _sum(records, "net_pnl")
    if net != gross - total: raise RuntimeError("run-level accounting reconciliation failed")
    metrics = build_metrics_report(to_neutral_backtest_result(result), 24 * 365)
    wins, losses = [r.net_pnl for r in records if r.net_pnl > 0], [r.net_pnl for r in records if r.net_pnl < 0]
    positive = sum(wins, Decimal("0"))
    return {"trade_count": len(records), "gross_reference_pnl": str(gross), **{k: str(v) for k, v in costs.items()}, "total_costs": str(total), "net_pnl": str(net), "expectancy": str(net / len(records)) if records else None, "profit_factor": str(sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0")))) if losses else None, "max_drawdown": str(metrics["max_drawdown_pct"]), "solvent": not result.insolvent, "insolvent": result.insolvent, "termination_reason": result.termination_reason, "final_balance": str(result.final_account.balance), "cost_efficiency_ratio": str(total / gross) if gross > 0 else None, "largest_positive_trade_contribution": str(max(wins) / positive) if positive else None, "yearly_attribution": _attribution(records, lambda r: str(r.entry_timestamp.year)), "monthly_attribution": _attribution(records, lambda r: r.entry_timestamp.strftime("%Y-%m")), "entry_hour_attribution": _attribution(records, lambda r: f"{r.entry_timestamp.hour:02d}"), "trade_concentration": {"largest_positive_trade_contribution": str(max(wins) / positive) if positive else None}, "metrics": metrics}


def run_phase5h(output_root: Path = Path("data/fx/research/results/phase5h_run4_preregistered_failed_breakout")) -> dict[str, dict[str, dict[str, Any]]]:
    """Run the exact four frozen stages once; callers must not invoke a stage."""
    frozen = integrity_gate(); root = Path(__file__).resolve().parents[3]
    report = json.loads((root / "data/fx/EURUSD/H1/phase5h_cost_report.json").read_text())
    source = _load_bars(root / "data/fx/research/phase5g_availability/EURUSD/H1/bars.json")
    commit, branch = _revision(); all_output = {}
    for split, (start_raw, end_raw) in SPLITS.items():
        start, end = datetime.fromisoformat(start_raw), datetime.fromisoformat(end_raw)
        bars = _costed(tuple(b for b in source if start <= b.timestamp_utc < end), report)
        if len(bars) < 2: raise RuntimeError(f"no usable bars in {split}")
        all_output[split] = {}
        for variant in VARIANTS:
            raw_targets = daily_range_failed_breakout(bars, variant)
            if len(raw_targets) != len(bars):
                raise ValueError(f"Phase 5H raw target length mismatch split={split} variant={variant} bars={len(bars)} signals={len(raw_targets)}")
            targets = _completed_targets(raw_targets)
            _validate_pre_engine_targets(bars, targets, split, variant)
            result = FxBacktestEngine(_config(report)).run(bars, targets)
            records = _trade_records(result, bars, targets, variant, split)
            summary = _summary(records, result)
            manifest = ExperimentManifest("phase5h", RUN_ID, commit, branch, frozen["capture_dataset_sha256"], frozen["cost_profile_sha256"], frozen["metadata_sha256"], frozen["preregistration_sha256"], "EURUSD", "H1", split, VARIANTS, {"next_bar_execution": True, "holding_bars": HOLDING_BARS, "hourly_spread": "P95", "slippage_points_per_fill": 1, "rollover_utc_hour": 0}, {"initial_balance_usd": "100", "lots": "0.01", "commission": "NoCommission", "insolvency_equity_lte_zero": True}, "PHASE5H_PREREGISTRATION.md", datetime.now(timezone.utc))
            write_bundle(output_root / split / variant, manifest, summary, records)
            all_output[split][variant] = summary
    return all_output


def _rule_matrix(rows: dict[str, dict[str, Any]]) -> dict[str, bool]:
    minimums = {"development_inner_a": 8, "development_inner_b": 8, "development": 20, "validation": 8}
    all_rows = list(rows.items())
    gross_cost = all(r["gross_reference_pnl"] != "0" and (Decimal(r["gross_reference_pnl"]) > 0 and Decimal(r["total_costs"]) / Decimal(r["gross_reference_pnl"]) <= Decimal(".75")) for _, r in all_rows)
    basic = {f"{s}_sample": r["trade_count"] >= minimums[s] for s, r in all_rows} | {f"{s}_solvent": r["solvent"] for s, r in all_rows} | {f"{s}_net_pnl_positive": Decimal(r["net_pnl"]) > 0 for s, r in all_rows} | {f"{s}_expectancy_positive": r["expectancy"] is not None and Decimal(r["expectancy"]) > 0 for s, r in all_rows} | {f"{s}_pf_gt_1": r["profit_factor"] is not None and Decimal(r["profit_factor"]) > 1 for s, r in all_rows} | {f"{s}_drawdown": Decimal(r["max_drawdown"]) >= Decimal("-.20") for s, r in all_rows}
    basic["cost_efficiency_all_required_splits"] = gross_cost
    annual = defaultdict(lambda: [0, Decimal("0")])
    for split in ("development", "validation"):
        for year, value in rows[split]["yearly_attribution"].items(): annual[year][0] += value["trade_count"]; annual[year][1] += Decimal(value["net_pnl"])
    qualifying = [pnl for count, pnl in annual.values() if count >= 5]
    positive = [pnl for pnl in qualifying if pnl > 0]; total_positive = sum(positive, Decimal("0"))
    basic["annual_stability"] = bool(qualifying) and all(pnl > 0 for pnl in qualifying) and total_positive > 0 and max(positive) / total_positive <= Decimal(".70")
    largest = [r["largest_positive_trade_contribution"] for _, r in all_rows]
    basic["largest_positive_trade_contribution"] = all(v is not None and Decimal(v) <= Decimal(".25") for v in largest)
    return basic


def classify_phase5h(output_root: Path = Path("data/fx/research/results/phase5h_run4_preregistered_failed_breakout")) -> dict[str, dict[str, Any]]:
    """Classify completed artifacts only; no performance is run here."""
    results = {}
    for variant in VARIANTS:
        rows = {split: json.loads((output_root / split / variant / "summary.json").read_text()) for split in SPLITS}
        rules = _rule_matrix(rows)
        results[variant] = {"classification": "CANDIDATE" if all(rules.values()) else "REJECT", "candidate_rules": rules}
    (output_root / "classification.json").write_text(json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return results
