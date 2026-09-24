# Phase 5G Track A — Observability contract

Future research writes a strict bundle: `manifest.json`, `summary.json`, and
`trades.jsonl`. `ResearchTradeRecord` is strategy-neutral and persists the
complete signal/entry/exit, side, prices, lots, economic PnL decomposition,
duration, UTC entry/exit hours, and insolvency context. It validates the exact
net-PnL accounting identity and rejects non-UTC timestamps.

`ExperimentManifest` fail-closes on absent identity fields, dataset/cost/non-
spread/preregistration fingerprints, variant registry, split, or assumptions.
Its identity fingerprint excludes operational `created_at_utc`; serialization
is canonical strict JSON and rejects NaN/Infinity. JSONL permits later side,
month/year/hour, duration, concentration, sequence and rollover attribution
without rerunning an experiment. This contract applies only to future runs;
5D/5E remain unchanged.
