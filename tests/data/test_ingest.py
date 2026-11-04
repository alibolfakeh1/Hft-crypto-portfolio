"""Catch-up, idempotence, pending against overdue, quarantine and retry, all without a network."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from helpers import (
    BINANCE,
    FakeFetcher,
    base_config,
    make_context,
    make_day_files,
    publish_binance_day,
    with_sources_enabled,
    zip_bytes,
)
from hft_crypto.config import DatasetSpec, PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import timeframe_dataset
from hft_crypto.data.fetch import FetchError
from hft_crypto.data.ingest import IngestOptions, SourceDisabledError, plan_tasks, run_ingest
from hft_crypto.data.sources import expected_partitions
from hft_crypto.timeutil import day_start_us

BTC = "BTCUSDT"
TRADES_AND_CANDLES = ("binance.klines", "binance.aggTrades")


def small_config(start: dt.date) -> PipelineConfig:
    """The real configuration, with history starting close to the test's dates."""
    from dataclasses import replace

    config = base_config()
    datasets = tuple(replace(spec, start=start) for spec in config.datasets)
    return with_sources_enabled(replace(config, datasets=datasets, symbols=(BTC,)))


def options(**changes: object) -> IngestOptions:
    values: dict[str, object] = {"dataset_ids": TRADES_AND_CANDLES, "symbols": (BTC,), **changes}
    return IngestOptions(**values)  # type: ignore[arg-type]


def context(path: Path, now: dt.datetime, start: dt.date = dt.date(2026, 3, 1)) -> JobContext:
    return make_context(path, now=now, config=small_config(start))


def at(day: dt.date, hour: int = 10) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)


D1, D2, D3, D4, D5 = (dt.date(2026, 3, d) for d in range(1, 6))


def states(ctx: JobContext, dataset: str = "binance.aggTrades") -> dict[str, str]:
    return ctx.catalog.task_states(dataset, BTC)


def bars_state(ctx: JobContext) -> dict[str, str]:
    return ctx.catalog.task_states("derived.bars.binance", BTC)


# ---- catch-up ----------------------------------------------------------------------------------------------


def test_catch_up_after_a_missed_run(tmp_path: Path) -> None:
    """Run on day 3, miss days 4 and 5, run on day 6. Only missing days are fetched, and nothing is lost."""
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_binance_day(fetcher, BTC, day)
    first = run_ingest(context(tmp_path / "r", at(D3)), fetcher, options())
    assert first.done == 4
    assert first.status == "ok"
    ctx = context(tmp_path / "r", at(D3))
    assert set(states(ctx)) == {"2026-03-01", "2026-03-02"}

    for day in (D3, D4, D5):
        publish_binance_day(fetcher, BTC, day)
    fetcher.requests.clear()
    ctx = context(tmp_path / "r", at(dt.date(2026, 3, 6)))
    second = run_ingest(ctx, fetcher, options())
    assert second.done == 6
    assert states(ctx) == {f"2026-03-0{d}": "done" for d in range(1, 6)}
    fetched = [url for url in fetcher.requests if not url.endswith(".CHECKSUM")]
    assert not any("2026-03-01" in url or "2026-03-02" in url for url in fetched)
    assert len(fetched) == 6


def test_a_run_with_nothing_missing_fetches_nothing(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    run_ingest(context(tmp_path / "r", at(D2)), fetcher, options())
    fetcher.requests.clear()
    summary = run_ingest(context(tmp_path / "r", at(D2)), fetcher, options())
    assert summary.planned == 0
    assert fetcher.requests == []


def test_running_twice_gives_byte_identical_curated_files(tmp_path: Path) -> None:
    def build(path: Path) -> dict[str, bytes]:
        fetcher = FakeFetcher()
        for day in (D1, D2):
            publish_binance_day(fetcher, BTC, day)
        ctx = context(path, at(D3))
        run_ingest(ctx, fetcher, options())
        return {
            p.relative_to(ctx.root.path).as_posix(): p.read_bytes()
            for p in sorted(ctx.root.path.glob("curated/**/*.parquet"))
        }

    one = build(tmp_path / "a")
    two = build(tmp_path / "b")
    assert one == two
    assert len(one) >= 8


def test_how_long_a_run_took_does_not_reach_any_stored_file(tmp_path: Path) -> None:
    """Elapsed time once leaked into the catalog, and its length moved the published zone sizes."""

    def build(path: Path, step: float) -> dict[str, bytes]:
        fetcher = FakeFetcher()
        publish_binance_day(fetcher, BTC, D1)
        ticks = {"now": 0.0}

        def clock() -> float:
            ticks["now"] += step
            return ticks["now"]

        ctx = context(path, at(D2))
        summary = run_ingest(ctx, fetcher, options(), clock=clock)
        assert summary.seconds > 0
        ctx.catalog.close()
        return {
            p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()
        }

    # These give elapsed times with different numbers of digits.
    one = build(tmp_path / "a", 1.0)
    two = build(tmp_path / "b", 0.123)
    assert one == two
    assert "catalog/last_ingest.json" in one
    assert b"seconds" not in one["catalog/last_ingest.json"]


def test_order_is_newest_first_with_lighter_datasets_first(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r", at(D3))
    tasks = plan_tasks(ctx, options())
    assert [(t.partition, t.spec.id) for t in tasks] == [
        (D2, "binance.klines"),
        (D2, "binance.aggTrades"),
        (D1, "binance.klines"),
        (D1, "binance.aggTrades"),
    ]


def test_today_is_never_expected() -> None:
    spec = small_config(D1).dataset("binance.aggTrades")
    assert expected_partitions(spec, at(D3)) == [D1, D2]


def test_monthly_partitions_wait_for_the_month_to_end() -> None:
    from dataclasses import replace

    spec: DatasetSpec = replace(small_config(D1).dataset("binance.fundingRate"), start=dt.date(2026, 1, 1))
    assert expected_partitions(spec, at(dt.date(2026, 3, 31))) == [dt.date(2026, 1, 1), dt.date(2026, 2, 1)]
    assert expected_partitions(spec, at(dt.date(2026, 4, 1)))[-1] == dt.date(2026, 3, 1)


def test_with_no_approved_source_ingest_contacts_nothing_and_says_so(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = make_context(tmp_path / "r", now=at(D2))
    assert ctx.config.enabled_sources() == ()
    summary = run_ingest(ctx, fetcher, IngestOptions())
    assert summary.status == "no_approved_source"
    assert summary.source_state == "no approved source configured"
    assert summary.planned == 0
    assert summary.errors == []
    assert fetcher.requests == []
    assert plan_tasks(ctx, IngestOptions(include_book=True)) == []


def test_asking_for_a_disabled_source_is_an_error_and_never_a_fallback(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = make_context(tmp_path / "r", now=at(D2))
    with pytest.raises(SourceDisabledError, match="disabled"):
        run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.aggTrades",), symbols=(BTC,)))
    assert fetcher.requests == []


def test_one_enabled_source_does_not_open_the_others(tmp_path: Path) -> None:
    from dataclasses import replace

    config = base_config()
    bybit_only = replace(
        config,
        sources={**config.sources, "bybit": replace(config.source("bybit"), enabled=True)},
        datasets=tuple(replace(spec, start=D1) for spec in config.datasets),
    )
    ctx = make_context(tmp_path / "r", now=at(D2), config=bybit_only)
    assert {task.spec.venue for task in plan_tasks(ctx, IngestOptions())} == {"bybit"}


def test_a_monthly_partition_holding_the_start_date_is_expected() -> None:
    """A start in the middle of a month must not drop that month, which an early version did."""
    from dataclasses import replace

    spec = replace(small_config(D1).dataset("binance.fundingRate"), start=dt.date(2026, 1, 15))
    assert expected_partitions(spec, at(dt.date(2026, 2, 3))) == [dt.date(2026, 1, 1)]
    assert expected_partitions(spec, at(dt.date(2026, 2, 3)), start=dt.date(2026, 1, 20)) == [
        dt.date(2026, 1, 1)
    ]


def test_book_files_are_opt_in(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r", at(D3))
    plain = plan_tasks(ctx, IngestOptions(symbols=(BTC,)))
    assert not any(task.spec.kind == "orderbook" for task in plain)
    with_book = plan_tasks(ctx, IngestOptions(symbols=(BTC,), include_book=True))
    assert any(task.spec.kind == "orderbook" for task in with_book)


# ---- time budget -------------------------------------------------------------------------------------------


def test_time_budget_stops_cleanly_and_the_next_run_continues(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2, D3, D4):
        publish_binance_day(fetcher, BTC, day)

    class Clock:
        now = 0.0

        def __call__(self) -> float:
            self.now += 1.0
            return self.now

    first = run_ingest(context(tmp_path / "r", at(D5)), fetcher, options(time_budget_s=4.0), clock=Clock())
    assert first.status == "partial"
    assert first.not_started_time_budget > 0
    assert 0 < first.done < 8
    second = run_ingest(context(tmp_path / "r", at(D5)), fetcher, options())
    assert first.done + second.done == 8
    assert second.status == "ok"


# ---- not published yet -------------------------------------------------------------------------------------


def test_a_file_not_published_yet_stays_pending_and_is_not_an_error(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    ctx = context(tmp_path / "r", at(D2, 3))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.pending == 2
    assert summary.failed == 0
    assert summary.errors == []
    assert summary.status == "ok"
    assert states(ctx) == {"2026-03-01": "pending"}


def test_it_becomes_overdue_and_is_picked_up_once_it_appears(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    # Day 1 ends at day 2 00:00. The configured overdue time is 36 hours after that.
    ctx = context(tmp_path / "r", at(D3, 13))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",)))
    # Day 2 is still inside its 36 hours, and day 1 is past them.
    assert states(ctx) == {"2026-03-01": "overdue", "2026-03-02": "pending"}
    assert summary.overdue == 1
    assert summary.pending == 1
    assert summary.errors == []

    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D3, 14))
    run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",)))
    assert states(ctx)["2026-03-01"] == "done"


# ---- failures and quarantine -------------------------------------------------------------------------------


def _corrupt(fetcher: FakeFetcher, day: dt.date) -> str:
    """Change a delivered file so that it no longer matches its checksum sidecar."""
    url = f"{BINANCE}/daily/aggTrades/{BTC}/{BTC}-aggTrades-{day.isoformat()}.zip"
    fetcher.files[url] = fetcher.files[url] + b"tampered"
    return url


def quarantined(ctx: JobContext) -> list[Path]:
    return [p for p in ctx.root.guard.check("quarantine").rglob("*") if p.is_file()]


def test_a_checksum_failure_goes_to_quarantine_and_retries(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    _corrupt(fetcher, D1)
    ctx = context(tmp_path / "r", at(D2, 10))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",)))
    assert summary.failed == 1
    assert states(ctx) == {"2026-03-01": "failed"}
    assert len(quarantined(ctx)) == 1
    assert list(ctx.root.guard.check("raw/archive").rglob("*.zip")) == []
    assert not list(ctx.root.guard.check("curated/trades").rglob("*.parquet"))
    task = ctx.catalog.get_task(f"archive:binance.aggTrades:{BTC}:2026-03-01")
    assert task is not None
    assert task.attempts == 1
    assert task.last_error is not None
    assert "checksum" in task.last_error.lower() or "SHA-256" in task.last_error

    # Later, the host delivers a good file. The retry waits for its backoff, then succeeds.
    publish_binance_day(fetcher, BTC, D1)
    soon = context(tmp_path / "r", at(D2, 10) + dt.timedelta(minutes=5))
    assert run_ingest(soon, fetcher, options(dataset_ids=("binance.aggTrades",))).skipped_retry_wait == 1
    later = context(tmp_path / "r", at(D2, 12))
    summary = run_ingest(later, fetcher, options(dataset_ids=("binance.aggTrades",)))
    assert summary.done == 1
    assert states(later) == {"2026-03-01": "done"}


@pytest.mark.parametrize(
    "bad_csv",
    [
        "wrong,header,entirely\n1,2,3\n",
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n",
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "1,not_a_price,1,1,1,1772323200000,true\n",
    ],
    ids=["unknown header", "no rows", "bad number"],
)
def test_a_format_change_quarantines_instead_of_writing_bad_data(tmp_path: Path, bad_csv: str) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1, trades_csv=bad_csv)
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",)))
    assert summary.failed == 1
    assert states(ctx) == {"2026-03-01": "failed"}
    assert len(quarantined(ctx)) == 1
    assert not list(ctx.root.guard.check("curated/trades").rglob("*.parquet"))


def test_a_network_failure_is_retried_later_without_quarantine(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    url = f"{BINANCE}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    fetcher.failures[url] = FetchError("connection reset")
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",)))
    assert summary.failed == 1
    assert quarantined(ctx) == []
    del fetcher.failures[url]
    later = context(tmp_path / "r", at(D2, 14))
    assert run_ingest(later, fetcher, options(dataset_ids=("binance.aggTrades",))).done == 1


def test_a_missing_sidecar_is_recorded_and_not_fatal(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    del fetcher.files[f"{BINANCE}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip.CHECKSUM"]
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",))).done == 1
    record = ctx.catalog.get_file(
        f"raw/archive/binance/aggTrades/{BTC}/date=2026-03-01/{BTC}-aggTrades-2026-03-01.zip"
    )
    assert record is not None
    assert record.check_detail is not None
    assert record.check_detail["checksum_source"] == "none"


def test_a_sidecar_naming_another_file_is_refused(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    url = f"{BINANCE}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    digest = fetcher.files[f"{url}.CHECKSUM"].split()[0].decode()
    fetcher.files[f"{url}.CHECKSUM"] = f"{digest}  other-file.zip\n".encode()
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options(dataset_ids=("binance.aggTrades",))).failed == 1


# ---- bars, the midnight boundary, reconciliation --------------------------------------------------------


def test_bars_and_all_timeframes_are_built_with_knowable_times(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_binance_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    bars = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D1))
    assert bars.height == 1440
    assert (bars["knowable_time"] == bars["close_time"]).all()
    assert bars["volume"].sum() == 1440.0
    assert bars["buy_volume"].sum() == 1440.0
    for minutes in ctx.config.timeframes_minutes:
        higher = read_parquet(ctx.root.curated_part(timeframe_dataset(minutes), "binance", BTC, D1))
        assert higher.height == 1440 // minutes
        assert higher["complete"].all()
        assert higher["volume"].sum() == 1440.0
        assert (higher["knowable_time"] == higher["close_time"]).all()


def test_timeframe_dataset_names() -> None:
    assert [timeframe_dataset(m) for m in (1, 5, 30, 60, 120, 240, 1440)] == [
        "bars_1m", "bars_5m", "bars_30m", "bars_1h", "bars_2h", "bars_4h", "bars_1d",
    ]  # fmt: skip


def test_newest_day_stays_provisional_until_the_next_file_arrives(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx) == {"2026-03-01": "provisional"}
    bars = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D1))
    assert bars["gap"].to_list() == [False] * 1439 + [True]

    publish_binance_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx) == {"2026-03-01": "done", "2026-03-02": "provisional"}
    bars = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D1))
    assert not bars["gap"].any()


def test_a_trade_exactly_at_midnight_moves_to_the_bar_of_the_day_before(tmp_path: Path) -> None:
    """The file of day 2 holds a trade stamped 00:00:00.000. It closes the last bar of day 1."""
    midnight_ms = day_start_us(D2) // 1000
    day_two_trades, day_two_candles = make_day_files(D2)
    lines = day_two_trades.splitlines()
    head, rows = lines[0], lines[1:]
    extra = f"999,250.5,7.0,999,999,{midnight_ms},false"
    # Keep ids contiguous by giving the extra row an id just below the first.
    first_id = int(rows[0].split(",")[0])
    extra = f"{first_id - 1},250.5,7.0,{first_id - 1},{first_id - 1},{midnight_ms},false"
    candle_lines = day_two_candles.splitlines()
    fields = candle_lines[1].split(",")
    fields[5] = str(float(fields[5]) + 7.0)
    fields[9] = str(float(fields[9]) + 7.0)
    candle_lines[1] = ",".join(fields)
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    publish_binance_day(
        fetcher,
        BTC,
        D2,
        trades_csv="\n".join([head, extra, *rows]) + "\n",
        candles_csv="\n".join(candle_lines) + "\n",
    )
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.errors == []
    day_one = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D1))
    last = day_one.row(-1, named=True)
    assert last["close_time"].isoformat() == "2026-03-02T00:00:00+00:00"
    assert last["volume"] == 8.0
    assert last["close"] == 250.5
    assert last["trade_count"] == 2
    day_two = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D2))
    assert day_two.row(0, named=True)["volume"] == 1.0
    assert float(day_one["volume"].sum()) + float(day_two["volume"].sum()) == 2880.0 + 7.0


def test_a_daily_total_mismatch_fails_the_day_and_keeps_its_raw_data(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    trades, candles = make_day_files(D1)
    wrong = candles.splitlines()
    fields = wrong[700].split(",")
    fields[5] = str(float(fields[5]) + 5.0)
    wrong[700] = ",".join(fields)
    publish_binance_day(fetcher, BTC, D1, trades_csv=trades, candles_csv="\n".join(wrong) + "\n")
    publish_binance_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    assert summary.bars_failed >= 1
    assert any("not explained by midnight" in message for message in summary.errors)
    assert bars_state(ctx)["2026-03-01"] == "failed"
    # Bad bars are not readable under curated, and the raw trades of that day stay.
    assert not ctx.root.curated_part("bars_1m", "binance", BTC, D1).exists()
    assert list(ctx.root.guard.check("raw/archive/binance/aggTrades").rglob("*2026-03-01*.zip"))
    # Both sides are fetched again later.
    assert states(ctx)["2026-03-01"] == "failed"


def test_a_day_already_built_moves_to_quarantine_when_it_later_fails(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    trades, candles = make_day_files(D1)
    publish_binance_day(fetcher, BTC, D1, trades_csv=trades, candles_csv=candles)
    publish_binance_day(fetcher, BTC, D2)
    # The candles of day 1 are late, so its bars are first built without being reconciled.
    candle_url = f"{BINANCE}/daily/klines/{BTC}/1m/{BTC}-1m-2026-03-01.zip"
    del fetcher.files[candle_url]
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    bars_part = ctx.root.curated_part("bars_1m", "binance", BTC, D1)
    assert bars_part.is_file()
    assert bars_state(ctx)["2026-03-01"] == "provisional"

    # They arrive disagreeing with the trades. The bars must stop being readable as curated data.
    wrong = candles.splitlines()
    fields = wrong[700].split(",")
    fields[5] = str(float(fields[5]) + 5.0)
    wrong[700] = ",".join(fields)
    publish_binance_day(fetcher, BTC, D1, trades_csv=trades, candles_csv="\n".join(wrong) + "\n")
    ctx = context(tmp_path / "r", at(D3, 12))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.bars_failed == 1
    assert bars_state(ctx)["2026-03-01"] == "failed"
    assert not bars_part.exists()
    assert not ctx.root.curated_part("bars_1h", "binance", BTC, D1).exists()
    assert list(ctx.root.guard.check("quarantine").rglob("*part-2026-03-01.parquet"))
    record = ctx.catalog.get_file(ctx.relative(bars_part))
    assert record is not None
    assert record.status == "quarantined"


def test_reconciliation_runs_when_candles_arrive_after_the_trades(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    publish_binance_day(fetcher, BTC, D2)
    candle_url = f"{BINANCE}/daily/klines/{BTC}/1m/{BTC}-1m-2026-03-01.zip"
    held = fetcher.files.pop(candle_url)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-01"] == "provisional"
    assert ctx.catalog.reconciliations("official_candles")[0]["date"] != "2026-03-01"

    fetcher.files[candle_url] = held
    ctx = context(tmp_path / "r", at(D3, 12))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-01"] == "done"
    dates = [row["date"] for row in ctx.catalog.reconciliations("official_candles")]
    assert "2026-03-01" in dates


# ---- raw is transient --------------------------------------------------------------------------------------


def test_raw_goes_as_soon_as_curated_data_passes(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_binance_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    assert summary.raw_deleted_files == 4
    assert summary.raw_kept_after_curated == 0
    assert [p for p in ctx.root.guard.check("raw/archive").rglob("*") if p.is_file()] == []
    assert len(ctx.root.deletions_log.read_text(encoding="utf-8").splitlines()) == 4
    assert ctx.root.curated_part("trades", "binance", BTC, D1).is_file()


def test_without_the_flag_raw_stays(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options()).raw_deleted_files == 0
    assert list(ctx.root.guard.check("raw/archive").rglob("*.zip"))


# ---- a lost cache ------------------------------------------------------------------------------------------


def test_a_vanished_runner_disk_does_not_refetch_what_is_curated(tmp_path: Path) -> None:
    """Raw files disappear with each runner, and that is expected."""
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    for path in ctx.root.guard.check("raw/archive").rglob("*.zip"):
        path.unlink()
    fetcher.requests.clear()
    ctx = context(tmp_path / "r", at(D2, 12))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.catalog_marked_absent == 2
    assert fetcher.requests == []


def test_losing_a_curated_file_refetches_only_that_file(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_binance_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    ctx.root.curated_part("trades", "binance", BTC, D1).unlink()
    fetcher.requests.clear()
    ctx = context(tmp_path / "r", at(D3, 12))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    assert summary.catalog_rebuild_needed == 1
    assert summary.done == 1
    assert ctx.root.curated_part("trades", "binance", BTC, D1).is_file()
    assert [u for u in fetcher.requests if not u.endswith(".CHECKSUM")] == [
        f"{BINANCE}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    ]


def test_losing_a_curated_file_rebuilds_from_raw_still_on_disk_without_a_download(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    part = ctx.root.curated_part("trades", "binance", BTC, D1)
    before = part.read_bytes()
    part.unlink()
    fetcher.requests.clear()
    ctx = context(tmp_path / "r", at(D2, 12))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.done == 1
    assert fetcher.requests == []
    assert part.read_bytes() == before


def test_a_completely_lost_cache_rebuilds_through_catch_up(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_binance_day(fetcher, BTC, day)

    ctx = context(tmp_path / "first", at(D3))
    run_ingest(ctx, fetcher, options())
    before = read_parquet(ctx.root.curated_part("bars_1m", "binance", BTC, D1))

    rebuilt = context(tmp_path / "second", at(D3))
    summary = run_ingest(rebuilt, fetcher, options())
    assert summary.done == 4
    assert read_parquet(rebuilt.root.curated_part("bars_1m", "binance", BTC, D1)).equals(before)


def test_a_rebuild_with_only_a_partial_budget_leaves_a_consistent_catalog(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2, D3):
        publish_binance_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D4))
    summary = run_ingest(ctx, fetcher, options(time_budget_s=0.0))
    assert summary.done == 0
    assert summary.status == "partial"
    assert summary.not_started_time_budget == 6


@pytest.mark.parametrize(
    ("used_pct", "old_done", "recent_done"),
    [
        (79.0, True, True),  # below the stop-backfill line
        (80.0, False, True),  # backfill stops, routine catch-up goes on
        (94.0, False, True),
        (95.0, False, False),  # critical: ingest is not essential work
        (120.0, False, False),
    ],
)
def test_storage_watermarks_hold_backfill_first_then_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, used_pct: float, old_done: bool, recent_done: bool
) -> None:
    fetcher = FakeFetcher()
    old_day = dt.date(2026, 3, 1)
    recent_day = dt.date(2026, 3, 19)
    publish_binance_day(fetcher, BTC, old_day)
    publish_binance_day(fetcher, BTC, recent_day)
    monkeypatch.setenv("DATA_QUOTA_GB", "1")
    monkeypatch.setattr(
        "hft_crypto.data.ingest.measure_zones", lambda _root: {"curated": int(used_pct * 10_000_000)}
    )
    ctx = context(tmp_path / "r", at(dt.date(2026, 3, 20)))
    summary = run_ingest(ctx, fetcher, options(start=old_day, dataset_ids=("binance.aggTrades",)))
    assert (states(ctx).get("2026-03-01") == "done") is old_done
    assert (states(ctx).get("2026-03-19") == "done") is recent_done
    # 17 days lie between them, all pending in the fake archive unless held.
    if not recent_done:
        assert summary.done == 0
        assert summary.status == "partial"
    if not old_done:
        assert summary.held_by_watermark > 0
        assert summary.status == "partial"


def test_curated_trades_have_the_unified_schema(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_binance_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    frame = read_parquet(ctx.root.curated_part("trades", "binance", BTC, D1))
    assert frame.columns == [
        "venue",
        "symbol",
        "ts",
        "price",
        "qty",
        "is_taker_buy",
        "trade_id",
        "n_fills",
        "is_rpi",
        "knowable_time",
    ]
    assert frame["ts"].dtype == pl.Datetime("us", "UTC")
    assert (frame["knowable_time"] == frame["ts"]).all()


def test_bybit_book_runs_one_day_per_run(tmp_path: Path) -> None:
    from helpers import book_lines, book_message

    fetcher = FakeFetcher()
    base = "https://quote-saver.bycsi.com/orderbook/linear"
    for day in (D1, D2, D3):
        lines = book_lines(
            [
                book_message("snapshot", 1, [["100.0", "1"]], [["101.0", "1"]]),
                book_message("delta", 2, [["99.0", "2"]], []),
            ]
        )
        name = f"{day.isoformat()}_{BTC}_ob200.data"
        fetcher.files[f"{base}/{BTC}/{name}.zip"] = zip_bytes(name, lines.decode())
    ctx = context(tmp_path / "r", at(D4))
    summary = run_ingest(
        ctx, fetcher, IngestOptions(dataset_ids=("bybit.orderbook",), symbols=(BTC,), delete_raw=True)
    )
    assert summary.done == 1
    assert summary.book_days_left == 2
    assert summary.raw_deleted_files == 1
    assert ctx.catalog.task_states("bybit.orderbook", BTC) == {"2026-03-03": "done"}
    second = run_ingest(
        context(tmp_path / "r", at(D4)),
        fetcher,
        IngestOptions(dataset_ids=("bybit.orderbook",), symbols=(BTC,), delete_raw=True),
    )
    assert second.done == 1


def test_bybit_book_tries_each_depth(tmp_path: Path) -> None:
    from helpers import book_lines, book_message

    fetcher = FakeFetcher()
    base = "https://quote-saver.bycsi.com/orderbook/linear"
    lines = book_lines([book_message("snapshot", 1, [["100.0", "1"]], [["101.0", "1"]])])
    name = f"2026-03-01_{BTC}_ob500.data"
    fetcher.files[f"{base}/{BTC}/{name}.zip"] = zip_bytes(name, lines.decode())
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("bybit.orderbook",), symbols=(BTC,)))
    assert summary.done == 1
    assert any("ob200" in url for url in fetcher.requests)
    assert any("ob500" in url for url in fetcher.requests)
