"""Safe no-trade operational runtime for TradingIA.

The runtime is deliberately an observer: Phase 5 has zero authorized
strategies, so no runtime path owns a trading executor or can reach an MT5
write method. It turns read-only bridge state into a durable decision journal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import fcntl
import signal
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

from src.execution.quote_freshness import (
    DEFAULT_MAX_QUOTE_AGE_SECONDS,
    DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
    QuoteFreshnessError,
    validate_quote_freshness,
)

logger = logging.getLogger(__name__)


class RuntimeMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    RESEARCH = "RESEARCH"
    DEMO = "DEMO"
    LIVE = "LIVE"


class ConnectivityState(str, Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    RECOVERING = "RECOVERING"


class DecisionReason(str, Enum):
    NO_AUTHORIZED_STRATEGY = "NO_AUTHORIZED_STRATEGY"
    MARKET_CLOSED = "MARKET_CLOSED"
    QUOTE_STALE = "QUOTE_STALE"
    BRIDGE_UNAVAILABLE = "BRIDGE_UNAVAILABLE"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    UNKNOWN_BROKER_POSITION = "UNKNOWN_BROKER_POSITION"
    MODE_READ_ONLY = "MODE_READ_ONLY"
    LIVE_DISABLED = "LIVE_DISABLED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"


class ReadOnlyClient(Protocol):
    def health(self): ...
    def terminal(self): ...
    def account(self): ...
    def symbol_metadata(self, symbol: str): ...
    def quote(self, symbol: str): ...
    def positions(self): ...
    def orders(self): ...
    def kill_switch_status(self): ...
    def reconciliation_status(self): ...


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RuntimeMode
    symbol: str
    strategy_id: str
    journal_path: Path
    max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS
    max_quote_future_skew_seconds: float = DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS
    cycle_seconds: float = 30.0
    max_backoff_seconds: float = 300.0
    journal_max_bytes: int = 10 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        raw_mode = os.environ.get("TRADINGIA_MODE", RuntimeMode.READ_ONLY.value).upper()
        try:
            mode = RuntimeMode(raw_mode)
        except ValueError as exc:
            raise ValueError(f"TRADINGIA_MODE must be one of: {', '.join(m.value for m in RuntimeMode)}") from exc
        strategy_id = os.environ.get("TRADINGIA_STRATEGY", "NONE").strip() or "NONE"
        # No strategy registry is consulted: Phase 5 closeout authorizes NONE only.
        if strategy_id != "NONE":
            raise ValueError("TRADINGIA_STRATEGY must be NONE while Phase 5 research is closed")
        journal = Path(os.environ.get(
            "TRADINGIA_RUNTIME_JOURNAL",
            str(Path.home() / ".local" / "state" / "tradingia" / "runtime_journal.jsonl"),
        ))
        symbol = os.environ.get("TRADINGIA_SYMBOL", "EURUSD").strip()
        if not symbol:
            raise ValueError("TRADINGIA_SYMBOL must not be empty")
        try:
            cycle_seconds = float(os.environ.get("TRADINGIA_CYCLE_SECONDS", "30"))
        except ValueError as exc:
            raise ValueError("TRADINGIA_CYCLE_SECONDS must be numeric") from exc
        if cycle_seconds <= 0:
            raise ValueError("TRADINGIA_CYCLE_SECONDS must be > 0")
        return cls(mode=mode, symbol=symbol, strategy_id=strategy_id, journal_path=journal, cycle_seconds=cycle_seconds)


@dataclass(frozen=True)
class CycleResult:
    timestamp_utc: str
    mode: str
    symbol: str
    connectivity: str
    market_state: str
    strategy_id: str
    decision: str
    reason: str
    execution_allowed: bool
    execution_denial_reason: str
    preflight_passed: bool
    checks: dict[str, str]
    account_identity: str | None = None
    quote_age_seconds: float | None = None


class JsonlDecisionJournal:
    """Append-only local journal; never records tokens or raw account IDs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, result: CycleResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size >= 10 * 1024 * 1024:
            rotated = self.path.with_name(self.path.name + ".1")
            if rotated.exists():
                rotated.unlink()
            self.path.replace(rotated)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def last(self) -> dict | None:
        if not self.path.exists():
            return None
        with self.path.open(encoding="utf-8") as handle:
            lines = handle.readlines()
        return json.loads(lines[-1]) if lines else None


class RuntimeLock:
    """Advisory non-blocking process lock; never kills another runtime."""
    def __init__(self, path: Path) -> None:
        self.path, self.handle = path, None
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            raise RuntimeError("runtime already active for this state directory") from exc
        self.handle.seek(0); self.handle.truncate(); self.handle.write(str(os.getpid())); self.handle.flush()
        return self
    def __exit__(self, *_args):
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN); self.handle.close()


class NoopExecutor:
    """A capability boundary for READ_ONLY and dry-run operation.

    It intentionally exposes no order-placement method. A runtime using it
    cannot accidentally invoke the remote client's write API.
    """

    name = "NOOP_EXECUTOR"


class OperationalRuntime:
    def __init__(self, client: ReadOnlyClient, config: RuntimeConfig, journal: JsonlDecisionJournal | None = None) -> None:
        self.client = client
        self.config = config
        self.journal = journal or JsonlDecisionJournal(config.journal_path)
        self.executor = NoopExecutor()
        self._stop_requested = False
        self._cycle_count = 0
        self._started_at = datetime.now(timezone.utc)

    @property
    def heartbeat_path(self) -> Path:
        return self.config.journal_path.with_name("runtime_heartbeat.json")

    def _heartbeat(self, result: CycleResult, duration_seconds: float) -> None:
        usage = shutil.disk_usage(self.config.journal_path.parent if self.config.journal_path.parent.exists() else Path.home())
        payload = {"started_at_utc": self._started_at.isoformat(), "last_heartbeat_utc": datetime.now(timezone.utc).isoformat(),
                   "cycle_count": self._cycle_count, "last_cycle": asdict(result), "cycle_duration_seconds": duration_seconds,
                   "filesystem_free_bytes": usage.free, "health_state": "HEALTHY" if result.preflight_passed else "DEGRADED"}
        temp = self.heartbeat_path.with_suffix(".tmp"); temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8"); os.replace(temp, self.heartbeat_path)

    def request_stop(self, *_unused) -> None:
        self._stop_requested = True

    @staticmethod
    def _account_identity(account) -> str:
        raw = f"{account.account_id}|{account.server or ''}|{account.currency}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def cycle(self) -> CycleResult:
        now = datetime.now(timezone.utc)
        checks: dict[str, str] = {"config": "PASS", "strategy_authorization": "NONE"}
        reasons: list[DecisionReason] = []
        connectivity = ConnectivityState.CONNECTED
        market_state = "OPEN"
        account_identity = None
        quote_age = None

        if self.config.mode is RuntimeMode.LIVE:
            checks["live_hard_block"] = "PASS: LIVE_DISABLED"
            reasons.append(DecisionReason.LIVE_DISABLED)
        else:
            checks["live_hard_block"] = "PASS"

        try:
            health = self.client.health()
            checks["bridge"] = "PASS" if health.bridge_alive else "FAIL"
            checks["mt5"] = "PASS" if health.terminal_connected else "FAIL"
            if not health.bridge_alive or not health.terminal_connected:
                reasons.append(DecisionReason.BRIDGE_UNAVAILABLE)
                connectivity = ConnectivityState.DISCONNECTED

            terminal = self.client.terminal()
            checks["terminal"] = "PASS" if terminal.connected else "FAIL"
            if not terminal.connected:
                reasons.append(DecisionReason.BRIDGE_UNAVAILABLE)
                connectivity = ConnectivityState.DISCONNECTED

            account = self.client.account()
            account_identity = self._account_identity(account)
            checks["account"] = "PASS" if account.trade_mode.value == "demo" else f"FAIL:{account.trade_mode.value}"
            if account.trade_mode.value != "demo":
                reasons.append(DecisionReason.PREFLIGHT_FAILED)

            metadata = self.client.symbol_metadata(self.config.symbol)
            checks["symbol_metadata"] = "PASS" if metadata.volume_min > 0 and metadata.point > 0 else "FAIL"
            kill = self.client.kill_switch_status()
            checks["kill_switch"] = kill.status.value.upper()
            if kill.status.value == "active":
                reasons.append(DecisionReason.KILL_SWITCH_ACTIVE)

            reconciliation = self.client.reconciliation_status()
            checks["reconciliation"] = reconciliation.state.value.upper()
            if reconciliation.state.value != "ok":
                reasons.append(DecisionReason.RECONCILIATION_FAILED)

            positions = tuple(self.client.positions())
            orders = tuple(self.client.orders())
            checks["positions"] = "PASS:0" if not positions else f"FAIL:{len(positions)}"
            checks["orders"] = "PASS:0" if not orders else f"FAIL:{len(orders)}"
            if positions or orders:
                reasons.append(DecisionReason.UNKNOWN_BROKER_POSITION)

            try:
                quote = self.client.quote(self.config.symbol)
                fresh = validate_quote_freshness(
                    symbol=self.config.symbol,
                    quote_timestamp=quote.timestamp,
                    now_utc=now,
                    max_age_seconds=self.config.max_quote_age_seconds,
                    max_future_skew_seconds=self.config.max_quote_future_skew_seconds,
                )
                quote_age = fresh.age_seconds
                checks["quote"] = "PASS"
            except QuoteFreshnessError:
                checks["quote"] = "FAIL:STALE"
                reasons.append(DecisionReason.QUOTE_STALE)
                connectivity = ConnectivityState.STALE
            except Exception:
                # Weekend closure is expected; no stale quote is reused.
                if now.weekday() >= 5:
                    checks["quote"] = "EXPECTED_MARKET_CLOSED"
                    market_state = "EXPECTED_MARKET_CLOSED"
                    reasons.append(DecisionReason.MARKET_CLOSED)
                    connectivity = ConnectivityState.DEGRADED
                else:
                    logger.exception("quote check failed outside expected weekend closure")
                    checks["quote"] = "FAIL:UNAVAILABLE"
                    reasons.append(DecisionReason.BRIDGE_UNAVAILABLE)
                    connectivity = ConnectivityState.DEGRADED
        except Exception:
            logger.exception("bridge/account/reconciliation check failed")
            checks["bridge"] = "FAIL:UNAVAILABLE"
            reasons.append(DecisionReason.BRIDGE_UNAVAILABLE)
            connectivity = ConnectivityState.DISCONNECTED

        # Phase 5P's permanent operational default: a complete observer cycle
        # always decides NO_ACTION; strategy absence is the primary reason when
        # preflight is otherwise healthy.
        if not reasons:
            reasons.append(DecisionReason.NO_AUTHORIZED_STRATEGY)
        elif DecisionReason.NO_AUTHORIZED_STRATEGY not in reasons:
            # Strategy is still absent, but retain the first critical reason for
            # actionability while exposing authorization separately below.
            pass

        primary = reasons[0]
        healthy_values = {"PASS", "NONE", "INACTIVE", "OK"}
        preflight_passed = all(value in healthy_values or value.startswith("PASS:") for value in checks.values())
        return CycleResult(
            timestamp_utc=now.isoformat(),
            mode=self.config.mode.value,
            symbol=self.config.symbol,
            connectivity=connectivity.value,
            market_state=market_state,
            strategy_id=self.config.strategy_id,
            decision="NO_ACTION",
            reason=primary.value,
            execution_allowed=False,
            execution_denial_reason=DecisionReason.NO_AUTHORIZED_STRATEGY.value,
            preflight_passed=preflight_passed,
            checks=checks,
            account_identity=account_identity,
            quote_age_seconds=quote_age,
        )

    def run_cycle(self) -> CycleResult:
        started = time.monotonic()
        result = self.cycle()
        self.journal.append(result)
        self._cycle_count += 1
        self._heartbeat(result, time.monotonic() - started)
        return result

    def run_forever(self) -> None:
        previous_handlers = {sig: signal.signal(sig, self.request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        backoff = self.config.cycle_seconds
        lock_path = self.config.journal_path.with_name("runtime.lock")
        try:
            with RuntimeLock(lock_path):
                while not self._stop_requested:
                    result = self.run_cycle()
                    healthy = result.preflight_passed
                    backoff = self.config.cycle_seconds if healthy else min(self.config.max_backoff_seconds, max(self.config.cycle_seconds, backoff * 2))
                    time.sleep(backoff)
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
