# Phase 5E — Event-driven FX research preregistration

Status: design frozen before any Phase 5E historical performance calculation.

## Scope and hypothesis

Phase 5D rejected global, continuously exposed EURUSD M15 baselines. Phase 5E
does not repair them. It asks a separate question: whether sparse, causal
temporal or structural events have any economically usable information after
the same conservative execution assumptions. No result is implied.

## Frozen data, execution, and account rules

- Symbol/timeframe: `EURUSD` / `M15`; dataset SHA-256
  `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59`.
- Frozen Phase 5C spread-profile fingerprint:
  `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575`.
  Each fill uses UTC-hour P95 spread.
- Frozen non-spread fingerprint:
  `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36`:
  explicit `NoCommission`, frozen side-aware swap terms, and one adverse
  slippage point per fill.
- USD 100 initial balance, 0.01 fixed lot, one position maximum.
- Signal at close, engine-enforced next-bar-open execution. Targets are FLAT
  20:00–00:45 UTC; no intended overnight position.
- Balance is realized value; equity is conservative liquidation value. At
  `equity <= 0`, record `INSOLVENCY` and terminate: no later entry, cost, or
  curve point. No invented intrabar margin call, stop-out, or terminal fill.
- Undefined metrics are `null`, never `NaN`.

## Temporal protocol

| Evaluation | UTC interval | Purpose |
|---|---|---|
| Development inner A | 2022-09-01 → 2023-08-31 23:45 | Internal stability check |
| Development inner B | 2023-09-01 → 2024-08-30 23:45 | Internal stability check |
| Development aggregate | 2022-09-01 → 2024-08-30 23:45 | Frozen aggregate result |
| Validation, one run | 2024-09-02 → 2025-08-29 23:45 | Post-freeze evaluation |
| Untouched test | 2025-09-01 → 2026-09-04 | Structurally prohibited |

No Phase 5E code may load, inspect, calculate a trade, metric, chart, or
diagnostic from test. The runner rejects `test` before any data access.

## Exact variants

| ID | Hypothesis and causal event | Frozen parameters |
|---|---|---|
| compression-expansion-16-4 | A compressed M15 range followed by a close outside the prior range may expand directionally. | range 4 / ATR 16 <= 0.75; prior-range breakout 4; hold 4 bars |
| compression-expansion-24-6 | Same structural hypothesis at a distinct, predeclared scale. | range 6 / ATR 24 <= 0.70; prior-range breakout 6; hold 4 bars |
| session-range-01-08 | An early-Asian range may resolve during an early-European entry window. | build 01:00–04:45; enter 08:00–10:45; one event/day; hold 4 |
| session-range-02-09 | Same session-transition hypothesis at a distinct predeclared UTC range. | build 02:00–05:45; enter 09:00–11:45; one event/day; hold 4 |
| expansion-reversal-32-2p5-2 | A standardized large M15 impulse may partially reverse immediately. | prior-return normalization 32; abs z >= 2.5; contrarian; hold 2 |
| expansion-reversal-48-2p25-4 | Same reversal hypothesis at a distinct scale. | normalization 48; abs z >= 2.25; contrarian; hold 4 |
| impulse-continuation-32-2p5-2 | A qualifying impulse may briefly continue, unlike Phase 5D continuous momentum. | normalization 32; abs z >= 2.5; same direction; hold 2 |
| impulse-continuation-48-2p25-4 | Same event-driven continuation hypothesis at a distinct scale. | normalization 48; abs z >= 2.25; same direction; hold 4 |
| control-flat | Accounting control. | always FLAT |

An event is computed only from the current and prior bars, is consumed while
its fixed holding target is active, and never opens a second simultaneous
position. No variants, filters, cooldowns, parameters, pairs or timeframes
outside this table are in scope.

## Metrics and candidate rules

Record per split and calendar year: trade counts; gross reference PnL; net
PnL; expectancy; PF; long/short count; spread, slippage, commission and swap;
total costs; cost efficiency; exposure; concentration; equity and insolvency.

`max_drawdown` uses the existing signed equity-curve convention: zero at a
peak and negative below it. Therefore the fixed criterion is
`max_drawdown >= -0.20`.

Cost efficiency is evaluated only when `gross_reference_pnl > 0`; otherwise
it fails. Its criterion is `total_costs / gross_reference_pnl <= 0.75`.

Year concentration uses only positive year PnLs in its denominator. For years
with at least ten trades, at least two must have positive net PnL; no one such
positive year may contribute over 70% of the sum of all positive yearly PnL.
Negative years remain visible and do not enter that positive-PnL denominator.

A non-control is `CANDIDATE` only if development aggregate **and** validation
are solvent, have >=30 trades, positive net PnL/expectancy, PF > 1,
`max_drawdown >= -0.20`, >=10 long and >=10 short trades, largest positive
trade contribution <=30%, and pass cost efficiency. Both internal development
splits must be solvent with positive net PnL. It must also pass the yearly
stability/concentration rule above. Anything else is `REJECT`; controls are
never candidates. No candidate is authorized to consume test automatically.
