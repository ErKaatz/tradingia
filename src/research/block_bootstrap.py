"""POST-HOC SHORT-HORIZON RESEARCH — optional block bootstrap (Task 20).

Short-horizon strategies can produce trade returns with temporal
dependence (e.g. a cluster of consecutive losing trades during a single
adverse regime, rather than independent draws). The existing
`monte_carlo_trade_returns` (i.i.d. bootstrap with replacement) assumes no
such dependence. This module adds a MOVING BLOCK BOOTSTRAP: instead of
resampling individual trade returns independently, it resamples
overlapping contiguous BLOCKS of `block_size` consecutive trades (in their
original chronological order) with replacement, concatenating blocks until
a full-length synthetic sequence is built.

This is a standard time-series bootstrap technique (moving block
bootstrap, Kunsch 1989) -- not a novel invention for this project. It is
NOT a full model of the trades' dependence structure: it only preserves
correlation *within* a block of length `block_size`; dependence longer
than one block is still broken at block boundaries. Choosing `block_size`
too small approaches the i.i.d. bootstrap's assumption; too large leaves
too few blocks to resample meaningfully. This module does not attempt to
select an "optimal" block size (that would itself be a form of post-hoc
tuning) -- callers must supply a reasoned fixed value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.research.monte_carlo import MonteCarloSummary, _path_drawdown


def block_bootstrap_trade_returns(
    trade_returns: list[float] | np.ndarray,
    block_size: int,
    simulations: int = 2000,
    seed: int = 42,
) -> tuple[MonteCarloSummary, np.ndarray, np.ndarray]:
    """Moving block bootstrap over a chronologically-ordered trade-return
    sequence. Same return shape/summary as `monte_carlo_trade_returns` for
    drop-in comparability, but resamples overlapping blocks of `block_size`
    consecutive trades instead of individual trades.
    """
    r = np.asarray(trade_returns, dtype=float)
    if simulations < 1:
        raise ValueError("simulations must be >= 1")
    if len(r) == 0:
        raise ValueError("at least one trade return is required")
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    if block_size > len(r):
        raise ValueError("block_size must be <= number of trade returns")
    if np.any(~np.isfinite(r)) or np.any(r <= -1):
        raise ValueError("trade returns must be finite and > -1")

    n = len(r)
    n_blocks_needed = math_ceil_div(n, block_size)
    max_block_start = n - block_size  # inclusive, so overlapping blocks are allowed

    rng = np.random.default_rng(seed)
    finals = np.empty(simulations)
    dds = np.empty(simulations)
    for sim_idx in range(simulations):
        block_starts = rng.integers(0, max_block_start + 1, size=n_blocks_needed)
        pieces = [r[start : start + block_size] for start in block_starts]
        sequence = np.concatenate(pieces)[:n]  # trim to original trade count
        finals[sim_idx] = np.prod(1.0 + sequence) - 1.0
        dds[sim_idx] = _path_drawdown(sequence)

    summary = MonteCarloSummary(
        simulations=simulations,
        num_trades=n,
        return_p05=float(np.quantile(finals, 0.05)),
        return_p50=float(np.quantile(finals, 0.50)),
        return_p95=float(np.quantile(finals, 0.95)),
        probability_negative=float(np.mean(finals < 0)),
        max_drawdown_p05=float(np.quantile(dds, 0.05)),
        max_drawdown_p50=float(np.quantile(dds, 0.50)),
        max_drawdown_p95=float(np.quantile(dds, 0.95)),
        worst_final_return=float(finals.min()),
    )
    return summary, finals, dds


def math_ceil_div(a: int, b: int) -> int:
    return -(-a // b)
