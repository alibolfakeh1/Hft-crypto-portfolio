"""The first end-to-end output, from generated data through to the published files."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from helpers import FakeFetcher, base_config, klines_csv, agg_trades_csv, make_context, publish_binance_day

from hft_crypto.config import PipelineConfig
from hft_crypto.data.context import JobContext
from hft_crypto.data.ingest import IngestOptions, run_ingest
from hft_crypto.reports.report import BENCHMARK_LABEL, summarise_poll, write_report
from hft_crypto.timeutil import day_start_us

SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIRST = dt.date(2026, 3, 1)
PRICES = {
    # Daily closes for BTC go 100, 110, 99, and ETH stays flat.
    "BTCUSDT": {FIRST: 100.0, FIRST + dt.timedelta(days=1): 110.0, FIRST + dt.timedelta(days=2): 99.0},
    "ETHUSDT": {FIRST: 50.0, FIRST + dt.timedelta(days=1): 50.0, FIRST + dt.timedelta(days=2): 50.0},
}


def config() -> PipelineConfig:
    base = base_config()
    return replace(
        base,
        symbols=SYMBOLS,
        datasets=tuple(replace(spec, start=FIRST) for spec in base.datasets),
        timeframes_minutes=(60, 1440),
    )


def publish_day(fetcher: FakeFetcher, symbol: str, day: dt.date, price: float) -> None:
    """One trade a minute at a fixed price, so each day's close is exact."""
    start_ms = day_start_us(day) // 1000
    trades = [(start_ms + m * 60_000 + 30_000, price, 1.0, True) for m in range(1440)]
    candles = [(start_ms + m * 60_000, price, price, price, price, 1.0, 1.0) for m in range(1440)]
    publish_binance_day(
        fetcher, symbol, day, trades_csv=agg_trades_csv(trades), candles_csv=klines_csv(candles)
    )


def build(path: Path, days: int = 3, *, now: dt.datetime | None = None) -> JobContext:
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        for offset in range(days):
            day = FIRST + dt.timedelta(days=offset)
            publish_day(fetcher, symbol, day, PRICES[symbol][day])
    moment = now or dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC)
    ctx = make_context(path, now=moment, config=config())
    run_ingest(
        ctx,
        fetcher,
        IngestOptions(dataset_ids=("binance.klines", "binance.aggTrades"), symbols=SYMBOLS),
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
    assert any("bars_1d" in path for path in record["data_manifest"])
    assert any("bars_1h" in path for path in record["data_manifest"])
    assert len(record["data_manifest"]) == 2 * 2 * 3  # symbols, timeframes, days
    assert ctx.catalog.published_runs_depending_on(record["data_manifest"][0]) == [status["run_id"]]


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


def test_a_lost_cache_shows_partial_coverage(tmp_path: Path) -> None:
    """Rebuilding: only the newest day is back. The page must say so and still work."""
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        publish_day(fetcher, symbol, FIRST + dt.timedelta(days=2), 99.0)
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC), config=config())
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines", "binance.aggTrades"), symbols=SYMBOLS))
    status = report(ctx, tmp_path / "out")
    assert status["partial_coverage"] is True
    html = (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8")
    assert "PARTIAL COVERAGE" in html
    assert status["benchmarks"]["BTCUSDT"]["days"] == 1.0


def test_a_hole_in_history_is_not_bridged_by_a_multi_day_return(tmp_path: Path) -> None:
    """Days 1 and 3 exist, day 2 does not. Statistics must use only the unbroken run at the end."""
    fetcher = FakeFetcher()
    for symbol in SYMBOLS:
        publish_day(fetcher, symbol, FIRST, 100.0)
        publish_day(fetcher, symbol, FIRST + dt.timedelta(days=2), 120.0)
    ctx = make_context(tmp_path / "r", now=dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC), config=config())
    run_ingest(ctx, fetcher, IngestOptions(dataset_ids=("binance.klines", "binance.aggTrades"), symbols=SYMBOLS))
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["days"] == 1.0
    assert btc["total_return"] == pytest.approx(0.0)
    assert btc["missing_days_before_start"] is True


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
    """Report as of the start of day 3. Day 3's bars exist on disk but were not yet knowable."""
    ctx = build(tmp_path / "r")
    earlier = dt.datetime(2026, 3, 3, 0, 0, tzinfo=dt.UTC)
    ctx.now = lambda: earlier
    status = report(ctx, tmp_path / "out")
    btc = status["benchmarks"]["BTCUSDT"]
    assert btc["days"] == 2.0
    assert btc["total_return"] == pytest.approx(0.10)
    assert btc["end"] == "2026-03-03T00:00:00Z"


def test_values_are_escaped_in_the_page(tmp_path: Path) -> None:
    ctx = build(tmp_path / "r")
    ctx.catalog.add_gap("d", "a", "b", "r", now="n", run_id=None)
    status = report(ctx, tmp_path / "out")
    assert status["health"]["gaps"]
    from hft_crypto.reports.site import _e

    assert _e('<script>"x"</script>') == "&lt;script&gt;&quot;x&quot;&lt;/script&gt;"


def test_poll_summary_measures_how_late_the_schedule_is() -> None:
    def run(run_id: str, start: str, delay: float | None, missed: int | None, status: str = "ok") -> dict[str, Any]:
        return {
            "run_id": run_id,
            "job_started_at": start,
            "delay_s": delay,
            "missed_slots": missed,
            "duration_s": 60.0,
            "status": status,
            "caught_up": True,
            "gaps": [],
            "symbols": {"BTCUSD": {"last_bar_close": "2026-03-01T03:20:00Z", "data_age_s": 200.0, "caught_up": True, "late_trades": 1}},
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
