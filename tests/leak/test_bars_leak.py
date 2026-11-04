"""Leak tests for bars, as the leak auditor demands: truncation invariance and future perturbation."""

from __future__ import annotations

import random

import polars as pl
import pytest
from helpers import MINUTE, trades_frame, us

from hft_crypto.bars.core import UTC_TIME, aggregate_bars, build_bars_1m, visible_bars

START = us("2026-03-01T00:00:00")
TIMEFRAMES = [1, 5, 15, 60, 240]


def random_trades(seed: int = 7, count: int = 3000, hours: int = 8) -> pl.DataFrame:
    rng = random.Random(seed)
    span = hours * 60 * MINUTE
    stamps = sorted(START + rng.randrange(1, span) for _ in range(count))
    # Some trades sit exactly on boundaries, where a leak would most likely hide.
    stamps = sorted(stamps + [START + m * MINUTE for m in range(1, hours * 60, 7)])
    rows = [
        (stamp, 100.0 + rng.uniform(-5, 5), round(rng.uniform(0.001, 3.0), 3), rng.random() < 0.5)
        for stamp in stamps
    ]
    return trades_frame(rows)


def before_or_at(trades: pl.DataFrame, cutoff: int) -> pl.DataFrame:
    return trades.filter(pl.col("ts") <= pl.lit(cutoff, dtype=pl.Int64).cast(UTC_TIME))


def all_bars(trades: pl.DataFrame, minutes: int) -> pl.DataFrame:
    bars = build_bars_1m(trades, venue="v", symbol="S")
    return bars if minutes == 1 else aggregate_bars(bars, minutes)


def perturb_after(trades: pl.DataFrame, cutoff: int, seed: int) -> pl.DataFrame:
    """Replace everything after the cutoff with noise, including a different number of trades."""
    rng = random.Random(seed)
    kept = before_or_at(trades, cutoff)
    future_stamps = sorted(cutoff + rng.randrange(1, 4 * 60 * MINUTE) for _ in range(500))
    future = trades_frame(
        [(s, rng.uniform(1, 100000), rng.uniform(0.001, 500.0), rng.random() < 0.5) for s in future_stamps],
        first_id=10_000_000,
    )
    return pl.concat([kept, future])


@pytest.mark.parametrize("minutes", TIMEFRAMES)
@pytest.mark.parametrize(
    "cutoff_minutes",
    [37, 60, 61, 120, 241, 300, 479],
    ids=lambda m: f"t+{m}m",
)
def test_truncation_invariance(minutes: int, cutoff_minutes: int) -> None:
    """Removing data after t leaves every bar knowable by t unchanged."""
    trades = random_trades()
    cutoff = START + cutoff_minutes * MINUTE
    full = visible_bars(all_bars(trades, minutes), cutoff)
    truncated = visible_bars(all_bars(before_or_at(trades, cutoff), minutes), cutoff)
    assert full.height > 0 or minutes > cutoff_minutes
    assert full.equals(truncated)


@pytest.mark.parametrize("minutes", TIMEFRAMES)
def test_truncation_invariance_inside_a_minute(minutes: int) -> None:
    """A cutoff in the middle of a minute must not change any bar that closed before it."""
    trades = random_trades()
    cutoff = START + 121 * MINUTE + 12_345_678
    full = visible_bars(all_bars(trades, minutes), cutoff)
    truncated = visible_bars(all_bars(before_or_at(trades, cutoff), minutes), cutoff)
    assert full.equals(truncated)


@pytest.mark.parametrize("minutes", TIMEFRAMES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_future_perturbation(minutes: int, seed: int) -> None:
    """Randomising data after t must not change anything knowable at or before t."""
    trades = random_trades()
    cutoff = START + 241 * MINUTE
    original = visible_bars(all_bars(trades, minutes), cutoff)
    changed = visible_bars(all_bars(perturb_after(trades, cutoff, seed), minutes), cutoff)
    assert original.height > 0
    assert original.equals(changed)


def test_a_perturbation_at_or_before_t_is_detected() -> None:
    """Guard against a vacuous test: changing past data must change the visible bars."""
    trades = random_trades()
    cutoff = START + 241 * MINUTE
    original = visible_bars(all_bars(trades, 1), cutoff)
    changed_trades = trades.with_columns(
        pl.when(pl.col("trade_id") == 5).then(pl.col("price") * 2).otherwise(pl.col("price")).alias("price")
    )
    changed = visible_bars(all_bars(changed_trades, 1), cutoff)
    assert not original.equals(changed)


@pytest.mark.parametrize("minutes", [5, 15, 60, 240])
def test_higher_timeframe_never_visible_before_it_closes(minutes: int) -> None:
    trades = random_trades()
    bars_1m = build_bars_1m(trades, venue="v", symbol="S")
    width = minutes * MINUTE
    # Walk one minute at a time through the first two higher bars, feeding only what has happened.
    for step in range(1, 2 * minutes + 1):
        moment = START + step * MINUTE
        seen = aggregate_bars(visible_bars(bars_1m, moment), minutes)
        closes = seen["close_time"].dt.timestamp("us").to_list()
        assert closes == [START + width * k for k in range(1, step // minutes + 1)]
        assert all(close <= moment for close in closes)


@pytest.mark.parametrize("minutes", [5, 15, 60])
def test_a_bar_built_as_time_passes_equals_the_one_built_afterwards(minutes: int) -> None:
    """Repaint test: once closed, a higher bar is the same whenever it is computed."""
    trades = random_trades()
    bars_1m = build_bars_1m(trades, venue="v", symbol="S")
    final = aggregate_bars(bars_1m, minutes)
    for row_index in range(min(6, final.height)):
        close = int(final["close_time"].dt.timestamp("us")[row_index])
        at_that_moment = aggregate_bars(visible_bars(bars_1m, close), minutes)
        assert at_that_moment.row(row_index) == final.row(row_index)


def test_knowable_time_is_never_before_the_close() -> None:
    for minutes in TIMEFRAMES:
        bars = all_bars(random_trades(), minutes)
        assert (bars["knowable_time"] >= bars["close_time"]).all()


def test_polled_bars_are_invisible_until_they_were_received() -> None:
    """On the poll path a bar closed at 12:01 may only reach us at 13:23, and is unknowable before."""
    close = us("2026-03-01T12:01:00")
    received = us("2026-03-01T13:23:00")
    bars = build_bars_1m(
        trades_frame([(close - 5, 1.0, 1.0, True)]),
        venue="v",
        symbol="S",
        knowable_at_us=received,
    )
    assert visible_bars(bars, close).is_empty()
    assert visible_bars(bars, received - 1).is_empty()
    assert visible_bars(bars, received).height == 1
