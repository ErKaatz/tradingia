"""Tests for src/fx/data/storage.py."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.fx.data.dataset import build_dataset_metadata
from src.fx.data.schema import FxBar, FxSymbolMetadata, FxTimeframe
from src.fx.data.storage import dataset_dir, load_bars_dataframe, load_metadata, save_dataset


def _bar(ts, **overrides) -> FxBar:
    defaults = dict(
        open=Decimal("1.1000"), high=Decimal("1.1010"), low=Decimal("1.0990"), close=Decimal("1.1005"),
        tick_volume=Decimal("120"), real_volume=None, spread_points=10,
    )
    defaults.update(overrides)
    return FxBar(timestamp_utc=ts, **defaults)


def _symbol_metadata(**overrides) -> FxSymbolMetadata:
    defaults = dict(
        requested_symbol="EURUSD", resolved_symbol="EURUSD", description=None, digits=5,
        point=Decimal("0.00001"), volume_min=Decimal("0.01"), volume_step=Decimal("0.01"),
        volume_max=Decimal("100"), contract_size=Decimal("100000"), tick_size=Decimal("0.00001"),
        tick_value=Decimal("1.0"), currency_base="EUR", currency_profit="USD", currency_margin="EUR",
        broker=None, server=None,
    )
    defaults.update(overrides)
    return FxSymbolMetadata(**defaults)


def test_save_and_load_metadata_roundtrip(tmp_path: Path):
    ts = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    bars = (_bar(ts),)
    metadata = build_dataset_metadata(
        bars, FxTimeframe.H1, _symbol_metadata(),
        datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    out_dir = save_dataset(bars, metadata, root=tmp_path)
    assert out_dir == tmp_path / "EURUSD" / "H1"

    loaded = load_metadata("EURUSD", "H1", root=tmp_path)
    assert loaded.dataset_sha256 == metadata.dataset_sha256
    assert loaded.bar_count == 1


def test_save_and_load_bars_dataframe_roundtrip(tmp_path: Path):
    ts = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    bars = (_bar(ts),)
    metadata = build_dataset_metadata(
        bars, FxTimeframe.H1, _symbol_metadata(),
        datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    save_dataset(bars, metadata, root=tmp_path)
    df = load_bars_dataframe("EURUSD", "H1", root=tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["close"] == "1.1005"  # stored as string, not float


def test_load_metadata_missing_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        load_metadata("NOPE", "H1", root=Path("/tmp/definitely-does-not-exist-fx"))


def test_dataset_dir_uses_uppercase_symbol(tmp_path: Path):
    assert dataset_dir("eurusd", "H1", root=tmp_path) == tmp_path / "EURUSD" / "H1"
