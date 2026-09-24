# Phase 5M — Regime-Safe Fundamental Hypothesis Redesign

Status: **CLOSED — regime-safe family found; sample insufficient**.

No prices, returns, signals, PnL, backtests, cost calibration, or future-test
data were used. The evidence is limited to the official timestamped Fed/BoJ
decision infrastructure, BoJ regime labels, and policy-action counts.

## 1. Phase 5L handoff and usable information

Phase 5L permanently prohibits a cross-regime numeric BoJ scalar. Usable
infrastructure is 24/24 timestamped Fed decisions, 24/24 timestamped BoJ
decisions, official-source provenance/bytes, UTC normalization, scheduled/
unscheduled distinction, strict JSON, and the three BoJ regime labels.

## 2. Mechanism A — within-regime numeric differential changes

This would use Fed midpoint minus BoJ scalar only when both states are in the
same BoJ regime. It is safe before March 2024 because the BoJ short-term rate
is a fixed -0.1 point. It is not a complete post-transition solution: a 0–0.1
guideline versus later point guidance still needs a range-representation choice.
It therefore cannot supply one coherent family across the frozen splits without
reintroducing the forbidden scalar convention. **Deferred — not selected.**

## 3. Mechanism B — event direction without cross-regime level

Each scheduled official action is classified without a BoJ level comparison:

- `relative-tightening`: Fed `TIGHTEN` or BoJ `EASE`.
- `relative-easing`: Fed `EASE` or BoJ `TIGHTEN`.
- `UNCHANGED` and `REGIME_TRANSITION` are retained for completeness only; they
  are not hypotheses.

This is economically interpretable as a relative *change of stance*, requires
no cross-regime scalar, has causal source timestamps, and is independent of
the previously rejected technical families. It has low turnover and simple H1
alignment, but sparse action counts.

## 4. Mechanism C — March 2024 regime transition

The transition is official and causally timestamped, but it is exactly one
event (`n = 1`) in validation. It is not suitable for empirical strategy
testing and cannot be inflated with communications or other events.

## 5. Comparison matrix

| Criterion | A: within-regime differential | B: action asymmetry | C: transition event |
| --- | --- | --- | --- |
| Economic rationale | Direct but incomplete post-regime | Direct relative stance change | Historically important but singular |
| Regime safety | Partial | Full | Full |
| Independent of 5D/5E/5H | Yes | Yes | Yes |
| Sample feasibility | Weak | Weak | Impossible |
| Degrees of freedom | Range representation remains | Low | Low, but n=1 |
| Auditability / causal H1 alignment | High where defined | High | High |
| Cost compatibility | Requires future USDJPY/H1 calibration | Requires future USDJPY/H1 calibration | Not applicable |
| Post-hoc tuning risk | Moderate | Low | High if expanded |

## 6. Official event counts by frozen split

Counts are feasibility-only and use no price data. Fed rate changes come from
the frozen midpoint source feed; BoJ actions are official decision-direction
labels inside their own regime. `relative-tightening` is Fed tighten or BoJ
ease; `relative-easing` is Fed ease or BoJ tighten.

| Frozen segment | Relative tightening | Relative easing | Unchanged | Regime transition |
| --- | ---: | ---: | ---: | ---: |
| Internal A: 2022-09-01 to 2023-06-01 | 6 | 0 | 6 | 0 |
| Internal B: 2023-06-01 to 2024-03-01 | 1 | 0 | 11 | 0 |
| Aggregate development | 7 | 0 | 17 | 0 |
| Validation: 2024-03-01 to 2024-09-01 | 0 | 1 | 6 | 1 |
| Future-test reserve | 0 | 4 | 4 | 0 |
| Operational reserve | 0 | 0 | 8 | 0 |

## 7. Selected family and proposed hypotheses

**SELECTED FAMILY: central-bank action asymmetry (Mechanism B).**

The only permitted future hypotheses would have been `relative-tightening` and
`relative-easing`; unchanged and transition never become a third hypothesis.
They are not preregistered, implemented, or tested.

## 8. Sample feasibility and recommendation

The original independent-evaluation expectation is at least 8 events per
internal split. Relative-tightening has 6 then 1; relative-easing has 0 then 0.
This is plainly insufficient before any price observation. The selected family
is regime-safe but **must not be preregistered**. Adding unchanged decisions,
communications, surprises, unscheduled actions, or changing split dates would
be an unauthorized sample rescue.

## 9. Degrees of freedom for any future redesign

A future, independently authorized design would have to freeze event
classification, direction mapping, official release-time handling, complete-H1
alignment, entry, holding/exit, overlap, expiry, sizing, and regime
applicability. No values are selected here.

USDJPY/H1-specific cost calibration remains mandatory before any later
performance. The causal H1 rule remains: a partially post-release bar cannot
be used; the first eligible observation must be a fully observed H1 bar after
the official release. Future execution must retain `manifest.json`,
`summary.json`, and `trades.jsonl`, with event source, release UTC, regime and
classification on every trade row.

## 10. Safety

Historical strategy performance: `NOT RUN`  
Historical strategy signals: `NOT GENERATED`  
EURUSD/M15: `UNTOUCHED`  
Phase 5H future test: `NOT ASSIGNED`  
USDJPY/H1 future-test performance: `NOT CONSUMED`  
LIVE disabled; orders: `0`.

**PHASE 5M CLOSED — SAMPLE INSUFFICIENT**
