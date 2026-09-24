# Phase 5H — EURUSD/H1 Cost Calibration Preregistration

Status: frozen before cost-statistics calculation.

## Scope and fixed capture interval

This is a read-only cost calibration for `EURUSD` / `H1`, not strategy
research. The fixed interval is `2025-03-01T00:00:00+00:00` through exclusive
`2025-08-30T00:00:00+00:00`. It is a recent six-month subwindow of Phase 5G's
already permitted common history and remains entirely before the protected
EURUSD/M15 untouched interval. The interval was selected by calendar recency
and six-month/UTC-hour coverage requirement, before observing this window's
spread statistics.

Only bridge read-only history, symbol metadata and account metadata are in
scope. No signal, strategy PnL, backtest, order, DEMO or LIVE endpoint is in
scope.

## Frozen data-quality and spread rules

The historical MT5 per-bar `spread` field is the observed spread source. Each
UTC-hour bucket requires at least **100 observed non-null spreads**. For every
bucket, capture count, missing count, median, P75, P95 and P99. The frozen
execution research profile is each hour's P95. A missing or insufficient
bucket remains `null`; it is never zero-filled and never receives a global
fallback. The calibration gate fails closed if any of 24 buckets is
insufficient, data validation has errors, or required metadata is absent.

## Frozen non-spread terms

- Commission: `NoCommission` only as a **RESEARCH ASSUMPTION** unless the
  current broker/account metadata supplies direct per-lot evidence. It is not
  asserted as a universal broker fact.
- Swap: capture current `swap_long`, `swap_short`, `swap_mode` and
  `swap_rollover3days`. Convert only supported MT5 points mode where profit
  currency equals account currency; otherwise fail closed.
- Slippage: `1` adverse point per fill, an **ASSUMPTION**, not a historical
  OHLC-derived estimate.

Metadata is captured from MT5 as authority: digits, point, tick size/value,
contract size, volume min/max/step, base/profit/margin currencies and server.
The local artifact uses strict JSON (`null`, never NaN/Infinity), includes
dataset/raw-capture/metadata/non-spread/cost-profile fingerprints and records
provenance.

Preregistration fingerprint: `a3f18e3876bd0b739d21fc5cb30ac722f58c9d8032099ef2d25831b4267b122c`.
