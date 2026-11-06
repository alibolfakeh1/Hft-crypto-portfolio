"""The tier T0 path on the shipped configuration, switched on in memory, with a fake fetcher behind the real
addresses.

Candles and funding on the approved route, through the file parsers, bars under ruling 7, the reader and the
report. All files are generated, and all prices are invented. Nothing here reaches a network.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from helpers import (
    FakeFetcher,
    base_config,
    make_context,
    policy_with_raw_reviewed,
    with_binance_enabled,
    zip_bytes,
)
from hft_crypto.bars.core import SOURCE_OFFICIAL, DateGuardError
from hft_crypto.config import PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import day_is_usable, derive_day, official_dataset
from hft_crypto.data.fetch import check_url
from hft_crypto.data.health import build_health
from hft_crypto.data.ingest import IngestOptions, Task, plan_tasks, run_ingest
from hft_crypto.data.parsers import ValidationError, parse_klines
from hft_crypto.data.reader import MarketReader, RunClock
from hft_crypto.data.sources import archive_candidates
from hft_crypto.reports.report import build_benchmark, write_report
from hft_crypto.timeutil import day_start_us, to_us

BTC = "BTCUSDT"
NOW = dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC)
NOV = dt.date(2023, 11, 1)
DEC = dt.date(2023, 12, 1)
ROUTE = "https://data.binance.vision/data/futures/um"
ATTRIBUTION = "CC BY-NC-SA 4.0"


def _config(*, last_opened: dt.date | None = None) -> PipelineConfig:
    base = with_binance_enabled(base_config(), last_opened_date=last_opened)
    datasets = tuple(replace(spec, start=NOV) for spec in base.datasets)
    return replace(
        base,
        datasets=datasets,
        symbols=(BTC,),
        timeframes_minutes=(60, 1440),
        report=replace(base.report, benchmark_venue="binance", benchmark_symbols=(BTC,), span_start=NOV),
    )


def _days_in(month: dt.date) -> int:
    following = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (following - month).days


def _candles_csv(month: dt.date, *, price: float = 100.0, days: int | None = None) -> str:
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
        "taker_buy_quote_volume,ignore"
    ]
    start_ms = day_start_us(month) // 1000
    for minute in range((days or _days_in(month)) * 1440):
        stamp = start_ms + minute * 60_000
        lines.append(f"{stamp},{price},{price},{price},{price},2.0,{stamp + 59_999},200.0,3,1.0,100.0,0")
    return "\n".join(lines) + "\n"


def _funding_csv(month: dt.date) -> str:
    start_ms = day_start_us(month) // 1000
    lines = ["calc_time,funding_interval_hours,last_funding_rate"]
    for step in range(_days_in(month) * 3):
        lines.append(f"{start_ms + step * 28_800_000},8,0.0001")
    return "\n".join(lines) + "\n"


def _publish(fetcher: FakeFetcher, config: PipelineConfig, month: dt.date, *, price: float = 100.0) -> None:
    for dataset, text in (
        ("binance.klines", _candles_csv(month, price=price)),
        ("binance.fundingRate", _funding_csv(month)),
    ):
        target = archive_candidates(config, config.dataset(dataset), BTC, month)[0]
        fetcher.publish(
            target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
        )


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> JobContext:
    config = _config()
    fetcher = FakeFetcher()
    _publish(fetcher, config, NOV, price=100.0)
    _publish(fetcher, config, DEC, price=110.0)
    ctx = make_context(
        tmp_path_factory.mktemp("candles") / "r", now=NOW, config=config, policy=policy_with_raw_reviewed()
    )
    summary = run_ingest(ctx, fetcher, IngestOptions(delete_raw=True))
    assert summary.errors == []
    ctx.fetcher_requests = list(fetcher.requests)  # type: ignore[attr-defined]
    return ctx


def test_it_asks_only_for_monthly_candles_and_funding_on_the_route(built: JobContext) -> None:
    requests = built.fetcher_requests  # type: ignore[attr-defined]
    assert sorted(requests) == sorted(
        f"{ROUTE}/monthly/{kind}/{BTC}/{middle}{BTC}-{name}-{month}.zip{tail}"
        for kind, middle, name in (("klines", "1m/", "1m"), ("fundingRate", "", "fundingRate"))
        for month in ("2023-11", "2023-12")
        for tail in ("", ".CHECKSUM")
    )
    for url in requests:
        check_url(url, built.config.enabled_hosts())


def test_no_trades_are_fetched_or_stored(built: JobContext) -> None:
    assert not [url for url in built.fetcher_requests if "aggTrades" in url]  # type: ignore[attr-defined]
    assert built.root.curated_parts("trades", "binance", BTC) == []


def test_these_bars_have_datasets_of_their_own(built: JobContext) -> None:
    """Ruling 7: separate names mean they can never be read as trade-built bars."""
    assert len(built.root.curated_parts("bars_1m_official", "binance", BTC)) == 61
    assert len(built.root.curated_parts("bars_1h_official", "binance", BTC)) == 61
    assert len(built.root.curated_parts("bars_1d_official", "binance", BTC)) == 61
    for name in ("bars_1m", "bars_1h", "bars_1d"):
        assert built.root.curated_parts(name, "binance", BTC) == []


def test_each_bar_states_its_source_its_boundary_and_when_it_is_known(built: JobContext) -> None:
    part = built.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 11, 15))
    bars = read_parquet(part)
    assert bars.height == 1440
    assert bars["bar_source"].unique().to_list() == [SOURCE_OFFICIAL]
    assert bars["boundary"].unique().to_list() == ["[open, close)"]
    spread = bars["close_time"].dt.timestamp("us") - bars["open_time"].dt.timestamp("us")
    assert spread.unique().to_list() == [60_000_000]
    # Close plus the candle allowance, which is its own key, and not the trade rows' 250 ms.
    known = bars["knowable_time"].dt.timestamp("us") - bars["close_time"].dt.timestamp("us")
    assert known.unique().to_list() == [1_000_000]
    assert bars["gap"].sum() == 0
    # The curated candles say the same, and they do not use the trade rows' allowance.
    candles = read_parquet(built.root.curated_month_part("candles_official", "binance", BTC, NOV))
    spread = candles["knowable_time"].dt.timestamp("us") - candles["open_time"].dt.timestamp("us")
    assert spread.unique().to_list() == [61_000_000]


def test_reconciliation_says_not_available_and_never_passed(built: JobContext) -> None:
    rows = built.catalog.reconciliations("official_candles")
    assert len(rows) == 61
    assert {row["status"] for row in rows} == {"not_available"}
    record = built.catalog.get_file(
        built.relative(built.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 11, 15)))
    )
    assert record is not None
    assert record.check_status == "unreconciled"
    assert record.check_detail is not None
    assert record.check_detail["bar_source"] == SOURCE_OFFICIAL


def test_a_month_of_raw_candles_goes_once_its_curated_file_passes(built: JobContext) -> None:
    left = [path.name for path in built.root.guard.check("raw/archive").rglob("*") if path.is_file()]
    assert left == []


def test_the_reader_serves_them_through_the_route_with_funding(built: JobContext) -> None:
    reader = MarketReader(built.root, built.config)
    midnight = day_start_us(dt.date(2023, 12, 1))
    clock = RunClock(midnight, midnight + 1_000_000)
    rows = reader.candles("binance", BTC, clock)
    assert rows.height == 30 * 1440
    assert rows["bar_source"].unique().to_list() == [SOURCE_OFFICIAL]
    funding = reader.funding("binance", BTC, clock)
    # 30 days of three settlements, and the one exactly at the cut.
    assert funding.height == 30 * 3 + 1
    hourly = reader.candles("binance", BTC, clock, minutes=60)
    assert hourly.height == 30 * 24


def test_the_report_covers_the_span_with_the_credit_and_the_guard_stated(
    built: JobContext, tmp_path: Path
) -> None:
    status = write_report(built, out_dir=tmp_path / "out")
    item = status["benchmarks"][BTC]
    assert item["days_used"] == 61
    assert item["days_in_span"] == 61
    assert item["days_excluded"] == 0
    assert item["end"].startswith("2024-01-01T00:00:00")
    assert item["total_return"] == pytest.approx(0.10)
    assert status["last_opened_date"] == "2023-12-31"
    assert status["last_opened_decision"] == "D-34"
    official = status["reconciliation"]["official_candles"]
    assert official["not_available"] == 61
    assert official["pass"] == 0
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "Reconciliation is not available on 61 symbol-days" in html
    assert "2023-12-31" in html
    assert ATTRIBUTION in html
    assert "Not associated with or endorsed by Binance" in html
    assert any(ATTRIBUTION in line for line in status["attributions"])
    published = (tmp_path / "out" / "results" / "status.json").read_text(encoding="utf-8")
    assert ATTRIBUTION in published
    logged = (tmp_path / "out" / "results" / "run_log" / "pipeline_runs.jsonl").read_text(encoding="utf-8")
    assert ATTRIBUTION in json.loads(logged.splitlines()[-1])["attributions"][0]


def test_health_counts_a_monthly_file_by_the_days_its_bars_cover(built: JobContext) -> None:
    report = build_health(built.root, built.catalog, built.config, built.policy, NOW)
    row = next(item for item in report["bars_coverage"] if item["symbol"] == BTC)
    assert row["expected"] == 61
    assert row["final"] == 61
    assert row["dataset"] == "bars_1m.binance"
    # And the files themselves, by the month.
    files = next(item for item in report["coverage"] if item["dataset"] == "binance.klines")
    assert files["expected"] == 2
    assert files["done"] == 2
    assert files["last_done"] == "2023-12"


def test_a_candle_file_that_changes_rebuilds_only_its_own_days(tmp_path: Path) -> None:
    config = _config()
    fetcher = FakeFetcher()
    _publish(fetcher, config, NOV)
    _publish(fetcher, config, DEC)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    run_ingest(ctx, fetcher, IngestOptions())
    first_dec = ctx.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 12, 5)).read_bytes()
    from hft_crypto.data.derive import reopen_day

    reopen_day(ctx, "binance", BTC, dt.date(2023, 11, 5))
    summary = run_ingest(ctx, fetcher, IngestOptions())
    assert summary.errors == []
    assert (
        ctx.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 12, 5)).read_bytes()
        == first_dec
    )


def test_a_rebuilt_day_is_byte_identical(tmp_path: Path) -> None:
    config = _config()
    fetcher = FakeFetcher()
    _publish(fetcher, config, NOV)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    run_ingest(ctx, fetcher, IngestOptions())
    day = dt.date(2023, 11, 5)
    part = ctx.root.curated_part(official_dataset(1), "binance", BTC, day)
    before = part.read_bytes()
    derive_day(ctx, "binance", BTC, day)
    assert part.read_bytes() == before


def _with_row_change(text: str, index: int, field: int, value: str) -> str:
    lines = text.splitlines()
    fields = lines[index + 1].split(",")
    fields[field] = value
    lines[index + 1] = ",".join(fields)
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [(2, "99.0"), (3, "101.0"), (9, "9.0")],
    ids=["high below", "low above", "taker above volume"],
)
def test_a_bad_row_flags_its_minute_and_warns_the_day_and_keeps_the_rest(
    tmp_path: Path, field: int, value: str
) -> None:
    """Ruling 7 condition 5. It used to refuse the whole file, which on a monthly file is a month for one
    minute."""
    config = _config()
    fetcher = FakeFetcher()
    target = archive_candidates(config, config.dataset("binance.klines"), BTC, NOV)[0]
    text = _with_row_change(_candles_csv(NOV), 1440 * 2 + 5, field, value)
    fetcher.publish(
        target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
    )
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    summary = run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines",)))
    assert summary.errors == []
    bad_day = dt.date(2023, 11, 3)
    bars = read_parquet(ctx.root.curated_part(official_dataset(1), "binance", BTC, bad_day))
    assert bars.height == 1440
    assert bars["gap"].to_list() == [minute == 5 for minute in range(1440)]
    record = ctx.catalog.get_file(
        ctx.relative(ctx.root.curated_part(official_dataset(1), "binance", BTC, bad_day))
    )
    assert record is not None
    assert record.check_status == "warn"
    # RA-01: the minute is flagged and the day says so. A flagged minute excludes nothing.
    assert record.check_detail is not None
    assert record.check_detail["flagged_minutes"] == 1
    assert record.check_detail["hole"] is False
    assert ctx.catalog.exclusions() == []
    other = ctx.catalog.get_file(
        ctx.relative(ctx.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 11, 4)))
    )
    assert other is not None
    assert other.check_status == "unreconciled"


def test_a_missing_row_is_a_gap_with_a_record(tmp_path: Path) -> None:
    config = _config()
    fetcher = FakeFetcher()
    target = archive_candidates(config, config.dataset("binance.klines"), BTC, NOV)[0]
    lines = _candles_csv(NOV).splitlines()
    del lines[1 + 1440 * 2 + 5]
    fetcher.publish(
        target.url,
        zip_bytes(target.filename.replace(".zip", ".csv"), "\n".join(lines) + "\n"),
        name=target.filename,
    )
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines",)))
    bars = read_parquet(ctx.root.curated_part(official_dataset(1), "binance", BTC, dt.date(2023, 11, 3)))
    missing = bars.filter(pl.col("gap"))
    assert missing.height == 1
    assert missing["empty_proof"].to_list() == ["none"]
    assert ctx.catalog.gaps(f"curated.candles_official.binance.{BTC}")


def test_what_cannot_be_a_candle_still_refuses_the_file(tmp_path: Path) -> None:
    """The file's own close field is checked and discarded (ruling 7). A wrong one means the format
    changed."""
    path = tmp_path / "k.zip"
    bad = _with_row_change(_candles_csv(NOV, days=1), 3, 6, "1")
    path.write_bytes(zip_bytes("k.csv", bad))
    with pytest.raises(ValidationError, match="close time"):
        parse_klines(path, BTC, NOV, 10**9, venue="binance", allowance_us=0)


def test_a_longer_file_is_read_as_its_period_and_a_day_as_its_day(tmp_path: Path) -> None:
    path = tmp_path / "k.zip"
    path.write_bytes(zip_bytes("k.csv", _candles_csv(NOV, days=2)))
    with pytest.raises(ValidationError, match="UTC day"):
        parse_klines(path, BTC, NOV, 10**9, venue="binance", allowance_us=0)
    result = parse_klines(
        path, BTC, NOV, 10**9, venue="binance", allowance_us=0, last_day=NOV + dt.timedelta(days=1)
    )
    assert result.frame.height == 2880
    assert result.checks["expected_rows"] == 2880


def test_each_row_of_a_file_is_known_at_its_close_plus_the_candle_allowance(tmp_path: Path) -> None:
    path = tmp_path / "k.zip"
    path.write_bytes(zip_bytes("k.csv", _candles_csv(NOV, days=1)))
    frame = parse_klines(path, BTC, NOV, 10**9, venue="binance", allowance_us=1_000_000).frame
    spread = frame["knowable_time"].dt.timestamp("us") - frame["open_time"].dt.timestamp("us")
    assert spread.unique().to_list() == [61_000_000]


def test_a_daily_dataset_works_the_same_way(tmp_path: Path) -> None:
    """Either file size gives the same bars, so the choice of monthly files is one line in the
    configuration."""
    monthly = _config()
    specs = tuple(
        replace(spec, granularity="day") if spec.id == "binance.klines" else spec for spec in monthly.datasets
    )
    daily = replace(monthly, datasets=specs)
    day = dt.date(2023, 11, 2)
    fetcher = FakeFetcher()
    start_ms = day_start_us(day) // 1000
    lines = _candles_csv(NOV, days=2).splitlines()
    wanted = [lines[0], *[line for line in lines[1:] if int(line.split(",")[0]) >= start_ms]]
    target = archive_candidates(daily, daily.dataset("binance.klines"), BTC, day)[0]
    assert re.search(r"/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2023-11-02\.zip$", target.url)
    fetcher.publish(
        target.url,
        zip_bytes(target.filename.replace(".zip", ".csv"), "\n".join(wanted) + "\n"),
        name=target.filename,
    )
    ctx = make_context(tmp_path / "d", now=NOW, config=daily)
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines",), start=day, end=day))
    from_day = read_parquet(ctx.root.curated_part(official_dataset(1), "binance", BTC, day))
    other = FakeFetcher()
    month_target = archive_candidates(monthly, monthly.dataset("binance.klines"), BTC, NOV)[0]
    other.publish(
        month_target.url,
        zip_bytes(month_target.filename.replace(".zip", ".csv"), _candles_csv(NOV)),
        name=month_target.filename,
    )
    second = make_context(tmp_path / "m", now=NOW, config=monthly)
    run_ingest(second, other, IngestOptions(dataset_ids=("binance.klines",)))
    assert from_day.equals(read_parquet(second.root.curated_part(official_dataset(1), "binance", BTC, day)))


def test_a_report_with_later_dates_on_disk_stops_at_the_last_opened_date(tmp_path: Path) -> None:
    """FP-01, the test the audit asks for. Unopened dates on disk, by whatever route, change no figure."""
    december_end = dt.date(2023, 12, 31)
    wide = _config(last_opened=dt.date(2099, 12, 31))
    fetcher = FakeFetcher()
    _publish(fetcher, wide, NOV, price=100.0)
    _publish(fetcher, wide, DEC, price=110.0)
    january = dt.date(2024, 1, 1)
    _publish(fetcher, wide, january, price=77777.0)
    holding = make_context(tmp_path / "with", now=NOW, config=wide)
    run_ingest(holding, fetcher, IngestOptions())
    assert (
        holding.root.curated_parts(official_dataset(1440), "binance", BTC)[-1].name
        == "part-2024-01-31.parquet"
    )
    # The same disk, and the guard back where it ships.
    guarded = replace(wide, last_opened_date=december_end)
    holding.config = guarded
    with_later = write_report(holding, out_dir=tmp_path / "out-with")

    fetcher_two = FakeFetcher()
    _publish(fetcher_two, guarded, NOV, price=100.0)
    _publish(fetcher_two, guarded, DEC, price=110.0)
    without = make_context(tmp_path / "without", now=NOW, config=guarded)
    run_ingest(without, fetcher_two, IngestOptions())
    without_later = write_report(without, out_dir=tmp_path / "out-without")

    first = with_later["benchmarks"][BTC]
    assert first == without_later["benchmarks"][BTC]
    assert first["end"].startswith("2024-01-01T00:00:00")
    assert first["total_return"] == pytest.approx(0.10)
    assert first["newest_day_provisional"] is False
    assert (
        with_later["reconciliation"]["official_candles"]
        == without_later["reconciliation"]["official_candles"]
    )
    html = (tmp_path / "out-with" / "site" / "index.html").read_text(encoding="utf-8")
    published = (tmp_path / "out-with" / "status.json").read_text(encoding="utf-8")
    for blob in (html, published):
        assert "77777" not in blob
        assert "2024-02" not in blob
    # The reader stops there too.
    reader = MarketReader(holding.root, guarded)
    moment = day_start_us(january) + 60_000_000
    with pytest.raises(DateGuardError):
        reader.candles("binance", BTC, RunClock(moment, moment + 1_000_000))


def test_the_shipped_plan_has_no_trade_dataset_in_stage_one(tmp_path: Path) -> None:
    """D-31: candles and funding only, unless a later stage names aggregate trades."""
    config = with_binance_enabled(base_config())
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    tasks: list[Task] = plan_tasks(ctx, IngestOptions())
    assert {task.spec.kind for task in tasks} == {"klines", "fundingRate"}
    light = plan_tasks(ctx, IngestOptions(include_book=False))
    assert {task.spec.kind for task in light} == {"klines", "fundingRate"}


# ---- RA-01: a flagged minute does not exclude a day --------------------------------------------------------


def _falling_month(*, drop: tuple[int, ...] = (), empty: tuple[int, ...] = ()) -> str:
    """Twelve days at 100, except the seventh, which falls to 75 and stays there. `drop` removes rows by
    minute, and `empty` makes a row a proved empty minute, with a count of zero.
    """
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
        "taker_buy_quote_volume,ignore"
    ]
    start_ms = day_start_us(NOV) // 1000
    for minute in range(12 * 1440):
        if minute in drop:
            continue
        day = minute // 1440
        price = 100.0 if day < 6 else 75.0
        if day == 6:
            price = 100.0 - 25.0 * (minute % 1440) / 1439.0
        # On the 0.01 grid: check K1 after the fetch stops stage one on a first-span price off it.
        price = round(price, 2)
        stamp = start_ms + minute * 60_000
        count = 0 if minute in empty else 3
        volume = 0.0 if minute in empty else 2.0
        close_ms = stamp + 59_999
        lines.append(
            f"{stamp},{price},{price},{price},{price},{volume},{close_ms},200.0,{count},{volume / 2},100.0,0"
        )
    return "\n".join(lines) + "\n"


def _ingest_month(tmp_path: Path, name: str, text: str) -> tuple[JobContext, PipelineConfig]:
    config = _config()
    fetcher = FakeFetcher()
    target = archive_candidates(config, config.dataset("binance.klines"), BTC, NOV)[0]
    fetcher.publish(
        target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
    )
    ctx = make_context(tmp_path / name, now=NOW, config=config)
    summary = run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines",)))
    assert summary.errors == []
    return ctx, config


def _benchmark(ctx: JobContext, config: PipelineConfig) -> Any:
    found, _ = build_benchmark(ctx.root, config, ctx.catalog, BTC, to_us(NOW))
    assert found is not None
    return found


FALL_DAY = 6  # the seventh day, counted from 0
_TAIL_DAYS = {(NOV + dt.timedelta(days=offset)).isoformat() for offset in range(12, 30)}


def _excluded(ctx: JobContext) -> set[str]:
    return {row["date"] for row in ctx.catalog.exclusions()}


MIDDAY = FALL_DAY * 1440 + 13 * 60 + 5


def test_ra01_the_auditor_s_case_one_missing_candle_leaves_the_benchmark_as_it_was(tmp_path: Path) -> None:
    """A fall of 25 percent on the seventh day, and one candle missing at 13:05 that day. Excluding the day
    took its one-day returns away and turned a Sharpe of about -4 into about +5. An outage is likely on a
    stressed day.
    """
    clean_ctx, config = _ingest_month(tmp_path, "clean", _falling_month())
    gapped_ctx, _ = _ingest_month(tmp_path, "gapped", _falling_month(drop=(MIDDAY,)))
    clean = _benchmark(clean_ctx, config)
    gapped = _benchmark(gapped_ctx, config)
    assert clean.stats["sharpe"] < 0
    for key in ("sharpe", "annualised_volatility", "total_return", "daily_returns"):
        assert gapped.stats[key] == pytest.approx(clean.stats[key])
    assert gapped.days_used == clean.days_used == 12
    # The file holds twelve days, so the rest of the month has no rows at all, and each of those is a hole.
    assert gapped.days_excluded == clean.days_excluded == len(_TAIL_DAYS)
    assert _excluded(gapped_ctx) == _TAIL_DAYS
    assert gapped.stats["minutes_flagged_in_days_used"] == 1
    assert clean.stats["minutes_flagged_in_days_used"] == 0


def test_ra01_the_day_states_its_flagged_minutes_and_warn_stays_as_an_alert(tmp_path: Path) -> None:
    ctx, _ = _ingest_month(tmp_path, "r", _falling_month(drop=(MIDDAY, MIDDAY + 1)))
    day = NOV + dt.timedelta(days=FALL_DAY)
    record = ctx.catalog.get_file(
        ctx.relative(ctx.root.curated_part(official_dataset(1), "binance", BTC, day))
    )
    assert record is not None
    assert record.check_status == "warn"
    assert record.check_detail is not None
    assert (record.check_detail["flagged_minutes"], record.check_detail["hole"]) == (2, False)


@pytest.mark.parametrize(
    "minute",
    [FALL_DAY * 1440, FALL_DAY * 1440 + 1439],
    ids=["the row giving its open", "the row giving its close"],
)
def test_ra01_a_day_is_a_hole_only_when_the_row_giving_its_open_or_close_is_missing(
    tmp_path: Path, minute: int
) -> None:
    ctx, config = _ingest_month(tmp_path, "r", _falling_month(drop=(minute,)))
    day = NOV + dt.timedelta(days=FALL_DAY)
    assert _excluded(ctx) == {day.isoformat(), *_TAIL_DAYS}
    found = _benchmark(ctx, config)
    assert found.days_used == 11
    assert found.days_excluded == 1 + len(_TAIL_DAYS)


def test_ra01_a_first_minute_proved_empty_is_no_hole_since_the_next_row_gives_the_open(
    tmp_path: Path,
) -> None:
    ctx, config = _ingest_month(tmp_path, "r", _falling_month(empty=(FALL_DAY * 1440,)))
    assert _excluded(ctx) == _TAIL_DAYS
    assert _benchmark(ctx, config).days_used == 12


def test_ra01_the_status_alone_decides_nothing_on_candles() -> None:
    assert day_is_usable("warn", {"hole": False, "flagged_minutes": 3}) is True
    assert day_is_usable("warn", {"hole": True, "flagged_minutes": 1}) is False
    assert day_is_usable("unreconciled", {"hole": False, "flagged_minutes": 0}) is True
    assert day_is_usable("fail", {"hole": False, "flagged_minutes": 0}) is False
    assert day_is_usable("provisional", {"hole": False}) is False
    # Bars from trades have no such detail, and there a warn is a disagreement over the whole day (F-04).
    assert day_is_usable("warn", {"reasons": []}) is False
    assert day_is_usable("pass", None) is True
