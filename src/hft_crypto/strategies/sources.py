"""Where a strategy's levels come from, so C15 can replace them and leave every rule as it is.

A strategy with levels or bands asks this object for each one at the close that first makes it knowable, and
reads the answer from then on. There are three sources, and the strategy's code is the same under all of them:

- `LevelSource` is the real run. It hands back what the document's formula gave.
- `RecordingSource` is also the real run, and it writes down each level's signed distance from the close, in
  `ATR` units. Those rows are the only input to a placebo's distance distribution.
- `PlaceboSource` is a C15 draw. It replaces the level with one drawn from earlier blocks.

**A kind is never pooled with another.** A set of levels born together, such as one day's pivots, is asked for
as one call and draws one earlier set's whole vector, so it keeps its real order and spacing. An object born
alone asks for one distance. A band asks for its anchor and keeps its own width, which `shifted` applies.

**Only earlier blocks.** `DistancePool.count_before` is the one way to reach a row, so a row from the current
block or a later one cannot be drawn.
"""

from __future__ import annotations

import bisect
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from hft_crypto.engine.tape import Bar
from hft_crypto.timeutil import date_of_us

ATR_UNDEFINED_AT_BIRTH = "ATR_UNDEFINED_AT_BIRTH"
NO_EARLIER_BLOCK = "NO_EARLIER_BLOCK"


def quarter_of(moment_us: int) -> int:
    """A calendar quarter as a running number. An instant on a boundary belongs to the one opening there."""
    day = date_of_us(moment_us)
    return day.year * 4 + (day.month - 1) // 3


def quarter_name(quarter: int) -> str:
    return f"{quarter // 4}-Q{quarter % 4 + 1}"


def shifted(placed: float, anchor: float, other: float) -> float:
    """A band's far edge, when its anchor has moved. The width stays the real object's width."""
    return placed + (other - anchor)


class LevelSource:
    """The real run: a level is what the document's formula says."""

    def vector(self, kind: str, values: dict[str, float], bar: Bar) -> dict[str, float] | None:
        del kind, bar
        return values


@dataclass(frozen=True)
class Birth:
    """One real object, or one set born together, as a signed distance from the close at its knowable time."""

    kind: str
    knowable_us: int
    distances: dict[str, float]


class RecordingSource(LevelSource):
    """The real run, unchanged, writing down what a later block may draw."""

    def __init__(self) -> None:
        self.births: list[Birth] = []

    def vector(self, kind: str, values: dict[str, float], bar: Bar) -> dict[str, float] | None:
        atr = bar.atr
        if atr is not None and atr > 0.0:
            distances = {name: (value - bar.c) / atr for name, value in values.items()}
            self.births.append(Birth(kind, bar.close_us, distances))
        return values


class DistancePool:
    """Real objects by kind and by block, in time order."""

    def __init__(self, births: list[Birth]) -> None:
        self._blocks: dict[str, list[int]] = {}
        self._rows: dict[str, list[Mapping[str, float]]] = {}
        for birth in sorted(births, key=lambda item: item.knowable_us):
            self._blocks.setdefault(birth.kind, []).append(quarter_of(birth.knowable_us))
            self._rows.setdefault(birth.kind, []).append(birth.distances)

    def count_before(self, kind: str, block: int) -> int:
        """How many rows of this kind were born in earlier blocks. Row 0 up to this count may be drawn."""
        blocks = self._blocks.get(kind)
        return 0 if blocks is None else bisect.bisect_left(blocks, block)

    def row(self, kind: str, index: int) -> Mapping[str, float]:
        return self._rows[kind][index]

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._rows))


class PlaceboSource(LevelSource):
    """One C15 draw. Every draw is uniform, with replacement, over the earlier blocks."""

    def __init__(self, pool: DistancePool, rng: random.Random) -> None:
        self._pool = pool
        self._rng = rng
        self.missing: Counter[str] = Counter()

    def vector(self, kind: str, values: dict[str, float], bar: Bar) -> dict[str, float] | None:
        atr = bar.atr
        if atr is None or atr <= 0.0:
            self.missing[ATR_UNDEFINED_AT_BIRTH] += 1
            return None
        count = self._pool.count_before(kind, quarter_of(bar.close_us))
        if count == 0:
            self.missing[NO_EARLIER_BLOCK] += 1
            return None
        row = self._pool.row(kind, uniform_index(self._rng, count))
        return {name: bar.c + row[name] * atr for name in values}


def uniform_index(rng: random.Random, size: int) -> int:
    """Below `size`, from `random()` alone, the one call whose sequence Python promises not to change."""
    return int(rng.random() * size)


def sample_without_replacement(rng: random.Random, items: list[int], count: int) -> list[int]:
    """A partial Fisher-Yates shuffle, resting on `random()` alone. Takes all if there are too few."""
    pool = list(items)
    chosen: list[int] = []
    for taken in range(min(count, len(pool))):
        pick = taken + uniform_index(rng, len(pool) - taken)
        pool[taken], pool[pick] = pool[pick], pool[taken]
        chosen.append(pool[taken])
    return chosen
