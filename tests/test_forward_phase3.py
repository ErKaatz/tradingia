import pandas as pd
import pytest
from src.strategies.breakout_forward import BreakoutConfirmed24h, BreakoutAdaptiveVolGate
from src.forward.runner import FROZEN_START, FROZEN_VARIANTS


def _df(n=9200):
    ts=pd.date_range('2025-01-01',periods=n,freq='h',tz='UTC')
    close=pd.Series([100.0 + i*0.01 for i in range(n)])
    return pd.DataFrame({'timestamp':ts,'open':close,'high':close+0.1,'low':close-0.1,'close':close,'volume':1.0})


def test_forward_start_frozen():
    assert FROZEN_START == pd.Timestamp('2026-09-03T00:00:00Z')
    assert [n for n,_ in FROZEN_VARIANTS] == ['baseline_168_60','baseline_168_72','confirmed24_168_60','adaptive_vol_168_60']


def test_confirmed_strategy_params_frozen():
    with pytest.raises(ValueError):
        BreakoutConfirmed24h(168,60,12)


def test_vol_gate_params_frozen():
    with pytest.raises(ValueError):
        BreakoutAdaptiveVolGate(168,60,168,1000)


def test_confirmed_has_no_future_dependence():
    df=_df(500)
    s=BreakoutConfirmed24h().generate_signals(df)
    cut=350
    s2=BreakoutConfirmed24h().generate_signals(df.iloc[:cut].copy())
    pd.testing.assert_series_equal(s.iloc[:cut].reset_index(drop=True), s2.reset_index(drop=True))


def test_vol_gate_has_no_future_dependence():
    df=_df(9200)
    s=BreakoutAdaptiveVolGate().generate_signals(df)
    cut=9100
    s2=BreakoutAdaptiveVolGate().generate_signals(df.iloc[:cut].copy())
    pd.testing.assert_series_equal(s.iloc[:cut].reset_index(drop=True), s2.reset_index(drop=True))
