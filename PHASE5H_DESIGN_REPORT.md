# Phase 5H — Hypothesis Selection Design Report

Status: design only. No strategy performance, backtest, signal generation,
untouched-test read, DEMO operation or LIVE operation was performed.

Phase 5G inputs reviewed directly:

- `PHASE5G_VIABILITY_PREREGISTRATION.md` — fingerprint
  `7bbeab4c4ee8b97aa555b52d13ef8a5b347b6350e3ac46ea1358efd522046e0d`.
- `PHASE5G_VIABILITY_STATUS.md`.
- `PHASE5G_OBSERVABILITY_CONTRACT.md`.
- `PHASE5F_STATUS.md`, `PHASE5E_STATUS.md`, and `RESEARCH_RULES.md`.
- Local machine-readable viability report — fingerprint
  `2ed51e0cf7826cc1d390df7f1e8a1bdc778244be6d57de89ca2361d89254930d`.

## 1. Structural evidence summary

All eligible data is in the already-frozen common window
`2022-09-01T00:00:00Z` through exclusive `2025-08-30T00:00:00Z`. Coverage is
the Phase 5G weekday-slot proxy. Range is native price range. Burden is the
dimensionless ratio after converting spread points to price using the captured
symbol point. The best/worst hourly figures are descriptive extrema only;
they are not proposed trading-hour filters.

| Cell | Coverage / unexpected gaps | Spread points median / P95 | Median range / P95 | Median / P95 burden | Hourly burden best → worst | Metadata / label |
| --- | --- | --- | --- | --- | --- | --- |
| EURUSD/H1 | 0.9923 / 6 | 15 / 20.85 | 0.0011300 / 0.0034500 | 0.1327 / 0.1845 | 0.0619 at 17 UTC → 0.4677 at 00 UTC | point 0.00001; complete / VIABLE |
| EURUSD/M15 | 0.9915 / 27 | 15 / 25 | 0.0005500 / 0.0016800 | 0.2727 / 0.4545 | 0.1327 at 17 UTC → 1.2143 at 00 UTC | point 0.00001; complete / BORDERLINE |
| GBPUSD/H1 | 0.9923 / 6 | 16 / 25 | 0.0014500 / 0.0043800 | 0.1103 / 0.1724 | 0.0559 at 17 UTC → 0.4393 at 00 UTC | point 0.00001; complete / VIABLE |
| GBPUSD/M15 | 0.9912 / 45 | 17 / 27 | 0.0007100 / 0.0021300 | 0.2394 / 0.3803 | 0.1143 at 17 UTC → 1.3659 at 00 UTC | point 0.00001; complete / VIABLE |
| USDJPY/H1 | 0.9923 / 6 | 19 / 26 | 0.20300 / 0.58600 | 0.0936 / 0.1281 | 0.0541 at 15 UTC → 0.3838 at 00 UTC | point 0.001; complete / VIABLE |
| USDJPY/M15 | 0.9914 / 34 | 19 / 30 | 0.09800 / 0.28400 | 0.1939 / 0.3061 | 0.1173 at 17 UTC → 1.1395 at 00 UTC | point 0.001; complete / VIABLE |

M5 is not included: all three M5 cells are `INSUFFICIENT_DATA`, with actual
availability beginning only in May 2025. No missing bar is repaired and no
metadata conversion is guessed.

## 2. Primary cell

**PRIMARY: EURUSD/H1.**

It is selected solely as a controlled, structurally viable next research
environment: coverage is 0.9923, there are six unexpected gaps, the median
spread/range burden is 0.1327, P95-spread/median-range burden is 0.1845, and
symbol metadata is complete (5 digits, point/tick size 0.00001). It preserves
EURUSD while changing one dimension from the prior EURUSD/M15 research:
timeframe. This is simpler to interpret than changing both symbol and
timeframe. It is not selected as a market "winner" and it is not a claim of
profitability.

## 3. Secondary cell

**SECONDARY: NONE.**

The available hypothesis budget should not be divided before the new
cell-specific cost calibration and an independent mechanism are established.
Adding a second cell would change a second research environment without a
need established by the present structural evidence.

## 4. Deferred cells

- EURUSD/M15 is deferred: it is `BORDERLINE`, and its burden is materially
  higher (0.2727 median; 0.4545 P95) than EURUSD/H1. Its reserved untouched
  test remains unavailable.
- GBPUSD/M15, GBPUSD/H1, USDJPY/M15 and USDJPY/H1 are deferred, not rejected.
  They are structurally viable, but using one of them now would change symbol
  and/or add a parallel research branch unnecessarily.
- All M5 cells are deferred as `INSUFFICIENT_DATA`, not structurally judged.

## 5. Proposed mechanisms

At most one mechanism family is proposed for the first Phase 5H
preregistration:

**Completed daily-range failed breakout on EURUSD/H1.** A completed prior UTC
daily range supplies fixed, knowable levels. The hypothesis is that an H1 bar
which first closes outside that completed range but subsequently closes back
inside indicates a failed expansion/absorption event, which may permit a
short, fixed-horizon reversion toward the interior. This is event-driven and
low-frequency by construction. It is not the Phase 5E standardized impulse
reversal: its reference is a completed daily range and a two-stage
outside-then-inside sequence, rather than a rolling standardized return.

No other mechanism is proposed. In particular, no EMA, z-score, momentum,
session breakout/range, compression-expansion, standardized impulse, or their
parameter variants will be transplanted from Phase 5D/5E.

## 6. Recommended hypothesis budget

**Two variants total, one family:**

1. `daily-range-failed-breakout-long` — re-entry from a downside break.
2. `daily-range-failed-breakout-short` — re-entry from an upside break.

They are the two directional instances of one predeclared economic mechanism,
not a search over sides. `control-flat` may be retained only as a descriptive
control and does not consume hypothesis budget.

## 7. Degrees of freedom to freeze before any run

The eventual preregistration must freeze every one of these without inspecting
strategy performance:

- cell: EURUSD/H1 only;
- prior range: the immediately preceding completed UTC calendar day only;
- break event: one H1 close strictly beyond that range boundary;
- failure confirmation: the next eligible H1 close strictly back inside that
  same completed range; no intrabar inference;
- direction mapping: downside failure → long; upside failure → short;
- entry: next-bar execution after confirmation;
- fixed holding period: exactly 4 H1 bars;
- one event / one position; ignore overlapping events while a position exists;
- mandatory flat handling at the frozen daily/session boundary, if retained;
- 0.01 lot, USD 100 initial balance, insolvency policy and non-spread cost
  terms only after their EURUSD/H1 calibration is frozen;
- no stop, target, trailing exit, hour/weekday/month filter, volatility filter,
  side selection, dynamic sizing, parameter sweep or discretionary exception.

The fixed 4-bar horizon is a design proposal, not a tuned value; it must be
frozen or replaced once, before any signal/performance calculation.

## 8. Expected turnover

**Low.** The mechanism requires a prior completed daily range plus a two-stage
break-and-re-entry event, and holds at most one position for a fixed four H1
bars. This follows Phase 5F's descriptive warning against permanently exposed
or high-turnover cost-dominated families; it does not filter historical hours,
sides or periods based on PnL.

## 9. Cost-calibration prerequisites

**A fresh EURUSD/H1 calibration is mandatory before strategy research.** The
EURUSD/M15 Phase 5C cost profile cannot be reused. The prerequisite must
capture and freeze:

- an EURUSD/H1-specific spread profile and fingerprint from the selected
  pre-performance dataset;
- exact point, tick size, tick value, contract-size and volume metadata;
- commission assumption and fingerprint;
- swap long/short terms, rollover convention and fingerprint;
- adverse slippage assumption and next-bar execution convention;
- the complete cost-calibration artifact and its dataset fingerprint.

No Phase 5H strategy may run until this is separately preregistered, captured
read-only, validated and frozen.

## 10. Proposed temporal research policy

All dates are within the consumed Phase 5G common window. No date at or after
`2025-08-30T00:00:00Z` is declared a test for EURUSD/H1.

| Split | Start | End exclusive | Purpose |
| --- | --- | --- | --- |
| Inner development A | 2022-09-01 | 2023-09-01 | implementation and first independent development check |
| Inner development B | 2023-09-01 | 2024-09-01 | second independent development check |
| Aggregate development | 2022-09-01 | 2024-09-01 | fixed aggregation only |
| Single validation | 2024-09-01 | 2025-08-30 | one validation application |
| Future test | not assigned | not assigned | requires separately available and frozen data |

The split boundary and warm-up rules must be explicit in the preregistration.
No strategy output is calculated as part of this design.

## 11. Observability integration

Any future run must use the Phase 5G contract: `manifest.json`, `summary.json`
and `trades.jsonl`. Each trade must persist identity, UTC signal/entry/exit,
side, lots, reference/bid/ask/execution prices, gross/spread/slippage/
commission/swap/net decomposition, duration, bars held and insolvency context.
The accounting identity and strict JSON requirements remain fail-closed.

## 12. Multiple-testing implications

The ledger must contain exactly this one family and exactly two directional
variants, plus a non-hypothesis flat control if used. It must state that prior
Phase 5D/5E variants are not reused and that no new variant, parameter,
filter, symbol, timeframe or split may be added after preregistration. Any
follow-up from either directional variant requires a new independently
preregistered budget and must not consume the existing EURUSD/M15 untouched
test.

## 13. Main risks

- The proposed event may be too rare for the minimum-trade requirement.
- A failed breakout can still be a trend continuation; no stop/target tuning
  is authorized to rescue it.
- EURUSD/H1's aggregate burden is favorable, but hourly burden varies; the
  report's 00 UTC observation cannot be converted into an hour exclusion.
- H1 spread data is an OHLC-bar proxy, not transaction-level executable
  microstructure.
- A new H1 cost calibration can invalidate this design's feasibility before
  any strategy is run.
- The construction is untested; structural viability does not imply edge.

## 14. Recommendation

**READY TO PREREGISTER PHASE 5H**

Only after the separate EURUSD/H1 cost-calibration prerequisite is designed
and frozen. This report itself authorizes neither a preregistration nor a
performance run.
