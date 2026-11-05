"""FP-01 and item 3a of the leak recheck: nothing reads, fetches or reports a date nobody has opened.

One scheduled run over these dates would read and publish the locked block, and that cannot be undone. All
files here are generated, and all prices are invented.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from helpers import (
    FAR_FUTURE,
    REPO_ROOT,
    FakeFetcher,
    base_config,
    make_context,
    us,
    with_binance_enabled,
    with_sources_enabled,
    zip_bytes,
)
from hft_crypto.bars.core import UTC_TIME, DateGuardError, bars_from_official
from hft_crypto.cli import main
from hft_crypto.config import (
    LAST_OPENED_DATE,
    LAST_OPENED_DECISION,
    PipelineConfig,
    load_pipeline_config,
)
from hft_crypto.data.atomic import atomic_write_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M, TRADES, derive_day, official_dataset
from hft_crypto.data.ingest import IngestOptions, IngestSummary, Task, _fetch_raw, plan_tasks, run_ingest
from hft_crypto.data.parsers import TRADE_SCHEMA
from hft_crypto.data.poll import BARS_1M_LIVE, TRADES_LIVE
from hft_crypto.data.reader import FUNDING, MarketReader, RunClock
from hft_crypto.data.sources import expected_partitions, last_partition_within, partition_last_day
from hft_crypto.reports.report import write_report
from hft_crypto.timeutil import day_start_us

BTC = "BTCUSDT"
NOW = dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC)
DOCS = REPO_ROOT / "docs" / "decisions"


# ---- the value, and who can move it
# ---------------------------------------------------------------------------------


def test_the_guard_is_the_date_in_the_log_and_the_plan() -> None:
    """A test compares the two, as item 3a asks. Opening a block means a new entry and a change here,
    together."""
    log = (DOCS / "DECISION_LOG.md").read_text(encoding="utf-8")
    row = next(line for line in log.splitlines() if line.startswith(f"| {LAST_OPENED_DECISION} |"))
    found = re.search(r"The last opened date is (\d{4}-\d{2}-\d{2})", row)
    assert found is not None
    assert dt.date.fromisoformat(found.group(1)) == LAST_OPENED_DATE
    plan = " ".join((DOCS / "FOLD_PLAN_2026-11-05.md").read_text(encoding="utf-8").split())
    stated = re.search(
        rf"The last opened date is (\d{{4}}-\d{{2}}-\d{{2}}) \(`{LAST_OPENED_DECISION}`\)", plan
    )
    assert stated is not None
    assert dt.date.fromisoformat(stated.group(1)) == LAST_OPENED_DATE


def test_no_file_and_no_variable_can_move_the_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shipped = (REPO_ROOT / "configs" / "pipeline.toml").read_text(encoding="utf-8")
    shutil.copy(REPO_ROOT / "configs" / "retention.toml", tmp_path / "retention.toml")
    (tmp_path / "pipeline.toml").write_text('last_opened_date = "2030-01-01"\n' + shipped, encoding="utf-8")
    monkeypatch.setenv("LAST_OPENED_DATE", "2030-01-01")
    assert load_pipeline_config(tmp_path).last_opened_date == LAST_OPENED_DATE
    assert base_config().last_opened_date == LAST_OPENED_DATE
    assert base_config().opened_through_us == day_start_us(dt.date(2024, 1, 1))


# ---- the ceiling on ingest: flags are not a ceiling
# -----------------------------------------------------------------


def _shipped_on() -> PipelineConfig:
    return with_binance_enabled(base_config())


def _context(path: Path, config: PipelineConfig | None = None, now: dt.datetime = NOW) -> JobContext:
    return make_context(path, now=now, config=config or _shipped_on())


@pytest.mark.parametrize(
    "options",
    [
        IngestOptions(),
        IngestOptions(end=dt.date(2030, 1, 1)),
        IngestOptions(start=dt.date(2026, 1, 1)),
        IngestOptions(start=dt.date(2024, 1, 1), end=dt.date(2026, 9, 30)),
        IngestOptions(dataset_ids=("binance.klines",)),
    ],
    ids=["no flags", "a later end", "a later start", "the closed dates by name", "one dataset"],
)
def test_no_flag_gets_ingest_past_the_last_opened_date(tmp_path: Path, options: IngestOptions) -> None:
    """Coverage record 4.3. --end is optional, and the daily workflow passes neither flag."""
    tasks = plan_tasks(_context(tmp_path / "r"), options)
    for task in tasks:
        assert partition_last_day(task.spec, task.partition) <= LAST_OPENED_DATE


@pytest.mark.parametrize(
    "now", [NOW, dt.datetime(2030, 6, 1, tzinfo=dt.UTC)], ids=["today", "years from now"]
)
def test_the_first_span_list_comes_from_the_calendar_and_not_from_today(
    tmp_path: Path, now: dt.datetime
) -> None:
    """The 192 files of stage one, whenever it runs, newest first and all inside the first span."""
    tasks = plan_tasks(_context(tmp_path / "r", now=now), IngestOptions())
    assert len(tasks) == 192
    assert {task.spec.id for task in tasks} == {"binance.klines", "binance.fundingRate"}
    assert {task.symbol for task in tasks} == {BTC, "ETHUSDT"}
    assert tasks[0].partition == dt.date(2023, 12, 1)
    assert tasks[-1].partition == dt.date(2020, 1, 1)


def test_a_partition_is_expected_only_when_it_lies_wholly_inside() -> None:
    spec = base_config().dataset("binance.fundingRate")
    assert last_partition_within(spec, dt.date(2023, 12, 31)) == dt.date(2023, 12, 1)
    assert last_partition_within(spec, dt.date(2023, 12, 30)) == dt.date(2023, 11, 1)
    assert expected_partitions(spec, NOW, ceiling=dt.date(2020, 2, 29))[-1] == dt.date(2020, 2, 1)
    with pytest.raises(TypeError):
        expected_partitions(spec, NOW)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("dataset", "partition", "guard"),
    [
        ("binance.klines", dt.date(2024, 1, 1), LAST_OPENED_DATE),
        ("binance.fundingRate", dt.date(2024, 1, 1), LAST_OPENED_DATE),
        ("binance.fundingRate", dt.date(2023, 12, 1), dt.date(2023, 12, 30)),
    ],
    ids=["candles", "funding", "a month reaching past it"],
)
def test_the_fetch_itself_refuses_past_the_guard_and_asks_for_nothing(
    tmp_path: Path, dataset: str, partition: dt.date, guard: dt.date
) -> None:
    """A second lock, for whatever reaches it other than the plan."""
    config = replace(_shipped_on(), last_opened_date=guard)
    fetcher = FakeFetcher()
    ctx = _context(tmp_path / "r", config)
    with pytest.raises(DateGuardError):
        _fetch_raw(
            ctx,
            fetcher,
            Task(config.dataset(dataset), BTC, partition),
            IngestSummary(run_id="x"),
            refetch=False,
        )
    assert fetcher.requests == []


def test_a_whole_run_with_everything_published_asks_for_nothing_past_the_guard(tmp_path: Path) -> None:
    """With start at T_start, and every later month on offer. No file past the date, and nothing fetched for
    one."""
    base = _shipped_on()
    datasets = tuple(replace(spec, start=dt.date(2023, 11, 1)) for spec in base.datasets)
    config = replace(base, datasets=datasets, symbols=(BTC,))
    ctx = _context(tmp_path / "r", config)
    fetcher = FakeFetcher()
    run_ingest(ctx, fetcher, IngestOptions())
    assert fetcher.requests
    months = {match for url in fetcher.requests for match in re.findall(r"-(\d{4}-\d{2})\.zip", url)}
    assert months == {"2023-11", "2023-12"}


# ---- the reader
# ----------------------------------------------------------------------------------------------------


GUARD = dt.date(2026, 3, 1)
END_OF_GUARD = us("2026-03-02T00:00:00")


def _guarded() -> PipelineConfig:
    return replace(with_sources_enabled(base_config()), last_opened_date=GUARD)


def _store_row(ctx: JobContext, dataset: str, venue: str, day: dt.date, frame: pl.DataFrame) -> None:
    atomic_write_parquet(ctx.root.curated_part(dataset, venue, BTC, day), frame, guard=ctx.root.guard)


def _candle_frame(day: dt.date, *, price: float = 100.0) -> pl.DataFrame:
    low = day_start_us(day)
    stamps = [low + minute * 60_000_000 for minute in range(1440)]
    return pl.DataFrame(
        {
            "open_time": pl.Series(stamps, dtype=pl.Int64).cast(UTC_TIME),
            "open": [price] * 1440,
            "high": [price] * 1440,
            "low": [price] * 1440,
            "close": [price] * 1440,
            "volume": [1.0] * 1440,
            "quote_volume": [price] * 1440,
            "trade_count": [2] * 1440,
            "taker_buy_volume": [1.0] * 1440,
            "taker_buy_quote_volume": [price] * 1440,
        }
    )


def _official(day: dt.date, venue: str = "generated") -> pl.DataFrame:
    low = day_start_us(day)
    return bars_from_official(
        _candle_frame(day),
        venue=venue,
        symbol=BTC,
        first_close_us=low + 60_000_000,
        last_close_us=low + 86_400_000_000,
        candle_allowance_us=1_000_000,
    )


CLOCKS = {
    "one microsecond past": END_OF_GUARD + 1,
    "a day past": END_OF_GUARD + 86_400_000_000,
}


@pytest.mark.parametrize("moment", list(CLOCKS.values()), ids=list(CLOCKS))
def test_every_read_refuses_a_cut_past_the_guard(tmp_path: Path, moment: int) -> None:
    config = _guarded()
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    reader = MarketReader(ctx.root, config)
    clock = RunClock(moment, moment + 65_000_000)
    calls: list[Callable[[], object]] = [
        lambda: reader.bars(1, "generated", BTC, clock),
        lambda: reader.bars(60, "generated", BTC, clock),
        lambda: reader.trades("generated", BTC, clock),
        lambda: reader.funding("generated", BTC, clock),
        lambda: reader.as_of_bars(1, "generated", BTC, moment, moment + 65_000_000),
        lambda: reader.live_bars(1, BTC, clock),
        lambda: reader.live_trades(BTC, clock),
    ]
    for call in calls:
        with pytest.raises(DateGuardError):
            call()


def test_ideal_and_a_live_gate_refuse_it_too(tmp_path: Path) -> None:
    config = _guarded()
    specs = tuple(
        replace(spec, live_eligible=True) if spec.id == "generated.fundingRate" else spec
        for spec in config.datasets
    )
    measured = replace(config.source("generated"), allowance_state="measured", allowance_evidence="x")
    setup = replace(config, datasets=specs, sources={**config.sources, "generated": measured})
    ctx = make_context(tmp_path / "r", now=NOW, config=setup)
    reader = MarketReader(ctx.root, setup)
    moment = END_OF_GUARD + 1
    with pytest.raises(DateGuardError):
        reader.ideal_bars(1, "generated", BTC, moment)
    with pytest.raises(DateGuardError):
        reader.live_dataset("generated.fundingRate", BTC, RunClock(moment, moment))


def test_the_last_bar_of_the_span_stays_readable_though_it_is_known_after_midnight(tmp_path: Path) -> None:
    """Item 3a: do not guard on knowable_time, or the last bar of the span is lost."""
    config = replace(_binance_far(), last_opened_date=GUARD)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    _store_row(ctx, official_dataset(1), "binance", GUARD, _official(GUARD, "binance"))
    rows = MarketReader(ctx.root, config).candles(
        "binance", BTC, RunClock(END_OF_GUARD, END_OF_GUARD + 1_000_000)
    )
    assert rows.height == 1440
    last = rows.row(-1, named=True)
    assert last["close_time"].isoformat() == "2026-03-02T00:00:00+00:00"
    assert last["knowable_time"] > last["close_time"]


def _binance_far() -> PipelineConfig:
    return with_binance_enabled(base_config(), last_opened_date=FAR_FUTURE)


def test_a_part_past_the_guard_is_never_even_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(_binance_far(), last_opened_date=GUARD)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    _store_row(ctx, official_dataset(1), "binance", GUARD, _official(GUARD, "binance"))
    later = GUARD + dt.timedelta(days=1)
    _store_row(ctx, official_dataset(1), "binance", later, _official(later, "binance"))
    opened: list[str] = []
    real = pl.read_parquet

    def recording(path: Any, *args: Any, **kwargs: Any) -> pl.DataFrame:
        opened.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr("hft_crypto.data.atomic.pl.read_parquet", recording)
    MarketReader(ctx.root, config).candles("binance", BTC, RunClock(END_OF_GUARD, END_OF_GUARD + 1_000_000))
    assert opened
    assert not [name for name in opened if later.isoformat() in name]


def test_the_guard_stands_with_every_kind_of_row_on_disk_past_it(tmp_path: Path) -> None:
    """Bars by close time, trades by stamp and funding by settlement time."""
    config = _guarded()
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    later = GUARD + dt.timedelta(days=1)
    _store_row(ctx, BARS_1M, "generated", later, _official(later))
    _store_row(ctx, TRADES, "generated", later, pl.DataFrame(schema=TRADE_SCHEMA))
    _store_row(ctx, FUNDING, "generated", later, pl.DataFrame(schema={"settle_time": UTC_TIME}))
    _store_row(ctx, BARS_1M_LIVE, config.poll.venue, later, _official(later))
    _store_row(ctx, TRADES_LIVE, config.poll.venue, later, pl.DataFrame(schema=TRADE_SCHEMA))
    reader = MarketReader(ctx.root, config)
    inside = RunClock(END_OF_GUARD, END_OF_GUARD + 1_000_000)
    assert reader.bars(1, "generated", BTC, inside).is_empty()
    assert reader.trades("generated", BTC, inside).is_empty()
    assert reader.funding("generated", BTC, inside).is_empty()
    assert reader.live_bars(1, BTC, inside).is_empty()
    assert reader.live_trades(BTC, inside).is_empty()


# ---- bar building
# --------------------------------------------------------------------------------------------------


def test_no_bars_are_built_past_the_guard(tmp_path: Path) -> None:
    config = _guarded()
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    with pytest.raises(DateGuardError):
        derive_day(ctx, "generated", BTC, GUARD + dt.timedelta(days=1))
    assert ctx.root.curated_parts(BARS_1M, "generated", BTC) == []


def test_a_base_file_past_the_guard_is_left_unread_by_the_sweep_and_says_so(tmp_path: Path) -> None:
    base = replace(with_sources_enabled(base_config()), last_opened_date=GUARD, symbols=(BTC,))
    ctx = make_context(tmp_path / "r", now=NOW, config=base)
    later = GUARD + dt.timedelta(days=1)
    _store_row(ctx, TRADES, "generated", later, pl.DataFrame(schema=TRADE_SCHEMA))
    summary = run_ingest(
        ctx,
        FakeFetcher(),
        IngestOptions(dataset_ids=("generated.aggTrades",), symbols=(BTC,), start=later, end=later),
    )
    assert ctx.root.curated_parts(BARS_1M, "generated", BTC) == []
    assert any("past the last opened date" in alert for alert in summary.alerts)


# ---- CHECK_ROOT: closed dates never enter DATA_ROOT
# -----------------------------------------------------------------


def _check_root(path: Path) -> Path:
    from hft_crypto.data.coverage import init_check_root

    return init_check_root(path, data_root=str(path.parent / "data-root"))


def test_a_check_root_holds_a_marker_and_nothing_else_yet(tmp_path: Path) -> None:
    root = _check_root(tmp_path / "check")
    assert sorted(item.name for item in root.iterdir()) == ["ROOT_KIND"]
    for zone in ("curated", "features", "results", "ledger", "decisions", "catalog"):
        assert not (root / zone).exists()


def test_a_check_root_must_be_new_and_empty_and_apart_from_data_root(tmp_path: Path) -> None:
    from hft_crypto.data.coverage import init_check_root
    from hft_crypto.data.zones import DataRootError

    used = tmp_path / "used"
    used.mkdir()
    (used / "x").write_text("x", encoding="utf-8")
    with pytest.raises(DataRootError, match="new and empty"):
        init_check_root(used, data_root=None)
    data = tmp_path / "data"
    with pytest.raises(DataRootError, match="hold one another"):
        init_check_root(data / "inside", data_root=str(data))
    with pytest.raises(DataRootError, match="hold one another"):
        init_check_root(tmp_path / "outer", data_root=str(tmp_path / "outer" / "data"))
    with pytest.raises(DataRootError, match="outside the repository"):
        init_check_root(REPO_ROOT / "not-here", data_root=None)
    assert not (REPO_ROOT / "not-here").exists()


def test_nothing_that_takes_a_data_root_can_open_a_check_root(tmp_path: Path) -> None:
    from hft_crypto.data.zones import DataRoot, DataRootError, resolve_data_root

    root = _check_root(tmp_path / "check")
    with pytest.raises(DataRootError, match="check root"):
        DataRoot(root, create=False)
    with pytest.raises(DataRootError, match="check root"):
        DataRoot(root)
    with pytest.raises(DataRootError, match="check root"):
        resolve_data_root(str(root))
    # Opening it created nothing.
    assert sorted(item.name for item in root.iterdir()) == ["ROOT_KIND"]


@pytest.mark.parametrize("left", ["ROOT_KIND", "coverage/coverage_check.json"])
def test_a_root_that_becomes_a_check_root_is_refused_by_the_reader_report_and_bars(
    tmp_path: Path, left: str
) -> None:
    """Held by what uses a root too, and either file is enough, since a root can lose its marker."""
    from hft_crypto.data.zones import DataRootError

    config = _binance_far()
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    target = ctx.root.path / left
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(DataRootError):
        MarketReader(ctx.root, config)
    with pytest.raises(DataRootError):
        write_report(ctx, out_dir=tmp_path / "out")
    with pytest.raises(DataRootError):
        derive_day(ctx, "binance", BTC, dt.date(2023, 1, 1))
    with pytest.raises(DataRootError):
        run_ingest(ctx, FakeFetcher(), IngestOptions())
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "command",
    [
        ["report"],
        ["report", "--published", "--out-dir", "X"],
        ["health"],
        ["retention"],
        ["ingest", "--light"],
        ["poll"],
        ["reconcile-live"],
        ["init"],
    ],
    ids=lambda item: item[0] if len(item) < 2 else "-".join(item[:2]),
)
def test_every_command_refuses_a_check_root_as_its_data_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    root = _check_root(tmp_path / "check")
    args = ["--config-dir", str(REPO_ROOT / "configs"), "--data-root", str(root)]
    filled = [str(tmp_path / "out") if item == "X" else item for item in command]
    assert main([*args, *filled]) == 2
    assert "check root" in capsys.readouterr().err
    assert sorted(item.name for item in root.iterdir()) == ["ROOT_KIND"]
    assert not (tmp_path / "out").exists()


def test_a_check_root_cannot_be_named_as_the_live_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from hft_crypto.data.catalog import Catalog
    from hft_crypto.data.zones import DataRoot

    root = _check_root(tmp_path / "check")
    real = DataRoot(tmp_path / "real")
    Catalog(real.catalog_path).close()
    args = ["--config-dir", str(REPO_ROOT / "configs"), "--data-root", str(tmp_path / "real")]
    assert main([*args, "report", "--out-dir", str(tmp_path / "out"), "--live-root", str(root)]) == 2
    assert "check root" in capsys.readouterr().err


# ---- the check: what may leave
# --------------------------------------------------------------------------------------


PRICE = 12345.678
MONTHS = ((2024, 1, 31), (2024, 2, 29), (2024, 3, 31))
_ONE_QUARTER = (dt.date(2024, 1, 1), dt.date(2024, 3, 1))


def _month_csv(
    year: int, month: int, days: int, *, count: int = 5, skip: int = 0, bad_row: bool = False
) -> str:
    start_ms = day_start_us(dt.date(year, month, 1)) // 1000
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
        "taker_buy_quote_volume,ignore"
    ]
    for minute in range(days * 1440 - skip):
        stamp = start_ms + minute * 60_000
        high = PRICE - 1 if bad_row and minute == 7 else PRICE
        lines.append(
            f"{stamp},{PRICE},{high},{PRICE},{PRICE},2.5,{stamp + 59_999},30864.2,{count},1.5,18518.5,0"
        )
    return "\n".join(lines) + "\n"


def _publish(
    config: PipelineConfig,
    *,
    symbol: str = BTC,
    bodies: dict[tuple[int, int], str] | None = None,
) -> FakeFetcher:
    from hft_crypto.data.sources import monthly_candle_file

    fetcher = FakeFetcher()
    for year, month, days in MONTHS:
        target = monthly_candle_file(config, "binance", symbol, dt.date(year, month, 1))
        text = (bodies or {}).get((year, month)) or _month_csv(year, month, days)
        fetcher.publish(
            target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
        )
    return fetcher


@pytest.fixture
def one_quarter(monkeypatch: pytest.MonkeyPatch) -> PipelineConfig:
    """One symbol over one quarter, as a smaller frozen list, so a test is not months of generated rows."""
    from hft_crypto.data import coverage

    monkeypatch.setitem(coverage.FROZEN_LISTS, "closed-dates", _ONE_QUARTER)
    return replace(_shipped_on(), symbols=(BTC,))


def _run(config: PipelineConfig, root: Path, fetcher: FakeFetcher) -> dict[str, Any]:
    from hft_crypto.data.coverage import run_coverage_check

    return run_coverage_check(
        root,
        config,
        fetcher,
        venue="binance",
        list_name="closed-dates",
        now=lambda: NOW,
        sleep=lambda _: None,
    )


def test_a_clean_quarter_passes_and_only_the_list_leaves(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    from hft_crypto.data.coverage import QUARTER_TYPES, TOP_LEVEL_TYPES

    root = _check_root(tmp_path / "check")
    document = _run(one_quarter, root, _publish(one_quarter))
    written = (root / "coverage" / "coverage_check.json").read_text(encoding="utf-8")
    assert json.loads(written) == document
    assert set(document) == set(TOP_LEVEL_TYPES)
    row = document["quarters"][0]
    assert set(row) == set(QUARTER_TYPES)
    assert (row["quarter"], row["symbol"]) == ("2024-Q1", BTC)
    assert row["files"] == row["files_checksum_ok"] == 3
    assert row["rows"] == 91 * 1440
    assert row["empty_minutes_unproved"] == 0
    assert row["empty_minutes_proved"] == 0
    assert row["row_checks_pass"] is True
    assert row["passes"] is True
    assert document["stopped"] == "none"


def _walk_floats(value: Any) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [item for inner in value.values() for item in _walk_floats(inner)]
    if isinstance(value, list):
        return [item for inner in value for item in _walk_floats(inner)]
    return []


def test_nothing_read_from_a_row_leaves_it(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    root = _check_root(tmp_path / "check")
    document = _run(one_quarter, root, _publish(one_quarter))
    written = (root / "coverage" / "coverage_check.json").read_text(encoding="utf-8")
    assert _walk_floats(document) == []
    for word in ("12345", "30864", "18518", "2.5", "1.5"):
        assert word not in written.replace(document["file_list_sha256"], "").replace(
            document["code_version"], ""
        )
    for name in ("volume", "price", "open", "close", "high", "low", "trade_count", "funding", "stamp"):
        assert f'"{name}"' not in written


def test_the_tree_after_a_run_holds_only_the_declared_paths(
    tmp_path: Path, one_quarter: PipelineConfig
) -> None:
    root = _check_root(tmp_path / "check")
    _run(one_quarter, root, _publish(one_quarter))
    found = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    wanted = {"ROOT_KIND", "coverage/coverage_check.json"}
    for year, month, _ in MONTHS:
        name = f"{BTC}-1m-{year}-{month:02d}.zip"
        folder = f"raw/archive/binance/klines/{BTC}/date={year}-{month:02d}-01"
        wanted |= {f"{folder}/{name}", f"{folder}/{name}.CHECKSUM"}
    assert set(found) == wanted
    assert not (root / "curated").exists()


def test_the_schema_check_refuses_anything_off_the_list() -> None:
    from hft_crypto.data.coverage import check_output
    from hft_crypto.data.parsers import ValidationError

    good_row = {
        "quarter": "2024-Q1",
        "symbol": BTC,
        "files": 3,
        "files_checksum_ok": 3,
        "rows": 1,
        "empty_minutes_unproved": 0,
        "empty_minutes_proved": 0,
        "row_checks_pass": True,
        "passes": True,
    }
    good = {
        "check": "x",
        "code_version": "x",
        "run_at": "x",
        "file_list_sha256": "x",
        "stopped": "none",
        "quarters": [good_row],
    }
    check_output(good)
    for bad in (
        {**good, "note": "x"},
        {key: value for key, value in good.items() if key != "check"},
        {**good, "quarters": [{**good_row, "close": 100.0}]},
        {**good, "quarters": [{**good_row, "rows": 1.0}]},
        {**good, "quarters": [{**good_row, "passes": 1}]},
        {**good, "quarters": [{**good_row, "files": True}]},
        {**good, "quarters": [{key: value for key, value in good_row.items() if key != "rows"}]},
    ):
        with pytest.raises(ValidationError):
            check_output(bad)


def test_a_planted_row_error_flips_a_flag_and_no_row_reaches_any_output(
    tmp_path: Path, one_quarter: PipelineConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _check_root(tmp_path / "check")
    fetcher = _publish(one_quarter, bodies={(2024, 2): _month_csv(2024, 2, 29, bad_row=True)})
    document = _run(one_quarter, root, fetcher)
    row = document["quarters"][0]
    assert row["row_checks_pass"] is False
    # A flagged minute is not a coverage failure on its own.
    assert row["passes"] is True
    captured = capsys.readouterr()
    assert "12345" not in captured.out + captured.err


def test_a_file_that_cannot_be_read_fails_its_quarter_with_no_reason_from_the_row(
    tmp_path: Path, one_quarter: PipelineConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _check_root(tmp_path / "check")
    broken = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,x,y\nnot,a,row\n"
    )
    document = _run(one_quarter, root, _publish(one_quarter, bodies={(2024, 2): broken}))
    row = document["quarters"][0]
    assert row["passes"] is False
    assert row["row_checks_pass"] is False
    written = (root / "coverage" / "coverage_check.json").read_text(encoding="utf-8")
    assert "not,a,row" not in written
    captured = capsys.readouterr()
    assert "not,a,row" not in captured.out + captured.err


def test_missing_rows_over_one_percent_fail_and_zero_rows_count_as_proved(
    tmp_path: Path, one_quarter: PipelineConfig
) -> None:
    root = _check_root(tmp_path / "check")
    expected = 91 * 1440
    missing = int(expected * 0.011)
    zero = _month_csv(2024, 1, 31).splitlines()
    zero[1] = zero[1].replace(",2.5,", ",0.0,").replace(",5,1.5,", ",0,0.0,")
    bodies = {(2024, 3): _month_csv(2024, 3, 31, skip=missing), (2024, 1): "\n".join(zero) + "\n"}
    row = _run(one_quarter, root, _publish(one_quarter, bodies=bodies))["quarters"][0]
    assert row["empty_minutes_unproved"] == missing
    assert row["empty_minutes_proved"] == 1
    assert row["passes"] is False


def test_just_under_one_percent_missing_passes(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    root = _check_root(tmp_path / "check")
    missing = int(91 * 1440 * 0.009)
    bodies = {(2024, 3): _month_csv(2024, 3, 31, skip=missing)}
    row = _run(one_quarter, root, _publish(one_quarter, bodies=bodies))["quarters"][0]
    assert row["empty_minutes_unproved"] == missing
    assert row["passes"] is True


def test_too_few_trades_an_hour_fail_and_the_count_does_not_leave(
    tmp_path: Path, one_quarter: PipelineConfig
) -> None:
    """One trade a minute is 60 an hour, under the 100 of plan section 2."""
    root = _check_root(tmp_path / "check")
    bodies = {(year, month): _month_csv(year, month, days, count=1) for year, month, days in MONTHS}
    row = _run(one_quarter, root, _publish(one_quarter, bodies=bodies))["quarters"][0]
    assert row["passes"] is False
    assert not [key for key in row if "hour" in key or "trade" in key]


def test_a_month_that_is_not_published_fails_its_quarter(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    from hft_crypto.data.sources import monthly_candle_file

    fetcher = _publish(one_quarter)
    target = monthly_candle_file(one_quarter, "binance", BTC, dt.date(2024, 2, 1))
    del fetcher.files[target.url]
    row = _run(one_quarter, _check_root(tmp_path / "check"), fetcher)["quarters"][0]
    assert row["files"] == 2
    assert row["passes"] is False


def test_a_quarter_with_no_file_says_no_row_check_passed(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    row = _run(one_quarter, _check_root(tmp_path / "check"), FakeFetcher())["quarters"][0]
    assert row["files"] == 0
    assert row["rows"] == 0
    assert row["row_checks_pass"] is False
    assert row["passes"] is False


def test_an_error_nobody_planned_for_quotes_no_row(
    tmp_path: Path,
    one_quarter: PipelineConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plan section 3 counts a log as a read, and Actions logs are public."""

    def quoting(*_: object, **__: object) -> None:
        raise RuntimeError(f"could not read the row with price {PRICE}")

    monkeypatch.setattr("hft_crypto.data.coverage.parse_klines", quoting)
    root = _check_root(tmp_path / "check")
    row = _run(one_quarter, root, _publish(one_quarter))["quarters"][0]
    assert row["passes"] is False
    captured = capsys.readouterr()
    written = (root / "coverage" / "coverage_check.json").read_text(encoding="utf-8")
    assert str(PRICE) not in captured.out + captured.err + written


def test_a_checksum_mismatch_fails_its_quarter_and_is_never_parsed(
    tmp_path: Path, one_quarter: PipelineConfig
) -> None:
    from hft_crypto.data.sources import monthly_candle_file

    fetcher = _publish(one_quarter)
    target = monthly_candle_file(one_quarter, "binance", BTC, dt.date(2024, 2, 1))
    fetcher.files[target.url] = fetcher.files[target.url] + b"x"
    row = _run(one_quarter, _check_root(tmp_path / "check"), fetcher)["quarters"][0]
    assert row["files"] == 3
    assert row["files_checksum_ok"] == 2
    assert row["rows"] == 62 * 1440
    assert row["passes"] is False


def test_a_refusal_by_the_host_stops_the_job_with_a_fixed_code(
    tmp_path: Path, one_quarter: PipelineConfig
) -> None:
    from hft_crypto.data.fetch import FetchError
    from hft_crypto.data.sources import monthly_candle_file

    fetcher = _publish(one_quarter)
    target = monthly_candle_file(one_quarter, "binance", BTC, dt.date(2024, 2, 1))
    fetcher.failures[target.url] = FetchError("403 and any words the host chose")
    document = _run(one_quarter, _check_root(tmp_path / "check"), fetcher)
    assert document["stopped"] == "fetch_refused"
    assert document["quarters"][0]["passes"] is False
    # It stopped there, and did not go round it.
    march = monthly_candle_file(one_quarter, "binance", BTC, dt.date(2024, 3, 1))
    assert march.url not in fetcher.requests
    assert "any words" not in json.dumps(document)


def test_the_check_paces_itself_as_the_terms_ask(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    from hft_crypto.data.coverage import MIN_REQUEST_GAP_S, run_coverage_check

    waits: list[float] = []
    run_coverage_check(
        _check_root(tmp_path / "check"),
        one_quarter,
        _publish(one_quarter),
        venue="binance",
        list_name="closed-dates",
        now=lambda: NOW,
        sleep=waits.append,
    )
    assert waits == [MIN_REQUEST_GAP_S] * 6
    assert MIN_REQUEST_GAP_S >= 2.0


def test_the_frozen_lists_are_the_declared_files_and_no_flag_widens_them(tmp_path: Path) -> None:
    from hft_crypto.data.coverage import FROZEN_LISTS, file_list_sha256, frozen_file_list

    config = _shipped_on()
    closed = frozen_file_list(config, "binance", "closed-dates")
    assert len(closed) == 66
    assert closed[0][2].filename == f"{BTC}-1m-2024-01.zip"
    assert closed[-1][2].filename == "ETHUSDT-1m-2026-09.zip"
    assert closed[0][2].url == (
        f"https://data.binance.vision/data/futures/um/monthly/klines/{BTC}/1m/{BTC}-1m-2024-01.zip"
    )
    assert len(frozen_file_list(config, "binance", "first-span")) == 96
    assert file_list_sha256(closed) == file_list_sha256(frozen_file_list(config, "binance", "closed-dates"))
    assert set(FROZEN_LISTS) == {"closed-dates", "first-span"}


def test_every_file_on_a_frozen_list_is_on_the_approved_route() -> None:
    from hft_crypto.data.coverage import frozen_file_list
    from hft_crypto.data.fetch import check_url

    config = _shipped_on()
    for name in ("closed-dates", "first-span"):
        for _, _, target in frozen_file_list(config, "binance", name):
            check_url(target.url, config.enabled_hosts())
            assert target.checksum_url is not None
            check_url(target.checksum_url, config.enabled_hosts())


def test_with_the_source_off_the_check_does_not_run_and_contacts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from hft_crypto.config import ConfigError
    from hft_crypto.data.coverage import run_coverage_check

    root = _check_root(tmp_path / "check")
    fetcher = FakeFetcher()
    with pytest.raises(ConfigError, match="not approved and enabled"):
        run_coverage_check(
            root, base_config(), fetcher, venue="binance", list_name="closed-dates", now=lambda: NOW
        )
    assert fetcher.requests == []
    args = ["--config-dir", str(REPO_ROOT / "configs")]
    assert (
        main([*args, "coverage-check", "--list", "closed-dates", "--check-root", str(tmp_path / "other")])
        == 2
    )
    assert "not approved and enabled" in capsys.readouterr().err
    assert not (tmp_path / "other").exists()


def test_the_check_runs_only_in_a_check_root(tmp_path: Path, one_quarter: PipelineConfig) -> None:
    from hft_crypto.data.coverage import run_coverage_check
    from hft_crypto.data.zones import DataRootError

    plain = tmp_path / "plain"
    plain.mkdir()
    fetcher = FakeFetcher()
    with pytest.raises(DataRootError, match="check-only"):
        run_coverage_check(
            plain, one_quarter, fetcher, venue="binance", list_name="closed-dates", now=lambda: NOW
        )
    assert fetcher.requests == []


def test_the_command_needs_a_named_root_and_a_declared_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CHECK_ROOT", raising=False)
    args = ["--config-dir", str(REPO_ROOT / "configs")]
    assert main([*args, "coverage-check", "--list", "closed-dates"]) == 2
    assert "CHECK_ROOT" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([*args, "coverage-check", "--list", "all-dates", "--check-root", str(tmp_path / "x")])
    with pytest.raises(SystemExit):
        main([*args, "coverage-check", "--list", "closed-dates", "--last-month", "2030-01"])


def test_the_coverage_module_reads_no_stored_data_and_builds_no_bars() -> None:
    text = (REPO_ROOT / "src" / "hft_crypto" / "data" / "coverage.py").read_text(encoding="utf-8")
    for word in (
        "read_parquet",
        "scan_parquet",
        "curated_part",
        "aggregate_bars",
        "bars_from_official",
        "derive_day",
    ):
        assert word not in text


def test_python_can_start_with_the_marker_module_alone() -> None:
    """The guard's child hook must not disturb a plain child. A smoke test for the suite's own setup."""
    done = subprocess.run(
        [sys.executable, "-c", "print(1)"], capture_output=True, text=True, check=False, timeout=60
    )
    assert done.stdout.strip() == "1"


# ---- condition 2: the command, which runs later on the declared sample days
# ----------------------------------------------------------


SAMPLE = dt.date(2021, 3, 15)


def _agg_csv(day: dt.date, *, first_id: int, price: float = PRICE) -> str:
    """A row a minute: one fill, and every fifth a row of three fills, 200 ms long, across the next
    boundary."""
    start = day_start_us(day) // 1000
    lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
    fill = first_id
    for minute in range(1440):
        stamp = start + minute * 60_000
        count = 3 if minute % 5 == 4 else 1
        at = stamp + 59_900 if count == 3 else stamp + 30_000
        maker = "true" if minute % 10 == 4 else "false"
        lines.append(f"{fill},{price},{count * 2.5},{fill},{fill + count - 1},{at},{maker}")
        fill += count
    return "\n".join(lines) + "\n"


def _month_candles_csv(day: dt.date, *, price: float = PRICE) -> str:
    """Candles of the sample day alone, built by each fill's own stamp from the rows above."""
    start = day_start_us(day) // 1000
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
        "taker_buy_quote_volume,ignore"
    ]
    fills = [0] * 1441
    buys = [0] * 1441
    for minute in range(1440):
        if minute % 5 == 4:
            taker = minute % 10 != 4
            fills[minute] += 1
            fills[minute + 1] += 2
            buys[minute] += 1 if taker else 0
            buys[minute + 1] += 2 if taker else 0
        else:
            fills[minute] += 1
            buys[minute] += 1
    # The day before ends on a row of three fills at 23:59:59.900, so two of them land in the first minute.
    fills[0] += 2
    buys[0] += 2
    for minute in range(1440):
        stamp = start + minute * 60_000
        volume = fills[minute] * 2.5
        bought = buys[minute] * 2.5
        lines.append(
            f"{stamp},{price},{price},{price},{price},{volume},{stamp + 59_999},{volume * price},"
            f"{fills[minute]},{bought},{bought * price},0"
        )
    return "\n".join(lines) + "\n"


def _publish_sample(
    config: PipelineConfig, day: dt.date = SAMPLE, *, candles: str | None = None
) -> FakeFetcher:
    from hft_crypto.data.sources import archive_candidates, monthly_candle_file

    fetcher = FakeFetcher()
    spec = config.dataset("binance.aggTrades")
    # The day before's file ends in a row across midnight, as every fifth minute does.
    for when, first in ((day - dt.timedelta(days=1), 1_000_000), (day, 2_000_000)):
        target = archive_candidates(config, spec, BTC, when)[0]
        text = _agg_csv(when, first_id=first)
        fetcher.publish(
            target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
        )
    month = monthly_candle_file(config, "binance", BTC, day.replace(day=1))
    fetcher.publish(
        month.url,
        zip_bytes(month.filename.replace(".zip", ".csv"), candles or _month_candles_csv(day)),
        name=month.filename,
    )
    return fetcher


def _run_candle(
    config: PipelineConfig, root: Path, fetcher: FakeFetcher, days: tuple[dt.date, ...] = (SAMPLE,)
) -> Any:
    from hft_crypto.data.coverage import run_candle_check

    return run_candle_check(
        root, config, fetcher, venue="binance", days=days, now=lambda: NOW, sleep=lambda _: None
    )


def _one_symbol() -> PipelineConfig:
    return replace(_shipped_on(), symbols=(BTC,))


def test_the_command_reads_the_files_and_gives_a_flag_per_symbol_and_day(tmp_path: Path) -> None:
    config = _one_symbol()
    root = _check_root(tmp_path / "check")
    document = _run_candle(config, root, _publish_sample(config))
    assert document["days"] == [{"day": "2021-03-15", "symbol": BTC, "result": "PASS", "code": "ok"}]
    assert document["symbols"] == [
        {"symbol": BTC, "days_pass": 1, "days_fail": 0, "days_inconclusive": 0, "shown": False}
    ]
    written = (root / "coverage" / "candle_check.json").read_text(encoding="utf-8")
    assert json.loads(written) == document
    assert _walk_floats(document) == []
    assert "12345" not in written


def test_a_planted_excess_fails_through_the_command_and_quotes_nothing(tmp_path: Path) -> None:
    config = _one_symbol()
    lines = _month_candles_csv(SAMPLE).splitlines()
    fields = lines[100].split(",")
    fields[5] = str(float(fields[5]) + 2.5)
    fields[9] = str(float(fields[9]) + 2.5)
    fields[8] = str(int(fields[8]) + 1)
    lines[100] = ",".join(fields)
    root = _check_root(tmp_path / "check")
    fetcher = _publish_sample(config, candles="\n".join(lines) + "\n")
    document = _run_candle(config, root, fetcher)
    assert document["days"][0]["result"] == "FAIL"
    assert document["days"][0]["code"].startswith("step")
    assert document["symbols"][0]["days_fail"] == 1
    assert document["symbols"][0]["shown"] is False
    written = (root / "coverage" / "candle_check.json").read_text(encoding="utf-8")
    assert "12345" not in written
    assert "2.5" not in written.replace(document["code_version"], "")


def test_the_tree_after_the_command_holds_raw_files_and_one_output_and_no_bars(tmp_path: Path) -> None:
    config = _one_symbol()
    root = _check_root(tmp_path / "check")
    _run_candle(config, root, _publish_sample(config))
    found = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    assert "ROOT_KIND" in found
    assert "coverage/candle_check.json" in found
    assert {name.split("/")[0] for name in found} == {"ROOT_KIND", "coverage", "raw"}
    assert not [name for name in found if name.endswith(".parquet")]


def test_a_missing_or_altered_file_drops_its_day_by_name_and_nothing_takes_its_place(tmp_path: Path) -> None:
    from hft_crypto.data.sources import archive_candidates

    config = _one_symbol()
    target = archive_candidates(config, config.dataset("binance.aggTrades"), BTC, SAMPLE)[0]
    gone = _publish_sample(config)
    del gone.files[target.url]
    del gone.files[target.checksum_url or ""]
    first = _run_candle(config, _check_root(tmp_path / "one"), gone)["days"][0]
    assert (first["result"], first["code"]) == ("INCONCLUSIVE", "file_missing")
    altered = _publish_sample(config)
    altered.files[target.url] = altered.files[target.url] + b"x"
    second = _run_candle(config, _check_root(tmp_path / "two"), altered)["days"][0]
    assert (second["result"], second["code"]) == ("INCONCLUSIVE", "file_unreadable")


def test_a_refusal_stops_the_command_with_a_fixed_code(tmp_path: Path) -> None:
    from hft_crypto.data.fetch import FetchError
    from hft_crypto.data.sources import archive_candidates

    config = _one_symbol()
    fetcher = _publish_sample(config)
    target = archive_candidates(config, config.dataset("binance.aggTrades"), BTC, SAMPLE)[0]
    fetcher.failures[target.url] = FetchError("429 and any words the host chose")
    document = _run_candle(config, _check_root(tmp_path / "check"), fetcher)
    assert document["stopped"] == "fetch_refused"
    assert document["days"] == []
    assert "any words" not in json.dumps(document)


def test_one_month_of_candles_is_fetched_once_for_its_sample_days(tmp_path: Path) -> None:
    from hft_crypto.data.sources import monthly_candle_file

    config = _one_symbol()
    fetcher = _publish_sample(config)
    month = monthly_candle_file(config, "binance", BTC, SAMPLE.replace(day=1))
    _run_candle(config, _check_root(tmp_path / "check"), fetcher)
    assert fetcher.requests.count(month.url) == 1
    assert all("BTCUSDT-aggTrades-2021-03-1" in url or "-1m-2021-03" in url for url in fetcher.requests)


def test_the_days_are_the_declared_15ths_and_no_others() -> None:
    from hft_crypto.config import ConfigError
    from hft_crypto.data.coverage import declared_days

    assert len(declared_days("declared")) == 48
    assert declared_days("2020-01-15,2021-06-15") == (dt.date(2020, 1, 15), dt.date(2021, 6, 15))
    for bad in ("2020-01-14", "2020-01-15,2020-01-15", "soon"):
        with pytest.raises(ConfigError):
            declared_days(bad)


def test_the_candle_check_output_schema_refuses_anything_off_the_list() -> None:
    from hft_crypto.data.coverage import check_candle_output
    from hft_crypto.data.parsers import ValidationError

    day = {"day": "2021-03-15", "symbol": BTC, "result": "PASS", "code": "ok"}
    symbol = {"symbol": BTC, "days_pass": 1, "days_fail": 0, "days_inconclusive": 0, "shown": False}
    good = {
        "check": "x",
        "code_version": "x",
        "run_at": "x",
        "days_sha256": "x",
        "stopped": "none",
        "days": [day],
        "symbols": [symbol],
    }
    check_candle_output(good)
    for bad in (
        {**good, "note": "x"},
        {**good, "days": [{**day, "volume": 1.0}]},
        {**good, "days": [{**day, "code": "the row said 12345.678"}]},
        {**good, "days": [{**day, "result": "MAYBE"}]},
        {**good, "symbols": [{**symbol, "days_pass": 1.0}]},
        {**good, "symbols": [{**symbol, "shown": 1}]},
    ):
        with pytest.raises(ValidationError):
            check_candle_output(bad)


def test_the_command_refuses_with_the_source_off_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--config-dir", str(REPO_ROOT / "configs")]
    command = [*args, "candle-check", "--days", "declared", "--check-root", str(tmp_path / "x")]
    assert main(command) == 2
    assert "not approved and enabled" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
    bad_day = [*args, "candle-check", "--days", "2020-01-14", "--check-root", str(tmp_path / "x")]
    assert main(bad_day) == 2
    assert "15th" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


def test_the_output_of_the_candle_check_alone_marks_a_root_nothing_may_open(tmp_path: Path) -> None:
    from hft_crypto.data.zones import DataRoot, DataRootError

    target = tmp_path / "lost-marker"
    (target / "coverage").mkdir(parents=True)
    (target / "coverage" / "candle_check.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DataRootError):
        DataRoot(target, create=False)


def test_the_check_sets_nothing_so_ideal_stays_off_until_someone_with_the_evidence_says(
    tmp_path: Path,
) -> None:
    config = _one_symbol()
    _run_candle(config, _check_root(tmp_path / "check"), _publish_sample(config))
    assert config.source("binance").candle_check == "not_shown"
    assert config.source("binance").ideal_allowed is False
