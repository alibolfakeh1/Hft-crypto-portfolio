"""Condition 2 of ruling 7: does a candle hold a print from after its close? Section 15 of the leak recheck.

This is its own code, apart from `reconcile._walk`, because they ask different questions. The walk asks
whether a day's difference can be explained by rows near a boundary. This asks whether candles have counted
more than had been stamped before each close. It works in integers, with no tolerance, no window and nothing
fitted, and it has no configuration key, so no value of anything can make it pass.

For one day and one symbol, and each of volume, taker-buy volume and fill count:

1. `S(b)` sums the day's rows stamped in `[midnight, b)`, so a row stamped exactly at `b` is after it. `K(b)`
sums the candles closing at or before `b`. `d(b) = S(b) - K(b)`. 2. `b` is a zero point if the last row
stamped before it on the day is one fill. Nothing is then still printing across `b`, so `d(b)` is exactly
minus the carry across midnight. 3. Every zero point reads the same value, `d0`. Fewer than two makes the day
INCONCLUSIVE, and different values fail it. 4. `d(b) >= d0` at all 1,440 boundaries. Below it, candles have
counted more than had been stamped before the close. 5. `-d0` lies between 0 and the previous file's last row:
its amount in this column if it has more than one fill, and 0 if it has one, which is all the previous day can
supply. 6. A traded candle's close equals the price of the last row stamped before its close. 7. `d(b) > d0`
occurs somewhere, or the day is INCONCLUSIVE. Candles built by row stamp read `d0` everywhere, and pass steps
3 to 6 while holding later fills, so a day that never saw a split has shown nothing.

The result is one of three words and a fixed code, and never a quantity. It assumes a row is stamped at its
first fill and that rows do not overlap. If not, clean days fail, so the cost is `IDEAL` and never a false
pass.

What it cannot see: an excess in the first candle that is never given back, and no larger than the previous
file's last row, cannot be told from a carry. A candle counting some rows by stamp and others by fill time
passes, since step 7 needs one split a day.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.timeutil import MICROS_PER_DAY, MICROS_PER_MINUTE, day_start_us

PASS = "PASS"  # noqa: S105
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"

# Fixed codes. No quantity ever goes in one.
CODE_OK = "ok"
CODE_NO_PREVIOUS_FILE = "no_previous_file"
CODE_NO_ROWS = "no_rows"
CODE_NO_CANDLES = "no_candles"
CODE_NOT_ON_SCALE = "not_on_scale"
CODE_FEW_ZERO_POINTS = "step3_fewer_than_two_zero_points"
CODE_PRICE = "step6_price"
COLUMN_VOLUME = "volume"
COLUMN_TAKER_BUY = "taker_buy"
COLUMN_FILLS = "fills"
COLUMNS = (COLUMN_VOLUME, COLUMN_TAKER_BUY, COLUMN_FILLS)


def _column_codes(step: str) -> tuple[str, ...]:
    return tuple(f"{step}_{column}" for column in COLUMNS)


CODES = frozenset(
    {
        CODE_OK,
        CODE_NO_PREVIOUS_FILE,
        CODE_NO_ROWS,
        CODE_NO_CANDLES,
        CODE_NOT_ON_SCALE,
        CODE_FEW_ZERO_POINTS,
        CODE_PRICE,
        *_column_codes("step3_zero_points_differ"),
        *_column_codes("step4_excess"),
        *_column_codes("step5_carry"),
        *_column_codes("step7_no_split_seen"),
    }
)

# Whole units of this fraction of a coin or a price. A value that is not a whole unit is reported, and never
# rounded in.
_SCALE = 100_000_000
_BOUNDARIES = 1440
# Condition 2 is shown for a symbol only on these (section 15).
REQUIRED_PASS_DAYS = 43

_Ints = npt.NDArray[np.int64]


class _NotOnScale(Exception):
    """A value that is not a whole number of units, so no sum of it could be exact."""


def _units(series: pl.Series) -> _Ints:
    """Exact integers from a float column, or a refusal. The check on a value is what its float can represent,
    and it says only whether the value is a whole unit. It is no allowance on any reading."""
    values = series.cast(pl.Float64).to_numpy()
    if not np.isfinite(values).all():
        raise _NotOnScale
    scaled = values * _SCALE
    whole = np.rint(scaled)
    representable = np.maximum(np.abs(scaled) * 4 * np.finfo(np.float64).eps, 1e-6)
    if (np.abs(scaled - whole) > representable).any():
        raise _NotOnScale
    result: _Ints = whole.astype(np.int64)
    return result


def _integers(series: pl.Series) -> _Ints:
    result: _Ints = series.cast(pl.Int64).to_numpy().astype(np.int64)
    return result


@dataclass(frozen=True)
class DayVerdict:
    result: str
    code: str


@dataclass(frozen=True)
class _Rows:
    stamps: _Ints
    price: _Ints
    columns: dict[str, _Ints]
    fills: _Ints


def _rows_of(frame: pl.DataFrame) -> _Rows:
    ordered = frame.sort(["ts", "trade_id"])
    quantity = _units(ordered["qty"])
    fills = _integers(ordered["n_fills"])
    taker = ordered["is_taker_buy"].to_numpy().astype(bool)
    return _Rows(
        stamps=_integers(ordered["ts"].dt.timestamp("us")),
        price=_units(ordered["price"]),
        columns={
            COLUMN_VOLUME: quantity,
            COLUMN_TAKER_BUY: np.where(taker, quantity, 0),
            COLUMN_FILLS: fills,
        },
        fills=fills,
    )


def _with_zero_start(values: _Ints) -> _Ints:
    result: _Ints = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(values)))
    return result


def check_candle_day(
    rows: pl.DataFrame, candles: pl.DataFrame, previous_rows: pl.DataFrame | None, day: dt.date
) -> DayVerdict:
    """One symbol on one day. `rows` and `previous_rows` are that day's and the day before's aggregate
    rows."""
    if previous_rows is None or previous_rows.is_empty():
        return DayVerdict(INCONCLUSIVE, CODE_NO_PREVIOUS_FILE)
    midnight = day_start_us(day)
    following = midnight + MICROS_PER_DAY
    stamp = rows["ts"].dt.timestamp("us")
    todays = rows.filter((stamp >= midnight) & (stamp < following))
    opening = candles["open_time"].dt.timestamp("us")
    kept = candles.filter((opening >= midnight) & (opening < following)).sort("open_time")
    if todays.is_empty():
        return DayVerdict(INCONCLUSIVE, CODE_NO_ROWS)
    if kept.is_empty():
        return DayVerdict(INCONCLUSIVE, CODE_NO_CANDLES)
    try:
        today = _rows_of(todays)
        before = _rows_of(previous_rows)
        candle_columns = {
            COLUMN_VOLUME: _units(kept["volume"]),
            COLUMN_TAKER_BUY: _units(kept["taker_buy_volume"]),
            COLUMN_FILLS: _integers(kept["trade_count"]),
        }
        candle_close = _units(kept["close"])
    except _NotOnScale:
        return DayVerdict(INCONCLUSIVE, CODE_NOT_ON_SCALE)
    closes = _integers(kept["open_time"].dt.timestamp("us")) + MICROS_PER_MINUTE
    traded = _integers(kept["trade_count"]) > 0

    boundaries: _Ints = midnight + MICROS_PER_MINUTE * np.arange(1, _BOUNDARIES + 1, dtype=np.int64)
    # A row stamped exactly at a boundary is after it.
    stamped_before = np.searchsorted(today.stamps, boundaries, side="left")
    closed_by = np.searchsorted(closes, boundaries, side="right")
    # Step 2. Rows are in stamp order, so the last one before a boundary is the one just below this position.
    has_row = stamped_before > 0
    one_fill = np.zeros(_BOUNDARIES, dtype=bool)
    one_fill[has_row] = today.fills[stamped_before[has_row] - 1] == 1
    if int(one_fill.sum()) < 2:
        return DayVerdict(INCONCLUSIVE, CODE_FEW_ZERO_POINTS)

    last_before = before.stamps.size - 1
    settled: dict[str, tuple[_Ints, int]] = {}
    for column in COLUMNS:
        readings: _Ints = (
            _with_zero_start(today.columns[column])[stamped_before]
            - _with_zero_start(candle_columns[column])[closed_by]
        )
        at_zero = readings[one_fill]
        d0 = int(at_zero[0])
        # Step 3.
        if not (at_zero == d0).all():
            return DayVerdict(FAIL, f"step3_zero_points_differ_{column}")
        # Step 4.
        if (readings < d0).any():
            return DayVerdict(FAIL, f"step4_excess_{column}")
        # Step 5. That row is all the previous day supplies, and one fill cannot still be printing.
        bound = int(before.columns[column][last_before]) if before.fills[last_before] > 1 else 0
        if not 0 <= -d0 <= bound:
            return DayVerdict(FAIL, f"step5_carry_{column}")
        settled[column] = (readings, d0)

    # Step 6.
    positions = np.searchsorted(today.stamps, closes[traded], side="left")
    reference = np.where(positions > 0, today.price[np.maximum(positions - 1, 0)], before.price[last_before])
    if (candle_close[traded] != reference).any():
        return DayVerdict(FAIL, CODE_PRICE)

    # Step 7.
    for column, (readings, d0) in settled.items():
        if not (readings > d0).any():
            return DayVerdict(INCONCLUSIVE, f"step7_no_split_seen_{column}")
    return DayVerdict(PASS, CODE_OK)


def _quarter(day: dt.date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3


def declared_sample_days(first_year: int = 2020, last_year: int = 2023) -> tuple[dt.date, ...]:
    """The 15th of every month of the first span (coverage record, section 6). From the calendar, with no
    replacements."""
    return tuple(
        dt.date(year, month, 15) for year in range(first_year, last_year + 1) for month in range(1, 13)
    )


def condition_2_shown(
    verdicts: Iterable[tuple[dt.date, str]], declared: Sequence[dt.date] | None = None
) -> bool:
    """For one symbol: no day fails, at least 43 of the 48 days pass, and every quarter has a passing day."""
    days = list(declared_sample_days() if declared is None else declared)
    results = list(verdicts)
    if any(result == FAIL for _, result in results):
        return False
    passed = {day for day, result in results if result == PASS}
    if len(passed & set(days)) < REQUIRED_PASS_DAYS:
        return False
    return {_quarter(day) for day in days} <= {_quarter(day) for day in passed}
