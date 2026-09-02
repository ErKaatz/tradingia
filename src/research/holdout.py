"""Final-holdout guardrails. Research code must opt in explicitly to touch it."""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class HoldoutSplit:
    research: pd.DataFrame
    final_holdout: pd.DataFrame
    cutoff: pd.Timestamp


def _utc(ts: str | pd.Timestamp) -> pd.Timestamp:
    out = pd.Timestamp(ts)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


def split_final_holdout(df: pd.DataFrame, holdout_start: str | pd.Timestamp = "2025-01-01") -> HoldoutSplit:
    cutoff = _utc(holdout_start)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    research = df.loc[ts < cutoff].reset_index(drop=True)
    holdout = df.loc[ts >= cutoff].reset_index(drop=True)
    if research.empty:
        raise ValueError("research period is empty before final holdout cutoff")
    return HoldoutSplit(research=research, final_holdout=holdout, cutoff=cutoff)


def guard_final_holdout_evaluation(df: pd.DataFrame, holdout_start: str | pd.Timestamp, allow: bool = False) -> None:
    if allow or df.empty:
        return
    cutoff = _utc(holdout_start)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    if (ts >= cutoff).any():
        raise PermissionError(
            f"FINAL_HOLDOUT starts at {cutoff.isoformat()} and is locked. "
            "Set allow_final_holdout_evaluation=true only in a future explicitly authorized phase."
        )
