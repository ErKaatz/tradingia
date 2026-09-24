# Phase 5F — Mechanism & Cost Attribution Preregistration

Status: frozen before Phase 5F aggregation.

## Purpose and immutable scope

Phase 5F is a descriptive attribution of already observed Phase 5D Run 2 and
Phase 5E artifacts. It neither creates nor evaluates a strategy, parameter,
filter, alternative cost assumption, temporal split, sizing rule, or execution
rule. Historical `REJECT` classifications remain immutable and no result can
become a candidate.

## Permitted inputs

- Phase 5D Run 2: `development` and `validation` JSON under
  `data/fx/research/results/phase5d_run2_insolvency_policy/`.
- Phase 5E: `development_inner_a`, `development_inner_b`, `development`, and
  `validation` JSON under
  `data/fx/research/results/phase5e_run1_preregistered_events/`.

The source-artifact path, SHA-256, run id, split, dataset fingerprint, cost
fingerprints and preregistration fingerprint are retained in the derived
output. Controls are excluded from variant/family conclusions and may only be
retained as references.

## Explicit exclusion

The final untouched range (`2025-09-01` through `2026-09-04`) is not read,
enumerated, or processed. No source file below an `untouched_test`/`test`
split is accepted by the attribution loader. No signals are generated and no
backtest engine, execution client, MT5 bridge, DEMO order, or LIVE operation
is invoked.

## Frozen descriptive analyses

For every permitted non-control artifact, derive only from observed fields:

1. Gross reference PnL, all cost components, total costs, net PnL, trade
   count, gross/net/cost per trade, and cost-to-gross ratio only when gross is
   positive.
2. Failure mechanism: `NEGATIVE_GROSS_SIGNAL`,
   `POSITIVE_GROSS_COST_DESTROYED`, `POSITIVE_NET_BUT_NOT_ROBUST`, or
   `INSUFFICIENT_SAMPLE`, with separate flags for insufficient sample,
   insolvency, and cross-split sign instability.
3. Accounting break-even identity: `max(0, -net_pnl)` in USD and per trade;
   price points per trade only if supported by a frozen artifact conversion.
4. Turnover/cost burden, observed side counts and (where an artifact contains
   them) side PnL, yearly records, and positive-trade concentration fields.
5. Family summaries and the predeclared compression, session, reversal, and
   momentum/continuation comparisons.

Monthly attribution, entry-hour attribution, holding-duration distribution,
side gross/cost/PF/expectancy, and loss concentration are emitted as `null`
with an availability reason unless source artifacts already contain completed
trade rows carrying those fields. They will not be reconstructed by rerunning
signals or an engine.

## Interpretation discipline

All observations are post-hoc descriptive, not causal estimates and not input
to retroactive selection. Ratios with non-positive gross or an invalid
denominator are `null`, never `NaN`. A follow-up may only be recommended as
`YES — DESIGN NEW PREREGISTERED HYPOTHESIS` or `NO — CURRENT EVIDENCE DOES
NOT JUSTIFY FOLLOW-UP`; it cannot be evaluated in this phase.

## Variants in scope

Phase 5D: `trend-ema-20-100`, `trend-ema-50-200`, `mean-z-20-2`,
`mean-z-40-2`, `momentum-4`, `momentum-16`, `session-breakout-00-06`, and
`session-breakout-07-10`.

Phase 5E: `compression-expansion-16-4`, `compression-expansion-24-6`,
`session-range-01-08`, `session-range-02-09`,
`expansion-reversal-32-2p5-2`, `expansion-reversal-48-2p25-4`,
`impulse-continuation-32-2p5-2`, and `impulse-continuation-48-2p25-4`.
