# Phase 2.5 status

Phase 2.5 is a deliberately narrow robustness pass over the long-lookback BTCUSDT 1h breakout region found in Phase 2.

## Frozen study

- Entry lookbacks: 96, 120, 144, 168, 192, 240 hours
- Exit lookbacks: 36, 48, 60, 72 hours
- 24 variants total
- Research data only through 2024-12-31
- FINAL_HOLDOUT starts 2025-01-01 and remains inaccessible to this runner

## New diagnostics

- Local parameter-neighborhood plateau metrics
- Stress scenarios A-E for every variant
- Stricter candidate classifier
- Fixed-parameter walk-forward for plateau variants
- Trade-entry trend/volatility regime reports using trailing-only features
- 2,000-sequence trade Monte Carlo for plateau variants

Run with:

```bash
python -m src.cli research25 configs/research_phase25.yaml
```

Outputs are written under `research/phase25/`.
