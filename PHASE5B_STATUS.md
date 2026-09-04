# Phase 5B — FX Economic Backtest Foundation

## Objective

Build and validate the economic/accounting foundation required to
backtest FX correctly: position representation, bid/ask execution,
lot/contract economics, PnL, cost accounting (spread, slippage,
commission, swap), causal signal->execution, and an auditable
trade/account model. **Not** a strategy search — no strategy was
researched, tuned, or run against real EURUSD data in this phase (see
`RESEARCH_RULES.md` and the task's explicit exclusions).

## Architecture

```
src/fx/backtesting/
    models.py       -- PositionSide, TargetPosition, Position, TradeResult, AccountState
    costs.py         -- SlippageModel, CommissionModel, SwapModel, RolloverSchedule
    execution.py     -- bid/ask reconstruction + directional fills
    pnl.py           -- gross PnL with explicit currency-conversion refusal
    engine.py        -- FxBacktestEngine: causal loop, position/account state
    metrics_adapter.py -- FxBacktestResult -> neutral BacktestResult/Trade
```

Also, resolving pre-existing technical debt (Section 1 of the task):

```
src/backtesting/models.py   -- NEW: Trade/BacktestResult extracted from engine.py
src/backtesting/engine.py   -- unchanged behavior; now imports Trade/BacktestResult
                                from models.py and re-exports them (no import
                                broke: `from src.backtesting.engine import Trade`
                                still works)
src/metrics/metrics.py      -- now imports BacktestResult from
                                src.backtesting.models, not src.backtesting.engine
```

### Old engine: not retired

`src/backtesting/engine.py` (`BacktestEngine`/`BacktestConfig`,
FLAT/LONG-only, crypto-era) still has active consumers: its own test
suite (`tests/test_engine.py`, `test_engine_invariants.py`,
`test_engine_validation.py`, `test_warmup.py`) and `tests/test_metrics.py`
construct it/its types directly. Per the task's own instruction ("if
`src/backtesting/engine.py` has no active consumers, remove it"), it is
**not orphaned**, so it was **not removed** — only its two data
structures were extracted to a neutral module so `metrics.py` no longer
needs to import a crypto-shaped engine to get at them. `git log`/the
`crypto-research-final` tag remain the place to find the old engine if
this changes later.

## Verified MT5 OHLC price-side semantics

**VERIFIED (documented, not independently re-derived at tick level):**
MetaQuotes documents `copy_rates_range()` OHLC for FX symbols as built
from the **BID** price stream; `spread` is the bar's last-known spread
in points, which is how a caller reconstructs ASK:

```
bid = bar price (open/high/low/close, as returned)
ask = bid + spread_points * point
```

This is a stable, platform-level MT5 contract (not broker-specific),
consistent with `mt5_bridge/backend.py::RealMT5Backend.copy_rates_range`
already carrying `spread` on every bar and Phase 5A's `FxBar.spread_points`
already existing for exactly this reason. It was **not** re-verified in
this phase by comparing `copy_rates_range` bars against
`copy_ticks_range` bid/ask ticks over the same real window — that would
be a tick-data study, out of Phase 5B's stated scope (economic
foundation, not a market-microstructure investigation). If a future
phase needs certainty beyond MetaQuotes' own documentation, that
tick-level comparison is the concrete next step.

## Signal model (Section 5)

`TargetPosition` (LONG/SHORT/FLAT) is the engine's signal contract. The
engine — not the caller — applies the one-bar causal shift: the target
known as of bar i's close becomes the position held starting at bar
i+1's open (`FxBacktestEngine.run`'s `shifted_targets` list). No
same-bar lookahead is possible by construction: a signal on the last
bar of the dataset has no next-bar open to execute on, and simply never
opens (see `tests/fx/backtesting/test_causality.py`).

Only synthetic signals were used anywhere in this phase — no real
strategy logic.

## Bid/ask execution model (Sections 6-7)

```
LONG:  open at ASK, close at BID.
SHORT: open at BID, close at ASK.
```

plus adverse slippage on top of that reference price. Fills always
execute at the *next* bar's OPEN — no intrabar path, no stop/take-profit
simulation, no tick simulation (`src/fx/backtesting/execution.py`).

A signal that flips directly LONG<->SHORT is executed as two separate,
fully audited trades (close-then-open at the same bar's open), never a
single netted fill — see `test_position_state.py`'s transition tests.

## Lot / exposure model (Section 9)

`FxEngineConfig` takes the *caller-supplied* `volume_min`/`volume_max`/
`volume_step`/`contract_size` (from real `SymbolMetadata`, never
hardcoded) and validates `lots` against them at construction time —
`InvalidLotsError` on violation, never silent clamping
(`tests/fx/backtesting/test_lots.py`). Exposure = `lots * contract_size`.
Fixed lot sizing only; no risk-based sizing, no leverage/margin logic.

## PnL model (Sections 9-10)

`src/fx/backtesting/pnl.py::compute_gross_pnl` computes PnL from two
already-cost-adjusted execution prices times `lots * contract_size`.
**VERIFIED / fully supported**: `currency_profit == account_currency`
(EURUSD on a USD account — this project's real HFM demo account). **NOT
YET SUPPORTED**: any symbol whose `currency_profit` differs from the
account currency — `compute_gross_pnl` raises
`UnsupportedCurrencyConversionError` rather than silently computing a
wrong number; there is no conversion mechanism in Phase 5B.

## MT5 PnL oracle (Section 11)

**Investigated**: no `order_calc_profit`-equivalent bridge endpoint
existed before this phase. Added (this phase, code-complete):

- `mt5_bridge/backend.py`: `ProfitCalcRequest`, `MT5Backend.order_calc_profit`
  (protocol method), `FakeMT5Backend.order_calc_profit` (deterministic
  fake formula, tests only), `RealMT5Backend.order_calc_profit` (calls
  `MetaTrader5.order_calc_profit()` directly — a pure calculation, never
  an order/deal/position).
- `mt5_bridge/app.py`: new **read-only** `GET
  /v1/profit-calc/{symbol}?side=...&volume=...&price_open=...&price_close=...`.
  Never calls into `mt5_bridge/trading.py`; creates nothing.
- `src/execution/mt5_remote.py::MT5RemoteExecutionClient.profit_calc` —
  Linux-side client method.
- Unit tests: `mt5_bridge/tests/test_profit_calc.py` (6 tests, FakeMT5Backend),
  `tests/test_mt5_remote.py` (4 tests, fake transport) — all passing.

**NOT YET VALIDATED against the real bridge.** `mt5_bridge/` is
deployed to the Windows VM by manual copy (see
`FX_PHASE0_STATUS.md`/README) — the VM's currently-running bridge
predates this endpoint. An empirical attempt in this session against
the real, reachable bridge (`tia mt5 status` confirmed
`bridge_alive=True`) returned `HTTP 404` for `/v1/profit-calc/EURUSD`,
exactly as expected for an undeployed endpoint — this was not
fabricated as a pass. The comparison test
(`tests/fx/test_profit_calc_integration.py`, marked `requires_real_mt5`,
4 parametrized LONG/SHORT gain/loss scenarios) is written and ready; it
requires the updated `mt5_bridge/` to be copied to the VM and the
bridge restarted before it can run for real. **This is the one item
Phase 5B leaves for a deploy-and-rerun step, not a design gap.**

## Spread cost accounting (Section 12)

`TradeResult` carries `gross_pnl` (bid-to-bid, zero-cost reference),
`spread_cost`, `slippage_cost`, `commission_cost`, `swap_cost`, and
`net_pnl`, satisfying exactly:

```
net_pnl = gross_pnl - spread_cost - slippage_cost - commission_cost - swap_cost
```

Each term is derived independently in `engine.py::_close` from three
PnL points along the same price move (bid-to-bid reference ->
correct-side-no-slippage -> correct-side-with-slippage), so nothing is
subtracted twice. Proven by `tests/fx/backtesting/test_costs.py`'s
identity tests (with and without slippage/commission active).

## Slippage model (Section 8)

`ZeroSlippage`, `FixedPointsSlippage(points)` — adverse by construction
(`SlippageModel.apply` always moves BUY-direction fills up and
SELL-direction fills down; callers cannot get the sign backwards). No
random/distributional slippage yet.

## Commission model (Section 13)

`NoCommission` (explicit "assume zero" research choice, not a broker
claim), `PerLotPerSide`, `PerLotRoundTurn` (splits its rate in half per
side so two calls sum to the full round-turn charge). No HFM commission
rate is hardcoded anywhere.

## Swap / rollover model (Sections 14-15)

`SwapModel` is **mandatory** in `FxEngineConfig` — there is no default,
so "zero swap" must be the explicit `NoSwap()` choice, never an
omission. `RolloverSchedule(hours_utc={...})` is a caller-supplied set
of UTC hours; the engine does not assume a New York close or any other
broker-specific convention (Section 15's requirement). If a position
crosses a real day boundary and a non-`NoSwap` model has no schedule to
tell it *when* to charge, `SwapRequiredError` is raised — this can
never silently resolve to zero. `NoSwap` is exempt from needing a
schedule (it charges nothing regardless of timing). Triple-swap is
representable by baking a 3x rate into a specific `RolloverSchedule`
hour, not detected automatically.

**NOT YET SUPPORTED**: no real HFM swap rate is known or hardcoded
anywhere; `FixedSwapModel` is a testing/demonstration model only.

## Account / equity model (Section 16)

Single-symbol, single-position `AccountState` (`initial_balance`,
`balance`, `realized_pnl`, `position`, `equity`). Unrealized equity
marks the open position at the **conservative liquidation price**: LONG
at BID, SHORT at ASK (the price at which it could actually be closed
right now), with no slippage applied to the mark (slippage is a
fill-time cost, not a valuation convention) — documented and tested in
`engine.py::_unrealized_pnl` / exercised implicitly by the engine's
equity curve.

## Trade result model (Section 17)

`TradeResult`: symbol, side, lots, open/close time, entry/exit
execution price, entry/exit bid+ask, gross/spread/slippage/commission/
swap/net PnL, bars_held. Deliberately does not duplicate fields
`Position` already types (no redundant symbol metadata re-embedded).

## Metrics integration (Section 18)

`src/fx/backtesting/metrics_adapter.py::to_neutral_backtest_result`
converts `FxBacktestResult` to `src.backtesting.models.BacktestResult`/
`Trade` — the same neutral types `metrics.py` already consumed after
the Section 1 extraction. `metrics.py`'s formulas are **unchanged**;
`periods_per_year` remains an explicit caller-supplied value (no
market-specific default, per the FX-first baseline's existing rule).
Verified end to end in
`tests/fx/backtesting/test_metrics_integration.py`, including a direct
source-inspection assertion that `metrics.py` no longer imports
`src.backtesting.engine`.

## Unit / invariant tests

```
tests/fx/backtesting/
    test_causality.py           -- 3 tests: one-bar shift, no lookahead, FLAT never opens
    test_long_short.py          -- 11 tests: profitable/losing/spread-only/slippage/
                                     commission for both LONG and SHORT, symmetry
    test_lots.py                -- 6 tests: min/max/step validation
    test_costs.py               -- 3 tests: no double-counting, full identity,
                                     adverse cost cannot improve net_pnl
    test_swap.py                -- 5 tests: no-crossing, undefined-model raises,
                                     explicit NoSwap, fixed-swap crossing/no-crossing
    test_position_state.py      -- 6 tests: no second position, close-when-flat,
                                     LONG<->SHORT transitions, end-of-data force-close
    test_metrics_integration.py -- 2 tests: FX result through metrics.py, no old-engine import
```

36 new tests, all passing. Plus:

```
mt5_bridge/tests/test_profit_calc.py   -- 6 tests (bridge-side, FakeMT5Backend)
tests/test_mt5_remote.py               -- +4 tests (profit_calc client method)
tests/fx/test_profit_calc_integration.py -- 4 tests, requires_real_mt5, currently
                                             skip/fail pending bridge redeploy (see above)
```

## MT5 empirical checks (Section 21)

1. **Symbol metadata used by the engine**: reuses `SymbolMetadata`
   already empirically verified in Phase 5A (`PHASE5A_STATUS.md`) — not
   re-verified here, no new claim made.
2. **Historical OHLC price-side semantics**: VERIFIED (documented), see
   above — not re-derived empirically at tick level in this phase.
3. **`order_calc_profit` oracle**: endpoint built, unit-tested; **real
   comparison pending bridge redeploy** (see above) — explicitly not
   fabricated.
4. **Deterministic PnL examples**: 4 LONG/SHORT gain/loss scenarios are
   written and parametrized in `test_profit_calc_integration.py`, ready
   to run the moment the bridge is redeployed.

No order was placed at any point during this investigation.

## Regression / safety (Sections 24, 16)

```
pytest -q                 : 666 passed, 8 skipped (4 pre-existing MT5-integration
                             skips + 4 new profit-calc-oracle skips, all self-skipping
                             by design when the bridge/env is absent)
pytest -q -k "mt5 or execution or fx" : 530 passed, 8 skipped, 136 deselected
```

- Step 4/4.1 and Phase 5A tests: unchanged, still passing.
- LIVE: disabled (`configs/real_money_policy.yaml: live_trading_enabled: false`),
  untouched.
- Zero orders sent: confirmed via `tia mt5 journal --limit 3` — latest
  entry predates this session (2026-09-03).
- No secrets added; `mt5_bridge.sqlite3` remains gitignored; no dataset
  files committed.
- No `/v1/demo/...` code path touched by this phase's changes.

## Technical debt / limitations

- MT5 OHLC bid/ask semantics rest on MetaQuotes' documentation, not an
  independent tick-level empirical re-derivation for this broker.
- Cross-currency PnL (`currency_profit != account_currency`) is
  explicitly unsupported (fails loudly), not implemented.
- No real HFM swap rate is known; `FixedSwapModel`/`RolloverSchedule`
  are a correctness-tested interface, not a broker-calibrated model.
- The MT5 `order_calc_profit` oracle comparison requires deploying the
  updated `mt5_bridge/` package to the Windows VM and restarting the
  bridge — not yet done as of this commit.
- No FXBacktestEngine-level walk-forward/optimization/strategy work was
  done or is implied by this phase — explicitly out of scope.

## Git

This phase's changes: new `src/fx/backtesting/` package,
`src/backtesting/models.py` extraction (`engine.py`/`metrics.py`
updated to use it, behavior unchanged), a new read-only
`order_calc_profit` bridge diagnostic (`mt5_bridge/backend.py`,
`app.py`, `schemas.py`) plus its Linux-side client method, and the full
test suite described above. No push.

## Next phase

```
Phase 5C — not started, not designed here.
```
