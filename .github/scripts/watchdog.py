#!/usr/bin/env python3
"""Check the last result on the results branch, and alert the owner through Telegram.

A watchdog exists for the cases where something is wrong, so anything it cannot read is an alert and not a
reason to stay quiet. Standard library only, because it must work with no project code and with nothing
installed.

What it does, by what it finds:
- The result is there and fine: nothing to send. Any earlier alert is forgotten, so the next problem sends
  again.
- The result is old, says its data is stale, or carries alerts: send them. The same text goes to each owner
  once.
- The result cannot be read, for any reason but a true 404: send that.
- A true 404: a note, until the result is overdue. It is overdue once it has been missing for longer than the
  age limit, or after the date in WATCHDOG_EXPECT_RESULT_AFTER, whichever comes first.

An owner's copy counts as sent only on a 200 whose body says ok, and the memory is per owner, so an owner
whose send failed still gets it next time. If any send fails, the run fails, because an alert that did not go
out is the one thing that must not look green. With no Telegram secrets there is nowhere to send, so it writes
the text to the run summary, succeeds, and sends once the secrets exist.

It runs on the same platform as everything else, so a GitHub outage can silence it too.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# Telegram refuses a longer message outright, which would turn a long list of alerts into no alert at all.
MAX_TEXT = 3500
_TIMEOUT_S = 30

Http = Callable[[str, dict[str, str], bytes | None], tuple[int, bytes]]


def http_call(url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    """One request. Any answer is returned with its status, so that a refusal can be told from a success."""
    request = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read())


def read_result(http: Http, repository: str, token: str) -> tuple[str, Any]:
    """Return ("ok", the parsed result), ("missing", None) on a true 404, or ("unreadable", why)."""
    url = f"https://api.github.com/repos/{repository}/contents/status.json?ref=results"
    headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "hft-crypto-watchdog"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, body = http(url, headers, None)
    except (OSError, ValueError) as exc:
        return "unreadable", f"the request failed: {type(exc).__name__}"
    if status == 404:
        return "missing", None
    if status != 200:
        return "unreadable", f"the answer was HTTP {status}"
    try:
        parsed = json.loads(body)
    except ValueError:
        return "unreadable", "status.json is not valid JSON"
    if not isinstance(parsed, dict):
        return "unreadable", "status.json does not hold an object"
    return "ok", parsed


def _parse_time(text: Any) -> dt.datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def problems_in(result: dict[str, Any], now: dt.datetime, max_age_hours: float) -> list[str]:
    """What a readable result says is wrong."""
    found: list[str] = []
    generated = _parse_time(result.get("generated_at"))
    if generated is None:
        found.append("The last result has no readable time, so its age is unknown.")
    else:
        age = (now - generated).total_seconds() / 3600.0
        if age > max_age_hours:
            found.append(f"The last result is {age:.0f} hours old (limit {max_age_hours:g}).")
    if result.get("stale") is True:
        found.append("The last result says its own data is stale.")
    health = result.get("health")
    alerts = health.get("alerts") if isinstance(health, dict) else None
    if not isinstance(alerts, list):
        found.append("The last result holds no list of alerts, so it cannot say what is wrong.")
    else:
        found.extend(str(alert) for alert in alerts)
    return found


def _overdue_since(state_dir: Path, now: dt.datetime) -> dt.datetime:
    """When the result was first seen missing. Kept in the Actions cache, and so lost with it."""
    marker = state_dir / "first_missing"
    seen = _parse_time(marker.read_text(encoding="utf-8").strip()) if marker.is_file() else None
    if seen is None:
        marker.write_text(now.isoformat(), encoding="utf-8")
        return now
    return seen


def problems_when_missing(
    state_dir: Path, now: dt.datetime, max_age_hours: float, expect_after: str
) -> tuple[list[str], str]:
    since = _overdue_since(state_dir, now)
    hours = (now - since).total_seconds() / 3600.0
    expected = _parse_time(expect_after)
    if hours > max_age_hours or (expected is not None and now >= expected):
        return [f"There is no result on the results branch, for at least {hours:.0f} hours."], ""
    return [], f"No result on the results branch yet. First seen missing {hours:.0f} hours ago."


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _owner_file(state_dir: Path, owner: str) -> Path:
    return state_dir / f"last_digest_{digest_of(owner)[:16]}"


def send_one(http: Http, token: str, owner: str, text: str) -> str | None:
    """Return None on a real success, or why not. The reason never holds the token."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": owner, "text": text}).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "hft-crypto-watchdog"}
    try:
        status, answer = http(url, headers, body)
    except (OSError, ValueError) as exc:
        return f"the request failed: {type(exc).__name__}"
    if status != 200:
        return f"HTTP {status}"
    try:
        parsed = json.loads(answer)
    except ValueError:
        return "HTTP 200 with an answer that is not JSON"
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        return "HTTP 200 and the answer does not say ok"
    return None


def run(
    env: Mapping[str, str],
    http: Http,
    now: dt.datetime,
    state_dir: Path,
    note: Callable[[str], None],
) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        max_age = float(env.get("MAX_AGE_HOURS") or "48")
    except ValueError:
        note("MAX_AGE_HOURS is not a number, so 48 hours is used.")
        max_age = 48.0
    state, value = read_result(http, env.get("GITHUB_REPOSITORY", ""), env.get("GH_TOKEN", ""))
    if state == "ok":
        (state_dir / "first_missing").unlink(missing_ok=True)
        problems = problems_in(value, now, max_age)
        note(f"Last result: {value.get('generated_at')}. {len(problems)} things to report.")
    elif state == "missing":
        problems, message = problems_when_missing(
            state_dir, now, max_age, env.get("WATCHDOG_EXPECT_RESULT_AFTER", "")
        )
        if message:
            note(message)
    else:
        (state_dir / "first_missing").unlink(missing_ok=True)
        problems = [f"The watchdog cannot read the last result: {value}."]
    if not problems:
        for old in state_dir.glob("last_digest_*"):
            old.unlink()
        return 0
    text = "\n".join(problems)
    repository = env.get("GITHUB_REPOSITORY", "")
    message_text = f"Watchdog, {repository}:\n{text}"[:MAX_TEXT]
    digest = digest_of(text)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    owners = [item.strip() for item in env.get("TELEGRAM_OWNER_IDS", "").split(",") if item.strip()]
    if not token or not owners:
        note("There is something to report. The Telegram secrets are not set, so no alert was sent.")
        note(text)
        return 0
    failures = 0
    for owner in owners:
        memory = _owner_file(state_dir, owner)
        if memory.is_file() and memory.read_text(encoding="utf-8").strip() == digest:
            note("Nothing has changed since this owner's last alert, so none was sent.")
            continue
        problem = send_one(http, token, owner, message_text)
        if problem is None:
            memory.write_text(digest, encoding="utf-8")
            note("An alert was sent.")
        else:
            failures += 1
            note(f"An alert could not be sent: {problem}.")
    # The step fails here, and only here. An alert that did not go out must not look like a green run.
    return 1 if failures else 0


def _write_note(line: str) -> None:
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def main() -> int:
    state_dir = Path(os.environ.get("STATE_DIR") or "watchdog-state")
    return run(os.environ, http_call, dt.datetime.now(dt.UTC), state_dir, _write_note)


if __name__ == "__main__":
    sys.exit(main())
