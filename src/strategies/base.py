"""Strategy interface.

A strategy's only job is to look at OHLCV history and decide, for each bar,
whether it *wants* to be long (1) or flat (0). It does NOT decide execution
price or timing — that is the backtest engine's job, and it always executes
one bar after the signal is known (see backtesting/engine.py) to avoid
lookahead bias.

Signals must only use information available at or before the current bar's
close. Do not use `.shift(-1)`, future rolling windows, or anything that
peeks ahead — the engine cannot detect this kind of leakage on your behalf.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

# Position states supported in this phase of the project.
FLAT = 0
LONG = 1


class Strategy(ABC):
    """Base class for all strategies.

    Subclasses implement `generate_signals`, returning a pandas Series of
    the same length and index as the input dataframe, containing only FLAT
    or LONG values (no shorting yet).
    """

    name: str = "base"

    def __init__(self, **params: Any):
        self.params = params

    @property
    def warmup_bars(self) -> int:
        """Number of leading bars this strategy needs before its signal is
        considered fully "warmed up" (indicators past their initialization
        transient).

        This is used (via `src/data/splitter.py`'s `slice_with_warmup`) to
        borrow that many bars of history from *before* a split's start (e.g.
        validation borrowing trailing history from train) so the first bars
        of a split don't see an artificially cold/degenerate indicator. It is
        bookkeeping for the caller, not a lookahead mechanism: warm-up bars
        are always chronologically before the target period, never after.

        Default is 0 (no warm-up needed). Strategies with trailing windows
        (moving averages, RSI, momentum lookback, ...) must override this.
        """
        return 0

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Given an OHLCV dataframe (columns: timestamp, open, high, low,
        close, volume), return a Series of desired position state (FLAT or
        LONG) indexed the same as `df`.

        The value at row i must depend only on df.iloc[:i+1] (rows up to and
        including i). The engine will apply this decision starting at the
        *next* bar's open.
        """
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """Parameters recorded into experiment config for reproducibility."""
        return {"name": self.name, "params": self.params}
