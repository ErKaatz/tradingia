# Phase 5N — USDJPY/H1 Research Continuation Gate

Status: **CLOSED — DECISION ONLY**.

This gate reviews the completed Phase 5D–5M record to decide whether further USDJPY/H1 research is justified. It creates no strategy design, signals, backtests, performance calculations, return calculations, cost calibration, or orders. The decision is made before any new price-based experiment.

## 1. Mandatory closeout of the fundamental route

| Route | Formal outcome | Reason |
| --- | --- | --- |
| Scheduled policy-rate differential repricing | `NOT PREREGISTERED` | The required coherent cross-regime numeric definition was not available. |
| Cross-regime numeric differential | `REJECTED ON DEFINITION GROUNDS` | Phase 5L prohibits inventing a scalar bridge between the negative-rate and overnight-rate BoJ regimes. |
| Regime-safe action asymmetry | `NOT PREREGISTERED — SAMPLE INSUFFICIENT` | Phase 5M found fewer than eight relevant events in each internal split before observing price performance. |
| March 2024 transition | `NOT TESTABLE — n=1` | One validation event cannot support empirical strategy testing. |

These are research-design outcomes, not observed strategy failures. They must not be converted into additional hypotheses by adding unchanged decisions, communications, surprises, unscheduled events, altered splits, or a numeric BoJ convention.

## 2. Actual research-family accounting

| Phase | Cell | Mechanism family | Outcome | Reason | Performance observed? | Reusable negative lesson |
| --- | --- | --- | --- | --- | --- | --- |
| 5D | EURUSD/M15 | Trend/EMA | `REJECT` | Did not meet frozen candidate criteria. | Yes | A conventional trend formulation was not robust under the registered evaluation. |
| 5D | EURUSD/M15 | Mean reversion/z-score | `REJECT` | Did not meet frozen candidate criteria. | Yes | A conventional reversion formulation was not robust under the registered evaluation. |
| 5D | EURUSD/M15 | Momentum | `REJECT` | Did not meet frozen candidate criteria. | Yes | Simple momentum did not establish a candidate. |
| 5D | EURUSD/M15 | Session breakout | `REJECT` | Did not meet frozen candidate criteria. | Yes | A session-breakout route did not establish a candidate. |
| 5E | EURUSD/M15 | Compression-expansion | `REJECT` | Did not meet frozen candidate criteria. | Yes | Volatility compression expansion was not a robust route in the registered variants. |
| 5E | EURUSD/M15 | Session range | `REJECT` | Did not meet frozen candidate criteria. | Yes | A session-range route did not establish a candidate. |
| 5E | EURUSD/M15 | Expansion reversal | `REJECT` | Did not meet frozen candidate criteria. | Yes | Expansion reversal did not establish a candidate. |
| 5E | EURUSD/M15 | Impulse continuation | `REJECT` | Did not meet frozen candidate criteria. | Yes | Impulse continuation did not establish a candidate. |
| 5F | EURUSD/M15 | No new family | Closed | Post-hoc attribution only. | No new performance | Attribution is not authorization to rescue rejected rules. |
| 5G | Multi-cell | No new family | Closed | Descriptive viability audit only. | No | Microstructure viability is not an edge estimate. |
| 5H | EURUSD/H1 | Daily-range failed breakout | `REJECT` | Valid Run 4 was temporally unstable/negative out of sample; Runs 1–3 are invalid and excluded. | Yes | A positive inner segment or aggregate cannot override split instability and negative validation. |
| 5I | Multi-cell | No new family | Closed | Direction selection only; USDJPY/H1 was structurally preferred. | No | Lower burden and good coverage justify feasibility only, never profitability. |
| 5J | USDJPY/H1 concept | Scheduled policy-rate differential repricing | Not ready to preregister | Official-source definition/provenance requirements remained unresolved. | No | A causal narrative is insufficient without a coherent, auditable state definition. |
| 5K | USDJPY/H1 support | No new family | Source provenance corrected | Official BoJ release-time evidence was rebuilt; no strategy was selected. | No | Data-source repair is infrastructure work, not a strategy result. |
| 5L | USDJPY/H1 support | Cross-regime numeric differential | `REJECTED ON DEFINITION GROUNDS` | No source-supported numeric bridge across BoJ regimes. | No | Do not solve a measurement ambiguity with a post-hoc research convention. |
| 5M | USDJPY/H1 concept | Central-bank action asymmetry | `NOT PREREGISTERED — SAMPLE INSUFFICIENT` | Event counts fail the pre-price feasibility requirement in both internal splits. | No | A sound, independent mechanism must still have sufficient split-level sample. |

There are **nine** distinct families with valid observed historical performance and `REJECT` outcomes: four in 5D, four in 5E, and the one 5H family. Two further distinct fundamental routes stopped before performance: the cross-regime numeric differential on definition grounds and action asymmetry for insufficient sample. Variant counts are not treated as separate families.

## 3. Strategy failure versus research-design failure

The 5D, 5E, and valid 5H Run 4 outcomes are strategy-performance rejections. They say that the registered rules did not meet their criteria; they do not prove that a symbol, timeframe, or FX market is impossible to research.

The 5J–5M outcomes are pre-performance research-design gates. In particular, Phase 5M's sample insufficiency is not negative PnL and must never be narrated as a strategy loss. Conversely, its economic plausibility cannot compensate for missing split-level sample.

## 4. Continuation directions

| Direction | Positive justification | Fishing risk | New information | Cost before testing | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A — one final USDJPY/H1 family | USDJPY/H1 is structurally viable: 99.23% coverage, 6 unexpected gaps, 9.36% median and 12.81% P95 spread/range burden. | High unless an independently evidenced mechanism arrives; the current record supplies none. | No new causal or market-structure evidence identified by this gate. | USDJPY/H1-specific calibration would be mandatory before any performance. | Do not authorize now. |
| B — move to GBPUSD/H1 | GBPUSD/H1 is structurally viable: 99.23% coverage, 6 unexpected gaps, 11.03% median and 17.24% P95 burden. | High: a new cell alone expands the search space and does not create a mechanism. | No symbol-specific independent rationale identified. | A new GBPUSD/H1 cost calibration, new design, and new temporal policy would be mandatory. | Do not select. |
| C — stop new hypothesis search | Nine valid performance rejections and two principled pre-performance stops have exhausted the current bounded search without a positive independent continuation reason. | Lowest; prevents treating feasibility or low cost as an edge. | Preserves all infrastructure for later use if genuinely new evidence emerges. | None. | **Selected.** |

## 5. Required questions

### Q1. What was actually tested and rejected?

Nine distinct families received valid historical performance evaluation and were rejected: the four 5D technical families, four 5E technical families, and 5H daily-range failed breakout. The latter's valid result is especially clear: long had +51.011 USD in Inner A, -10.381 USD in Inner B, and -20.056 USD in validation; short had no robust positive split pattern. Invalid 5H Runs 1–3 are preserved but excluded from inference.

### Q2. What was rejected before performance, and why?

The numeric cross-regime differential was rejected because a source-supported BoJ scalar bridge does not exist. The regime-safe action-asymmetry mechanism was not preregistered because relevant event counts were 6/1 for relative tightening and 0/0 for relative easing across the internal splits. The March 2024 transition is n=1. No rejection was caused by price performance.

### Q3. Does USDJPY/H1 structural viability justify another family?

No. It supports data feasibility and future infrastructure reuse, not a positive expectation or a new causal thesis. A low burden must not be used as a substitute for independent economic or market-structure evidence.

### Q4. Is there a genuinely independent final USDJPY/H1 family available now?

No. This gate identified no positive evidence for a family independent of the technical mechanisms in 5D/5E/5H and the fundamental mechanisms reviewed in 5J–5M. Inventing one here would violate the decision-only scope.

### Q5. Should GBPUSD/H1 be selected solely because it is viable?

No. GBPUSD/H1 has a valid structural case, but a cell change without a new independent mechanism is an unbounded expansion of the hypothesis search. It would require a future new direction, design, temporal policy, and GBPUSD/H1 cost calibration before testing.

### Q6. What is the correct accounting of research budget and families?

The search contains nine performance-tested families and two separate pre-performance fundamental failures. No individual variant, attribution exercise, source repair, or structural audit is counted as a new family. This avoids both understating search breadth and mislabeling infrastructure as evidence.

### Q7. What conditions could reopen research later?

Only genuinely new, independently motivated evidence could reopen it. It must first support a bounded family (one family, at most two hypotheses), an independent rationale, a frozen temporal policy, applicable fresh cost calibration, causal tests, and separate authorization before performance. Neither lower observed cost, a more attractive cell, a post-hoc filter, nor a reinterpretation of current results qualifies as new evidence.

### Q8. What remains preserved after stopping?

The MT5 bridge, read-only data/provenance infrastructure, official policy-event timestamps, BoJ regime labels, cost and execution test infrastructure, structural viability audit, invalid-run preservation, and protected EURUSD/M15 untouched interval remain reusable. No historical result is recalculated or altered.

## 6. Selection, safety, and closeout

**Selected direction: C — stop new hypothesis search.** Under the current research budget, the search is exhausted. This is not a claim that no future FX edge can exist; it is a refusal to continue without a positive independent reason.

Historical performance: `NOT RUN`  
Signals: `NOT GENERATED`  
Returns/PnL: `NOT CALCULATED`  
Cost calibration: `NOT RUN`  
EURUSD/M15 untouched test: `UNTOUCHED`  
Orders (DEMO/LIVE): `0`  
LIVE: disabled.

**PHASE 5N CLOSED — NEW HYPOTHESIS SEARCH STOPPED**

