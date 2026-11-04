"""Bars against values worked out by hand."""

from __future__ import annotations

import polars as pl
import pytest

from helpers import DAY, MINUTE, trades_frame, us
from hft_crypto.bars.core import (
    TimingContractError,
    aggregate_bars,
    assert_knowable,
    build_bars_1m,
    minute_close_us,
    visible_bars,
)


def build(rows: list[tuple[int, float, float, bool]], **kwargs: object) -> pl.DataFrame:
    return build_bars_1m(trades_frame(rows), venue="v", symbol="S", **kwargs)  # type: ignore[arg-type]


def test_hand_computed_bar() -> None:
    # Bar (12:00, 12:01]. VWAP inputs: 10@100 buy, 5@103 sell, 1@99 sell, 4@101 buy.
    open_ = us("2026-01-01T12:00:00")
    bars = build(
        [
            (open_ + 1_000_000, 100.0, 10.0, True),
            (open_ + 2_000_000, 103.0, 5.0, False),
            (open_ + 3_000_000, 99.0, 1.0, False),
            (open_ + 4_000_000, 101.0, 4.0, True),
        ]
    )
    assert bars.height == 1
    row = bars.row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (100.0, 103.0, 99.0, 101.0)
    assert row["volume"] == 20.0
    assert row["buy_volume"] == 14.0
    assert row["sell_volume"] == 6.0
    # 1000 + 515 + 99 + 404
    assert row["quote_volume"] == 2018.0
    assert row["trade_count"] == 4
    assert row["fill_count"] == 4
    assert row["gap"] is False
    assert row["open_time"].isoformat() == "2026-01-01T12:00:00+00:00"
    assert row["close_time"].isoformat() == "2026-01-01T12:01:00+00:00"
    assert row["knowable_time"] == row["close_time"]


def test_trade_exactly_on_a_boundary_closes_the_bar_ending_there() -> None:
    boundary = us("2026-01-01T12:01:00")
    assert int(minute_close_us(pl.Series([boundary]).to_numpy())[0]) == boundary
    assert int(minute_close_us(pl.Series([boundary + 1]).to_numpy())[0]) == boundary + MINUTE

    bars = build(
        [
            (boundary - 1, 10.0, 1.0, True),  # (12:00, 12:01]
            (boundary, 20.0, 2.0, False),  # exactly 12:01, still (12:00, 12:01]
            (boundary + 1, 30.0, 4.0, True),  # (12:01, 12:02]
        ]
    )
    first, second = bars.row(0, named=True), bars.row(1, named=True)
    assert first["close_time"].isoformat() == "2026-01-01T12:01:00+00:00"
    assert (first["open"], first["close"], first["volume"]) == (10.0, 20.0, 3.0)
    assert second["close_time"].isoformat() == "2026-01-01T12:02:00+00:00"
    assert (second["open"], second["volume"]) == (30.0, 4.0)


def test_trade_at_the_open_time_belongs_to_the_previous_bar() -> None:
    open_ = us("2026-01-01T12:00:00")
    bars = build(
        [(open_, 50.0, 1.0, True), (open_ + 1, 60.0, 1.0, True)],
        first_close_us=open_ + MINUTE,
        last_close_us=open_ + MINUTE,
    )
    row = bars.row(0, named=True)
    assert row["trade_count"] == 1
    assert row["open"] == 60.0


def test_minutes_with_no_trades_are_rows_with_null_prices_and_zero_volume() -> None:
    start = us("2026-01-01T12:00:00")
    bars = build([(start + 1, 10.0, 1.0, True), (start + 2 * MINUTE + 1, 12.0, 1.0, True)])
    assert bars.height == 3
    empty = bars.row(1, named=True)
    assert empty["close_time"].isoformat() == "2026-01-01T12:02:00+00:00"
    assert empty["open"] is None
    assert empty["high"] is None
    assert empty["low"] is None
    assert empty["close"] is None
    assert empty["volume"] == 0.0
    assert empty["buy_volume"] == 0.0
    assert empty["sell_volume"] == 0.0
    assert empty["trade_count"] == 0


def test_a_grid_with_no_trades_at_all_is_all_empty_rows() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([], first_close_us=start + MINUTE, last_close_us=start + 3 * MINUTE)
    assert bars.height == 3
    assert bars["close"].null_count() == 3
    assert bars["volume"].sum() == 0.0


def test_no_trades_and_no_grid_gives_no_rows() -> None:
    assert build([]).is_empty()


def test_trades_outside_the_grid_are_ignored() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build(
        [(start - 5, 1.0, 1.0, True), (start + 5, 2.0, 1.0, True), (start + 2 * MINUTE, 3.0, 1.0, True)],
        first_close_us=start + MINUTE,
        last_close_us=start + MINUTE,
    )
    assert bars.height == 1
    assert bars["trade_count"][0] == 1
    assert bars["open"][0] == 2.0


def test_equal_timestamps_keep_trade_id_order_whatever_the_input_order() -> None:
    stamp = us("2026-01-01T00:00:30")
    ordered = trades_frame([(stamp, 1.0, 1.0, True), (stamp, 2.0, 1.0, True), (stamp, 3.0, 1.0, True)])
    shuffled = ordered.reverse()
    one = build_bars_1m(ordered, venue="v", symbol="S")
    two = build_bars_1m(shuffled, venue="v", symbol="S")
    assert one.equals(two)
    assert (one["open"][0], one["close"][0]) == (1.0, 3.0)


def test_summing_is_free_of_float_noise() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([(start + i + 1, 100.0, 0.1, i % 2 == 0) for i in range(10)])
    row = bars.row(0, named=True)
    assert row["volume"] == 1.0
    assert row["buy_volume"] == 0.5
    assert row["sell_volume"] == 0.5


def test_knowable_at_moves_knowable_time_later_but_never_earlier() -> None:
    start = us("2026-01-01T00:00:00")
    trades = [(start + 1, 1.0, 1.0, True)]
    close = start + MINUTE
    later = build(trades, knowable_at_us=close + 3_600_000_000)
    assert later["knowable_time"][0].isoformat() == "2026-01-01T01:01:00+00:00"
    earlier = build(trades, knowable_at_us=close - 1)
    assert earlier["knowable_time"][0] == earlier["close_time"][0]


def test_gap_marks_only_the_named_bars() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build(
        [],
        first_close_us=start + MINUTE,
        last_close_us=start + 2 * MINUTE,
        gap_close_us={start + 2 * MINUTE},
    )
    assert bars["gap"].to_list() == [False, True]


def test_grid_must_be_on_a_minute() -> None:
    with pytest.raises(ValueError, match="minute boundary"):
        build([], first_close_us=1, last_close_us=MINUTE)


def _five_minutes() -> pl.DataFrame:
    start = us("2026-01-01T00:00:00")
    rows = [
        (start + 10, 10.0, 1.0, True),
        (start + MINUTE + 10, 14.0, 2.0, False),
        (start + 2 * MINUTE + 10, 8.0, 3.0, True),
        (start + 3 * MINUTE + 10, 11.0, 4.0, False),
        (start + 4 * MINUTE + 10, 12.0, 5.0, True),
    ]
    return build(rows)


def test_higher_timeframe_hand_computed() -> None:
    higher = aggregate_bars(_five_minutes(), 5)
    assert higher.height == 1
    row = higher.row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (10.0, 14.0, 8.0, 12.0)
    assert row["volume"] == 15.0
    assert row["buy_volume"] == 9.0
    assert row["sell_volume"] == 6.0
    assert row["trade_count"] == 5
    assert row["n_1m"] == 5
    assert row["complete"] is True
    assert row["gap"] is False
    assert row["open_time"].isoformat() == "2026-01-01T00:00:00+00:00"
    assert row["close_time"].isoformat() == "2026-01-01T00:05:00+00:00"
    assert row["knowable_time"] == row["close_time"]


def test_higher_timeframe_does_not_appear_until_its_last_minute_is_known() -> None:
    bars = _five_minutes()
    assert aggregate_bars(bars.head(4), 5).is_empty()
    assert aggregate_bars(bars.head(5), 5).height == 1


def test_higher_timeframe_skips_empty_minutes_for_open_and_close() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build(
        [(start + MINUTE + 5, 7.0, 1.0, True), (start + 3 * MINUTE + 5, 9.0, 1.0, True)],
        first_close_us=start + MINUTE,
        last_close_us=start + 5 * MINUTE,
    )
    row = aggregate_bars(bars, 5).row(0, named=True)
    assert (row["open"], row["close"]) == (7.0, 9.0)
    assert row["high"] == 9.0
    assert row["low"] == 7.0
    assert row["complete"] is True


def test_higher_timeframe_with_no_trades_has_null_prices_and_is_still_complete() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([], first_close_us=start + MINUTE, last_close_us=start + 5 * MINUTE)
    row = aggregate_bars(bars, 5).row(0, named=True)
    assert row["close"] is None
    assert row["volume"] == 0.0
    assert row["complete"] is True


def test_higher_timeframe_with_a_missing_minute_is_flagged_not_hidden() -> None:
    bars = _five_minutes().filter(pl.col("close_time").dt.minute() != 3)
    row = aggregate_bars(bars, 5).row(0, named=True)
    assert row["n_1m"] == 4
    assert row["complete"] is False
    assert row["gap"] is True


def test_higher_timeframe_inherits_a_gap_and_a_late_knowable_time() -> None:
    start = us("2026-01-01T00:00:00")
    late = start + 2 * DAY
    bars = build(
        [],
        first_close_us=start + MINUTE,
        last_close_us=start + 5 * MINUTE,
        knowable_at_us=late,
        gap_close_us={start + 2 * MINUTE},
    )
    row = aggregate_bars(bars, 5).row(0, named=True)
    assert row["gap"] is True
    assert row["knowable_time"].isoformat() == "2026-01-03T00:00:00+00:00"


@pytest.mark.parametrize("minutes", [1, 7, 11, 2000])
def test_timeframes_that_cannot_divide_a_day_are_refused(minutes: int) -> None:
    with pytest.raises(ValueError, match="divide"):
        aggregate_bars(_five_minutes(), minutes)


def test_visible_bars_and_the_join_assertion() -> None:
    bars = _five_minutes()
    start = us("2026-01-01T00:00:00")
    assert visible_bars(bars, start + 2 * MINUTE).height == 2
    assert visible_bars(bars, start + 2 * MINUTE - 1).height == 1
    assert_knowable(bars, start + 5 * MINUTE)
    with pytest.raises(TimingContractError):
        assert_knowable(bars, start + 5 * MINUTE - 1)
