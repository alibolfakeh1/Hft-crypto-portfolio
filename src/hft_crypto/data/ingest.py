"""Historical ingest with catch-up.

Each run asks the catalog what is missing and processes it, newest first, so a missed run repairs itself and
a long backfill continues across runs. Every step is idempotent. A file that is not published yet stays
pending and is not an error until it is overdue. A file that fails a check goes to quarantine and is
downloaded again by a later run.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.core import DateGuardError
from hft_crypto.config import NO_APPROVED_SOURCE, ConfigError, DatasetSpec, quota_bytes
from hft_crypto.data.atomic import (
    append_jsonl,
    atomic_write_json,
    atomic_write_parquet,
    sha256_file,
    sweep_temp_files,
    temp_path_for,
)
from hft_crypto.data.book_replay import replay_zip
from hft_crypto.data.context import JobContext, write_heartbeat
from hft_crypto.data.derive import (
    OFFICIAL,
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_PROVISIONAL,
    TRADES,
    base_dataset,
    derive_dataset_id,
    derive_day,
    derive_task_key,
    needs_derive,
    reopen_day,
)
from hft_crypto.data.fetch import Fetcher, FetchError, NotPublishedError
from hft_crypto.data.guard import PathGuardError
from hft_crypto.data.parsers import (
    CuratedResult,
    ValidationError,
    parse_agg_trades,
    parse_book_depth,
    parse_bybit_trades,
    parse_checksum_sidecar,
    parse_funding,
    parse_klines,
)
from hft_crypto.data.retention import LEVEL_CRITICAL, evaluate_watermarks
from hft_crypto.data.retention import delete_raw_if_allowed as protocol_delete
from hft_crypto.data.sources import (
    ArchiveFile,
    archive_candidates,
    expected_partitions,
    partition_last_day,
)
from hft_crypto.data.zones import ZONE_DIRS, measure_zones, part_period, persisted_bytes
from hft_crypto.timeutil import MICROS_PER_SECOND, date_range, iso, iso_us, month_key, next_month, to_us
from hft_crypto.versioning import code_version

STATE_OVERDUE = "overdue"
RAW_RULE = "raw-archive-after-curated"
QUARANTINE_LOG = "catalog/quarantine.jsonl"
_SIDECAR_LIMIT = 4096
# Runs in a row that left work unstarted for lack of time, before that is worth telling someone.
UNSTARTED_ALERT_RUNS = 3
_LONG_NUMBER = re.compile(r"\d[\d.,:_-]*")
_PATH_LIKE = re.compile(r"[A-Za-z]:[\\/]\S*|(?<![\w.])/\S+")


@dataclass(frozen=True)
class Task:
    spec: DatasetSpec
    symbol: str
    partition: dt.date

    @property
    def partition_key(self) -> str:
        if self.spec.granularity == "month":
            return month_key(self.partition)
        return self.partition.isoformat()

    @property
    def key(self) -> str:
        return f"archive:{self.spec.id}:{self.symbol}:{self.partition_key}"

    def partition_end(self) -> dt.datetime:
        """The moment the data of this partition is complete."""
        last = (
            next_month(self.partition)
            if self.spec.granularity == "month"
            else self.partition + dt.timedelta(days=1)
        )
        return dt.datetime(last.year, last.month, last.day, tzinfo=dt.UTC)


@dataclass
class IngestOptions:
    dataset_ids: tuple[str, ...] | None = None
    symbols: tuple[str, ...] | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    time_budget_s: float | None = None
    delete_raw: bool = False
    include_book: bool = False


@dataclass
class IngestSummary:
    run_id: str
    status: str = "ok"
    source_state: str = ""
    planned: int = 0
    done: int = 0
    pending: int = 0
    overdue: int = 0
    failed: int = 0
    skipped_retry_wait: int = 0
    held_by_watermark: int = 0
    held_by_disk: int = 0
    book_days_left: int = 0
    not_started_time_budget: int = 0
    bars_built: int = 0
    bars_provisional: int = 0
    bars_failed: int = 0
    raw_deleted_files: int = 0
    raw_deleted_bytes: int = 0
    raw_kept_after_curated: int = 0
    bars_left_by_budget: int = 0
    nothing_selected: bool = False
    alerts: list[str] = field(default_factory=list)
    catalog_marked_absent: int = 0
    catalog_rebuild_needed: int = 0
    temp_files_swept: int = 0
    downloaded_bytes: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class SourceDisabledError(ConfigError):
    """A job asked for a dataset whose source is not enabled in configuration."""


def check_requested_sources(ctx: JobContext, options: IngestOptions) -> None:
    """Naming a disabled source is an error. It must never quietly fall back to something else."""
    for dataset_id in options.dataset_ids or ():
        spec = ctx.config.dataset(dataset_id)
        if not ctx.config.dataset_enabled(spec):
            raise SourceDisabledError(
                f"dataset {dataset_id} needs source {spec.venue}, which is disabled in configuration"
            )


def curated_path(ctx: JobContext, spec: DatasetSpec, symbol: str, partition: dt.date) -> Path:
    if spec.granularity == "month":
        return ctx.root.curated_month_part(spec.curated, spec.venue, symbol, partition)
    return ctx.root.curated_part(spec.curated, spec.venue, symbol, partition)


def sync_catalog_with_disk(ctx: JobContext) -> tuple[int, int]:
    """Make the catalog match the disk after a lost cache or a disposed runner.

    Raw files vanish with each runner, and that is expected. A curated file that vanished means its work must
    be redone, so its task reopens.
    """
    now = ctx.now_iso()
    absent = 0
    reopened = 0
    for record in ctx.catalog.files(status="present"):
        try:
            present = ctx.root.guard.check(record.rel_path).is_file()
        except PathGuardError:
            present = False
        if present:
            continue
        ctx.catalog.set_file_status(record.rel_path, "absent", now)
        absent += 1
        if not record.rel_path.startswith("curated/") or record.partition_key is None:
            continue
        reopened += _reopen_task_for(ctx, record.rel_path, record.kind, record.partition_key)
    return absent, reopened


def _reopen_task_for(ctx: JobContext, rel_path: str, kind: str, partition_key: str) -> int:
    """Set the task that produced a lost curated file back to pending."""
    fields = {part.split("=")[0]: part.split("=", 1)[1] for part in rel_path.split("/") if "=" in part}
    venue = fields.get("venue")
    symbol = fields.get("symbol")
    if venue is None or symbol is None:
        return 0
    now = ctx.now_iso()
    if kind.startswith("bars_"):
        key = derive_task_key(venue, symbol, dt.date.fromisoformat(partition_key))
        ctx.catalog.set_task(
            key,
            dataset_id=derive_dataset_id(venue),
            symbol=symbol,
            partition_key=partition_key,
            state=STATE_PENDING,
            now=now,
        )
        return 1
    for spec in ctx.config.datasets:
        if spec.venue == venue and spec.curated == kind:
            ctx.catalog.set_task(
                f"archive:{spec.id}:{symbol}:{partition_key}",
                dataset_id=spec.id,
                symbol=symbol,
                partition_key=partition_key,
                state=STATE_PENDING,
                now=now,
                attempts=0,
            )
            return 1
    return 0


def plan_tasks(ctx: JobContext, options: IngestOptions) -> list[Task]:
    """Everything still open, newest first. On the same date, lighter datasets go first."""
    now = ctx.now()
    tasks: list[Task] = []
    for spec in ctx.config.datasets:
        if not ctx.config.dataset_enabled(spec):
            continue
        if options.dataset_ids is not None:
            if spec.id not in options.dataset_ids:
                continue
        elif spec.opt_in and not options.include_book:
            continue
        symbols = options.symbols if options.symbols is not None else ctx.config.symbols
        for symbol in symbols:
            states = ctx.catalog.task_states(spec.id, symbol)
            ceiling = ctx.config.last_opened_date
            for partition in expected_partitions(spec, now, options.start, options.end, ceiling=ceiling):
                task = Task(spec, symbol, partition)
                if states.get(task.partition_key) != STATE_DONE:
                    tasks.append(task)
    tasks.sort(key=lambda t: (-t.partition.toordinal(), t.spec.priority, t.symbol))
    return tasks


def _retry_at(ctx: JobContext, attempts: int) -> str:
    minutes = ctx.config.retry_base_minutes * (2 ** max(0, attempts - 1))
    capped = min(minutes, ctx.config.retry_max_hours * 60.0)
    return iso(ctx.now() + dt.timedelta(minutes=capped))


def _set_failed(ctx: JobContext, task: Task, message: str) -> None:
    current = ctx.catalog.get_task(task.key)
    attempts = (current.attempts if current else 0) + 1
    ctx.catalog.set_task(
        task.key,
        dataset_id=task.spec.id,
        symbol=task.symbol,
        partition_key=task.partition_key,
        state=STATE_FAILED,
        now=ctx.now_iso(),
        attempts=attempts,
        last_error=message[:500],
        next_retry_at=_retry_at(ctx, attempts),
    )


def publishable_reason(text: str) -> str:
    """A reason that can go on a public branch: no numbers, which could be row values, and no paths."""
    without_paths = _PATH_LIKE.sub("<path>", text)
    return _LONG_NUMBER.sub("#", without_paths)[:300]


def _quarantine_file(
    ctx: JobContext, path: Path, rel_name: str, *, task: Task, reason: str, source_url: str | None
) -> None:
    """Move a bad file aside and record it. The file leaves with the runner, so the record is what stays."""
    size = path.stat().st_size
    digest = sha256_file(path)
    target = ctx.root.quarantine_path(rel_name, ctx.now().strftime("%Y%m%dT%H%M%SZ"))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    append_jsonl(
        ctx.root.guard.check(QUARANTINE_LOG),
        {
            "time": ctx.now_iso(),
            "dataset": task.spec.id,
            "symbol": task.symbol,
            "partition": task.partition_key,
            "source_url": source_url,
            "path": ctx.relative(target),
            "size": size,
            "sha256": digest,
            "reason": publishable_reason(reason),
            "code_version": code_version(),
            "run_id": ctx.run_id,
            "data_kind": "SYNTHETIC" if ctx.root.is_synthetic else "MARKET",
        },
        guard=ctx.root.guard,
    )


def _fetch_raw(
    ctx: JobContext, fetcher: Fetcher, task: Task, summary: IngestSummary, *, refetch: bool
) -> tuple[Path, ArchiveFile, dict[str, Any]]:
    """Download into a temporary name, verify any checksum, then rename into the raw zone.

    refetch ignores a copy already on disk, because a retry after a failed check is looking for a better file.
    No partition past the last opened date is fetched into a root that a report could open, however it was
    asked for.
    """
    if partition_last_day(task.spec, task.partition) > ctx.config.last_opened_date:
        raise DateGuardError(f"{task.partition} is after the last opened date, so it is not fetched here")
    limits = ctx.config.fetch
    last_missing: NotPublishedError | None = None
    for candidate in archive_candidates(ctx.config, task.spec, task.symbol, task.partition):
        final = ctx.root.raw_archive_path(
            task.spec.venue, task.spec.kind, task.symbol, task.partition, candidate.filename
        )
        record = ctx.catalog.get_file(ctx.relative(final))
        if (
            not refetch
            and final.is_file()
            and record is not None
            and record.status == "present"
            and record.sha256 == sha256_file(final)
        ):
            return final, candidate, {"reused": True}
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = temp_path_for(final)
        try:
            summary.downloaded_bytes += fetcher.download(candidate.url, temporary, limits.max_download_bytes)
        except NotPublishedError as exc:
            temporary.unlink(missing_ok=True)
            last_missing = exc
            continue
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        digest = sha256_file(temporary)
        checks: dict[str, Any] = {"sha256": digest, "checksum_source": "none"}
        if candidate.checksum_url is not None:
            try:
                sidecar = fetcher.get_bytes(candidate.checksum_url, _SIDECAR_LIMIT)
            except NotPublishedError:
                sidecar = None
            if sidecar is not None:
                try:
                    expected = parse_checksum_sidecar(
                        sidecar.decode("utf-8", errors="replace"), candidate.filename
                    )
                    if digest != expected:
                        raise ValidationError("SHA-256 does not match the checksum sidecar")
                except ValidationError as exc:
                    _quarantine_file(
                        ctx,
                        temporary,
                        ctx.relative(final),
                        task=task,
                        reason=f"checksum: {exc}",
                        source_url=candidate.url,
                    )
                    raise
                checks["checksum_source"] = "sidecar"
        temporary.replace(final)
        return final, candidate, checks
    raise last_missing if last_missing is not None else NotPublishedError(task.key)


def _parse(ctx: JobContext, task: Task, raw: Path) -> CuratedResult:
    limit = ctx.config.fetch.max_uncompressed_bytes
    kind = task.spec.kind
    venue = task.spec.venue
    source = ctx.config.source(venue)
    allowance_us = source.fill_span_allowance_us
    if kind == "aggTrades":
        return parse_agg_trades(
            raw, task.symbol, task.partition, limit, venue=venue, allowance_us=allowance_us
        )
    if kind == "trades":
        return parse_bybit_trades(
            raw, task.symbol, task.partition, limit, venue=venue, allowance_us=allowance_us
        )
    if kind == "klines":
        # On bars from candles the candle's own allowance applies. Elsewhere they are only a check on trades.
        return parse_klines(
            raw,
            task.symbol,
            task.partition,
            limit,
            venue=venue,
            allowance_us=source.bar_allowance_us,
            last_day=partition_last_day(task.spec, task.partition),
        )
    if kind == "bookDepth":
        return parse_book_depth(
            raw, task.symbol, task.partition, limit, ctx.config.book_depth_allowance_s, venue=venue
        )
    if kind == "fundingRate":
        return parse_funding(raw, task.symbol, task.partition, limit, venue=venue, allowance_us=allowance_us)
    raise ValueError(f"no parser for {kind}")


def _refuse_future_stamps(ctx: JobContext, result: CuratedResult) -> None:
    """A row stamped ahead of the clock cannot be real, so nothing built on it can be trusted."""
    newest = result.checks.get("last_ts_us")
    limit = to_us(ctx.now()) + round(ctx.config.max_future_skew_s * MICROS_PER_SECOND)
    if newest is not None and int(newest) > limit:
        raise ValidationError(f"a row is stamped {iso_us(int(newest))}, ahead of the clock")


def _book_result(raw: Path, task: Task) -> CuratedResult:
    """Book files yield replay statistics only. Book features are not defined yet."""
    replay = replay_zip(raw)
    detail = replay.to_dict()
    if not replay.ok:
        raise ValidationError(f"book replay failed: {detail}")
    row = {k: v for k, v in detail.items() if k not in ("break_examples",)}
    frame = pl.DataFrame([{"venue": task.spec.venue, "symbol": task.symbol, **row}])
    return CuratedResult(frame, detail)


def run_archive_task(ctx: JobContext, fetcher: Fetcher, task: Task, summary: IngestSummary) -> str:
    """Process one partition from download to curated. Return the state it ended in."""
    now_iso = ctx.now_iso()
    spec = task.spec
    before = ctx.catalog.get_task(task.key)
    refetch = before is not None and before.state == STATE_FAILED
    try:
        raw, source, raw_checks = _fetch_raw(ctx, fetcher, task, summary, refetch=refetch)
    except NotPublishedError:
        overdue_at = task.partition_end() + dt.timedelta(hours=spec.overdue_hours)
        state = STATE_OVERDUE if ctx.now() > overdue_at else STATE_PENDING
        ctx.catalog.set_task(
            task.key,
            dataset_id=spec.id,
            symbol=task.symbol,
            partition_key=task.partition_key,
            state=state,
            now=now_iso,
            last_error=None if state == STATE_PENDING else "not published yet, past its overdue time",
        )
        return state
    except ValidationError as exc:
        _set_failed(ctx, task, f"validation: {exc}")
        summary.errors.append(f"{task.key}: {exc}")
        return STATE_FAILED
    except FetchError as exc:
        _set_failed(ctx, task, f"download: {exc}")
        summary.errors.append(f"{task.key}: {exc}")
        return STATE_FAILED

    raw_rel = ctx.relative(raw)
    partition_text = task.partition.isoformat()
    date_end = (
        (next_month(task.partition) - dt.timedelta(days=1)).isoformat()
        if spec.granularity == "month"
        else partition_text
    )
    if not raw_checks.get("reused"):
        ctx.register_output(
            raw,
            dataset_id=f"raw.{spec.venue}.{spec.kind}.{task.symbol}",
            kind=spec.kind,
            zone="raw/archive",
            partition_key=task.partition_key,
            date_start=partition_text,
            date_end=date_end,
            rows=None,
            check_status="pass",
            check_detail=raw_checks,
            source_url=source.url,
            tier=spec.tier,
            venue=spec.venue,
            symbol=task.symbol,
            terms_note=ctx.config.source(spec.venue).terms_note,
        )
    try:
        result = _book_result(raw, task) if spec.kind == "orderbook" else _parse(ctx, task, raw)
        _refuse_future_stamps(ctx, result)
    except ValidationError as exc:
        _quarantine_file(ctx, raw, raw_rel, task=task, reason=f"validation: {exc}", source_url=source.url)
        ctx.catalog.set_file_status(raw_rel, "quarantined", now_iso)
        _set_failed(ctx, task, f"validation: {exc}")
        summary.errors.append(f"{task.key}: {exc}")
        return STATE_FAILED

    # A long silence is not here. It is a state of the market, so it never sets a status (DR-13).
    warnings = list(result.warnings)
    target = curated_path(ctx, spec, task.symbol, task.partition)
    atomic_write_parquet(target, result.frame, guard=ctx.root.guard)
    ctx.register_output(
        target,
        dataset_id=f"curated.{spec.curated}.{spec.venue}.{task.symbol}",
        kind=spec.curated,
        zone="curated",
        partition_key=task.partition_key,
        date_start=partition_text,
        date_end=date_end,
        rows=result.frame.height,
        check_status="warn" if warnings else "pass",
        check_detail={**result.checks, "warnings": warnings},
        parents=[raw_rel],
        tier=spec.tier,
        venue=spec.venue,
        symbol=task.symbol,
        terms_note=ctx.config.source(spec.venue).terms_note,
    )
    ctx.catalog.set_task(
        task.key,
        dataset_id=spec.id,
        symbol=task.symbol,
        partition_key=task.partition_key,
        state=STATE_DONE,
        now=now_iso,
        attempts=0,
    )
    # What this file feeds has to be built again, whatever state it was left in. A replaced file also changes
    # what its neighbours can conclude about the midnight between them.
    if spec.curated == base_dataset(ctx.config.source(spec.venue)):
        # A candle file decides only its own days. A trade file also reaches over both midnights.
        if spec.curated == OFFICIAL:
            for day in date_range(task.partition, partition_last_day(spec, task.partition)):
                reopen_day(ctx, spec.venue, task.symbol, day)
        else:
            for offset in (-1, 0, 1):
                reopen_day(ctx, spec.venue, task.symbol, task.partition + dt.timedelta(days=offset))
    elif spec.curated == OFFICIAL:
        for offset in (-1, 0, 1):
            reopen_day(ctx, spec.venue, task.symbol, task.partition + dt.timedelta(days=offset))
    return STATE_DONE


def _fail_derive(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, reason: str, summary: IngestSummary
) -> None:
    """Record a failed day and schedule both of its files to be fetched again, in case a good one appears."""
    key = derive_task_key(venue, symbol, day)
    summary.bars_failed += 1
    summary.errors.append(f"{key}: {reason}")
    current = ctx.catalog.get_task(key)
    attempts = (current.attempts if current else 0) + 1
    retry_at = _retry_at(ctx, attempts)
    ctx.catalog.set_task(
        key,
        dataset_id=derive_dataset_id(venue),
        symbol=symbol,
        partition_key=day.isoformat(),
        state=STATE_FAILED,
        now=ctx.now_iso(),
        attempts=attempts,
        last_error=reason[:500],
        next_retry_at=retry_at,
    )
    for spec in ctx.config.datasets:
        if spec.venue == venue and spec.curated in (TRADES, OFFICIAL):
            ctx.catalog.set_task(
                f"archive:{spec.id}:{symbol}:{day.isoformat()}",
                dataset_id=spec.id,
                symbol=symbol,
                partition_key=day.isoformat(),
                state=STATE_FAILED,
                now=ctx.now_iso(),
                attempts=attempts,
                last_error="the bars built from this file failed a check",
                next_retry_at=retry_at,
            )


def _run_derive(ctx: JobContext, venue: str, symbol: str, day: dt.date, summary: IngestSummary) -> None:
    key = derive_task_key(venue, symbol, day)
    try:
        outcome = derive_day(ctx, venue, symbol, day)
    except Exception as exc:
        # One bad day must not stop the others. Its task stays open and the next run tries again.
        _fail_derive(ctx, venue, symbol, day, f"{type(exc).__name__}: {exc}", summary)
        return
    if outcome.state == STATE_FAILED:
        _fail_derive(ctx, venue, symbol, day, str(outcome.reason), summary)
        return
    summary.bars_built += 1
    if outcome.state == STATE_PROVISIONAL:
        summary.bars_provisional += 1
    ctx.catalog.set_task(
        key,
        dataset_id=derive_dataset_id(venue),
        symbol=symbol,
        partition_key=day.isoformat(),
        state=outcome.state,
        now=ctx.now_iso(),
        attempts=0 if outcome.state == STATE_DONE else None,
    )


def _delete_raw_for(ctx: JobContext, task: Task, summary: IngestSummary) -> None:
    """Raw data is transient: it goes as soon as the protocol says its derived data passes."""
    prefix = (
        f"raw/archive/{task.spec.venue}/{task.spec.kind}/{task.symbol}/date={task.partition.isoformat()}/"
    )
    for record in ctx.catalog.files(status="present", prefix=prefix):
        deleted, _reason = protocol_delete(ctx, record.rel_path, RAW_RULE)
        if deleted:
            summary.raw_deleted_files += 1
            summary.raw_deleted_bytes += record.size_bytes
        else:
            summary.raw_kept_after_curated += 1


def _bar_targets(ctx: JobContext, options: IngestOptions) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    symbols = options.symbols if options.symbols is not None else ctx.config.symbols
    for spec in ctx.config.datasets:
        if not ctx.config.dataset_enabled(spec):
            continue
        if spec.curated != base_dataset(ctx.config.source(spec.venue)):
            continue
        if options.dataset_ids is not None and spec.id not in options.dataset_ids:
            continue
        pairs.extend((spec.venue, symbol) for symbol in symbols)
    return pairs


def _stored_days(
    ctx: JobContext, options: IngestOptions, summary: IngestSummary
) -> list[tuple[str, str, dt.date]]:
    """Each day with a base file. A name that is not a date is a stray no job wrote, and it must not stop a
    run."""
    days: list[tuple[str, str, dt.date]] = []
    for venue, symbol in _bar_targets(ctx, options):
        source = ctx.config.source(venue)
        base = base_dataset(source)
        for part in ctx.root.curated_parts(base, venue, symbol):
            period = part_period(part)
            if period is not None and source.official_bars and period[0] != period[1]:
                # A month of candles decides each of its days.
                last = min(period[1], ctx.config.last_opened_date)
                days.extend((venue, symbol, day) for day in date_range(period[0], last))
                continue
            if period is None or period[0] != period[1]:
                alert = f"A file with a name that is not a day was skipped: {ctx.relative(part)}"
                if alert not in summary.alerts:
                    summary.alerts.append(alert)
                continue
            if period[0] > ctx.config.last_opened_date:
                alert = f"A file past the last opened date was left unread: {ctx.relative(part)}"
                if alert not in summary.alerts:
                    summary.alerts.append(alert)
                continue
            days.append((venue, symbol, period[0]))
    return days


def _sweep_open_bars(
    ctx: JobContext,
    options: IngestOptions,
    summary: IngestSummary,
    *,
    deadline: float | None,
    clock: Callable[[], float],
) -> None:
    """Rebuild any day whose inputs have changed since it was built, whichever run fetched them.

    A rebuild can make a neighbour's answer available, so this repeats until nothing changes. Newly final days
    can settle their neighbours, and each pass can only move a day towards final, so it ends. The budget
    bounds it too.
    """
    for _ in range(4):
        days = _stored_days(ctx, options, summary)
        open_days = [item for item in days if needs_derive(ctx, *item)]
        if not open_days:
            return
        for index, (venue, symbol, day) in enumerate(open_days):
            if deadline is not None and clock() >= deadline:
                summary.bars_left_by_budget = len(open_days) - index
                return
            _run_derive(ctx, venue, symbol, day, summary)


def _delete_settled_raw(ctx: JobContext, summary: IngestSummary) -> None:
    """A last pass: a file kept earlier in this run may now be allowed to go. The protocol decides each
    one."""
    kept = 0
    for record in ctx.catalog.files(status="present", prefix="raw/archive/"):
        deleted, _reason = protocol_delete(ctx, record.rel_path, RAW_RULE)
        if deleted:
            summary.raw_deleted_files += 1
            summary.raw_deleted_bytes += record.size_bytes
        else:
            kept += 1
    summary.raw_kept_after_curated = kept


def _persisted(summary: IngestSummary) -> dict[str, Any]:
    """The summary as stored. Wall-clock time stays out of it, so the same inputs give identical files."""
    values = asdict(summary)
    del values["seconds"]
    return values


def _contain_task_failure(ctx: JobContext, task: Task, exc: Exception, summary: IngestSummary) -> None:
    """Record whatever escaped, keep the evidence out of the way, and let the run go on."""
    message = f"{type(exc).__name__}: {exc}"
    reason = message
    prefix = (
        f"raw/archive/{task.spec.venue}/{task.spec.kind}/{task.symbol}/date={task.partition.isoformat()}/"
    )
    for record in ctx.catalog.files(status="present", prefix=prefix):
        try:
            path = ctx.root.guard.check(record.rel_path)
            if path.is_file():
                _quarantine_file(
                    ctx, path, record.rel_path, task=task, reason=reason, source_url=record.source_url
                )
            ctx.catalog.set_file_status(record.rel_path, "quarantined", ctx.now_iso())
        except (PathGuardError, OSError) as quarantine_error:
            message += f"; could not quarantine: {quarantine_error}"
    _set_failed(ctx, task, message)
    summary.errors.append(f"{task.key}: {message}")


def _finish_status(summary: IngestSummary) -> str:
    if summary.nothing_selected:
        return "nothing_selected"
    if (
        summary.not_started_time_budget
        or summary.held_by_watermark
        or summary.held_by_disk
        or summary.bars_left_by_budget
    ):
        return "partial"
    if summary.failed or summary.bars_failed:
        return "partial"
    return "ok"


def free_disk_bytes(ctx: JobContext) -> int:
    """Free space where raw files land. They leave with the runner, so they spend no cache budget, but they
    can fill it."""
    return shutil.disk_usage(ctx.root.path).free


def _budget_order(ctx: JobContext, tasks: list[Task]) -> list[Task]:
    """Tasks never tried take the budget first, and retries get what is left.

    Work is newest first, so if failing newest files could use the whole budget again on every run, older days
    would never be reached.
    """
    fresh: list[Task] = []
    retries: list[Task] = []
    for task in tasks:
        row = ctx.catalog.get_task(task.key)
        (retries if row is not None and row.state == STATE_FAILED else fresh).append(task)
    return [*fresh, *retries]


def _note_unstarted(ctx: JobContext, summary: IngestSummary) -> None:
    """Count runs in a row that left work unstarted, and say so once it is a pattern and not one long day."""
    previous = int(ctx.catalog.get_meta("unstarted_runs") or 0)
    streak = previous + 1 if summary.not_started_time_budget else 0
    ctx.catalog.set_meta("unstarted_runs", str(streak))
    if streak >= UNSTARTED_ALERT_RUNS:
        summary.alerts.append(
            f"{streak} runs in a row ran out of time, with {summary.not_started_time_budget} partitions "
            "left unstarted this time."
        )


def _run_tasks(
    ctx: JobContext,
    fetcher: Fetcher,
    options: IngestOptions,
    summary: IngestSummary,
    *,
    deadline: float | None,
    clock: Callable[[], float],
) -> None:
    tasks = _budget_order(ctx, plan_tasks(ctx, options))
    summary.planned = len(tasks)
    # An approved source with nothing selected must not look like a healthy run that fetched nothing.
    if options.dataset_ids is not None:
        selected = {spec.venue for spec in ctx.config.datasets if spec.id in options.dataset_ids}
        for name in ctx.config.enabled_sources():
            if name not in selected:
                summary.alerts.append(
                    f"Approved source {name} has no dataset selected, so nothing was fetched."
                )
        summary.nothing_selected = not selected
    quota = quota_bytes(ctx.config.default_quota_gb)
    routine_since = ctx.now().date() - dt.timedelta(days=ctx.config.routine_window_days)
    books_done = 0
    for index, task in enumerate(tasks):
        if deadline is not None and clock() >= deadline:
            summary.not_started_time_budget = len(tasks) - index
            break
        if task.spec.kind == "orderbook" and books_done >= ctx.config.max_book_days_per_run:
            summary.book_days_left += 1
            continue
        state_row = ctx.catalog.get_task(task.key)
        if (
            state_row is not None
            and state_row.state == STATE_FAILED
            and state_row.next_retry_at is not None
            and state_row.next_retry_at > ctx.now_iso()
        ):
            summary.skipped_retry_wait += 1
            continue
        # Against the cache budget, because raw and quarantine leave with the runner and spend none of it.
        used = persisted_bytes(measure_zones(ctx.root), ctx.config.persisted_zones)
        storage = evaluate_watermarks(used, quota, ctx.policy.watermarks)
        # A backfill stops first. At the critical level only essential work runs, and ingest is not essential.
        if storage.level == LEVEL_CRITICAL or (storage.stop_backfill and task.partition < routine_since):
            summary.held_by_watermark += 1
            continue
        # Watermarks no longer see raw files, so this is what stops one from filling the runner's disk.
        if free_disk_bytes(ctx) < ctx.config.fetch.max_download_bytes:
            summary.held_by_disk += 1
            alert = "The runner's disk has less free space than one file may take, so downloads are held."
            if alert not in summary.alerts:
                summary.alerts.append(alert)
            continue
        try:
            state = run_archive_task(ctx, fetcher, task, summary)
        except Exception as exc:
            # One bad partition can never stop the others. Work is newest first, so an escape here would hit
            # the same file again on every later run, and catch-up would never get past it.
            _contain_task_failure(ctx, task, exc, summary)
            summary.failed += 1
            continue
        if state == STATE_DONE:
            summary.done += 1
            if task.spec.kind == "orderbook":
                books_done += 1
            venue, symbol, day = task.spec.venue, task.symbol, task.partition
            # With the partner file still to come in this run, wait for it. Deriving now would judge the new
            # file against the old one, and that is how a failed day used to stay failed.
            waiting = task.spec.curated == OFFICIAL and any(
                later.spec.curated == TRADES
                and later.spec.venue == venue
                and later.symbol == symbol
                and later.partition == day
                for later in tasks[index + 1 :]
            )
            if task.spec.curated in (TRADES, OFFICIAL) and not waiting:
                for target in (day, day - dt.timedelta(days=1)):
                    if needs_derive(ctx, venue, symbol, target):
                        _run_derive(ctx, venue, symbol, target, summary)
            if options.delete_raw:
                _delete_raw_for(ctx, task, summary)
        elif state == STATE_PENDING:
            summary.pending += 1
        elif state == STATE_OVERDUE:
            summary.overdue += 1
            summary.alerts.append(f"{task.key} is overdue")
        else:
            summary.failed += 1
    _note_unstarted(ctx, summary)
    _sweep_open_bars(ctx, options, summary, deadline=deadline, clock=clock)
    if options.delete_raw:
        _delete_settled_raw(ctx, summary)


def run_ingest(
    ctx: JobContext,
    fetcher: Fetcher,
    options: IngestOptions,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> IngestSummary:
    """Run catch-up until the work is done or the time budget ends. Stopping early is never a failure.

    The run row always finishes. Whatever escapes the containment around tasks ends the run with status
    `failed` and goes on up, so that the job says so too.
    """
    ctx.root.refuse_unopened("ingest")
    check_requested_sources(ctx, options)
    summary = IngestSummary(run_id=ctx.run_id)
    started = clock()
    deadline = None if options.time_budget_s is None else started + options.time_budget_s
    ctx.catalog.start_run(
        ctx.run_id,
        "ingest",
        now=ctx.now_iso(),
        code_version=code_version(),
        config_hash=ctx.config.config_hash,
    )
    try:
        zones = tuple(zone for zone in ZONE_DIRS if zone not in ("ledger", "decisions"))
        summary.temp_files_swept = len(sweep_temp_files(ctx.root.guard, zones))
        summary.catalog_marked_absent, summary.catalog_rebuild_needed = sync_catalog_with_disk(ctx)

        if not ctx.config.enabled_sources():
            # Not a failure and not a reason to try anything else. The report says so plainly.
            summary.source_state = NO_APPROVED_SOURCE
            summary.status = "no_approved_source"
            write_heartbeat(
                ctx.root, "ingest", now=ctx.now(), detail={"status": summary.status, "run_id": ctx.run_id}
            )
            ctx.catalog.finish_run(
                ctx.run_id, now=ctx.now_iso(), status=summary.status, summary=_persisted(summary)
            )
            return summary

        _run_tasks(ctx, fetcher, options, summary, deadline=deadline, clock=clock)
    except Exception as exc:
        summary.status = "failed"
        summary.errors.append(f"{type(exc).__name__}: {exc}")
        ctx.catalog.finish_run(ctx.run_id, now=ctx.now_iso(), status="failed", summary=_persisted(summary))
        raise
    summary.seconds = round(clock() - started, 3)
    summary.status = _finish_status(summary)
    summary.source_state = ctx.config.source_state()
    write_heartbeat(
        ctx.root,
        "ingest",
        now=ctx.now(),
        detail={"status": summary.status, "done": summary.done, "run_id": ctx.run_id},
    )
    ctx.catalog.finish_run(ctx.run_id, now=ctx.now_iso(), status=summary.status, summary=_persisted(summary))
    atomic_write_json(
        ctx.root.guard.check("catalog/last_ingest.json"), _persisted(summary), guard=ctx.root.guard
    )
    # Health reads these, which is how they reach the page and the watchdog. Each overdue file already counts
    # there.
    carried = [alert for alert in summary.alerts if not alert.endswith("is overdue")]
    ctx.catalog.set_meta("last_ingest_alerts", json.dumps(carried, sort_keys=True))
    return summary
