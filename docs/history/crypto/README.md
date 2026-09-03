# Crypto research — historical record

TradingIA's first research track (Phase 2 through Phase 4B) was a
spot-crypto quantitative study on BTCUSDT. That track is now historical.
TradingIA is **FX-first / MT5-first** going forward; crypto is no longer
an active surface of this repository.

This directory preserves the minimum documentation needed to understand
what was tried and why it stopped, without keeping a second live
application around. The full executable state — code, configs, and
tests, exactly as they ran — is preserved by Git, not by copying source
into this folder.

## Purpose of the crypto research

Determine whether a systematic breakout/momentum/mean-reversion strategy
on BTCUSDT (later extended to shorter horizons) could be shown, under
causal backtesting with realistic costs and a genuine forward holdout,
to have a tradeable edge.

## Phases run

- **Phase 2** — Donchian/breakout parameter grid on BTCUSDT 1h,
  research window 2018–2024, with cost stress scenarios, bootstrap, and
  a locked final-holdout guardrail from 2025-01-01 onward. See
  [`PHASE2_STATUS.md`](PHASE2_STATUS.md).
- **Phase 2.5** — narrow robustness pass over the best Phase 2 region
  (168/60, 168/72 lookbacks), plateau/stress/walk-forward diagnostics.
  See [`PHASE25_STATUS.md`](PHASE25_STATUS.md).
- **Phase 3** — preregistered forward validation. The final holdout
  (2025-01-01 → 2026-09-02) **failed** for both frozen breakout
  candidates (approx. 168/60: return -16.15%, DD -38.24%, Sharpe -0.37;
  168/72: return -11.85%, DD -39.23%, Sharpe -0.21; buy & hold ≈ -18.4%
  over the same window). Phase 3 responded by freezing four hypotheses
  and a forward start of **2026-09-03 00:00 UTC**, deliberately waiting
  on future data rather than re-fitting history. See
  [`PHASE3_FORWARD.md`](PHASE3_FORWARD.md).
- **Phase 4A** — 40 short-horizon variants (15m/1h) across seven
  strategy families. All 40 were **rejected under realistic execution
  costs**. See [`PHASE4A_STATUS.md`](PHASE4A_STATUS.md).
- **Phase 4B** — post-hoc edge-vs-cost diagnostics on the strongest
  Phase 4A families (volume shock, range expansion, extreme reversal).
  Best gross signal (RangeExpansion 1h) was still **destroyed by
  costs**. See [`PHASE4B_STATUS.md`](PHASE4B_STATUS.md).

## Result

**No profitable, validated crypto strategy exists.** Every candidate
that reached a genuine out-of-sample or forward test failed, or failed
once realistic costs were applied. This is the documented reason the
project moved to FX/MT5 research instead of continuing to search the
crypto parameter space.

## Last complete executable state

- Branch: `master`
- Commit: see `crypto-research-final` tag (below) for the exact SHA
- Tag: `crypto-research-final`
- Test suite at freeze time: see the checkpoint commit message /
  `FX_MIGRATION_AUDIT.txt` M1 section for the exact `pytest` count
  recorded at freeze time
- Phase 3 integrity guard (`src/research/phase3_guard.py`) values at
  freeze time:
  - `frozen_start`: `2026-09-03 00:00:00+00:00`
  - `frozen_variants`: `baseline_168_60`, `baseline_168_72`,
    `confirmed24_168_60`, `adaptive_vol_168_60`
  - Guarded file SHA-256 hashes: see the checkpoint commit message for
    the exact values recorded at freeze time.
  - This is the **Phase 3 integrity guard** (a live code check across 5
    specific files plus the two semantic values above). It is a
    different thing from a separate, previously-quoted **historical
    frozen-spec SHA-256**
    (`130c9c60265fded8fa71f3d85863cd7b362e640faa8dcd19496815bef4fa35d7`)
    that appears in earlier handoff documents. That single hash could
    not be reproduced from any serialization this guard computes; it is
    recorded here only so the discrepancy is not lost, not because it
    is used by any code in this repository.

## Phase 3 retirement from the active path (2026-09-03)

Phase 3's forward preregistration was removed from the active working
tree in the FX-first cleanup (M3), since its full executable state was
already safe under the `crypto-research-final` tag and TradingIA no
longer maintains functional compatibility with Phase 2/2.5/3/4.

Before removal, the guard was run one final time and reproduced the
exact same fingerprint already recorded above (`frozen_start`,
`frozen_variants`, and all 5 guarded-file SHA-256 hashes unchanged
since the M1 checkpoint) — confirmed by direct byte-for-byte comparison
against the `crypto-research-final` tag's copies of each guarded file.
No guarded file had been modified between the M1 checkpoint and this
retirement.

The 5 files the guard fingerprinted, plus the guard module itself, are
additionally copied verbatim into [`phase3/`](phase3/) so this
historical record is self-contained even without checking out the Git
tag: [`PHASE3_FORWARD.md`](phase3/PHASE3_FORWARD.md),
[`phase3_guard.py`](phase3/phase3_guard.py),
[`breakout_forward.py`](phase3/breakout_forward.py),
[`forward_runner.py`](phase3/forward_runner.py) (originally
`src/forward/runner.py`), [`forward_validation.yaml`](phase3/forward_validation.yaml).
`tests/test_forward_phase3.py` and `tests/test_phase3_guard.py` are not
duplicated here; they are unchanged in the `crypto-research-final` tag.

## How to return to the crypto-era executable state

The entire crypto application — `src/research/*` phase runners,
`src/backtesting/engine.py`, the Binance data provider, crypto configs,
and their tests — is not deleted from history, only from the active
working tree. To get it back exactly as it last ran:

```bash
git checkout crypto-research-final
```

or, to inspect without checking out:

```bash
git show crypto-research-final:src/backtesting/engine.py
```

or, to bring back one file into a new branch without reverting FX work:

```bash
git checkout crypto-research-final -- src/backtesting/engine.py
```
