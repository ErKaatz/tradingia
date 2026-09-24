"""Fail-closed runner for the preregistered Phase 5D remediation batch."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from src.fx.backtesting.costs import FixedPointsSlippage
from src.fx.backtesting.engine import FxBacktestEngine, FxEngineConfig
from src.fx.backtesting.models import TargetPosition
from src.fx.backtesting.metrics_adapter import to_neutral_backtest_result
from src.metrics.metrics import build_metrics_report
from src.fx.cost_calibration import FrozenNonSpreadCosts, SpreadBucket, SpreadCalibration, apply_hourly_p95_spread
from src.fx.data.schema import FxBar
from src.fx.data.storage import load_metadata
from src.fx.strategies.baselines import directional_control, ema_trend, session_breakout, signed_momentum, zscore_mean_reversion

RESEARCH_SHA = "5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59"
COST_DATASET_SHA = "0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9"
SPREAD_SHA = "a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575"
NON_SPREAD_SHA = "9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36"
SPLITS = {"development": ("2022-09-01", "2024-08-30 23:45:00"), "validation": ("2024-09-02", "2025-08-29 23:45:00")}
RUN_ID = "phase5d_run2_insolvency_policy"


def _bars() -> tuple[FxBar, ...]:
    df = pd.read_parquet("data/fx/research/EURUSD/M15/bars.parquet")
    return tuple(FxBar(pd.Timestamp(r.timestamp_utc).to_pydatetime(), Decimal(r.open), Decimal(r.high), Decimal(r.low), Decimal(r.close), Decimal(r.tick_volume), Decimal(r.real_volume) if pd.notna(r.real_volume) else None, int(r.spread_points) if pd.notna(r.spread_points) else None) for r in df.itertuples())


def _profile() -> tuple[SpreadCalibration, FrozenNonSpreadCosts]:
    raw = json.loads(Path("data/fx/EURUSD/M15/phase5c_cost_report.json").read_text())
    if raw["dataset_sha256"] != COST_DATASET_SHA or raw["non_spread_cost_fingerprint"] != NON_SPREAD_SHA:
        raise ValueError("Phase 5C fingerprint mismatch")
    p = raw["spread_calibration"]
    calibration = SpreadCalibration(p["dataset_sha256"], tuple(SpreadBucket(b["hour"], b["n"], b["missing"], Decimal(b["median"]) if b["median"] is not None else None, Decimal(b["p95"]) if b["p95"] is not None else None) for b in p["buckets"]), p["overall_observations"], p["overall_missing"], Decimal(p["overall_p95"]) if p["overall_p95"] else None, p["minimum_observations_per_hour"])
    if calibration.fingerprint() != SPREAD_SHA:
        raise ValueError("spread profile fingerprint mismatch")
    n = raw["non_spread_costs"]
    terms = FrozenNonSpreadCosts(n["symbol"], n["account_currency"], Decimal(n["commission_per_lot_per_side"]), Decimal(n["long_swap_per_lot"]), Decimal(n["short_swap_per_lot"]), n["triple_swap_weekday"], n["source"])
    if terms.fingerprint() != NON_SPREAD_SHA:
        raise ValueError("non-spread profile fingerprint mismatch")
    return calibration, terms


def _variants(bars):
    return {"trend-ema-20-100": ("trend", {"fast":20,"slow":100}, ema_trend(bars,20,100)), "trend-ema-50-200": ("trend", {"fast":50,"slow":200}, ema_trend(bars,50,200)), "mean-z-20-2": ("mean_reversion", {"window":20,"threshold":2.0}, zscore_mean_reversion(bars,20,2.0)), "mean-z-40-2": ("mean_reversion", {"window":40,"threshold":2.0}, zscore_mean_reversion(bars,40,2.0)), "momentum-4": ("momentum", {"lookback":4}, signed_momentum(bars,4)), "momentum-16": ("momentum", {"lookback":16}, signed_momentum(bars,16)), "session-breakout-00-06": ("session", {"range_start":0,"trade_start":6}, session_breakout(bars,0,6)), "session-breakout-07-10": ("session", {"range_start":7,"trade_start":10}, session_breakout(bars,7,10)), "control-flat": ("control", {}, directional_control(bars,TargetPosition.FLAT)), "control-long": ("control", {}, directional_control(bars,TargetPosition.LONG)), "control-short": ("control", {}, directional_control(bars,TargetPosition.SHORT))}


def _finite_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, dict): return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list): return [_finite_json(item) for item in value]
    return value


def _metrics(result) -> dict[str, Any]:
    report = build_metrics_report(to_neutral_backtest_result(result), 24960)
    if result.insolvent:
        report.update(total_return=-1.0, annualized_return=None, sharpe_ratio=None, sortino_ratio=None, volatility_annualized=None)
        report["notes"].append("account insolvent: terminal loss is -100%; annualized return, volatility, Sharpe and Sortino are undefined")
    return _finite_json(report)


def run_phase5d(split: str, output_root: Path = Path("data/fx/research/results/phase5d_run2_insolvency_policy")) -> list[dict]:
    if split not in SPLITS: raise ValueError("Phase 5D only permits development or validation; test is forbidden")
    metadata = load_metadata("EURUSD", "M15", root=Path("data/fx/research"))
    if metadata.dataset_sha256 != RESEARCH_SHA: raise ValueError("research dataset fingerprint mismatch")
    calibration, terms = _profile(); start, end = (pd.Timestamp(value, tz="UTC") for value in SPLITS[split])
    bars = apply_hourly_p95_spread(tuple(b for b in _bars() if start <= pd.Timestamp(b.timestamp_utc) <= end), calibration)
    cfg = FxEngineConfig("EURUSD", Decimal("0.01"), Decimal("100000"), Decimal("0.00001"), Decimal("0.01"), Decimal("60"), Decimal("0.01"), "USD", "USD", Decimal("100"), terms.commission_model(), FixedPointsSlippage(Decimal("1")), terms.swap_model(), None, terminate_on_insolvency=True)
    prereg_sha = hashlib.sha256(Path("PHASE5D_PREREGISTRATION.md").read_bytes()).hexdigest()
    results=[]
    for ident,(family,params,signals) in _variants(bars).items():
        result=FxBacktestEngine(cfg).run(bars, signals)
        trades=result.trades; net=sum((t.net_pnl for t in trades),Decimal("0")); gross=sum((t.gross_pnl for t in trades),Decimal("0"))
        costs={k:sum((getattr(t,k) for t in trades),Decimal("0")) for k in ("spread_cost","slippage_cost","commission_cost","swap_cost")}
        long=[t for t in trades if t.side.value=="long"]; short=[t for t in trades if t.side.value=="short"]
        positive=sum((t.net_pnl for t in trades if t.net_pnl>0),Decimal("0")); ranked=sorted((t.net_pnl for t in trades if t.net_pnl>0),reverse=True)
        payload={"run_id":RUN_ID,"variant_id":ident,"family":family,"parameters":params,"split":split,"dataset_sha256":RESEARCH_SHA,"spread_profile_sha256":SPREAD_SHA,"non_spread_cost_profile_sha256":NON_SPREAD_SHA,"preregistration_sha256":prereg_sha,"initial_balance":"100","fixed_lots":"0.01","trade_count":len(trades),"long_trade_count":len(long),"short_trade_count":len(short),"gross_pnl":str(gross),"net_pnl":str(net),**{k:str(v) for k,v in costs.items()},"long_net_pnl":str(sum((t.net_pnl for t in long),Decimal("0"))),"short_net_pnl":str(sum((t.net_pnl for t in short),Decimal("0"))),"largest_trade_contribution":str(ranked[0]/positive) if positive else None,"top_5_trade_contribution":str(sum(ranked[:5])/positive) if positive else None,"insolvent":result.insolvent,"terminated_early":result.terminated_early,"termination_reason":result.termination_reason,"termination_timestamp":result.termination_timestamp.isoformat() if result.termination_timestamp else None,"bars_survived":len(result.equity_curve),"final_balance":str(result.final_account.balance),"final_equity":str(result.final_account.equity),"metrics":_metrics(result),"classification":"CONTROL" if family=="control" else "PENDING_CROSS_SPLIT_CLASSIFICATION"}
        output_root.joinpath(split).mkdir(parents=True,exist_ok=True); output_root.joinpath(split,f"{ident}.json").write_text(json.dumps(_finite_json(payload),indent=2,sort_keys=True,allow_nan=False)+"\n"); results.append(payload)
    return results


def classify_phase5d(output_root: Path = Path("data/fx/research/results/phase5d_run2_insolvency_policy")) -> list[dict]:
    """Apply fixed two-split rules; never reads test."""
    outcomes=[]
    for dev_path in sorted((output_root/"development").glob("*.json")):
        dev=json.loads(dev_path.read_text()); val=json.loads((output_root/"validation"/dev_path.name).read_text())
        if dev["family"]=="control": label="CONTROL"
        else:
            checks=[]
            for item in (dev,val):
                m=item["metrics"]; checks.append(not item["insolvent"] and item["trade_count"]>=30 and float(item["net_pnl"])>0 and (m["expectancy"] or 0)>0 and (m["profit_factor"] or 0)>1 and m["max_drawdown_pct"]>=-0.2 and item["long_trade_count"]>=10 and item["short_trade_count"]>=10 and (item["largest_trade_contribution"] is None or float(item["largest_trade_contribution"])<=.3))
            label="CANDIDATE" if all(checks) else ("INSUFFICIENT SAMPLE" if min(dev["trade_count"],val["trade_count"])<30 else "REJECT")
        for item in (dev,val): item["classification"]=label; Path(output_root/item["split"]/f"{item['variant_id']}.json").write_text(json.dumps(_finite_json(item),indent=2,sort_keys=True,allow_nan=False)+"\n")
        outcomes.append({"variant_id":dev["variant_id"],"classification":label})
    return outcomes
