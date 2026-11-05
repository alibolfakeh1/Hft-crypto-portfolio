"""S09 UTC session range breakout, `V0`. See docs/01_strategies/S09_utc_session_range_breakout.md.

Its seasonal profile is an estimated object under C12: fitted at each date of the calendar, from data before
that date only, and frozen until the next. Before the first fit there is no profile, so there is no setup.

The window is section 3 of the document: bars opening in the 90 calendar days before the date, Monday to
Friday UTC.

**A missing or zero-volume hour fails closed.** `m_h` takes a log of volume, and the document does not yet
say what to do with an hour that has none. Under C2, read strictly, a bar a formula needs is missing, so the
object is
not computed:
one such hour leaves that quarter with no profile, and so no setup, and the reason is logged. This is open
with
`strategy-architect`, and no substitute rule is invented here.

A reading the document leaves open, reported: the first close meeting the break conditions spends the day's
break, even if the setup then fails a later test such as `VR`.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, weekday
from hft_crypto.strategies.base import (
    ATRD_RESTART_CLOSES,
    ATRD_RESTART_RANGES_LOST,
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
)
from hft_crypto.timeutil import date_of_us, day_start_us

HOUR = 3_600_000_000
DAY = 24 * HOUR
_FIT_DAYS = 90
_CALENDAR_MONTHS = (1, 4, 7, 10)
_PEAK_SEARCH_HOURS = 8
_FLAT_AFTER_HOURS = 11
_BREAK_WINDOW_HOURS = 8
_SCALE_T1 = 0.5
SATURDAY = 5
NO_PROFILE = "SEASONAL_PROFILE_UNDEFINED"


@dataclass(frozen=True)
class SeasonalProfile:
    window_start_hour: int
    peak_hour: int
    fitted_at_us: int


@dataclass
class _Range:
    """A window of `W` hours on one day, and what follows from it."""

    start_us: int
    end_us: int
    peak_us: int
    flat_us: int
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    broken: bool = False
    gap: bool = False


@dataclass
class _Memo:
    """Prices in the trade's side space."""

    range_high: float
    range_width: float
    peak_us: int
    flat_us: int
    srv: list[float | None] = field(default_factory=list)
    armed: bool = False
    raised_at_peak: bool = False
    follow_checked: bool = False


def fit_profile(
    samples: dict[int, float], *, fitted_at_us: int, window_hours: int
) -> tuple[SeasonalProfile | None, str | None]:
    """C12 and section 3: mean log volume by hour, the quietest window, and the busiest hour after it.

    `samples` maps a 1h bar's open to its volume, for the bars this run holds with no gap. Returns the
    profile, or None and why not: every weekday hour in the 90 days before the date must be there, with volume
    above zero.
    """
    sums = [0.0] * 24
    counts = [0] * 24
    open_us = fitted_at_us - _FIT_DAYS * DAY
    while open_us < fitted_at_us:
        if weekday(open_us) < SATURDAY:
            volume = samples.get(open_us)
            if volume is None:
                return None, "MISSING_HOUR"
            if volume <= 0.0:
                return None, "ZERO_VOLUME_HOUR"
            hour = (open_us % DAY) // HOUR
            sums[hour] += math.log(volume)
            counts[hour] += 1
        open_us += HOUR
    means = [total / count for total, count in zip(sums, counts, strict=True)]
    totals = [sum(means[(start + offset) % 24] for offset in range(window_hours)) for start in range(24)]
    start = min(range(24), key=lambda hour: (totals[hour], hour))
    first_after = (start + window_hours) % 24
    candidates = [(first_after + offset) % 24 for offset in range(_PEAK_SEARCH_HOURS)]
    peak = max(candidates, key=lambda hour: (means[hour], -candidates.index(hour)))
    return SeasonalProfile(start, peak, fitted_at_us), None


def calendar_date_at_or_before(moment_us: int) -> int:
    """The newest estimation date of C12 at or before a moment."""
    day = date_of_us(moment_us)
    month = max((value for value in _CALENDAR_MONTHS if value <= day.month), default=None)
    if month is None:
        return day_start_us(dt.date(day.year - 1, 10, 1))
    return day_start_us(dt.date(day.year, month, 1))


class S09SessionRangeBreakout(Strategy):
    id = "S09"
    # 7.10.
    v0s_m = 2.0
    v0s_hold_bars: ClassVar[dict[int, int]] = {}
    h_max_hours: ClassVar[dict[int, float]] = {60: 11.0}
    requirements = (
        "A seasonal profile: every weekday hour in the 90 days before a calendar date of C12, with volume",
        "ATR(14) on the decision timeframe",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "SRV: the same weekly slot in at least 4 of the previous 8 weeks",
        "ATRD: 14 true ranges from consecutive completed UTC days",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.window_hours = int(params["window_hours"])
        self.srv_min = float(params["srv_min"])
        self._samples: dict[int, float] = {}
        self._profile: SeasonalProfile | None = None
        self._fitted_for: int | None = None
        self._ranges: list[_Range] = []
        self._qualified: list[_Range] = []

    def _maybe_refit(self, bar: Bar) -> None:
        date = calendar_date_at_or_before(bar.open_us)
        if date == self._fitted_for:
            return
        self._fitted_for = date
        self._profile, why = fit_profile(self._samples, fitted_at_us=date, window_hours=self.window_hours)
        if why is not None:
            self.log("SEASONAL_PROFILE_NOT_COMPUTED", fitted_at_us=date, reason=why)
            self.note(f"PROFILE_FIT_{why}")
        else:
            self.log(
                "SEASONAL_PROFILE_FITTED",
                fitted_at_us=date,
                window_start_hour=None if self._profile is None else self._profile.window_start_hour,
                peak_hour=None if self._profile is None else self._profile.peak_hour,
            )
        self._samples = {key: value for key, value in self._samples.items() if key >= date - DAY}

    def _schedule_from(self, bar: Bar) -> _Range | None:
        """The day's schedule, if the profile says this bar opens its window."""
        profile = self._profile
        if profile is None or (bar.open_us % DAY) // HOUR != profile.window_start_hour:
            return None
        start = bar.open_us
        end = start + self.window_hours * HOUR
        hour_at_end = (end % DAY) // HOUR
        peak = end + ((profile.peak_hour - hour_at_end) % 24) * HOUR
        return _Range(start, end, peak, end + _FLAT_AFTER_HOURS * HOUR)

    def _start_range(self, bar: Bar) -> None:
        schedule = self._schedule_from(bar)
        if schedule is not None:
            self._ranges.append(schedule)

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        restart = self.watch_atrd(bar)
        self._maybe_refit(bar)
        if not bar.gap:
            self._samples[bar.open_us] = bar.v
        self._start_range(bar)
        finished = self._collect_range(bar)
        proposal = self._look_for_break(market, bar)
        for item in finished:
            self._qualify(item, bar)
        if proposal is not None:
            return [proposal]
        if self._profile is None:
            self.note(NO_PROFILE)
            return []
        if bar.gap:
            self.note(BAR_GAP)
            return []
        missing = self.missing(bar, "atr", "vr", "srv", "atrd")
        self.note(missing if missing else NO_PATTERN)
        if restart:
            self.note(ATRD_RESTART_CLOSES)
        return []

    def _collect_range(self, bar: Bar) -> list[_Range]:
        """The ranges whose last bar this is. At most one, unless a placebo's moved windows overlap."""
        finished: list[_Range] = []
        still: list[_Range] = []
        for item in self._ranges:
            if bar.gap:
                item.gap = True
            else:
                item.highs.append(bar.h)
                item.lows.append(bar.l)
            if bar.close_us >= item.end_us:
                if not item.gap and len(item.highs) == self.window_hours:
                    finished.append(item)
            else:
                still.append(item)
        self._ranges = still
        return finished

    def _qualify(self, item: _Range, bar: Bar) -> None:
        atrd = bar.atrd
        if weekday(item.end_us) >= SATURDAY:
            return
        if atrd is None:
            if getattr(self, "_atrd_seen", False):
                self.note(ATRD_RESTART_RANGES_LOST)
            return
        width = max(item.highs) - min(item.lows)
        expected = atrd * math.sqrt(self.window_hours / 24.0)
        if expected > 0 and 0.35 <= width / expected <= 1.00:
            self._qualified.append(item)

    def _look_for_break(self, market: MarketView, bar: Bar) -> Proposal | None:
        result: Proposal | None = None
        still: list[_Range] = []
        for item in self._qualified:
            if bar.close_us > item.end_us + _BREAK_WINDOW_HOURS * HOUR:
                continue
            if item.broken:
                continue
            atr = bar.atr
            if atr is not None and bar.srv is not None and bar.srv >= self.srv_min and not bar.gap:
                for side in SIDES:
                    edge = max(item.highs) if side > 0 else -min(item.lows)
                    open_, _, _, close = sided(bar, side)
                    if close > edge + 0.10 * atr and close - open_ >= 0.5 * (bar.h - bar.l):
                        item.broken = True
                        self.log("BREAK", side=side, range_end_us=item.end_us)
                        setup = self._setup(market, bar, item, side, edge)
                        result = result if result is not None else setup
                        break
            if not item.broken:
                still.append(item)
        self._qualified = still
        return result

    def _setup(self, market: MarketView, bar: Bar, item: _Range, side: int, edge: float) -> Proposal | None:
        atr, vr = bar.atr, bar.vr
        if atr is None:
            return None
        if vr is None:
            self.note("VR_UNDEFINED_AT_BREAK")
            return None
        if vr > 2.0:
            self.note("VR_BLOCK")
            return None
        close = side * bar.c
        width = max(item.highs) - min(item.lows)
        middle = side * (max(item.highs) + min(item.lows)) / 2.0
        struct = middle - 0.25 * clip(vr, 0.8, 1.5) * atr
        s0 = min(struct, close - market.r_min(1.0))
        distance = close - s0
        if distance > 3.0 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        t1 = max(edge + 1.0 * width, close + 1.25 * distance)
        t2 = max(edge + 2.0 * width, close + 2.50 * distance)
        memo = _Memo(edge, width, item.peak_us, item.flat_us)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"range_high": max(item.highs), "range_low": min(item.lows)},
            expiry_bars=3,
            memo=memo,
        )

    def v0s_time_up(self, market: MarketView, position: PositionView) -> bool:
        """7.10: `H` is replaced by the same hard flat at `T_flat`."""
        memo: _Memo = position.memo
        return market.bar.close_us >= memo.flat_us

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        memo.srv.append(bar.srv)
        _, _, _, close = sided(bar, side)
        n = position.n
        fill = position.fill_side
        r = position.r
        if n <= 3 and close < memo.range_high - 0.25 * memo.range_width:
            return Management(exit_reason=INVALIDATION, exit_note="BACK_IN_THE_RANGE")
        # 7.7: one check, at n = 4 or once at the next close that has one, as S03's stall.
        if n >= 4 and not memo.follow_checked and bar.has_price:
            memo.follow_checked = True
            if close < fill + 0.5 * r:
                return Management(exit_reason=TIME_STOP, exit_note="NO_FOLLOW_THROUGH")
        if bar.close_us >= memo.flat_us:
            return Management(exit_reason=TIME_STOP, exit_note="HARD_FLAT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        mean_srv = None if any(value is None for value in memo.srv) else _mean(memo.srv)
        if n == 2 and mean_srv is not None and mean_srv < 1.0:
            decision.stops.append(StopCandidate(side * (memo.range_high - 0.25 * atr), "VOLUME_ARRIVAL"))
        if close >= fill + 1.0 * r:
            memo.armed = True
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
        if memo.armed:
            decision.stops.append(
                StopCandidate(
                    side * (position.highest - self._session_multiple(bar, memo) * atr), "CHANDELIER"
                )
            )
        self._targets(bar, position, memo, decision, atr, mean_srv)
        return decision

    def _session_multiple(self, bar: Bar, memo: _Memo) -> float:
        if bar.close_us < memo.peak_us:
            return 3.0
        return 2.0 if bar.close_us < memo.peak_us + 4 * HOUR else 1.25

    def _targets(
        self,
        bar: Bar,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        mean_srv: float | None,
    ) -> None:
        side = position.side
        current = position.target("T2")
        if current is None:
            return
        t2 = side * current
        if not memo.raised_at_peak and bar.close_us >= memo.peak_us:
            memo.raised_at_peak = True
            if bar.close_us == memo.peak_us and mean_srv is not None and mean_srv >= 1.5:
                t2 = max(t2, memo.range_high + 3.0 * memo.range_width)
        if bar.close_us >= memo.peak_us + 4 * HOUR:
            t2 = min(t2, position.highest + 1.0 * atr)
        if t2 != side * current:
            decision.targets.append(TargetMove("T2", side * t2, "SESSION_CLOCK"))

    def snapshot(self) -> dict[str, Any]:
        profile = self._profile
        return {
            "profile": None if profile is None else [profile.window_start_hour, profile.peak_hour],
            "ranges": [[item.start_us, item.end_us, item.gap] for item in self._ranges],
            "qualified": [[item.start_us, item.broken] for item in self._qualified],
        }


def _mean(values: list[float | None]) -> float:
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined)
