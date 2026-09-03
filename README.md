# TradingIA

TradingIA is FX-first / MT5-first. It investigates and executes trading
systems reproducibly, auditably, and without self-deceiving backtests.

**No live trading and no real money anywhere in this codebase.**
`configs/real_money_policy.yaml` sets `live.live_trading_enabled: false`;
see `LIVE_TRADING_RULES.md`.

## History

TradingIA's first research track (Phase 2 through Phase 4B) was a
spot-crypto study on BTCUSDT. No profitable, validated crypto strategy
was found; the project moved to FX/MT5 research as a result. That full
history — what was tried, what failed, and why — is preserved at
[`docs/history/crypto/`](docs/history/crypto/README.md), and the last
complete crypto-era executable state (code, configs, and tests exactly
as they ran) is recoverable with:

```bash
git checkout crypto-research-final
```

## Architecture

```
src/
  data/          # DataProvider interface, local cache/loader, chronological splitter, OHLCV validation
  strategies/    # Reference strategy implementations (Strategy ABC: FLAT/LONG signals from OHLC)
  backtesting/   # BacktestEngine: bar-by-bar simulation, next-bar execution, fees/slippage
  metrics/       # Pure performance-metric functions (Sharpe, Sortino, drawdown, trade stats, ...)
  research/      # Generic, market-agnostic research primitives (see below)
  execution/     # MT5 execution: policy, safe execution, quote freshness, remote client
  cli/           # Command-line interface (compare, mt5-remote)
mt5_bridge/      # FastAPI bridge deployed on the Windows VM running MetaTrader5
configs/         # YAML configs (execution policy)
docs/            # Active + historical documentation
tests/           # Unit tests
```

`src/experiments/` (the old crypto-era experiment runner/CLI `backtest`
command) and Phase 2/2.5/3/3B/4A/4B's research modules were removed from
the active tree once their full state was captured under the
`crypto-research-final` Git tag — see
[`docs/history/crypto/README.md`](docs/history/crypto/README.md) for
what was removed and why.

## What is currently implemented

- **Generic data/research infrastructure**: `DataProvider` interface,
  local OHLCV cache/loader with dataset-content hashing
  (`src/data/loader.py`), chronological train/validation/test
  splitting with warm-up handling (`src/data/splitter.py`), OHLCV
  structural validation (`src/data/validation.py`).
- **`BacktestEngine`** (`src/backtesting/engine.py`): bar-by-bar
  simulation with anti-lookahead enforcement (a strategy's signal at
  bar `i` executes at bar `i+1`'s open), FLAT/LONG only, percentage
  fee/slippage, cash-fraction position sizing. It currently has no
  active orchestrator wired to it (the old crypto experiment runner was
  removed); it is kept because `src/metrics/metrics.py` depends on its
  `BacktestResult`/`Trade` data shape, and because a future
  `FXBacktestEngine` is expected to reuse its anti-lookahead/warm-up
  design patterns (by copying, not by inheriting from it).
- **Reference strategies** (`src/strategies/`): `Breakout`,
  `BuyAndHold`, `MeanReversion`, `Momentum`, `SmaCross` — small, OHLC-only,
  no exchange/symbol coupling. Long/flat only; no short-selling
  interface exists yet.
- **Generic research primitives** (`src/research/`): chronological
  holdout locking (`holdout.py`), walk-forward window generation
  (`walk_forward.py`), IID and moving-block trade-return bootstrap
  (`monte_carlo.py`, `block_bootstrap.py`), cost-stress scenarios
  (`stress.py`), a causal realized-volatility entry filter
  (`volatility_filter.py`), a parameter-grid generator
  (`parameter_study.py`), and time-of-day descriptive analysis
  (`time_of_day.py`). None of these are wired into an active CLI
  command yet; they exist as building blocks for future research
  phases.
- **MT5 execution** (`src/execution/`, `mt5_bridge/`): a Linux client
  talking over HTTP to a small FastAPI bridge on a Windows VM running
  the `MetaTrader5` Python package, which drives an HFM Demo MT5
  account. Includes fail-closed DEMO-only execution policy, safe
  order-placement/closing, quote-freshness validation (both client-side
  and independently bridge-side), broker-server-clock auto-calibration,
  idempotency, reconciliation, a kill switch, and an append-only
  execution journal. See `FX_PHASE0_STATUS.md` and
  `LIVE_TRADING_RULES.md`.
- **Research methodology rules** (`RESEARCH_RULES.md`): market-agnostic
  rules on causality, train/validation/test discipline, preregistration,
  costs, multiple testing, and reproducibility.

## What is not implemented yet

- FX historical data ingestion (no `MT5HistoricalProvider`).
- Any FX-aware backtest engine (spread/bid-ask, lot sizing, contract
  size, pip value, swap/rollover, trading sessions, weekend/holiday gap
  handling).
- Short-selling in the `Strategy` interface.
- Any FX strategy.
- Any automatic/scheduled DEMO or LIVE order placement.

These are explicitly deferred to a future FX research phase.

## Core design principles (apply to any future backtest engine or research code)

### Anti-lookahead

A strategy decides its desired position for bar `i` using only
`df.iloc[:i+1]` (see `src/strategies/base.py`). `BacktestEngine` never
executes at the price that generated the signal: it shifts the signal
one bar forward (`shift(1)`) and executes at the **next bar's open**.
This happens inside the engine, not in each strategy, so it cannot be
forgotten when adding a new strategy.

### Warm-up bars are not data leakage

A strategy declares `warmup_bars` (leading bars of trailing history it
needs before its indicator stops being degenerate/NaN). `validation`
and `test` splits may borrow up to `warmup_bars` chronologically
**earlier** bars purely to warm up indicators — never to open, hold, or
close a position, and never counted in that split's equity curve or
trade history (`evaluation_start` in `BacktestEngine.run`). See
`tests/test_warmup.py`.

### Metrics require an explicit annualization factor

`src/metrics/metrics.py` has no built-in trading calendar: `volatility`,
`sharpe_ratio`, `sortino_ratio`, and `build_metrics_report` all require
an explicit `periods_per_year` argument from the caller. This is
deliberate — a spot-crypto market trades continuously (24/7/365) while
FX trades roughly 252 days/year with real session gaps, and guessing one
convention from a timeframe string would silently bake in the wrong
market's assumption for whichever caller didn't expect it.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## MT5 execution CLI

See [`docs/CLI_SETUP.md`](docs/CLI_SETUP.md) for the `tia` wrapper setup,
and `FX_PHASE0_STATUS.md` for current MT5 execution status. Quick
reference of the read-only/DEMO-only commands:

```bash
tia mt5 status
tia mt5 preflight EURUSD
tia mt5 positions
tia mt5 time-diagnostics EURUSD
tia mt5 journal
tia mt5 demo-open EURUSD buy --confirm-demo-order
tia mt5 demo-close <position_id>
```

## Comparing experiment result folders

```bash
python -m src.cli compare results/<experiment_a> results/<experiment_b>
```

Reads `config.json`/`metrics.json` from each folder and prints a
comparison table. This command has no dependency on any specific
research runner — it works with any result folder that writes those two
files in the expected shape.

## Creating a new reference strategy

1. Create a file in `src/strategies/` with a class inheriting from
   `Strategy` (`src/strategies/base.py`) implementing
   `generate_signals(df) -> pd.Series`, returning `FLAT` (0) or `LONG`
   (1) per row.
2. **Row `i` may only depend on `df.iloc[:i+1]`.** No `.shift(-1)`,
   forward windows, or anything that looks at the future.
3. If your indicator needs trailing history, override the
   `warmup_bars` property.
4. Register it in `src/strategies/registry.py`.
5. Add tests in `tests/test_strategies.py` (including a
   truncation-invariance test) and, if `warmup_bars > 0`, add it to
   `tests/test_warmup.py`'s strategy list.
