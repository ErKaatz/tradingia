"""Integrity guard for the existing, already-frozen Phase 3 forward
preregistration.

Phase 3B (regime research) must never modify Phase 3's four preregistered
hypotheses, its forward start date, or its guardrail code. This module
fingerprints every file that defines that contract and lets any Phase 3B
command verify, before and after running, that nothing changed. It reports
a violation as a hard failure (raises), never as a warning.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Every file that defines Phase 3's frozen contract. If Phase 3 is ever
# legitimately extended, this list must be updated deliberately as part of
# that change -- not silently by a Phase 3B command touching one of these
# paths.
PHASE3_GUARDED_FILES = [
    Path("PHASE3_FORWARD.md"),
    Path("src/forward/runner.py"),
    Path("src/strategies/breakout_forward.py"),
    Path("configs/forward_validation.yaml"),
    Path("tests/test_forward_phase3.py"),
]

# The exact frozen values Phase 3 committed to. Checked independently of
# the file hashes above so a violation is diagnosed precisely (e.g. "the
# frozen start date changed" rather than just "some byte in some file
# changed").
EXPECTED_FROZEN_START = "2026-09-03 00:00:00+00:00"
EXPECTED_FROZEN_VARIANTS = (
    "baseline_168_60",
    "baseline_168_72",
    "confirmed24_168_60",
    "adaptive_vol_168_60",
)


def _sha256_of_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_phase3_fingerprint() -> dict[str, Any]:
    """Snapshot of everything Phase 3B must never change: per-file content
    hashes plus the semantic frozen values read directly from the forward
    runner's source, so a rewrite that preserves behavior but reformats the
    file is still caught (file hash differs) and a rewrite that changes the
    frozen values themselves is caught with a specific, named diagnosis.
    """
    file_hashes = {str(p): _sha256_of_file(p) for p in PHASE3_GUARDED_FILES}

    frozen_start = None
    frozen_variants: tuple[str, ...] = ()
    runner_path = Path("src/forward/runner.py")
    if runner_path.exists():
        namespace: dict[str, Any] = {}
        exec(compile(runner_path.read_text(), str(runner_path), "exec"), namespace)  # noqa: S102
        frozen_start = str(namespace["FROZEN_START"])
        frozen_variants = tuple(name for name, _ in namespace["FROZEN_VARIANTS"])

    return {
        "file_sha256": file_hashes,
        "frozen_start": frozen_start,
        "frozen_variants": frozen_variants,
    }


def save_phase3_fingerprint(path: Path = Path("research/regime_study/PHASE3_FINGERPRINT.json")) -> Path:
    fingerprint = compute_phase3_fingerprint()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fingerprint, indent=2, sort_keys=True) + "\n")
    return path


class Phase3IntegrityError(RuntimeError):
    """Raised when Phase 3's frozen preregistration was modified."""


def assert_phase3_intact(baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify Phase 3's guarded files and frozen values are unchanged
    relative to `baseline` (or, if omitted, verify the frozen semantic
    values match the hardcoded expectations in this module -- a "cold"
    check useful before any baseline has been captured yet).

    Raises Phase3IntegrityError with a specific diagnosis on any mismatch.
    Returns the freshly computed fingerprint on success, so callers can use
    it as the next baseline.
    """
    current = compute_phase3_fingerprint()

    if current["frozen_start"] != EXPECTED_FROZEN_START:
        raise Phase3IntegrityError(
            f"Phase 3 forward start changed: expected {EXPECTED_FROZEN_START!r}, "
            f"found {current['frozen_start']!r}"
        )
    if current["frozen_variants"] != EXPECTED_FROZEN_VARIANTS:
        raise Phase3IntegrityError(
            f"Phase 3 frozen variants changed: expected {EXPECTED_FROZEN_VARIANTS!r}, "
            f"found {current['frozen_variants']!r}"
        )
    for path_str in [str(p) for p in PHASE3_GUARDED_FILES]:
        if current["file_sha256"].get(path_str) is None:
            raise Phase3IntegrityError(f"Phase 3 guarded file is missing: {path_str}")

    if baseline is not None:
        for path_str, expected_hash in baseline.get("file_sha256", {}).items():
            actual_hash = current["file_sha256"].get(path_str)
            if actual_hash != expected_hash:
                raise Phase3IntegrityError(
                    f"Phase 3 guarded file changed since baseline: {path_str} "
                    f"(expected sha256={expected_hash}, found sha256={actual_hash})"
                )
        if baseline.get("frozen_start") != current["frozen_start"]:
            raise Phase3IntegrityError(
                f"Phase 3 forward start changed since baseline: "
                f"{baseline.get('frozen_start')!r} -> {current['frozen_start']!r}"
            )
        if tuple(baseline.get("frozen_variants", ())) != current["frozen_variants"]:
            raise Phase3IntegrityError(
                f"Phase 3 frozen variants changed since baseline: "
                f"{baseline.get('frozen_variants')!r} -> {current['frozen_variants']!r}"
            )

    return current
