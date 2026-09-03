"""Bridge configuration from environment variables (FX Phase 0, Step 3).

No secrets are ever read from a tracked file. `BridgeConfig.__repr__` is
overridden so the token cannot leak through a log line or an assertion
failure that prints the config object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_MAGIC = 20260903  # Phase 0 demo magic; see mt5_bridge/identity.py
DEFAULT_MAX_QUOTE_AGE_SECONDS = 5.0
# Deliberately tiny: this tolerates ordinary clock resolution/NTP drift and
# the sub-second gap between MT5 timestamping a tick and this process
# reading it -- NOT a multi-hour "broker server time labeled as UTC"
# conversion bug (see FX Phase 0's "quote has a timestamp in the future"
# investigation, mt5_bridge/quote_freshness.py). If a real deployment
# needs more than ~1s of tolerance, that is a sign of a clock/timezone bug
# to fix at the source, not a threshold to raise blindly.
DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS = 1.0
DEFAULT_DEVIATION_POINTS = 20
DEFAULT_DB_PATH = "mt5_bridge.sqlite3"

# Bump when mt5_bridge's write-path behavior changes in a way worth being
# able to see at a glance in `/v1/health` -- this exists specifically
# because a stale VM deployment once looked like a code bug (see
# FX_PHASE0_STATUS.md's Step 3.1 follow-up).
BRIDGE_BUILD = "step4-audit-hardened-2026-09-03"


class BridgeConfigError(Exception):
    pass


@dataclass(frozen=True)
class BridgeConfig:
    host: str
    port: int
    api_token: str
    terminal_path: str | None = None
    login: int | None = None
    password: str | None = None
    server: str | None = None
    magic: int = DEFAULT_MAGIC
    max_quote_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS
    max_quote_future_skew_seconds: float = DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS
    deviation_points: int = DEFAULT_DEVIATION_POINTS
    db_path: str = DEFAULT_DB_PATH

    def __repr__(self) -> str:
        return (
            f"BridgeConfig(host={self.host!r}, port={self.port!r}, api_token=***, "
            f"terminal_path={self.terminal_path!r}, login={self.login!r}, "
            f"password={'***' if self.password else None}, server={self.server!r}, "
            f"magic={self.magic!r}, max_quote_age_seconds={self.max_quote_age_seconds!r}, "
            f"max_quote_future_skew_seconds={self.max_quote_future_skew_seconds!r}, "
            f"deviation_points={self.deviation_points!r}, db_path={self.db_path!r})"
        )

    @staticmethod
    def from_env(environ: dict[str, str] | None = None) -> "BridgeConfig":
        env = environ if environ is not None else os.environ
        token = env.get("MT5_BRIDGE_TOKEN")
        if not token:
            raise BridgeConfigError("MT5_BRIDGE_TOKEN environment variable is required and must be non-empty")

        host = env.get("MT5_BRIDGE_HOST", DEFAULT_HOST)
        if host == "0.0.0.0":
            raise BridgeConfigError(
                "MT5_BRIDGE_HOST=0.0.0.0 is refused; bind explicitly to 127.0.0.1 "
                "or the VM's LAN IP (see mt5_bridge/README.md)"
            )

        port_raw = env.get("MT5_BRIDGE_PORT", str(DEFAULT_PORT))
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise BridgeConfigError(f"MT5_BRIDGE_PORT must be an integer, got {port_raw!r}") from exc
        if not (1 <= port <= 65535):
            raise BridgeConfigError(f"MT5_BRIDGE_PORT must be between 1 and 65535, got {port}")

        login_raw = env.get("MT5_LOGIN")
        login = None
        if login_raw:
            try:
                login = int(login_raw)
            except ValueError as exc:
                raise BridgeConfigError(f"MT5_LOGIN must be an integer, got {login_raw!r}") from exc

        magic_raw = env.get("MT5_TRADINGIA_MAGIC", str(DEFAULT_MAGIC))
        try:
            magic = int(magic_raw)
        except ValueError as exc:
            raise BridgeConfigError(f"MT5_TRADINGIA_MAGIC must be an integer, got {magic_raw!r}") from exc
        if magic == 0:
            raise BridgeConfigError("MT5_TRADINGIA_MAGIC must not be 0 (0 typically means 'no magic'/manual order)")

        quote_age_raw = env.get("MT5_MAX_QUOTE_AGE_SECONDS", str(DEFAULT_MAX_QUOTE_AGE_SECONDS))
        try:
            max_quote_age_seconds = float(quote_age_raw)
        except ValueError as exc:
            raise BridgeConfigError(f"MT5_MAX_QUOTE_AGE_SECONDS must be a number, got {quote_age_raw!r}") from exc
        if max_quote_age_seconds <= 0:
            raise BridgeConfigError("MT5_MAX_QUOTE_AGE_SECONDS must be positive")

        future_skew_raw = env.get("MT5_MAX_QUOTE_FUTURE_SKEW_SECONDS", str(DEFAULT_MAX_QUOTE_FUTURE_SKEW_SECONDS))
        try:
            max_quote_future_skew_seconds = float(future_skew_raw)
        except ValueError as exc:
            raise BridgeConfigError(
                f"MT5_MAX_QUOTE_FUTURE_SKEW_SECONDS must be a number, got {future_skew_raw!r}"
            ) from exc
        if max_quote_future_skew_seconds < 0:
            raise BridgeConfigError("MT5_MAX_QUOTE_FUTURE_SKEW_SECONDS must not be negative")
        if max_quote_future_skew_seconds > 60:
            raise BridgeConfigError(
                "MT5_MAX_QUOTE_FUTURE_SKEW_SECONDS must be <= 60 -- a larger value would mask a real "
                "clock/timezone conversion bug rather than tolerate ordinary clock skew; fix the "
                "underlying clock/timezone issue instead of raising this further"
            )

        deviation_raw = env.get("MT5_DEVIATION_POINTS", str(DEFAULT_DEVIATION_POINTS))
        try:
            deviation_points = int(deviation_raw)
        except ValueError as exc:
            raise BridgeConfigError(f"MT5_DEVIATION_POINTS must be an integer, got {deviation_raw!r}") from exc
        if deviation_points < 0:
            raise BridgeConfigError("MT5_DEVIATION_POINTS must be >= 0")

        return BridgeConfig(
            host=host,
            port=port,
            api_token=token,
            terminal_path=env.get("MT5_TERMINAL_PATH"),
            login=login,
            password=env.get("MT5_PASSWORD"),
            server=env.get("MT5_SERVER"),
            magic=magic,
            max_quote_age_seconds=max_quote_age_seconds,
            max_quote_future_skew_seconds=max_quote_future_skew_seconds,
            deviation_points=deviation_points,
            db_path=env.get("MT5_BRIDGE_DB_PATH", DEFAULT_DB_PATH),
        )
