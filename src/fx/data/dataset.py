"""FX dataset metadata and deterministic fingerprinting (Phase 5A).

A dataset's identity (its fingerprint) must depend only on its
deterministic content: timestamps, OHLC, tick_volume, real_volume,
spread, symbol, timeframe, and the normalization/schema semantics that
produced it. It must NOT depend on operational metadata such as
`created_at_utc`, local file path, or JSON key order -- two runs that
fetched the same underlying data at different times must produce the
same fingerprint, or the fingerprint is useless for detecting real
content drift.

`hashlib.sha256` is used directly (never Python's built-in `hash()`,
which is salted per-process and not stable across runs/machines).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.fx.data.schema import FxBar, FxSymbolMetadata, FxTimeframe

SCHEMA_VERSION = "1.0.0"
NORMALIZATION_VERSION = "1.0.0"


def _bar_to_canonical_dict(bar: FxBar) -> dict[str, Any]:
    """One bar's deterministic (fingerprint-relevant) fields as JSON-safe
    primitives. Decimal is serialized via `str()` (never `float()`,
    which can silently change the value's exact decimal representation).
    """
    return {
        "timestamp_utc": bar.timestamp_utc.astimezone(timezone.utc).isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "tick_volume": str(bar.tick_volume),
        "real_volume": str(bar.real_volume) if bar.real_volume is not None else None,
        "spread_points": bar.spread_points,
    }


def _symbol_metadata_to_canonical_dict(metadata: FxSymbolMetadata) -> dict[str, Any]:
    def _dec(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    return {
        "requested_symbol": metadata.requested_symbol,
        "resolved_symbol": metadata.resolved_symbol,
        "digits": metadata.digits,
        "point": _dec(metadata.point),
        "volume_min": _dec(metadata.volume_min),
        "volume_step": _dec(metadata.volume_step),
        "volume_max": _dec(metadata.volume_max),
        "contract_size": _dec(metadata.contract_size),
        "tick_size": _dec(metadata.tick_size),
        "tick_value": _dec(metadata.tick_value),
        "currency_base": metadata.currency_base,
        "currency_profit": metadata.currency_profit,
        "currency_margin": metadata.currency_margin,
    }


def compute_dataset_fingerprint(
    bars: tuple[FxBar, ...],
    timeframe: FxTimeframe,
    symbol_metadata: FxSymbolMetadata,
) -> str:
    """SHA-256 hex digest over exactly the deterministic identity of this
    dataset: schema/normalization version, timeframe, symbol metadata
    (excluding broker/server -- see note below), and every bar's
    canonical fields, in a fixed, explicit JSON serialization
    (`sort_keys=True`, `separators=(",", ":")` for a byte-stable
    encoding independent of dict insertion order or whitespace).

    `broker`/`server` are deliberately excluded from the fingerprint:
    they identify *which account* fetched the data, not what the data
    *is* -- the same EURUSD H1 bars fetched from two different demo
    accounts on the same broker should fingerprint identically.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "timeframe": timeframe.value,
        "symbol_metadata": _symbol_metadata_to_canonical_dict(symbol_metadata),
        "bars": [_bar_to_canonical_dict(b) for b in bars],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FxDatasetMetadata:
    """Structured metadata persisted alongside every FX historical
    dataset. Fields are split into two groups, per Phase 5A's explicit
    requirement:

    Deterministic (part of the dataset's identity/fingerprint):
    `schema_version`, `normalization_version`, `source`,
    `requested_symbol`, `resolved_symbol`, `timeframe`,
    `requested_start_utc`, `requested_end_utc`, `actual_start_utc`,
    `actual_end_utc`, `bar_count`, `volume_kind`, `symbol_metadata`,
    `dataset_sha256`.

    Operational (must NOT alter the dataset's identity):
    `created_at_utc`, `bridge_build`, `broker`, `server` -- these
    describe *how and when* this copy was fetched, not what the
    normalized content *is*. Two fetches of the same underlying bars at
    different times, or from different demo accounts on the same
    broker, must produce the same `dataset_sha256` despite these fields
    differing.
    """

    schema_version: str
    normalization_version: str
    source: str
    broker: str | None
    server: str | None
    requested_symbol: str
    resolved_symbol: str
    timeframe: str
    requested_start_utc: str
    requested_end_utc: str
    actual_start_utc: str | None
    actual_end_utc: str | None
    bar_count: int
    volume_kind: str
    symbol_metadata: dict[str, Any]
    dataset_sha256: str
    created_at_utc: str
    bridge_build: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_dataset_metadata(
    bars: tuple[FxBar, ...],
    timeframe: FxTimeframe,
    symbol_metadata: FxSymbolMetadata,
    requested_start_utc: datetime,
    requested_end_utc: datetime,
    source: str = "mt5_bridge",
    bridge_build: str | None = None,
    now_utc: datetime | None = None,
) -> FxDatasetMetadata:
    """Assemble `FxDatasetMetadata` for a fetched-and-normalized dataset.

    `volume_kind` is always recorded as `tick_volume` in Phase 5A: MT5's
    `copy_rates_range` always returns tick_volume, and `real_volume` is
    frequently `None`/0 for FX OTC symbols (not an error -- see
    `schema.py`). A dataset that later gains verified real traded volume
    for its symbol could record `real_volume` here instead, but no such
    verification exists yet.
    """
    fingerprint = compute_dataset_fingerprint(bars, timeframe, symbol_metadata)
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    return FxDatasetMetadata(
        schema_version=SCHEMA_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        source=source,
        broker=symbol_metadata.broker,
        server=symbol_metadata.server,
        requested_symbol=symbol_metadata.requested_symbol,
        resolved_symbol=symbol_metadata.resolved_symbol,
        timeframe=timeframe.value,
        requested_start_utc=requested_start_utc.astimezone(timezone.utc).isoformat(),
        requested_end_utc=requested_end_utc.astimezone(timezone.utc).isoformat(),
        actual_start_utc=bars[0].timestamp_utc.astimezone(timezone.utc).isoformat() if bars else None,
        actual_end_utc=bars[-1].timestamp_utc.astimezone(timezone.utc).isoformat() if bars else None,
        bar_count=len(bars),
        volume_kind="tick_volume",
        symbol_metadata=_symbol_metadata_to_canonical_dict(symbol_metadata),
        dataset_sha256=fingerprint,
        created_at_utc=now.isoformat(),
        bridge_build=bridge_build,
    )
