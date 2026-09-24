# Phase 5H — Preregistered EURUSD/H1 Failed-Breakout Evaluation

Status: frozen before implementation performance or signal generation.

## Identity, costs and scope

Cell: `EURUSD` / `H1`. This study uses the Phase 5H EURUSD/H1 cost profile
`b23bb974e4ea3e7f200a7dee9548c9dcc0ef8168afc41fc14cc939c88ad565c7` and
cost preregistration `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c`.
The Phase 5G common-data scope is preserved. No EURUSD/M15 untouched data is
read. No strategy performance is included in this preregistration.

## Exact registry

Exactly two hypotheses, independently classified:

1. `daily-range-failed-breakout-long`
2. `daily-range-failed-breakout-short`

`control-flat` is permitted only as a non-hypothesis descriptive control. No
other family, variant, parameter, symbol or timeframe may be added.

## Causal event definition

The reference range is high/low of the immediately preceding completed UTC
calendar day. It is finalized only when the next UTC day begins; current-day
bars never enter their own reference range.

Long: an H1 close strictly below the prior-day low creates a pending downside
break. Only the immediately following chronological eligible H1 close can
confirm it. If that close is strictly inside `(prior-day low, prior-day high)`,
emit a LONG signal at its close; otherwise the event expires with no signal.

Short is symmetric: a close strictly above prior-day high, followed only by
the immediately next eligible H1 close strictly inside the same open range,
emits SHORT. Equality with a boundary is not inside. There is no intrabar
inference, wick trigger, delayed re-entry or unbounded confirmation window.

Execution is next-bar open. Each event owns one position, no pyramiding,
averaging, stacking, immediate reversal or overlapping event. While held, all
new events are ignored. The holding period is exactly four H1 bars, then FLAT.
There is no stop, target, trailing stop or break-even exit.

## Flat, rollover and account policy

There is no special H1 time-of-day flat window: it would be an untested
hour filter and is not necessary to define the daily reference/event state.
Positions may cross a UTC daily boundary; frozen swap terms apply whenever
the engine's rollover policy charges them. This does not omit swap. Initial
balance is USD 100, fixed size is 0.01 lot, adverse slippage is one point per
fill, commission is frozen NoCommission research assumption, and insolvency
at equity <= 0 terminates the split.

## Fixed temporal policy

| Split | Start | End exclusive |
| --- | --- | --- |
| Inner development A | 2022-09-01 | 2023-09-01 |
| Inner development B | 2023-09-01 | 2024-09-01 |
| Aggregate development | 2022-09-01 | 2024-09-01 |
| Validation | 2024-09-01 | 2025-08-30 |
| Future test | NOT ASSIGNED | NOT ASSIGNED |

## Minimum sample and candidate rules

Each directional hypothesis is independent. It requires at least 20 aggregate
development trades and at least 8 trades in each inner-development split and
validation. The threshold is intentionally conservative for a daily event and
prevents conclusions from 5–10 observations.

A candidate must, in every required split: remain solvent; meet its sample
minimum; have net PnL > 0; expectancy > 0; PF > 1; signed max drawdown >=
-0.20; and, only if gross reference PnL > 0, total costs/gross reference PnL
<= 0.75 (non-positive gross fails). Across annual records, every year with at
least 5 trades must have positive net PnL, no positive year may contribute
more than 70% of summed positive-year PnL, and the largest positive trade may
not exceed 25% of total positive PnL. Missing required fields fail closed.

## Observability and protection

Every future run must write the Phase 5G contract bundle: `manifest.json`,
`summary.json`, `trades.jsonl`, with complete side/time/price/gross-cost-net
decomposition and fingerprints. Untouched EURUSD/M15 remains UNTOUCHED; no
future test is assigned here. Historical performance is NOT RUN.

Preregistration fingerprint: `212993340e68c33c78fbb10dbc618c4c10acc6e21ffd81b94faa6571e32fc709`.
