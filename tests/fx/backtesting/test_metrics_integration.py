from __future__ import annotations

from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.metrics_adapter import to_neutral_backtest_result
from src.fx.backtesting.models import TargetPosition
from src.metrics.metrics import build_metrics_report, total_return

from .conftest import make_bars


def test_fx_trade_results_accepted_without_old_engine_dependency(make_config):
    """metrics.py must consume an FX result end to end (report built,
    totals computed) using only the neutral adapter -- the import-graph
    guarantee itself is asserted separately below."""
    bars = make_bars([1.1000, 1.1000, 1.1100, 1.1050, 1.1000])
    signals = [
        TargetPosition.LONG,
        TargetPosition.LONG,
        TargetPosition.FLAT,
        TargetPosition.SHORT,
        TargetPosition.FLAT,
    ]
    engine = FxBacktestEngine(make_config())
    fx_result = engine.run(bars, signals)

    neutral = to_neutral_backtest_result(fx_result)
    report = build_metrics_report(neutral, periods_per_year=252 * 24)

    assert report["num_trades"] == len(fx_result.trades)
    assert isinstance(total_return(neutral), float)


def test_metrics_module_has_no_old_engine_import():
    import src.metrics.metrics as metrics_module
    import inspect

    source = inspect.getsource(metrics_module)
    assert "from src.backtesting.engine import" not in source
    assert "src.backtesting.models" in source
