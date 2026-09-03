# Phase 4A status — short-horizon research

Status: **implementation complete; real historical run pending on a machine with the project's parquet dependency (`pyarrow`) available.**

## Implemented

- BTCUSDT 15m + 1h scope, no other timeframes.
- Frozen short-horizon variants across seven experiment families (six primary + explicitly weak UTC-session VWAP experiment): 40 variants total.
- Four fixed execution-cost scenarios (optimistic/base/conservative/severe) with fee + spread-as-effective-slippage + slippage.
- LONG/FLAT only, one-bar-later execution inherited from the audited engine.
- Timeout exits, per-trade MAE/MFE and cost decomposition.
- Historical reporting split into already-observed 2018-2024, already-consumed 2025-2026, and full sample. No period is called a fresh holdout.
- Annual and quarterly trade-cohort summaries derived from the exact BASE full-sample trades, grouped by entry period, avoiding thousands of redundant 303k-bar reruns.
- Descriptive time-of-day analysis with global Kruskal-Wallis + Bonferroni-aware hour flags.
- Parameter plateau/cliff diagnostic over frozen variants only.
- Cross-timeframe mechanism comparison (15m vs 1h).
- All variants receive all four full-sample cost scenarios; research/recent comparisons use BASE costs.
- Monte Carlo (2,000 IID trade bootstrap) plus optional moving-block bootstrap for descriptively eligible variants.
- Multiple-testing accounting and descriptive-only classifications.
- Maximum-three post-hoc candidate shortlist; no Phase-4 forward phase is created automatically.
- Phase-3 fingerprint checked before/after and required unchanged.
- CLI: `python -m src.cli short-horizon configs/short_horizon_phase4a.yaml`.

## Frozen variant count

- 15m: 20 variants.
- 1h: 20 variants.
- Total: 40 variants.

The same seven family names exist on both timeframes. Parameters use deliberately sparse, approximately clock-time-matched horizons where appropriate.

## Tests in this environment

- New Phase-4A integration/guardrail tests: 13/13 pass.
- Combined short-horizon/causality/cost/MAE-MFE/time-of-day/bootstrap suite: 78/78 pass.
- Full repository run here: 264 tests pass. The remaining 6 failures + 4 setup errors are all parquet-I/O tests blocked because this runtime has neither `pyarrow` nor `fastparquet`; no non-parquet test failed.

The repository's `requirements.txt` declares `pyarrow`, so on the user's normal `.venv` the full suite should exercise those parquet tests as well.

## Next command

```bash
python -m src.cli short-horizon configs/short_horizon_phase4a.yaml
```

Expected output root:

`research/short_horizon/`

Key files include `all_variants.csv`, `family_summary.csv`, `cost_analysis.csv`, `classifications.csv`, annual/quarterly summaries, time-of-day reports, MAE/MFE trade reports, parameter sensitivity, Monte Carlo, multiple-testing metadata, and a maximum-three candidate shortlist.
