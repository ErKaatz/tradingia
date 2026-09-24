# Phase 5H — Consolidated History and Current Status

Status date: 2026-09-08. Frozen cell: `EURUSD / H1`.

## Current verdict

There are no valid Phase 5H research-performance results and no candidates.
All three historical attempts are preserved technical incidents and must not
be used for PnL, metrics, attribution, candidate classification, hypothesis
design, or performance comparison.

| Run | ID | Status | Primary reason |
| --- | --- | --- | --- |
| 1 | `phase5h_run1_preregistered_failed_breakout` | `INVALID — PRESERVED` | Semantic holding failure |
| 2 | `phase5h_run2_preregistered_failed_breakout` | `INVALID — PRESERVED` | End-of-data target-length failure |
| 3 | `phase5h_run3_preregistered_failed_breakout` | `INVALID — PRESERVED` | Prior-UTC-day semantic failure |

No Run 4 is defined or authorized. The future test is `NOT ASSIGNED` and
EURUSD/M15 is `UNTOUCHED`.

## Frozen design

The preregistration documents were never changed: `PHASE5H_COST_PREREGISTRATION.md`
and `PHASE5H_PREREGISTRATION.md`.

Exactly two independently classified hypotheses are frozen:

1. `daily-range-failed-breakout-long`
2. `daily-range-failed-breakout-short`

`control-flat` is descriptive only. Account policy is USD 100, fixed 0.01
lot, maximum one position, insolvency at equity <= 0. Entry is next-bar open
after B1 confirmation. Holding is B2–B5, with exit at B6 open and
`bars_held == 4`.

LONG requires B0 strictly below and B1 strictly inside the previous completed
UTC-day range. SHORT is symmetric above/inside. Equality and delayed
confirmation are rejected.

## Frozen integrity evidence

Self-fingerprinted preregistrations use the verified generation-order rule:
SHA-256 of exact UTF-8 bytes with the one self-field replaced by
`TO_BE_FILLED_BY_FREEZE_TOOL`, then embedding that hash.

| Artifact | Frozen SHA-256 |
| --- | --- |
| Cost preregistration | `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c` |
| Strategy preregistration | `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709` |
| Cost profile | `b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7` |
| Capture slice | `96025369147c81ce9c10df34b1505f263c3622085100502ec8ff238ecd44912e` |
| Raw capture | `099e120c0c92062056961139fd08e207f82d4368caf7e9952a69c59584f1b738` |
| Metadata | `9cb69f172b716b878957ecc1ee4267cdf0d3c37d8a613ceca5d88356e6ce3267` |

Hourly P95 spread: UTC 00=55 points, UTC 01–21=16, UTC 22=17, UTC 23=50.
Commission is NoCommission research assumption; slippage is one adverse point
per fill; long swap is 8.3 USD/lot/rollover and short swap is 0.

## Run 1

Run 1 found a holding-semantic failure. A validation SHORT event had B0 at
2025-08-29 17:00 UTC, B1 signal at 18:00, correct entry at 19:00, but an
incorrect exit at 20:00 with `bars_held=1`; B6 was 23:00.

Cause: tail cleanup individually removed later targets while retaining the
first of a valid four-target event. The engine therefore exited early. The
repair applies an all-or-nothing event-block rule. See
`PHASE5H_SEMANTIC_REMEDIATION.md`.

## Run 2

Run 2 found an end-of-data length failure: bars length = 6186, signals length
= 6189. The conceptual Python operation `targets[start:start + 4] = [FLAT] *
4` can extend a list when the tail slice is shorter than four positions.

The repair mutates only existing indexes and enforces raw-target and
cleaned-target equality with bars before every engine call. It also requires
every retained block to have four same-side targets, a following FLAT, and B6.
See `PHASE5H_TAIL_LENGTH_REMEDIATION.md`.

## Run 3

Run 3 passed input, target-length, and regression gates, and emitted bundles
for both variants in all four frozen stages. A post-run B0/B1 audit then found
a frozen-semantics violation:

`development_inner_a / daily-range-failed-breakout-long`, signal
`2022-09-26T01:00:00+00:00`.

UTC Sunday 2022-09-25 had no captured bars. The strategy carried Friday's
range into Monday, which does not satisfy the literal frozen rule requiring
the immediately preceding completed UTC calendar day. Consequently all Run 3
artifacts, including `classification.json`, are invalid and must not be used
as research performance.

Each run directory contains an immutable `INVALID_RUN.md` marker.

## Safety and verification

LIVE and DEMO were not used: zero orders, demo opens, demo closes,
`place_order`, and `close_position`. EURUSD/M15 remains `UNTOUCHED`; the
future test remains `NOT ASSIGNED`.

Current test evidence: focused Phase 5H tests `35 passed`; full suite
`732 passed, 8 skipped, 2 warnings`, exit code 0; `git diff --check` passed.

No commit and no push were made. The worktree was already dirty with
accumulated unrelated changes, so no global commit was appropriate.

## Required decision before another run

Before any new performance attempt, the weekend-gap semantic issue must be
resolved prospectively: either Monday events require a fully observed Sunday
UTC range and are unavailable, or the preregistration must formally allow the
last fully observed trading-day range. The current wording does not justify
silently treating Friday as Monday's prior UTC day.

`PHASE 5H — NO VALID PERFORMANCE RESULT; REMEDIATION DECISION REQUIRED`
