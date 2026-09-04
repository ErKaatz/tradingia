"""Unit tests for src/fx/data/time_diagnostics.py's observation logic
(mocked client -- no real MT5/bridge access).

Real-bridge empirical validation is a separate, explicitly marked
integration test -- see tests/fx/test_time_diagnostics_integration.py,
which is skipped unless a real bridge is configured (see
PHASE5A_STATUS.md's Empirical Findings section for the current,
pending status and the exact command to run it manually).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.execution.base import ExecutionTimeframe, HealthStatus, HistoryBar, HistoryResult
from src.fx.data.schema import FxBar
from src.fx.data.time_diagnostics import observe_h4_alignment, observe_weekend_gap, run_time_diagnostics


class _MockClient:
    def __init__(self, bars):
        self._bars = bars

    def history(self, request):
        return HistoryResult(symbol=request.symbol, bars=self._bars)

    def symbol_metadata(self, symbol):
        raise ValueError("not used by time_diagnostics")

    def account(self):
        raise ValueError("not used by time_diagnostics")

    def health(self):
        return HealthStatus(bridge_alive=True, terminal_connected=True, server_time=None)


def _history_bar(ts, **overrides) -> HistoryBar:
    defaults = dict(
        symbol="EURUSD", timestamp=ts,
        open=Decimal("1.1000"), high=Decimal("1.1010"), low=Decimal("1.0990"), close=Decimal("1.1005"),
        tick_volume=Decimal("120"), real_volume=None, spread_points=10,
    )
    defaults.update(overrides)
    return HistoryBar(**defaults)


def _fx_bar(ts) -> FxBar:
    return FxBar(
        timestamp_utc=ts, open=Decimal("1.1"), high=Decimal("1.11"), low=Decimal("1.09"), close=Decimal("1.1"),
        tick_volume=Decimal("100"), real_volume=None, spread_points=None,
    )


def test_observe_weekend_gap_finds_friday_to_sunday_boundary():
    friday = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    sunday = datetime(2026, 1, 4, 22, tzinfo=timezone.utc)
    bars = (_fx_bar(friday), _fx_bar(sunday))
    observation = observe_weekend_gap(bars)
    assert observation.last_bar_before_weekend.timestamp_utc == friday
    assert observation.first_bar_after_weekend.timestamp_utc == sunday
    assert observation.gap_duration is not None


def test_observe_weekend_gap_no_boundary_found():
    ts1 = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 5, 11, tzinfo=timezone.utc)
    observation = observe_weekend_gap((_fx_bar(ts1), _fx_bar(ts2)))
    assert observation.last_bar_before_weekend is None
    assert observation.gap_duration is None


def test_observe_weekend_gap_counts_sunday_bars():
    sunday1 = datetime(2026, 1, 4, 21, tzinfo=timezone.utc)
    sunday2 = datetime(2026, 1, 4, 22, tzinfo=timezone.utc)
    observation = observe_weekend_gap((_fx_bar(sunday1), _fx_bar(sunday2)))
    assert observation.sunday_bars_found == 2


def test_observe_h4_alignment_reports_distinct_hours():
    bars = (_fx_bar(datetime(2026, 1, 5, 0, tzinfo=timezone.utc)), _fx_bar(datetime(2026, 1, 5, 4, tzinfo=timezone.utc)))
    observation = observe_h4_alignment(bars)
    assert observation.hours_of_day_seen == (0, 4)


def test_run_time_diagnostics_reports_h4_alignment_only_for_h4():
    ts = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    client = _MockClient(bars=(_history_bar(ts),))
    report_h1 = run_time_diagnostics(client, "EURUSD", ts, end, timeframe=ExecutionTimeframe.H1)
    report_h4 = run_time_diagnostics(client, "EURUSD", ts, end, timeframe=ExecutionTimeframe.H4)
    assert report_h1.h4_alignment is None
    assert report_h4.h4_alignment is not None


def test_run_time_diagnostics_empty_response_reports_zero_bars():
    client = _MockClient(bars=())
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    report = run_time_diagnostics(client, "EURUSD", start, end)
    assert report.bar_count == 0
    assert report.first_bar_timestamp_utc is None
    assert report.weekend_gap is None


def test_run_time_diagnostics_bridge_error_propagates():
    import pytest

    class _RaisingClient:
        def history(self, request):
            raise ConnectionError("bridge unreachable")

    with pytest.raises(ConnectionError):
        run_time_diagnostics(_RaisingClient(), "EURUSD", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
