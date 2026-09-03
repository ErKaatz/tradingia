# Phase 3 — preregistered forward validation

The final holdout failed for both frozen breakout candidates. Diagnostics showed a large reduction in follow-through: lower 24/48/72h MFE, fewer +5% excursions, lower volatility/range at entry, and longer loss streaks. This phase does **not** repair history. It freezes new hypotheses and waits for future data.

Frozen forward start: **2026-09-03 00:00 UTC**.

Hypotheses:
1. `baseline_168_60` — unchanged benchmark.
2. `baseline_168_72` — unchanged secondary benchmark.
3. `confirmed24_168_60` — wait exactly 24 bars after the breakout setup and require price to remain above the original breakout level before becoming long.
4. `adaptive_vol_168_60` — enter only when current 168h realized volatility is above the median of the previous 365 days of 168h realized volatility; exits remain ungated.

The last two were inspired by consumed data and therefore can only earn evidence from forward data.

Workflow:

```bash
python -m src.cli preregister-forward configs/forward_validation.yaml
# Later, after appending candles newer than 2026-09-03:
python -m src.cli forward-eval configs/forward_validation.yaml
```

`forward-eval` refuses to run if there are fewer than two bars at/after the frozen start.
