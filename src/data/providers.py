"""Data provider abstractions.

The rest of the system never talks to an exchange API directly. It talks to
the `DataProvider` interface, so the underlying source (Binance public REST,
a different exchange, a local file dump, ...) can be swapped without
touching strategies, the backtest engine, or the CLI.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd
import requests

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


class BinancePublicProvider(DataProvider):
    """Fetches historical klines from Binance's public REST API.

    No API key is required for public market data. This class only reads
    historical candles; it never places orders.
    """

    BASE_URL = "https://api.binance.com/api/v3/klines"

    # Binance interval strings map 1:1 to our timeframe strings for the ones
    # we currently support. Kept as an explicit map (not a passthrough) so
    # unsupported timeframes fail loudly instead of silently hitting the API
    # with a bogus value.
    _TIMEFRAME_TO_BINANCE = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }

    _MAX_LIMIT = 1000  # Binance API cap per request

    def __init__(self, session: requests.Session | None = None, request_pause_s: float = 0.2):
        self._session = session or requests.Session()
        self._request_pause_s = request_pause_s

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if timeframe not in self._TIMEFRAME_TO_BINANCE:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {sorted(self._TIMEFRAME_TO_BINANCE)}"
            )
        interval = self._TIMEFRAME_TO_BINANCE[timeframe]

        start_ms = _to_ms(start)
        end_ms = _to_ms(end)

        rows: list[list] = []
        cursor = start_ms
        while cursor < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": self._MAX_LIMIT,
            }
            resp = self._session.get(self.BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            last_open_time = batch[-1][0]
            next_cursor = last_open_time + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < self._MAX_LIMIT:
                break
            time.sleep(self._request_pause_s)

        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        df = pd.DataFrame(
            rows,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "num_trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[OHLCV_COLUMNS].sort_values("timestamp").reset_index(drop=True)
        # Deduplicate in case of overlapping pagination boundaries.
        df = df.drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
        return df


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
