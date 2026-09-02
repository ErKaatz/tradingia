import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig
from src.research.holdout_eval import (
    FROZEN_CANDIDATES,
    _run_with_warmup,
    validate_preregistration,
)
from src.strategies.breakout import Breakout


def _raw(candidates=None, start="2025-01-01", search=False):
    if candidates is None:
        candidates = [
            {"entry_lookback": 168, "exit_lookback": 60},
            {"entry_lookback": 168, "exit_lookback": 72},
        ]
    return {
        "final_holdout_start": start,
        "candidates": candidates,
        "allow_parameter_search": search,
    }


def test_frozen_candidates_are_exactly_two():
    assert FROZEN_CANDIDATES == ((168, 60), (168, 72))
    validate_preregistration(_raw())


def test_third_candidate_is_rejected():
    c = _raw()["candidates"] + [{"entry_lookback": 144, "exit_lookback": 60}]
    with pytest.raises(PermissionError):
        validate_preregistration(_raw(candidates=c))


def test_reordered_or_changed_candidate_is_rejected():
    c = [
        {"entry_lookback": 168, "exit_lookback": 72},
        {"entry_lookback": 168, "exit_lookback": 60},
    ]
    with pytest.raises(PermissionError):
        validate_preregistration(_raw(candidates=c))


def test_holdout_boundary_is_frozen():
    with pytest.raises(PermissionError):
        validate_preregistration(_raw(start="2025-02-01"))


def test_parameter_search_is_rejected():
    with pytest.raises(PermissionError):
        validate_preregistration(_raw(search=True))


def test_warmup_does_not_enter_equity_or_trades_before_holdout():
    # Enough synthetic bars for the breakout to warm up; all prices rise so
    # the strategy eventually enters. Pre-holdout data must not appear in
    # returned equity/trades even though it supplies indicator context.
    n_research = 220
    n_holdout = 60
    ts = pd.date_range("2024-12-01", periods=n_research + n_holdout, freq="h", tz="UTC")
    base = pd.Series(range(100, 100 + len(ts)), dtype=float)
    df = pd.DataFrame({
        "timestamp": ts,
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base + 0.5,
        "volume": 1.0,
    })
    research = df.iloc[:n_research].reset_index(drop=True)
    holdout = df.iloc[n_research:].reset_index(drop=True)
    result, _ = _run_with_warmup(
        research, holdout, Breakout(168, 60), BacktestConfig(trading_fee=0, slippage=0), "1h"
    )
    holdout_start = holdout.timestamp.iloc[0]
    assert pd.to_datetime(result.equity_curve.timestamp, utc=True).min() >= holdout_start
    if result.trades:
        assert min(pd.Timestamp(t.entry_time) for t in result.trades) >= holdout_start


def test_annual_holdout_factory_and_context_are_callable_and_preserve_prior_history():
    """Regression test for final-holdout annual reporting.

    annual_strategy_metrics expects a factory, not a Strategy instance, and the
    first holdout year needs pre-boundary bars as indicator warm-up.
    """
    from src.research.annual import annual_strategy_metrics

    ts = pd.date_range("2024-12-20", periods=500, freq="h", tz="UTC")
    base = pd.Series(range(100, 100 + len(ts)), dtype=float)
    df = pd.DataFrame({
        "timestamp": ts,
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base + 0.5,
        "volume": 1.0,
    })
    holdout_start = pd.Timestamp("2025-01-01", tz="UTC")
    research = df.loc[df.timestamp < holdout_start].reset_index(drop=True)
    holdout = df.loc[df.timestamp >= holdout_start].reset_index(drop=True)
    strategy = Breakout(168, 60)
    annual_context = pd.concat(
        [research.tail(strategy.warmup_bars), holdout], ignore_index=True
    )
    annual = annual_strategy_metrics(
        annual_context,
        lambda: Breakout(168, 60),
        BacktestConfig(trading_fee=0, slippage=0),
        "1h",
    )
    assert 2025 in annual
