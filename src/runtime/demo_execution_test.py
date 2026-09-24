"""Single-use, test-only DEMO execution probe.

This is not a strategy and cannot be selected by the normal runtime. It exists
only to validate the already implemented bridge execution plumbing.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.execution.base import AccountTradeMode, Environment, Side
from src.execution.policy import RealMoneyPolicy
from src.execution.quote_freshness import (
    DEFAULT_MAX_QUOTE_AGE_SECONDS, DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
    validate_quote_freshness,
)
from src.execution.safe_execution import (
    SafeExecutionDeniedError, SafeExecutionQuoteFreshnessError, SafeExecutionService,
)


class DemoExecutionTestError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoExecutionTestConfig:
    symbol: str
    side: Side
    state_path: Path
    test_run_id: str
    enabled: bool

    @classmethod
    def from_env(cls, *, side: str) -> "DemoExecutionTestConfig":
        if os.environ.get("TRADINGIA_MODE", "READ_ONLY").upper() != "DEMO":
            raise DemoExecutionTestError("TRADINGIA_MODE must be DEMO for a test-only execution probe")
        enabled = os.environ.get("TRADINGIA_DEMO_EXECUTION_TEST") == "ENABLED"
        if not enabled:
            raise DemoExecutionTestError("TRADINGIA_DEMO_EXECUTION_TEST=ENABLED is required")
        symbol = os.environ.get("TRADINGIA_DEMO_TEST_SYMBOL", "EURUSD").strip()
        if not symbol:
            raise DemoExecutionTestError("TRADINGIA_DEMO_TEST_SYMBOL must not be empty")
        path = Path(os.environ.get(
            "TRADINGIA_DEMO_EXECUTION_TEST_STATE",
            str(Path.home() / ".local" / "state" / "tradingia" / "demo_execution_test.json"),
        ))
        return cls(symbol=symbol, side=Side.BUY if side == "buy" else Side.SELL, state_path=path, test_run_id=str(uuid.uuid4()), enabled=True)


class DemoExecutionTestState:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict | None:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temp, self.path)


class DemoExecutionProbe:
    """Owns exactly one open/close test cycle; never evaluates PnL."""

    def __init__(self, client, policy: RealMoneyPolicy, config: DemoExecutionTestConfig) -> None:
        self.client, self.policy, self.config = client, policy, config
        self.state = DemoExecutionTestState(config.state_path)

    def _record(self, **fields) -> None:
        current = self.state.load() or {}
        current.update(fields)
        current["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.state.save(current)

    def _preflight(self):
        prior = self.state.load()
        if prior and prior.get("state") in {"OPENING", "OPEN", "CLOSING", "CLOSED", "AMBIGUOUS"}:
            raise DemoExecutionTestError(f"test authorization is single-use and state is {prior['state']}")
        if self.policy.live_trading_enabled:
            raise DemoExecutionTestError("LIVE policy is enabled; test-only DEMO probe refuses to run")
        account = self.client.account()
        if account.trade_mode is not AccountTradeMode.DEMO:
            raise DemoExecutionTestError("account is not unambiguously DEMO")
        terminal = self.client.terminal()
        if terminal.connected is not True or terminal.trade_allowed is not True:
            raise DemoExecutionTestError("MT5 terminal is not connected/trade-enabled")
        if account.trade_allowed is not True or account.trade_expert is not True:
            raise DemoExecutionTestError("account automated trading permission is not enabled")
        if self.client.kill_switch_status().status.value == "active":
            raise DemoExecutionTestError("kill switch active")
        if self.client.reconciliation_status().state.value != "ok":
            raise DemoExecutionTestError("reconciliation is not healthy")
        if tuple(self.client.positions()) or tuple(self.client.orders()):
            raise DemoExecutionTestError("foreign or unexpected broker exposure exists before test")
        metadata = self.client.symbol_metadata(self.config.symbol)
        if metadata.volume_min <= 0 or metadata.volume_min > metadata.volume_max:
            raise DemoExecutionTestError("invalid broker volume metadata")
        quote = self.client.quote(self.config.symbol)
        validate_quote_freshness(
            symbol=self.config.symbol, quote_timestamp=quote.timestamp,
            max_age_seconds=DEFAULT_MAX_QUOTE_AGE_SECONDS,
            max_future_skew_seconds=DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS,
        )
        return metadata, quote

    def run(self) -> dict:
        metadata, quote = self._preflight()
        volume: Decimal = metadata.volume_min
        open_id, close_id = f"probe-open-{self.config.test_run_id}", f"probe-close-{self.config.test_run_id}"
        self._record(
            state="OPENING", test_run_id=self.config.test_run_id, decision_source="TEST_ONLY_EXECUTION_PROBE",
            runtime_mode="DEMO", symbol=self.config.symbol, side=self.config.side.value,
            volume=str(volume), requested_at_utc=datetime.now(timezone.utc).isoformat(),
            open_idempotency_key=open_id, close_idempotency_key=close_id,
            quote_timestamp_utc=quote.timestamp.isoformat(), events=["authorization", "preflight", "decision", "execution_authorized"],
        )
        service = SafeExecutionService(client=self.client, policy=self.policy, local_environment=Environment.DEMO)
        try:
            opened = service.safe_open(open_id, self.config.symbol, self.config.side, volume)
        except (SafeExecutionDeniedError, SafeExecutionQuoteFreshnessError) as exc:
            self._record(state="EXPIRED", failure="open_denied", events=(self.state.load() or {}).get("events", []) + ["open_denied"])
            raise DemoExecutionTestError(str(exc)) from exc
        except Exception as exc:
            # A response ambiguity is never retried. Persist it and require
            # bridge reconciliation/human inspection before any later action.
            self._record(state="AMBIGUOUS", failure="open_response_ambiguous", events=(self.state.load() or {}).get("events", []) + ["open_ambiguous"])
            try:
                self.client.run_reconciliation()
            finally:
                raise DemoExecutionTestError("open response ambiguous; reconciled, no blind retry") from exc

        positions = tuple(self.client.positions())
        expected = [p for p in positions if p.position_id == opened.position_id and p.symbol == self.config.symbol and p.side is self.config.side and p.volume == volume]
        if len(positions) != 1 or len(expected) != 1 or tuple(self.client.orders()):
            self._record(state="AMBIGUOUS", failure="open_reconciliation_mismatch")
            raise DemoExecutionTestError("open reconciliation mismatch; refusing automatic close")
        self._record(state="OPEN", position_id=opened.position_id, broker_order_id=opened.broker_order_id, deal_id=opened.deal_id,
                     fill_price=str(opened.fill_price) if opened.fill_price is not None else None,
                     events=(self.state.load() or {}).get("events", []) + ["open_acknowledged", "open_reconciled"])

        # Existing policy intentionally permits risk-reducing close if a kill
        # switch activates after open. Reconciliation is still required.
        closing_side = Side.SELL if self.config.side is Side.BUY else Side.BUY
        self._record(state="CLOSING", events=(self.state.load() or {}).get("events", []) + ["close_requested"])
        try:
            closed = service.safe_close(close_id, opened.position_id, self.config.symbol, closing_side, volume)
        except Exception as exc:
            self._record(state="AMBIGUOUS", failure="close_response_ambiguous", events=(self.state.load() or {}).get("events", []) + ["close_ambiguous"])
            try:
                self.client.run_reconciliation()
            finally:
                raise DemoExecutionTestError("close response ambiguous; reconciled, no blind retry") from exc
        if tuple(self.client.positions()) or tuple(self.client.orders()):
            self._record(state="AMBIGUOUS", failure="final_reconciliation_mismatch")
            raise DemoExecutionTestError("final reconciliation mismatch; exposure may remain")
        self._record(state="CLOSED", test_authorization="EXPIRED", close_deal_id=closed.deal_id,
                     events=(self.state.load() or {}).get("events", []) + ["close_acknowledged", "final_reconciled", "shutdown"])
        return self.state.load() or {}

