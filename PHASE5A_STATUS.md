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
this project actually uses: **PENDING EMPIRICAL VALIDATION.** The
diagnostic tooling to verify it (`time_diagnostics.py`,
`fx-history time-diagnostics` CLI command, and the marked integration
tests in `tests/fx/test_time_diagnostics_integration.py`) is built and
was actually run against the real bridge during this phase — see
Empirical Findings below for what happened and the exact command to
re-run once the bridge is reachable.

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
- The Friday/Sunday-or-Monday weekend heuristic is a common
  approximation for FX, but the *exact* broker weekend close/open
  timestamps have not been empirically confirmed against the real
  bridge (see Empirical Findings) — treat `EXPECTED_WEEKEND` as
  **INFERRED**, not **VERIFIED**, until that validation runs.

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
pytest -q tests/fx/                                                 → 68 passed
pytest -q tests/fx/test_time_diagnostics_integration.py             → 4 skipped (bridge unreachable; see below)
```

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

## MT5 integration — what was actually verified against HFM

```
PENDING EMPIRICAL VALIDATION
```

The Windows VM / bridge was **not reachable** from this environment
during this phase. Verified attempts, all timing out after the
client's configured 10s timeout (not a code error — a genuine
unreachable-host condition):

```
$ tia mt5 status
(no response within the wrapper's own read timeout)

$ tia fx-history time-diagnostics EURUSD --timeframe H1 \
    --start 2026-08-25T00:00:00+00:00 --end 2026-09-04T00:00:00+00:00
ERROR: request to bridge timed out after 10.0s

$ MT5_REMOTE_URL=... MT5_REMOTE_TOKEN=... \
    pytest -q tests/fx/test_time_diagnostics_integration.py -m requires_real_mt5 -s
1 skipped in 10.10s  (skip reason: "bridge configured but unreachable -- PENDING EMPIRICAL VALIDATION")
```

No fabricated finding is reported for weekend-gap shape, Sunday-bar
presence, H4 alignment stability across DST, or the exact UTC contract
of historical timestamps for this specific broker/server. All of that
remains genuinely unknown until the Windows VM is running and reachable.

**To run the empirical validation once the bridge is reachable:**

```bash
tia mt5 status   # confirm reachability first (read-only)

# Weekly EURUSD H1 window spanning a weekend
tia fx-history time-diagnostics EURUSD --timeframe H1 \
    --start <10-days-ago ISO-8601 UTC> --end <now ISO-8601 UTC>

# H4 alignment over two weeks (repeat once more, straddling a DST date,
# to check for a seasonal shift)
tia fx-history time-diagnostics EURUSD --timeframe H4 \
    --start <14-days-ago ISO-8601 UTC> --end <now ISO-8601 UTC>

# Full fetch + validate + fingerprint + optionally save (also captures symbol metadata)
python -m src.cli fx-history fetch EURUSD --timeframe H1 \
    --start <range-start> --end <range-end> [--save]

# Or run the marked integration tests directly:
MT5_REMOTE_URL=http://<vm-ip>:<port> MT5_REMOTE_TOKEN=<token> \
    pytest -q tests/fx/test_time_diagnostics_integration.py -m requires_real_mt5 -s
```

M1/M15/H4 empirical validation (per the task's timeframe checklist) is
covered by the same commands with `--timeframe M1`/`M15`/`H4`; none
were run for the reason above.

## EURUSD observations

None. No dataset was fetched (bridge unreachable). No claim is made
about EURUSD's real historical data quality, timestamp behavior, or
gaps in this environment — see the section above for exactly how to
obtain that once the bridge is reachable. **No performance, return, or
PnL figure was computed or would be computed by any tool built in this
phase** — `time_diagnostics.py` and the `fx-history` CLI commands report
only bar counts, timestamps, gap classifications, and metadata.

## Limitations

- No holiday calendar (see Session/Gap Model).
- No incremental cache/partial-range merge (see Storage/Cache).
- `broker` (distinct from `server`) is not available from any current
  bridge endpoint.
- The weekend-gap heuristic and the UTC-timestamp contract for
  `copy_rates_range` are both **INFERRED**, not **VERIFIED**, for this
  specific broker/server, pending the empirical validation above.
- M1/M5/M15/M30/D1 timeframes are supported by the schema/provider/CLI
  exactly as H1/H4 are, but none were empirically exercised against
  real HFM data in this phase (bridge unreachable).

## Next phase

```
Phase 5B — cost/spread model design (not started; explicitly out of scope for this phase)
```
