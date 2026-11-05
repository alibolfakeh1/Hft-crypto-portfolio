"""S04 Supply and demand zones, `V0`. See docs/01_strategies/S04_supply_demand_zones.md.

Readings the document leaves open, each reported:
- Two zones qualifying on one bar: the higher `Q` is taken.
- A target whose source zone broke, with no further candidate: the target stays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar
from hft_crypto.strategies.base import (
    BAR_GAP,
    BREAK_EVEN,
    INVALIDATION,
    NO_PATTERN,
    REST,
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
from hft_crypto.strategies.zones import Zone, ZoneBook

_SCALE_T1 = 0.5
_TARGET_Q = 45.0
_TARGET_TOUCHES = 2
_ABSORPTION_BARS = 6
_REACTION_BAR = 3
_T1_DEADLINE = {60: 24, 240: 12}
_ABSOLUTE = {60: 96, 240: 42}


@dataclass
class _Memo:
    prox: float
    dist: float
    mid: float
    extreme: float
    # The zone each target came from, if it came from one.
    sources: dict[str, str | None] = field(default_factory=dict)


class S04SupplyDemandZones(Strategy):
    id = "S04"
    h_max_hours: ClassVar[dict[int, float]] = {60: 96.0, 240: 168.0}
    requirements = (
        "ATR(14) on the decision timeframe, defined at the base",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "A zone born earlier, returned to for the first time",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.q_min = float(params["q_min"])
        self.touch_limit = int(params["touch_limit"])
        self.book = ZoneBook(self.timeframe_minutes)
        self._new_stack: list[Zone] = []

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        self.book.update(market.bars)
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
        if len(market.bars) < 2:
            self.note(NO_PATTERN)
            return []
        best: Proposal | None = None
        best_q = -1.0
        for zone in self.book.entry:
            quality = self.book.quality(zone, bar)
            if not zone.active or quality <= best_q or not self._qualifies(zone, market, quality):
                continue
            proposal = self._setup(market, bar, zone)
            if proposal is not None:
                best, best_q = proposal, quality
        if best is not None:
            return [best]
        self.note(NO_PATTERN)
        return []

    def _qualifies(self, zone: Zone, market: MarketView, quality: float) -> bool:
        bar = market.bar
        atr = bar.atr
        if atr is None:
            return False
        side = zone.side
        prox = side * zone.prox
        dist = side * zone.dist
        _, _, low, close = sided(bar, side)
        return (
            zone.touches_before(bar.close_us) <= self.touch_limit
            and quality >= self.q_min
            and side * market.bars[-2].c > prox
            and low <= prox
            and low >= dist - 0.25 * atr
            and close > prox
            and sided_clv(bar, side) >= 0.50
        )

    def _candidates(self, side: int, bar: Bar, extreme: float) -> list[tuple[float, str | None]]:
        """7.3, ascending as this side sees them: opposing zones, and the highest high since birth."""
        rows: list[tuple[float, str | None]] = [(extreme, None)]
        for zone in self.book.entry:
            if (
                zone.side == -side
                and zone.active
                and side * zone.prox > side * bar.c
                and self.book.quality(zone, bar) >= _TARGET_Q
                and zone.touches_before(bar.close_us) < _TARGET_TOUCHES
            ):
                rows.append((side * zone.prox, zone.id))
        rows.sort(key=lambda item: item[0])
        return rows

    def _setup(self, market: MarketView, bar: Bar, zone: Zone) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        side = zone.side
        close = side * bar.c
        struct = side * zone.dist - 0.25 * clip(vr, 0.8, 1.5) * atr
        s0 = min(struct, close - market.r_min(0.75))
        distance = close - s0
        if distance > 2.5 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        candidates = self._candidates(side, bar, zone.extreme)
        floor = close + 1.5 * distance
        ceiling = close + 6.0 * distance
        first = next((row for row in candidates if floor <= row[0] <= ceiling), None)
        t1 = first if first is not None else (close + 2.5 * distance, None)
        second = next((row for row in candidates if row[0] > t1[0]), None)
        t2 = second if second is not None else (t1[0] + 1.5 * distance, None)
        memo = _Memo(
            prox=side * zone.prox,
            dist=side * zone.dist,
            mid=side * zone.mid,
            extreme=zone.extreme,
            sources={"T1": t1[1], "T2": t2[1]},
        )
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1[0], _SCALE_T1), TargetPlan("T2", side * t2[0], REST)),
            level={"zone": zone.id, "prox": zone.prox, "dist": zone.dist},
            expiry_bars=4,
            memo=memo,
        )

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        _, _, _, close = sided(bar, side)
        n = position.n
        minutes = self.timeframe_minutes
        if n <= _ABSORPTION_BARS and close < memo.mid:
            return Management(exit_reason=INVALIDATION, exit_note="ABSORBED")
        t1_filled = position.filled("T1")
        if not t1_filled and n >= _T1_DEADLINE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if n == _REACTION_BAR and close < memo.prox + 0.5 * atr:
            decision.stops.append(StopCandidate(side * memo.dist, "REACTION_TEST"))
        if close >= position.fill_side + 1.0 * position.r:
            decision.stops.append(StopCandidate(side * memo.mid, "ZONE_SPENT"))
        if t1_filled:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        for zone in self.book.new_stack:
            if zone.side != side:
                continue
            if self.book.quality(zone, bar) >= self.q_min and side * zone.dist > side * position.stop:
                decision.stops.append(StopCandidate(side * (side * zone.dist - 0.25 * atr), "ZONE_STACK"))
        self._targets(bar, position, memo, decision, atr, t1_filled)
        return decision

    def _targets(
        self,
        bar: Bar,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        t1_filled: bool,
    ) -> None:
        """7.3 recompute, for the next unfilled target only."""
        side = position.side
        name = "T2" if t1_filled else "T1"
        current = position.target(name)
        if current is None:
            return
        target = side * current
        close = side * bar.c
        floor = close + 0.5 * atr
        for zone in self.book.new_entry:
            if zone.side != -side or not zone.active:
                continue
            price = side * zone.prox
            if floor <= price < target:
                target = price
                memo.sources[name] = zone.id
        source = memo.sources.get(name)
        broken = any(zone.id == source for zone in self.book.broken_now)
        if broken:
            following = next(
                (row for row in self._candidates(side, bar, memo.extreme) if row[0] >= floor), None
            )
            if following is not None:
                target = following[0]
                memo.sources[name] = following[1]
        if target != side * current:
            decision.targets.append(TargetMove(name, side * target, "ZONE_RECOMPUTE"))

    def snapshot(self) -> dict[str, Any]:
        return self.book.snapshot()
