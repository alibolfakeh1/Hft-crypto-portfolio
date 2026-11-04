"""The first end-to-end output, from generated data through to the published files."""

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
    agg_trades_csv,
    base_config,
    day_first_id,
    klines_csv,
    make_context,
    publish_generated_day,
    with_sources_enabled,
)
from hft_crypto.bars.core import UTC_TIME
from hft_crypto.config import ConfigError, PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.ingest import IngestOptions, run_ingest
from hft_crypto.reports.report import BENCHMARK_LABEL, summarise_poll, write_report
from hft_crypto.timeutil import day_start_us

SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIRST = dt.date(2026, 3, 1)
PRICES = {
    # Daily closes for BTC go 100, 110, 99, and ETH stays flat. The fourth day stays provisional, because its
    # next file has not come, so it is delivered and never counted.
    "BTCUSDT": {
        FIRST: 100.0,
        FIRST + dt.timedelta(days=1): 110.0,
        FIRST + dt.timedelta(days=2): 99.0,
        FIRST + dt.timedelta(days=3): 500.0,
    },
    "ETHUSDT": {
        FIRST: 50.0,
        FIRST + dt.timedelta(days=1): 50.0,
        FIRST + dt.timedelta(days=2): 50.0,
        FIRST + dt.timedelta(days=3): 50.0,
    },
}
DEFAULT_NOW = dt.datetime(2026, 3, 5, 10, tzinfo=dt.UTC)


def config() -> PipelineConfig:
    base = base_config()
    return with_sources_enabled(
        replace(
            base,
            symbols=SYMBOLS,
            datasets=tuple(replace(spec, start=FIRST) for spec in base.datasets),
            timeframes_minutes=(60, 1440),
            report=replace(base.report, benchmark_venue="generated"),
        )
    )


def publish_day(fetcher: FakeFetcher, symbol: str, day: dt.date, price: float) -> None:
    """One trade a minute at a fixed price, so each day's close is exact."""
    start_ms = day_start_us(day) // 1000
    trades = [(start_ms + m * 60_000 + 30_000, price, 1.0, True) for m in range(1440)]
    candles = [(start_ms + m * 60_000, price, price, price, price, 1.0, 1.0) for m in range(1440)]
    publish_generated_day(
        fetcher,
        symbol,
        day,
        trades_csv=agg_trades_csv(trades, first_id=day_first_id(day)),
        candles_csv=klines_csv(candles),
    )


def build(path: Path, days: int = 4, *, now: dt.datetime | None = None) -> JobContext:
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        for offset in range(days):
            day = FIRST + dt.timedelta(days=offset)
            publish_day(fetcher, symbol, day, PRICES[symbol][day])
    moment = now or DEFAULT_NOW
    ctx = make_context(path, now=moment, config=config())
    run_ingest(
        ctx,
        fetcher,
        IngestOptions(dataset_ids=("generated.klines", "generated.aggTrades"), symbols=SYMBOLS),
    )
    return ctx


def report(ctx: JobContext, out: Path, **kwargs: Any) -> dict[str, Any]:
    return write_report(ctx, out_dir=out, **kwargs)


def test_benchmark_numbers_are_right_end_to_end(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    # Bought at the first traded price, 100. Final close 99.
    assert btc["total_return"] == pytest.approx(-0.01)
    assert btc["days"] == 3.0
    assert btc["daily_returns"] == 3
    # Daily returns 0, +10%, -10%. The drawdown from 110 to 99 is -10%.
    assert btc["max_drawdown"] == pytest.approx(-0.10)
    assert btc["cagr"] == pytest.approx(0.99 ** (365.0 / 3.0) - 1.0)
    eth = status["benchmarks"]["ETHUSDT"]
    assert eth["total_return"] == pytest.approx(0.0)
    assert eth["annualised_volatility"] == pytest.approx(0.0)
    assert eth["sharpe"] is None


def test_every_output_carries_the_label(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out")
    assert BENCHMARK_LABEL == "BENCHMARK, not a strategy result"
    assert status["label"] == BENCHMARK_LABEL
    assert all(item["label"] == BENCHMARK_LABEL for item in status["benchmarks"].values())
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert BENCHMARK_LABEL in html
    assert "not investment advice" in html.lower()


def test_page_is_self_contained_and_persian_friendly(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    report(ctx, tmp_path / "out")
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in html
    assert 'dir="rtl"' in html
    assert "معیار مقایسه" in html
    assert not re.search(r'(src|href)="https?://', html)
    assert not re.search(r"@import|url\(", html)
    assert "<svg" in html
    assert "Equity, start = 100" in html
    assert "Underwater drawdown" in html
    assert ">0%</text>" in html
    assert ">-0%</text>" not in html
    assert len(list((tmp_path / "out" / "site").iterdir())) == 1


def test_no_raw_market_data_or_local_paths_leave(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    report(ctx, tmp_path / "out")
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    text = (tmp_path / "out" / "status.json").read_text(encoding="utf-8")
    status = json.loads(text)
    for blob in (html, text):
        assert str(tmp_path) not in blob
        assert str(tmp_path).replace("\\", "\\\\") not in blob
        assert "taker_buy" not in blob

    # BTC's final price of 99 is not a published value. Equity normalised to 100 happens to reach
    # 99.0, so the check is that no field called a price exists and no bars are listed.
    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    assert not keys(status) & {"open", "high", "low", "close", "price", "qty", "volume", "trades"}


def test_status_is_published_where_the_workflow_expects_it(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    report(ctx, tmp_path / "out")
    assert (tmp_path / "out" / "status.json").is_file()
    assert (tmp_path / "out" / "site" / "index.html").is_file()
    assert (tmp_path / "out" / "results" / "status.json").is_file()
    log = (tmp_path / "out" / "results" / "run_log" / "pipeline_runs.jsonl").read_text(encoding="utf-8")
    assert len(log.splitlines()) == 1
    assert (tmp_path / "out" / "results" / "run_log" / "deletions.jsonl").exists() is False


def test_each_run_records_its_version_config_and_manifest(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out", published=True)
    assert status["code_version"]
    assert status["config_hash"] == ctx.config.config_hash
    run_dir = ctx.root.run_dir(status["run_id"])
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert record["config_hash"] == ctx.config.config_hash
    paths = [item["path"] for item in record["data_manifest"]]
    assert any("bars_1d" in path for path in paths)
    assert any("bars_1h" in path for path in paths)
    assert len(paths) == 2 * 2 * 3  # symbols, timeframes, passing days
    assert ctx.catalog.published_runs_depending_on(paths[0]) == [status["run_id"]]


def test_a_manifest_names_what_it_read_by_hash_so_two_results_can_be_told_apart(tmp_path: Path) -> None:
    """DC-14. It listed paths only, so two backtests could differ with no trace."""
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out")
    record = json.loads((ctx.root.run_dir(status["run_id"]) / "run.json").read_text(encoding="utf-8"))
    for item in record["data_manifest"]:
        stored = ctx.catalog.get_file(item["path"])
        assert stored is not None
        assert item["sha256"] == stored.sha256


def test_same_inputs_and_clock_give_byte_identical_output(tmp_path: Path) -> None:
    def run(name: str) -> tuple[bytes, bytes]:
        ctx = build(tmp_path / name)
        ctx.run_id = "fixed"
        report(ctx, tmp_path / f"out-{name}")
        return (
            (tmp_path / f"out-{name}" / "site" / "index.html").read_bytes(),
            (tmp_path / f"out-{name}" / "status.json").read_bytes(),
        )

    assert run("a") == run("b")


def _deliver(ctx_path: Path, days: dict[int, float], now: dt.datetime) -> JobContext:
    """Deliver only the named days after the first, each at one price, for both symbols."""
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        for offset, price in days.items():
            publish_day(fetcher, symbol, FIRST + dt.timedelta(days=offset), price)
    ctx = make_context(ctx_path, now=now, config=config())
    run_ingest(
        ctx, fetcher, IngestOptions(dataset_ids=("generated.klines", "generated.aggTrades"), symbols=SYMBOLS)
    )
    return ctx


def test_a_lost_cache_shows_partial_coverage(tmp_path: Path) -> None:
    """Rebuilding: only some days are back, and of those only one has both neighbours. The page must say
    so."""
    ctx = _deliver(tmp_path / "r", {1: 99.0, 2: 99.0, 3: 99.0}, DEFAULT_NOW)
    status = report(ctx, tmp_path / "out")
    assert status["partial_coverage"] is True
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "PARTIAL COVERAGE" in html
    assert status["benchmarks"]["BTCUSDT"]["days"] == 1.0
    assert status["benchmarks"]["BTCUSDT"]["start"] == "2026-03-03T00:00:00Z"


def test_a_hole_in_history_is_not_bridged_by_a_multi_day_return(tmp_path: Path) -> None:
    """Day 3 does not exist. Statistics must use only the unbroken run at the end."""
    days = {0: 100.0, 1: 100.0, 3: 120.0, 4: 120.0, 5: 120.0}
    ctx = _deliver(tmp_path / "r", days, dt.datetime(2026, 3, 7, 10, tzinfo=dt.UTC))
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["days"] == 1.0
    assert btc["start"] == "2026-03-05T00:00:00Z"
    assert btc["total_return"] == pytest.approx(0.0)
    assert btc["missing_days_before_start"] is True


# ---- only a whole, passing day counts
# --------------------------------------------------------------------------


def _publish_one_bad_price(fetcher: FakeFetcher, symbol: str, day: dt.date, price: float, bad: float) -> None:
    start_ms = day_start_us(day) // 1000
    trades = [(start_ms + m * 60_000 + 30_000, price, 1.0, True) for m in range(1439)]
    trades.append((start_ms + 1439 * 60_000 + 30_000, bad, 1.0, True))
    candles = [(start_ms + m * 60_000, price, price, price, price, 1.0, 1.0) for m in range(1440)]
    publish_generated_day(
        fetcher,
        symbol,
        day,
        trades_csv=agg_trades_csv(trades, first_id=day_first_id(day)),
        candles_csv=klines_csv(candles),
    )


def test_a_slipped_digit_cannot_reach_the_published_statistics(tmp_path: Path) -> None:
    """F-04. A price of 990 for 99 used to give Sharpe 9.42 and a drawdown of -90%, with no flag beside
    them."""
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        for offset, price in {0: 100.0, 1: 100.0, 3: 100.0, 4: 100.0, 5: 100.0}.items():
            publish_day(fetcher, symbol, FIRST + dt.timedelta(days=offset), price)
        _publish_one_bad_price(fetcher, symbol, FIRST + dt.timedelta(days=2), 100.0, 1000.0)
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 7, 10, tzinfo=dt.UTC), config=config())
    run_ingest(
        ctx, fetcher, IngestOptions(dataset_ids=("generated.klines", "generated.aggTrades"), symbols=SYMBOLS)
    )
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["total_return"] == pytest.approx(0.0)
    assert btc["max_drawdown"] == pytest.approx(0.0)
    assert btc["start"] == "2026-03-04T00:00:00Z"
    assert status["reconciliation"]["exclusions"] == 2
    assert any("left out of results" in alert for alert in status["health"]["alerts"])
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "left out of results: 2" in html


def test_the_newest_day_is_not_counted_until_it_is_final(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["end"] == "2026-03-04T00:00:00Z"
    assert btc["newest_day_provisional"] is True


def _drop_marks(ctx: JobContext, day: dt.date) -> None:
    ctx.root.curated_part("bars_1h", "generated", "BTCUSDT", day).unlink()


def test_missing_hourly_marks_give_no_drawdown_and_a_reason(tmp_path: Path) -> None:
    """F-20. Removing one day's hourly bars moved max drawdown from -50% to -10%, with no error and no
    flag."""
    ctx = build(tmp_path / "r")
    whole = report(ctx, tmp_path / "out")["benchmarks"]["BTCUSDT"]
    assert whole["max_drawdown"] == pytest.approx(-0.10)
    assert whole["max_drawdown_note"] is None
    _drop_marks(ctx, FIRST + dt.timedelta(days=1))
    status = report(ctx, tmp_path / "out2")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["max_drawdown"] is None
    assert "48 of 72 marks" in btc["max_drawdown_note"]
    assert btc["total_return"] == pytest.approx(whole["total_return"])
    html = (tmp_path / "out2" / "site" / "index.html").read_text(encoding="utf-8")
    assert "48 of 72 marks" in html
    assert status["benchmarks"]["ETHUSDT"]["max_drawdown"] == pytest.approx(0.0)


def test_marks_that_end_on_another_price_give_no_drawdown(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    part = ctx.root.curated_part("bars_1h", "generated", "BTCUSDT", FIRST + dt.timedelta(days=2))
    frame = read_parquet(part)
    last = frame["close_time"].max()
    changed = frame.with_columns(
        pl.when(pl.col("close_time") == last).then(1.0).otherwise(pl.col("close")).alias("close")
    )
    changed.write_parquet(part)
    btc = report(ctx, tmp_path / "out")["benchmarks"]["BTCUSDT"]
    assert btc["max_drawdown"] is None
    assert "one price" in btc["max_drawdown_note"]


def test_equity_marks_are_read_as_of_the_stated_time(tmp_path: Path) -> None:
    """Report equity marks with no as-of filter passed every focused test. On late-known bars it would
    matter."""
    ctx = build(tmp_path / "r")
    part = ctx.root.curated_part("bars_1h", "generated", "BTCUSDT", FIRST + dt.timedelta(days=1))
    frame = read_parquet(part)
    much_later = pl.lit(9_000_000_000_000_000, dtype=pl.Int64).cast(UTC_TIME)
    frame.with_columns(much_later.alias("knowable_time")).write_parquet(part)
    btc = report(ctx, tmp_path / "out")["benchmarks"]["BTCUSDT"]
    assert btc["equity_marks"] == 1 + 48
    assert btc["max_drawdown"] is None


# ---- which labels can be lost
# --------------------------------------------------------------------------------


def _with_venue(root_config: PipelineConfig, venue: str | None) -> PipelineConfig:
    return replace(root_config, report=replace(root_config.report, benchmark_venue=venue))


def test_a_prohibited_venue_is_never_published_even_with_its_files_on_disk(tmp_path: Path) -> None:
    """F-12. With that venue as the benchmark, a report exited 0 and said data_kind MARKET, venue binance."""
    ctx = build(tmp_path / "r")
    base = ctx.config
    banned = replace(
        base,
        sources={**base.sources, "binance": base_config().source("binance")},
        report=replace(base.report, benchmark_venue="binance"),
    )
    for dataset in ("bars_1d", "bars_1h"):
        for part in ctx.root.curated_parts(dataset, "generated", "BTCUSDT"):
            target = ctx.root.guard.check(
                part.relative_to(ctx.root.path).as_posix().replace("venue=generated", "venue=binance")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(part.read_bytes())
    ctx.config = banned
    status = report(ctx, tmp_path / "out")
    assert status["benchmarks"] == {}
    assert status["data_kind"] == "NONE"


def test_a_market_label_needs_a_usable_venue(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    assert report(ctx, tmp_path / "out")["data_kind"] == "MARKET"
    ctx.config = _with_venue(ctx.config, None)
    assert report(ctx, tmp_path / "out2")["data_kind"] == "NONE"


def test_a_root_of_generated_data_with_its_marker_gone_refuses_to_report(tmp_path: Path) -> None:
    """F-13. Delete one file, and generated data came out labelled MARKET."""
    ctx = make_context(tmp_path / "r", now=DEFAULT_NOW)
    ctx.catalog.set_meta("data_kind", "SYNTHETIC")
    with pytest.raises(ConfigError, match="SYNTHETIC"):
        report(ctx, tmp_path / "out")


def test_a_dataset_naming_a_generated_venue_needs_the_marker(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=DEFAULT_NOW)
    ctx.catalog.upsert_dataset(
        "x",
        zone="curated",
        kind="trades",
        tier=None,
        source=None,
        venue="synthetic",
        symbol="S",
        terms_note=None,
        now="2026-03-01T00:00:00Z",
    )
    with pytest.raises(ConfigError, match="SYNTHETIC"):
        report(ctx, tmp_path / "out")


def test_every_log_line_carries_what_kind_of_data_it_is_about(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    report(ctx, tmp_path / "out")
    line = (tmp_path / "out" / "results" / "run_log" / "pipeline_runs.jsonl").read_text(encoding="utf-8")
    assert json.loads(line)["data_kind"] == "MARKET"


# ---- a report states a moment
# ------------------------------------------------------------------------------------


def test_status_fields_are_as_of_the_stated_time(tmp_path: Path) -> None:
    """DC-15. A report stated at one moment counted later checks, and showed a later run with a negative
    age."""
    ctx = build(tmp_path / "r")
    log = tmp_path / "poll.jsonl"
    log.write_text(
        "".join(
            json.dumps(
                {
                    "run_id": name,
                    "job_started_at": moment,
                    "delay_s": 10.0,
                    "missed_slots": 0,
                    "duration_s": 1.0,
                    "status": "ok",
                    "caught_up": True,
                    "gaps": [],
                    "symbols": {},
                }
            )
            + "\n"
            for name, moment in (("early", "2026-03-04T09:00:00Z"), ("later", "2026-03-15T09:00:00Z"))
        ),
        encoding="utf-8",
    )
    ctx.catalog.put_reconciliation(
        "official_candles",
        "generated",
        "BTCUSDT",
        "2026-03-09",
        "fail",
        {"max_bar_volume_diff": 9.0, "max_bar_price_diff": 9.0},
        now="2026-03-15T00:00:00Z",
    )
    status = report(ctx, tmp_path / "out", poll_logs=(log,))
    assert status["live_poll"]["runs"] == 1
    assert status["live_poll"]["last_run"] == "2026-03-04T09:00:00Z"
    assert status["live_poll"]["last_run_age_hours"] > 0
    assert status["reconciliation"]["official_candles"]["fail"] == 0


def test_with_no_approved_source_the_page_says_exactly_that(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=DEFAULT_NOW)
    status = report(ctx, tmp_path / "out")
    assert status["source_state"] == "no approved source configured"
    assert status["data_kind"] == "NONE"
    assert status["benchmarks"] == {}
    assert status["partial_coverage"] is False
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "No approved source configured" in html
    assert html.count("No approved source configured") == 1
    assert "SYNTHETIC" not in html


def test_empty_data_center_still_gives_a_page(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC), config=config())
    status = report(ctx, tmp_path / "out")
    assert status["benchmarks"] == {}
    assert status["stale"] is True
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "No benchmark data yet" in html


def test_old_data_is_labelled_stale(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r", now=dt.datetime(2026, 3, 20, 10, tzinfo=dt.UTC))
    status = report(ctx, tmp_path / "out")
    assert status["stale"] is True
    assert status["data_age_hours"] > 60
    assert "STALE" in (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")


def test_fresh_data_is_not_labelled_stale(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    status = report(ctx, tmp_path / "out")
    assert status["stale"] is False
    assert "STALE" not in (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")


def test_the_report_cannot_see_bars_from_after_its_own_time(tmp_path: Path) -> None:
    """Report as of the end of day 3. Its bars exist on disk, and the file that finishes them could not
    yet."""
    ctx = build(tmp_path / "r")
    # Day 2 is final at this moment, because the file that decides its last minute could exist. Day 3 is not.
    earlier = dt.datetime(2026, 3, 4, 0, 0, tzinfo=dt.UTC)
    ctx.now = lambda: earlier
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["days"] == 2.0
    assert btc["total_return"] == pytest.approx(0.10)
    assert btc["end"] == "2026-03-03T00:00:00Z"


def test_values_are_escaped_in_the_page(tmp_path: Path) -> None:
    """The poll log comes from the results branch, so what it says reaches the page as text and nothing
    else."""
    ctx = build(tmp_path / "r")
    planted = '<script>alert("x")</script>'
    log = tmp_path / "poll.jsonl"
    log.write_text(
        json.dumps(
            {
                "run_id": "a",
                "job_started_at": "2026-03-04T09:40:00Z",
                "delay_s": 1.0,
                "missed_slots": 0,
                "duration_s": 1.0,
                "status": planted,
                "caught_up": True,
                "gaps": [],
                "symbols": {
                    planted: {
                        "last_bar_close": planted,
                        "data_age_s": 1.0,
                        "caught_up": True,
                        "late_trades": 0,
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report(ctx, tmp_path / "out", poll_logs=(log,))
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert planted not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html


def test_poll_summary_measures_how_late_the_schedule_is() -> None:
    def run(
        run_id: str, start: str, delay: float | None, missed: int | None, status: str = "ok"
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "job_started_at": start,
            "delay_s": delay,
            "missed_slots": missed,
            "duration_s": 60.0,
            "status": status,
            "caught_up": True,
            "gaps": [],
            "symbols": {
                "BTCUSD": {
                    "last_bar_close": "2026-03-01T03:20:00Z",
                    "data_age_s": 200.0,
                    "caught_up": True,
                    "late_trades": 1,
                }
            },
        }

    now = dt.datetime(2026, 3, 1, 5, 0, tzinfo=dt.UTC)
    summary = summarise_poll(
        [
            run("a", "2026-03-01T00:30:00Z", 420.0, None),
            run("b", "2026-03-01T01:40:00Z", 1020.0, 0),
            run("c", "2026-03-01T04:25:00Z", 120.0, 2),
            run("d", "2026-03-01T04:50:00Z", None, 0, status="failed"),
        ],
        now,
    )
    assert summary["runs"] == 4
    assert summary["scheduled_runs"] == 3
    assert summary["delay_median_s"] == 420.0
    assert summary["delay_max_s"] == 1020.0
    assert summary["missed_slots_total"] == 2
    assert summary["failed_runs"] == 1
    assert summary["symbols"]["BTCUSD"]["late_trades_total"] == 4
    assert summary["last_run_age_hours"] == pytest.approx(0.17)
    assert summary["data_gap_runs"] == 0
    assert summary["server_time_share"] == 0.0


def test_poll_summary_with_no_runs() -> None:
    assert summarise_poll([], dt.datetime(2026, 3, 1, tzinfo=dt.UTC))["runs"] == 0


def test_poll_timing_reaches_the_page(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    log = tmp_path / "poll.jsonl"
    log.write_text(
        json.dumps(
            {
                "run_id": "a",
                "job_started_at": "2026-03-04T09:40:00Z",
                "delay_s": 1020.0,
                "missed_slots": 0,
                "duration_s": 60.0,
                "status": "ok",
                "caught_up": True,
                "gaps": [],
                "symbols": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status = report(ctx, tmp_path / "out", poll_logs=(log,))
    assert status["live_poll"]["delay_max_s"] == 1020.0
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "how late is the schedule" in html
    assert "17.0 min" in html
    published = (tmp_path / "out" / "results" / "run_log" / "poll_runs.jsonl").read_text(encoding="utf-8")
    assert json.loads(published.splitlines()[0])["run_id"] == "a"


def test_the_page_states_the_rule_that_is_really_used(tmp_path: Path) -> None:
    """F-23. It said the daily totals must match, which is no longer the rule."""
    ctx = build(tmp_path / "r")
    report(ctx, tmp_path / "out")
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "daily totals must match" not in html
    assert "what one day sends past midnight the next must take in" in html
    assert "declared placeholder" in html


def test_a_day_that_only_warned_is_left_out_of_results(tmp_path: Path) -> None:
    """F-04. Decide what `warn` means. No bar is flagged here, so only the check status can keep it out."""
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        for offset in (0, 2, 3, 4):
            publish_day(fetcher, symbol, FIRST + dt.timedelta(days=offset), 100.0)
        day = FIRST + dt.timedelta(days=1)
        start_ms = day_start_us(day) // 1000
        trades = [(start_ms + m * 60_000 + 30_000, 100.0, 1.0, True) for m in range(1440)]
        candles = [(start_ms + m * 60_000, 100.0, 100.0, 100.0, 100.0, 1.0, 1.0) for m in range(1440)]
        lines = klines_csv(candles).splitlines()
        # The official fill count is five times ours, so the day warns.
        counted = [lines[0]]
        for line in lines[1:]:
            fields = line.split(",")
            fields[8] = "5"
            counted.append(",".join(fields))
        publish_generated_day(
            fetcher,
            symbol,
            day,
            trades_csv=agg_trades_csv(trades, first_id=day_first_id(day)),
            candles_csv="\n".join(counted) + "\n",
        )
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 6, 10, tzinfo=dt.UTC), config=config())
    run_ingest(
        ctx, fetcher, IngestOptions(dataset_ids=("generated.klines", "generated.aggTrades"), symbols=SYMBOLS)
    )
    daily = read_parquet(
        ctx.root.curated_part("bars_1d", "generated", "BTCUSDT", FIRST + dt.timedelta(days=1))
    )
    assert daily["complete"].to_list() == [True]
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["start"] == "2026-03-03T00:00:00Z"
    assert btc["missing_days_before_start"] is True
    assert status["reconciliation"]["exclusions"] == 2
