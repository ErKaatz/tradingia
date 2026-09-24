# Phase 5D — FX strategy baselines status

The preregistered development/validation batch completed. See
`PHASE5D_RESULTS.md`: all eight non-control baselines were rejected and no
candidate exists. Phase 5D is **not formally closed** because its current
metric artifacts are invalid after simulated account insolvency; the untouched
test remains unobserved.

## Run 2 remediation

Run 1 remains preserved as the original preregistered observation: the account
was allowed to continue below zero, invalidating only its full account-level
metrics, not the observed negative trade-level PnL, expectancy, and profit
factor. The Phase 5D preregistration now defines a deterministic equity-based
`INSOLVENCY` terminal state. Run 2 will execute exactly the same eleven
variants on development and validation only, in the separate artifact root
`phase5d_run2_insolvency_policy`; it must not overwrite Run 1 or access test.

## Formal closure

Run 2 completed on development and validation only. Its explicit terminal
account policy removes the prior metric defect; all eight non-control variants
are `REJECT` and no candidate qualifies for untouched test. `control-flat`
remained solvent with zero trades and PnL. See `PHASE5D_RUN2_RESULTS.md` for
the complete results and terminal timestamps. Phase 5D is formally closed;
Phase 5E, if opened, requires its own preregistration and must not access the
Phase 5D untouched test merely because no candidate advanced.
