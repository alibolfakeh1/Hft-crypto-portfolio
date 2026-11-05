"""Catch-up, idempotence, pending against overdue, quarantine and retry, all without a network."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from helpers import (
    FAR_FUTURE,
    GENERATED,
    FakeFetcher,
    agg_trades_csv,
    base_config,
    day_first_id,
    klines_csv,
    make_context,
    make_day_files,
    policy_with_raw_reviewed,
    publish_generated_day,
    with_sources_enabled,
    zip_bytes,
)
from hft_crypto.config import DatasetSpec, PipelineConfig
from hft_crypto.data.atomic import atomic_write_parquet, read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import timeframe_dataset
from hft_crypto.data.fetch import FetchError
from hft_crypto.data.ingest import IngestOptions, SourceDisabledError, plan_tasks, run_ingest
from hft_crypto.data.sources import expected_partitions
from hft_crypto.timeutil import day_start_us

BTC = "BTCUSDT"
TRADES_AND_CANDLES = ("generated.klines", "generated.aggTrades")


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
    return make_context(path, now=now, config=small_config(start), policy=policy_with_raw_reviewed())


def at(day: dt.date, hour: int = 10) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)


D1, D2, D3, D4, D5 = (dt.date(2026, 3, d) for d in range(1, 6))


def states(ctx: JobContext, dataset: str = "generated.aggTrades") -> dict[str, str]:
    return ctx.catalog.task_states(dataset, BTC)


def bars_state(ctx: JobContext) -> dict[str, str]:
    return ctx.catalog.task_states("derived.bars.generated", BTC)


# ---- catch-up ----------------------------------------------------------------------------------------------


def test_catch_up_after_a_missed_run(tmp_path: Path) -> None:
    """Run on day 3, miss days 4 and 5, run on day 6. Only missing days are fetched, and nothing is lost."""
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_generated_day(fetcher, BTC, day)
    first = run_ingest(context(tmp_path / "r", at(D3)), fetcher, options())
    assert first.done == 4
    assert first.status == "ok"
    ctx = context(tmp_path / "r", at(D3))
    assert set(states(ctx)) == {"2026-03-01", "2026-03-02"}

    for day in (D3, D4, D5):
        publish_generated_day(fetcher, BTC, day)
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
    publish_generated_day(fetcher, BTC, D1)
    run_ingest(context(tmp_path / "r", at(D2)), fetcher, options())
    fetcher.requests.clear()
    summary = run_ingest(context(tmp_path / "r", at(D2)), fetcher, options())
    assert summary.planned == 0
    assert fetcher.requests == []


def test_running_twice_gives_byte_identical_curated_files(tmp_path: Path) -> None:
    def build(path: Path) -> dict[str, bytes]:
        fetcher = FakeFetcher()
        for day in (D1, D2):
            publish_generated_day(fetcher, BTC, day)
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
        publish_generated_day(fetcher, BTC, D1)
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
        (D2, "generated.klines"),
        (D2, "generated.aggTrades"),
        (D1, "generated.klines"),
        (D1, "generated.aggTrades"),
    ]


def test_today_is_never_expected() -> None:
    spec = small_config(D1).dataset("generated.aggTrades")
    assert expected_partitions(spec, at(D3), ceiling=FAR_FUTURE) == [D1, D2]


def test_monthly_partitions_wait_for_the_month_to_end() -> None:
    from dataclasses import replace

    spec: DatasetSpec = replace(small_config(D1).dataset("generated.fundingRate"), start=dt.date(2026, 1, 1))
    assert expected_partitions(spec, at(dt.date(2026, 3, 31)), ceiling=FAR_FUTURE) == [
        dt.date(2026, 1, 1),
        dt.date(2026, 2, 1),
    ]
    assert expected_partitions(spec, at(dt.date(2026, 4, 1)), ceiling=FAR_FUTURE)[-1] == dt.date(2026, 3, 1)


def test_with_no_approved_source_ingest_contacts_nothing_and_says_so(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
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
    publish_generated_day(fetcher, BTC, D1)
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
        last_opened_date=FAR_FUTURE,
    )
    ctx = make_context(tmp_path / "r", now=at(D2), config=bybit_only)
    assert {task.spec.venue for task in plan_tasks(ctx, IngestOptions())} == {"bybit"}


def test_a_monthly_partition_holding_the_start_date_is_expected() -> None:
    """A start in the middle of a month must not drop that month, which an early version did."""
    from dataclasses import replace

    spec = replace(small_config(D1).dataset("generated.fundingRate"), start=dt.date(2026, 1, 15))
    assert expected_partitions(spec, at(dt.date(2026, 2, 3)), ceiling=FAR_FUTURE) == [dt.date(2026, 1, 1)]
    assert expected_partitions(
        spec, at(dt.date(2026, 2, 3)), start=dt.date(2026, 1, 20), ceiling=FAR_FUTURE
    ) == [dt.date(2026, 1, 1)]


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
        publish_generated_day(fetcher, BTC, day)

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
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    # Day 2 is still inside its 36 hours, and day 1 is past them.
    assert states(ctx) == {"2026-03-01": "overdue", "2026-03-02": "pending"}
    assert summary.overdue == 1
    assert summary.pending == 1
    assert summary.errors == []

    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D3, 14))
    run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert states(ctx)["2026-03-01"] == "done"


# ---- failures and quarantine -------------------------------------------------------------------------------


def _corrupt(fetcher: FakeFetcher, day: dt.date) -> str:
    """Change a delivered file so that it no longer matches its checksum sidecar."""
    url = f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-{day.isoformat()}.zip"
    fetcher.files[url] = fetcher.files[url] + b"tampered"
    return url


def quarantined(ctx: JobContext) -> list[Path]:
    return [p for p in ctx.root.guard.check("quarantine").rglob("*") if p.is_file()]


def test_a_checksum_failure_goes_to_quarantine_and_retries(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    _corrupt(fetcher, D1)
    ctx = context(tmp_path / "r", at(D2, 10))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert states(ctx) == {"2026-03-01": "failed"}
    assert len(quarantined(ctx)) == 1
    assert list(ctx.root.guard.check("raw/archive").rglob("*.zip")) == []
    assert not list(ctx.root.guard.check("curated/trades").rglob("*.parquet"))
    task = ctx.catalog.get_task(f"archive:generated.aggTrades:{BTC}:2026-03-01")
    assert task is not None
    assert task.attempts == 1
    assert task.last_error is not None
    assert "checksum" in task.last_error.lower() or "SHA-256" in task.last_error

    # Later, the host delivers a good file. The retry waits for its backoff, then succeeds.
    publish_generated_day(fetcher, BTC, D1)
    soon = context(tmp_path / "r", at(D2, 10) + dt.timedelta(minutes=5))
    assert run_ingest(soon, fetcher, options(dataset_ids=("generated.aggTrades",))).skipped_retry_wait == 1
    later = context(tmp_path / "r", at(D2, 12))
    summary = run_ingest(later, fetcher, options(dataset_ids=("generated.aggTrades",)))
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
    publish_generated_day(fetcher, BTC, D1, trades_csv=bad_csv)
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert states(ctx) == {"2026-03-01": "failed"}
    assert len(quarantined(ctx)) == 1
    assert not list(ctx.root.guard.check("curated/trades").rglob("*.parquet"))


def test_a_network_failure_is_retried_later_without_quarantine(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    url = f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    fetcher.failures[url] = FetchError("connection reset")
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert quarantined(ctx) == []
    del fetcher.failures[url]
    later = context(tmp_path / "r", at(D2, 14))
    assert run_ingest(later, fetcher, options(dataset_ids=("generated.aggTrades",))).done == 1


def test_a_missing_sidecar_is_recorded_and_not_fatal(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    del fetcher.files[f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip.CHECKSUM"]
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",))).done == 1
    record = ctx.catalog.get_file(
        f"raw/archive/generated/aggTrades/{BTC}/date=2026-03-01/{BTC}-aggTrades-2026-03-01.zip"
    )
    assert record is not None
    assert record.check_detail is not None
    assert record.check_detail["checksum_source"] == "none"


def test_a_sidecar_naming_another_file_is_refused(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    url = f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    digest = fetcher.files[f"{url}.CHECKSUM"].split()[0].decode()
    fetcher.files[f"{url}.CHECKSUM"] = f"{digest}  other-file.zip\n".encode()
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",))).failed == 1


# ---- bars, the midnight boundary, reconciliation --------------------------------------------------------


def test_bars_and_all_timeframes_are_built_with_knowable_times(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2):
        publish_generated_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    assert bars.height == 1440
    allowance = ctx.config.source("generated").fill_span_allowance_us
    assert allowance == 250_000
    known = bars["knowable_time"].dt.timestamp("us") - bars["close_time"].dt.timestamp("us")
    assert known.unique().to_list() == [allowance]
    assert bars["volume"].sum() == 1440.0
    assert bars["buy_volume"].sum() == 1440.0
    for minutes in ctx.config.timeframes_minutes:
        higher = read_parquet(ctx.root.curated_part(timeframe_dataset(minutes), "generated", BTC, D1))
        assert higher.height == 1440 // minutes
        assert higher["complete"].all()
        assert higher["volume"].sum() == 1440.0
        spread = higher["knowable_time"].dt.timestamp("us") - higher["close_time"].dt.timestamp("us")
        assert spread.unique().to_list() == [allowance]


def test_timeframe_dataset_names() -> None:
    assert [timeframe_dataset(m) for m in (1, 5, 30, 60, 120, 240, 1440)] == [
        "bars_1m", "bars_5m", "bars_30m", "bars_1h", "bars_2h", "bars_4h", "bars_1d",
    ]  # fmt: skip


def test_newest_day_stays_provisional_until_the_next_file_arrives(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx) == {"2026-03-01": "provisional"}
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    assert bars["gap"].to_list() == [False] * 1439 + [True]

    publish_generated_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx) == {"2026-03-01": "done", "2026-03-02": "provisional"}
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    assert not bars["gap"].any()


def test_a_trade_exactly_at_midnight_moves_to_the_bar_of_the_day_before(tmp_path: Path) -> None:
    """The file of day 2 holds a trade stamped 00:00:00.000. It closes the last bar of day 1."""
    midnight_ms = day_start_us(D2) // 1000
    _, day_two_candles = make_day_files(D2)
    rows = [(midnight_ms, 100.01, 7.0, False)] + [
        (midnight_ms + minute * 60_000 + 30_000, 100.0, 1.0, True) for minute in range(1440)
    ]
    candle_lines = day_two_candles.splitlines()
    fields = candle_lines[1].split(",")
    fields[5] = str(float(fields[5]) + 7.0)
    # The official candle opening at midnight holds this print, as one more fill.
    fields[8] = "2"
    candle_lines[1] = ",".join(fields)
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(
        fetcher,
        BTC,
        D2,
        trades_csv=agg_trades_csv(rows, first_id=day_first_id(D2)),
        candles_csv="\n".join(candle_lines) + "\n",
    )
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.errors == []
    day_one = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    last = day_one.row(-1, named=True)
    assert last["close_time"].isoformat() == "2026-03-02T00:00:00+00:00"
    assert last["volume"] == 8.0
    assert last["close"] == 100.01
    assert last["trade_count"] == 2
    day_two = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    assert day_two.row(0, named=True)["volume"] == 1.0
    assert float(day_one["volume"].sum()) + float(day_two["volume"].sum()) == 2880.0 + 7.0


def _with_extra_official_volume(candles: str, line: int, extra: float) -> str:
    """Official candles holding volume the trade file does not have, from one minute on."""
    wrong = candles.splitlines()
    fields = wrong[line].split(",")
    fields[5] = str(float(fields[5]) + extra)
    wrong[line] = ",".join(fields)
    return "\n".join(wrong) + "\n"


def test_a_failed_day_keeps_its_bars_flagged_from_the_first_minute_it_cannot_explain(tmp_path: Path) -> None:
    """DC-08. It used to quarantine the whole day, so an event at 23:59 decided which bars exist at 08:00."""
    trades, candles = make_day_files(D1)
    fetcher = FakeFetcher()
    # Line 701 is minute 699: 11:39 to 11:40.
    publish_generated_day(
        fetcher, BTC, D1, trades_csv=trades, candles_csv=_with_extra_official_volume(candles, 700, 5.0)
    )
    publish_generated_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    assert summary.bars_failed >= 1
    assert any("minute boundaries" in message for message in summary.errors)
    assert bars_state(ctx)["2026-03-01"] == "failed"
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    assert bars.height == 1440
    flagged = bars["gap"].to_list()
    assert flagged[:699] == [False] * 699
    assert flagged[699:] == [True] * 741
    # The bars before that minute are what a clean day would have had.
    clean = FakeFetcher()
    publish_generated_day(clean, BTC, D1)
    publish_generated_day(clean, BTC, D2)
    other = context(tmp_path / "clean", at(D3))
    run_ingest(other, clean, options())
    good = read_parquet(other.root.curated_part("bars_1m", "generated", BTC, D1))
    assert bars.head(699).equals(good.head(699))
    # The raw trades of that day stay, and both sides are fetched again later.
    assert list(ctx.root.guard.check("raw/archive/generated/aggTrades").rglob("*2026-03-01*.zip"))
    assert states(ctx)["2026-03-01"] == "failed"
    assert states(ctx, "generated.klines")["2026-03-01"] == "failed"
    record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("bars_1d", "generated", BTC, D1)))
    assert record is not None
    assert record.check_status == "fail"


def test_a_failed_day_is_logged_as_an_exclusion_in_a_file_that_only_grows(tmp_path: Path) -> None:
    trades, candles = make_day_files(D1)
    fetcher = FakeFetcher()
    publish_generated_day(
        fetcher, BTC, D1, trades_csv=trades, candles_csv=_with_extra_official_volume(candles, 700, 5.0)
    )
    publish_generated_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    excluded = ctx.catalog.exclusions()
    assert [(row["date"], row["boundary_window_ms"]) for row in excluded] == [("2026-03-01", 250.0)]
    lines = ctx.root.guard.check("catalog/exclusions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"date":"2026-03-01"' in lines[0].replace(" ", "")
    assert '"data_kind":"MARKET"' in lines[0].replace(" ", "")


def test_a_failed_day_recovers_when_a_good_file_is_published(tmp_path: Path) -> None:
    """DC-08. Candles run first and re-derived on the old trades, which reset the trade file's retry, for
    ever."""
    good_trades, good_candles = make_day_files(D2)
    bad = good_trades.splitlines()
    fields = bad[700].split(",")
    fields[2] = "9.0"
    bad[700] = ",".join(fields)
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2, trades_csv="\n".join(bad) + "\n", candles_csv=good_candles)
    publish_generated_day(fetcher, BTC, D3)
    ctx = context(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-02"] == "failed"
    assert ctx.catalog.exclusions()
    assert ctx.catalog.get_reconciliation("official_candles", "generated", BTC, "2026-03-02") is not None

    # Raw is still on this disk, and the retry must not simply reuse it.
    publish_generated_day(fetcher, BTC, D2, trades_csv=good_trades, candles_csv=good_candles)
    fetcher.requests.clear()
    later = context(tmp_path / "r", at(D5))
    summary = run_ingest(later, fetcher, options())
    assert summary.errors == []
    assert any("aggTrades-2026-03-02" in url for url in fetcher.requests)
    assert bars_state(later)["2026-03-02"] == "done"
    bars = read_parquet(later.root.curated_part("bars_1m", "generated", BTC, D2))
    assert not bars["gap"].any()
    # The exclusion is resolved, and its record stays, with the failure that caused it.
    assert later.catalog.exclusions() == []
    history = later.catalog.exclusions(active_only=False)
    assert len(history) == 1
    assert history[0]["resolved_at"] is not None
    statuses = [row["status"] for row in later.catalog.reconciliation_history("generated", BTC, "2026-03-02")]
    assert "fail" in statuses
    assert statuses[-1] == "pass"
    # A delivered file that changed is an event.
    assert later.catalog.changed_files("raw/archive/generated/aggTrades/")


def test_a_day_already_built_is_flagged_when_it_later_fails_and_its_bars_stay(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    trades, candles = make_day_files(D1)
    publish_generated_day(fetcher, BTC, D1, trades_csv=trades, candles_csv=candles)
    publish_generated_day(fetcher, BTC, D2)
    # The candles of day 1 are late, so its bars are first built without being reconciled.
    candle_url = f"{GENERATED}/daily/klines/{BTC}/1m/{BTC}-1m-2026-03-01.zip"
    del fetcher.files[candle_url]
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options())
    bars_part = ctx.root.curated_part("bars_1m", "generated", BTC, D1)
    assert bars_part.is_file()
    assert bars_state(ctx)["2026-03-01"] == "provisional"

    # They arrive disagreeing with the trades.
    publish_generated_day(
        fetcher, BTC, D1, trades_csv=trades, candles_csv=_with_extra_official_volume(candles, 700, 5.0)
    )
    ctx = context(tmp_path / "r", at(D3, 12))
    summary = run_ingest(ctx, fetcher, options())
    assert summary.bars_failed == 1
    assert bars_state(ctx)["2026-03-01"] == "failed"
    assert read_parquet(bars_part)["gap"].sum() == 741
    assert ctx.root.curated_part("bars_1h", "generated", BTC, D1).is_file()
    assert not list(ctx.root.guard.check("quarantine").rglob("*part-2026-03-01.parquet"))
    record = ctx.catalog.get_file(ctx.relative(bars_part))
    assert record is not None
    assert record.status == "present"
    assert record.check_status == "fail"


# ---- what counts as a passing day: the table in F-04, through the whole path
# --------------------------------


def _truth(
    day: dt.date,
) -> tuple[list[tuple[int, float, float, bool]], list[tuple[int, float, float, float, float, float, float]]]:
    """One trade a minute. Takers buy in the first two hours of every four, so a flip can net to zero."""
    start_ms = day_start_us(day) // 1000
    rows = []
    candles = []
    for minute in range(1440):
        open_ms = start_ms + minute * 60_000
        buy = minute % 240 < 120
        rows.append((open_ms + 30_000, 100.0, 1.0, buy))
        candles.append((open_ms, 100.0, 100.0, 100.0, 100.0, 1.0, 1.0 if buy else 0.0))
    return rows, candles


def _publish_truth(fetcher: FakeFetcher, day: dt.date, rows: list[tuple[int, float, float, bool]]) -> None:
    _, candles = _truth(day)
    publish_generated_day(
        fetcher,
        BTC,
        day,
        trades_csv=agg_trades_csv(rows, first_id=day_first_id(day)),
        candles_csv=klines_csv(candles),
    )


def _invented_at_the_end(rows: list[tuple[int, float, float, bool]]) -> None:
    rows.append((rows[-1][0] + 29_900, 100.0, 4.0, True))


def _invented_at_noon(rows: list[tuple[int, float, float, bool]]) -> None:
    rows[720] = (rows[720][0], 100.0, 5.0, rows[720][3])


def _flipped_for_two_hours(rows: list[tuple[int, float, float, bool]]) -> None:
    for minute in range(60, 180):
        stamp, price, qty, buy = rows[minute]
        rows[minute] = (stamp, price, qty, not buy)


def _stamped_early(rows: list[tuple[int, float, float, bool]]) -> None:
    for minute in range(600, 780):
        stamp, price, qty, buy = rows[minute]
        rows[minute] = (stamp - 40_000, price, qty, buy)


def _slipped_digit_at_the_end(rows: list[tuple[int, float, float, bool]]) -> None:
    stamp, _, qty, buy = rows[-1]
    rows[-1] = (stamp, 1000.0, qty, buy)


@pytest.mark.parametrize(
    "damage",
    [
        _invented_at_the_end,
        _invented_at_noon,
        _flipped_for_two_hours,
        _stamped_early,
        _slipped_digit_at_the_end,
    ],
    ids=[
        "B invented at the end",
        "C2 invented at noon",
        "D flipped sides",
        "E2 stamped early",
        "F slipped digit",
    ],
)
def test_a_damaged_file_fails_its_day_and_keeps_its_raw_data(tmp_path: Path, damage: Any) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D3):
        _publish_truth(fetcher, day, _truth(day)[0])
    rows = _truth(D2)[0]
    damage(rows)
    _publish_truth(fetcher, D2, rows)
    ctx = context(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    assert bars_state(ctx)["2026-03-02"] == "failed"
    assert list(ctx.root.guard.check("raw/archive/generated/aggTrades").rglob("*2026-03-02*.zip"))
    checked = ctx.catalog.get_reconciliation("official_candles", "generated", BTC, "2026-03-02")
    assert checked is not None
    assert checked["status"] == "fail"
    assert read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))["gap"].any()


def test_a2_a_real_trade_lost_after_midnight_fails_on_the_previous_days_figure(tmp_path: Path) -> None:
    """F-04 row A2. The previous tail could explain it, though the previous day's difference was 0."""
    fetcher = FakeFetcher()
    _publish_truth(fetcher, D1, _truth(D1)[0])
    _publish_truth(fetcher, D3, _truth(D3)[0])
    rows, candles = _truth(D2)
    candles[0] = (candles[0][0], 100.0, 100.0, 100.0, 100.0, 4.0, candles[0][6])
    publish_generated_day(
        fetcher,
        BTC,
        D2,
        trades_csv=agg_trades_csv(rows, first_id=day_first_id(D2)),
        candles_csv=klines_csv(candles),
    )
    ctx = context(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    assert bars_state(ctx)["2026-03-02"] == "failed"
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    assert bars["gap"].to_list()[:2] == [True, False]


def test_k_the_first_day_of_a_dataset_does_not_stay_open_for_good(tmp_path: Path) -> None:
    """F-04 row K. With 3 coins lost and no previous file ever to come, it warns, and raw stays."""
    fetcher = FakeFetcher()
    rows, candles = _truth(D1)
    candles[0] = (candles[0][0], 100.0, 100.0, 100.0, 100.0, 4.0, candles[0][6])
    publish_generated_day(
        fetcher,
        BTC,
        D1,
        trades_csv=agg_trades_csv(rows, first_id=day_first_id(D1)),
        candles_csv=klines_csv(candles),
    )
    _publish_truth(fetcher, D2, _truth(D2)[0])
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    assert bars_state(ctx)["2026-03-01"] == "done"
    record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("bars_1m", "generated", BTC, D1)))
    assert record is not None
    assert record.check_status == "warn"
    assert list(ctx.root.guard.check("raw/archive/generated/aggTrades").rglob("*2026-03-01*.zip"))
    assert read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))["gap"].to_list()[:2] == [
        True,
        False,
    ]


# ---- holes in a delivered file -----------------------------------------------------------------------------


def _no_candles(path: Path, now: dt.datetime, start: dt.date = D1) -> JobContext:
    """A venue with no official candles, which today is every venue but the one D-17 bans."""
    from dataclasses import replace

    config = small_config(start)
    datasets = tuple(spec for spec in config.datasets if spec.curated != "candles_official")
    return make_context(path, now=now, config=replace(config, datasets=datasets))


def _day_with_hole(day: dt.date, first: int, last: int, *, ids_skip: bool) -> str:
    start_ms = day_start_us(day) // 1000
    lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
    identifier = day_first_id(day)
    for minute in range(1440):
        if first <= minute <= last:
            identifier += 1 if ids_skip else 0
            continue
        stamp = start_ms + minute * 60_000 + 30_000
        lines.append(f"{identifier},100.0,1.0,{identifier},{identifier},{stamp},false")
        identifier += 1
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("ids_skip", [True, False], ids=["ids skip", "ids run on"])
def test_a_six_hour_hole_in_a_file_is_recorded_and_flagged(tmp_path: Path, ids_skip: bool) -> None:
    """F-03 and DC-02. It used to give check_status pass, no gap record, and complete bars for all 24
    hours."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2, trades_csv=_day_with_hole(D2, 360, 719, ids_skip=ids_skip))
    start_ms = day_start_us(D3) // 1000
    rows = [(start_ms + minute * 60_000 + 30_000, 100.0, 1.0, True) for minute in range(1440)]
    # Ids run on past the hole, so the next day's file continues from where this one ends.
    first_id = day_first_id(D3) - (0 if ids_skip else 360)
    publish_generated_day(fetcher, BTC, D3, trades_csv=agg_trades_csv(rows, first_id=first_id))
    ctx = _no_candles(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("generated.aggTrades",), symbols=(BTC,)))
    gaps = ctx.catalog.gaps(f"curated.trades.generated.{BTC}")
    assert gaps
    trades_record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("trades", "generated", BTC, D2)))
    assert trades_record is not None
    # DR-13. A silence is a state of the market, so it never sets a status. A skip in the ids is a fault.
    assert trades_record.check_status == ("warn" if ids_skip else "pass")
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    in_hole = bars.slice(360, 360)
    assert in_hole["gap"].all()
    hourly = read_parquet(ctx.root.curated_part("bars_1h", "generated", BTC, D2))
    # The bar before the hole is flagged only by a skip in the ids, which says rows may be missing from it.
    before = 5 if ids_skip else 6
    assert hourly["complete"].to_list() == [True] * before + [False] * (13 - before) + [True] * 11
    record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("bars_1m", "generated", BTC, D2)))
    assert record is not None
    # A silence alone never excludes a day from statistics, and its minutes stay flagged all the same.
    assert record.check_status == ("warn" if ids_skip else "unreconciled")
    assert bars_state(ctx)["2026-03-02"] == "done"
    assert bool(ctx.catalog.exclusions()) is ids_skip


def test_a_break_in_the_ids_with_no_silence_is_a_warning_and_flags_its_minutes(tmp_path: Path) -> None:
    """F-03. A break of 500 ids used to pass."""
    start_ms = day_start_us(D2) // 1000
    rows = [(start_ms + m * 60_000 + 30_000, 100.0, 1.0, True) for m in range(1440)]
    text = agg_trades_csv(rows, first_id=day_first_id(D2)).splitlines()
    shifted = text[:701]
    for line in text[701:]:
        identifier, rest = line.split(",", 1)
        shifted.append(f"{int(identifier) + 500},{rest}")
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D2, trades_csv="\n".join(shifted) + "\n")
    ctx = _no_candles(tmp_path / "r", at(D3), start=D2)
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("generated.aggTrades",), symbols=(BTC,)))
    record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("trades", "generated", BTC, D2)))
    assert record is not None
    assert record.check_status == "warn"
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    assert bars["gap"].to_list()[698:702] == [False, True, True, False]


def test_on_a_source_with_no_sequence_every_empty_minute_is_a_gap(tmp_path: Path) -> None:
    """DC-02 c. Row numbers ran unbroken across any hole. With continuity `none`, nothing proves an empty
    minute."""
    from dataclasses import replace

    config = small_config(D1)
    bybit = replace(config.dataset("bybit.trades"), start=D1)
    ctx = make_context(tmp_path / "r", now=at(D2), config=replace(config, datasets=(bybit,)))
    assert ctx.config.source("bybit").continuity == "none"
    start = day_start_us(D1) / 1_000_000
    head = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,"
        "grossValue,homeNotional,foreignNotional,RPI\n"
    )
    lines = [
        f"{start + minute * 60 + 30},{BTC},Buy,1,100.0,PlusTick,id{minute},1,1,1,false"
        for minute in range(1440)
        if not 100 <= minute < 110
    ]
    import gzip

    url = f"{ctx.config.source('bybit').urls['trades_base']}/{BTC}/{BTC}2026-03-01.csv.gz"
    fetcher = FakeFetcher(files={url: gzip.compress((head + "\n".join(lines) + "\n").encode(), mtime=0)})
    summary = run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("bybit.trades",), symbols=(BTC,)))
    assert summary.errors == []
    bars = read_parquet(ctx.root.curated_part("bars_1m", "bybit", BTC, D1))
    assert bars["gap"].to_list()[100:110] == [True] * 10
    assert bars["gap"].to_list()[99] is False
    assert bars["empty_proof"].to_list()[100] == "none"


def test_a_row_stamped_ahead_of_the_clock_fails_its_file(tmp_path: Path) -> None:
    """The clock check on the archive path."""
    midnight_ms = day_start_us(D2) // 1000
    rows = [(midnight_ms - 30_000, 100.0, 1.0, True), (midnight_ms + 80_000_000, 100.0, 1.0, True)]
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1, trades_csv=agg_trades_csv(rows, first_id=day_first_id(D1)))
    ctx = context(tmp_path / "r", dt.datetime(2026, 3, 2, 1, tzinfo=dt.UTC))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert any("ahead of the clock" in message for message in summary.errors)
    assert not ctx.root.curated_part("trades", "generated", BTC, D1).exists()


def test_rows_received_after_their_stamp_cannot_become_archive_bars(tmp_path: Path) -> None:
    """DC-05. Bars built from polled trades used to be knowable at their close, with state `done`."""
    from hft_crypto.data.derive import derive_day
    from hft_crypto.data.parsers import ValidationError

    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    part = ctx.root.curated_part("trades", "generated", BTC, D1)
    received = read_parquet(part).with_columns((pl.col("ts") + pl.duration(hours=1)).alias("knowable_time"))
    received.write_parquet(part)
    with pytest.raises(ValidationError, match="after their stamp"):
        derive_day(ctx, "generated", BTC, D1)


def test_the_same_trade_in_two_files_counts_once(tmp_path: Path) -> None:
    """A day's window reads rows from its neighbours, so a repeated id must not count twice."""
    midnight_ms = day_start_us(D2) // 1000
    identifier = day_first_id(D1) + 1439
    day_two = [(midnight_ms + 30_000, 100.0, 1.0, True)]
    text = agg_trades_csv(day_two, first_id=identifier + 1).splitlines()
    text.insert(1, f"{identifier},100.0,1.0,{identifier},{identifier},{midnight_ms - 30_000},false")
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2, trades_csv="\n".join(text) + "\n")
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    assert bars["trade_count"].sum() == 1440


# ---- what one bad file can do
# --------------------------------------------------------------------------------


def _bad_deflate(body: bytes) -> bytes:
    middle = len(body) // 3
    return body[:middle] + bytes(b ^ 0xFF for b in body[middle : middle + 8]) + body[middle + 8 :]


def test_one_corrupt_file_cannot_stop_catch_up(tmp_path: Path) -> None:
    """F-05. The newest file had bad compressed data, with no sidecar, and three runs died on it in turn."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2)
    url = f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-02.zip"
    fetcher.files[url] = _bad_deflate(fetcher.files[url])
    del fetcher.files[f"{url}.CHECKSUM"]
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert summary.done == 1
    assert states(ctx) == {"2026-03-01": "done", "2026-03-02": "failed"}
    assert len(quarantined(ctx)) == 1
    assert ctx.catalog.last_runs()["ingest"][0]["status"] == "partial"


def test_anything_escaping_a_task_is_contained_and_the_run_row_finishes(tmp_path: Path) -> None:
    """F-05. Around each task, whatever the error, one partition can never stop the others."""

    class Odd(FakeFetcher):
        def download(self, url: str, dest: Path, max_bytes: int) -> int:
            if "2026-03-02" in url:
                raise RuntimeError("something nobody planned for")
            return super().download(url, dest, max_bytes)

    fetcher = Odd()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2)
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.failed == 1
    assert summary.done == 1
    assert states(ctx)["2026-03-02"] == "failed"
    assert any("something nobody planned for" in message for message in summary.errors)
    assert ctx.catalog.last_runs()["ingest"][0]["finished_at"] is not None


class _Crash(BaseException):
    """A killed process. Not an Exception, so nothing in the code can catch it."""


def test_a_crash_during_a_rebuild_heals_on_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-06. A crash after bars_1m said final left bars_1d wrong for ever, while bars_1m was right."""
    midnight_ms = day_start_us(D2) // 1000
    rows = [(midnight_ms, 100.01, 7.0, True)] + [
        (midnight_ms + minute * 60_000 + 30_000, 100.0, 1.0, True) for minute in range(1440)
    ]
    day_two = agg_trades_csv(rows, first_id=day_first_id(D2))
    _, day_two_candles = make_day_files(D2)
    lines = day_two_candles.splitlines()
    fields = lines[1].split(",")
    fields[5] = str(float(fields[5]) + 7.0)
    fields[9] = str(float(fields[9]) + 7.0)
    fields[8] = "2"
    lines[1] = ",".join(fields)
    candles_two = "\n".join(lines) + "\n"

    def publish(fetcher: FakeFetcher, day: dt.date) -> None:
        if day == D2:
            publish_generated_day(fetcher, BTC, day, trades_csv=day_two, candles_csv=candles_two)
        else:
            publish_generated_day(fetcher, BTC, day)

    fetcher = FakeFetcher()
    publish(fetcher, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-01"] == "provisional"

    # The next day's file arrives, and the rebuild of day 1 dies at its first write.
    publish(fetcher, D2)
    writes = {"count": 0}

    def dying(path: Path, frame: pl.DataFrame, **kwargs: Any) -> None:
        if "part-2026-03-01" in str(path):
            writes["count"] += 1
            if writes["count"] == 2:
                raise _Crash
        atomic_write_parquet(path, frame, **kwargs)

    monkeypatch.setattr("hft_crypto.data.derive.atomic_write_parquet", dying)
    with pytest.raises(_Crash):
        run_ingest(context(tmp_path / "r", at(D3)), fetcher, options())
    monkeypatch.undo()

    healed = context(tmp_path / "r", at(D3, 12))
    run_ingest(healed, fetcher, options())
    assert bars_state(healed)["2026-03-01"] == "done"
    daily = read_parquet(healed.root.curated_part("bars_1d", "generated", BTC, D1)).row(0, named=True)
    assert (daily["volume"], daily["close"], daily["gap"]) == (1447.0, 100.01, False)

    # Identical to a run that never crashed.
    clean = FakeFetcher()
    publish(clean, D1)
    publish(clean, D2)
    other = context(tmp_path / "clean", at(D3))
    run_ingest(other, clean, options())
    for name in ("bars_1m", "bars_1h", "bars_1d"):
        assert (
            healed.root.curated_part(name, "generated", BTC, D1).read_bytes()
            == other.root.curated_part(name, "generated", BTC, D1).read_bytes()
        )


def test_the_time_budget_also_bounds_the_bar_sweep(tmp_path: Path) -> None:
    """F-21. A budget of 1 s with 6 days to rebuild used to rebuild all 6 after it ended, with status ok."""
    fetcher = FakeFetcher()
    days = [dt.date(2026, 3, d) for d in range(1, 8)]
    for day in days:
        publish_generated_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(dt.date(2026, 3, 8)))
    run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    for day in days:
        ctx.catalog.set_task(
            f"derive:generated:{BTC}:{day.isoformat()}",
            dataset_id="derived.bars.generated",
            symbol=BTC,
            partition_key=day.isoformat(),
            state="pending",
            now=ctx.now_iso(),
        )

    class Jumping:
        now = 0.0

        def __call__(self) -> float:
            self.now += 100.0
            return self.now

    summary = run_ingest(
        ctx, fetcher, options(dataset_ids=("generated.aggTrades",), time_budget_s=250.0), clock=Jumping()
    )
    assert summary.bars_left_by_budget > 0
    assert summary.status == "partial"


def test_approving_a_source_the_daily_job_does_not_select_raises_an_alert(tmp_path: Path) -> None:
    """F-16. A green daily job that fetches nothing and tells nobody."""
    from dataclasses import replace

    config = base_config()
    bybit_only = replace(
        config,
        sources={**config.sources, "bybit": replace(config.source("bybit"), enabled=True)},
        datasets=tuple(replace(spec, start=D1) for spec in config.datasets),
    )
    ctx = make_context(tmp_path / "r", now=at(D2), config=bybit_only)
    summary = run_ingest(ctx, FakeFetcher(), IngestOptions(dataset_ids=()))
    assert summary.status == "nothing_selected"
    assert any("no dataset selected" in alert for alert in summary.alerts)


def test_reconciliation_runs_when_candles_arrive_after_the_trades(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    publish_generated_day(fetcher, BTC, D2)
    candle_url = f"{GENERATED}/daily/klines/{BTC}/1m/{BTC}-1m-2026-03-01.zip"
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
        publish_generated_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    # R6.1. A day's trade file also waits for its bars to pass, and the newest day's are provisional.
    assert summary.raw_deleted_files == 3
    left = [p.name for p in ctx.root.guard.check("raw/archive").rglob("*") if p.is_file()]
    assert left == [f"{BTC}-aggTrades-{D2.isoformat()}.zip"]
    assert len(ctx.root.deletions_log.read_text(encoding="utf-8").splitlines()) == 3
    assert ctx.root.curated_part("trades", "generated", BTC, D1).is_file()
    # The next day's file makes that day final, and then its raw file goes too.
    publish_generated_day(fetcher, BTC, D3)
    later = context(tmp_path / "r", at(D4))
    run_ingest(later, fetcher, options(delete_raw=True))
    assert f"{BTC}-aggTrades-{D2.isoformat()}.zip" not in [
        p.name for p in later.root.guard.check("raw/archive").rglob("*") if p.is_file()
    ]


def test_without_the_flag_raw_stays(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    assert run_ingest(ctx, fetcher, options()).raw_deleted_files == 0
    assert list(ctx.root.guard.check("raw/archive").rglob("*.zip"))


# ---- a lost cache ------------------------------------------------------------------------------------------


def test_a_vanished_runner_disk_does_not_refetch_what_is_curated(tmp_path: Path) -> None:
    """Raw files disappear with each runner, and that is expected."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
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
        publish_generated_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D3))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    ctx.root.curated_part("trades", "generated", BTC, D1).unlink()
    fetcher.requests.clear()
    ctx = context(tmp_path / "r", at(D3, 12))
    summary = run_ingest(ctx, fetcher, options(delete_raw=True))
    assert summary.catalog_rebuild_needed == 1
    assert summary.done == 1
    assert ctx.root.curated_part("trades", "generated", BTC, D1).is_file()
    assert [u for u in fetcher.requests if not u.endswith(".CHECKSUM")] == [
        f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-01.zip"
    ]


def test_losing_a_curated_file_rebuilds_from_raw_still_on_disk_without_a_download(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    part = ctx.root.curated_part("trades", "generated", BTC, D1)
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
        publish_generated_day(fetcher, BTC, day)

    ctx = context(tmp_path / "first", at(D3))
    run_ingest(ctx, fetcher, options())
    before = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))

    rebuilt = context(tmp_path / "second", at(D3))
    summary = run_ingest(rebuilt, fetcher, options())
    assert summary.done == 4
    assert read_parquet(rebuilt.root.curated_part("bars_1m", "generated", BTC, D1)).equals(before)


def test_a_rebuild_with_only_a_partial_budget_leaves_a_consistent_catalog(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    for day in (D1, D2, D3):
        publish_generated_day(fetcher, BTC, day)
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
    publish_generated_day(fetcher, BTC, old_day)
    publish_generated_day(fetcher, BTC, recent_day)
    monkeypatch.setenv("DATA_QUOTA_GB", "1")
    monkeypatch.setattr(
        "hft_crypto.data.ingest.measure_zones", lambda _root: {"curated": int(used_pct * 10_000_000)}
    )
    ctx = context(tmp_path / "r", at(dt.date(2026, 3, 20)))
    summary = run_ingest(ctx, fetcher, options(start=old_day, dataset_ids=("generated.aggTrades",)))
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
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    frame = read_parquet(ctx.root.curated_part("trades", "generated", BTC, D1))
    assert frame.columns == [
        "venue",
        "symbol",
        "ts",
        "price",
        "qty",
        "is_taker_buy",
        "trade_id",
        "file_row",
        "n_fills",
        "is_rpi",
        "knowable_time",
    ]
    assert frame["ts"].dtype == pl.Datetime("us", "UTC")
    spread = frame["knowable_time"].dt.timestamp("us") - frame["ts"].dt.timestamp("us")
    assert spread.unique().to_list() == [250_000]


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


def test_the_temp_sweep_leaves_the_ledger_and_decisions_alone(tmp_path: Path) -> None:
    """F-23. The sweep covered these zones, and deleted with no log line, outside the protocol."""
    from hft_crypto.data.atomic import temp_path_for

    ctx = context(tmp_path / "r", at(D2))
    kept = []
    for zone in ("ledger", "decisions"):
        leftover = temp_path_for(ctx.root.guard.check(f"{zone}/record.jsonl"))
        leftover.write_bytes(b"x")
        kept.append(leftover)
    swept = temp_path_for(ctx.root.guard.check("curated/part.parquet"))
    swept.write_bytes(b"x")
    summary = run_ingest(ctx, FakeFetcher(), options())
    assert summary.temp_files_swept == 1
    assert not swept.exists()
    assert all(path.is_file() for path in kept)


def test_a_row_longer_than_the_allowance_fails_its_boundary_and_records_the_allowance_false(
    tmp_path: Path,
) -> None:
    """Ruling 2 and DR-06. Window and allowance are one constant, so this detector can fire, and raising the
    window to pass a day also moves every knowable time. It used to need a second, wider key, which shipped
    set apart."""
    rows, candles = _truth(D2)
    stamp = rows[100][0]
    # Stamped 300 ms before its minute ends, and counted in the next one. The declared allowance is 250 ms.
    rows[100] = (stamp + 29_700, rows[100][1], rows[100][2], rows[100][3])
    candles[100] = (candles[100][0], 100.0, 100.0, 100.0, 100.0, 0.0, 0.0)
    candles[101] = (candles[101][0], 100.0, 100.0, 100.0, 100.0, 2.0, 2.0)
    fetcher = FakeFetcher()
    _publish_truth(fetcher, D1, _truth(D1)[0])
    _publish_truth(fetcher, D3, _truth(D3)[0])
    publish_generated_day(
        fetcher,
        BTC,
        D2,
        trades_csv=agg_trades_csv(rows, first_id=day_first_id(D2)),
        candles_csv=klines_csv(candles),
    )
    ctx = context(tmp_path / "r", at(D4), D1)
    run_ingest(ctx, fetcher, options())
    record = ctx.catalog.get_file(ctx.relative(ctx.root.curated_part("bars_1m", "generated", BTC, D2)))
    assert record is not None
    assert record.check_status == "fail"
    assert record.check_detail is not None
    assert any("allowance is false" in reason for reason in record.check_detail["reasons"])
    # DR-05. Only the boundary it could not explain is flagged, and the next minute stands.
    bars = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    assert bars.filter(pl.col("gap")).height == 1
    assert [event["date"] for event in ctx.catalog.allowance_events()] == [D2.isoformat()]
    logged = ctx.root.guard.check("catalog/allowance_events.jsonl").read_text(encoding="utf-8")
    assert '"needed_ms":300.0' in logged.replace(" ", "")


def test_a_row_just_before_midnight_settles_into_the_next_days_first_bar(tmp_path: Path) -> None:
    """Through derive_day. Tested only in build_bars_1m, a mutant that lost it at each midnight passed the
    suite."""
    midnight_ms = day_start_us(D2) // 1000
    trades_one = [
        (day_start_us(D1) // 1000 + minute * 60_000 + 30_000, 100.0, 1.0, True) for minute in range(1440)
    ]
    # Stamped 100 ms before midnight, inside the allowance of 250 ms, so it was not sure to have printed by
    # then.
    trades_one.append((midnight_ms - 100, 100.0, 5.0, False))
    candles_one = [
        (day_start_us(D1) // 1000 + minute * 60_000, 100.0, 100.0, 100.0, 100.0, 1.0, 1.0)
        for minute in range(1439)
    ]
    candles_one.append((midnight_ms - 60_000, 100.0, 100.0, 100.0, 100.0, 6.0, 1.0))
    fetcher = FakeFetcher()
    publish_generated_day(
        fetcher,
        BTC,
        D1,
        trades_csv=agg_trades_csv(trades_one, first_id=day_first_id(D1) - 1),
        candles_csv=klines_csv(candles_one),
    )
    publish_generated_day(fetcher, BTC, D2)
    publish_generated_day(fetcher, BTC, D3)
    ctx = context(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, options())
    day_one = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D1))
    day_two = read_parquet(ctx.root.curated_part("bars_1m", "generated", BTC, D2))
    assert day_one.row(-1, named=True)["volume"] == 6.0
    assert day_one.row(-1, named=True)["settled_volume"] == 1.0
    first = day_two.row(0, named=True)
    assert first["volume"] == 1.0
    assert first["settled_volume"] == 6.0
    assert first["settled_sell_volume"] == 5.0


def test_a_replaced_file_rebuilds_its_day_and_its_neighbours(tmp_path: Path) -> None:
    """DC-06 and section 9. `needs_derive` used to call a day done, with its trade part replaced under it."""
    fetcher = FakeFetcher()
    for day in (D1, D2, D3):
        publish_generated_day(fetcher, BTC, day)
    ctx = context(tmp_path / "r", at(D4))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-02"] == "done"
    ctx.catalog.set_task(
        f"archive:generated.aggTrades:{BTC}:2026-03-02",
        dataset_id="generated.aggTrades",
        symbol=BTC,
        partition_key="2026-03-02",
        state="failed",
        now=ctx.now_iso(),
        next_retry_at=ctx.now_iso(),
    )
    new_trades, _ = make_day_files(D2, price=101.0)
    _, same_candles = make_day_files(D2)
    publish_generated_day(fetcher, BTC, D2, trades_csv=new_trades, candles_csv=same_candles)
    later = context(tmp_path / "r", at(D4, 14))
    run_ingest(later, fetcher, options())
    assert read_parquet(later.root.curated_part("bars_1m", "generated", BTC, D2))["close"][0] == 101.0
    for day in (D1, D2, D3):
        part = later.root.curated_part("bars_1m", "generated", BTC, day)
        record = later.catalog.get_file(later.relative(part))
        assert record is not None
        assert record.created_at == later.now_iso(), day


def test_a_crash_after_the_last_write_of_a_rebuild_still_finishes_the_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-06. Every file is right and says final, and only the task is not. Only the pending mark can show
    that."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-01"] == "provisional"
    publish_generated_day(fetcher, BTC, D2)

    from hft_crypto.data.derive import derive_day as real

    def finishes_then_dies(job: JobContext, venue: str, symbol: str, day: dt.date) -> Any:
        outcome = real(job, venue, symbol, day)
        if day == D1:
            raise _Crash
        return outcome

    monkeypatch.setattr("hft_crypto.data.ingest.derive_day", finishes_then_dies)
    with pytest.raises(_Crash):
        run_ingest(context(tmp_path / "r", at(D3)), fetcher, options())
    monkeypatch.undo()

    healed = context(tmp_path / "r", at(D3, 12))
    run_ingest(healed, fetcher, options())
    assert bars_state(healed)["2026-03-01"] == "done"


def test_a_rebuild_marks_its_task_pending_before_its_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-06. A new file also reopens a day, so this holds the mark in `derive_day` itself, whatever started
    it."""
    from hft_crypto.data.derive import derive_day

    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options())
    assert bars_state(ctx)["2026-03-01"] == "provisional"

    def dies(*_: object, **__: object) -> None:
        raise _Crash

    monkeypatch.setattr("hft_crypto.data.derive.atomic_write_parquet", dies)
    with pytest.raises(_Crash):
        derive_day(ctx, "generated", BTC, D1)
    assert bars_state(ctx)["2026-03-01"] == "pending"


# ---- N-04, N-18, and the steward's list
# ---------------------------------------------------------------------------


def test_a_stray_file_name_cannot_stop_a_run(tmp_path: Path) -> None:
    """N-04. A name that was not a date killed the run, and left its row `running` for ever."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    ctx = context(tmp_path / "r", at(D2))
    folder = ctx.root.curated_part("trades", "generated", BTC, D1).parent
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "part-notadate.parquet").write_bytes(b"not a parquet file")
    summary = run_ingest(ctx, fetcher, options())
    assert summary.errors == []
    assert any("not a day" in alert for alert in summary.alerts)
    assert ctx.catalog.last_runs()["ingest"][0]["finished_at"] is not None
    assert states(ctx)["2026-03-01"] == "done"


def test_whatever_escapes_the_tasks_finishes_the_run_row_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-04. The fixes file said the run row always finishes, and this refuted it."""

    def dies(*_: object, **__: object) -> None:
        raise RuntimeError("beyond any task")

    monkeypatch.setattr("hft_crypto.data.ingest._run_tasks", dies)
    ctx = context(tmp_path / "r", at(D2))
    with pytest.raises(RuntimeError, match="beyond any task"):
        run_ingest(ctx, FakeFetcher(), options())
    row = ctx.catalog.last_runs()["ingest"][0]
    assert row["status"] == "failed"
    assert row["finished_at"] is not None


def test_failing_newest_files_do_not_use_up_the_budget_of_every_run(tmp_path: Path) -> None:
    """N-18. Work is newest first, so a file that keeps failing used to take the budget ahead of older
    days."""
    fetcher = FakeFetcher()
    for day in (D1, D2, D3):
        publish_generated_day(fetcher, BTC, day)
    url = f"{GENERATED}/daily/aggTrades/{BTC}/{BTC}-aggTrades-2026-03-03.zip"
    fetcher.failures[url] = FetchError("still broken")
    ctx = context(tmp_path / "r", at(D4))
    only_trades = {"dataset_ids": ("generated.aggTrades",)}
    run_ingest(ctx, fetcher, options(time_budget_s=1.0, **only_trades), clock=_ticks_after(1))
    assert states(ctx)["2026-03-03"] == "failed"
    # On the next run the failed file waits, and the older days go first.
    later = context(tmp_path / "r", at(D4, 23))
    task_row = later.catalog.get_task(f"archive:generated.aggTrades:{BTC}:2026-03-03")
    assert task_row is not None
    run_ingest(later, fetcher, options(time_budget_s=1.0, **only_trades), clock=_ticks_after(1))
    assert states(later)["2026-03-02"] == "done"


def _ticks_after(allowed: int) -> Any:
    """A clock that lets this many tasks start, and then is past any budget."""
    calls = {"count": 0}

    def clock() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] <= allowed + 1 else 1000.0

    return clock


def test_runs_that_keep_running_out_of_time_say_so(tmp_path: Path) -> None:
    """N-18. One long day is fine, and three in a row is a pattern someone must see."""
    fetcher = FakeFetcher()
    for day in (D1, D2, D3):
        publish_generated_day(fetcher, BTC, day)
    alerts: list[str] = []
    for run in range(3):
        ctx = context(tmp_path / "r", at(D4, 10 + run))
        for state_day in ("2026-03-01", "2026-03-02", "2026-03-03"):
            ctx.catalog.set_task(
                f"archive:generated.aggTrades:{BTC}:{state_day}",
                dataset_id="generated.aggTrades",
                symbol=BTC,
                partition_key=state_day,
                state="pending",
                now=ctx.now_iso(),
            )
        summary = run_ingest(
            ctx,
            fetcher,
            options(time_budget_s=0.0, dataset_ids=("generated.aggTrades",)),
            clock=lambda: 1000.0,
        )
        alerts = summary.alerts
    assert any("ran out of time" in alert for alert in alerts)


def test_watermarks_are_measured_on_what_the_cache_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.1. A large raw file leaves with the runner and spends no cache, so it cannot stop a backfill."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    monkeypatch.setenv("DATA_QUOTA_GB", "1")
    monkeypatch.setattr(
        "hft_crypto.data.ingest.measure_zones",
        lambda _root: {"raw": 50_000_000_000, "quarantine": 50_000_000_000, "curated": 1000},
    )
    ctx = context(tmp_path / "r", at(dt.date(2026, 3, 20)))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.held_by_watermark == 0
    assert states(ctx)["2026-03-01"] == "done"


def test_a_runner_short_of_disk_holds_downloads_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.2. R3.1 removed the only check on raw files during a job, so this takes its place."""
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, D1)
    monkeypatch.setattr("hft_crypto.data.ingest.free_disk_bytes", lambda _ctx: 1)
    ctx = context(tmp_path / "r", at(D2))
    summary = run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    assert summary.held_by_disk == 1
    assert fetcher.requests == []
    assert any("free space" in alert for alert in summary.alerts)


def test_each_quarantined_file_leaves_a_record_with_no_row_in_it(tmp_path: Path) -> None:
    """R4.1. The file leaves with the runner, so the record is what data-steward reviews. It gets
    published."""
    fetcher = FakeFetcher()
    secret_price = "98765.4321"
    bad = (
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        f"1,{secret_price},not_a_number,1,1,1,false\n"
    )
    publish_generated_day(fetcher, BTC, D1, trades_csv=bad)
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options(dataset_ids=("generated.aggTrades",)))
    text = ctx.root.guard.check("catalog/quarantine.jsonl").read_text(encoding="utf-8")
    record = json.loads(text.splitlines()[0])
    assert set(record) == {
        "time",
        "dataset",
        "symbol",
        "partition",
        "source_url",
        "path",
        "size",
        "sha256",
        "reason",
        "code_version",
        "run_id",
        "data_kind",
    }
    assert record["dataset"] == "generated.aggTrades"
    assert record["partition"] == "2026-03-01"
    assert record["data_kind"] == "MARKET"
    assert record["path"].startswith("quarantine/")
    assert secret_price not in text
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_a_warned_day_keeps_its_raw_file_while_it_is_provisional(tmp_path: Path) -> None:
    """R6.2. `provisional` outranks `warn`, so a day with a known warning used to lose its raw file."""
    fetcher = FakeFetcher()
    lines = make_day_files(D1)[1].splitlines()
    counted = [lines[0]]
    for line in lines[1:]:
        fields = line.split(",")
        fields[8] = "5"
        counted.append(",".join(fields))
    publish_generated_day(fetcher, BTC, D1, candles_csv="\n".join(counted) + "\n")
    ctx = context(tmp_path / "r", at(D2))
    run_ingest(ctx, fetcher, options(delete_raw=True))
    assert bars_state(ctx)["2026-03-01"] == "provisional"
    left = [p.name for p in ctx.root.guard.check("raw/archive").rglob("*") if p.is_file()]
    assert f"{BTC}-aggTrades-2026-03-01.zip" in left
