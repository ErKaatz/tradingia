"""Tests for the fail-closed execution policy (FX Phase 0, Step 1).

Every test in this file runs purely against in-memory dataclasses -- no
network, no MT5, no filesystem except where explicitly loading the frozen
YAML config.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.execution.base import (
    AccountTradeMode,
    ActionKind,
    Environment,
    OrderRequest,
    OrderType,
    ReconciliationState,
    Side,
    SymbolMetadata,
)
from src.execution.policy import (
    PolicyContext,
    RealMoneyPolicy,
    authorize_close,
    authorize_open,
)

POLICY_CONFIG_PATH = Path("configs/real_money_policy.yaml")


def _symbol_metadata(**overrides) -> SymbolMetadata:
    defaults = dict(
        symbol="EURUSD",
        volume_min=Decimal("0.01"),
        volume_step=Decimal("0.01"),
        volume_max=Decimal("100"),
        contract_size=Decimal("100000"),
        digits=5,
        point=Decimal("0.00001"),
    )
    defaults.update(overrides)
    return SymbolMetadata(**defaults)


def _valid_demo_context(**overrides) -> PolicyContext:
    defaults = dict(
        local_environment=Environment.DEMO,
        remote_environment=Environment.DEMO,
        account_trade_mode=AccountTradeMode.DEMO,
        reconciliation_state=ReconciliationState.OK,
        kill_switch_active=False,
        current_position_count=0,
        symbol_metadata=_symbol_metadata(),
        account_known=True,
    )
    defaults.update(overrides)
    return PolicyContext(**defaults)


def _open_request(volume: Decimal = Decimal("0.01"), action_kind: ActionKind = ActionKind.OPEN) -> OrderRequest:
    return OrderRequest(
        client_order_id="test-order-1",
        symbol="EURUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume=volume,
        action_kind=action_kind,
    )


def _close_request(volume: Decimal = Decimal("0.01")) -> OrderRequest:
    return OrderRequest(
        client_order_id="test-close-1",
        symbol="EURUSD",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        volume=volume,
        action_kind=ActionKind.CLOSE,
        position_id="pos-1",
    )


@pytest.fixture
def frozen_policy() -> RealMoneyPolicy:
    return RealMoneyPolicy.from_yaml(POLICY_CONFIG_PATH)


# 1. valid demo context allows minimum-size demo entry.
def test_valid_demo_context_allows_minimum_size_entry(frozen_policy):
    decision = authorize_open(_valid_demo_context(), _open_request(), frozen_policy)
    assert decision.allowed is True
    assert decision.reasons == ()


# 2. live environment rejected.
def test_live_local_environment_rejected(frozen_policy):
    context = _valid_demo_context(local_environment=Environment.LIVE)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("local environment is LIVE" in r for r in decision.reasons)


def test_live_remote_environment_rejected(frozen_policy):
    context = _valid_demo_context(remote_environment=Environment.LIVE)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("remote environment is LIVE" in r for r in decision.reasons)


# 3. unknown environment rejected.
def test_unknown_local_environment_rejected(frozen_policy):
    context = _valid_demo_context(local_environment=Environment.UNKNOWN)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("local environment is UNKNOWN" in r for r in decision.reasons)


def test_unknown_remote_environment_rejected(frozen_policy):
    context = _valid_demo_context(remote_environment=Environment.UNKNOWN)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("remote environment is UNKNOWN" in r for r in decision.reasons)


# 4. live account rejected.
def test_live_account_trade_mode_rejected(frozen_policy):
    context = _valid_demo_context(account_trade_mode=AccountTradeMode.LIVE)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("account trade mode is LIVE" in r for r in decision.reasons)


# 5. unknown account type rejected.
def test_unknown_account_trade_mode_rejected(frozen_policy):
    context = _valid_demo_context(account_trade_mode=AccountTradeMode.UNKNOWN)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("account trade mode is UNKNOWN" in r for r in decision.reasons)


# 6. live_trading_enabled=true rejected in Phase0.
def test_live_trading_enabled_true_rejected(frozen_policy):
    forced_live_policy = RealMoneyPolicy(
        live_trading_enabled=True,
        max_initial_capital_usd=frozen_policy.max_initial_capital_usd,
        max_additional_funding_usd=frozen_policy.max_additional_funding_usd,
        max_simultaneous_positions=frozen_policy.max_simultaneous_positions,
        minimum_volume_only=frozen_policy.minimum_volume_only,
        martingale_forbidden=True,
        averaging_down_forbidden=True,
        recovery_grid_forbidden=True,
        automatic_size_increase_forbidden=True,
        compounding_forbidden=True,
    )
    decision = authorize_open(_valid_demo_context(), _open_request(), forced_live_policy)
    assert decision.allowed is False
    assert any("live_trading_enabled is true" in r for r in decision.reasons)


# 7. kill switch blocks new entry.
def test_kill_switch_blocks_new_entry(frozen_policy):
    context = _valid_demo_context(kill_switch_active=True)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("kill switch is active" in r for r in decision.reasons)


def test_kill_switch_blocks_increase(frozen_policy):
    context = _valid_demo_context(kill_switch_active=True)
    decision = authorize_open(context, _open_request(action_kind=ActionKind.INCREASE), frozen_policy)
    assert decision.allowed is False


# 8. kill switch does NOT automatically block close.
def test_kill_switch_does_not_block_close(frozen_policy):
    context = _valid_demo_context(kill_switch_active=True)
    decision = authorize_close(context, _close_request(), frozen_policy)
    assert decision.allowed is True


def test_kill_switch_does_not_block_reduce(frozen_policy):
    context = _valid_demo_context(kill_switch_active=True)
    request = OrderRequest(
        client_order_id="reduce-1",
        symbol="EURUSD",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        volume=Decimal("0.01"),
        action_kind=ActionKind.REDUCE,
        position_id="pos-1",
    )
    decision = authorize_close(context, request, frozen_policy)
    assert decision.allowed is True


# 9. reconciliation mismatch blocks new entry.
def test_reconciliation_mismatch_blocks_new_entry(frozen_policy):
    context = _valid_demo_context(reconciliation_state=ReconciliationState.MISMATCH)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("reconciliation state is mismatch" in r for r in decision.reasons)


def test_reconciliation_unknown_blocks_new_entry(frozen_policy):
    context = _valid_demo_context(reconciliation_state=ReconciliationState.UNKNOWN)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False


def test_reconciliation_mismatch_also_blocks_close(frozen_policy):
    context = _valid_demo_context(reconciliation_state=ReconciliationState.MISMATCH)
    decision = authorize_close(context, _close_request(), frozen_policy)
    assert decision.allowed is False


# 10. second simultaneous position blocked.
def test_second_simultaneous_position_blocked(frozen_policy):
    context = _valid_demo_context(current_position_count=1)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("max_simultaneous_positions" in r for r in decision.reasons)


def test_position_count_unknown_blocks_entry(frozen_policy):
    context = _valid_demo_context(current_position_count=None)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("current position count is unknown" in r for r in decision.reasons)


# 11. requested volume > minimum rejected.
def test_requested_volume_above_minimum_rejected(frozen_policy):
    decision = authorize_open(_valid_demo_context(), _open_request(volume=Decimal("0.02")), frozen_policy)
    assert decision.allowed is False
    assert any("!= symbol minimum" in r for r in decision.reasons)


# 12. requested volume < minimum rejected.
def test_requested_volume_below_minimum_rejected(frozen_policy):
    decision = authorize_open(_valid_demo_context(), _open_request(volume=Decimal("0.005")), frozen_policy)
    assert decision.allowed is False
    assert any("!= symbol minimum" in r for r in decision.reasons)


# 13. exact minimum accepted.
def test_exact_minimum_volume_accepted(frozen_policy):
    meta = _symbol_metadata(volume_min=Decimal("0.10"))
    context = _valid_demo_context(symbol_metadata=meta)
    decision = authorize_open(context, _open_request(volume=Decimal("0.10")), frozen_policy)
    assert decision.allowed is True


# 14. absent symbol metadata rejected.
def test_absent_symbol_metadata_rejected(frozen_policy):
    context = _valid_demo_context(symbol_metadata=None)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("symbol metadata is missing" in r for r in decision.reasons)


# 15. absent account metadata rejected.
def test_absent_account_metadata_rejected(frozen_policy):
    context = _valid_demo_context(account_known=False)
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert any("account information is missing" in r for r in decision.reasons)


# 16. banned behaviors cannot be enabled by config.
def test_banned_behaviors_cannot_be_enabled_by_config():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    raw["forbidden_behaviors"]["martingale"] = False
    with pytest.raises(ValueError, match="martingale"):
        RealMoneyPolicy.from_dict(raw)


@pytest.mark.parametrize(
    "behavior_key",
    ["martingale", "averaging_down", "recovery_grid", "automatic_size_increase", "compounding"],
)
def test_each_forbidden_behavior_rejects_false(behavior_key):
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    raw["forbidden_behaviors"][behavior_key] = False
    with pytest.raises(ValueError):
        RealMoneyPolicy.from_dict(raw)


def test_minimum_volume_only_cannot_be_disabled_by_config():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    raw["limits"]["minimum_volume_only"] = False
    with pytest.raises(ValueError, match="minimum_volume_only"):
        RealMoneyPolicy.from_dict(raw)


# 17. malformed/incomplete policy config fails closed.
def test_missing_live_trading_enabled_key_fails_to_load():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    del raw["live"]["live_trading_enabled"]
    with pytest.raises(ValueError, match="live_trading_enabled"):
        RealMoneyPolicy.from_dict(raw)


def test_missing_forbidden_behaviors_section_fails_to_load():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    del raw["forbidden_behaviors"]["compounding"]
    with pytest.raises(ValueError, match="compounding"):
        RealMoneyPolicy.from_dict(raw)


def test_missing_max_positions_key_fails_to_load():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    del raw["limits"]["max_simultaneous_positions"]
    with pytest.raises(ValueError, match="max_simultaneous_positions"):
        RealMoneyPolicy.from_dict(raw)


def test_non_mapping_config_rejected(tmp_path):
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="mapping"):
        RealMoneyPolicy.from_yaml(bad_path)


def test_live_trading_enabled_non_boolean_rejected():
    raw = yaml.safe_load(POLICY_CONFIG_PATH.read_text())
    raw["live"]["live_trading_enabled"] = "false"  # string, not bool
    with pytest.raises(ValueError, match="boolean"):
        RealMoneyPolicy.from_dict(raw)


# 18. Decimal/volume comparisons behave correctly.
def test_decimal_volume_comparison_not_fooled_by_float_noise(frozen_policy):
    meta = _symbol_metadata(volume_min=Decimal("0.1"))
    context = _valid_demo_context(symbol_metadata=meta)
    # Decimal("0.1") vs a value that float arithmetic would corrupt
    # (float(0.1) * 3 != 0.3, but Decimal keeps exact decimal semantics).
    decision = authorize_open(context, _open_request(volume=Decimal("0.1")), frozen_policy)
    assert decision.allowed is True
    decision_mismatch = authorize_open(
        context, _open_request(volume=Decimal("0.1000001")), frozen_policy
    )
    assert decision_mismatch.allowed is False


def test_volume_above_symbol_maximum_rejected(frozen_policy):
    meta = _symbol_metadata(volume_min=Decimal("50"), volume_max=Decimal("10"))
    context = _valid_demo_context(symbol_metadata=meta)
    decision = authorize_open(context, _open_request(volume=Decimal("50")), frozen_policy)
    assert decision.allowed is False
    assert any("> symbol maximum" in r for r in decision.reasons)


def test_zero_or_negative_volume_rejected(frozen_policy):
    meta = _symbol_metadata(volume_min=Decimal("0"))
    context = _valid_demo_context(symbol_metadata=meta)
    decision = authorize_open(context, _open_request(volume=Decimal("0")), frozen_policy)
    assert decision.allowed is False
    assert any("must be positive" in r for r in decision.reasons)


# 19. no secret/credential concepts are introduced into these models unnecessarily.
def test_policy_context_and_decision_carry_no_secrets():
    from dataclasses import fields as dc_fields

    forbidden_substrings = ("password", "secret", "token", "api_key", "credential")
    for cls in (PolicyContext,):
        for f in dc_fields(cls):
            lowered = f.name.lower()
            for forbidden in forbidden_substrings:
                assert forbidden not in lowered


# 20. policy config round-trips/loads deterministically.
def test_policy_config_loads_deterministically():
    policy_a = RealMoneyPolicy.from_yaml(POLICY_CONFIG_PATH)
    policy_b = RealMoneyPolicy.from_yaml(POLICY_CONFIG_PATH)
    assert policy_a == policy_b


def test_frozen_policy_values_match_documented_rules(frozen_policy):
    assert frozen_policy.live_trading_enabled is False
    assert frozen_policy.max_initial_capital_usd == Decimal("10")
    assert frozen_policy.max_additional_funding_usd == Decimal("0")
    assert frozen_policy.max_simultaneous_positions == 1
    assert frozen_policy.minimum_volume_only is True
    assert frozen_policy.martingale_forbidden is True
    assert frozen_policy.averaging_down_forbidden is True
    assert frozen_policy.recovery_grid_forbidden is True
    assert frozen_policy.automatic_size_increase_forbidden is True
    assert frozen_policy.compounding_forbidden is True


# Additional edge cases


def test_authorize_open_rejects_close_action_kind(frozen_policy):
    with pytest.raises(ValueError, match="OPEN/INCREASE"):
        authorize_open(_valid_demo_context(), _close_request(), frozen_policy)


def test_authorize_close_rejects_open_action_kind(frozen_policy):
    with pytest.raises(ValueError, match="CLOSE/REDUCE"):
        authorize_close(_valid_demo_context(), _open_request(), frozen_policy)


def test_multiple_simultaneous_violations_all_reported(frozen_policy):
    context = _valid_demo_context(
        local_environment=Environment.LIVE,
        account_trade_mode=AccountTradeMode.UNKNOWN,
        kill_switch_active=True,
    )
    decision = authorize_open(context, _open_request(), frozen_policy)
    assert decision.allowed is False
    assert len(decision.reasons) >= 3


def test_close_allowed_in_clean_demo_context(frozen_policy):
    decision = authorize_close(_valid_demo_context(), _close_request(), frozen_policy)
    assert decision.allowed is True


def test_close_rejected_when_account_unknown(frozen_policy):
    context = _valid_demo_context(account_known=False)
    decision = authorize_close(context, _close_request(), frozen_policy)
    assert decision.allowed is False
