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


def total_return(result: BacktestResult) -> float:
    return (result.final_equity / result.initial_capital) - 1.0


def annualized_return(result: BacktestResult, timeframe: str) -> float | None:
    n_bars = len(result.equity_curve)
    periods_per_year = TRADING_PERIODS_PER_YEAR.get(timeframe)
    if periods_per_year is None or n_bars < 2:
        return None
    years = n_bars / periods_per_year
    if years <= 0:
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
    downside = excess[excess < 0]
    if len(downside) == 0:
        return None  # no downside deviation: ratio undefined, not infinite
    downside_std = downside.std()
    if downside_std == 0 or np.isnan(downside_std):
        return None
    return float((excess.mean() / downside_std) * math.sqrt(periods_per_year))


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
        notes.append("annualized_return: unavailable (unsupported timeframe or too few bars)")
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
