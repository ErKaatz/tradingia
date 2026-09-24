# Phase 5L — BoJ Scalar Convention Gate

Status: **CLOSED — regime split requires hypothesis redesign**.

This is an economic-definition decision only. No USDJPY prices, returns, signals, trades, PnL, cost calibration, or future-test data were used.

## Official frameworks

Before March 2024, archived official BoJ Statements define the short-term policy interest rate as minus 0.1 percent applied to Policy-Rate Balances. It is a point-valued administered-rate instrument.

The official March 19, 2024 framework document states that negative-rate policy and QQE with Yield Curve Control had fulfilled their roles. It says the BoJ will guide the short-term interest rate as a primary policy tool and announces an uncollateralized overnight call-rate guideline around 0 to 0.1 percent. The document separately states the new guideline/current-account interest are effective March 21, 2024.

Post-transition decisions use the overnight-call-rate guideline: initially a range, then point-style guidance such as around 0.25 percent. This establishes conceptual succession of short-rate policy stance, but not a BoJ-published numeric equivalence between the two instruments.

## Four-option evaluation

| Option | Source fidelity | Cross-regime comparability | Hidden freedom | March 19 treatment | Decision |
| --- | --- | --- | --- | --- | --- |
| A — no scalar | Highest | None | None | NOT_COMPARABLE | Not selected |
| B — midpoint stance | Adds midpoint to official range | Unproven | Midpoint plus splice | Numeric +15 bp | Not selected |
| C — lower-bound stance | Adds preferred endpoint | Unproven | Lower bound plus splice | Numeric +10 bp | Not selected |
| D — regime-separated | Highest | Within regime only | None across transition | REGIME_TRANSITION | **Selected** |

Fed midpoint use is not a reason to adopt BoJ midpoint. The Fed publishes a target range; the BoJ transition links a former administered point rate to a later operating guideline. Cosmetic symmetry would not establish economic equivalence.

## Selected convention

**D — REGIME-SEPARATED SERIES.**

`BOJ_NEGATIVE_RATE_REGIME` applies before March 19, 2024; `REGIME_TRANSITION` on March 19; and `BOJ_OVERNIGHT_RATE_REGIME` afterward. `regime_safe_differential_direction()` refuses numeric direction whenever a comparison crosses regimes.

Official observation and research convention remain separate: -0.1 percent, 0–0.1 percent and later point guidance are official observations. No midpoint, lower bound, upper bound or implied March +10/+15 bp value is frozen as a research scalar.

## Consequences

No scalar convention manifest, Phase 5K v3 differential feed, WIDENS/NARROWS/UNCHANGED events, or split counts is created. The Phase 5J cross-regime policy-differential mechanism needs a new hypothesis design; sample feasibility cannot be evaluated without inventing the rejected numeric bridge.

Phase 5K v1 remains preserved as incomplete. The timestamp-corrected v2 feed remains valid, with SHA-256 `a82a1369eedab35b2d5f2fd6273934046638e1087edc8dba14b2beb003d7f15e`.

## Tests and safety

Tests cover pre-transition, March transition, post-transition, and rejection of numeric direction across regimes, alongside source parsing/timezone/strict JSON and fingerprint checks.

Historical strategy performance: `NOT RUN`  
Historical strategy signals: `NOT GENERATED`  
EURUSD/M15: `UNTOUCHED`  
Phase 5H future test: `NOT ASSIGNED`  
USDJPY/H1 future-test performance: `NOT CONSUMED`  
LIVE disabled; orders: `0`.

**PHASE 5L CLOSED — REGIME SPLIT REQUIRES HYPOTHESIS REDESIGN**
