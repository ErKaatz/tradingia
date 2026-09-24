"""Tests for walk-forward window generation in src/research/walk_forward.py."""

from __future__ import annotations

import pandas as pd
import pytest

from src.research.walk_forward import generate_walk_forward_windows, slice_window


def make_df(timestamps):
    return pd.DataFrame({"timestamp": timestamps, "close": range(len(timestamps))})


def test_rejects_non_positive_train_or_evaluation_months():
    df = make_df(pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"))
    with pytest.raises(ValueError):
        generate_walk_forward_windows(df, train_months=0, evaluation_months=1)
    with pytest.raises(ValueError):
        generate_walk_forward_windows(df, train_months=1, evaluation_months=0)


def test_empty_dataframe_yields_no_windows():
    df = make_df([])
    assert generate_walk_forward_windows(df, train_months=1, evaluation_months=1) == []


def test_no_windows_when_data_shorter_than_one_training_period():
    df = make_df([pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-15", tz="UTC")])
    assert generate_walk_forward_windows(df, train_months=1, evaluation_months=1) == []


def test_windows_walk_forward_contiguously_and_truncate_final_evaluation():
    # generate_walk_forward_windows only ever looks at the first/last
    # timestamp, so a 2-row dataframe spanning the desired range is enough.
    df = make_df([pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-04-15", tz="UTC")])
    windows = generate_walk_forward_windows(df, train_months=1, evaluation_months=1)

    assert len(windows) == 3
    assert windows[0].train_start == pd.Timestamp("2024-01-01", tz="UTC")

    for w in windows:
        # Train and evaluation are adjacent with no gap and no overlap.
        assert w.train_end == w.evaluation_start - pd.Timedelta(nanoseconds=1)
        assert w.train_start < w.train_end
        assert w.evaluation_start <= w.evaluation_end

    for prev, nxt in zip(windows, windows[1:]):
        assert nxt.train_start == prev.train_start + pd.DateOffset(months=1)
        assert nxt.evaluation_start == prev.evaluation_start + pd.DateOffset(months=1)

    # The last window's evaluation period is clamped to the data's final
    # timestamp instead of running past the end of available data.
    assert windows[-1].evaluation_end == pd.Timestamp("2024-04-15", tz="UTC")


def test_slice_window_respects_boundaries_with_no_overlap_or_gap():
    timestamps = pd.date_range("2024-01-01", "2024-03-01", freq="D", tz="UTC")
    df = make_df(timestamps)
    windows = generate_walk_forward_windows(df, train_months=1, evaluation_months=1)
    assert windows

    window = windows[0]
    train, evaluation = slice_window(df, window)

    train_ts = pd.to_datetime(train["timestamp"], utc=True)
    eval_ts = pd.to_datetime(evaluation["timestamp"], utc=True)

    assert (train_ts >= window.train_start).all() and (train_ts <= window.train_end).all()
    assert (eval_ts >= window.evaluation_start).all() and (eval_ts <= window.evaluation_end).all()
    assert set(train_ts).isdisjoint(set(eval_ts))
    assert len(train) > 0 and len(evaluation) > 0
