"""FX historical-data CLI (Phase 5A).

Read-only. No command here places, checks, or modifies any order, and
none of them touch `/v1/demo/...`. Every command talks to the bridge
only through `src/fx/data/mt5_provider.py` and
`src/fx/data/time_diagnostics.py`, which in turn only call the
already-existing read-only `ExecutionClient` methods
(`history`/`symbol_metadata`/`account`/`health`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from src.execution.base import ExecutionTimeframe
from src.execution.mt5_remote import ExecutionClientError, MT5RemoteExecutionClient, RemoteConfig
from src.fx.data.mt5_provider import FxProviderError, build_metadata_for_fetch, fetch_history
from src.fx.data.storage import DEFAULT_FX_DATA_ROOT, load_bars_dataframe, load_metadata, save_dataset
from src.fx.data.time_diagnostics import run_time_diagnostics
from src.fx.data.validation import validate_fx_bars


def _build_client() -> MT5RemoteExecutionClient:
    bridge_url = os.environ.get("MT5_REMOTE_URL")
    if not bridge_url:
        print("ERROR: MT5_REMOTE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    try:
        config = RemoteConfig.from_env(bridge_url=bridge_url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    return MT5RemoteExecutionClient(config)


def _parse_timeframe(value: str) -> ExecutionTimeframe:
    try:
        return ExecutionTimeframe(value)
    except ValueError:
        valid = ", ".join(t.value for t in ExecutionTimeframe)
        print(f"ERROR: invalid timeframe {value!r}. Valid values: {valid}", file=sys.stderr)
        sys.exit(1)


def _parse_utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        print(f"ERROR: invalid ISO-8601 datetime {value!r} (e.g. 2026-01-01T00:00:00+00:00)", file=sys.stderr)
        sys.exit(1)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cmd_fx_history_fetch(args: argparse.Namespace) -> None:
    client = _build_client()
    timeframe = _parse_timeframe(args.timeframe)
    start = _parse_utc_datetime(args.start)
    end = _parse_utc_datetime(args.end)

    try:
        fetch = fetch_history(client, args.symbol, timeframe, start, end)
    except (ExecutionClientError, FxProviderError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    metadata = build_metadata_for_fetch(fetch)
    validation = validate_fx_bars(fetch.bars, timeframe)

    print(f"Fetched {metadata.bar_count} bars for {metadata.resolved_symbol} {metadata.timeframe}")
    print(f"Requested range: {metadata.requested_start_utc} -> {metadata.requested_end_utc}")
    print(f"Actual range:    {metadata.actual_start_utc} -> {metadata.actual_end_utc}")
    print(f"volume_kind: {metadata.volume_kind}")
    print(f"dataset_sha256: {metadata.dataset_sha256}")
    if not validation.is_valid:
        print("VALIDATION ERRORS:", file=sys.stderr)
        for error in validation.errors:
            print(f"  - {error}", file=sys.stderr)
    for warning in validation.warnings:
        print(f"warning: {warning}")

    if args.save:
        out_dir = save_dataset(fetch.bars, metadata, root=args.data_root)
        print(f"Saved to {out_dir}")


def cmd_fx_metadata(args: argparse.Namespace) -> None:
    try:
        metadata = load_metadata(args.symbol, args.timeframe, root=args.data_root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(metadata.to_json_dict(), indent=2, sort_keys=True))


def cmd_fx_fingerprint(args: argparse.Namespace) -> None:
    try:
        metadata = load_metadata(args.symbol, args.timeframe, root=args.data_root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(metadata.dataset_sha256)


def cmd_fx_validate(args: argparse.Namespace) -> None:
    from decimal import Decimal, InvalidOperation

    from src.fx.data.schema import FxBar

    try:
        metadata = load_metadata(args.symbol, args.timeframe, root=args.data_root)
        df = load_bars_dataframe(args.symbol, args.timeframe, root=args.data_root)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    timeframe = _parse_timeframe(metadata.timeframe)
    bars = []
    for row in df.itertuples(index=False):
        try:
            real_volume = Decimal(row.real_volume) if row.real_volume is not None else None
        except InvalidOperation:
            real_volume = None
        bars.append(
            FxBar(
                timestamp_utc=row.timestamp_utc.to_pydatetime().astimezone(timezone.utc)
                if hasattr(row.timestamp_utc, "to_pydatetime")
                else row.timestamp_utc,
                open=Decimal(row.open),
                high=Decimal(row.high),
                low=Decimal(row.low),
                close=Decimal(row.close),
                tick_volume=Decimal(row.tick_volume),
                real_volume=real_volume,
                spread_points=int(row.spread_points) if row.spread_points is not None else None,
            )
        )
    result = validate_fx_bars(tuple(bars), timeframe)
    print(f"is_valid: {result.is_valid}")
    print(f"gap_counts: {[(k.value, v) for k, v in result.gap_counts.items()]}")
    for error in result.errors:
        print(f"ERROR: {error}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for example in result.unexpected_gap_examples:
        print(f"  {example}")
    if not result.is_valid:
        sys.exit(1)


def cmd_fx_time_diagnostics(args: argparse.Namespace) -> None:
    client = _build_client()
    timeframe = _parse_timeframe(args.timeframe)
    start = _parse_utc_datetime(args.start)
    end = _parse_utc_datetime(args.end)

    try:
        report = run_time_diagnostics(client, args.symbol, start, end, timeframe=timeframe)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"symbol: {report.symbol}  timeframe: {report.timeframe}")
    print(f"requested range: {report.requested_start_utc} -> {report.requested_end_utc}")
    print(f"bar_count: {report.bar_count}")
    print(f"first_bar_timestamp_utc: {report.first_bar_timestamp_utc}")
    print(f"last_bar_timestamp_utc: {report.last_bar_timestamp_utc}")
    if report.weekend_gap is not None:
        wg = report.weekend_gap
        print(f"weekend_gap: last_before={wg.last_bar_before_weekend and wg.last_bar_before_weekend.timestamp_utc}")
        print(f"             first_after={wg.first_bar_after_weekend and wg.first_bar_after_weekend.timestamp_utc}")
        print(f"             duration={wg.gap_duration}")
        print(f"             sunday_bars_found={wg.sunday_bars_found}")
    if report.h4_alignment is not None:
        print(f"h4_hours_of_day_seen: {report.h4_alignment.hours_of_day_seen}")


def add_fx_subparser(subparsers) -> None:
    p_fx = subparsers.add_parser("fx-history", help="Read-only FX historical data (Phase 5A)")
    fx_sub = p_fx.add_subparsers(dest="fx_command", required=True)

    p_fetch = fx_sub.add_parser("fetch", help="Fetch historical bars from the bridge, validate, optionally save")
    p_fetch.add_argument("symbol")
    p_fetch.add_argument("--timeframe", required=True, help="M1|M5|M15|M30|H1|H4|D1")
    p_fetch.add_argument("--start", required=True, help="ISO-8601 UTC datetime")
    p_fetch.add_argument("--end", required=True, help="ISO-8601 UTC datetime")
    p_fetch.add_argument("--save", action="store_true", help="Persist the dataset under --data-root")
    p_fetch.add_argument("--data-root", default=DEFAULT_FX_DATA_ROOT, help="Root directory for saved datasets")
    p_fetch.set_defaults(func=cmd_fx_history_fetch)

    p_metadata = fx_sub.add_parser("metadata", help="Print a saved dataset's metadata")
    p_metadata.add_argument("symbol")
    p_metadata.add_argument("--timeframe", required=True)
    p_metadata.add_argument("--data-root", default=DEFAULT_FX_DATA_ROOT)
    p_metadata.set_defaults(func=cmd_fx_metadata)

    p_fingerprint = fx_sub.add_parser("fingerprint", help="Print a saved dataset's fingerprint")
    p_fingerprint.add_argument("symbol")
    p_fingerprint.add_argument("--timeframe", required=True)
    p_fingerprint.add_argument("--data-root", default=DEFAULT_FX_DATA_ROOT)
    p_fingerprint.set_defaults(func=cmd_fx_fingerprint)

    p_validate = fx_sub.add_parser("validate", help="Re-validate a saved dataset (structural + gap report)")
    p_validate.add_argument("symbol")
    p_validate.add_argument("--timeframe", required=True)
    p_validate.add_argument("--data-root", default=DEFAULT_FX_DATA_ROOT)
    p_validate.set_defaults(func=cmd_fx_validate)

    p_time_diag = fx_sub.add_parser("time-diagnostics", help="Empirical timestamp/weekend-gap diagnostics against the real bridge")
    p_time_diag.add_argument("symbol")
    p_time_diag.add_argument("--timeframe", default="H1")
    p_time_diag.add_argument("--start", required=True, help="ISO-8601 UTC datetime")
    p_time_diag.add_argument("--end", required=True, help="ISO-8601 UTC datetime")
    p_time_diag.set_defaults(func=cmd_fx_time_diagnostics)
