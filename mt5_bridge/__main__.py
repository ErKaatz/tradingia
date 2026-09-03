"""Entrypoint: `python -m mt5_bridge` starts the bridge server (read-only
+ Step 4 DEMO-only writes).

Windows-only in practice (imports `RealMT5Backend`, which imports the
real `MetaTrader5` package). Reads all configuration from environment
variables via `BridgeConfig.from_env()` -- see mt5_bridge/README.md.

Runs reconciliation once at startup, BEFORE the server starts accepting
requests -- see `mt5_bridge/reconciliation.py`. If a prior run left any
idempotency row stuck in RECEIVED/SUBMITTED (e.g. the bridge crashed
between order_send and recording FILLED), reconciliation reports
MISMATCH and `authorize_open`/`mt5_bridge.trading.place_demo_order`
refuse new entries until `POST /v1/reconciliation/run` resolves it --
the server still starts (reads and closes remain available), it simply
starts with entries already blocked rather than blind.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from mt5_bridge.app import create_app
from mt5_bridge.backend import RealMT5Backend
from mt5_bridge.config import BridgeConfig, BridgeConfigError
from mt5_bridge.reconciliation import run_reconciliation
from mt5_bridge.store import BridgeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mt5_bridge")


def main() -> int:
    try:
        config = BridgeConfig.from_env()
    except BridgeConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    backend = RealMT5Backend(terminal_path=config.terminal_path)
    if not backend.connect():
        print("ERROR: MetaTrader5.initialize() failed. Run `python -m mt5_bridge.smoke` first.", file=sys.stderr)
        return 1

    store = BridgeStore(config.db_path)
    startup_report = run_reconciliation(store, backend)
    logger.info("startup reconciliation: state=%s details=%s", startup_report.state.value, startup_report.details)
    if startup_report.state.value != "ok":
        logger.warning(
            "reconciliation is NOT ok at startup (state=%s) -- new demo orders will be refused "
            "until POST /v1/reconciliation/run resolves it; reads and closes remain available.",
            startup_report.state.value,
        )

    logger.info("MT5 backend connected; starting bridge on %s:%s (magic=%s)", config.host, config.port, config.magic)
    app = create_app(backend, config, store=store)
    try:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info")
    finally:
        backend.shutdown()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
