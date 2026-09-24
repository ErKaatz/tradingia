# Phase 5E — Multiple-testing ledger

Frozen before any Phase 5E historical performance calculation. There are eight
new strategic hypotheses and one non-hypothesis accounting control. A failed
entry remains recorded; no replacement or parameter modification is permitted
within this phase after evaluation begins. Untouched test is prohibited.

| ID | Family | Parameters | Status | Result |
|---|---|---|---|---|
| compression-expansion-16-4 | compression/expansion | ATR=16, range=4, ratio=.75, hold=4 | observed | A: 5 / 1.10; B: 3 / -0.42; Dev: 8 / 0.68; Val: 2 / -0.31; REJECT |
| compression-expansion-24-6 | compression/expansion | ATR=24, range=6, ratio=.70, hold=4 | observed | A: 1 / -0.49; B: 1 / -0.62; Dev: 2 / -1.11; Val: 1 / -1.44; REJECT |
| session-range-01-08 | session range | range=01:00–04:45, entry=08:00–10:45, hold=4 | observed | A: 240 / -52.91; B: 231 / -55.19; Dev: 422 / -99.71 I; Val: 220 / -36.47; REJECT |
| session-range-02-09 | session range | range=02:00–05:45, entry=09:00–11:45, hold=4 | observed | A: 243 / -58.18; B: 240 / -98.67; Dev: 340 / -99.71 I; Val: 225 / 2.75; REJECT |
| expansion-reversal-32-2p5-2 | expansion reversal | norm=32, threshold=2.5, hold=2 | observed | A: 743 / -99.00 I; B: 707 / -99.46 I; Dev: 743 / -99.00 I; Val: 702 / -96.85 I; REJECT |
| expansion-reversal-48-2p25-4 | expansion reversal | norm=48, threshold=2.25, hold=4 | observed | A: 983 / -84.20; B: 705 / -99.13 I; Dev: 1017 / -97.42 I; Val: 660 / -95.90 I; REJECT |
| impulse-continuation-32-2p5-2 | impulse continuation | norm=32, threshold=2.5, hold=2 | observed | A: 406 / -99.29 I; B: 435 / -99.71 I; Dev: 406 / -99.29 I; Val: 389 / -99.33 I; REJECT |
| impulse-continuation-48-2p25-4 | impulse continuation | norm=48, threshold=2.25, hold=4 | observed | A: 282 / -98.83 I; B: 495 / -98.05 I; Dev: 282 / -98.83 I; Val: 464 / -97.55 I; REJECT |
| control-flat | control | always flat | observed | A/B/Dev/Val: 0 trades / 0 PnL / solvent; CONTROL |

Multiple-testing count: **8** strategy variants across four families; the
flat control is descriptive and cannot be a candidate.
