"""Reconciliation against official candles, on generated files with invented values."""

from __future__ import annotations

import polars as pl
import pytest

from helpers import DAY, MINUTE, trades_frame, us
from hft_crypto.bars.core import UTC_TIME, build_bars_1m
from hft_crypto.bars.reconcile import (
    DayFlow,
    OfficialReconciliation,
    compare_emitted_with_rebuild,
    compare_live_with_archive,
    cross_venue_check,
    reconcile_official,
)
from hft_crypto.config import ReconTolerance

DAY_START = us("2026-02-10T00:00:00")
DAY_END = DAY_START + DAY
TOLERANCE = ReconTolerance(daily_total_abs=1e-6, bar_price_rel=0.02, fill_count_rel=0.01)
WINDOW_MS = 250.0
QUIET = DayFlow(0.0, 0.0, 0.0, 0.0)
SECOND = 1_000_000


def official_from(rows: list[tuple[int, float, float]], *, count: int | None = None) -> pl.DataFrame:
    """Candles from (minute index, volume, taker buy volume). Other minutes are empty, at the same price."""
    table = {minute: (volume, buy) for minute, volume, buy in rows}
    stamps = [DAY_START + m * MINUTE for m in range(1440)]
    return pl.DataFrame(
        {
            "open_time": pl.Series(stamps, dtype=pl.Int64).cast(UTC_TIME),
            "open": [100.0] * 1440,
            "high": [100.0] * 1440,
            "low": [100.0] * 1440,
            "close": [100.0] * 1440,
            "volume": [table.get(m, (0.0, 0.0))[0] for m in range(1440)],
            "taker_buy_volume": [table.get(m, (0.0, 0.0))[1] for m in range(1440)],
            "trade_count": [
                (1 if table.get(m, (0.0, 0.0))[0] else 0) if count is None else count for m in range(1440)
            ],
        }
    )


def day_bars(trades: pl.DataFrame) -> pl.DataFrame:
    return build_bars_1m(
        trades,
        venue="generated",
        symbol="BTCUSDT",
        first_close_us=DAY_START + MINUTE,
        last_close_us=DAY_END,
        continuity="none",
        fill_span_allowance_us=0,
        received_at_us=None,
    )


def trades(rows: list[tuple[int, float]], *, buy: bool = True) -> pl.DataFrame:
    return trades_frame([(stamp, 100.0, qty, buy) for stamp, qty in rows])


def check(
    file: pl.DataFrame,
    official: pl.DataFrame,
    *,
    tail: pl.DataFrame | None = None,
    previous: DayFlow | None = QUIET,
    following: DayFlow | None = QUIET,
    first_day: bool = False,
) -> OfficialReconciliation:
    return reconcile_official(
        file,
        day_bars(file),
        official,
        TOLERANCE,
        window_ms=WINDOW_MS,
        previous_tail=tail,
        previous_flow=previous,
        next_flow=following,
        is_first_day=first_day,
    )


def test_identical_day_passes() -> None:
    file = trades([(DAY_START + 30 * SECOND, 2.0), (DAY_START + 90 * SECOND, 3.0)])
    result = check(file, official_from([(0, 2.0, 2.0), (1, 3.0, 3.0)]))
    assert result.status == "pass"
    assert result.volume_diff == 0.0
    assert result.needs_previous_day is False
    assert result.needs_next_day is False
    assert result.boundaries_unexplained == 0
    assert result.flag_close_us == ()
    assert result.flag_first_bar is False
    assert result.flag_last_bar is False


def test_a_day_is_not_final_until_both_neighbours_are_known() -> None:
    file = trades([(DAY_START + 30 * SECOND, 2.0)])
    official = official_from([(0, 2.0, 2.0)])
    result = check(file, official, previous=None, following=None)
    assert result.status == "pass"
    assert result.needs_previous_day is True
    assert result.needs_next_day is True


def test_volume_straddling_midnight_is_explained_when_the_next_day_took_it_in() -> None:
    # An aggregate of 5.0 stamped 25 ms before midnight, 4.5 of it counted in the next day's candles.
    stamp = DAY_END - 25_000
    file = trades([(DAY_START + 30 * SECOND, 1.0), (stamp, 5.0)])
    official = official_from([(0, 1.0, 1.0), (1439, 0.5, 0.5)])
    result = check(file, official, following=DayFlow(4.5, 0.0, 4.5, 0.0))
    assert result.status == "pass"
    assert result.volume_diff == 4.5
    assert result.taker_buy_diff == 4.5
    assert result.carry_out == 4.5
    assert result.carry_out_buy == 4.5
    assert result.volume_explainable_up == 5.0
    assert result.largest_window_needed_ms == 25.0


def test_b_invented_volume_at_the_end_of_a_day_fails_on_the_next_days_carry() -> None:
    """F-04 row B. The window that excuses the trade contains the trade, so only the next day can tell."""
    file = trades([(DAY_END - 100_000, 4.0)])
    result = check(file, official_from([]), following=QUIET)
    assert result.status == "fail"
    assert result.flag_last_bar is True
    assert result.flag_first_bar is False
    assert result.flag_close_us == ()
    assert any("not explained by midnight" in reason for reason in result.reasons)


def test_a2_a_lost_trade_at_the_start_of_a_day_fails_on_the_previous_days_carry() -> None:
    """F-04 row A2. The previous tail could explain it, but the previous day says it sent nothing."""
    file = trades([(DAY_START + 90 * SECOND, 1.0)])
    official = official_from([(0, 3.0, 3.0), (1, 1.0, 1.0)])
    tail = trades([(DAY_START - 10_000, 5.0)])
    result = check(file, official, tail=tail, previous=QUIET)
    assert result.status == "fail"
    assert result.carry_in == 3.0
    assert result.flag_first_bar is True
    assert result.flag_close_us == ()
    assert any("not explained by midnight" in reason for reason in result.reasons)


def test_a_carry_the_previous_day_did_send_passes() -> None:
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    official = official_from([(0, 1.25, 1.25)])
    tail = trades([(DAY_START - 40_000, 0.75)])
    result = check(file, official, tail=tail, previous=DayFlow(0.0, 0.25, 0.0, 0.25))
    assert result.status == "pass"
    assert result.volume_diff == -0.25
    assert result.carry_in == 0.25
    assert result.volume_explainable_down == 0.75


def test_a_carry_with_no_previous_day_yet_stays_open() -> None:
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    result = check(file, official_from([(0, 1.25, 1.25)]), previous=None)
    assert result.status == "pass"
    assert result.needs_previous_day is True


def test_k_the_first_day_of_a_dataset_cannot_stay_open_for_good() -> None:
    """F-04 row K. No previous file will ever arrive, so an unconfirmed carry warns and flags the first
    bar."""
    file = trades([(DAY_START + 90 * SECOND, 1.0)])
    official = official_from([(0, 3.0, 3.0), (1, 1.0, 1.0)])
    result = check(file, official, previous=None, first_day=True)
    assert result.status == "warn"
    assert result.needs_previous_day is False
    assert result.flag_first_bar is True


def test_a_clean_first_day_of_a_dataset_passes() -> None:
    file = trades([(DAY_START + 30 * SECOND, 2.0)])
    result = check(file, official_from([(0, 2.0, 2.0)]), previous=None, first_day=True)
    assert result.status == "pass"
    assert result.needs_previous_day is False


def test_a_deficit_that_first_appears_later_in_the_day_fails_whatever_the_neighbours_say() -> None:
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    result = check(file, official_from([(0, 1.0, 1.0), (700, 5.0, 5.0)]), previous=None, following=None)
    assert result.status == "fail"
    assert result.volume_diff == -5.0
    # A deficit that never closes is bad at every boundary from its own minute on.
    assert result.flag_close_us[0] == DAY_START + 701 * MINUTE
    assert result.flag_close_us[-1] == DAY_END
    assert len(result.flag_close_us) == 740


def test_c2_invented_volume_at_noon_fails_from_its_own_minute() -> None:
    """F-04 row C2. This used to be only a warning, and the day became final."""
    noon = DAY_START + 720 * MINUTE
    file = trades([(noon + 30 * SECOND, 4.0)], buy=False)
    result = check(file, official_from([]))
    assert result.status == "fail"
    assert result.flag_close_us[0] == noon + MINUTE
    assert len(result.flag_close_us) == 720
    assert result.boundaries_unexplained == 720


def test_e2_hours_stamped_early_fail() -> None:
    """F-04 row E2. Totals match, and each row is 40 s early, far more than a fill can run on."""
    rows = [(DAY_START + m * MINUTE + 10 * SECOND, 1.0) for m in range(600, 780)]
    official = official_from([(m + 1, 1.0, 1.0) for m in range(600, 780)])
    early = [(stamp - 40 * SECOND + MINUTE, qty) for stamp, qty in rows]
    # Each row belongs in minute m + 1 by the candles, and is stamped in minute m.
    result = check(trades(early), official)
    assert result.status == "fail"
    # The hours that break are flagged, and the day after them, which adds up again, is not.
    assert result.flag_close_us[0] == DAY_START + 601 * MINUTE
    assert result.flag_close_us[-1] == DAY_START + 780 * MINUTE
    assert len(result.flag_close_us) == 180


def test_d_taker_side_flipped_for_two_hours_fails_though_the_totals_match() -> None:
    """F-04 row D. Only daily taker totals used to be compared, and these net to zero."""
    truth = [(m, 1.0, 1.0 if m < 120 else 0.0) for m in range(240)]
    official = official_from(truth)
    rows = []
    for minute, qty, buy in truth:
        flipped = 60 <= minute < 180
        rows.append((DAY_START + minute * MINUTE + 30 * SECOND, 100.0, qty, (buy > 0) != flipped))
    file = trades_frame(rows)
    result = check(file, official)
    assert result.taker_buy_diff == 0.0
    assert result.status == "fail"
    assert result.boundaries_unexplained == 0
    assert result.boundaries_unexplained_buy > 0
    assert result.flag_close_us[0] == DAY_START + 61 * MINUTE
    assert result.flag_close_us[-1] == DAY_START + 179 * MINUTE


def test_f_a_slipped_digit_in_the_last_price_fails_and_flags_only_that_bar() -> None:
    """F-04 row F. This used to warn, and the day reached the published statistics."""
    file = trades_frame(
        [
            (DAY_START + 30 * SECOND, 100.0, 1.0, True),
            (DAY_END - 30 * SECOND, 1000.0, 1.0, True),
        ]
    )
    result = check(file, official_from([(0, 1.0, 1.0), (1439, 1.0, 1.0)]))
    assert result.status == "fail"
    assert result.bars_price_over_tolerance == 1
    assert result.flag_close_us == (DAY_END,)


def test_price_tolerance_is_relative_so_it_means_the_same_at_any_price() -> None:
    file = trades_frame([(DAY_START + 30 * SECOND, 101.0, 1.0, True)])
    assert check(file, official_from([(0, 1.0, 1.0)])).status == "pass"
    wide = trades_frame([(DAY_START + 30 * SECOND, 103.0, 1.0, True)])
    result = check(wide, official_from([(0, 1.0, 1.0)]))
    assert result.status == "fail"
    assert result.max_bar_price_diff_rel == 0.03


def test_a_carry_larger_than_the_previous_tail_is_an_error() -> None:
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    official = official_from([(0, 2.0, 2.0)])
    result = check(file, official, tail=trades([(DAY_START - 40_000, 0.5)]), previous=None)
    assert result.status == "fail"
    assert result.flag_first_bar is True


def test_a_previous_tail_outside_the_window_explains_nothing() -> None:
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    official = official_from([(0, 1.5, 1.5)])
    result = check(file, official, tail=trades([(DAY_START - 5 * SECOND, 5.0)]), previous=None)
    assert result.status == "fail"


def test_a_minute_boundary_straddle_is_explained() -> None:
    # 2.0 stamped 50 ms before 00:01, officially counted after it.
    file = trades([(DAY_START + MINUTE - 50_000, 2.0)])
    result = check(file, official_from([(1, 2.0, 2.0)]))
    assert result.status == "pass"
    assert result.boundaries_unexplained == 0
    assert result.max_bar_volume_diff == 2.0
    assert result.bars_volume_diff_over_0_001 == 2
    assert result.largest_window_needed_ms == 50.0


def test_a_shift_too_wide_to_be_a_straddle_fails() -> None:
    # 2.0 stamped 30 s before 00:01 but officially counted after it.
    file = trades([(DAY_START + MINUTE - 30 * SECOND, 2.0)])
    result = check(file, official_from([(1, 2.0, 2.0)]))
    assert result.status == "fail"
    assert result.boundaries_unexplained == 1
    assert result.flag_close_us == (DAY_START + MINUTE,)


def test_taker_buy_mismatch_alone_is_an_error() -> None:
    file = trades([(DAY_START + 30 * SECOND, 2.0)])
    result = check(file, official_from([(0, 2.0, 1.0)]))
    assert result.status == "fail"
    assert result.taker_buy_diff == 1.0


def test_a_fill_count_far_from_official_warns() -> None:
    file = trades([(DAY_START + 30 * SECOND, 2.0)])
    result = check(file, official_from([(0, 2.0, 2.0)], count=1))
    assert result.official_count == 1440
    assert result.status == "warn"
    assert any("fill count" in reason for reason in result.reasons)


def test_empty_minutes_are_not_compared_on_price() -> None:
    """Our no-trade minute has null prices. It must not count as a price difference."""
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    result = check(file, official_from([(0, 1.0, 1.0)]))
    assert result.max_bar_price_diff == 0.0


def test_a_minutes_standing_never_depends_on_what_came_later_in_the_day() -> None:
    """The flag starts at the first bad boundary, whatever follows. So earlier minutes cannot depend on later
    data."""
    first_error = trades([(DAY_START + 700 * MINUTE + 30 * SECOND, 3.0)])
    both_errors = trades(
        [(DAY_START + 700 * MINUTE + 30 * SECOND, 3.0), (DAY_START + 1000 * MINUTE + 30 * SECOND, 9.0)]
    )
    official = official_from([])
    first = check(first_error, official)
    both = check(both_errors, official)
    assert first.flag_close_us[0] == both.flag_close_us[0] == DAY_START + 701 * MINUTE
    # A later fault cannot change the standing of any boundary before it.
    cut = DAY_START + 1000 * MINUTE
    assert [c for c in first.flag_close_us if c <= cut] == [c for c in both.flag_close_us if c <= cut]


def test_a_spill_past_the_window_fails_and_a_wider_window_is_a_different_declared_rule() -> None:
    """The window decides which days pass, so it is a declared constant and a change is a counted trial."""
    file = trades([(DAY_START + MINUTE - 300_000, 5.0)]).with_columns(
        pl.lit(2, dtype=pl.Int32).alias("n_fills")
    )
    official = official_from([(0, 3.0, 3.0), (1, 2.0, 2.0)])
    narrow = check(file, official)
    assert narrow.status == "fail"
    # The check reports how long the row must have run even when that is what failed it, or a row longer than
    # the window could never show.
    assert narrow.largest_window_needed_ms == 300.0
    result = reconcile_official(
        file,
        day_bars(file),
        official,
        TOLERANCE,
        window_ms=500.0,
        previous_tail=None,
        previous_flow=QUIET,
        next_flow=QUIET,
        is_first_day=False,
    )
    assert result.status == "pass"
    assert result.largest_window_needed_ms == 300.0


def test_a_broken_days_far_midnight_figure_is_marked_and_a_neighbour_does_not_fail_on_it() -> None:
    """A deficit of 5 at noon leaves a figure of -5 at midnight. That is not volume crossing midnight."""
    file = trades([(DAY_START + 30 * SECOND, 1.0)])
    broken = check(file, official_from([(0, 1.0, 1.0), (700, 5.0, 5.0)]))
    assert broken.carry_out_reliable is False
    flow = DayFlow.from_detail(broken.to_dict())
    assert flow.carry_out_reliable is False
    clean = trades([(DAY_START + 30 * SECOND, 2.0)])
    neighbour = check(clean, official_from([(0, 2.0, 2.0)]), previous=flow)
    assert neighbour.status == "pass"
    assert neighbour.needs_previous_day is False


def test_a_carry_that_a_broken_neighbour_cannot_vouch_for_warns() -> None:
    broken = DayFlow(0.0, -5.0, 0.0, -5.0, carry_in_reliable=False, carry_out_reliable=False)
    file = trades([(DAY_START + 90 * SECOND, 1.0)])
    result = check(file, official_from([(0, 3.0, 3.0), (1, 1.0, 1.0)]), previous=broken)
    assert result.status == "warn"
    assert result.flag_first_bar is True
    going = trades([(DAY_END - 100_000, 4.0)])
    out = check(going, official_from([]), following=broken)
    assert out.status == "warn"
    assert out.flag_last_bar is True


def test_the_day_flow_comes_back_from_what_is_stored() -> None:
    file = trades([(DAY_END - 25_000, 5.0)])
    official = official_from([(1439, 0.5, 0.5)])
    result = check(file, official, following=DayFlow(4.5, 0.0, 4.5, 0.0))
    assert DayFlow.from_detail(result.to_dict()) == DayFlow(0.0, 4.5, 0.0, 4.5)


def test_dr04_a_fault_at_noon_does_not_reach_back_across_the_midnight_before_it() -> None:
    """DR-04. A carry in is known at the first boundary, so a break ten hours later says nothing about it.

    Day one sent 0.5 over midnight. Day two took exactly that and then broke at noon. Day one's last bar must
    stand, and day two's own carry stays readable.
    """
    day_two_start = DAY_END
    day_two = trades([(day_two_start + 30 * SECOND, 1.0)])
    stamps = [day_two_start + m * MINUTE for m in range(1440)]
    official_two = official_from([]).with_columns(
        pl.Series("open_time", stamps, dtype=pl.Int64).cast(UTC_TIME),
        pl.Series("volume", [1.5 if m == 0 else 5.0 if m == 720 else 0.0 for m in range(1440)]),
        pl.Series("taker_buy_volume", [1.5 if m == 0 else 5.0 if m == 720 else 0.0 for m in range(1440)]),
    )
    bars_two = build_bars_1m(
        day_two,
        venue="generated",
        symbol="BTCUSDT",
        first_close_us=day_two_start + MINUTE,
        last_close_us=day_two_start + DAY,
        continuity="none",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    broken = reconcile_official(
        day_two,
        bars_two,
        official_two,
        TOLERANCE,
        window_ms=WINDOW_MS,
        previous_tail=None,
        previous_flow=None,
        next_flow=QUIET,
        is_first_day=False,
    )
    assert broken.status == "fail"
    assert broken.carry_in == 0.5
    assert broken.carry_in_reliable is True
    assert broken.carry_out_reliable is False
    flow = DayFlow.from_detail(broken.to_dict())

    day_one = trades([(DAY_END - 100_000, 2.0)])
    result = check(day_one, official_from([(1439, 1.5, 1.5)]), following=flow)
    assert result.carry_out == 0.5
    assert result.status == "pass"
    assert result.flag_last_bar is False
    assert result.unconfirmed_next is False


def test_dr04_a_fault_at_the_first_boundary_does_leave_the_carry_unconfirmed() -> None:
    """The other side of the split: when the first boundary itself is bad, nobody can vouch for that
    midnight."""
    # 9.0 stamped 30 s into the day, counted in no candle: bad at the first boundary, so not a carry at all.
    broken_day = trades([(DAY_START + 30 * SECOND, 9.0)])
    broken = check(broken_day, official_from([]))
    assert broken.carry_in_reliable is False
    day_before = trades([(DAY_START - 100_000, 2.0)])
    stamps = [DAY_START - DAY + m * MINUTE for m in range(1440)]
    official_before = official_from([]).with_columns(
        pl.Series("open_time", stamps, dtype=pl.Int64).cast(UTC_TIME),
        pl.Series("volume", [1.5 if m == 1439 else 0.0 for m in range(1440)]),
        pl.Series("taker_buy_volume", [1.5 if m == 1439 else 0.0 for m in range(1440)]),
    )
    bars_before = build_bars_1m(
        day_before,
        venue="generated",
        symbol="BTCUSDT",
        first_close_us=DAY_START - DAY + MINUTE,
        last_close_us=DAY_START,
        continuity="none",
        fill_span_allowance_us=0,
        received_at_us=None,
    )
    result = reconcile_official(
        day_before,
        bars_before,
        official_before,
        TOLERANCE,
        window_ms=WINDOW_MS,
        previous_tail=None,
        previous_flow=QUIET,
        next_flow=DayFlow.from_detail(broken.to_dict()),
        is_first_day=False,
    )
    assert result.status == "warn"
    assert result.flag_last_bar is True
    assert result.unconfirmed_next is True


def test_dr05_one_long_row_flags_only_its_own_boundary_and_the_next_minute_stands() -> None:
    """DR-05. One aggregate that ran past the window used to flag every bar until midnight."""
    file = trades([(DAY_START + MINUTE - 300_000, 5.0), (DAY_START + 90 * SECOND, 1.0)])
    result = check(file, official_from([(0, 3.0, 3.0), (1, 3.0, 3.0)]))
    assert result.status == "fail"
    assert result.flag_close_us == (DAY_START + MINUTE,)
    assert result.boundaries_unexplained == 1


def test_dr05_a_failing_day_flags_a_price_bar_and_a_broken_boundary_together() -> None:
    file = trades_frame(
        [
            (DAY_START + MINUTE - 300_000, 100.0, 5.0, True),
            (DAY_END - 30 * SECOND, 1000.0, 1.0, True),
        ]
    )
    result = check(file, official_from([(0, 3.0, 3.0), (1, 2.0, 2.0), (1439, 1.0, 1.0)]))
    assert result.flag_close_us == (DAY_START + MINUTE, DAY_END)


# ---- other comparisons
# --------------------------------------------------------------------------------------


def _bars(
    volume: list[float],
    close: list[float | None],
    *,
    venue: str = "generated",
    count: list[int] | None = None,
) -> pl.DataFrame:
    stamps = [DAY_START + (i + 1) * MINUTE for i in range(len(volume))]
    return pl.DataFrame(
        {
            "venue": [venue] * len(volume),
            "close_time": pl.Series(stamps, dtype=pl.Int64).cast(UTC_TIME),
            "volume": volume,
            "close": close,
            "high": close,
            "low": close,
            "trade_count": count if count is not None else [1 if v else 0 for v in volume],
        }
    )


def test_rebuild_finds_a_late_trade() -> None:
    emitted = _bars([1.0, 0.0], [10.0, None])
    rebuilt = _bars([1.0, 2.0], [10.0, 11.0])
    result = compare_emitted_with_rebuild(emitted, rebuilt)
    assert result["status"] == "warn"
    assert result["bars_different"] == 1
    assert result["late_trades"] == 1


def test_a_rebuild_has_nothing_to_say_about_bars_that_were_themselves_rebuilt() -> None:
    emitted = _bars([1.0], [10.0]).with_columns(pl.lit("rebuild").alias("emission"))
    result = compare_emitted_with_rebuild(emitted, _bars([9.0], [10.0]))
    assert result["status"] == "not_applicable"


@pytest.mark.parametrize(
    ("archive_volume", "archive_close", "archive_count", "field"),
    [
        ([2.0, 1.0], [10.0, 11.0], [1, 1], "volume"),
        ([1.0, 1.0], [10.0, 12.0], [1, 1], "close"),
        ([1.0, 1.0], [10.0, 11.0], [6, 1], "trade count"),
    ],
)
def test_live_against_the_archive_finds_what_the_poll_never_received(
    archive_volume: list[float], archive_close: list[float | None], archive_count: list[int], field: str
) -> None:
    live = _bars([1.0, 1.0], [10.0, 11.0], count=[1, 1])
    archive = _bars(archive_volume, archive_close, count=archive_count)
    result = compare_live_with_archive(live, archive)
    assert result["status"] == "warn", field
    assert result["bars_different"] == 1


def test_live_against_the_archive_finds_a_lower_low_the_live_run_never_saw() -> None:
    live = _bars([1.0], [10.0])
    archive = _bars([1.0], [10.0]).with_columns(pl.lit(9.0).alias("low"))
    assert compare_live_with_archive(live, archive)["bars_different"] == 1


def test_live_against_the_archive_finds_a_bar_only_one_side_has() -> None:
    live = _bars([1.0], [10.0])
    archive = _bars([1.0, 2.0], [10.0, 11.0])
    assert compare_live_with_archive(live, archive)["bars_different"] == 1


def test_live_against_the_archive_passes_when_they_agree_and_refuses_another_venue() -> None:
    live = _bars([1.0, 0.0], [10.0, None])
    assert compare_live_with_archive(live, _bars([1.0, 0.0], [10.0, None]))["status"] == "pass"
    with pytest.raises(ValueError, match="same venue"):
        compare_live_with_archive(live, _bars([1.0, 0.0], [10.0, None], venue="other"))


def test_cross_venue_refuses_a_same_venue_pair() -> None:
    """A loose sanity check must not stand in for the real comparison."""
    values: list[float | None] = [100.0 + i * 0.1 for i in range(60)]
    with pytest.raises(ValueError, match="same venue"):
        cross_venue_check(
            _bars([1.0] * 60, values),
            _bars([1.0] * 60, values),
            median_bps_warn=30.0,
            min_corr_warn=0.5,
        )


def test_cross_venue_hand_computed() -> None:
    values = [100.0 + i * 0.1 for i in range(60)]
    closes_a: list[float | None] = list(values)
    closes_b: list[float | None] = [value * 1.001 for value in values]  # a constant 10 bps away
    result = cross_venue_check(
        _bars([1.0] * 60, closes_a),
        _bars([1.0] * 60, closes_b, venue="other"),
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert result["status"] == "pass"
    assert round(result["median_abs_close_diff_bps"]) == 10
    assert result["one_minute_return_corr"] > 0.99


def test_cross_venue_warns_on_a_wide_basis_and_on_too_few_bars() -> None:
    values = [100.0 + i * 0.1 for i in range(60)]
    closes: list[float | None] = list(values)
    wide = cross_venue_check(
        _bars([1.0] * 60, closes),
        _bars([1.0] * 60, [c * 1.01 for c in values], venue="other"),
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert wide["status"] == "warn"
    few = cross_venue_check(
        _bars([1.0] * 5, [1.0] * 5),
        _bars([1.0] * 5, [1.0] * 5, venue="other"),
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert few["status"] == "warn"
