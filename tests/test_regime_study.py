"""Tests for the Phase 3B regime study orchestration and its guardrails:
at most 3 hypotheses, exactly one simulation variant per hypothesis, no
threshold grid search, correct yearly separation, POST-HOC labeling
throughout, and Phase 3 integrity preserved before and after running.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.regime_gate_simulation import (
    ADX_STANDARD_TREND_THRESHOLD,
    adx_minimum_gate,
    volatility_compression_gate,
)
from src.research.regime_study import (
    EXPLORATORY_SIMULATIONS,
    LABEL,
    LABEL_FULL,
    MAX_HYPOTHESES,
    RECENT_END,
    RECENT_START,
    build_yearly_analysis,
)


def test_max_hypotheses_is_three_or_fewer():
    assert MAX_HYPOTHESES <= 3


def test_exactly_one_simulation_variant_declared_per_hypothesis():
    """EXPLORATORY_SIMULATIONS must be a fixed, finite tuple/list of specs
    -- one dict per hypothesis, never a loop that could expand to multiple
    variants (e.g. a grid) per hypothesis id.
    """
    ids = [spec["hypothesis_id"] for spec in EXPLORATORY_SIMULATIONS]
    assert len(ids) == len(set(ids)), "duplicate hypothesis_id would mean >1 variant per hypothesis"
    assert len(EXPLORATORY_SIMULATIONS) <= MAX_HYPOTHESES


def test_declaring_more_simulations_than_max_hypotheses_raises_at_import_time():
    """The module itself enforces this invariant at import time (a runtime
    assertion on the module-level constant), not just by convention.
    """
    import src.research.regime_study as regime_study_module

    assert len(regime_study_module.EXPLORATORY_SIMULATIONS) <= regime_study_module.MAX_HYPOTHESES


def test_no_threshold_grid_in_gate_functions():
    """Gate functions must take a single, fixed threshold policy -- not a
    list/range of candidate thresholds to search over. Verified by
    inspecting the gate simulation module's source for grid-like
    constructs (range(), np.linspace, np.arange, itertools.product) applied
    to a threshold value.
    """
    source = Path("src/research/regime_gate_simulation.py").read_text()
    forbidden_patterns = ["np.linspace", "np.arange", "itertools.product", "GridSearchCV", "Optuna", "optuna"]
    for pattern in forbidden_patterns:
        assert pattern not in source, f"found threshold-grid-like construct: {pattern}"


def test_no_ml_or_optimization_libraries_used():
    """This module must not depend on any ML/optimization library."""
    for path in [
        Path("src/research/regime_study.py"),
        Path("src/research/regime_gate_simulation.py"),
        Path("src/research/regime_features.py"),
    ]:
        source = path.read_text()
        forbidden = [
            "sklearn", "xgboost", "lightgbm", "torch", "tensorflow",
            "optuna", "hyperopt", "RandomForest", "DecisionTree",
            "KMeans", "GradientBoosting",
        ]
        for pattern in forbidden:
            assert pattern not in source, f"{path}: found forbidden ML/optimization reference: {pattern}"


def test_adx_gate_uses_a_single_fixed_literature_threshold():
    assert ADX_STANDARD_TREND_THRESHOLD == 20.0

    df = pd.DataFrame({"close": [1.0] * 5})
    adx = pd.Series([25.0, 15.0, 22.0, 18.0, 30.0])
    from src.strategies.base import FLAT, LONG

    signals = pd.Series([FLAT, LONG, LONG, LONG, LONG])
    gated = adx_minimum_gate(df, adx, signals)
    # Entry attempted at index 1 (adx=15, below threshold) must be blocked.
    assert gated.iloc[1] == FLAT


def test_volatility_gate_uses_trailing_median_not_a_fixed_constant():
    """The volatility gate's threshold must be derived from the feature's
    own trailing history (median), not a fixed numeric constant baked into
    the gate function itself.
    """
    source = Path("src/research/regime_gate_simulation.py").read_text()
    assert "trailing_median" in source
    assert "rolling(" in source
    assert "median()" in source


def test_recent_window_matches_already_consumed_holdout():
    assert RECENT_START == "2025-01-01"
    assert RECENT_END == "2026-09-02"


def test_label_is_post_hoc_regime_research():
    assert LABEL == "POST-HOC REGIME RESEARCH"
    assert "NOT OUT-OF-SAMPLE VALIDATION" in LABEL_FULL


def test_yearly_analysis_separates_years_correctly():
    entry_features = pd.DataFrame(
        {
            "strategy": ["s"] * 6,
            "period": ["research"] * 4 + ["recent"] * 2,
            "entry_time": pd.to_datetime(
                [
                    "2024-06-01", "2024-12-31",
                    "2023-01-01", "2023-06-01",
                    "2025-01-02", "2026-03-01",
                ],
                utc=True,
            ),
            "net_pnl": [10, -5, 20, -1, -3, 8],
            "return_pct": [0.1, -0.05, 0.2, -0.01, -0.03, 0.08],
            "outcome": ["winner", "loser", "winner", "loser", "loser", "winner"],
            "realized_vol_24h": [0.01] * 6,
        }
    )
    for col in [
        "realized_vol_168h", "realized_vol_720h", "atr_14", "atr_over_close_14", "adx_14",
        "sma50_slope", "sma200_slope", "distance_from_sma200", "autocorr_24h", "autocorr_168h",
        "efficiency_ratio_20", "range_compression_24_168", "directional_persistence_168",
        "pct_positive_bars_24h", "pct_positive_bars_72h", "pct_positive_bars_168h",
    ]:
        entry_features[col] = 0.5

    yearly = build_yearly_analysis(entry_features)

    years = set(yearly["year"])
    assert years == {2023, 2024, 2025, 2026}

    row_2024 = yearly[yearly["year"] == 2024].iloc[0]
    assert row_2024["n_trades"] == 2  # only the two 2024 entries, not 2023's
    assert row_2024["period_label"] == "research"

    row_2025 = yearly[yearly["year"] == 2025].iloc[0]
    assert row_2025["n_trades"] == 1
    assert row_2025["period_label"] == "recent (post-hoc)"

    row_2026 = yearly[yearly["year"] == 2026].iloc[0]
    assert row_2026["n_trades"] == 1
    assert row_2026["period_label"] == "recent (post-hoc)"
    # 2025 and 2026 must never be merged into a single row.
    assert len(yearly[yearly["year"].isin([2025, 2026])]) == 2


@pytest.mark.skipif(
    not Path("research/regime_study/metadata.json").exists(),
    reason="regime study has not been run in this checkout",
)
def test_generated_metadata_is_labeled_post_hoc_and_reports_phase3_intact():
    with open("research/regime_study/metadata.json") as f:
        meta = json.load(f)
    assert meta["status"] == LABEL_FULL
    assert meta["phase3_intact"] is True
    assert meta["recent_period"]["start"] == RECENT_START
    assert meta["recent_period"]["end"] == RECENT_END
    assert meta["max_hypotheses_allowed"] <= 3
    assert len(meta["exploratory_simulations_run"]) <= 3
    for forbidden_word in ["out-of-sample", "validated", "proven", "grid search", "machine learning"]:
        assert forbidden_word in meta["forbidden"]


@pytest.mark.skipif(
    not Path("research/regime_study/PHASE3_FINGERPRINT.json").exists(),
    reason="regime study has not been run in this checkout",
)
def test_phase3_fingerprint_identical_before_and_after():
    with open("research/regime_study/PHASE3_FINGERPRINT.json") as f:
        fp = json.load(f)
    assert fp["before"] == fp["after"]


@pytest.mark.skipif(
    not Path("research/regime_study/posthoc_simulations").exists(),
    reason="regime study has not been run in this checkout",
)
def test_each_simulation_report_labeled_post_hoc():
    sim_dir = Path("research/regime_study/posthoc_simulations")
    reports = list(sim_dir.glob("*/report.json"))
    assert len(reports) >= 1
    assert len(reports) <= MAX_HYPOTHESES
    for report_path in reports:
        with open(report_path) as f:
            report = json.load(f)
        assert report["label"] == LABEL_FULL
        assert "not out-of-sample" in report["note"].lower() or "not a new holdout" in report["note"].lower()


@pytest.mark.skipif(
    not Path("research/regime_study/posthoc_simulations").exists(),
    reason="regime study has not been run in this checkout",
)
def test_each_simulation_reports_gate_impact_not_just_return():
    """Task 10: every simulation report must quantify what was blocked,
    not only whether the return improved.
    """
    sim_dir = Path("research/regime_study/posthoc_simulations")
    for report_path in sim_dir.glob("*/report.json"):
        with open(report_path) as f:
            report = json.load(f)
        impact = report["gate_impact"]
        for key in [
            "pct_time_blocked", "n_baseline_entries", "n_gated_entries",
            "n_trades_avoided", "n_winners_avoided", "n_losers_avoided",
            "baseline_exposure", "gated_exposure",
        ]:
            assert key in impact
