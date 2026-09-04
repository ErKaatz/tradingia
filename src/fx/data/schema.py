"""Canonical FX historical-bar schema (Phase 5A).

This module defines the one shape every FX historical bar takes once it
has left the bridge/provider boundary, independent of MT5's own wire
format. Nothing here talks to MT5, HTTP, or a file -- see
`mt5_provider.py` (fetching) and `normalize.py` (converting a raw
`HistoryBar` into `FxBar`).

## Timeframe representation

The bridge and `src/execution/base.py` already define a canonical,
closed timeframe enum (`ExecutionTimeframe`: M1/M5/M15/M30/H1/H4/D1).
This module reuses that enum rather than inventing a second one --
duplicating it would create exactly the "1h vs H1 vs 60 vs TIMEFRAME_H1"
silent-mismatch risk this phase is required to avoid.

## Volume semantics

`FxBar.tick_volume` is MT5's per-bar tick count -- how many price
updates occurred, NOT how many units of currency were traded. It is
never called `volume` here or anywhere downstream, because that name
would imply real traded volume, which FX OTC brokers routinely do not
report. `real_volume` is broker-reported traded volume when available;
`None` is an expected, common, non-error value for FX symbols -- never
treated as a data-quality problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from src.execution.base import ExecutionTimeframe

# Re-exported so `src/fx/data` callers use one canonical timeframe type
# without needing to know it is defined in `src.execution.base`.
FxTimeframe = ExecutionTimeframe


class VolumeKind(Enum):
    """What a dataset's volume-shaped numbers actually represent.

    Exists so a dataset's metadata can honestly declare
    `volume_kind: tick_volume` rather than a bare, ambiguous `volume`
    column whose meaning has to be guessed or assumed.
    """

    TICK_VOLUME = "tick_volume"
    REAL_VOLUME = "real_volume"


@dataclass(frozen=True)
class FxBar:
    """One canonical, normalized FX historical bar.

    `timestamp_utc` is always timezone-aware UTC (see `normalize.py` and
    `PHASE5A_STATUS.md`'s Time Handling section for the exact contract
    and what remains empirically unverified about it).
    """

    timestamp_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: Decimal
    real_volume: Decimal | None
    spread_points: int | None

    def __post_init__(self) -> None:
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("FxBar.timestamp_utc must be timezone-aware")
        if self.timestamp_utc.utcoffset() != timezone.utc.utcoffset(None):
            raise ValueError("FxBar.timestamp_utc must be normalized to UTC")
        for name, value in [("open", self.open), ("high", self.high), ("low", self.low), ("close", self.close)]:
            if value <= 0:
                raise ValueError(f"FxBar.{name} must be positive, got {value}")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("FxBar.high must be >= max(open, close, low)")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("FxBar.low must be <= min(open, close, high)")
        if self.tick_volume < 0:
            raise ValueError(f"FxBar.tick_volume must be non-negative, got {self.tick_volume}")
        if self.real_volume is not None and self.real_volume < 0:
            raise ValueError(f"FxBar.real_volume must be non-negative, got {self.real_volume}")
        if self.spread_points is not None and self.spread_points < 0:
            raise ValueError(f"FxBar.spread_points must be non-negative, got {self.spread_points}")


@dataclass(frozen=True)
class FxSymbolMetadata:
    """Broker-reported trading constraints for one FX symbol, captured at
    dataset-creation time. All fields are optional except `symbol` and
    `resolved_symbol`, because not every bridge/backend reports every
    field -- a missing field stays `None`, never guessed or defaulted
    from a "typical" value for the instrument (e.g. never assume
    `contract_size == 100000` because that's common for FX majors).
    """

    requested_symbol: str
    resolved_symbol: str
    description: str | None
    digits: int | None
    point: Decimal | None
    volume_min: Decimal | None
    volume_step: Decimal | None
    volume_max: Decimal | None
    contract_size: Decimal | None
    tick_size: Decimal | None
    tick_value: Decimal | None
    currency_base: str | None
    currency_profit: str | None
    currency_margin: str | None
    broker: str | None
    server: str | None
