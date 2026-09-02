from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class CostScenario:
    name: str
    fee_multiplier: float
    slippage_multiplier: float

DEFAULT_COST_SCENARIOS = [
    CostScenario("A_base", 1.0, 1.0),
    CostScenario("B_slippage_x2", 1.0, 2.0),
    CostScenario("C_slippage_x3", 1.0, 3.0),
    CostScenario("D_fee_x2", 2.0, 1.0),
    CostScenario("E_fee_x2_slippage_x3", 2.0, 3.0),
]
