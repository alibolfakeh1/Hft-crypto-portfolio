"""The first end-to-end output, on generated data only, and the daily job with no approved source."""

from __future__ import annotations

import datetime as dt
import json
import re
import socket
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers import base_config, base_policy
from hft_crypto.cli import main
from hft_crypto.config import ConfigError
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.zones import DataRoot
from hft_crypto.reports.report import SYNTHETIC_LABEL
from hft_crypto.synthetic import _FAULT_DAY_INDEX, FIRST_DAY, SYMBOLS, SyntheticMarket, run_synthetic

DAYS = 7
SEED = 11
# The generator spills one aggregate on this symbol further than the window explains, so the failing path
# always runs.
FAULT_SYMBOL = SYMBOLS[0]
CLEAN_SYMBOL = SYMBOLS[1]
FAULT_DAY = FIRST_DAY + dt.timedelta(days=_FAULT_DAY_INDEX)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file fails on any attempt to reach a network."""

    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("a test tried to use the network")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base = tmp_path_factory.mktemp("synthetic")
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("DATA_QUOTA_GB", raising=False)

        def refuse(*_: object, **__: object) -> None:
            raise AssertionError("the synthetic run tried to use the network")

        patch.setattr(urllib.request.OpenerDirector, "open", refuse)
        patch.setattr(socket.socket, "connect", refuse)
        summary = run_synthetic(
            base / "root",
            base / "live",
            base / "out",
            base_config=base_config(),
            policy=base_policy(),
            days=DAYS,
            seed=SEED,
        )
    yield {
        "summary": summary,
        "base": base,
        "html": (base / "out" / "site" / "index.html").read_text(encoding="utf-8"),
        "status_text": (base / "out" / "status.json").read_text(encoding="utf-8"),
        "status": json.loads((base / "out" / "status.json").read_text(encoding="utf-8")),
    }


def test_every_output_is_labelled_synthetic(run: dict[str, Any]) -> None:
    status = run["status"]
    assert status["data_kind"] == "SYNTHETIC"
    assert status["label"] == SYNTHETIC_LABEL
    assert "SYNTHETIC" in SYNTHETIC_LABEL
    assert status["benchmarks"]
    assert all(item["label"] == SYNTHETIC_LABEL for item in status["benchmarks"].values())
    html = run["html"]
    assert "<title>SYNTHETIC test output</title>" in html
    assert "<h1>SYNTHETIC test output, not market data</h1>" in html
    assert SYNTHETIC_LABEL in html
    assert "داده‌های ساختگی" in html
    # In the chart itself, so that a screenshot of it still says so.
    assert re.search(r"<svg.*>SYNTHETIC</text>.*</svg>", html, re.DOTALL)
    headings = re.findall(r"<h2>(.*?)</h2>", html)
    assert len(headings) == 5
    assert all(heading.startswith("SYNTHETIC: ") for heading in headings)
    assert "BENCHMARK, not a strategy result" not in html


def test_nothing_real_appears_in_the_output(run: dict[str, Any]) -> None:
    for blob in (run["html"], run["status_text"]):
        for word in ("BTCUSDT", "ETHUSDT", "binance", "Binance", "bybit", "kraken", "BTC and ETH"):
            assert word not in blob, word
        assert "2000-" in blob
        assert "2026-" not in blob.replace(run["status"]["code_version"], "")
        assert str(run["base"]) not in blob
        assert str(run["base"]).replace("\\", "\\\\") not in blob


def test_no_generated_prices_or_bars_are_published(run: dict[str, Any]) -> None:
    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {k for v in value.values() for k in keys(v)}
        if isinstance(value, list):
            return {k for v in value for k in keys(v)}
        return set()

    assert not keys(run["status"]) & {"open", "high", "low", "close", "price", "qty", "trades", "bars"}


def test_the_whole_path_ran(run: dict[str, Any]) -> None:
    summary = run["summary"]
    # One day of three daily datasets for two symbols is held back at first, and arrives on the next run.
    assert summary["first_pass"]["pending"] == 6
    assert summary["second_pass"]["pending"] == 0
    # Only the injected fault is an error, and its day is fetched again later, so the run says partial and not
    # ok.
    errors = summary["second_pass"]["errors"]
    assert errors
    assert all(FAULT_DAY.isoformat() in message and FAULT_SYMBOL in message for message in errors)
    assert summary["second_pass"]["status"] == "partial"
    # Raw is transient, and every file went through the deletion protocol. The failed day's trades stay.
    root = run["base"] / "root"
    left = [path.name for path in (root / "raw").rglob("*") if path.is_file()]
    assert summary["raw_files_left"] == len(left)
    assert left
    assert all(FAULT_DAY.isoformat() in name and FAULT_SYMBOL in name for name in left)
    assert summary["second_pass"]["raw_deleted_files"] > 0
    log = (root / "catalog" / "deletions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == summary["second_pass"]["raw_deleted_files"]
    assert all(json.loads(line)["data_kind"] == "SYNTHETIC" for line in log)
    assert run["status"]["partial_coverage"] is True


def test_bars_and_higher_timeframes_exist_with_their_knowable_times(run: dict[str, Any]) -> None:
    root = DataRoot(run["base"] / "root", create=False)
    assert root.is_synthetic
    import polars as pl

    bars = pl.concat(
        [
            pl.read_parquet(p, hive_partitioning=False)
            for p in root.curated_parts("bars_1m", "synthetic", CLEAN_SYMBOL)
        ]
    )
    assert bars.height == DAYS * 1440
    # A minute with trades is known at its close plus the declared allowance.
    traded = bars.filter(pl.col("trade_count") > 0)
    spread = traded["knowable_time"].dt.timestamp("us") - traded["close_time"].dt.timestamp("us")
    assert spread.unique().to_list() == [250_000]
    # Some minutes have no trades. They stay as rows with no price, and consecutive ids prove them.
    empty = bars.filter(pl.col("close").is_null())
    assert empty.height > 0
    assert empty["volume"].sum() == 0.0
    # The last minute of the last day has no row after it, so it alone can be unproven.
    assert empty["empty_proof"].unique().sort().to_list() in (["id_run"], ["id_run", "none"])
    assert (empty["knowable_time"] > empty["close_time"]).all()
    daily = pl.concat(
        [
            pl.read_parquet(p, hive_partitioning=False)
            for p in root.curated_parts("bars_1d", "synthetic", CLEAN_SYMBOL)
        ]
    )
    assert daily.height == DAYS
    # Every day but the last, whose next file has not come.
    assert daily["complete"].to_list() == [True] * (DAYS - 1) + [False]


def test_reconciliation_sees_the_spills_it_should_explain_and_fails_the_one_it_should_not(
    run: dict[str, Any],
) -> None:
    """The generator implements the rule's own hypothesis, so a run that always passed would say nothing about
    the rule."""
    official = run["status"]["reconciliation"]["official_candles"]
    assert official["days"] == DAYS * 2
    assert official["fail"] == 1
    assert official["pass"] + official["warn"] == DAYS * 2 - 1
    with Catalog(run["base"] / "root" / "catalog" / "catalog.sqlite") as catalog:
        rows = catalog.reconciliations("official_candles")
        excluded = catalog.exclusions()
    failed = [row for row in rows if row["status"] == "fail"]
    assert [(row["symbol"], row["date"]) for row in failed] == [(FAULT_SYMBOL, FAULT_DAY.isoformat())]
    assert [(row["symbol"], row["date"]) for row in excluded] == [(FAULT_SYMBOL, FAULT_DAY.isoformat())]
    assert run["status"]["reconciliation"]["exclusions"] == 1
    details = [row["detail"] for row in rows if row["status"] != "fail"]
    # The generator spills volume over some midnights, and the checks must find it and account for it.
    assert any(detail["volume_diff"] > 0 for detail in details)
    assert any(detail["carry_in"] > 0 for detail in details)
    assert all(detail["boundaries_unexplained"] == 0 for detail in details)
    assert any(detail["bars_volume_diff_over_0_001"] > 0 for detail in details)
    assert all(detail["largest_window_needed_ms"] <= 250.0 for detail in details)
    assert failed[0]["detail"]["boundaries_unexplained"] == 1


def test_a_failed_day_keeps_its_bars_and_only_the_minute_it_cannot_explain_is_flagged(
    run: dict[str, Any],
) -> None:
    """DC-08, through the whole path: an aggregate 400 ms before a minute's end, against a window of 250
    ms."""
    import polars as pl

    root = DataRoot(run["base"] / "root", create=False)
    bars = pl.read_parquet(
        root.curated_part("bars_1m", "synthetic", FAULT_SYMBOL, FAULT_DAY), hive_partitioning=False
    )
    assert bars.height == 1440
    flagged = bars.filter(pl.col("gap"))
    assert flagged.height > 0
    first_flag = flagged["close_time"].to_list()[0]
    # 10:00 on that day: the bar holding the spill closes at 10:01. Everything before it stands.
    assert first_flag.isoformat().startswith(f"{FAULT_DAY.isoformat()}T10:01:00")
    assert bars.filter(pl.col("close_time") < first_flag)["gap"].sum() == 0


def test_benchmark_equals_a_calculation_made_directly_from_the_generator(run: dict[str, Any]) -> None:
    """Only whole, passing days count, so the last day and the failed day do not."""
    market = SyntheticMarket(SEED, FIRST_DAY, DAYS)
    start_ms = market.day_range_ms(market.first_day)[0]
    end_ms = market.day_range_ms(market.last_day() - dt.timedelta(days=1))[1]
    # Bars cover (open, close], so a trade exactly at the first midnight belongs to the bar before the period,
    # and one exactly at the last midnight belongs to its last bar.
    inside = [t for t in market.trades[CLEAN_SYMBOL] if start_ms < t.stamp_ms <= end_ms]
    item = run["status"]["benchmarks"][CLEAN_SYMBOL]
    days = DAYS - 1
    expected = inside[-1].price / inside[0].price - 1.0
    assert item["total_return"] == pytest.approx(expected)
    assert item["days"] == float(days)
    assert item["daily_returns"] == days
    assert item["cagr"] == pytest.approx((1.0 + expected) ** (365.0 / days) - 1.0)
    assert item["max_drawdown"] <= 0.0
    assert item["max_drawdown_note"] is None


def test_results_leave_out_the_failed_day_and_start_after_it(run: dict[str, Any]) -> None:
    item = run["status"]["benchmarks"][FAULT_SYMBOL]
    assert item["start"].startswith((FAULT_DAY + dt.timedelta(days=1)).isoformat())
    assert item["days"] == float(DAYS - 2 - _FAULT_DAY_INDEX)
    assert item["missing_days_before_start"] is True
    assert "left out of results: 1" in run["html"]


def test_the_hourly_poll_ran_with_its_lateness_measured(run: dict[str, Any]) -> None:
    summary = run["summary"]
    poll = run["status"]["live_poll"]
    assert summary["poll_runs"] == summary["poll_runs_logged"] == poll["runs"]
    assert poll["runs"] > 30
    assert poll["scheduled_runs"] == poll["runs"]
    assert poll["delay_median_s"] > 0
    assert poll["delay_max_s"] >= poll["delay_p90_s"] >= poll["delay_median_s"]
    # One per symbol: what happened between the start date and the first row is not known.
    assert poll["gaps"] == 2
    assert poll["failed_runs"] == 0
    assert poll["last_status"] == "ok"
    # At this trade rate some hours hold no record close enough to the cut. They say so, and most do not.
    assert 0 <= poll["data_gap_runs"] < poll["runs"]
    assert poll["server_time_share"] == 0.0
    assert set(poll["symbols"]) == set(SYMBOLS)
    assert "how late is the schedule" in run["html"]


def test_polled_bars_match_a_rebuild_and_agree_with_the_other_market(run: dict[str, Any]) -> None:
    results = run["summary"]["live_checks"]
    same = [item for item in results if item["check"] == "poll_rebuild"]
    other = [item for item in results if item["check"] == "cross_venue"]
    assert same
    assert other
    assert all(item["status"] == "pass" and item["bars_different"] == 0 for item in same)
    assert all(item["status"] == "pass" for item in other)
    assert all(item["median_abs_close_diff_bps"] < 30.0 for item in other)


def test_polled_bars_were_only_knowable_when_received(run: dict[str, Any]) -> None:
    import polars as pl

    root = DataRoot(run["base"] / "live", create=False)
    bars = pl.concat(
        [
            pl.read_parquet(p, hive_partitioning=False)
            for p in root.curated_parts("bars_1m_live", "synthetic-poll", SYMBOLS[0])
        ]
    )
    assert bars.height > 0
    assert (bars["knowable_time"] >= bars["close_time"]).all()
    assert (bars["knowable_time"] > bars["close_time"]).any()


def test_opt_in_book_day_went_through_the_validator_and_only_statistics_are_kept(run: dict[str, Any]) -> None:
    book = run["status"]["book_replay"]
    assert len(book) == 1
    assert book[0]["ok"] is True
    assert book[0]["update_id_breaks"] == 0
    assert book[0]["crossed"] == 0
    assert book[0]["snapshot_mismatches"] == 0
    assert book[0]["snapshots"] == 2
    assert run["summary"]["second_pass"]["book_days_left"] > 0


def test_retention_plan_is_sensible_after_the_run(run: dict[str, Any]) -> None:
    plan = run["summary"]["retention_plan"]
    # What raw is left failed its check, so nothing allows it to go. Curated data is too young for the window
    # rule.
    assert plan["raw-archive-after-curated"]["deletable_files"] == 0
    window = plan["curated-trades-window"]
    assert window["deletable_files"] == 0
    assert window["blocked_files"] == DAYS * 2


def test_same_seed_gives_byte_identical_output(run: dict[str, Any], tmp_path: Path) -> None:
    run_synthetic(
        tmp_path / "root",
        tmp_path / "live",
        tmp_path / "out",
        base_config=base_config(),
        policy=base_policy(),
        days=DAYS,
        seed=SEED,
    )
    assert (tmp_path / "out" / "site" / "index.html").read_text(encoding="utf-8") == run["html"]
    assert (tmp_path / "out" / "status.json").read_text(encoding="utf-8") == run["status_text"]
    # And not only the published files: every file in the data center must come out the same.

    def tree(base: Path) -> dict[str, bytes]:
        found = {}
        for name in ("root", "live", "out"):
            for path in sorted((base / name).rglob("*")):
                if path.is_file():
                    found[path.relative_to(base).as_posix()] = path.read_bytes()
        return found

    first, second = tree(run["base"]), tree(tmp_path)
    assert sorted(first) == sorted(second)
    assert [name for name in first if first[name] != second[name]] == []


def test_another_seed_gives_other_numbers(run: dict[str, Any], tmp_path: Path) -> None:
    run_synthetic(
        tmp_path / "root",
        tmp_path / "live",
        tmp_path / "out",
        base_config=base_config(),
        policy=base_policy(),
        days=2,
        seed=SEED + 1,
    )
    other = json.loads((tmp_path / "out" / "status.json").read_text(encoding="utf-8"))
    assert other["data_kind"] == "SYNTHETIC"
    assert (
        other["benchmarks"][SYMBOLS[0]]["total_return"]
        != run["status"]["benchmarks"][SYMBOLS[0]]["total_return"]
    )


def test_a_real_job_refuses_a_marked_live_root(
    run: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-13. A real root with a generated live root showed 43 generated poll runs, with no label."""
    real = DataRoot(tmp_path / "real")
    Catalog(real.catalog_path).close()
    args = [*_configs_args(), "--data-root", str(tmp_path / "real")]
    live = str(run["base"] / "live")
    assert main([*args, "report", "--published", "--out-dir", str(tmp_path / "x"), "--live-root", live]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
    assert main([*args, "reconcile-live", "--live-root", live]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err


def test_a_generated_root_that_lost_its_marker_cannot_become_market_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F-13. Refusal to publish used to go with the marker."""
    run_synthetic(
        tmp_path / "root",
        tmp_path / "live",
        tmp_path / "out",
        base_config=base_config(),
        policy=base_policy(),
        days=2,
    )
    (tmp_path / "root" / "catalog" / "SYNTHETIC").unlink()
    args = [*_configs_args(), "--data-root", str(tmp_path / "root")]
    assert main([*args, "report", "--published", "--out-dir", str(tmp_path / "x")]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


def test_a_synthetic_run_refuses_a_root_holding_other_data(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "real")
    Catalog(root.catalog_path).close()
    with pytest.raises(ConfigError, match="already holds other data"):
        run_synthetic(
            tmp_path / "real",
            tmp_path / "live",
            tmp_path / "out",
            base_config=base_config(),
            policy=base_policy(),
            days=2,
        )


def _configs_args() -> list[str]:
    return ["--config-dir", str(Path(__file__).resolve().parents[1] / "configs")]


def test_real_ingest_and_poll_refuse_a_synthetic_root(
    run: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(run["base"] / "root")
    assert main([*_configs_args(), "--data-root", root, "ingest", "--light"]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err
    assert main([*_configs_args(), "--data-root", root, "poll"]) == 2
    assert "SYNTHETIC" in capsys.readouterr().err


def test_synthetic_output_cannot_be_marked_published(
    run: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(run["base"] / "root")
    code = main(
        [*_configs_args(), "--data-root", root, "report", "--published", "--out-dir", str(tmp_path / "x")]
    )
    assert code == 2
    assert "SYNTHETIC" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


def test_the_command_line_runs_it_and_labels_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            *_configs_args(),
            "--data-root",
            str(tmp_path / "root"),
            "synthetic-run",
            "--days",
            "2",
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["data_kind"] == "SYNTHETIC"
    assert (tmp_path / "root-live" / "catalog" / "SYNTHETIC").is_file()
    assert (tmp_path / "out" / "site" / "index.html").is_file()


# ---- with no approved source ------------------------------------------------------------------------


def test_daily_workflow_steps_with_no_approved_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The commands of daily-pipeline.yml, in order, on the shipped configuration, network refused."""
    root = str(tmp_path / "root")
    live = str(tmp_path / "live")
    out = tmp_path / "out"
    args = [*_configs_args(), "--data-root", root]

    assert main([*args, "ingest", "--light", "--time-budget", "50m", "--delete-raw-after-curated"]) == 0
    ingest = json.loads(capsys.readouterr().out)
    assert ingest["status"] == "no_approved_source"
    assert ingest["source_state"] == "no approved source configured"
    assert ingest["planned"] == 0
    assert ingest["downloaded_bytes"] == 0

    assert main([*args, "reconcile-live", "--live-root", live]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"
    assert main([*args, "retention"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert main([*args, "health"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert health["source_state"] == "no approved source configured"
    assert health["sources"]["binance"]["prohibited"] is True
    assert all(not item["enabled"] for item in health["sources"].values())
    assert health["coverage"] == []
    assert main([*args, "report", "--published", "--out-dir", str(out), "--live-root", live]) == 0
    capsys.readouterr()

    status = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert status["source_state"] == "no approved source configured"
    assert status["data_kind"] == "NONE"
    assert status["benchmarks"] == {}
    html = (out / "site" / "index.html").read_text(encoding="utf-8")
    assert "No approved source configured" in html
    assert (out / "results" / "status.json").is_file()
    assert (out / "results" / "run_log" / "pipeline_runs.jsonl").is_file()


def test_poll_command_with_no_approved_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = [*_configs_args(), "--data-root", str(tmp_path / "live")]
    assert main([*args, "poll", "--event", "schedule", "--scheduled-cron", "7 * * * *"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "no_approved_source"
    assert record["symbols"] == {}


@pytest.mark.parametrize("command", ["ingest", "poll"])
def test_jobs_that_record_receipts_refuse_a_fixed_clock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """DC-05. A run with a fixed clock stamped its receipts at that time."""
    args = [*_configs_args(), "--data-root", str(tmp_path / "r"), "--now", "2026-03-01T00:00:00Z", command]
    assert main(args) == 2
    assert "--now" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()


@pytest.mark.parametrize("command", [["retention"], ["health"], ["report"], ["reconcile-live"]])
def test_commands_that_only_look_do_not_create_a_mistyped_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    """F-23. A dry run on a mistyped DATA_ROOT used to create it, with zones and a catalog."""
    missing = tmp_path / "mistyped"
    assert main([*_configs_args(), "--data-root", str(missing), *command]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not missing.exists()


def test_the_daily_job_logs_how_late_it_ran(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """F-22. Each run logs how late it was. The poll did, and the daily job did not."""
    root = tmp_path / "r"
    args = [*_configs_args(), "--data-root", str(root)]
    started = "2026-03-01T03:20:00Z"
    command = [
        "ingest",
        "--light",
        "--scheduled-cron",
        "17 3 * * *",
        "--job-started-at",
        started,
        "--event",
        "schedule",
    ]
    assert main([*args, *command]) == 0
    capsys.readouterr()
    logged = json.loads(
        (root / "catalog" / "pipeline_runs.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert logged["scheduled_time"] == "2026-03-01T03:17:00Z"
    assert logged["delay_s"] == 180.0
    assert logged["data_kind"] == "NONE"
    out = tmp_path / "out"
    assert main([*args, "report", "--out-dir", str(out)]) == 0
    capsys.readouterr()
    line = json.loads(
        (out / "results" / "run_log" / "pipeline_runs.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert line["lateness"]["delay_s"] == 180.0


def test_asking_for_a_disabled_dataset_on_the_command_line_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = [*_configs_args(), "--data-root", str(tmp_path / "r")]
    assert main([*args, "ingest", "--datasets", "binance.aggTrades"]) == 2
    assert "disabled" in capsys.readouterr().err
