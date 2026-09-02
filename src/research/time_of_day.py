"""POST-HOC SHORT-HORIZON RESEARCH — time-of-day descriptive analysis.

Task 10: purely descriptive. Reports mean return, volatility, volume, and
a simple continuation/reversion rate by UTC hour-of-day. This module does
NOT produce a Strategy or any tradeable signal -- it exists only to detect
whether intraday structure is visible enough to justify a FUTURE
hypothesis (which would then need its own preregistration and forward
test, exactly like everything else in this project).

## Multiple testing

Grouping by 24 hours-of-day and computing several statistics per hour is,
by construction, 24+ simultaneous comparisons. `build_time_of_day_report`
therefore also runs a global test (Kruskal-Wallis across all 24 hourly
return distributions) and reports it alongside the per-hour breakdown, and
`flag_significant_hours` applies a Bonferroni correction (dividing the
target significance level by 24) before flagging any individual hour as
"different from the rest" -- so a single hour's low p-value from scanning
24 of them is not treated as if it were the only test run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kruskal

N_HOURS = 24


@dataclass(frozen=True)
class TimeOfDayReport:
    per_hour: pd.DataFrame
    kruskal_wallis_statistic: float | None
    kruskal_wallis_pvalue: float | None
    bonferroni_alpha: float
    significant_hours: list[int]


def _continuation_rate(returns_by_hour_group: pd.Series) -> float | None:
    """Fraction of bars in this hour whose return has the SAME sign as the
    immediately preceding bar's return (a simple same-direction-as-prior-
    bar continuation proxy). Returns None if fewer than 2 observations.
    """
    if len(returns_by_hour_group) < 2:
        return None
    signs = np.sign(returns_by_hour_group.to_numpy())
    same_as_prior = signs[1:] == signs[:-1]
    if len(same_as_prior) == 0:
        return None
    return float(np.mean(same_as_prior))


def build_time_of_day_report(
    df: pd.DataFrame, target_alpha: float = 0.05
) -> TimeOfDayReport:
    """`df` must have `timestamp`, `open`, `high`, `low`, `close`, `volume`
    columns, sorted ascending by timestamp. Returns per-hour descriptive
    statistics plus a multiple-testing-aware significance flag.
    """
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").reset_index(drop=True)
    work["hour"] = work["timestamp"].dt.hour
    work["bar_return"] = work["close"].pct_change()
    work["bar_range"] = (work["high"] - work["low"]) / work["close"]

    rows = []
    return_groups: dict[int, pd.Series] = {}
    for hour in range(N_HOURS):
        group = work[work["hour"] == hour]
        returns = group["bar_return"].dropna()
        return_groups[hour] = returns
        rows.append(
            {
                "hour_utc": hour,
                "n_bars": len(group),
                "mean_return": returns.mean() if len(returns) else None,
                "median_return": returns.median() if len(returns) else None,
                "std_return": returns.std(ddof=1) if len(returns) > 1 else None,
                "mean_range_pct": group["bar_range"].mean() if len(group) else None,
                "mean_volume": group["volume"].mean() if len(group) else None,
                "median_volume": group["volume"].median() if len(group) else None,
                "continuation_rate": _continuation_rate(returns),
            }
        )
    per_hour = pd.DataFrame(rows)

    valid_groups = [g for g in return_groups.values() if len(g) >= 30]
    if len(valid_groups) >= 2:
        kw_stat, kw_pvalue = kruskal(*valid_groups)
        kw_stat = float(kw_stat)
        kw_pvalue = float(kw_pvalue)
    else:
        kw_stat, kw_pvalue = None, None

    bonferroni_alpha = target_alpha / N_HOURS
    significant_hours = flag_significant_hours(work, return_groups, bonferroni_alpha)

    return TimeOfDayReport(
        per_hour=per_hour,
        kruskal_wallis_statistic=kw_stat,
        kruskal_wallis_pvalue=kw_pvalue,
        bonferroni_alpha=bonferroni_alpha,
        significant_hours=significant_hours,
    )


def flag_significant_hours(
    work: pd.DataFrame, return_groups: dict[int, pd.Series], bonferroni_alpha: float
) -> list[int]:
    """For each hour with >=30 observations, compare its return
    distribution against ALL OTHER hours combined (Mann-Whitney U), and
    flag it only if the p-value survives the Bonferroni-corrected alpha
    (target_alpha / 24). This is intentionally conservative: with 24
    simultaneous comparisons, an uncorrected p<0.05 would be expected to
    produce roughly one "significant" hour by chance alone even if there is
    no real intraday structure at all.
    """
    from scipy.stats import mannwhitneyu

    significant = []
    for hour, group_returns in return_groups.items():
        if len(group_returns) < 30:
            continue
        other_returns = pd.concat(
            [r for h, r in return_groups.items() if h != hour and len(r) > 0]
        )
        if len(other_returns) < 30:
            continue
        _, p_value = mannwhitneyu(group_returns, other_returns, alternative="two-sided")
        if p_value < bonferroni_alpha:
            significant.append(int(hour))
    return significant


def report_to_dict(report: TimeOfDayReport) -> dict[str, Any]:
    return {
        "kruskal_wallis_statistic": report.kruskal_wallis_statistic,
        "kruskal_wallis_pvalue": report.kruskal_wallis_pvalue,
        "bonferroni_alpha": report.bonferroni_alpha,
        "significant_hours_utc": report.significant_hours,
        "note": (
            "Descriptive only. No strategy or trading rule is derived here. "
            "significant_hours_utc are the hours whose return distribution "
            "differs from all other hours combined at the Bonferroni-"
            "corrected alpha (target_alpha / 24), guarding against the "
            "multiple-testing risk of scanning 24 hours independently. "
            "Even a flagged hour is not evidence of a tradeable edge on its "
            "own -- see RESEARCH_RULES.md."
        ),
    }
