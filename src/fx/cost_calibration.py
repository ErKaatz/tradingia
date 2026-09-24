"""Read-only, deterministic spread calibration for Phase 5C.

This module deliberately calibrates only what is observed in an immutable
historical FX dataset: MT5's per-bar spread field.  It does not infer
commission, slippage, or swap rates when the broker has not supplied them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from hashlib import sha256
import json

from src.fx.backtesting.costs import NoCommission, PerLotPerSide, SideAwareFixedSwapModel
from src.fx.data.schema import FxBar

MT5_SWAP_MODE_DISABLED = 0
MT5_SWAP_MODE_POINTS = 1


def mt5_rollover_day_to_python_weekday(mt5_day: int | None) -> int | None:
    """Map MT5 ``ENUM_DAY_OF_WEEK`` (Sunday=0) to Python weekday.

    Keeping the mapping here makes the broker's numeric metadata auditable and
    avoids leaking MT5-specific numbering into the backtest model.
    """
    if mt5_day is None:
        return None
    if not 0 <= mt5_day <= 6:
        raise ValueError(f"invalid MT5 rollover weekday={mt5_day!r}")
    return 6 if mt5_day == 0 else mt5_day - 1


def swap_points_cost_per_lot(*, swap_value: Decimal, swap_mode: int | None, point: Decimal,
                             contract_size: Decimal, currency_profit: str | None,
                             account_currency: str | None) -> Decimal:
    """Return a positive debit / negative credit per rollover for one lot.

    MT5 mode 1 is documented as points.  Other modes have different units
    (deposit currency, interest, reopen) and are intentionally rejected until
    their conversion is separately verified.
    """
    if swap_mode == MT5_SWAP_MODE_DISABLED:
        return Decimal("0")
    if swap_mode != MT5_SWAP_MODE_POINTS:
        raise ValueError(f"unsupported MT5 swap_mode={swap_mode!r}; refusing unit conversion")
    if currency_profit is None or account_currency is None or currency_profit != account_currency:
        raise ValueError("swap points require currency_profit == account_currency")
    if point <= 0 or contract_size <= 0:
        raise ValueError("point and contract_size must be positive")
    # MT5 reports a negative swap as a debit; backtest costs use positive debit.
    return -(swap_value * point * contract_size)


@dataclass(frozen=True)
class FrozenNonSpreadCosts:
    """Versionable non-spread terms observed for one account and symbol.

    Spread is deliberately absent: this object may be frozen before market
    history becomes available, but it cannot be mistaken for a full execution
    profile.  A positive swap is a debit; a negative swap is a credit.
    """

    symbol: str
    account_currency: str
    commission_per_lot_per_side: Decimal
    long_swap_per_lot: Decimal
    short_swap_per_lot: Decimal
    triple_swap_weekday: int | None
    source: str

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if not self.account_currency:
            raise ValueError("account_currency must not be empty")
        if self.commission_per_lot_per_side < 0:
            raise ValueError("commission_per_lot_per_side must be non-negative")

    def commission_model(self):
        return (NoCommission() if self.commission_per_lot_per_side == 0
                else PerLotPerSide(self.commission_per_lot_per_side))

    def swap_model(self) -> SideAwareFixedSwapModel:
        return SideAwareFixedSwapModel(
            long_rate_per_lot=self.long_swap_per_lot,
            short_rate_per_lot=self.short_swap_per_lot,
            triple_swap_weekday=self.triple_swap_weekday,
        )

    def fingerprint(self) -> str:
        payload = self.to_json_dict()
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_json_dict(self) -> dict[str, str | int | None]:
        return {
            "symbol": self.symbol, "account_currency": self.account_currency,
            "commission_per_lot_per_side": str(self.commission_per_lot_per_side),
            "long_swap_per_lot": str(self.long_swap_per_lot),
            "short_swap_per_lot": str(self.short_swap_per_lot),
            "triple_swap_weekday": self.triple_swap_weekday, "source": self.source,
        }


@dataclass(frozen=True)
class SpreadBucket:
    hour_utc: int
    observations: int
    missing: int
    median_points: Decimal | None
    p95_points: Decimal | None


@dataclass(frozen=True)
class SpreadCalibration:
    """A reproducible descriptive profile, not an execution-cost promise."""

    dataset_sha256: str
    buckets: tuple[SpreadBucket, ...]
    overall_observations: int
    overall_missing: int
    overall_p95_points: Decimal | None
    minimum_observations_per_hour: int

    def fingerprint(self) -> str:
        return sha256(json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def to_json_dict(self) -> dict:
        return {
            "dataset_sha256": self.dataset_sha256,
            "buckets": [{"hour": b.hour_utc, "n": b.observations, "missing": b.missing,
                         "median": str(b.median_points) if b.median_points is not None else None,
                         "p95": str(b.p95_points) if b.p95_points is not None else None} for b in self.buckets],
            "overall_p95": str(self.overall_p95_points) if self.overall_p95_points is not None else None,
            "overall_observations": self.overall_observations,
            "overall_missing": self.overall_missing,
            "minimum_observations_per_hour": self.minimum_observations_per_hour,
        }


def _quantile(sorted_values: list[int], numerator: int, denominator: int) -> Decimal | None:
    if not sorted_values:
        return None
    # Nearest-rank, deliberately conservative for p95 and reproducible.
    index = max(0, (len(sorted_values) * numerator + denominator - 1) // denominator - 1)
    return Decimal(sorted_values[index])


def _median(sorted_values: list[int]) -> Decimal | None:
    if not sorted_values:
        return None
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return Decimal(sorted_values[middle])
    return (Decimal(sorted_values[middle - 1]) + Decimal(sorted_values[middle])) / 2


def calibrate_spread_by_hour(bars: tuple[FxBar, ...], dataset_sha256: str, minimum_observations_per_hour: int = 30) -> SpreadCalibration:
    """Summarise observed MT5 spread points by UTC hour without filling gaps.

    Missing spread remains missing and is reported; it is never converted to
    zero.  Callers must choose a conservative policy before using this output
    in a backtest.
    """
    if minimum_observations_per_hour < 1:
        raise ValueError("minimum_observations_per_hour must be >= 1")
    values: dict[int, list[int]] = {hour: [] for hour in range(24)}
    missing: dict[int, int] = {hour: 0 for hour in range(24)}
    all_values: list[int] = []
    for bar in bars:
        hour = bar.timestamp_utc.hour
        if bar.spread_points is None:
            missing[hour] += 1
        else:
            values[hour].append(bar.spread_points)
            all_values.append(bar.spread_points)
    buckets = tuple(SpreadBucket(hour, len(sorted(values[hour])), missing[hour],
                                 _median(sorted(values[hour])) if len(values[hour]) >= minimum_observations_per_hour else None,
                                 _quantile(sorted(values[hour]), 95, 100) if len(values[hour]) >= minimum_observations_per_hour else None) for hour in range(24))
    return SpreadCalibration(
        dataset_sha256, buckets, len(all_values), sum(missing.values()),
        _quantile(sorted(all_values), 95, 100) if len(all_values) >= minimum_observations_per_hour else None,
        minimum_observations_per_hour,
    )


def apply_hourly_p95_spread(bars: tuple[FxBar, ...], calibration: SpreadCalibration) -> tuple[FxBar, ...]:
    """Return bars with their spread replaced by the frozen hourly P95.

    This is deliberately a separate, explicit research transformation: it
    never mutates the captured dataset and refuses a profile from another
    dataset or an insufficient hour rather than falling back to observed data.
    """
    values = {bucket.hour_utc: bucket.p95_points for bucket in calibration.buckets}
    transformed = []
    for bar in bars:
        spread = values.get(bar.timestamp_utc.hour)
        if spread is None:
            raise ValueError(f"no sufficient hourly P95 spread for UTC hour {bar.timestamp_utc.hour}")
        transformed.append(replace(bar, spread_points=int(spread)))
    return tuple(transformed)
