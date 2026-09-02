"""Performance metrics computed from a BacktestResult.

All functions are pure (take plain data in, return plain data out) so each
one can be unit tested in isolation against hand-computed expected values.
Where a metric is not meaningful for the data at hand (e.g. annualized
return on a dataset spanning under a day, or win rate with zero trades), the
function returns None rather than a misleading number, and the caller
(build_metrics_report) records why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestResult

TRADING_PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


SECONDS_PER_YEAR = 365 * 24 * 3600


def total_return(result: BacktestResult) -> float:
    return (result.final_equity / result.initial_capital) - 1.0


def elapsed_years(result: BacktestResult) -> float | None:
    """Wall-clock duration of the evaluated period, in years, computed from
    the equity curve's actual first/last timestamps rather than a bar count.

    Using real elapsed time (instead of `n_bars / periods_per_year`) keeps
    this correct even when the data has gaps or missing candles: a period
    with 5 missing days is still ~5 fewer days long in reality, not a period
    that "doesn't count" those days while still spanning them chronologically.
    """
    equity = result.equity_curve
    if len(equity) < 2:
        return None
    start_ts = pd.Timestamp(equity["timestamp"].iloc[0])
    end_ts = pd.Timestamp(equity["timestamp"].iloc[-1])
    seconds = (end_ts - start_ts).total_seconds()
    if seconds <= 0:
        return None
    return seconds / SECONDS_PER_YEAR


def annualized_return(result: BacktestResult, timeframe: str | None = None) -> float | None:
    """Compound annual growth rate over the evaluated period.

    Computed from real elapsed wall-clock time (see `elapsed_years`), not
    from a bar count divided by a nominal periods-per-year for `timeframe`.
    `timeframe` is accepted for API symmetry with the other metrics but is
    no longer used in this computation; it may be removed once callers stop
    passing it.
    """
    years = elapsed_years(result)
    if years is None:
        return None
    ratio = result.final_equity / result.initial_capital
    if ratio <= 0:
        # Total wipeout: annualized return is mathematically -100%,
        # not undefined, but flag it distinctly from a "can't compute" None.
        return -1.0
    return ratio ** (1 / years) - 1.0


def bar_returns(result: BacktestResult) -> pd.Series:
    equity = result.equity_curve["equity"]
    return equity.pct_change().dropna()


def volatility(result: BacktestResult, timeframe: str, annualize: bool = True) -> float | None:
    returns = bar_returns(result)
    if len(returns) < 2:
        return None
    vol = returns.std()
    if annualize:
        periods_per_year = TRADING_PERIODS_PER_YEAR.get(timeframe)
        if periods_per_year is None:
            return None
        vol *= math.sqrt(periods_per_year)
    return float(vol)


def sharpe_ratio(
    result: BacktestResult, timeframe: str, risk_free_rate: float = 0.0
) -> float | None:
    returns = bar_returns(result)
    if len(returns) < 2:
        return None
    periods_per_year = TRADING_PERIODS_PER_YEAR.get(timeframe)
    if periods_per_year is None:
        return None
    period_rf = risk_free_rate / periods_per_year
    excess = returns - period_rf
    std = excess.std()
    if std == 0 or np.isnan(std):
        return None
    return float((excess.mean() / std) * math.sqrt(periods_per_year))


def sortino_ratio(
    result: BacktestResult,
    timeframe: str,
    minimum_acceptable_return: float = 0.0,
) -> float | None:
    """Sortino ratio using the standard definition:

        (mean(period_return) - MAR_period) / downside_deviation

    where MAR_period is the Minimum Acceptable Return for a single bar
    (`minimum_acceptable_return`, an annual rate, divided by periods/year —
    same role a risk-free rate plays in Sharpe; 0.0 means "any loss counts
    as downside", the common default), and downside_deviation is the
    root-mean-square of (period_return - MAR_period) over bars where the
    return fell BELOW the MAR — with underperforming bars counted against
    the FULL sample size N, not just the count of losing bars. This
    (Sortino & van der Meer's original definition) is deliberately not the
    "std of negative returns only" formula sometimes seen in simplified
    implementations, which understates risk by ignoring how frequently
    losses occur relative to the whole sample.

    Both the mean excess return and the downside deviation are annualized
    by sqrt(periods_per_year) / periods_per_year in the standard way, so the
    ratio is on the same annualized scale as `sharpe_ratio`.
    """
    returns = bar_returns(result)
    if len(returns) < 2:
        return None
    periods_per_year = TRADING_PERIODS_PER_YEAR.get(timeframe)
    if periods_per_year is None:
        return None
    mar_period = minimum_acceptable_return / periods_per_year
    excess = returns - mar_period

    downside_diff = excess.clip(upper=0.0)
    downside_deviation = math.sqrt((downside_diff**2).sum() / len(excess))
    if downside_deviation == 0 or np.isnan(downside_deviation):
        return None  # no downside relative to MAR: ratio undefined, not infinite

    return float((excess.mean() / downside_deviation) * math.sqrt(periods_per_year))


@dataclass
class DrawdownInfo:
    max_drawdown_pct: float
    max_drawdown_duration_bars: int


def max_drawdown(result: BacktestResult) -> DrawdownInfo:
    equity = result.equity_curve["equity"]
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max

    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    # Duration: longest run of consecutive bars strictly below a prior peak.
    in_drawdown = equity < running_max
    max_duration = 0
    current_duration = 0
    for flag in in_drawdown:
        if flag:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return DrawdownInfo(max_drawdown_pct=max_dd, max_drawdown_duration_bars=max_duration)


def market_exposure(result: BacktestResult) -> float:
    """Fraction of bars during which the strategy held a position."""
    position = result.equity_curve["position"]
    if len(position) == 0:
        return 0.0
    return float((position != 0).mean())


@dataclass
class TradeStats:
    num_trades: int
    win_rate: float | None
    average_win: float | None
    average_loss: float | None
    expectancy: float | None
    profit_factor: float | None
    total_fees: float


def trade_stats(result: BacktestResult) -> TradeStats:
    trades = result.trades
    num_trades = len(trades)
    total_fees = sum(t.total_fees for t in trades)

    if num_trades == 0:
        return TradeStats(
            num_trades=0,
            win_rate=None,
            average_win=None,
            average_loss=None,
            expectancy=None,
            profit_factor=None,
            total_fees=total_fees,
        )

    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / num_trades
    average_win = (sum(wins) / len(wins)) if wins else None
    average_loss = (sum(losses) / len(losses)) if losses else None
    expectancy = sum(pnls) / num_trades

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    return TradeStats(
        num_trades=num_trades,
        win_rate=win_rate,
        average_win=average_win,
        average_loss=average_loss,
        expectancy=expectancy,
        profit_factor=profit_factor,
        total_fees=total_fees,
    )


def build_metrics_report(result: BacktestResult, timeframe: str) -> dict[str, Any]:
    """Assemble the full metrics dict saved into metrics.json for an
    experiment. Any metric that could not be computed meaningfully is
    reported as null with an accompanying note.
    """
    dd = max_drawdown(result)
    stats = trade_stats(result)

    ann_return = annualized_return(result, timeframe)
    sharpe = sharpe_ratio(result, timeframe)
    sortino = sortino_ratio(result, timeframe)
    vol = volatility(result, timeframe)

    notes = []
    if ann_return is None:
        notes.append("annualized_return: unavailable (fewer than 2 bars or zero elapsed time)")
    if sharpe is None:
        notes.append("sharpe_ratio: unavailable (insufficient variance or data)")
    if sortino is None:
        notes.append("sortino_ratio: unavailable (no downside periods or insufficient data)")
    if stats.num_trades == 0:
        notes.append("trade-level stats unavailable: zero trades executed")
    elif stats.num_trades < 30:
        notes.append(
            f"only {stats.num_trades} trades executed: trade-level statistics "
            "(win rate, profit factor, expectancy) are not statistically reliable"
        )
    if stats.profit_factor is None and stats.num_trades > 0:
        notes.append("profit_factor: unavailable (no losing trades to divide by)")

    return {
        "total_return": total_return(result),
        "annualized_return": ann_return,
        "num_trades": stats.num_trades,
        "win_rate": stats.win_rate,
        "average_win": stats.average_win,
        "average_loss": stats.average_loss,
        "expectancy": stats.expectancy,
        "profit_factor": stats.profit_factor,
        "max_drawdown_pct": dd.max_drawdown_pct,
        "max_drawdown_duration_bars": dd.max_drawdown_duration_bars,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "volatility_annualized": vol,
        "market_exposure": market_exposure(result),
        "total_fees": stats.total_fees,
        "final_equity": result.final_equity,
        "initial_capital": result.initial_capital,
        "notes": notes,
    }
