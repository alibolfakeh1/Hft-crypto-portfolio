"""Retention job. Implements docs/05_DATA_LIFECYCLE.md: classes, watermarks and the deletion protocol.

It is a dry run unless explicitly told otherwise. A real delete needs the explicit flag and a rule marked
reviewed. Whatever the configuration says, these hold:

- A path outside DATA_ROOT or passing through a link is refused.
- The ledger, decisions and catalog zones are never selected.
- IRREPLACEABLE data inside its retention period is never deleted, at any watermark.
- A file not in the catalog is never deleted, because nothing is known about it.
- Raw data goes only when its derived data exists and passes its checks.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

from hft_crypto.config import (
    FORBIDDEN_RETENTION_ZONES,
    ConfigError,
    RetentionPolicy,
    RetentionRule,
    Watermarks,
    quota_bytes,
)
from hft_crypto.data.atomic import append_jsonl, sha256_file
from hft_crypto.data.catalog import Catalog, FileRecord
from hft_crypto.data.context import JobContext
from hft_crypto.data.guard import PathGuardError, canonical_rel_path
from hft_crypto.data.zones import DataClass, DataRoot, classify, measure_zones
from hft_crypto.timeutil import iso, parse_iso
from hft_crypto.versioning import code_version

LEVEL_NORMAL = "normal"
LEVEL_WARN = "warn"
LEVEL_STOP_BACKFILL = "stop_backfill"
LEVEL_PURGE_RAW = "purge_raw"
LEVEL_PURGE_RUNS = "purge_runs"
LEVEL_CRITICAL = "critical"


@dataclass(frozen=True)
class WatermarkState:
    used_bytes: int
    quota_bytes: int
    used_pct: float
    level: str
    stop_backfill: bool
    pause_feature_rebuilds: bool
    alerts: tuple[str, ...]
    headroom_days: float | None


def evaluate_watermarks(
    used_bytes: int,
    quota_bytes: int,
    marks: Watermarks,
    *,
    days_until_full: float | None = None,
    live_growth_bytes_per_day: float | None = None,
) -> WatermarkState:
    """Map disk use to the actions in section 4 of the lifecycle document."""
    used_pct = 100.0 * used_bytes / quota_bytes
    alerts: list[str] = []
    level = LEVEL_NORMAL
    if used_pct >= marks.critical_pct:
        level = LEVEL_CRITICAL
        alerts.append(f"URGENT: storage at {used_pct:.1f}%. Only essential work continues.")
    elif used_pct >= marks.purge_runs_pct:
        level = LEVEL_PURGE_RUNS
        alerts.append(f"Storage at {used_pct:.1f}%. Feature rebuilds paused. The owner must look.")
    elif used_pct >= marks.purge_raw_pct:
        level = LEVEL_PURGE_RAW
        alerts.append(f"Storage at {used_pct:.1f}%. Deleting raw data past its derived-data check.")
    elif used_pct >= marks.stop_backfill_pct:
        level = LEVEL_STOP_BACKFILL
        alerts.append(f"Storage at {used_pct:.1f}%. New backfills stopped.")
    elif used_pct >= marks.warn_pct:
        level = LEVEL_WARN
        horizon = "unknown" if days_until_full is None else f"{days_until_full:.0f} days"
        alerts.append(f"Storage at {used_pct:.1f}%. Time until full at current growth: {horizon}.")
    # Headroom protects anything recording live data. With no recorder it stays None and never fires.
    headroom = None
    if live_growth_bytes_per_day is not None and live_growth_bytes_per_day > 0:
        headroom = max(0, quota_bytes - used_bytes) / live_growth_bytes_per_day
        if headroom < marks.headroom_alert_days:
            alerts.append(f"URGENT: only {headroom:.1f} days of recording headroom left.")
    return WatermarkState(
        used_bytes=used_bytes,
        quota_bytes=quota_bytes,
        used_pct=round(used_pct, 3),
        level=level,
        stop_backfill=used_pct >= marks.stop_backfill_pct,
        pause_feature_rebuilds=used_pct >= marks.purge_runs_pct,
        alerts=tuple(alerts),
        headroom_days=None if headroom is None else round(headroom, 2),
    )


@dataclass(frozen=True)
class PlanItem:
    rel_path: str
    data_class: str
    size_bytes: int
    rule_id: str
    action: str  # delete or blocked
    reason: str
    reviewed: bool
    created_at: str


@dataclass
class RetentionPlan:
    generated_at: str
    policy_version: str
    used_bytes: int
    quota_bytes: int
    watermark_level: str
    alerts: list[str]
    deletable: list[PlanItem] = field(default_factory=list)
    blocked: list[PlanItem] = field(default_factory=list)

    @property
    def bytes_freed_if_run(self) -> int:
        # A file selected by two rules still frees its bytes only once.
        sizes = {item.rel_path: item.size_bytes for item in self.deletable if item.reviewed}
        return sum(sizes.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "policy_version": self.policy_version,
            "used_bytes": self.used_bytes,
            "quota_bytes": self.quota_bytes,
            "watermark_level": self.watermark_level,
            "alerts": self.alerts,
            "summary": _summary(self.deletable, self.blocked),
            "bytes_freed_if_run": self.bytes_freed_if_run,
            "deletable": [asdict(item) for item in self.deletable],
            "blocked": [asdict(item) for item in self.blocked],
        }


def _summary(deletable: list[PlanItem], blocked: list[PlanItem]) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for label, items in (("deletable", deletable), ("blocked", blocked)):
        for item in items:
            entry = rows.setdefault(
                item.rule_id,
                {"deletable_files": 0, "deletable_bytes": 0, "blocked_files": 0, "blocked_bytes": 0},
            )
            entry[f"{label}_files"] += 1
            entry[f"{label}_bytes"] += item.size_bytes
    return rows


def _is_sample_day(record: FileRecord, policy: RetentionPolicy) -> bool:
    """The monthly regression sample. Selected by a fixed rule, never by looking at the data."""
    sample = policy.sample_days
    if record.partition_key is None or len(record.partition_key) != 10:
        return False
    if record.rel_path.startswith("raw/archive/"):
        selected = sample.protect_raw
    else:
        selected = record.kind in sample.kinds
    return selected and dt.date.fromisoformat(record.partition_key).day == sample.day_of_month


def effective_class(
    catalog: Catalog, record: FileRecord, policy: RetentionPolicy, rule: RetentionRule
) -> DataClass | None:
    """The class this file must be treated as. The zone decides first, and only the safe direction is open.

    Derived data whose raw data is gone is treated as IRREPLACEABLE, unless the rule explicitly relies on
    every raw parent being refetchable from a public archive.
    """
    base = classify(record.rel_path)
    if base is None:
        return None
    if _is_sample_day(record, policy):
        return DataClass.IRREPLACEABLE
    if base is not DataClass.DERIVED or record.rel_path.startswith("results/"):
        return base
    raw_parents = [a for a in catalog.ancestors_of(record.rel_path) if a.rel_path.startswith("raw/")]
    if not raw_parents:
        return DataClass.IRREPLACEABLE
    if all(a.status == "present" for a in raw_parents):
        return base
    if rule.rebuildable_from_archive and all(
        a.rel_path.startswith("raw/archive/") and a.source_url for a in raw_parents
    ):
        return base
    return DataClass.IRREPLACEABLE


def _age_days(record: FileRecord, now: dt.datetime) -> float:
    return (now - parse_iso(record.created_at)).total_seconds() / 86_400.0


def check_preconditions(
    root: DataRoot, catalog: Catalog, record: FileRecord, rule: RetentionRule
) -> str | None:
    """Step 2 of the protocol. Return why a deletion must not happen, or None if it may."""
    required = rule.requires.get(record.kind) or rule.requires.get("*") or ()
    if record.rel_path.startswith("raw/"):
        # Fail closed: raw data with no stated requirement has no evidence that anything replaced it.
        if not required:
            return f"no derived-data requirement is declared for kind {record.kind}"
        if record.rel_path.startswith("raw/archive/") and not record.source_url:
            return "no source URL is recorded, so nothing could fetch this file again"
    if required:
        descendants = catalog.descendants_of(record.rel_path)
        for kind, accepted in required:
            matching = [d for d in descendants if d.kind == kind and d.status == "present"]
            if not matching:
                return f"derived data missing: {kind}"
            for child in matching:
                if child.check_status not in accepted:
                    return f"derived data not passing: {kind} is {child.check_status}"
                try:
                    canonical_rel_path(child.rel_path)
                    if not root.guard.check(child.rel_path).is_file():
                        return f"derived file missing from disk: {child.rel_path}"
                except PathGuardError as exc:
                    return f"derived file path refused: {exc}"
    dependent_runs = catalog.published_runs_depending_on(record.rel_path)
    if dependent_runs and not (record.rel_path.startswith("raw/archive/") and record.source_url):
        return f"published run depends on it and it cannot be rebuilt: {dependent_runs[0]}"
    if rule.unpublished_only:
        parts = record.rel_path.split("/")
        run = catalog.get_run(parts[2]) if len(parts) > 2 else None
        if run is None:
            return "run not found in the catalog"
        if run["published"]:
            return "published run results are kept forever"
    return None


def _in_forbidden_zone(rel_path: str) -> bool:
    return any(rel_path == z or rel_path.startswith(f"{z}/") for z in FORBIDDEN_RETENTION_ZONES)


def _evaluate(
    root: DataRoot,
    catalog: Catalog,
    policy: RetentionPolicy,
    rule: RetentionRule,
    record: FileRecord,
    now: dt.datetime,
    used_pct: float,
) -> tuple[str, str, bool, DataClass | None]:
    """Decide one file for one rule. Return action, reason, whether only a watermark allowed it, class."""
    try:
        canonical_rel_path(record.rel_path)
        if root.guard.relative(record.rel_path) != record.rel_path:
            return "blocked", "path refused: it does not name itself", False, None
    except PathGuardError as exc:
        return "blocked", f"path refused: {exc}", False, None
    if _in_forbidden_zone(record.rel_path):
        return "blocked", "this zone is never deleted", False, None
    try:
        data_class = effective_class(catalog, record, policy, rule)
        age = _age_days(record, now)
    except ValueError as exc:
        return "blocked", f"catalog row cannot be read: {exc}", False, None
    if data_class is None:
        return "blocked", "unknown class, so it is not deleted", False, None
    old_enough = age >= rule.min_age_days
    if data_class is DataClass.IRREPLACEABLE:
        if not rule.zone.startswith("raw/live"):
            return "blocked", "IRREPLACEABLE and has no retention period", False, data_class
        if not old_enough:
            # No watermark can reach this branch's way out.
            return "blocked", "IRREPLACEABLE inside its retention period", False, data_class
    bypass = (
        not old_enough
        and rule.watermark_bypass_pct is not None
        and used_pct >= rule.watermark_bypass_pct
        and age >= rule.watermark_min_age_days
    )
    if not old_enough and not bypass:
        return "blocked", f"age {age:.1f} days is below {rule.min_age_days:g}", False, data_class
    problem = check_preconditions(root, catalog, record, rule)
    if problem is not None:
        return "blocked", problem, False, data_class
    return "delete", "watermark" if bypass else "age", bypass, data_class


def _rule_applies(rule: RetentionRule, record: FileRecord) -> bool:
    if not (record.rel_path == rule.zone or record.rel_path.startswith(f"{rule.zone}/")):
        return False
    return "*" in rule.kinds or record.kind in rule.kinds


def build_plan(
    root: DataRoot,
    catalog: Catalog,
    policy: RetentionPolicy,
    state: WatermarkState,
    now: dt.datetime,
) -> RetentionPlan:
    """Step 1 of the protocol. Lists each file, class, size and rule. Touches nothing."""
    plan = RetentionPlan(
        generated_at=iso(now),
        policy_version=policy.policy_version,
        used_bytes=state.used_bytes,
        quota_bytes=state.quota_bytes,
        watermark_level=state.level,
        alerts=list(state.alerts),
    )
    records = catalog.files(status="present")
    projected = state.used_bytes
    for rule in policy.rules:
        watermark_only: list[PlanItem] = []
        for record in records:
            if not _rule_applies(rule, record):
                continue
            action, reason, via_watermark, data_class = _evaluate(
                root, catalog, policy, rule, record, now, state.used_pct
            )
            item = PlanItem(
                rel_path=record.rel_path,
                data_class="UNKNOWN" if data_class is None else data_class.value,
                size_bytes=record.size_bytes,
                rule_id=rule.id,
                action=action,
                reason=reason,
                reviewed=rule.reviewed,
                created_at=record.created_at,
            )
            if action == "blocked":
                plan.blocked.append(item)
            elif via_watermark:
                watermark_only.append(item)
            else:
                plan.deletable.append(item)
                if rule.reviewed:
                    projected -= item.size_bytes
        # Beyond normal rules, a watermark frees only what it needs, oldest first.
        watermark_only.sort(key=lambda entry: (entry.created_at, entry.rel_path))
        target = state.quota_bytes * (rule.watermark_bypass_pct or 0.0) / 100.0
        for item in watermark_only:
            if projected < target:
                plan.blocked.append(
                    PlanItem(**{**asdict(item), "action": "blocked", "reason": "watermark target met"})
                )
                continue
            plan.deletable.append(item)
            if rule.reviewed:
                projected -= item.size_bytes
    return plan


class DeletionRefused(Exception):
    """The protocol stopped a deletion."""


def delete_file(ctx: JobContext, rel_path: str, rule: RetentionRule, *, used_pct: float = 0.0) -> int:
    """The only way to delete a file. Runs the whole protocol again and returns the bytes freed.

    Nothing about the file is taken from the caller: not its class, and not that a plan once allowed it. A
    plan can be stale or forged, and deletion cannot be undone. used_pct should be the storage use measured
    now, because it decides whether a watermark may shorten a retention period.
    """
    try:
        canonical_rel_path(rel_path)
    except PathGuardError as exc:
        raise DeletionRefused(str(exc)) from exc
    if not rule.reviewed:
        raise DeletionRefused(f"rule {rule.id} is not marked reviewed")
    record = ctx.catalog.get_file(rel_path)
    if record is None or record.status != "present":
        raise DeletionRefused(f"not a present catalog file: {rel_path}")
    if not _rule_applies(rule, record):
        raise DeletionRefused(f"rule {rule.id} does not cover this file: {rel_path}")
    action, reason, _, data_class = _evaluate(
        ctx.root, ctx.catalog, ctx.policy, rule, record, ctx.now(), used_pct
    )
    if action != "delete" or data_class is None:
        raise DeletionRefused(f"{rel_path}: {reason}")
    path = ctx.root.guard.check(rel_path)
    if not path.is_file():
        raise DeletionRefused(f"file is not on disk: {rel_path}")
    size = path.stat().st_size
    checksum = sha256_file(path)
    if checksum != record.sha256:
        raise DeletionRefused(f"file differs from its manifest entry: {rel_path}")
    # The log line is written first. If the delete then fails, the log shows an attempt, not a silent loss.
    now_text = ctx.now_iso()
    append_jsonl(
        ctx.root.deletions_log,
        {
            "time": now_text,
            "path": rel_path,
            "size": size,
            "checksum": checksum,
            "rule": rule.id,
            "class": data_class.value,
            "data_kind": "SYNTHETIC" if ctx.root.is_synthetic else "MARKET",
            "code_version": code_version(),
            "run_id": ctx.run_id,
        },
        guard=ctx.root.guard,
    )
    ctx.root.guard.unlink(path)
    ctx.catalog.record_deletion(
        deleted_at=now_text,
        rel_path=rel_path,
        size_bytes=size,
        sha256=checksum,
        rule_id=rule.id,
        data_class=data_class.value,
        code_version=code_version(),
        run_id=ctx.run_id,
    )
    ctx.root.guard.remove_empty_parents(path, rule.zone)
    return size


def delete_raw_if_allowed(ctx: JobContext, rel_path: str, rule_id: str) -> tuple[bool, str]:
    """Used by ingest when raw data is transient: delete now if, and only if, the protocol allows it."""
    try:
        delete_file(ctx, rel_path, ctx.policy.rule(rule_id))
    except (DeletionRefused, PathGuardError, OSError) as exc:
        return False, str(exc)
    return True, "deleted"


@dataclass
class ExecutionResult:
    deleted_files: int = 0
    deleted_bytes: int = 0
    refused: list[dict[str, str]] = field(default_factory=list)


def execute_plan(ctx: JobContext, plan: RetentionPlan) -> ExecutionResult:
    """Run a plan for real. Each item goes back through the whole protocol at the moment of deletion.

    A plan says what someone wanted. It grants nothing, so its class, size and reason are not used, and the
    storage use comes from the disk now, not from the plan.
    """
    result = ExecutionResult()
    quota = quota_bytes(ctx.config.default_quota_gb)
    used = sum(measure_zones(ctx.root).values())
    for item in plan.deletable:
        try:
            rule = ctx.policy.rule(item.rule_id)
            freed = delete_file(ctx, item.rel_path, rule, used_pct=100.0 * used / quota)
        except (DeletionRefused, PathGuardError, ConfigError, OSError) as exc:
            result.refused.append({"path": item.rel_path, "reason": str(exc)})
            continue
        used -= freed
        result.deleted_bytes += freed
        result.deleted_files += 1
    return result
