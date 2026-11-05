"""The supply and demand zone register of S04 section 3, which S05 reuses exactly.

A zone is knowable at the close of its last departure bar, and never at its base. The register only ever
grows, and every state change carries its own time, under C4. Scores are computed at the close being
evaluated, from touches that have already happened.

All detection here is written in side space, where a demand zone has `side = 1` and a supply zone `side = -1`.
`prox` and `dist` are stored in real prices, as the documents write them.

A reading of 3 that the document leaves open: its departure conditions refer to the base, and its search says
to pick the departure first and the longest valid base afterwards. For each departure length, in order, this
takes the longest valid base ending just before it, and tests the departure against that base. The worked
example agrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hft_crypto.engine.tape import Bar
from hft_crypto.strategies.base import sided, sided_clv

_MAX_BASE = 5
_DEPARTURE_LENGTHS = (1, 2, 3)
_MAX_AGE_DAYS = 14


@dataclass
class Zone:
    id: str
    side: int
    prox: float
    dist: float
    atr_base: float
    departure: float
    tightness: float
    birth_index: int
    birth_us: int
    base_end: int
    is_entry: bool
    touch_starts: list[int] = field(default_factory=list)
    touching: bool = False
    broken_at: int | None = None
    dead_at: int | None = None
    superseded_at: int | None = None
    # The best price since birth for a trade from this zone, in side space.
    extreme: float = 0.0

    @property
    def mid(self) -> float:
        return (self.prox + self.dist) / 2.0

    @property
    def height(self) -> float:
        return abs(self.prox - self.dist)

    @property
    def active(self) -> bool:
        return self.broken_at is None and self.dead_at is None and self.superseded_at is None

    def touches_before(self, close_us: int) -> int:
        return sum(1 for start in self.touch_starts if start < close_us)


class ZoneBook:
    """Entry zones with the arrival condition, and stack zones without it, as two separate lists."""

    def __init__(self, minutes: int) -> None:
        self.max_age = _MAX_AGE_DAYS * 1440 // minutes
        self.entry: list[Zone] = []
        self.stack: list[Zone] = []
        self._seen: set[tuple[bool, int, int]] = set()
        self.new_entry: list[Zone] = []
        self.new_stack: list[Zone] = []
        self.broken_now: list[Zone] = []

    def quality(self, zone: Zone, bar: Bar) -> float:
        """Q at this close, with `age` at this close and touches whose first bar closed before it."""
        age = bar.index - zone.birth_index
        freshness = 0.5 ** zone.touches_before(bar.close_us) * max(0.0, 1.0 - age / self.max_age)
        return 100.0 * (0.5 * zone.departure + 0.3 * zone.tightness + 0.2 * freshness)

    def update(self, bars: list[Bar]) -> None:
        """Existing zones first, so a bar never touches a zone born at its own close. Then new births."""
        bar = bars[-1]
        self.new_entry = []
        self.new_stack = []
        self.broken_now = []
        self._age_and_touch(bar)
        self._detect(bars)

    def _age_and_touch(self, bar: Bar) -> None:
        atr = bar.atr if bar.atr is not None else bar.atr_last
        for zone in self.entry:
            if not zone.active:
                continue
            side = zone.side
            _, high, low, close = sided(bar, side)
            zone.extreme = max(zone.extreme, high)
            touching = low <= side * zone.prox
            if touching and not zone.touching:
                zone.touch_starts.append(bar.close_us)
            zone.touching = touching
            if atr is not None and close < side * zone.dist - 0.25 * atr:
                zone.broken_at = bar.close_us
                self.broken_now.append(zone)
                continue
            if bar.index - zone.birth_index > self.max_age:
                zone.dead_at = bar.close_us

    def _longest_base(self, bars: list[Bar], base_end: int) -> tuple[int, float] | None:
        atr = bars[base_end].atr
        if atr is None:
            return None
        start: int | None = None
        highest = -float("inf")
        lowest = float("inf")
        for index in range(base_end, max(base_end - _MAX_BASE, -1), -1):
            bar = bars[index]
            if bar.gap or bar.h - bar.l > 1.0 * atr or abs(bar.c - bar.o) > 0.5 * atr:
                break
            highest = max(highest, bar.h)
            lowest = min(lowest, bar.l)
            if highest - lowest > 1.5 * atr:
                break
            start = index
        return None if start is None else (start, atr)

    def _detect(self, bars: list[Bar]) -> None:
        k = len(bars) - 1
        for side in (1, -1):
            for length in _DEPARTURE_LENGTHS:
                base_end = k - length
                if base_end < 0:
                    break
                base = self._longest_base(bars, base_end)
                if base is None:
                    continue
                start, atr_base = base
                born = self._try_birth(bars, side, start, base_end, k, atr_base)
                if born:
                    break

    def _try_birth(
        self, bars: list[Bar], side: int, start: int, base_end: int, k: int, atr_base: float
    ) -> bool:
        departure_bars = bars[base_end + 1 : k + 1]
        if any(bar.gap for bar in departure_bars):
            return False
        views = [sided(bar, side) for bar in departure_bars]
        if not all(close > open_ for open_, _, _, close in views):
            return False
        ranges = [bar.h - bar.l for bar in departure_bars]
        if max(ranges) < 1.2 * atr_base:
            return False
        if sum(sided_clv(bar, side) for bar in departure_bars) / len(departure_bars) < 0.60:
            return False
        base_bars = bars[start : base_end + 1]
        base_views = [sided(bar, side) for bar in base_bars]
        _, _, _, close_e = views[-1]
        if close_e <= max(high for _, high, _, _ in base_views):
            return False
        prox = max(max(open_, close) for open_, _, _, close in base_views)
        if close_e - prox < 1.5 * atr_base:
            return False
        lowest = min(low for _, _, low, _ in base_views)
        dist = min(lowest, views[0][2])
        height = prox - dist
        if height < 0.1 * atr_base or height > 1.5 * atr_base:
            return False
        strength = min(1.0, (close_e - prox) / (3.0 * atr_base))
        if max(ranges) > 4.0 * atr_base:
            strength = min(strength, 0.5)
        tightness = 1.0 - min(1.0, height / (1.5 * atr_base))
        arrival = (
            start >= 3
            and not any(bar.gap for bar in bars[start - 3 : start])
            and sided(bars[start - 3], side)[0] - sided(bars[start - 1], side)[3] >= 1.0 * atr_base
        )
        bar = bars[k]
        for is_entry, wanted in ((False, True), (True, arrival)):
            if not wanted or (is_entry, side, base_end) in self._seen:
                continue
            self._seen.add((is_entry, side, base_end))
            zone = Zone(
                id=f"{'E' if is_entry else 'K'}:{side}:{bars[base_end].close_us}",
                side=side,
                prox=side * prox,
                dist=side * dist,
                atr_base=atr_base,
                departure=strength,
                tightness=tightness,
                birth_index=k,
                birth_us=bar.close_us,
                base_end=base_end,
                is_entry=is_entry,
                extreme=sided(bar, side)[1],
            )
            if is_entry:
                self._register_entry(zone, bar)
                self.entry.append(zone)
                self.new_entry.append(zone)
            else:
                self.stack.append(zone)
                self.new_stack.append(zone)
        return True

    def _register_entry(self, zone: Zone, bar: Bar) -> None:
        """The overlap rule, among entry zones only. Both stay in the register."""
        high_new = max(zone.prox, zone.dist)
        low_new = min(zone.prox, zone.dist)
        for other in self.entry:
            if other.side != zone.side or not other.active:
                continue
            overlap = min(high_new, max(other.prox, other.dist)) - max(low_new, min(other.prox, other.dist))
            if overlap <= 0.5 * zone.height:
                continue
            if self.quality(zone, bar) > self.quality(other, bar):
                other.superseded_at = zone.birth_us
            else:
                zone.superseded_at = zone.birth_us
                return

    def snapshot(self) -> dict[str, Any]:
        def row(zone: Zone) -> list[Any]:
            return [
                zone.id,
                zone.prox,
                zone.dist,
                zone.birth_us,
                list(zone.touch_starts),
                zone.broken_at,
                zone.dead_at,
                zone.superseded_at,
            ]

        return {"entry": [row(zone) for zone in self.entry], "stack": [row(zone) for zone in self.stack]}
