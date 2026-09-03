"""Tests for the `tia` shell wrapper, `scripts/install_cli.sh`, and
`scripts/setup_mt5_remote.sh` (ergonomics layer around `python -m src.cli`,
FX Phase 0). These tests never talk to a real bridge -- they only verify
argument translation, repo-root/venv resolution, config-file loading and
its security properties, and installer behavior, using subprocess + a
tiny fake `python` stand-in so no real MT5 client code runs.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TIA_SCRIPT = REPO_ROOT / "scripts" / "tia"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install_cli.sh"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_mt5_remote.sh"


def _make_fake_repo(tmp_path: Path) -> Path:
    """Builds a throwaway repo skeleton: scripts/tia (a copy of the real
    wrapper) + .venv/bin/python (a fake interpreter that just echoes its
    argv so we can assert on translation/forwarding without importing any
    real TradingIA/MT5 code).
    """

    repo = tmp_path / "fakerepo"
    (repo / "src").mkdir(parents=True)
    (repo / "scripts").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)

    wrapper_text = TIA_SCRIPT.read_text()
    fake_tia = repo / "scripts" / "tia"
    fake_tia.write_text(wrapper_text)
    fake_tia.chmod(0o755)

    fake_python = repo / ".venv" / "bin" / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"ARGS:$*\"\n"
        "for v in MT5_REMOTE_URL MT5_REMOTE_TOKEN; do\n"
        '  echo "ENV:$v=${!v:-<unset>}"\n'
        "done\n"
        'exit "${FAKE_EXIT_CODE:-0}"\n'
    )
    fake_python.chmod(0o755)
    return repo


def _run_tia(repo: Path, args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env.pop("MT5_REMOTE_URL", None)
    full_env.pop("MT5_REMOTE_TOKEN", None)
    if env:
        full_env.update(env)
    return subprocess.run(
        [str(repo / "scripts" / "tia"), *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_repo_root_resolved_from_script_not_cwd(tmp_path):
    repo = _make_fake_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run_tia(repo, ["status"], cwd=elsewhere)
    assert result.returncode == 0
    assert "ARGS:-m src.cli status" in result.stdout


def test_runs_from_arbitrary_directory(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    result = _run_tia(repo, ["mt5", "positions"], cwd=home)
    assert result.returncode == 0
    assert "ARGS:-m src.cli mt5-remote positions" in result.stdout


def test_mt5_alias_translated_to_mt5_remote(tmp_path):
    repo = _make_fake_repo(tmp_path)
    result = _run_tia(repo, ["mt5", "preflight", "EURUSD"], cwd=tmp_path)
    assert "ARGS:-m src.cli mt5-remote preflight EURUSD" in result.stdout


def test_non_mt5_command_passes_through_unchanged(tmp_path):
    repo = _make_fake_repo(tmp_path)
    result = _run_tia(repo, ["backtest", "configs/sma_cross.yaml"], cwd=tmp_path)
    assert "ARGS:-m src.cli backtest configs/sma_cross.yaml" in result.stdout


def test_arguments_with_flags_preserved(tmp_path):
    repo = _make_fake_repo(tmp_path)
    result = _run_tia(
        repo,
        ["mt5", "demo-open", "EURUSD", "buy", "--confirm-demo-order"],
        cwd=tmp_path,
    )
    assert "ARGS:-m src.cli mt5-remote demo-open EURUSD buy --confirm-demo-order" in result.stdout


def test_missing_repo_gives_human_error(tmp_path):
    # Simulate an unmounted volume: the wrapper script exists but its
    # parent repo structure (src/) does not.
    orphan_dir = tmp_path / "orphan" / "scripts"
    orphan_dir.mkdir(parents=True)
    wrapper_text = TIA_SCRIPT.read_text()
    orphan_script = orphan_dir / "tia"
    orphan_script.write_text(wrapper_text)
    orphan_script.chmod(0o755)

    result = subprocess.run(
        [str(orphan_script), "status"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "repository is unavailable" in result.stderr
    assert "mounted" in result.stderr


def test_missing_venv_gives_human_error(tmp_path):
    repo = _make_fake_repo(tmp_path)
    (repo / ".venv" / "bin" / "python").unlink()
    result = _run_tia(repo, ["status"], cwd=tmp_path)
    assert result.returncode == 1
    assert "virtual environment not found" in result.stderr


def test_env_file_is_loaded(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text("MT5_REMOTE_URL=http://10.0.0.5:8765\nMT5_REMOTE_TOKEN=filetoken\n")
    env_file.chmod(0o600)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert result.returncode == 0
    assert "ENV:MT5_REMOTE_URL=http://10.0.0.5:8765" in result.stdout
    assert "ENV:MT5_REMOTE_TOKEN=filetoken" in result.stdout


def test_existing_process_env_takes_precedence_over_file(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text("MT5_REMOTE_URL=http://from-file:8765\nMT5_REMOTE_TOKEN=filetoken\n")
    env_file.chmod(0o600)

    result = _run_tia(
        repo,
        ["status"],
        cwd=tmp_path,
        env={"HOME": str(home), "MT5_REMOTE_URL": "http://from-explicit-env:9999"},
    )
    assert "ENV:MT5_REMOTE_URL=http://from-explicit-env:9999" in result.stdout


def test_token_never_appears_in_stderr_on_error_path(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text("MT5_REMOTE_URL=http://10.0.0.5:8765\nMT5_REMOTE_TOKEN=super-secret-token\n")
    env_file.chmod(0o600)
    (repo / ".venv" / "bin" / "python").write_text("#!/usr/bin/env bash\nexit 1\n")
    (repo / ".venv" / "bin" / "python").chmod(0o755)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert "super-secret-token" not in result.stdout
    assert "super-secret-token" not in result.stderr


def test_world_readable_env_file_rejected(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text("MT5_REMOTE_URL=http://10.0.0.5:8765\nMT5_REMOTE_TOKEN=secret\n")
    env_file.chmod(0o644)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert result.returncode == 1
    assert "too open" in result.stderr
    assert "secret" not in result.stdout
    assert "secret" not in result.stderr


def test_permissions_600_accepted(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text("MT5_REMOTE_URL=http://10.0.0.5:8765\nMT5_REMOTE_TOKEN=secret\n")
    env_file.chmod(0o600)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert result.returncode == 0


def test_malformed_lines_ignored_safely(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text(
        "this is not a key=value line\n"
        "MT5_REMOTE_URL=http://10.0.0.5:8765\n"
        "=orphan-value\n"
        "MT5_REMOTE_TOKEN=secret\n"
    )
    env_file.chmod(0o600)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert result.returncode == 0
    assert "ENV:MT5_REMOTE_URL=http://10.0.0.5:8765" in result.stdout
    assert "ENV:MT5_REMOTE_TOKEN=secret" in result.stdout


def test_unknown_keys_not_exported(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text(
        "MT5_REMOTE_URL=http://10.0.0.5:8765\n"
        "MT5_REMOTE_TOKEN=secret\n"
        "SOME_OTHER_VAR=should-not-be-exported\n"
    )
    env_file.chmod(0o600)
    fake_python = repo / ".venv" / "bin" / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'echo "SOME_OTHER_VAR=${SOME_OTHER_VAR:-<unset>}"\n'
    )
    fake_python.chmod(0o755)

    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert "SOME_OTHER_VAR=<unset>" in result.stdout


def test_shell_commands_in_env_file_not_executed(tmp_path):
    repo = _make_fake_repo(tmp_path)
    home = tmp_path / "home"
    (home / ".config" / "tradingia").mkdir(parents=True)
    marker = tmp_path / "should_not_exist.txt"
    env_file = home / ".config" / "tradingia" / "mt5.env"
    env_file.write_text(
        f'MT5_REMOTE_URL=http://10.0.0.5:8765; touch {marker}\n'
        f"MT5_REMOTE_TOKEN=$(touch {marker})\n"
    )
    env_file.chmod(0o600)

    _run_tia(repo, ["status"], cwd=tmp_path, env={"HOME": str(home)})
    assert not marker.exists()


def test_exit_code_propagated(tmp_path):
    repo = _make_fake_repo(tmp_path)
    result = _run_tia(repo, ["status"], cwd=tmp_path, env={"FAKE_EXIT_CODE": "7"})
    assert result.returncode == 7


@pytest.mark.skipif(sys.platform == "win32", reason="posix-only script")
def test_installer_creates_symlink(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    target = home / ".local" / "bin" / "tia"
    assert target.is_symlink()
    assert Path(os.readlink(target)) == REPO_ROOT / "scripts" / "tia"


def test_installer_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    r1 = subprocess.run(["bash", str(INSTALL_SCRIPT)], cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=10)
    r2 = subprocess.run(["bash", str(INSTALL_SCRIPT)], cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=10)
    assert r1.returncode == 0
    assert r2.returncode == 0
    assert "already points to" in r2.stdout


def test_installer_does_not_overwrite_real_file_without_confirmation(tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    real_file = home / ".local" / "bin" / "tia"
    real_file.write_text("#!/bin/sh\necho not-the-wrapper\n")
    real_file.chmod(0o755)
    env = dict(os.environ, HOME=str(home))

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        input="n\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert real_file.read_text() == "#!/bin/sh\necho not-the-wrapper\n"


@pytest.mark.skipif(sys.platform == "win32", reason="posix-only script")
def test_setup_helper_creates_0600_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    result = subprocess.run(
        ["bash", str(SETUP_SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        input="http://192.168.1.50:8765\nmy-secret-token\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    env_file = home / ".config" / "tradingia" / "mt5.env"
    assert env_file.exists()
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600
    content = env_file.read_text()
    assert "MT5_REMOTE_URL=http://192.168.1.50:8765" in content
    assert "MT5_REMOTE_TOKEN=my-secret-token" in content
    assert "my-secret-token" not in result.stdout
