from __future__ import annotations
import pandas as pd
from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.metrics.metrics import build_metrics_report
from src.strategies.base import Strategy


def annual_strategy_metrics(df: pd.DataFrame, strategy_factory, backtest_config: BacktestConfig, timeframe: str) -> dict[int, dict]:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    out: dict[int, dict] = {}
    for year in sorted(ts.dt.year.unique()):
        year_df = df.loc[ts.dt.year == year].reset_index(drop=True)
        if len(year_df) < 2:
            continue
        strategy: Strategy = strategy_factory()
        # Annual reports intentionally evaluate only that calendar year. Context
        # from the immediately preceding data is prepended for indicators.
        first_idx = int(df.index[ts.dt.year == year][0])
        warm = strategy.warmup_bars
        start_idx = max(0, first_idx - warm)
        last_idx = int(df.index[ts.dt.year == year][-1]) + 1
        ext = df.iloc[start_idx:last_idx].reset_index(drop=True)
        evaluation_start = first_idx - start_idx
        signals = strategy.generate_signals(ext)
        result = BacktestEngine(backtest_config).run(ext, signals, evaluation_start=evaluation_start)
        out[int(year)] = build_metrics_report(result, timeframe)
    return out
