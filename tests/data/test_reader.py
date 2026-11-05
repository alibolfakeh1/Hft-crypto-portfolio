"""The one way later code reads market data. A strategy or a feature gets frames from here, and holds no
root."""

from __future__ import annotations

import ast
import datetime as dt
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from helpers import (
    FAR_FUTURE,
    MINUTE,
    REPO_ROOT,
    base_config,
    make_context,
    trades_frame,
    us,
    with_binance_enabled,
    with_sources_enabled,
)
from hft_crypto.bars.core import (
    BAR_SCHEMA,
    SOURCE_OFFICIAL,
    UTC_TIME,
    TimingContractError,
    aggregate_bars,
    bars_from_official,
    build_bars_1m,
)
from hft_crypto.config import ConfigError, PipelineConfig
from hft_crypto.data.atomic import atomic_write_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M, TRADES, official_dataset
from hft_crypto.data.parsers import TRADE_SCHEMA
from hft_crypto.data.poll import BARS_1M_LIVE, TRADES_LIVE
from hft_crypto.data.reader import FUNDING_SCHEMA, MarketReader, RunClock, SourceNotApproved

DAY = dt.date(2026, 3, 1)
START = us("2026-03-01T00:00:00")
HOUR = 3_600_000_000


def config() -> PipelineConfig:
    return with_sources_enabled(base_config())


def context(path: Path, setup: PipelineConfig | None = None) -> JobContext:
    return make_context(path, now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup or config())


def _rows() -> pl.DataFrame:
    return trades_frame([(START + m * MINUTE + 30_000_000, 100.0 + m, 1.0, True) for m in range(120)])


IDEAL_TIMEFRAMES = [1, 5, 15, 30, 60, 120, 240, 1440]


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
    measured = replace(ctx.config.source("generated"), allowance_state="measured", allowance_evidence="x")
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


def test_a_live_dataset_reads_by_the_cut_and_not_by_the_decision(tmp_path: Path) -> None:
    """A row knowable after the cut and before the decision is what a live gate must not see."""
    ctx = context(tmp_path / "r")
    specs = tuple(
        replace(spec, live_eligible=True) if spec.id == "generated.fundingRate" else spec
        for spec in ctx.config.datasets
    )
    setup = replace(ctx.config, datasets=specs)
    t_cut = START + 2 * MINUTE
    t_dec = t_cut + 65_000_000
    frame = pl.DataFrame(
        {
            "knowable_time": pl.Series([t_cut, t_cut + 1, t_dec], dtype=pl.Int64).cast(UTC_TIME),
            "rate": [0.1, 0.2, 0.3],
        }
    )
    _store(ctx, "funding", "generated", frame)
    clock = RunClock(t_cut, t_dec)
    assert MarketReader(ctx.root, setup).live_dataset("generated.fundingRate", "S", clock)[
        "rate"
    ].to_list() == [0.1]


# ---- N-08: this source only through its route
# --------------------------------------------------------------------


def _candles(day_start: int = START, *, minutes: int = 1440) -> pl.DataFrame:
    stamps = [day_start + m * MINUTE for m in range(minutes)]
    return pl.DataFrame(
        {
            "open_time": pl.Series(stamps, dtype=pl.Int64).cast(UTC_TIME),
            "open": [100.0] * minutes,
            "high": [101.0] * minutes,
            "low": [99.0] * minutes,
            "close": [100.5] * minutes,
            "volume": [2.0] * minutes,
            "quote_volume": [200.0] * minutes,
            "trade_count": [3] * minutes,
            "taker_buy_volume": [1.0] * minutes,
            "taker_buy_quote_volume": [100.0] * minutes,
        }
    )


def _official_bars(venue: str, day_start: int = START) -> pl.DataFrame:
    return bars_from_official(
        _candles(day_start),
        venue=venue,
        symbol="S",
        first_close_us=day_start + MINUTE,
        last_close_us=day_start + 1440 * MINUTE,
        candle_allowance_us=1_000_000,
    )


def _binance() -> PipelineConfig:
    return with_binance_enabled(base_config(), last_opened_date=FAR_FUTURE)


def _funding_frame(times: list[int], knowable: list[int] | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "venue": ["binance"] * len(times),
            "symbol": ["S"] * len(times),
            "settle_time": pl.Series(times, dtype=pl.Int64).cast(UTC_TIME),
            "funding_interval_hours": pl.Series([8] * len(times), dtype=pl.Int32),
            "funding_rate": [0.0001 * (i + 1) for i in range(len(times))],
            "knowable_time": pl.Series(knowable or times, dtype=pl.Int64).cast(UTC_TIME),
        }
    )


CLOCK = RunClock(START + 2 * HOUR, START + 2 * HOUR)


def _calls(reader: MarketReader, venue: str) -> list[object]:
    return [
        lambda: reader.bars(1, venue, "S", CLOCK),
        lambda: reader.candles(venue, "S", CLOCK),
        lambda: reader.funding(venue, "S", CLOCK),
        lambda: reader.trades(venue, "S", CLOCK),
        lambda: reader.as_of_bars(1, venue, "S", START + HOUR, START + 2 * HOUR),
        lambda: reader.ideal_bars(1, venue, "S", START + HOUR),
    ]


@pytest.mark.parametrize("venue", ["binance", "bybit", "kraken", "no-such-source"])
def test_a_source_that_is_not_enabled_is_not_read_whatever_is_on_disk(tmp_path: Path, venue: str) -> None:
    """N-08. The reader used to read any folder it was pointed at."""
    shipped = replace(base_config(), last_opened_date=FAR_FUTURE)
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=shipped)
    _store(ctx, BARS_1M, venue, _official_bars(venue))
    _store(ctx, official_dataset(1), venue, _official_bars(venue))
    reader = MarketReader(ctx.root, shipped)
    for call in _calls(reader, venue):
        with pytest.raises(SourceNotApproved):
            call()  # type: ignore[operator]


def test_a_refusal_of_a_source_is_a_configuration_error_the_commands_already_report(tmp_path: Path) -> None:
    assert issubclass(SourceNotApproved, ConfigError)


def test_the_enabled_source_is_served_through_its_route(tmp_path: Path) -> None:
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    reader = MarketReader(ctx.root, setup)
    t_cut = START + 60 * MINUTE
    clock = RunClock(t_cut, t_cut + 65_000_000)
    rows = reader.candles("binance", "S", clock)
    assert rows.height == 60
    assert rows["bar_source"].unique().to_list() == [SOURCE_OFFICIAL]
    assert rows["empty_proof"].unique().to_list() == ["traded"]
    # They can never be read as trade-built bars, whatever sits in that dataset.
    _store(ctx, BARS_1M, "binance", _official_bars("binance"))
    with pytest.raises(SourceNotApproved, match="candles"):
        reader.bars(1, "binance", "S", clock)


def _ideal_setup(shown: bool) -> PipelineConfig:
    setup = _binance()
    source = replace(
        setup.source("binance"),
        candle_check="shown" if shown else "not_shown",
        candle_check_evidence="sample days" if shown else "",
    )
    return replace(setup, sources={**setup.sources, "binance": source})


def test_ideal_on_official_bars_rests_on_condition_2_and_not_on_the_trade_rows(tmp_path: Path) -> None:
    """Ruling 7 condition 7. `ideal_allowed` used to look at the source's trade rows, which is the wrong test
    here."""
    moment = START + 60 * MINUTE
    closed = _ideal_setup(False)
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=closed)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    # A measured allowance on the trade rows does not open it.
    measured = replace(closed.source("binance"), allowance_state="measured", allowance_evidence="x")
    with pytest.raises(TimingContractError, match="IDEAL"):
        MarketReader(ctx.root, replace(closed, sources={**closed.sources, "binance": measured})).ideal_bars(
            1, "binance", "S", moment
        )
    view = MarketReader(ctx.root, _ideal_setup(True)).ideal_bars(1, "binance", "S", moment)
    assert view.height == 60
    assert view["volume"].to_list() == [2.0] * 60
    assert view["fill_count"].to_list() == [3] * 60
    assert "knowable_time" not in view.columns


def test_as_of_on_official_bars_waits_for_the_candle_allowance(tmp_path: Path) -> None:
    """S01 and S06 select under IDEAL-1M, which is read as of t + max(latency, A)."""
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    reader = MarketReader(ctx.root, setup)
    moment = START + 60 * MINUTE
    with pytest.raises(TimingContractError, match="allowance"):
        reader.as_of_bars(1, "binance", "S", moment, moment + 999_999)
    rows = reader.as_of_bars(1, "binance", "S", moment, moment + 1_000_000)
    assert rows.height == 60
    assert rows["close_time"].dt.timestamp("us").max() == moment
    five = reader.as_of_bars(5, "binance", "S", moment, moment + 60_000_000)
    assert five.height == 12
    assert "knowable_time" not in five.columns


def test_an_archive_only_source_has_no_live_read_even_with_the_poll_pointed_at_it(tmp_path: Path) -> None:
    """D-29. Loading a file refuses this, and the reader refuses it again for a configuration built in
    memory."""
    setup = _binance()
    moved = replace(setup, poll=replace(setup.poll, venue="binance"))
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    _store(ctx, BARS_1M_LIVE, "binance", _official_bars("binance"))
    reader = MarketReader(ctx.root, moved)
    with pytest.raises(SourceNotApproved, match="archive"):
        reader.live_bars(1, "S", CLOCK)
    with pytest.raises(SourceNotApproved, match="archive"):
        reader.live_trades("S", CLOCK)
    specs = tuple(
        replace(spec, live_eligible=True) if spec.id == "binance.fundingRate" else spec
        for spec in setup.datasets
    )
    with pytest.raises(SourceNotApproved, match="archive"):
        MarketReader(ctx.root, replace(setup, datasets=specs)).live_dataset("binance.fundingRate", "S", CLOCK)


def test_a_candle_read_on_a_source_that_builds_from_trades_is_refused(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    with pytest.raises(SourceNotApproved, match="trades"):
        MarketReader(ctx.root, ctx.config).candles("generated", "S", CLOCK)


def test_funding_stops_at_the_cut_and_a_row_not_yet_knowable_raises(tmp_path: Path) -> None:
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    times = [START, START + 8 * HOUR, START + 16 * HOUR]
    part = ctx.root.curated_month_part("funding", "binance", "S", DAY)
    atomic_write_parquet(part, _funding_frame(times), guard=ctx.root.guard)
    reader = MarketReader(ctx.root, setup)
    t_cut = START + 9 * HOUR
    rows = reader.funding("binance", "S", RunClock(t_cut, t_cut))
    assert rows["funding_rate"].to_list() == [0.0001, 0.0002]
    # A rate published later than it settled is not there at the settlement time.
    atomic_write_parquet(
        part, _funding_frame(times, [START, START + 10 * HOUR, START + 16 * HOUR]), guard=ctx.root.guard
    )
    with pytest.raises(TimingContractError, match="funding"):
        MarketReader(ctx.root, setup).funding("binance", "S", RunClock(t_cut, t_cut))
    with pytest.raises(TimingContractError):
        reader.funding("binance", "S", RunClock(t_cut, t_cut - 1))


# ---- N-12, N-13: empties and ranges
# ------------------------------------------------------------------------------


def test_an_empty_read_keeps_its_columns(tmp_path: Path) -> None:
    """N-12. A mistyped symbol used to give a frame with no columns, and a distant ColumnNotFoundError."""
    ctx = context(tmp_path / "r")
    reader = MarketReader(ctx.root, ctx.config)
    assert reader.bars(1, "generated", "NOPE", CLOCK).schema == BAR_SCHEMA
    assert "complete" in reader.bars(60, "generated", "NOPE", CLOCK).columns
    assert reader.trades("generated", "NOPE", CLOCK).schema == TRADE_SCHEMA
    assert reader.funding("generated", "NOPE", CLOCK).schema == FUNDING_SCHEMA
    assert reader.live_bars(1, "NOPE", CLOCK).schema == BAR_SCHEMA
    assert reader.live_trades("NOPE", CLOCK).schema == TRADE_SCHEMA


def test_a_monthly_part_is_read_by_its_period_and_not_by_its_name(tmp_path: Path) -> None:
    """N-13. The name was compared as text, so a part 2026-03 was dropped for since = 2026-03-15."""
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 31, tzinfo=dt.UTC), config=setup)
    mid = us("2026-03-20T00:00:00")
    times = [START, us("2026-03-15T00:00:00"), mid]
    part = ctx.root.curated_month_part("funding", "binance", "S", DAY)
    atomic_write_parquet(part, _funding_frame(times), guard=ctx.root.guard)
    reader = MarketReader(ctx.root, setup)
    clock = RunClock(mid, mid)
    rows = reader.funding("binance", "S", clock, since=dt.date(2026, 3, 15))
    assert rows.height == 2
    assert reader.funding("binance", "S", clock, since=dt.date(2026, 4, 1)).height == 0
    # A cut before the month starts reads nothing from it.
    early = us("2026-02-20T00:00:00")
    assert reader.funding("binance", "S", RunClock(early, early)).height == 0


def test_a_cut_at_exactly_midnight_reads_the_last_bar_of_the_day_before(tmp_path: Path) -> None:
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 3, tzinfo=dt.UTC), config=setup)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    midnight = START + 1440 * MINUTE
    rows = MarketReader(ctx.root, setup).candles("binance", "S", RunClock(midnight, midnight + 65_000_000))
    assert rows.height == 1440
    assert rows["close_time"].dt.timestamp("us").max() == midnight


def test_a_cut_at_midnight_leaves_the_next_days_bars_shut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A range ending at midnight reads its last bar, with no file after the range opened. The engine asked
    for it."""
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 3, tzinfo=dt.UTC), config=setup)
    next_day = DAY + dt.timedelta(days=1)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    atomic_write_parquet(
        ctx.root.curated_part(official_dataset(1), "binance", "S", next_day),
        _official_bars("binance", START + 1440 * MINUTE),
        guard=ctx.root.guard,
    )
    opened: list[str] = []
    real = pl.read_parquet

    def recording(path: object, *args: object, **kwargs: object) -> pl.DataFrame:
        opened.append(str(path))
        return real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("hft_crypto.data.atomic.pl.read_parquet", recording)
    midnight = START + 1440 * MINUTE
    rows = MarketReader(ctx.root, setup).candles("binance", "S", RunClock(midnight, midnight + 65_000_000))
    assert rows["close_time"].dt.timestamp("us").max() == midnight
    assert opened
    assert not [name for name in opened if next_day.isoformat() in name]


def test_as_of_reads_refuse_a_time_before_the_allowance_has_passed(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    _store(ctx, BARS_1M, "generated", _bars(None, venue="generated"))
    reader = MarketReader(ctx.root, ctx.config)
    moment = START + 60 * MINUTE
    with pytest.raises(TimingContractError, match="allowance"):
        reader.as_of_bars(1, "generated", "S", moment, moment + 249_999)
    rows = reader.as_of_bars(1, "generated", "S", moment, moment + 250_000)
    assert rows.height == 60
    assert rows["close_time"].dt.timestamp("us").max() == moment
    assert "knowable_time" not in rows.columns


def test_trades_read_to_the_cut_and_not_to_the_decision(tmp_path: Path) -> None:
    """Item 4. These tests used to set the two times equal, so a run reading past its cut passed."""
    ctx = context(tmp_path / "r")
    frame = _rows().with_columns(
        pl.lit("generated").alias("venue"), pl.lit("S").alias("symbol"), pl.lit(False).alias("is_rpi")
    )
    _store(ctx, TRADES, "generated", frame)
    _store(ctx, TRADES_LIVE, ctx.config.poll.venue, frame)
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 10 * MINUTE
    clock = RunClock(t_cut, t_cut + 5 * MINUTE)
    assert reader.trades("generated", "S", clock).height == 10
    assert reader.live_trades("S", clock).height == 10


def test_the_next_test_covers_every_configured_timeframe() -> None:
    assert set(base_config().timeframes_minutes) <= set(IDEAL_TIMEFRAMES)


@pytest.mark.parametrize("minutes", IDEAL_TIMEFRAMES)
def test_ideal_reads_settled_flow_on_every_timeframe_and_on_every_column(
    tmp_path: Path, minutes: int
) -> None:
    """Item 4. A view returning plain flow on a higher timeframe used to pass, because only 1m was tested."""
    ctx = context(tmp_path / "r")
    measured = replace(ctx.config.source("generated"), allowance_state="measured", allowance_evidence="x")
    setup = replace(ctx.config, sources={**ctx.config.sources, "generated": measured})
    # Each minute has one row inside the allowance before its close, on a side of its own.
    rows = [(START + m * MINUTE + 59_900_000, 100.0 + m % 7, 1.0 + m % 5, bool(m % 2)) for m in range(1440)]
    bars = build_bars_1m(
        trades_frame(rows, allowance_us=250_000),
        venue="generated",
        symbol="S",
        first_close_us=START + MINUTE,
        last_close_us=START + 1441 * MINUTE,
        continuity="trade_id",
        fill_span_allowance_us=250_000,
        received_at_us=None,
    )
    _store(ctx, BARS_1M, "generated", bars)
    moment = START + 1440 * MINUTE
    view = MarketReader(ctx.root, setup).ideal_bars(minutes, "generated", "S", moment)
    higher = bars if minutes == 1 else aggregate_bars(bars, minutes, through_close_us=moment)
    wanted = higher.filter(pl.col("close_time").dt.timestamp("us") <= moment)
    assert view.height == wanted.height
    for name in ("volume", "quote_volume", "buy_volume", "sell_volume"):
        assert view[name].to_list() == wanted[f"settled_{name}"].to_list(), name
    assert view["volume"].to_list() != wanted["volume"].to_list()
    assert "fill_count" not in view.columns
    assert not [name for name in view.columns if name.startswith("settled_")]


def test_a_read_since_a_day_leaves_out_the_days_before_it(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r")
    _store(ctx, BARS_1M, "generated", _bars(None, venue="generated"))
    reader = MarketReader(ctx.root, ctx.config)
    t_cut = START + 60 * MINUTE
    clock = RunClock(t_cut, t_cut + 65_000_000)
    assert reader.bars(1, "generated", "S", clock, since=DAY).height == 60
    assert reader.bars(1, "generated", "S", clock, since=DAY + dt.timedelta(days=1)).height == 0


def test_a_read_at_a_moment_equals_a_read_of_data_cut_there_on_every_column(tmp_path: Path) -> None:
    """DR-03. What an as-of read gives cannot depend on anything printed after its moment."""
    measured_ctx = context(tmp_path / "r")
    measured = replace(
        measured_ctx.config.source("generated"), allowance_state="measured", allowance_evidence="x"
    )
    setup = replace(measured_ctx.config, sources={**measured_ctx.config.sources, "generated": measured})
    # Rows close to their closes, and some empty minutes that only a later row can prove.
    rows = [
        (START + m * MINUTE + (59_900_000 if m % 3 else 10_000_000), 100.0 + m, 1.0, bool(m % 2))
        for m in range(120)
        if m % 7 != 3
    ]

    def stored(path: Path, kept: list[tuple[int, float, float, bool]], last: int) -> MarketReader:
        ctx = make_context(path, now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
        bars = build_bars_1m(
            trades_frame(kept, allowance_us=250_000),
            venue="generated",
            symbol="S",
            first_close_us=START + MINUTE,
            last_close_us=last,
            continuity="trade_id",
            fill_span_allowance_us=250_000,
            received_at_us=None,
        )
        _store(ctx, BARS_1M, "generated", bars)
        return MarketReader(ctx.root, setup)

    full = stored(tmp_path / "full", rows, START + 120 * MINUTE)
    for minute in (10, 17, 30, 45, 60):
        moment = START + minute * MINUTE
        cut = stored(tmp_path / f"cut{minute}", [row for row in rows if row[0] <= moment], moment)
        for timeframe in (1, 5, 15):
            assert full.ideal_bars(timeframe, "generated", "S", moment).equals(
                cut.ideal_bars(timeframe, "generated", "S", moment)
            ), (minute, timeframe)


def test_a_recorded_false_allowance_refuses_ideal_reads_from_then_on(tmp_path: Path) -> None:
    """DR-06. A source's class is a declared value, and one row running past it ends it."""
    ctx = context(tmp_path / "r")
    _store(ctx, BARS_1M, "generated", _bars(None, venue="generated"))
    measured = replace(ctx.config.source("generated"), allowance_state="measured")
    setup = replace(ctx.config, sources={**ctx.config.sources, "generated": measured})
    moment = START + 60 * MINUTE
    assert MarketReader(ctx.root, setup).ideal_bars(1, "generated", "S", moment).height == 60
    (ctx.root.path / "catalog").mkdir(exist_ok=True)
    (ctx.root.path / "catalog" / "allowance_events.jsonl").write_text(
        '{"venue": "generated", "symbol": "S", "date": "2026-03-01"}\n', encoding="utf-8"
    )
    with pytest.raises(TimingContractError, match="IDEAL"):
        MarketReader(ctx.root, setup).ideal_bars(1, "generated", "S", moment)


# ---- the import rule: strategy and feature code cannot go around the reader
# ---------------------------------------

FORBIDDEN_READS = {"read_parquet", "scan_parquet", "curated_part", "curated_parts"}
# A list of who may read, and not of who may not, so a new package name cannot escape it. Each of these is
# data work with no run clock of its own: the reader, the layer that builds what it serves, and the report on
# stored files.
ALLOWED_TO_READ_STORED_DATA = {
    "data/atomic.py",
    "data/derive.py",
    "data/ingest.py",
    "data/live_checks.py",
    "data/poll.py",
    "data/reader.py",
    "reports/report.py",
}


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


def test_only_the_data_layer_can_read_stored_data_directly() -> None:
    """Every module in the package is scanned, also those that do not exist yet."""
    root = REPO_ROOT / "src" / "hft_crypto"
    offenders = {
        path.relative_to(root).as_posix(): direct_reads(path)
        for path in root.rglob("*.py")
        if direct_reads(path) and path.relative_to(root).as_posix() not in ALLOWED_TO_READ_STORED_DATA
    }
    assert offenders == {}


# ---- section 17.5 of the recheck: two reads a test must hold -----------------------------------------------


def test_funding_reads_to_the_cut_and_not_to_the_decision(tmp_path: Path) -> None:
    """The engine's clock sets its decision far past its cut, so only the cut keeps a later settlement out.
    Here the cut is at hour 2 and the decision at hour 5, and the settlements at hours 3 and 4 must not come
    back.
    """
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    times = [START + hour * HOUR for hour in (1, 2, 3, 4)]
    _store(ctx, "funding", "binance", _funding_frame(times))
    rows = MarketReader(ctx.root, setup).funding("binance", "S", RunClock(START + 2 * HOUR, START + 5 * HOUR))
    assert rows["settle_time"].dt.timestamp("us").to_list() == times[:2]


def test_as_of_bars_a_minute_after_t_still_ends_at_t(tmp_path: Path) -> None:
    """A read a minute or more after `t` is where reading to the read and not to `t` would show."""
    setup = _binance()
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 2, tzinfo=dt.UTC), config=setup)
    _store(ctx, official_dataset(1), "binance", _official_bars("binance"))
    moment = START + 60 * MINUTE
    rows = MarketReader(ctx.root, setup).as_of_bars(1, "binance", "S", moment, moment + 60_000_000)
    assert rows.height == 60
    assert rows["close_time"].dt.timestamp("us").max() == moment
    later = MarketReader(ctx.root, setup).as_of_bars(1, "binance", "S", moment, moment + 600_000_000)
    assert later.height == 60
