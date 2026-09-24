# Phase 5D — Run 2 results (insolvency-policy remediation)

Run ID: `phase5d_run2_insolvency_policy`.

This is a methodological rerun of the eleven already-preregistered Phase 5D
observations, not a new hypothesis batch. It retains exactly the frozen data,
splits, variants, costs, fixed 0.01 lot, USD 100 initial balance, one-point
adverse slippage, signal timing, and active window. The untouched test split
was neither read nor executed.

Run 1 artifacts remain in `data/fx/research/results/phase5d/`. They are not
overwritten. Their negative trade-level PnL, expectancy, and PF observations
remain factual; only account-level metrics were invalid because simulated
trading continued after equity became non-positive.

## Corrected account policy

Equity is balance plus conservative liquidation-value unrealized PnL. At the
first M15 mark where equity is at or below zero, Run 2 records `INSOLVENCY`
and stops. It does not manufacture intrabar stop-outs or a closing fill. If a
close realizes non-positive balance, no same-bar replacement entry is allowed.
The terminal artifacts include final balance/equity, timestamp, bars survived,
and insolvency state. Insolvent results report total loss of capital as -100%;
annualized return, volatility, Sharpe and Sortino are explicitly `null`.

## Results

`P/L` below is realized completed-trade net PnL up to the terminal mark; the
terminal artifact's `final_equity` additionally retains any open-position
liquidation loss. `I` denotes `INSOLVENCY` and the timestamp of the first
terminal mark. All eight non-controls are `REJECT`; no candidate exists.

| Variant | Development P/L / terminal state | Validation P/L / terminal state | Decision |
|---|---:|---:|---|
| control-flat | 0 / solvent | 0 / solvent | CONTROL |
| control-long | -99.14 / I 2024-03-22 03:30 | -98.80 / I 2025-01-02 12:30 | CONTROL |
| control-short | -89.87 / I 2023-07-12 17:30 | -96.39 / I 2025-06-26 06:00 | CONTROL |
| trend-ema-20-100 | -89.26 / I 2022-12-15 19:00 | -99.10 / I 2025-05-06 09:30 | REJECT |
| trend-ema-50-200 | -99.47 / I 2022-12-22 10:30 | -74.88 / solvent | REJECT |
| mean-z-20-2 | -96.32 / I 2023-03-10 16:30 | -97.03 / I 2025-03-14 13:15 | REJECT |
| mean-z-40-2 | -99.53 / I 2023-04-18 10:00 | -97.66 / I 2025-06-12 12:00 | REJECT |
| momentum-4 | -99.89 / I 2022-11-01 11:30 | -99.96 / I 2024-10-15 15:00 | REJECT |
| momentum-16 | -99.02 / I 2022-10-13 15:45 | -99.57 / I 2024-10-18 12:45 | REJECT |
| session-breakout-00-06 | -99.05 / I 2023-01-23 12:30 | -99.86 / I 2025-01-29 08:00 | REJECT |
| session-breakout-07-10 | -98.90 / I 2023-01-19 14:45 | -99.82 / I 2025-01-17 15:15 | REJECT |

Timestamps are UTC. Exact, machine-readable artifacts are stored separately
under `data/fx/research/results/phase5d_run2_insolvency_policy/` and validate
the dataset, spread-profile, non-spread-cost, and preregistration fingerprints.
They are strict JSON: undefined values are `null`, never `NaN`.

## Formal disposition

Phase 5D can now be formally closed: every preregistered non-control has been
evaluated under the corrected account model and rejected by the fixed rules;
none may advance to untouched test. Phase 5E may begin only as a separately
preregistered research phase, with no reuse of the untouched test results.
