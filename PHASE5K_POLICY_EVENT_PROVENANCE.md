# Phase 5K — Official Policy Event Provenance

Status: **NOT CLOSED — OFFICIAL EVENT DATA INCOMPLETE**.

This is a source/dataset audit only. It contains no USDJPY bar lookup, return,
signal, trade, PnL, engine execution, cost calibration, or future-test use.

## 1. Initial state

Phase 5J selected the conceptual Fed–BoJ policy-differential family but was
not ready to preregister. Phase 5K audited only official sources and created a
strict local provenance dataset. EURUSD/M15 remains `UNTOUCHED`; Phase 5H
future test remains `NOT ASSIGNED`; USDJPY/H1 future-test performance remains
`NOT CONSUMED`.

## 2. Fed official source hierarchy

1. Federal Reserve FOMC meeting-calendar archive: meeting dates and links to
   every statement and implementation note.
2. Individual Federal Reserve FOMC statement / press-release HTML documents:
   authoritative release wording, release time, and target range.
3. Implementation note only when it is necessary to distinguish public
   announcement from operational effectiveness.

The event source is restricted to `federalreserve.gov`. The calendar confirms
the scheduled meetings in the audit period; the individual statement explicitly
states a release time (for example, the September 2022 statement says “For
release at 2:00 p.m. EDT” and gives the target range).

## 3. BoJ official source hierarchy

1. Bank of Japan past Monetary Policy Meetings page: official scheduled MPM
   dates and release material links.
2. Bank of Japan annual “Statements on Monetary Policy” catalog.
3. Individual official Statement on Monetary Policy / decision document.

The event source is restricted to `boj.or.jp`. The calendar/catalog establishes
scheduled dates and statements; it does **not** license substituting meeting-end
date, noon JST, or any assumed time for a publication timestamp.

## 4. Policy instrument definitions

The Fed measure is prospectively defined as the **midpoint of the FOMC target
range for the federal funds rate**, in percentage points. It is consistent over
the 2022–2025 audit window; the range midpoint is an explicit scalar
representation, rather than a hidden lower/upper-bound choice.

No BoJ scalar is frozen. The official materials show a negative short-term
policy-rate regime before the March 2024 framework change and an overnight
uncollateralized-call-rate guideline afterward. Phase 5K does not silently
splice these instruments or assign an equivalence.

## 5. Release and effective-time semantics

`official_release_timestamp_*` means the source-stated public release time;
that is the earliest `information_available_timestamp` permitted to a future
causal signal. `effective_timestamp` is deliberately separate and remains
unaudited/null where the document does not establish a usable timestamp. A
decision is never treated as public merely because it later became effective.

Fed statements expose their individual release time. The BoJ statement/catalog
sources reviewed expose date and document identity, but not an official
individual publication time suitable for H1 alignment. All BoJ scheduled
records therefore carry `MISSING_OFFICIAL_TIME` and are signal-ineligible.

## 6. UTC normalization and H1 alignment proposal

Fed local source times use `America/New_York`, converted by IANA timezone rules
(not a fixed UTC offset); BoJ source times, if later documented, use
`Asia/Tokyo`. All normalized timestamps are timezone-aware UTC.

The future H1 convention is: a release occurring inside bar `[T,T+1h)` cannot
use that partly post-release bar. A future signal may first evaluate the close
of `[ceil_hour(release), ceil_hour(release)+1h)`, then execute only at the next
bar open. This is a causal design proposal only and was not evaluated.

## 7. Canonical event schema

`PolicyRateDecisionEvent` is implemented in
`src/fx/research/policy_events.py`. Its fields include central bank, event and
meeting identity, scheduled flag, local/timezone/UTC release timestamps,
source URL/title/date/retrieval time, policy instrument and old/new/change
values, effective-time convention, source identity fingerprint, and
`provenance_status`. `signal_ready()` fails closed unless the event is
scheduled and `VERIFIED`.

## 8. Completeness audit

| Institution | Scheduled official meetings expected | Statements / event rows found | Official release timestamps found | Parseable coherent policy values | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Fed | 24 | 24 | 24 | 24 midpoint records | Complete for source audit |
| BoJ | 24 | 24 scheduled statement dates | 0 individually verified times | Not frozen across regimes | Incomplete |

Scheduled versus unscheduled is explicit: only a decision belonging to the
official pre-announced meeting calendar is in scope. Emergency/unscheduled
actions would be recorded as `UNSCHEDULED_OUT_OF_HYPOTHESIS_SCOPE`, not merged
into the hypothesis.

## 9. Differential construction and counts

The only permitted future definition is:

`policy_differential = Fed midpoint − BoJ coherent scalar`, in percentage
points. A signed delta would classify `WIDENS`, `NARROWS`, or `UNCHANGED`.
The local helper implements signed changes/differentials but does not touch
prices or create signals.

Because BoJ time and scalar series are not verified, no differential event is
emitted and no WIDENS/NARROWS/UNCHANGED count is honestly computable.

| Proposed segment | WIDENS | NARROWS | UNCHANGED |
| --- | ---: | ---: | ---: |
| Internal development A (2022-09 to 2023-06) | n/a — blocked | n/a — blocked | n/a — blocked |
| Internal development B (2023-06 to 2024-03) | n/a — blocked | n/a — blocked | n/a — blocked |
| Aggregate development | n/a — blocked | n/a — blocked | n/a — blocked |
| Validation (2024-03 to 2024-09) | n/a — blocked | n/a — blocked | n/a — blocked |
| Future-test reserve (2024-09 to 2025-03) | n/a — blocked | n/a — blocked | n/a — blocked |
| Operational reserve (2025-03 to 2025-08-30) | n/a — blocked | n/a — blocked | n/a — blocked |

No dates were changed to increase sample. Unchanged decisions are represented
in the Fed feed but cannot become a third strategy hypothesis.

## 10. Machine-readable artifacts and fingerprints

The local strict-JSON artifacts are under
`data/fx/research/events/policy_rates/`:

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| `fed_policy_events.json` | `39f4381076fd1713e76e049c7f0ceb6ad26f9027aec96e8515e0823c796cacc8` | 24 official Fed statement identities/times/midpoints |
| `boj_policy_events.json` | `d3b362727aa7c0e688d60797b168d620eaa3e97dab31228e748f0cf65eddf3b0` | 24 official scheduled BoJ dates, explicitly missing times |
| `fed_boj_differential_events.json` | `cdd40b6f69fbfc47f2fc791f38106c6356bd6ed2c714e41c75dc6bc0c47ec1de` | Empty and blocked differential feed |

These are deterministic content fingerprints, not a claim that an external
HTML/PDF byte cache was captured. Every retained source URL remains official;
the lack of source-byte persistence is an additional reason not to freeze a
signal feed yet.

## 11. Missing or ambiguous records

- All 24 BoJ scheduled records: `MISSING_OFFICIAL_TIME`.
- BoJ scalar: `AMBIGUOUS_ACROSS_NEGATIVE_RATE_AND_OVERNIGHT_CALL_RATE_REGIMES`.
- BoJ policy effectiveness: not inferred from statement date.
- Fed operational effectiveness: not used as a substitute for public release;
  it remains separately auditable if a future preregistration needs it.
- No source HTML/PDF byte archive is retained yet; only official URL identities
  and retrieved-at provenance are persisted.

## 12. Required questions

1. **Fed complete?** Yes for the 24 scheduled audit-period decisions.
2. **Fed timestamp for each?** Yes: the source-stated individual statement
   release convention is retained and timezone-normalized.
3. **BoJ complete?** Scheduled meeting/statement dates: yes; executable event
   provenance: no.
4. **BoJ official timestamp for each?** No.
5. **Coherent Fed series?** Yes, target-range midpoint.
6. **Coherent BoJ series across regimes?** Not yet established.
7. **Differential without hidden arbitrary choices?** No, until BoJ scalar and
   public release time are verified.
8. **Counts by split?** Not computed; fail-closed because no valid differential
   events exist.
9. **Potential sample sufficient?** Unknown; it cannot be assessed from an
   invalid event feed.
10. **Feed ready to freeze?** No.

## 13. Tests and safety

`tests/fx/test_policy_events.py` covers Fed EDT/EST conversion, BoJ JST
conversion, signed rate/differential changes, WIDENS/NARROWS/UNCHANGED,
missing-time/rate failure, scheduled/unscheduled scope, deterministic
fingerprints, strict JSON, and the blocked dataset state.

Historical strategy performance: `NOT RUN`  
Historical strategy signals: `NOT GENERATED`  
EURUSD/M15: `UNTOUCHED`  
Future tests: `NOT CONSUMED`  
LIVE: disabled; orders: `0`.

Official sources consulted: Federal Reserve [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) and [sample official FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20220921a.htm); Bank of Japan [past MPM calendar](https://www.boj.or.jp/en/mopo/mpmsche_minu/past.htm), [2024 statement catalog](https://www.boj.or.jp/en/mopo/mpmdeci/state_2024/), and [June 2024 statement](https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2024/k240614a.pdf).

**PHASE 5K NOT CLOSED — OFFICIAL EVENT DATA INCOMPLETE**
