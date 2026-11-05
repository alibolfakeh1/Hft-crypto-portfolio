"""S05 Zone polarity flip, `V0`. See docs/01_strategies/S05_zone_polarity_flip.md.

Readings the document leaves open, each reported:
- `X` updates at each close through the trigger, as section 4 says, though section 3 says "until the retest".
- Once a retest's three bars have passed with no trigger, the flip can give no trade, and it stays in the
register
  until its window ends.
- Two flips triggering on one bar: the one nearest the close.
"""

from __future__ import annotations

from dataclasses import dataclass
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
from hft_crypto.strategies.registers import SwingList, against, towards
from hft_crypto.strategies.zones import Zone, ZoneBook

_SCALE_T1 = 1.0 / 3.0
_ELIGIBLE_Q = 45.0
_RETEST_EXTRA = 2
_INVENTORY_BAR = 9
_T1_DEADLINE = {60: 18, 240: 9}
_ABSOLUTE = {60: 72, 240: 36}


@dataclass
class _Flip:
    """All prices in the trade's side space."""

    id: str
    side: int
    top: float
    bottom: float
    mid: float
    extreme: float
    break_index: int
    retest_start: int | None = None
    retest_low: float = 0.0
    dead_at: int | None = None
    traded: bool = False


@dataclass
class _Memo:
    flip_id: str
    top: float
    bottom: float
    mid: float
    extreme: float
    rebased: bool = False


class S05ZonePolarityFlip(Strategy):
    id = "S05"
    h_max_hours: ClassVar[dict[int, float]] = {60: 72.0, 240: 144.0}
    requirements = (
        "ATR(14) on the decision timeframe, defined at the zone's base",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "SRV: the same weekly slot in at least 4 of the previous 8 weeks, at the break bar",
        "A zone that formed and then broke, retested from the other side",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.window = int(params["rw"])
        self.book = ZoneBook(self.timeframe_minutes)
        self.swings = SwingList(3, 2, 1.0)
        self.flips: list[_Flip] = []
        self._new_swings: list[Any] = []

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        self.book.update(market.bars)
        self._new_swings = self.swings.update(market.bars)
        triggers = self._advance_flips(bar)
        self._new_flips(bar)
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
        for flip in sorted(triggers, key=lambda item: abs(item.side * bar.c - item.top)):
            proposal = self._setup(market, bar, flip)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _new_flips(self, bar: Bar) -> None:
        """A flip comes from a zone broken at this close, by a bar that meets the break conditions."""
        atr = bar.atr
        if atr is None:
            return
        for zone in self.book.broken_now:
            side = -zone.side  # a supply zone broken upward gives a long
            if not self._eligible(zone, bar, side, atr):
                continue
            top = side * zone.dist
            bottom = side * zone.prox
            self.flips.append(
                _Flip(zone.id, side, top, bottom, (top + bottom) / 2.0, sided(bar, side)[1], bar.index)
            )

    def _eligible(self, zone: Zone, bar: Bar, side: int, atr: float) -> bool:
        open_, _, _, close = sided(bar, side)
        return (
            zone.touches_before(bar.close_us) <= 1
            and self.book.quality(zone, bar) >= _ELIGIBLE_Q
            and close > side * zone.dist + 0.25 * atr
            and close - open_ >= 0.75 * atr
            and bar.srv is not None
            and bar.srv >= 1.2
            and bar.h - bar.l <= 4.0 * atr
        )

    def _advance_flips(self, bar: Bar) -> list[_Flip]:
        atr = bar.atr if bar.atr is not None else bar.atr_last
        triggers: list[_Flip] = []
        for flip in self.flips:
            if flip.dead_at is not None or flip.traded or atr is None:
                continue
            _, high, low, close = sided(bar, flip.side)
            flip.extreme = max(flip.extreme, high)
            in_retest = flip.retest_start is not None
            if close < flip.bottom - 0.25 * atr or (in_retest and close < flip.mid):
                flip.dead_at = bar.close_us
                continue
            if bar.index - flip.break_index > self.window:
                flip.dead_at = bar.close_us
                continue
            if flip.retest_start is None:
                # The first bar after travel with its low back at the top opens the retest.
                if flip.extreme - flip.top >= 1.0 * atr and low <= flip.top and bar.index > flip.break_index:
                    flip.retest_start = bar.index
                    flip.retest_low = low
            else:
                flip.retest_low = min(flip.retest_low, low)
            if flip.retest_start is None or bar.index - flip.retest_start > _RETEST_EXTRA:
                continue
            if low >= flip.bottom - 0.25 * atr and close > flip.top and sided_clv(bar, flip.side) >= 0.50:
                triggers.append(flip)
        return triggers

    def _setup(self, market: MarketView, bar: Bar, flip: _Flip) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        side = flip.side
        close = side * bar.c
        struct = flip.bottom - 0.25 * clip(vr, 0.8, 1.5) * atr
        s0 = min(struct, close - market.r_min(0.75))
        distance = close - s0
        if distance > 2.5 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        if flip.extreme - close < 0.75 * distance:
            self.note("NO_ROOM_TO_X")
            return None
        t1 = flip.extreme
        t2 = flip.extreme + (flip.extreme - flip.retest_low)
        memo = _Memo(flip.id, flip.top, flip.bottom, flip.mid, flip.extreme)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={
                "flip": flip.id,
                "top": side * flip.top,
                "bottom": side * flip.bottom,
                "x": side * flip.extreme,
            },
            expiry_bars=4,
            memo=memo,
        )

    def notify_sent(self, proposal: Proposal) -> None:
        for flip in self.flips:
            if flip.id == proposal.memo.flip_id:
                flip.traded = True

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        _, _, _, close = sided(bar, side)
        t1_filled = position.filled("T1")
        stage_b = t1_filled or close > memo.extreme
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        if not stage_b and close < memo.mid:
            return Management(exit_reason=INVALIDATION, exit_note="STAGE_A_BELOW_MID")
        if stage_b and frozen is not None and close < memo.top - 0.25 * frozen:
            return Management(exit_reason=INVALIDATION, exit_note="STAGE_B_REENTERED")
        n = position.n
        minutes = self.timeframe_minutes
        if not t1_filled and n >= _T1_DEADLINE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if not t1_filled and n == _INVENTORY_BAR:
            decision.stops.append(StopCandidate(side * (memo.mid - 0.25 * atr), "INVENTORY_CLOCK"))
        if t1_filled:
            decision.stops.append(StopCandidate(side * (memo.top - 0.25 * atr), "ZONE_MUST_HOLD"))
        if stage_b:
            self._stage_b(bar, position, memo, decision, atr, close)
        return decision

    def _stage_b(
        self,
        bar: Bar,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        close: float,
    ) -> None:
        side = position.side
        if close > memo.extreme:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        for swing in self._new_swings:
            if swing.kind != against(side) or swing.valid_from <= position.fill_us:
                continue
            price = side * swing.price
            if price > side * position.stop:
                decision.stops.append(StopCandidate(side * (price - 0.25 * atr), "HIGHER_LOW_STEP"))
            self._rebase(position, memo, decision, price, close, atr)
        current = position.target("T2")
        if current is None:
            return
        target = side * current
        for zone in self.book.new_entry:
            if zone.side != -side or not zone.active or self.book.quality(zone, bar) < _ELIGIBLE_Q:
                continue
            price = side * zone.prox
            if close + 0.5 * atr <= price < target:
                decision.targets.append(TargetMove("T2", side * price, "OPPOSING_ZONE"))
                target = price

    def _rebase(
        self,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        swing_low: float,
        close: float,
        atr: float,
    ) -> None:
        """7.3, once: the first swing low above the flip, after a swing high above `X` is also confirmed."""
        if memo.rebased or swing_low <= memo.top:
            return
        side = position.side
        highs = [
            side * entry.price
            for entry in self.swings.visible(towards(side))
            if entry.valid_from > position.fill_us and side * entry.price > memo.extreme
        ]
        if not highs:
            return
        memo.rebased = True
        swing_high = highs[-1]
        target = max(swing_high + (swing_high - swing_low), close + 1.0 * atr)
        decision.targets.append(TargetMove("T2", side * target, "REBASE"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "zones": self.book.snapshot(),
            "swings": self.swings.snapshot(),
            "flips": [
                [flip.id, flip.top, flip.bottom, flip.extreme, flip.retest_start, flip.dead_at, flip.traded]
                for flip in self.flips
            ],
        }
