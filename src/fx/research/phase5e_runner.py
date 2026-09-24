"""Fail-closed evaluator for the frozen Phase 5E batch."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.fx.backtesting.costs import FixedPointsSlippage
from src.fx.backtesting.engine import FxBacktestEngine, FxEngineConfig
from src.fx.backtesting.metrics_adapter import to_neutral_backtest_result
from src.fx.cost_calibration import FrozenNonSpreadCosts, SpreadBucket, SpreadCalibration, apply_hourly_p95_spread
from src.fx.data.schema import FxBar
from src.fx.data.storage import load_metadata
from src.fx.strategies.phase5e_events import compression_expansion, control_flat, session_range_breakout, standardized_impulse
from src.metrics.metrics import build_metrics_report

RESEARCH_SHA = "5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59"
SPREAD_SHA = "a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575"
NON_SPREAD_SHA = "9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36"
EXPECTED_PREREG_SHA = "b5359b37c865ecf72666a62aee4d3849b8386ea5eb1b4c4df0d43fb9bf7dcd10"
RUN_ID = "phase5e_run1_preregistered_events"
SPLITS = {"development_inner_a": ("2022-09-01", "2023-08-31 23:45:00"), "development_inner_b": ("2023-09-01", "2024-08-30 23:45:00"), "development": ("2022-09-01", "2024-08-30 23:45:00"), "validation": ("2024-09-02", "2025-08-29 23:45:00")}


class Phase5ENotAuthorizedError(RuntimeError):
    pass


@dataclass(frozen=True)
class Variant:
    variant_id: str
    family: str
    parameters: dict[str, object]
    signal: Callable[[tuple[FxBar, ...]], tuple]
    control: bool = False


def registry() -> tuple[Variant, ...]:
    return (
        Variant("compression-expansion-16-4", "compression_expansion", {"atr_lookback":16,"breakout_lookback":4,"compression_ratio":.75,"holding_bars":4}, lambda b: compression_expansion(b,16,4,.75,4)),
        Variant("compression-expansion-24-6", "compression_expansion", {"atr_lookback":24,"breakout_lookback":6,"compression_ratio":.70,"holding_bars":4}, lambda b: compression_expansion(b,24,6,.70,4)),
        Variant("session-range-01-08", "session_range", {"range_start_hour":1,"range_end_hour":5,"entry_start_hour":8,"entry_end_hour":11,"holding_bars":4}, lambda b: session_range_breakout(b,1,5,8,11,4)),
        Variant("session-range-02-09", "session_range", {"range_start_hour":2,"range_end_hour":6,"entry_start_hour":9,"entry_end_hour":12,"holding_bars":4}, lambda b: session_range_breakout(b,2,6,9,12,4)),
        Variant("expansion-reversal-32-2p5-2", "expansion_reversal", {"normalization_lookback":32,"threshold":2.5,"holding_bars":2}, lambda b: standardized_impulse(b,32,2.5,2,True)),
        Variant("expansion-reversal-48-2p25-4", "expansion_reversal", {"normalization_lookback":48,"threshold":2.25,"holding_bars":4}, lambda b: standardized_impulse(b,48,2.25,4,True)),
        Variant("impulse-continuation-32-2p5-2", "impulse_continuation", {"normalization_lookback":32,"threshold":2.5,"holding_bars":2}, lambda b: standardized_impulse(b,32,2.5,2,False)),
        Variant("impulse-continuation-48-2p25-4", "impulse_continuation", {"normalization_lookback":48,"threshold":2.25,"holding_bars":4}, lambda b: standardized_impulse(b,48,2.25,4,False)),
        Variant("control-flat", "control", {}, control_flat, True),
    )


@dataclass(frozen=True)
class Summary:
    insolvent: bool; trade_count: int; net_pnl: Decimal; expectancy: Decimal | None; profit_factor: Decimal | None; max_drawdown: Decimal; long_trade_count: int; short_trade_count: int; largest_trade_contribution: Decimal | None; gross_reference_pnl: Decimal; total_costs: Decimal


def cost_efficient(gross_reference_pnl: Decimal, total_costs: Decimal) -> bool:
    return gross_reference_pnl > 0 and total_costs / gross_reference_pnl <= Decimal("0.75")


def year_stable(yearly_net_pnl: dict[int, Decimal], yearly_trade_count: dict[int, int]) -> bool:
    positive = [pnl for year,pnl in yearly_net_pnl.items() if yearly_trade_count.get(year,0) >= 10 and pnl > 0]
    total = sum(positive, Decimal("0"))
    return len(positive) >= 2 and total > 0 and max(positive) / total <= Decimal(".70")


def meets_split_rules(s: Summary) -> bool:
    return not s.insolvent and s.trade_count >= 30 and s.net_pnl > 0 and (s.expectancy or 0) > 0 and (s.profit_factor or 0) > 1 and s.max_drawdown >= Decimal("-.20") and s.long_trade_count >= 10 and s.short_trade_count >= 10 and (s.largest_trade_contribution is None or s.largest_trade_contribution <= Decimal(".30")) and cost_efficient(s.gross_reference_pnl,s.total_costs)


def candidate(development: Summary, validation: Summary, inner_a: Summary, inner_b: Summary, yearly_net_pnl: dict[int, Decimal], yearly_trade_count: dict[int, int]) -> bool:
    return all(meets_split_rules(s) for s in (development,validation)) and all(not s.insolvent and s.net_pnl > 0 for s in (inner_a,inner_b)) and year_stable(yearly_net_pnl,yearly_trade_count)


def assert_permitted_split(split: str) -> None:
    if split == "test": raise ValueError("Phase 5E untouched test is structurally forbidden")
    if split not in SPLITS: raise ValueError("Phase 5E permits only preregistered development or validation splits")


def _finite(value: Any) -> Any:
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,dict): return {k:_finite(v) for k,v in value.items()}
    if isinstance(value,list): return [_finite(v) for v in value]
    return value


def _precheck() -> str:
    actual = hashlib.sha256(Path("PHASE5E_PREREGISTRATION.md").read_bytes()).hexdigest()
    if actual != EXPECTED_PREREG_SHA: raise ValueError("Phase 5E preregistration fingerprint mismatch")
    return actual


def _bars() -> tuple[FxBar,...]:
    df=pd.read_parquet("data/fx/research/EURUSD/M15/bars.parquet")
    return tuple(FxBar(pd.Timestamp(r.timestamp_utc).to_pydatetime(),Decimal(r.open),Decimal(r.high),Decimal(r.low),Decimal(r.close),Decimal(r.tick_volume),Decimal(r.real_volume) if pd.notna(r.real_volume) else None,int(r.spread_points) if pd.notna(r.spread_points) else None) for r in df.itertuples())


def _profile() -> tuple[SpreadCalibration,FrozenNonSpreadCosts]:
    raw=json.loads(Path("data/fx/EURUSD/M15/phase5c_cost_report.json").read_text())
    if raw["dataset_sha256"] != "0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9" or raw["non_spread_cost_fingerprint"] != NON_SPREAD_SHA: raise ValueError("Phase 5C profile mismatch")
    p=raw["spread_calibration"]
    spread=SpreadCalibration(p["dataset_sha256"],tuple(SpreadBucket(x["hour"],x["n"],x["missing"],Decimal(x["median"]) if x["median"] is not None else None,Decimal(x["p95"]) if x["p95"] is not None else None) for x in p["buckets"]),p["overall_observations"],p["overall_missing"],Decimal(p["overall_p95"]) if p["overall_p95"] else None,p["minimum_observations_per_hour"])
    if spread.fingerprint()!=SPREAD_SHA: raise ValueError("spread profile fingerprint mismatch")
    n=raw["non_spread_costs"]; terms=FrozenNonSpreadCosts(n["symbol"],n["account_currency"],Decimal(n["commission_per_lot_per_side"]),Decimal(n["long_swap_per_lot"]),Decimal(n["short_swap_per_lot"]),n["triple_swap_weekday"],n["source"])
    if terms.fingerprint()!=NON_SPREAD_SHA: raise ValueError("non-spread profile fingerprint mismatch")
    return spread,terms


def _yearly(trades) -> dict[str,dict]:
    output={}
    for year in sorted({t.close_time.year for t in trades}):
        rows=[t for t in trades if t.close_time.year==year]; pnls=[t.net_pnl for t in rows]; wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
        output[str(year)]={"trade_count":len(rows),"net_pnl":str(sum(pnls,Decimal("0"))),"expectancy":str(sum(pnls,Decimal("0"))/len(rows)) if rows else None,"profit_factor":str(sum(wins,Decimal("0"))/abs(sum(losses,Decimal("0")))) if losses else None}
    return output


def _revision() -> str:
    return subprocess.run(["git","rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip()


def run_phase5e(split: str, output_root: Path = Path("data/fx/research/results/phase5e_run1_preregistered_events")) -> list[dict]:
    assert_permitted_split(split); prereg=_precheck()
    meta=load_metadata("EURUSD","M15",root=Path("data/fx/research"))
    if meta.dataset_sha256 != RESEARCH_SHA: raise ValueError("research dataset fingerprint mismatch")
    spread,terms=_profile(); start,end=(pd.Timestamp(v,tz="UTC") for v in SPLITS[split]); bars=apply_hourly_p95_spread(tuple(b for b in _bars() if start<=pd.Timestamp(b.timestamp_utc)<=end),spread)
    cfg=FxEngineConfig("EURUSD",Decimal(".01"),Decimal("100000"),Decimal(".00001"),Decimal(".01"),Decimal("60"),Decimal(".01"),"USD","USD",Decimal("100"),terms.commission_model(),FixedPointsSlippage(Decimal("1")),terms.swap_model(),None,terminate_on_insolvency=True)
    output=[]
    for v in registry():
        result=FxBacktestEngine(cfg).run(bars,v.signal(bars)); trades=result.trades; gross=sum((t.gross_pnl for t in trades),Decimal("0")); costs={k:sum((getattr(t,k) for t in trades),Decimal("0")) for k in ("spread_cost","slippage_cost","commission_cost","swap_cost")}; total=sum(costs.values(),Decimal("0")); net=sum((t.net_pnl for t in trades),Decimal("0")); long=[t for t in trades if t.side.value=="long"]; short=[t for t in trades if t.side.value=="short"]; positives=sorted((t.net_pnl for t in trades if t.net_pnl>0),reverse=True); pos=sum(positives,Decimal("0")); metrics=build_metrics_report(to_neutral_backtest_result(result),24960)
        if result.insolvent: metrics.update(total_return=-1.0,annualized_return=None,sharpe_ratio=None,sortino_ratio=None,volatility_annualized=None); metrics["notes"].append("account insolvent: terminal loss -100%; annualized risk metrics undefined")
        payload={"run_id":RUN_ID,"code_commit":_revision(),"variant_id":v.variant_id,"family":v.family,"parameters":v.parameters,"control":v.control,"split":split,"dataset_sha256":RESEARCH_SHA,"spread_profile_sha256":SPREAD_SHA,"non_spread_cost_profile_sha256":NON_SPREAD_SHA,"preregistration_sha256":prereg,"initial_balance":"100","fixed_lots":"0.01","trade_count":len(trades),"long_trade_count":len(long),"short_trade_count":len(short),"gross_reference_pnl":str(gross),"net_pnl":str(net),**{k:str(x) for k,x in costs.items()},"total_costs":str(total),"cost_per_trade":str(total/len(trades)) if trades else None,"cost_efficiency_ratio":str(total/gross) if gross>0 else None,"largest_trade_contribution":str(positives[0]/pos) if pos else None,"top_5_trade_contribution":str(sum(positives[:5],Decimal("0"))/pos) if pos else None,"yearly":_yearly(trades),"insolvent":result.insolvent,"terminated_early":result.terminated_early,"termination_reason":result.termination_reason,"termination_timestamp":result.termination_timestamp.isoformat() if result.termination_timestamp else None,"bars_survived":len(result.equity_curve),"final_balance":str(result.final_account.balance),"final_equity":str(result.final_account.equity),"metrics":_finite(metrics),"classification":"CONTROL" if v.control else "PENDING"}
        output_root.joinpath(split).mkdir(parents=True,exist_ok=True); output_root.joinpath(split,f"{v.variant_id}.json").write_text(json.dumps(_finite(payload),indent=2,sort_keys=True,allow_nan=False)+"\n"); output.append(payload)
    return output


def _summary(item: dict) -> Summary:
    m=item["metrics"]
    return Summary(item["insolvent"],item["trade_count"],Decimal(item["net_pnl"]),Decimal(str(m["expectancy"])) if m["expectancy"] is not None else None,Decimal(str(m["profit_factor"])) if m["profit_factor"] is not None else None,Decimal(str(m["max_drawdown_pct"])),item["long_trade_count"],item["short_trade_count"],Decimal(item["largest_trade_contribution"]) if item["largest_trade_contribution"] else None,Decimal(item["gross_reference_pnl"]),Decimal(item["total_costs"]))


def classify_phase5e(output_root: Path = Path("data/fx/research/results/phase5e_run1_preregistered_events")) -> list[dict]:
    required=("development_inner_a","development_inner_b","development","validation")
    if any(not (output_root/s).exists() for s in required): raise ValueError("all preregistered stages must exist before classification")
    outcomes=[]
    for v in registry():
        items={s:json.loads((output_root/s/f"{v.variant_id}.json").read_text()) for s in required}
        yearly_net={}; yearly_count={}
        for split in ("development","validation"):
            for year,row in items[split]["yearly"].items():
                yearly_net[int(year)]=yearly_net.get(int(year),Decimal("0"))+Decimal(row["net_pnl"]); yearly_count[int(year)]=yearly_count.get(int(year),0)+row["trade_count"]
        label="CONTROL" if v.control else ("CANDIDATE" if candidate(_summary(items["development"]),_summary(items["validation"]),_summary(items["development_inner_a"]),_summary(items["development_inner_b"]),yearly_net,yearly_count) else "REJECT")
        for item in items.values(): item["classification"]=label; (output_root/item["split"]/f"{item['variant_id']}.json").write_text(json.dumps(item,indent=2,sort_keys=True,allow_nan=False)+"\n")
        outcomes.append({"variant_id":v.variant_id,"classification":label})
    return outcomes
