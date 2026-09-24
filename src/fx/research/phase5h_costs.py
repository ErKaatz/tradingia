"""Strict, read-only EURUSD/H1 Phase 5H cost-calibration artifact builder."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _q(values: list[int], p: Decimal) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = int(position), min(int(position) + 1, len(ordered) - 1)
    return str(Decimal(ordered[lo]) + (Decimal(ordered[hi]) - Decimal(ordered[lo])) * (position - lo))


def build_cost_report(*, bars_path: Path, availability_record_path: Path, metadata: dict[str, Any], account: dict[str, Any], start: datetime, end_exclusive: datetime, minimum_observations_per_hour: int, preregistration_sha256: str) -> dict[str, Any]:
    """Build a strict artifact; missing/insufficient hourly spread fails closed."""
    if start.tzinfo is None or end_exclusive.tzinfo is None or start >= end_exclusive:
        raise ValueError("invalid calibration window")
    raw = json.loads(bars_path.read_text())
    selected = [r for r in raw if start <= datetime.fromisoformat(r["timestamp"]).astimezone(timezone.utc) < end_exclusive]
    if not selected:
        raise ValueError("calibration window has no bars")
    buckets = []
    all_spreads: list[int] = []
    for hour in range(24):
        entries = [r.get("spread") for r in selected if datetime.fromisoformat(r["timestamp"]).hour == hour]
        values = [int(x) for x in entries if x is not None]
        all_spreads.extend(values)
        sufficient = len(values) >= minimum_observations_per_hour
        buckets.append({"hour_utc": hour, "count": len(values), "missing": len(entries) - len(values), "median_points": _q(values, Decimal("0.50")) if sufficient else None, "p75_points": _q(values, Decimal("0.75")) if sufficient else None, "p95_points": _q(values, Decimal("0.95")) if sufficient else None, "p99_points": _q(values, Decimal("0.99")) if sufficient else None, "sufficient": sufficient})
    required = ("digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "volume_min", "volume_max", "volume_step", "currency_base", "currency_profit", "currency_margin")
    missing_metadata = [name for name in required if metadata.get(name) is None]
    swap_mode = metadata.get("swap_mode")
    swap_convertible = swap_mode == 1 and metadata.get("currency_profit") == account.get("currency")
    point = Decimal(str(metadata["point"])) if metadata.get("point") is not None else None
    contract = Decimal(str(metadata["trade_contract_size"])) if metadata.get("trade_contract_size") is not None else None
    def swap_cost(value: Any) -> str | None:
        if not swap_convertible or point is None or contract is None:
            return None
        return str(-(Decimal(str(value)) * point * contract))
    availability = json.loads(availability_record_path.read_text())
    slice_fingerprint = _sha({"symbol": "EURUSD", "timeframe": "H1", "start": start.astimezone(timezone.utc).isoformat(), "end_exclusive": end_exclusive.astimezone(timezone.utc).isoformat(), "bars": selected})
    commission = {"treatment": "NoCommission", "classification": "RESEARCH_ASSUMPTION", "commission_per_lot_per_side": "0", "evidence": "No direct per-lot commission field exposed by read-only bridge metadata."}
    swap = {"source": "current MT5 symbol metadata", "swap_long_raw": metadata.get("swap_long"), "swap_short_raw": metadata.get("swap_short"), "swap_mode": swap_mode, "swap_rollover3days": metadata.get("swap_rollover3days"), "convertible": swap_convertible, "long_debit_per_lot": swap_cost(metadata.get("swap_long")), "short_debit_per_lot": swap_cost(metadata.get("swap_short"))}
    profile = {"policy": "hourly_p95", "minimum_observations_per_hour": minimum_observations_per_hour, "buckets": buckets}
    report: dict[str, Any] = {"phase": "5H", "kind": "EURUSD_H1_cost_calibration", "provenance": {"requested_start_utc": start.astimezone(timezone.utc).isoformat(), "requested_end_exclusive_utc": end_exclusive.astimezone(timezone.utc).isoformat(), "actual_start_utc": selected[0]["timestamp"], "actual_end_utc": selected[-1]["timestamp"], "bar_count": len(selected), "source": "Phase 5G read-only H1 capture", "preregistration_sha256": preregistration_sha256}, "fingerprints": {"capture_dataset_sha256": slice_fingerprint, "source_dataset_sha256": availability["fingerprint_sha256"], "raw_capture_sha256": availability["raw_capture_sha256"], "metadata_sha256": _sha(metadata)}, "metadata": metadata | {"server": account.get("server"), "account_currency": account.get("currency")}, "spread_profile": profile, "commission": commission, "swap": swap, "slippage": {"adverse_points_per_fill": 1, "classification": "ASSUMPTION"}}
    gate = {"dataset_valid": True, "all_hourly_buckets_sufficient": all(b["sufficient"] for b in buckets), "metadata_complete": not missing_metadata, "missing_metadata": missing_metadata, "swap_convertible": swap_convertible, "commission_explicit": True, "slippage_explicit": True}
    gate["verdict"] = "PASS" if all(gate[k] for k in ("dataset_valid", "all_hourly_buckets_sufficient", "metadata_complete", "swap_convertible", "commission_explicit", "slippage_explicit")) else "FAIL"
    report["gate"] = gate
    report["fingerprints"]["cost_profile_sha256"] = _sha({"spread_profile": profile, "commission": commission, "swap": swap, "slippage": report["slippage"], "metadata_sha256": report["fingerprints"]["metadata_sha256"], "capture_dataset_sha256": slice_fingerprint})
    return report


def write_cost_report(report: dict[str, Any], path: Path = Path("data/fx/EURUSD/H1/phase5h_cost_report.json")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path
