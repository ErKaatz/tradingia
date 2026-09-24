"""Strict, strategy-neutral artifact contract for future FX research."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib, json
from pathlib import Path
from typing import Any

def _utc(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{name} must be UTC-aware")
    return value.isoformat()

def _clean(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return _utc(value, "timestamp")
    if isinstance(value, dict): return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_clean(v) for v in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")): raise ValueError("NaN/Infinity forbidden")
    return value

def strict_json(value: Any) -> bytes:
    return json.dumps(_clean(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def fingerprint(value: Any) -> str: return hashlib.sha256(strict_json(value)).hexdigest()

@dataclass(frozen=True)
class ResearchTradeRecord:
    experiment_id: str; run_id: str; variant_id: str; split: str; symbol: str; timeframe: str; side: str; lots: Decimal
    signal_timestamp: datetime; entry_timestamp: datetime; exit_timestamp: datetime
    entry_reference_price: Decimal; entry_bid: Decimal; entry_ask: Decimal; entry_execution_price: Decimal
    exit_reference_price: Decimal; exit_bid: Decimal; exit_ask: Decimal; exit_execution_price: Decimal
    gross_reference_pnl: Decimal; spread_cost: Decimal; slippage_cost: Decimal; commission_cost: Decimal; swap_cost: Decimal; net_pnl: Decimal
    bars_held: int; duration_seconds: int; insolvency_terminal_context: bool = False
    def __post_init__(self):
        for name in ("experiment_id","run_id","variant_id","split","symbol","timeframe"): 
            if not getattr(self,name): raise ValueError(f"{name} required")
        if self.side not in {"long","short"}: raise ValueError("side must be long/short")
        if self.lots <= 0 or self.bars_held < 0 or self.duration_seconds < 0: raise ValueError("invalid size/duration")
        for name in ("signal_timestamp","entry_timestamp","exit_timestamp"): _utc(getattr(self,name), name)
        if self.exit_timestamp < self.entry_timestamp: raise ValueError("exit before entry")
        expected=self.gross_reference_pnl-self.spread_cost-self.slippage_cost-self.commission_cost-self.swap_cost
        if self.net_pnl != expected: raise ValueError("trade accounting identity violated")
    def to_dict(self) -> dict[str,Any]:
        d=_clean(asdict(self)); d["entry_utc_hour"]=self.entry_timestamp.hour; d["exit_utc_hour"]=self.exit_timestamp.hour; return d

@dataclass(frozen=True)
class ExperimentManifest:
    experiment_id: str; run_id: str; code_commit: str; branch: str; dataset_sha256: str; cost_profile_sha256: str; non_spread_cost_sha256: str; preregistration_sha256: str; symbol: str; timeframe: str; split: str; variant_registry: tuple[str,...]; execution_assumptions: dict[str,Any]; account_assumptions: dict[str,Any]; research_rules_reference: str; created_at_utc: datetime
    def __post_init__(self):
        for name in ("experiment_id","run_id","code_commit","branch","dataset_sha256","cost_profile_sha256","non_spread_cost_sha256","preregistration_sha256","symbol","timeframe","split","research_rules_reference"):
            if not getattr(self,name): raise ValueError(f"{name} required")
        if not self.variant_registry: raise ValueError("variant_registry required")
        _utc(self.created_at_utc,"created_at_utc")
    def identity_dict(self):
        d=_clean(asdict(self)); d.pop("created_at_utc"); return d
    def to_dict(self): return _clean(asdict(self)) | {"manifest_sha256": fingerprint(self.identity_dict())}

def write_bundle(root: Path, manifest: ExperimentManifest, summary: dict[str,Any], trades: list[ResearchTradeRecord]) -> Path:
    if any(t.experiment_id != manifest.experiment_id or t.run_id != manifest.run_id for t in trades): raise ValueError("trade/manifest identity mismatch")
    root.mkdir(parents=True,exist_ok=True)
    (root/"manifest.json").write_bytes(strict_json(manifest.to_dict())+b"\n")
    (root/"summary.json").write_bytes(strict_json(summary)+b"\n")
    (root/"trades.jsonl").write_bytes(b"".join(strict_json(t.to_dict())+b"\n" for t in trades))
    return root
