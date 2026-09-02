"""Post-holdout diagnostics.

This module is intentionally descriptive, not an optimizer. 2025+ has already
been consumed as holdout; outputs from this module may generate NEW hypotheses
for future forward/paper tests but must not be presented as fresh out-of-sample
validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import pandas as pd
import numpy as np
import yaml

from src.data.loader import load_ohlcv, dataset_hash


@dataclass(frozen=True)
class DiagnosticVariant:
    name: str
    research_trades: Path
    holdout_trades: Path


def _utc_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True)


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = _utc_series(out["timestamp"])
    out = out.sort_values("timestamp").reset_index(drop=True)
    close = out["close"].astype(float)
    out["trailing_return_168h"] = close / close.shift(168) - 1.0
    hourly = close.pct_change()
    out["realized_vol_168h"] = hourly.rolling(168, min_periods=168).std(ddof=0) * math.sqrt(24 * 365)
    out["range_pct_24h"] = (
        out["high"].rolling(24, min_periods=24).max()
        / out["low"].rolling(24, min_periods=24).min()
        - 1.0
    )
    return out


def _time_to_threshold(window: pd.DataFrame, entry_price: float, threshold: float) -> float | None:
    hits = window.loc[window["high"] >= entry_price * (1.0 + threshold), "timestamp"]
    if hits.empty:
        return None
    start = window["timestamp"].iloc[0]
    return float((hits.iloc[0] - start).total_seconds() / 3600.0)


def enrich_trades(trades: pd.DataFrame, ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Add path-dependent diagnostics such as MAE/MFE and follow-through.

    Entry/exit timestamps correspond to execution bars. We include both endpoint
    bars because an execution at the open can subsequently experience that bar's
    high/low. This is diagnostic only and does not alter backtest PnL.
    """
    bars = _prepare_ohlcv(ohlcv)
    bars = bars.set_index("timestamp", drop=False)
    rows: list[dict] = []
    for _, t in trades.iterrows():
        entry_time = pd.Timestamp(t["entry_time"])
        exit_time = pd.Timestamp(t["exit_time"])
        if entry_time.tzinfo is None:
            entry_time = entry_time.tz_localize("UTC")
        else:
            entry_time = entry_time.tz_convert("UTC")
        if exit_time.tzinfo is None:
            exit_time = exit_time.tz_localize("UTC")
        else:
            exit_time = exit_time.tz_convert("UTC")
        window = bars.loc[(bars.index >= entry_time) & (bars.index <= exit_time)]
        if window.empty:
            raise ValueError(f"No OHLCV bars for trade {entry_time} -> {exit_time}")
        entry = float(t["entry_price"])
        max_high = float(window["high"].max())
        min_low = float(window["low"].min())
        mfe = max_high / entry - 1.0
        mae = min_low / entry - 1.0
        max_high_time = window.loc[window["high"].idxmax(), "timestamp"]
        min_low_time = window.loc[window["low"].idxmin(), "timestamp"]
        duration_h = (exit_time - entry_time).total_seconds() / 3600.0

        first24 = window[window["timestamp"] <= entry_time + pd.Timedelta(hours=24)]
        first48 = window[window["timestamp"] <= entry_time + pd.Timedelta(hours=48)]
        first72 = window[window["timestamp"] <= entry_time + pd.Timedelta(hours=72)]
        def fav(w: pd.DataFrame) -> float:
            return float(w["high"].max() / entry - 1.0) if not w.empty else np.nan

        # Entry-regime features use values on the execution bar based on trailing
        # completed history. They are descriptive; do not optimize thresholds here.
        try:
            entry_bar = bars.loc[entry_time]
            if isinstance(entry_bar, pd.DataFrame):
                entry_bar = entry_bar.iloc[0]
            trailing_ret = float(entry_bar["trailing_return_168h"])
            realized_vol = float(entry_bar["realized_vol_168h"])
            range24 = float(entry_bar["range_pct_24h"])
        except KeyError:
            trailing_ret = realized_vol = range24 = np.nan

        row = dict(t)
        row.update({
            "duration_hours": duration_h,
            "bars_held": int(len(window)),
            "mfe_pct": mfe,
            "mae_pct": mae,
            "giveback_from_mfe_pct": mfe - float(t["return_pct"]),
            "hours_to_mfe": float((max_high_time - entry_time).total_seconds() / 3600.0),
            "hours_to_mae": float((min_low_time - entry_time).total_seconds() / 3600.0),
            "mfe_first24h_pct": fav(first24),
            "mfe_first48h_pct": fav(first48),
            "mfe_first72h_pct": fav(first72),
            "time_to_plus_1pct_h": _time_to_threshold(window, entry, 0.01),
            "time_to_plus_2pct_h": _time_to_threshold(window, entry, 0.02),
            "time_to_plus_5pct_h": _time_to_threshold(window, entry, 0.05),
            "no_followthrough_24h_1pct": bool(fav(first24) < 0.01),
            "no_followthrough_48h_2pct": bool(fav(first48) < 0.02),
            "entry_trailing_return_168h": trailing_ret,
            "entry_realized_vol_168h": realized_vol,
            "entry_range_pct_24h": range24,
            "winner": bool(float(t["return_pct"]) > 0),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _max_streak(values: list[bool], target: bool) -> int:
    best = cur = 0
    for v in values:
        if bool(v) == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize_enriched(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"num_trades": 0}
    wins = df[df["return_pct"] > 0]
    losses = df[df["return_pct"] <= 0]
    gross_profit = float(wins["net_pnl"].sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses["net_pnl"].sum())) if not losses.empty else 0.0
    fees = float((df["entry_fee"] + df["exit_fee"]).sum())
    return {
        "num_trades": int(len(df)),
        "win_rate": float((df["return_pct"] > 0).mean()),
        "mean_trade_return": float(df["return_pct"].mean()),
        "median_trade_return": float(df["return_pct"].median()),
        "avg_win": float(wins["return_pct"].mean()) if not wins.empty else None,
        "avg_loss": float(losses["return_pct"].mean()) if not losses.empty else None,
        "profit_factor_from_trade_pnl": gross_profit / gross_loss if gross_loss else None,
        "median_winner_duration_h": float(wins["duration_hours"].median()) if not wins.empty else None,
        "median_loser_duration_h": float(losses["duration_hours"].median()) if not losses.empty else None,
        "median_mfe_pct": float(df["mfe_pct"].median()),
        "median_mae_pct": float(df["mae_pct"].median()),
        "winner_median_mfe_pct": float(wins["mfe_pct"].median()) if not wins.empty else None,
        "loser_median_mfe_pct": float(losses["mfe_pct"].median()) if not losses.empty else None,
        "loser_median_mae_pct": float(losses["mae_pct"].median()) if not losses.empty else None,
        "no_followthrough_24h_1pct_rate": float(df["no_followthrough_24h_1pct"].mean()),
        "no_followthrough_48h_2pct_rate": float(df["no_followthrough_48h_2pct"].mean()),
        "plus_5pct_reached_rate": float(df["time_to_plus_5pct_h"].notna().mean()),
        "max_consecutive_losses": _max_streak((df["return_pct"] > 0).tolist(), False),
        "max_consecutive_wins": _max_streak((df["return_pct"] > 0).tolist(), True),
        "total_fees": fees,
        "fee_share_of_absolute_net_pnl": fees / max(abs(float(df["net_pnl"].sum())), 1e-12),
        "entry_trailing_return_168h_median": float(df["entry_trailing_return_168h"].median()),
        "entry_realized_vol_168h_median": float(df["entry_realized_vol_168h"].median()),
        "entry_range_pct_24h_median": float(df["entry_range_pct_24h"].median()),
    }


def compare_periods(research: pd.DataFrame, holdout: pd.DataFrame) -> pd.DataFrame:
    rs = summarize_enriched(research)
    hs = summarize_enriched(holdout)
    keys = sorted(set(rs) | set(hs))
    rows = []
    for key in keys:
        r, h = rs.get(key), hs.get(key)
        delta = None
        if isinstance(r, (int, float)) and isinstance(h, (int, float)) and r is not None and h is not None:
            delta = h - r
        rows.append({"metric": key, "research_2018_2024": r, "holdout_2025_2026": h, "delta": delta})
    return pd.DataFrame(rows)


def _hypothesis_notes(comparison: pd.DataFrame, holdout: pd.DataFrame) -> list[str]:
    # Descriptive prompts only. These are deliberately not parameter rules.
    notes = [
        "2025-2026 is consumed data. Any rule suggested below is post-hoc and must be validated only in future forward/paper data.",
    ]
    h = summarize_enriched(holdout)
    if h.get("win_rate", 1) < 0.35:
        notes.append("Entry selectivity/follow-through is a candidate research question: the holdout win rate was low, suggesting many breakouts failed to develop into sustained trends.")
    if h.get("median_winner_duration_h") and h.get("median_loser_duration_h") and h["median_winner_duration_h"] > 1.5 * h["median_loser_duration_h"]:
        notes.append("Winners tended to require materially more time than losers. Future work can test whether early post-entry behavior predicts eventual follow-through, without tuning on this consumed period.")
    if h.get("no_followthrough_24h_1pct_rate", 0) > 0.4:
        notes.append("A large share of entries had little first-24h follow-through. A confirmation concept may be worth preregistering for forward testing, but thresholds must not be optimized on 2025-2026.")
    if h.get("max_consecutive_losses", 0) >= 7:
        notes.append("Losses clustered in long streaks. Regime gating or risk throttling is a future hypothesis, not a validated fix.")
    return notes


def run_holdout_diagnostics(config_path: str | Path) -> Path:
    config_path = Path(config_path)
    cfg = yaml.safe_load(config_path.read_text())
    symbol = cfg.get("symbol", "BTCUSDT")
    timeframe = cfg.get("timeframe", "1h")
    out_dir = Path(cfg.get("output_dir", "research/post_holdout_diagnostics"))
    out_dir.mkdir(parents=True, exist_ok=True)

    ohlcv = load_ohlcv(symbol, timeframe)
    variants = [
        DiagnosticVariant(
            name=v["name"],
            research_trades=Path(v["research_trades"]),
            holdout_trades=Path(v["holdout_trades"]),
        ) for v in cfg["variants"]
    ]

    all_summary = []
    for variant in variants:
        research = pd.read_csv(variant.research_trades)
        holdout = pd.read_csv(variant.holdout_trades)
        for d in (research, holdout):
            d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
            d["exit_time"] = pd.to_datetime(d["exit_time"], utc=True)
        research_e = enrich_trades(research, ohlcv)
        holdout_e = enrich_trades(holdout, ohlcv)
        vdir = out_dir / variant.name
        vdir.mkdir(parents=True, exist_ok=True)
        research_e.to_csv(vdir / "research_trades_enriched.csv", index=False)
        holdout_e.to_csv(vdir / "holdout_trades_enriched.csv", index=False)
        comparison = compare_periods(research_e, holdout_e)
        comparison.to_csv(vdir / "research_vs_holdout.csv", index=False)

        # Calendar clustering is descriptive and useful for locating streaks.
        hmonth = holdout_e.assign(month=holdout_e["entry_time"].dt.to_period("M").astype(str)).groupby("month").agg(
            trades=("return_pct", "size"),
            win_rate=("winner", "mean"),
            mean_return=("return_pct", "mean"),
            sum_return=("return_pct", "sum"),
            median_mfe=("mfe_pct", "median"),
            median_mae=("mae_pct", "median"),
            no_followthrough_24h_1pct=("no_followthrough_24h_1pct", "mean"),
        ).reset_index()
        hmonth.to_csv(vdir / "holdout_by_month.csv", index=False)

        rs, hs = summarize_enriched(research_e), summarize_enriched(holdout_e)
        (vdir / "summary.json").write_text(json.dumps({"research": rs, "holdout": hs}, indent=2, default=str))
        notes = _hypothesis_notes(comparison, holdout_e)
        (vdir / "HYPOTHESES_FOR_FORWARD_TESTING.md").write_text(
            "# Post-holdout hypotheses — NOT validated\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
        )
        all_summary.append({"variant": variant.name, **{f"research_{k}": val for k,val in rs.items()}, **{f"holdout_{k}": val for k,val in hs.items()}})

    pd.DataFrame(all_summary).to_csv(out_dir / "summary.csv", index=False)
    meta = {
        "status": "POST_HOLDOUT_DIAGNOSTIC_CONSUMED_DATA",
        "warning": "Do not call any derived rule out-of-sample. 2025-2026 was already inspected.",
        "symbol": symbol,
        "timeframe": timeframe,
        "dataset_hash": dataset_hash(ohlcv),
        "variants": [v.name for v in variants],
    }
    (out_dir / "DIAGNOSTIC_METADATA.json").write_text(json.dumps(meta, indent=2))
    (out_dir / "README.md").write_text(
        "# Post-holdout diagnostics\n\n"
        "This directory explains why the frozen breakouts behaved differently in 2025-2026. "
        "It is descriptive and hypothesis-generating only. Any new filter, stop, confirmation, or regime rule "
        "derived here must be preregistered and tested only on future forward/paper data.\n"
    )
    return out_dir
