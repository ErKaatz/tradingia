from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig
from src.research.annual import annual_strategy_metrics
from src.research.holdout import guard_final_holdout_evaluation, split_final_holdout
from src.research.monte_carlo import monte_carlo_trade_returns
from src.research.parameter_study import generate_parameter_grid
from src.research.stress import DEFAULT_COST_SCENARIOS
from src.research.volatility_filter import apply_realized_volatility_entry_filter
from src.research.walk_forward import generate_walk_forward_windows
from src.strategies.breakout import Breakout
from src.strategies.buy_and_hold import BuyAndHold


def make_df(n=200, start="2024-01-01", freq="h"):
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    close = 100 + np.sin(np.arange(n)/8) + np.arange(n)*0.02
    return pd.DataFrame({"timestamp": idx, "open": close, "high": close+1, "low": close-1, "close": close, "volume": 1.0})


def test_parameter_grid_discards_invalid_sma_pairs():
    grid = generate_parameter_grid("sma_cross", {"fast": [10, 50], "slow": [20, 50]})
    assert {tuple(sorted(x.items())) for x in grid} == {
        tuple(sorted({"fast": 10, "slow": 20}.items())),
        tuple(sorted({"fast": 10, "slow": 50}.items())),
    }


def test_parameter_grid_rejects_empty_value_list():
    with pytest.raises(ValueError):
        generate_parameter_grid("momentum", {"lookback": []})


def test_breakout_excludes_current_bar_from_channel():
    df = make_df(10)
    # Current bar itself makes a dramatic high, but close does not exceed the
    # PRIOR 3-bar high. Including current high in channel would alter semantics.
    df.loc[5, "high"] = 1000
    s = Breakout(entry_lookback=3, exit_lookback=2).generate_signals(df)
    truncated = Breakout(entry_lookback=3, exit_lookback=2).generate_signals(df.iloc[:6].copy())
    assert s.iloc[:6].tolist() == truncated.tolist()


def test_breakout_truncation_invariance_no_future_lookahead():
    df = make_df(100)
    full = Breakout(10, 5).generate_signals(df)
    for cut in (20, 50, 80):
        partial = Breakout(10, 5).generate_signals(df.iloc[:cut].copy())
        assert partial.tolist() == full.iloc[:cut].tolist()


def test_holdout_split_exact_boundary():
    df = make_df(72, start="2024-12-30")
    split = split_final_holdout(df, "2025-01-01")
    assert (pd.to_datetime(split.research.timestamp, utc=True) < split.cutoff).all()
    assert (pd.to_datetime(split.final_holdout.timestamp, utc=True) >= split.cutoff).all()


def test_holdout_guard_rejects_locked_rows():
    df = make_df(48, start="2025-01-01")
    with pytest.raises(PermissionError):
        guard_final_holdout_evaluation(df, "2025-01-01", allow=False)


def test_holdout_guard_allows_explicit_future_unlock():
    df = make_df(48, start="2025-01-01")
    guard_final_holdout_evaluation(df, "2025-01-01", allow=True)


def test_walk_forward_has_train_before_evaluation_and_no_eval_overlap():
    df = make_df(24*365*4, start="2020-01-01")
    windows = generate_walk_forward_windows(df, 24, 6)
    assert windows
    for w in windows:
        assert w.train_end < w.evaluation_start <= w.evaluation_end
    for a, b in zip(windows, windows[1:]):
        assert a.evaluation_end < b.evaluation_start


def test_walk_forward_train_never_uses_future_eval_data():
    df = make_df(24*365*3, start="2020-01-01")
    for w in generate_walk_forward_windows(df, 12, 6):
        assert w.train_end < w.evaluation_start


def test_cost_scenarios_are_predeclared_and_monotone_multipliers():
    assert [s.name for s in DEFAULT_COST_SCENARIOS] == ["A_base","B_slippage_x2","C_slippage_x3","D_fee_x2","E_fee_x2_slippage_x3"]
    assert DEFAULT_COST_SCENARIOS[2].slippage_multiplier == 3
    assert DEFAULT_COST_SCENARIOS[4].fee_multiplier == 2


def test_monte_carlo_is_reproducible_and_keeps_trade_count():
    r = [0.1, -0.03, 0.02, 0.04, -0.01]
    a, fa, da = monte_carlo_trade_returns(r, simulations=100, seed=7)
    b, fb, db = monte_carlo_trade_returns(r, simulations=100, seed=7)
    assert a.num_trades == len(r)
    assert np.array_equal(fa, fb)
    assert np.array_equal(da, db)


def test_monte_carlo_rejects_impossible_loss():
    with pytest.raises(ValueError):
        monte_carlo_trade_returns([-1.0, 0.1])


def test_annual_metrics_use_only_calendar_year():
    # 2023 rises; 2024 falls. If years leak into each other, signs can blur.
    idx = pd.date_range("2023-01-01", "2024-12-31 23:00", freq="h", tz="UTC")
    n23 = (idx.year == 2023).sum()
    close = np.concatenate([np.linspace(100, 200, n23), np.linspace(200, 100, len(idx)-n23)])
    df = pd.DataFrame({"timestamp":idx,"open":close,"high":close+1,"low":close-1,"close":close,"volume":1.0})
    annual = annual_strategy_metrics(df, BuyAndHold, BacktestConfig(trading_fee=0, slippage=0), "1h")
    assert annual[2023]["total_return"] > 0
    assert annual[2024]["total_return"] < 0


def test_volatility_filter_is_truncation_invariant():
    df = make_df(100)
    base = pd.Series([0]*20 + [1]*80)
    full = apply_realized_volatility_entry_filter(df, base, window=10, min_vol=0)
    part = apply_realized_volatility_entry_filter(df.iloc[:60].copy(), base.iloc[:60].copy(), window=10, min_vol=0)
    assert full.iloc[:60].tolist() == part.tolist()
