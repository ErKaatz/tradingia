# Live trading rules

## Phase 0: DEMO ONLY

**NO REAL MONEY. NO LIVE ORDERS.**

`configs/real_money_policy.yaml` sets `live.live_trading_enabled: false`.
`src/execution/policy.py` refuses to authorize any opening or increasing
action unless every one of the following independently confirms a demo
context — a single missing or ambiguous fact is enough to deny:

- `live_trading_enabled == false`
- local config/environment says DEMO (not LIVE, not UNKNOWN)
- the remote bridge/terminal's reported environment says DEMO (not LIVE, not UNKNOWN)
- the account's own reported trade mode says DEMO (not LIVE, not UNKNOWN, not missing)
- reconciliation state is OK (not MISMATCH, not UNKNOWN)
- the kill switch is not active
- current open positions are below the configured maximum
- the requested volume equals the broker/symbol's minimum tradeable size

This is intentionally stricter than what a real broker API would require
on its own. Phase 0 has no path to live trading at all; the policy that
Phase 0 builds and tests is the same one a future micro-live phase would
inherit, so it is written fail-closed from the start.

Closing or reducing an existing position is evaluated separately and is
**not** blocked by the kill switch — a kill switch exists to stop new or
growing risk, not to trap the account in an open position. It still
requires environment/account identity and reconciliation to check out.

## Future micro-live phase — only after explicit separate approval

Nothing below is active during Phase 0. It documents the frozen rules a
future, separately-approved micro-live phase must operate under. Enabling
it requires an explicit decision outside of Phase 0's scope — not a
config flip made in passing.

- Maximum initial funding: **USD 10**.
- No additional funding during the initial experiment (USD 0).
- Maximum 1 simultaneous position.
- Broker/symbol minimum size only — never a manually chosen lot size.
- No martingale.
- No averaging down.
- No recovery grid.
- No compounding.
- No automatic size increases.

## Success is not just "$10 became $11"

Turning $10 into $11 is not, by itself, evidence that anything worked.
Evaluating the future micro-live experiment also requires looking at:

- sample size (number of trades — too few tells you nothing)
- drawdown
- expectancy (gross and net)
- profit factor
- execution costs actually paid (fees, spread, slippage)
- realized slippage vs. what was assumed
- operational errors (missed fills, disconnects, duplicate-order attempts,
  reconciliation mismatches)
- dependence on a small number of outlier trades

A result that looks good only because of one lucky trade, or that used so
few trades that the outcome is statistically meaningless, is not a
validated result — regardless of the ending balance.
