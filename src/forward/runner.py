"""Forward-only evaluation after the final holdout was consumed."""
from __future__ import annotations
from pathlib import Path
import hashlib, json
import pandas as pd
import yaml
from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.data.loader import load_ohlcv, dataset_hash
from src.metrics.metrics import build_metrics_report
from src.strategies.breakout import Breakout
from src.strategies.breakout_forward import BreakoutConfirmed24h, BreakoutAdaptiveVolGate

FROZEN_START = pd.Timestamp("2026-09-03T00:00:00Z")
FROZEN_VARIANTS = [
    ("baseline_168_60", lambda: Breakout(168, 60)),
    ("baseline_168_72", lambda: Breakout(168, 72)),
    ("confirmed24_168_60", BreakoutConfirmed24h),
    ("adaptive_vol_168_60", BreakoutAdaptiveVolGate),
]


def _utc(x):
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _frozen_spec():
    return {
        "forward_start": str(FROZEN_START),
        "variants": [n for n,_ in FROZEN_VARIANTS],
        "purpose": "forward/paper validation only; no optimization on consumed 2025-2026 holdout",
    }


def preregister_forward(config_path: str | Path) -> Path:
    cfg=yaml.safe_load(Path(config_path).read_text()) or {}
    if _utc(cfg.get("forward_start")) != FROZEN_START:
        raise ValueError(f"forward_start is frozen at {FROZEN_START}")
    out=Path(cfg.get("output_dir","research/forward")); out.mkdir(parents=True,exist_ok=True)
    spec=_frozen_spec(); blob=json.dumps(spec,sort_keys=True).encode(); spec["spec_sha256"]=hashlib.sha256(blob).hexdigest()
    path=out/"PREREGISTRATION.json"; path.write_text(json.dumps(spec,indent=2)+"\n")
    md="# Forward preregistration\n\nStart: **2026-09-03 00:00 UTC**.\n\nFrozen candidates:\n"+"\n".join(f"- `{n}`" for n,_ in FROZEN_VARIANTS)+"\n\n2025-2026 is consumed and may not be used to select/tune these rules.\n"
    (out/"PREREGISTRATION.md").write_text(md)
    return out


def run_forward_eval(config_path: str | Path) -> Path:
    cfg=yaml.safe_load(Path(config_path).read_text()) or {}
    if _utc(cfg.get("forward_start")) != FROZEN_START:
        raise ValueError(f"forward_start is frozen at {FROZEN_START}")
    out=Path(cfg.get("output_dir","research/forward")); pre=out/"PREREGISTRATION.json"
    if not pre.exists():
        raise ValueError("run preregister-forward before forward-eval")
    symbol=cfg.get("symbol","BTCUSDT"); timeframe=cfg.get("timeframe","1h")
    df=load_ohlcv(symbol,timeframe)
    df=df.copy(); df["timestamp"]=pd.to_datetime(df["timestamp"],utc=True); df=df.sort_values("timestamp").reset_index(drop=True)
    future=df[df["timestamp"]>=FROZEN_START]
    if len(future)<2:
        raise ValueError(f"no forward data yet at/after {FROZEN_START}; update dataset later")
    bcfg=BacktestConfig(initial_capital=float(cfg.get("initial_capital",10000)),trading_fee=float(cfg.get("trading_fee",0.001)),slippage=float(cfg.get("slippage",0.0002)),position_size_fraction=float(cfg.get("position_size_fraction",1.0)))
    rows=[]
    variants_dir=out/"variants"; variants_dir.mkdir(parents=True,exist_ok=True)
    for name,factory in FROZEN_VARIANTS:
        strat=factory(); start_idx=int(future.index[0]); context_start=max(0,start_idx-strat.warmup_bars)
        work=df.iloc[context_start:].reset_index(drop=True); evaluation_start=start_idx-context_start
        sig=strat.generate_signals(work)
        res=BacktestEngine(bcfg).run(work,sig,evaluation_start=evaluation_start)
        metrics=build_metrics_report(res,timeframe)
        vd=variants_dir/name; vd.mkdir(parents=True,exist_ok=True)
        res.trades_df().to_csv(vd/"trades.csv",index=False); res.equity_curve.to_csv(vd/"equity.csv",index=False)
        (vd/"metrics.json").write_text(json.dumps(metrics,indent=2,default=str)+"\n")
        rows.append({"variant":name,**{k:metrics.get(k) for k in ["total_return","annualized_return","num_trades","win_rate","profit_factor","max_drawdown_pct","sharpe_ratio","total_fees"]}})
    pd.DataFrame(rows).to_csv(out/"summary.csv",index=False)
    meta={"forward_start":str(FROZEN_START),"data_end":str(df['timestamp'].max()),"forward_bars":int(len(future)),"dataset_hash":dataset_hash(df),"consumed_holdout_note":"2025-2026 remains consumed; this report evaluates only 2026-09-03 onward"}
    (out/"FORWARD_EVAL_METADATA.json").write_text(json.dumps(meta,indent=2)+"\n")
    return out
