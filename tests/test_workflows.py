"""The workflows are part of the system. These checks run on their text, and publish_results.sh for real."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPT = REPO_ROOT / ".github" / "scripts" / "publish_results.sh"
ALL = sorted(WORKFLOWS.glob("*.yml"))
BASH = shutil.which("bash")
GIT = shutil.which("git")


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_the_expected_workflows_exist() -> None:
    assert {path.name for path in ALL} >= {
        "ci.yml",
        "daily-pipeline.yml",
        "live-poll.yml",
        "watchdog.yml",
    }


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_commit(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.search(r"uses:\s*(\S+)", line)
        if match:
            assert re.search(r"@[0-9a-f]{40}$", match.group(1)), line
            assert "# v" in line, f"say which version this commit is: {line}"


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_runner_image_is_fixed(path: Path) -> None:
    body = path.read_text(encoding="utf-8")
    assert "ubuntu-latest" not in body
    assert "runs-on: ubuntu-24.04" in body


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_default_permissions_are_read_only(path: Path) -> None:
    assert re.search(r"^permissions:\n  contents: read$", path.read_text(encoding="utf-8"), re.MULTILINE)


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_jobs_have_time_limits(path: Path) -> None:
    body = path.read_text(encoding="utf-8")
    assert body.count("runs-on:") == body.count("timeout-minutes:")


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_workflow_reaches_a_dataset_host(path: Path) -> None:
    """Which sources are used is decided in configuration only. No workflow names a dataset host."""
    body = path.read_text(encoding="utf-8")
    for host in (
        "binance",
        "bybit",
        "bycsi",
        "api.kraken.com",
        "okx",
        "gateio",
        "coinbase",
        "bitstamp",
    ):
        for line in body.splitlines():
            if host in line.lower() and not line.lstrip().startswith("#"):
                pytest.fail(f"{path.name} names {host}: {line}")


@pytest.mark.parametrize("name", ["daily-pipeline.yml", "live-poll.yml"])
def test_only_the_job_that_needs_it_can_write(name: str) -> None:
    body = text(name)
    jobs = re.split(r"^  (?=[a-z-]+:\n)", body.split("\njobs:\n", 1)[1], flags=re.MULTILINE)
    for job in jobs:
        if "contents: write" in job:
            assert "uv " not in job, "a job that can write must run no project code"
            assert "publish_results.sh" in job
        if "actions: write" in job:
            assert "gh cache delete" in job
            assert "uv " not in job
            assert "actions/checkout" not in job
    assert body.count("contents: write") == 1
    assert body.count("actions: write") == 1


def test_daily_budget_is_about_an_hour() -> None:
    body = text("daily-pipeline.yml")
    assert 'default: "50m"' in body
    assert "|| '50m'" in body
    assert re.search(r"pipeline:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 75", body)


def test_daily_deletes_raw_and_keeps_only_the_persisted_zones() -> None:
    body = text("daily-pipeline.yml")
    assert "--delete-raw-after-curated" in body
    assert "--light" in body
    assert "/raw" not in body
    for zone in ("curated", "features", "catalog"):
        assert f"${{{{ env.DATA_ROOT }}}}/{zone}" in body
    assert 'DATA_QUOTA_GB: "8"' in body


def test_retention_is_a_dry_run_in_the_workflow() -> None:
    assert "--execute" not in text("daily-pipeline.yml")


def test_hourly_poll_is_short_never_overlaps_and_stays_off_until_enabled() -> None:
    body = text("live-poll.yml")
    assert 'cron: "23 * * * *"' in body
    assert "group: live-poll" in body
    assert "cancel-in-progress: false" in body
    assert "--time-budget 120s" in body
    assert re.search(r"poll:\n    if: [^\n]*vars\.LIVE_POLL_ENABLED == 'true'", body)
    for flag in ("--scheduled-cron", "--job-started-at", "--previous-state"):
        assert flag in body


def test_watchdog_is_quiet_without_secrets_and_never_fails() -> None:
    body = text("watchdog.yml")
    assert '[ -z "$TELEGRAM_BOT_TOKEN" ]' in body
    assert "ref=results" in body
    assert "exit 1" not in body


def test_ci_runs_all_three_tools() -> None:
    body = text("ci.yml")
    for command in ("ruff check", "ruff format --check", "mypy", "pytest"):
        assert command in body


def git(cwd: Path, *args: str) -> str:
    assert GIT is not None
    done = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=60)
    return done.stdout


def publish(work: Path, bundle: Path, message: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    return subprocess.run(
        [BASH, str(SCRIPT).replace("\\", "/"), str(bundle).replace("\\", "/"), message],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path]:
    if BASH is None or GIT is None:
        pytest.skip("needs bash and git")
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--quiet", "--bare", str(origin))
    work = tmp_path / "work"
    git(tmp_path, "clone", "--quiet", str(origin), str(work))
    git(work, "config", "user.name", "t")
    git(work, "config", "user.email", "t@example.invalid")
    (work / "code.txt").write_text("the main branch\n", encoding="utf-8")
    git(work, "add", "--all")
    git(work, "commit", "--quiet", "-m", "start")
    git(work, "push", "--quiet", "origin", "HEAD:main")
    return origin, work


def write_bundle(path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return path


def branch_file(origin: Path, name: str) -> str:
    return git(origin, "show", f"results:{name}")


def test_publish_creates_the_branch_without_the_code(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    bundle = write_bundle(
        tmp_path / "b1", {"status.json": "{}\n", "run_log/poll_runs.jsonl": '{"run_id":"a"}\n'}
    )
    done = publish(work, bundle, "first")
    assert done.returncode == 0, done.stderr
    assert sorted(git(origin, "ls-tree", "-r", "--name-only", "results").split()) == [
        "run_log/poll_runs.jsonl",
        "status.json",
    ]


def test_publish_only_appends_to_logs(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    first = write_bundle(tmp_path / "b1", {"run_log/x.jsonl": '{"a":1}\n{"a":2}\n'})
    assert publish(work, first, "one").returncode == 0
    # The next bundle lost line 1, as after a lost cache, and adds line 3. Line 1 must survive, in place.
    second = write_bundle(tmp_path / "b2", {"run_log/x.jsonl": '{"a":2}\n{"a":3}\n'})
    assert publish(work, second, "two").returncode == 0
    assert branch_file(origin, "run_log/x.jsonl").splitlines() == ['{"a":1}', '{"a":2}', '{"a":3}']


def test_publish_replaces_current_state(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    assert publish(work, write_bundle(tmp_path / "b1", {"status.json": "old\n"}), "one").returncode == 0
    assert publish(work, write_bundle(tmp_path / "b2", {"status.json": "new\n"}), "two").returncode == 0
    assert branch_file(origin, "status.json") == "new\n"


def test_publish_refuses_to_change_a_ledger_record(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    assert publish(work, write_bundle(tmp_path / "b1", {"ledger/e1.json": "first\n"}), "one").returncode == 0
    done = publish(work, write_bundle(tmp_path / "b2", {"ledger/e1.json": "edited\n"}), "two")
    assert done.returncode != 0
    assert "append-only" in done.stderr
    assert branch_file(origin, "ledger/e1.json") == "first\n"


def test_publish_with_nothing_new_makes_no_commit(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    bundle = write_bundle(tmp_path / "b1", {"run_log/x.jsonl": '{"a":1}\n'})
    assert publish(work, bundle, "one").returncode == 0
    before = git(origin, "rev-parse", "results")
    done = publish(work, bundle, "two")
    assert done.returncode == 0
    assert "Nothing new" in done.stdout
    assert git(origin, "rev-parse", "results") == before
