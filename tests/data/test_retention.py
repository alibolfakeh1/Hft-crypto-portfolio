"""Retention must be hard to misuse. Most of these tests try to make it delete something it must not."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from helpers import base_policy, make_context, policy_with_rules
from hft_crypto.config import ConfigError, RetentionPolicy
from hft_crypto.data.atomic import sha256_file
from hft_crypto.data.catalog import FileRecord
from hft_crypto.data.context import JobContext
from hft_crypto.data.guard import PathGuardError
from hft_crypto.data.retention import (
    DeletionRefused,
    RetentionPlan,
    WatermarkState,
    build_plan,
    delete_file,
    delete_raw_if_allowed,
    evaluate_watermarks,
    execute_plan,
)

NOW = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)
OLD = "2026-01-01T00:00:00Z"
RECENT = "2026-11-04T11:00:00Z"
GB = 1_000_000_000
QUOTA = 8 * GB
RAW = "raw/archive/binance/aggTrades/BTCUSDT/date=2026-11-02/x.zip"
TRADES = "curated/trades/venue=binance/symbol=BTCUSDT/month=2026-11/part-2026-11-02.parquet"
BARS = "curated/bars_1m/venue=binance/symbol=BTCUSDT/month=2026-11/part-2026-11-02.parquet"
LIVE = "raw/live/kraken/book/BTCUSD/date=2026-11-02/x.jsonl.gz"


def add_file(
    ctx: JobContext,
    rel: str,
    *,
    kind: str,
    parents: tuple[str, ...] = (),
    status: str = "pass",
    created: str = OLD,
    partition: str | None = "2026-11-02",
    source: str | None = None,
    on_disk: bool = True,
    row_status: str = "present",
) -> None:
    path = ctx.root.guard.root / rel
    size = 0
    digest = "0" * 64
    if on_disk:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content of " + rel.encode())
        size = path.stat().st_size
        digest = sha256_file(path)
    ctx.catalog.register_file(
        FileRecord(
            rel_path=rel,
            dataset_id="d",
            kind=kind,
            partition_key=partition,
            date_start=partition,
            date_end=partition,
            size_bytes=size,
            sha256=digest,
            row_count=1,
            source_url=source,
            created_at=created,
            code_version="test",
            check_status=status,
            status=row_status,
        ),
        parents,
    )


def state(pct: float, quota: int = QUOTA) -> WatermarkState:
    return evaluate_watermarks(int(quota * pct / 100.0), quota, base_policy().watermarks)


def raw_rule(**changes: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "raw",
        "zone": "raw/archive",
        "kinds": ["aggTrades"],
        "min_age_days": 0.0,
        "reviewed": True,
        "requires": {"aggTrades": ["trades:pass", "bars_1m:pass,warn,provisional"]},
    }
    rule.update(changes)
    return rule


def live_rule(**changes: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "live",
        "zone": "raw/live",
        "kinds": ["*"],
        "min_age_days": 90.0,
        "reviewed": True,
        "requires": {"*": ["bars_1m:pass,warn"]},
    }
    rule.update(changes)
    return rule


@pytest.fixture
def ctx(tmp_path: Path) -> JobContext:
    return make_context(tmp_path / "root", now=NOW, policy=policy_with_rules([raw_rule(), live_rule()]))


def plan_for(ctx: JobContext, pct: float = 10.0, quota: int = QUOTA) -> RetentionPlan:
    return build_plan(ctx.root, ctx.catalog, ctx.policy, state(pct, quota), NOW)


def add_raw_with_children(ctx: JobContext, *, trades: str = "pass", bars: str = "pass", **raw: Any) -> None:
    add_file(ctx, RAW, kind="aggTrades", source="https://archive/x.zip", **raw)
    add_file(ctx, TRADES, kind="trades", parents=(RAW,), status=trades)
    add_file(ctx, BARS, kind="bars_1m", parents=(TRADES,), status=bars)


# ---- dry run and the explicit flag -------------------------------------------------------------------------


def test_a_plan_touches_nothing(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    plan = plan_for(ctx)
    assert [item.rel_path for item in plan.deletable] == [RAW]
    assert plan.deletable[0].data_class == "RE-DOWNLOADABLE"
    assert plan.deletable[0].rule_id == "raw"
    assert plan.deletable[0].size_bytes > 0
    assert (ctx.root.path / RAW).is_file()
    assert not ctx.root.deletions_log.exists()


def test_executing_a_plan_deletes_and_logs_all_protocol_fields(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    size = (ctx.root.path / RAW).stat().st_size
    digest = sha256_file(ctx.root.path / RAW)
    result = execute_plan(ctx, plan_for(ctx))
    assert result.deleted_files == 1
    assert result.deleted_bytes == size
    assert not (ctx.root.path / RAW).exists()
    assert (ctx.root.path / TRADES).exists()
    line = json.loads(ctx.root.deletions_log.read_text(encoding="utf-8").splitlines()[0])
    assert line["path"] == RAW
    assert line["size"] == size
    assert line["checksum"] == digest
    assert line["rule"] == "raw"
    assert line["class"] == "RE-DOWNLOADABLE"
    assert line["code_version"]
    assert line["time"]
    record = ctx.catalog.get_file(RAW)
    assert record is not None
    assert record.status == "deleted"
    assert ctx.catalog.deletions_since("2000-01-01")[0]["rel_path"] == RAW


def test_a_rule_not_marked_reviewed_cannot_delete(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([raw_rule(reviewed=False)]))
    add_raw_with_children(ctx)
    plan = plan_for(ctx)
    assert plan.bytes_freed_if_run == 0
    result = execute_plan(ctx, plan)
    assert result.deleted_files == 0
    assert "not marked reviewed" in result.refused[0]["reason"]
    assert (ctx.root.path / RAW).is_file()
    deleted, reason = delete_raw_if_allowed(ctx, RAW, "raw")
    assert deleted is False
    assert "not marked reviewed" in reason


def test_the_shipped_policy_marks_only_the_raw_rule_reviewed() -> None:
    assert [rule.id for rule in base_policy().rules if rule.reviewed] == ["raw-archive-after-curated"]


# ---- outside DATA_ROOT and links ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    ["raw/archive/../../../outside.txt", "../outside.txt", "raw/archive/x/../../../../outside.txt"],
)
def test_catalog_paths_outside_the_root_are_refused(tmp_path: Path, escape: str) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    rule = raw_rule(zone="raw/archive", requires={})
    ctx = make_context(tmp_path / "a" / "b" / "root", now=NOW, policy=policy_with_rules([rule]))
    ctx.catalog.register_file(
        FileRecord(
            rel_path=escape,
            dataset_id="d",
            kind="aggTrades",
            partition_key="2026-11-02",
            date_start=None,
            date_end=None,
            size_bytes=7,
            sha256=sha256_file(outside),
            row_count=None,
            source_url="https://archive/x",
            created_at=OLD,
            code_version="t",
            check_status="pass",
        )
    )
    plan = plan_for(ctx)
    for item in plan.deletable:
        pytest.fail(f"planned deletion of {item.rel_path}")
    with pytest.raises(PathGuardError):
        delete_file(ctx, escape, ctx.policy.rule("raw"), data_class="RE-DOWNLOADABLE")
    assert outside.read_text() == "keep me"


def test_absolute_paths_outside_the_root_are_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    ctx = make_context(tmp_path / "root", now=NOW, policy=policy_with_rules([raw_rule(requires={})]))
    with pytest.raises((PathGuardError, DeletionRefused)):
        delete_file(ctx, str(outside), ctx.policy.rule("raw"), data_class="RE-DOWNLOADABLE")
    assert outside.read_text() == "keep me"


def test_files_behind_a_link_are_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.zip").write_text("keep me")
    ctx = make_context(tmp_path / "root", now=NOW, policy=policy_with_rules([raw_rule(requires={})]))
    link = ctx.root.path / "raw" / "archive" / "link"
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=False
        )
        if done.returncode != 0:
            pytest.skip("cannot create a junction")
    else:
        link.symlink_to(outside, target_is_directory=True)
    rel = "raw/archive/link/x.zip"
    ctx.catalog.register_file(
        FileRecord(
            rel_path=rel,
            dataset_id="d",
            kind="aggTrades",
            partition_key="2026-11-02",
            date_start=None,
            date_end=None,
            size_bytes=7,
            sha256=sha256_file(outside / "x.zip"),
            row_count=None,
            source_url="https://archive/x",
            created_at=OLD,
            code_version="t",
            check_status="pass",
        )
    )
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert "link" in plan.blocked[0].reason
    with pytest.raises(PathGuardError):
        delete_file(ctx, rel, ctx.policy.rule("raw"), data_class="RE-DOWNLOADABLE")
    assert (outside / "x.zip").read_text() == "keep me"


def test_a_file_not_in_the_catalog_is_never_selected(ctx: JobContext) -> None:
    stray = ctx.root.path / "raw" / "archive" / "binance" / "stray.zip"
    stray.parent.mkdir(parents=True)
    stray.write_text("unknown")
    plan = plan_for(ctx, pct=99.0)
    assert plan.deletable == []
    assert stray.is_file()


def test_a_changed_file_is_refused(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    (ctx.root.path / RAW).write_bytes(b"edited after it was catalogued")
    result = execute_plan(ctx, plan_for(ctx))
    assert result.deleted_files == 0
    assert "differs from its manifest" in result.refused[0]["reason"]
    assert (ctx.root.path / RAW).is_file()


# ---- IRREPLACEABLE data at every watermark -----------------------------------------------------------------


@pytest.mark.parametrize("pct", [0.0, 50.0, 69.9, 70.0, 80.0, 85.0, 90.0, 95.0, 99.9, 100.0, 150.0, 1000.0])
def test_irreplaceable_inside_retention_is_never_deleted_at_any_watermark(tmp_path: Path, pct: float) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([live_rule()]))
    add_file(ctx, LIVE, kind="book", created=RECENT)
    add_file(ctx, BARS, kind="bars_1m", parents=(LIVE,))
    plan = plan_for(ctx, pct=pct)
    assert plan.deletable == []
    assert plan.blocked[0].data_class == "IRREPLACEABLE"
    assert "inside its retention period" in plan.blocked[0].reason
    assert execute_plan(ctx, plan).deleted_files == 0
    assert (ctx.root.path / LIVE).is_file()


def test_irreplaceable_one_day_inside_retention_is_kept(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([live_rule()]))
    created = (NOW - dt.timedelta(days=89)).isoformat().replace("+00:00", "Z")
    add_file(ctx, LIVE, kind="book", created=created)
    add_file(ctx, BARS, kind="bars_1m", parents=(LIVE,))
    assert plan_for(ctx, pct=100.0).deletable == []


def test_irreplaceable_past_retention_still_needs_derived_data(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([live_rule()]))
    add_file(ctx, LIVE, kind="book", created=OLD)
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert "derived data missing" in plan.blocked[0].reason


def test_irreplaceable_past_retention_with_passing_derived_data_may_go(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([live_rule()]))
    add_file(ctx, LIVE, kind="book", created=OLD)
    add_file(ctx, BARS, kind="bars_1m", parents=(LIVE,))
    assert [item.rel_path for item in plan_for(ctx).deletable] == [LIVE]


@pytest.mark.parametrize("zone", ["ledger", "ledger/x", "decisions", "catalog", "decisions/a/b"])
def test_no_rule_may_select_the_forbidden_zones(zone: str) -> None:
    with pytest.raises(ConfigError, match="can never be selected"):
        policy_with_rules([raw_rule(zone=zone, requires={})])


def test_a_rule_cannot_give_irreplaceable_data_a_watermark_exit() -> None:
    with pytest.raises(ConfigError, match="never deleted at a watermark"):
        policy_with_rules([live_rule(watermark_bypass_pct=95.0)])


def test_a_rule_cannot_give_irreplaceable_data_no_retention() -> None:
    with pytest.raises(ConfigError, match="above zero"):
        policy_with_rules([live_rule(min_age_days=0.0)])


def test_ledger_files_survive_even_if_catalogued(tmp_path: Path) -> None:
    policy = policy_with_rules([raw_rule(zone="raw/archive", kinds=["*"], requires={})])
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy)
    add_file(ctx, "ledger/events.jsonl", kind="aggTrades", partition=None)
    plan = plan_for(ctx, pct=200.0)
    assert plan.deletable == []
    assert (ctx.root.path / "ledger/events.jsonl").is_file()


def test_derived_data_with_its_raw_gone_is_treated_as_irreplaceable(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "requires": {"trades": ["bars_1m:pass,warn"]},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_raw_with_children(ctx)
    ctx.catalog.set_file_status(RAW, "absent", "2026-11-03T00:00:00Z")
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert plan.blocked[0].data_class == "IRREPLACEABLE"


def test_a_rule_may_rely_on_a_public_archive_only_by_saying_so(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "rebuildable_from_archive": True,
        "requires": {"trades": ["bars_1m:pass,warn"]},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_raw_with_children(ctx)
    ctx.catalog.set_file_status(RAW, "absent", "2026-11-03T00:00:00Z")
    assert [item.rel_path for item in plan_for(ctx).deletable] == [TRADES]


def test_archive_reliance_does_not_cover_data_built_from_live_recordings(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "rebuildable_from_archive": True,
        "requires": {},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_file(ctx, LIVE, kind="book", on_disk=False, row_status="deleted")
    add_file(ctx, TRADES, kind="trades", parents=(LIVE,))
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert plan.blocked[0].data_class == "IRREPLACEABLE"


def test_sample_days_are_kept_as_curated_data(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "rebuildable_from_archive": True,
        "requires": {},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    first = "curated/trades/venue=binance/symbol=BTCUSDT/month=2026-10/part-2026-10-01.parquet"
    other = "curated/trades/venue=binance/symbol=BTCUSDT/month=2026-10/part-2026-10-02.parquet"
    # Both were built from an archive file that has since gone, which the rule says it may rely on.
    raw = "raw/archive/binance/aggTrades/BTCUSDT/date=2026-10-01/x.zip"
    add_file(ctx, raw, kind="aggTrades", source="https://archive/x.zip", on_disk=False, row_status="absent")
    add_file(ctx, first, kind="trades", partition="2026-10-01", parents=(raw,))
    add_file(ctx, other, kind="trades", partition="2026-10-02", parents=(raw,))
    plan = plan_for(ctx)
    assert [item.rel_path for item in plan.deletable] == [other]
    assert plan.blocked[0].rel_path == first
    assert plan.blocked[0].data_class == "IRREPLACEABLE"


def test_raw_sample_days_can_be_protected_by_policy(tmp_path: Path) -> None:
    policy = policy_with_rules(
        [raw_rule(requires={})],
        sample_days={"day_of_month": 2, "kinds": ["trades"], "protect_raw": True},
    )
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy)
    add_file(ctx, RAW, kind="aggTrades", source="https://archive/x.zip")
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert plan.blocked[0].data_class == "IRREPLACEABLE"


# ---- derived data preconditions ----------------------------------------------------------------------------


def test_raw_is_kept_when_derived_data_is_missing(ctx: JobContext) -> None:
    add_file(ctx, RAW, kind="aggTrades", source="https://archive/x.zip")
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert plan.blocked[0].reason == "derived data missing: trades"


def test_raw_is_kept_when_only_part_of_the_derived_chain_exists(ctx: JobContext) -> None:
    add_file(ctx, RAW, kind="aggTrades", source="https://archive/x.zip")
    add_file(ctx, TRADES, kind="trades", parents=(RAW,))
    plan = plan_for(ctx)
    assert plan.blocked[0].reason == "derived data missing: bars_1m"


@pytest.mark.parametrize(
    ("trades", "bars", "reason"),
    [
        ("fail", "pass", "trades is fail"),
        ("provisional", "pass", "trades is provisional"),
        ("pass", "fail", "bars_1m is fail"),
    ],
)
def test_raw_is_kept_when_derived_data_is_failing(
    ctx: JobContext, trades: str, bars: str, reason: str
) -> None:
    add_raw_with_children(ctx, trades=trades, bars=bars)
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert reason in plan.blocked[0].reason


def test_raw_goes_when_bars_wait_only_for_their_neighbour(ctx: JobContext) -> None:
    """Provisional bars can be rebuilt from curated trades, which stay, so raw is not needed for them."""
    add_raw_with_children(ctx, bars="provisional")
    assert [item.rel_path for item in plan_for(ctx).deletable] == [RAW]


def test_raw_is_kept_when_derived_file_vanished_from_disk(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    (ctx.root.path / BARS).unlink()
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert "missing from disk" in plan.blocked[0].reason


def test_quarantined_derived_data_does_not_count(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    ctx.catalog.set_file_status(BARS, "quarantined", "2026-11-04T00:00:00Z")
    assert plan_for(ctx).deletable == []


def test_a_published_run_protects_what_it_depends_on_unless_rebuildable(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "rebuildable_from_archive": True,
        "requires": {},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_raw_with_children(ctx)
    ctx.catalog.start_run("r1", "report", now=OLD, code_version="t", config_hash="h")
    ctx.catalog.finish_run("r1", now=OLD, status="ok", data_manifest=[TRADES], published=True)
    plan = plan_for(ctx)
    assert plan.deletable == []
    assert "published run" in plan.blocked[0].reason


def test_an_unpublished_run_does_not_protect_a_file(tmp_path: Path) -> None:
    rule = {
        "id": "window",
        "zone": "curated/trades",
        "kinds": ["trades"],
        "min_age_days": 30.0,
        "reviewed": True,
        "rebuildable_from_archive": True,
        "requires": {},
    }
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_raw_with_children(ctx)
    ctx.catalog.start_run("r1", "report", now=OLD, code_version="t", config_hash="h")
    ctx.catalog.finish_run("r1", now=OLD, status="ok", data_manifest=[TRADES], published=False)
    assert [item.rel_path for item in plan_for(ctx).deletable] == [TRADES]


# ---- run results -------------------------------------------------------------------------------------------


def run_rule() -> dict[str, Any]:
    return {
        "id": "runs",
        "zone": "results/runs",
        "kinds": ["run"],
        "min_age_days": 180.0,
        "reviewed": True,
        "unpublished_only": True,
        "watermark_bypass_pct": 90.0,
        "watermark_min_age_days": 30.0,
    }


def add_run(ctx: JobContext, run_id: str, created: str, *, published: bool) -> str:
    rel = f"results/runs/{run_id}/status.json"
    add_file(ctx, rel, kind="run", created=created, partition=None)
    ctx.catalog.start_run(run_id, "report", now=created, code_version="t", config_hash="h")
    ctx.catalog.finish_run(run_id, now=created, status="ok", published=published)
    return rel


def test_published_results_are_kept_forever(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([run_rule()]))
    add_run(ctx, "pub", "2020-01-01T00:00:00Z", published=True)
    plan = plan_for(ctx, pct=99.0)
    assert plan.deletable == []
    assert "kept forever" in plan.blocked[0].reason


def test_unpublished_results_expire_after_180_days(tmp_path: Path) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([run_rule()]))
    old = add_run(ctx, "old", "2026-01-01T00:00:00Z", published=False)
    add_run(ctx, "young", "2026-10-30T00:00:00Z", published=False)
    assert [item.rel_path for item in plan_for(ctx).deletable] == [old]


@pytest.mark.parametrize(("pct", "expected"), [(85.0, 0), (89.9, 0), (90.0, 1), (95.0, 1)])
def test_the_90_percent_watermark_reaches_results_past_30_days_only(
    tmp_path: Path, pct: float, expected: int
) -> None:
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([run_rule()]))
    add_run(ctx, "aged", "2026-09-15T00:00:00Z", published=False)  # 50 days
    add_run(ctx, "fresh", "2026-10-30T00:00:00Z", published=False)  # 5 days
    assert len(plan_for(ctx, pct=pct).deletable) == expected


# ---- watermarks --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pct", "level", "stop", "pause"),
    [
        (0.0, "normal", False, False),
        (69.9, "normal", False, False),
        (70.0, "warn", False, False),
        (79.9, "warn", False, False),
        (80.0, "stop_backfill", True, False),
        (85.0, "purge_raw", True, False),
        (90.0, "purge_runs", True, True),
        (95.0, "critical", True, True),
        (120.0, "critical", True, True),
    ],
)
def test_watermark_levels(pct: float, level: str, stop: bool, pause: bool) -> None:
    result = state(pct)
    assert result.level == level
    assert result.stop_backfill is stop
    assert result.pause_feature_rebuilds is pause


def test_warning_reports_days_until_full() -> None:
    marks = base_policy().watermarks
    result = evaluate_watermarks(int(QUOTA * 0.75), QUOTA, marks, days_until_full=12.0)
    assert any("12 days" in alert for alert in result.alerts)


@pytest.mark.parametrize(("growth", "alerts"), [(GB / 2.0, 0), (GB * 2.0, 1), (None, 0), (0.0, 0)])
def test_recording_headroom_alert_fires_whatever_the_percentage(growth: float | None, alerts: int) -> None:
    # 10% of 8 GB used leaves 7.2 GB: 14.4 days at 0.5 GB a day, 3.6 at 2 GB, and under 3 at 3 GB.
    used = int(QUOTA * 0.10)
    result = evaluate_watermarks(
        used,
        QUOTA,
        base_policy().watermarks,
        live_growth_bytes_per_day=growth if growth != GB * 2.0 else GB * 3.0,
    )
    assert sum("headroom" in alert for alert in result.alerts) == alerts


def test_85_percent_frees_oldest_first_and_stops_at_the_target(tmp_path: Path) -> None:
    rule = raw_rule(min_age_days=30.0, requires={}, kinds=["aggTrades"], watermark_bypass_pct=85.0)
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    paths = []
    for index in range(4):
        rel = f"raw/archive/binance/aggTrades/BTCUSDT/date=2026-11-0{index + 1}/x{index}.zip"
        created = f"2026-11-0{index + 1}T00:00:00Z"
        add_file(ctx, rel, kind="aggTrades", created=created, source="https://a/x", partition=None)
        paths.append(rel)
    size = (ctx.root.path / paths[0]).stat().st_size
    # Quota small enough that one file is about 1%: 86% used needs two files gone to fall below 85%.
    quota = size * 100
    plan = build_plan(ctx.root, ctx.catalog, ctx.policy, state(86.0, quota), NOW)
    assert [item.rel_path for item in plan.deletable] == paths[:2]
    assert {item.reason for item in plan.blocked} == {"watermark target met"}


def test_below_the_watermark_age_still_rules(tmp_path: Path) -> None:
    rule = raw_rule(min_age_days=30.0, requires={}, watermark_bypass_pct=85.0)
    ctx = make_context(tmp_path / "r", now=NOW, policy=policy_with_rules([rule]))
    add_file(ctx, RAW, kind="aggTrades", created=RECENT, source="https://a/x")
    assert plan_for(ctx, pct=84.0).deletable == []


# ---- raw deletion during ingest ----------------------------------------------------------------------------


def test_ingest_style_delete_goes_through_the_same_protocol(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    deleted, _ = delete_raw_if_allowed(ctx, RAW, "raw")
    assert deleted is True
    assert not (ctx.root.path / RAW).exists()
    assert ctx.root.deletions_log.is_file()


def test_ingest_style_delete_refuses_what_the_protocol_refuses(ctx: JobContext) -> None:
    add_file(ctx, RAW, kind="aggTrades", source="https://archive/x.zip")
    deleted, reason = delete_raw_if_allowed(ctx, RAW, "raw")
    assert deleted is False
    assert "derived data missing" in reason
    assert (ctx.root.path / RAW).is_file()


def test_ingest_style_delete_cannot_reach_another_zone(ctx: JobContext) -> None:
    add_file(ctx, "ledger/events.jsonl", kind="aggTrades", partition=None)
    deleted, reason = delete_raw_if_allowed(ctx, "ledger/events.jsonl", "raw")
    assert deleted is False
    assert "does not cover" in reason
    assert (ctx.root.path / "ledger/events.jsonl").is_file()


def test_empty_partition_folders_are_cleaned_but_zones_stay(ctx: JobContext) -> None:
    add_raw_with_children(ctx)
    execute_plan(ctx, plan_for(ctx))
    assert not (ctx.root.path / "raw/archive/binance").exists()
    assert (ctx.root.path / "raw/archive").is_dir()


def test_policy_type_is_what_the_shipped_file_parses_to() -> None:
    assert isinstance(base_policy(), RetentionPolicy)
