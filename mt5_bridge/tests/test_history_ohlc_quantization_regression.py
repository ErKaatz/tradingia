"""Regression test for a real-world OHLC float artifact observed in HFM
demo testing on 2026-09-03 (FX Phase 0, Step 3.1 follow-up).

A live `copy_rates_range` call against HFM's MT5 terminal returned
`open=1.1584699999999999` (M15) and `open=1.1586400000000001` (H1) for
EURUSD (digits=5). Investigation (documented in the Step 3.1 follow-up
report) confirmed the CURRENT `RealMT5Backend.copy_rates_range` code
already runs every OHLC field through `quantize_price(value, digits)`
before constructing `BackendBar` -- verified here end-to-end with a
`MetaTrader5`-shaped stub carrying the exact real values, not just a
direct `quantize_price` unit test. The root cause of the field
observation was a stale `mt5_bridge/` deployment on the Windows VM that
predated this quantization being added to `copy_rates_range` -- not a
defect in this code. This test exists so that regression here is
caught immediately by the test suite, independent of what is or isn't
currently deployed to any given VM.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pytest

from mt5_bridge.app import create_app
from mt5_bridge.config import BridgeConfig
from src.execution.base import ExecutionTimeframe, HistoryRequest
from src.execution.mt5_remote import MT5RemoteExecutionClient

# The exact real-world observed values (2026-09-03, HFM demo, EURUSD digits=5).
REAL_M15_OPEN = 1.1584699999999999
REAL_H1_OPEN = 1.1586400000000001

_RATES_DTYPE = np.dtype(
    [
        ("time", "i8"),
        ("open", "f8"),
        ("high", "f8"),
        ("low", "f8"),
        ("close", "f8"),
        ("tick_volume", "u8"),
        ("spread", "i4"),
        ("real_volume", "u8"),
    ]
)


def _make_mt5_stub(open_value: float, high: float, low: float, close: float):
    """Builds a MagicMock standing in for the `MetaTrader5` module,
    returning a real numpy structured array (the actual shape MT5's
    `copy_rates_range` returns) containing the given OHLC values.
    """

    stub = MagicMock()
    stub.TIMEFRAME_M15 = 15
    stub.TIMEFRAME_H1 = 16

    rates = np.zeros(1, dtype=_RATES_DTYPE)
    rates[0]["time"] = int(datetime(2026, 9, 3, tzinfo=timezone.utc).timestamp())
    rates[0]["open"] = open_value
    rates[0]["high"] = high
    rates[0]["low"] = low
    rates[0]["close"] = close
    rates[0]["tick_volume"] = 100
    rates[0]["spread"] = 2
    rates[0]["real_volume"] = 0
    stub.copy_rates_range.return_value = rates

    symbol_info = MagicMock()
    symbol_info.digits = 5
    stub.symbol_info.return_value = symbol_info

    return stub


def _real_backend_with_stub(mt5_stub) -> "RealMT5Backend":
    """This fixture predates FX Phase 0's server-clock-offset auto-
    calibration (mt5_bridge/server_clock.py) and its tests are purely
    about OHLC Decimal-cleaning, not timestamps -- so the clock offset is
    pre-seeded to exactly 0 here (as if already calibrated against a
    server with no skew) rather than exercising real calibration, which
    is covered separately in mt5_bridge/tests/test_server_clock.py.
    """

    from datetime import timezone as _tz

    from mt5_bridge.backend import RealMT5Backend
    from mt5_bridge.server_clock import ServerClockOffset

    backend = RealMT5Backend.__new__(RealMT5Backend)
    backend._mt5 = mt5_stub
    backend._connected = True
    clock = ServerClockOffset()
    clock.to_utc(datetime.now(_tz.utc), bridge_now_utc=datetime.now(_tz.utc))
    backend._server_clock = clock
    return backend


# --- 1. RealMT5Backend.copy_rates_range -> BackendBar, exact real values ---


def test_real_backend_copy_rates_range_cleans_m15_artifact():
    """Reproduces the exact M15 case: 1.1584699999999999 -> Decimal('1.15847')."""
    stub = _make_mt5_stub(open_value=REAL_M15_OPEN, high=1.15860, low=1.15840, close=1.15850)
    backend = _real_backend_with_stub(stub)

    bars = backend.copy_rates_range(
        "EURUSD", "M15", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )

    assert len(bars) == 1
    assert bars[0].open == Decimal("1.15847")
    assert str(bars[0].open) == "1.15847"


def test_real_backend_copy_rates_range_cleans_h1_artifact():
    """Reproduces the exact H1 case: 1.1586400000000001 -> Decimal('1.15864')."""
    stub = _make_mt5_stub(open_value=REAL_H1_OPEN, high=1.15900, low=1.15800, close=1.15870)
    backend = _real_backend_with_stub(stub)

    bars = backend.copy_rates_range(
        "EURUSD", "H1", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )

    assert len(bars) == 1
    assert bars[0].open == Decimal("1.15864")
    assert str(bars[0].open) == "1.15864"


def test_real_backend_copy_rates_range_cleans_all_ohlc_fields_not_just_open():
    """The same artifact pattern applied to high/low/close as well --
    the requirement is ALL FOUR OHLC fields, not just open."""
    stub = _make_mt5_stub(
        open_value=1.1584699999999999,
        high=1.1585400000000002,
        low=1.1583999999999998,
        close=1.1584999999999999,
    )
    backend = _real_backend_with_stub(stub)

    bars = backend.copy_rates_range(
        "EURUSD", "M15", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )

    bar = bars[0]
    assert bar.open == Decimal("1.15847")
    assert bar.high == Decimal("1.15854")
    assert bar.low == Decimal("1.15840")
    assert bar.close == Decimal("1.15850")
    for field_value in (bar.open, bar.high, bar.low, bar.close):
        assert isinstance(field_value, Decimal)
        assert len(str(field_value).split(".")[-1]) <= 5  # no more than `digits` decimal places


def test_real_backend_copy_rates_range_filters_mt5_bars_outside_requested_interval():
    """The bridge, not MT5, enforces its advertised inclusive range."""
    stub = _make_mt5_stub(open_value=1.1, high=1.101, low=1.099, close=1.1005)
    rates = np.zeros(2, dtype=_RATES_DTYPE)
    rates[0] = stub.copy_rates_range.return_value[0]
    rates[1] = stub.copy_rates_range.return_value[0]
    rates[1]["time"] = int(datetime(2022, 8, 24, tzinfo=timezone.utc).timestamp())
    stub.copy_rates_range.return_value = rates
    backend = _real_backend_with_stub(stub)

    bars = backend.copy_rates_range(
        "EURUSD", "M15", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )

    assert len(bars) == 1
    assert bars[0].time_utc == datetime(2026, 9, 3, tzinfo=timezone.utc)


# --- 2. history_response JSON carries the clean string ---


def test_history_response_json_contains_clean_open_string_m15():
    stub = _make_mt5_stub(open_value=REAL_M15_OPEN, high=1.15860, low=1.15840, close=1.15850)
    backend = _real_backend_with_stub(stub)
    from mt5_bridge.schemas import history_response

    bars = backend.copy_rates_range(
        "EURUSD", "M15", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )
    body = history_response(bars)
    assert body["bars"][0]["open"] == "1.15847"


def test_history_response_json_contains_clean_open_string_h1():
    stub = _make_mt5_stub(open_value=REAL_H1_OPEN, high=1.15900, low=1.15800, close=1.15870)
    backend = _real_backend_with_stub(stub)
    from mt5_bridge.schemas import history_response

    bars = backend.copy_rates_range(
        "EURUSD", "H1", datetime(2026, 9, 3, tzinfo=timezone.utc), datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
    )
    body = history_response(bars)
    assert body["bars"][0]["open"] == "1.15864"


# --- 3. full HTTP response body (bridge layer) carries the clean string ---


def test_bridge_http_response_open_field_is_clean_string():
    from fastapi.testclient import TestClient

    stub = _make_mt5_stub(open_value=REAL_M15_OPEN, high=1.15860, low=1.15840, close=1.15850)
    backend = _real_backend_with_stub(stub)
    config = BridgeConfig(host="127.0.0.1", port=8765, api_token="regression-test-token")
    app = create_app(backend, config)
    client = TestClient(app)

    resp = client.get(
        "/v1/history/EURUSD",
        params={"start": "2026-09-03T00:00:00+00:00", "end": "2026-09-03T01:00:00+00:00", "timeframe": "M15"},
        headers={"Authorization": "Bearer regression-test-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["bars"][0]["open"] == "1.15847"


# --- 4. client-side integration: clean JSON -> clean HistoryBar.Decimal ---


def test_client_parses_clean_json_into_clean_decimal():
    """End-to-end from the bridge's JSON shape through the Linux client's
    own parser (`_parse_history_bar`), confirming the client sees the
    already-clean string and produces an equally clean Decimal -- no
    float arithmetic reintroduced client-side."""
    from src.execution.mt5_remote import _parse_history

    payload = {
        "bars": [
            {
                "timestamp": "2026-09-03T00:00:00+00:00",
                "open": "1.15847",
                "high": "1.15860",
                "low": "1.15840",
                "close": "1.15850",
                "tick_volume": "100",
            }
        ]
    }
    result = _parse_history(payload, "EURUSD")
    assert result.bars[0].open == Decimal("1.15847")
    assert str(result.bars[0].open) == "1.15847"
