"""Minimal FX session/gap classification (Phase 5A).

FX does not trade 24/7 the way spot crypto does: the market closes for
the weekend and (per broker) around some holidays. This module gives
just enough session awareness to classify gaps in a historical dataset
honestly -- it is explicitly NOT a full trading-hours calendar (no
London/NY/Asia session boundaries, no holiday table). That is deferred
to a future research phase; see PHASE5A_STATUS.md.

## What this does NOT do

- It does not know about holidays (Christmas, New Year, etc.) -- an
  unexpected closure around a holiday will be classified as
  `UNEXPECTED_GAP`, not a special holiday category, because this phase
  has not built a holiday calendar and must not guess one.
- It does not assign a named trading session (London/NY/Asia) to each
  bar. That is a research-time concern, not a data-integrity concern,
  and is deferred.
- The weekend boundary used here (Friday close / Sunday open, in UTC)
  is a common approximation for FX; the EXACT broker weekend-close/open
  timestamps have not been empirically verified against the real
  bridge in this phase (see PHASE5A_STATUS.md's Empirical Findings
  section) -- treat `EXPECTED_WEEKEND` as `INFERRED`, not `VERIFIED`,
  until that validation runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class GapClassification(Enum):
    """Classification of the interval between two consecutive bars."""

    CONTIGUOUS = "contiguous"
    EXPECTED_WEEKEND = "expected_weekend"
    UNEXPECTED_GAP = "unexpected_gap"


@dataclass(frozen=True)
class GapReport:
    previous_timestamp_utc: datetime
    current_timestamp_utc: datetime
    expected_step: timedelta
    actual_step: timedelta
    classification: GapClassification


# Saturday=5, Sunday=6 in Python's `datetime.weekday()`. A gap that spans
# from Friday into the following Sunday/Monday (i.e. skips all of
# Saturday and includes part of Sunday) is treated as the expected FX
# weekend closure. This is intentionally simple: it looks at the
# weekday of the two bars on either side of the gap, not a broker-
# specific exact close/open time, because that exact time has not been
# empirically confirmed (see module docstring).
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


def is_expected_weekend_gap(previous_timestamp_utc: datetime, current_timestamp_utc: datetime) -> bool:
    """True if the gap between these two bars plausibly spans the FX
    weekend closure: the earlier bar falls on Friday and the later bar
    falls on Sunday or Monday, with the gap covering at least one full
    Saturday. Deliberately conservative -- a gap that starts before
    Friday or ends before Sunday is never classified as the weekend,
    even if it happens to be long, so a real mid-week outage cannot be
    mistaken for a weekend closure.
    """
    if previous_timestamp_utc.weekday() != _FRIDAY:
        return False
    if current_timestamp_utc.weekday() not in (_SUNDAY, 0):  # Sunday or Monday
        return False
    if (current_timestamp_utc - previous_timestamp_utc) < timedelta(hours=24):
        return False
    return True


def classify_gap(
    previous_timestamp_utc: datetime,
    current_timestamp_utc: datetime,
    expected_step: timedelta,
) -> GapReport:
    """Classify the interval between two consecutive bars.

    `expected_step` is the timeframe's nominal bar duration (e.g. 1 hour
    for H1). A step within a small tolerance of `expected_step` is
    `CONTIGUOUS`; a longer step that plausibly spans the FX weekend is
    `EXPECTED_WEEKEND`; anything else longer than expected is
    `UNEXPECTED_GAP` and must not be silently repaired.
    """
    actual_step = current_timestamp_utc - previous_timestamp_utc
    tolerance = expected_step * 0.01 if expected_step > timedelta(0) else timedelta(0)

    if actual_step <= expected_step + tolerance:
        classification = GapClassification.CONTIGUOUS
    elif is_expected_weekend_gap(previous_timestamp_utc, current_timestamp_utc):
        classification = GapClassification.EXPECTED_WEEKEND
    else:
        classification = GapClassification.UNEXPECTED_GAP

    return GapReport(
        previous_timestamp_utc=previous_timestamp_utc,
        current_timestamp_utc=current_timestamp_utc,
        expected_step=expected_step,
        actual_step=actual_step,
        classification=classification,
    )
