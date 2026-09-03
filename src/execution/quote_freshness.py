"""Quote freshness/future-skew validation -- Linux-side (FX Phase 0).

Shared by `mt5_remote_cli.py`'s `preflight` and by
`SafeExecutionService`, so the two never validate the same quote by two
different rules again (see FX Phase 0's "preflight said OK, demo-open
immediately failed on a timestamp check" incident -- the two call sites
had never shared this logic before).

This is an independent implementation of
`mt5_bridge.quote_freshness` (same field names, same semantics), not a
shared import: `mt5_bridge/` is deployed standalone to the Windows VM and
must have zero dependency on `src/`, and this Linux-side module is not
copied there. The two are kept in sync by convention, the same way
`mt5_bridge/reconciliation.py`'s `ReconciliationState` mirrors
`src.execution.base.ReconciliationState`.

IMPORTANT: this client-side check exists only as an early, friendlier
warning (fail fast before even calling the bridge, and give
`preflight`/`safe_open` a consistent answer). It is NOT the authoritative
safety check -- `mt5_bridge/trading.py`'s own server-side call to this
same logic, using the bridge's own clock, is what actually gates
`order_send`. A Linux clock that is wrong must never be able to let an
order through; it can only ever make this client-side check reject
something the bridge would have allowed (never the reverse), because the
bridge re-validates independently against its own clock regardless of
what Linux decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Mirrors mt5_bridge/config.py's DEFAULT_MAX_QUOTE_AGE_SECONDS /
# DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS -- kept in sync by convention (see
# module docstring on why this isn't a shared import). Used only as this
# module's own default for callers (`preflight`, `SafeExecutionService`)
# that don't have a bridge-reported threshold to use instead; the bridge's
# own server-side check is always the authoritative one regardless of what
# default is used here.
DEFAULT_MAX_QUOTE_AGE_SECONDS = 5.0
DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS = 1.0


class QuoteFreshnessError(Exception):
    """Same shape as `mt5_bridge.quote_freshness.QuoteFreshnessError` --
    carries every field needed for a useful, secret-free diagnostic
    message."""

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
    """See `mt5_bridge.quote_freshness.validate_quote_freshness` -- same
    semantics, deliberately duplicated rather than imported (see module
    docstring)."""

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
