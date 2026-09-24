# Phase 5K — BoJ Source Audit Correction (v2)

Status: **timestamps corrected; BoJ scalar still blocking**.

## Root cause

Phase 5K v1 inspected the official past-meeting calendar, annual catalogs and
supporting PDFs, but did not follow and parse every individual BoJ HTML decision
page. Those pages expose `Release dates and times:`. v1 therefore mistook an
uninspected field for an absent field. It is preserved as incomplete audit
history at `data/fx/research/events/policy_rates/boj_policy_events.json`.

## Corrected source hierarchy and byte provenance

For each scheduled MPM: official BoJ past-MPM calendar → annual Statement
catalog → individual official HTML decision page → supporting PDF only if
needed. Only `boj.or.jp` was used; HTML has priority for release time.

All 24 raw official HTML pages were downloaded on `2026-09-08T00:00:00+00:00`
and retained outside Git at
`data/fx/research/events/policy_rates/phase5k_policy_events_v2/boj_sources/`.
Every v2 record retains official URL, retrieval timestamp and source SHA-256.
The v2 strict JSON SHA-256 is
`a82a1369eedab35b2d5f2fd6273934046638e1087edc8dba14b2beb003d7f15e`.

## 24-event timestamp completeness

All rows are `VERIFIED_OFFICIAL_TIME`, local timezone `Asia/Tokyo`; scalar is
unfrozen pending a separate regime-coherence decision. URL suffixes are under
`https://www.boj.or.jp/en/mopo/mpmdeci/state_<year>/`.

| Event | URL suffix | Title | Local | UTC | Instrument |
| --- | --- | --- | --- | --- | --- |
| 2022-09-22 | k220922a.htm | Statement | 11:51 JST | 02:51 UTC | short-term policy rate |
| 2022-10-28 | k221028a.htm | Statement | 11:50 JST | 02:50 UTC | short-term policy rate |
| 2022-12-20 | k221220a.htm | Statement | 12:01 JST | 03:01 UTC | short-term policy rate |
| 2023-01-18 | k230118a.htm | Statement | 11:40 JST | 02:40 UTC | short-term policy rate |
| 2023-03-10 | k230310a.htm | Statement | 11:30 JST | 02:30 UTC | short-term policy rate |
| 2023-04-28 | k230428a.htm | Statement | 13:00 JST | 04:00 UTC | short-term policy rate |
| 2023-06-16 | k230616a.htm | Statement | 11:47 JST | 02:47 UTC | short-term policy rate |
| 2023-07-28 | k230728a.htm | Statement | 12:28 JST | 03:28 UTC | short-term policy rate |
| 2023-09-22 | k230922a.htm | Statement | 11:52 JST | 02:52 UTC | short-term policy rate |
| 2023-10-31 | k231031a.htm | Statement | 12:27 JST | 03:27 UTC | short-term policy rate |
| 2023-12-19 | k231219a.htm | Statement | 11:49 JST | 02:49 UTC | short-term policy rate |
| 2024-01-23 | k240123a.htm | Statement | 12:09 JST | 03:09 UTC | short-term policy rate |
| 2024-03-19 | k240319a.htm | Framework change | 12:35 JST | 03:35 UTC | transition |
| 2024-04-26 | k240426a.htm | Statement | 12:22 JST | 03:22 UTC | overnight-call guideline |
| 2024-06-14 | k240614a.htm | Statement | 12:23 JST | 03:23 UTC | overnight-call guideline |
| 2024-07-31 | k240731a.htm | Guideline/JGB plan | 12:56 JST | 03:56 UTC | overnight-call guideline |
| 2024-09-20 | k240920a.htm | Statement | 11:52 JST | 02:52 UTC | overnight-call guideline |
| 2024-10-31 | k241031a.htm | Statement | 11:48 JST | 02:48 UTC | overnight-call guideline |
| 2024-12-19 | k241219a.htm | Statement | 11:52 JST | 02:52 UTC | overnight-call guideline |
| 2025-01-24 | k250124a.htm | Guideline change | 12:23 JST | 03:23 UTC | overnight-call guideline |
| 2025-03-19 | k250319a.htm | Statement | 11:25 JST | 02:25 UTC | overnight-call guideline |
| 2025-05-01 | k250501a.htm | Statement | 12:02 JST | 03:02 UTC | overnight-call guideline |
| 2025-06-17 | k250617a.htm | Statement | 12:31 JST | 03:31 UTC | overnight-call guideline |
| 2025-07-31 | k250731a.htm | Statement | 11:57 JST | 02:57 UTC | overnight-call guideline |

Summary: 24 scheduled / 24 verified times / 0 missing / 0 ambiguous / 0
frozen scalar values.

## JST→UTC and scalar-regime gate

UTC conversion uses `zoneinfo` for `Asia/Tokyo`, not handwritten arithmetic:
11:51 JST → 02:51 UTC; 12:35 JST → 03:35 UTC; 11:48 JST → 02:48 UTC.

Before 2024-03-19, official Statements define a minus-0.1 percent short-term
policy interest rate applied to Policy-Rate Balances. The official March 19
framework document says negative-rate policy and QQE/YCC ended, identifies the
short-term rate as the primary tool, and announces an uncollateralized overnight
call-rate guideline around 0–0.1 percent, effective March 21. Post-transition
documents use that guideline.

**Can one coherent scalar be defined now? NO.** A midpoint, lower/upper bound,
or splice across Policy-Rate-Balances and the overnight-call-rate guideline is
an extra economic convention not established by these sources. Thus no v2
WIDENS/NARROWS/UNCHANGED records or differential feed are emitted.

## Tests and safety

The parser accepts Statement, Framework Change and Guideline Change titles;
fails closed for absent/ambiguous release sections; and archived official HTML
fixtures verify 2022-09-22, 2023-01-18, 2024-03-19 and 2024-10-31.

Historical strategy performance: `NOT RUN`  
Historical strategy signals: `NOT GENERATED`  
EURUSD/M15: `UNTOUCHED`  
Phase 5H future test: `NOT ASSIGNED`  
USDJPY/H1 future test: `NOT CONSUMED`  
LIVE disabled; orders: `0`.

**PHASE 5K SOURCE AUDIT CORRECTED — BOJ SCALAR STILL BLOCKING**
