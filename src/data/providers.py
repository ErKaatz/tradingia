"""Data provider abstractions.

The rest of the system never talks to a market-data source directly. It
talks to the `DataProvider` interface, so the underlying source (a broker
API, a local file dump, ...) can be swapped without touching strategies,
the backtest engine, or the CLI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class DataProvider(ABC):
    """Source of historical OHLCV candles."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return a DataFrame with columns OHLCV_COLUMNS, sorted ascending by
        timestamp, with `timestamp` as UTC tz-aware pandas Timestamps.
        """
        raise NotImplementedError
