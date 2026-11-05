"""Leak tests for bars: truncation invariance and future perturbation, on the paths production uses.

Every test here goes through an explicit grid, as production does, or through `derive_day` or `run_poll`. Cuts
are every minute, or a timeframe's own closes one minute either side, because a leak on one bar in seven lands
on no fixed cut. Data is dense and sparse, because a leak in a silence does not show on data with no silences.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from helpers import MINUTE, base_config, make_context, trades_frame, us, with_sources_enabled
from hft_crypto.bars.core import (
    UTC_TIME,
    aggregate_bars,
    build_bars_1m,
    closes_between,
    visible_bars,
)
from hft_crypto.data.atomic import atomic_write_parquet, read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M, TRADES, derive_day, timeframe_dataset
from hft_crypto.data.fetch import NotPublishedError
from hft_crypto.data.parsers import TRADE_SCHEMA
from hft_crypto.data.poll import BARS_1M_LIVE, KrakenClient, live_dataset, run_poll
from hft_crypto.timeutil import day_start_us

START = us("2026-03-01T00:00:00")
HOURS = 12
CONFIGURED = tuple(base_config().timeframes_minutes)
SHORT_FRAMES = [m for m in CONFIGURED if m <= HOURS * 60]


def random_trades(
    *, seed: int = 7, per_minute: float = 6.0, hours: int = HOURS, allowance_us: int = 0
) -> pl.DataFrame:
    rng = random.Random(seed)
    span = hours * 60 * MINUTE
    count = round(per_minute * hours * 60)
    stamps = {START + rng.randrange(1, span) for _ in range(count)}
    # Some trades sit exactly on boundaries, where a leak would most likely hide.
    stamps |= {START + m * MINUTE for m in range(1, hours * 60, 7)}
    rows = [
        (stamp, 100.0 + rng.uniform(-5, 5), round(rng.uniform(0.001, 3.0), 3), rng.random() < 0.5)
        for stamp in sorted(stamps)
    ]
    return trades_frame(rows, allowance_us=allowance_us)


DENSE = random_trades()
SPARSE = random_trades(seed=11, per_minute=0.2)
DATASETS = [pytest.param(DENSE, id="dense"), pytest.param(SPARSE, id="sparse")]


def before_or_at(trades: pl.DataFrame, cutoff: int) -> pl.DataFrame:
    return trades.filter(pl.col("ts") <= pl.lit(cutoff, dtype=pl.Int64).cast(UTC_TIME))


def bars_1m(trades: pl.DataFrame, *, hours: int = HOURS) -> pl.DataFrame:
    return build_bars_1m(
        trades,
        venue="v",
        symbol="S",
        first_close_us=START + MINUTE,
        last_close_us=START + hours * 60 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=None,
    )


def bars_at(trades: pl.DataFrame, minutes: int, *, hours: int = HOURS) -> pl.DataFrame:
    minute_bars = bars_1m(trades, hours=hours)
    if minutes == 1:
        return minute_bars
    return aggregate_bars(minute_bars, minutes, through_close_us=START + hours * 60 * MINUTE)


def perturb_after(trades: pl.DataFrame, cutoff: int, seed: int) -> pl.DataFrame:
    """Replace everything after the cutoff with noise, with ids that run on from the last row kept."""
    rng = random.Random(seed)
    kept = before_or_at(trades, cutoff)
    last_id = int(kept["trade_id"].to_numpy().max())
    future_stamps = sorted({cutoff + rng.randrange(1, 4 * 60 * MINUTE) for _ in range(500)})
    future = trades_frame(
        [(s, rng.uniform(1, 100000), rng.uniform(0.001, 500.0), rng.random() < 0.5) for s in future_stamps],
        first_id=last_id + 1,
    )
    return pl.concat([kept.select(future.columns), future])


def newest_close(trades: pl.DataFrame, cutoff: int) -> int | None:
    """The close of the minute holding the newest row at or before the cut, or None if there is none."""
    newest = before_or_at(trades, cutoff)["ts"].dt.timestamp("us").max()
    return None if newest is None else (int(str(newest)) - 1) // MINUTE * MINUTE + MINUTE


def assert_truncation_holds(
    full: pl.DataFrame, truncated: pl.DataFrame, cutoff: int, newest: int | None, label: str
) -> None:
    """What is known at a cut must not depend on anything after it.

    Up to the minute holding the newest row at the cut, both views are exactly the same. After it, the
    truncated view knows only that no row has come, so every bar there is flagged. The full view shows no more
    than that: a bar whose standing rests on a later row is not visible yet, and where both show a bar its
    prices and volume are the same, because every row in it is at or before the cut.
    """
    seen_full = visible_bars(full, cutoff)
    seen_truncated = visible_bars(truncated, cutoff)
    if newest is None:
        assert seen_full["volume"].sum() == 0.0, label
        return
    edge = pl.lit(newest, dtype=pl.Int64).cast(UTC_TIME)
    before_full = seen_full.filter(pl.col("close_time") <= edge)
    before_truncated = seen_truncated.filter(pl.col("close_time") <= edge)
    assert before_full.equals(before_truncated), label
    tail_full = seen_full.filter(pl.col("close_time") > edge)
    tail_truncated = seen_truncated.filter(pl.col("close_time") > edge)
    assert tail_truncated["gap"].all(), label
    assert set(tail_full["close_time"].to_list()) <= set(tail_truncated["close_time"].to_list()), label
    both = tail_full.join(tail_truncated, on="close_time", suffix="_t")
    for column in ("open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "trade_count"):
        assert both[column].to_list() == both[f"{column}_t"].to_list(), f"{label} {column}"


@pytest.mark.parametrize("trades", DATASETS)
def test_truncation_invariance_at_every_minute_for_one_minute_bars(trades: pl.DataFrame) -> None:
    """A peek on one bar in seven lands on no fixed cut, and every minute is a cut here."""
    full = bars_1m(trades)
    assert full.height == HOURS * 60
    for step in range(1, HOURS * 60 + 1):
        cutoff = START + step * MINUTE
        assert_truncation_holds(
            full, bars_1m(before_or_at(trades, cutoff)), cutoff, newest_close(trades, cutoff), f"cut {step}"
        )


@pytest.mark.parametrize("trades", DATASETS)
@pytest.mark.parametrize("minutes", SHORT_FRAMES)
def test_truncation_invariance_around_every_close_of_every_configured_timeframe(
    trades: pl.DataFrame, minutes: int
) -> None:
    full = bars_at(trades, minutes)
    closes = range(minutes, HOURS * 60 + 1, minutes)
    for close in closes:
        for offset in (-1, 0, 1):
            cutoff = START + (close + offset) * MINUTE
            truncated = bars_at(before_or_at(trades, cutoff), minutes)
            assert_truncation_holds(
                full, truncated, cutoff, newest_close(trades, cutoff), f"{minutes}m {close}{offset}"
            )


def test_truncation_invariance_on_daily_bars() -> None:
    """A bar of 1440 minutes needs two days of data, which is what let this timeframe go untested."""
    trades = random_trades(seed=3, per_minute=0.5, hours=48)
    full = bars_at(trades, 1440, hours=48)
    assert full.height == 2
    for offset in (-1, 0, 1):
        cutoff = START + (1440 + offset) * MINUTE
        truncated = bars_at(before_or_at(trades, cutoff), 1440, hours=48)
        assert_truncation_holds(full, truncated, cutoff, newest_close(trades, cutoff), f"daily {offset}")


@pytest.mark.parametrize("trades", DATASETS)
def test_truncation_invariance_inside_a_minute(trades: pl.DataFrame) -> None:
    """A cutoff in the middle of a minute must not change any bar that closed before it."""
    cutoff = START + 121 * MINUTE + 12_345_678
    for minutes in (1, *SHORT_FRAMES):
        full = bars_at(trades, minutes)
        truncated = bars_at(before_or_at(trades, cutoff), minutes)
        assert_truncation_holds(full, truncated, cutoff, newest_close(trades, cutoff), f"{minutes}m")


@pytest.mark.parametrize("trades", DATASETS)
@pytest.mark.parametrize("minutes", [1, *SHORT_FRAMES])
@pytest.mark.parametrize("seed", [1, 2])
def test_future_perturbation(trades: pl.DataFrame, minutes: int, seed: int) -> None:
    """Randomising data after t must not change a value knowable at or before t."""
    cutoff = START + 241 * MINUTE
    original = visible_bars(bars_at(trades, minutes), cutoff)
    changed = visible_bars(bars_at(perturb_after(trades, cutoff, seed), minutes), cutoff)
    # Both are truncation views of one past, so what each shows of it agrees exactly.
    newest = newest_close(trades, cutoff)
    assert newest is not None
    edge = pl.lit(newest, dtype=pl.Int64).cast(UTC_TIME)
    assert original.filter(pl.col("close_time") <= edge).equals(changed.filter(pl.col("close_time") <= edge))


def test_a_perturbation_at_or_before_t_is_detected() -> None:
    """Guard against a vacuous test: changing past data must change the visible bars."""
    cutoff = START + 241 * MINUTE
    original = visible_bars(bars_at(DENSE, 1), cutoff)
    changed_trades = DENSE.with_columns(
        pl.when(pl.col("trade_id") == 5).then(pl.col("price") * 2).otherwise(pl.col("price")).alias("price")
    )
    changed = visible_bars(bars_at(changed_trades, 1), cutoff)
    assert not original.equals(changed)


@pytest.mark.parametrize("minutes", SHORT_FRAMES)
def test_higher_timeframe_never_visible_before_it_closes(minutes: int) -> None:
    minute_bars = bars_1m(DENSE)
    width = minutes * MINUTE
    # Walk one minute at a time through the first two higher bars, feeding only what has happened.
    for step in range(1, min(2 * minutes, HOURS * 60) + 1):
        moment = START + step * MINUTE
        seen = aggregate_bars(visible_bars(minute_bars, moment), minutes, through_close_us=moment)
        closes = seen["close_time"].dt.timestamp("us").to_list()
        assert closes == [START + width * k for k in range(1, step // minutes + 1)]
        assert all(close <= moment for close in closes)


@pytest.mark.parametrize("minutes", SHORT_FRAMES)
def test_a_bar_built_as_time_passes_equals_the_one_built_afterwards(minutes: int) -> None:
    """Repaint test, on every configured timeframe: once closed, a higher bar is the same whenever
    computed."""
    minute_bars = bars_1m(DENSE)
    final = aggregate_bars(minute_bars, minutes, through_close_us=START + HOURS * 60 * MINUTE)
    assert final.height > 0
    for row_index in range(final.height):
        close = int(final["close_time"].dt.timestamp("us")[row_index])
        known = int(final["knowable_time"].dt.timestamp("us")[row_index])
        at_that_moment = aggregate_bars(visible_bars(minute_bars, known), minutes, through_close_us=close)
        assert at_that_moment.row(row_index) == final.row(row_index)


@pytest.mark.parametrize("trades", DATASETS)
def test_knowable_time_is_never_before_the_close(trades: pl.DataFrame) -> None:
    for minutes in (1, *SHORT_FRAMES):
        bars = bars_at(trades, minutes)
        assert (bars["knowable_time"] >= bars["close_time"]).all()


def test_a_trade_cannot_change_the_bar_before_its_own(tmp_path: Path) -> None:
    """A direct probe for a close peeking one minute ahead, on every bar and on one bar in seven."""
    base = bars_1m(DENSE)
    for minute in range(HOURS * 60 - 1):
        changed = DENSE.with_columns(
            pl.when(
                (pl.col("ts") > pl.lit(START + (minute + 1) * MINUTE, dtype=pl.Int64).cast(UTC_TIME))
                & (pl.col("ts") <= pl.lit(START + (minute + 2) * MINUTE, dtype=pl.Int64).cast(UTC_TIME))
            )
            .then(pl.col("price") * 3)
            .otherwise(pl.col("price"))
            .alias("price")
        )
        rebuilt = bars_1m(changed)
        assert rebuilt.slice(0, minute + 1).equals(base.slice(0, minute + 1)), f"minute {minute}"
        if minute > 40:
            return


def test_polled_bars_are_invisible_until_they_were_received() -> None:
    """On the poll path a bar closed at 12:01 may only reach us at 13:23, and is unknowable before."""
    close = us("2026-03-01T12:01:00")
    received = us("2026-03-01T13:23:00")
    bars = build_bars_1m(
        trades_frame([(close - 5, 1.0, 1.0, True)]),
        venue="v",
        symbol="S",
        first_close_us=close,
        last_close_us=close,
        continuity="trade_id",
        fill_span_allowance_us=0,
        received_at_us=received,
    )
    assert visible_bars(bars, close).is_empty()
    assert visible_bars(bars, received - 1).is_empty()
    assert visible_bars(bars, received).height == 1


# ---- what had printed by the close: a generator at the level of fills
# ------------------------------------------


def fills_to_rows(fills: list[tuple[int, float, bool, int]], allowance_us: int) -> pl.DataFrame:
    """Aggregate rows from (stamp, qty, taker buy, order id). A row takes its first fill's stamp, as
    delivered."""
    rows: dict[int, list[tuple[int, float, bool, int]]] = {}
    for fill in fills:
        rows.setdefault(fill[3], []).append(fill)
    ordered = sorted(rows.values(), key=lambda group: group[0][0])
    return trades_frame(
        [(group[0][0], 100.0, sum(fill[1] for fill in group), group[0][2]) for group in ordered],
        allowance_us=allowance_us,
    ).with_columns(pl.Series("n_fills", [len(group) for group in ordered], dtype=pl.Int32))


def _dc03_bars(late_qty: float, allowance_us: int) -> pl.DataFrame:
    """The audit's scenario. Order 2 fills 1.5 at 11:59:59.950, and more at 12:00:00.046."""
    close = us("2026-03-01T12:00:00")
    fills = [
        (close - 30_000_000, 10.0, True, 1),
        (close - 50_000, 1.5, True, 2),
        (close + 46_000, late_qty, True, 2),
    ]
    return build_bars_1m(
        fills_to_rows(fills, allowance_us),
        venue="v",
        symbol="S",
        first_close_us=close,
        last_close_us=close + MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=allowance_us,
        received_at_us=None,
    )


def test_a_fill_after_the_close_cannot_change_what_ideal_reads_at_that_close() -> None:
    """DC-03. This is the future perturbation no row-level test could see: the row is all they are given."""
    allowance_us = 250_000
    one = _dc03_bars(1.5, allowance_us)
    other = _dc03_bars(9.0, allowance_us)
    # The plain column moves, and that is why nothing may read it at the close.
    assert one["buy_volume"][0] == 13.0
    assert other["buy_volume"][0] != one["buy_volume"][0]
    # What IDEAL reads does not.
    assert one["settled_buy_volume"][0] == other["settled_buy_volume"][0] == 10.0


def test_a_plain_volume_that_could_hold_a_later_fill_is_not_known_at_the_close() -> None:
    """DC-03. A value with a later fill in it was visible at 12:00:00.000, knowable 12:00:00.000."""
    allowance_us = 250_000
    close = us("2026-03-01T12:00:00")
    bars = _dc03_bars(1.5, allowance_us)
    assert visible_bars(bars, close).is_empty()
    assert visible_bars(bars, close + allowance_us).height >= 1


# ---- derive_day: the same, on the path archive data takes
# -------------------------------------------------------


def _generated_context(path: Path, now: dt.datetime) -> JobContext:
    config = with_sources_enabled(base_config())
    datasets = tuple(spec for spec in config.datasets if spec.curated != "candles_official")
    return make_context(path, now=now, config=replace(config, datasets=datasets, symbols=("S",)))


def _store_trades(ctx: JobContext, trades: pl.DataFrame, day: dt.date) -> None:
    frame = trades.with_columns(
        pl.lit("generated").alias("venue"),
        pl.lit("S").alias("symbol"),
        pl.lit(False).alias("is_rpi"),
    ).select(list(TRADE_SCHEMA))
    atomic_write_parquet(ctx.root.curated_part(TRADES, "generated", "S", day), frame, guard=ctx.root.guard)


def _derive(path: Path, trades: pl.DataFrame, day: dt.date) -> dict[str, pl.DataFrame]:
    ctx = _generated_context(path, dt.datetime(2026, 3, 3, tzinfo=dt.UTC))
    _store_trades(ctx, trades, day)
    derive_day(ctx, "generated", "S", day)
    found = {
        name: read_parquet(ctx.root.curated_part(name, "generated", "S", day))
        for name in (BARS_1M, *[timeframe_dataset(m) for m in ctx.config.timeframes_minutes])
    }
    ctx.catalog.close()
    return found


def _allowance() -> int:
    return with_sources_enabled(base_config()).source("generated").fill_span_allowance_us


@pytest.mark.parametrize("data", DATASETS)
def test_derive_day_truncation_invariance_on_every_dataset(tmp_path: Path, data: pl.DataFrame) -> None:
    """A close peek placed only in derive_day shows here, and nowhere else in the suite would by design."""
    allowance = _allowance()
    day = dt.date(2026, 3, 1)
    trades = data.with_columns(
        (pl.col("ts").dt.timestamp("us") + allowance).cast(UTC_TIME).alias("knowable_time")
    )
    full = _derive(tmp_path / "full", trades, day)
    # Consecutive minutes, so a peek on one bar in seven cannot miss, and the closes of the larger timeframes.
    cuts = [START + (240 + step) * MINUTE for step in range(8)]
    cuts += [START + 120 * MINUTE, START + 480 * MINUTE, START + 720 * MINUTE]
    for index, cutoff in enumerate(cuts):
        as_of = cutoff + allowance
        truncated = _derive(tmp_path / f"cut{index}", before_or_at(trades, cutoff), day)
        for name, bars in full.items():
            assert_truncation_holds(
                bars, truncated[name], as_of, newest_close(trades, cutoff), f"{name} at {cutoff}"
            )


@pytest.mark.parametrize("seed", [1, 2])
def test_derive_day_future_perturbation(tmp_path: Path, seed: int) -> None:
    allowance = _allowance()
    day = dt.date(2026, 3, 1)
    trades = DENSE.with_columns(
        (pl.col("ts").dt.timestamp("us") + allowance).cast(UTC_TIME).alias("knowable_time")
    )
    cutoff = START + 241 * MINUTE
    noise = perturb_after(DENSE, cutoff, seed).with_columns(
        (pl.col("ts").dt.timestamp("us") + allowance).cast(UTC_TIME).alias("knowable_time"),
    )
    one = _derive(tmp_path / "one", trades, day)
    two = _derive(tmp_path / "two", noise, day)
    newest = newest_close(trades, cutoff)
    assert newest is not None
    edge = pl.lit(newest, dtype=pl.Int64).cast(UTC_TIME)
    for name in one:
        left = visible_bars(one[name], cutoff + allowance).filter(pl.col("close_time") <= edge)
        right = visible_bars(two[name], cutoff + allowance).filter(pl.col("close_time") <= edge)
        assert left.equals(right), name


def test_a_quiet_stretch_cannot_reach_back_into_the_bar_before_it(tmp_path: Path) -> None:
    """How long a silence lasts is known only when it ends, so it must not flag the last bar before it."""
    allowance = _allowance()
    day = dt.date(2026, 3, 1)
    rows = trades_frame(
        [(START + 5 * MINUTE - 1000, 100.0, 1.0, True), (START + 60 * MINUTE, 100.0, 1.0, True)],
        allowance_us=allowance,
    )
    with_silence = _derive(tmp_path / "a", rows, day)[BARS_1M]
    before = with_silence.filter(pl.col("close_time").dt.timestamp("us") == START + 5 * MINUTE)
    assert before["gap"].to_list() == [False]
    assert with_silence.filter(pl.col("close_time").dt.timestamp("us") == START + 6 * MINUTE)[
        "gap"
    ].to_list() == [True]
    assert closes_between(START + 1, START + 1) == {START + MINUTE}


# ---- run_poll: the same, on the path a live run takes
# -----------------------------------------------------------


class _Feed:
    """A source that can only say what has happened by the time it is asked."""

    def __init__(self, rows: list[list[Any]], clock: dict[str, int]) -> None:
        self.rows = rows
        self.clock = clock

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        since_us = int(query["since"]) // 1000
        page = []
        for row in self.rows:
            whole, _, fraction = str(row[2]).partition(".")
            stamp = int(whole) * 1_000_000 + int(fraction)
            if since_us <= stamp <= self.clock["now"]:
                page.append(row)
            if len(page) == 1000:
                break
        last = since_us * 1000
        if page:
            whole, _, fraction = str(page[-1][2]).partition(".")
            last = (int(whole) * 1_000_000 + int(fraction)) * 1000
        return json.dumps({"error": [], "result": {"XXBTZUSD": page, "last": str(last)}}).encode()

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        raise NotPublishedError(url)


def _feed_rows(*, seed: int, hours: int, per_minute: float = 2.0) -> list[list[Any]]:
    rng = random.Random(seed)
    stamps = sorted(
        {START + rng.randrange(1, hours * 60 * MINUTE) for _ in range(round(hours * 60 * per_minute))}
    )
    return [
        [
            f"{100.0 + rng.uniform(-5, 5):.5f}",
            f"{rng.uniform(0.01, 3.0):.8f}",
            f"{stamp // 1_000_000}.{stamp % 1_000_000:06d}",
            "b" if rng.random() < 0.5 else "s",
            "l",
            "",
            1000 + index,
        ]
        for index, stamp in enumerate(stamps)
    ]


def _poll_config() -> Any:
    config = base_config()
    poll = replace(
        config.poll,
        start_date=dt.date(2026, 3, 1),
        page_size=1000,
        pairs=(config.poll.pairs[0],),
    )
    return with_sources_enabled(replace(config, poll=poll, timeframes_minutes=(5, 15, 30, 60, 120, 240)))


def _run_hours(path: Path, rows: list[list[Any]], hours: range) -> dict[str, pl.DataFrame]:
    clock = {"now": 0}
    feed = _Feed(rows, clock)
    config = _poll_config()
    last: JobContext | None = None
    for hour in hours:
        moment = dt.datetime(2026, 3, 1, hour, 7, 5, tzinfo=dt.UTC)
        clock["now"] = day_start_us(moment.date()) + hour * 3_600_000_000 + 7 * MINUTE + 5_000_000
        ctx = make_context(path, now=moment, config=config)
        ctx.run_id = f"hour-{hour:02d}"
        client = KrakenClient(feed, config.poll, sleep=lambda _: None)
        run_poll(ctx, client)
        last = ctx
    assert last is not None
    symbol = config.poll.pairs[0].symbol
    day = dt.date(2026, 3, 1)
    names = [BARS_1M_LIVE, *[live_dataset(m) for m in config.timeframes_minutes]]
    venue = config.poll.venue
    return {
        name: read_parquet(last.root.curated_part(name, venue, symbol, day))
        for name in names
        if last.root.curated_part(name, venue, symbol, day).is_file()
    }


@pytest.mark.parametrize("stop", [3, 5, 9])
def test_a_later_run_cannot_change_what_earlier_runs_made_known(tmp_path: Path, stop: int) -> None:
    """Real poll runs, hourly. What a run at hour N made known is the same with or without any later run."""
    rows = _feed_rows(seed=5, hours=12)
    full = _run_hours(tmp_path / "full", rows, range(1, 12))
    stopped = _run_hours(tmp_path / "stopped", rows, range(1, stop + 1))
    as_of = us(f"2026-03-01T{stop:02d}:07:05")
    assert visible_bars(stopped[BARS_1M_LIVE], as_of).height > 0
    for name, bars in stopped.items():
        assert visible_bars(full[name], as_of).equals(visible_bars(bars, as_of)), name


@pytest.mark.parametrize("seed", [21, 22, 23])
def test_scrambling_the_future_of_the_feed_changes_nothing_already_known(tmp_path: Path, seed: int) -> None:
    rows = _feed_rows(seed=5, hours=12)
    cut = us("2026-03-01T05:07:05")
    kept = [row for row in rows if int(str(row[2]).split(".")[0]) * 1_000_000 <= cut]
    rng = random.Random(seed)
    future = [
        [f"{rng.uniform(1, 100000):.5f}", row[1], row[2], row[3], row[4], row[5], row[6]]
        for row in rows
        if row not in kept
    ]
    original = _run_hours(tmp_path / "a", rows, range(1, 11))
    scrambled = _run_hours(tmp_path / "b", [*kept, *future], range(1, 11))
    for name, bars in original.items():
        assert visible_bars(bars, cut).equals(visible_bars(scrambled[name], cut)), name


def test_no_polled_bar_is_visible_at_its_own_close(tmp_path: Path) -> None:
    rows = _feed_rows(seed=5, hours=4)
    bars = _run_hours(tmp_path / "r", rows, range(1, 4))
    for frame in bars.values():
        if frame.height:
            gaps = frame["knowable_time"].dt.timestamp("us") - frame["close_time"].dt.timestamp("us")
            assert int(str(gaps.min())) > 0


def _a_trade_in_every_minute(hours: int) -> pl.DataFrame:
    """A peek one minute ahead shows only if that minute has a price, and here every minute has its own."""
    rng = random.Random(9)
    return trades_frame(
        [
            (START + minute * MINUTE + 30_000_000, 100.0 + rng.uniform(-5, 5), 1.0, rng.random() < 0.5)
            for minute in range(hours * 60)
        ]
    )


@pytest.mark.parametrize("minutes", CONFIGURED)
def test_a_peek_past_a_higher_bar_shows_on_every_configured_timeframe(minutes: int) -> None:
    """A higher close peeking one minute past its bar passed the old suite on 240m, 30m, 120m and 1440m."""
    trades = _a_trade_in_every_minute(48)
    full = bars_at(trades, minutes, hours=48)
    assert full["complete"][0] is True
    for close in range(minutes, min(1441, 48 * 60), minutes):
        cutoff = START + close * MINUTE
        row = full.filter(pl.col("close_time").dt.timestamp("us") == cutoff)
        truncated = bars_at(before_or_at(trades, cutoff), minutes, hours=48)
        other = truncated.filter(pl.col("close_time").dt.timestamp("us") == cutoff)
        assert row["close"].to_list() == other["close"].to_list(), f"{minutes}m at {close}"
        assert row["high"].to_list() == other["high"].to_list(), f"{minutes}m at {close}"
        if minutes < 60 and close >= 240:
            break
