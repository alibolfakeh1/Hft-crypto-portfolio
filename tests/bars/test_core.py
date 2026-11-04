"""Bars against values worked out by hand."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from helpers import DAY, MINUTE, trades_frame, us
from hft_crypto.bars.core import (
    PROOF_ID_RUN,
    PROOF_NONE,
    PROOF_TRADED,
    TimingContractError,
    aggregate_bars,
    assert_knowable,
    bars_for_run,
    build_bars_1m,
    closes_between,
    find_id_skips,
    find_long_quiets,
    ideal_view,
    minute_close_us,
    trades_for_run,
    visible_bars,
)

Rows = list[tuple[int, float, float, bool]]


def closes_for(rows: Rows) -> tuple[int, int]:
    stamps = [row[0] for row in rows]
    return (
        ((min(stamps) - 1) // MINUTE + 1) * MINUTE,
        ((max(stamps) - 1) // MINUTE + 1) * MINUTE,
    )


def build(rows: Rows, **kwargs: Any) -> pl.DataFrame:
    """A test's own convenience: the grid covers its rows unless the test names one."""
    first, last = closes_for(rows) if rows else (0, 0)
    arguments: dict[str, Any] = {
        "venue": "v",
        "symbol": "S",
        "first_close_us": first,
        "last_close_us": last,
        "continuity": "trade_id",
        "fill_span_allowance_us": 0,
        "received_at_us": None,
    }
    arguments.update(kwargs)
    return build_bars_1m(trades_frame(rows), **arguments)


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
    assert row["empty_proof"] == PROOF_TRADED
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


def test_a_grid_is_required_so_a_bar_never_exists_because_a_later_trade_does() -> None:
    frame = trades_frame([(us("2026-01-01T12:00:30"), 1.0, 1.0, True)])
    with pytest.raises(TypeError):
        build_bars_1m(frame, venue="v", symbol="S")  # type: ignore[call-arg]


@pytest.mark.parametrize("missing", ["continuity", "fill_span_allowance_us", "received_at_us"])
def test_every_argument_that_decides_timing_is_required(missing: str) -> None:
    arguments: dict[str, Any] = {
        "venue": "v",
        "symbol": "S",
        "first_close_us": MINUTE,
        "last_close_us": MINUTE,
        "continuity": "trade_id",
        "fill_span_allowance_us": 0,
        "received_at_us": None,
    }
    del arguments[missing]
    with pytest.raises(TypeError):
        build_bars_1m(trades_frame([]), **arguments)


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


def test_consecutive_ids_prove_an_empty_minute() -> None:
    start = us("2026-01-01T12:00:00")
    bars = build([(start + 1, 10.0, 1.0, True), (start + 2 * MINUTE + 1, 12.0, 1.0, True)])
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_ID_RUN, PROOF_TRADED]
    assert bars["gap"].to_list() == [False, False, False]


def test_a_proven_empty_minute_is_not_known_until_the_row_that_proves_it_is() -> None:
    start = us("2026-01-01T12:00:00")
    later = start + 5 * MINUTE + 1
    bars = build([(start + 1, 10.0, 1.0, True), (later, 12.0, 1.0, True)])
    empty = bars.filter(pl.col("empty_proof") == PROOF_ID_RUN)
    assert empty.height == 4
    assert empty["knowable_time"].dt.timestamp("us").unique().to_list() == [later]


def test_a_skip_in_the_ids_flags_every_minute_from_the_row_before_through_the_row_after() -> None:
    start = us("2026-01-01T12:00:00")
    rows = trades_frame([(start + 1, 10.0, 1.0, True)])
    after = trades_frame([(start + 3 * MINUTE + 1, 12.0, 1.0, True)], first_id=50)
    bars = build_bars_1m(
        pl.concat([rows, after]),
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 5 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    # The row before is in 12:01, the row after in 12:04. The last minute has no row after it at all.
    assert bars["gap"].to_list() == [True, True, True, True, True]
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_NONE, PROOF_NONE, PROOF_TRADED, PROOF_NONE]


def test_what_a_skip_flags_is_not_known_before_the_row_that_shows_the_skip() -> None:
    start = us("2026-01-01T12:00:00")
    before = trades_frame([(start + 1, 10.0, 1.0, True)])
    after = trades_frame([(start + 3 * MINUTE + 1, 12.0, 1.0, True)], first_id=50)
    bars = build_bars_1m(
        pl.concat([before, after]),
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 4 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    known = bars["knowable_time"].dt.timestamp("us").to_list()
    assert known[:3] == [start + 3 * MINUTE + 1] * 3
    assert visible_bars(bars, start + 3 * MINUTE).is_empty()


def test_continuity_none_never_proves_an_empty_minute() -> None:
    start = us("2026-01-01T12:00:00")
    bars = build(
        [(start + 1, 10.0, 1.0, True), (start + 2 * MINUTE + 1, 12.0, 1.0, True)],
        continuity="none",
    )
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_NONE, PROOF_TRADED]
    assert bars["gap"].to_list() == [False, True, False]


def test_a_row_number_can_never_prove_continuity() -> None:
    start = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [(start + 1, 10.0, 1.0, True), (start + 2 * MINUTE + 1, 12.0, 1.0, True)]
    ).with_columns(pl.lit(None, dtype=pl.Int64).alias("trade_id"))
    with pytest.raises(ValueError, match="id on every row"):
        build_bars_1m(
            frame,
            venue="v",
            symbol="S",
            first_close_us=start + MINUTE,
            last_close_us=start + 3 * MINUTE,
            continuity="trade_id",
            fill_span_allowance_us=0,
            received_at_us=None,
        )
    assert find_id_skips(frame) == []


def test_rows_outside_the_grid_prove_its_edges_and_add_nothing_to_it() -> None:
    start = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [
            (start - 10 * MINUTE, 1.0, 1.0, True),
            (start + 10 * MINUTE, 2.0, 1.0, True),
        ]
    )
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 2 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    assert bars["trade_count"].sum() == 0
    assert bars["empty_proof"].to_list() == [PROOF_ID_RUN, PROOF_ID_RUN]
    assert bars["gap"].to_list() == [False, False]


def test_a_grid_with_no_trades_at_all_is_all_gaps() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([], first_close_us=start + MINUTE, last_close_us=start + 3 * MINUTE)
    assert bars.height == 3
    assert bars["close"].null_count() == 3
    assert bars["volume"].sum() == 0.0
    assert bars["gap"].to_list() == [True, True, True]
    assert bars["empty_proof"].to_list() == [PROOF_NONE] * 3


def test_an_empty_grid_gives_no_rows() -> None:
    assert build([], first_close_us=2 * MINUTE, last_close_us=MINUTE).is_empty()


def test_trades_outside_the_grid_are_not_counted() -> None:
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
    grid: dict[str, Any] = {
        "venue": "v",
        "symbol": "S",
        "first_close_us": us("2026-01-01T00:01:00"),
        "last_close_us": us("2026-01-01T00:01:00"),
        "continuity": "trade_id",
        "fill_span_allowance_us": 0,
        "received_at_us": None,
    }
    one = build_bars_1m(ordered, **grid)
    two = build_bars_1m(shuffled, **grid)
    assert one.equals(two)
    assert (one["open"][0], one["close"][0]) == (1.0, 3.0)


def test_summing_is_free_of_float_noise() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([(start + i + 1, 100.0, 0.1, i % 2 == 0) for i in range(10)])
    row = bars.row(0, named=True)
    assert row["volume"] == 1.0
    assert row["buy_volume"] == 0.5
    assert row["sell_volume"] == 0.5


def test_received_time_moves_knowable_time_later_but_never_earlier() -> None:
    start = us("2026-01-01T00:00:00")
    trades = [(start + 1, 1.0, 1.0, True)]
    close = start + MINUTE
    later = build(trades, received_at_us=close + 3_600_000_000)
    assert later["knowable_time"][0].isoformat() == "2026-01-01T01:01:00+00:00"
    earlier = build(trades, received_at_us=close - 1)
    assert earlier["knowable_time"][0] == earlier["close_time"][0]


def test_a_bar_is_knowable_at_its_close_plus_the_allowance() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([(start + 1, 1.0, 1.0, True)], fill_span_allowance_us=250_000)
    assert bars["knowable_time"].dt.timestamp("us")[0] == start + MINUTE + 250_000


def test_a_bar_is_never_knowable_before_its_newest_row_is() -> None:
    """Rows received late keep that receipt, and a bar built from them cannot be known before it."""
    start = us("2026-01-01T00:00:00")
    received = start + 3_600_000_000
    frame = trades_frame([(start + 1, 1.0, 1.0, True)]).with_columns(
        pl.lit(received, dtype=pl.Int64).cast(pl.Datetime("us", "UTC")).alias("knowable_time")
    )
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    assert bars["knowable_time"].dt.timestamp("us")[0] == received


def test_gap_marks_the_named_bars_as_well() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build(
        [(start + 1, 1.0, 1.0, True), (start + MINUTE + 1, 1.0, 1.0, True)],
        first_close_us=start + MINUTE,
        last_close_us=start + 2 * MINUTE,
        gap_close_us={start + 2 * MINUTE},
    )
    assert bars["gap"].to_list() == [False, True]


def test_grid_must_be_on_a_minute() -> None:
    with pytest.raises(ValueError, match="minute boundary"):
        build([], first_close_us=1, last_close_us=MINUTE)


def test_a_negative_allowance_and_an_unknown_continuity_are_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        build([], first_close_us=MINUTE, last_close_us=MINUTE, fill_span_allowance_us=-1)
    with pytest.raises(ValueError, match="continuity"):
        build([], first_close_us=MINUTE, last_close_us=MINUTE, continuity="sometimes")


def test_helpers_for_holes() -> None:
    start = us("2026-01-01T12:00:00")
    assert closes_between(start + 1, start + 2 * MINUTE + 1) == {
        start + MINUTE,
        start + 2 * MINUTE,
        start + 3 * MINUTE,
    }
    frame = trades_frame([(start + 1, 1.0, 1.0, True), (start + 20 * MINUTE, 1.0, 1.0, True)])
    assert find_long_quiets(frame, 15 * MINUTE) == [(start + 1, start + 20 * MINUTE)]
    assert find_long_quiets(frame, 20 * MINUTE) == []


# ---- what had printed by the close: the leak audit's ruling 2
# ------------------------------------------------


def _spanning_row() -> tuple[pl.DataFrame, int]:
    """A one-stamp row of 3 units, 50 ms before 12:00, whose fills may run past it. Plus 10 units earlier."""
    close = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [(close - 30_000_000, 100.0, 10.0, True), (close - 50_000, 100.0, 3.0, True)]
    ).with_columns(pl.Series("n_fills", [1, 2], dtype=pl.Int32))
    return frame, close


def _spanning_bars(frame: pl.DataFrame, close: int, allowance_us: int) -> pl.DataFrame:
    return build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=close,
        last_close_us=close + MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=allowance_us,
        received_at_us=None,
    )


def test_settled_columns_hold_only_what_had_printed_by_the_close() -> None:
    frame, close = _spanning_row()
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["volume"].to_list() == [13.0, 0.0]
    assert bars["settled_volume"].to_list() == [10.0, 3.0]
    assert bars["settled_buy_volume"].to_list() == [10.0, 3.0]
    assert bars["settled_quote_volume"].to_list() == [1000.0, 300.0]


def test_a_row_of_one_fill_with_its_own_stamp_is_not_deferred() -> None:
    close = us("2026-01-01T12:00:00")
    frame = trades_frame([(close - 50_000, 100.0, 3.0, True)])
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["settled_volume"].to_list() == [3.0, 0.0]


def test_rows_sharing_a_stamp_near_the_close_are_deferred() -> None:
    close = us("2026-01-01T12:00:00")
    stamp = close - 50_000
    frame = trades_frame([(stamp, 100.0, 1.0, True), (stamp, 101.0, 2.0, False)])
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["settled_volume"].to_list() == [0.0, 3.0]
    assert bars["settled_sell_volume"].to_list() == [0.0, 2.0]


def test_a_spanning_row_older_than_the_allowance_stays_in_its_bar() -> None:
    frame, close = _spanning_row()
    bars = _spanning_bars(frame, close, 10_000)
    assert bars["settled_volume"].to_list() == [13.0, 0.0]


def test_a_row_just_before_the_grid_carries_into_the_first_settled_columns() -> None:
    close = us("2026-01-01T12:00:00")
    frame = trades_frame([(close - 50_000, 100.0, 3.0, True)]).with_columns(
        pl.Series("n_fills", [2], dtype=pl.Int32)
    )
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=close + MINUTE,
        last_close_us=close + MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
    )
    assert bars["volume"].to_list() == [0.0]
    assert bars["settled_volume"].to_list() == [3.0]


def test_ideal_reads_only_the_settled_columns_and_a_source_that_cannot_give_them_is_refused() -> None:
    frame, close = _spanning_row()
    bars = _spanning_bars(frame, close, 250_000)
    view = ideal_view(bars, ideal_allowed=True)
    assert view["volume"].to_list() == [10.0, 3.0]
    assert "settled_volume" not in view.columns
    with pytest.raises(TimingContractError, match="IDEAL"):
        ideal_view(bars, ideal_allowed=False)


def test_settled_columns_add_up_across_a_higher_bar() -> None:
    frame, close = _spanning_row()
    start = close - 5 * MINUTE
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 10 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
    )
    higher = aggregate_bars(bars, 5, through_close_us=start + 10 * MINUTE)
    assert higher["volume"].to_list() == [13.0, 0.0]
    assert higher["settled_volume"].to_list() == [10.0, 3.0]


# ---- higher timeframes
# ---------------------------------------------------------------------------------------


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


END = us("2026-01-02T00:00:00")


def test_higher_timeframe_hand_computed() -> None:
    higher = aggregate_bars(_five_minutes(), 5, through_close_us=END)
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


def test_a_stated_closing_time_is_required() -> None:
    with pytest.raises(TypeError):
        aggregate_bars(_five_minutes(), 5)  # type: ignore[call-arg]


def test_higher_timeframe_does_not_appear_until_its_close_is_known() -> None:
    bars = _five_minutes()
    close = us("2026-01-01T00:05:00")
    assert aggregate_bars(bars, 5, through_close_us=close - 1).is_empty()
    assert aggregate_bars(bars, 5, through_close_us=close).height == 1


def test_a_higher_bar_missing_its_last_minutes_is_flagged_even_when_past_the_close() -> None:
    """A row held from 12:04:30 must not pass as the finished 5m bar closing 12:05."""
    bars = _five_minutes().head(4)
    row = aggregate_bars(bars, 5, through_close_us=END).row(0, named=True)
    assert row["n_1m"] == 4
    assert row["complete"] is False
    assert row["gap"] is True


def test_higher_timeframe_skips_empty_minutes_for_open_and_close() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build(
        [
            (start + 5, 6.0, 1.0, True),
            (start + MINUTE + 5, 7.0, 1.0, True),
            (start + 3 * MINUTE + 5, 9.0, 1.0, True),
            (start + 5 * MINUTE + 5, 6.0, 1.0, True),
        ],
        first_close_us=start + 6 * MINUTE,
        last_close_us=start + 6 * MINUTE,
    )
    assert bars.height == 1
    grid = build(
        [
            (start + MINUTE + 5, 7.0, 1.0, True),
            (start + 3 * MINUTE + 5, 9.0, 1.0, True),
            (start + 5 * MINUTE + 5, 6.0, 1.0, True),
        ],
        first_close_us=start + MINUTE,
        last_close_us=start + 5 * MINUTE,
    )
    row = aggregate_bars(grid, 5, through_close_us=END).row(0, named=True)
    assert (row["open"], row["close"]) == (7.0, 9.0)
    assert row["high"] == 9.0
    assert row["low"] == 7.0


def test_a_higher_bar_is_complete_only_if_every_empty_minute_is_proven() -> None:
    start = us("2026-01-01T00:00:00")
    rows = [(start + 5, 7.0, 1.0, True), (start + 5 * MINUTE + 5, 9.0, 1.0, True)]
    proven = build(rows, first_close_us=start + MINUTE, last_close_us=start + 5 * MINUTE)
    assert aggregate_bars(proven, 5, through_close_us=END)["complete"].to_list() == [True]
    unproven = build(rows, first_close_us=start + MINUTE, last_close_us=start + 5 * MINUTE, continuity="none")
    row = aggregate_bars(unproven, 5, through_close_us=END).row(0, named=True)
    assert row["complete"] is False
    assert row["gap"] is True


def test_higher_timeframe_with_no_trades_has_null_prices_and_is_not_complete() -> None:
    start = us("2026-01-01T00:00:00")
    bars = build([], first_close_us=start + MINUTE, last_close_us=start + 5 * MINUTE)
    row = aggregate_bars(bars, 5, through_close_us=END).row(0, named=True)
    assert row["close"] is None
    assert row["volume"] == 0.0
    assert row["complete"] is False


def test_higher_timeframe_with_a_missing_minute_is_flagged_not_hidden() -> None:
    bars = _five_minutes().filter(pl.col("close_time").dt.minute() != 3)
    row = aggregate_bars(bars, 5, through_close_us=END).row(0, named=True)
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
        received_at_us=late,
        gap_close_us={start + 2 * MINUTE},
    )
    row = aggregate_bars(bars, 5, through_close_us=late).row(0, named=True)
    assert row["gap"] is True
    assert row["knowable_time"].isoformat() == "2026-01-03T00:00:00+00:00"


@pytest.mark.parametrize("minutes", [1, 7, 11, 2000])
def test_timeframes_that_cannot_divide_a_day_are_refused(minutes: int) -> None:
    with pytest.raises(ValueError, match="divide"):
        aggregate_bars(_five_minutes(), minutes, through_close_us=END)


def test_two_venues_are_never_merged_into_one_bar() -> None:
    bars = _five_minutes()
    other = bars.with_columns(pl.lit("w").alias("venue"))
    with pytest.raises(ValueError, match="one venue"):
        aggregate_bars(pl.concat([bars.head(2), other.tail(3)]), 5, through_close_us=END)


# ---- reading by time
# ----------------------------------------------------------------------------------------


def test_visible_bars_and_the_join_assertion() -> None:
    bars = _five_minutes()
    start = us("2026-01-01T00:00:00")
    assert visible_bars(bars, start + 2 * MINUTE).height == 2
    assert visible_bars(bars, start + 2 * MINUTE - 1).height == 1
    assert_knowable(bars, start + 5 * MINUTE)
    with pytest.raises(TimingContractError):
        assert_knowable(bars, start + 5 * MINUTE - 1)


def test_a_run_reads_by_both_of_its_clocks() -> None:
    bars = _five_minutes()
    start = us("2026-01-01T00:00:00")
    t_cut = start + 3 * MINUTE
    selected = bars_for_run(bars, t_cut, t_cut + 65_000_000)
    assert selected["close_time"].dt.timestamp("us").to_list() == [
        start + MINUTE,
        start + 2 * MINUTE,
        start + 3 * MINUTE,
    ]


def test_a_bar_at_or_before_the_cut_that_this_run_could_not_have_had_is_an_error() -> None:
    """The bar closed before t_cut and was received after t_dec. It is never quietly dropped."""
    start = us("2026-01-01T00:00:00")
    received = start + 2 * 3_600_000_000
    bars = build([(start + 1, 1.0, 1.0, True)], received_at_us=received)
    with pytest.raises(TimingContractError):
        bars_for_run(bars, start + MINUTE, start + MINUTE + 65_000_000)
    assert bars_for_run(bars, start + MINUTE, received).height == 1


def test_a_run_cannot_commit_before_its_own_cut() -> None:
    bars = _five_minutes()
    with pytest.raises(TimingContractError, match="before its own"):
        bars_for_run(bars, 2 * MINUTE, MINUTE)
    with pytest.raises(TimingContractError, match="before its own"):
        trades_for_run(trades_frame([]), 2 * MINUTE, MINUTE)


def test_trades_for_a_run_stop_at_the_cut_and_raise_on_a_late_receipt() -> None:
    start = us("2026-01-01T00:00:00")
    frame = trades_frame([(start + 1, 1.0, 1.0, True), (start + MINUTE + 1, 1.0, 1.0, True)])
    assert trades_for_run(frame, start + MINUTE, start + MINUTE).height == 1
    late = frame.with_columns(
        pl.lit(start + 3_600_000_000, dtype=pl.Int64).cast(pl.Datetime("us", "UTC")).alias("knowable_time")
    )
    with pytest.raises(TimingContractError):
        trades_for_run(late, start + MINUTE, start + MINUTE)
