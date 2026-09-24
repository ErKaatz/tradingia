from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

from src.fx.research.contracts import ExperimentManifest, ResearchTradeRecord, fingerprint, strict_json, write_bundle


UTC = timezone.utc


def _trade() -> ResearchTradeRecord:
    return ResearchTradeRecord(experiment_id="exp", run_id="run", variant_id="variant", split="development", symbol="EURUSD", timeframe="M15", side="long", lots=Decimal("0.01"), signal_timestamp=datetime(2025, 1, 1, tzinfo=UTC), entry_timestamp=datetime(2025, 1, 1, 0, 15, tzinfo=UTC), exit_timestamp=datetime(2025, 1, 1, 1, 15, tzinfo=UTC), entry_reference_price=Decimal("1"), entry_bid=Decimal("1"), entry_ask=Decimal("1"), entry_execution_price=Decimal("1"), exit_reference_price=Decimal("1"), exit_bid=Decimal("1"), exit_ask=Decimal("1"), exit_execution_price=Decimal("1"), gross_reference_pnl=Decimal("10"), spread_cost=Decimal("2"), slippage_cost=Decimal("3"), commission_cost=Decimal("4"), swap_cost=Decimal("1"), net_pnl=Decimal("0"), bars_held=4, duration_seconds=3600)


def _manifest() -> ExperimentManifest:
    return ExperimentManifest("exp", "run", "abc", "main", "dataset", "cost", "nonspread", "prereg", "EURUSD", "M15", "development", ("variant",), {"next_bar": True}, {"balance": "100"}, "RESEARCH_RULES.md", datetime(2025, 1, 1, tzinfo=UTC))


def test_trade_contract_identity_and_utc_enforced():
    assert _trade().to_dict()["entry_utc_hour"] == 0
    with pytest.raises(ValueError, match="accounting"):
        ResearchTradeRecord(**(_trade().__dict__ | {"net_pnl": Decimal("1")}))
    with pytest.raises(ValueError, match="UTC-aware"):
        ResearchTradeRecord(**(_trade().__dict__ | {"entry_timestamp": datetime(2025, 1, 1)}))


def test_manifest_and_json_are_deterministic_and_strict(tmp_path):
    manifest = _manifest()
    assert fingerprint(manifest.identity_dict()) == fingerprint(manifest.identity_dict())
    with pytest.raises(ValueError):
        strict_json({"bad": float("nan")})
    write_bundle(tmp_path, manifest, {"experiment_id": "exp", "run_id": "run"}, (_trade(),))
    assert json.loads((tmp_path / "manifest.json").read_text())["manifest_sha256"]
    assert (tmp_path / "trades.jsonl").read_text().count("\n") == 1
