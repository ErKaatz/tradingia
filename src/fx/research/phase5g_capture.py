"""Read-only, block-wise historical capture for the Phase 5G availability audit.

This module intentionally stops at availability and integrity evidence.  It
does not calculate spreads, ranges, labels, signals, PnL, or any strategy
output.  The Windows bridge token stays on the VM: SSH runs a PowerShell GET
there and only the resulting historical JSON crosses the SSH channel.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

from src.fx.data.schema import FxBar, FxTimeframe
from src.fx.data.validation import validate_fx_bars


PHASE5G_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")
PHASE5G_TIMEFRAMES = ("M5", "M15", "H1")
PHASE5G_REQUESTED_START = datetime(2022, 9, 1, tzinfo=timezone.utc)
PHASE5G_LATEST_END_EXCLUSIVE = datetime(2025, 8, 30, tzinfo=timezone.utc)
_CHUNK_DAYS = {"M5": 60, "M15": 180, "H1": 365}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AvailabilityRecord:
    symbol: str
    timeframe: str
    requested_start_utc: str
    requested_end_exclusive_utc: str
    actual_first_bar_utc: str | None
    actual_last_bar_utc: str | None
    bar_count: int
    gap_counts: dict[str, int]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    fingerprint_sha256: str
    raw_capture_sha256: str
    chunks_requested: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def chunk_ranges(start: datetime, end_exclusive: datetime, timeframe: str) -> tuple[tuple[datetime, datetime], ...]:
    """Return contiguous, end-exclusive ranges below the bridge bar cap."""
    if timeframe not in _CHUNK_DAYS:
        raise ValueError(f"unsupported Phase 5G timeframe: {timeframe}")
    if start.tzinfo is None or end_exclusive.tzinfo is None or start >= end_exclusive:
        raise ValueError("invalid requested range")
    result = []
    cursor = start.astimezone(timezone.utc)
    final = end_exclusive.astimezone(timezone.utc)
    while cursor < final:
        next_cursor = min(cursor + timedelta(days=_CHUNK_DAYS[timeframe]), final)
        result.append((cursor, next_cursor))
        cursor = next_cursor
    return tuple(result)


def _parse_bar(row: dict[str, object]) -> FxBar:
    timestamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    real_volume = row.get("real_volume")
    spread = row.get("spread")
    return FxBar(
        timestamp_utc=timestamp,
        open=Decimal(str(row["open"])), high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])), close=Decimal(str(row["close"])),
        tick_volume=Decimal(str(row["tick_volume"])),
        real_volume=Decimal(str(real_volume)) if real_volume is not None else None,
        spread_points=int(spread) if spread is not None else None,
    )


def _remote_history_json(ssh_host: str, identity_file: Path, symbol: str, timeframe: str, start: datetime, end: datetime) -> bytes:
    query = urlencode({"start": _iso(start), "end": _iso(end), "timeframe": timeframe})
    uri = f"http://192.168.100.195:8765/v1/history/{symbol}?{query}"
    # The token is deliberately expanded on Windows, never locally or in logs.
    command = (
        "powershell -NoProfile -Command "
        "\"$h=@{Authorization=('Bearer '+$env:MT5_BRIDGE_TOKEN)}; "
        f"Invoke-RestMethod -Headers $h -Uri '{uri}' | ConvertTo-Json -Depth 6 -Compress\""
    )
    completed = subprocess.run(
        ["ssh", "-i", str(identity_file), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", ssh_host, command],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return completed.stdout


def capture_cell(
    *, ssh_host: str, identity_file: Path, symbol: str, timeframe: str,
    start: datetime = PHASE5G_REQUESTED_START, end_exclusive: datetime = PHASE5G_LATEST_END_EXCLUSIVE,
    output_root: Path = Path("data/fx/research/phase5g_availability"),
) -> AvailabilityRecord:
    """Capture one cell through read-only GET calls and write raw evidence locally."""
    ranges = chunk_ranges(start, end_exclusive, timeframe)
    raw_chunks: list[bytes] = []
    parsed: dict[datetime, FxBar] = {}
    errors: list[str] = []
    for chunk_start, chunk_end in ranges:
        try:
            raw = _remote_history_json(ssh_host, identity_file, symbol, timeframe, chunk_start, chunk_end)
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
                raise ValueError("bridge response has no bars list")
            raw_chunks.append(raw)
            for row in payload["bars"]:
                bar = _parse_bar(row)
                if start <= bar.timestamp_utc < end_exclusive:
                    parsed[bar.timestamp_utc] = bar
        except Exception as exc:  # preserve partial capture honestly for the availability ledger
            errors.append(f"{_iso(chunk_start)}..{_iso(chunk_end)}: {type(exc).__name__}: {exc}")
    bars = tuple(parsed[timestamp] for timestamp in sorted(parsed))
    validation = validate_fx_bars(bars, FxTimeframe(timeframe))
    raw_capture = b"\n".join(raw_chunks)
    canonical_bars = [
        {"timestamp": _iso(b.timestamp_utc), "open": str(b.open), "high": str(b.high), "low": str(b.low), "close": str(b.close),
         "tick_volume": str(b.tick_volume), "real_volume": str(b.real_volume) if b.real_volume is not None else None, "spread": b.spread_points}
        for b in bars
    ]
    record = AvailabilityRecord(
        symbol=symbol, timeframe=timeframe, requested_start_utc=_iso(start), requested_end_exclusive_utc=_iso(end_exclusive),
        actual_first_bar_utc=_iso(bars[0].timestamp_utc) if bars else None,
        actual_last_bar_utc=_iso(bars[-1].timestamp_utc) if bars else None,
        bar_count=len(bars), gap_counts={key.value: value for key, value in validation.gap_counts.items()},
        warnings=tuple(validation.warnings), errors=tuple([*validation.errors, *errors]),
        fingerprint_sha256=_sha256_json({"symbol": symbol, "timeframe": timeframe, "bars": canonical_bars}),
        raw_capture_sha256=hashlib.sha256(raw_capture).hexdigest(), chunks_requested=len(ranges),
    )
    destination = output_root / symbol / timeframe
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "availability.json").write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n")
    (destination / "bars.json").write_text(json.dumps(canonical_bars, separators=(",", ":")) + "\n")
    return record


def write_availability_ledger(records: Iterable[AvailabilityRecord], output_root: Path = Path("data/fx/research/phase5g_availability")) -> Path:
    ordered = sorted((record.to_dict() for record in records), key=lambda row: (str(row["symbol"]), str(row["timeframe"])))
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / "availability_ledger.json"
    destination.write_text(json.dumps({"phase": "5G", "scope": "availability-only", "cells": ordered, "ledger_sha256": _sha256_json(ordered)}, indent=2, sort_keys=True) + "\n")
    return destination
