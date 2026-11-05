"""Health report, with the GitHub cache as the data center."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from helpers import FakeFetcher, base_config, make_context, publish_generated_day, with_sources_enabled
from hft_crypto.config import ConfigError, PipelineConfig, load_pipeline_config, quota_bytes
from hft_crypto.data.context import write_heartbeat
from hft_crypto.data.health import build_health
from hft_crypto.data.ingest import IngestOptions, run_ingest
from hft_crypto.data.zones import measure_zones
from hft_crypto.timeutil import iso

NOW = dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC)
BTC = "BTCUSDT"


def _config() -> PipelineConfig:
    from dataclasses import replace

    config = base_config()
    return with_sources_enabled(
        replace(
            config,
            symbols=(BTC,),
            datasets=tuple(replace(spec, start=dt.date(2026, 3, 1)) for spec in config.datasets),
        )
    )


def test_quota_defaults_to_under_half_of_the_cache_limit_and_the_variable_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-17. Each save makes a new copy before the old one is pruned, so two copies must fit in 10 GB."""
    monkeypatch.delenv("DATA_QUOTA_GB", raising=False)
    assert quota_bytes(base_config().default_quota_gb) == 4_000_000_000
    monkeypatch.setenv("DATA_QUOTA_GB", "2.5")
    assert quota_bytes(8.0) == 2_500_000_000
    monkeypatch.setenv("DATA_QUOTA_GB", "lots")
    with pytest.raises(ConfigError):
        quota_bytes(8.0)
    monkeypatch.setenv("DATA_QUOTA_GB", "0")
    with pytest.raises(ConfigError):
        quota_bytes(8.0)


def test_persisted_zones_are_curated_features_catalog() -> None:
    assert set(load_pipeline_config().persisted_zones) == {"curated", "features", "catalog"}


def test_zone_sizes_are_measured(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    (ctx.root.path / "curated" / "x").write_bytes(b"12345")
    (ctx.root.path / "raw" / "archive" / "y").write_bytes(b"123")
    zones = measure_zones(ctx.root)
    assert zones["curated"] == 5
    assert zones["raw/archive"] == 3
    assert zones["ledger"] == 0


def test_partial_coverage_is_reported_with_missing_ranges(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    publish_generated_day(fetcher, BTC, dt.date(2026, 3, 3))
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    run_ingest(
        ctx,
        fetcher,
        IngestOptions(dataset_ids=("generated.klines", "generated.aggTrades"), symbols=(BTC,)),
    )
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["partial_coverage"] is True
    item = next(c for c in report["coverage"] if c["dataset"] == "generated.aggTrades")
    assert item["expected"] == 3
    assert item["done"] == 1
    assert item["coverage_pct"] == 33.33
    assert item["first_done"] == "2026-03-03"
    assert item["missing_ranges"] == ["2026-03-01..2026-03-02"]
    # Day 1 is past its 36 hours at this moment. Day 2 ends at 03-03 00:00, so it is not, until 12:00 today.
    assert item["overdue"] == 1
    assert item["pending"] == 1
    bars = next(b for b in report["bars_coverage"] if b["dataset"] == "bars_1m.generated")
    assert bars["provisional"] == 1
    assert bars["expected"] == 3


def test_opt_in_datasets_do_not_count_against_coverage(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert not any(c["dataset"] == "bybit.orderbook" for c in report["coverage"])


def test_an_enabled_dataset_nothing_has_started_shows_as_a_coverage_problem(tmp_path: Path) -> None:
    """F-16. Health used to skip it, so approving a source could look like a healthy job with no data."""
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    item = next(c for c in report["coverage"] if c["dataset"] == "bybit.trades")
    assert item["done"] == 0
    assert report["partial_coverage"] is True
    assert any("bybit" in alert and "selects" in alert for alert in report["alerts"])


def test_exclusions_and_changed_files_reach_the_alerts(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    ctx.catalog.add_exclusion("generated", BTC, "2026-03-01", "because", 250.0, now=iso(NOW))
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert any("left out of results" in alert for alert in report["alerts"])
    assert report["exclusions"][0]["date"] == "2026-03-01"


def test_growth_and_days_until_full_come_from_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_QUOTA_GB", "0.00001")  # 10 kB
    ctx = make_context(tmp_path / "r", now=NOW)
    ctx.catalog.close()
    day_before = NOW - dt.timedelta(days=1)
    ctx = make_context(tmp_path / "r", now=NOW)
    first = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, day_before)
    assert first["disk"]["growth_bytes_per_day"] is None
    assert first["disk"]["days_until_full"] is None
    (ctx.root.path / "curated" / "x").write_bytes(b"x" * 1000)
    second = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    growth = second["disk"]["growth_bytes_per_day"]
    assert growth is not None
    assert 900 < growth < 1100
    assert second["disk"]["days_until_full"] is not None


def test_measured_growth_needs_snapshots_at_least_an_hour_apart(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW - dt.timedelta(minutes=5))
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["disk"]["growth_bytes_per_day"] is None


def test_cache_use_is_reported(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    (ctx.root.path / "curated" / "x").write_bytes(b"x" * 1000)
    (ctx.root.path / "raw" / "archive" / "transient").write_bytes(b"x" * 500)
    cache = {"active_caches_size_in_bytes": 1234, "active_caches_count": 2}
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW, actions_cache=cache)
    assert report["actions_cache"] == cache
    # raw is on the runner only, and does not count as what the cache will hold.
    assert report["disk"]["persisted_bytes"] >= 1000
    assert report["disk"]["persisted_bytes"] < report["disk"]["total_bytes"]


def test_heartbeats_and_last_runs_appear(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    write_heartbeat(ctx.root, "ingest", now=NOW - dt.timedelta(hours=2), detail={"status": "ok"})
    ctx.catalog.start_run("r1", "ingest", now=iso(NOW), code_version="c", config_hash="h")
    ctx.catalog.finish_run("r1", now=iso(NOW), status="ok")
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["heartbeats"]["ingest"]["age_hours"] == 2.0
    assert report["last_runs"]["ingest"]["status"] == "ok"
    assert report["last_runs"]["ingest"]["last_success"] == iso(NOW)


def test_failed_runs_do_not_count_as_success(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    ctx.catalog.start_run("r1", "ingest", now=iso(NOW), code_version="c", config_hash="h")
    ctx.catalog.finish_run("r1", now=iso(NOW), status="failed")
    assert ctx.catalog.last_success("ingest") is None


def test_the_report_holds_no_absolute_paths(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    write_heartbeat(ctx.root, "ingest", now=NOW, detail={"status": "ok"})
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    text = json.dumps(report)
    assert str(tmp_path) not in text
    assert str(tmp_path).replace("\\", "\\\\") not in text


def test_deletions_of_the_last_day_are_summarised(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW)
    ctx.catalog.record_deletion(
        deleted_at=iso(NOW - dt.timedelta(hours=1)),
        rel_path="raw/archive/x",
        size_bytes=100,
        sha256="a",
        rule_id="raw-archive-after-curated",
        data_class="RE-DOWNLOADABLE",
        code_version="c",
        run_id="r",
    )
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["deleted_last_24h"] == {
        "files": 1,
        "bytes": 100,
        "by_rule": {"raw-archive-after-curated": 1},
    }


def test_an_enabled_source_on_a_placeholder_allowance_raises_an_alert(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert any("generated" in alert and "placeholder" in alert for alert in report["alerts"])
    shipped = make_context(tmp_path / "s", now=NOW)
    plain = build_health(shipped.root, shipped.catalog, shipped.config, shipped.policy, NOW)
    assert not any("placeholder" in alert for alert in plain["alerts"])


# ---- the steward's list
# -------------------------------------------------------------------------------------------


def _with_files(ctx: Any, *rows: tuple[str, str, int, int | None, str]) -> None:
    for rel, dataset, size, count, day in rows:
        path = ctx.root.guard.check(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        ctx.register_output(
            path,
            dataset_id=dataset,
            kind=dataset.split(".")[1] if "." in dataset else dataset,
            zone="/".join(rel.split("/")[:1]),
            partition_key=day,
            date_start=day,
            date_end=day,
            rows=count,
            check_status="pass",
            check_detail={},
        )


def test_health_reports_each_dataset_by_size_and_rows(tmp_path: Path) -> None:
    """R2.1. It reported by zone, which met neither the ruling nor the daily report the lifecycle asks for."""
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    _with_files(
        ctx,
        ("curated/a/x1.parquet", "curated.a.v.S", 100, 10, "2026-03-02"),
        ("curated/a/x2.parquet", "curated.a.v.S", 300, 30, "2026-03-03"),
        ("curated/b/x1.parquet", "curated.b.v.S", 50, None, "2026-03-02"),
    )
    rows = {
        row["dataset"]: row
        for row in build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)["datasets"]
    }
    assert rows["curated.a.v.S"] == {
        "dataset": "curated.a.v.S",
        "files": 2,
        "bytes": 400,
        "rows": 40,
        "median_bytes_per_partition": 200.0,
        "median_rows_per_partition": 20.0,
    }
    assert rows["curated.b.v.S"]["median_rows_per_partition"] is None


def test_sample_days_over_a_quarter_of_the_quota_raise_an_alert_and_delete_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5.1. Sample days are never deleted, so they add up. It goes to data-steward."""
    monkeypatch.setenv("DATA_QUOTA_GB", "0.000001")
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    _with_files(ctx, ("curated/trades/x1.parquet", "curated.trades.v.S", 300, 1, "2026-03-01"))
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["sample_days_bytes"] == 300
    assert any("Sample days" in alert for alert in report["alerts"])
    assert ctx.root.guard.check("curated/trades/x1.parquet").is_file()
    other = make_context(tmp_path / "other", now=NOW, config=_config())
    _with_files(other, ("curated/trades/x2.parquet", "curated.trades.v.S", 300, 1, "2026-03-02"))
    assert not any(
        "Sample days" in alert
        for alert in build_health(other.root, other.catalog, other.config, other.policy, NOW)["alerts"]
    )


def test_a_file_quarantined_in_the_last_day_raises_an_alert(tmp_path: Path) -> None:
    """R4.3. The record is what data-steward reviews, so a new one must reach someone."""
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    log = ctx.root.guard.check("catalog/quarantine.jsonl")
    old = NOW - dt.timedelta(days=2)
    log.write_text(json.dumps({"time": old.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n", encoding="utf-8")
    alerts = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)["alerts"]
    assert not any("quarantine" in alert for alert in alerts)
    recent = NOW - dt.timedelta(hours=2)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"time": recent.strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    alerts = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)["alerts"]
    assert any("1 files went to quarantine" in alert for alert in alerts)


def test_a_repository_cache_total_near_the_limit_raises_an_alert(tmp_path: Path) -> None:
    """R7.1. Past the limit GitHub chooses what to evict, and nothing compared the total with it."""
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())

    def alerts(total: int) -> list[str]:
        cache = {"active_caches_size_in_bytes": total, "active_caches_count": 1}
        report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW, actions_cache=cache)
        found: list[str] = report["alerts"]
        return found

    assert not any("caches use" in alert for alert in alerts(8_000_000_000))
    assert any("caches use 8.0 GB" in alert for alert in alerts(8_000_000_001))


def test_what_a_run_left_as_alerts_reaches_health(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    ctx.catalog.set_meta(
        "last_ingest_alerts", json.dumps(["A file with a name that is not a day was skipped: x"])
    )
    assert any(
        "not a day" in alert
        for alert in build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)["alerts"]
    )


def test_a_false_allowance_reaches_the_alerts(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    ctx.catalog.add_allowance_event("generated", "S", "2026-03-01", 300.0, 250.0, now="2026-03-02T00:00:00Z")
    assert any(
        "allowance is false" in alert
        for alert in build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)["alerts"]
    )


def test_storage_state_is_measured_on_what_the_cache_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.1. Raw and quarantine leave with the runner, so they cannot read as the cache being full."""
    monkeypatch.setenv("DATA_QUOTA_GB", "0.01")
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    raw = ctx.root.guard.check("raw/archive/x/y.bin")
    raw.parent.mkdir(parents=True, exist_ok=True)
    # Five times the quota on the runner, and the cache itself far under it.
    raw.write_bytes(b"x" * 50_000_000)
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["disk"]["total_bytes"] >= 50_000_000
    assert report["disk"]["persisted_bytes"] < 10_000_000
    assert not any("Storage at" in alert for alert in report["alerts"])
