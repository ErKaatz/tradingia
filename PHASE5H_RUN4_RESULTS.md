# Phase 5H — Run 4 Results

Status: **valid complete historical research run; 0 candidates**.

Run ID: `phase5h_run4_preregistered_failed_breakout`  
Frozen cell: `EURUSD / H1`  
Future test: `NOT ASSIGNED`  
EURUSD/M15: `UNTOUCHED`

## Integrity and safety

Runs 1, 2 and 3 remain `INVALID — PRESERVED` engineering incidents and were not
used for any result, classification, comparison, or design decision.

All frozen gates matched:

- Cost preregistration: `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c`
- Strategy preregistration: `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709`
- Cost profile: `b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7`
- Capture slice: `96025369147c81ce9c10df34b1505f263c3622085100502ec8ff238ecd44912e`
- Raw capture: `099e120c0c92062056961139fd08e207f82d4368caf7e9952a69c59584f1b738`
- Metadata: `9cb69f172b716b878957ecc1ee4267cdf0d3c37d8a613ceca5d88356e6ce3267`

Focused Phase 5H regression gate: `39 passed`.  Post-run full suite:
`736 passed, 8 skipped, 2 warnings`, exit code 0. `git diff --check` passed.

Historical research only: LIVE was disabled; zero orders, zero demo opens/closes,
zero `place_order`, and zero `close_position` calls were made.

## Frozen hypotheses and execution

Exactly two independent hypotheses were observed, with zero substitutions and zero
additions:

1. `daily-range-failed-breakout-long`
2. `daily-range-failed-breakout-short`

The executed stages were Inner Development A, Inner Development B, aggregate
development, then single validation. The control was not a performance variant.

## Results

All values are USD. `DD` is the signed maximum drawdown convention used by the
preregistration. Commission was the frozen `NoCommission` research assumption.

| Stage | Variant | Trades | Gross PnL | Spread | Slippage | Commission | Swap | Total costs | Net PnL | Expectancy | PF | DD | Solvent |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Inner A | LONG | 49 | 61.950 | 8.880 | 0.980 | 0 | 1.079 | 10.939 | 51.011 | 1.041 | 2.611 | -7.685% | Yes |
| Inner A | SHORT | 57 | 3.830 | 10.290 | 1.140 | 0 | 0 | 11.430 | -7.600 | -0.133 | 0.881 | -29.683% | Yes |
| Inner B | LONG | 49 | 0.920 | 8.910 | 0.980 | 0 | 1.411 | 11.301 | -10.381 | -0.212 | 0.705 | -16.069% | Yes |
| Inner B | SHORT | 54 | 13.670 | 11.540 | 1.080 | 0 | 0 | 12.620 | 1.050 | 0.019 | 1.025 | -10.428% | Yes |
| Development | LONG | 99 | 54.850 | 17.950 | 1.980 | 0 | 2.490 | 22.420 | 32.430 | 0.328 | 1.432 | -13.967% | Yes |
| Development | SHORT | 111 | 17.500 | 21.830 | 2.220 | 0 | 0 | 24.050 | -6.550 | -0.059 | 0.939 | -29.683% | Yes |
| Validation | LONG | 51 | -8.700 | 9.340 | 1.020 | 0 | 0.996 | 11.356 | -20.056 | -0.393 | 0.682 | -46.163% | Yes |
| Validation | SHORT | 45 | -2.420 | 8.980 | 0.900 | 0 | 0 | 9.880 | -12.300 | -0.273 | 0.682 | -17.173% | Yes |

The aggregate-development row is intentionally an independently executed frozen
stage; it is not added to Inner A/B when counting unique historical observations.

## Candidate-rule matrix

| Frozen criterion | LONG | SHORT |
|---|---|---|
| Inner A / B / development / validation minimum sample | PASS / PASS / PASS / PASS | PASS / PASS / PASS / PASS |
| Inner A / B / development / validation solvency | PASS / PASS / PASS / PASS | PASS / PASS / PASS / PASS |
| Inner A / B / development / validation positive net PnL | PASS / FAIL / PASS / FAIL | FAIL / PASS / FAIL / FAIL |
| Inner A / B / development / validation positive expectancy | PASS / FAIL / PASS / FAIL | FAIL / PASS / FAIL / FAIL |
| Inner A / B / development / validation PF > 1 | PASS / FAIL / PASS / FAIL | FAIL / PASS / FAIL / FAIL |
| Inner A / B / development / validation DD >= -20% | PASS / PASS / PASS / FAIL | FAIL / PASS / FAIL / PASS |
| Cost efficiency on all required splits | FAIL | FAIL |
| Annual stability and positive-year concentration | FAIL | FAIL |
| Largest positive-trade contribution <= 25% | FAIL | PASS |

Classification: `daily-range-failed-breakout-long = REJECT`; 
`daily-range-failed-breakout-short = REJECT`.

## Mandatory semantic and accounting audit

An independent post-run audit covered all 515 persisted stage-trade rows. It
passed for every row:

- reference range came only from the exact prior UTC calendar date;
- no trade used an unavailable prior date, a Friday fallback, carry-forward, or
  previous observed trading day;
- B0 was strictly outside and B1 was the immediate strict-inside confirmation;
- entry was signal + 1 observed H1 bar; exit was entry + 4 completed H1 bars;
  `bars_held = 4`;
- per-trade accounting reconciled exactly: gross minus spread, slippage,
  commission, and swap equals net PnL.

There were 23 positions whose four H1 bars crossed a market-closed interval, so
their wall-clock duration exceeded four hours. This is descriptive only: the
frozen rule is four completed H1 bars, and no new duration or completeness filter
was introduced.

Partial-day involvement is descriptive only. Across the independently relevant
development and validation results, 4 LONG and 2 SHORT signals occurred on a
partial current UTC date; none used a partial prior-reference date. Exact prior
dates with at least one bar remained eligible as frozen.

Year, month, entry-hour, trade-concentration, and cost-efficiency attributions are
preserved in each `summary.json`; the raw audit trail is each `trades.jsonl`.

## Observability

All eight stage/variant bundles are complete and strict JSON:
`manifest.json`, `summary.json`, and `trades.jsonl` (24 files total). The
classification is in `data/fx/research/results/phase5h_run4_preregistered_failed_breakout/classification.json`.

POST-HOC observations: `NOT TESTED`. No follow-up strategy, time frame, symbol,
filter, or parameter was tested after these results.

## Git

The worktree was already dirty with accumulated unrelated tracked and untracked
work. No global commit and no push were made.

**PHASE 5H RUN 4 COMPLETE — 0 CANDIDATES**
