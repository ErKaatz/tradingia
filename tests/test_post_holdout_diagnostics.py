import pandas as pd
import pytest
from src.research.diagnostics import enrich_trades, summarize_enriched


def _bars():
    ts = pd.date_range('2025-01-01', periods=6, freq='h', tz='UTC')
    return pd.DataFrame({
        'timestamp': ts,
        'open': [100,101,102,99,98,103],
        'high': [101,104,103,100,105,106],
        'low': [99,100,98,95,97,102],
        'close': [100,102,99,98,104,105],
        'volume': [1]*6,
    })


def test_enrich_trade_mae_mfe_and_duration():
    trades = pd.DataFrame([{
        'entry_time':'2025-01-01T01:00:00Z','entry_price':100.0,
        'exit_time':'2025-01-01T04:00:00Z','exit_price':104.0,
        'size_base':1.0,'entry_notional':100.0,'gross_pnl':4.0,
        'entry_fee':0.1,'exit_fee':0.104,'net_pnl':3.796,'return_pct':0.03796,
    }])
    e = enrich_trades(trades, _bars())
    assert e.loc[0,'duration_hours'] == 3.0
    assert e.loc[0,'mfe_pct'] == pytest.approx(0.05)
    assert e.loc[0,'mae_pct'] == pytest.approx(-0.05)
    assert bool(e.loc[0,'winner']) is True


def test_summary_tracks_loss_streak_and_followthrough():
    bars = _bars()
    trades=[]
    for i, ret in enumerate([-0.01,-0.02,0.03]):
        trades.append({'entry_time':bars.timestamp.iloc[0], 'entry_price':100.0,
          'exit_time':bars.timestamp.iloc[2], 'exit_price':100*(1+ret), 'size_base':1,
          'entry_notional':100, 'gross_pnl':ret*100, 'entry_fee':.1,'exit_fee':.1,
          'net_pnl':ret*100-.2,'return_pct':ret})
    e=enrich_trades(pd.DataFrame(trades),bars)
    s=summarize_enriched(e)
    assert s['num_trades']==3
    assert s['max_consecutive_losses']==2
    assert s['win_rate']==pytest.approx(1/3)
