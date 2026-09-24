"""CLI commands for the safe no-trade operational runtime."""

from __future__ import annotations

import json
import sys

from src.cli.mt5_remote_cli import DEFAULT_POLICY_CONFIG, _build_client, _build_policy
from src.runtime.demo_execution_test import DemoExecutionProbe, DemoExecutionTestConfig, DemoExecutionTestError, DemoExecutionTestState
from src.runtime.operational import JsonlDecisionJournal, OperationalRuntime, RuntimeConfig


def _runtime() -> OperationalRuntime:
    try:
        config = RuntimeConfig.from_env()
    except ValueError as exc:
        print(f"CONFIGURATION ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    return OperationalRuntime(client=_build_client(), config=config)


def _print(result) -> None:
    print(json.dumps({
        "timestamp_utc": result.timestamp_utc,
        "runtime_mode": result.mode,
        "symbol": result.symbol,
        "connectivity": result.connectivity,
        "market_state": result.market_state,
        "strategy": result.strategy_id,
        "decision": result.decision,
        "reason": result.reason,
        "execution_allowed": result.execution_allowed,
        "execution_denial_reason": result.execution_denial_reason,
        "preflight": "PASS" if result.preflight_passed else "FAIL",
        "quote_age_seconds": result.quote_age_seconds,
        "checks": result.checks,
    }, sort_keys=True, indent=2))


def cmd_runtime_status(args) -> None:
    runtime = _runtime()
    last = JsonlDecisionJournal(runtime.config.journal_path).last()
    heartbeat = None
    if runtime.heartbeat_path.exists():
        heartbeat = json.loads(runtime.heartbeat_path.read_text(encoding="utf-8"))
    test_state = DemoExecutionTestState(runtime.config.journal_path.parent / "demo_execution_test.json").load()
    payload = {
        "runtime_mode": runtime.config.mode.value, "symbol": runtime.config.symbol,
        "strategy_authorization": runtime.config.strategy_id, "demo_authorization": "NONE", "live_authorization": "NONE",
        "test_execution_authorization": test_state.get("test_authorization", test_state.get("state", "NONE")) if test_state else "NONE",
        "active_test_run_id": test_state.get("test_run_id") if test_state and test_state.get("state") not in {"CLOSED", "EXPIRED"} else "NONE",
        "executor": "NOOP_EXECUTOR", "journal": str(runtime.config.journal_path), "last_cycle": last, "heartbeat": heartbeat,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return
    print(f"runtime_mode: {runtime.config.mode.value}")
    print(f"symbol: {runtime.config.symbol}")
    print(f"strategy_authorization: {runtime.config.strategy_id}")
    print("demo_authorization: NONE")
    print("live_authorization: NONE")
    print(f"test_execution_authorization: {test_state.get('test_authorization', test_state.get('state', 'NONE')) if test_state else 'NONE'}")
    print(f"active_test_run_id: {test_state.get('test_run_id') if test_state and test_state.get('state') not in {'CLOSED', 'EXPIRED'} else 'NONE'}")
    print("executor: NOOP_EXECUTOR")
    print(f"journal: {runtime.config.journal_path}")
    print("last_cycle:")
    print(json.dumps(last, sort_keys=True, indent=2) if last else "  none")


def cmd_doctor(args) -> None:
    result = _runtime().run_cycle()
    _print(result)
    print("PRE-FLIGHT PASS" if result.preflight_passed else "PRE-FLIGHT FAIL")
    if not result.preflight_passed:
        raise SystemExit(1)


def cmd_dry_run(args) -> None:
    result = _runtime().run_cycle()
    _print(result)
    print("DRY-RUN COMPLETE — NOOP_EXECUTOR — 0 ORDERS")


def cmd_start(args) -> None:
    runtime = _runtime()
    if args.once:
        result = runtime.run_cycle()
        _print(result)
        return
    print("TradingIA runtime started in safe no-trade mode. Press Ctrl+C to stop.")
    try:
        runtime.run_forever()
    except KeyboardInterrupt:
        runtime.request_stop()
    print("TradingIA runtime stopped safely; no broker position was closed.")


def cmd_demo_execution_test(args) -> None:
    if not args.confirm_demo_execution_test:
        print("REFUSED: --confirm-demo-execution-test is required.", file=sys.stderr)
        raise SystemExit(2)
    try:
        config = DemoExecutionTestConfig.from_env(side=args.side)
        probe = DemoExecutionProbe(_build_client(), _build_policy(args.policy_config), config)
        print("DEMO ACCOUNT VERIFIED (pre-flight pending)")
        print("LIVE DISABLED")
        print("TEST_ONLY EXECUTION — ONE OPEN/CLOSE CYCLE")
        result = probe.run()
    except (DemoExecutionTestError, ValueError) as exc:
        print(f"DEMO EXECUTION TEST REFUSED/INCOMPLETE: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps({"test_run_id": result.get("test_run_id"), "state": result.get("state"), "test_authorization": result.get("test_authorization"), "pnl": "NOT EVALUATED — EXECUTION TEST ONLY"}, sort_keys=True))


def add_runtime_subparser(subparsers) -> None:
    parser = subparsers.add_parser("runtime", help="Safe no-strategy operational runtime")
    commands = parser.add_subparsers(dest="runtime_command", required=True)
    status = commands.add_parser("status", help="Show local runtime status and last journaled cycle")
    status.add_argument("--json", action="store_true", help="Emit strict JSON")
    status.set_defaults(func=cmd_runtime_status)
    doctor = commands.add_parser("doctor", help="Run read-only pre-flight; non-zero on critical failure")
    doctor.set_defaults(func=cmd_doctor)
    dry = commands.add_parser("dry-run", help="Run one full read-only cycle through NoopExecutor")
    dry.set_defaults(func=cmd_dry_run)
    start = commands.add_parser("start", help="Run the continuous read-only operational loop")
    start.add_argument("--once", action="store_true", help="Run exactly one cycle and exit")
    start.set_defaults(func=cmd_start)
    probe = commands.add_parser("demo-execution-test", help="Single-use TEST_ONLY DEMO open/close plumbing validation")
    probe.add_argument("--side", choices=["buy", "sell"], required=True, help="Explicit fixture direction; never market logic")
    probe.add_argument("--confirm-demo-execution-test", action="store_true", help="Required explicit authorization")
    probe.add_argument("--policy-config", default=DEFAULT_POLICY_CONFIG)
    probe.set_defaults(func=cmd_demo_execution_test)
