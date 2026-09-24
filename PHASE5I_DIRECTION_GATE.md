# Phase 5I — Research Direction Gate

Status: **CLOSED — DESIGN / DECISION ONLY**.

This phase generated no new strategy signals, ran no strategy performance or
backtest, consumed no future test, and did not access the protected
EURUSD/M15 interval. Its evidence is limited to the valid Phase 5H Run 4
result and the previously completed Phase 5G descriptive structural audit.

## 1. Phase 5H formal closeout

Phase 5H is closed with valid Run 4, two observed hypotheses, two `REJECT`,
and zero `CANDIDATE`. Runs 1–3 remain `INVALID — PRESERVED` and are excluded
from every performance inference. The future test is `NOT ASSIGNED`.

## 2. Phase 5H failure interpretation

`daily-range-failed-breakout-long` is descriptively
`TEMPORALLY_UNSTABLE`: Inner A was strongly positive (+51.011 USD), Inner B
was negative (-10.381 USD), and validation was materially negative
(-20.056 USD). The positive aggregate-development result (+32.430 USD) is not
sufficient under the frozen split criteria.

`daily-range-failed-breakout-short` is descriptively `MIXED` under the existing
Phase 5F taxonomy, with no robust positive edge: Inner A, aggregate development,
and validation were negative; only Inner B was slightly positive. It remains
`REJECT` under its frozen candidate matrix.

The rejected failed-breakout family is closed. The following are
`POST-HOC — NOT AUTHORIZED`: changing the hold or confirmation, previous
trading-day reference, hour/weekday/ATR filters, stops, targets, range
boundaries, or a LONG-only rescue.

## 3. Phase 5G structural evidence refresh

Window: `2022-09-01T00:00:00Z` to exclusive `2025-08-30T00:00:00Z`.
All figures below are descriptive broker-native microstructure measures, not
cross-symbol PnL or edge estimates. Metadata quality is `0 errors / 1 gap
warning` for every eligible cell; all warnings record unrepaired gaps.

| Cell | Coverage | Unexpected gaps | Median/P95 spread (points) | Median/P95 range (price) | Median burden | P95 burden | Hourly burden, best/worst UTC | Label |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| EURUSD/H1 | 99.23% | 6 | 15.00 / 20.85 | .0011300 / .0034500 | 13.27% | 18.45% | 17=.0619 / 00=.4677 | VIABLE |
| EURUSD/M15 | 99.15% | 27 | 15.00 / 25.00 | .0005500 / .0016800 | 27.27% | 45.45% | 17=.1327 / 00=1.2143 | BORDERLINE |
| GBPUSD/H1 | 99.23% | 6 | 16.00 / 25.00 | .0014500 / .0043800 | 11.03% | 17.24% | 17=.0559 / 00=.4393 | VIABLE |
| GBPUSD/M15 | 99.12% | 45 | 17.00 / 27.00 | .0007100 / .0021300 | 23.94% | 38.03% | 17=.1143 / 00=1.3659 | VIABLE |
| USDJPY/H1 | 99.23% | 6 | 19.00 / 26.00 | .20300 / .58600 | 9.36% | 12.81% | 15=.0541 / 00=.3838 | VIABLE |
| USDJPY/M15 | 99.14% | 34 | 19.00 / 30.00 | .09800 / .28400 | 19.39% | 30.61% | 17=.1173 / 00=1.1395 | VIABLE |

M5 is `INSUFFICIENT_DATA` for all three symbols. EURUSD/M15 remains
`BORDERLINE` and `UNTOUCHED`.

For both GBPUSD and USDJPY, H1 has lower median and P95 burden, fewer
unexpected gaps, and less adverse hour-00 burden than M15. This is a local
structural comparison only; it does not establish that H1 is universally
superior or profitable.

## 4. Decision matrix

| Direction | Structural justification | Statistical / research risk | New cost calibration? | Contamination risk | Recommendation |
| --- | --- | --- | --- | --- | --- |
| EURUSD/H1 | Viable burden and quality | Three Phase 5H observations do not justify rescuing the rejected family; any new mechanism needs an independent rationale | No existing profile may be assumed for a new design without checking its scope | Higher, due to recent Phase 5H result | Deferred |
| GBPUSD/H1 | Viable; 11.03% median and 17.24% P95 burden | No strategy evidence; symbol-specific mechanism remains unknown | Yes | Low if independently designed | Deferred |
| USDJPY/H1 | Viable; lowest eligible H1 burden (9.36% median, 12.81% P95), 99.23% coverage, 6 gaps | Structural quality is not edge; continued search can still rationally fail | **Yes — required** | Low if independently designed | Primary cell |
| STOP | Avoids further search after 5D, 5E, and 5H produced zero candidates | Opportunity cost of not testing an independently justified mechanism | No | None | Rational alternative, but not selected |

## 5. Required questions

### Q1. What did Phase 5H actually teach us?

The completed-daily-range failed-breakout LONG effect did not persist across
the frozen splits; SHORT showed no robust positive edge. It did not show that
EURUSD/H1, failed breakouts generally, or FX research are unworkable.

### Q2. Is there a preregistration-clean reason to continue EURUSD/H1?

Not from the positive Inner A result. Continuing there is permissible only if a
future mechanism has an independent causal rationale and is not a derivative
of 5D/5E/5H. This gate does not select it.

### Q3. Which of GBPUSD/H1 and USDJPY/H1 has the better structural case?

USDJPY/H1: it has the lower median and P95 spread/range burden while matching
GBPUSD/H1 on coverage and unexpected-gap count.

### Q4. Does changing symbol add less post-hoc-rescue risk than modifying failed-breakout?

Yes, provided the new symbol receives a genuinely independent mechanism,
preregistration, cost calibration, and temporal policy. It is not a transfer
of the Phase 5H strategy.

### Q5. Is continuing rational?

It is rational but optional. The three zero-candidate phases make STOP a valid
choice. One tightly budgeted, structurally justified independent design is
proportionate; continued broad searching is not.

### Q6. If continuing, what is the only primary cell?

`USDJPY/H1`.

### Q7. What must happen before any backtest?

1. Independently define one causal mechanism family, with at most two variants;
   it must not be a derivative of 5D/5E/5H.
2. Freeze strategy preregistration, hypothesis ledger, candidate rules, and a
   prospective temporal-data reservation policy.
3. Perform and freeze USDJPY/H1-specific cost calibration. EURUSD/H1 and
   EURUSD/M15 profiles may not be reused.
4. Add and pass causal, truncation, event, cost, split-protection, and
   observability tests; then pass the full suite and `git diff --check`.
5. Obtain separate explicit authorization for historical performance.

## 6. Selection and budget

**PRIMARY NEXT RESEARCH CELL: `USDJPY/H1`**

Deferred cells: `GBPUSD/H1`, `GBPUSD/M15`, `USDJPY/M15`, and `EURUSD/H1`.
EURUSD/M15 remains `UNTOUCHED`; M5 remains `INSUFFICIENT_DATA`.

If a next phase is authorized, its maximum budget is **one independent
mechanism family and two variants**. No strategy, indicator, threshold,
holding period, entry rule, or parameter is selected in this document.

## 7. Performance and safety

New strategy performance: `NOT RUN`  
New signals: `NOT GENERATED`  
Future test: `NOT ASSIGNED`  
EURUSD/M15: `UNTOUCHED`

No orders, MT5 write actions, DEMO actions, or LIVE actions occurred.

**PHASE 5I CLOSED — READY FOR NEXT RESEARCH DESIGN**
