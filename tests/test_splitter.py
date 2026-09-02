"""Tests for chronological data splitting."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.splitter import chronological_split


def make_df(n):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
            "close": range(n),
        }
    )


def test_split_sizes_match_fractions():
    df = make_df(100)
    split = chronological_split(df, train_frac=0.6, validation_frac=0.2, test_frac=0.2)
    assert len(split.train) == 60
    assert len(split.validation) == 20
    assert len(split.test) == 20


def test_split_is_chronological_not_shuffled():
    df = make_df(10)
    split = chronological_split(df, train_frac=0.5, validation_frac=0.3, test_frac=0.2)
    assert split.train["timestamp"].max() < split.validation["timestamp"].min()
    assert split.validation["timestamp"].max() < split.test["timestamp"].min()
    # And no overlap / no missing rows.
    total = len(split.train) + len(split.validation) + len(split.test)
    assert total == len(df)


def test_split_fractions_must_sum_to_one():
    df = make_df(10)
    with pytest.raises(ValueError):
        chronological_split(df, train_frac=0.6, validation_frac=0.6, test_frac=0.2)


def test_split_rejects_negative_fraction():
    df = make_df(10)
    with pytest.raises(ValueError):
        chronological_split(df, train_frac=-0.1, validation_frac=0.9, test_frac=0.2)


def test_split_empty_dataframe_raises():
    df = make_df(0)
    with pytest.raises(ValueError):
        chronological_split(df)
