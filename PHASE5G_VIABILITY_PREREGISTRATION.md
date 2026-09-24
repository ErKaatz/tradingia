# Phase 5G — Track B Viability Preregistration

Status: frozen after the availability-only capture on 2026-09-07.

## Scope

This is a market/timeframe data-quality and microstructure audit only. It does
not create strategies or signals, calculate strategy PnL, select by
profitability, evaluate the EURUSD/M15 untouched test, or use DEMO/LIVE order
endpoints.

The frozen universe is exactly EURUSD, GBPUSD and USDJPY crossed with M5, M15
and H1. No additional symbol or timeframe may be added.

## Availability evidence and mechanical window rule

The availability probe requested `2022-09-01T00:00:00+00:00` through the
exclusive fixed cap `2025-08-30T00:00:00+00:00`, by read-only bridge GET calls
below its 20,000-bar limit. The cap is before the protected EURUSD/M15
untouched-strategy interval (`2025-09-01` through `2026-09-04`).

A cell is `ELIGIBLE` if it has no capture error and its observed temporal
envelope covers at least 24 full calendar months before the cap. Otherwise it
is `INSUFFICIENT_DATA`. The selected window is the maximum common temporal
envelope: maximum observed first timestamp across eligible cells through the
minimum exclusive end across eligible cells, capped at the fixed date. It must
itself be at least 24 full calendar months. Observed gaps are recorded but do
not permit date cherry-picking at this selection stage; their quality impact
is assessed only after this document is frozen.

Applying that rule to the availability ledger selects:

`2022-09-01T00:00:00+00:00` through `2025-08-30T00:00:00+00:00` (end exclusive).

Eligible cells: EURUSD/M15, EURUSD/H1, GBPUSD/M15, GBPUSD/H1, USDJPY/M15,
USDJPY/H1. M5 for all three symbols is `INSUFFICIENT_DATA`, because the
observed capture begins in May 2025 and cannot supply 24 months. It is not
used to shorten the selected study.

## Post-freeze metrics, definitions and labels

Only for the selected eligible cells and selected window, later code may
calculate coverage, gaps, spread median/P75/P95/P99, OHLC movement/range,
spread-to-movement ratios, and UTC-hour microstructure summaries. Prices and
spreads must remain in their native broker point/price units; no cross-symbol
economic comparison is implied without a separately frozen conversion.

Coverage is the observed bar count divided by the weekday-only nominal bar
slots between the actual first and last bar (Monday 00:00 through Friday
23:59 UTC); it is a reproducible availability proxy, not a holiday calendar.
The primary dimensional ratio is `spread_price / bar_range_price`, summarized
as median spread divided by median range and P95 spread divided by median
range. `spread_price = spread_points * point`; no conversion is guessed when
the point is absent.

The descriptive label is frozen as follows. A cell has adequate data quality
only when it has at least 500 bars, coverage >= 0.98, no capture/validation
errors and at most 50 unexpected gaps. It is `VIABLE_FOR_FUTURE_RESEARCH` if
adequate and median spread/range <= 0.25 and P95-spread/median-range <= 1.00;
`BORDERLINE` if adequate and those values are <= 0.50 and <= 2.00;
otherwise it is `STRUCTURALLY_UNATTRACTIVE`. A failed availability rule remains
`INSUFFICIENT_DATA`. Labels are not candidate selection, are never an
instruction to trade, and cannot use strategy performance.

## Data and execution safeguards

Input evidence is the ignored local availability ledger at
`data/fx/research/phase5g_availability/availability_ledger.json`; its cell
fingerprints and raw-capture hashes are the source identity. The bridge
transport uses only `GET /v1/history/{symbol}`. No account, quote, order,
position, DEMO or LIVE endpoint is needed by this track.

Preregistration fingerprint: `7bbeab4c4ee8b97aa555b52d13ef8a5b347b6350e3ac46ea1358efd522046e0d`.
It is SHA-256 of this document with the fingerprint value represented by the
literal placeholder `TO_BE_FILLED_BY_FREEZE_TOOL`, avoiding a self-referential
hash.
