# mt5_bridge — Windows VM deployment

Read-only endpoints (Step 3) plus DEMO-only market order placement/close
(Step 4). **No live trading anywhere, no order ever leaves this bridge
without the account first confirming DEMO server-side.** See
`../LIVE_TRADING_RULES.md` and `../FX_PHASE0_STATUS.md` for the
surrounding policy. Step 4's write path (`/v1/demo/orders`,
`/v1/demo/positions/{id}/close`) has been validated against a real
FakeMT5Backend/HTTP round-trip but, at the time of writing, NOT yet
against a real MT5 terminal -- see FX_PHASE0_STATUS.md for exactly what
is/isn't validated for real.

This package is meant to be copied to the Windows VM **on its own** —
not the full `tradingia` repository. Only the `mt5_bridge/` directory is
needed there.

## 1. Install Python on the Windows VM

Install Python 3.11+ from python.org (the official installer, not the
Microsoft Store version, to avoid path/permission quirks with MT5).

## 2. Install the MT5 terminal for your demo broker

Download and install the MetaTrader 5 terminal from your chosen broker
(see `../BROKERS_MT5_OPTIONS.txt` — nothing there is a final choice).

## 3. Log into a DEMO account in the terminal

Open the terminal, log into a **demo** account. Confirm in the terminal
UI itself that the account is demo before continuing — do not rely on
this bridge to be the first thing that checks that.

## 4. Copy `mt5_bridge/` to the VM

The Linux repo stays on Linux. Copy only this directory to the VM, e.g.:

- `scp` from Linux to the VM (if SSH is enabled on the VM), or
- a shared temp folder / drag-and-drop through your VM software, or
- zip `mt5_bridge/` on Linux and transfer it manually, then unzip on
  the VM.

## 5. Install dependencies (on the VM)

```
cd mt5_bridge
pip install -r requirements-windows.txt
```

This installs `MetaTrader5`, `fastapi`, and `uvicorn` — kept out of the
main Linux repo's `requirements.txt` on purpose (see that file's
comments / `FX_PHASE0_STATUS.md`).

## 6. Set environment variables (on the VM)

Required:

```
set MT5_BRIDGE_TOKEN=<a long random string you generate yourself>
```

Optional (defaults shown):

```
set MT5_BRIDGE_HOST=127.0.0.1
set MT5_BRIDGE_PORT=8765
set MT5_TERMINAL_PATH=C:\path\to\terminal64.exe
set MT5_TRADINGIA_MAGIC=20260903
set MT5_MAX_QUOTE_AGE_SECONDS=5
set MT5_DEVIATION_POINTS=20
set MT5_BRIDGE_DB_PATH=mt5_bridge.sqlite3
```

`MT5_TRADINGIA_MAGIC` (Step 4) is the fixed magic number this bridge
tags every order it places with (never 0, never randomized per request)
-- see `mt5_bridge/identity.py`. `MT5_MAX_QUOTE_AGE_SECONDS` (default 5)
is how old a quote can be before a demo order is refused as stale.
`MT5_BRIDGE_DB_PATH` is the SQLite file holding idempotency records, the
append-only journal, kill-switch state, and the last reconciliation
result -- it persists across restarts by design; do not delete it
casually, and back it up before any experiment where losing that history
would matter.

`MT5_BRIDGE_HOST=0.0.0.0` is refused by `BridgeConfig` — you must bind
explicitly. For local-only testing, leave the default `127.0.0.1`. To
reach the bridge from the Linux host over the bridged/LAN network,
set this to the VM's own LAN IP (see step 8).

If your terminal is not already logged in and you need the bridge
process itself to log in, you can also set:

```
set MT5_LOGIN=<account number>
set MT5_PASSWORD=<account password>
set MT5_SERVER=<broker server name>
```

Step 3's `RealMT5Backend.connect()` currently calls
`MetaTrader5.initialize()` without performing an explicit `mt5.login(...)`
call using these values — the simpler path of reusing an already
logged-in terminal session is what Step 3 implements and tests. If you
need the bridge to log in itself, treat `MT5_LOGIN`/`MT5_PASSWORD`/
`MT5_SERVER` as reserved for a later step and flag it back rather than
assuming it already works.

Never put any of these values in a file that gets committed anywhere.

## 7. Run the smoke check first

```
python -m mt5_bridge.smoke
```

This confirms MT5 initializes, a terminal is connected, an account is
logged in, and it prints (safely) whether that account reports as DEMO.
**Do not proceed if this reports anything other than DEMO**, and do not
proceed if it errors. It does not place any order.

## 8. Find the VM's LAN IP

In the Windows VM (with the network adapter in bridged mode), run:

```
ipconfig
```

Note the IPv4 address for the adapter connected to your LAN (e.g.
`192.168.1.50`). This is the value you'll set as `MT5_BRIDGE_HOST` if you
want to reach the bridge from the Linux host, and it's also the value
you'll use as `bridge_url` on the Linux side.

## 9. Start the bridge

```
python -m mt5_bridge
```

It runs reconciliation once at startup (Step 4) before logging
`MT5 backend connected; starting bridge on <host>:<port>`. If
reconciliation is not OK (e.g. a prior run's demo order was left
unresolved), it logs a warning but still starts -- reads and closes
remain available; new demo orders are refused until you run
`POST /v1/reconciliation/run` (or `python -m src.cli mt5-remote
reconcile`) to resolve it. Leave this running in its own terminal
window.

## 10. Restrict the Windows Firewall to the Linux host's IP

This project does not modify the Windows Firewall automatically. If you
want the bridge reachable from the LAN (not just `127.0.0.1`), open the
port manually and restrict it:

1. Find the Linux host's LAN IP (`ip addr` on Linux).
2. Windows Defender Firewall → Advanced Settings → Inbound Rules → New
   Rule → Port → TCP → the port from `MT5_BRIDGE_PORT` (default 8765).
3. Under Scope, set "Remote IP address" to **only** the Linux host's
   specific IP — not "Any IP address".
4. Name the rule clearly (e.g. "mt5_bridge from TradingIA host only")
   so it's easy to find and remove later.

## 11. Test from Linux -- READ-ONLY PREFLIGHT (do this first)

From the Linux repo, with `MT5_REMOTE_TOKEN` set to the same value as
the VM's `MT5_BRIDGE_TOKEN` and `MT5_REMOTE_URL` set to the bridge's URL:

```
export MT5_REMOTE_URL="http://<VM LAN IP>:8765"
export MT5_REMOTE_TOKEN="<same token as MT5_BRIDGE_TOKEN>"
python -m src.cli mt5-remote status
python -m src.cli mt5-remote preflight EURUSD
```

`preflight` is entirely read-only -- it never places an order -- and
prints exactly what to check: terminal connected, account trade_mode is
demo, kill switch inactive, reconciliation OK, zero open positions,
symbol's minimum volume, and a fresh bid/ask. Do not proceed past this
until `preflight` reports OK for every line.

## 12. First DEMO order -- only after explicit approval

```
python -m src.cli mt5-remote demo-open EURUSD buy --confirm-demo-order
```

This goes through `SafeExecutionService` (policy-checked on the Linux
side) and the bridge's own server-side DEMO/kill-switch/reconciliation/
symbol/quote checks -- both must agree before anything reaches MT5.
`--confirm-demo-order` is required; without it the command refuses to
run (a safety barrier against an accidental invocation during
development). Volume is always the symbol's own minimum -- there is no
flag to request a different size.

```
python -m src.cli mt5-remote positions
python -m src.cli mt5-remote demo-close <position_id>
```

`demo-close` always closes the position's FULL current volume -- Step 4
does not support partial closes.

## Kill switch / reconciliation / journal from the CLI

```
python -m src.cli mt5-remote kill-status
python -m src.cli mt5-remote kill-activate --reason "manual pause"
python -m src.cli mt5-remote kill-deactivate
python -m src.cli mt5-remote reconcile
```

## What this bridge will refuse to do

- No pending/stop/limit orders, no partial closes, no order type other
  than a MARKET buy/sell -- there is no route or code path for any of
  those in Step 4.
- No `/v1/live/...` route exists anywhere, and no generic ambiguous
  `POST /v1/orders` exists -- writes are exclusively under
  `/v1/demo/...`.
- Every write is re-verified server-side (a fresh `account_info()` call,
  never a cached value) to be DEMO immediately before touching MT5 --
  independent of whatever the Linux side already checked.
- A new/increased-risk write while the kill switch is ACTIVE is refused
  (`error.code = "kill_switch_active"`); closing a position is still
  allowed while the kill switch is active.
- A write while reconciliation is not OK is refused
  (`error.code = "reconciliation_required"`) -- see step 9 above.
- The same `client_order_id` retried with an identical request replays
  the stored result instead of submitting to MT5 again
  (`idempotent_replay: true` in the response); retried with a
  *different* request, it is rejected with HTTP 409.
- `/v1/health` and every other endpoint requires
  `Authorization: Bearer <MT5_BRIDGE_TOKEN>` — no unauthenticated route.
- Binding to `0.0.0.0` is refused at config-load time.
- Any account that does not report `trade_mode == demo` is still fully
  readable, but `account_response()` reports `environment`/`trade_mode`
  truthfully as `live`/`unknown` — it never claims `demo` unless MT5
  itself reports that trade mode code, and every write path hard-rejects
  in that case.

## Live tick clock normalization

The bridge has an empirical live-tick clock normalizer in `server_clock.py`.
It exists because the HFM Demo terminal used during Phase 0 produced a live
`symbol_info_tick().time` about three hours ahead of the bridge's synchronized
UTC clock. The normalizer does not hardcode HFM, EET/EEST, or +3h: it derives a
plausible 30-minute-aligned offset from a fresh live tick and only recalibrates
on a similarly clean clock-step signal.

This normalization is intentionally limited to **live ticks used by execution**.
`copy_rates_range()` bar timestamps remain interpreted as UTC, matching the
MetaQuotes Python API documentation. Do not apply the current live offset to
historical bars: a current offset cannot safely represent older data across
DST/server-clock changes.

Use `tia mt5 time-diagnostics EURUSD` after each bridge deployment to verify the
live correction before enabling any DEMO order attempt.
