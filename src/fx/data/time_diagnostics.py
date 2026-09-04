"""Empirical historical-timestamp diagnostics (Phase 5A, read-only).

Answers, for a real MT5/HFM connection, the questions Phase 5A's spec
requires before trusting `copy_rates_range`'s documented UTC contract
for this specific broker:

1. what timestamps does the bridge actually return for historical bars;
2. do they look like UTC (vs. a broker-local time mislabeled as UTC,
   the exact bug class `ServerClockOffset` was built to fix for LIVE
   ticks -- see that module's docstring);
3. does H4 bar alignment shift seasonally (a DST-shifted broker would
   produce H4 bars starting at different hour-of-day boundaries across
   a DST transition);
4. how does the weekend gap look (which weekday/hour the last
   pre-weekend bar and the first post-weekend bar fall on);
5. do any Sunday bars exist at all;
6. is there anything unusual around a rollover-like boundary.

This module NEVER places an order and never mutates `ServerClockOffset`
-- it only fetches historical bars via the existing read-only
`ExecutionClient.history()` and reports what it observed. It answers
questions; it does not decide policy.

Every finding here is empirical observation from actual bridge
responses -- if the bridge cannot be reached, `run_time_diagnostics`
propagates the underlying `ExecutionClientError` and the caller (see
`src/cli/fx_cli.py`) is expected to report the situation as
`PENDING EMPIRICAL VALIDATION` rather than fabricate a result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.execution.base import ExecutionClient, ExecutionTimeframe
from src.fx.data.mt5_provider import fetch_history
from src.fx.data.schema import FxBar


@dataclass(frozen=True)
class WeekendGapObservation:
    last_bar_before_weekend: FxBar | None
    first_bar_after_weekend: FxBar | None
    gap_duration: timedelta | None
    sunday_bars_found: int


@dataclass(frozen=True)
class H4AlignmentObservation:
    hours_of_day_seen: tuple[int, ...]
    """Distinct UTC hour-of-day values H4 bars started on, across the
    requested window. A broker with a stable UTC-aligned H4 grid
    produces a small, constant set (e.g. {0, 4, 8, 12, 16, 20}); a
    seasonally shifting grid would show a different set before/after a
    DST-like transition -- compare two windows straddling a known DST
    date to detect that, this single observation only reports what was
    seen in one window."""


@dataclass(frozen=True)
class TimeDiagnosticsReport:
    symbol: str
    timeframe: str
    requested_start_utc: datetime
    requested_end_utc: datetime
    bar_count: int
    first_bar_timestamp_utc: datetime | None
    last_bar_timestamp_utc: datetime | None
    weekend_gap: WeekendGapObservation | None
    h4_alignment: H4AlignmentObservation | None


def observe_weekend_gap(bars: tuple[FxBar, ...]) -> WeekendGapObservation:
    """Find the first Friday-to-(Sunday|Monday) gap in `bars` and report
    its exact boundary bars and duration, plus how many Sunday-timestamped
    bars exist in the whole sequence (expected to be 0 or very few for a
    market that is closed Saturday/most of Sunday)."""
    sunday_count = sum(1 for b in bars if b.timestamp_utc.weekday() == 6)

    last_before = None
    first_after = None
    for earlier, later in zip(bars, bars[1:]):
        if earlier.timestamp_utc.weekday() == 4 and later.timestamp_utc.weekday() in (6, 0):
            gap = later.timestamp_utc - earlier.timestamp_utc
            if gap >= timedelta(hours=20):
                last_before = earlier
                first_after = later
                break

    gap_duration = (first_after.timestamp_utc - last_before.timestamp_utc) if last_before and first_after else None
    return WeekendGapObservation(
        last_bar_before_weekend=last_before,
        first_bar_after_weekend=first_after,
        gap_duration=gap_duration,
        sunday_bars_found=sunday_count,
    )


def observe_h4_alignment(bars: tuple[FxBar, ...]) -> H4AlignmentObservation:
    hours = sorted({b.timestamp_utc.hour for b in bars})
    return H4AlignmentObservation(hours_of_day_seen=tuple(hours))


def run_time_diagnostics(
    client: ExecutionClient,
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: ExecutionTimeframe = ExecutionTimeframe.H1,
) -> TimeDiagnosticsReport:
    """Fetch `timeframe` bars for `symbol` over [start, end) and report
    weekend-gap and (for H4) alignment observations. Raises whatever
    `ExecutionClientError` subclass the underlying client raises if the
    bridge is unreachable/misconfigured -- this function does not catch
    or paper over that, so a caller can distinguish "bridge unreachable"
    from "bridge reachable but data looks odd"."""
    fetch = fetch_history(client, symbol, timeframe, start, end, fetch_symbol_metadata=False, fetch_account=False)
    bars = fetch.bars

    weekend_gap = observe_weekend_gap(bars) if bars else None
    h4_alignment = observe_h4_alignment(bars) if bars and timeframe == ExecutionTimeframe.H4 else None

    return TimeDiagnosticsReport(
        symbol=symbol,
        timeframe=timeframe.value,
        requested_start_utc=start.astimezone(timezone.utc),
        requested_end_utc=end.astimezone(timezone.utc),
        bar_count=len(bars),
        first_bar_timestamp_utc=bars[0].timestamp_utc if bars else None,
        last_bar_timestamp_utc=bars[-1].timestamp_utc if bars else None,
        weekend_gap=weekend_gap,
        h4_alignment=h4_alignment,
    )
