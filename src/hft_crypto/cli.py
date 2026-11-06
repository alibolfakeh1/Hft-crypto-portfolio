"""Console command `hft-crypto`. It reads public data and writes files, and can place no orders."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from hft_crypto.config import (
    ConfigError,
    PipelineConfig,
    RetentionPolicy,
    find_config_dir,
    load_pipeline_config,
    load_retention_policy,
    quota_bytes,
)
from hft_crypto.data.atomic import append_jsonl, atomic_write_json, canonical_json_bytes
from hft_crypto.data.book_replay import replay_zip
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.context import JobContext
from hft_crypto.data.coverage import (
    CHECK_ROOT_VARIABLE,
    FROZEN_LISTS,
    declared_days,
    init_check_root,
    run_candle_check,
    run_coverage_check,
)
from hft_crypto.data.fetch import HttpFetcher
from hft_crypto.data.guard import PathGuardError
from hft_crypto.data.health import build_health
from hft_crypto.data.ingest import IngestOptions, run_ingest
from hft_crypto.data.live_checks import run_live_checks
from hft_crypto.data.parsers import ValidationError
from hft_crypto.data.poll import KrakenClient, run_poll, scheduled_time
from hft_crypto.data.retention import build_plan, evaluate_watermarks, execute_plan
from hft_crypto.data.zones import (
    CANDLE_CHECK_OUTPUT,
    COVERAGE_OUTPUT,
    ROOT_KIND,
    SYNTHETIC_MARKER,
    DataRoot,
    DataRootError,
    measure_zones,
    persisted_bytes,
    resolve_data_root,
)
from hft_crypto.reports.report import write_report
from hft_crypto.synthetic import DEFAULT_SEED, run_synthetic
from hft_crypto.timeutil import iso, parse_date, parse_duration, parse_iso, utcnow


def _print_json(value: Any) -> None:
    sys.stdout.write(canonical_json_bytes(value).decode("utf-8"))


def _clock(args: argparse.Namespace) -> Callable[[], dt.datetime]:
    """--now fixes the clock, which makes a report byte-identical between runs on the same inputs."""
    fixed = getattr(args, "now", None)
    if not fixed:
        return utcnow
    moment = parse_iso(fixed)
    return lambda: moment


def _run_id() -> str:
    github = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{github}-{attempt}" if github else uuid.uuid4().hex[:16]


def _context(
    args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy, *, create: bool = True
) -> JobContext:
    root = resolve_data_root(args.data_root, create=create)
    root.refuse_unopened("this command")
    if not create and not root.catalog_path.is_file():
        raise DataRootError("DATA_ROOT has no catalog. Run `init` or `ingest` first, or check the path.")
    return JobContext(
        root=root,
        catalog=Catalog(root.catalog_path),
        config=config,
        policy=policy,
        now=_clock(args),
        run_id=_run_id(),
    )


def _refuse_synthetic(root: DataRoot) -> None:
    """Real jobs never run on a root of generated data, so the two can never mix."""
    if root.is_synthetic:
        raise ConfigError("this DATA_ROOT holds SYNTHETIC data, so a real job is refused here")


def _refuse_mixed_roots(root: DataRoot, live_root: str | None) -> None:
    """Generated poll runs must never show up in a report on real data, whatever became of one marker file."""
    if not live_root:
        return
    live = Path(live_root)
    if any((live / name).is_file() for name in (ROOT_KIND, COVERAGE_OUTPUT, CANDLE_CHECK_OUTPUT)):
        raise DataRootError(
            "the live root is a check root for unopened dates, so this command cannot open it"
        )
    if root.is_synthetic:
        return
    if (live / SYNTHETIC_MARKER).is_file():
        raise ConfigError(
            "the live root holds SYNTHETIC data and DATA_ROOT does not, so they cannot be mixed"
        )
    if (live / "catalog" / "catalog.sqlite").is_file():
        catalog = Catalog(live / "catalog" / "catalog.sqlite")
        generated = catalog.holds_generated_data()
        catalog.close()
        if generated:
            raise ConfigError(
                "the live root's catalog holds generated data, so it cannot be mixed with this root"
            )


def _refuse_fixed_clock(args: argparse.Namespace) -> None:
    """These jobs stamp when they received data, so a fixed clock would write a false receipt."""
    if getattr(args, "now", None):
        raise ConfigError("--now is refused here, because this job records real receive times")


def _cmd_synthetic_run(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    value = args.data_root or os.environ.get("DATA_ROOT", "").strip()
    if not value:
        raise DataRootError("DATA_ROOT is not set. Set the environment variable or pass --data-root.")
    data_root = Path(value)
    live_root = Path(args.live_root) if args.live_root else data_root.with_name(f"{data_root.name}-live")
    summary = run_synthetic(
        data_root,
        live_root,
        Path(args.out_dir),
        base_config=config,
        policy=policy,
        days=args.days,
        seed=args.seed,
        bar_source=args.bars_from,
    )
    _print_json(summary)
    return 0


def _cmd_init(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    ctx = _context(args, config, policy)
    ctx.catalog.close()
    sys.stdout.write("DATA_ROOT zones and catalog are ready.\n")
    return 0


def _selected_datasets(args: argparse.Namespace, config: PipelineConfig) -> tuple[str, ...] | None:
    if args.datasets:
        return tuple(item.strip() for item in args.datasets.split(",") if item.strip())
    if args.light:
        chosen = [spec.id for spec in config.datasets if spec.light and config.dataset_enabled(spec)]
        if args.include_book:
            chosen.extend(
                spec.id
                for spec in config.datasets
                if spec.kind == "orderbook" and config.dataset_enabled(spec)
            )
        return tuple(chosen)
    return None


def _log_daily_lateness(ctx: JobContext, args: argparse.Namespace, status: str) -> None:
    """Each scheduled job logs how late it ran, and the daily job is one of them."""
    started = parse_iso(args.job_started_at) if args.job_started_at else ctx.now()
    slot = scheduled_time(args.scheduled_cron or None, started)
    append_jsonl(
        ctx.root.pipeline_log,
        {
            "run_id": ctx.run_id,
            "kind": "ingest",
            "data_kind": "SYNTHETIC"
            if ctx.root.is_synthetic
            else "MARKET"
            if config_has_source(ctx)
            else "NONE",
            "event": args.event or None,
            "job_started_at": iso(started),
            "scheduled_time": None if slot is None else iso(slot),
            "delay_s": None if slot is None else round((started - slot).total_seconds(), 1),
            "status": status,
        },
        guard=ctx.root.guard,
    )


def config_has_source(ctx: JobContext) -> bool:
    return bool(ctx.config.enabled_sources())


def _market_ticks(args: argparse.Namespace) -> dict[str, Any] | None:
    """C16's tick tables from configs/engine.toml, for the checks after the fetch. None if there is none."""
    from hft_crypto.engine.config import load_engine_config

    path = find_config_dir(args.config_dir) / "engine.toml"
    return dict(load_engine_config(path).ticks) if path.is_file() else None


def _cmd_ingest(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    _refuse_fixed_clock(args)
    ctx = _context(args, config, policy)
    _refuse_synthetic(ctx.root)
    options = IngestOptions(
        dataset_ids=_selected_datasets(args, config),
        symbols=tuple(args.symbols.split(",")) if args.symbols else None,
        start=parse_date(args.start) if args.start else None,
        end=parse_date(args.end) if args.end else None,
        time_budget_s=parse_duration(args.time_budget) if args.time_budget else None,
        delete_raw=args.delete_raw_after_curated,
        include_book=args.include_book,
        ticks=_market_ticks(args),
    )
    fetcher = HttpFetcher(config.fetch, allowed_hosts=config.enabled_hosts())
    summary = run_ingest(ctx, fetcher, options)
    _log_daily_lateness(ctx, args, summary.status)
    ctx.catalog.close()
    _print_json(asdict(summary))
    return 0


def _cmd_validate_book(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    del config, policy
    result = replay_zip(Path(args.path))
    _print_json(result.to_dict())
    return 0 if result.ok else 1


def _cmd_retention(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    ctx = _context(args, config, policy, create=False)
    used = persisted_bytes(measure_zones(ctx.root), config.persisted_zones)
    state = evaluate_watermarks(used, quota_bytes(config.default_quota_gb), policy.watermarks)
    plan = build_plan(ctx.root, ctx.catalog, policy, state, ctx.now())
    output: dict[str, Any] = {"mode": "execute" if args.execute else "dry-run", **plan.to_dict()}
    if not args.show_files:
        output["deletable"] = len(plan.deletable)
        output["blocked"] = len(plan.blocked)
        output["blocked_reasons"] = _count_reasons(plan.blocked)
    if args.execute:
        reviewed_only = [item for item in plan.deletable if item.reviewed]
        plan.deletable = reviewed_only
        result = execute_plan(ctx, plan)
        output["executed"] = asdict(result)
    ctx.catalog.close()
    _print_json(output)
    return 0


def _count_reasons(items: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = f"{item.rule_id}: {item.reason.split(':')[0]}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _cmd_health(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    ctx = _context(args, config, policy, create=False)
    report = build_health(
        ctx.root,
        ctx.catalog,
        config,
        policy,
        ctx.now(),
        actions_cache=_read_cache_usage(args.actions_cache_json),
    )
    atomic_write_json(ctx.root.guard.check("catalog/health.json"), report, guard=ctx.root.guard)
    ctx.catalog.close()
    _print_json(report)
    return 0


def _read_cache_usage(path: str | None) -> dict[str, Any] | None:
    """GitHub's own figure for the repository's caches. Optional, because it needs an API call."""
    if not path or not Path(path).is_file():
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    return {k: value[k] for k in ("active_caches_size_in_bytes", "active_caches_count") if k in value}


def _cmd_poll(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    _refuse_fixed_clock(args)
    ctx = _context(args, config, policy)
    _refuse_synthetic(ctx.root)
    # Its own limits, so that one page cannot take a whole run's time budget.
    limits = replace(config.fetch, timeout_s=config.poll.timeout_s, attempts=config.poll.attempts)
    client = KrakenClient(HttpFetcher(limits, allowed_hosts=config.enabled_hosts()), config.poll)
    record = run_poll(
        ctx,
        client,
        time_budget_s=parse_duration(args.time_budget) if args.time_budget else None,
        cron=args.scheduled_cron or None,
        job_started_at=parse_iso(args.job_started_at) if args.job_started_at else None,
        event_name=args.event or None,
        published_before=bool(args.previous_state and Path(args.previous_state).is_file()),
    )
    changed = bool(record["state_changes"])
    if args.bundle_dir and changed:
        _write_poll_bundle(ctx.root, Path(args.bundle_dir))
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if changed else 'false'}\n")
    ctx.catalog.close()
    _print_json(record)
    return 0


def _write_poll_bundle(root: DataRoot, bundle: Path) -> None:
    """The small files a state change publishes to the results branch."""
    (bundle / "run_log").mkdir(parents=True, exist_ok=True)
    state = root.guard.check("catalog/live_state.json")
    (bundle / "live_state.json").write_bytes(state.read_bytes())
    (bundle / "run_log" / "poll_runs.jsonl").write_bytes(root.poll_log.read_bytes())


def _poll_context(
    args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy
) -> JobContext | None:
    if not args.live_root or not (Path(args.live_root) / "catalog" / "catalog.sqlite").is_file():
        return None
    root = DataRoot(args.live_root, create=False)
    return JobContext(
        root=root,
        catalog=Catalog(root.catalog_path),
        config=config,
        policy=policy,
        now=_clock(args),
        run_id=_run_id(),
    )


def _cmd_reconcile_live(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    ctx = _context(args, config, policy, create=False)
    _refuse_mixed_roots(ctx.root, args.live_root)
    poll_ctx = _poll_context(args, config, policy)
    if poll_ctx is None:
        ctx.catalog.close()
        _print_json({"status": "skipped", "reason": "no poll data available"})
        return 0
    results = run_live_checks(ctx, poll_ctx, days=args.days)
    ctx.catalog.close()
    poll_ctx.catalog.close()
    _print_json(results)
    return 0


def _cmd_report(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    ctx = _context(args, config, policy, create=False)
    _refuse_mixed_roots(ctx.root, args.live_root)
    live_log = Path(args.live_root) / "catalog" / "poll_runs.jsonl" if args.live_root else None
    branch_log = Path(args.results_dir) / "run_log" / "poll_runs.jsonl" if args.results_dir else None
    status = write_report(
        ctx,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        poll_logs=(branch_log, live_log),
        actions_cache=_read_cache_usage(args.actions_cache_json),
        published=args.published,
    )
    ctx.catalog.close()
    _print_json(
        {
            "run_id": status["run_id"],
            "data_as_of": status["data_as_of"],
            "data_age_hours": status["data_age_hours"],
            "stale": status["stale"],
            "partial_coverage": status["partial_coverage"],
            "benchmarks": status["benchmarks"],
            "alerts": status["health"]["alerts"],
        }
    )
    return 0


def _cmd_coverage_check(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    """No workflow starts this. Whether it may run is for project-manager and leak-auditor."""
    _refuse_fixed_clock(args)
    named = args.check_root or os.environ.get(CHECK_ROOT_VARIABLE)
    if not named:
        raise DataRootError(f"name the check root with --check-root or {CHECK_ROOT_VARIABLE}")
    if not config.source_usable(args.venue):
        raise ConfigError(
            f"source {args.venue} is not approved and enabled, so the coverage check does not run"
        )
    check_root = init_check_root(named, data_root=args.data_root)
    fetcher = HttpFetcher(config.fetch, allowed_hosts=config.enabled_hosts())
    document = run_coverage_check(
        check_root, config, fetcher, venue=args.venue, list_name=args.list, now=_clock(args)
    )
    _print_json(document)
    return 0


def _cmd_candle_check(args: argparse.Namespace, config: PipelineConfig, policy: RetentionPolicy) -> int:
    """Condition 2 of ruling 7. No workflow starts this, and it needs no outcome. Only flags leave it."""
    _refuse_fixed_clock(args)
    named = args.check_root or os.environ.get(CHECK_ROOT_VARIABLE)
    if not named:
        raise DataRootError(f"name the check root with --check-root or {CHECK_ROOT_VARIABLE}")
    days = declared_days(args.days)
    if not config.source_usable(args.venue):
        raise ConfigError(
            f"source {args.venue} is not approved and enabled, so the candle check does not run"
        )
    check_root = init_check_root(named, data_root=args.data_root)
    fetcher = HttpFetcher(config.fetch, allowed_hosts=config.enabled_hosts())
    _print_json(run_candle_check(check_root, config, fetcher, venue=args.venue, days=days, now=_clock(args)))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hft-crypto",
        description="Data center and report pipeline. Reads public data and sends no orders.",
    )
    parser.add_argument("--data-root", help="data directory. Defaults to the DATA_ROOT variable.")
    parser.add_argument("--config-dir", help="directory holding pipeline.toml and retention.toml")
    parser.add_argument("--now", help="fix the clock to this UTC time, for reproducible runs")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="create the zones and the catalog").set_defaults(func=_cmd_init)

    ingest = commands.add_parser("ingest", help="catch up on whatever the catalog says is missing")
    ingest.add_argument("--datasets", help="comma-separated dataset ids, such as binance.klines")
    ingest.add_argument("--light", action="store_true", help="only the light historical datasets")
    ingest.add_argument("--symbols", help="comma-separated symbols")
    ingest.add_argument("--start", help="earliest date to consider, YYYY-MM-DD")
    ingest.add_argument("--end", help="latest date to consider, YYYY-MM-DD")
    ingest.add_argument("--time-budget", help="stop starting new work after this long, such as 50m")
    ingest.add_argument(
        "--delete-raw-after-curated",
        action="store_true",
        help="delete each raw file as soon as the deletion protocol allows",
    )
    ingest.add_argument(
        "--include-book",
        action="store_true",
        help="also process order book files, which are large, at one day per run",
    )
    ingest.add_argument("--scheduled-cron", help="the cron expression that started this run")
    ingest.add_argument("--job-started-at", help="UTC time the job's first step began")
    ingest.add_argument("--event", help="what started the run, such as schedule")
    ingest.set_defaults(func=_cmd_ingest)

    book = commands.add_parser("validate-book", help="replay one Bybit order book zip and check it")
    book.add_argument("path", help="path of the .data.zip file")
    book.set_defaults(func=_cmd_validate_book)

    retention = commands.add_parser("retention", help="plan deletions. A dry run unless told otherwise")
    retention.add_argument(
        "--execute",
        action="store_true",
        help="really delete, and only for rules marked reviewed. Without this, nothing is touched",
    )
    retention.add_argument("--show-files", action="store_true", help="list every file in the plan")
    retention.set_defaults(func=_cmd_retention)

    health = commands.add_parser("health", help="coverage, gaps, disk use, growth and last runs")
    health.add_argument("--actions-cache-json", help="GitHub's cache usage response, saved to a file")
    health.set_defaults(func=_cmd_health)

    poll = commands.add_parser("poll", help="one short pass over closed trades since the last cursor")
    poll.add_argument("--time-budget", help="stop fetching after this long, such as 120s")
    poll.add_argument("--scheduled-cron", help="the cron expression that started this run")
    poll.add_argument("--job-started-at", help="UTC time the job's first step began")
    poll.add_argument("--event", help="what started the run, such as schedule")
    poll.add_argument("--previous-state", help="last published live state, to recognise a lost cache")
    poll.add_argument("--bundle-dir", help="write files to publish here when the state changed")
    poll.set_defaults(func=_cmd_poll)

    live = commands.add_parser("reconcile-live", help="daily checks on polled bars")
    live.add_argument("--live-root", help="the poll job's data directory")
    live.add_argument("--days", type=int, default=3, help="how many recent days to check")
    live.set_defaults(func=_cmd_reconcile_live)

    report = commands.add_parser("report", help="write status.json and site/index.html")
    report.add_argument("--out-dir", help="also copy the output here, for publishing")
    report.add_argument("--live-root", help="the poll job's data directory")
    report.add_argument("--results-dir", help="a checkout of the results branch")
    report.add_argument("--actions-cache-json", help="GitHub's cache usage response, saved to a file")
    report.add_argument("--published", action="store_true", help="mark this run as published")
    report.set_defaults(func=_cmd_report)

    synthetic = commands.add_parser(
        "synthetic-run",
        help="run everything once on generated data, with no network. Output is labelled SYNTHETIC",
    )
    synthetic.add_argument("--out-dir", required=True, help="where to write the labelled output")
    synthetic.add_argument("--live-root", help="data directory for the poll. Defaults to DATA_ROOT-live")
    synthetic.add_argument("--days", type=int, default=30, help="how many generated days")
    synthetic.add_argument("--seed", type=int, default=DEFAULT_SEED, help="same seed, same output")
    synthetic.add_argument(
        "--bars-from",
        choices=["trades", "official_1m"],
        default="trades",
        help="build bars from trades, or take the tier T0 path from official candles with no trades",
    )
    synthetic.set_defaults(func=_cmd_synthetic_run)

    coverage = commands.add_parser(
        "coverage-check",
        help="counts over unopened dates, in a root of their own. Only counts and flags leave it",
    )
    coverage.add_argument("--check-root", help=f"a new, empty folder. Defaults to {CHECK_ROOT_VARIABLE}")
    coverage.add_argument(
        "--list", required=True, choices=sorted(FROZEN_LISTS), help="which frozen file list"
    )
    coverage.add_argument("--venue", default="binance", help="the source, which must be enabled")
    coverage.set_defaults(func=_cmd_coverage_check)

    candle = commands.add_parser(
        "candle-check",
        help="whether a candle holds a print from after its close, on sample days. Only flags leave it",
    )
    candle.add_argument("--check-root", help=f"a new, empty folder. Defaults to {CHECK_ROOT_VARIABLE}")
    candle.add_argument("--days", required=True, help="the word declared, or 15ths separated by commas")
    candle.add_argument("--venue", default="binance", help="the source, which must be enabled")
    candle.set_defaults(func=_cmd_candle_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _build_parser().parse_args(argv)
    try:
        config = load_pipeline_config(args.config_dir)
        policy = load_retention_policy(args.config_dir)
        result: int = args.func(args, config, policy)
    except (ConfigError, DataRootError, PathGuardError, ValidationError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return result


if __name__ == "__main__":
    sys.exit(main())
