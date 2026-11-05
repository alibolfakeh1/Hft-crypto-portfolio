"""Causal indicators from convention C3, computed one closed bar at a time.

None of these holds fitted state, under timing contract item 10. Each value depends only on bars at or before
the one it is attached to, because the bars arrive one at a time and nothing here can look further.
"""

from __future__ import annotations

import bisect
from collections import deque

ATR_PERIOD = 14
MICROS_PER_DAY = 86_400_000_000
VR_WINDOW_DAYS = 30
SRV_LOOKBACK_WEEKS = 8
SRV_MIN_SLOTS = 4
_WEEK = 7 * MICROS_PER_DAY


def clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def true_range(high: float, low: float, previous_close: float) -> float:
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def clv(high: float, low: float, close: float) -> float:
    """Close location value, or 0.5 on a bar with no range."""
    return (close - low) / (high - low) if high != low else 0.5


class WilderAtr:
    """ATR(14), seeded with the mean of the first 14 true ranges.

    After a gap it is undefined until 14 complete bars have followed, and is then seeded again. `last` is the
    last defined value, which exit rules and register events use in the meantime, under C3.
    """

    __slots__ = ("_seed", "last", "value")

    def __init__(self) -> None:
        self.value: float | None = None
        self.last: float | None = None
        self._seed: list[float] = []

    def gap(self) -> None:
        self.value = None
        self._seed = []

    def update(self, tr: float) -> None:
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == ATR_PERIOD:
                self.value = sum(self._seed) / ATR_PERIOD
                self.last = self.value
                self._seed = []
            return
        self.value = ((ATR_PERIOD - 1) * self.value + tr) / ATR_PERIOD
        self.last = self.value


class RollingWindow:
    """Values in the last stretch of clock time, kept sorted so a median or a rank costs little."""

    __slots__ = ("_order", "_sorted", "_window_us")

    def __init__(self, window_us: int) -> None:
        self._window_us = window_us
        self._order: deque[tuple[int, float]] = deque()
        self._sorted: list[float] = []

    def advance(self, now_us: int) -> None:
        """Drop everything at or before the start of the window ending at now."""
        floor = now_us - self._window_us
        while self._order and self._order[0][0] <= floor:
            _, old = self._order.popleft()
            del self._sorted[bisect.bisect_left(self._sorted, old)]

    def push(self, now_us: int, value: float) -> None:
        self._order.append((now_us, value))
        bisect.insort(self._sorted, value)

    def __len__(self) -> int:
        return len(self._sorted)

    def median(self) -> float:
        count = len(self._sorted)
        middle = count // 2
        if count % 2:
            return self._sorted[middle]
        return (self._sorted[middle - 1] + self._sorted[middle]) / 2.0

    def share_at_or_below(self, value: float) -> float:
        return bisect.bisect_right(self._sorted, value) / len(self._sorted)


class VolatilityRatio:
    """VR_k: ATR_k over the median ATR in the last 30 days of clock time.

    Undefined with fewer than N/2 values in the window, where N is the number of bars in 30 days. The window
    is clock time and not a count of rows, so bars from another month can never stand in for this one.
    """

    __slots__ = ("_minimum", "_window")

    def __init__(self, minutes: int) -> None:
        per_day = 1440 // minutes
        self._minimum = VR_WINDOW_DAYS * per_day / 2.0
        self._window = RollingWindow(VR_WINDOW_DAYS * MICROS_PER_DAY)

    def update(self, close_us: int, atr: float | None) -> float | None:
        self._window.advance(close_us)
        if atr is None:
            return None
        self._window.push(close_us, atr)
        if len(self._window) < self._minimum:
            return None
        median = self._window.median()
        return atr / median if median > 0 else None


class SeasonalVolume:
    """SRV_k: volume over the median volume of the same weekly slot in each of the previous 8 weeks."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: dict[int, float] = {}

    def update(self, close_us: int, volume: float, *, usable: bool) -> float | None:
        slots = [
            self._seen[slot]
            for slot in (close_us - week * _WEEK for week in range(1, SRV_LOOKBACK_WEEKS + 1))
            if slot in self._seen
        ]
        if usable:
            self._seen[close_us] = volume
        if not usable or len(slots) < SRV_MIN_SLOTS:
            return None
        slots.sort()
        middle = len(slots) // 2
        median = slots[middle] if len(slots) % 2 else (slots[middle - 1] + slots[middle]) / 2.0
        return volume / median if median > 0 else None
