"""Local caching layer for OHLCV data.

Downloading from a provider is slow and rate-limited; this module persists
raw candles to local parquet files under `data/raw/` so experiments are
reproducible even if the upstream API changes or becomes unavailable, and so
repeated backtests don't re-hit the network.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.providers import OHLCV_COLUMNS, DataProvider

DEFAULT_RAW_DIR = Path("data/raw")


def cache_path(symbol: str, timeframe: str, raw_dir: Path = DEFAULT_RAW_DIR) -> Path:
    filename = f"{symbol.upper()}_{timeframe}.parquet"
    return raw_dir / filename


def download_and_cache(
    provider: DataProvider,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    raw_dir: Path = DEFAULT_RAW_DIR,
) -> Path:
    """Fetch OHLCV from `provider` and merge it into the local cache file.

    Existing cached candles are preserved; only the newly fetched range is
    merged in, deduplicated by timestamp.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(symbol, timeframe, raw_dir)

    new_df = provider.fetch_ohlcv(symbol, timeframe, start, end)

    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = (
        combined.drop_duplicates(subset="timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    combined.to_parquet(path, index=False)
    return path


def load_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime | None = None,
    end: datetime | None = None,
    raw_dir: Path = DEFAULT_RAW_DIR,
) -> pd.DataFrame:
    """Load cached OHLCV data for a symbol/timeframe, optionally sliced by
    date range. Raises if no cached data exists.
    """
    path = cache_path(symbol, timeframe, raw_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"No cached data at {path}. Run `download-data` first."
        )
    df = pd.read_parquet(path)
    if start is not None:
        start_ts = pd.Timestamp(start)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        df = df[df["timestamp"] >= start_ts]
    if end is not None:
        end_ts = pd.Timestamp(end)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        df = df[df["timestamp"] <= end_ts]
    return df.reset_index(drop=True)


def dataset_hash(df: pd.DataFrame) -> str:
    """Stable content hash of an OHLCV dataframe, used to record exactly
    which data an experiment ran on (for reproducibility bookkeeping).
    """
    payload = df[OHLCV_COLUMNS].to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
