# Phase 5H — Holding-Semantics Remediation

Run 1 is `INVALID — SEMANTIC VALIDATION FAILURE`; its partial artifacts remain
preserved and are not research evidence.

## Frozen engine correspondence

The generic FX engine shifts a target known at close index `i` to execution at
open index `i + 1`.  For a Phase 5H confirmation B1 at signal index `s`:

| Meaning | Index | Timestamp action |
| --- | ---: | --- |
| breakout B0 | `s - 1` | close |
| confirmation / signal B1 | `s` | close |
| entry B2 | `s + 1` | open |
| completed holding bars | `s + 1` through `s + 4` | B2, B3, B4, B5 |
| exit B6 | `s + 5` | open |

Thus the strategy emits its side target at `s, s+1, s+2, s+3`, followed by
FLAT.  The engine reports `bars_held == 4` when it closes at `s+5`.

## Root cause and minimal repair

The runner's end-of-data helper tested every non-flat target independently.
For a valid final target block it retained `s` but erased `s+1:s+3`, so the
engine entered at `s+1` and closed at `s+2` with `bars_held == 1`.  The helper
now evaluates only a target block's first index and either retains all four
targets or removes the whole incomplete block.  This is an implementation
repair; no frozen research parameter or document changed.

The first observed failing event was validation SHORT: B0 `2025-08-29T17:00Z`,
B1/signal `2025-08-29T18:00Z`, actual entry `19:00Z`, actual premature exit
`20:00Z`, and reported `bars_held=1`.  It had a valid B6 at `23:00Z`; the
correct event would retain B2--B5 and exit at B6.  Therefore the issue was
execution semantics, not merely record metadata.

Run 2 ID is reserved as `phase5h_run2_preregistered_failed_breakout`; it has
not been run.
