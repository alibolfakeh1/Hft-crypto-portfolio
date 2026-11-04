"""Health report: coverage and gaps per dataset, disk use per zone, growth, days until full, last runs.

On GitHub the data center lives in the Actions cache, so this also reports what the cache will hold, and what
GitHub itself says the repository's caches use when that figure is supplied.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from hft_crypto.config import NO_APPROVED_SOURCE, DatasetSpec, PipelineConfig, RetentionPolicy, quota_bytes
from hft_crypto.data.atomic import is_temp_file
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.retention import evaluate_watermarks
from hft_crypto.data.sources import expected_partitions
from hft_crypto.data.zones import DataRoot, measure_zones
from hft_crypto.timeutil import iso, parse_iso


def persisted_bytes(zones: dict[str, int], config: PipelineConfig) -> int:
    """Bytes that survive between runs through the Actions cache."""
    return sum(size for zone, size in zones.items() if zone in config.persisted_zones)


def _missing_ranges(missing: list[str], limit: int = 12) -> list[str]:
    """Compact a sorted list of daily keys into ranges."""
    if not missing:
        return []
    ranges: list[list[str]] = []
    for key in missing:
        if len(key) == 10 and ranges:
            previous = dt.date.fromisoformat(ranges[-1][1])
            if dt.date.fromisoformat(key) == previous + dt.timedelta(days=1):
                ranges[-1][1] = key
                continue
        ranges.append([key, key])
    text = [a if a == b else f"{a}..{b}" for a, b in ranges]
    if len(text) > limit:
        return [*text[:limit], f"and {len(text) - limit} more ranges"]
    return text


def coverage_for_dataset(
    catalog: Catalog, spec: DatasetSpec, symbol: str, now: dt.datetime
) -> dict[str, Any]:
    partitions = expected_partitions(spec, now)
    keys = [p.isoformat()[:7] if spec.granularity == "month" else p.isoformat() for p in partitions]
    states = catalog.task_states(spec.id, symbol)
    done = [key for key in keys if states.get(key) == "done"]
    missing = [key for key in keys if states.get(key) != "done"]
    counts = {
        "pending": sum(states.get(key, "pending") == "pending" for key in missing),
        "overdue": sum(states.get(key) == "overdue" for key in missing),
        "failed": sum(states.get(key) == "failed" for key in missing),
    }
    expected = len(keys)
    return {
        "dataset": spec.id,
        "symbol": symbol,
        "tier": spec.tier,
        "opt_in": spec.opt_in,
        "granularity": spec.granularity,
        "expected": expected,
        "done": len(done),
        **counts,
        "coverage_pct": round(100.0 * len(done) / expected, 2) if expected else 100.0,
        "first_done": done[0] if done else None,
        "last_done": done[-1] if done else None,
        "missing_ranges": _missing_ranges(missing),
    }


def _bars_coverage(
    catalog: Catalog, venue: str, symbol: str, spec: DatasetSpec, now: dt.datetime
) -> dict[str, Any]:
    partitions = expected_partitions(spec, now)
    keys = [p.isoformat() for p in partitions]
    states = catalog.task_states(f"derived.bars.{venue}", symbol)
    final = [key for key in keys if states.get(key) == "done"]
    provisional = [key for key in keys if states.get(key) == "provisional"]
    failed = [key for key in keys if states.get(key) == "failed"]
    built = sorted(set(final) | set(provisional))
    expected = len(keys)
    return {
        "dataset": f"bars_1m.{venue}",
        "symbol": symbol,
        "expected": expected,
        "final": len(final),
        "provisional": len(provisional),
        "failed": len(failed),
        "coverage_pct": round(100.0 * len(built) / expected, 2) if expected else 100.0,
        "first_built": built[0] if built else None,
        "last_built": built[-1] if built else None,
        "missing_ranges": _missing_ranges([k for k in keys if k not in set(built)]),
    }


def _growth_per_day(catalog: Catalog, zone: str, now: dt.datetime) -> float | None:
    """Measured growth over up to two weeks. None until two measurements are at least an hour apart."""
    history = catalog.disk_history(zone, iso(now - dt.timedelta(days=14)))
    if len(history) < 2:
        return None
    first_time, first_size = history[0]
    last_time, last_size = history[-1]
    elapsed_days = (parse_iso(last_time) - parse_iso(first_time)).total_seconds() / 86_400.0
    if elapsed_days < 1.0 / 24.0:
        return None
    return (last_size - first_size) / elapsed_days


def read_heartbeats(root: DataRoot, now: dt.datetime) -> dict[str, dict[str, Any]]:
    folder = root.guard.check("catalog/heartbeats")
    beats: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return beats
    for path in sorted(folder.glob("*.json")):
        if is_temp_file(path):
            continue
        try:
            beat = json.loads(path.read_text(encoding="utf-8"))
            beat["age_hours"] = round((now - parse_iso(beat["at"])).total_seconds() / 3600.0, 2)
            beats[path.stem] = beat
        except (OSError, ValueError, KeyError):
            beats[path.stem] = {"error": "unreadable heartbeat"}
    return beats


def build_health(
    root: DataRoot,
    catalog: Catalog,
    config: PipelineConfig,
    policy: RetentionPolicy,
    now: dt.datetime,
    *,
    actions_cache: dict[str, Any] | None = None,
    record_snapshot: bool = True,
) -> dict[str, Any]:
    """Assemble the health report. It holds no absolute paths, because it is published."""
    zones = measure_zones(root)
    total = sum(zones.values())
    persisted = persisted_bytes(zones, config)
    if record_snapshot:
        catalog.add_disk_snapshot(iso(now), {**zones, "_persisted": persisted, "_total": total})
    quota = quota_bytes(config.default_quota_gb)
    growth = _growth_per_day(catalog, "_persisted", now)
    days_until_full = None
    if growth is not None and growth > 0:
        days_until_full = round(max(0, quota - persisted) / growth, 1)
    live_growth = _growth_per_day(catalog, "raw/live", now)
    state = evaluate_watermarks(
        total,
        quota,
        policy.watermarks,
        days_until_full=days_until_full,
        live_growth_bytes_per_day=live_growth,
    )

    coverage: list[dict[str, Any]] = []
    bars: list[dict[str, Any]] = []
    for spec in config.datasets:
        if spec.opt_in or not config.dataset_enabled(spec):
            continue
        for symbol in config.symbols:
            # An enabled dataset that nothing has started is a coverage problem, and it shows here.
            item = coverage_for_dataset(catalog, spec, symbol, now)
            coverage.append(item)
            if spec.curated == "trades":
                bars.append(_bars_coverage(catalog, spec.venue, symbol, spec, now))

    alerts = list(state.alerts)
    if not config.enabled_sources():
        alerts.append(f"{NO_APPROVED_SOURCE.capitalize()}. No market data is being collected.")
    overdue = sum(item["overdue"] for item in coverage)
    failed = sum(item["failed"] for item in coverage)
    if overdue:
        alerts.append(f"{overdue} archive partitions are overdue.")
    if failed:
        alerts.append(f"{failed} archive partitions failed and are waiting to retry.")
    for name in config.enabled_sources():
        specs = [spec for spec in config.datasets if spec.venue == name and not spec.opt_in]
        if specs and not any(spec.light for spec in specs):
            alerts.append(
                f"Approved source {name} has no dataset the daily job selects, so it fetches nothing."
            )
    for name in config.enabled_sources():
        if config.source(name).allowance_state != "measured":
            alerts.append(
                f"Source {name} runs on a placeholder fill span allowance. It has not been measured."
            )
    changed = catalog.changed_files("raw/archive/")
    if changed:
        alerts.append(f"{len(changed)} delivered files changed after they were recorded.")
    exclusions = catalog.exclusions()
    if exclusions:
        alerts.append(f"{len(exclusions)} symbol-days are left out of results, each with a logged reason.")
    partial = any(item["coverage_pct"] < 100.0 for item in coverage)
    last_runs = {}
    for kind, rows in catalog.last_runs().items():
        row = rows[0]
        last_runs[kind] = {
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "code_version": row["code_version"],
        }
    deletions = catalog.deletions_since(iso(now - dt.timedelta(days=1)))
    return {
        "generated_at": iso(now),
        "source_state": config.source_state(),
        "sources": {
            name: {
                "enabled": source.enabled,
                "prohibited": source.prohibited,
                "terms_note": source.terms_note,
            }
            for name, source in sorted(config.sources.items())
        },
        "partial_coverage": partial,
        "coverage": coverage,
        "bars_coverage": bars,
        "gaps": catalog.gaps(),
        "exclusions": exclusions,
        "changed_delivered_files": changed,
        "disk": {
            "zones_bytes": zones,
            "total_bytes": total,
            "persisted_bytes": persisted,
            "persisted_zones": list(config.persisted_zones),
            "quota_bytes": quota,
            "used_pct": state.used_pct,
            "watermark_level": state.level,
            "growth_bytes_per_day": None if growth is None else round(growth),
            "days_until_full": days_until_full,
            "recording_headroom_days": state.headroom_days,
        },
        "actions_cache": actions_cache,
        "last_runs": {
            kind: {**info, "last_success": catalog.last_success(kind)} for kind, info in last_runs.items()
        },
        "heartbeats": read_heartbeats(root, now),
        "deleted_last_24h": {
            "files": len(deletions),
            "bytes": sum(row["size_bytes"] for row in deletions),
            "by_rule": _count_by_rule(deletions),
        },
        "alerts": alerts,
    }


def _count_by_rule(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["rule_id"]] = counts.get(row["rule_id"], 0) + 1
    return counts
