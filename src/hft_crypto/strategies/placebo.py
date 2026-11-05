"""The C15 placebos that are not a matter of replacing levels: S03, S07, S09 and S10.

Each is the real strategy with one thing swapped, as section 10 of its document says, and every other rule
comes from the real class, so a placebo cannot drift from what it is compared with. The levels and bands of
S01, S02, S04, S05, S06 and S08 need no subclass here, because they only take a `PlaceboSource`.

- **S03 and S10** enter on drawn bars. A scan finds the bars that pass their non-signal filters, using the
  same code as the real setup. `engine.placebo` draws from that list, and hands the result to the placebo
  class.
- **S09** moves each day's whole schedule by its own shift, from 1 to 23 hours.
- **S07** takes its anchors from drawn bars in place of its major swing list.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar
from hft_crypto.strategies.base import REST, SIDES, Proposal, TargetPlan
from hft_crypto.strategies.registers import HIGH, LOW, Swing, SwingList, against
from hft_crypto.strategies.s03_market_structure import _SCALE_T1 as S03_SCALE_T1
from hft_crypto.strategies.s03_market_structure import BOS, CHOCH, S03MarketStructure
from hft_crypto.strategies.s03_market_structure import _Memo as S03Memo
from hft_crypto.strategies.s07_anchored_vwap_pullback import S07AnchoredVwapPullback
from hft_crypto.strategies.s09_session_range_breakout import HOUR, S09SessionRangeBreakout, _Range
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression
from hft_crypto.strategies.sources import uniform_index

NOT_AN_ENTRY_BAR = "PLACEBO_NOT_AN_ENTRY_BAR"
_S03_T1_MULTIPLE = 1.5
_S03_T2_MULTIPLE = 3.0
_MAX_SHIFT_HOURS = 23


@dataclass(frozen=True)
class Eligible:
    """A close a placebo may enter on, for one side."""

    close_us: int
    side: int


class S03Scan(S03MarketStructure):
    """Runs the registers and lists the bars passing section 5's c, d, e and f. It proposes nothing."""

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.eligible: list[Eligible] = []

    def on_close(self, market: MarketView) -> list[Proposal]:
        self._advance(market)
        bar = market.bar
        atr, vr = bar.atr, bar.vr
        if atr is None or vr is None or not bar.complete:
            return []
        for side in SIDES:
            base, _ = self.sigma.latest_two(against(side))
            if base is not None and self.non_signal_failure(bar, side, base, atr, vr) is None:
                self.eligible.append(Eligible(bar.close_us, side))
        return []


class S03Placebo(S03MarketStructure):
    """Section 10. No swing was just broken at a drawn bar, so `SH` and `Leg` do not exist, and the fallback
    targets stand until a real break of the structure recomputes them under 7.3.
    """

    # A placebo long may be open while `state` is DOWN, so either kind of break against it exits it.
    exits_on: ClassVar[tuple[str, ...]] = (CHOCH, BOS)

    def __init__(self, params: dict[str, Any], entries: dict[int, int]) -> None:
        super().__init__(params)
        self._entries = entries

    def on_close(self, market: MarketView) -> list[Proposal]:
        self._advance(market)
        bar = market.bar
        side = self._entries.get(bar.close_us)
        if side is None:
            self.note(NOT_AN_ENTRY_BAR)
            return []
        atr, vr = bar.atr, bar.vr
        base, _ = self.sigma.latest_two(against(side))
        if atr is None or vr is None or base is None:
            return []
        close = side * bar.c
        s0 = self._initial_stop(market, close, side * base.price, atr, vr)
        if s0 is None:
            return []  # logged by the check, and an entry that fails is not replaced
        distance = close - s0
        return [
            Proposal(
                side=side,
                s0=side * s0,
                targets=(
                    TargetPlan("T1", side * (close + _S03_T1_MULTIPLE * distance), S03_SCALE_T1),
                    TargetPlan("T2", side * (close + _S03_T2_MULTIPLE * distance), REST),
                ),
                level={"placebo": True, "base_swing": base.price},
                expiry_bars=3,
                memo=S03Memo(),
            )
        ]


class S10Scan(S10VolatilityCompression):
    """Lists the bars where the box is armed: section 3's `CF` count and `BoxH` limit. It proposes nothing."""

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.eligible: list[Eligible] = []

    def on_close(self, market: MarketView) -> list[Proposal]:
        bars = market.bars
        bar = bars[-1]
        self._compressed.append(self._rank(bars))
        if (
            bar.complete
            and bar.atr is not None
            and len(self._widths) >= self._pr_minimum
            and self._armed_box(bars) is not None
        ):
            self.eligible.extend(Eligible(bar.close_us, side) for side in SIDES)
        return []


class S10Placebo(S10VolatilityCompression):
    """Section 10: the same stop and target model, from the box as of a drawn bar, with no breakout needed."""

    def __init__(self, params: dict[str, Any], entries: dict[int, int]) -> None:
        super().__init__(params)
        self._entries = entries

    def on_close(self, market: MarketView) -> list[Proposal]:
        bars = market.bars
        bar = bars[-1]
        self._compressed.append(self._rank(bars))
        side = self._entries.get(bar.close_us)
        if side is None:
            self.note(NOT_AN_ENTRY_BAR)
            return []
        armed = self._armed_box(bars)
        if armed is None:
            return []
        high, low, height, _ = armed
        box_high = high if side > 0 else -low
        proposal = self._setup(market, bar, side, box_high, height, (high + low) / 2.0)
        return [] if proposal is None else [proposal]


class S09Placebo(S09SessionRangeBreakout):
    """Section 10. Each day's real schedule moves by a shift drawn for that day, from 1 to 23 hours, so 0
    cannot occur, and `h_end`, `h_peak` and `T_flat` move with it. Shifted windows can overlap, and each runs
    alone.
    """

    def __init__(self, params: dict[str, Any], rng: random.Random) -> None:
        super().__init__(params)
        self._rng = rng
        self._waiting: list[_Range] = []
        self.shifts_hours: list[int] = []

    def _start_range(self, bar: Bar) -> None:
        schedule = self._schedule_from(bar)
        if schedule is not None:
            hours = 1 + uniform_index(self._rng, _MAX_SHIFT_HOURS)
            self.shifts_hours.append(hours)
            move = hours * HOUR
            self._waiting.append(
                _Range(
                    schedule.start_us + move,
                    schedule.end_us + move,
                    schedule.peak_us + move,
                    schedule.flat_us + move,
                )
            )
        for item in self._waiting:
            if item.start_us == bar.open_us:
                self._ranges.append(item)
        # A window whose first bar is missing never starts, as a real one would not.
        self._waiting = [item for item in self._waiting if item.start_us > bar.open_us]


class _DrawnSwings(SwingList):
    """A major swing list whose entries come from drawn bars and pass no test of amplitude or alternation.

    Each becomes usable `Rt` bars later, the same lag as a real swing. A bar a formula needs is still missing
    when it is missing, so a window with a gap gives no anchor, under C2.
    """

    def __init__(self, lf: int, rt: int, a: float, anchors: frozenset[tuple[int, str]]) -> None:
        super().__init__(lf, rt, a)
        self._anchors = anchors

    def update(self, bars: list[Bar]) -> list[Swing]:
        k = len(bars) - 1
        i = k - self.rt
        if i - self.lf < 0:
            return []
        center = bars[i]
        kinds = [kind for kind in (LOW, HIGH) if (center.close_us, kind) in self._anchors]
        if not kinds or bars[k].atr_last is None or any(bar.gap for bar in bars[i - self.lf : k + 1]):
            return []
        added = []
        for kind in kinds:
            previous = self.latest(kind)
            swing = Swing(
                kind,
                center.h if kind == HIGH else center.l,
                i,
                center.close_us,
                bars[k].close_us,
                previous_price=None if previous is None else previous.price,
            )
            self.entries.append(swing)
            added.append(swing)
        return added


class S07Placebo(S07AnchoredVwapPullback):
    """Section 10: a random anchor. The same rules run from it, and only the major list is replaced."""

    def __init__(self, params: dict[str, Any], anchors: frozenset[tuple[int, str]]) -> None:
        super().__init__(params)
        lf, rt, a = params["major"]
        self.major = _DrawnSwings(int(lf), int(rt), float(a), anchors)
