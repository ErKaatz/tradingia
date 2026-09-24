# Phase 5F — Mechanism & Cost Attribution

Status: **CLOSED — POST-HOC DESCRIPTIVE — NOT TESTED.** No strategy, variant,
parameter, filter, cost counterfactual, temporal split, order, or performance
rerun was created.

## Sources and integrity

The local machine-readable result is
`data/fx/research/results/phase5f_mechanism_attribution/phase5f_attribution.json`.
It contains 58 source-referenced rows: Phase 5D Run 2 development/validation
and Phase 5E inner A, inner B, aggregate development, and validation. Every
row retains source path/SHA-256, run id, and frozen dataset/cost/preregistration
fingerprints. The loader structurally rejects `test`, `untouched_test`, and
`untouched` paths or split names.

**UNTOUCHED TEST: UNTOUCHED.** No source artifact, signal, strategy, engine,
or dataset from the final test range was read.

## Observed gross versus costs

`gross / cost / net` is USD. The full split-level table, including every cost
component and per-trade identity, is in the JSON.

| Phase/family | Observed pattern | Descriptive mechanism |
|---|---|---|
| 5D trend | Gross negative in 3/4 splits; one +2.82 gross split had -74.88 net and 27.55x cost/gross | raw-negative plus cost destruction; insolvency |
| 5D mean reversion | Gross +27.47 to +51.62; costs 124.50 to 149.28; all net about -96 to -100 | positive-gross cost-destroyed; insolvency |
| 5D momentum | Momentum-16 gross negative both splits; momentum-4 gross +46.47/+11.04 but costs 146.36/111.00 | mixed raw-negative and cost destruction; insolvency |
| 5D session | Gross negative in all four rows (-26.96 to -45.44) | raw-negative; insolvency |
| 5E compression | 1–8 trades; net signs +, -, +, - across allowed splits | insufficient observation frequency |
| 5E session range | Gross negative except validation 01-08 +3.13 and 02-09 +43.25; only latter net +2.75 | mostly raw-negative; isolated net-positive not robust |
| 5E reversal | Gross positive in all rows (23.40–92.84), costs 119.30–183.16 and net negative | positive-gross cost-destroyed; insolvency |
| 5E impulse continuation | Gross negative in every row (-8.95 to -47.77) | raw-negative; insolvency |

The observed identity remains `net = gross - spread - slippage - commission -
swap`; commission and swap were zero.

## Break-even, turnover, side, temporal and concentration attribution

For every row JSON records `max(0, -net_pnl)` and per-trade break-even gross.
Examples: 5D momentum-4 validation $99.96/595 = $0.1680 per trade; 5E
reversal-32 inner B $99.46/707 = $0.1407; session-range-02-09 development
$99.71/340 = $0.2933. They are accounting gaps, not proposed changes.

Gross-positive 5E reversal rows have cost/gross 1.91x–5.10x; 5D mean
reversion 2.89x–4.53x; 5D momentum-4 validation 10.05x. This associates high
activity with cost burden but does not establish causality.

Long/short counts are observed for all rows; Phase 5D additionally stores
side net PnL. Phase 5E does not store side net PnL. Yearly records exist for
5E; Phase 5D Run 2 did not store yearly rows. Monthly, entry-hour, holding
duration distribution, loss concentration, side gross/cost/PF/expectancy, and
net-without-best/worst are `null`: artifacts have aggregates, not completed
trade rows. They were not reconstructed by rerunning strategies.

Observed split sign flips include compression 16-4 (+1.10 inner A, -0.42
inner B, +0.68 development, -0.31 validation) and session-range 02-09
(-58.18, -98.67, -99.71, +2.75). Neither changes a historical rejection.

## Required answers Q1–Q9

1. Persistent negative gross: 5D session breakout, 5E impulse continuation,
   and momentum-16.
2. Positive gross destroyed by costs: 5D mean reversion/momentum-4 and 5E
   reversal; also some trend/session/compression rows.
3. Insufficient sample: both compression-expansion variants.
4. Period sign changes: compression 16-4 and session-range 02-09.
5. Long/short asymmetry: only 5D side net supports comparison; 5E has counts
   only, so no stronger claim is supported.
6. Highest cost burden: reversal, mean-reversion and momentum-4 rows above.
7. Largest break-even gaps: insolvent rows require roughly $84–$100 aggregate
   gross improvement; JSON records per-trade amounts.
8. Concentration: positive-trade fields exist where saved; month/hour/loss
   sensitivity is unavailable without trade rows.
9. **NO — CURRENT EVIDENCE DOES NOT JUSTIFY FOLLOW-UP.** No evidence here can
   legitimately prescribe a new rule.

## Safety and disposition

LIVE is disabled. Zero DEMO opens/closes, `place_order`, `close_position`, or
MT5 operations occurred. Phase 5D remains 8 REJECT/0 candidate and Phase 5E
remains 8 REJECT/0 candidate; no retroactive candidate exists.
