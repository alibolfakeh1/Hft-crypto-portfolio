"""S07 Anchored VWAP pullback, `V0`. See docs/01_strategies/S07_anchored_vwap_pullback.md.

Tier `T1`: the line is a sum over trades. On candles this gives no result and logs why. `T0-APPROX` is not
built, because the fold plan and leak recheck say it may not stand in, and this code offers no substitute.

A value exists only from the anchor's confirmation close, although the sum begins at the swing's extreme.
Each read uses trades at or before the close, through `MarketView`, which refuses anything later.

A reading the document leaves open, reported: a swing's age of at most 21 days runs from the close of its
extreme bar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from hft_crypto.engine.indicators import MICROS_PER_DAY
from hft_crypto.engine.market import MarketView, TradeSlice
from hft_crypto.engine.tape import Bar
from hft_crypto.strategies.base import (
    BAR_GAP,
    BREAK_EVEN,
    INVALIDATION,
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
from hft_crypto.strategies.registers import Swing, SwingList, against

_MINOR = (3, 3, 1.0)
_ANCHOR_AGE_DAYS = 21
_MAJOR_KEEP_DAYS = 27
_MINOR_KEEP_DAYS = 7
_SLOPE_BARS = 6
_SCALE_T1 = 0.5
_T1_DEADLINE_BARS = 24
_ABSOLUTE_BARS = 120


@dataclass
class Anchor:
    """Running totals from the start of the sum, in real prices. Updated once per close."""

    kind: str
    price: float
    extreme_close_us: int
    valid_from: int
    n: float = 0.0
    pq: float = 0.0
    ppq: float = 0.0
    values: dict[int, float] = field(default_factory=dict)
    close_beyond: bool = False
    excursion: bool = False
    triggers: int = 0

    def add(self, trades: TradeSlice) -> None:
        self.n += float(trades.qty.sum())
        weighted = trades.price * trades.qty
        self.pq += float(weighted.sum())
        self.ppq += float((trades.price * weighted).sum())

    @property
    def line(self) -> float:
        return self.pq / self.n

    @property
    def sigma(self) -> float:
        return math.sqrt(max(self.ppq / self.n - self.line * self.line, 0.0))


@dataclass
class _Memo:
    a0: Anchor
    stack: list[Anchor] = field(default_factory=list)
    below: int = 0


class S07AnchoredVwapPullback(Strategy):
    id = "S07"
    # 7.10.
    v0s_m = 2.0
    v0s_hold_bars: ClassVar[dict[int, int]] = {60: 48}
    needs_trades = True
    h_max_hours: ClassVar[dict[int, float]] = {60: 120.0}
    requirements = (
        "Trades, tier T1. On candles this strategy gives no result",
        "ATR(14) on the decision timeframe",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "A confirmed major swing, at least 6 bars old, not closed beyond, and at most 21 days old",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        lf, rt, a = params["major"]
        self.major = SwingList(int(lf), int(rt), float(a))
        self.minor = SwingList(*_MINOR)
        self.max_touch = int(params["max_touch"])
        self._anchors: dict[int, Anchor] = {}
        self._minors: dict[int, Anchor] = {}
        self._new_minor: list[Swing] = []

    def _anchor_from(self, swing: Swing, market: MarketView) -> Anchor:
        """The sum starts at the first trade at the extreme price, in the swing's own bar."""
        bars = market.bars
        center = bars[swing.bar_index]
        anchor = Anchor(swing.kind, swing.price, swing.extreme_close_us, swing.valid_from)
        inside = market.trades_between(center.open_us, center.close_us)
        hits = np.flatnonzero(inside.price == swing.price)
        first = int(hits[0]) if hits.size else 0
        anchor.add(TradeSlice(inside.price[first:], inside.qty[first:]))
        anchor.add(market.trades_between(center.close_us, market.now_us))
        return anchor

    def on_close(self, market: MarketView) -> list[Proposal]:
        if self.missing_tier(market):
            return []
        bars = market.bars
        bar = bars[-1]
        latest = market.trades_between(bar.open_us, bar.close_us)
        for group in (self._anchors, self._minors):
            for anchor in group.values():
                anchor.add(latest)
        for swing in self.major.update(bars):
            self._anchors[swing.valid_from * 2 + (swing.kind == "H")] = self._anchor_from(swing, market)
        self._new_minor = self.minor.update(bars)
        for swing in self._new_minor:
            self._minors[swing.valid_from * 2 + (swing.kind == "H")] = self._anchor_from(swing, market)
        self._forget(bar)
        self._advance_anchors(bar)
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
        triggered = [
            item for item in ((side, self._pullback(bar, side)) for side in SIDES) if item[1] is not None
        ]
        if len(triggered) == 2:
            self.note("BOTH_SIDES_TRIGGERED")
            return []
        for side, chosen in triggered:
            if chosen is None:
                continue
            proposal = self._setup(market, bar, side, chosen)
            if proposal is not None:
                chosen.triggers += 1
                chosen.excursion = False
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _forget(self, bar: Bar) -> None:
        for group, days in ((self._anchors, _MAJOR_KEEP_DAYS), (self._minors, _MINOR_KEEP_DAYS)):
            floor = bar.close_us - days * MICROS_PER_DAY
            for key in [key for key, anchor in group.items() if anchor.extreme_close_us < floor]:
                del group[key]

    def _advance_anchors(self, bar: Bar) -> None:
        for anchor in self._anchors.values():
            side = 1 if anchor.kind == "L" else -1
            line = anchor.line
            anchor.values[bar.index] = line
            if side * bar.c < side * anchor.price:
                anchor.close_beyond = True
            if side * bar.c >= side * line + anchor.sigma:
                anchor.excursion = True

    def _latest_anchor(self, side: int) -> Anchor | None:
        swing = self.major.latest(against(side))
        if swing is None:
            return None
        return self._anchors.get(swing.valid_from * 2 + (swing.kind == "H"))

    def _pullback(self, bar: Bar, side: int) -> Anchor | None:
        anchor = self._latest_anchor(side)
        atr = bar.atr
        if anchor is None or atr is None or anchor.close_beyond or anchor.triggers >= self.max_touch:
            return None
        if bar.close_us - anchor.extreme_close_us > _ANCHOR_AGE_DAYS * MICROS_PER_DAY or not anchor.excursion:
            return None
        earlier = anchor.values.get(bar.index - _SLOPE_BARS)
        if earlier is None:
            return None
        line = side * anchor.line
        sigma = anchor.sigma
        _, _, low, close = sided(bar, side)
        passes = (
            low <= line + 0.25 * sigma
            and low >= line - 0.50 * sigma
            and close > line
            and sided_clv(bar, side) >= 0.50
            and line >= side * earlier
            and sigma >= 0.75 * atr
        )
        return anchor if passes else None

    def _setup(self, market: MarketView, bar: Bar, side: int, anchor: Anchor) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        line = side * anchor.line
        sigma = anchor.sigma
        _, _, low, close = sided(bar, side)
        cushion = max(0.5 * sigma, 0.5 * atr)
        buffer = 0.25 * clip(vr, 0.8, 1.5) * atr
        struct = min(low, line - cushion) - buffer
        s0 = min(struct, close - market.r_min(1.0))
        distance = close - s0
        if distance > 2.5 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        floor = close + 0.25 * atr
        t1 = max(line + 1.5 * sigma, close + 1.0 * distance, floor)
        t2 = max(line + 3.0 * sigma, close + 2.0 * distance, floor)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"anchor_price": anchor.price, "line": anchor.line, "sigma": sigma},
            expiry_bars=4,
            memo=_Memo(anchor),
        )

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        _, _, _, close = sided(bar, side)
        line = side * memo.a0.line
        # 7.8: a bar with no trade is neither one of the two closes nor a break between them.
        if bar.has_price:
            memo.below = memo.below + 1 if close < line else 0
        if memo.below >= 2:
            return Management(exit_reason=INVALIDATION, exit_note="TWO_CLOSES_BELOW_A0")
        n = position.n
        t1_filled = position.filled("T1")
        if not t1_filled and n >= _T1_DEADLINE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE_BARS:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr, vr = bar.atr, bar.vr
        if atr is None:
            return decision
        for swing in self._new_minor:
            if swing.kind != against(side) or swing.valid_from <= position.fill_us:
                continue
            if swing.previous_price is None or side * swing.price > side * swing.previous_price:
                minor = self._minors.get(swing.valid_from * 2 + (swing.kind == "H"))
                if minor is not None:
                    memo.stack.append(minor)
        if vr is not None:
            buffer = 0.25 * clip(vr, 0.8, 1.5) * atr
            for anchor, reason in (
                (memo.a0, "ENTRY_ANCHOR"),
                *((item, "STACK_ANCHOR") for item in memo.stack),
            ):
                cushion = max(0.5 * anchor.sigma, 0.5 * atr)
                decision.stops.append(StopCandidate(side * (side * anchor.line - cushion - buffer), reason))
        if t1_filled:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        fill = position.fill_side
        r = position.r
        sigma = memo.a0.sigma
        floor = close + 0.25 * atr
        if not t1_filled:
            decision.targets.append(TargetMove("T1", side * max(line + 1.5 * sigma, fill + r, floor), "BAND"))
        decision.targets.append(
            TargetMove("T2", side * max(line + 3.0 * sigma, fill + 2.0 * r, floor), "BAND")
        )
        return decision

    def snapshot(self) -> dict[str, Any]:
        return {
            "major": self.major.snapshot(),
            "minor": self.minor.snapshot(),
            "anchors": {
                str(key): [
                    anchor.price,
                    anchor.n,
                    anchor.pq,
                    anchor.close_beyond,
                    anchor.excursion,
                    anchor.triggers,
                ]
                for key, anchor in sorted(self._anchors.items())
            },
        }
