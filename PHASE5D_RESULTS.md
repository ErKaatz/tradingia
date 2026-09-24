# Phase 5D — Preregistered baseline results

## Scope and integrity

Only the preregistered development and validation intervals were executed.
The untouched test interval was not selected by the runner and was not read for
performance. Dataset and Phase 5C fingerprints matched their preregistered
values. No orders were sent and LIVE remained disabled.

## Results

| Variant | Dev net PnL | Validation net PnL | Dev/Val trades | Dev/Val PF | Classification |
|---|---:|---:|---:|---:|---|
| control-flat | 0.00 | 0.00 | 0 / 0 | n/a / n/a | CONTROL |
| control-long | -118.27 | -15.84 | 519 / 258 | 0.881 / 0.970 | CONTROL |
| control-short | -120.27 | -102.84 | 519 / 258 | 0.879 / 0.818 | CONTROL |
| trend-ema-20-100 | -327.42 | -115.71 | 1080 / 541 | 0.781 / 0.854 | REJECT |
| trend-ema-50-200 | -300.48 | -74.88 | 752 / 360 | 0.763 / 0.882 | REJECT |
| mean-z-20-2 | -420.35 | -191.40 | 2816 / 1296 | 0.544 / 0.592 | REJECT |
| mean-z-40-2 | -368.77 | -112.56 | 2358 / 1053 | 0.592 / 0.731 | REJECT |
| momentum-4 | -1920.76 | -923.62 | 9614 / 4792 | 0.566 / 0.609 | REJECT |
| momentum-16 | -985.38 | -534.53 | 5108 / 2599 | 0.650 / 0.652 | REJECT |
| session-breakout-00-06 | -393.59 | -189.15 | 1911 / 891 | 0.719 / 0.716 | REJECT |
| session-breakout-07-10 | -273.46 | -230.55 | 1584 / 821 | 0.773 / 0.648 | REJECT |

Every non-control has enough trades but fails preregistered candidate rules:
both splits have negative net PnL and expectancy and profit factor below one.
No candidate exists. The flat control has zero trades and zero PnL as expected.

## Methodological finding — closure blocked

The fixed 100 USD account can fall below zero in these unconstrained baseline
simulations. The current engine continues trading after that point, so generic
return, annualized-return, Sharpe, Sortino, volatility, drawdown and exposure
values can become mathematically invalid or misleading (including `NaN`, and
annualized return reported as -100%). This does **not** rescue any rejected
baseline: their negative PnL and PF below one are direct trade-level facts.

However, it prevents formal Phase 5D closure because the promised complete,
interpretable metric report is not yet valid. The correct next step is a
pre-performance engine/research-account policy for insolvency (for example,
stop when equity reaches zero), with tests and a new preregistered rerun. The
existing development and validation observations remain in the ledger; they
must not be discarded or silently replaced. The untouched test remains
unconsumed.
