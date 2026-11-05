"""Bars against values worked out by hand."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from helpers import DAY, MINUTE, trades_frame, us
from hft_crypto.bars.core import (
    BAR_SCHEMA,
    BOUNDARY_OFFICIAL,
    BOUNDARY_TRADES,
    PROOF_ID_RUN,
    PROOF_NONE,
    PROOF_OFFICIAL,
    PROOF_TRADED,
    SOURCE_OFFICIAL,
    SOURCE_TRADES,
    UTC_TIME,
    TimingContractError,
    aggregate_bars,
    as_of_view,
    assert_knowable,
    bars_for_run,
    bars_from_official,
    build_bars_1m,
    candle_row_faults,
    closes_between,
    find_id_skips,
    find_long_quiets,
    ideal_view,
    minute_close_us,
    standing_as_of,
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


def test_any_row_inside_the_allowance_is_deferred_whatever_its_fill_count() -> None:
    """DR-01, the leak audit correcting its own ruling 2. A row's fill count includes fills from after the
    close, so a rule that excused a row of one fill read the future. This test used to say the opposite."""
    close = us("2026-01-01T12:00:00")
    frame = trades_frame([(close - 50_000, 100.0, 3.0, True)])
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["settled_volume"].to_list() == [0.0, 3.0]


@pytest.mark.parametrize("fills", [1, 2, 9])
def test_what_a_row_settles_into_cannot_depend_on_how_many_fills_it_held(fills: int) -> None:
    """The same row, with fills taken away after the close. What had printed by the close cannot change."""
    close = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [(close - 50_000, 100.0, 3.0, True), (close - 600_000, 100.0, 1.0, False)]
    ).with_columns(pl.Series("n_fills", [fills, fills], dtype=pl.Int32))
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["settled_volume"].to_list() == [1.0, 3.0]


@pytest.mark.parametrize(
    ("before_close_us", "settled"),
    [
        (249_999, [0.0, 2.0]),
        (125_000, [0.0, 2.0]),  # inside half the allowance, which a mutant once treated as enough
        (1, [0.0, 2.0]),
        (250_000, [2.0, 0.0]),
        (250_001, [2.0, 0.0]),
    ],
)
def test_the_allowance_is_the_exact_edge_of_deferral(before_close_us: int, settled: list[float]) -> None:
    close = us("2026-01-01T12:00:00")
    frame = trades_frame([(close - before_close_us, 100.0, 2.0, True)])
    assert _spanning_bars(frame, close, 250_000)["settled_volume"].to_list() == settled


def test_settled_buy_and_sell_follow_the_side_of_each_row() -> None:
    close = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [
            (close - 30_000_000, 100.0, 1.0, True),
            (close - 20_000_000, 100.0, 4.0, False),
            (close - 50_000, 100.0, 2.0, True),
            (close - 40_000, 100.0, 8.0, False),
        ]
    )
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["settled_buy_volume"].to_list() == [1.0, 2.0]
    assert bars["settled_sell_volume"].to_list() == [4.0, 8.0]
    assert bars["settled_quote_volume"].to_list() == [500.0, 1000.0]


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


def test_ideal_replaces_every_flow_column_and_keeps_nothing_that_moves_later() -> None:
    """A view that swapped only the volume survived mutation, so each flow is checked on its own."""
    close = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [
            (close - 30_000_000, 100.0, 1.0, True),
            (close - 20_000_000, 100.0, 4.0, False),
            (close - 50_000, 100.0, 2.0, True),
        ]
    ).with_columns(pl.Series("n_fills", [1, 1, 3], dtype=pl.Int32))
    bars = _spanning_bars(frame, close, 250_000)
    view = ideal_view(bars, ideal_allowed=True)
    for name in ("volume", "quote_volume", "buy_volume", "sell_volume"):
        assert view[name].to_list() == bars[f"settled_{name}"].to_list(), name
    assert view["buy_volume"].to_list() != bars["buy_volume"].to_list()
    assert view["quote_volume"].to_list() != bars["quote_volume"].to_list()
    assert not {"fill_count", "knowable_time", "gap_at_close"} & set(view.columns)
    assert not [name for name in view.columns if name.startswith("settled_")]


# ---- standing as of a moment
# ---------------------------------------------------------------------------------


def _with_empty_minute() -> tuple[pl.DataFrame, int]:
    start = us("2026-01-01T12:00:00")
    # Traded in the first minute, nothing in the second, traded again in the third. Consecutive ids, so the
    # third minute's row is what proves the second empty.
    frame = trades_frame([(start + 30_000_000, 100.0, 1.0, True), (start + 150_000_000, 101.0, 1.0, True)])
    return (
        build_bars_1m(
            frame,
            venue="v",
            symbol="S",
            first_close_us=start + MINUTE,
            last_close_us=start + 3 * MINUTE,
            continuity="trade_id",
            fill_span_allowance_us=250_000,
            received_at_us=None,
        ),
        start,
    )


def test_a_proof_does_not_exist_before_the_row_that_shows_it() -> None:
    """DR-03. Stored standing used to hand a reader at 12:02 the proof that came with a trade at 12:02:30."""
    bars, start = _with_empty_minute()
    second = start + 2 * MINUTE
    assert bars.filter(pl.col("close_time").dt.timestamp("us") == second)["empty_proof"].to_list() == [
        "id_run"
    ]
    assert bars.filter(pl.col("close_time").dt.timestamp("us") == second)["gap"].to_list() == [False]
    before = standing_as_of(bars, second)
    assert before["empty_proof"].to_list() == ["traded", "none"]
    assert before["gap"].to_list() == [False, True]
    after = standing_as_of(bars, start + 3 * MINUTE)
    assert after["empty_proof"].to_list() == ["traded", "id_run", "traded"]
    assert after["gap"].to_list() == [False, False, False]


def test_a_flag_known_only_later_reads_as_unflagged_before_that() -> None:
    """DR-04. A last bar flagged because the next day disagrees has its own known time, and it is not the
    close."""
    start = us("2026-01-01T12:00:00")
    frame = trades_frame([(start + 30_000_000, 100.0, 1.0, True), (start + 90_000_000, 100.0, 1.0, True)])
    last = start + 2 * MINUTE
    later = last + MINUTE + 250_000
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=last,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
        late_gap_close_us={last: later},
    )
    assert bars["gap"].to_list() == [False, True]
    assert bars["gap_at_close"].to_list() == [False, False]
    assert bars["knowable_time"].dt.timestamp("us").to_list()[-1] == later
    assert standing_as_of(bars, later - 1)["gap"].to_list() == [False, False]
    assert standing_as_of(bars, later)["gap"].to_list() == [False, True]


def test_a_flag_for_a_cause_known_at_the_close_counts_from_the_close() -> None:
    start = us("2026-01-01T12:00:00")
    frame = trades_frame([(start + 30_000_000, 100.0, 1.0, True), (start + 90_000_000, 100.0, 1.0, True)])
    bars = build_bars_1m(
        frame,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 2 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
        gap_close_us=frozenset({start + MINUTE}),
    )
    assert bars["gap_at_close"].to_list() == [True, False]


def test_a_view_at_a_moment_equals_a_build_truncated_at_that_moment_on_every_column() -> None:
    """DR-03, on the one case that is easy to state by hand. tests/leak does it on generated days."""
    bars, start = _with_empty_minute()
    moment = start + 2 * MINUTE
    cut = trades_frame([(start + 30_000_000, 100.0, 1.0, True)])
    truncated = build_bars_1m(
        cut,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=moment,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
    )
    assert as_of_view(bars, 1, moment).equals(as_of_view(truncated, 1, moment))
    assert ideal_view(as_of_view(bars, 1, moment), ideal_allowed=True).equals(
        ideal_view(as_of_view(truncated, 1, moment), ideal_allowed=True)
    )


# ---- official candles, the tier T0 path
# ---------------------------------------------------------------------------------


def _candles(rows: list[tuple[int, float, int]]) -> pl.DataFrame:
    """Candles from (open_us, volume, trade_count), at one price, with a third of the volume bought."""
    return pl.DataFrame(
        {
            "open_time": pl.Series([r[0] for r in rows], dtype=pl.Int64).cast(UTC_TIME),
            "open": [100.0] * len(rows),
            "high": [102.0] * len(rows),
            "low": [99.0] * len(rows),
            "close": [101.0] * len(rows),
            "volume": [r[1] for r in rows],
            "quote_volume": [r[1] * 100.0 for r in rows],
            "taker_buy_volume": [r[1] / 3.0 for r in rows],
            "trade_count": [r[2] for r in rows],
        }
    )


def _official(rows: list[tuple[int, float, int]], start: int, minutes: int) -> pl.DataFrame:
    return bars_from_official(
        _candles(rows),
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + minutes * MINUTE,
        candle_allowance_us=250_000,
    )


def test_official_bars_say_so_on_every_row_and_fit_the_schema() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2), (start + MINUTE, 6.0, 5)], start, 2)
    assert bars.schema == BAR_SCHEMA
    assert bars["bar_source"].to_list() == [SOURCE_OFFICIAL] * 2
    assert bars["bar_source"][0] == "official_1m"
    assert bars["boundary"].to_list() == [BOUNDARY_OFFICIAL] * 2
    assert bars["boundary"][0] == "[open, close)"
    assert bars["open"].to_list() == [100.0, 100.0]
    assert bars["high"].to_list() == [102.0, 102.0]
    assert bars["low"].to_list() == [99.0, 99.0]
    assert bars["close"].to_list() == [101.0, 101.0]
    assert bars["volume"].to_list() == [3.0, 6.0]
    assert bars["quote_volume"].to_list() == [300.0, 600.0]
    assert bars["buy_volume"].to_list() == [1.0, 2.0]
    assert bars["sell_volume"].to_list() == [2.0, 4.0]
    assert bars["trade_count"].to_list() == [2, 5]
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_TRADED]
    assert bars["gap"].to_list() == [False, False]
    assert bars["close_time"].dt.timestamp("us").to_list() == [start + MINUTE, start + 2 * MINUTE]
    assert bars["knowable_time"].dt.timestamp("us").to_list() == [
        start + MINUTE + 250_000,
        start + 2 * MINUTE + 250_000,
    ]


def test_official_bars_need_no_settling_because_a_candle_counts_each_fill_in_its_own_minute() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2), (start + MINUTE, 6.0, 5)], start, 2)
    for name in ("volume", "quote_volume", "buy_volume", "sell_volume"):
        assert bars[f"settled_{name}"].to_list() == bars[name].to_list(), name


def test_an_official_minute_with_no_trades_has_no_price_and_a_proof_of_its_own() -> None:
    """A candle with a count of zero carries the last price, which is not a print."""
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2), (start + MINUTE, 0.0, 0)], start, 2)
    assert bars["close"].to_list() == [101.0, None]
    assert bars["open"].to_list() == [100.0, None]
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_OFFICIAL]
    assert bars["gap"].to_list() == [False, False]
    # The row is its own proof, so nothing here rests on a later row (ruling 7 condition 4).
    assert standing_as_of(bars, start + 2 * MINUTE)["empty_proof"].to_list() == [PROOF_TRADED, PROOF_OFFICIAL]
    assert standing_as_of(bars, start + 2 * MINUTE)["gap"].to_list() == [False, False]


def test_a_minute_with_no_candle_at_all_is_a_gap_and_candles_off_the_grid_are_ignored() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official(
        [
            (start - MINUTE, 9.0, 9),
            (start, 3.0, 2),
            (start + 2 * MINUTE, 6.0, 5),
            (start + 3 * MINUTE, 9.0, 9),
        ],
        start,
        3,
    )
    assert bars["volume"].to_list() == [3.0, 0.0, 6.0]
    assert bars["empty_proof"].to_list() == [PROOF_TRADED, PROOF_NONE, PROOF_TRADED]
    assert bars["gap"].to_list() == [False, True, False]


def test_official_bars_refuse_a_grid_off_the_minute_and_empty_grids_are_empty() -> None:
    start = us("2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="minute"):
        bars_from_official(
            _candles([]),
            venue="v",
            symbol="S",
            first_close_us=start + 1,
            last_close_us=start + MINUTE,
            candle_allowance_us=0,
        )
    with pytest.raises(ValueError, match="negative"):
        bars_from_official(
            _candles([]),
            venue="v",
            symbol="S",
            first_close_us=start,
            last_close_us=start + MINUTE,
            candle_allowance_us=-1,
        )
    empty = bars_from_official(
        _candles([]),
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start,
        candle_allowance_us=0,
    )
    assert empty.is_empty()
    assert empty.schema == BAR_SCHEMA


def test_a_bar_is_unknowable_until_its_close_plus_the_candle_allowance() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2), (start + MINUTE, 6.0, 5)], start, 2)
    close = start + MINUTE
    # Not at its open, which would be a one-bar leak, and not at its close either.
    assert visible_bars(bars, start).is_empty()
    assert visible_bars(bars, close).is_empty()
    assert visible_bars(bars, close + 249_999).is_empty()
    assert visible_bars(bars, close + 250_000).height == 1
    with pytest.raises(TimingContractError):
        bars_for_run(bars, close, close + 249_999)
    assert bars_for_run(bars, close, close + 250_000).height == 1


@pytest.mark.parametrize(
    ("change", "flagged"),
    [
        ({"high": 99.5}, True),  # below the open
        ({"high": 100.5}, True),  # below the close
        ({"low": 100.5}, True),  # above the open
        ({"low": 101.5}, True),  # above the close
        ({"taker_buy_volume": 4.0}, True),  # above the volume
        ({"trade_count": 0}, True),  # volume with no trades
        ({"volume": 3.0}, False),
    ],
)
def test_a_row_that_fails_a_check_flags_that_minute_and_no_other(
    change: dict[str, Any], flagged: bool
) -> None:
    """Ruling 7 condition 5. The bar stays, as a failed check never removes one."""
    start = us("2026-01-01T00:00:00")
    candles = _candles([(start, 3.0, 2), (start + MINUTE, 3.0, 2), (start + 2 * MINUTE, 3.0, 2)])
    row = pl.DataFrame({name: [value] for name, value in change.items()})
    columns = {
        name: pl.when(pl.col("open_time").dt.timestamp("us") == start + MINUTE)
        .then(pl.lit(row[name][0]))
        .otherwise(pl.col(name))
        .cast(candles.schema[name])
        .alias(name)
        for name in change
    }
    bad = candles.with_columns(*columns.values())
    assert candle_row_faults(bad).tolist() == [False, flagged, False]
    bars = bars_from_official(
        bad,
        venue="v",
        symbol="S",
        first_close_us=start + MINUTE,
        last_close_us=start + 3 * MINUTE,
        candle_allowance_us=0,
    )
    assert bars["gap"].to_list() == [False, flagged, False]
    assert bars.height == 3


def test_a_row_with_no_trades_is_not_checked_on_its_prices() -> None:
    """What a venue writes there is UNVERIFIED, and the prices are removed in any case."""
    start = us("2026-01-01T00:00:00")
    candles = _candles([(start, 0.0, 0)]).with_columns(pl.lit(0.0).alias("high"), pl.lit(0.0).alias("low"))
    assert candle_row_faults(candles).tolist() == [False]


def test_a_candles_open_label_and_file_close_field_are_not_its_close() -> None:
    """close_time is open + 60 s on the grid. The file's own field, open + 59.999 s, would show a bar 1 ms
    early."""
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2)], start, 1)
    assert bars["open_time"].dt.timestamp("us").to_list() == [start]
    assert bars["close_time"].dt.timestamp("us").to_list() == [start + MINUTE]


def test_trade_bars_state_their_own_source_and_boundary() -> None:
    frame, close = _spanning_row()
    bars = _spanning_bars(frame, close, 250_000)
    assert bars["bar_source"].unique().to_list() == [SOURCE_TRADES]
    assert bars["boundary"].unique().to_list() == [BOUNDARY_TRADES]
    assert bars["boundary"][0] == "(open, close]"


def test_ideal_on_official_bars_keeps_fill_count_only_when_asked() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official([(start, 3.0, 2)], start, 1)
    assert "fill_count" not in ideal_view(bars, ideal_allowed=True).columns
    kept = ideal_view(bars, ideal_allowed=True, keep_fill_count=True)
    assert kept["fill_count"].to_list() == [2]


def test_a_view_of_official_bars_needs_no_later_row() -> None:
    start = us("2026-01-01T00:00:00")
    full = _official([(start, 3.0, 2), (start + MINUTE, 0.0, 0), (start + 2 * MINUTE, 6.0, 5)], start, 3)
    cut = _official([(start, 3.0, 2), (start + MINUTE, 0.0, 0)], start, 2)
    moment = start + 2 * MINUTE
    assert as_of_view(full, 1, moment).equals(as_of_view(cut, 1, moment))


def test_higher_bars_keep_the_source_and_refuse_a_mix_of_sources() -> None:
    start = us("2026-01-01T00:00:00")
    bars = _official([(start + m * MINUTE, 1.0, 1) for m in range(10)], start, 10)
    higher = aggregate_bars(bars, 5, through_close_us=start + 10 * MINUTE)
    assert higher["bar_source"].to_list() == [SOURCE_OFFICIAL] * 2
    assert higher["boundary"].to_list() == [BOUNDARY_OFFICIAL] * 2
    assert higher["volume"].to_list() == [5.0, 5.0]
    mixed = pl.concat(
        [
            bars.head(5),
            bars.tail(5).with_columns(pl.lit("trades").alias("bar_source")),
        ]
    )
    with pytest.raises(ValueError, match="source"):
        aggregate_bars(mixed, 5, through_close_us=start + 10 * MINUTE)


def test_trades_for_a_run_stop_at_the_cut_and_not_at_the_decision() -> None:
    """Item 4. Its test used to call this with the two times equal, so it could not tell them apart."""
    start = us("2026-01-01T12:00:00")
    frame = trades_frame(
        [
            (start - 1, 100.0, 1.0, True),
            (start, 100.0, 1.0, True),
            (start + 1, 100.0, 1.0, True),
            (start + MINUTE, 100.0, 1.0, True),
        ]
    )
    rows = trades_for_run(frame, start, start + 5 * MINUTE)
    # A trade exactly at the cut is in, and the two after it are not, though the decision comes later.
    assert rows["ts"].dt.timestamp("us").to_list() == [start - 1, start]


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
