"""Central sanitizer for anything that might leave the bridge process:
error messages, exception text, journal entries, API response bodies
(FX Phase 0, Step 4).

This is the ONE place that decides what a raw string is allowed to look
like before it is logged, persisted to the journal DB, or returned in an
HTTP response. Every other module that needs to expose a message coming
from MT5 or from an internal exception should route it through
`sanitize_message` rather than re-inventing its own redaction.

What this removes:
- Anything that looks like `Authorization: Bearer <token>` or a bare
  long opaque token.
- Anything that looks like a password field/value pair.
- Windows/Unix filesystem paths beyond the last two path segments (a
  path can be useful for debugging which file failed without exposing a
  full local username/home-directory layout).

What this does NOT attempt: this is a best-effort filter for operational
strings (MT5 error text, Python exception messages), not a guarantee
against a determined secret leak in a message that was never designed to
carry one. The actual token/password themselves are never passed
through this function to begin with (see `mt5_bridge/config.py`'s
`BridgeConfig.__repr__`, `auth.py`) -- this is a second, defensive layer,
not the only one.
"""

from __future__ import annotations

import re

_AUTH_HEADER_RE = re.compile(r"(?i)authorization\s*[:=]\s*\S+(?:\s+\S+)?")
_BEARER_RE = re.compile(r"(?i)bearer\s+\S+")
_PASSWORD_KV_RE = re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+")
_TOKEN_KV_RE = re.compile(r"(?i)(api[_-]?key|token)\s*[:=]\s*\S+")
# Windows path: C:\Users\name\...  or  \\server\share\...
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"']+|\\\\[^\s\"']+")
# Unix absolute path with at least 2 segments (avoid matching e.g. "a/b" in prose)
_UNIX_PATH_RE = re.compile(r"/(?:[\w.\-]+/){2,}[\w.\-]+")

_REDACTED = "[REDACTED]"
_PATH_REDACTED = "[PATH]"


def sanitize_message(text: str | None) -> str | None:
    """Returns a copy of `text` with credential-shaped substrings and
    filesystem paths replaced by placeholders. `None` stays `None`.
    """

    if text is None:
        return None
    result = _AUTH_HEADER_RE.sub(_REDACTED, text)
    result = _BEARER_RE.sub(_REDACTED, result)
    result = _PASSWORD_KV_RE.sub(_REDACTED, result)
    result = _TOKEN_KV_RE.sub(_REDACTED, result)
    result = _WINDOWS_PATH_RE.sub(_PATH_REDACTED, result)
    result = _UNIX_PATH_RE.sub(_PATH_REDACTED, result)
    return result


def sanitize_exception(exc: BaseException) -> str:
    """Sanitized, single-line string safe to log/journal/return for an
    unexpected exception. Deliberately does NOT include a traceback --
    only the exception's own message text, itself sanitized.
    """

    return sanitize_message(str(exc)) or f"{type(exc).__name__} (no message)"
