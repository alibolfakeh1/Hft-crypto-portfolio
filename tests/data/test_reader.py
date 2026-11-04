"""The one way later code reads market data. A strategy or a feature gets frames from here, and holds no
root."""

from __future__ import annotations

import ast
import datetime as dt
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from helpers import MINUTE, REPO_ROOT, base_config, make_context, trades_frame, us, with_sources_enabled
from hft_crypto.bars.core import UTC_TIME, TimingContractError, aggregate_bars, build_bars_1m
from hft_crypto.config import PipelineConfig
from hft_crypto.data.atomic import atomic_write_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M, TRADES
from hft_crypto.data.poll import BARS_1M_LIVE, TRADES_LIVE
from hft_crypto.data.reader import MarketReader, RunClock

DAY = dt.date(2026, 3, 1)
START = us("2026-03-01T00:00:00")
HOUR = 3_600_000_000


def config() -> PipelineConfig:
    return with_sources_enabled(base_config())


def context(path: Path, setup: PipelineConfig | None = None) -> JobContext:
    return make_context(path, now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup or config())


def _rows() -> pl.DataFrame:
    return trades_frame([(START + m * MINUTE + 30_000_000, 100.0 + m, 1.0, True) for m in range(120)])


def _bars(received: int | None, *, venue: str, allowance_us: int = 250_000) -> pl.DataFrame:
    return build_bars_1m(
        _rows().with_columns(
            (pl.col("ts").dt.timestamp("us") + allowance_us).cast(UTC_TIME).alias("knowable_time")
        ),
        venue=venue,
        symbol="S",
        first_close_us=START + MINUTE,
        last_close_us=START + 120 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=allowance_us,
        received_at_us=received,
    )


def _store(ctx: JobContext, dataset: str, venue: str, frame: pl.DataFrame) -> None:
    atomic_write_parquet(ctx.root.curated_part(dataset, venue, "S", DAY), frame, guard=ctx.root.guard)


def test_a_run_gets_the_bars_closed_by_its_cut_and_no_more(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    _store(ctx, BARS_1M, "generated", _bars(None, venue="generated"))
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 60 * MINUTE
    bars = reader.bars(1, "generated", "S", RunClock(t_cut, t_cut + 65_000_000))
    assert bars.height == 60
    assert bars["close_time"].dt.timestamp("us").max() == t_cut


def test_a_polled_bar_this_run_could_not_have_had_raises(tmp_path: Path) -> None:
    """DC-07. Received at 01:07, so a run at 00:30 reading a store that holds it is reading its own future."""
    ctx = context(tmp_path / "r")
    received = START + HOUR + 7 * MINUTE
    _store(ctx, BARS_1M_LIVE, ctx.config.poll.venue, _bars(received, venue=ctx.config.poll.venue))
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 30 * MINUTE
    with pytest.raises(TimingContractError):
        reader.live_bars(1, "S", RunClock(t_cut, t_cut + 65_000_000))
    assert reader.live_bars(1, "S", RunClock(START + HOUR, received)).height == 60


def test_trades_for_a_run_stop_at_the_cut(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    frame = _rows().with_columns(
        pl.lit("generated").alias("venue"), pl.lit("S").alias("symbol"), pl.lit(False).alias("is_rpi")
    )
    _store(ctx, TRADES, "generated", frame)
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 10 * MINUTE
    trades = reader.trades("generated", "S", RunClock(t_cut, t_cut))
    assert trades.height == 10
    late = frame.with_columns(pl.lit(START + HOUR, dtype=pl.Int64).cast(UTC_TIME).alias("knowable_time"))
    _store(ctx, TRADES_LIVE, ctx.config.poll.venue, late)
    with pytest.raises(TimingContractError):
        reader.live_trades("S", RunClock(t_cut, t_cut))


def test_ideal_reads_only_what_had_printed_and_only_on_a_source_that_can_give_it(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    bars = _bars(None, venue="generated")
    _store(ctx, BARS_1M, "generated", bars)
    reader = MarketReader(ctx.root, ctx.config)
    moment = START + 60 * MINUTE
    # Unmeasured, and an allowance nobody measured cannot say what had printed by a close.
    with pytest.raises(TimingContractError, match="IDEAL"):
        reader.ideal_bars(1, "generated", "S", moment)
    measured = replace(ctx.config.source("generated"), allowance_state="measured")
    reader = MarketReader(
        ctx.root, replace(ctx.config, sources={**ctx.config.sources, "generated": measured})
    )
    view = reader.ideal_bars(1, "generated", "S", moment)
    assert view.height == 60
    assert "settled_volume" not in view.columns
    assert view["volume"].to_list() == bars.head(60)["settled_volume"].to_list()
    coarse = replace(
        ctx.config, sources={**ctx.config.sources, "generated": replace(measured, stamp_kind="floored")}
    )
    with pytest.raises(TimingContractError, match="IDEAL"):
        MarketReader(ctx.root, coarse).ideal_bars(1, "generated", "S", moment)


def test_a_higher_timeframe_is_read_the_same_way(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    bars = _bars(None, venue="generated")
    higher = aggregate_bars(bars, 60, through_close_us=START + 120 * MINUTE)
    _store(ctx, "bars_1h", "generated", higher)
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 90 * MINUTE
    assert reader.bars(60, "generated", "S", RunClock(t_cut, t_cut + 65_000_000)).height == 1


def test_a_live_read_refuses_a_dataset_that_is_not_live_eligible(tmp_path: Path) -> None:
    """DC-04. A book row stamped 14:20:30 passed the timestamp audit at a 14:21 run, though a run sees no
    book."""
    ctx = context(tmp_path / "r")
    reader = MarketReader(ctx.root, ctx.config)
    clock = RunClock(START, START)
    with pytest.raises(TimingContractError, match="not eligible"):
        reader.live_dataset("generated.bookDepth", "S", clock)
    with pytest.raises(TimingContractError, match="not eligible"):
        reader.live_dataset("no.such.dataset", "S", clock)
    assert not any(spec.live_eligible for spec in ctx.config.datasets)


def test_a_dataset_marked_eligible_reads_by_its_knowable_time(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    specs = tuple(
        replace(spec, live_eligible=True) if spec.id == "generated.fundingRate" else spec
        for spec in ctx.config.datasets
    )
    setup = replace(ctx.config, datasets=specs)
    frame = pl.DataFrame(
        {
            "knowable_time": pl.Series([START + MINUTE, START + HOUR], dtype=pl.Int64).cast(UTC_TIME),
            "rate": [0.1, 0.2],
        }
    )
    _store(ctx, "funding", "generated", frame)
    clock = RunClock(START + 2 * MINUTE, START + 2 * MINUTE)
    assert MarketReader(ctx.root, setup).live_dataset("generated.fundingRate", "S", clock)[
        "rate"
    ].to_list() == [0.1]


# ---- the import rule: strategy and feature code cannot go around the reader
# ---------------------------------------

FORBIDDEN_READS = {"read_parquet", "scan_parquet", "curated_part", "curated_parts"}
GUARDED_PACKAGES = ("strategies", "features", "decide", "engine")


def direct_reads(path: Path) -> list[str]:
    """Names in one file that read stored data without a run clock."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            found += [alias.name for alias in node.names if alias.name in FORBIDDEN_READS]
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_READS:
            found.append(node.attr)
    return found


def test_the_scanner_finds_what_it_is_looking_for(tmp_path: Path) -> None:
    """Otherwise the next test would pass by finding nothing."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from hft_crypto.data.atomic import read_parquet\n"
        "import polars as pl\n"
        "def f(root):\n"
        "    return pl.scan_parquet('x'), root.curated_parts('a', 'b', 'c')\n",
        encoding="utf-8",
    )
    assert sorted(direct_reads(bad)) == ["curated_parts", "read_parquet", "scan_parquet"]
    good = tmp_path / "good.py"
    good.write_text("from hft_crypto.data.reader import MarketReader\n", encoding="utf-8")
    assert direct_reads(good) == []


def test_strategy_and_feature_code_cannot_read_stored_data_directly() -> None:
    """None of these packages exists yet. The rule is in place for the day one does."""
    root = REPO_ROOT / "src" / "hft_crypto"
    offenders = {
        path.relative_to(root).as_posix(): direct_reads(path)
        for package in GUARDED_PACKAGES
        for path in (root / package).rglob("*.py")
        if direct_reads(path)
    }
    assert offenders == {}
