import json
from pathlib import Path

import pytest

from src.fx.research.phase5f_attribution import derive_artifact, load_observed_artifact, family_summary


def payload(**overrides):
    data = {"run_id": "phase5e_run1_preregistered_events", "variant_id": "v", "family": "f", "split": "development", "gross_reference_pnl": "10", "net_pnl": "-2", "trade_count": 10, "spread_cost": "10", "slippage_cost": "2", "commission_cost": "0", "swap_cost": "0", "long_trade_count": 5, "short_trade_count": 5}
    data.update(overrides)
    return data


def test_cost_ratio_and_break_even_are_accounting_identities():
    row = derive_artifact(payload())
    assert row["cost_to_gross_ratio"] == "1.2"
    assert row["required_extra_gross_usd"] == "2"
    assert row["required_extra_gross_per_trade_usd"] == "0.2"
    assert row["primary_mechanism"] == "POSITIVE_GROSS_COST_DESTROYED"


def test_nonpositive_gross_has_null_ratio_and_raw_signal_mechanism():
    row = derive_artifact(payload(gross_reference_pnl="0", net_pnl="-2"))
    assert row["cost_to_gross_ratio"] is None
    assert row["primary_mechanism"] == "NEGATIVE_GROSS_SIGNAL"


def test_positive_net_low_sample_is_insufficient_sample():
    assert derive_artifact(payload(net_pnl="1"))["primary_mechanism"] == "INSUFFICIENT_SAMPLE"


def test_source_loader_rejects_untouched_test(tmp_path: Path):
    path = tmp_path / "test" / "x.json"; path.parent.mkdir()
    path.write_text(json.dumps(payload()))
    with pytest.raises(ValueError, match="untouched-test"):
        load_observed_artifact(path)


def test_family_summary_is_deterministic_and_marks_raw_negative():
    rows = [derive_artifact(payload(gross_reference_pnl="-1", net_pnl="-2", trade_count=40)), derive_artifact(payload(variant_id="v2", gross_reference_pnl="-2", net_pnl="-3", trade_count=40))]
    assert family_summary(rows)[0]["primary_failure_mechanism"] == "RAW_SIGNAL_NEGATIVE"
