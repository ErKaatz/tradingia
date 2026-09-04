"""Deterministic normalization from bridge response types to the
canonical FX schema (Phase 5A).

The same input must always produce the same normalized output: same
sort order, same timezone representation, same numeric types, same
duplicate-handling policy. This module is the single place that
guarantee is implemented so `fingerprint.py` can rely on it.
"""

from __future__ import annotations

from datetime import timezone

from src.execution.base import AccountSummary, HistoryBar, SymbolMetadata

from src.fx.data.schema import FxBar, FxSymbolMetadata


def normalize_bar(bar: HistoryBar) -> FxBar:
    """Convert one bridge `HistoryBar` into a canonical `FxBar`.

    Timestamp normalization: `HistoryBar.timestamp` is already
    timezone-aware (enforced by `MT5RemoteExecutionClient`'s parsing --
    see `src/execution/mt5_remote.py::_parse_utc_timestamp`, which
    rejects naive timestamps and always converts to UTC). This function
    re-asserts UTC explicitly rather than trusting that invariant
    silently, so a future change to the upstream parser cannot let a
    non-UTC timestamp reach a dataset undetected.
    """
    timestamp_utc = bar.timestamp.astimezone(timezone.utc)
    return FxBar(
        timestamp_utc=timestamp_utc,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        tick_volume=bar.tick_volume,
        real_volume=bar.real_volume,
        spread_points=bar.spread_points,
    )


def normalize_bars(bars: tuple[HistoryBar, ...]) -> tuple[FxBar, ...]:
    """Normalize and deterministically sort a sequence of bars.

    Sort key is `timestamp_utc` ascending. Duplicate timestamps are NOT
    silently dropped here -- `validation.py` reports them as an error, so
    a caller who fixed the underlying provider issue can tell a
    duplicate-free dataset from one where duplicates were quietly
    discarded.
    """
    normalized = [normalize_bar(b) for b in bars]
    normalized.sort(key=lambda b: b.timestamp_utc)
    return tuple(normalized)


def normalize_symbol_metadata(
    requested_symbol: str,
    metadata: SymbolMetadata | None,
    account: AccountSummary | None = None,
    broker: str | None = None,
) -> FxSymbolMetadata:
    """Build canonical `FxSymbolMetadata` from what the bridge reported.

    `metadata` may be `None` if the bridge could not resolve the symbol
    at all -- callers should prefer to fail before reaching this point,
    but this function still produces a well-formed (mostly-null) record
    rather than raising, so a dataset can honestly record "we had no
    metadata for this symbol" instead of silently omitting the field.
    `account.server` (when available) is the source for `server`;
    `broker` is passed separately because no current bridge endpoint
    reports a broker *name* distinct from the account's `server` string
    -- see PHASE5A_STATUS.md's Symbol Metadata section.
    """
    server = account.server if account is not None else None
    if metadata is None:
        return FxSymbolMetadata(
            requested_symbol=requested_symbol,
            resolved_symbol=requested_symbol,
            description=None,
            digits=None,
            point=None,
            volume_min=None,
            volume_step=None,
            volume_max=None,
            contract_size=None,
            tick_size=None,
            tick_value=None,
            currency_base=None,
            currency_profit=None,
            currency_margin=None,
            broker=broker,
            server=server,
        )
    return FxSymbolMetadata(
        requested_symbol=requested_symbol,
        resolved_symbol=metadata.symbol,
        description=None,
        digits=metadata.digits,
        point=metadata.point,
        volume_min=metadata.volume_min,
        volume_step=metadata.volume_step,
        volume_max=metadata.volume_max,
        contract_size=metadata.contract_size,
        tick_size=metadata.tick_size,
        tick_value=metadata.tick_value,
        currency_base=metadata.currency_base,
        currency_profit=metadata.currency_profit,
        currency_margin=metadata.currency_margin,
        broker=broker,
        server=server,
    )
