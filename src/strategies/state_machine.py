"""Shared sequential FLAT/LONG state machine.

`Breakout`, `MeanReversion`, and `volatility_filter.py` each need to walk a
dataframe bar by bar, deciding at each row whether to hold LONG or FLAT based
on a per-bar transition rule that may depend on the state carried over from
the previous row. That per-row dependency on the *previous output* is exactly
why this cannot be vectorized away -- pandas has no built-in "fold" over a
Series -- so instead of every caller hand-rolling its own `state = FLAT; for
i in range(len(df)): ...` loop, they share this one.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from src.strategies.base import FLAT, LONG

Transition = Callable[[int, int], int]


def run_sequential_flat_long(length: int, transition: Transition) -> pd.Series:
    """Build a length-`length` FLAT/LONG signal by folding `transition` over
    the row indices in order.

    `transition(state, i)` receives the state held going into row `i` (the
    output written at row `i - 1`, or FLAT before row 0) and returns the
    state to hold *at* row `i`, which becomes the next call's `state`. The
    returned Series has a default RangeIndex; callers reindex it onto their
    dataframe's actual index.
    """
    signal = pd.Series(FLAT, index=range(length), dtype=int)
    state = FLAT
    for i in range(length):
        state = transition(state, i)
        signal.iloc[i] = state
    return signal


def run_entry_exit_state_machine(
    length: int,
    should_enter: Callable[[int], bool],
    should_exit: Callable[[int], bool],
) -> pd.Series:
    """Common case of `run_sequential_flat_long`: enter LONG from FLAT when
    `should_enter(i)` holds, exit back to FLAT from LONG when `should_exit(i)`
    holds. Neither callback is consulted outside its matching state (an
    already-LONG bar never re-checks `should_enter`, and vice versa).
    """

    def transition(state: int, i: int) -> int:
        if state == FLAT and should_enter(i):
            return LONG
        if state != FLAT and should_exit(i):
            return FLAT
        return state

    return run_sequential_flat_long(length, transition)
