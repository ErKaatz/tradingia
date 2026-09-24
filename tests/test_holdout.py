"""Tests for the final-holdout guardrails in src/research/holdout.py."""

from __future__ import annotations

import pandas as pd
import pytest

from src.research.holdout import guard_final_holdout_evaluation, split_final_holdout


def make_df(timestamps):
    return pd.DataFrame({"timestamp": timestamps, "close": range(len(timestamps))})


def test_split_final_holdout_partitions_on_cutoff():
    timestamps = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    df = make_df(timestamps)
    result = split_final_holdout(df, holdout_start="2024-01-04")

    assert list(result.research["close"]) == [0, 1, 2]
    assert list(result.final_holdout["close"]) == [3, 4, 5]
    assert result.cutoff == pd.Timestamp("2024-01-04", tz="UTC")


def test_split_final_holdout_raises_when_research_period_empty():
    timestamps = pd.date_range("2025-06-01", periods=3, freq="D", tz="UTC")
    df = make_df(timestamps)
    with pytest.raises(ValueError, match="research period is empty"):
        split_final_holdout(df, holdout_start="2025-01-01")


def test_split_final_holdout_accepts_naive_and_aware_cutoff_equivalently():
    timestamps = pd.date_range("2024-01-01", periods=6, freq="D", tz="UTC")
    df = make_df(timestamps)
    naive = split_final_holdout(df, holdout_start="2024-01-04")
    aware = split_final_holdout(df, holdout_start=pd.Timestamp("2024-01-04", tz="UTC"))

    assert naive.cutoff == aware.cutoff
    pd.testing.assert_frame_equal(naive.research, aware.research)
    pd.testing.assert_frame_equal(naive.final_holdout, aware.final_holdout)


def test_split_final_holdout_allows_empty_holdout_side():
    # Every row is before the cutoff -- final_holdout is legitimately empty,
    # only the research side is required to be non-empty.
    timestamps = pd.date_range("2020-01-01", periods=4, freq="D", tz="UTC")
    df = make_df(timestamps)
    result = split_final_holdout(df, holdout_start="2025-01-01")
    assert result.final_holdout.empty
    assert len(result.research) == 4


def test_guard_allows_when_allow_is_true_even_with_holdout_rows_present():
    timestamps = pd.date_range("2025-06-01", periods=3, freq="D", tz="UTC")
    df = make_df(timestamps)
    guard_final_holdout_evaluation(df, holdout_start="2025-01-01", allow=True)  # must not raise


def test_guard_allows_empty_dataframe_regardless_of_allow():
    empty = make_df([])
    guard_final_holdout_evaluation(empty, holdout_start="2025-01-01", allow=False)  # must not raise


def test_guard_passes_when_no_row_reaches_the_cutoff():
    timestamps = pd.date_range("2020-01-01", periods=4, freq="D", tz="UTC")
    df = make_df(timestamps)
    guard_final_holdout_evaluation(df, holdout_start="2025-01-01", allow=False)  # must not raise


def test_guard_raises_permission_error_when_holdout_rows_present_and_not_allowed():
    timestamps = pd.date_range("2024-12-30", periods=4, freq="D", tz="UTC")
    df = make_df(timestamps)  # last two rows fall on/after 2025-01-01
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT"):
        guard_final_holdout_evaluation(df, holdout_start="2025-01-01", allow=False)
