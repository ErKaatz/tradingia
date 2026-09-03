# `tia` CLI setup

`tia` is a convenience wrapper around TradingIA's real CLI
(`python -m src.cli ...`), letting you run it from any directory without
manually `cd`-ing into the repo, activating `.venv`, or exporting bridge
connection variables every time. It contains no trading logic of its own --
see `scripts/tia`.

## First-time installation (run once)

```
cd /path/to/tradingia
./scripts/install_cli.sh
```

This creates a symlink at `~/.local/bin/tia` pointing at `scripts/tia` in
this repo. Because it's a symlink, `git pull` picks up wrapper changes
immediately -- no reinstall needed. If `~/.local/bin` is not already on
your `PATH`, the script prints the exact line to add to your shell rc file
(it will not edit `~/.bashrc`/`~/.zshrc` for you).

## Configure the MT5 bridge connection (run once, or whenever it changes)

```
./scripts/setup_mt5_remote.sh
```

This prompts for `MT5_REMOTE_URL` and `MT5_REMOTE_TOKEN` (the token input is
hidden) and writes them to:

```
~/.config/tradingia/mt5.env
```

with permissions `600`. This file lives outside the repo and is never
committed. It holds only the bridge URL and bridge token -- **never** your
MT5 account login/password/broker password; those are only ever set as
environment variables directly on the Windows VM running `mt5_bridge`, per
`mt5_bridge/README.md`.

`tia` refuses to read this file if its permissions are looser than `600`
(fails closed, since it can hold a real bridge token) -- fix with:

```
chmod 600 ~/.config/tradingia/mt5.env
```

You can skip the helper and create the file yourself with a text editor if
you prefer; just make sure to `chmod 600` it afterward.

### Env var precedence

1. A variable already set in your shell's environment always wins.
2. Otherwise, the value from `~/.config/tradingia/mt5.env` is used.
3. Otherwise, the underlying CLI will fail with a clear error when it
   actually needs the missing value.

This means you can override the file temporarily without editing it:

```
MT5_REMOTE_URL="http://other-host:8765" tia mt5 status
```

## Everyday usage

From any directory:

```
tia mt5 status
tia mt5 preflight EURUSD
tia mt5 positions
tia mt5 reconcile
tia mt5 kill-status
```

And later, only after you've explicitly reviewed and approved a
`preflight` result:

```
tia mt5 demo-open EURUSD buy --confirm-demo-order
tia mt5 demo-close <position_id>
```

`tia mt5 ...` is translated to `python -m src.cli mt5-remote ...` inside
the wrapper -- nothing else changes; every safety rule documented in
`mt5_bridge/README.md` and `FX_PHASE0_STATUS.md` (DEMO-only, kill switch,
reconciliation, minimum-volume-only sizing, `--confirm-demo-order`
required) still applies exactly as before. Any other TradingIA subcommand
also works unchanged, e.g. `tia backtest configs/sma_cross.yaml`.

## How it works (for reference)

- **Repo root**: resolved from the wrapper script's own location (`scripts/tia`),
  following symlinks, never from a hardcoded path or the current directory.
- **Python interpreter**: always `<repo>/.venv/bin/python`. If that doesn't
  exist, `tia` fails with a clear error rather than silently falling back to
  a global Python (a bridge-talking tool should never run under an
  unexpected interpreter).
- **Config file**: parsed with a restricted line-by-line `KEY=VALUE` reader,
  not `source` -- only `MT5_REMOTE_URL`, `MT5_REMOTE_TOKEN`, and
  `MT5_REMOTE_API_VERSION` are recognized; nothing in the file is ever
  executed as shell.
- **Signals/exit codes**: the wrapper `exec`s the real Python process (no
  subshell in between), so Ctrl+C and the process's exit code both pass
  through unchanged.

## Troubleshooting

- `TradingIA repository is unavailable ... Is the data volume mounted?` --
  the repo's disk/mount isn't attached. Mount it and retry.
- `TradingIA virtual environment not found` -- create it:
  ```
  python3 -m venv /path/to/tradingia/.venv
  /path/to/tradingia/.venv/bin/python -m pip install -r /path/to/tradingia/requirements.txt
  ```
- `refusing to read ... permissions are too open` -- run
  `chmod 600 ~/.config/tradingia/mt5.env`.
