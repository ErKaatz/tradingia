# Phase 5A — FX Data Foundation status

## Objective

Build a reproducible, auditable, deterministic historical FX data layer
backed initially by MT5/HFM, explicit about timezone, sessions, gaps,
and `tick_volume` semantics. First instrument: EURUSD. Purpose:
**validate the infrastructure, not select a strategy, timeframe, or
period by performance.** No FXBacktestEngine, no FX strategy, no
optimization, no SHORT semantics, no lot/spread/commission/swap
simulation was implemented in this phase — all explicitly deferred.

## Architecture

```
src/fx/
    __init__.py
    data/
        __init__.py
        schema.py           # FxBar, FxSymbolMetadata, VolumeKind, FxTimeframe (= ExecutionTimeframe)
        normalize.py         # HistoryBar/SymbolMetadata/AccountSummary -> canonical FxBar/FxSymbolMetadata
        sessions.py           # minimal FX gap classification (CONTIGUOUS/EXPECTED_WEEKEND/UNEXPECTED_GAP)
        validation.py         # structural + temporal validation over FxBar sequences
        dataset.py            # FxDatasetMetadata + deterministic SHA-256 fingerprint
        storage.py             # data/fx/<SYMBOL>/<TIMEFRAME>/{bars.parquet,metadata.json}
        mt5_provider.py         # read-only fetch: ExecutionClient.history() -> normalized FxBar
        time_diagnostics.py      # empirical weekend-gap/H4-alignment observation tooling
src/cli/fx_cli.py                # `fx-history {fetch,metadata,fingerprint,validate,time-diagnostics}`
```

No new `core/` directory, no move of existing generic infrastructure.
`src/data/`, `src/research/`, `src/metrics/` are untouched.

### Reused, not duplicated

Phase 5A deliberately builds on top of infrastructure that already
existed before this phase, rather than reinventing it:

- `src/execution/base.py`'s `ExecutionTimeframe` enum (M1/M5/M15/M30/H1/H4/D1)
  is the one canonical timeframe representation — `schema.py`'s
  `FxTimeframe` is a direct alias, not a second enum.
- `HistoryRequest`/`HistoryResult`/`MT5RemoteExecutionClient.history()`
  and the bridge's `GET /v1/history/{symbol}` (backed by
  `RealMT5Backend.copy_rates_range`) already existed (FX Phase 0, Step
  3.1) and are used as-is — no new HTTP endpoint was added for fetching
  bars.
- `mt5_bridge/backend.py::RealMT5Backend.copy_rates_range` already
  deliberately does NOT apply the live-tick `ServerClockOffset`
  correction to historical bars (a decision made before this phase —
  see that module's own comment). Phase 5A's `mt5_provider.py` respects
  that boundary and does not reapply any correction either.
- `SymbolMetadata`, `AccountSummary`, `HealthStatus` already existed;
  this phase only added the fields they were missing
  (`tick_size`/`tick_value`/currency fields on `SymbolMetadata`,
  `server` on `AccountSummary`) rather than inventing parallel types.

## FX Schema (exact contract)

```python
FxBar:
    timestamp_utc: datetime      # tz-aware, asserted == UTC in __post_init__
    open, high, low, close: Decimal
    tick_volume: Decimal          # MT5's per-bar tick count -- NEVER "volume"
    real_volume: Decimal | None    # broker traded volume; None is common/expected for FX OTC
    spread_points: int | None       # bar's spread in the symbol's own points

FxSymbolMetadata:
    requested_symbol, resolved_symbol: str
    description, digits, point: ... | None
    volume_min, volume_step, volume_max, contract_size: Decimal | None
    tick_size, tick_value: Decimal | None
    currency_base, currency_profit, currency_margin: str | None
    broker, server: str | None
```

`symbol`/`timeframe`/`source` live in dataset-level metadata
(`FxDatasetMetadata`), not on every `FxBar` row — a `FxBar` is already
scoped to one symbol/timeframe/dataset by construction (it lives inside
one dataset file), so repeating those three strings per row would be
pure duplication with no independent meaning.

## Volume semantics — the honesty fix

Before this phase, `src/execution/base.py::HistoryBar` had a single
generic `volume: Decimal` field, and
`src/execution/mt5_remote.py::_parse_history_bar` populated it from
`tick_volume` with a silent fallback to a `volume` key if present —
exactly the kind of tick-count-as-traded-volume conflation this task
explicitly forbids. Both were changed:

- `HistoryBar` now carries `tick_volume: Decimal` (required),
  `real_volume: Decimal | None`, and `spread_points: int | None` as
  distinct, honestly named fields. There is no generic `volume` field
  anywhere in this history path anymore.
- `_parse_history_bar` requires `tick_volume` from the bridge response
  and never falls back to a generic `volume` key. A bar missing
  `tick_volume` is now rejected (`ExecutionProtocolError`), not
  silently accepted — see
  `test_history_bar_missing_tick_volume_rejected_not_defaulted_from_generic_volume`.
- `FxDatasetMetadata.volume_kind` is always recorded explicitly as
  `"tick_volume"` in Phase 5A. `real_volume` legitimately stays `None`
  in the dataset and is never treated as a validation error
  (`test_real_volume_zero_or_none_not_rejected`,
  `test_history_bar_real_volume_absent_is_none_not_an_error`).

The bridge itself (`mt5_bridge/schemas.py::history_bar_response`) was
already sending `tick_volume`/`real_volume`/`spread` honestly before
this phase; the conflation was entirely on the Linux parsing side.

## Time Handling

```
raw MT5 historical timestamp (from RealMT5Backend.copy_rates_range)
    -> bridge sends it as an ISO-8601 UTC string (mt5_bridge/schemas.py::history_bar_response)
    -> MT5RemoteExecutionClient._parse_utc_timestamp rejects naive timestamps,
       converts any tz-aware value to UTC
    -> src/fx/data/normalize.py::normalize_bar re-asserts .astimezone(timezone.utc)
    -> FxBar.__post_init__ asserts tzinfo is not None AND utcoffset() == UTC's offset
```

**`ServerClockOffset` is NOT reused here, by design.** That correction
(built for FX Phase 0's live-tick clock-skew bug, see
`mt5_bridge/server_clock.py`) is deliberately scoped to
`RealMT5Backend.symbol_info_tick` (live quotes) only.
`RealMT5Backend.copy_rates_range` (historical bars) has its own,
separate comment explaining why the same correction is NOT applied
there: MetaQuotes documents `copy_rates_range` timestamps as UTC, and
applying today's live-tick offset to historical bars could silently
corrupt them across a DST transition. This phase's `mt5_provider.py`
respects that same boundary and adds no new correction of its own.

Status of that documented UTC contract for the real HFM broker/server
this project actually uses, after empirical validation (2026-09-04):

```
VERIFIED:
bridge historical timestamps represent UTC instants, and normalization
(normalize_bar / FxBar.__post_init__) preserves them unchanged.
ServerClockOffset is confirmed NOT applied to historical bars.

VERIFIED (separately):
H4 bar alignment is stable at UTC hours {0,4,8,12,16,20} across the
2026 US and EU DST transitions -- no seasonal shift observed for this
broker/account. See Empirical Findings below for the exact evidence and
what remains a bar-alignment question versus a timestamp-timezone
question (they are not the same claim).
```

## Session/Gap Model

`src/fx/data/sessions.py` implements exactly three gap classifications,
no more:

```
CONTIGUOUS        -- interval matches the timeframe's nominal step (within 1% tolerance)
EXPECTED_WEEKEND   -- earlier bar is Friday, later bar is Sunday or Monday, gap >= 24h
UNEXPECTED_GAP      -- anything else longer than the nominal step
```

**Limitations, explicit and intentional:**

- No holiday calendar. A gap around a bank holiday will be classified
  `UNEXPECTED_GAP`, not a special holiday category, because no holiday
  table exists yet and inventing one was out of scope.
- No London/NY/Asia session boundaries assigned per bar — that is a
  research-time concern for a future phase, not a data-integrity
  concern this phase needed to solve.
- The Friday/Sunday-or-Monday weekend heuristic was empirically
  confirmed against this broker (see Empirical Findings): HFM's actual
  weekend boundary for EURUSD is Friday 23:00 UTC (last H1/M15 bar) to
  Monday 00:00 UTC (first bar) — **zero Sunday bars observed** across
  every weekend checked. `EXPECTED_WEEKEND` is now **VERIFIED** for
  this broker/symbol, not merely inferred.

**No gap is ever repaired.** `validation.py` never forward-fills OHLC,
interpolates, fabricates a synthetic candle, duplicates the last close,
or invents a zero-volume bar to paper over a gap. Gaps are reported as
data (`gap_counts`, `unexpected_gap_examples`), never silently patched.

## Symbol Metadata

Fields actually available from the bridge, all now captured on the
Linux side in `FxSymbolMetadata`:

| Field | Source | Status |
|---|---|---|
| `digits`, `point`, `volume_min/step/max`, `contract_size` | already existed (`SymbolMetadata`) | available |
| `tick_size`, `tick_value` | bridge already sent them (`trade_tick_size`/`trade_tick_value`); Linux parser did not read them | **fixed this phase** |
| `currency_base`, `currency_profit`, `currency_margin` | did not exist anywhere | **added this phase** (bridge: `BackendSymbolInfo` + `symbol_response`; Linux: `SymbolMetadata` + parser) |
| `server` | bridge already sent it in `/v1/account`; Linux parser did not read it | **fixed this phase** (`AccountSummary.server`) |
| `broker` (a broker *name* distinct from `server`) | no bridge endpoint reports this | **not available** — `FxSymbolMetadata.broker` stays `None`; `normalize_symbol_metadata` accepts an explicit `broker` argument for a future caller that has one, but nothing currently supplies it |

No field was invented or defaulted (e.g. `contract_size` is never
assumed to be 100000 just because that's typical for FX majors — it is
`None` if the bridge did not report it).

## Dataset Identity — metadata + fingerprint policy

`FxDatasetMetadata` splits fields into two explicit groups:

**Deterministic** (part of the fingerprint): `schema_version`,
`normalization_version`, `requested_symbol`, `resolved_symbol`,
`timeframe`, every bar's `timestamp_utc`/OHLC/`tick_volume`/
`real_volume`/`spread_points`, and the symbol metadata's numeric/currency
fields (excluding `broker`/`server` — see below).

**Operational** (recorded, but explicitly excluded from the
fingerprint): `created_at_utc`, `bridge_build`, `broker`, `server`.
`broker`/`server` are classified operational rather than deterministic
because they identify *which account fetched the data*, not *what the
data is* — the same EURUSD H1 bars fetched from two different demo
accounts on the same broker must fingerprint identically.

Fingerprint mechanism: `hashlib.sha256` (never Python's `hash()`, which
is per-process-salted) over `json.dumps(payload, sort_keys=True,
separators=(",", ":"))` — a byte-stable, deterministic serialization.
Verified in `tests/fx/test_dataset_fingerprint.py`: identical for
repeated computation and independent of fetch time/bridge
build/broker/server; changes for any price, timestamp, tick_volume,
real_volume, symbol, or timeframe difference.

## Storage/Cache

Implemented: `data/fx/<SYMBOL>/<TIMEFRAME>/{bars.parquet,metadata.json}`
(gitignored, same convention as the existing `data/raw/` crypto cache).
Prices/volumes are stored as strings in parquet (never `float64`) so a
round-trip never reintroduces binary-float noise into an originally
exact `Decimal`.

**Deferred, not implemented:** incremental/partial-range fetch merging
(the "cached 2024→2025, request 2024→2025-06, fetch only the missing
tail" pattern). Every `fx-history fetch --save` call writes one
complete dataset for its requested range; extending a range currently
means re-fetching the full new range and overwriting. This was an
explicit scope decision (Phase 5A prioritizes correctness of a single
fetch over an incremental cache manager) and is documented here as
deferred, not silently missing.

## Unit tests

```
pytest -q tests/fx/                                                                    → 68 passed
pytest -q tests/fx/test_time_diagnostics_integration.py                                → 4 skipped (bridge unreachable in a plain run)
pytest -q tests/fx/test_time_diagnostics_integration.py -m requires_real_mt5 -s         → 4 passed (bridge reachable, real HFM, 2026-09-04)
```

The default `pytest -q` run never requires the bridge (the integration
file self-skips via `pytest.skip` when `MT5_REMOTE_URL`/`MT5_REMOTE_TOKEN`
are not set in that process's environment) — verified both with the
bridge unreachable and, later in this closeout, with it reachable and
the marker explicitly selected.

Coverage: schema invariants (11 tests: valid bar, naive/non-UTC
timestamp, invalid OHLC both directions, non-positive price, negative
tick_volume/real_volume/spread, None real_volume/spread valid),
normalization (determinism, sorting, timezone conversion, duplicate
preservation, symbol-metadata mapping including all-`None` and
missing-account cases), fingerprint (12 tests: same-input stability,
independence from fetch time/bridge build/broker-server, sensitivity to
price/timestamp/tick_volume/real_volume/symbol/timeframe changes, row-
order invariance), gap classification (12 tests covering contiguous,
Friday→Sunday, Friday→Monday, midweek missing bar, multi-hour gap,
boundary-not-weekend cases in both directions, H1/H4/D1), FX-aware
validation (8 tests: empty dataset, contiguous, weekend-gap-not-an-
error, midweek-gap-is-warning-not-hard-error, duplicates, non-monotonic,
real_volume None/zero accepted, single-bar dataset), provider (8 tests
with a mocked `ExecutionClient`: normal/empty response, bridge-error
propagation, invalid range/symbol/naive-datetime rejected before any
call, metadata-fetch-failure does not fail the bar fetch, full
metadata-building round trip), storage (4 tests: metadata/dataframe
round trip, missing-dataset error, symbol case normalization), and
mocked time-diagnostics logic (7 tests: weekend-boundary detection,
Sunday-bar counting, H4-alignment reporting, empty response, bridge-
error propagation).

## MT5 integration — empirically verified against real HFM (2026-09-04)

The Windows VM/bridge was unreachable earlier in this phase (network-
level timeout, confirmed via `tia mt5 status`, raw TCP, and ICMP ping
all timing out) and was started/made reachable mid-session. Full
empirical validation was then run read-only against the real HFM Demo
account. **Zero orders were placed; `demo-open`/`demo-close` were never
called.**

### Connectivity

```
$ tia mt5 status
bridge_alive:            True
terminal_connected:      True
terminal_trade_allowed:  True
api_version:             1
bridge_version:          1
bridge_build:            step4-audit-hardened-2026-09-03   (matches expected)
broker_name:             HF Markets (SV) Ltd.
account_trade_mode:      demo
account_trade_allowed:   True
account_trade_expert:    True
account_currency:        USD
account_balance:         99.61
kill_switch:             inactive
reconciliation:          ok
```

Live-tick diagnostic (`tia mt5 time-diagnostics EURUSD`), for context
only — this is the LIVE-tick correction, not the historical-bar path:
`server_clock_offset_seconds: 10800.0` (3h, consistent with HFM
EEST), `quote_age_seconds ≈ 0.7s`. Working exactly as designed.

### Symbol metadata — EURUSD

| Field | Value | Present? |
|---|---|---|
| `requested_symbol` | EURUSD | yes |
| `resolved_symbol` | EURUSD (no broker suffix on this account) | yes |
| `digits` | 5 | yes |
| `point` | 0.00001 | yes |
| `trade_tick_size` | 0.00001 | yes |
| `trade_tick_value` | 1.0 | yes |
| `contract_size` | 100000.0 | yes |
| `volume_min` | 0.01 | yes |
| `volume_max` | 60.0 | yes |
| `volume_step` | 0.01 | yes |
| `currency_base` | EUR | yes |
| `currency_profit` | USD | yes |
| `currency_margin` | EUR | yes |
| `server` (via `account()`) | HFMarketsGlobal-Demo | yes |
| `broker` (distinct from `server`) | — | **not available** (no endpoint reports it; confirmed still `None`, not a bug) |

No discrepancy found between what MT5 returned and what the Phase 5A
parsers (`SymbolMetadata`, `AccountSummary`) captured — every field
above round-tripped correctly through `client.symbol_metadata()` /
`client.account()`.

### Timestamp findings — M1 / M15 / H1 / H4

6-hour window, `2026-09-04 08:31→14:30 UTC` (M1/M15/H1) and current H4 bar:

| Timeframe | Bar count | First timestamp (UTC) | Last timestamp (UTC) | Monotonic | Duplicates | tz-aware UTC |
|---|---|---|---|---|---|---|
| M1 | 360 | 08:31:00 | 14:30:00 | yes | 0 | yes |
| M15 | 24 | 08:45:00 | 14:30:00 | yes | 0 | yes |
| H1 | 6 | 09:00:00 | 14:00:00 | yes | 0 | yes |
| H4 | 1 | 12:00:00 | 12:00:00 | yes | 0 | yes |

`ServerClockOffset` non-application confirmed directly: the most
recent real H1 bar (`14:00 UTC`) was only 0.51h old relative to actual
wall-clock UTC at fetch time — if the live tick's +3h correction were
wrongly applied to history, this bar would appear either ~3.5h stale or
~2.5h in the future. Neither happened.

### Weekend findings

Two independent recent weekends, H1, plus one in M15:

| Window | Last bar before weekend (UTC, weekday) | First bar after (UTC, weekday) | Gap duration | Sunday bars | Classification |
|---|---|---|---|---|---|
| H1, Aug 28→31 | 2026-08-28 23:00 (Fri) | 2026-08-31 00:00 (Mon) | 2d 1h | 0 | `EXPECTED_WEEKEND` |
| H1, Aug 21→24 | 2026-08-21 23:00 (Fri) | 2026-08-24 00:00 (Mon) | 2d 1h | 0 | `EXPECTED_WEEKEND` |
| M15, Aug 28→31 | 2026-08-28 23:45 (Fri) | 2026-08-31 00:00 (Mon) | 2d 0h15m | 0 | `EXPECTED_WEEKEND` |

Both weekends behave identically. **HFM/this account never produces a
Sunday-timestamped EURUSD bar** — the market reopens exactly at Monday
00:00 UTC. A 3-week continuous H1 fetch (`2026-08-17→2026-09-04`, 351
real bars) spanning both weekends confirmed: `contiguous=348,
expected_weekend=2, unexpected_gap=0` — zero false positives, both real
weekend closures correctly classified, `validation.is_valid == True`.
The synthetic `UNEXPECTED_GAP` unit tests (`tests/fx/test_sessions_gaps.py`,
`tests/fx/test_validation.py`, 19 tests) still pass unchanged, confirming
the classifier correctly separates real normal weekly progression from
a genuine anomaly in both directions.

### DST / H4 alignment findings

H4 bars fetched for windows straddling both 2026 DST transitions
(2026-03-08 US spring-forward, 2026-03-29 EU spring-forward — both
fall on a Sunday when the market is closed, so the transition instant
itself has no bars; the meaningful test is grid alignment immediately
before vs. after):

| Window | Hours of day seen (UTC) |
|---|---|
| Before US DST (Mar 1–7) | {0, 4, 8, 12, 16, 20} |
| After US DST (Mar 9–15) | {0, 4, 8, 12, 16, 20} |
| Before EU DST (Mar 22–28) | {0, 4, 8, 12, 16, 20} |
| After EU DST (Mar 30–Apr 5) | {0, 4, 8, 12, 16, 20} |
| Current (Sep, both DST active) | {0, 4, 8, 12, 16, 20} |

**H4 alignment is stable and identical across all five windows.** No
seasonal shift was observed for this broker/account/symbol. H1 bars
directly spanning the DST weekend (`2026-03-07 20:00 → 2026-03-09 04:00`)
show no gap/skip/duplicate beyond the ordinary weekend closure itself
(market was closed Sat–Sun as usual; 5 contiguous bars resume Monday
00:00 UTC with zero anomalous entries).

**Explicit distinction, as required:** this is a finding about **bar
grid alignment** (H4 buckets start at the same UTC hours year-round for
this broker), not a claim about which economic session/timezone
convention the broker uses to define those buckets — no assumption
about New York close, EET/EEST, or any named convention was made or is
needed to state this result.

### Daily / rollover findings

D1 bars for one real trading week (`2026-08-24→2026-08-31`), read-only:

```
2026-08-24 00:00 UTC (Mon)  tick_volume=77516  spread=16
2026-08-25 00:00 UTC (Tue)  tick_volume=69528  spread=16
2026-08-26 00:00 UTC (Wed)  tick_volume=76202  spread=16
2026-08-27 00:00 UTC (Thu)  tick_volume=69622  spread=16
2026-08-28 00:00 UTC (Fri)  tick_volume=91874  spread=16
2026-08-31 00:00 UTC (Mon)  tick_volume=70560  spread=16   <- correctly skips Sat/Sun
```

D1 bars start exactly at `00:00 UTC` every weekday, with no missing
Mon–Fri bar and a correct Fri→Mon skip (no Saturday/Sunday D1 bar
exists). No anomalous bar duration/position was found. This is
read-only inspection only — no swap/rollover economic model was built,
per instructions.

### Volume findings

3-week real H1 dataset (351 bars):

| Field | Observation |
|---|---|
| `tick_volume` | always present; min 131, max 18793; **zero zero-values**; no negatives |
| `real_volume` | always present at the wire level, but **always exactly `0.0`** for every bar (not `null`/absent — this broker reports an explicit zero rather than omitting the field) |
| Normalization | both fields preserved distinctly through `normalize_bar`; `validate_fx_bars` correctly does not flag `real_volume == 0` as an error |

Confirms the FX-OTC pattern the schema was designed for: `tick_volume`
is a real, populated, market-activity proxy; `real_volume` carries no
independent broker-reported trading-volume information for this
symbol/account, and is not treated as a data-quality problem.

### Spread-field findings

Same 351-bar dataset:

| Metric | Value |
|---|---|
| Present (non-null) | 351/351 |
| Negative values | 0 |
| Min / max | 16 / 44 points |
| Distribution | 337/351 bars at the baseline 16 points; remaining bars (17, 19×2, 22×3, 25, 26, 28, 29, 30, 37, 44×2) are occasional elevated-spread bars |

Quality-only observation, per instructions — no cost model, no
strategy-relevant interpretation drawn from this.

### Fingerprint reproducibility

Fixed range `EURUSD H1 2026-08-10T00:00→2026-08-11T00:00 UTC`, two
independent fetches:

```
fetch 1: 25 bars, sha256 = 2d91015f819a5a954c7cd48adf7ce6e08c08645e7e03866432e915e46c9e0f8f
fetch 2: 25 bars, sha256 = 2d91015f819a5a954c7cd48adf7ce6e08c08645e7e03866432e915e46c9e0f8f
SHA1 == SHA2: True
created_at_utc differs between the two (confirms operational metadata correctly excluded)
```

No investigation needed — identical on the first attempt, no
discrepancy to localize.

### Storage roundtrip

Same real 25-bar dataset, into a temporary directory (never
`data/fx/`, never committed):

```
fingerprint before save: 2d91015f819a5a954c7cd48adf7ce6e08c08645e7e03866432e915e46c9e0f8f
fingerprint after load:  2d91015f819a5a954c7cd48adf7ce6e08c08645e7e03866432e915e46c9e0f8f
match: True
```

Confirmed `data/fx/` remains absent from the working tree and untracked
after this validation (`git status` unaffected).

### Bugs found

**None.** No discrepancy between MT5's real responses and the Phase 5A
parsers/schema/normalization/gap-classifier was found. No code change
was made as part of this empirical closeout — every result above
matched the implementation's existing contract on the first real
attempt.

## EURUSD observations

Real EURUSD data was fetched and inspected across M1/M15/H1/H4/D1 for
structure, timestamps, gaps, volume, and spread quality only — see
tables above. **No performance, return, drawdown, or PnL figure was
computed anywhere in this phase or this closeout.**

## Limitations

- No holiday calendar (see Session/Gap Model) — still deferred; not
  needed for what real data showed (only ordinary weekend closures were
  observed, no unexplained holiday-shaped gap).
- No incremental cache/partial-range merge (see Storage/Cache) — still
  deferred.
- `broker` (distinct from `server`) is confirmed not available from any
  current bridge endpoint (empirically re-checked, not just inferred).
- DST/H4 alignment was validated for the **2026 US and EU spring**
  transitions only (the only ones with available history at validation
  time); the 2026 autumn transitions (2026-10-25 EU, 2026-11-01 US) had
  not occurred yet and were not checked.
- Validation covers EURUSD only, on one specific HFM demo account/server
  (`HFMarketsGlobal-Demo`). Behavior was not cross-checked against a
  second symbol or a second broker/server.

## Next phase

```
Phase 5B — cost/spread model design (not started; explicitly out of scope for this phase)
```
