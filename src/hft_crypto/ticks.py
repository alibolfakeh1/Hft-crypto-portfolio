"""C16's dated tick table, shared by the engine and by the data layer's checks after the fetch."""

from __future__ import annotations

import bisect
import itertools
from dataclasses import dataclass
from typing import Any

from hft_crypto.config import ConfigError
from hft_crypto.timeutil import iso_us

# A tick stated as one number holds at every instant, as if its row took effect before any data.
ALWAYS_US = -(2**62)


@dataclass(frozen=True)
class TickTable:
    """A symbol's tick by date. `at(t)` is the tick of the latest row taking effect at or before `t`.

    A change is known from the instant it takes effect, and earlier from its announcement, so reading the tick
    at an instant reads nothing later than that instant.
    """

    starts_us: tuple[int, ...]
    ticks: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.starts_us or len(self.starts_us) != len(self.ticks):
            raise ConfigError("a tick table needs one tick for each instant, and at least one row")
        if any(later <= earlier for earlier, later in itertools.pairwise(self.starts_us)):
            raise ConfigError("a tick table's rows must be in time order, with no instant twice")
        if any(isinstance(tick, bool) or not tick > 0.0 for tick in self.ticks):
            raise ConfigError("every tick must be a number above zero")

    @classmethod
    def single(cls, tick: float) -> TickTable:
        """One tick at every instant, as a plain number in a configuration states."""
        return cls((ALWAYS_US,), (tick,))

    @property
    def first_us(self) -> int:
        return self.starts_us[0]

    def at(self, moment_us: int) -> float:
        index = bisect.bisect_right(self.starts_us, moment_us) - 1
        if index < 0:
            raise ConfigError("no tick is in force before the first row of the tick table")
        return self.ticks[index]

    def as_output(self) -> float | list[dict[str, Any]]:
        if self.starts_us == (ALWAYS_US,):
            return self.ticks[0]
        return [
            {"from": iso_us(start), "tick": tick}
            for start, tick in zip(self.starts_us, self.ticks, strict=True)
        ]
