# Phase 5D — FX strategy baselines preregistration

Status: preregistered before any strategy performance was calculated.

## Dataset and splits

- Symbol/timeframe: `EURUSD` / `M15`, HFM MT5 Demo history.
- Dataset SHA-256: `5c6c65bf2fb127f63b08edc905eef61b583f4220dd7e7e0b2ad37ba0bc22dd59`.
- Total: `2022-09-01T00:00:00+00:00` to `2026-09-04T23:45:00+00:00`,
  99,597 bars.
- Development: `2022-09-01T00:00:00+00:00` to
  `2024-08-30T23:45:00+00:00`.
- Validation: `2024-09-02T00:00:00+00:00` to
  `2025-08-29T23:45:00+00:00`.
- Untouched test: `2025-09-01T00:00:00+00:00` to
  `2026-09-04T23:45:00+00:00`. It must not be executed or inspected in
  Phase 5D.

The availability scan found 35 unexpected gaps in the total data. They are
recorded and never filled; no variant may exclude them post-hoc.

## Common execution and costs

- Signal at bar *i* close, engine-enforced execution at bar *i+1* open.
- Fixed `0.01` lot; initial balance `100 USD`; one position maximum.
- Cost profile dataset SHA-256:
  `0735a45b0b6cf2a198ab2731ee5532390d5d750561f5b6580520e5d3b46ea5a9`.
- Spread profile fingerprint:
  `a658c5503b32687d05a4dbab6e5b5f0f64154e8d967a96c1265c6b2971938575`.
  Every fill uses the frozen UTC-hour P95 spread, not the observed bar spread.
- Non-spread fingerprint:
  `9acbcc180a63c76c90018b91bebeb9b2cc8d91907fe16bd6ec285d9185b24c36`.
  Commission is explicit `NoCommission`; frozen swap terms are retained.
- Adverse slippage: fixed 1 point per fill, an explicit conservative research
  assumption because no empirical HFM slippage distribution has been captured.
- All variants target `FLAT` from 20:00 through 00:45 UTC. This is a
  preregistered operational restriction to avoid an unverified rollover-hour
  / DST model; no position may be intentionally held overnight. It is not a
  performance-driven session filter.

## Run 2 account-model remediation

Run 1 was the original preregistered execution. Its trade-level negative PnL,
expectancy and profit-factor observations are preserved in the results and
ledger, but its account-level metrics are not interpretable because it allowed
trading after equity became non-positive.

Before the Run 2 performance rerun, the following deterministic correction is
preregistered. It changes no strategy, parameter, data, split, cost, lot,
signal timing, or active-window assumption:

- `balance` is realized account value; `equity` is balance plus the open
  position's conservative liquidation-value unrealized PnL (BID for LONG,
  ASK for SHORT), less accrued swap.
- After each bar's mark-to-market update, if equity is `<= 0`, record
  `INSOLVENCY` at that bar timestamp and terminate the backtest immediately.
- If a close realizes balance `<= 0`, terminate before any same-bar replacement
  entry. No subsequent entries, costs, or equity points are generated.
- An open position at terminal marking is not forcibly liquidated: no intrabar
  margin call, broker stop-out, or invented closing price is modeled. Its
  observed liquidation-value equity is retained as the terminal state.
- Terminal artifacts record `terminated_early`, reason, timestamp, final
  balance, final equity, insolvency flag and bars survived.
- For an insolvent account, reported total return is the explicit total-capital
  loss `-100%`; annualized return, volatility, Sharpe and Sortino are
  `null`/undefined. The raw equity trajectory is never clipped or rewritten.

This is a methodological rerun of the same eleven hypotheses, not eleven new
hypotheses. The untouched test remains prohibited.

## Variants and controls

Every non-control is symmetric LONG/SHORT.

| ID | Family | Rule / parameters |
|---|---|---|
| trend-ema-20-100 | Trend | EMA 20 versus EMA 100 |
| trend-ema-50-200 | Trend | EMA 50 versus EMA 200 |
| mean-z-20-2 | Mean reversion | close z-score, trailing 20, threshold 2.0 |
| mean-z-40-2 | Mean reversion | close z-score, trailing 40, threshold 2.0 |
| momentum-4 | Momentum | signed 4-bar return |
| momentum-16 | Momentum | signed 16-bar return |
| session-breakout-00-06 | Session | 00:00–05:45 UTC range, 06:00–19:45 breakout |
| session-breakout-07-10 | Session | 07:00–09:45 UTC range, 10:00–19:45 breakout |
| control-flat | Control | always flat |
| control-long | Control | long during the common active window |
| control-short | Control | short during the common active window |

No other parameter, filter, exit, sizing rule, pair, session, or optimizer is
in scope for this batch.

## Metrics and decisions

For development and validation separately: net PnL, return, max drawdown,
Sharpe, Sortino, profit factor, trade count, win rate, average win/loss,
expectancy, exposure, long/short count, gross PnL, spread/slippage/commission/
swap costs, and largest/top-five trade contribution.

Controls are descriptive and cannot be candidates. A non-control is a
`CANDIDATE` only if **both** development and validation have at least 30
trades, positive net PnL and expectancy, profit factor above 1, maximum
drawdown no worse than -20%, at least 10 LONG and 10 SHORT trades, and no
single trade contributes more than 30% of positive net PnL. Any other
completed variant is `REJECT`; a variant with fewer than 30 trades in either
split is `INSUFFICIENT SAMPLE`. No test result may change these rules.
Additionally, an insolvent non-control is automatically `REJECT` and cannot
be a candidate.
