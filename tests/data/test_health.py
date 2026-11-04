"""Health report, with the GitHub cache as the data center."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from helpers import FakeFetcher, base_config, make_context, publish_binance_day, with_sources_enabled
from hft_crypto.config import ConfigError, PipelineConfig, load_pipeline_config, quota_bytes
from hft_crypto.data.context import write_heartbeat
from hft_crypto.data.health import build_health, measure_zones
from hft_crypto.data.ingest import IngestOptions, run_ingest
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


def test_quota_defaults_to_8_gb_and_the_variable_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_QUOTA_GB", raising=False)
    assert quota_bytes(base_config().default_quota_gb) == 8_000_000_000
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
    publish_binance_day(fetcher, BTC, dt.date(2026, 3, 3))
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    run_ingest(
        ctx,
        fetcher,
        IngestOptions(dataset_ids=("binance.klines", "binance.aggTrades"), symbols=(BTC,)),
    )
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert report["partial_coverage"] is True
    item = next(c for c in report["coverage"] if c["dataset"] == "binance.aggTrades")
    assert item["expected"] == 3
    assert item["done"] == 1
    assert item["coverage_pct"] == 33.33
    assert item["first_done"] == "2026-03-03"
    assert item["missing_ranges"] == ["2026-03-01..2026-03-02"]
    # Day 1 is past its 36 hours at this moment. Day 2 ends at 03-03 00:00, so it is not, until 12:00 today.
    assert item["overdue"] == 1
    assert item["pending"] == 1
    bars = next(b for b in report["bars_coverage"] if b["dataset"] == "bars_1m.binance")
    assert bars["provisional"] == 1
    assert bars["expected"] == 3


def test_opt_in_datasets_do_not_count_against_coverage(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, config=_config())
    report = build_health(ctx.root, ctx.catalog, ctx.config, ctx.policy, NOW)
    assert not any(c["dataset"] == "bybit.orderbook" for c in report["coverage"])
    assert not any(c["dataset"] == "bybit.trades" for c in report["coverage"])


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
