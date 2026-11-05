"""S10 Volatility compression expansion, `V0`. See its document in docs/01_strategies/."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.indicators import MICROS_PER_DAY, RollingWindow
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, weekday
from hft_crypto.strategies.base import (
    BAR_GAP,
    INVALIDATION,
    NO_PATTERN,
    REST,
    SIDES,
    TIME_STOP,
    UNDEFINED_ATR,
    UNDEFINED_SRV,
    Management,
    PositionView,
    Proposal,
    StopCandidate,
    Strategy,
    TargetMove,
    TargetPlan,
    clip,
    sided,
)

_BAND_BARS = 20
_PR_WINDOW_DAYS = 30
_RE_ARM_BARS = 12
_SCALE_T1 = 0.25
_THESIS_BAR = {240: 6, 60: 12}
_STALL_BAR = {240: 18, 60: 36}
_ABSOLUTE = {240: 60, 60: 120}
SATURDAY = 5
PR_UNDEFINED = "PR_UNDEFINED"


@dataclass
class _Memo:
    """Prices in the trade's side space."""

    box_high: float
    box_height: float
    box_mid: float
    atr_e: float
    armed: bool = False
    largest_tr: float = 0.0
    filled_t1: bool = False
    srv: list[float | None] = field(default_factory=list)
    thesis_checked: bool = False
    stall_checked: bool = False


class S10VolatilityCompression(Strategy):
    id = "S10"
    # 7.10.
    v0s_m = 4.0
    v0s_hold_bars: ClassVar[dict[int, int]] = {240: 36, 60: 72}
    h_max_hours: ClassVar[dict[int, float]] = {240: 240.0, 60: 120.0}
    requirements = (
        "ATR(14) on the decision timeframe",
        "PR: at least 15 days of band widths in the last 30 days, under C3",
        "SRV: the same weekly slot in at least 4 of the previous 8 weeks",
        "A box of B bars with no gap, and compression on at least 3 of the last 6 bars",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.pr_max = float(params["pr_max"])
        self.box_bars = int(params["box_bars"])
        per_day = 1440 // self.timeframe_minutes
        self._pr_minimum = _PR_WINDOW_DAYS * per_day / 2.0
        self._widths = RollingWindow(_PR_WINDOW_DAYS * MICROS_PER_DAY)
        self._compressed: list[bool] = []
        self._spent_until = -1

    def _rank(self, bars: list[Bar]) -> bool:
        """`CF_k` at the newest close, or False when `PR_k` is undefined."""
        bar = bars[-1]
        self._widths.advance(bar.close_us)
        window = bars[-_BAND_BARS:]
        if len(window) < _BAND_BARS or any(item.gap for item in window):
            return False
        closes = [item.c for item in window]
        mean = sum(closes) / _BAND_BARS
        deviation = math.sqrt(sum((value - mean) ** 2 for value in closes) / _BAND_BARS)
        width = 4.0 * deviation / mean
        self._widths.push(bar.close_us, width)
        if len(self._widths) < self._pr_minimum:
            return False
        return self._widths.share_at_or_below(width) <= self.pr_max

    def _armed_box(self, bars: list[Bar]) -> tuple[float, float, float, float] | None:
        """The box and `ATR_(k-1)` when section 3's armed condition holds. C15 enters on these bars too."""
        k = len(bars) - 1
        if k < max(self.box_bars, 6) + 1:
            return None
        prior_atr = bars[k - 1].atr
        box = bars[k - self.box_bars : k]
        if prior_atr is None or any(item.gap for item in box):
            return None
        high = max(item.h for item in box)
        low = min(item.l for item in box)
        height = high - low
        recent = self._compressed[k - 6 : k]
        if sum(1 for flag in recent if flag) < 3 or height > 4.0 * prior_atr:
            return None
        return high, low, height, prior_atr

    def on_close(self, market: MarketView) -> list[Proposal]:
        bars = market.bars
        bar = bars[-1]
        self._compressed.append(self._rank(bars))
        k = len(bars) - 1
        if bar.gap:
            self.note(BAR_GAP)
            return []
        if bar.atr is None:
            self.note(UNDEFINED_ATR)
            return []
        if len(self._widths) < self._pr_minimum:
            self.note(PR_UNDEFINED)
            return []
        if bar.srv is None:
            self.note(UNDEFINED_SRV)
            return []
        if k < self._spent_until:
            self.note(NO_PATTERN)
            return []
        armed = self._armed_box(bars)
        if armed is None:
            self.note(NO_PATTERN)
            return []
        high, low, height, prior_atr = armed
        weekend = weekday(bar.close_us - 1) >= SATURDAY
        if bar.tr is None or bar.tr < 1.0 * prior_atr or bar.srv < (1.25 if weekend else 1.0):
            self.note(NO_PATTERN)
            return []
        for side in SIDES:
            box_high = high if side > 0 else -low
            close = side * bar.c
            if close > box_high + 0.10 * prior_atr:
                # The state is spent by any breakout, traded or not.
                self._spent_until = k + _RE_ARM_BARS
                proposal = self._setup(market, bar, side, box_high, height, (high + low) / 2.0)
                if proposal is not None:
                    return [proposal]
                return []
        self.note(NO_PATTERN)
        return []

    def _setup(
        self, market: MarketView, bar: Bar, side: int, box_high: float, height: float, mid: float
    ) -> Proposal | None:
        atr = bar.atr
        if atr is None:
            return None
        close = side * bar.c
        mid_side = side * mid
        struct = mid_side - 0.25 * atr
        r_min = market.r_min(1.25)
        s0 = min(struct, close - r_min)
        if close - s0 > 3.0 * atr:
            s0 = close - 3.0 * atr
            if close - s0 < r_min:
                self.note("STOP_TOO_WIDE")
                return None
        distance = close - s0
        t1 = max(box_high + height, close + 2.0 * distance)
        memo = _Memo(box_high, height, mid_side, atr)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", None, REST)),
            level={"box_high": side * box_high, "box_mid": mid, "box_height": height},
            expiry_bars=2,
            memo=memo,
        )

    def on_fill(self, position: PositionView) -> list[TargetMove]:
        """7.3. The named exception to C7: `T1` is set at the fill, and rules the fill bar."""
        memo: _Memo = position.memo
        t1 = max(memo.box_high + memo.box_height, position.fill_side + 2.0 * position.r)
        return [TargetMove("T1", position.side * t1, "SET_AT_FILL")]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        _, _, _, close = sided(bar, side)
        n = position.n
        fill = position.fill_side
        r = position.r
        minutes = self.timeframe_minutes
        if bar.tr is not None:
            memo.largest_tr = max(memo.largest_tr, bar.tr)
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        ratio = None if frozen is None else frozen / memo.atr_e
        if close < memo.box_mid:
            return Management(exit_reason=INVALIDATION, exit_note="BACK_IN_THE_BOX")
        # 7.7: each is one check, at that close, or at the next close that has a price. A trade that passes
        # one is not checked again by it.
        if n >= _THESIS_BAR[minutes] and not memo.thesis_checked and bar.has_price:
            memo.thesis_checked = True
            if ratio is not None and ratio < 1.10 and memo.largest_tr < 1.25 * memo.atr_e:
                return Management(exit_reason=INVALIDATION, exit_note="THESIS_CHECK")
        if n >= _STALL_BAR[minutes] and not memo.stall_checked and bar.has_price:
            memo.stall_checked = True
            if close < fill + 1.0 * r:
                return Management(exit_reason=TIME_STOP, exit_note="STALL")
        if n >= _ABSOLUTE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if close >= fill + 1.0 * r:
            memo.armed = True
        if memo.armed:
            multiple = clip(4.5 - atr / memo.atr_e, 2.0, 3.5)
            decision.stops.append(StopCandidate(side * (memo.box_high - 0.50 * atr), "BOX_LOCK"))
            decision.stops.append(StopCandidate(side * (position.highest - multiple * atr), "CHANDELIER"))
        if position.filled("T1"):
            t2 = max(position.highest + 2.0 * atr, fill + 3.0 * r)
            decision.targets.append(TargetMove("T2", side * t2, "CLIMAX_TARGET"))
        return decision

    def snapshot(self) -> dict[str, Any]:
        return {"compressed": list(self._compressed), "spent_until": self._spent_until}
