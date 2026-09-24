"""Phase 5F: attribution over saved research artifacts only.

This module deliberately never imports a strategy, data set, backtest engine,
or execution client.  It is an accounting reader for already observed JSON.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

PHASE5D_ROOT = Path("data/fx/research/results/phase5d_run2_insolvency_policy")
PHASE5E_ROOT = Path("data/fx/research/results/phase5e_run1_preregistered_events")
OUTPUT_ROOT = Path("data/fx/research/results/phase5f_mechanism_attribution")
MIN_SAMPLE = 30


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _number(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator > 0 else None


def _source_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_observed_artifact(path: Path) -> dict[str, Any]:
    """Load one saved result; structurally reject test/untouched inputs."""
    lowered = {part.lower() for part in path.parts}
    if {"test", "untouched_test", "untouched"} & lowered:
        raise ValueError("Phase 5F forbids untouched-test source artifacts")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("split", "").lower() in {"test", "untouched_test", "untouched"}:
        raise ValueError("Phase 5F forbids untouched-test source artifacts")
    payload["_source_path"] = str(path)
    payload["_source_sha256"] = _source_sha(path)
    return payload


def _gross(payload: dict[str, Any]) -> Decimal:
    value = payload.get("gross_reference_pnl")
    if value is None:
        value = payload["gross_pnl"]
    return _decimal(value)


def derive_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """Produce deterministic, JSON-safe attribution from existing fields."""
    gross = _gross(payload)
    net = _decimal(payload["net_pnl"])
    count = int(payload["trade_count"])
    costs = {key: _decimal(payload.get(key, 0)) for key in (
        "spread_cost", "slippage_cost", "commission_cost", "swap_cost")}
    total = _decimal(payload.get("total_costs", sum(costs.values())))
    insufficient = count < MIN_SAMPLE
    if gross <= 0:
        mechanism = "NEGATIVE_GROSS_SIGNAL"
    elif net <= 0:
        mechanism = "POSITIVE_GROSS_COST_DESTROYED"
    elif insufficient:
        mechanism = "INSUFFICIENT_SAMPLE"
    else:
        mechanism = "POSITIVE_NET_BUT_NOT_ROBUST"
    per_trade = lambda x: x / count if count else None
    return {
        "phase": "5E" if payload["run_id"].startswith("phase5e") else "5D",
        "variant_id": payload["variant_id"], "family": payload["family"],
        "split": payload["split"], "control": bool(payload.get("control", False) or payload["family"] == "control"),
        "source": {key: payload.get(key) for key in ("run_id", "dataset_sha256", "spread_profile_sha256", "non_spread_cost_profile_sha256", "preregistration_sha256")},
        "source_path": payload.get("_source_path"), "source_sha256": payload.get("_source_sha256"),
        "trade_count": count, "gross_reference_pnl": _number(gross),
        "spread_cost": _number(costs["spread_cost"]), "slippage_cost": _number(costs["slippage_cost"]),
        "commission_cost": _number(costs["commission_cost"]), "swap_cost": _number(costs["swap_cost"]),
        "total_costs": _number(total), "net_pnl": _number(net),
        "gross_pnl_per_trade": _number(per_trade(gross)), "cost_per_trade": _number(per_trade(total)),
        "net_pnl_per_trade": _number(per_trade(net)), "cost_to_gross_ratio": _number(_safe_ratio(total, gross)),
        "required_extra_gross_usd": _number(max(Decimal(0), -net)),
        "required_extra_gross_per_trade_usd": _number(per_trade(max(Decimal(0), -net))),
        "required_extra_gross_points_per_trade": None,
        "points_reason": "not stored as a per-trade conversion in source artifact",
        "primary_mechanism": mechanism, "insufficient_sample": insufficient,
        "insolvent": bool(payload.get("insolvent", False)),
        "long": {"trade_count": payload.get("long_trade_count"), "net_pnl": payload.get("long_net_pnl"), "gross_pnl": None, "total_costs": None, "expectancy": None, "profit_factor": None},
        "short": {"trade_count": payload.get("short_trade_count"), "net_pnl": payload.get("short_net_pnl"), "gross_pnl": None, "total_costs": None, "expectancy": None, "profit_factor": None},
        "yearly": payload.get("yearly"),
        "concentration": {"largest_positive_trade_contribution": payload.get("largest_trade_contribution"), "top_5_positive_trade_contribution": payload.get("top_5_trade_contribution"), "largest_loss_contribution": None, "top_5_losses_contribution": None, "net_without_best_trade": None, "net_without_worst_trade": None},
        "monthly": None, "entry_hour": None, "holding_time": None,
        "unavailable_reason": "source artifacts contain aggregate results, not completed-trade rows",
    }


def family_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row["control"]:
            groups[(row["phase"], row["family"])].append(row)
    summaries = []
    for (phase, family), values in sorted(groups.items()):
        mechanisms = {v["primary_mechanism"] for v in values}
        net_signs = {"positive" if _decimal(v["net_pnl"]) > 0 else "non_positive" for v in values}
        gross_signs = {"positive" if _decimal(v["gross_reference_pnl"]) > 0 else "non_positive" for v in values}
        if all(v["insufficient_sample"] for v in values): label = "INSUFFICIENT_SAMPLE"
        elif any(v["insolvent"] for v in values): label = "INSOLVENCY"
        elif mechanisms == {"NEGATIVE_GROSS_SIGNAL"}: label = "RAW_SIGNAL_NEGATIVE"
        elif mechanisms <= {"POSITIVE_GROSS_COST_DESTROYED", "INSUFFICIENT_SAMPLE"}: label = "COST_DOMINATED"
        elif len(net_signs) > 1: label = "TEMPORALLY_UNSTABLE"
        else: label = "MIXED"
        summaries.append({"phase": phase, "family": family, "variants": sorted({v["variant_id"] for v in values}), "typical_trade_count": sorted(v["trade_count"] for v in values)[len(values)//2], "gross_sign": sorted(gross_signs), "net_sign": sorted(net_signs), "primary_failure_mechanism": label})
    return summaries


def build_phase5f(phase5d_root: Path = PHASE5D_ROOT, phase5e_root: Path = PHASE5E_ROOT) -> dict[str, Any]:
    paths = sorted(phase5d_root.glob("development/*.json")) + sorted(phase5d_root.glob("validation/*.json"))
    paths += sorted(phase5e_root.glob("development_inner_a/*.json")) + sorted(phase5e_root.glob("development_inner_b/*.json")) + sorted(phase5e_root.glob("development/*.json")) + sorted(phase5e_root.glob("validation/*.json"))
    rows = [derive_artifact(load_observed_artifact(path)) for path in paths]
    return {"phase": "5F", "kind": "POST-HOC_DESCRIPTIVE_NOT_TESTED", "untouched_test": "UNTOUCHED", "rows": rows, "families": family_summary(rows)}


def write_phase5f(output_root: Path = OUTPUT_ROOT) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    result = build_phase5f()
    path = output_root / "phase5f_attribution.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
