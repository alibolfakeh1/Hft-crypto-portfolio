"""The data a run holds, private to the simulator. A strategy never receives anything from this module whole.

Bars come from `MarketReader`, and only 1m bars: decision-timeframe, daily and weekly bars are aggregated here
from those rows, as C2 and ruling 4 of the data center recheck require, and never read from stored higher bars
whose flags could rest on a later row.

**Standing is read as of the decision.** A close at t is decided with what was known at t + delay. A row whose
`knowable_time` is later than that has its standing resting on something later, so it reads as ruling 4 says:
an empty minute is unproven, and a traded minute reads as a build with no later row would give.

An unproven empty minute after the bar's last trade is a *pending tail*. The bar's prices are known and do not
change, so indicators and exit rules carry on, but the bar is not complete as of its close, so no setup is
created there. A proof that arrives later creates nothing retroactively. A gap that turns out to be real takes
effect from its own knowable time, as `late_gap` on the bar being closed when it became known.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.bars.core import TimingContractError
from hft_crypto.engine.indicators import (
    MICROS_PER_DAY,
    SeasonalVolume,
    VolatilityRatio,
    WilderAtr,
    clv,
    true_range,
)
from hft_crypto.timeutil import MICROS_PER_MINUTE

_IntArray = npt.NDArray[np.int64]
_FloatArray = npt.NDArray[np.float64]
_BoolArray = npt.NDArray[np.bool_]

MICROS_PER_WEEK = 7 * MICROS_PER_DAY
# 1970-01-05 was a Monday, and a UTC week runs from Monday 00:00.
_MONDAY_OFFSET = 4 * MICROS_PER_DAY
_REQUIRED_ROW_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "knowable_time",
)


def floor_day(value_us: int) -> int:
    return (value_us // MICROS_PER_DAY) * MICROS_PER_DAY


def floor_week(value_us: int) -> int:
    return ((value_us - _MONDAY_OFFSET) // MICROS_PER_WEEK) * MICROS_PER_WEEK + _MONDAY_OFFSET


def ceil_minute(value_us: int) -> int:
    return ((value_us + MICROS_PER_MINUTE - 1) // MICROS_PER_MINUTE) * MICROS_PER_MINUTE


def weekday(value_us: int) -> int:
    """Monday is 0. A time on a boundary reads as the day that opens there."""
    return ((value_us - _MONDAY_OFFSET) // MICROS_PER_DAY) % 7


@dataclass(frozen=True, slots=True)
class PeriodBar:
    """A completed UTC day or week, built from 1m rows."""

    start_us: int
    end_us: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Bar:
    """One closed bar, with everything knowable at its close. Immutable, so sharing it leaks nothing."""

    index: int
    minutes: int
    open_us: int
    close_us: int
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
    has_price: bool
    complete: bool
    pending_tail: bool
    gap: bool
    late_gap: bool
    tr: float | None
    atr: float | None
    atr_last: float | None
    vr: float | None
    srv: float | None
    clv: float
    # ATRD and the period bars in force at this bar's open, which is what a setup reads under C2.
    atrd: float | None
    day: PeriodBar | None
    week: PeriodBar | None
    # What a rule updating an open trade reads at this close, which can be the set that has just rolled.
    day_at_close: PeriodBar | None
    week_at_close: PeriodBar | None
    day_open: float | None


@dataclass(frozen=True)
class Standing:
    pending_tail: bool
    gap_known: bool
    has_price: bool
    # The last row in the span with a trade. Rows after it form the tail.
    last_priced_row: int


class TradeTape:
    """Trades in time order, for tier T1. Only `MarketView` reads this, and only up to its own close."""

    def __init__(self, ts_us: _IntArray, price: _FloatArray, qty: _FloatArray) -> None:
        self.ts_us = ts_us
        self.price = price
        self.qty = qty

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> TradeTape:
        if frame.is_empty():
            empty_int: _IntArray = np.empty(0, dtype=np.int64)
            empty_float: _FloatArray = np.empty(0, dtype=np.float64)
            return cls(empty_int, empty_float, empty_float)
        sorted_frame = frame.sort(["ts", "trade_id", "file_row"])
        ts_us = cast(_IntArray, sorted_frame["ts"].dt.timestamp("us").to_numpy().astype(np.int64))
        price = cast(_FloatArray, sorted_frame["price"].to_numpy().astype(np.float64))
        qty = cast(_FloatArray, sorted_frame["qty"].to_numpy().astype(np.float64))
        return cls(ts_us, price, qty)

    def digest(self) -> str:
        hasher = hashlib.sha256()
        for array in (self.ts_us, self.price, self.qty):
            hasher.update(array.tobytes())
        return hasher.hexdigest()


class MinuteTape:
    """1m rows for one symbol, plus every higher bar built from them for a stated decision delay."""

    def __init__(
        self,
        *,
        symbol: str,
        open_us: _IntArray,
        close_us: _IntArray,
        open_: _FloatArray,
        high: _FloatArray,
        low: _FloatArray,
        close: _FloatArray,
        volume: _FloatArray,
        trade_count: _IntArray,
        gap: _BoolArray,
        knowable_us: _IntArray,
        delay_us: int,
    ) -> None:
        self.symbol = symbol
        self.open_us = open_us
        self.close_us = close_us
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.trade_count = trade_count
        self.gap = gap
        self.knowable_us = knowable_us
        self.delay_us = delay_us
        self.size = int(close_us.size)
        self._frames: dict[int, list[Bar]] = {}
        self._gap_rows: _IntArray = np.flatnonzero(gap).astype(np.int64)
        priced = np.flatnonzero(~np.isnan(close))
        self._priced_close_us: _IntArray = close_us[priced]
        self._priced_close: _FloatArray = close[priced]

    @classmethod
    def from_frame(cls, frame: pl.DataFrame, *, symbol: str, delay_us: int) -> MinuteTape:
        """A frame of 1m rows from the reader. Official candles and bars built from trades both fit.

        A candle publishes a price on a minute with no trades, and such a minute must touch nothing, so its
        prices are removed here. Candles carry no gap flag, because a missing minute there is a missing row.
        """
        missing = [name for name in _REQUIRED_ROW_COLUMNS if name not in frame.columns]
        if missing:
            raise TimingContractError(f"1m rows are missing columns {missing}")
        rows = frame.sort("open_time")
        count = cast(_IntArray, rows["trade_count"].to_numpy().astype(np.int64))

        def prices(name: str) -> _FloatArray:
            values = cast(_FloatArray, rows[name].fill_null(np.nan).to_numpy().astype(np.float64))
            values = values.copy()
            values[count == 0] = np.nan
            return values

        open_us = cast(_IntArray, rows["open_time"].dt.timestamp("us").to_numpy().astype(np.int64))
        close_us: _IntArray = open_us + MICROS_PER_MINUTE
        if close_us.size > 1 and not bool((np.diff(close_us) > 0).all()):
            raise TimingContractError("1m rows are not in strictly increasing order of close")
        gap: _BoolArray
        if "gap" in rows.columns:
            gap = cast(_BoolArray, rows["gap"].to_numpy().astype(bool))
        else:
            gap = np.zeros(close_us.size, dtype=bool)
        return cls(
            symbol=symbol,
            open_us=open_us,
            close_us=close_us,
            open_=prices("open"),
            high=prices("high"),
            low=prices("low"),
            close=prices("close"),
            volume=cast(_FloatArray, rows["volume"].fill_null(0.0).to_numpy().astype(np.float64)),
            trade_count=count,
            gap=gap,
            knowable_us=cast(_IntArray, rows["knowable_time"].dt.timestamp("us").to_numpy().astype(np.int64)),
            delay_us=delay_us,
        )

    def __getstate__(self) -> dict[str, object]:
        """A worker process builds the bars it needs, which costs less than carrying them across."""
        return {**self.__dict__, "_frames": {}}

    def digest(self) -> str:
        """A hash of exactly what this run read, whichever files it came from."""
        hasher = hashlib.sha256()
        for array in (
            self.open_us,
            self.close_us,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.trade_count,
            self.gap,
            self.knowable_us,
        ):
            hasher.update(np.ascontiguousarray(array).tobytes())
        return hasher.hexdigest()

    def mark_price(self, at_us: int) -> float | None:
        """The last traded close at or before a moment. A valuation mark, never an input to a decision."""
        position = int(np.searchsorted(self._priced_close_us, at_us, side="right"))
        return float(self._priced_close[position - 1]) if position else None

    def mark_series(self, times_us: _IntArray) -> _FloatArray:
        """The same mark at many moments. NaN before the first trade."""
        marks: _FloatArray = np.full(times_us.size, np.nan)
        positions = np.searchsorted(self._priced_close_us, times_us, side="right")
        priced = positions > 0
        marks[priced] = self._priced_close[positions[priced] - 1]
        return marks

    def standing(self, first: int, end: int, as_of_us: int) -> Standing:
        """What is known at a moment about the rows in [first, end)."""
        if end <= first:
            return Standing(pending_tail=False, gap_known=True, has_price=False, last_priced_row=first - 1)
        counts = self.trade_count[first:end]
        traded = np.flatnonzero(counts > 0)
        if traded.size == 0:
            return Standing(pending_tail=False, gap_known=True, has_price=False, last_priced_row=first - 1)
        slice_gap = self.gap[first:end]
        last_traded = int(traded[-1])
        last_row = first + last_traded
        if not bool(slice_gap.any()) and last_traded == end - first - 1:
            return Standing(pending_tail=False, gap_known=False, has_price=True, last_priced_row=last_row)
        slice_known = self.knowable_us[first:end] <= as_of_us
        view_gap = np.where(slice_known, slice_gap, counts == 0)
        in_tail = np.arange(end - first) > last_traded
        return Standing(
            pending_tail=bool((view_gap & in_tail).any()),
            gap_known=bool((view_gap & ~in_tail).any()),
            has_price=True,
            last_priced_row=last_row,
        )

    def _spans(self, width_us: int) -> list[tuple[int, int, int]]:
        """(bucket close, first row, end row) for each bucket of a width, in time order."""
        if self.size == 0:
            return []
        buckets = ((self.close_us - 1) // width_us + 1) * width_us
        starts = np.concatenate(([0], np.flatnonzero(np.diff(buckets)) + 1))
        ends = np.concatenate((starts[1:], [buckets.size]))
        return [
            (int(buckets[start]), int(start), int(end))
            for start, end in zip(starts.tolist(), ends.tolist(), strict=True)
        ]

    def _on_grid(self, width_us: int) -> Iterator[tuple[int, int, int]]:
        """The same, with an empty span for each bucket on the grid that has no rows. C2: bars sit on a fixed
        grid, and a bar with no rows is a missing bar, so it must be seen as one.
        """
        previous: int | None = None
        for bucket_close, first, end in self._spans(width_us):
            if previous is not None:
                for missing in range(previous + width_us, bucket_close, width_us):
                    yield missing, first, first
            yield bucket_close, first, end
            previous = bucket_close

    def frame(self, minutes: int) -> list[Bar]:
        """Every bar of a timeframe that has closed in this tape, each with its as-of values. Cached."""
        cached = self._frames.get(minutes)
        if cached is None:
            cached = self._build_frame(minutes)
            self._frames[minutes] = cached
        return cached

    def _build_frame(self, minutes: int) -> list[Bar]:
        if minutes < 1 or 1440 % minutes != 0:
            raise TimingContractError(f"timeframe {minutes}m must divide a UTC day")
        width = minutes * MICROS_PER_MINUTE
        last_close = int(self.close_us[-1]) if self.size else 0
        days = _PeriodBook(self)
        atr = WilderAtr()
        ratio = VolatilityRatio(minutes)
        seasonal = SeasonalVolume()
        bars: list[Bar] = []
        previous_close: float | None = None
        previous_close_us: int | None = None
        gap_cursor = 0
        gap_rows = self._gap_rows
        # Flagged rows not yet accounted for: not known at their own close, or sitting in a tail.
        waiting: list[int] = []
        current_day: int | None = None
        current_day_open: float | None = None
        for bucket_close, first, end in self._on_grid(width):
            if bucket_close > last_close:
                break  # the last bucket has not closed in this tape
            as_of = bucket_close + self.delay_us
            standing = self.standing(first, end, as_of)
            # A flagged row in an earlier bar that has only now become known takes effect here.
            late_gap = any(int(self.knowable_us[row]) <= as_of for row in waiting)
            waiting = [row for row in waiting if int(self.knowable_us[row]) > as_of]
            while gap_cursor < gap_rows.size and int(gap_rows[gap_cursor]) < end:
                row = int(gap_rows[gap_cursor])
                gap_cursor += 1
                if int(self.knowable_us[row]) > as_of or row > standing.last_priced_row:
                    waiting.append(row)

            whole = end - first == minutes
            adjacent = previous_close_us == bucket_close - width
            if standing.has_price:
                highs = self.high[first:end]
                lows = self.low[first:end]
                opens = self.open[first:end]
                closes = self.close[first:end]
                o = float(opens[~np.isnan(opens)][0])
                h = float(np.nanmax(highs))
                l_ = float(np.nanmin(lows))
                c = float(closes[~np.isnan(closes)][-1])
            elif previous_close is not None:
                # C2: a close with no trades in the bar uses the last trade before it. It touches nothing.
                o = h = l_ = c = previous_close
            else:
                continue  # nothing has traded yet, so there is no bar to speak of
            gap = standing.gap_known or not whole or not standing.has_price
            volume = float(self.volume[first:end].sum())

            tr: float | None = None
            if gap or late_gap or not adjacent:
                atr.gap()
            if not gap and adjacent and previous_close is not None:
                tr = true_range(h, l_, previous_close)
                atr.update(tr)
            atr_value = atr.value
            vr = ratio.update(bucket_close, atr_value)
            srv = seasonal.update(bucket_close, volume, usable=not gap and standing.has_price)

            bar_open = bucket_close - width
            day_key = (bucket_close - 1) // MICROS_PER_DAY
            if day_key != current_day:
                current_day = day_key
                current_day_open = o if bar_open == floor_day(bar_open) and standing.has_price else None
            days.advance(bucket_close, as_of)
            bars.append(
                Bar(
                    index=len(bars),
                    minutes=minutes,
                    open_us=bar_open,
                    close_us=bucket_close,
                    o=o,
                    h=h,
                    l=l_,
                    c=c,
                    v=volume,
                    has_price=standing.has_price,
                    complete=not (gap or late_gap or standing.pending_tail),
                    pending_tail=standing.pending_tail,
                    gap=gap,
                    late_gap=late_gap,
                    tr=tr,
                    atr=atr_value,
                    atr_last=atr.last,
                    vr=vr,
                    srv=srv,
                    clv=clv(h, l_, c),
                    atrd=days.atrd_ending(floor_day(bar_open)),
                    day=days.day_ending(floor_day(bar_open)),
                    week=days.week_ending(floor_week(bar_open)),
                    day_at_close=days.day_ending(floor_day(bucket_close)),
                    week_at_close=days.week_ending(floor_week(bucket_close)),
                    day_open=current_day_open,
                )
            )
            previous_close = c
            if end > first:
                # A true range needs the close before it, and a bucket with no rows has none.
                previous_close_us = bucket_close
        return bars


class _PeriodBook:
    """Completed days and weeks, finished in time order as they become knowable.

    A day whose last minutes are still unproven waits, and later days wait behind it. A day with a known gap,
    or with minutes missing, is not computed, and ATRD starts again after it. Nothing is carried across a
    hole: the set in force for a bar is the day ending exactly at the start of its own UTC day, or nothing.
    """

    def __init__(self, tape: MinuteTape) -> None:
        self._tape = tape
        self._spans = tape._spans(MICROS_PER_DAY)
        self._next = 0
        self._atr = WilderAtr()
        self._previous_close: float | None = None
        self._previous_end: int | None = None
        self._days: dict[int, PeriodBar] = {}
        self._atrd: dict[int, float] = {}
        self._weeks: dict[int, PeriodBar] = {}

    def advance(self, close_us: int, as_of_us: int) -> None:
        tape = self._tape
        while self._next < len(self._spans):
            end_us, first, end = self._spans[self._next]
            if end_us > close_us:
                return
            standing = tape.standing(first, end, as_of_us)
            if standing.pending_tail:
                return  # retried at the next close
            self._next += 1
            whole = end - first == 1440
            if not whole or standing.gap_known or not standing.has_price:
                self._atr.gap()
                self._previous_close = None
                self._previous_end = None
                continue
            opens = tape.open[first:end]
            closes = tape.close[first:end]
            day = PeriodBar(
                start_us=end_us - MICROS_PER_DAY,
                end_us=end_us,
                open=float(opens[~np.isnan(opens)][0]),
                high=float(np.nanmax(tape.high[first:end])),
                low=float(np.nanmin(tape.low[first:end])),
                close=float(closes[~np.isnan(closes)][-1]),
            )
            self._days[end_us] = day
            if self._previous_end != end_us - MICROS_PER_DAY:
                self._atr.gap()
            elif self._previous_close is not None:
                self._atr.update(true_range(day.high, day.low, self._previous_close))
                if self._atr.value is not None:
                    self._atrd[end_us] = self._atr.value
            self._previous_close = day.close
            self._previous_end = end_us
            self._finish_week(end_us)

    def _finish_week(self, day_end: int) -> None:
        if day_end != floor_week(day_end):
            return
        ends = [day_end - back * MICROS_PER_DAY for back in range(6, -1, -1)]
        days = [self._days.get(end) for end in ends]
        if any(day is None for day in days):
            return
        whole = [day for day in days if day is not None]
        self._weeks[day_end] = PeriodBar(
            start_us=day_end - MICROS_PER_WEEK,
            end_us=day_end,
            open=whole[0].open,
            high=max(day.high for day in whole),
            low=min(day.low for day in whole),
            close=whole[-1].close,
        )

    def day_ending(self, end_us: int) -> PeriodBar | None:
        return self._days.get(end_us)

    def week_ending(self, end_us: int) -> PeriodBar | None:
        return self._weeks.get(end_us)

    def atrd_ending(self, end_us: int) -> float | None:
        return self._atrd.get(end_us)
