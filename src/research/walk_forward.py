from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    evaluation_start: pd.Timestamp
    evaluation_end: pd.Timestamp


def generate_walk_forward_windows(df: pd.DataFrame, train_months: int = 24, evaluation_months: int = 6) -> list[WalkForwardWindow]:
    if train_months < 1 or evaluation_months < 1:
        raise ValueError("train_months and evaluation_months must be >= 1")
    if df.empty:
        return []
    ts = pd.to_datetime(df["timestamp"], utc=True)
    first = ts.iloc[0]
    last = ts.iloc[-1]
    windows: list[WalkForwardWindow] = []
    train_start = first
    while True:
        eval_start = train_start + pd.DateOffset(months=train_months)
        eval_end_exclusive = eval_start + pd.DateOffset(months=evaluation_months)
        if eval_start > last:
            break
        eval_end = min(last, eval_end_exclusive - pd.Timedelta(nanoseconds=1))
        train_end = eval_start - pd.Timedelta(nanoseconds=1)
        windows.append(WalkForwardWindow(train_start, train_end, eval_start, eval_end))
        if eval_end_exclusive > last:
            break
        train_start = train_start + pd.DateOffset(months=evaluation_months)
    return windows


def slice_window(df: pd.DataFrame, window: WalkForwardWindow) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    train = df.loc[(ts >= window.train_start) & (ts <= window.train_end)].reset_index(drop=True)
    evaluation = df.loc[(ts >= window.evaluation_start) & (ts <= window.evaluation_end)].reset_index(drop=True)
    return train, evaluation
