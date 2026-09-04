"""FX-aware structural and temporal validation (Phase 5A).

Structural checks (non-empty, required fields, monotonic timestamps, no
duplicates, positive prices, valid OHLC relationships, non-negative
volumes) are analogous to `src/data/validation.py`'s generic OHLCV
checks, but this module is written against `FxBar` (Decimal fields,
`tick_volume`/`real_volume` kept distinct) rather than a pandas
DataFrame with a generic `volume` column, and it never rejects
`real_volume is None` -- routine for FX OTC symbols.

Temporal checks add FX-aware gap classification (`sessions.py`) instead
of the generic engine's binary "any gap is an error" rule: an expected
weekend closure must not be flagged the same way as a genuinely missing
bar in the middle of a trading week.

This module NEVER repairs data. No forward-fill, no interpolation, no
synthetic bars, no duplicated closes. A gap is reported, never patched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from src.fx.data.schema import FxBar, FxTimeframe
from src.fx.data.sessions import GapClassification, classify_gap

# Nominal bar duration per timeframe. Matches the bridge's own supported
# set (`ExecutionTimeframe`) -- adding a timeframe here without it also
# being supported end-to-end would be a silent gap in this table, so
# every `FxTimeframe` member has an entry.
TIMEFRAME_TO_TIMEDELTA: dict[FxTimeframe, timedelta] = {
    FxTimeframe.M1: timedelta(minutes=1),
    FxTimeframe.M5: timedelta(minutes=5),
    FxTimeframe.M15: timedelta(minutes=15),
    FxTimeframe.M30: timedelta(minutes=30),
    FxTimeframe.H1: timedelta(hours=1),
    FxTimeframe.H4: timedelta(hours=4),
    FxTimeframe.D1: timedelta(days=1),
}


@dataclass
class FxValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gap_counts: dict[GapClassification, int] = field(default_factory=dict)
    unexpected_gap_examples: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise ValueError(
                "FX dataset validation failed with the following errors:\n"
                + "\n".join(f"  - {e}" for e in self.errors)
            )


def validate_fx_bars(
    bars: tuple[FxBar, ...],
    timeframe: FxTimeframe,
    max_gap_examples: int = 10,
) -> FxValidationResult:
    """Validate structural and temporal integrity of a normalized FX bar
    sequence. `bars` is assumed already normalize.py-normalized (i.e.
    each `FxBar` already passed its own `__post_init__` invariants); this
    function focuses on sequence-level properties `__post_init__` cannot
    see: emptiness, ordering, duplicates, and gaps.
    """
    result = FxValidationResult()

    if len(bars) == 0:
        result.errors.append("dataset is empty")
        return result

    seen_timestamps: set = set()
    duplicate_count = 0
    non_increasing_count = 0
    for earlier, later in zip(bars, bars[1:]):
        if later.timestamp_utc <= earlier.timestamp_utc:
            non_increasing_count += 1
            if later.timestamp_utc == earlier.timestamp_utc:
                duplicate_count += 1

    if non_increasing_count > 0:
        result.errors.append(
            f"timestamps are not strictly increasing: {non_increasing_count} "
            f"non-increasing step(s) found ({duplicate_count} exact duplicate(s))"
        )
        # Gap classification requires strictly increasing timestamps to be
        # meaningful; bail out rather than report misleading gap counts.
        return result

    expected_step = TIMEFRAME_TO_TIMEDELTA[timeframe]
    gap_counts: dict[GapClassification, int] = {c: 0 for c in GapClassification}
    for earlier, later in zip(bars, bars[1:]):
        report = classify_gap(earlier.timestamp_utc, later.timestamp_utc, expected_step)
        gap_counts[report.classification] += 1
        if report.classification == GapClassification.UNEXPECTED_GAP and len(result.unexpected_gap_examples) < max_gap_examples:
            result.unexpected_gap_examples.append(
                f"unexpected gap between {report.previous_timestamp_utc} and "
                f"{report.current_timestamp_utc} (expected step {report.expected_step}, "
                f"actual {report.actual_step})"
            )
    result.gap_counts = gap_counts

    if gap_counts[GapClassification.UNEXPECTED_GAP] > 0:
        result.warnings.append(
            f"{gap_counts[GapClassification.UNEXPECTED_GAP]} unexpected gap(s) detected "
            "(not repaired -- gaps are data, see module docstring)"
        )

    return result
