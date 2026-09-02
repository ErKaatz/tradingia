"""Buy and Hold benchmark strategy.

Goes long on the first bar and stays long for the entire dataset. This is
not meant to be "the strategy to beat" in a sophisticated sense — it is a
sanity-check benchmark. Any active strategy that cannot at least be
understood relative to this baseline should be treated with suspicion.
"""

from __future__ import annotations

import pandas as pd

from src.strategies.base import LONG, Strategy


class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(LONG, index=df.index, dtype=int)
