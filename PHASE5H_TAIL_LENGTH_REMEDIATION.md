# Phase 5H — Run 2 Tail-Length Remediation

Run 2 is `INVALID — PRESERVED` and its partial artifacts are not research
evidence. Run 3 is reserved as `phase5h_run3_preregistered_failed_breakout`
and is **NOT RUN**.

## Root cause

An incomplete final event was correctly identified, but the old helper used
the conceptual operation `targets[start:start + 4] = [FLAT] * 4`. Python
allows a slice assignment to change list length. If fewer than four elements
exist at the tail, replacing that shorter slice with four values extends the
list; Run 2 consequently produced 6,189 signals for 6,186 bars.

## Corrected invariant

For every target transformation:

```text
len(targets before) == len(targets after) == len(bars)
```

The cleanup now mutates only existing indexes from `start` through
`min(start + 4, len(targets))`. An incomplete event is therefore fully
removed without extending, shifting, or truncating any target sequence.

Before the engine is called, the runner verifies the raw length, cleanup
length, bars/signals equality, every complete four-target block, its following
FLAT target, and availability of B6 for the required exit. Any violation
fails before historical execution.

## Tail decision matrix

An event at signal index `s` needs its four target positions plus B5 and B6,
so it requires at least six remaining sequence positions (`s` through `s+5`).

| Remaining positions | Outcome |
| ---: | --- |
| 0–5 | remove the incomplete event; sequence length unchanged |
| 6 or more | retain exactly all four event targets; sequence length unchanged |

This retains the Run 1 correction: never preserve a partial 1/4, 2/4, or 3/4
event block.
