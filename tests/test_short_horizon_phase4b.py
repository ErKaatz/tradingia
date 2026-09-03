from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.research.short_horizon_phase4b import (
    POSTHOC_LABEL,
    TARGET_FAMILIES,
    break_even_base_cost_multiplier_from_zero_trades,
    build_follow_through_rows,
    frozen_phase4b_variant_count,
    frozen_phase4b_variants,
    reentry_diagnostics,
    signal_strength_series,
)
from src.strategies.base import FLAT, LONG
from src.strategies.short_horizon import RangeExpansion, VolumeShockDirection, ExtremeMoveReversal


def make_df(n=600, freq='15min'):
    # deterministic gently rising tape with valid OHLCV
    close=[100.0 + i*0.05 for i in range(n)]
    return pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=n, freq=freq, tz='UTC'),
        'open': close,
        'high': [x*1.002 for x in close],
        'low': [x*0.998 for x in close],
        'close': close,
        'volume': [100.0 + (i%13)*5 for i in range(n)],
    })


def test_phase4b_uses_only_three_existing_families_and_14_variants():
    frozen=frozen_phase4b_variants()
    assert tuple(next(iter(frozen.values())).keys()) == TARGET_FAMILIES
    assert frozen_phase4b_variant_count() == 14


def test_posthoc_label_is_explicit():
    assert 'POST-HOC' in POSTHOC_LABEL
    assert 'NOT OUT-OF-SAMPLE' in POSTHOC_LABEL


def test_break_even_zero_when_even_zero_cost_loses():
    df=make_df(10)
    # buy before a drop, then exit
    df.loc[2:, ['open','high','low','close']] = [80,81,79,80]
    signals=pd.Series([FLAT,LONG,LONG,FLAT,FLAT,FLAT,FLAT,FLAT,FLAT,FLAT])
    zero=BacktestEngine(BacktestConfig(trading_fee=0.0,slippage=0.0)).run(df,signals)
    x=break_even_base_cost_multiplier_from_zero_trades(zero.trades,base_fee=0.001,base_slippage=0.0004,iterations=16)
    assert x == 0.0


def test_break_even_positive_for_large_zero_cost_edge():
    df=make_df(10)
    df.loc[2:3, ['open','high','low','close']] = [200,201,199,200]
    df.loc[4:, ['open','high','low','close']] = [300,301,299,300]
    signals=pd.Series([FLAT,LONG,LONG,FLAT,FLAT,FLAT,FLAT,FLAT,FLAT,FLAT])
    zero=BacktestEngine(BacktestConfig(trading_fee=0.0,slippage=0.0)).run(df,signals)
    x=break_even_base_cost_multiplier_from_zero_trades(zero.trades,base_fee=0.001,base_slippage=0.0004,iterations=16)
    assert x is not None and x > 1.0


def test_follow_through_uses_15m_master_and_expected_horizons():
    master=make_df(40)
    trades=pd.DataFrame([{'entry_time': master.timestamp.iloc[4]}])
    out=build_follow_through_rows(trades,master,timeframe='1h',family='range_expansion',variant_id='x')
    assert set(out.horizon_minutes)=={15,30,60,120,240}
    # rising tape -> positive close return at every horizon
    assert (out.close_return > 0).all()


def test_reentry_diagnostics_counts_trigger_runs():
    ts=pd.Series(pd.date_range('2024-01-01', periods=8, freq='h', tz='UTC'))
    cond=pd.Series([False,True,True,False,True,False,True,True])
    trades=pd.DataFrame({
        'entry_time':[ts.iloc[1],ts.iloc[4],ts.iloc[6]],
        'exit_time':[ts.iloc[3],ts.iloc[5],ts.iloc[7]],
    })
    d=reentry_diagnostics(trades,cond,ts)
    assert d['raw_entry_condition_true_bars']==5
    assert d['raw_trigger_runs']==3
    assert d['max_trigger_run_bars']==2
    assert d['executed_trades']==3


def test_strength_series_is_causal_under_future_mutation():
    df=make_df(900)
    strategies=[
        (VolumeShockDirection(volume_median_window=24,volume_multiple=2.0,close_position_threshold=.75,max_holding_bars=2),'volume_shock_direction'),
        (RangeExpansion(atr_period=14,atr_multiple=1.5,close_position_threshold=.75,max_holding_bars=2),'range_expansion'),
        (ExtremeMoveReversal(return_lookback=3,zscore_window=120,entry_z_score=-2.0,max_holding_bars=2),'extreme_move_reversal'),
    ]
    cut=700
    mutated=df.copy()
    mutated.loc[cut+1:,'close'] *= 5
    mutated.loc[cut+1:,'high'] *= 5
    mutated.loc[cut+1:,'low'] *= 5
    mutated.loc[cut+1:,'open'] *= 5
    mutated.loc[cut+1:,'volume'] *= 7
    for strat,fam in strategies:
        a=signal_strength_series(strat,df,fam).iloc[:cut+1]
        b=signal_strength_series(strat,mutated,fam).iloc[:cut+1]
        pd.testing.assert_series_equal(a,b)
