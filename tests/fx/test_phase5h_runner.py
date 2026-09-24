from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.fx.research.phase5h_runner import HOLDING_BARS, VARIANTS, _completed_targets, _rule_matrix, _validate_pre_engine_targets
from src.fx.backtesting.costs import NoCommission, NoSwap, ZeroSlippage
from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.engine import FxEngineConfig
from src.fx.backtesting.models import TargetPosition
from src.fx.data.schema import FxBar
from src.fx.strategies.phase5h_failed_breakout import daily_range_failed_breakout


UTC = timezone.utc


def _bar(index: int, close: str) -> FxBar:
    value = Decimal(close)
    return FxBar(datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=index), value, value + Decimal(".1"), value - Decimal(".1"), value, Decimal("1"), None, 1)


def _event_bars(direction: str) -> tuple[FxBar, ...]:
    # Day 1 establishes an exactly [9.9, 10.1] completed range.  Day 2
    # contains B0 (index 25), B1 confirmation (26), B2 entry (27), then
    # four completed holding bars and B6's exit open (31).
    prior = tuple(_bar(i, "10") for i in range(24))
    broken = "8" if direction == "long" else "12"
    return prior + tuple(_bar(24 + i, value) for i, value in enumerate(("10", broken, "10", "10", "10", "10", "10", "10")))


def _engine_config() -> FxEngineConfig:
    return FxEngineConfig("EURUSD", Decimal(".01"), Decimal("100000"), Decimal(".00001"), Decimal(".01"), Decimal("60"), Decimal(".01"), "USD", "USD", Decimal("100"), NoCommission(), ZeroSlippage(), NoSwap(), None)


def test_tail_targets_without_a_full_entry_and_hold_are_discarded_only_at_tail():
    source = (TargetPosition.FLAT,) * 4 + (TargetPosition.LONG,) * HOLDING_BARS
    assert _completed_targets(source)[:4] == source[:4]
    assert _completed_targets(source)[4:] == (TargetPosition.FLAT,) * HOLDING_BARS


def test_tail_mask_keeps_an_entire_valid_event_block_regression_for_run1_failure():
    # This is the exact shape that used to fail: the signal block had enough
    # room for entry + four holding bars + exit, but the old per-index mask
    # erased its final three targets and caused a one-bar trade.
    source = (TargetPosition.FLAT,) * 3 + (TargetPosition.SHORT,) * HOLDING_BARS + (TargetPosition.FLAT,) * 2
    assert _completed_targets(source) == source


def test_run2_short_tail_regression_does_not_extend_signal_sequence():
    # The old slice assignment replaced the final one-item slice with four
    # FLAT values, changing this five-item sequence into eight items.
    source = (TargetPosition.FLAT,) * 4 + (TargetPosition.SHORT,)
    cleaned = _completed_targets(source)
    assert len(cleaned) == len(source) == 5
    assert cleaned == (TargetPosition.FLAT,) * 5


@pytest.mark.parametrize("remaining", range(0, 11))
def test_tail_matrix_preserves_length_and_keeps_only_complete_events(remaining):
    prefix = (TargetPosition.FLAT,) * 3
    raw_block = (TargetPosition.LONG,) * min(HOLDING_BARS, remaining)
    source = prefix + raw_block + (TargetPosition.FLAT,) * max(0, remaining - HOLDING_BARS)
    cleaned = _completed_targets(source)
    assert len(cleaned) == len(source)
    block = cleaned[3:3 + min(HOLDING_BARS, remaining)]
    if remaining >= HOLDING_BARS + 2:  # signal targets plus B5 and B6
        assert block == raw_block
    else:
        assert block == (TargetPosition.FLAT,) * len(block)


def test_pre_engine_gate_reports_length_and_incomplete_event_context():
    bars = tuple(_bar(i, "10") for i in range(6))
    with pytest.raises(ValueError, match="split=validation variant=short bars=6 signals=5"):
        _validate_pre_engine_targets(bars, (TargetPosition.FLAT,) * 5, "validation", "short")
    with pytest.raises(ValueError, match="incomplete event block split=validation variant=short signal_index=2"):
        _validate_pre_engine_targets(bars, (TargetPosition.FLAT, TargetPosition.FLAT, TargetPosition.SHORT, TargetPosition.SHORT, TargetPosition.SHORT, TargetPosition.SHORT), "validation", "short")


def test_long_and_short_signal_to_engine_contract_is_entry_plus_four_complete_bars():
    for direction, variant, target in (("long", "daily-range-failed-breakout-long", TargetPosition.LONG), ("short", "daily-range-failed-breakout-short", TargetPosition.SHORT)):
        bars = _event_bars(direction)
        targets = daily_range_failed_breakout(bars, variant)
        assert targets[26:30] == (target,) * HOLDING_BARS
        result = FxBacktestEngine(_engine_config()).run(bars, targets)
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.open_time == bars[27].timestamp_utc  # B2 open
        assert trade.close_time == bars[31].timestamp_utc  # B6 open
        assert trade.bars_held == HOLDING_BARS


def test_registry_is_exactly_the_two_frozen_hypotheses():
    assert VARIANTS == ("daily-range-failed-breakout-long", "daily-range-failed-breakout-short")


def test_candidate_rules_fail_closed_when_cost_gross_is_nonpositive():
    row = {"trade_count": 100, "solvent": True, "net_pnl": "1", "expectancy": "1", "profit_factor": "2", "max_drawdown": "-0.1", "gross_reference_pnl": "0", "total_costs": "0", "yearly_attribution": {"2024": {"trade_count": 10, "net_pnl": "1"}}, "largest_positive_trade_contribution": "0.2"}
    rules = _rule_matrix({"development_inner_a": row, "development_inner_b": row, "development": row, "validation": row})
    assert not rules["cost_efficiency_all_required_splits"]
