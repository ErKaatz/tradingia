"""Availability-only selection rules for Phase 5G Track B.

No function in this module reads OHLC/spread values to rank a market, builds
signals, or runs a backtest.  It turns the prior read-only availability ledger
into a deterministic common-window decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from src.fx.research.phase5g_capture import AvailabilityRecord


MINIMUM_MONTHS = 24


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add whole calendar months without a third-party date dependency."""
    if value.tzinfo is None:
        raise ValueError("value must be timezone-aware")
    year, zero_month = divmod(value.month - 1 + months, 12)
    return value.replace(year=value.year + year, month=zero_month + 1)


@dataclass(frozen=True)
class CellDecision:
    symbol: str
    timeframe: str
    status: str
    reason: str


@dataclass(frozen=True)
class CommonWindowDecision:
    eligible_cells: tuple[CellDecision, ...]
    insufficient_cells: tuple[CellDecision, ...]
    start_utc: datetime | None
    end_exclusive_utc: datetime | None

    @property
    def has_window(self) -> bool:
        return self.start_utc is not None and self.end_exclusive_utc is not None


def select_common_window(records: Iterable[AvailabilityRecord], latest_end_exclusive: datetime, minimum_months: int = MINIMUM_MONTHS) -> CommonWindowDecision:
    """Select the maximum common temporal envelope without subjective tuning.

    A cell is eligible solely when its capture has no errors and its actual
    first/last timestamps cover a full ``minimum_months`` calendar period
    ending no later than the fixed cap. Gaps are retained as integrity evidence
    and are deliberately not used to cherry-pick dates at this step.
    """
    if latest_end_exclusive.tzinfo is None:
        raise ValueError("latest_end_exclusive must be timezone-aware")
    cap = latest_end_exclusive.astimezone(timezone.utc)
    usable: list[tuple[AvailabilityRecord, datetime, datetime]] = []
    rejected: list[CellDecision] = []
    for record in sorted(records, key=lambda row: (row.symbol, row.timeframe)):
        if record.errors or record.actual_first_bar_utc is None or record.actual_last_bar_utc is None:
            rejected.append(CellDecision(record.symbol, record.timeframe, "INSUFFICIENT_DATA", "capture has errors or no bars"))
            continue
        first = datetime.fromisoformat(record.actual_first_bar_utc).astimezone(timezone.utc)
        # Last bar is inclusive; the cap is already an exclusive boundary.
        last = min(datetime.fromisoformat(record.requested_end_exclusive_utc).astimezone(timezone.utc), cap)
        if add_calendar_months(first, minimum_months) > last:
            rejected.append(CellDecision(record.symbol, record.timeframe, "INSUFFICIENT_DATA", f"does not cover {minimum_months} full calendar months"))
            continue
        usable.append((record, first, last))
    if not usable:
        return CommonWindowDecision((), tuple(rejected), None, None)
    start = max(first for _, first, _ in usable)
    end = min(last for _, _, last in usable)
    if add_calendar_months(start, minimum_months) > end:
        # No eligible group can support the required common duration. Mark all
        # individually eligible cells insufficient rather than invent a shorter window.
        rejected.extend(CellDecision(r.symbol, r.timeframe, "INSUFFICIENT_DATA", "eligible individually but no common 24-month window") for r, _, _ in usable)
        return CommonWindowDecision((), tuple(sorted(rejected, key=lambda row: (row.symbol, row.timeframe))), None, None)
    eligible = tuple(CellDecision(r.symbol, r.timeframe, "ELIGIBLE", "covers selected maximum common window") for r, _, _ in usable)
    return CommonWindowDecision(eligible, tuple(rejected), start, end)


def _quantile(values: list[Decimal], quantile: Decimal) -> Decimal | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _summary(values: list[Decimal]) -> dict[str, str | None]:
    return {"median": _decimal(_quantile(values, Decimal("0.50"))), "p75": _decimal(_quantile(values, Decimal("0.75"))), "p95": _decimal(_quantile(values, Decimal("0.95"))), "p99": _decimal(_quantile(values, Decimal("0.99")))}


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _weekday_slots(start: datetime, end_exclusive: datetime, timeframe: str) -> int:
    minutes = {"M5": 5, "M15": 15, "H1": 60}[timeframe]
    cursor = start.replace(second=0, microsecond=0)
    count = 0
    while cursor < end_exclusive:
        if cursor.weekday() < 5:
            count += 1
        cursor = cursor.replace() + __import__("datetime").timedelta(minutes=minutes)
    return count


def classify_structural_viability(*, bar_count: int, coverage_ratio: Decimal, validation_errors: tuple[str, ...], unexpected_gaps: int, median_ratio: Decimal | None, p95_ratio: Decimal | None) -> str:
    if bar_count < 500 or coverage_ratio < Decimal("0.98") or validation_errors or unexpected_gaps > 50:
        return "INSUFFICIENT_DATA"
    if median_ratio is None or p95_ratio is None:
        return "STRUCTURALLY_UNATTRACTIVE"
    if median_ratio <= Decimal("0.25") and p95_ratio <= Decimal("1.00"):
        return "VIABLE_FOR_FUTURE_RESEARCH"
    if median_ratio <= Decimal("0.50") and p95_ratio <= Decimal("2.00"):
        return "BORDERLINE"
    return "STRUCTURALLY_UNATTRACTIVE"


def build_viability_report(records: Iterable[AvailabilityRecord], *, metadata: dict[str, dict[str, Any]], availability_root: Path = Path("data/fx/research/phase5g_availability"), output_path: Path = Path("data/fx/research/results/phase5g_viability/viability_report.json")) -> dict[str, Any]:
    """Calculate only frozen descriptive microstructure metrics after freeze."""
    report_cells: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda row: (row.symbol, row.timeframe)):
        raw_rows = json.loads((availability_root / record.symbol / record.timeframe / "bars.json").read_text())
        start = datetime.fromisoformat(record.requested_start_utc).astimezone(timezone.utc)
        end = datetime.fromisoformat(record.requested_end_exclusive_utc).astimezone(timezone.utc)
        actual_start = datetime.fromisoformat(record.actual_first_bar_utc).astimezone(timezone.utc) if record.actual_first_bar_utc else start
        actual_end = datetime.fromisoformat(record.actual_last_bar_utc).astimezone(timezone.utc) if record.actual_last_bar_utc else start
        eligible = bool(record.actual_first_bar_utc) and not record.errors and add_calendar_months(actual_start, MINIMUM_MONTHS) <= end
        base = {"symbol": record.symbol, "timeframe": record.timeframe, "availability_status": "ELIGIBLE" if eligible else "INSUFFICIENT_DATA", "range": {"requested_start_utc": record.requested_start_utc, "requested_end_exclusive_utc": record.requested_end_exclusive_utc, "actual_first_bar_utc": record.actual_first_bar_utc, "actual_last_bar_utc": record.actual_last_bar_utc}, "bar_count": record.bar_count, "fingerprints": {"dataset_sha256": record.fingerprint_sha256, "raw_capture_sha256": record.raw_capture_sha256, "symbol_metadata_sha256": hashlib.sha256(json.dumps(metadata[record.symbol], sort_keys=True, separators=(",", ":")).encode()).hexdigest()}, "gaps": record.gap_counts, "warnings": list(record.warnings), "errors": list(record.errors)}
        if not eligible:
            base.update({"coverage": None, "spread_points": None, "spread_price": None, "movement_price": None, "cost_to_movement": None, "hourly_microstructure": {}, "structural_label": "INSUFFICIENT_DATA", "reason": "not evaluated beyond availability because it cannot support the frozen 24-month window"})
            report_cells.append(base)
            continue
        # Only eligible cells are evaluated in the frozen common window.
        rows = [row for row in raw_rows if record.actual_first_bar_utc and start <= datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc) < end]
        point = Decimal(str(metadata[record.symbol]["point"]))
        spreads = [Decimal(str(row["spread"])) for row in rows if row["spread"] is not None]
        ranges = [Decimal(str(row["high"])) - Decimal(str(row["low"])) for row in rows]
        close_moves = [abs(Decimal(str(curr["close"])) - Decimal(str(prev["close"]))) for prev, curr in zip(rows, rows[1:])]
        spread_price = [spread * point for spread in spreads]
        range_median = _quantile(ranges, Decimal("0.50"))
        close_move_median = _quantile(close_moves, Decimal("0.50"))
        median_spread = _quantile(spread_price, Decimal("0.50"))
        p95_spread = _quantile(spread_price, Decimal("0.95"))
        median_ratio = median_spread / range_median if median_spread is not None and range_median not in (None, Decimal(0)) else None
        p95_ratio = p95_spread / range_median if p95_spread is not None and range_median not in (None, Decimal(0)) else None
        hourly: dict[str, Any] = {}
        for hour in range(24):
            bucket = [row for row in rows if datetime.fromisoformat(row["timestamp"]).hour == hour]
            if len(bucket) < 50:
                continue
            bucket_spreads = [Decimal(str(row["spread"])) * point for row in bucket if row["spread"] is not None]
            bucket_ranges = [Decimal(str(row["high"])) - Decimal(str(row["low"])) for row in bucket]
            bucket_spread = _quantile(bucket_spreads, Decimal("0.50"))
            bucket_range = _quantile(bucket_ranges, Decimal("0.50"))
            hourly[str(hour)] = {"observation_count": len(bucket), "spread_price": _summary(bucket_spreads), "bar_range_price": _summary(bucket_ranges), "median_spread_to_median_range": _decimal(bucket_spread / bucket_range if bucket_spread is not None and bucket_range not in (None, Decimal(0)) else None)}
        expected_slots = _weekday_slots(actual_start, actual_end + __import__("datetime").timedelta(minutes={"M5": 5, "M15": 15, "H1": 60}[record.timeframe]), record.timeframe)
        coverage = Decimal(record.bar_count) / Decimal(expected_slots) if expected_slots else Decimal(0)
        label = classify_structural_viability(bar_count=record.bar_count, coverage_ratio=coverage, validation_errors=record.errors, unexpected_gaps=record.gap_counts.get("unexpected_gap", 0), median_ratio=median_ratio, p95_ratio=p95_ratio)
        base.update({"coverage": {"expected_weekday_slots": expected_slots, "coverage_ratio": _decimal(coverage)}, "spread_points": _summary(spreads), "spread_price": _summary(spread_price), "movement_price": {"absolute_close_to_close": _summary(close_moves), "bar_range": _summary(ranges), "atr_like_14_not_calculated": "not required for structural label"}, "cost_to_movement": {"median_spread_to_median_range": _decimal(median_ratio), "p95_spread_to_median_range": _decimal(p95_ratio), "median_spread_to_median_abs_close_move": _decimal(median_spread / close_move_median if median_spread is not None and close_move_median not in (None, Decimal(0)) else None), "median_range_to_median_spread": _decimal(range_median / median_spread if median_spread not in (None, Decimal(0)) and range_median is not None else None)}, "hourly_microstructure": hourly, "structural_label": label})
        report_cells.append(base)
    payload: dict[str, Any] = {"phase": "5G", "scope": "descriptive microstructure only; no strategy performance", "cells": report_cells}
    payload["report_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return payload
