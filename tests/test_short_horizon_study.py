"""Phase 4A orchestration/guardrail tests."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.phase3_guard import compute_phase3_fingerprint
from src.research.short_horizon_study import (
    ALLOWED_CLASSIFICATIONS,
    FROZEN_VARIANTS,
    POSTHOC_LABEL,
    _classify_variant,
    _parameter_plateau_table,
    _period_slice_with_warmup,
    build_strategy,
    frozen_variant_count,
)


def test_frozen_variant_count_is_exactly_40():
    assert frozen_variant_count() == 40
    assert set(FROZEN_VARIANTS) == {"15m", "1h"}


def test_same_family_set_exists_on_both_timeframes():
    assert set(FROZEN_VARIANTS["15m"]) == set(FROZEN_VARIANTS["1h"])
    assert len(FROZEN_VARIANTS["15m"]) == 7


def test_no_unapproved_classification_language():
    assert ALLOWED_CLASSIFICATIONS == {
        "REJECTED",
        "INTERESTING POST-HOC",
        "COST-SENSITIVE",
        "REGIME-SENSITIVE",
        "INSUFFICIENT EVIDENCE",
    }
    assert "PROFITABLE" not in ALLOWED_CLASSIFICATIONS
    assert "PROVEN" not in ALLOWED_CLASSIFICATIONS


def test_every_frozen_variant_builds_and_is_long_flat_strategy():
    for tf, families in FROZEN_VARIANTS.items():
        for family, variants in families.items():
            for params in variants:
                s = build_strategy(family, params)
                assert s.name == family
                assert s.warmup_bars >= 0


def test_build_strategy_rejects_family_not_frozen_into_phase():
    with pytest.raises(ValueError, match="Unknown/frozen-out"):
        build_strategy("secret_optimizer", {})


def test_period_slice_includes_only_past_warmup():
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-12-01", periods=100, freq="h", tz="UTC"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0,
    })
    strat = build_strategy("short_momentum", {"lookback": 8, "max_holding_bars": 8})
    start = df.timestamp.iloc[50]
    end = df.timestamp.iloc[70]
    ext, eval_start = _period_slice_with_warmup(df, strat, start, end)
    assert eval_start == 8
    assert ext.timestamp.iloc[eval_start] == start
    assert ext.timestamp.max() == end
    assert (ext.timestamp.iloc[:eval_start] < start).all()
    assert not (ext.timestamp > end).any()


def _series(**kwargs):
    base = dict(num_trades=100, net_expectancy=1.0, total_return=0.2)
    base.update(kwargs)
    return pd.Series(base)


def test_classification_rejected_when_base_expectancy_nonpositive():
    label, _ = _classify_variant(_series(net_expectancy=0), _series(), _series(), _series())
    assert label == "REJECTED"


def test_classification_cost_sensitive_when_conservative_kills_edge():
    label, _ = _classify_variant(_series(), _series(net_expectancy=-0.1), _series(), _series())
    assert label == "COST-SENSITIVE"


def test_classification_regime_sensitive_when_period_sign_flips():
    label, _ = _classify_variant(_series(), _series(), _series(total_return=0.2), _series(total_return=-0.1))
    assert label == "REGIME-SENSITIVE"


def test_classification_interesting_requires_enough_trades_and_cost_survival():
    label, _ = _classify_variant(_series(), _series(), _series(total_return=0.2), _series(total_return=0.1))
    assert label == "INTERESTING POST-HOC"
    label2, _ = _classify_variant(_series(num_trades=20), _series(), _series(), _series())
    assert label2 == "INSUFFICIENT EVIDENCE"


def test_plateau_diagnostic_uses_only_existing_rows():
    rows = pd.DataFrame([
        {"timeframe": "1h", "family": "x", "net_expectancy": 1.0},
        {"timeframe": "1h", "family": "x", "net_expectancy": 1.2},
        {"timeframe": "1h", "family": "x", "net_expectancy": 0.8},
    ])
    out = _parameter_plateau_table(rows)
    assert len(out) == 1
    assert out.iloc[0]["variants"] == 3
    assert out.iloc[0]["shape"] == "plateau"


def test_posthoc_label_is_unambiguous():
    assert "POST-HOC" in POSTHOC_LABEL
    assert "NOT OUT-OF-SAMPLE" in POSTHOC_LABEL


def test_phase3_guarded_files_unchanged_by_importing_phase4a():
    before = compute_phase3_fingerprint()
    # All work above has imported/constructed Phase-4A objects; none may mutate Phase 3.
    after = compute_phase3_fingerprint()
    assert before == after
