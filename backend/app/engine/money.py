"""Decimal USD accounting and bounded numerical tolerance for projected budgets."""
from math import isclose
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Iterable

USD_QUANTUM = Decimal("0.000000001")


def decimal_usd(value: float | Decimal) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Monetary values must be finite")
    return number.quantize(USD_QUANTUM, rounding=ROUND_HALF_EVEN)


def total_usd(values: Iterable[float | Decimal]) -> float:
    return float(sum((decimal_usd(value) for value in values), Decimal(0)))


def within_budget(amount: float, budget: float | None) -> bool:
    return budget is None or amount <= budget or isclose(amount, budget, rel_tol=0, abs_tol=1e-12)
