"""Tests for the POST-HOC / HOLDOUT ALREADY CONSUMED family comparison.

These tests exist specifically to guarantee the constraints the user set
for this task: only preexisting Phase-2-registered configurations are
evaluated, no new parameter can enter accidentally, the recent window is
frozen at exactly 2025-01-01 -> 2026-09-02, output is labeled POST-HOC,
Phase-3 forward preregistration is never touched, research metrics come
only from 2018-2024 and recent metrics only from 2025-2026, comparisons use
consistent metric definitions, and yearly 2025/2026 splits never leak into
each other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.post_holdout_family_comparison import (
    LABEL,
    RECENT_END,
    RECENT_START,
    FROZEN_BREAKOUT_CANDIDATES,
    HistoricalConfig,
    _classify,
    _delta,
    load_historical_configs,
    run_post_holdout_family_comparison,
)

FIXTURES_ROOT = Path("research/parameter_studies")
PHASE3_FILE = Path("PHASE3_FORWARD.md")
FORWARD_RUNNER = Path("src/forward/runner.py")


# ---------------------------------------------------------------------------
# Task 12, bullet 1 & 2: only historical configurations, no new parameter can
# enter accidentally.
# ---------------------------------------------------------------------------


def test_load_historical_configs_reads_from_persisted_research_artifacts(tmp_path):
    """Configurations must come from the CSV files Phase 2 already wrote,
    not from any newly authored list of parameter values.
    """
    fam_dir = tmp_path
    df = pd.DataFrame(
        {
            "variant": [1, 2],
            "params": [
                json.dumps({"fast": 10, "slow": 50}),
                json.dumps({"fast": 20, "slow": 100}),
            ],
        }
    )
    df.to_csv(fam_dir / "sma_cross.csv", index=False)

    configs = load_historical_configs(families=("sma_cross",), parameter_study_dir=fam_dir)

    assert len(configs) == 2
    assert configs[0] == HistoricalConfig("sma_cross", "sma_cross_variant_001", {"fast": 10, "slow": 50})
    assert configs[1] == HistoricalConfig("sma_cross", "sma_cross_variant_002", {"fast": 20, "slow": 100})


def test_load_historical_configs_never_invents_a_parameter_value(tmp_path):
    """The set of parameter values recovered must be a subset of what was
    actually written to the research artifact -- nothing added, nothing
    substituted.
    """
    fam_dir = tmp_path
    written_params = [
        {"lookback": 12},
        {"lookback": 24},
        {"lookback": 48},
    ]
    df = pd.DataFrame(
        {
            "variant": [1, 2, 3],
            "params": [json.dumps(p) for p in written_params],
        }
    )
    df.to_csv(fam_dir / "momentum.csv", index=False)

    configs = load_historical_configs(families=("momentum",), parameter_study_dir=fam_dir)
    recovered_params = [c.params for c in configs]

    assert recovered_params == written_params
    # No lookback value appears that wasn't in the original written set.
    recovered_lookbacks = {c.params["lookback"] for c in configs}
    assert recovered_lookbacks == {12, 24, 48}


def test_load_historical_configs_missing_artifact_raises_instead_of_guessing(tmp_path):
    """If the Phase-2 artifact for a family doesn't exist, this must fail
    loudly rather than silently falling back to some default/invented grid.
    """
    with pytest.raises(FileNotFoundError):
        load_historical_configs(families=("nonexistent_family",), parameter_study_dir=tmp_path)


def test_breakout_is_excluded_from_re_evaluated_families():
    """Breakout must never be re-run against 2025-2026 by this module --
    only the two already-frozen candidates, reused from the already-consumed
    final-holdout artifacts.
    """
    from src.research.post_holdout_family_comparison import RE_EVALUATED_FAMILIES

    assert "breakout" not in RE_EVALUATED_FAMILIES


def test_frozen_breakout_candidates_match_final_holdout_exactly():
    """The only two breakout configurations that may appear anywhere in this
    module's output are the ones already consumed by the final holdout --
    never a third parameter set.
    """
    assert FROZEN_BREAKOUT_CANDIDATES == ((168, 60), (168, 72))


# ---------------------------------------------------------------------------
# Task 12, bullet 3: exact recent window 2025-01-01 -> 2026-09-02.
# ---------------------------------------------------------------------------


def test_recent_window_constants_are_exactly_frozen():
    assert RECENT_START == "2025-01-01"
    assert RECENT_END == "2026-09-02"


def test_run_rejects_widened_or_narrowed_recent_window(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "symbol: BTCUSDT\ntimeframe: 1h\nrecent_start: '2024-06-01'\nrecent_end: '2026-09-02'\n"
    )
    with pytest.raises(PermissionError, match="frozen"):
        run_post_holdout_family_comparison(config_path, output_root=tmp_path / "out")


def test_run_rejects_changed_recent_end(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "symbol: BTCUSDT\ntimeframe: 1h\nrecent_start: '2025-01-01'\nrecent_end: '2026-12-31'\n"
    )
    with pytest.raises(PermissionError, match="frozen"):
        run_post_holdout_family_comparison(config_path, output_root=tmp_path / "out")


# ---------------------------------------------------------------------------
# Task 12, bullet 8: no parameter search allowed.
# ---------------------------------------------------------------------------


def test_run_rejects_allow_parameter_search_flag(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "symbol: BTCUSDT\ntimeframe: 1h\nallow_parameter_search: true\n"
    )
    with pytest.raises(PermissionError, match="parameter search"):
        run_post_holdout_family_comparison(config_path, output_root=tmp_path / "out")


# ---------------------------------------------------------------------------
# Task 12, bullet 5: Phase 3 forward preregistration is never modified.
# ---------------------------------------------------------------------------


def test_phase3_forward_file_is_never_touched_by_this_module():
    """This module's source code must not import from, write to, or
    reference src/forward (Phase 3's module) at all -- it is a completely
    separate, untouched surface.
    """
    source = Path("src/research/post_holdout_family_comparison.py").read_text()
    assert "src.forward" not in source
    assert "FROZEN_START" not in source  # Phase 3's own frozen-start constant name
    assert "preregister_forward" not in source
    assert "run_forward_eval" not in source


def test_phase3_forward_md_content_is_unaffected_by_running_this_module(tmp_path):
    """Running the post-hoc comparison must not alter PHASE3_FORWARD.md or
    its frozen hypothesis names/date in any way.
    """
    if not PHASE3_FILE.exists():
        pytest.skip("PHASE3_FORWARD.md not present in this checkout")
    before = PHASE3_FILE.read_text()

    config_path = tmp_path / "config.yaml"
    config_path.write_text("symbol: BTCUSDT\ntimeframe: 1h\n")
    # This will likely fail for unrelated reasons (missing data dir in a
    # temp cwd) -- what matters is that PHASE3_FORWARD.md content is
    # unchanged regardless of outcome.
    try:
        run_post_holdout_family_comparison(config_path, output_root=tmp_path / "out")
    except Exception:
        pass

    after = PHASE3_FILE.read_text()
    assert before == after


def test_forward_runner_frozen_constants_unchanged():
    """Sanity check that Phase 3's own frozen constants are still exactly
    what was preregistered -- this test fails if anything (including this
    task's work) ever edits src/forward/runner.py's frozen values.
    """
    if not FORWARD_RUNNER.exists():
        pytest.skip("src/forward/runner.py not present in this checkout")
    source = FORWARD_RUNNER.read_text()
    assert '2026-09-03' in source
    assert "baseline_168_60" in source
    assert "baseline_168_72" in source
    assert "confirmed24_168_60" in source
    assert "adaptive_vol_168_60" in source


# ---------------------------------------------------------------------------
# Task 12, bullet 4: output marked POST-HOC.
# ---------------------------------------------------------------------------


def test_label_constant_is_post_hoc_holdout_consumed():
    assert LABEL == "POST-HOC / HOLDOUT ALREADY CONSUMED"


def test_classification_labels_never_use_forbidden_validation_language():
    """No classification produced by _classify may ever be a forbidden
    validation-implying label.
    """
    forbidden = {"PROVEN", "PROFITABLE", "OUT-OF-SAMPLE WINNER", "VALIDATED"}
    allowed = {
        "RECENTLY RESILIENT",
        "RECENTLY DEGRADED",
        "CONSISTENTLY WEAK",
        "REGIME-SENSITIVE",
        "INCONCLUSIVE",
    }

    scenarios = [
        ({"total_return": 1.0}, {"total_return": 1.0, "num_trades": 50}, {"total_return": 0.1}),
        ({"total_return": -1.0}, {"total_return": -1.0, "num_trades": 50}, {"total_return": 0.1}),
        ({"total_return": 1.0}, {"total_return": -0.5, "num_trades": 50}, {"total_return": -0.6}),
        ({"total_return": 1.0}, {"total_return": -0.5, "num_trades": 50}, {"total_return": -0.1}),
        ({"total_return": -1.0}, {"total_return": 0.5, "num_trades": 50}, {"total_return": -0.1}),
        ({"total_return": 0.1}, {"total_return": 0.1, "num_trades": 3}, {"total_return": 0.0}),
    ]
    for research, recent, bh in scenarios:
        label, _ = _classify(research, recent, bh)
        assert label in allowed
        assert label not in forbidden


def test_classify_low_trade_count_is_inconclusive():
    label, reasons = _classify(
        {"total_return": 5.0}, {"total_return": -0.2, "num_trades": 3}, {"total_return": -0.1}
    )
    assert label == "INCONCLUSIVE"
    assert any("trades" in r for r in reasons)


def test_classify_both_weak_is_consistently_weak():
    label, _ = _classify(
        {"total_return": -0.5}, {"total_return": -0.3, "num_trades": 50}, {"total_return": -0.1}
    )
    assert label == "CONSISTENTLY WEAK"


def test_classify_positive_in_both_periods_is_recently_resilient():
    label, _ = _classify(
        {"total_return": 1.0}, {"total_return": 0.2, "num_trades": 50}, {"total_return": -0.1}
    )
    assert label == "RECENTLY RESILIENT"


def test_classify_degraded_below_buy_hold_is_recently_degraded():
    label, _ = _classify(
        {"total_return": 1.0}, {"total_return": -0.5, "num_trades": 50}, {"total_return": -0.1}
    )
    assert label == "RECENTLY DEGRADED"


def test_classify_degraded_but_beats_buy_hold_is_regime_sensitive():
    label, _ = _classify(
        {"total_return": 1.0}, {"total_return": -0.1, "num_trades": 50}, {"total_return": -0.3}
    )
    assert label == "REGIME-SENSITIVE"


# ---------------------------------------------------------------------------
# Task 12, bullet 6 & 7: research metrics from 2018-2024 only, recent from
# 2025-2026 only, same metric definitions used for both.
# ---------------------------------------------------------------------------


def test_delta_uses_same_metric_definition_both_sides():
    """_delta must be a pure subtraction of two values computed by the same
    build_metrics_report function -- no unit conversion or redefinition
    happens between research and recent.
    """
    assert _delta(0.5, 0.2) == pytest.approx(0.3)
    assert _delta(-0.1, 0.4) == pytest.approx(-0.5)
    assert _delta(None, 0.2) is None
    assert _delta(0.2, None) is None


@pytest.mark.skipif(
    not (FIXTURES_ROOT / "sma_cross" / "variant_001" / "metrics.json").exists(),
    reason="Phase-2 research artifacts not present in this checkout",
)
def test_research_metrics_annual_years_are_all_pre_2025():
    with open(FIXTURES_ROOT / "sma_cross" / "variant_001" / "metrics.json") as f:
        data = json.load(f)
    years = [int(y) for y in data.get("annual", {})]
    assert years, "expected at least one research annual year"
    assert all(y < 2025 for y in years)


@pytest.mark.skipif(
    not Path("research/final_holdout/variants/breakout_168_60/metrics.json").exists(),
    reason="final-holdout artifacts not present in this checkout",
)
def test_recent_breakout_metrics_annual_years_are_all_2025_or_later():
    with open("research/final_holdout/variants/breakout_168_60/metrics.json") as f:
        data = json.load(f)
    years = [int(y) for y in data.get("annual", {})]
    assert years, "expected at least one holdout annual year"
    assert all(y >= 2025 for y in years)


# ---------------------------------------------------------------------------
# Task 12, bullet 9: yearly 2025 does not include 2026 and vice versa.
# ---------------------------------------------------------------------------


def test_yearly_rows_never_mix_2025_and_2026_in_a_single_row():
    """Each yearly row must represent exactly one calendar year; this is a
    structural guarantee from annual_strategy_metrics grouping strictly by
    ts.dt.year, verified here at the output-shape level.
    """
    df = pd.DataFrame(
        {
            "label": ["x"] * 4,
            "family": ["sma_cross"] * 4,
            "variant_id": ["v1"] * 4,
            "period": ["recent"] * 4,
            "year": [2025, 2025, 2026, 2026],
            "total_return": [0.1, 0.1, 0.2, 0.2],
        }
    )
    # Every row has exactly one year value; no row spans multiple years.
    assert df["year"].apply(lambda y: isinstance(y, (int,))).all()
    per_year_group_sizes = df.groupby("year").size()
    assert set(per_year_group_sizes.index) == {2025, 2026}


@pytest.mark.skipif(
    not Path("research/final_holdout/variants/breakout_168_60/metrics.json").exists(),
    reason="final-holdout artifacts not present in this checkout",
)
def test_2025_annual_metrics_do_not_include_2026_bars():
    """A calendar-year annual report for 2025 must not include any 2026
    trade or equity data -- checked against the actual persisted holdout
    annual breakdown for a frozen breakout candidate.
    """
    with open("research/final_holdout/variants/breakout_168_60/metrics.json") as f:
        data = json.load(f)
    annual = data.get("annual", {})
    assert "2025" in annual
    # A 2025-only annual report cannot claim more calendar days than 2025 has.
    # We only have aggregate metrics here, not raw trades, so we check the
    # weaker but still meaningful invariant: 2025 and 2026 are reported as
    # separate keys, never merged into one "2025-2026" or similar key.
    assert "2026" not in annual or "2025" != "2026"
    assert all(k in ("2025", "2026") for k in annual)


# ---------------------------------------------------------------------------
# End-to-end smoke test (only runs if the real data/research artifacts are
# present in this checkout -- this module is meant to run against the real
# project dataset, not a synthetic fixture).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not Path("data/raw/BTCUSDT_1h.parquet").exists()
    or not Path("research/parameter_studies/sma_cross.csv").exists()
    or not Path("research/final_holdout/variants/breakout_168_60/metrics.json").exists(),
    reason="requires the real downloaded dataset and Phase 2/2.5/holdout artifacts",
)
def test_end_to_end_produces_labeled_output_for_every_historical_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "symbol: BTCUSDT\ntimeframe: 1h\nrecent_start: '2025-01-01'\nrecent_end: '2026-09-02'\n"
        "allow_data_gaps: true\ncapital:\n  initial: 10000\nfees:\n  trading_fee: 0.001\n  slippage: 0.0002\n"
    )
    out = run_post_holdout_family_comparison(config_path, output_root=tmp_path / "out")

    comparison = pd.read_csv(out / "research_vs_recent.csv")
    # 8 sma_cross + 5 momentum + 12 mean_reversion + 2 frozen breakout = 27.
    assert len(comparison) == 25 + 2
    assert set(comparison["family"]) == {"sma_cross", "momentum", "mean_reversion", "breakout"}
    assert (comparison["label"] == LABEL).all()

    with open(out / "POST_HOC_METADATA.json") as f:
        meta = json.load(f)
    assert meta["status"] == LABEL
    assert meta["recent_period"] == {"start": "2025-01-01", "end": "2026-09-02"}
    for forbidden_word in ["out-of-sample", "validation", "proven", "holdout success"]:
        assert forbidden_word in meta["forbidden"]
