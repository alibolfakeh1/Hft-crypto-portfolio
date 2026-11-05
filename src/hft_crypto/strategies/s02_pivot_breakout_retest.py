"""S02 Pivot breakout, acceptance and retest, `V0`. See
docs/01_strategies/S02_pivot_breakout_acceptance_retest.md.

Readings the document leaves open, each reported:
- A level belongs to the set in force at a bar's open, under C2, so a sequence on a level ends when its set
rolls.
- Two retests on one bar take the level nearest the close.
- `NO_RETEST` is logged. Its counterfactual of buying at acceptance is not built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, PeriodBar
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
from hft_crypto.strategies.levels import Level, floor_pivots, nearest_at_or_above, period_levels

_TRADABLE = ("S2", "S1", "P", "R1", "R2")
_WEEKLY = ("S1", "P", "R1")
_RETEST_WINDOW = 12
_T1_DEADLINE_BARS = 24
_ABSOLUTE_BARS = 72
_PARTICIPATION_BAR = 6
_SCALE_T1 = 0.5


@dataclass
class _Sequence:
    """One level and side: closes counted so far, or accepted and waiting for a retest."""

    count: int = 0
    srv: list[float | None] = field(default_factory=list)
    accepted_at: int | None = None


@dataclass
class _Memo:
    level_id: str
    level: float
    rung_closes: dict[str, int] = field(default_factory=dict)
    srv: list[float | None] = field(default_factory=list)
    roll_end_us: int = 0
    t1_price: float | None = None


class S02PivotBreakoutRetest(Strategy):
    id = "S02"
    h_max_hours: ClassVar[dict[int, float]] = {60: 72.0}
    requirements = (
        "ATR(14) on the decision timeframe",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "SRV: the same weekly slot in at least 4 of the previous 8 weeks",
        "The UTC day before the current one, complete",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.acc = int(params["acc"])
        self.weekly = bool(params["weekly_levels"])
        self._sequences: dict[tuple[str, int], _Sequence] = {}
        self._traded: set[str] = set()
        self._set_key: tuple[int, int] | None = None

    def _tradable(self, day: PeriodBar | None, week: PeriodBar | None) -> list[Level]:
        levels = period_levels(day, "D", _TRADABLE)
        if self.weekly:
            levels += period_levels(week, "W", _WEEKLY)
        return levels

    def _target_prices(self, day: PeriodBar | None, week: PeriodBar | None, side: int) -> list[float]:
        """The tradable set plus the target-only R3 and S3."""
        prices = [side * level.price for level in self._tradable(day, week)]
        for period in (day, week) if self.weekly else (day,):
            if period is not None:
                values = floor_pivots(period)
                prices.append(side * values["R3" if side > 0 else "S3"])
        return prices

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        levels = self._tradable(bar.day, bar.week)
        key = (
            0 if bar.day is None else bar.day.end_us,
            0 if bar.week is None or not self.weekly else bar.week.end_us,
        )
        if key != self._set_key:
            self._set_key = key
            live = {level.id for level in levels}
            self._sequences = {seq: item for seq, item in self._sequences.items() if seq[0] in live}
            self._traded &= live
        candidates = self._advance_sequences(market, levels)
        if bar.gap:
            self.note(BAR_GAP)
            return []
        missing = self.missing(bar, "atr", "vr", "srv")
        if missing:
            self.note(missing)
            return []
        if not levels:
            self.note(NO_LEVELS)
            return []
        if bar.vr is not None and bar.vr > 2.0:
            self.note("VR_BLOCK")
            return []
        ordered = sorted(candidates, key=lambda item: abs(bar.c - item[0].price))
        for level, side in ordered:
            proposal = self._setup(market, bar, level, side)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _advance_sequences(self, market: MarketView, levels: list[Level]) -> list[tuple[Level, int]]:
        """Walk every level's state machine one close, in time order. Returns retests at this close."""
        bars = market.bars
        bar = bars[-1]
        atr = bar.atr
        found: list[tuple[Level, int]] = []
        if atr is None or len(bars) < 2:
            return found
        previous = bars[-2]
        for level in levels:
            for side in SIDES:
                price = side * level.price
                _, _, low, close = sided(bar, side)
                band = 0.10 * atr
                key = (level.id, side)
                sequence = self._sequences.get(key)
                if sequence is not None and sequence.accepted_at is None:
                    if close > price + band:
                        sequence.count += 1
                        sequence.srv.append(bar.srv)
                        if sequence.count == self.acc:
                            defined = [value for value in sequence.srv if value is not None]
                            if len(defined) == self.acc and sum(defined) / self.acc >= 1.0:
                                sequence.accepted_at = bar.index
                            else:
                                del self._sequences[key]
                    else:
                        del self._sequences[key]
                    sequence = self._sequences.get(key)
                    if sequence is None or sequence.accepted_at is not None:
                        continue
                    continue
                if sequence is not None and sequence.accepted_at is not None:
                    if close <= price - band:
                        del self._sequences[key]
                        continue
                    age = bar.index - sequence.accepted_at
                    is_retest = (
                        low <= price + 0.25 * atr
                        and low >= price - 0.50 * atr
                        and close > price + band
                        and sided_clv(bar, side) >= 0.50
                    )
                    if is_retest and level.id not in self._traded:
                        found.append((level, side))
                    if age >= _RETEST_WINDOW:
                        self.log("NO_RETEST", level=level.id, side=side)
                        del self._sequences[key]
                    continue
                if previous.atr is None:
                    continue
                prior_close = side * previous.c
                if close > price + band and prior_close <= price + 0.10 * previous.atr:
                    self._sequences[key] = _Sequence(count=1, srv=[bar.srv])
                    if self.acc == 1:
                        self._sequences[key].accepted_at = bar.index
        return found

    def _setup(self, market: MarketView, bar: Bar, level: Level, side: int) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        price = side * level.price
        _, _, low, close = sided(bar, side)
        k_s = 0.50 * clip(vr, 0.8, 1.5)
        struct = min(low, price) - k_s * atr
        s0 = min(struct, close - market.r_min(1.0))
        distance = close - s0
        if distance > 2.5 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        first, second = nearest_at_or_above(
            self._target_prices(bar.day, bar.week, side), close + 1.5 * distance
        )
        if first is None:
            self.note("NO_T1_ROOM")
            return None
        t2 = second if second is not None else first + (first - price)
        memo = _Memo(level.id, price, roll_end_us=0 if bar.day is None else bar.day.end_us)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * first, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"id": level.id, "price": level.price},
            expiry_bars=4,
            memo=memo,
        )

    def notify_sent(self, proposal: Proposal) -> None:
        self._traded.add(proposal.memo.level_id)

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        memo.srv.append(bar.srv)
        _, _, _, close = sided(bar, side)
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        if frozen is not None and close < memo.level - 0.10 * frozen:
            return Management(exit_reason=INVALIDATION, exit_note="ACCEPTANCE_LOST")
        n = position.n
        t1_filled = position.filled("T1")
        if not t1_filled and n >= _T1_DEADLINE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        fill = position.fill_side
        r = position.r
        if close >= fill + 1.0 * r:
            decision.stops.append(StopCandidate(side * (memo.level - 0.25 * atr), "LEVEL_TIGHTEN"))
        if n == _PARTICIPATION_BAR:
            defined = [value for value in memo.srv[:_PARTICIPATION_BAR] if value is not None]
            if len(defined) == _PARTICIPATION_BAR and sum(defined) / _PARTICIPATION_BAR < 0.8:
                decision.stops.append(StopCandidate(side * (memo.level - 0.10 * atr), "PARTICIPATION"))
        if close >= fill + 1.5 * r:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        if t1_filled:
            if memo.t1_price is None:
                memo.t1_price = position.target("T1")
            if memo.t1_price is not None:
                decision.stops.append(StopCandidate(side * (side * memo.t1_price - 1.5 * atr), "T1_REACHED"))
        self._ladder(market, position, memo, decision, atr)
        self._roll(bar, position, memo, decision, atr, t1_filled)
        return decision

    def _ladder(
        self, market: MarketView, position: PositionView, memo: _Memo, decision: Management, atr: float
    ) -> None:
        """Two consecutive closes above a rung, both from bars that open at or after its knowable time."""
        bar = market.bar
        side = position.side
        _, _, _, close = sided(bar, side)
        day = bar.day
        if day is None:
            return
        rungs = {level.id: side * level.price for level in self._tradable(day, bar.week)}
        values = floor_pivots(day)
        rungs[f"D:{day.end_us}:R3S3"] = side * values["R3" if side > 0 else "S3"]
        if self.weekly and bar.week is not None:
            weekly = floor_pivots(bar.week)
            rungs[f"W:{bar.week.end_us}:R3S3"] = side * weekly["R3" if side > 0 else "S3"]
        counts: dict[str, int] = {}
        for rung, price in rungs.items():
            if price <= memo.level:
                continue
            counts[rung] = memo.rung_closes.get(rung, 0) + 1 if close > price + 0.10 * atr else 0
            if counts[rung] >= 2:
                decision.stops.append(StopCandidate(side * (price - 0.50 * atr), "LADDER"))
        memo.rung_closes = counts

    def _roll(
        self, bar: Bar, position: PositionView, memo: _Memo, decision: Management, atr: float, t1_filled: bool
    ) -> None:
        """7.3, at the first close at which a newer completed day can be read."""
        day = bar.day_at_close
        if day is None or day.end_us <= memo.roll_end_us:
            return
        memo.roll_end_us = day.end_us
        side = position.side
        _, _, _, close = sided(bar, side)
        prices = self._target_prices(day, bar.week_at_close, side)
        if t1_filled:
            first, _ = nearest_at_or_above(prices, close + 0.5 * atr)
            if first is not None:
                decision.targets.append(TargetMove("T2", side * first, "UTC_ROLL"))
            return
        floor = max(close + 0.5 * atr, position.fill_side + 1.5 * position.r)
        first, second = nearest_at_or_above(prices, floor)
        if first is None:
            return
        decision.targets.append(TargetMove("T1", side * first, "UTC_ROLL"))
        if second is not None:
            decision.targets.append(TargetMove("T2", side * second, "UTC_ROLL"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "sequences": {
                f"{key[0]}|{key[1]}": [item.count, item.accepted_at]
                for key, item in sorted(self._sequences.items())
            },
            "traded": sorted(self._traded),
        }
