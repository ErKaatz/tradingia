"""Local storage for normalized FX historical datasets (Phase 5A).

Layout, one directory per symbol/timeframe under `data/fx/` (gitignored,
same convention as the existing `data/raw/` crypto cache):

    data/fx/<SYMBOL>/<TIMEFRAME>/bars.parquet
    data/fx/<SYMBOL>/<TIMEFRAME>/metadata.json

`bars.parquet` holds exactly the deterministic bar fields (see
`dataset.py`); `metadata.json` holds the full `FxDatasetMetadata`,
including its `dataset_sha256`. Saving never silently overwrites a
dataset whose fingerprint would change without the caller being told --
`save_dataset` always writes the new metadata's fingerprint, and it is
the caller's responsibility (see `mt5_provider.py`) to have decided
whether an overwrite is intended (e.g. extending the requested range).

No incremental/partial fetch merging is implemented here (Phase 5A
defers that -- see PHASE5A_STATUS.md's Storage/Cache section); each
`save_dataset` call writes one complete dataset for its requested range.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pandas as pd

from src.fx.data.dataset import FxDatasetMetadata
from src.fx.data.schema import FxBar

DEFAULT_FX_DATA_ROOT = Path("data/fx")

_BAR_COLUMNS = ["timestamp_utc", "open", "high", "low", "close", "tick_volume", "real_volume", "spread_points"]


def dataset_dir(symbol: str, timeframe: str, root: Path = DEFAULT_FX_DATA_ROOT) -> Path:
    return root / symbol.upper() / timeframe


def _bars_to_dataframe(bars: tuple[FxBar, ...]) -> pd.DataFrame:
    rows = [
        {
            "timestamp_utc": b.timestamp_utc,
            "open": str(b.open),
            "high": str(b.high),
            "low": str(b.low),
            "close": str(b.close),
            "tick_volume": str(b.tick_volume),
            "real_volume": str(b.real_volume) if b.real_volume is not None else None,
            "spread_points": b.spread_points,
        }
        for b in bars
    ]
    return pd.DataFrame(rows, columns=_BAR_COLUMNS)


def save_dataset(
    bars: tuple[FxBar, ...],
    metadata: FxDatasetMetadata,
    root: Path = DEFAULT_FX_DATA_ROOT,
) -> Path:
    """Write `bars.parquet` + `metadata.json` for one symbol/timeframe.

    Prices/volumes are stored as strings in the parquet file (not
    `float64`) so re-loading never reintroduces binary floating-point
    noise into values that were exact `Decimal`s -- `load_dataset`
    converts them back to `Decimal` on read.
    """
    out_dir = dataset_dir(metadata.resolved_symbol, metadata.timeframe, root)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _bars_to_dataframe(bars)
    df.to_parquet(out_dir / "bars.parquet", index=False)

    (out_dir / "metadata.json").write_text(json.dumps(metadata.to_json_dict(), indent=2, sort_keys=True) + "\n")
    return out_dir


def load_metadata(symbol: str, timeframe: str, root: Path = DEFAULT_FX_DATA_ROOT) -> FxDatasetMetadata:
    path = dataset_dir(symbol, timeframe, root) / "metadata.json"
    if not path.exists():
        raise FileNotFoundError(f"no FX dataset metadata at {path}")
    raw = json.loads(path.read_text())
    known_fields = {f.name for f in fields(FxDatasetMetadata)}
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    return FxDatasetMetadata(**filtered)


def load_bars_dataframe(symbol: str, timeframe: str, root: Path = DEFAULT_FX_DATA_ROOT) -> pd.DataFrame:
    """Load the raw stored dataframe (string-encoded prices/volumes,
    exactly as saved). Callers that need `FxBar` objects should use
    `mt5_provider.py`'s round-trip helpers rather than parsing this
    dataframe by hand, to keep exactly one place responsible for the
    string<->Decimal conversion.
    """
    path = dataset_dir(symbol, timeframe, root) / "bars.parquet"
    if not path.exists():
        raise FileNotFoundError(f"no FX dataset at {path}")
    return pd.read_parquet(path)
