"""Every settlement a funding file should hold, including those it does not.

C17 says a missing rate is logged as `DATA_GAP` and is not assumed, and C10 that it stays open as a reported
liability. So a settlement with no rate must first be seen. The file's own `funding_interval_hours` gives the
cadence, and a stretch longer than that holds settlements with no row. A venue can stamp a settlement a few
milliseconds late, and can change a contract's interval, so a gap counts only past half an interval, and the
interval is read from the row before each stretch.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from hft_crypto.engine.simulator import FundingEvent

_MICROS_PER_HOUR = 3_600_000_000


@dataclass(frozen=True)
class FundingRow:
    settle_us: int
    rate: float
    interval_hours: int

    @property
    def interval_us(self) -> int:
        return self.interval_hours * _MICROS_PER_HOUR


def funding_schedule(
    rows: Sequence[FundingRow], *, first_open_us: int, end_us: int
) -> tuple[FundingEvent, ...]:
    """Each row as it stands, and an event with no rate at each settlement the cadence says is missing.

    Inside the run's range only: after `first_open_us`, because no position exists at the first instant, and
    before `end_us`, since a settlement exactly at the end belongs to the next day and FP-07 means no position
    can owe it.
    """
    if not rows:
        return ()
    ordered = sorted(rows, key=lambda row: row.settle_us)
    events: list[FundingEvent] = []
    first = ordered[0]
    moment = first.settle_us - first.interval_us
    before: list[FundingEvent] = []
    while moment > first_open_us:
        before.append(FundingEvent(moment, None))
        moment -= first.interval_us
    events.extend(reversed(before))
    for row, following in itertools.pairwise(ordered):
        events.append(FundingEvent(row.settle_us, row.rate))
        steps = round((following.settle_us - row.settle_us) / row.interval_us)
        for step in range(1, steps):
            events.append(FundingEvent(row.settle_us + step * row.interval_us, None))
    last = ordered[-1]
    events.append(FundingEvent(last.settle_us, last.rate))
    moment = last.settle_us + last.interval_us
    while moment < end_us:
        events.append(FundingEvent(moment, None))
        moment += last.interval_us
    return tuple(events)


def missing_settlements(events: Sequence[FundingEvent]) -> tuple[int, ...]:
    return tuple(event.settle_us for event in events if event.rate is None)
