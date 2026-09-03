# Continuation notes — MT5 clock fix

Continued from Claude's interrupted session on 2026-09-03.

Key decisions in this continuation:

- Kept dynamic live-tick clock calibration for the empirically measured HFM +3h skew.
- Hardened calibration so ordinary stale ticks do not trigger timezone recalibration; freshness logic remains responsible for rejecting stale quotes.
- Recalibration occurs only on a clean 30-minute clock-step signature (e.g. DST/server-clock shift).
- Initial calibration rejects ambiguous/non-timezone-shaped skew and implausible offsets.
- **Did not apply the current live-tick offset to `copy_rates_range()` history.** MetaQuotes documents returned bar history as UTC, and applying today's offset to old bars could corrupt timestamps across DST. Historical HFM semantics need a separate real-world validation.
- Added dedicated server-clock tests, including the measured +3h case, DST-like +3→+2 transition, stale quote behavior, fail-closed cases, backend tick integration, and a regression proving live offset does not shift historical bars.

Validation in the sandbox:

- `236 passed` for execution/bridge/CLI/freshness focused tests.
- `11 passed` for Phase 3 guard/forward tests.
- `657 passed` for the whole suite excluding the three parquet-dependent test files.
- Full suite could not be run here because the sandbox lacks `pyarrow==25.0.1` and has no package-network access. The remaining full-suite failures were dependency errors, not assertion/code failures.

Next real-machine steps:

1. Copy the updated `mt5_bridge/` folder to the Windows VM and restart the bridge.
2. Run `tia mt5 time-diagnostics EURUSD` from Linux.
3. Verify `server_clock_offset_seconds` is about `10800` for the current HFM session and `tick_bridge_skew_seconds`/quote age collapse to normal sub-second/few-second values.
4. Do **not** retry the prior failed `client_order_id`.
5. Check reconciliation. The previous failed attempt likely left a `RECEIVED` idempotency record; do not delete it blindly.
6. Only after diagnostics + reconciliation are clean, repeat preflight before any new DEMO order.

## Manual resolution for provably pre-submission RECEIVED rows

Added after the first real HFM demo-open attempt was blocked by quote-time validation and left its idempotency row in `RECEIVED`.

- New operator command: `tia mt5 resolve-received <client_order_id> --confirm-abort-before-submission`.
- New authenticated bridge endpoint: `POST /v1/reconciliation/resolve-received/{client_order_id}` with body `{"confirm_abort_before_submission": true}`.
- The resolver accepts **only** `RECEIVED`. `SUBMITTED` is never resolvable through this path.
- It refuses rows carrying broker/deal/position/result identifiers.
- It refuses journal evidence of submission/send/fill.
- It independently queries current MT5 positions/orders and refuses a matching TradingIA `magic + comment` identity.
- The state transition is atomic (`RECEIVED -> REJECTED`) with `error_code=aborted_before_submission`; a concurrent request cannot overwrite the resolution and continue to `order_send`.
- The resolution is journaled append-only as `reconciliation.received_resolved`, then reconciliation is recomputed.
- Terminal `REJECTED` client IDs without replay payload are now explicitly non-reusable; callers must use a new `client_order_id`.

Validation in this sandbox after the change:

- 235 focused bridge/client tests passed after the explicit-confirmation hardening.
- 669 tests passed across the full suite excluding the three parquet-dependent test files.
- Full-suite remaining failures are still only missing `pyarrow`/`fastparquet` in this sandbox.


## AutoTrading preflight patch (2026-09-03)

After a real HFM demo `order_send` returned retcode 10027 (`AutoTrading disabled by client`) with no position opened, the bridge/client were hardened so this operational condition is detected before submission:

- `/v1/terminal` already exposed `terminal_info().trade_allowed`; Linux now models/reads it.
- `/v1/account` now exposes MT5 `trade_allowed` and `trade_expert` flags. Missing flags remain `None`/unknown and fail closed for automated writes.
- `tia mt5 status` and `tia mt5 preflight` show the permission flags.
- preflight fails with a clear manual-action message when terminal AutoTrading is disabled.
- bridge `place_demo_order` independently re-reads terminal/account permissions after idempotent replay/conflict handling but before `order_check`/`order_send`. A fresh permission failure is terminally recorded as `REJECTED`, so it cannot create another orphan `RECEIVED` reconciliation mismatch while preserving the idempotency-first replay contract.
- bridge close path also checks permissions because MT5 cannot execute an API close while client Algo Trading is disabled; kill-switch semantics remain unchanged (the bridge does not itself block risk-reducing closes).
- new bridge build id: `step4-autotrading-preflight-2026-09-03`.

No order was executed while implementing this patch.


## 2026-09-03 — Journal CLI operator view

Added read-only `tia mt5 journal [--limit N]` on the Linux side. The bridge already exposed authenticated `GET /v1/journal`; this change only wires that existing endpoint into `MT5RemoteExecutionClient` and the CLI. No Windows bridge redeploy is required for this patch. Journal payloads remain bridge-sanitized and are treated as opaque structured data by Linux.


## 2026-09-03 — Step 4.1 audit hardening after real HFM Demo validation

Real DEMO cycle completed successfully before this patch: EURUSD minimum-volume
BUY filled, position was visible, full close filled, final positions were empty,
and reconciliation returned `ok`. Journal review exposed two audit weaknesses
(`request_id=None` on normal writes and sparse fill payloads) plus two safety
edge cases found during the hardening pass.

Changes:

- write endpoints now pass `Request.state.request_id` from the bridge request-ID
  middleware into trading/reconciliation journal events, preserving generated or
  caller-supplied `X-Request-ID`;
- open/close order-check, submitting, rejection, and fill journal events carry
  exact quote/execution context (UTC quote timestamp, bid/ask/spread, reference
  price, volume, fill, slippage, MT5 retcode, broker/deal/position IDs);
- close idempotency is resolved before live position lookup, so retrying an
  already-successful close replays safely after the position disappeared;
- definite pre-submission TradingError paths terminalize fresh RECEIVED rows as
  REJECTED, preventing false reconciliation mismatches;
- close now journals an explicit `close_position.submitting` boundary;
- bridge build bumped to `step4-audit-hardened-2026-09-03`.

Validation in this sandbox:

- 121 focused trading/app tests passed after the changes.
- Phase 3 guard/forward: 11/11 passed.
- broad suite: 715 passed; 6 failures + 4 setup errors are exclusively missing
  `pyarrow`/`fastparquet` parquet support in this environment, not assertion
  failures in the changed execution code.
- No MT5 order was executed while implementing this hardening.
