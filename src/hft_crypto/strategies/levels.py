"""Floor pivot levels, from a completed UTC period only. S01 and S02 share these formulas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hft_crypto.engine.tape import Bar, PeriodBar
from hft_crypto.strategies.sources import LevelSource


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


class PeriodSets:
    """Each completed period's values, fixed at the first close that can read that period.

    That close is the set's knowable time, so a placebo set is drawn there and not at whichever later close
    first needs it. A set whose source gives nothing stays empty for good, and the strategy reads it as no
    levels.
    """

    def __init__(
        self,
        source: LevelSource,
        compute: Callable[[PeriodBar], dict[str, float]],
        *,
        weekly: bool,
    ) -> None:
        self._source = source
        self._compute = compute
        self._weekly = weekly
        self._sets: dict[tuple[str, int], dict[str, float] | None] = {}

    def observe(self, bar: Bar) -> None:
        """At the top of every close, so a set is born here whether or not anything reads it."""
        self.at("D", bar.day_at_close, bar)
        self.at("D", bar.day, bar)
        if self._weekly:
            self.at("W", bar.week_at_close, bar)
            self.at("W", bar.week, bar)

    def at(self, kind: str, period: PeriodBar | None, bar: Bar) -> dict[str, float] | None:
        if period is None:
            return None
        key = (kind, period.end_us)
        if key not in self._sets:
            self._sets[key] = self._source.vector(kind, self._compute(period), bar)
        return self._sets[key]

    def levels(self, kind: str, period: PeriodBar | None, names: tuple[str, ...], bar: Bar) -> list[Level]:
        """Levels with ids that name their period, so a new day's P is a different level from yesterday's."""
        values = self.at(kind, period, bar)
        if values is None or period is None:
            return []
        return [Level(f"{kind}:{period.end_us}:{name}", values[name]) for name in names]


def nearest_at_or_above(prices: list[float], floor: float) -> tuple[float | None, float | None]:
    """The lowest price at or above a floor, and the next one above that. Prices are in side space."""
    ordered = sorted(price for price in prices if price >= floor)
    first = ordered[0] if ordered else None
    second = next((price for price in ordered[1:] if first is not None and price > first), None)
    return first, second
