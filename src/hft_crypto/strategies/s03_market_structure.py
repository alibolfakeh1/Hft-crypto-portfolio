"""S03 Market structure, BOS and CHoCH, `V0`. See docs/01_strategies/S03_market_structure_bos_choch.md.

Readings the document leaves open, each reported:
- At a recompute after entry, if no candidate clears the threshold, `T1` stays as it was. The fallback in 7.3
is
  written for the setup, and its terms do not exist at a later close.
"""

from __future__ import annotations

from collections import deque
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
from hft_crypto.strategies.registers import HIGH, LOW, Swing, SwingList, against, towards

_AMPLITUDE = 1.0
_CHOP_WINDOW = 72
_SCALE_T1 = 0.30
_HIGHER = {60: 240, 240: 1440}
_STALL_BARS = {60: 30, 240: 12}
_ABSOLUTE_BARS = {60: 240, 240: 60}
BOS = "BOS"
CHOCH = "CHOCH"


@dataclass
class _Memo:
    bos_since_entry: bool = False


class S03MarketStructure(Strategy):
    id = "S03"
    h_max_hours: ClassVar[dict[int, float]] = {60: 240.0, 240: 240.0}
    requirements = (
        "ATR(14) on the decision timeframe, and on its higher timeframe for the amplitude test",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "Confirmed swings on both sides, and a first break that sets the structure state",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        lf, rt = params["swing"]
        self.max_bos = int(params["max_bos"])
        self.sigma = SwingList(int(lf), int(rt), _AMPLITUDE)
        self.sigma_h = SwingList(int(lf), int(rt), _AMPLITUDE)
        self.state = "NONE"
        self.bos_count = 0
        self._choch_at: deque[int] = deque()
        # Events at the newest close: (kind, side, the swing broken).
        self.events: list[tuple[str, int, Swing]] = []
        self.new_swings: list[Swing] = []

    @property
    def higher_minutes(self) -> tuple[int, ...]:
        return (_HIGHER[self.timeframe_minutes],)

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        self._update_higher(market)
        self.new_swings = self.sigma.update(market.bars)
        self.events = self._run_state_machine(bar)
        while self._choch_at and self._choch_at[0] <= bar.index - _CHOP_WINDOW:
            self._choch_at.popleft()
        if bar.gap:
            self.note(BAR_GAP)
            return []
        missing = self.missing(bar, "atr", "vr")
        if missing:
            self.note(missing)
            return []
        for kind, side, broken in self.events:
            if kind != BOS:
                continue
            proposal = self._setup(market, bar, side, broken)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _update_higher(self, market: MarketView) -> None:
        """`Sigma_H`, on its own closed bars. Its `broken_at` comes at a close of its own timeframe."""
        frame = market.higher(_HIGHER[self.timeframe_minutes])
        if not frame.has_new_bar:
            return
        self.sigma_h.update(frame.bars)
        last = frame.last
        atr = last.atr if last.atr is not None else last.atr_last
        if atr is None:
            return
        for entry in self.sigma_h.entries:
            if entry.valid_to is not None or entry.broken_at is not None:
                continue
            side = 1 if entry.kind == HIGH else -1
            if side * last.c > side * entry.price + 0.10 * atr:
                entry.broken_at = last.close_us

    def _run_state_machine(self, bar: Bar) -> list[tuple[str, int, Swing]]:
        atr = bar.atr if bar.atr is not None else bar.atr_last
        events: list[tuple[str, int, Swing]] = []
        if atr is None:
            return events
        band = 0.10 * atr
        for side, kind, direction in ((1, HIGH, "UP"), (-1, LOW, "DOWN")):
            swing = self.sigma.latest(kind)
            if swing is None or swing.broken_at is not None:
                continue
            if side * bar.c > side * swing.price + band:
                swing.broken_at = bar.close_us
                if self.state == direction:
                    self.bos_count += 1
                    events.append((BOS, side, swing))
                else:
                    self.state = direction
                    self.bos_count = 0
                    self._choch_at.append(bar.index)
                    events.append((CHOCH, side, swing))
        return events

    def _setup(self, market: MarketView, bar: Bar, side: int, broken: Swing) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None:
            return None
        if self.bos_count > self.max_bos:
            self.note("BOS_COUNT_OVER_LIMIT")
            return None
        base, base_previous = self.sigma.latest_two(against(side), before_us=bar.close_us)
        if base is None or base_previous is None or side * base.price <= side * base_previous.price:
            self.note("NO_HIGHER_LOW")
            return None
        _, high, low, close = sided(bar, side)
        price = side * base.price
        if high - low > 3.0 * atr:
            self.note("CLIMAX_BAR")
            return None
        if close - price > 3.5 * atr:
            self.note("TOO_EXTENDED")
            return None
        if len(self._choch_at) > 2:
            self.note("CHOP")
            return None
        if vr > 2.0:
            self.note("VR_BLOCK")
            return None
        struct = price - 0.30 * clip(vr, 0.8, 1.5) * atr
        s0 = min(struct, close - market.r_min(1.0))
        distance = close - s0
        if distance > 4.0 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        broken_price = side * broken.price
        leg = broken_price - price
        t1 = self._lowest_candidate(side, broken_price, leg, close, close + 1.25 * distance)
        if t1 is None:
            t1 = close + 1.5 * distance
        t2 = broken_price + 2.618 * leg
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"broken_swing": broken.price, "base_swing": base.price},
            expiry_bars=3,
            memo=_Memo(),
        )

    def _lowest_candidate(
        self, side: int, broken_price: float, leg: float, close: float, threshold: float
    ) -> float | None:
        """The measured move, or the nearest unbroken higher-timeframe swing beyond the close."""
        candidates = [broken_price + 1.618 * leg]
        beyond = [
            side * entry.price
            for entry in self.sigma_h.visible(towards(side))
            if entry.broken_at is None and side * entry.price > close
        ]
        if beyond:
            candidates.append(min(beyond))
        eligible = [value for value in candidates if value >= threshold]
        return min(eligible) if eligible else None

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        minutes = self.timeframe_minutes
        for kind, event_side, _ in self.events:
            if kind == CHOCH and event_side == -side:
                return Management(exit_reason=INVALIDATION, exit_note="CHOCH_AGAINST")
        bos_now = [swing for kind, event_side, swing in self.events if kind == BOS and event_side == side]
        if bos_now:
            memo.bos_since_entry = True
        _, high, low, close = sided(bar, side)
        n = position.n
        fill = position.fill_side
        r = position.r
        if n >= _STALL_BARS[minutes] and not memo.bos_since_entry and close < fill + 1.0 * r:
            return Management(exit_reason=TIME_STOP, exit_note="STALL")
        if n >= _ABSOLUTE_BARS[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if bar.vr is not None:
            for swing in self.new_swings:
                if swing.kind != against(side) or swing.previous_price is None:
                    continue
                if side * swing.price > side * swing.previous_price:
                    buffer = 0.30 * clip(bar.vr, 0.8, 1.5) * atr
                    decision.stops.append(
                        StopCandidate(side * (side * swing.price - buffer), "HIGHER_LOW_STEP")
                    )
        for swing in bos_now:
            decision.stops.append(StopCandidate(side * (side * swing.price - 1.0 * atr), "BOS_LOCK"))
        if high - low >= 3.0 * atr and sided_clv(bar, side) >= 0.80:
            decision.stops.append(StopCandidate(side * (low - 0.25 * atr), "CLIMAX_TIGHTEN"))
        t1_filled = position.filled("T1")
        if t1_filled:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        if bos_now:
            self._recompute(position, decision, bos_now[-1], close, atr, t1_filled)
        return decision

    def _recompute(
        self,
        position: PositionView,
        decision: Management,
        broken: Swing,
        close: float,
        atr: float,
        t1_filled: bool,
    ) -> None:
        side = position.side
        base, _ = self.sigma.latest_two(against(side))
        if base is None:
            return
        broken_price = side * broken.price
        leg = broken_price - side * base.price
        if not t1_filled:
            threshold = position.fill_side + 1.25 * position.r
            t1 = self._lowest_candidate(side, broken_price, leg, close, threshold)
            if t1 is not None:
                decision.targets.append(TargetMove("T1", side * t1, "BOS_RECOMPUTE"))
        t2 = max(broken_price + 2.618 * leg, close + 0.5 * atr)
        decision.targets.append(TargetMove("T2", side * t2, "BOS_RECOMPUTE"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "sigma": self.sigma.snapshot(),
            "sigma_h": self.sigma_h.snapshot(),
            "state": self.state,
            "bos_count": self.bos_count,
            "chop": list(self._choch_at),
        }


_LOW = LOW
