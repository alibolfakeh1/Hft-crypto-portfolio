"""Condition 2 of ruling 7, in the form of section 15 of the leak recheck, on generated fills only.

The generator makes fills, each with its own stamp, groups them into rows as an archive does, and builds
candles from them as the rule under test says a venue does. Each planted case then changes how candles count
those fills. All prices are invented.
"""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Callable
from dataclasses import dataclass

import polars as pl
import pytest

from hft_crypto.bars.candle_check import (
    CODE_FEW_ZERO_POINTS,
    CODE_NO_CANDLES,
    CODE_NO_PREVIOUS_FILE,
    CODE_NO_ROWS,
    CODE_NOT_ON_SCALE,
    CODE_OK,
    CODE_PRICE,
    CODES,
    FAIL,
    INCONCLUSIVE,
    PASS,
    check_candle_day,
    condition_2_shown,
    declared_sample_days,
)
from hft_crypto.bars.core import UTC_TIME
from hft_crypto.timeutil import MICROS_PER_DAY, MICROS_PER_MINUTE, day_start_us

DAY = dt.date(2021, 3, 15)
MIDNIGHT = day_start_us(DAY)
QUIET_SEEDS = tuple(range(1, 9))
BUSY_SEEDS = (101, 102, 103)
ALL_SEEDS = (*QUIET_SEEDS, *BUSY_SEEDS)
UNIT = 1_000  # 0.001 of a coin, in units of 0.000001, so every quantity is a whole number of them


@dataclass(frozen=True)
class Fill:
    stamp: int
    price_ticks: int
    quantity: int
    taker_buy: bool
    row: int


@dataclass(frozen=True)
class Market:
    fills: tuple[Fill, ...]

    def rows(self) -> list[tuple[int, int, int, bool, int, int]]:
        """(stamp, price, quantity, taker buy, row id, fills). A row is stamped at its first fill."""
        grouped: dict[int, list[Fill]] = {}
        for fill in self.fills:
            grouped.setdefault(fill.row, []).append(fill)
        return [
            (
                items[0].stamp,
                items[0].price_ticks,
                sum(item.quantity for item in items),
                items[0].taker_buy,
                row,
                len(items),
            )
            for row, items in sorted(grouped.items())
        ]


def generate(seed: int, *, busy: bool = False) -> Market:
    """Rows one after another, each up to 400 ms long, from the last minutes of the day before to just past
    midnight."""
    rng = random.Random(seed)
    cursor = MIDNIGHT - 5 * MICROS_PER_MINUTE
    end = MIDNIGHT + MICROS_PER_DAY + MICROS_PER_MINUTE
    gap = 2_000_000 if busy else 20_000_000
    fills: list[Fill] = []
    row = 0
    price = 100_000
    while cursor < end:
        cursor += rng.randint(gap // 2, gap * 3 // 2)
        count = rng.choice((1, 1, 1, 2, 3, 5, 8))
        price += rng.randint(-5, 5)
        side = rng.random() < 0.5
        stamp = cursor
        for index in range(count):
            if index:
                stamp += rng.randint(1_000, 400_000 // max(count - 1, 1))
            fills.append(Fill(stamp, price, UNIT * rng.randint(1, 50), side, row))
        cursor = stamp + 1
        row += 1
    return Market(tuple(fills))


def rows_frame(rows: list[tuple[int, int, int, bool, int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": pl.Series([row[0] for row in rows], dtype=pl.Int64).cast(UTC_TIME),
            "price": pl.Series([row[1] / 100.0 for row in rows], dtype=pl.Float64),
            "qty": pl.Series([row[2] / 1_000_000.0 for row in rows], dtype=pl.Float64),
            "is_taker_buy": pl.Series([row[3] for row in rows], dtype=pl.Boolean),
            "trade_id": pl.Series([row[4] for row in rows], dtype=pl.Int64),
            "n_fills": pl.Series([row[5] for row in rows], dtype=pl.Int32),
        }
    )


def day_frames(market: Market) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = market.rows()
    following = MIDNIGHT + MICROS_PER_DAY
    today = [row for row in rows if MIDNIGHT <= row[0] < following]
    previous = [row for row in rows if row[0] < MIDNIGHT]
    return rows_frame(today), rows_frame(previous)


Assign = Callable[[Fill], int]


def by_own_stamp(fill: Fill) -> int:
    return fill.stamp // MICROS_PER_MINUTE * MICROS_PER_MINUTE


def candles_frame(
    fills: tuple[Fill, ...], assign: Assign = by_own_stamp, *, extras: dict[int, list[Fill]] | None = None
) -> pl.DataFrame:
    """One candle a minute of the day, a row with zero trades when nothing printed, carrying the last price
    forward."""
    minutes: dict[int, list[Fill]] = {}
    for fill in fills:
        minutes.setdefault(assign(fill), []).append(fill)
    for opening, added in (extras or {}).items():
        minutes.setdefault(opening, []).extend(added)
    columns: dict[str, list[object]] = {
        name: [] for name in ("open_time", "close", "volume", "taker_buy_volume", "trade_count")
    }
    last = 100.0
    for index in range(1440):
        opening = MIDNIGHT + index * MICROS_PER_MINUTE
        items = sorted(minutes.get(opening, []), key=lambda item: item.stamp)
        if items:
            last = items[-1].price_ticks / 100.0
        columns["open_time"].append(opening)
        columns["close"].append(last)
        columns["volume"].append(sum(item.quantity for item in items) / 1_000_000.0)
        columns["taker_buy_volume"].append(
            sum(item.quantity for item in items if item.taker_buy) / 1_000_000.0
        )
        columns["trade_count"].append(len(items))
    frame = pl.DataFrame(columns, strict=False)
    return frame.with_columns(
        pl.col("open_time").cast(pl.Int64).cast(UTC_TIME),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Float64),
        pl.col("taker_buy_volume").cast(pl.Float64),
        pl.col("trade_count").cast(pl.Int64),
    )


def verdict(market: Market, candles: pl.DataFrame | None = None) -> tuple[str, str]:
    today, previous = day_frames(market)
    result = check_candle_day(
        today, candles_frame(market.fills) if candles is None else candles, previous, DAY
    )
    assert result.code in CODES
    return result.result, result.code


def market(seed: int) -> Market:
    return generate(seed, busy=seed in BUSY_SEEDS)


# ---- the table in section 15
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", QUIET_SEEDS)
def test_nothing_planted_on_quiet_days_passes_with_rows_running_up_to_400_ms(seed: int) -> None:
    """The walk passes 2 of 8 here, because it fails on a row longer than its window, which is no after-close
    print."""
    assert verdict(market(seed)) == (PASS, CODE_OK)


@pytest.mark.parametrize("seed", BUSY_SEEDS)
def test_nothing_planted_on_busy_days_passes(seed: int) -> None:
    assert verdict(market(seed)) == (PASS, CODE_OK)


def test_the_generated_rows_do_run_past_a_boundary_and_up_to_400_ms() -> None:
    """Otherwise the two tests above would say nothing."""
    crossings = 0
    longest = 0
    for seed in ALL_SEEDS:
        grouped: dict[int, list[int]] = {}
        for fill in market(seed).fills:
            grouped.setdefault(fill.row, []).append(fill.stamp)
        for stamps in grouped.values():
            longest = max(longest, stamps[-1] - stamps[0])
            crossings += stamps[0] // MICROS_PER_MINUTE != stamps[-1] // MICROS_PER_MINUTE
    assert crossings > 100
    assert longest > 300_000


def _moved_into(target_minute: int, moved: int) -> Callable[[Market], pl.DataFrame]:
    """The next fills after a candle's close, counted in that candle.

    Each comes from a row that had not begun by the close. The later fills of a row already stamped by then
    are the limit section 15 states, and the test after this one holds that.
    """

    def build(item: Market) -> pl.DataFrame:
        close = MIDNIGHT + (target_minute + 1) * MICROS_PER_MINUTE
        began_by_close = {fill.row for fill in item.fills if fill.stamp < close}
        later = sorted(
            (fill for fill in item.fills if fill.stamp >= close and fill.row not in began_by_close),
            key=lambda fill: fill.stamp,
        )[:moved]
        chosen = {id(fill) for fill in later}
        opening = MIDNIGHT + target_minute * MICROS_PER_MINUTE

        def assign(fill: Fill) -> int:
            return opening if id(fill) in chosen else by_own_stamp(fill)

        return candles_frame(item.fills, assign)

    return build


@pytest.mark.parametrize("seed", ALL_SEEDS)
@pytest.mark.parametrize(
    "plant",
    [
        pytest.param(_moved_into(0, 1), id="next fill into the first candle"),
        pytest.param(_moved_into(0, 20), id="next 20 fills into the first candle"),
        pytest.param(_moved_into(720, 1), id="next fill into a midday candle"),
        pytest.param(_moved_into(720, 20), id="next 20 fills into a midday candle"),
    ],
)
def test_later_fills_moved_into_an_earlier_candle_fail(
    seed: int, plant: Callable[[Market], pl.DataFrame]
) -> None:
    item = market(seed)
    result, code = verdict(item, plant(item))
    assert result == FAIL
    assert code.startswith(("step3", "step4", "step5"))


def test_a_later_fill_of_a_row_already_stamped_cannot_be_seen_and_that_is_the_stated_limit() -> None:
    """Section 15: "A candle that counts some rows by stamp and others by fill time passes." One such row,
    here."""
    later_buy_row = [
        Fill(MIDNIGHT + 10 * MICROS_PER_MINUTE - 100_000, 100_600, UNIT, True, 7),
        Fill(MIDNIGHT + 10 * MICROS_PER_MINUTE + 100_000, 100_600, UNIT, True, 7),
    ]
    item = Market((*hand_day(), *later_buy_row))
    spill = next(
        fill for fill in item.fills if fill.row == 3 and fill.stamp >= MIDNIGHT + 3 * MICROS_PER_MINUTE
    )

    def assign(fill: Fill) -> int:
        return MIDNIGHT + 2 * MICROS_PER_MINUTE if fill is spill else by_own_stamp(fill)

    # Rows 5 and 7 still split, so step 7 is met, and row 3's later fill sits in the earlier candle unseen.
    assert verdict(item, candles_frame(item.fills, assign)) == (PASS, CODE_OK)


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_every_candle_reaching_50_ms_past_its_close_fails(seed: int) -> None:
    item = market(seed)

    def assign(fill: Fill) -> int:
        return (fill.stamp - 50_000) // MICROS_PER_MINUTE * MICROS_PER_MINUTE

    assert verdict(item, candles_frame(item.fills, assign))[0] == FAIL


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_one_extra_fill_in_the_first_candle_never_given_back(seed: int) -> None:
    """Fails unless the previous file's last row could have held it, which is the limit section 15 states.

    The walk passes 5 of 11 of these. The auditor's run fails 8 of 11 on its generator, and this one fails
    what the form says it must: a taker buy of one unit can read as a carry only from a taker-buy row of more
    than one fill.
    """
    item = market(seed)
    extra = Fill(MIDNIGHT + 1, 100_000, UNIT, True, -1)
    last = max((row for row in item.rows() if row[0] < MIDNIGHT), key=lambda row: row[0])
    could_hold = last[5] > 1 and last[3]
    result, code = verdict(item, candles_frame(item.fills, extras={MIDNIGHT: [extra]}))
    if could_hold:
        assert (result, code) == (PASS, CODE_OK)
    else:
        assert result == FAIL
        assert code.startswith("step5_carry")


def test_an_extra_fill_too_large_for_the_previous_row_fails_on_step_5() -> None:
    item = market(1)
    too_large = Fill(MIDNIGHT + 1, 100_000, 10_000 * UNIT, True, -1)
    result, code = verdict(item, candles_frame(item.fills, extras={MIDNIGHT: [too_large]}))
    assert result == FAIL
    assert code.startswith("step5_carry")


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_candles_built_by_row_stamp_are_inconclusive_and_not_passed(seed: int) -> None:
    """The case condition 2 exists to exclude. They pass steps 3 to 6 while holding later fills. The walk
    passes them."""
    item = market(seed)
    first_of_row: dict[int, int] = {}
    for fill in item.fills:
        first_of_row.setdefault(fill.row, fill.stamp)

    def assign(fill: Fill) -> int:
        return first_of_row[fill.row] // MICROS_PER_MINUTE * MICROS_PER_MINUTE

    result, code = verdict(item, candles_frame(item.fills, assign))
    assert result == INCONCLUSIVE
    assert code.startswith("step7_no_split_seen")


# ---- its assumptions fail safe
# -------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", ALL_SEEDS)
def test_rows_stamped_at_their_last_fill_fail_on_clean_candles(seed: int) -> None:
    """The cost of a wrong assumption is IDEAL, and never a false pass."""
    item = market(seed)
    grouped: dict[int, list[Fill]] = {}
    for fill in item.fills:
        grouped.setdefault(fill.row, []).append(fill)
    rows = [
        (
            items[-1].stamp,
            items[0].price_ticks,
            sum(fill.quantity for fill in items),
            items[0].taker_buy,
            row,
            len(items),
        )
        for row, items in sorted(grouped.items())
    ]
    following = MIDNIGHT + MICROS_PER_DAY
    today = rows_frame([row for row in rows if MIDNIGHT <= row[0] < following])
    previous = rows_frame([row for row in rows if row[0] < MIDNIGHT])
    assert check_candle_day(today, candles_frame(item.fills), previous, DAY).result == FAIL


def test_overlapping_rows_fail_on_step_3() -> None:
    """Section 15 says this is reasoning and not a probe, so here is the probe, on a hand-made day."""
    fills = [
        Fill(MIDNIGHT - 10_000_000, 100_000, UNIT, True, 0),
        Fill(MIDNIGHT + 10_000_000, 100_000, UNIT, True, 1),
        # A long row across 00:02, with a one-fill row inside it just before that boundary.
        Fill(MIDNIGHT + 2 * MICROS_PER_MINUTE - 200_000, 100_000, UNIT, False, 2),
        Fill(MIDNIGHT + 2 * MICROS_PER_MINUTE - 100_000, 100_000, UNIT, True, 3),
        Fill(MIDNIGHT + 2 * MICROS_PER_MINUTE + 100_000, 100_000, UNIT, False, 2),
        Fill(MIDNIGHT + 5 * MICROS_PER_MINUTE, 100_000, UNIT, True, 4),
    ]
    result, code = verdict(Market(tuple(fills)))
    assert result == FAIL
    assert code.startswith("step3_zero_points_differ")


# ---- each step, by hand
# --------------------------------------------------------------------------------------------


def hand_day() -> list[Fill]:
    """One-fill rows, and one row of two fills across 00:03, with both sides, so every step has something to
    read."""
    return [
        Fill(MIDNIGHT - 10_000_000, 100_000, 2 * UNIT, True, 0),
        Fill(MIDNIGHT + 10_000_000, 100_000, UNIT, True, 1),
        Fill(MIDNIGHT + 70_000_000, 100_100, 3 * UNIT, False, 2),
        # Across 00:03 on both counts: a buy row and a sell row, one after the other.
        Fill(MIDNIGHT + 3 * MICROS_PER_MINUTE - 100_000, 100_200, UNIT, True, 3),
        Fill(MIDNIGHT + 3 * MICROS_PER_MINUTE + 100_000, 100_200, 4 * UNIT, True, 3),
        Fill(MIDNIGHT + 5 * MICROS_PER_MINUTE, 100_300, UNIT, True, 4),
        Fill(MIDNIGHT + 6 * MICROS_PER_MINUTE - 100_000, 100_400, UNIT, False, 5),
        Fill(MIDNIGHT + 6 * MICROS_PER_MINUTE + 100_000, 100_400, 2 * UNIT, False, 5),
        Fill(MIDNIGHT + 8 * MICROS_PER_MINUTE, 100_500, UNIT, True, 6),
    ]


def test_a_hand_made_clean_day_passes() -> None:
    assert verdict(Market(tuple(hand_day()))) == (PASS, CODE_OK)


def test_a_row_stamped_exactly_on_a_boundary_is_after_it() -> None:
    """S(b) sums `[midnight, b)`. A row at exactly 00:05 is in the candle that opens then, which closes at
    00:06."""
    item = Market(tuple(hand_day()))
    assert any(fill.stamp == MIDNIGHT + 5 * MICROS_PER_MINUTE for fill in item.fills)
    assert verdict(item) == (PASS, CODE_OK)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("volume", "step4_excess_volume"),
        ("taker_buy_volume", "step4_excess_taker_buy"),
        ("trade_count", "step4_excess_fills"),
    ],
)
def test_there_is_no_tolerance_on_any_column(change: str, code: str) -> None:
    """The smallest amount over, in one candle at 00:04, given back at once in the next. One unit fails the
    day."""
    item = Market(tuple(hand_day()))
    good = candles_frame(item.fills)
    step = 1 if change == "trade_count" else 0.00000001
    changed = good.with_row_index().with_columns(
        pl.when(pl.col("index") == 4)
        .then(pl.col(change) + step)
        .when(pl.col("index") == 5)
        .then(pl.col(change) - step)
        .otherwise(pl.col(change))
        .alias(change)
    )
    assert verdict(item, changed.drop("index")) == (FAIL, code)


def test_a_deficit_that_lasts_makes_the_zero_points_differ() -> None:
    """Fills never counted. Every later zero point reads higher than the earlier ones."""
    item = Market(tuple(hand_day()))
    dropped = (
        candles_frame(item.fills)
        .with_row_index()
        .with_columns(pl.when(pl.col("index") == 5).then(0.0).otherwise(pl.col("volume")).alias("volume"))
    )
    assert verdict(item, dropped.drop("index")) == (FAIL, "step3_zero_points_differ_volume")


def test_a_row_too_small_to_have_carried_it_fails_step_5() -> None:
    """The previous file's last row is one fill, so nothing can have crossed midnight, and -d0 must be 0."""
    item = Market(tuple(hand_day()))
    extra = Fill(MIDNIGHT + 1, 100_000, UNIT, True, -1)
    planted = candles_frame(item.fills, extras={MIDNIGHT: [extra]})
    assert verdict(item, planted) == (FAIL, "step5_carry_volume")


def test_a_carry_the_previous_row_can_hold_passes_and_is_computed_and_not_absorbed() -> None:
    """Row 0 has two fills, the second after midnight, so d0 is minus that fill in all three columns."""
    fills = hand_day()
    fills[0] = Fill(MIDNIGHT - 100_000, 100_000, 2 * UNIT, True, 0)
    fills.insert(1, Fill(MIDNIGHT + 100_000, 100_000, 3 * UNIT, True, 0))
    assert verdict(Market(tuple(fills))) == (PASS, CODE_OK)


def test_trades_above_candles_at_every_zero_point_fail_step_5() -> None:
    """A positive d0 has no reading as a carry at all, so it cannot be absorbed into one."""
    item = Market(tuple(hand_day()))
    reduced = (
        candles_frame(item.fills)
        .with_row_index()
        .with_columns(
            pl.when(pl.col("index") == 0).then(0.0).otherwise(pl.col("volume")).alias("volume"),
        )
    )
    assert verdict(item, reduced.drop("index")) == (FAIL, "step5_carry_volume")


def test_a_close_one_tick_from_the_last_row_fails_step_6() -> None:
    item = Market(tuple(hand_day()))
    good = candles_frame(item.fills)
    bad = good.with_row_index().with_columns(
        pl.when(pl.col("index") == 1).then(pl.col("close") + 0.01).otherwise(pl.col("close")).alias("close")
    )
    assert verdict(item, bad.drop("index")) == (FAIL, CODE_PRICE)


def test_a_candle_with_no_trades_is_not_held_to_a_price() -> None:
    """What the venue writes on an empty minute is UNVERIFIED, and it is never read as a print."""
    item = Market(tuple(hand_day()))
    good = candles_frame(item.fills)
    carried = good.with_row_index().with_columns(
        pl.when(pl.col("trade_count") == 0).then(0.0).otherwise(pl.col("close")).alias("close")
    )
    assert verdict(item, carried.drop("index")) == (PASS, CODE_OK)


def test_fewer_than_two_zero_points_is_inconclusive() -> None:
    fills = [
        Fill(MIDNIGHT - 10_000_000, 100_000, UNIT, True, 0),
        Fill(MIDNIGHT + 10_000_000, 100_000, UNIT, True, 1),
        Fill(MIDNIGHT + 2 * MICROS_PER_MINUTE - 100, 100_000, UNIT, True, 2),
        Fill(MIDNIGHT + 2 * MICROS_PER_MINUTE + 100, 100_000, UNIT, True, 2),
    ]
    assert len(fills) == 4
    # The day's only row has two fills, so the last row before every boundary is more than one fill.
    two_fill_first = [
        fills[0],
        Fill(MIDNIGHT + 59_999_000, 100_000, UNIT, True, 1),
        Fill(MIDNIGHT + 60_001_000, 100_000, UNIT, True, 1),
    ]
    assert verdict(Market(tuple(two_fill_first))) == (INCONCLUSIVE, CODE_FEW_ZERO_POINTS)


def test_exactly_one_zero_point_is_still_too_few() -> None:
    """One row of one fill before 00:01, and then a row of two fills, last before every later boundary."""
    fills = [
        Fill(MIDNIGHT - 10_000_000, 100_000, UNIT, True, 0),
        Fill(MIDNIGHT + 30_000_000, 100_000, UNIT, True, 1),
        Fill(MIDNIGHT + 90_000_000, 100_000, UNIT, True, 2),
        Fill(MIDNIGHT + 90_000_100, 100_000, UNIT, True, 2),
    ]
    assert verdict(Market(tuple(fills))) == (INCONCLUSIVE, CODE_FEW_ZERO_POINTS)


def test_a_day_that_never_sees_a_split_in_one_column_is_inconclusive() -> None:
    """Rows of one fill only: every reading is d0, so the day cannot show anything."""
    fills = [
        Fill(MIDNIGHT + minute * MICROS_PER_MINUTE + 1000, 100_000, UNIT, bool(minute % 2), minute + 1)
        for minute in range(30)
    ]
    fills.insert(0, Fill(MIDNIGHT - 1000, 100_000, UNIT, True, 0))
    assert verdict(Market(tuple(fills))) == (INCONCLUSIVE, "step7_no_split_seen_volume")


def test_a_taker_buy_column_that_never_splits_stays_inconclusive() -> None:
    """Each column must have been able to see a split. Here only the sell side ever crosses a boundary."""
    fills = [
        Fill(MIDNIGHT - 1000, 100_000, UNIT, True, 0),
        Fill(MIDNIGHT + 1000, 100_000, UNIT, True, 1),
        Fill(MIDNIGHT + 60_000_000 - 100, 100_000, UNIT, False, 2),
        Fill(MIDNIGHT + 60_000_000 + 100, 100_000, UNIT, False, 2),
        Fill(MIDNIGHT + 90_000_000, 100_000, UNIT, True, 3),
        Fill(MIDNIGHT + 150_000_000, 100_000, UNIT, True, 4),
    ]
    assert verdict(Market(tuple(fills))) == (INCONCLUSIVE, "step7_no_split_seen_taker_buy")


@pytest.mark.parametrize(
    ("kind", "code"),
    [("previous", CODE_NO_PREVIOUS_FILE), ("rows", CODE_NO_ROWS), ("candles", CODE_NO_CANDLES)],
)
def test_a_day_with_something_missing_says_so(kind: str, code: str) -> None:
    item = Market(tuple(hand_day()))
    today, previous = day_frames(item)
    candles = candles_frame(item.fills)
    if kind == "previous":
        result = check_candle_day(today, candles, None, DAY)
    elif kind == "rows":
        result = check_candle_day(today.clear(), candles, previous, DAY)
    else:
        result = check_candle_day(today, candles.clear(), previous, DAY)
    assert (result.result, result.code) == (INCONCLUSIVE, code)


def test_a_value_that_is_not_a_whole_unit_is_reported_and_not_rounded_in() -> None:
    item = Market(tuple(hand_day()))
    today, previous = day_frames(item)
    off = today.with_row_index().with_columns(
        pl.when(pl.col("index") == 0).then(pl.col("qty") + 0.000000001).otherwise(pl.col("qty")).alias("qty")
    )
    result = check_candle_day(off.drop("index"), candles_frame(item.fills), previous, DAY)
    assert (result.result, result.code) == (INCONCLUSIVE, CODE_NOT_ON_SCALE)


def test_rows_and_candles_from_other_days_do_not_count() -> None:
    item = Market(tuple(hand_day()))
    today, previous = day_frames(item)
    candles = candles_frame(item.fills)
    stray_rows = today.with_columns(
        (pl.col("ts").dt.timestamp("us") + MICROS_PER_DAY).cast(pl.Int64).cast(UTC_TIME).alias("ts")
    )
    stray_candles = candles.with_columns(
        (pl.col("open_time").dt.timestamp("us") + MICROS_PER_DAY)
        .cast(pl.Int64)
        .cast(UTC_TIME)
        .alias("open_time")
    )
    both_rows = pl.concat([today, stray_rows])
    both_candles = pl.concat([candles, stray_candles])
    assert check_candle_day(both_rows, both_candles, previous, DAY).result == PASS


def test_the_result_holds_only_a_word_and_a_fixed_code() -> None:
    result = check_candle_day(
        *day_frames(market(1))[:1], candles_frame(market(1).fills), day_frames(market(1))[1], DAY
    )
    assert result.result in (PASS, FAIL, INCONCLUSIVE)
    assert result.code in CODES
    assert not [code for code in CODES if any(character.isdigit() for character in code.split("_", 1)[-1])]


# ---- when condition 2 counts as shown
# ------------------------------------------------------------------------------


DECLARED = declared_sample_days()


def test_the_declared_days_are_the_15ths_of_the_first_span() -> None:
    assert len(DECLARED) == 48
    assert {day.day for day in DECLARED} == {15}
    assert DECLARED[0] == dt.date(2020, 1, 15)
    assert DECLARED[-1] == dt.date(2023, 12, 15)


def test_all_48_passing_shows_it() -> None:
    assert condition_2_shown([(day, PASS) for day in DECLARED]) is True


def test_43_passing_with_every_quarter_covered_shows_it() -> None:
    results = [
        (day, INCONCLUSIVE if index in (1, 4, 7, 10, 13) else PASS) for index, day in enumerate(DECLARED)
    ]
    assert sum(result == PASS for _, result in results) == 43
    assert condition_2_shown(results) is True


def test_42_passing_does_not() -> None:
    results = [
        (day, INCONCLUSIVE if index in (1, 4, 7, 10, 13, 16) else PASS) for index, day in enumerate(DECLARED)
    ]
    assert condition_2_shown(results) is False


def test_one_failing_day_does_not_however_many_pass() -> None:
    results = [(day, FAIL if index == 20 else PASS) for index, day in enumerate(DECLARED)]
    assert condition_2_shown(results) is False


def test_a_quarter_with_no_passing_day_does_not() -> None:
    """2021-Q1 has three of the 48, so 45 pass and that quarter has none."""
    results = [
        (day, INCONCLUSIVE if (day.year, day.month) in ((2021, 1), (2021, 2), (2021, 3)) else PASS)
        for day in DECLARED
    ]
    assert sum(result == PASS for _, result in results) == 45
    assert condition_2_shown(results) is False


def test_passes_on_other_days_do_not_count() -> None:
    results = [(dt.date(2020, 1, 15) + dt.timedelta(days=index + 1), PASS) for index in range(48)]
    assert condition_2_shown(results) is False
