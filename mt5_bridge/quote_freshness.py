"""Quote freshness/future-skew validation, shared by the bridge's
server-side write path (`trading.py`) and its read-only diagnostics
(`app.py`'s `/v1/time-diagnostics` endpoint), so the two never drift
apart -- the exact bug this module fixes (see FX Phase 0 "quote has a
timestamp in the future" investigation) was partly caused by ad hoc
freshness logic living inline in `trading.py` with no equivalent
elsewhere to cross-check it against.

This module NEVER trusts the Linux client's clock -- it only ever
compares a quote's timestamp against `datetime.now(timezone.utc)` taken
on THIS machine (the Windows VM running the bridge), because it is the
bridge, not the Linux CLI, that ultimately calls `order_send`. See
`src/execution/quote_freshness.py` for the Linux-side equivalent used
by `preflight`/`SafeExecutionService` -- the two are independent
implementations of the same semantics (same field names, same
threshold meaning), not a shared import, because `mt5_bridge/` must
have zero dependency on `src/` (see FX_PHASE0_STATUS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


class QuoteFreshnessError(Exception):
    """Raised when a quote is stale or has an untrustworthy future
    timestamp. Carries every field needed for a useful, secret-free
    diagnostic message -- see `__str__`."""

    def __init__(
        self,
        *,
        reason: str,
        symbol: str,
        quote_timestamp: datetime,
        now_utc: datetime,
        age_seconds: float,
        max_age_seconds: float,
        max_future_skew_seconds: float,
    ) -> None:
        self.reason = reason
        self.symbol = symbol
        self.quote_timestamp = quote_timestamp
        self.now_utc = now_utc
        self.age_seconds = age_seconds
        self.max_age_seconds = max_age_seconds
        self.max_future_skew_seconds = max_future_skew_seconds
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.reason == "future":
            skew = -self.age_seconds
            return (
                f"quote for {self.symbol!r} timestamp is {skew:.3f}s in the future "
                f"(quote_timestamp={self.quote_timestamp.isoformat()}, "
                f"now_utc={self.now_utc.isoformat()}, "
                f"allowed_future_skew_seconds={self.max_future_skew_seconds:.3f})"
            )
        return (
            f"quote for {self.symbol!r} is {self.age_seconds:.3f}s old, exceeding "
            f"max_quote_age_seconds={self.max_age_seconds:.3f} "
            f"(quote_timestamp={self.quote_timestamp.isoformat()}, now_utc={self.now_utc.isoformat()})"
        )


@dataclass(frozen=True)
class QuoteFreshnessResult:
    """Successful validation result -- carries the same measurements a
    caller would want to log/display even when nothing is wrong."""

    age_seconds: float
    future_skew_seconds: float


def validate_quote_freshness(
    *,
    symbol: str,
    quote_timestamp: datetime,
    now_utc: datetime | None = None,
    max_age_seconds: float,
    max_future_skew_seconds: float,
) -> QuoteFreshnessResult:
    """Validates a quote's timestamp against the caller's own clock.

    Fails closed on ambiguity: a naive (timezone-unaware) `quote_timestamp`
    is rejected outright rather than assumed to be UTC or local -- silently
    guessing here is exactly the class of bug that caused the original
    "timestamp in the future" incident (a value from a different clock
    domain was labeled UTC without conversion).

    `max_future_skew_seconds` exists to tolerate real, small clock/latency
    skew between the machine generating the quote and the machine checking
    it -- NOT to paper over a systematically wrong timestamp (e.g. a
    multi-hour broker-server-time-labeled-as-UTC bug). If skew is
    consistently on the order of minutes or hours, that is a conversion
    bug to fix at the source, not a tolerance to raise.
    """

    if quote_timestamp.tzinfo is None:
        raise QuoteFreshnessError(
            reason="naive_timestamp",
            symbol=symbol,
            quote_timestamp=quote_timestamp,
            now_utc=now_utc if now_utc is not None else datetime.now(timezone.utc),
            age_seconds=float("nan"),
            max_age_seconds=max_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
        )

    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    quote_timestamp_utc = quote_timestamp.astimezone(timezone.utc)
    age_seconds = (now - quote_timestamp_utc).total_seconds()
    future_skew_seconds = -age_seconds if age_seconds < 0 else 0.0

    if age_seconds < -max_future_skew_seconds:
        raise QuoteFreshnessError(
            reason="future",
            symbol=symbol,
            quote_timestamp=quote_timestamp_utc,
            now_utc=now,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
        )
    if age_seconds > max_age_seconds:
        raise QuoteFreshnessError(
            reason="stale",
            symbol=symbol,
            quote_timestamp=quote_timestamp_utc,
            now_utc=now,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            max_future_skew_seconds=max_future_skew_seconds,
        )

    return QuoteFreshnessResult(age_seconds=age_seconds, future_skew_seconds=future_skew_seconds)
