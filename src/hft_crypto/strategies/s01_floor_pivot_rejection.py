"""S01 Floor pivot rejection, `V0`. See docs/01_strategies/S01_floor_pivot_rejection.md.

Backtest only. Every output carries `NOT LIVE-COMPARABLE`, under section 14 of the document.

Left out, and reported: the `confluence` log, because the document does not say how close two levels must be
to coincide, and the `CYCLE` control run, because C-10 holds back every `CYCLE` run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, PeriodBar, weekday
from hft_crypto.strategies.base import (
    ATRD_RESTART_CLOSES,
    ATRD_RESTART_SETUPS_LOST,
    BAR_GAP,
    BREAK_EVEN,
    INVALIDATION,
    NO_LEVELS,
    NO_PATTERN,
    REST,
    SIDES,
    TIME_STOP,
    UNDEFINED_ATRD,
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
from hft_crypto.strategies.levels import Level, PeriodSets, floor_pivots, nearest_at_or_above
from hft_crypto.strategies.sources import LevelSource

_DAILY_FULL = ("S2", "S1", "P", "R1", "R2")
_DAILY_CORE = ("S1", "P", "R1")
_WEEKLY = ("S1", "P", "R1")
_ROLE_BARS = 4
_SCALE_T1 = 0.5
_T1_DEADLINE_BARS = 16
_ABSOLUTE_BARS = 48
SATURDAY = 5


@dataclass
class _LevelState:
    price: float
    # Per side: is a touch running, and how many touches so far.
    touching: dict[int, bool] = field(default_factory=lambda: {1: False, -1: False})
    index: dict[int, int] = field(default_factory=lambda: {1: 0, -1: 0})
    traded: bool = False


@dataclass
class _Memo:
    level_id: str
    level: float
    t2: float | None
    roll_end_us: int
    weekend_applied: bool


def is_weekend(close_us: int) -> bool:
    """The day of the bar opening at this close."""
    return weekday(close_us) >= SATURDAY


def _target_plan(t1: float, t2: float, close_us: int) -> tuple[TargetPlan, TargetPlan]:
    """7.4 and 7.5. On Saturday and Sunday UTC, T2 is dropped and everything exits at T1."""
    if is_weekend(close_us):
        return TargetPlan("T1", t1, REST), TargetPlan("T2", None, REST)
    return TargetPlan("T1", t1, _SCALE_T1), TargetPlan("T2", t2, REST)


class S01FloorPivotRejection(Strategy):
    id = "S01"
    # 7.10.
    v0s_m = 2.0
    v0s_hold_bars: ClassVar[dict[int, int]] = {15: 16, 30: 16}
    live_comparable = False
    h_max_hours: ClassVar[dict[int, float]] = {15: 12.0, 30: 24.0}
    requirements = (
        "ATR(14) on the decision timeframe",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "ATRD: 14 true ranges from consecutive completed UTC days",
        "The UTC day before the current one, complete",
    )

    def __init__(self, params: dict[str, Any], source: LevelSource | None = None) -> None:
        super().__init__(params)
        self.touch_limit = int(params["touch_limit"])
        level_set = params["level_set"]
        if level_set not in ("full", "daily_core"):
            raise ValueError(f"S01 has no level set named {level_set!r}")
        self.weekly = level_set == "full"
        self.daily_names = _DAILY_FULL if self.weekly else _DAILY_CORE
        self.sets = PeriodSets(source or LevelSource(), floor_pivots, weekly=self.weekly)
        self._states: dict[str, _LevelState] = {}

    def _levels_for(self, day: PeriodBar | None, week: PeriodBar | None, bar: Bar) -> list[Level]:
        levels = self.sets.levels("D", day, self.daily_names, bar)
        if self.weekly:
            levels += self.sets.levels("W", week, _WEEKLY, bar)
        return levels

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        self.sets.observe(bar)
        levels = self._levels_for(bar.day, bar.week, bar)
        self._states = {level.id: self._states.get(level.id, _LevelState(level.price)) for level in levels}
        self._count_touches(levels, bar, market.bars)
        if bar.gap:
            self.note(BAR_GAP)
            return []
        restart = self.watch_atrd(bar)
        missing = self.missing(bar, "atr", "vr", "atrd")
        if missing:
            self.note(missing)
            if restart and missing == UNDEFINED_ATRD:
                self.note(ATRD_RESTART_CLOSES)
                if self._lost_to_restart(market, bar, levels):
                    self.note(ATRD_RESTART_SETUPS_LOST)
            return []
        if bar.day is None or not levels:
            self.note(NO_LEVELS)
            return []
        if bar.day_open is None:
            self.note("DAY_OPEN_UNDEFINED")
            return []
        if bar.vr is not None and bar.vr > 1.75:
            self.note("VR_BLOCK")
            return []
        for side in SIDES:
            proposal = self._setup(market, bar, levels, side)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _lost_to_restart(self, market: MarketView, bar: Bar, levels: list[Level]) -> bool:
        """Whether this close would have given a setup with ATRD defined, so that day-move filter passing."""
        if bar.day is None or not levels or bar.day_open is None or bar.vr is None or bar.vr > 1.75:
            return False
        open_day = replace(bar, atrd=math.inf)
        return any(self.would_set_up(partial(self._setup, market, open_day, levels, side)) for side in SIDES)

    def _count_touches(self, levels: list[Level], bar: Bar, bars: list[Bar]) -> None:
        """Section 3: a touch of support is a bar where the level has that role and `L <= l + b`, so a level
        first seen above the price has no touch until price has held above it and come back.
        """
        atr = bar.atr
        for level in levels:
            state = self._states[level.id]
            for side in SIDES:
                _, _, low, _ = sided(bar, side)
                price = side * level.price
                now = atr is not None and low <= price + 0.10 * atr and self._has_role(bars, price, side)
                if now and not state.touching[side]:
                    state.index[side] += 1
                state.touching[side] = now

    def _has_role(self, bars: list[Bar], level: float, side: int) -> bool:
        if len(bars) <= _ROLE_BARS:
            return False
        for back in range(1, _ROLE_BARS + 1):
            earlier = bars[-1 - back]
            if earlier.atr is None or side * earlier.c <= level + 0.10 * earlier.atr:
                return False
        return True

    def _setup(self, market: MarketView, bar: Bar, levels: list[Level], side: int) -> Proposal | None:
        atr, vr, atrd, day_open = bar.atr, bar.vr, bar.atrd, bar.day_open
        if atr is None or vr is None or atrd is None or day_open is None:
            return None
        _, _, low, close = sided(bar, side)
        band = 0.10 * atr
        if side * day_open - close > 0.8 * atrd:
            return None
        if sided_clv(bar, side) < 0.60:
            return None
        chosen: Level | None = None
        for level in levels:
            state = self._states[level.id]
            price = side * level.price
            if (
                not state.traded
                and low <= price + band
                and low >= price - 0.75 * atr
                and close > price + band
                and state.index[side] <= self.touch_limit
                and self._has_role(market.bars, price, side)
                and (chosen is None or close - price < close - side * chosen.price)
            ):
                chosen = level
        if chosen is None:
            return None
        price = side * chosen.price
        k_s = 0.35 * clip(vr, 0.8, 1.5)
        struct = min(low, price - band) - k_s * atr
        r_min = market.r_min(0.8)
        if close - struct > 1.75 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        if r_min > 2.5 * atr:
            self.note("COST_VETO")
            return None
        s0 = min(struct, close - r_min)
        distance = close - s0
        first, second = nearest_at_or_above([side * item.price for item in levels], close + 1.2 * distance)
        if first is None:
            self.note("NO_T1_ROOM")
            return None
        t2 = second if second is not None else first + (first - price)
        day = bar.day
        if day is None:
            return None
        memo = _Memo(chosen.id, price, side * t2, day.end_us, is_weekend(bar.close_us))
        return Proposal(
            side=side,
            s0=side * s0,
            targets=_target_plan(side * first, side * t2, bar.close_us),
            level={"id": chosen.id, "price": chosen.price},
            expiry_bars=4,
            memo=memo,
        )

    def notify_sent(self, proposal: Proposal) -> None:
        state = self._states.get(proposal.memo.level_id)
        if state is not None:
            state.traded = True

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        t1_filled = position.filled("T1")
        _, _, _, close = sided(bar, side)
        # Exit rules do not fail open: they use the last defined ATR, under C3.
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        if not t1_filled and frozen is not None and close < memo.level - 0.25 * frozen:
            return Management(exit_reason=INVALIDATION, exit_note="LEVEL_LOST")
        n = position.n
        if not t1_filled and n >= _T1_DEADLINE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is not None:
            self._stops(market, position, memo, decision, atr, t1_filled)
            self._roll(bar, position, memo, decision, atr, t1_filled)
        self._weekend(bar, position, memo, decision, t1_filled)
        return decision

    def _stops(
        self,
        market: MarketView,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        t1_filled: bool,
    ) -> None:
        side = position.side
        fill = side * position.fill
        r = position.r
        n = position.n
        _, _, _, close = sided(market.bar, side)
        if not t1_filled:
            mfe_r = (position.highest - fill) / r if r > 0 else 0.0
            if n >= 4 and mfe_r < 0.75:
                candidate = fill - r * max(0.25, 1.0 - 0.125 * (n - 3))
                decision.stops.append(StopCandidate(side * candidate, "REACTION_CLOCK"))
            if close >= fill + 0.75 * r:
                decision.stops.append(StopCandidate(side * (memo.level - 0.25 * atr), "LEVEL_LOCK"))
            return
        decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        lows = [sided(item, side)[2] for item in market.bars[-3:]]
        decision.stops.append(StopCandidate(side * (min(lows) - 0.25 * atr), "FAST_TRAIL"))

    def _roll(
        self, bar: Bar, position: PositionView, memo: _Memo, decision: Management, atr: float, t1_filled: bool
    ) -> None:
        """7.3. The first close at which a newer completed day can be read is the roll for this trade."""
        day = bar.day_at_close
        if day is None or day.end_us <= memo.roll_end_us:
            return
        memo.roll_end_us = day.end_us
        side = position.side
        _, _, _, close = sided(bar, side)
        levels = self._levels_for(day, bar.week_at_close, bar)
        first, second = nearest_at_or_above([side * item.price for item in levels], close + 0.5 * atr)
        if first is None:
            return
        if t1_filled:
            memo.t2 = side * first
            decision.targets.append(TargetMove("T2", memo.t2, "UTC_ROLL"))
            return
        decision.targets.append(TargetMove("T1", side * first, "UTC_ROLL"))
        if second is not None:
            memo.t2 = side * second
            decision.targets.append(TargetMove("T2", memo.t2, "UTC_ROLL"))

    def _weekend(
        self, bar: Bar, position: PositionView, memo: _Memo, decision: Management, t1_filled: bool
    ) -> None:
        """7.5. Read from the day of the bar that opens next, so it first acts on Saturday's first bar."""
        weekend = is_weekend(bar.close_us)
        if weekend == memo.weekend_applied:
            if weekend:
                # T2 stays dropped, and a roll during the weekend only updates what comes back on Monday.
                decision.targets = [move for move in decision.targets if move.name != "T2"]
            return
        memo.weekend_applied = weekend
        t1_price = next((move.price for move in decision.targets if move.name == "T1"), position.target("T1"))
        decision.targets = [move for move in decision.targets if move.name != "T2"]
        decision.targets.append(
            TargetMove("T2", None if weekend else memo.t2, "WEEKEND_DROP" if weekend else "WEEKEND_OVER")
        )
        if not t1_filled:
            decision.targets.append(
                TargetMove(
                    "T1",
                    t1_price,
                    "WEEKEND_ALL_AT_T1" if weekend else "WEEKEND_OVER",
                    set_fraction=True,
                    fraction=REST if weekend else _SCALE_T1,
                )
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            level_id: {
                "price": state.price,
                "index": dict(state.index),
                "touching": dict(state.touching),
                "traded": state.traded,
            }
            for level_id, state in sorted(self._states.items())
        }
