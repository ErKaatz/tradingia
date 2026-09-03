"""Fail-closed execution policy (FX Phase 0, Step 1).

This module answers exactly one question: given everything we currently
know (config, remote-reported environment/account, reconciliation state,
kill-switch state, current positions, symbol metadata), is a specific
requested action authorized right now?

The central design rule, repeated because it is the entire point of this
file: **any missing, unknown, or ambiguous input causes a deny.** There is
no code path in `authorize_open` or `authorize_close` that allows an
action when a required fact could not be established. This is deliberately
more restrictive than a real broker/terminal will usually require —
Phase 0 has no live trading at all, and the future micro-live phase must
inherit a policy that already assumes the worst about missing information.

Two authorization entry points exist because opening/increasing risk and
closing/reducing risk must be evaluated differently under a kill switch:
a kill switch exists to stop new or growing risk, not to trap a user in a
position they need to exit. See `authorize_close` for the risk-reducing
path, which does not check the kill switch.

Nothing in this module talks to a network, a file, or MetaTrader5. It is
pure decision logic over plain data, which is what makes it exhaustively
unit-testable without a bridge or a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.execution.base import (
    AccountTradeMode,
    ActionKind,
    Environment,
    OrderRequest,
    ReconciliationState,
    SymbolMetadata,
)


# --------------------------------------------------------------------------
# Frozen policy config
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RealMoneyPolicy:
    """The frozen rules from `configs/real_money_policy.yaml`.

    `live_trading_enabled` must be `False` throughout Phase 0. Every other
    field describes constraints for a *future* micro-live phase (see
    LIVE_TRADING_RULES.md) — their presence here does not mean live
    trading is possible yet; `live_trading_enabled` is the actual gate,
    and it is combined with several independently-required remote facts
    in `authorize_open` before any order could ever be allowed, live or
    demo.

    The forbidden-behavior fields are typed as booleans that must be
    `True` (forbidden) — the loader rejects a config that tries to set
    any of them to `False`; see `RealMoneyPolicy.from_dict`. This is what
    "banned behaviors cannot be enabled by config" means concretely: the
    schema itself has no way to represent "martingale is allowed."
    """

    live_trading_enabled: bool
    max_initial_capital_usd: Decimal
    max_additional_funding_usd: Decimal
    max_simultaneous_positions: int
    minimum_volume_only: bool
    martingale_forbidden: bool
    averaging_down_forbidden: bool
    recovery_grid_forbidden: bool
    automatic_size_increase_forbidden: bool
    compounding_forbidden: bool

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "RealMoneyPolicy":
        live_section = raw.get("live", {}) or {}
        limits = raw.get("limits", {}) or {}
        forbidden = raw.get("forbidden_behaviors", {}) or {}

        required_forbidden_true = {
            "martingale": "martingale_forbidden",
            "averaging_down": "averaging_down_forbidden",
            "recovery_grid": "recovery_grid_forbidden",
            "automatic_size_increase": "automatic_size_increase_forbidden",
            "compounding": "compounding_forbidden",
        }
        values: dict[str, bool] = {}
        for config_key, field_name in required_forbidden_true.items():
            if config_key not in forbidden:
                raise ValueError(
                    f"real_money_policy config is missing required forbidden_behaviors.{config_key}"
                )
            value = forbidden[config_key]
            if value is not True:
                raise ValueError(
                    f"forbidden_behaviors.{config_key} must be true; "
                    "this policy schema cannot express permission for it"
                )
            values[field_name] = True

        if "minimum_volume_only" not in limits:
            raise ValueError("real_money_policy config is missing limits.minimum_volume_only")
        if limits["minimum_volume_only"] is not True:
            raise ValueError(
                "limits.minimum_volume_only must be true in this phase; "
                "non-minimum sizing is not implemented"
            )

        if "live_trading_enabled" not in live_section:
            raise ValueError("real_money_policy config is missing live.live_trading_enabled")
        live_enabled = live_section["live_trading_enabled"]
        if not isinstance(live_enabled, bool):
            raise ValueError("live.live_trading_enabled must be a boolean")

        if "max_simultaneous_positions" not in limits:
            raise ValueError("real_money_policy config is missing limits.max_simultaneous_positions")
        max_positions = int(limits["max_simultaneous_positions"])
        if max_positions < 1:
            raise ValueError("limits.max_simultaneous_positions must be >= 1")

        if "max_initial_capital_usd" not in live_section:
            raise ValueError("real_money_policy config is missing live.max_initial_capital_usd")
        if "max_additional_funding_usd" not in live_section:
            raise ValueError("real_money_policy config is missing live.max_additional_funding_usd")

        return RealMoneyPolicy(
            live_trading_enabled=live_enabled,
            max_initial_capital_usd=Decimal(str(live_section["max_initial_capital_usd"])),
            max_additional_funding_usd=Decimal(str(live_section["max_additional_funding_usd"])),
            max_simultaneous_positions=max_positions,
            minimum_volume_only=True,
            **values,
        )

    @staticmethod
    def from_yaml(path: str | Path) -> "RealMoneyPolicy":
        with open(path) as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError("real_money_policy config must be a mapping")
        return RealMoneyPolicy.from_dict(raw)


# --------------------------------------------------------------------------
# Runtime context (facts gathered from config + remote state)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyContext:
    """Everything policy needs to know to decide, gathered from wherever
    it actually lives (local config, bridge health check, account query,
    reconciliation routine, kill-switch store, position list).

    Every field that can legitimately be "we don't know" uses the
    corresponding `UNKNOWN` enum member or `None` — there is no boolean
    "is_valid" flag to fake confidence with. Step 1 has no bridge, so
    tests construct this directly; a later step will populate it from
    real queries.
    """

    local_environment: Environment
    remote_environment: Environment
    account_trade_mode: AccountTradeMode
    reconciliation_state: ReconciliationState
    kill_switch_active: bool
    current_position_count: int | None
    symbol_metadata: SymbolMetadata | None
    account_known: bool = True


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def deny(*reasons: str) -> "PolicyDecision":
        return PolicyDecision(allowed=False, reasons=tuple(reasons))

    @staticmethod
    def allow() -> "PolicyDecision":
        return PolicyDecision(allowed=True, reasons=())


_INCREASING_ACTIONS = frozenset({ActionKind.OPEN, ActionKind.INCREASE})
_REDUCING_ACTIONS = frozenset({ActionKind.CLOSE, ActionKind.REDUCE})


def _normalized_volume_matches_minimum(volume: Decimal, metadata: SymbolMetadata) -> bool:
    """True iff `volume` equals the symbol's minimum tradeable size.

    Comparison is done on `Decimal` values as given — callers are expected
    to pass volumes already expressed in the same scale/precision as the
    broker's own `volume_min`/`volume_step` (both `Decimal`), which avoids
    the float-drift problem entirely rather than trying to paper over it
    with a tolerance. `volume_step` is accepted here for future sizing
    logic beyond "exactly the minimum" but is not used for tolerance in
    this minimum-only-sizing phase.
    """

    return volume == metadata.volume_min


def authorize_open(context: PolicyContext, request: OrderRequest, policy: RealMoneyPolicy) -> PolicyDecision:
    """Authorize an action that opens or increases risk (OPEN/INCREASE).

    Fails closed on any missing or non-DEMO signal. Every check below is
    independent and additive — removing any single one must not be able
    to turn a deny into an allow for a case this function is meant to
    reject (see the Step 1 test suite, which exercises each check alone).
    """

    if request.action_kind not in _INCREASING_ACTIONS:
        raise ValueError(
            f"authorize_open only accepts OPEN/INCREASE action kinds, got {request.action_kind}"
        )

    reasons: list[str] = []

    if policy.live_trading_enabled:
        reasons.append("live_trading_enabled is true; Phase 0 permits demo only")

    if context.local_environment is Environment.LIVE:
        reasons.append("local environment is LIVE")
    elif context.local_environment is Environment.UNKNOWN:
        reasons.append("local environment is UNKNOWN")
    elif context.local_environment is not Environment.DEMO:
        reasons.append(f"local environment {context.local_environment} is not DEMO")

    if context.remote_environment is Environment.LIVE:
        reasons.append("remote environment is LIVE")
    elif context.remote_environment is Environment.UNKNOWN:
        reasons.append("remote environment is UNKNOWN")
    elif context.remote_environment is not Environment.DEMO:
        reasons.append(f"remote environment {context.remote_environment} is not DEMO")

    if not context.account_known:
        reasons.append("account information is missing")
    elif context.account_trade_mode is AccountTradeMode.LIVE:
        reasons.append("account trade mode is LIVE")
    elif context.account_trade_mode is AccountTradeMode.UNKNOWN:
        reasons.append("account trade mode is UNKNOWN")
    elif context.account_trade_mode is not AccountTradeMode.DEMO:
        reasons.append(f"account trade mode {context.account_trade_mode} is not DEMO")

    if context.reconciliation_state is not ReconciliationState.OK:
        reasons.append(f"reconciliation state is {context.reconciliation_state.value}, not OK")

    if context.kill_switch_active:
        reasons.append("kill switch is active; new/increased risk is blocked")

    if context.current_position_count is None:
        reasons.append("current position count is unknown")
    elif context.current_position_count >= policy.max_simultaneous_positions:
        reasons.append(
            f"current position count {context.current_position_count} "
            f">= max_simultaneous_positions {policy.max_simultaneous_positions}"
        )

    if context.symbol_metadata is None:
        reasons.append("symbol metadata is missing")
    else:
        if policy.minimum_volume_only and not _normalized_volume_matches_minimum(
            request.volume, context.symbol_metadata
        ):
            reasons.append(
                f"requested volume {request.volume} != symbol minimum "
                f"{context.symbol_metadata.volume_min} (minimum_volume_only policy)"
            )
        if request.volume > context.symbol_metadata.volume_max:
            reasons.append(
                f"requested volume {request.volume} > symbol maximum {context.symbol_metadata.volume_max}"
            )
        if request.volume <= Decimal(0):
            reasons.append("requested volume must be positive")

    if reasons:
        return PolicyDecision.deny(*reasons)
    return PolicyDecision.allow()


def authorize_close(context: PolicyContext, request: OrderRequest, policy: RealMoneyPolicy) -> PolicyDecision:
    """Authorize an action that closes or reduces risk (CLOSE/REDUCE).

    Deliberately does NOT check the kill switch: a kill switch exists to
    stop new/growing risk, never to trap the user in an existing
    position. It still fails closed on missing/ambiguous account or
    environment identity, and on unresolved reconciliation, because
    executing against a venue we cannot positively identify is not made
    safer by the action being a close.
    """

    if request.action_kind not in _REDUCING_ACTIONS:
        raise ValueError(
            f"authorize_close only accepts CLOSE/REDUCE action kinds, got {request.action_kind}"
        )

    reasons: list[str] = []

    if context.local_environment is Environment.LIVE:
        reasons.append("local environment is LIVE")
    elif context.local_environment is Environment.UNKNOWN:
        reasons.append("local environment is UNKNOWN")

    if context.remote_environment is Environment.LIVE:
        reasons.append("remote environment is LIVE")
    elif context.remote_environment is Environment.UNKNOWN:
        reasons.append("remote environment is UNKNOWN")

    if not context.account_known:
        reasons.append("account information is missing")
    elif context.account_trade_mode is AccountTradeMode.LIVE:
        reasons.append("account trade mode is LIVE")
    elif context.account_trade_mode is AccountTradeMode.UNKNOWN:
        reasons.append("account trade mode is UNKNOWN")

    if context.reconciliation_state is not ReconciliationState.OK:
        reasons.append(f"reconciliation state is {context.reconciliation_state.value}, not OK")

    if policy.live_trading_enabled:
        reasons.append("live_trading_enabled is true; Phase 0 permits demo only")

    if reasons:
        return PolicyDecision.deny(*reasons)
    return PolicyDecision.allow()
