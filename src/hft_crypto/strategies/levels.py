"""Floor pivot levels, from a completed UTC period only. S01 and S02 share these formulas."""

from __future__ import annotations

from dataclasses import dataclass

from hft_crypto.engine.tape import PeriodBar


@dataclass(frozen=True)
class Level:
    id: str
    price: float


def floor_pivots(period: PeriodBar) -> dict[str, float]:
    """P, R1, S1, R2, S2, and the target-only R3 and S3 of S02."""
    high, low, close = period.high, period.low, period.close
    pivot = (high + low + close) / 3.0
    return {
        "P": pivot,
        "R1": 2.0 * pivot - low,
        "S1": 2.0 * pivot - high,
        "R2": pivot + (high - low),
        "S2": pivot - (high - low),
        "R3": high + 2.0 * (pivot - low),
        "S3": low - 2.0 * (high - pivot),
    }


def period_levels(period: PeriodBar | None, kind: str, names: tuple[str, ...]) -> list[Level]:
    """Levels with ids that name their period, so a new day's P is a different level from yesterday's."""
    if period is None:
        return []
    values = floor_pivots(period)
    return [Level(f"{kind}:{period.end_us}:{name}", values[name]) for name in names]


def nearest_at_or_above(prices: list[float], floor: float) -> tuple[float | None, float | None]:
    """The lowest price at or above a floor, and the next one above that. Prices are in side space."""
    ordered = sorted(price for price in prices if price >= floor)
    first = ordered[0] if ordered else None
    second = next((price for price in ordered[1:] if first is not None and price > first), None)
    return first, second
