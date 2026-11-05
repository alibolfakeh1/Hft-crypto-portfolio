"""First end-to-end output: status.json and a static site, from curated data only.

Only derived statistics leave this module: no trades, no prices, no bars, no book data. The chart carries
equity normalised to 100, never a price. Nothing here reads a raw zone, and every bar is filtered to what was
knowable at the report's own time.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from hft_crypto.bars.core import visible_bars
from hft_crypto.config import LAST_OPENED_DECISION, ConfigError, PipelineConfig
from hft_crypto.data.atomic import atomic_write_bytes, canonical_json_bytes, read_parquet
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import bars_dataset, day_is_usable
from hft_crypto.data.health import build_health
from hft_crypto.data.ingest import QUARANTINE_LOG
from hft_crypto.data.poll import read_poll_log
from hft_crypto.data.zones import DataRoot, part_period
from hft_crypto.reports.benchmark import compute_span_stats, normalise_to_100, underwater
from hft_crypto.reports.site import render_site
from hft_crypto.timeutil import MICROS_PER_DAY, date_of_us, iso, parse_iso, to_us
from hft_crypto.versioning import code_version

BENCHMARK_LABEL = "BENCHMARK, not a strategy result"
SYNTHETIC_LABEL = "SYNTHETIC: generated test data. Not market data and not a strategy result"


@dataclass(frozen=True)
class SeriesPoint:
    time_us: int
    equity: float
    drawdown: float


@dataclass(frozen=True)
class Benchmark:
    symbol: str
    start: str
    end: str
    stats: dict[str, Any]
    points: tuple[SeriesPoint, ...]
    span_start: str
    span_end: str
    days_in_span: int
    days_used: int
    days_excluded: int
    days_without_data: int
    newest_day_provisional: bool


def _read_all(
    root: DataRoot, dataset: str, venue: str, symbol: str, *, last_opened: dt.date
) -> tuple[pl.DataFrame, list[str]]:
    """Every part through the last opened date. A later part is never opened, so nothing later can reach a
    figure."""
    parts = [
        part
        for part in root.curated_parts(dataset, venue, symbol)
        if (period := part_period(part)) is not None and period[0] <= last_opened
    ]
    if not parts:
        return pl.DataFrame(), []
    frames = [read_parquet(part) for part in parts]
    return pl.concat(frames).sort("close_time"), [root.guard.relative(part) for part in parts]


def _day_status(
    catalog: Catalog, root: DataRoot, dataset: str, venue: str, symbol: str
) -> dict[str, tuple[str, dict[str, Any] | None]]:
    """The check status and detail of each stored day, as the catalog holds them."""
    statuses: dict[str, tuple[str, dict[str, Any] | None]] = {}
    for part in root.curated_parts(dataset, venue, symbol):
        record = catalog.get_file(root.guard.relative(part))
        day = part.stem.removeprefix("part-")
        statuses[day] = ("unknown", None) if record is None else (record.check_status, record.check_detail)
    return statuses


def _drawdown_problem(used: pl.DataFrame, marks: pl.DataFrame, minutes: int, last_price: float) -> str | None:
    """Missing marks would shrink a drawdown silently, so the two series must cover the same days and
    agree."""
    expected = used.height * (1440 // minutes)
    if marks.height != expected:
        return f"{marks.height} of {expected} marks are available, so no drawdown is given"
    priced = marks.filter(pl.col("close").is_not_null())
    if priced.is_empty() or float(priced["close"][-1]) != last_price:
        return "the finer marks and the daily closes do not end on one price, so no drawdown is given"
    return None


def _span_end(now_us: int) -> dt.date:
    """The last day that can be final. Its next file could exist by now, so a later delivery changes nothing
    here."""
    return date_of_us(now_us - MICROS_PER_DAY) - dt.timedelta(days=1)


def build_benchmark(
    root: DataRoot, config: PipelineConfig, catalog: Catalog, symbol: str, now_us: int
) -> tuple[Benchmark | None, list[str]]:
    """Buy and hold over a span declared in advance and common to all symbols, with excluded days left as
    holes.

    The span is not re-based on any failure, because a bad day may well be a stressed one, and a window
    starting after it would say something else entirely. Total return runs from the first usable open to the
    last usable close, across holes. Volatility and Sharpe use only one-day returns between adjacent usable
    days. Drawdown uses the marks that exist. The output states the days in the span, used and excluded.

    A day is used if it passed its checks, or if nothing outside its files could check it. A provisional or
    failed day is not, so a bad price cannot reach these figures. On candles a flagged minute does not exclude
    a day, only a hole at the row giving its open or close does, under `day_is_usable`. A day is final only
    once the next day's file could exist, so what a report says as of a moment does not depend on anything
    delivered later.
    """
    root.refuse_unopened("a report")
    venue = config.report.benchmark_venue
    if venue is None or not config.source_usable(venue):
        return None, []
    minutes = config.report.equity_timeframe_minutes
    source = config.source(venue)
    equity_dataset = bars_dataset(source, minutes)
    daily_dataset = bars_dataset(source, 1440)
    opened = config.last_opened_date
    daily_all, daily_parts = _read_all(root, daily_dataset, venue, symbol, last_opened=opened)
    equity_all, equity_parts = _read_all(root, equity_dataset, venue, symbol, last_opened=opened)
    if daily_all.is_empty() or equity_all.is_empty():
        return None, []
    statuses = _day_status(catalog, root, daily_dataset, venue, symbol)
    usable_days = [day for day, (status, detail) in statuses.items() if day_is_usable(status, detail)]
    span_start = config.report.span_start
    span_end = min(_span_end(now_us), opened)
    if span_end < span_start:
        return None, []
    daily_visible = visible_bars(daily_all, now_us)
    opening = pl.col("open_time").dt.date()
    used = daily_visible.filter(
        pl.col("close").is_not_null()
        & pl.col("open").is_not_null()
        & opening.cast(pl.String).is_in(usable_days)
        & (opening >= span_start)
        & (opening <= span_end)
    ).sort("close_time")
    if used.is_empty():
        return None, []
    first_open = float(used["open"][0])
    closes = [float(value) for value in used["close"].to_list()]
    days = used["open_time"].dt.date().to_list()
    one_day_returns = [closes[0] / first_open - 1.0]
    one_day_returns.extend(
        later / earlier - 1.0
        for earlier, later, before, after in zip(closes, closes[1:], days, days[1:], strict=False)
        if (after - before).days == 1
    )
    start_time = used["open_time"][0]
    end_time = used["close_time"][-1]
    in_span = visible_bars(equity_all, now_us).filter(pl.col("open_time").dt.date().is_in(days))
    marks = in_span.filter(pl.col("close").is_not_null()).sort("close_time")
    equity_prices = [first_open, *[float(v) for v in marks["close"].to_list()]]
    times = [
        to_us(start_time),
        *[int(v) for v in marks["close_time"].dt.timestamp("us").to_list()],
    ]
    calendar_days = (to_us(end_time) - to_us(start_time)) / MICROS_PER_DAY
    computed = compute_span_stats(first_open, closes[-1], one_day_returns, calendar_days, equity_prices)
    problem = _drawdown_problem(used, in_span, minutes, closes[-1])
    stats = computed.to_dict() if problem is None else {**computed.to_dict(), "max_drawdown": None}
    stats["max_drawdown_note"] = problem
    # RA-01: each day used states how many minutes it flagged, and this is their sum.
    stats["minutes_flagged_in_days_used"] = sum(
        int((statuses[day.isoformat()][1] or {}).get("flagged_minutes", 0))
        for day in days
        if day.isoformat() in statuses
    )
    equity = normalise_to_100(equity_prices)
    drawdown = underwater(equity)
    points = tuple(
        SeriesPoint(t, round(e, 4), round(d, 6)) for t, e, d in zip(times, equity, drawdown, strict=True)
    )
    used_files = {f"part-{day}.parquet" for day in days}
    manifest = [p for p in [*daily_parts, *equity_parts] if Path(p).name in used_files]
    newer_days = daily_visible.filter(pl.col("close_time") > end_time)
    in_span_days = (span_end - span_start).days + 1
    excluded = {
        row["date"]
        for row in catalog.exclusions()
        if row["venue"] == venue
        and row["symbol"] == symbol
        and span_start.isoformat() <= row["date"] <= span_end.isoformat()
    }
    return (
        Benchmark(
            symbol=symbol,
            start=iso(start_time),
            end=iso(end_time),
            stats=stats,
            points=points,
            span_start=span_start.isoformat(),
            span_end=span_end.isoformat(),
            days_in_span=in_span_days,
            days_used=used.height,
            days_excluded=len(excluded),
            days_without_data=max(0, in_span_days - used.height - len(excluded)),
            newest_day_provisional=newer_days.height > 0,
        ),
        manifest,
    )


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values), q)), 1)


def summarise_poll(runs: list[dict[str, Any]], now: dt.datetime) -> dict[str, Any]:
    """How late GitHub's schedule really is, and how old the polled data is."""
    # A report states a moment. Runs after it are not part of what it can say.
    runs = [r for r in runs if parse_iso(r["job_started_at"]) <= now]
    if not runs:
        return {"runs": 0, "note": "no poll runs recorded yet"}
    scheduled = [r for r in runs if r.get("delay_s") is not None]
    delays = [float(r["delay_s"]) for r in scheduled]
    missed = sum(int(r.get("missed_slots") or 0) for r in runs)
    last = runs[-1]
    gaps = [gap for r in runs for gap in r.get("gaps", [])]
    last_start = parse_iso(last["job_started_at"])
    symbols = {
        symbol: {
            "last_bar_close": item.get("last_bar_close"),
            "data_age_s_at_run": item.get("data_age_s"),
            "caught_up": item.get("caught_up"),
            "late_trades_total": sum(
                int(r.get("symbols", {}).get(symbol, {}).get("late_trades") or 0) for r in runs
            ),
        }
        for symbol, item in last.get("symbols", {}).items()
    }
    return {
        "runs": len(runs),
        "scheduled_runs": len(scheduled),
        "first_run": runs[0]["job_started_at"],
        "last_run": last["job_started_at"],
        "last_run_age_hours": round((now - last_start).total_seconds() / 3600.0, 2),
        "last_status": last.get("status"),
        "caught_up": last.get("caught_up"),
        "delay_median_s": _percentile(delays, 50),
        "delay_p90_s": _percentile(delays, 90),
        "delay_max_s": round(max(delays), 1) if delays else None,
        "missed_slots_total": missed,
        "duration_median_s": _percentile([float(r.get("duration_s") or 0.0) for r in runs], 50),
        "failed_runs": sum(r.get("status") != "ok" for r in runs),
        "gaps": len(gaps),
        # The poll's root has its own storage, which only its own run log reports.
        "storage_used_pct": last.get("storage_used_pct"),
        "watermark_level": last.get("watermark_level"),
        "alerts": list(last.get("alerts") or []),
        "data_gap_runs": sum(
            any(item.get("data_gap") for item in r.get("symbols", {}).values()) for r in runs
        ),
        # C17 asks for this share. No adapter reads a server time yet, so it is zero by construction.
        "server_time_share": sum(
            any(item.get("passed_on_server_time") for item in r.get("symbols", {}).values()) for r in runs
        )
        / len(runs),
        "symbols": symbols,
    }


def _book_replay_summary(ctx: JobContext) -> list[dict[str, Any]]:
    """Book files are large and stay opt-in. Only the statistics of each validated day are published."""
    rows = []
    for record in ctx.catalog.files(status="present", prefix="curated/book_replay/"):
        detail = record.check_detail or {}
        rows.append(
            {
                "date": record.partition_key,
                "dataset": record.dataset_id,
                "lines": detail.get("lines"),
                "snapshots": detail.get("snapshots"),
                "update_id_breaks": detail.get("update_id_breaks"),
                "crossed": detail.get("crossed"),
                "snapshot_mismatches": detail.get("snapshot_mismatches"),
                "ok": detail.get("ok"),
            }
        )
    return rows


def _reconciliation_summary(ctx: JobContext) -> dict[str, Any]:
    stated = ctx.now_iso()

    opened = ctx.config.last_opened_date.isoformat()

    def as_of(name: str) -> list[dict[str, Any]]:
        return [
            row
            for row in ctx.catalog.reconciliations(name)
            if row["checked_at"] <= stated and row["date"] <= opened
        ]

    official = as_of("official_candles")
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for row in official:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    worst_volume: dict[str, float] = {}
    worst_price: dict[str, float] = {}
    for row in official:
        symbol = row["symbol"]
        worst_volume[symbol] = max(
            worst_volume.get(symbol, 0.0), float(row["detail"].get("max_bar_volume_diff", 0.0))
        )
        worst_price[symbol] = max(
            worst_price.get(symbol, 0.0), float(row["detail"].get("max_bar_price_diff", 0.0))
        )
    not_available = counts.pop("not_available", 0)
    live = as_of("poll_rebuild")
    cross = as_of("cross_venue")
    against_archive = as_of("live_archive")
    return {
        "exclusions": sum(row["excluded_at"] <= stated for row in ctx.catalog.exclusions()),
        "live_archive": [
            {
                "date": r["date"],
                "symbol": r["symbol"],
                "status": r["status"],
                "bars_compared": r["detail"].get("bars_compared"),
                "bars_different": r["detail"].get("bars_different"),
            }
            for r in against_archive[-14:]
        ],
        "official_candles": {
            "days": len(official),
            **counts,
            # Never counted as passed, under charter G1.
            "not_available": not_available,
            "worst_bar_volume_diff": worst_volume,
            "worst_bar_price_diff": worst_price,
        },
        "poll_rebuild": [
            {
                "date": r["date"],
                "symbol": r["symbol"],
                "status": r["status"],
                "bars_compared": r["detail"].get("bars_compared"),
                "bars_different": r["detail"].get("bars_different"),
            }
            for r in live[-14:]
        ],
        "cross_venue": [
            {
                "date": r["date"],
                "symbol": r["symbol"],
                "status": r["status"],
                "median_abs_close_diff_bps": r["detail"].get("median_abs_close_diff_bps"),
                "one_minute_return_corr": r["detail"].get("one_minute_return_corr"),
            }
            for r in cross[-14:]
        ],
    }


def _is_synthetic(ctx: JobContext) -> bool:
    """Generated data keeps its label however one file fares: a lost marker stops the report instead."""
    marked = ctx.root.is_synthetic
    if ctx.catalog.holds_generated_data() and not marked:
        raise ConfigError("this root's catalog holds generated data and its SYNTHETIC marker is missing")
    return marked


def _refuse_generated_poll_runs(ctx: JobContext, runs: list[dict[str, Any]]) -> None:
    """A poll log saying SYNTHETIC cannot go in a report on real data, whatever became of that root's
    marker."""
    if not ctx.root.is_synthetic and any(run.get("data_kind") == "SYNTHETIC" for run in runs):
        raise ConfigError("a poll log holds SYNTHETIC runs and this root does not, so they cannot be mixed")


def attributions(config: PipelineConfig) -> list[str]:
    """What each source in use asks to be credited with, for everything published from its data."""
    return sorted(
        {
            config.source(name).attribution
            for name in config.enabled_sources()
            if config.source(name).attribution
        }
    )


def build_status(
    ctx: JobContext,
    benchmarks: list[Benchmark],
    poll_runs: list[dict[str, Any]],
    *,
    actions_cache: dict[str, Any] | None,
    run_id: str,
) -> dict[str, Any]:
    """The machine-readable result. It holds statistics only, and no local paths."""
    ctx.root.refuse_unopened("a report")
    now = ctx.now()
    health = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, now, actions_cache=actions_cache)
    live_poll = summarise_poll(poll_runs, now)
    # The poll's alerts come from another root, and this is the file the watchdog reads.
    health["alerts"].extend(f"Hourly poll: {alert}" for alert in live_poll.get("alerts", []))
    newest = max((parse_iso(b.end) for b in benchmarks), default=None)
    age_hours = None if newest is None else round((now - newest).total_seconds() / 3600.0, 2)
    stale = newest is None or (age_hours or 0.0) > ctx.config.report.stale_after_hours
    synthetic = _is_synthetic(ctx)
    label = SYNTHETIC_LABEL if synthetic else BENCHMARK_LABEL
    return {
        "label": label,
        "data_kind": "SYNTHETIC" if synthetic else "MARKET" if benchmarks else "NONE",
        "source_state": health["source_state"],
        "disclaimer": "Not investment advice. This project sends no orders. No strategy has been tested.",
        "attributions": attributions(ctx.config),
        "last_opened_date": ctx.config.last_opened_date.isoformat(),
        "last_opened_decision": LAST_OPENED_DECISION,
        "generated_at": iso(now),
        "run_id": run_id,
        "code_version": code_version(),
        "config_hash": ctx.config.config_hash,
        "retention_policy_hash": ctx.policy.config_hash,
        "data_as_of": None if newest is None else iso(newest),
        "data_age_hours": age_hours,
        "stale": stale,
        "partial_coverage": health["partial_coverage"],
        "benchmarks": {
            b.symbol: {
                "label": label,
                "venue": ctx.config.report.benchmark_venue,
                "start": b.start,
                "end": b.end,
                "span_start": b.span_start,
                "span_end": b.span_end,
                "days_in_span": b.days_in_span,
                "days_used": b.days_used,
                "days_excluded": b.days_excluded,
                "days_without_data": b.days_without_data,
                "newest_day_provisional": b.newest_day_provisional,
                **b.stats,
            }
            for b in benchmarks
        },
        "reconciliation": _reconciliation_summary(ctx),
        "book_replay": _book_replay_summary(ctx),
        "live_poll": live_poll,
        "health": health,
    }


def write_report(
    ctx: JobContext,
    *,
    out_dir: Path | None,
    poll_logs: tuple[Path | None, ...] = (),
    actions_cache: dict[str, Any] | None = None,
    published: bool = False,
) -> dict[str, Any]:
    """Write the run folder and, when asked, a copy for publishing outside DATA_ROOT."""
    ctx.root.refuse_unopened("a report")
    if published and _is_synthetic(ctx):
        raise ConfigError("SYNTHETIC output cannot be marked as published")
    now = ctx.now()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_id = f"report-{stamp}-{ctx.run_id[:8]}"
    ctx.catalog.start_run(
        run_id,
        "report",
        now=iso(now),
        code_version=code_version(),
        config_hash=ctx.config.config_hash,
    )
    now_us = to_us(now)
    benchmarks: list[Benchmark] = []
    manifest: list[str] = []
    for symbol in ctx.config.report.benchmark_symbols:
        benchmark, used = build_benchmark(ctx.root, ctx.config, ctx.catalog, symbol, now_us)
        manifest.extend(used)
        if benchmark is not None:
            benchmarks.append(benchmark)
    runs = read_poll_log(*poll_logs)
    _refuse_generated_poll_runs(ctx, runs)
    status = build_status(ctx, benchmarks, runs, actions_cache=actions_cache, run_id=run_id)
    html = render_site(status, benchmarks)
    run_dir = ctx.root.run_dir(run_id)
    status_bytes = canonical_json_bytes(status)
    atomic_write_bytes(run_dir / "status.json", status_bytes, guard=ctx.root.guard)
    atomic_write_bytes(run_dir / "site" / "index.html", html.encode("utf-8"), guard=ctx.root.guard)
    # With hashes, so two results can be told apart by what they read, not only by which paths they read.
    data_manifest = [
        {"path": path, "sha256": record.sha256 if record else None}
        for path, record in ((path, ctx.catalog.get_file(path)) for path in sorted(manifest))
    ]
    run_record = {
        "run_id": run_id,
        "kind": "report",
        "started_at": iso(now),
        "code_version": code_version(),
        "config_hash": ctx.config.config_hash,
        "data_manifest": data_manifest,
        "published": published,
    }
    atomic_write_bytes(run_dir / "run.json", canonical_json_bytes(run_record), guard=ctx.root.guard)
    for name in ("status.json", "site/index.html", "run.json"):
        path = run_dir / name
        ctx.register_output(
            path,
            dataset_id="results.report",
            kind="run",
            zone="results/runs",
            partition_key=None,
            date_start=None,
            date_end=None,
            rows=None,
            check_status="pass",
        )
    ctx.catalog.finish_run(
        run_id,
        now=iso(ctx.now()),
        status="ok",
        summary={"benchmarks": [b.symbol for b in benchmarks], "stale": status["stale"]},
        data_manifest=data_manifest,
        published=published,
    )
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "site").mkdir(exist_ok=True)
        shutil.copyfile(run_dir / "site" / "index.html", out_dir / "site" / "index.html")
        results = out_dir / "results"
        (results / "run_log").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run_dir / "status.json", results / "status.json")
        shutil.copyfile(run_dir / "status.json", out_dir / "status.json")
        _copy_logs(ctx, results / "run_log", poll_logs, status)
    return status


def _last_ingest_lateness(ctx: JobContext) -> dict[str, Any] | None:
    """How late the daily job ran, from the line its ingest step wrote."""
    path = ctx.root.pipeline_log
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            try:
                value: dict[str, Any] = json.loads(line)
            except ValueError:
                continue
            return value
    return None


def _copy_logs(
    ctx: JobContext, target: Path, poll_logs: tuple[Path | None, ...], status: dict[str, Any]
) -> None:
    """Prepare the small append-only logs for the results branch. The publish step only ever appends."""
    if ctx.root.deletions_log.is_file():
        shutil.copyfile(ctx.root.deletions_log, target / "deletions.jsonl")
    # The bad files leave with the runner, so this record is the evidence a reviewer has.
    quarantine = ctx.root.guard.check(QUARANTINE_LOG)
    if quarantine.is_file():
        shutil.copyfile(quarantine, target / "quarantine.jsonl")
    runs = read_poll_log(*poll_logs)
    if runs:
        with (target / "poll_runs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for run in runs:
                handle.write(json.dumps(run, sort_keys=True, ensure_ascii=False) + "\n")
    line = {
        "run_id": status["run_id"],
        "data_kind": status["data_kind"],
        "attributions": status["attributions"],
        "lateness": _last_ingest_lateness(ctx),
        "generated_at": status["generated_at"],
        "code_version": status["code_version"],
        "config_hash": status["config_hash"],
        "data_as_of": status["data_as_of"],
        "stale": status["stale"],
        "partial_coverage": status["partial_coverage"],
        "alerts": status["health"]["alerts"],
    }
    with (target / "pipeline_runs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n")
