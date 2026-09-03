"""Bearer-token authentication for the bridge (FX Phase 0, Step 3).

Constant-time comparison via `hmac.compare_digest` so a timing attack
can't be used to guess the token one byte at a time. The token is never
echoed back in any response or exception message raised from here.
"""

from __future__ import annotations

import hmac


class AuthResult:
    __slots__ = ("authenticated", "failure_reason")

    def __init__(self, authenticated: bool, failure_reason: str | None = None) -> None:
        self.authenticated = authenticated
        self.failure_reason = failure_reason


def check_bearer_token(authorization_header: str | None, expected_token: str) -> AuthResult:
    if not authorization_header:
        return AuthResult(authenticated=False, failure_reason="missing_authorization_header")
    if not authorization_header.startswith("Bearer "):
        return AuthResult(authenticated=False, failure_reason="malformed_authorization_header")
    provided = authorization_header[len("Bearer ") :]
    if hmac.compare_digest(provided, expected_token):
        return AuthResult(authenticated=True)
    return AuthResult(authenticated=False, failure_reason="invalid_token")
