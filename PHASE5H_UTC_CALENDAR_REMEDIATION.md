# Phase 5H — Prior UTC Calendar-Day Remediation

## Root cause

Run 3 used a previous-observed-day lookup in
`daily_range_failed_breakout`: at the first observed bar of a new date it
promoted the range accumulated for the prior **observed** date. When weekend
dates had no bars, this carried Friday's range into Monday.

Primary classification:

```text
PRIOR_CALENDAR_DAY_LOOKBACK_VIOLATION
```

## Corrected frozen interpretation

For every current UTC date `D`, the only permitted reference is `D - 1 day`.
The implementation keeps completed ranges keyed by their actual UTC date and
looks up exactly that calendar key. It does not group-shift, forward-fill, or
walk backward through missing dates.

If `D - 1` contains no bars, the prior range is unavailable. Every bar on `D`
is FLAT for this strategy: it cannot create B0, confirm B1, or preserve a
pending state across the unavailable date.

## Regression coverage

Tests now cover:

- Friday with bars, empty Saturday/Sunday, then Monday: no Monday event;
- consecutive observed calendar dates: the exact prior day is available;
- multiple empty dates: no backward lookup and no pending carry-forward;
- Dec 31 → Jan 1 and month boundary arithmetic via `date - timedelta(days=1)`;
- existing Run 1 four-target hold and Run 2 target-length protections.

`FxBar.timestamp_utc` rejects naive or non-UTC timestamps at construction, so
calendar identity is UTC-only.

## Structural EURUSD/H1 calendar audit

This audit read date identities only. It generated no signals, ran no engine,
and calculated no PnL.

| Item | Result |
| --- | ---: |
| Observed UTC dates | 777 |
| Date range | 2022-09-01 through 2025-08-29 |
| Missing calendar dates inside range | 317 |
| Missing weekend dates | 312 |
| Missing non-weekend dates | 5 |
| Observed dates whose exact prior date is unavailable | 159 |
| Partial UTC dates | 14 |

Non-weekend missing examples: 2022-12-26, 2023-12-25, 2024-01-01,
2024-12-25, 2025-01-01. Weekend examples begin 2022-09-03,
2022-09-04, 2022-09-10, and 2022-09-11.

Of the 777 observed dates, 763 contain 24 bars. Partial dates have 18, 19,
22, or 23 bars (14 dates total). Examples include 2022-11-04 (23),
2023-07-07 (19), 2023-12-26 (18), and 2024-12-31 (22).

No new completeness threshold has been introduced. Per the frozen rule, an
exact prior UTC date that contains any bars supplies its range exclusively;
an exact prior UTC date with zero bars is unavailable and never replaced by
an older date.

## Status

Runs 1–3 remain `INVALID — PRESERVED`. Run 4 is reserved as
`phase5h_run4_preregistered_failed_breakout` and is **NOT RUN**.
