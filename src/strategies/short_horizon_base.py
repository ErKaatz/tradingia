"""Shared machinery for Phase 4A short-horizon strategies.

Task 11: many short-horizon strategies need to say "if the move hasn't
appeared within N bars, exit" — a timeout exit — in addition to (or instead
of) a signal-based exit. This module provides one small, auditable,
reusable state machine for that pattern so every Family A-F strategy does
not reimplement its own bar-by-bar position-tracking loop.

This is NOT a generic take-profit/stop-loss optimizer (Task 11 explicitly
forbids that): `max_holding_bars` is a single, strategy-declared constant,
never grid-searched by this base class, and the only two exit conditions
supported are "the strategy's own causal exit condition fired" and "held
too long" -- both driven by information available at or before the current
bar's close, exactly like every other signal in this project.
"""

from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from src.strategies.base import FLAT, LONG, Strategy


class TimeoutExitStrategy(Strategy):
    """Base class for strategies that enter on a causal condition and exit
    on EITHER a causal exit condition OR after `max_holding_bars` bars,
    whichever comes first.

    Subclasses implement `entry_condition(df) -> pd.Series[bool]` and
    `exit_condition(df) -> pd.Series[bool]`, both causal (row i may depend
    only on df.iloc[:i+1]). This base class runs the same FLAT/LONG state
    machine every Family A-F strategy needs: while FLAT, enter when
    `entry_condition` is true; while LONG, exit when `exit_condition` is
    true OR the position has been held for `max_holding_bars` bars,
    whichever happens first. A strategy with no natural exit condition can
    return an always-False `exit_condition` series to rely purely on the
    timeout.
    """

    def __init__(self, max_holding_bars: int | None, **params):
        if max_holding_bars is not None and max_holding_bars < 1:
            raise ValueError("max_holding_bars must be >= 1 if provided")
        super().__init__(max_holding_bars=max_holding_bars, **params)
        self.max_holding_bars = max_holding_bars

    @abstractmethod
    def entry_condition(self, df: pd.DataFrame) -> pd.Series:
        """Boolean series: True where a new LONG entry is causally
        justified. Must depend only on df.iloc[:i+1] at row i.
        """
        raise NotImplementedError

    @abstractmethod
    def exit_condition(self, df: pd.DataFrame) -> pd.Series:
        """Boolean series: True where the strategy's own causal exit logic
        (distinct from the timeout) fires. Return an all-False series if
        the strategy relies purely on the timeout.
        """
        raise NotImplementedError

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        entry = self.entry_condition(df)
        exit_ = self.exit_condition(df)

        signal = pd.Series(FLAT, index=df.index, dtype=int)
        state = FLAT
        bars_held = 0
        for i in range(len(df)):
            if state == FLAT:
                if bool(entry.iloc[i]):
                    state = LONG
                    bars_held = 0
            else:
                bars_held += 1
                timed_out = self.max_holding_bars is not None and bars_held >= self.max_holding_bars
                if bool(exit_.iloc[i]) or timed_out:
                    state = FLAT
                    bars_held = 0
            signal.iloc[i] = state
        return signal
