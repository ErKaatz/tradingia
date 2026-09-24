"""Tests for the realized-volatility entry filter in
src/research/volatility_filter.py."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import FLAT, LONG
from src.research.volatility_filter import apply_realized_volatility_entry_filter


def make_df(closes):
    return pd.DataFrame({"close": closes})


def test_rejects_window_below_two():
    df = make_df([100, 100, 100])
    signals = pd.Series([FLAT, FLAT, LONG])
    with pytest.raises(ValueError):
        apply_realized_volatility_entry_filter(df, signals, window=1)


def test_rejects_min_vol_greater_than_max_vol():
    df = make_df([100, 100, 100])
    signals = pd.Series([FLAT, FLAT, LONG])
    with pytest.raises(ValueError):
        apply_realized_volatility_entry_filter(df, signals, window=2, min_vol=0.5, max_vol=0.1)


def test_entry_blocked_before_volatility_is_computable_even_with_no_thresholds():
    # window=2 means realized volatility is NaN for the first two rows
    # regardless of price data; the filter must deny entry there even with
    # min_vol=max_vol=None, since it cannot verify anything about volatility
    # at all yet.
    df = make_df([100, 100, 100, 100])
    signals = pd.Series([LONG, LONG, LONG, LONG])
    out = apply_realized_volatility_entry_filter(df, signals, window=2)
    assert out.iloc[0] == FLAT
    assert out.iloc[1] == FLAT


def test_entry_suppressed_while_volatility_stays_below_min_vol():
    # Flat prices -> zero realized volatility for every window -> an entry
    # that requires min_vol=0.001 is denied at every bar it's re-attempted.
    df = make_df([100, 100, 100, 100, 100])
    signals = pd.Series([FLAT, FLAT, LONG, LONG, LONG])
    out = apply_realized_volatility_entry_filter(df, signals, window=2, min_vol=0.001)
    assert (out == FLAT).all()


def test_entry_allowed_once_volatility_exceeds_min_vol():
    df = make_df([100, 100, 100, 100, 200])
    signals = pd.Series([FLAT, FLAT, LONG, LONG, LONG])
    out = apply_realized_volatility_entry_filter(df, signals, window=2, min_vol=0.2)
    # Volatility stays at 0 (flat prices) through index 3, so the entry
    # attempted at index 2 is denied and re-attempted at 3 -- still denied.
    assert out.iloc[2] == FLAT
    assert out.iloc[3] == FLAT
    # The 100 -> 200 jump at index 4 raises realized volatility above
    # min_vol, so the still-pending LONG signal is finally let through.
    assert out.iloc[4] == LONG


def test_entry_suppressed_when_volatility_exceeds_max_vol():
    # A price spike right where entry is attempted pushes realized
    # volatility above a low max_vol ceiling, so entry is denied at every
    # bar it's re-attempted (volatility stays elevated for two bars after
    # the spike because window=2 still includes it).
    df = make_df([100, 100, 200, 100, 100])
    signals = pd.Series([FLAT, FLAT, LONG, LONG, LONG])
    out = apply_realized_volatility_entry_filter(df, signals, window=2, max_vol=0.1)
    assert (out == FLAT).all()


def test_filter_never_forces_an_exit_once_long_is_held():
    # Realized volatility for this price path (spike then reversal) is
    # ~0.49 at index 2, ~0.98 at index 3, and ~0.49 at index 4. A
    # [0.4, 0.6] band lets entry through at index 2 but would deny a *new*
    # entry at index 3 (0.98 is out of range). Bar 3 is a continuation of
    # an existing LONG, not a new entry, so the filter must not force it
    # back to FLAT despite volatility being "out of range" there.
    df = make_df([100, 100, 200, 100, 100])
    signals = pd.Series([FLAT, FLAT, LONG, LONG, LONG])
    out = apply_realized_volatility_entry_filter(df, signals, window=2, min_vol=0.4, max_vol=0.6)
    assert out.iloc[2] == LONG  # entry allowed: volatility (~0.49) is in range
    assert out.iloc[3] == LONG  # held despite volatility (~0.98) now out of range
    assert out.iloc[4] == LONG


def test_filter_does_not_suppress_flat_signals():
    df = make_df([100, 100, 100, 100])
    signals = pd.Series([FLAT, FLAT, FLAT, FLAT])
    out = apply_realized_volatility_entry_filter(df, signals, window=2, min_vol=100.0)
    assert (out == FLAT).all()
