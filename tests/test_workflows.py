"""The workflows are part of the system. These checks run on their text, and publish_results.sh for real."""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from helpers import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SCRIPT = REPO_ROOT / ".github" / "scripts" / "publish_results.sh"
WATCHDOG = REPO_ROOT / ".github" / "scripts" / "watchdog.py"
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
    # F-17. Each save makes a new copy before the old one goes, so this stays under half of GitHub's limit.
    assert 'DATA_QUOTA_GB: "4"' in body


def test_retention_is_a_dry_run_in_the_workflow() -> None:
    assert "--execute" not in text("daily-pipeline.yml")


def test_hourly_poll_is_short_never_overlaps_and_stays_off_until_enabled() -> None:
    body = text("live-poll.yml")
    # C17 freezes minute 7, because it avoids the top of the hour.
    assert 'cron: "7 * * * *"' in body
    assert "group: live-poll" in body
    assert "cancel-in-progress: false" in body
    assert "--time-budget 120s" in body
    assert re.search(r"poll:\n    if: [^\n]*vars\.LIVE_POLL_ENABLED == 'true'", body)
    for flag in ("--scheduled-cron", "--job-started-at", "--previous-state"):
        assert flag in body


def _watchdog() -> Any:
    spec = importlib.util.spec_from_file_location("watchdog", WATCHDOG)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["watchdog"] = module
    spec.loader.exec_module(module)
    return module


NOW = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)
FRESH = {"generated_at": "2026-03-10T03:00:00Z", "stale": False, "health": {"alerts": []}}
SECRETS = {"TELEGRAM_BOT_TOKEN": "secret-token", "TELEGRAM_OWNER_IDS": "1,2", "GITHUB_REPOSITORY": "o/r"}


class _Host:
    """GitHub and Telegram, as far as the watchdog can tell. Each owner's answer can be set on its own."""

    def __init__(self, result: Any = FRESH, *, status: int = 200, error: Exception | None = None) -> None:
        self.result = result
        self.status = status
        self.error = error
        self.telegram: dict[str, tuple[int, bytes]] = {}
        self.sent: list[dict[str, str]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        if "api.github.com" in url:
            if self.error is not None:
                raise self.error
            payload = self.result if isinstance(self.result, bytes) else json.dumps(self.result).encode()
            return self.status, payload
        assert body is not None
        fields = dict(urllib.parse.parse_qsl(body.decode()))
        self.sent.append(fields)
        return self.telegram.get(fields["chat_id"], (200, b'{"ok": true}'))


def _watch(
    host: _Host, state: Path, *, env: dict[str, str] | None = None, now: dt.datetime = NOW
) -> tuple[int, list[str]]:
    notes: list[str] = []
    code = _watchdog().run(env if env is not None else SECRETS, host, now, state, notes.append)
    return code, notes


def _with_alert(text: str = "Storage at 96%") -> dict[str, Any]:
    return {**FRESH, "health": {"alerts": [text]}}


def test_a_clean_result_sends_nothing_and_exits_clean(tmp_path: Path) -> None:
    host = _Host()
    code, _ = _watch(host, tmp_path)
    assert code == 0
    assert host.sent == []


def test_a_real_alert_goes_to_each_owner_once(tmp_path: Path) -> None:
    host = _Host(_with_alert())
    assert _watch(host, tmp_path)[0] == 0
    assert sorted(item["chat_id"] for item in host.sent) == ["1", "2"]
    assert "Storage at 96%" in host.sent[0]["text"]
    host.sent.clear()
    assert _watch(host, tmp_path)[0] == 0
    assert host.sent == []


def test_a_change_sends_again_and_an_all_clear_forgets(tmp_path: Path) -> None:
    host = _Host(_with_alert("one"))
    _watch(host, tmp_path)
    host.sent.clear()
    host.result = _with_alert("two")
    _watch(host, tmp_path)
    assert len(host.sent) == 2
    host.sent.clear()
    host.result = FRESH
    _watch(host, tmp_path)
    host.result = _with_alert("two")
    _watch(host, tmp_path)
    assert len(host.sent) == 2


@pytest.mark.parametrize(
    "answer",
    [
        (400, b'{"ok": false}'),
        (401, b'{"ok": false}'),
        (403, b'{"ok": false, "description": "bot was blocked"}'),
        (429, b'{"ok": false}'),
        (500, b"oops"),
        (200, b"not json"),
        (200, b'{"ok": false}'),
    ],
    ids=["400", "401", "403", "429", "500", "200 not json", "200 not ok"],
)
def test_n01_a_refused_alert_is_not_recorded_and_the_run_fails(
    tmp_path: Path, answer: tuple[int, bytes]
) -> None:
    """N-01. A refusal counted as sent, its memory was stored, and the next run said nothing had changed."""
    host = _Host(_with_alert())
    host.telegram = {"1": answer, "2": answer}
    code, notes = _watch(host, tmp_path)
    assert code == 1
    assert not any("An alert was sent" in note for note in notes)
    assert not list(tmp_path.glob("last_digest_*"))
    # It is tried again on the next run, and goes when the host accepts it.
    host.telegram = {}
    host.sent.clear()
    assert _watch(host, tmp_path)[0] == 0
    assert len(host.sent) == 2


def test_n01_one_owners_failure_is_theirs_alone_and_fails_the_run(tmp_path: Path) -> None:
    """N-01. `sent=1` was set if any one send worked, so the other owner never got that alert."""
    host = _Host(_with_alert())
    host.telegram = {"2": (403, b'{"ok": false}')}
    assert _watch(host, tmp_path)[0] == 1
    host.telegram = {}
    host.sent.clear()
    assert _watch(host, tmp_path)[0] == 0
    assert [item["chat_id"] for item in host.sent] == ["2"]


def test_n01_a_connection_failure_is_a_failed_send(tmp_path: Path) -> None:
    class Down(_Host):
        def __call__(self, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
            if "telegram" in url:
                raise ConnectionResetError("reset")
            return super().__call__(url, headers, body)

    assert _watch(Down(_with_alert()), tmp_path)[0] == 1


def test_a_failed_send_never_prints_the_token(tmp_path: Path) -> None:
    host = _Host(_with_alert())
    host.telegram = {"1": (403, b"secret-token"), "2": (500, b"")}
    _, notes = _watch(host, tmp_path)
    assert "secret-token" not in "\n".join(notes)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (_Host(status=403), "HTTP 403"),
        (_Host(status=500), "HTTP 500"),
        (_Host(error=OSError("no route")), "the request failed"),
        (_Host(b"{truncated"), "not valid JSON"),
        (_Host(b"[1, 2]"), "does not hold an object"),
    ],
    ids=["403", "500", "no route", "corrupt", "not an object"],
)
def test_n02_a_result_that_cannot_be_read_is_an_alert(tmp_path: Path, host: _Host, expected: str) -> None:
    """N-02. All of these said "nothing to check", forever, and those are what a watchdog is for."""
    host.sent = []
    code, _ = _watch(host, tmp_path)
    assert code == 0
    assert len(host.sent) == 2
    assert expected in host.sent[0]["text"]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"stale": False, "health": {"alerts": []}}, "no readable time"),
        ({"generated_at": "soon", "stale": False, "health": {"alerts": []}}, "no readable time"),
        ({"generated_at": "2026-03-10T03:00:00Z", "stale": False}, "no list of alerts"),
        ({"generated_at": "2026-03-01T03:00:00Z", "stale": False, "health": {"alerts": []}}, "hours old"),
        ({"generated_at": "2026-03-10T03:00:00Z", "stale": True, "health": {"alerts": []}}, "stale"),
    ],
    ids=["no time", "bad time", "no alerts", "old", "says stale"],
)
def test_a_readable_result_with_something_wrong_is_an_alert(
    tmp_path: Path, result: dict[str, Any], expected: str
) -> None:
    host = _Host(result)
    assert _watch(host, tmp_path)[0] == 0
    assert expected in host.sent[0]["text"]


def test_n02_a_true_404_is_only_a_note_until_it_is_overdue(tmp_path: Path) -> None:
    host = _Host(status=404)
    code, notes = _watch(host, tmp_path)
    assert code == 0
    assert host.sent == []
    assert any("No result" in note for note in notes)
    assert _watch(host, tmp_path, now=NOW + dt.timedelta(hours=47))[0] == 0
    assert host.sent == []
    assert _watch(host, tmp_path, now=NOW + dt.timedelta(hours=49))[0] == 0
    assert len(host.sent) == 2
    assert "no result" in host.sent[0]["text"]


def test_n02_a_date_in_a_variable_makes_no_result_an_alert_from_then_on(tmp_path: Path) -> None:
    host = _Host(status=404)
    env = {**SECRETS, "WATCHDOG_EXPECT_RESULT_AFTER": "2026-03-10T00:00:00Z"}
    assert _watch(host, tmp_path, env=env)[0] == 0
    assert len(host.sent) == 2


def test_with_no_secrets_it_stays_quiet_says_what_it_found_and_sends_later(tmp_path: Path) -> None:
    host = _Host(_with_alert())
    code, notes = _watch(host, tmp_path, env={"GITHUB_REPOSITORY": "o/r"})
    assert code == 0
    assert host.sent == []
    assert any("Storage at 96%" in note for note in notes)
    assert _watch(host, tmp_path)[0] == 0
    assert len(host.sent) == 2


def test_a_long_list_of_alerts_still_fits_in_one_message(tmp_path: Path) -> None:
    """Telegram refuses a message that is too long, which would turn many alerts into none."""
    module = _watchdog()
    host = _Host({**FRESH, "health": {"alerts": ["x" * 50] * 500}})
    _watch(host, tmp_path)
    assert len(host.sent[0]["text"]) <= module.MAX_TEXT


def test_the_workflow_runs_the_script_and_keeps_what_was_sent() -> None:
    body = text("watchdog.yml")
    assert "python3 .github/scripts/watchdog.py" in body
    assert "persist-credentials: false" in body
    assert "ref=results" in WATCHDOG.read_text(encoding="utf-8")
    assert "if: always()" in body
    assert "WATCHDOG_EXPECT_RESULT_AFTER" in body


def test_the_watchdog_script_uses_the_standard_library_only() -> None:
    """It runs with nothing installed, so that a missing tool cannot read as nothing to report."""
    tree = ast.parse(WATCHDOG.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert names - {"__future__"} <= set(sys.stdlib_module_names)


SCHEDULE_OR_DEFAULT = (
    "github.event_name == 'schedule' || "
    "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
)


@pytest.mark.parametrize("name", ["daily-pipeline.yml", "live-poll.yml"])
def test_only_the_default_branch_prunes_publishes_and_saves(name: str) -> None:
    """F-17, N-03, R7.2. A schedule always runs on the default branch, and that case needs nothing from the
    payload.

    Whether a schedule's payload carries `repository` could not be checked here, and if it did not, publish,
    deploy and prune would all skip in a green run. So the expression no longer depends on it there.
    """
    body = text(name)
    for job in ("prune-cache", "publish-results" if name == "daily-pipeline.yml" else "publish"):
        block = body.split(f"\n  {job}:\n", 1)[1]
        head = block.split("steps:", 1)[0]
        assert SCHEDULE_OR_DEFAULT in head, job
    save = body.split("cache/save@", 1)[0].rsplit("- name:", 1)[1]
    assert SCHEDULE_OR_DEFAULT in save
    assert "REF_NAME: ${{ github.ref_name }}" in body
    assert '--ref "refs/heads/$REF_NAME"' in body
    assert "DEFAULT_BRANCH" not in body
    assert "github.ref == format" not in body.replace(SCHEDULE_OR_DEFAULT, "")


def test_the_page_deploys_on_the_same_terms() -> None:
    block = text("daily-pipeline.yml").split("\n  deploy-pages:\n", 1)[1].split("steps:", 1)[0]
    assert SCHEDULE_OR_DEFAULT in block


def test_the_retention_plan_lists_each_file() -> None:
    """R3.5. The lifecycle asks for each file, and the workflow printed counts."""
    assert "hft-crypto retention --show-files" in text("daily-pipeline.yml")


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_the_tool_is_pinned_as_well_as_the_action(path: Path) -> None:
    body = path.read_text(encoding="utf-8")
    assert body.count("astral-sh/setup-uv@") == body.count('version: "0.11.24"')


def test_no_input_reaches_a_shell_except_through_the_environment() -> None:
    for path in ALL:
        in_run = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("run:"):
                in_run = True
                indent = len(line) - len(line.lstrip())
                assert "${{" not in stripped, f"{path.name}: {line}"
                continue
            if in_run and stripped and len(line) - len(line.lstrip()) <= indent:
                in_run = False
            if in_run:
                assert "${{ inputs" not in line, f"{path.name}: {line}"
                assert "${{ matrix" not in line, f"{path.name}: {line}"


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


def test_publish_keeps_duplicate_lines_already_in_a_log(
    tmp_path: Path, repositories: tuple[Path, Path]
) -> None:
    """F-15. Three existing lines, two of them identical, plus one new line, used to give three."""
    origin, work = repositories
    first = write_bundle(tmp_path / "b1", {"run_log/x.jsonl": '{"a":1}\n{"a":1}\n{"a":2}\n'})
    assert publish(work, first, "one").returncode == 0
    second = write_bundle(tmp_path / "b2", {"run_log/x.jsonl": '{"a":3}\n'})
    assert publish(work, second, "two").returncode == 0
    assert branch_file(origin, "run_log/x.jsonl").splitlines() == ['{"a":1}', '{"a":1}', '{"a":2}', '{"a":3}']


def test_publish_refuses_an_edited_line_in_a_ledger_log(
    tmp_path: Path, repositories: tuple[Path, Path]
) -> None:
    """F-15. The log case came first, so a changed P&L was appended, with exit 0."""
    origin, work = repositories
    good = write_bundle(tmp_path / "b1", {"ledger/e.jsonl": '{"id":1,"pnl":-5}\n'})
    assert publish(work, good, "one").returncode == 0
    edited = write_bundle(tmp_path / "b2", {"ledger/e.jsonl": '{"id":1,"pnl":5}\n'})
    done = publish(work, edited, "two")
    assert done.returncode != 0
    assert "append-only" in done.stderr
    assert branch_file(origin, "ledger/e.jsonl") == '{"id":1,"pnl":-5}\n'
    grown = write_bundle(tmp_path / "b3", {"ledger/e.jsonl": '{"id":1,"pnl":-5}\n{"id":2,"pnl":1}\n'})
    assert publish(work, grown, "three").returncode == 0
    assert branch_file(origin, "ledger/e.jsonl").splitlines()[1] == '{"id":2,"pnl":1}'


@pytest.mark.parametrize(
    "name",
    [
        ".git/config",
        ".gitignore",
        "run_log/.hidden.jsonl",
        ".github/workflows/x.yml",
        "run_log/sub/x.jsonl",
        "ledger/sub/x.json",
        "decisions/sub/x.json",
        "README.md",
        "index.html",
        "a/b.json",
    ],
)
def test_publish_copies_only_what_is_on_the_list(
    tmp_path: Path, repositories: tuple[Path, Path], name: str
) -> None:
    """F-14. A bundle's .git/config ran a command during `git add`, in the job holding the write token."""
    origin, work = repositories
    assert publish(work, write_bundle(tmp_path / "b1", {"status.json": "{}\n"}), "one").returncode == 0
    before = git(origin, "rev-parse", "results")
    bundle = write_bundle(tmp_path / "b2", {"status.json": "changed\n", name: "anything\n"})
    done = publish(work, bundle, "two")
    assert done.returncode != 0
    assert "Refusing" in done.stderr
    assert git(origin, "rev-parse", "results") == before


def test_publish_refuses_a_link_in_the_bundle(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    bundle = write_bundle(tmp_path / "b1", {"status.json": "{}\n"})
    try:
        (bundle / "live_state.json").symlink_to(bundle / "status.json")
    except OSError:
        pytest.skip("creating file symlinks needs a privilege on this machine")
    done = publish(work, bundle, "one")
    assert done.returncode != 0
    assert "regular file" in done.stderr
    assert "results" not in git(origin, "branch", "--list", "results")


def test_publish_with_nothing_new_makes_no_commit(tmp_path: Path, repositories: tuple[Path, Path]) -> None:
    origin, work = repositories
    bundle = write_bundle(tmp_path / "b1", {"run_log/x.jsonl": '{"a":1}\n'})
    assert publish(work, bundle, "one").returncode == 0
    before = git(origin, "rev-parse", "results")
    done = publish(work, bundle, "two")
    assert done.returncode == 0
    assert "Nothing new" in done.stdout
    assert git(origin, "rev-parse", "results") == before


def run_blocks(path: Path) -> list[str]:
    """The shell text of every `run: |` block in a workflow."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for next_line in lines[index + 1 :]:
            if next_line.strip() and len(next_line) - len(next_line.lstrip()) <= indent:
                break
            body.append(next_line)
        blocks.append("\n".join(body) + "\n")
    return blocks


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_every_shell_block_in_a_workflow_parses(path: Path) -> None:
    """No tool here can run a workflow. This much can be checked, and it covers the rewritten watchdog."""
    if BASH is None:
        pytest.skip("needs bash")
    for block in run_blocks(path):
        done = subprocess.run(
            [BASH, "-n"], input=block, capture_output=True, text=True, check=False, timeout=60
        )
        assert done.returncode == 0, f"{done.stderr}\n{block}"


def test_the_publish_script_parses() -> None:
    if BASH is None:
        pytest.skip("needs bash")
    text_of = SCRIPT.read_text(encoding="utf-8")
    done = subprocess.run(
        [BASH, "-n"], input=text_of, capture_output=True, text=True, check=False, timeout=60
    )
    assert done.returncode == 0, done.stderr


def test_no_workflow_starts_the_coverage_check_or_names_a_check_root() -> None:
    """Coverage record, section 5. It gets its own manually started job once approved, with no cache and no
    publish."""
    for path in sorted((REPO_ROOT / ".github").rglob("*")):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "coverage-check" not in text, path.name
            assert "candle-check" not in text, path.name
            assert "CHECK_ROOT" not in text, path.name


def test_no_workflow_can_pass_a_flag_that_matters_to_the_ceiling() -> None:
    """The ceiling holds in code, so a workflow needs no --end. If one is ever added, it must not be taken for
    a guard."""
    from hft_crypto.config import LAST_OPENED_DATE

    daily = (REPO_ROOT / ".github" / "workflows" / "daily-pipeline.yml").read_text(encoding="utf-8")
    assert "--end" not in daily
    assert LAST_OPENED_DATE.year == 2023
