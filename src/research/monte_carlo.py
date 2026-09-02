from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class MonteCarloSummary:
    simulations: int
    num_trades: int
    return_p05: float
    return_p50: float
    return_p95: float
    probability_negative: float
    max_drawdown_p05: float
    max_drawdown_p50: float
    max_drawdown_p95: float
    worst_final_return: float


def _path_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    equity = np.concatenate(([1.0], equity))
    peaks = np.maximum.accumulate(equity)
    dd = equity / peaks - 1.0
    return float(dd.min())


def monte_carlo_trade_returns(trade_returns: list[float] | np.ndarray, simulations: int = 1000, seed: int = 42) -> tuple[MonteCarloSummary, np.ndarray, np.ndarray]:
    r = np.asarray(trade_returns, dtype=float)
    if simulations < 1:
        raise ValueError("simulations must be >= 1")
    if len(r) == 0:
        raise ValueError("at least one trade return is required")
    if np.any(~np.isfinite(r)) or np.any(r <= -1):
        raise ValueError("trade returns must be finite and > -1")
    rng = np.random.default_rng(seed)
    # bootstrap with replacement: preserves number of trades while allowing
    # composition and ordering to vary; limitations are documented in research README.
    samples = rng.choice(r, size=(simulations, len(r)), replace=True)
    finals = np.prod(1.0 + samples, axis=1) - 1.0
    dds = np.array([_path_drawdown(row) for row in samples])
    summary = MonteCarloSummary(
        simulations=simulations,
        num_trades=len(r),
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
