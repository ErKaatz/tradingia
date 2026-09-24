# Phase 5J — USDJPY/H1 Hypothesis Design

Status: **CLOSED — DESIGN ONLY — NOT READY TO PREREGISTER**.

No historical strategy performance was run and no historical signals were
generated in this phase. This document is a decision record, not a strategy
preregistration.

## 1. Phase 5I handoff

Phase 5I selected `USDJPY/H1` as the sole next research cell on structural,
non-performance evidence. EURUSD/M15 remains `UNTOUCHED`; the Phase 5H future
test remains `NOT ASSIGNED`; no USDJPY/H1 strategy-test interval has been
consumed.

## 2. USDJPY/H1 structural context

The Phase 5G availability-only window is `2022-09-01T00:00:00Z` through
exclusive `2025-08-30T00:00:00Z`. It was structurally observed for data
quality and microstructure, not for strategy performance.

| Property | USDJPY/H1 evidence |
| --- | --- |
| Available range | 2022-09-01 00:00 through 2025-08-29 23:00 UTC |
| Bars / coverage | 18,624 / 99.2327% of 18,768 weekday slots |
| Gaps | 6 unexpected; 153 expected weekends; unrepaired |
| Metadata quality | 0 errors; 1 gap warning; metadata fingerprint `8d7f8c…196bd` |
| Median / P95 spread | 19 / 26 broker points |
| Median / P95 bar range | .20300 / .58600 price units |
| Median / P95 spread-to-median-range burden | 9.36% / 12.81% |
| Hourly median burden | best 15 UTC: 5.41%; worst 00 UTC: 38.38% |

The broker point, tick size, tick value, contract size, commission, swaps,
triple rollover and execution assumptions require a USDJPY/H1-specific cost
calibration before any performance. No EURUSD cost profile can be reused.

## 3. Constraints inherited from prior failures

The family must not recycle or adapt EMA trend/crossover, mean-z, rolling
z-score reversion, simple momentum, session breakout/range, compression-
expansion, standardized expansion reversal, impulse continuation, or
daily-range failed breakout. A different symbol, threshold, hold, session, or
side would not make any of those families new.

The permissible negative design lessons are: avoid permanent exposure, high
turnover, weak gross edge relative to costs, broad parameter freedom, and
unobservable intrabar inference. No favorable hour, side, weekday, or isolated
split result from prior phases is used here.

## 4. Conceptual mechanisms considered

### A — Scheduled policy-rate differential repricing

**Economic rationale:** USDJPY prices the relative value of USD and JPY. A
scheduled, official Fed or Bank of Japan rate decision that changes the stated
policy-rate differential is new public information about the short-rate
component of that relative value. The intended effect is the post-release
absorption of an observed, signed differential change—not a chart breakout.

**USDJPY/H1 fit:** H1 permits timestamped event handling without intrabar
assumptions; the low structural burden supports sparse entries. **Independence:**
the input is a dated official policy action, rather than price momentum,
rolling statistics, session range, expansion, or a prior-day range. **Expected
turnover:** LOW. **Degrees of freedom:** moderate but auditable. **Main
falsification risk:** official target-rate changes may be too rare, or the
post-event price response may be negative, cost-destroyed, unstable, or
concentrated.

### B — Official intervention-regime transition

**Economic rationale:** explicit, timestamped official FX-intervention
operations or confirmations can alter the supply/demand regime for JPY. The
possible effect would be a short-lived adjustment following verified public
official information.

**USDJPY/H1 fit:** USDJPY is an obvious intervention-relevant pair. **Independence:**
it is event-source driven, not a technical signal family. **Expected turnover:**
VERY LOW. **Degrees of freedom:** high, because primary-source confirmation,
timestamp, event taxonomy and action direction all need objective definitions.
**Main falsification risk:** event scarcity and ambiguous or delayed public
confirmation make causal, complete event data difficult to establish.

### C — Scheduled policy-communication regime signal

**Economic rationale:** a predefined classification of official monetary-policy
communication could alter expected relative policy paths even when the stated
rate is unchanged.

**USDJPY/H1 fit:** the pair is economically sensitive to relative policy
expectations. **Independence:** it is fundamental-event driven. **Expected
turnover:** LOW. **Degrees of freedom:** unacceptably high without a
pre-existing, independently timestamped and coded source. **Main falsification
risk:** subjective language classification would create discretion and
post-hoc tuning risk.

## 5. Mechanism comparison matrix

| Criterion | A: rate differential repricing | B: intervention transition | C: communication regime |
| --- | --- | --- | --- |
| Independent from old families | Yes | Yes | Yes |
| Economic rationale | Strong, direct | Plausible, episodic | Plausible, indirect |
| Low degrees of freedom | Moderate | No | No |
| Expected turnover | Low | Very low | Low |
| Cost compatibility | Favorable in principle; must calibrate | Favorable in principle; must calibrate | Favorable in principle; must calibrate |
| Causal implementation | Yes, with official timestamps | Conditional on complete source | Conditional on external coding source |
| Ease of falsification | High | Moderate | Low |
| Post-hoc tuning risk | Lowest of the three | High | High |

## 6. Selected mechanism family

**SELECTED MECHANISM FAMILY: Scheduled policy-rate differential repricing.**

Mechanisms B and C are `DEFERRED — NOT TESTED`. Selection follows economic
interpretability and lower degrees of freedom, not historical PnL, event
counts, price returns, or simulated entries.

## 7. Proposed variants

At most two independent directional hypotheses are proposed for a later
preregistration:

1. `policy-differential-widens`: the official USD policy rate minus official
   JPY policy rate increases at a pre-specified, timestamped decision event;
   the future preregistration would define the USDJPY direction implied by that
   mechanism.
2. `policy-differential-narrows`: the same differential decreases; it is the
   separately registered opposite economic state, not a parameter variation.

These are not signals, entries, or executable rules. They are separate because
the two economic states can be falsified independently. No third neutral or
unchanged-rate variant is proposed.

## 8. Degrees of freedom that must be frozen

Before any implementation, each variant must state all of the following:

| Decision | Required future freeze |
| --- | --- |
| Reference window | Official event calendar and the prior officially effective policy-rate record |
| Trigger | Exact signed change in the defined official USD-minus-JPY policy-rate differential |
| Confirmation | Whether the first eligible post-release H1 close alone confirms, or no price confirmation is permitted |
| Direction | Explicit USDJPY long/short mapping for a widening and narrowing differential |
| Entry delay | Exact first eligible bar after the documented release timestamp |
| Holding / exit | A single fixed exit convention, not selected from performance |
| Event expiry | Exact expiry if an execution bar is unavailable or event timing is uncertain |
| Overlap policy | One event owns one position; later events during a position are ignored or explicitly queued |
| Position policy | One position, fixed lots, no pyramiding, averaging, partial exits, or reversal stacking |
| Calendar/session | UTC conversion, official-release timestamp rule, holidays, and daylight-saving source convention |
| Lot size | Frozen only with the new cost/account specification |

## 9. Parameter provenance

No performance-optimized number is proposed. Future values must be classified
as follows:

| Item | Provenance | Rationale |
| --- | --- | --- |
| H1 bars | MARKET CONVENTION | Selected cell and observed broker timeframe |
| Fed / BoJ official decision timestamp | MARKET CONVENTION | Source-issued event time, converted to UTC with source retained |
| Policy-rate differential sign | MARKET CONVENTION | Direct economic definition; no optimized threshold |
| First eligible post-event bar | EXECUTION CONVENTION | Needed to prevent look-ahead and intrabar inference |
| Fixed holding, expiry, lots, overlap | DESIGN ASSUMPTION | Must be selected once with a rationale before performance |
| Split boundaries | STRUCTURAL DATA-DERIVED | Mechanical use of the already observed Phase 5G availability envelope |
| Costs | STRUCTURAL DATA-DERIVED | New USDJPY/H1 calibration, not EURUSD reuse |

## 10. Expected turnover and falsification

Expected turnover is LOW and sample insufficiency is a material risk. No
historical event counting or signal simulation was performed. The family must
be rejected if the preregistered sample gate is not met, gross PnL is
non-positive, realistic costs destroy net PnL, signs reverse across frozen
periods, drawdown/solvency fails, annual results are unstable, or a small
number of trades dominates the outcome.

## 11. Required USDJPY/H1 cost calibration

Before performance, a read-only USDJPY/H1 calibration must freeze: resolved
symbol; digits; point; tick size/value; contract size; volume constraints;
currency conversion basis if needed; hourly spread distribution and coverage;
commission assumption; long and short swaps; triple-rollover rule; and a
separate adverse-slippage assumption. It must fingerprint its bars, raw
capture, metadata and final cost profile. Missing cost inputs must fail closed.

## 12. Proposed temporal-data policy

This is a prospective, mechanical policy derived from the Phase 5G availability
envelope, not copied from Phase 5H performance dates:

| Segment | UTC interval | Purpose |
| --- | --- | --- |
| Internal development A | 2022-09-01 to 2023-06-01 exclusive | Implementation and first internal check |
| Internal development B | 2023-06-01 to 2024-03-01 exclusive | Independent internal check |
| Development aggregate | 2022-09-01 to 2024-03-01 exclusive | Fixed aggregate evaluation |
| Single validation | 2024-03-01 to 2024-09-01 exclusive | One validation evaluation |
| Future test | 2024-09-01 to 2025-03-01 exclusive | Reserved; no strategy performance observed |
| Operational reserve | 2025-03-01 to 2025-08-30 exclusive | Excluded from the first strategy study; no automatic test assignment |

The full 2022-09 through 2025-08 period was already observed only for Phase 5G
structural viability. That provenance does not make it strategy performance,
but it is disclosed. The future-test interval remains unobserved for strategy
signals and performance.

## 13. Candidate-rule dimensions and observability

A later preregistration should require solvency, minimum sample, positive net
PnL, positive expectancy, PF, signed drawdown, cost efficiency, temporal and
year stability, and trade concentration. Thresholds are intentionally not
chosen here.

Every future run must use the Phase 5G contract: strict `manifest.json`,
`summary.json`, and `trades.jsonl`. Trade rows must reconstruct signal, entry,
exit, side, holding, gross, spread, slippage, commission, swap, net PnL, and
calendar/time attribution.

## 14. Implementation architecture and risks

Future implementation should use a small pure event/state function for a
frozen official event feed; generic next-bar engine execution; explicit
pre-engine event/length/split invariants; and synthetic fixtures for timestamp,
rate-differential, missing-event, overlap and truncation cases. Cost handling,
execution, insolvency, and artifact writing stay in their generic components.

The dominant risks are incomplete or non-auditable official event timestamps,
effective-date ambiguity, sparse samples, release-time bar alignment,
USDJPY-specific execution costs, and mistaking a structural-quality choice for
an edge. These are why no preregistration is frozen yet.

## 15. Safety and disposition

Historical strategy performance: `NOT RUN`  
Historical signals: `NOT GENERATED`  
EURUSD/M15: `UNTOUCHED`  
Phase 5H future test: `NOT ASSIGNED`  
USDJPY/H1 future test: `NOT CONSUMED`

LIVE remained disabled. Zero orders, demo opens/closes, `place_order`,
`close_position`, or MT5 write actions occurred.

**PHASE 5J CLOSED — NOT READY TO PREREGISTER**
