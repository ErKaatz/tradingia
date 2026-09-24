# TradingIA — Phase 5D consolidated summary

Date: 2026-09-07. Scope: FX-first / MT5-first research only. LIVE remains
disabled; no orders were sent during this work.

## Verified foundations

- Current branch: `master`.
- Crypto is historical and preserved at tag `crypto-research-final`.
- Phase 5A data layer is available and Phase 5B provides causal next-bar
  LONG/SHORT execution, bid/ask fills, fixed lots, spread, slippage,
  commission, swap, and auditable PnL.
- Phase 5B's real-MT5 EURUSD profit oracle matched the local PnL calculation
  for LONG/SHORT gains and losses.
- Generic metrics consume neutral result types through the FX adapter rather
  than the historical crypto engine.

## Phase 5C frozen cost profile

Cost calibration source: EURUSD M15, HFM MT5 Demo Premium, history
`2026-08-03T00:00:00Z` through `2026-09-07T14:30:00Z`.

- 2,459 bars; no validation warnings.
- Dataset SHA-256:
  `0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9`.
- Raw-capture SHA-256:
  `3ac7531d14360058e3988ba58c44a0c4b178bb4d362f0541595271a677dd3b49`.
- Hourly spread-P95 profile: UTC 00=`67`, 01=`26`, 02–22=`16`, 23=`31`
  points. These are historical cost-calibration values, not future execution
  guarantees.
- Commission: explicit `NoCommission` research assumption.
- Swap: long debit `8.3 USD/lot/rollover`; short `0`; triple-swap Wednesday
  (Python weekday `2`).
- Non-spread cost fingerprint:
  `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36`.

Complete local artifact:
`data/fx/EURUSD/M15/phase5c_cost_report.json`.

## Data-availability audit and repair

The first availability scan found that a request before terminal history could
return MT5's oldest cached bar outside the requested range. The bridge now
defensively filters `copy_rates_range` output to its requested inclusive time
range. It was deployed and verified on the Windows VM: a 2018 request returns
zero bars, while an in-range 2022 request returns only in-range bars.

Available research history, selected without strategy-performance inspection:

- EURUSD M15, `2022-09-01T00:00:00Z` through
  `2026-09-04T23:45:00Z`.
- 99,597 bars.
- Dataset SHA-256:
  `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59`.
- 99,355 contiguous transitions, 206 expected-weekend transitions, and 35
  unexpected gaps. No gap was filled, interpolated, or excluded.

The local research dataset and availability report are stored under
`data/fx/research/EURUSD/M15/` and remain gitignored.

## Phase 5D preregistered baseline batch

No development, validation, or test performance has been calculated yet.

- Development: 2022-09-01 through 2024-08-30.
- Validation: 2024-09-02 through 2025-08-29.
- Untouched test: 2025-09-01 through 2026-09-04; it must remain unexecuted
  during Phase 5D.
- Fixed sizing: 0.01 lot and 100 USD initial balance.
- Execution: signal at close, engine execution next-bar open.
- Frozen hourly P95 spread profile; explicit non-spread terms; one adverse
  slippage point per fill as a preregistered conservative assumption.
- Positions target flat from 20:00 through 00:45 UTC to avoid an unverified
  rollover-hour/DST model; this is operational and preregistered, not
  performance-driven.
- Variants: two EMA trends, two z-score mean-reversion, two momentum, two
  numerical-UTC session breakouts, plus flat/long/short controls.
- Candidate rules require both development and validation to satisfy minimum
  trade count, positive PnL/expectancy, profit factor above one, drawdown,
  long/short balance, and concentration limits. Controls cannot be candidates.

Exact parameters and acceptance rules are in `PHASE5D_PREREGISTRATION.md`;
every intended observation is listed in `PHASE5D_MULTIPLE_TESTING_LEDGER.md`.

## Current implementation and tests

- `src/fx/strategies/baselines.py` supplies the preregistered causal signal
  families and enforces the common active window.
- `src/fx/cost_calibration.py` can apply the frozen hourly P95 profile without
  mutating captured data and refuses insufficient buckets.
- Truncation-invariance tests for the baseline signals and Phase 5C tests
  passed: `10 passed`.
- The Phase 5C plus FX-backtesting targeted suite previously passed:
  `41 passed`.
- The full `.venv/bin/pytest -q` run did not complete through the current
  terminal session, so it is not claimed as green; this remains a required
  final gate before closing Phase 5D.

## Next action

Implement the research runner, run the complete preregistered batch only on
development and validation, persist all results (including failures) in the
ledger/status, and leave the untouched test unobserved.
