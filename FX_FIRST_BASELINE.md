# FX-first baseline

## Identity

TradingIA — FX-first / MT5-first.

## Historical boundary

Last full crypto executable snapshot:

```
tag:    crypto-research-final
commit: d5e1703b542cd133000b22d5dc61ed1a023de875
```

Everything Phase 2, 2.5, 3, 3B, 4A, and 4B built — code, configs, and
tests, exactly as they last ran — is recoverable with:

```bash
git checkout crypto-research-final
```

No profitable, validated crypto strategy was found in that research.
Full narrative in [`docs/history/crypto/README.md`](docs/history/crypto/README.md).

## Current active capabilities

- **Generic data infrastructure**: `DataProvider` interface, local
  OHLCV cache/loader with dataset-content hashing
  (`src/data/loader.py`), chronological train/validation/test
  splitting with warm-up handling (`src/data/splitter.py`), OHLCV
  structural validation (`src/data/validation.py`).
- **Generic research primitives** (`src/research/`): chronological
  holdout locking, walk-forward window generation, IID and
  moving-block trade-return bootstrap, cost-stress scenarios, a causal
  realized-volatility entry filter, a parameter-grid generator, and
  time-of-day descriptive analysis. None are currently wired into an
  active CLI command; they are building blocks for a future research
  phase.
- **Generic metrics** (`src/metrics/metrics.py`): total/annualized
  return, volatility, Sharpe, Sortino, drawdown, trade stats. No
  built-in trading calendar — annualization requires an explicit
  `periods_per_year` from the caller.
- **`BacktestEngine`** (`src/backtesting/engine.py`): bar-by-bar
  simulation, anti-lookahead enforced, FLAT/LONG only, percentage
  fee/slippage, cash-fraction sizing. Kept as a dependency of
  `metrics.py`'s data types and as a design reference; has no active
  orchestrator wired to it.
- **Reference strategies** (`src/strategies/`): `Breakout`,
  `BuyAndHold`, `MeanReversion`, `Momentum`, `SmaCross` — small,
  OHLC-only, no exchange/symbol coupling.
- **MT5 bridge and execution safety** (`mt5_bridge/`,
  `src/execution/`): DEMO-only fail-closed policy, safe order
  placement/closing, quote-freshness validation (client-side and
  independently bridge-side), broker-server-clock auto-calibration,
  idempotency, reconciliation, kill switch, append-only execution
  journal, AutoTrading/permission preflight checks.
- **DEMO execution infrastructure**: validated end-to-end against a
  real HFM Demo MT5 account (Step 4/4.1 — see `FX_PHASE0_STATUS.md`).
- **Research methodology** (`RESEARCH_RULES.md`): 16 market-agnostic
  rules on causality, train/validation/test discipline,
  preregistration, reproducibility, costs, and multiple testing.
- **CLI**: `compare` (generic result-folder comparison) and
  `mt5-remote` (full MT5 execution/diagnostics surface — `status`,
  `preflight`, `positions`, `demo-open`, `demo-close`, `kill-status`,
  `kill-activate`, `kill-deactivate`, `reconcile`, `resolve-received`,
  `journal`, `time-diagnostics`).

## Removed capabilities

- Binance data ingestion (`BinancePublicProvider`) and the
  `download-data` CLI command.
- All crypto phase runners and their CLI commands: Phase 2, Phase 2.5,
  final-holdout, diagnose-holdout, post-holdout-family-comparison,
  Phase 3B regime study, Phase 4A short-horizon, Phase 4B.
- Phase 3's forward preregistration (`src/forward/`,
  `src/research/phase3_guard.py`, `src/strategies/breakout_forward.py`,
  `configs/forward_validation.yaml`) and its active integrity guard —
  no longer a gate on this branch. Preserved verbatim under
  `docs/history/crypto/phase3/` and in the `crypto-research-final` tag.
- The old crypto-era experiment runner (`src/experiments/`) and the
  `backtest` CLI command.
- `src/research/annual.py` (a thin runner over the old engine with no
  remaining consumer).
- 11 crypto-only strategy/phase configs (`configs/*.yaml`).
- `TRADING_PERIODS_PER_YEAR` (the 24/7/365 crypto bars-per-year table)
  from `src/metrics/metrics.py` — annualization now requires an
  explicit caller-supplied value, with no default for any market.

Not yet implemented (not "removed" — never built): FX historical data
ingestion, any FX-aware backtest engine (spread/bid-ask, lot sizing,
contract size, pip value, swap/rollover, sessions, gap handling),
short-selling in the `Strategy` interface, any FX strategy.

## Safety

```
LIVE trading: disabled (configs/real_money_policy.yaml: live_trading_enabled: false)
No automatic/scheduled DEMO or LIVE order placement anywhere in this codebase.
No DEMO order was placed during the M1-M4 migration work.
```

## Test baseline

```
full pytest:                544 passed
MT5/execution-focused subset: 420 passed
```

(560 before M3; the decrease reflects removing 14 files' worth of dead
crypto-phase/experiment-runner tests, not a regression — see the M3
commit message for the exact accounting.)

## Security baseline

- No secrets, tokens, or credentials tracked in Git.
- `mt5_bridge.sqlite3` is untracked and ignored (`*.sqlite3` in
  `.gitignore`).
- No execution journals tracked (journal is bridge-side runtime state).

## Next phase

```
Phase 5A — FX Data Foundation
```

Not started. No FX data ingestion, schema, or provider exists yet.
