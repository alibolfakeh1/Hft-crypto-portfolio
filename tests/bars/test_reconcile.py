"""Reconciliation against official candles, on the mechanism measured in real files."""

from __future__ import annotations

import polars as pl
from helpers import DAY, MINUTE, trades_frame, us

from hft_crypto.bars.core import UTC_TIME, build_bars_1m
from hft_crypto.bars.reconcile import (
    compare_emitted_with_rebuild,
    cross_venue_check,
    reconcile_official,
)
from hft_crypto.config import ReconTolerance

DAY_START = us("2026-02-10T00:00:00")
DAY_END = DAY_START + DAY
TOLERANCE = ReconTolerance(daily_total_abs=1e-6, boundary_window_ms=250.0, bar_price_abs=5.0)


def official_from(rows: list[tuple[int, float, float]]) -> pl.DataFrame:
    """Candles from (minute index, volume, taker buy volume). Other minutes are empty."""
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
            "trade_count": [1] * 1440,
        }
    )


def day_bars(trades: pl.DataFrame) -> pl.DataFrame:
    return build_bars_1m(
        trades,
        venue="binance",
        symbol="BTCUSDT",
        first_close_us=DAY_START + MINUTE,
        last_close_us=DAY_END,
    )


def trades(rows: list[tuple[int, float]]) -> pl.DataFrame:
    return trades_frame([(stamp, 100.0, qty, True) for stamp, qty in rows])


def check(file: pl.DataFrame, official: pl.DataFrame, tail: pl.DataFrame | None = None):  # type: ignore[no-untyped-def]
    return reconcile_official(file, day_bars(file), official, TOLERANCE, previous_tail=tail)


def test_identical_day_passes() -> None:
    file = trades([(DAY_START + 30 * 1_000_000, 2.0), (DAY_START + 90 * 1_000_000, 3.0)])
    result = check(file, official_from([(0, 2.0, 2.0), (1, 3.0, 3.0)]))
    assert result.status == "pass"
    assert result.volume_diff == 0.0
    assert result.needs_previous_day is False
    assert result.boundaries_unexplained == 0


def test_volume_straddling_midnight_is_explained_and_passes() -> None:
    # Measured on ETHUSDT 2026-11-03: an aggregate of 9.759 stamped 25 ms before midnight, 9.724 of it
    # counted in the next day's official candles.
    stamp = DAY_END - 25_000
    file = trades([(DAY_START + 30_000_000, 1.0), (stamp, 9.759)])
    official = official_from([(0, 1.0, 1.0), (1439, 0.035, 0.035)])
    result = check(file, official)
    assert result.status == "pass"
    assert result.volume_diff == 9.724
    assert result.taker_buy_diff == 9.724
    assert result.volume_explainable_up == 9.759
    assert result.largest_window_needed_ms == 25.0


def test_a_lost_trade_is_an_error() -> None:
    """The check still catches what it is for: official counted volume our file does not have."""
    file = trades([(DAY_START + 30_000_000, 1.0)])
    official = official_from([(0, 1.0, 1.0), (700, 5.0, 5.0)])
    result = check(file, official, trades([(DAY_START - 10_000, 0.5)]))
    assert result.status == "fail"
    assert result.volume_diff == -5.0
    assert any("below official" in reason for reason in result.reasons)


def test_extra_volume_far_from_midnight_is_an_error() -> None:
    # 3.0 extra in our file, stamped at noon. Nothing near midnight can account for it.
    file = trades([(DAY_START + 43_200_000_000, 3.0), (DAY_END - 60_000_000, 1.0)])
    result = check(file, official_from([(1438, 1.0, 1.0)]))
    assert result.status == "fail"
    assert result.volume_diff == 3.0
    assert any("above official" in reason for reason in result.reasons)


def test_carry_from_the_previous_day_is_explained_by_its_tail() -> None:
    # Measured on BTCUSDT: 2026-11-01 was +0.010 and 2026-11-02 was -0.010, cancelling exactly.
    file = trades([(DAY_START + 30_000_000, 1.0)])
    official = official_from([(0, 1.01, 1.01)])
    tail = trades([(DAY_START - 40_000, 0.137)])
    result = check(file, official, tail)
    assert result.status == "pass"
    assert result.volume_diff == -0.01
    assert result.implied_carry_in == 0.01
    assert result.volume_explainable_down == 0.137
    assert result.needs_previous_day is False


def test_carry_with_no_previous_file_stays_open_instead_of_failing() -> None:
    file = trades([(DAY_START + 30_000_000, 1.0)])
    result = check(file, official_from([(0, 1.01, 1.01)]), None)
    assert result.status == "pass"
    assert result.needs_previous_day is True


def test_carry_larger_than_the_previous_tail_is_an_error() -> None:
    file = trades([(DAY_START + 30_000_000, 1.0)])
    official = official_from([(0, 2.0, 2.0)])
    result = check(file, official, trades([(DAY_START - 40_000, 0.5)]))
    assert result.status == "fail"


def test_previous_tail_outside_the_window_explains_nothing() -> None:
    file = trades([(DAY_START + 30_000_000, 1.0)])
    official = official_from([(0, 1.5, 1.5)])
    result = check(file, official, trades([(DAY_START - 5_000_000, 5.0)]))
    assert result.status == "fail"


def test_minute_boundary_straddle_is_explained_with_no_warning() -> None:
    # 2.0 stamped 50 ms before 00:01, officially counted after it. Daily totals match.
    file = trades([(DAY_START + MINUTE - 50_000, 2.0)])
    result = check(file, official_from([(1, 2.0, 2.0)]))
    assert result.status == "pass"
    assert result.boundaries_unexplained == 0
    assert result.max_bar_volume_diff == 2.0
    assert result.bars_volume_diff_over_0_001 == 2
    assert result.largest_window_needed_ms == 50.0


def test_a_shift_too_wide_to_be_a_straddle_warns() -> None:
    # 2.0 stamped 30 s before 00:01 but officially counted after it. Daily totals match, so not an error.
    file = trades([(DAY_START + MINUTE - 30_000_000, 2.0)])
    result = check(file, official_from([(1, 2.0, 2.0)]))
    assert result.status == "warn"
    assert result.boundaries_unexplained == 1


def test_price_outside_tolerance_warns() -> None:
    file = trades([(DAY_START + 30_000_000, 1.0)])
    official = official_from([(0, 1.0, 1.0)]).with_columns(
        pl.when(pl.col("open_time") == pl.lit(DAY_START, dtype=pl.Int64).cast(UTC_TIME))
        .then(90.0)
        .otherwise(pl.col("open"))
        .alias("open")
    )
    result = check(file, official)
    assert result.status == "warn"
    assert result.bars_price_over_tolerance == 1
    assert result.max_bar_price_diff == 10.0


def test_taker_buy_mismatch_alone_is_an_error() -> None:
    file = trades([(DAY_START + 30_000_000, 2.0)])
    result = check(file, official_from([(0, 2.0, 1.0)]))
    assert result.status == "fail"
    assert result.taker_buy_diff == 1.0


def test_empty_minutes_are_not_compared_on_price() -> None:
    """Our no-trade minute has null prices. It must not count as a price difference."""
    file = trades([(DAY_START + 30_000_000, 1.0)])
    result = check(file, official_from([(0, 1.0, 1.0)]))
    assert result.max_bar_price_diff == 0.0


def _bars(volume: list[float], close: list[float | None]) -> pl.DataFrame:
    stamps = [DAY_START + (i + 1) * MINUTE for i in range(len(volume))]
    return pl.DataFrame(
        {
            "close_time": pl.Series(stamps, dtype=pl.Int64).cast(UTC_TIME),
            "volume": volume,
            "close": close,
            "trade_count": [1 if v else 0 for v in volume],
        }
    )


def test_rebuild_matches_emitted() -> None:
    bars = _bars([1.0, 0.0], [10.0, None])
    result = compare_emitted_with_rebuild(bars, bars)
    assert result["status"] == "pass"
    assert result["bars_different"] == 0


def test_rebuild_finds_a_late_trade() -> None:
    emitted = _bars([1.0, 0.0], [10.0, None])
    rebuilt = _bars([1.0, 2.0], [10.0, 11.0])
    result = compare_emitted_with_rebuild(emitted, rebuilt)
    assert result["status"] == "warn"
    assert result["bars_different"] == 1
    assert result["late_trades"] == 1


def test_cross_venue_hand_computed() -> None:
    closes_a = [100.0 + i * 0.1 for i in range(60)]
    closes_b = [value * 1.001 for value in closes_a]  # a constant 10 bps away
    result = cross_venue_check(
        _bars([1.0] * 60, closes_a),  # type: ignore[arg-type]
        _bars([1.0] * 60, closes_b),  # type: ignore[arg-type]
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert result["status"] == "pass"
    assert round(result["median_abs_close_diff_bps"]) == 10
    assert result["one_minute_return_corr"] > 0.99


def test_cross_venue_warns_on_a_wide_basis_and_on_too_few_bars() -> None:
    closes = [100.0 + i * 0.1 for i in range(60)]
    wide = cross_venue_check(
        _bars([1.0] * 60, closes),  # type: ignore[arg-type]
        _bars([1.0] * 60, [c * 1.01 for c in closes]),  # type: ignore[arg-type]
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert wide["status"] == "warn"
    few = cross_venue_check(
        _bars([1.0] * 5, [1.0] * 5),  # type: ignore[arg-type]
        _bars([1.0] * 5, [1.0] * 5),  # type: ignore[arg-type]
        median_bps_warn=30.0,
        min_corr_warn=0.5,
    )
    assert few["status"] == "warn"
