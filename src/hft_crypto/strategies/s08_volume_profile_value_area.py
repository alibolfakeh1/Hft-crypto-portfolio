"""S08 Volume profile value area, `V0`. See docs/01_strategies/S08_volume_profile_value_area.md.

Tier `T1`: a profile is built from every trade in its period. On candles this gives no result and logs why,
and nothing stands in for it.

Readings the document leaves open, each reported:
- A tie for the point of control left after "nearest the middle of the range" goes to the lower bin.
- At the roll, `T1` stays as it was. 7.3 names `VAH`, `POC` and `T2`, and only `T2` can act on the position's
rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from hft_crypto.engine.indicators import MICROS_PER_DAY
from hft_crypto.engine.market import MarketView, TradeSlice
from hft_crypto.engine.tape import Bar, floor_day
from hft_crypto.strategies.base import (
    BAR_GAP,
    BREAK_EVEN,
    INVALIDATION,
    NO_LEVELS,
    NO_PATTERN,
    REST,
    SIDES,
    TIME_STOP,
    Management,
    PositionView,
    Proposal,
    StopCandidate,
    Strategy,
    TargetMove,
    TargetPlan,
    clip,
    sided,
    sided_clv,
)

_VALUE_SHARE = 0.70
_BIN_SHARE = 0.0002
_DEVELOPING_HOURS = 6
_SCALE_T1 = 0.5
REJECTION = "REJECTION"
ACCEPTANCE = "ACCEPTANCE"
_COUNTS = {
    60: {"M": 4, "A": 3, "RW": 8, "T1_REJECTION": 8, "T1_ACCEPTANCE": 12, "ABSOLUTE": 24, "K": 6},
    30: {"M": 8, "A": 3, "RW": 16, "T1_REJECTION": 16, "T1_ACCEPTANCE": 24, "ABSOLUTE": 48, "K": 12},
}


@dataclass(frozen=True)
class ValueArea:
    poc: float
    vah: float
    val: float

    @property
    def vaw(self) -> float:
        return self.vah - self.val


def value_area(trades: TradeSlice, tick: float) -> ValueArea | None:
    """Section 3. `w` comes from the period's first trade, so a developing profile knows nothing of its later
    range.
    """
    if trades.price.size == 0:
        return None
    width = max(tick, _BIN_SHARE * float(trades.price[0]))
    bins = np.floor(trades.price / width).astype(np.int64)
    low_bin = int(bins.min())
    volumes = np.bincount(bins - low_bin, weights=trades.qty)
    total = float(volumes.sum())
    if total <= 0.0:
        return None
    most = float(volumes.max())
    middle = (float(trades.price.max()) + float(trades.price.min())) / 2.0
    tied = np.flatnonzero(volumes == most)
    centres = (tied + low_bin + 0.5) * width
    poc_index = int(tied[int(np.argmin(np.abs(centres - middle)))])
    low = high = poc_index
    area = float(volumes[poc_index])
    size = int(volumes.size)
    while area < _VALUE_SHARE * total:
        above = float(volumes[high + 1]) if high + 1 < size else None
        below = float(volumes[low - 1]) if low - 1 >= 0 else None
        if above is None and below is None:
            break
        if below is None or (above is not None and above > below):
            high += 1
            area += float(volumes[high])
        elif above is None or below > above:
            low -= 1
            area += float(volumes[low])
        else:
            high += 1
            low -= 1
            area += float(volumes[high]) + float(volumes[low])
    return ValueArea(
        poc=(poc_index + low_bin + 0.5) * width,
        vah=(high + 1 + low_bin) * width,
        val=(low + low_bin) * width,
    )


@dataclass
class _Machine:
    """One side's excursion, in that side's space: `s = 1` is below `VAL`, and `s = -1` is above `VAH`."""

    state: str = "INSIDE"
    start: int = 0
    extreme: float = 0.0
    closes_out: int = 0
    run_out: bool = True
    srv: list[float | None] = field(default_factory=list)
    accepted_at: int = 0


@dataclass
class _Memo:
    """Prices in the trade's own side space."""

    branch: str
    val: float
    poc: float
    far: float
    edge: float
    vaw: float
    roll_end_us: int
    q_started: bool = False
    q: int = 0
    raised: bool = False


class S08VolumeProfileValueArea(Strategy):
    id = "S08"
    h_max_hours: ClassVar[dict[int, float]] = {60: 24.0, 30: 24.0}
    requirements = (
        "Trades, tier T1. On candles this strategy gives no result",
        "ATR(14) on the decision timeframe",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "SRV, for the acceptance branch: the same weekly slot in at least 4 of the previous 8 weeks",
        "The completed UTC days the profile covers, all with no gap",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.profile_days = int(params["profile_days"])
        self.counts = _COUNTS[self.timeframe_minutes]
        self._areas: dict[int, ValueArea | None] = {}
        self._complete: set[int] = set()
        self._machines: dict[int, _Machine] = {1: _Machine(), -1: _Machine()}
        self._profile_end: int | None = None
        self._traded_sides: set[int] = set()

    def _area_ending(self, market: MarketView, end_us: int) -> ValueArea | None:
        """The profile for the period ending at a roll, from the completed days it covers. Cached once
        computed.
        """
        if end_us in self._areas:
            return self._areas[end_us]
        days = [end_us - back * MICROS_PER_DAY for back in range(self.profile_days)]
        if not all(day in self._complete for day in days):
            return None
        area = value_area(
            market.trades_between(end_us - self.profile_days * MICROS_PER_DAY, end_us), market.tick
        )
        self._areas[end_us] = area
        return area

    def _developing(self, market: MarketView, bar: Bar) -> ValueArea | None:
        """Today's trades up to this close, usable from six hours into the day."""
        start = floor_day(bar.close_us - 1)
        if bar.close_us - start < _DEVELOPING_HOURS * 3_600_000_000:
            return None
        return value_area(market.trades_between(start, bar.close_us), market.tick)

    def on_close(self, market: MarketView) -> list[Proposal]:
        if self.missing_tier(market):
            return []
        bars = market.bars
        bar = bars[-1]
        for period in (bar.day, bar.day_at_close):
            if period is not None:
                self._complete.add(period.end_us)
        if bar.day is None:
            self._reset(None)
            self.note(NO_LEVELS)
            return []
        area = self._area_ending(market, bar.day.end_us)
        if bar.day.end_us != self._profile_end:
            self._reset(bar.day.end_us)
        if area is None:
            self.note(NO_LEVELS)
            return []
        triggers = self._advance(bars, area)
        if bar.gap:
            self.note(BAR_GAP)
            return []
        missing = self.missing(bar, "atr", "vr")
        if missing:
            self.note(missing)
            return []
        if bar.vr is not None and bar.vr > 2.0:
            self.note("VR_BLOCK")
            return []
        for machine_side, branch in triggers:
            trade_side = machine_side if branch == REJECTION else -machine_side
            if trade_side in self._traded_sides:
                continue
            proposal = self._setup(market, bar, area, machine_side, branch, trade_side)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _reset(self, end_us: int | None) -> None:
        self._profile_end = end_us
        self._machines = {1: _Machine(), -1: _Machine()}
        self._traded_sides = set()

    def _advance(self, bars: list[Bar], area: ValueArea) -> list[tuple[int, str]]:
        bar = bars[-1]
        atr = bar.atr
        if atr is None:
            return []
        previous = bars[-2] if len(bars) >= 2 else None
        found: list[tuple[int, str]] = []
        for side in SIDES:
            machine = self._machines[side]
            edge = side * (area.val if side > 0 else area.vah)
            _, high, low, close = sided(bar, side)
            band = 0.10 * atr
            if machine.state == "INSIDE":
                if close < edge - band:
                    machine.state = "EXCURSION"
                    machine.start = bar.index
                    machine.extreme = low
                    machine.closes_out = 1
                    machine.run_out = True
                    machine.srv = [bar.srv]
            elif machine.state == "EXCURSION":
                machine.extreme = min(machine.extreme, low)
                if close < edge - band and machine.run_out:
                    machine.closes_out += 1
                    machine.srv.append(bar.srv)
                else:
                    machine.run_out = False
                age = bar.index - machine.start
                prior_held = (
                    previous is not None
                    and previous.atr is not None
                    and side * previous.c >= edge + 0.10 * previous.atr
                )
                if close >= edge + band and prior_held and age <= self.counts["M"]:
                    machine.state = "DONE"
                    found.append((side, REJECTION))
                elif self._accepted(machine):
                    machine.state = "ACCEPTED"
                    machine.accepted_at = bar.index
                elif age > self.counts["M"]:
                    machine.state = "DONE"
            elif machine.state == "ACCEPTED":
                if (
                    high >= edge - 0.25 * atr
                    and high <= edge + 0.50 * atr
                    and close < edge - band
                    and sided_clv(bar, side) <= 0.50
                ):
                    machine.state = "DONE"
                    found.append((side, ACCEPTANCE))
                elif bar.index - machine.accepted_at >= self.counts["RW"]:
                    machine.state = "DONE"
        return found

    def _accepted(self, machine: _Machine) -> bool:
        if machine.closes_out < self.counts["A"] or any(value is None for value in machine.srv):
            return False
        defined = [value for value in machine.srv if value is not None]
        return sum(defined) / len(defined) >= 1.0

    def _setup(
        self,
        market: MarketView,
        bar: Bar,
        area: ValueArea,
        machine_side: int,
        branch: str,
        side: int,
    ) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        buffer = 0.25 * clip(vr, 0.8, 1.5) * atr
        _, _, low, close = sided(bar, side)
        val = side * (area.val if side > 0 else area.vah)
        far = side * (area.vah if side > 0 else area.val)
        poc = side * area.poc
        real_edge = area.val if machine_side > 0 else area.vah
        edge = side * real_edge
        if branch == REJECTION:
            machine = self._machines[machine_side]
            if val - machine.extreme > 1.5 * atr:
                self.note("EXCURSION_TOO_DEEP")
                return None
            struct = machine.extreme - buffer
        else:
            struct = min(low, edge) - buffer
        s0 = min(struct, close - market.r_min(0.75))
        distance = close - s0
        if distance > 2.5 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        if branch == REJECTION:
            if poc - close < 0.75 * distance:
                self.note("NO_ROOM_TO_POC")
                return None
            t1, t2 = poc, far
        else:
            t1, t2 = edge + 0.5 * area.vaw, edge + 1.0 * area.vaw
        memo = _Memo(
            branch=branch,
            val=val,
            poc=poc,
            far=far,
            edge=edge,
            vaw=area.vaw,
            roll_end_us=0 if bar.day is None else bar.day.end_us,
        )
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"branch": branch, "poc": area.poc, "vah": area.vah, "val": area.val},
            expiry_bars=3,
            memo=memo,
            tag=branch,
        )

    def notify_sent(self, proposal: Proposal) -> None:
        self._traded_sides.add(proposal.side)

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        _, _, _, close = sided(bar, side)
        t1_filled = position.filled("T1")
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        rejection = memo.branch == REJECTION
        line = memo.val if rejection else memo.edge
        if not t1_filled and frozen is not None and close < line - 0.10 * frozen:
            return Management(exit_reason=INVALIDATION, exit_note="BACK_ACROSS_VALUE")
        n = position.n
        deadline = self.counts["T1_REJECTION" if rejection else "T1_ACCEPTANCE"]
        if not t1_filled and n >= deadline:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= self.counts["ABSOLUTE"]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if close >= position.fill_side + 1.0 * position.r:
            decision.stops.append(StopCandidate(side * (line - 0.25 * atr), "VALUE_LOCK"))
        developing = self._developing(market, bar)
        if t1_filled:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
            if developing is not None:
                near = side * (developing.val if side > 0 else developing.vah)
                decision.stops.append(StopCandidate(side * (near - 0.25 * atr), "VALUE_MIGRATION"))
        if rejection:
            self._rejection_target(market, bar, position, memo, decision, atr, close, t1_filled)
        elif developing is not None and not memo.raised and side * developing.poc > memo.edge:
            memo.raised = True
            decision.targets.append(TargetMove("T2", side * (memo.edge + 1.5 * memo.vaw), "VALUE_ABOVE_EDGE"))
        return decision

    def _rejection_target(
        self,
        market: MarketView,
        bar: Bar,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        close: float,
        t1_filled: bool,
    ) -> None:
        """7.3. `T2` decays with bars since `T1`, and moves to a new profile at the roll if it clears the
        price.
        """
        side = position.side
        day = bar.day_at_close
        if day is not None and day.end_us > memo.roll_end_us:
            memo.roll_end_us = day.end_us
            self._complete.add(day.end_us)
            area = self._area_ending(market, day.end_us)
            if area is not None:
                far = side * (area.vah if side > 0 else area.val)
                if far >= close + 0.5 * atr:
                    memo.far = far
                    memo.poc = side * area.poc
                    memo.q_started = False
                    memo.q = 0
                    decision.targets.append(TargetMove("T2", side * far, "UTC_ROLL"))
                    if t1_filled:
                        memo.q_started = True
                    return
        if not t1_filled:
            return
        if memo.q_started:
            memo.q = min(memo.q + 1, self.counts["K"])
        memo.q_started = True
        target = memo.far - (memo.q / self.counts["K"]) * 0.5 * (memo.far - memo.poc)
        decision.targets.append(TargetMove("T2", side * target, "ROTATION_DECAY"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "machines": {
                str(side): [item.state, item.start, item.extreme, item.closes_out, item.accepted_at]
                for side, item in self._machines.items()
            },
            "profile_end": self._profile_end,
            "traded": sorted(self._traded_sides),
        }
