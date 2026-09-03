# FX Phase 0 status

**LIVE DISABLED.** No live trading exists anywhere in this phase. See
`LIVE_TRADING_RULES.md` and `configs/real_money_policy.yaml`
(`live_trading_enabled: false`).

## Objective

Prove that this codebase (running on Linux) can safely and observably
drive a MetaTrader 5 DEMO account (running in a Windows VM) before any
FX strategy research or real money is discussed. Phase 0 is
infrastructure and safety plumbing, not a trading strategy.

## Target architecture

```
Linux / TradingIA (this repo)
        |
        | LAN, HTTP (planned)
        v
Windows VM / mt5_bridge (separate small package, not this repo's strategy code)
        |
        v
MetaTrader5 Python package
        |
        v
MT5 terminal
        |
        v
Broker DEMO account
```

The Windows VM runs in bridge/LAN networking mode and gets its own LAN
IP; it does not need or receive a copy of this full repository — only
the small `mt5_bridge` package is deployed there. The `MetaTrader5`
Python package is imported only on the Windows side (`mt5_bridge/backend.py`'s
`RealMT5Backend`); nothing in this repo's Linux-side code imports it.

## READ-ONLY END-TO-END VALIDATED (2026-09-03, approximate UTC)

The full read-only path was exercised against real hardware/infrastructure,
not just fakes/tests:

```
Linux Mint
        |
        | LAN bridge
        v
Windows VM
        |
        v
FastAPI mt5_bridge
        |
        v
MetaTrader5 Python
        |
        v
HFM MT5 Demo
```

Verified in this real run:

- authenticated `GET /v1/health` (bearer token required and accepted)
- `terminal_connected = true`
- account detected, `trade_mode = DEMO`, `environment = DEMO`
- broker/server correctly identified as an HFM demo server
- `EURUSD` symbol metadata retrieved (digits, point, volume_min/step/max,
  contract size, tick size/value, trade_enabled, visible)
- real bid/ask quote retrieved
- historical M15 bar retrieval
- a 6-hour history request returned 24 M15 bars
- **no orders were placed** — this remains a read-only validation

No account login ID, token, broker password, or specific private IP is
recorded here. HFM is mentioned only as the demo broker currently used
for this validation pass — it is **not** frozen as the eventual live
broker; see `BROKERS_MT5_OPTIONS.txt`.

### Step 3.1 correction (same validation pass)

Two issues were found during this real run and fixed before proceeding
to any order-placement work:

1. **History requests had no explicit timeframe.** `HistoryRequest` did
   not expose a timeframe field, so every real request silently fell
   through to the bridge's old implicit `M15` default regardless of what
   was actually wanted. Fixed by adding `ExecutionTimeframe` (a closed
   enum: M1/M5/M15/M30/H1/H4/D1) and making `HistoryRequest.timeframe`
   required with no default. The bridge's `timeframe` query parameter is
   now also required (422 if omitted) rather than defaulting.
2. **Float artifacts reaching Decimal.** A real EURUSD ask arrived as
   `Decimal('1.1587399999999999')` instead of the economically correct
   `Decimal('1.15874')` — an MT5 binary-float artifact that survived
   `str(float)` → JSON → `Decimal(str(...))` unchanged. Fixed by adding
   `mt5_bridge/quantize.py`, a single centralized conversion point used
   inside `RealMT5Backend` (as close to the raw MT5 call as possible):
   `quantize_price` (uses the symbol's `digits`, for bid/ask/OHLC),
   `quantize_volume` (uses `volume_step`, kept independent of price
   digits), and `clean_decimal` (for account balance/equity/margin and
   other values with no natural fixed digit count — critically, this
   removes binary noise *without* truncating real precision, unlike the
   previous `format(value, ".2f")` behavior it replaced).

A follow-up real run after fix #2 still showed history OHLC artifacts
(`open=1.1584699999999999` for M15, `open=1.1586400000000001` for H1)
even though the quote path was already clean. Investigation reproduced
the exact reported values end-to-end (`RealMT5Backend.copy_rates_range`
with a numpy-structured-array MT5 stub carrying those precise floats →
`BackendBar` → `history_response` JSON → real HTTP → Linux client) and
confirmed the CURRENT code in this repository already quantizes all four
OHLC fields correctly (`mt5_bridge/tests/test_history_ohlc_quantization_regression.py`).
**The actual cause was an out-of-date `mt5_bridge/` deployment on the
Windows VM** — predating the `quantize_price` integration into
`copy_rates_range` — that had not been re-copied/restarted after that
fix landed. This is a reminder, not a code defect: `mt5_bridge/` has no
git history and is deployed by manual copy (see `mt5_bridge/README.md`
step 4) — after ANY change to `mt5_bridge/`, the whole directory must be
re-copied to the VM and `python -m mt5_bridge` restarted before the fix
can be observed there.

## READ-ONLY: end-to-end validated for real (see above, 2026-09-03).

## WRITE (Step 4, DEMO market orders): REAL END-TO-END VALIDATED (2026-09-03 UTC).

Validated against the Windows VM / real HFM Demo terminal from Linux via
`tia`: preflight, permission gating, minimum-volume BUY, broker fill, live
position visibility, full close, zero-position final state, and
reconciliation `ok`. The real test opened EURUSD at the broker minimum
volume (`0.01`) and closed the same position successfully. Balance moved
from USD 100.00 to USD 99.61, consistent with the observed price move.
No live account or real money was used.

The real validation also exercised failure paths before the successful
cycle: future-timestamp rejection, manual resolution of a provably
pre-submission `RECEIVED` row, and MT5 retcode 10027 when AutoTrading was
disabled. AutoTrading permission is now surfaced in status/preflight and
re-checked server-side before submission.

### Step 4 deploy-time bug found and fixed before any real-VM attempt

The first real attempt to run `python -m mt5_bridge` on the Windows VM
failed immediately with `ModuleNotFoundError: No module named 'src'`.
Cause: `mt5_bridge/reconciliation.py` imported
`ReconciliationReport`/`ReconciliationState` from `src.execution.base`
-- but `mt5_bridge/` is deployed to the VM **on its own**, without the
rest of this repo's `src/` tree (see `mt5_bridge/README.md` step 4).
Every other Step 3/4 module was already careful about this; this one
import slipped through. Fixed by defining an equivalent
`ReconciliationState`/`ReconciliationReport` locally inside
`mt5_bridge/reconciliation.py` (same member names/values as the
Linux-side ones, kept in sync by convention rather than a shared
import) -- `mt5_bridge/` now has zero imports from `src.*` anywhere in
its non-test code, verified by grepping the package and by importing
`mt5_bridge` from a directory that does not contain `src/` at all.

### Implemented

- `src/execution/base.py` — broker-agnostic domain types: `Environment`,
  `AccountTradeMode`, `ReconciliationState`, `Side`, `OrderType`,
  `OrderStatus`, `ActionKind`, `ExecutionTimeframe`, `SymbolMetadata`,
  `SymbolSummary`, `Quote`, `AccountSummary`, `Position`, `Order`,
  `OrderRequest`, `ExecutionResult` (now carries observed bid/ask,
  reference price, fill price, slippage, MT5 retcode, position_id,
  idempotent_replay), `CloseRequest`/`CloseResult`, `KillSwitchState`/
  `KillSwitchStatus`, `ReconciliationReport`, `HistoryRequest`,
  `HistoryBar`, `HistoryResult`, `HealthStatus` (now with
  `bridge_version`/`bridge_build`), and the `ExecutionClient` Protocol
  (now including `place_order`, `close_position`, kill-switch and
  reconciliation methods). Money/price/volume fields use `Decimal`.
- `src/execution/policy.py` — unchanged from Step 1; reused as-is by
  Step 4's `SafeExecutionService`, not duplicated.
- `src/execution/mt5_remote.py` — `MT5RemoteExecutionClient` now
  implements `place_order`/`close_position`/kill-switch/reconciliation
  methods via `POST` to `/v1/demo/...`, `/v1/kill-switch/...`,
  `/v1/reconciliation/run`. `ExecutionWriteRejectedError` carries the
  bridge's own structured `error.code` (e.g. `"kill_switch_active"`,
  `"reconciliation_required"`, `"not_demo"`) so callers can branch on
  the specific reason a write was refused.
- `src/execution/safe_execution.py` — `SafeExecutionService.safe_open`/
  `safe_close`: fetches account/symbol/positions/kill-switch/
  reconciliation, builds a `PolicyContext`, calls Step 1's
  `authorize_open`/`authorize_close` unchanged, and only on `allowed`
  proceeds to the remote call. This is the ONLY sanctioned way to place
  or close a demo order from Linux-side code (the raw client methods
  exist for the CLI/service to call, not for a strategy to call directly).
- `src/cli/mt5_remote_cli.py` — `python -m src.cli mt5-remote
  status|preflight|positions|demo-open|demo-close|kill-status|
  kill-activate|kill-deactivate|reconcile`. `demo-open` requires
  `--confirm-demo-order` and always uses the symbol's minimum volume
  (never a CLI-supplied size).
- `mt5_bridge/` (Windows-side package), extended:
  - `app.py` — adds `POST /v1/demo/orders`, `POST
    /v1/demo/positions/{id}/close`, `GET/POST /v1/kill-switch...`,
    `GET/POST /v1/reconciliation...`, `GET /v1/journal`. No
    `/v1/live/...` route exists; no generic `POST /v1/orders`. FastAPI's
    own 422 validation errors are now unified under the same
    `{"error": {code, message}}` envelope as every other error.
  - `backend.py` — `MT5Backend` gains `order_check`/`order_send`;
    `BackendSymbolInfo` gains `filling_mode`; `trade_enabled` now
    correctly reflects MT5's `SYMBOL_TRADE_MODE_FULL` (a Step 3 bug: it
    previously treated any nonzero `trade_mode` as enabled, which is
    wrong for long-only/short-only/close-only modes). `FakeMT5Backend`
    can simulate a successful fill, an `order_check` rejection, a
    non-DONE `order_send` retcode, and a crash during `order_send`.
  - `store.py` — new: SQLite-backed `BridgeStore` (idempotency table,
    append-only journal, kill-switch state, last reconciliation result).
    Persists across restarts.
  - `trading.py` — new: `place_demo_order`/`close_demo_position`, the
    only code that calls `order_check`/`order_send`. Re-verifies DEMO
    server-side (fresh `account_info()`) before anything else; checks
    idempotency before any business-state check (so a retry of an
    already-filled order replays correctly even if e.g. the position
    count would otherwise look "full"); on a crash between `order_send`
    and recording the result, leaves the record in SUBMITTED rather
    than assuming success or failure.
  - `reconciliation.py` — new: `run_reconciliation`/
    `get_reconciliation_status`. Never destructively "fixes" a stuck
    idempotency row -- only reports MISMATCH/UNKNOWN and lets policy
    block new entries until a human resolves it.
  - `identity.py` — new: fixed magic number (`MT5_TRADINGIA_MAGIC`,
    configurable, never 0) + a short deterministic comment tag
    (`TIA:<8 hex chars>`) derived from `client_order_id`, embedded in
    every order TradingIA places. The full mapping lives in SQLite; the
    comment tag alone is never treated as sufficient identity.
  - `sanitize.py` — new: central redaction of bearer tokens, password/
    token key-value pairs, and filesystem paths from any message before
    it is logged, journaled, or returned in an API response.
  - `quantize.py`, `config.py`, `auth.py`, `errors.py`, `schemas.py`,
    `smoke.py`, `__main__.py` — extended for Step 4 (config gains
    `magic`/`max_quote_age_seconds`/`deviation_points`/`db_path`;
    `__main__.py` now runs reconciliation once at startup before
    accepting requests; `errors.py` gains `ConflictError` (409) and
    `TradingWriteError` (per-reason status/code)).
- Extensive tests: `tests/test_execution_base.py`,
  `tests/test_execution_policy.py` (unchanged, reused),
  `tests/test_mt5_remote.py`, `tests/test_safe_execution.py`,
  `mt5_bridge/tests/test_app.py`, `test_store.py`, `test_trading.py`,
  `test_reconciliation.py`, `test_sanitize.py`, `test_identity.py`,
  `test_quantize.py`, `test_history_ohlc_quantization_regression.py`,
  plus real-socket integration coverage
  (`mt5_bridge/tests/test_integration_socket.py`, marked `integration`)
  for a successful demo open, idempotent retry, close, kill-switch
  lifecycle/enforcement, and reconciliation-mismatch enforcement -- all
  over genuine HTTP against an in-process `uvicorn` server, no MT5.

### Step 4.1 audit hardening after real validation

After inspecting the real execution journal, the audit trail was hardened:

- every write journal event now receives the actual middleware-generated or
  caller-supplied `X-Request-ID`; normal trading events no longer store
  `request_id=None`;
- fill/order-check/submission events persist the exact quote context used at
  the execution boundary: quote timestamp, bid, ask, spread, reference price,
  requested/filled or closed volume, fill price, slippage, MT5 retcode, and
  broker/deal/position identifiers where applicable;
- close retries now resolve idempotency **before** looking up the live position,
  so a network retry after a successful close replays the stored result instead
  of failing because the position is already gone;
- definite pre-submission rejects (kill switch, stale quote, invalid volume,
  missing position, permission denial, order-check rejection, etc.) are
  terminalized as `REJECTED` instead of leaving a false ambiguous `RECEIVED`
  row that poisons reconciliation;
- `close_position.submitting` is now journaled explicitly, matching the crash
  boundary already used by reconciliation safety checks.

Bridge build: `step4-audit-hardened-2026-09-03`. No additional real/demo order
was executed while implementing this hardening.

### Explicitly NOT implemented (Step 4 scope limits, deliberate)

- Pending/stop/limit orders, partial closes, any order type besides a
  single MARKET buy/sell.
- Live trading anywhere (`live_trading_enabled` stays `false`; no
  `/v1/live/...` route exists in code).
- A CLI-supplied order volume (always the symbol's minimum).
- Automated reconciliation "auto-fix" -- a human runs
  `POST /v1/reconciliation/run` (or the CLI) after resolving ambiguity
  manually; the bridge never guesses.
- Deep MT5-side reconciliation matching (using magic/comment/deals to
  positively confirm what an ambiguous stuck order actually did) --
  today's `run_reconciliation` reports the ambiguity; recovering full
  certainty about a specific stuck `client_order_id` from MT5's own
  history is a natural next step, not yet built.
- A `GET /v1/symbols` listing (added in the Step 3.1 correction) remains
  lightweight (symbol/description/visible/trade_enabled only).

## Phase 3 / prior-phase integrity

This work does not touch `src/research/`, `src/forward/`,
`src/strategies/`, or any file guarded by
`src/research/phase3_guard.py`. Phase 3's fingerprint was verified
unchanged before and after this step.

## MT5 live-tick clock normalization (2026-09-03)

A real HFM Demo diagnostic measured Linux and the Windows bridge within ~3 ms
of each other, while `symbol_info_tick("EURUSD").time` appeared ~10,799 s
(~3 h) ahead.  This is an observed HFM/terminal behavior in this environment;
it is **not** treated as a general MT5 guarantee. MetaQuotes' Python
`copy_rates_range` documentation states that received tick/bar history times
are UTC.

For the execution path, the bridge now normalizes **live tick timestamps only**
using an empirical `ServerClockOffset`: first use accepts only a plausible
clock offset close to a 30-minute boundary; later it can recalibrate only when
the residual itself looks like a clean half-hour clock change (for example a
DST/server-clock shift). Ordinary stale ticks do not trigger recalibration;
they remain stale so the existing freshness guard can reject them.

Historical bars are deliberately **not** shifted by the current live offset.
Applying today's +2/+3/etc. offset to older data could silently move bars by an
hour across DST transitions and corrupt research. Historical HFM timestamp
semantics must be validated independently before any broker-specific history
correction is introduced.

Read-only verification after deploying the updated bridge:

```bash
tia mt5 time-diagnostics EURUSD
```

Expected on a fresh market tick: `server_clock_offset_seconds` reports the
measured bridge correction (the HFM observation was +10800 s), while
`tick_bridge_skew_seconds` and quote age should collapse from hours to roughly
normal network/tick latency. No order should be retried until this diagnostic
and reconciliation are both clean.
