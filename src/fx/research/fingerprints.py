"""Exact-byte verification for self-fingerprinted preregistration Markdown."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


PLACEHOLDER = b"TO_BE_FILLED_BY_FREEZE_TOOL"
_SELF_FIELD = re.compile(rb"(?m)^Preregistration fingerprint: `([0-9a-f]{64})`\.$")


def canonicalize_self_fingerprinted_document(document: bytes) -> bytes:
    """Replace exactly one registered self-fingerprint value, byte-for-byte."""
    matches = list(_SELF_FIELD.finditer(document))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one valid self-fingerprint field, found {len(matches)}")
    match = matches[0]
    start, end = match.span(1)
    return document[:start] + PLACEHOLDER + document[end:]


def canonical_document_sha256(path: Path) -> str:
    return hashlib.sha256(canonicalize_self_fingerprinted_document(path.read_bytes())).hexdigest()


def verify_canonical_document_fingerprint(path: Path, expected_sha256: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected fingerprint must be lowercase SHA-256 hex")
    actual = canonical_document_sha256(path)
    if actual != expected_sha256:
        raise ValueError(f"canonical preregistration fingerprint mismatch: expected {expected_sha256}, got {actual}")
    return True
