"""Read-only MT5 historical bar provider (Phase 5A).

Fetches historical bars via the existing `ExecutionClient.history()`
contract (already implemented in `src/execution/mt5_remote.py` and
`mt5_bridge/app.py`'s `GET /v1/history/{symbol}`, backed by
`RealMT5Backend.copy_rates_range`) -- this module adds no new HTTP
endpoint and duplicates no transport/parsing logic. It only:

1. validates its own inputs before calling the client (symbol shape,
   timeframe, `start < end`);
2. calls `history()`, `symbol_metadata()`, and `account()` -- all
   already-existing read-only client methods;
3. converts the response into the canonical FX schema via
   `normalize.py`.

It never places an order, never touches `/v1/demo/...`, and never
imports or calls anything under `mt5_bridge/trading.py`.

## Timestamp handling -- do not reuse `ServerClockOffset` here

`mt5_bridge/backend.py::RealMT5Backend.copy_rates_range` deliberately
does NOT apply the live-tick `ServerClockOffset` correction to
historical bars (see that module's own comment, and
PHASE5A_STATUS.md's Time Handling section) -- MetaQuotes documents
`copy_rates_range` timestamps as already UTC, and applying today's live
skew to older bars could silently corrupt them across a DST boundary.
This provider does not re-apply any correction either; it trusts the
bridge's already-normalized `timestamp` field as-is. Whether that
documented UTC contract holds exactly for this broker/server has NOT
been empirically re-verified in Phase 5A (see
`time_diagnostics.py` and PHASE5A_STATUS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.execution.base import (
    AccountSummary,
    ExecutionClient,
    ExecutionTimeframe,
    HistoryRequest,
    SymbolMetadata,
)
from src.fx.data.dataset import FxDatasetMetadata, build_dataset_metadata
from src.fx.data.normalize import normalize_bars, normalize_symbol_metadata
from src.fx.data.schema import FxBar


class FxProviderError(Exception):
    """Base class for errors raised by this module specifically (as
    opposed to `ExecutionClientError` subclasses raised by the
    underlying `ExecutionClient`, which are allowed to propagate
    unchanged so callers can distinguish a transport/protocol problem
    from an input-validation problem)."""


def _validate_symbol(symbol: str) -> str:
    if not symbol or not symbol.strip():
        raise FxProviderError("symbol must not be empty")
    return symbol


def _validate_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise FxProviderError("start/end must be timezone-aware")
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    if start_utc >= end_utc:
        raise FxProviderError(f"start ({start_utc}) must be strictly before end ({end_utc})")
    return start_utc, end_utc


@dataclass(frozen=True)
class FxHistoricalFetch:
    """Result of one historical fetch: normalized bars plus everything
    needed to build dataset metadata and a fingerprint."""

    bars: tuple[FxBar, ...]
    timeframe: ExecutionTimeframe
    requested_symbol: str
    requested_start_utc: datetime
    requested_end_utc: datetime
    symbol_metadata_raw: SymbolMetadata | None
    account: AccountSummary | None
    bridge_build: str | None


def fetch_history(
    client: ExecutionClient,
    symbol: str,
    timeframe: ExecutionTimeframe,
    start: datetime,
    end: datetime,
    fetch_symbol_metadata: bool = True,
    fetch_account: bool = True,
) -> FxHistoricalFetch:
    """Fetch and normalize historical bars for one symbol/timeframe/range.

    Read-only: calls only `client.history()` and, optionally,
    `client.symbol_metadata()` / `client.account()` (both already
    read-only methods this client has supported since Step 2/Step
    3-era work). Never calls `place_order`/`close_position`.

    An empty response (zero bars) is not an error -- it is returned as
    an `FxHistoricalFetch` with `bars == ()`; the caller decides whether
    that is acceptable (see `validation.py`'s "dataset is empty" error
    if it later tries to persist an empty dataset).
    """
    symbol = _validate_symbol(symbol)
    start_utc, end_utc = _validate_range(start, end)

    request = HistoryRequest(symbol=symbol, timeframe=timeframe, start=start_utc, end=end_utc)
    result = client.history(request)
    bars = normalize_bars(result.bars)

    symbol_metadata_raw: SymbolMetadata | None = None
    if fetch_symbol_metadata:
        try:
            symbol_metadata_raw = client.symbol_metadata(symbol)
        except Exception:
            # Metadata is enrichment, not a precondition for having bars.
            # A bridge that cannot resolve symbol metadata for a name it
            # just returned history for is unusual but not fatal here --
            # normalize_symbol_metadata handles `None` explicitly.
            symbol_metadata_raw = None

    account: AccountSummary | None = None
    bridge_build: str | None = None
    if fetch_account:
        try:
            account = client.account()
        except Exception:
            account = None
    try:
        bridge_build = client.health().bridge_build
    except Exception:
        bridge_build = None

    return FxHistoricalFetch(
        bars=bars,
        timeframe=timeframe,
        requested_symbol=symbol,
        requested_start_utc=start_utc,
        requested_end_utc=end_utc,
        symbol_metadata_raw=symbol_metadata_raw,
        account=account,
        bridge_build=bridge_build,
    )


def build_metadata_for_fetch(fetch: FxHistoricalFetch) -> FxDatasetMetadata:
    symbol_metadata = normalize_symbol_metadata(
        requested_symbol=fetch.requested_symbol,
        metadata=fetch.symbol_metadata_raw,
        account=fetch.account,
        broker=None,  # no bridge endpoint currently reports a broker name distinct from `server`
    )
    return build_dataset_metadata(
        bars=fetch.bars,
        timeframe=fetch.timeframe,
        symbol_metadata=symbol_metadata,
        requested_start_utc=fetch.requested_start_utc,
        requested_end_utc=fetch.requested_end_utc,
        bridge_build=fetch.bridge_build,
    )
