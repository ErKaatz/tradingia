# Phase 5D — Multiple-testing ledger

All entries below are preregistered. Run 1 is preserved: it was the original
execution and allowed the account to continue below zero, so its account-level
metrics are methodologically invalid. Its negative trade-level PnL,
expectancy, and profit-factor observations remain factual. Run 2 is the
preregistered insolvency-policy remediation of these same eleven hypotheses;
it does not consume additional multiple-testing budget. The untouched test has
not been read or executed.

| ID | Family | Parameters | Status | Result |
|---|---|---|---|---|
| trend-ema-20-100 | trend | fast=20, slow=100 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| trend-ema-50-200 | trend | fast=50, slow=200 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| mean-z-20-2 | mean reversion | window=20, threshold=2.0 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| mean-z-40-2 | mean reversion | window=40, threshold=2.0 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| momentum-4 | momentum | lookback=4 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| momentum-16 | momentum | lookback=16 | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| session-breakout-00-06 | session | range=00:00–05:45 UTC | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| session-breakout-07-10 | session | range=07:00–09:45 UTC | Run 1 observed; Run 2 preregistered | Run 1 reject (negative PnL/expectancy, PF < 1 both splits) |
| control-flat | control | flat | Run 1 observed; Run 2 preregistered | Run 1: 0 trades, 0 PnL, solvent |
| control-long | control | long active window | Run 1 observed; Run 2 preregistered | descriptive control; rerun pending |
| control-short | control | short active window | Run 1 observed; Run 2 preregistered | descriptive control; rerun pending |

## Run 2 final disposition

The remediation run completed under `phase5d_run2_insolvency_policy` without
accessing untouched test. `control-flat` is `CONTROL` (0 trades, 0 PnL,
solvent). `control-long` and `control-short` are descriptive `CONTROL`s and
became insolvent in both splits. Every one of the eight non-controls is
`REJECT`; no candidate exists. Full split-level terminal facts are preserved
in `PHASE5D_RUN2_RESULTS.md` and in the separate Run 2 JSON artifact root.
