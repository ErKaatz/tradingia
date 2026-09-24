from __future__ import annotations

from decimal import Decimal

from src.fx.backtesting.engine import FxBacktestEngine
from src.fx.backtesting.metrics_adapter import to_neutral_backtest_result
from src.fx.backtesting.models import PositionSide, TargetPosition
from src.fx.research.phase5d_runner import _finite_json, _metrics

from .conftest import make_bars


def _run(make_config, prices, signals):
    config = make_config(initial_balance=Decimal("1"), terminate_on_insolvency=True)
    return FxBacktestEngine(config).run(make_bars(prices, spread=0), signals)


def test_long_equity_insolvency_is_terminal_and_auditable(make_config):
    result = _run(make_config, [1.1, 1.1, 0.9, 0.8, 0.7], [TargetPosition.LONG] * 5)

    assert result.insolvent is True
    assert result.terminated_early is True
    assert result.termination_reason == "INSOLVENCY"
    assert result.termination_timestamp == result.equity_curve[-1][0]
    assert result.final_account.equity <= 0
    assert len(result.equity_curve) == 3
    assert result.equity_curve[-1][2] is PositionSide.LONG
    assert result.trades == []  # no fictional liquidation or later fees


def test_short_equity_insolvency_is_terminal_and_no_later_entry(make_config):
    result = _run(make_config, [1.0, 1.0, 1.2, 1.3, 1.4], [TargetPosition.SHORT] * 5)

    assert result.insolvent is True
    assert len(result.equity_curve) == 3
    assert len(result.trades) == 0


def test_flat_control_stays_solvent_and_has_normal_end(make_config):
    bars = make_bars([1.1, 0.9, 1.2, 0.8], spread=0)
    result = FxBacktestEngine(make_config(initial_balance=Decimal("1"), terminate_on_insolvency=True)).run(bars, [TargetPosition.FLAT] * len(bars))

    assert result.insolvent is False
    assert result.termination_reason is None
    assert result.final_account.balance == Decimal("1")
    assert result.final_account.equity == Decimal("1")
    assert result.trades == []


def test_insolvency_metrics_are_explicit_and_json_safe(make_config):
    result = _run(make_config, [1.1, 1.1, 0.9, 0.8], [TargetPosition.LONG] * 4)
    report = _metrics(result)

    assert report["total_return"] == -1.0
    assert report["annualized_return"] is None
    assert report["sharpe_ratio"] is None
    assert report["sortino_ratio"] is None
    assert report["volatility_annualized"] is None
    assert _finite_json(report) == report
    assert to_neutral_backtest_result(result).equity_curve["position"].iloc[-1] == 1


def test_insolvency_run_is_deterministic(make_config):
    prices = [1.0, 1.0, 0.8, 0.7]
    signals = [TargetPosition.LONG] * len(prices)
    first = _run(make_config, prices, signals)
    second = _run(make_config, prices, signals)

    assert first.final_account == second.final_account
    assert first.equity_curve == second.equity_curve
    assert first.termination_timestamp == second.termination_timestamp
