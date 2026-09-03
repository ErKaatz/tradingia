"""Structured error responses for the bridge (FX Phase 0, Step 3).

Every error path in the bridge raises `BridgeError` (or a subclass), and
a single FastAPI exception handler (wired in `app.py`) converts it into
`{"error": {"code": ..., "message": ...}}` with the matching HTTP status.
No traceback, filesystem path, or secret ever reaches the response body
-- an unexpected exception is caught by a catch-all handler that returns
a generic 500 with no detail from the original exception.
"""

from __future__ import annotations


class BridgeError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequestError(BridgeError):
    status_code = 400
    code = "bad_request"


class NotFoundError(BridgeError):
    status_code = 404
    code = "not_found"


class BackendUnavailableError(BridgeError):
    """MT5/terminal is unreachable or returned an unexpected failure for
    a call that should otherwise have worked. Mapped to 502 -- the
    bridge itself is fine, but its upstream (the terminal) is not.
    """

    status_code = 502
    code = "backend_unavailable"


class ConflictError(BridgeError):
    """Same `client_order_id` reused with a semantically different
    request (Step 4 idempotency). Never silently resolved either way.
    """

    status_code = 409
    code = "conflict"


class TradingWriteError(BridgeError):
    """A write was refused for a safety reason -- kill switch active,
    account not confirmed DEMO, reconciliation not OK, too many
    positions, symbol not tradable, stale quote, order_check rejected,
    position not found, invalid volume. Each `mt5_bridge.trading`
    exception carries its own `code`/HTTP status (see
    `app.py::_TRADING_ERROR_STATUS`), passed through here rather than
    hardcoded to one status -- "your request was fine but policy said
    no" needs a distinguishable code per reason, not one generic 403.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def to_error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
