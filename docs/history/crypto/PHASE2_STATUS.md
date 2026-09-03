# Phase 2 implementation status

Implemented in this package:

- locked FINAL_HOLDOUT guardrail (2025-01-01 onward by default)
- controlled parameter-grid generation with invalid combinations discarded
- Donchian/simple breakout strategy excluding the current bar from its channel
- yearly strategy metrics with trailing warm-up context
- Buy & Hold benchmark comparisons
- parameter-family dispersion / cliff warning
- fixed-parameter rolling walk-forward windows
- cost stress scenarios A-E
- reproducible trade-return bootstrap Monte Carlo
- optional trailing realized-volatility entry filter
- pre-registered Phase-2 classification labels only
- multiple-testing counters
- research metadata, CSV/JSON/Markdown outputs
- experiment-log template and Phase-2 methodology rules
- CLI: `python -m src.cli research configs/research_phase2.yaml`

Not executed against the real 2018-2024 dataset in this environment because the supplied ZIP contains no `data/` cache and this runtime cannot reach Binance/install `pyarrow`. No real performance claim is made from the synthetic smoke run.
