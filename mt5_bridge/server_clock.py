"""Broker tick-clock normalization for FX Phase 0.

A real HFM Demo observation on 2026-09-03 showed ``symbol_info_tick().time``
about +3 hours ahead of the bridge's synchronized UTC clock, even though
MetaQuotes documents Python MT5 timestamps as UTC.  The bridge therefore
normalizes *live tick timestamps only* from empirical clock skew instead of
hardcoding HFM's current offset.

Important: this is deliberately NOT applied to historical bars.  The official
MT5 Python documentation says bar/tick history is UTC, and using today's live
server offset for older bars would be wrong across DST transitions.  Historical
time semantics must be validated independently before any correction is made.

Safety properties:
- no broker/timezone name or fixed +2/+3 offset is assumed;
- the first calibration is accepted only when the measured skew is within a
  plausible timezone range and very close to a 30-minute boundary;
- after calibration, ordinary stale ticks retain their corrected timestamp so
  the quote-freshness layer can reject them as stale;
- recalibration occurs only when the residual itself looks like a clean
  30-minute clock change (e.g. DST/server switch), never from arbitrary drift;
- ambiguous initial calibration fails closed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

HALF_HOUR_SECONDS = 1800
MAX_BROKER_OFFSET_SECONDS = 14 * 3600
CALIBRATION_RESIDUAL_TOLERANCE_SECONDS = 5.0


class ServerClockCalibrationError(Exception):
    """Raised when a raw live-tick timestamp cannot be normalized safely."""


@dataclass(frozen=True)
class _Calibration:
    offset: timedelta
    calibrated_at_bridge_utc: datetime


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ServerClockCalibrationError(f"{name} must be timezone-aware")


def _nearest_half_hour(seconds: float) -> int:
    # Avoid Python round()'s tie-to-even behavior. Exact ties are not expected
    # in live data, but deterministic half-away-from-zero is clearer here.
    if seconds >= 0:
        units = int((seconds + HALF_HOUR_SECONDS / 2) // HALF_HOUR_SECONDS)
    else:
        units = -int((abs(seconds) + HALF_HOUR_SECONDS / 2) // HALF_HOUR_SECONDS)
    return units * HALF_HOUR_SECONDS


class ServerClockOffset:
    """Thread-safe live broker-tick clock offset.

    ``offset`` is the duration to SUBTRACT from the raw MT5 live tick time to
    obtain bridge UTC.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calibration: _Calibration | None = None

    def to_utc(
        self,
        raw_tick_time_mislabeled_as_utc: datetime,
        bridge_now_utc: datetime | None = None,
    ) -> datetime:
        raw = raw_tick_time_mislabeled_as_utc
        now = bridge_now_utc if bridge_now_utc is not None else datetime.now(timezone.utc)
        _require_aware(raw, "raw tick timestamp")
        _require_aware(now, "bridge_now_utc")
        raw = raw.astimezone(timezone.utc)
        now = now.astimezone(timezone.utc)

        with self._lock:
            current = self._calibration
            if current is None:
                current = self._calibrate_initial(raw, now)
                self._calibration = current
                return raw - current.offset

            corrected = raw - current.offset
            residual = (corrected - now).total_seconds()

            # Normal latency/staleness is NOT a reason to recalibrate. The
            # quote-freshness layer needs to see the true stale timestamp.
            candidate_change = _nearest_half_hour(residual)
            candidate_residual = abs(residual - candidate_change)
            if (
                candidate_change != 0
                and candidate_residual <= CALIBRATION_RESIDUAL_TOLERANCE_SECONDS
            ):
                new_offset_seconds = current.offset.total_seconds() + candidate_change
                if abs(new_offset_seconds) > MAX_BROKER_OFFSET_SECONDS:
                    raise ServerClockCalibrationError(
                        "broker-server clock change would imply an implausible offset "
                        f"of {new_offset_seconds:.0f}s; refusing recalibration"
                    )
                current = _Calibration(
                    offset=timedelta(seconds=new_offset_seconds),
                    calibrated_at_bridge_utc=now,
                )
                self._calibration = current
                return raw - current.offset

            return corrected

    def _calibrate_initial(self, raw: datetime, now: datetime) -> _Calibration:
        measured = (raw - now).total_seconds()
        rounded = _nearest_half_hour(measured)
        residual = abs(measured - rounded)
        if abs(rounded) > MAX_BROKER_OFFSET_SECONDS:
            raise ServerClockCalibrationError(
                "cannot calibrate broker-server clock offset: measured offset "
                f"{measured:.3f}s exceeds the plausible +/-{MAX_BROKER_OFFSET_SECONDS}s range"
            )
        if residual > CALIBRATION_RESIDUAL_TOLERANCE_SECONDS:
            raise ServerClockCalibrationError(
                "cannot calibrate broker-server clock offset: measured offset "
                f"{measured:.3f}s is not within {CALIBRATION_RESIDUAL_TOLERANCE_SECONDS:.1f}s "
                f"of a 30-minute boundary (nearest {rounded}s); refusing to guess"
            )
        return _Calibration(offset=timedelta(seconds=rounded), calibrated_at_bridge_utc=now)

    def current_offset(self) -> timedelta | None:
        with self._lock:
            return self._calibration.offset if self._calibration is not None else None

    def reset(self) -> None:
        with self._lock:
            self._calibration = None
