"""Tests for the shared timeout-exit state machine used by Phase 4A families."""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.base import FLAT, LONG
from src.strategies.short_horizon_base import TimeoutExitStrategy


class _AlwaysEnterNeverExit(TimeoutExitStrategy):
    name = "test_always_enter"

    def entry_condition(self, df):
        return pd.Series(True, index=df.index)

    def exit_condition(self, df):
        return pd.Series(False, index=df.index)


class _EnterOnceExitOnFlag(TimeoutExitStrategy):
    name = "test_enter_once_exit_on_flag"

    def __init__(self, max_holding_bars, exit_at_index):
        super().__init__(max_holding_bars=max_holding_bars)
        self._exit_at_index = exit_at_index

    def entry_condition(self, df):
        out = pd.Series(False, index=df.index)
        out.iloc[0] = True
        return out

    def exit_condition(self, df):
        out = pd.Series(False, index=df.index)
        if self._exit_at_index is not None:
            out.iloc[self._exit_at_index] = True
        return out


def make_df(n):
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")})


def test_rejects_max_holding_bars_below_one():
    with pytest.raises(ValueError):
        _AlwaysEnterNeverExit(max_holding_bars=0)


def test_no_timeout_relies_purely_on_exit_condition():
    df = make_df(10)
    strat = _EnterOnceExitOnFlag(max_holding_bars=None, exit_at_index=5)
    signal = strat.generate_signals(df)
    assert list(signal) == [LONG, LONG, LONG, LONG, LONG, FLAT, FLAT, FLAT, FLAT, FLAT]


def test_timeout_exits_even_without_exit_condition_firing():
    df = make_df(10)
    strat = _EnterOnceExitOnFlag(max_holding_bars=3, exit_at_index=None)
    signal = strat.generate_signals(df)
    # Enter at bar 0, held for exactly 3 bars (0,1,2), exits at bar 3.
    assert signal.iloc[0] == LONG
    assert signal.iloc[1] == LONG
    assert signal.iloc[2] == LONG
    assert (signal.iloc[3:] == FLAT).all()


def test_exit_condition_fires_before_timeout():
    df = make_df(10)
    strat = _EnterOnceExitOnFlag(max_holding_bars=8, exit_at_index=2)
    signal = strat.generate_signals(df)
    assert signal.iloc[0] == LONG
    assert signal.iloc[1] == LONG
    assert signal.iloc[2] == FLAT  # exit condition fired before the 8-bar timeout


def test_timeout_fires_before_exit_condition():
    df = make_df(10)
    strat = _EnterOnceExitOnFlag(max_holding_bars=2, exit_at_index=8)
    signal = strat.generate_signals(df)
    assert signal.iloc[0] == LONG
    assert signal.iloc[1] == LONG
    assert signal.iloc[2] == FLAT  # timeout (2 bars held) fires well before index 8's exit flag


def test_always_enter_strategy_stays_long_with_no_timeout():
    df = make_df(5)
    strat = _AlwaysEnterNeverExit(max_holding_bars=None)
    signal = strat.generate_signals(df)
    assert (signal == LONG).all()


def test_can_reenter_after_timeout_exit():
    df = make_df(10)
    strat = _AlwaysEnterNeverExit(max_holding_bars=3)
    signal = strat.generate_signals(df)
    # Enters at 0, held for exactly 3 bars (0,1,2), exits at bar 3 (exit and
    # entry are mutually exclusive within one bar -- no same-bar re-entry),
    # re-enters at bar 4 with a fresh timeout.
    assert signal.iloc[0] == LONG
    assert signal.iloc[1] == LONG
    assert signal.iloc[2] == LONG
    assert signal.iloc[3] == FLAT
    assert signal.iloc[4] == LONG
