"""Tests for the Phase 3 integrity guard used by Phase 3B regime research."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.research.phase3_guard import (
    EXPECTED_FROZEN_START,
    EXPECTED_FROZEN_VARIANTS,
    Phase3IntegrityError,
    assert_phase3_intact,
    compute_phase3_fingerprint,
)


@pytest.mark.skipif(
    not Path("src/forward/runner.py").exists(),
    reason="Phase 3 forward runner not present in this checkout",
)
def test_current_repo_phase3_is_intact():
    """Sanity check against the real repo: Phase 3 as it exists right now
    must pass its own guard.
    """
    fingerprint = assert_phase3_intact()
    assert fingerprint["frozen_start"] == EXPECTED_FROZEN_START
    assert fingerprint["frozen_variants"] == EXPECTED_FROZEN_VARIANTS


@pytest.mark.skipif(
    not Path("src/forward/runner.py").exists(),
    reason="Phase 3 forward runner not present in this checkout",
)
def test_baseline_then_recheck_with_no_changes_passes():
    baseline = compute_phase3_fingerprint()
    # Re-verifying against its own baseline immediately after must not raise.
    assert_phase3_intact(baseline)


def test_detects_changed_frozen_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "forward").mkdir(parents=True)
    (tmp_path / "src" / "strategies").mkdir(parents=True)
    (tmp_path / "configs").mkdir(parents=True)

    (tmp_path / "PHASE3_FORWARD.md").write_text("frozen doc\n")
    (tmp_path / "src" / "forward" / "runner.py").write_text(
        "import pandas as pd\n"
        "FROZEN_START = pd.Timestamp('2027-01-01T00:00:00Z')\n"  # tampered date
        "FROZEN_VARIANTS = [('baseline_168_60', None), ('baseline_168_72', None), "
        "('confirmed24_168_60', None), ('adaptive_vol_168_60', None)]\n"
    )
    (tmp_path / "src" / "strategies" / "breakout_forward.py").write_text("# stub\n")
    (tmp_path / "configs" / "forward_validation.yaml").write_text("forward_start: 2027-01-01\n")

    with pytest.raises(Phase3IntegrityError, match="forward start changed"):
        assert_phase3_intact()


def test_detects_changed_frozen_variants(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "forward").mkdir(parents=True)
    (tmp_path / "src" / "strategies").mkdir(parents=True)
    (tmp_path / "configs").mkdir(parents=True)

    (tmp_path / "PHASE3_FORWARD.md").write_text("frozen doc\n")
    (tmp_path / "src" / "forward" / "runner.py").write_text(
        "import pandas as pd\n"
        "FROZEN_START = pd.Timestamp('2026-09-03T00:00:00Z')\n"
        "FROZEN_VARIANTS = [('baseline_168_60', None), ('baseline_168_72', None), "
        "('confirmed24_168_60', None), ('a_new_sneaky_variant', None)]\n"  # tampered
    )
    (tmp_path / "src" / "strategies" / "breakout_forward.py").write_text("# stub\n")
    (tmp_path / "configs" / "forward_validation.yaml").write_text("forward_start: 2026-09-03\n")

    with pytest.raises(Phase3IntegrityError, match="frozen variants changed"):
        assert_phase3_intact()


def test_detects_missing_guarded_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "forward").mkdir(parents=True)
    (tmp_path / "src" / "strategies").mkdir(parents=True)
    (tmp_path / "configs").mkdir(parents=True)
    (tmp_path / "src" / "forward" / "runner.py").write_text(
        "import pandas as pd\n"
        "FROZEN_START = pd.Timestamp('2026-09-03T00:00:00Z')\n"
        "FROZEN_VARIANTS = [('baseline_168_60', None), ('baseline_168_72', None), "
        "('confirmed24_168_60', None), ('adaptive_vol_168_60', None)]\n"
    )
    (tmp_path / "src" / "strategies" / "breakout_forward.py").write_text("# stub\n")
    (tmp_path / "configs" / "forward_validation.yaml").write_text("forward_start: 2026-09-03\n")
    # PHASE3_FORWARD.md deliberately not created -> missing guarded file.

    with pytest.raises(Phase3IntegrityError, match="missing"):
        assert_phase3_intact()


def test_detects_drift_from_explicit_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "forward").mkdir(parents=True)
    (tmp_path / "src" / "strategies").mkdir(parents=True)
    (tmp_path / "configs").mkdir(parents=True)

    (tmp_path / "PHASE3_FORWARD.md").write_text("original content\n")
    (tmp_path / "src" / "forward" / "runner.py").write_text(
        "import pandas as pd\n"
        "FROZEN_START = pd.Timestamp('2026-09-03T00:00:00Z')\n"
        "FROZEN_VARIANTS = [('baseline_168_60', None), ('baseline_168_72', None), "
        "('confirmed24_168_60', None), ('adaptive_vol_168_60', None)]\n"
    )
    (tmp_path / "src" / "strategies" / "breakout_forward.py").write_text("# stub\n")
    (tmp_path / "configs" / "forward_validation.yaml").write_text("forward_start: 2026-09-03\n")

    baseline = compute_phase3_fingerprint()

    # Now mutate a guarded file's content (same frozen values, different
    # bytes -- e.g. a stray edit) and confirm the byte-level check catches it
    # even though the semantic frozen values still parse as unchanged.
    (tmp_path / "PHASE3_FORWARD.md").write_text("original content, but someone added this line\n")

    with pytest.raises(Phase3IntegrityError, match="changed since baseline"):
        assert_phase3_intact(baseline)
