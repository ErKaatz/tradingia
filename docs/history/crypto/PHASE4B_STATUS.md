# Phase 4B — Edge vs Cost Diagnostics

Status: implemented, awaiting execution on the real BTCUSDT 15m/1h parquet datasets.

This phase is deliberately diagnostic and post-hoc. It reuses exactly 14 frozen Phase-4A variants from `volume_shock_direction`, `range_expansion`, and `extreme_move_reversal`; it does not add or search parameters.

Outputs include a true zero-cost counterfactual using the exact same signal path, a break-even multiplier of the existing BASE execution-cost model, 15m/30m/1h/2h/4h follow-through on the 15m master tape, repeated-trigger/reentry diagnostics, and descriptive signal-strength quartiles. No quartile is converted into a trading threshold.
