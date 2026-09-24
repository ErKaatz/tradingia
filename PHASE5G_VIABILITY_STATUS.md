# Phase 5G — Track B Status

Status: closed — availability capture and preregistered descriptive
microstructure audit complete.

The complete local availability evidence is ignored from Git at
`data/fx/research/phase5g_availability/availability_ledger.json`.
The ignored machine-readable report is
`data/fx/research/results/phase5g_viability/viability_report.json`, SHA-256
`2ed51e0cf7826cc1d390df7f1e8a1bdc778244be6d57de89ca2361d89254930d`.

## Frozen window and availability

The common eligible window is `2022-09-01T00:00:00Z` through exclusive
`2025-08-30T00:00:00Z`; it is entirely before the protected EURUSD/M15
untouched strategy interval. EURUSD/GBPUSD/USDJPY M15 and H1 each cover it.
All M5 cells begin only in May 2025 and are `INSUFFICIENT_DATA`; they did not
shorten the study. No data was repaired or interpolated.

## Structural labels

| Cell | Coverage | Median spread/range | P95 spread/median-range | Label |
| --- | ---: | ---: | ---: | --- |
| EURUSD H1 | 0.9923 | 0.1327 | 0.1845 | VIABLE_FOR_FUTURE_RESEARCH |
| EURUSD M15 | 0.9915 | 0.2727 | 0.4545 | BORDERLINE |
| GBPUSD H1 | 0.9923 | 0.1103 | 0.1724 | VIABLE_FOR_FUTURE_RESEARCH |
| GBPUSD M15 | 0.9912 | 0.2394 | 0.3803 | VIABLE_FOR_FUTURE_RESEARCH |
| USDJPY H1 | 0.9923 | 0.0936 | 0.1281 | VIABLE_FOR_FUTURE_RESEARCH |
| USDJPY M15 | 0.9914 | 0.1939 | 0.3061 | VIABLE_FOR_FUTURE_RESEARCH |
| EURUSD / GBPUSD / USDJPY M5 | n/a | n/a | n/a | INSUFFICIENT_DATA |

The ratios are dimensionless: broker spread points are multiplied by the
captured symbol point before comparison to OHLC price ranges. They measure
microstructure burden, not edge or expected return. Unexpected gaps were
recorded (H1: 6 each; M15: EURUSD 27, GBPUSD 45, USDJPY 34), all below the
frozen quality ceiling of 50.

## Decision matrix

Q1: Yes. Track A now requires deterministic manifest, summary and complete
trade JSONL records so future attribution need not rerun an experiment.

Q2: Six cells have sufficient data: all M15/H1 cells. The three M5 cells do
not.

Q3/Q4: No eligible cell crosses the frozen structural-unattractive burden
threshold; M5 cannot be assessed due to insufficient history.

Q5: H1 has a lower burden than its M15 counterpart in all three symbols. This
only justifies potential future research, not an assertion of profitability.

Q6: EURUSD/M15 remains structurally reasonable but is `BORDERLINE`, despite
the previous strategy hypotheses being rejected.

Q7: YES — FUTURE HYPOTHESIS DESIGN JUSTIFIED, subject to a new independent
preregistration and no reuse of this finding as a strategy result.

NO STRATEGY PERFORMANCE WAS MEASURED. No strategy, signal, backtest, PnL,
candidate selection, untouched test, DEMO order or LIVE order was executed in
Track B. LIVE remains disabled and the bridge use was GET history/metadata
only: zero orders, zero demo-open/demo-close, zero place/close-position calls.
