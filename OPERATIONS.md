# TradingIA Operations

## Operational contract

Phase 5 research is paused. TradingIA is operational as an observer, not as a trading strategy.

- Strategy authorization: **NONE**
- DEMO authorization: **NONE**
- LIVE authorization: **NONE**
- Default mode: `READ_ONLY`
- Default strategy: `NONE`
- Default decision: `NO_ACTION / NO_AUTHORIZED_STRATEGY`
- Orders authorized by the runtime: **0**

The runtime uses only read methods from the MT5 client and a `NoopExecutor` with no order-placement API. The Windows bridge retains its independently enforced DEMO-only write safeguards, but the operational runtime does not call them.

## How to start TradingIA

From the repository root:

```bash
./scripts/tia runtime start
```

This starts a continuous read-only cycle every 30 seconds. It reads bridge/MT5/account/symbol/quote/reconciliation state, writes an append-only local decision journal, and makes no order.

For one cycle only:

```bash
./scripts/tia runtime start --once
```

Required local connection settings are loaded by the existing `tia` wrapper from `~/.config/tradingia/mt5.env` if it is mode `0600`:

```text
MT5_REMOTE_URL=http://<windows-vm-ip>:8765
MT5_REMOTE_TOKEN=<bridge-token>
```

Do not commit this file or print its token.

Safe runtime environment defaults:

```text
TRADINGIA_MODE=READ_ONLY
TRADINGIA_STRATEGY=NONE
TRADINGIA_SYMBOL=EURUSD
TRADINGIA_CYCLE_SECONDS=30
TRADINGIA_RUNTIME_JOURNAL=~/.local/state/tradingia/runtime_journal.jsonl
```

`TRADINGIA_STRATEGY` is rejected unless it is exactly `NONE`. A missing mode becomes `READ_ONLY`; a `LIVE` mode is still hard-denied.

## How to check status

```bash
./scripts/tia runtime status
```

This is local and shows the configured mode, authorization state, journal path, and the last durable cycle. For direct bridge status:

```bash
./scripts/tia mt5 status
```

## How to run doctor

```bash
./scripts/tia runtime doctor
```

Doctor executes the full read-only pre-flight and prints `PRE-FLIGHT PASS` or `PRE-FLIGHT FAIL`. It exits non-zero on a critical failure. Checks include bridge/terminal/account, DEMO account identity, symbol metadata, quote freshness, kill switch, reconciliation, and unexpected broker positions/orders.

## How to run dry-run

```bash
./scripts/tia runtime dry-run
```

Dry-run performs one pipeline cycle: health, reconciliation status, fresh quote, strategy authorization, safety decision, and journal append. Its executor is `NOOP_EXECUTOR`; it cannot invoke `place_order` or `close_position`.

## How to stop

Press `Ctrl+C` or send `SIGTERM` to the runtime process. It stops future cycles after the current cycle journals its result. It does not close broker positions automatically.

## What a healthy no-trade cycle looks like

A healthy bridge/account/quote/reconciliation cycle with no positions yields:

```text
strategy: NONE
decision: NO_ACTION
reason: NO_AUTHORIZED_STRATEGY
execution_allowed: false
execution_denial_reason: NO_AUTHORIZED_STRATEGY
```

This is the expected current result, not an error.

## Failure states

- `QUOTE_STALE`: do not reuse an old quote; inspect Windows MT5 and clocks.
- `BRIDGE_UNAVAILABLE`: runtime becomes degraded/disconnected and makes no action.
- `MARKET_CLOSED`: expected during weekends when quote data is unavailable; still no action.
- `RECONCILIATION_FAILED`: refuse new exposure; inspect the bridge journal and reconciliation state.
- `KILL_SWITCH_ACTIVE`: no new exposure.
- `UNKNOWN_BROKER_POSITION`: journal the alert; do not close it automatically and do not open another position.
- `LIVE_DISABLED`: live mode is a hard no-trade block.

Run the bridge clock diagnostic when freshness is suspect:

```bash
./scripts/tia mt5 time-diagnostics EURUSD
```

## Recovery after a Windows VM restart

On Windows:

1. Start MT5 and confirm the intended **DEMO** account is logged in.
2. Start the bridge from the deployed `mt5_bridge` directory:

   ```powershell
   python -m mt5_bridge.smoke
   python -m mt5_bridge
   ```

   Bridge startup runs reconciliation before accepting requests.

3. On Linux, run:

   ```bash
   ./scripts/tia runtime doctor
   ./scripts/tia runtime dry-run
   ./scripts/tia runtime status
   ```

Do not deactivate a kill switch or resolve reconciliation merely to make a check green. Those are explicit operator actions. Never delete the bridge SQLite store casually: it contains idempotency, reconciliation, kill-switch, and bridge journal state.

## Service mode

The runtime is suitable for a foreground supervised process. A future systemd unit may invoke:

```text
<repo>/scripts/tia runtime start
```

but deployment automation is intentionally not installed by this phase. The Windows bridge is a separate VM process and must be supervised/restarted there; its startup procedure is documented in `mt5_bridge/README.md`.

## Continuous observation and recovery

`runtime start` is a sequential, single-instance loop. It holds an advisory
lock beside runtime state, writes `runtime_heartbeat.json` after each durable
cycle, and exponentially backs off read-only checks after degraded cycles
(bounded at five minutes). It never retries writes because normal operation has
no write capability.

Use compact machine-readable status for monitoring:

```bash
./scripts/tia runtime status --json
```

Status answers “what happened”; `runtime doctor` performs a deeper current
readiness check. A healthy READ_ONLY runtime requires read readiness only:
bridge/terminal/account/symbol/quote/reconciliation. AutoTrading disabled is
reported by the MT5 preflight for future write readiness but does not prevent
safe observation when reads work.

For Linux autostart, install a **user** systemd unit outside the repository
after confirming the connection environment is available through the protected
`~/.config/tradingia/mt5.env` file:

```ini
[Unit]
Description=TradingIA safe observation runtime
After=network-online.target
[Service]
Type=simple
ExecStart=/absolute/path/to/tradingia/scripts/tia runtime start
Restart=on-failure
RestartSec=30
[Install]
WantedBy=default.target
```

Then use `systemctl --user daemon-reload`, `enable --now tradingia-runtime`,
`status tradingia-runtime`, `restart tradingia-runtime`, and `disable --now
tradingia-runtime`. Do not put bridge tokens in the unit file.

Windows bridge/MT5 autostart has not been changed automatically. After a VM
reboot, log in, start MT5 and its DEMO session, then run `python -m mt5_bridge`
from the deployed bridge directory. If persistent Windows autostart is needed,
create a Task Scheduler task for that command only after verifying the logged-in
DEMO session; the bridge health and Linux doctor remain the readiness authority.

## Data capture boundary

Read-only operational observation may journal runtime health and future quote observations. It must not consume the protected EURUSD/M15 untouched interval, the unassigned Phase 5H future test, or USDJPY/H1 future-test performance for research. Operational observation is not a backtest and not research authorization.

## Single-use DEMO execution plumbing test

This is an infrastructure acceptance probe, never a strategy, candidate, or
performance test. Normal runtime operation remains `READ_ONLY` with
`strategy = NONE` and cannot invoke this path.

Only an explicit, temporary operator scope enables it:

```bash
TRADINGIA_MODE=DEMO \
TRADINGIA_DEMO_EXECUTION_TEST=ENABLED \
./scripts/tia runtime demo-execution-test --side buy --confirm-demo-execution-test
```

The side is an operator-selected fixture, not market logic. The command
requires the broker's unambiguous DEMO metadata, policy LIVE disabled, inactive
kill switch, reconciliation `OK`, zero pre-existing positions/orders, a visible
and tradable configured symbol, fresh quote, and the broker-reported minimum
volume. It performs exactly one open and one close, then writes a durable
single-use state record at `~/.local/state/tradingia/demo_execution_test.json`.
After a completed test the state is `CLOSED` and authorization is `EXPIRED`;
running the same path again refuses. It never evaluates PnL.

If an open/close response is ambiguous, the probe records `AMBIGUOUS`, runs
reconciliation, and refuses to retry the write. Do not delete that state or
retry with a new ID; inspect the bridge journal and broker state first.

If the kill switch activates after a known test position opens, the existing
bridge policy still permits a fully reducing close. It never permits a new
open. The final state must show zero positions and zero pending orders.
