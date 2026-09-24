# Phase 5 Research Program — Closeout

## Executive status

**PHASE 5 RESEARCH PROGRAM: CLOSED / PAUSED**  
**CURRENT CANDIDATES: 0**  
**NEW HYPOTHESIS SEARCH: STOPPED**

No candidate survived the bounded research program, and no independently justified continuation direction currently exists.

This is a documentation, freeze, and handoff record. It does **not** mean FX has no edge, FX is impossible, or research failed. It means no strategy is authorized from the evidence and budget actually used.

## Authoritative-reading rule

This document is the entry point, not a replacement for immutable research evidence. When documents conflict, use the latest phase-final artifact named in the inventory. Historical incident reports stay preserved but never override a later valid run or a stated correction.

## Phase inventory

| Phase | Purpose | Cell | Mechanism / infrastructure | Performance observed? | Outcome | Authoritative artifact |
| --- | --- | --- | --- | --- | --- | --- |
| 5A | Data foundation | EURUSD, multi-timeframe | Canonical schema, deterministic datasets, read-only MT5 history, UTC/gap validation | No | Closed foundation | `PHASE5A_STATUS.md` |
| 5B | Economic backtest foundation | Generic FX / EURUSD-compatible | Causal engine, BID/ASK, PnL, costs, solvency, accounting | No strategy performance | Closed foundation | `PHASE5B_STATUS.md` |
| 5C | Cost calibration | EURUSD/M15 | Historical spread capture; NoCommission and frozen swap terms | No | Frozen provenance profile for 5D/5E only | `PHASE5C_STATUS.md` |
| 5D | Baseline evaluation | EURUSD/M15 | Trend, reversion, momentum, session breakout | Yes | 8 non-controls `REJECT`; 0 candidate | `PHASE5D_STATUS.md`, `PHASE5D_RUN2_RESULTS.md` |
| 5E | Preregistered event evaluation | EURUSD/M15 | Compression, range, reversal, impulse families | Yes | 8 hypotheses `REJECT`; 0 candidate | `PHASE5E_STATUS.md` |
| 5F | Attribution | EURUSD/M15 artifacts | Post-hoc gross/cost/mechanism attribution | No new performance | Closed; no follow-up justified | `PHASE5F_STATUS.md` |
| 5G | Viability audit | EURUSD/GBPUSD/USDJPY M5/M15/H1 | Availability, gaps, microstructure burden | No | H1 and most M15 structurally viable; M5 insufficient | `PHASE5G_VIABILITY_STATUS.md` |
| 5H | Failed-breakout evaluation | EURUSD/H1 | Daily-range failed breakout | Yes, Run 4 only | 2 `REJECT`; 0 candidate | `PHASE5H_STATUS.md`, `PHASE5H_RUN4_RESULTS.md` |
| 5I | Direction gate | Multi-cell | Compare structural feasibility | No | USDJPY/H1 selected then; not a performance result | `PHASE5I_DIRECTION_GATE.md` |
| 5J | Fundamental design gate | USDJPY/H1 concept | Scheduled policy-rate differential repricing | No | Not ready to preregister | `PHASE5J_HYPOTHESIS_DESIGN.md` |
| 5K | Policy-event provenance | USDJPY/H1 support | Official BoJ release timestamps | No | v2 timestamps corrected; scalar remains blocked | `PHASE5K_SOURCE_AUDIT_CORRECTION.md` |
| 5L | Scalar convention gate | USDJPY/H1 support | BoJ regime/scalar decision | No | Cross-regime numeric bridge rejected | `PHASE5L_BOJ_SCALAR_CONVENTION_GATE.md` |
| 5M | Regime-safe redesign | USDJPY/H1 concept | Central-bank action asymmetry | No | Not preregistered: sample insufficient | `PHASE5M_REGIME_SAFE_FUNDAMENTAL_REDESIGN.md` |
| 5N | Continuation decision | USDJPY/H1 / GBPUSD/H1 review | Research-family accounting and stop decision | No | New-hypothesis search stopped | `PHASE5N_USDJPY_H1_CONTINUATION_GATE.md` |

## Research-family accounting

Exactly **9 distinct performance-tested families** and **2 distinct pre-performance fundamental stops** are counted.

Not separately counted: parameter variants, flat controls, invalid runs, source audits, cost calibration, attribution, viability studies, remediations, or infrastructure work.

### Performance-tested families — 9 REJECT / 0 CANDIDATE

| Phase | Family | Outcome |
| --- | --- | --- |
| 5D | Trend/EMA | `REJECT` |
| 5D | Mean reversion / z-score | `REJECT` |
| 5D | Momentum | `REJECT` |
| 5D | Session breakout | `REJECT` |
| 5E | Compression-expansion | `REJECT` |
| 5E | Session range | `REJECT` |
| 5E | Expansion reversal | `REJECT` |
| 5E | Impulse continuation | `REJECT` |
| 5H | Daily-range failed breakout | `REJECT` |

### Pre-performance fundamental routes

| Route | Status | Meaning |
| --- | --- | --- |
| Cross-regime numeric policy differential | `REJECTED ON DEFINITION GROUNDS` | No source-supported scalar bridge may be invented across BoJ regimes. |
| Central-bank action asymmetry | `NOT PREREGISTERED — SAMPLE INSUFFICIENT` | Relevant events fail the split-level feasibility gate before price observation. |
| March 2024 transition | `NOT TESTABLE — n=1` | A single event is not a strategy sample. |

These are not losing strategies and must not be reported as negative PnL findings.

## Phase 5H incident and final-run record

| Run | Status | Reason / use |
| --- | --- | --- |
| 1 | `INVALID — semantic holding failure` | Preserved incident; no usable performance evidence. |
| 2 | `INVALID — target-length failure` | Preserved incident; no usable performance evidence. |
| 3 | `INVALID — previous UTC-calendar-day failure` | Preserved incident; no usable performance evidence. |
| 4 | `VALID` | Two directional hypotheses observed; both `REJECT`; 0 candidates. |

Runs 1–3 contain no usable research-performance evidence. Run 4 is authoritative: LONG was positive only in Inner A and negative in Inner B and validation; SHORT had no robust positive split pattern. The valid result is a rejection under its frozen criteria, not a basis for rescue.

## Reusable negative lessons

- Costs can destroy an otherwise positive gross edge; net accounting and bid/ask execution are decisive.
- Temporal stability matters more than aggregate-development PnL or one favorable inner split.
- Microstructure viability is feasibility evidence, not evidence of edge.
- Source provenance and release-time correctness are part of research correctness.
- Sample feasibility must be checked before price performance.
- Measurement ambiguity must fail closed; a convenient numeric convention cannot be retrofitted.
- Invalid engineering runs must remain preserved and excluded rather than silently discarded or interpreted.
- A low-cost cell, a symbol switch, or a post-hoc filter is not an independent continuation rationale.

No lesson above authorizes a follow-up strategy.

## Reusable engineering infrastructure

The following are reusable engineering infrastructure, not research results:

- FX canonical data schema; deterministic dataset fingerprints; UTC normalization; and gap classification.
- Read-only MT5 historical provider and metadata access.
- Economic backtest engine with causal next-bar execution, BID/ASK accounting, explicit spread/slippage/commission/swap decomposition, and equity-based solvency logic.
- Research observability bundles: `manifest.json`, `summary.json`, `trades.jsonl`, semantic/accounting audits, and immutable invalid-run markers.
- Official Fed event feed; verified official BoJ release timestamps; BoJ regime labels; strict provenance tooling; and timezone conversion.
- Execution safety infrastructure: kill switch, reconciliation, idempotency, and DEMO/LIVE policy controls.

A validated bridge or engine is not a validated trading strategy.

## Dataset and reserve protection

| Asset | Status |
| --- | --- |
| EURUSD/M15 protected interval | `UNTOUCHED` |
| Phase 5H future test | `NOT ASSIGNED` |
| USDJPY/H1 future-test performance | `NOT CONSUMED` |

This closeout neither assigns nor consumes any reserve.

## Frozen cost-profile provenance

| Scope | Authoritative profile / status | Permitted interpretation |
| --- | --- | --- |
| EURUSD/M15, Phase 5D/5E | Phase 5C spread fingerprint `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575`; non-spread fingerprint `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36` | Historical provenance for those studies only. |
| EURUSD/H1, Phase 5H | Cost profile `b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7` | Historical provenance for Run 4 only. |
| Any new cell or materially new execution environment | No transferable profile | **New cost calibration required before performance.** |

Frozen profiles preserve what was applied historically; they do not authorize reuse for another symbol or timeframe.

## Superseded-document map

| Historical artifact | Status | Current authority |
| --- | --- | --- |
| `PHASE5K_POLICY_EVENT_PROVENANCE.md` (v1) | Preserved, incomplete timestamp audit; not current provenance truth | `PHASE5K_SOURCE_AUDIT_CORRECTION.md`: v2, 24/24 BoJ timestamps verified. |
| Phase 5K v2 scalar state | Timestamps valid, scalar intentionally unfrozen | `PHASE5L_BOJ_SCALAR_CONVENTION_GATE.md` for scalar/regime decision. |
| `PHASE5H_CONSOLIDATED_HISTORY.md` | Superseded historical snapshot ending after invalid Run 3 | `PHASE5H_STATUS.md` and `PHASE5H_RUN4_RESULTS.md`. |
| `PHASE5H_COMPLETE_STATUS.md` | Superseded pre-Run-4 summary | `PHASE5H_STATUS.md` and `PHASE5H_RUN4_RESULTS.md`. |
| Phase 5D Run 1 account metrics | Preserved but account-level metrics invalid after insolvency | `PHASE5D_RUN2_RESULTS.md` and `PHASE5D_STATUS.md`. |

## Authoritative fingerprint index

Hashes below are copied from final artifacts; they are not regenerated or replaced by this closeout.

| Artifact / data | SHA-256 | What it protects |
| --- | --- | --- |
| Phase 5D/5E EURUSD/M15 research dataset | `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59` | Historical dataset identity for 5D/5E. |
| Phase 5C capture dataset | `0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9` | EURUSD/M15 calibration capture identity. |
| Phase 5C raw capture | `3ac7531d14360058e3988ba58c44a0c4b178bb4d362f0541595271a677dd3b49` | Raw calibration provenance. |
| Phase 5C spread profile | `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575` | 5D/5E historical spread assumption. |
| Phase 5C non-spread profile | `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36` | 5D/5E commission/swap assumption. |
| Phase 5E preregistration | `b5359b37c865ecf72666a62aee4d3849b8386ea5eb1b4c4df0d43fb9bf7dcd10` | 5E frozen design. |
| Phase 5G viability preregistration | `7bbeab4c4ee8b97aa555b52d13ef8a5b347b6350e3ac46ea1358efd522046e0d` | Availability-only viability protocol. |
| Phase 5G viability report | `2ed51e0cf7826cc1d390df7f1e8a1bdc778244be6d57de89ca2361d89254930d` | Descriptive multi-cell audit. |
| Phase 5H cost preregistration | `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c` | Frozen H1 cost protocol. |
| Phase 5H strategy preregistration | `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709` | Frozen H1 strategy protocol. |
| Phase 5H cost profile | `b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7` | Run 4 historical cost profile. |
| Phase 5H capture slice | `96025369147c81ce9c10df34b1505f263c3622085100502ec8ff238ecd44912e` | Run 4 calibration slice. |
| Phase 5H raw capture | `099e120c0c92062056961139fd08e207f82d4368caf7e9952a69c59584f1b738` | Run 4 raw provenance. |
| Phase 5H metadata | `9cb69f172b716b878957ecc1ee4267cdf0d3c37d8a613ceca5d88356e6ce3267` | Run 4 symbol/account metadata. |
| Phase 5K corrected BoJ v2 strict JSON | `a82a1369eedab35b2d5f2fd6273934046638e1087edc8dba14b2beb003d7f15e` | 24 verified official BoJ timestamp records. |

The Phase 5K v1 hashes remain historical/incomplete and are not authoritative for current source provenance.

## Reopen conditions and budget

Research may reopen **only** on genuinely new independent evidence, such as:

- a new economically motivated mechanism supported independently of current results;
- a new external dataset enabling a previously impossible causal hypothesis;
- a material market-structure change creating a new measurable mechanism; or
- new academic or empirical evidence sufficient to motivate a bounded hypothesis.

The following are not sufficient: another indicator, changed holding period, added filters, another available symbol, the best historical hour, reinterpretation of rejection, lower sample gates, or added variants until something passes.

If reopened, the default budget is **one mechanism family and at most two hypotheses**, unless a completely new research program is prospectively defined. Before any performance, require independent rationale, source/data provenance, temporal policy, applicable cost calibration, preregistration, tests, and explicit authorization.

## Current trading status

**0 CANDIDATES**  
DEMO strategy authorization: **NONE**  
LIVE strategy authorization: **NONE**  
LIVE: disabled.  
Research queue: empty.

No code path, roadmap, task, or closeout section authorizes an automatic next strategy, symbol, parameter grid, or Phase 6 search.

## Phase 5O activity record

New hypotheses: `0`  
New signals: `0`  
New backtests: `0`  
New performance: `0`  
New cost calibration: `0`  
Orders: `0`

**PHASE 5 RESEARCH PROGRAM CLOSED — 0 CANDIDATES — REOPEN ONLY ON NEW INDEPENDENT EVIDENCE**
