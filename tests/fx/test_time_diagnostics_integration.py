"""Real-bridge empirical time-diagnostics integration tests (Phase 5A).

These tests require a REACHABLE real MT5 bridge (the Windows VM running
`mt5_bridge`, connected to a real MT5 terminal/account) -- they are
read-only (history/health/symbol_metadata/account only, never an order)
but they do make real network calls and depend on external
infrastructure this repo's default test run must not require.

Marked `requires_real_mt5` (see pytest.ini) AND self-skipping via
`pytest.skip` when the bridge is not configured/reachable, so `pytest -q`
(no marker filter) still passes cleanly in any environment without a
Windows VM -- exactly like every other test in this suite.

## How to run this for real

    export MT5_REMOTE_URL=http://<windows-vm-ip>:<port>
    export MT5_REMOTE_TOKEN=<bridge token>
    pytest -q tests/fx/test_time_diagnostics_integration.py -m requires_real_mt5 -s

Or via the `tia` wrapper's own config (~/.config/tradingia/mt5.env):

    tia python -m pytest -q tests/fx/test_time_diagnostics_integration.py -m requires_real_mt5 -s

No order is ever placed by these tests. See PHASE5A_STATUS.md's
"Empirical Findings" section for the current status (as of this commit:
PENDING EMPIRICAL VALIDATION -- the bridge was not reachable from this
environment) and exactly which of these commands to re-run once it is.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.requires_real_mt5


def _real_client():
    """Build a real MT5RemoteExecutionClient from environment variables,
    or skip the test if not configured. Import is local so this module
    can be collected even where `requests` behaves oddly in a sandboxed
    environment."""
    bridge_url = os.environ.get("MT5_REMOTE_URL")
    token = os.environ.get("MT5_REMOTE_TOKEN")
    if not bridge_url or not token:
        pytest.skip("MT5_REMOTE_URL/MT5_REMOTE_TOKEN not set -- PENDING EMPIRICAL VALIDATION, see PHASE5A_STATUS.md")

    from src.execution.mt5_remote import ExecutionClientError, MT5RemoteExecutionClient, RemoteConfig

    config = RemoteConfig(bridge_url=bridge_url, api_token=token, timeout_seconds=10.0)
    client = MT5RemoteExecutionClient(config)
    try:
        client.health()
    except ExecutionClientError as exc:
        pytest.skip(f"bridge configured but unreachable -- PENDING EMPIRICAL VALIDATION: {exc}")
    return client


def test_real_eurusd_h1_weekly_window_time_diagnostics():
    """Fetch one week of real EURUSD H1 bars spanning a weekend and
    report weekend-gap findings. Read-only. No performance/PnL claim."""
    from src.execution.base import ExecutionTimeframe
    from src.fx.data.time_diagnostics import run_time_diagnostics

    client = _real_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=10)
    report = run_time_diagnostics(client, "EURUSD", start, end, timeframe=ExecutionTimeframe.H1)

    assert report.bar_count >= 0  # empirical: report whatever the bridge actually returns
    print(f"\nEURUSD H1 diagnostics: {report}")


def test_real_eurusd_h4_alignment_over_two_weeks():
    """Fetch two weeks of real EURUSD H4 bars and report the set of
    UTC hour-of-day values seen, to check whether the H4 grid is stable."""
    from src.execution.base import ExecutionTimeframe
    from src.fx.data.time_diagnostics import run_time_diagnostics

    client = _real_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    report = run_time_diagnostics(client, "EURUSD", start, end, timeframe=ExecutionTimeframe.H4)

    print(f"\nEURUSD H4 alignment: {report.h4_alignment}")
    assert report.h4_alignment is not None or report.bar_count == 0


def test_real_eurusd_symbol_metadata_capture():
    """Read-only symbol metadata capture for EURUSD from the real bridge."""
    client = _real_client()
    metadata = client.symbol_metadata("EURUSD")
    print(f"\nEURUSD symbol metadata: {metadata}")
    assert metadata.symbol == "EURUSD"


def test_real_small_eurusd_h1_dataset_fetch_and_fingerprint():
    """End-to-end read-only fetch: real bridge -> normalize -> fingerprint.
    Does not persist anything to disk (this repo's data policy excludes
    committing datasets; this test only proves the pipeline works)."""
    from src.execution.base import ExecutionTimeframe
    from src.fx.data.mt5_provider import build_metadata_for_fetch, fetch_history

    client = _real_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=3)
    fetch = fetch_history(client, "EURUSD", ExecutionTimeframe.H1, start, end)
    metadata = build_metadata_for_fetch(fetch)

    print(f"\nFetched {metadata.bar_count} EURUSD H1 bars, fingerprint={metadata.dataset_sha256}")
    assert metadata.resolved_symbol == "EURUSD"
