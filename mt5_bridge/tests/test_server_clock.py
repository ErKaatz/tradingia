from datetime import datetime, timedelta, timezone

import pytest

from mt5_bridge.server_clock import ServerClockCalibrationError, ServerClockOffset

UTC = timezone.utc
BASE = datetime(2026, 9, 3, 13, 32, 7, tzinfo=UTC)


def test_real_hfm_observation_calibrates_plus_three_hours():
    clock = ServerClockOffset()
    corrected = clock.to_utc(BASE + timedelta(hours=3) - timedelta(milliseconds=763), BASE)
    assert abs((corrected - BASE).total_seconds()) < 1
    assert clock.current_offset() == timedelta(hours=3)


def test_zero_offset_is_supported():
    clock = ServerClockOffset()
    corrected = clock.to_utc(BASE - timedelta(seconds=2), BASE)
    assert corrected == BASE - timedelta(seconds=2)
    assert clock.current_offset() == timedelta(0)


def test_initial_ambiguous_non_timezone_skew_fails_closed():
    clock = ServerClockOffset()
    with pytest.raises(ServerClockCalibrationError, match="refusing to guess"):
        clock.to_utc(BASE + timedelta(minutes=17), BASE)


def test_initial_implausible_offset_fails_closed():
    clock = ServerClockOffset()
    with pytest.raises(ServerClockCalibrationError, match="plausible"):
        clock.to_utc(BASE + timedelta(hours=15), BASE)


def test_stale_tick_does_not_trigger_bad_recalibration():
    clock = ServerClockOffset()
    clock.to_utc(BASE + timedelta(hours=3), BASE)
    stale_raw = BASE + timedelta(seconds=30) + timedelta(hours=3)
    corrected = clock.to_utc(stale_raw, BASE + timedelta(seconds=60))
    assert corrected == BASE + timedelta(seconds=30)
    assert clock.current_offset() == timedelta(hours=3)


def test_dst_like_change_recalibrates_from_plus_three_to_plus_two():
    clock = ServerClockOffset()
    clock.to_utc(BASE + timedelta(hours=3), BASE)
    later = BASE + timedelta(days=60)
    corrected = clock.to_utc(later + timedelta(hours=2) - timedelta(seconds=1), later)
    assert corrected == later - timedelta(seconds=1)
    assert clock.current_offset() == timedelta(hours=2)


def test_arbitrary_large_staleness_is_preserved_not_misread_as_timezone_change():
    clock = ServerClockOffset()
    clock.to_utc(BASE + timedelta(hours=3), BASE)
    later = BASE + timedelta(minutes=17)
    # Feed is still reporting the original tick. This should remain an old
    # corrected timestamp so freshness rejects it, not mutate the timezone.
    corrected = clock.to_utc(BASE + timedelta(hours=3), later)
    assert corrected == BASE
    assert clock.current_offset() == timedelta(hours=3)


def test_naive_raw_timestamp_rejected():
    clock = ServerClockOffset()
    with pytest.raises(ServerClockCalibrationError, match="timezone-aware"):
        clock.to_utc(BASE.replace(tzinfo=None), BASE)


def test_naive_bridge_now_rejected():
    clock = ServerClockOffset()
    with pytest.raises(ServerClockCalibrationError, match="timezone-aware"):
        clock.to_utc(BASE, BASE.replace(tzinfo=None))


def test_real_backend_tick_path_uses_calibrated_offset():
    from unittest.mock import MagicMock

    from mt5_bridge.backend import RealMT5Backend

    mt5 = MagicMock()
    tick = MagicMock()
    tick.time = int((BASE + timedelta(hours=3)).timestamp())
    tick.bid = 1.16234
    tick.ask = 1.16251
    mt5.symbol_info_tick.return_value = tick
    info = MagicMock()
    info.digits = 5
    mt5.symbol_info.return_value = info

    backend = RealMT5Backend.__new__(RealMT5Backend)
    backend._mt5 = mt5
    backend._connected = True
    backend._server_clock = ServerClockOffset()

    # Pin the bridge-side 'now' by pre-calibrating the shared clock. The
    # backend then consumes the same +3h raw-tick convention.
    backend._server_clock.to_utc(BASE + timedelta(hours=3), BASE)
    result = backend.symbol_info_tick("EURUSD")
    assert result is not None
    assert result.time_utc == BASE
    assert backend.server_clock_offset_seconds() == 10800.0


def test_historical_bars_are_not_shifted_by_live_tick_offset():
    """Live HFM skew must not silently rewrite documented UTC bar times."""
    from unittest.mock import MagicMock

    import numpy as np

    from mt5_bridge.backend import RealMT5Backend

    mt5 = MagicMock()
    mt5.TIMEFRAME_H1 = 16385
    dtype = np.dtype([
        ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
        ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8"),
    ])
    rates = np.zeros(1, dtype=dtype)
    rates[0]["time"] = int(BASE.timestamp())
    rates[0]["open"] = 1.16
    rates[0]["high"] = 1.17
    rates[0]["low"] = 1.15
    rates[0]["close"] = 1.165
    rates[0]["tick_volume"] = 100
    mt5.copy_rates_range.return_value = rates
    info = MagicMock()
    info.digits = 5
    mt5.symbol_info.return_value = info

    backend = RealMT5Backend.__new__(RealMT5Backend)
    backend._mt5 = mt5
    backend._connected = True
    backend._server_clock = ServerClockOffset()
    backend._server_clock.to_utc(BASE + timedelta(hours=3), BASE)

    bars = backend.copy_rates_range("EURUSD", "H1", BASE - timedelta(hours=1), BASE + timedelta(hours=1))
    assert bars[0].time_utc == BASE
