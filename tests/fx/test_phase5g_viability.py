from datetime import datetime, timezone

from src.fx.research.phase5g_capture import AvailabilityRecord, PHASE5G_SYMBOLS, PHASE5G_TIMEFRAMES, chunk_ranges
from src.fx.research.phase5g_viability import classify_structural_viability, select_common_window


UTC = timezone.utc


def _record(symbol="EURUSD", timeframe="M15", first="2022-09-01T00:00:00+00:00", last="2025-08-29T23:45:00+00:00", errors=()):
    return AvailabilityRecord(symbol, timeframe, "2022-09-01T00:00:00+00:00", "2025-08-30T00:00:00+00:00", first, last, 1000, {"unexpected_gap": 0}, (), errors, "data", "raw", 1)


def test_frozen_universe_and_chunking_are_exact():
    assert PHASE5G_SYMBOLS == ("EURUSD", "GBPUSD", "USDJPY")
    assert PHASE5G_TIMEFRAMES == ("M5", "M15", "H1")
    ranges = chunk_ranges(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC), "M5")
    assert ranges[0][0] == datetime(2025, 1, 1, tzinfo=UTC)
    assert ranges[-1][1] == datetime(2025, 5, 1, tzinfo=UTC)


def test_common_window_rejects_short_history_without_shortening_group():
    decision = select_common_window([_record("EURUSD", "M15"), _record("GBPUSD", "H1"), _record("USDJPY", "M5", first="2025-05-01T00:00:00+00:00")], datetime(2025, 8, 30, tzinfo=UTC))
    assert decision.start_utc == datetime(2022, 9, 1, tzinfo=UTC)
    assert {(x.symbol, x.timeframe) for x in decision.insufficient_cells} == {("USDJPY", "M5")}


def test_structural_label_boundaries_and_missing_data():
    from decimal import Decimal
    assert classify_structural_viability(bar_count=500, coverage_ratio=Decimal("0.98"), validation_errors=(), unexpected_gaps=50, median_ratio=Decimal("0.25"), p95_ratio=Decimal("1")) == "VIABLE_FOR_FUTURE_RESEARCH"
    assert classify_structural_viability(bar_count=500, coverage_ratio=Decimal("0.98"), validation_errors=(), unexpected_gaps=50, median_ratio=Decimal("0.50"), p95_ratio=Decimal("2")) == "BORDERLINE"
    assert classify_structural_viability(bar_count=499, coverage_ratio=Decimal("1"), validation_errors=(), unexpected_gaps=0, median_ratio=Decimal("0.1"), p95_ratio=Decimal("0.1")) == "INSUFFICIENT_DATA"
