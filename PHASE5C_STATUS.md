# Phase 5C — Cost calibration

## Preregistered first capture

Before retrieving any history, this calibration fixes the following input:

- Account context: HFM MT5 Demo Premium; research only.
- Symbol/timeframe: `EURUSD` / `M15`.
- Requested interval: `2026-08-03T00:00:00+00:00` through
  `2026-08-31T23:59:59+00:00`.
- Spread metric: broker-provided historical `spread_points`, grouped by the
  bar's UTC hour. A bucket requires at least 30 observed values; absent data
  stays absent and never becomes zero.
- Spread policy candidate: per-hour P95, with no fallback to an invented
  spread for an insufficient bucket.
- Commission: explicit `NoCommission` research assumption for this account
  class, pending preservation in the final frozen profile.
- Swap: broker metadata is the operational authority. Only MT5 swap mode
  `points` is convertible in this phase; other modes fail closed.

This capture calls only the bridge's `GET /v1/history`, `GET /v1/symbols`,
and `GET /v1/account` endpoints. It does not place, amend, or close orders.

## Capture result and second preregistration

The first request returned no history from MT5 (`copy_rates_range` returned
`None`), so it is not used for calibration. Before another request, the second
input is fixed as `EURUSD` / `M15`, from `2026-09-01T00:00:00+00:00` through
`2026-09-04T23:59:59+00:00`. All other rules above are unchanged. This shorter
window is intentionally descriptive only: it may be insufficient for a final
24-hour execution model, in which case the code must fail closed rather than
invent a value.

## Weekend investigation (2026-09-05)

- Bridge health, terminal, account, and EURUSD metadata all responded. The
  account is DEMO in USD and the bridge exposed `swap_long=-8.3`,
  `swap_short=0.0`, `swap_mode=1` (points), and
  `swap_rollover3days=3`.
- The terminal's live quote was unavailable because the first clock
  calibration saw an off-market/stale tick and correctly refused to guess a
  broker-clock offset. The bridge now maps this upstream condition to its
  structured `backend_unavailable` response rather than an internal 500. This
  fix was deployed to the VM and verified as HTTP 502 without placing orders.
- MT5 historical calls returned `Terminal: Call failed`; no dataset or spread
  profile was created, and this phase does not claim a calibrated spread.

`FrozenNonSpreadCosts` can freeze the explicit commission and the converted,
side-aware MT5 swap terms without pretending that spread history is known. A
full Phase 5C cost profile remains blocked on a successful post-reopen
historical capture.

## Third preregistration — reopened-market capture

Following a successful fresh-quote and seven-bar M15 history smoke test on
2026-09-07, the next read-only capture is fixed as `EURUSD` / `M15` from
`2026-09-01T00:00:00+00:00` through `2026-09-07T14:30:00+00:00`. The end is
the last closed bar at the time of preregistration. The same 30-observation
minimum and no-imputation policy apply.

The capture returned 443 bars, with no validation warnings. Its global P95
was 26 points, but no UTC-hour bucket reached 30 observations, so that global
number is descriptive only and is not selected as an execution spread.

## Fourth preregistration — coverage capture

To obtain the minimum per-hour coverage, the next read-only capture is fixed
as `EURUSD` / `M15` from `2026-08-03T00:00:00+00:00` through
`2026-09-07T14:30:00+00:00`. It supersedes the shorter saved dataset because
it includes it in full. The 30-observation threshold and no-imputation rule
remain unchanged.

## Coverage-capture result

The coverage capture returned 2,459 M15 bars and passed structural and gap
validation with no warnings. Every UTC-hour bucket has 100–104 observed
spreads (103 at hour 14), so all meet the 30-observation threshold. The
dataset SHA-256 is
`0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9`;
the raw-capture SHA-256 is
`3ac7531d14360058e3988ba58c44a0c4b178bb4d362f0541595271a677dd3b49`.

The observed global spread P95 is 26 points. Per-hour P95 is 16 points for
UTC 02–22, 26 at UTC 01, 31 at UTC 23, and 67 at UTC 00. These are historical
descriptions, not a promise of future execution. The complete frozen report
is stored locally beside the dataset as
`data/fx/EURUSD/M15/phase5c_cost_report.json`.

The frozen non-spread terms are: explicit zero commission assumption; long
swap debit 8.3 USD/lot/crossing; short swap 0 USD/lot/crossing; and triple
swap Python weekday 2 (Wednesday). Their fingerprint is
`9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36`.
