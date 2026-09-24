# Phase 5E — Preregistered event-strategy evaluation status

## Integrity

Run ID: `phase5e_run1_preregistered_events`. The four permitted stages ran in
order: inner A, inner B, aggregate development, then exactly one complete
validation batch. Every stage contains the same eight hypotheses and the flat
control. No parameters, variants, costs, sizing, window, splits, or candidate
rules changed between stages. No Phase 5D artifact was overwritten.

## Fingerprints

| Input | SHA-256 |
|---|---|
| Research EURUSD/M15 dataset | `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59` |
| Phase 5C spread profile | `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575` |
| Phase 5C non-spread profile | `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36` |
| Phase 5E preregistration | `b5359b37c865ecf72666a62aee4d3849b8386ea5eb1b4c4df0d43fb9bf7dcd10` |

All result JSON artifacts record these fingerprints and commit
`5685f46`, and are stored separately under
`data/fx/research/results/phase5e_run1_preregistered_events/`.

## Variant set

The observed budget is exactly eight hypotheses: compression/expansion (2),
session range (2), expansion reversal (2), and impulse continuation (2), plus
descriptive `control-flat`. There were zero substitutions and zero additions.

## Inner Development A

| Variant | Trades | Net PnL | Insolvent |
|---|---:|---:|---|
| compression-expansion-16-4 | 5 | 1.10 | no |
| compression-expansion-24-6 | 1 | -0.49 | no |
| session-range-01-08 | 240 | -52.91 | no |
| session-range-02-09 | 243 | -58.18 | no |
| expansion-reversal-32-2p5-2 | 743 | -99.00 | yes |
| expansion-reversal-48-2p25-4 | 983 | -84.20 | no |
| impulse-continuation-32-2p5-2 | 406 | -99.29 | yes |
| impulse-continuation-48-2p25-4 | 282 | -98.83 | yes |
| control-flat | 0 | 0 | no |

## Inner Development B

| Variant | Trades | Net PnL | Insolvent |
|---|---:|---:|---|
| compression-expansion-16-4 | 3 | -0.42 | no |
| compression-expansion-24-6 | 1 | -0.62 | no |
| session-range-01-08 | 231 | -55.19 | no |
| session-range-02-09 | 240 | -98.67 | no |
| expansion-reversal-32-2p5-2 | 707 | -99.46 | yes |
| expansion-reversal-48-2p25-4 | 705 | -99.13 | yes |
| impulse-continuation-32-2p5-2 | 435 | -99.71 | yes |
| impulse-continuation-48-2p25-4 | 495 | -98.05 | yes |
| control-flat | 0 | 0 | no |

## Aggregate development and validation

| Variant | Dev trades / PnL / insolvency | Validation trades / PnL / insolvency | Classification |
|---|---:|---:|---|
| compression-expansion-16-4 | 8 / 0.68 / no | 2 / -0.31 / no | REJECT |
| compression-expansion-24-6 | 2 / -1.11 / no | 1 / -1.44 / no | REJECT |
| session-range-01-08 | 422 / -99.71 / yes | 220 / -36.47 / no | REJECT |
| session-range-02-09 | 340 / -99.71 / yes | 225 / 2.75 / no | REJECT |
| expansion-reversal-32-2p5-2 | 743 / -99.00 / yes | 702 / -96.85 / yes | REJECT |
| expansion-reversal-48-2p25-4 | 1017 / -97.42 / yes | 660 / -95.90 / yes | REJECT |
| impulse-continuation-32-2p5-2 | 406 / -99.29 / yes | 389 / -99.33 / yes | REJECT |
| impulse-continuation-48-2p25-4 | 282 / -98.83 / yes | 464 / -97.55 / yes | REJECT |
| control-flat | 0 / 0 / no | 0 / 0 / no | CONTROL |

## Cost decomposition

The full per-split decomposition is in each machine-readable artifact. Every
one of 36 artifacts passed the identity:

`net_pnl = gross_reference_pnl - spread_cost - slippage_cost - commission_cost - swap_cost`.

Aggregate development / validation: gross reference PnL, total costs, net PnL:

| Variant | Development | Validation |
|---|---:|---:|
| compression-expansion-16-4 | 2.32 / 1.64 / 0.68 | 0.25 / 0.56 / -0.31 |
| compression-expansion-24-6 | -0.65 / 0.46 / -1.11 | -1.16 / 0.28 / -1.44 |
| session-range-01-08 | -23.75 / 75.96 / -99.71 | 3.13 / 39.60 / -36.47 |
| session-range-02-09 | -38.51 / 61.20 / -99.71 | 43.25 / 40.50 / 2.75 |
| expansion-reversal-32-2p5-2 | 35.24 / 134.24 / -99.00 | 30.51 / 127.36 / -96.85 |
| expansion-reversal-48-2p25-4 | 85.74 / 183.16 / -97.42 | 23.40 / 119.30 / -95.90 |
| impulse-continuation-32-2p5-2 | -25.71 / 73.58 / -99.29 | -28.81 / 70.52 / -99.33 |
| impulse-continuation-48-2p25-4 | -47.77 / 51.06 / -98.83 | -13.83 / 83.72 / -97.55 |

## Insolvency, concentration, and yearly records

All impulse-continuation variants were insolvent in every evaluation. Both
reversal variants were insolvent in aggregate development and validation;
reversal 32 was insolvent in both inner splits and reversal 48 in inner B.
Both session variants were insolvent in aggregate development. Insolvency is a
formal automatic rejection, with no post-terminal metrics fabricated.

Each artifact includes yearly trade count, net PnL, expectancy and PF, largest
positive-trade contribution, top-five contribution, and annual inputs used for
the frozen concentration rule. No strategy reached candidate review because
each already failed an earlier fixed rule (sample, PnL, insolvency, costs, or
inner consistency); no concentration exception was introduced.

## Candidate-rule matrix

| Variant | Binding failures | Final |
|---|---|---|
| compression-expansion-16-4 | insufficient trades; inner B and validation PnL negative | REJECT |
| compression-expansion-24-6 | insufficient trades; negative PnL | REJECT |
| session-range-01-08 | negative PnL; aggregate insolvency; cost efficiency fails | REJECT |
| session-range-02-09 | inner PnL negative; aggregate insolvency; cost efficiency fails | REJECT |
| expansion-reversal-32-2p5-2 | insolvency; negative PnL; cost efficiency fails | REJECT |
| expansion-reversal-48-2p25-4 | aggregate/validation insolvency; negative PnL; cost efficiency fails | REJECT |
| impulse-continuation-32-2p5-2 | insolvency; negative PnL; non-positive gross reference PnL | REJECT |
| impulse-continuation-48-2p25-4 | insolvency; negative PnL; non-positive gross reference PnL | REJECT |
| control-flat | descriptive control; zero trades/PnL | CONTROL |

## Final classifications and multiple testing

**0 CANDIDATES.** Eight hypotheses observed, zero substitutions, zero added
variants. No test execution is authorized from this result.

## POST-HOC OBSERVATIONS — NOT TESTED

- The two compression variants generated too few events for the frozen sample
  criterion.
- Event families with many trades incurred costs larger than their gross
  reference PnL in the reported failing cases.
- These observations are descriptive only; no filter, parameter, variant, or
  follow-up experiment was run from them.

## Untouched test

UNTOUCHED

## Closure gate

**PASSED.** The apparent hang was a Codex filesystem/network sandbox runtime
limitation, not a FastAPI, Starlette, httpx, AnyIO, bridge, or pytest defect.
The isolated `anyio.from_thread.start_blocking_portal()` program entered its
context but could not complete portal-thread teardown when run inside that
sandbox. The same minimal program exited normally outside the sandbox using
the original declared environment: FastAPI 0.141.1, Starlette 1.6.0, httpx
0.28.1, AnyIO 4.15.0, and pytest 9.1.1.

The full suite was therefore executed outside the sandbox in that unchanged
environment: `.venv/bin/python -m pytest -q` → **696 passed, 8 skipped in
7.44s**, exit code 0 (wall-clock `real` 7.965s). No test was skipped, marked
xfail, removed, or masked to obtain this result. The previously hidden
test-only `NameError` in the 502 mapping regression was corrected by importing
`MT5BackendError`.

The Phase 5E research artifacts were not rerun or changed. Research semantics
affected: **NO**.

Phase 5E is formally closed: eight preregistered hypotheses were observed,
all eight are `REJECT`, and zero candidates may advance to test.
