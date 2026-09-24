# Phase 5H — Complete Status Summary

Status date: 2026-09-08  
Scope: EURUSD / H1 only

## Executive status

Phase 5H has not produced valid research performance results yet.

Run 1 (`phase5h_run1_preregistered_failed_breakout`) was stopped by the
semantic validator and is permanently classified:

```text
INVALID — SEMANTIC VALIDATION FAILURE
```

The implementation error has been reproduced, corrected, and regression
tested. A separate future identifier is reserved for a new run:

```text
phase5h_run2_preregistered_failed_breakout
```

Run 2 is **NOT RUN** and requires a new explicit authorization. No candidate
classification exists. The Phase 5H future test remains **NOT ASSIGNED**.

## Frozen study design

| Item | Frozen value |
| --- | --- |
| Symbol / timeframe | EURUSD / H1 |
| Hypotheses | `daily-range-failed-breakout-long`; `daily-range-failed-breakout-short` |
| Control | `control-flat`, descriptive only; not a hypothesis |
| Account | USD 100 initial balance; fixed 0.01 lot; maximum one position |
| Entry | next H1 bar open after confirmation close |
| Holding | exactly 4 completed H1 bars |
| Insolvency | terminate at equity <= 0 |
| Commission | NoCommission research assumption |
| Slippage | 1 adverse point per fill |
| Swap long / short | 8.3 USD/lot/rollover debit / 0 |
| Triple rollover | Wednesday (MT5 day 3) |
| Hour filter | none; UTC 00 remains eligible |

### Event semantics

The range is the high/low of the previous fully completed UTC calendar day.

- LONG: B0 closes strictly below the prior-day low; only B1, the immediately
  next eligible H1 close, may confirm by closing strictly inside the prior-day
  range.
- SHORT: symmetric, with B0 strictly above the prior-day high and B1 strictly
  inside the range.
- Equality is not inside. A failed immediate confirmation, a day-boundary
  expiry, missing required bars, or an existing open position produces no
  trade.

## Frozen temporal stages

| Stage | Start | End exclusive |
| --- | --- | --- |
| Inner development A | 2022-09-01 | 2023-09-01 |
| Inner development B | 2023-09-01 | 2024-09-01 |
| Aggregate development | 2022-09-01 | 2024-09-01 |
| Validation | 2024-09-01 | 2025-08-30 |
| Future test | NOT ASSIGNED | NOT ASSIGNED |

Minimum samples are 8 trades in each inner-development split and validation,
and 20 trades in aggregate development, independently per directional
hypothesis.

## Fingerprint and cost integrity

The preregistrations use the established generation-order convention:
calculate SHA-256 over exact UTF-8 document bytes while its sole embedded
self-fingerprint field contains `TO_BE_FILLED_BY_FREEZE_TOOL`; then replace
the placeholder with that hash. The shared verifier confirms this exact
representation.

| Artifact | Verified fingerprint |
| --- | --- |
| Cost preregistration | `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c` |
| Strategy preregistration | `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709` |
| Cost profile | `b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7` |
| Cost capture slice | `96025369147c81ce9c10df34b1505f263c3622085100502ec8ff238ecd44912e` |
| Raw capture | `099e120c0c92062056961139fd08e207f82d4368caf7e9952a69c59584f1b738` |
| Metadata | `9cb69f172b716b878957ecc1ee4267cdf0d3c37d8a613ceca5d88356e6ce3267` |

The frozen hourly P95 spread profile is 55 points at UTC 00, 16 at UTC
01–21, 17 at UTC 22, and 50 at UTC 23. The calibration capture covers
2025-03-03 00:00 through 2025-08-29 23:00 UTC, with 3,117 H1 bars.

## Run 1 incident

Run 1 passed its input integrity gate, then stopped when the semantic
validator found a non-four-bar trade. Partial artifacts were preserved, but
must never be used for performance metrics, attribution, classification, or
candidate selection:

`data/fx/research/results/phase5h_run1_preregistered_failed_breakout/`

The invalid marker is stored at:

`data/fx/research/results/phase5h_run1_preregistered_failed_breakout/INVALID_RUN.md`

### First failing trace

| Field | Value |
| --- | --- |
| Split / variant | Validation / `daily-range-failed-breakout-short` |
| B0 break | index 6179, 2025-08-29 17:00 UTC |
| B1 confirmation / signal | index 6180, 2025-08-29 18:00 UTC |
| Required entry B2 | index 6181, 19:00 UTC |
| Actual entry | index 6181, 19:00 UTC |
| Required exit B6 | index 6185, 23:00 UTC |
| Actual exit before remediation | index 6182, 20:00 UTC |
| Actual `bars_held` | 1 |
| Required `bars_held` | 4 |

No PnL findings from this partial run are research evidence.

## Root cause and remediation

Primary classification:

```text
HOLD_COUNTER_OFF_BY_ONE
```

The generic FX engine was correct: a target known at close index `i` is
applied at open index `i + 1`. For a Phase 5H signal index `s`, the intended
relationship is:

| Event | Index |
| --- | ---: |
| B0 break | `s - 1` |
| B1 confirmation / signal | `s` |
| B2 entry | `s + 1` |
| Held bars B2–B5 | `s + 1` through `s + 4` |
| B6 exit | `s + 5` |

The fault was in the runner's end-of-data helper. It assessed every non-flat
target independently. Near the data boundary it retained the first target of
a four-target event but erased later targets, causing the engine to enter and
then close after one bar. This made actual execution wrong, not only the
recorded metadata.

The minimal correction evaluates only the first target of an event block:
it keeps the entire four-target block when B6 exists, otherwise removes the
entire incomplete event. No research semantics, costs, splits, candidate
rules, or preregistration documents changed.

Detailed remediation record: `PHASE5H_SEMANTIC_REMEDIATION.md`.

## Test evidence after remediation

Targeted semantic and engine tests:

```text
22 passed
```

They cover LONG and SHORT signal-to-entry-to-exit mapping, four-bar holds,
the exact Run 1 tail-mask failure, delayed confirmation, strict boundaries,
UTC expiry, existing-position event suppression, end-of-data protection, and
the generic engine's next-bar execution contract.

Full suite:

```text
719 passed, 8 skipped, 2 warnings
exit code 0
```

`git diff --check` passed.

## Safety and protections

```text
LIVE disabled
zero orders
zero demo-open
zero demo-close
zero place_order
zero close_position
EURUSD/M15 UNTOUCHED
Phase 5H future test NOT ASSIGNED
Run 1 INVALID — PRESERVED
Run 2 NOT RUN
Historical performance NOT RUN AFTER REMEDIATION
```

No commit or push was made. The repository has accumulated unrelated dirty
changes, so Phase 5H work was not globally committed.

## Next permitted action

The semantic gate is remediated. The only appropriate next research action is
an explicitly authorized Phase 5H Run 2 using the reserved new run ID and the
same frozen preregistration, cost inputs, hypotheses, and stage order. Until
then, no new historical performance should be executed.

```text
PHASE 5H SEMANTIC GATE REMEDIATED — READY TO AUTHORIZE RUN 2
```
