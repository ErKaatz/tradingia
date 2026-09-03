"""`python -m src.cli mt5-remote ...` -- manual CLI for the FX Phase 0
bridge (Step 4).

`demo-open` goes through `SafeExecutionService` (policy-checked) and
ALWAYS uses the symbol's minimum volume -- there is no way to pass an
arbitrary volume from this CLI, by design (Step 4's frozen
minimum-volume-only sizing rule). It also requires `--confirm-demo-order`
so a typo/accidental invocation during development cannot place a real
(even if demo) order.

Every subcommand reads bridge connection info from `MT5_REMOTE_URL` and
`MT5_REMOTE_TOKEN` environment variables -- no bridge URL/token on the
command line, and nothing here ever prints the token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from decimal import Decimal

from src.execution.base import Side
from src.execution.mt5_remote import ExecutionClientError, MT5RemoteExecutionClient, RemoteConfig
from src.execution.policy import RealMoneyPolicy
from src.execution.quote_freshness import (
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
    QuoteFreshnessError,
    validate_quote_freshness,
)
from src.execution.safe_execution import SafeExecutionDeniedError, SafeExecutionQuoteFreshnessError, SafeExecutionService

DEFAULT_POLICY_CONFIG = "configs/real_money_policy.yaml"


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


def _build_policy(policy_path: str) -> RealMoneyPolicy:
    try:
        return RealMoneyPolicy.from_yaml(policy_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR loading policy config {policy_path!r}: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        health = client.health()
        terminal = client.terminal()
        account = client.account()
        kill_switch = client.kill_switch_status()
        reconciliation = client.reconciliation_status()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"bridge_alive:        {health.bridge_alive}")
    print(f"terminal_connected:  {health.terminal_connected}")
    print(f"terminal_trade_allowed: {terminal.trade_allowed}")
    print(f"api_version:         {health.api_version}")
    print(f"bridge_version:      {health.bridge_version}")
    print(f"bridge_build:        {health.bridge_build}")
    print(f"bridge_time_utc:     {health.bridge_time_utc.isoformat() if health.bridge_time_utc else None}")
    print(f"broker_name:         {health.broker_name}")
    print(f"account_trade_mode:  {account.trade_mode.value}")
    print(f"account_trade_allowed: {account.trade_allowed}")
    print(f"account_trade_expert:  {account.trade_expert}")
    print(f"account_currency:    {account.currency}")
    print(f"account_balance:     {account.balance}")
    print(f"kill_switch:         {kill_switch.status.value}")
    print(f"reconciliation:      {reconciliation.state.value}")


def cmd_preflight(args: argparse.Namespace) -> None:
    """READ-ONLY. Never places an order. Prints exactly the facts a
    human needs to check before authorizing a first demo order.
    """

    client = _build_client()
    symbol = args.symbol
    problems: list[str] = []
    try:
        health = client.health()
        if not health.terminal_connected:
            problems.append("terminal is NOT connected")
        terminal = client.terminal()
        if terminal.connected is not True:
            problems.append("terminal reports connected=False")
        if terminal.trade_allowed is not True:
            problems.append("MT5 AutoTrading is disabled in the client terminal; enable Algo Trading manually in MT5")
        account = client.account()
        if account.trade_allowed is not True:
            state = "unknown" if account.trade_allowed is None else "disabled"
            problems.append(f"account trading permission is {state}")
        if account.trade_expert is not True:
            state = "unknown" if account.trade_expert is None else "disabled"
            problems.append(f"account expert/algorithmic trading permission is {state}")
        if account.trade_mode.value != "demo":
            problems.append(f"account trade_mode is {account.trade_mode.value!r}, not 'demo'")
        kill_switch = client.kill_switch_status()
        if kill_switch.status.value == "active":
            problems.append("kill switch is ACTIVE")
        reconciliation = client.reconciliation_status()
        if reconciliation.state.value != "ok":
            problems.append(f"reconciliation state is {reconciliation.state.value!r}, not 'ok'")
        positions = client.positions()
        if positions:
            problems.append(f"{len(positions)} position(s) already open (expected 0)")
        try:
            symbol_metadata = client.symbol_metadata(symbol)
        except ExecutionClientError as exc:
            problems.append(f"could not fetch symbol metadata for {symbol!r}: {exc}")
            symbol_metadata = None
        try:
            quote = client.quote(symbol)
        except ExecutionClientError as exc:
            problems.append(f"could not fetch quote for {symbol!r}: {exc}")
            quote = None

        quote_age_seconds = None
        quote_future_skew_seconds = None
        if quote is not None:
            # Reuses the exact same validate_quote_freshness() helper (and
            # the same default thresholds) that SafeExecutionService's
            # safe_open() calls before placing an order -- see
            # src/execution/quote_freshness.py. This is what closes the
            # gap where preflight previously said OK using no temporal
            # check at all, while demo-open then failed immediately on
            # one: the two must always agree.
            try:
                result = validate_quote_freshness(
                    symbol=symbol,
                    quote_timestamp=quote.timestamp,
                    max_age_seconds=DEFAULT_MAX_QUOTE_AGE_SECONDS,
                    max_future_skew_seconds=DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
                )
                quote_age_seconds = result.age_seconds
                quote_future_skew_seconds = result.future_skew_seconds
            except QuoteFreshnessError as exc:
                problems.append(str(exc))
                quote_age_seconds = exc.age_seconds
                quote_future_skew_seconds = -exc.age_seconds if exc.reason == "future" else None
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"terminal_connected:  {health.terminal_connected}")
    print(f"terminal_trade_allowed: {terminal.trade_allowed}")
    print(f"account_trade_mode:  {account.trade_mode.value}")
    print(f"account_trade_allowed: {account.trade_allowed}")
    print(f"account_trade_expert:  {account.trade_expert}")
    print(f"kill_switch:         {kill_switch.status.value}")
    print(f"reconciliation:      {reconciliation.state.value}")
    print(f"open_positions:      {len(positions)}")
    if symbol_metadata is not None:
        print(f"{symbol}.volume_min: {symbol_metadata.volume_min}")
        print(f"{symbol}.trade_enabled(via /v1/symbols/{{symbol}}): see full metadata")
    if quote is not None:
        print(f"{symbol}.bid/ask:    {quote.bid} / {quote.ask}  (as of {quote.timestamp.isoformat()})")
        print(f"quote_age_seconds:   {quote_age_seconds:.3f}" if quote_age_seconds is not None else "quote_age_seconds:   unknown")
        if quote_future_skew_seconds:
            print(f"quote_future_skew_seconds: {quote_future_skew_seconds:.3f}")

    if problems:
        print()
        print("PREFLIGHT FAILED -- do not place a demo order:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print()
    print("PREFLIGHT OK.")


def cmd_positions(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        positions = client.positions()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    if not positions:
        print("(no open positions)")
        return
    for p in positions:
        print(f"position_id={p.position_id} symbol={p.symbol} side={p.side.value} volume={p.volume} open_price={p.open_price}")


def cmd_demo_open(args: argparse.Namespace) -> None:
    if not args.confirm_demo_order:
        print("ERROR: --confirm-demo-order is required to place a demo order.", file=sys.stderr)
        sys.exit(1)

    client = _build_client()
    policy = _build_policy(args.policy_config)
    service = SafeExecutionService(client=client, policy=policy)

    try:
        symbol_metadata = client.symbol_metadata(args.symbol)
    except ExecutionClientError as exc:
        print(f"ERROR: could not fetch symbol metadata: {exc}", file=sys.stderr)
        sys.exit(1)

    volume = symbol_metadata.volume_min  # frozen minimum-volume-only sizing; never a CLI-supplied volume
    side = Side.BUY if args.side == "buy" else Side.SELL
    client_order_id = str(uuid.uuid4())

    print(f"Placing DEMO {args.side.upper()} {args.symbol} volume={volume} client_order_id={client_order_id} ...")
    try:
        result = service.safe_open(client_order_id, args.symbol, side, volume)
    except SafeExecutionDeniedError as exc:
        print("DENIED by policy:", file=sys.stderr)
        for reason in exc.decision.reasons:
            print(f"  - {reason}", file=sys.stderr)
        sys.exit(1)
    except SafeExecutionQuoteFreshnessError as exc:
        print(f"DENIED: {exc}", file=sys.stderr)
        print("Run 'tia mt5 time-diagnostics <symbol>' to check for clock skew.", file=sys.stderr)
        sys.exit(1)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"status={result.status.value} position_id={result.position_id} fill_price={result.fill_price} slippage={result.slippage}")


def cmd_demo_close(args: argparse.Namespace) -> None:
    client = _build_client()
    policy = _build_policy(args.policy_config)
    service = SafeExecutionService(client=client, policy=policy)

    try:
        positions = client.positions()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    matching = [p for p in positions if p.position_id == args.position_id]
    if not matching:
        print(f"ERROR: position {args.position_id!r} not found among open positions.", file=sys.stderr)
        sys.exit(1)
    position = matching[0]
    # Closing side is the opposite of the position's own side.
    closing_side = Side.SELL if position.side == Side.BUY else Side.BUY
    client_order_id = str(uuid.uuid4())

    print(f"Closing DEMO position {args.position_id} ({position.symbol} {position.side.value} {position.volume}) client_order_id={client_order_id} ...")
    try:
        result = service.safe_close(client_order_id, args.position_id, position.symbol, closing_side, position.volume)
    except SafeExecutionDeniedError as exc:
        print("DENIED by policy:", file=sys.stderr)
        for reason in exc.decision.reasons:
            print(f"  - {reason}", file=sys.stderr)
        sys.exit(1)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"status={result.status.value} fill_price={result.fill_price} slippage={result.slippage}")


def cmd_kill_status(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        state = client.kill_switch_status()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"status={state.status.value} changed_at={state.changed_at} reason={state.reason}")


def cmd_kill_activate(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        state = client.activate_kill_switch(reason=args.reason)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"status={state.status.value} changed_at={state.changed_at}")


def cmd_kill_deactivate(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        state = client.deactivate_kill_switch()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"status={state.status.value} changed_at={state.changed_at}")


def cmd_reconcile(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        report = client.run_reconciliation()
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"state={report.state.value} checked_at={report.checked_at}")
    for detail in report.details:
        print(f"  - {detail}")


def cmd_resolve_received(args: argparse.Namespace) -> None:
    if not args.confirm_abort_before_submission:
        print(
            "REFUSED: resolving a RECEIVED attempt is an explicit operator action; "
            "re-run with --confirm-abort-before-submission",
            file=sys.stderr,
        )
        sys.exit(2)
    client = _build_client()
    try:
        report = client.resolve_received_attempt(args.client_order_id)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"resolved_received: {args.client_order_id}")
    print(f"reconciliation:    {report.state.value}")
    print(f"checked_at:        {report.checked_at}")
    for detail in report.details:
        print(f"  - {detail}")




def cmd_journal(args: argparse.Namespace) -> None:
    client = _build_client()
    try:
        entries = client.journal(limit=args.limit)
    except (ExecutionClientError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("(journal empty)")
        return

    for entry in entries:
        print(
            f"id={entry.entry_id} timestamp={entry.timestamp.isoformat()} "
            f"action={entry.action} request_id={entry.request_id} "
            f"client_order_id={entry.client_order_id}"
        )
        print("  " + json.dumps(dict(entry.payload), sort_keys=True, separators=(",", ":")))


def cmd_time_diagnostics(args: argparse.Namespace) -> None:
    """READ-ONLY. Never calls order_check/order_send/place_order/close_position.
    Shows the three clocks involved (this Linux process, the Windows
    bridge, and the requested symbol's own last tick) side by side, and
    every pairwise skew, so a human can tell clock/timezone skew apart
    from a code bug -- see FX Phase 0's "quote has a timestamp in the
    future" investigation.
    """

    client = _build_client()
    try:
        diag = client.time_diagnostics(args.symbol)
    except ExecutionClientError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"symbol:                      {diag.symbol}")
    print(f"linux_client_utc:            {diag.linux_client_utc.isoformat()}")
    print(f"bridge_utc:                  {diag.bridge_time_utc.isoformat()}")
    print(f"mt5_tick_utc:                {diag.mt5_tick_time_utc.isoformat() if diag.mt5_tick_time_utc else None}")
    print(f"bridge_client_skew_seconds:  {diag.bridge_client_skew_seconds:.3f}")
    print(f"tick_client_skew_seconds:    {diag.tick_client_skew_seconds:.3f}" if diag.tick_client_skew_seconds is not None else "tick_client_skew_seconds:    unknown (no tick)")
    print(f"tick_bridge_skew_seconds:    {diag.tick_bridge_skew_seconds:.3f}" if diag.tick_bridge_skew_seconds is not None else "tick_bridge_skew_seconds:    unknown (no tick)")
    print(f"quote_age_seconds (client):  {diag.quote_age_seconds_per_client:.3f}" if diag.quote_age_seconds_per_client is not None else "quote_age_seconds (client):  unknown (no tick)")
    print(f"quote_age_seconds (bridge):  {diag.quote_age_seconds_per_bridge:.3f}" if diag.quote_age_seconds_per_bridge is not None else "quote_age_seconds (bridge):  unknown (no tick)")
    print(f"server_clock_offset_seconds: {diag.server_clock_offset_seconds:.1f}" if diag.server_clock_offset_seconds is not None else "server_clock_offset_seconds: not yet calibrated")
    print()
    print("Positive skew means the second clock named is AHEAD of the first.")
    print("A skew of many minutes/hours (not sub-second) points to a clock or")
    print("timezone conversion problem, not ordinary latency -- see")
    print("docs/CLI_SETUP.md's troubleshooting section for what to run next.")


def add_mt5_remote_subparser(subparsers) -> None:
    p = subparsers.add_parser("mt5-remote", help="FX Phase 0: talk to the Windows mt5_bridge")
    sub = p.add_subparsers(dest="mt5_remote_command", required=True)

    p_status = sub.add_parser("status", help="Read-only bridge/account/kill-switch/reconciliation status")
    p_status.set_defaults(func=cmd_status)

    p_preflight = sub.add_parser("preflight", help="Read-only checks before placing any demo order")
    p_preflight.add_argument("symbol")
    p_preflight.set_defaults(func=cmd_preflight)

    p_positions = sub.add_parser("positions", help="List open positions")
    p_positions.set_defaults(func=cmd_positions)

    p_open = sub.add_parser("demo-open", help="Place ONE minimum-volume DEMO market order (policy-checked)")
    p_open.add_argument("symbol")
    p_open.add_argument("side", choices=["buy", "sell"])
    p_open.add_argument("--confirm-demo-order", action="store_true", help="Required safety flag; without it the command refuses to run")
    p_open.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    p_open.set_defaults(func=cmd_demo_open)

    p_close = sub.add_parser("demo-close", help="Fully close one open DEMO position by id")
    p_close.add_argument("position_id")
    p_close.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    p_close.set_defaults(func=cmd_demo_close)

    p_kill_status = sub.add_parser("kill-status", help="Show kill switch state")
    p_kill_status.set_defaults(func=cmd_kill_status)

    p_kill_activate = sub.add_parser("kill-activate", help="Activate the kill switch")
    p_kill_activate.add_argument("--reason", default=None)
    p_kill_activate.set_defaults(func=cmd_kill_activate)

    p_kill_deactivate = sub.add_parser("kill-deactivate", help="Deactivate the kill switch")
    p_kill_deactivate.set_defaults(func=cmd_kill_deactivate)

    p_reconcile = sub.add_parser("reconcile", help="Run reconciliation now")
    p_reconcile.set_defaults(func=cmd_reconcile)

    p_resolve_received = sub.add_parser(
        "resolve-received",
        help="Resolve one provably pre-submission RECEIVED idempotency row (never SUBMITTED)",
    )
    p_resolve_received.add_argument("client_order_id")
    p_resolve_received.add_argument(
        "--confirm-abort-before-submission",
        action="store_true",
        help="Required explicit acknowledgement; the bridge still independently verifies safety",
    )
    p_resolve_received.set_defaults(func=cmd_resolve_received)


    p_journal = sub.add_parser("journal", help="READ-ONLY: show recent append-only execution journal entries")
    p_journal.add_argument("--limit", type=int, default=20, choices=range(1, 1001), metavar="N")
    p_journal.set_defaults(func=cmd_journal)

    p_time_diag = sub.add_parser("time-diagnostics", help="READ-ONLY: compare Linux/bridge/MT5-tick clocks for a symbol")
    p_time_diag.add_argument("symbol")
    p_time_diag.set_defaults(func=cmd_time_diagnostics)
