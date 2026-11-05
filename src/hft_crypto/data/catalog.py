"""SQLite catalog: every dataset, file, run, deletion, gap and reconciliation.

This is the manifest of docs/05_DATA_LIFECYCLE.md section 6. A file's class is deliberately not stored
here, because it comes from the zone. See zones.classify.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hft_crypto.data.guard import canonical_rel_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  zone TEXT NOT NULL,
  kind TEXT NOT NULL,
  tier TEXT,
  source TEXT,
  venue TEXT,
  symbol TEXT,
  terms_note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  rel_path TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  partition_key TEXT,
  date_start TEXT,
  date_end TEXT,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  row_count INTEGER,
  source_url TEXT,
  created_at TEXT NOT NULL,
  code_version TEXT NOT NULL,
  check_status TEXT NOT NULL,
  check_detail TEXT,
  checked_at TEXT,
  status TEXT NOT NULL DEFAULT 'present',
  gone_at TEXT
);
CREATE INDEX IF NOT EXISTS files_by_dataset ON files(dataset_id, partition_key);
CREATE TABLE IF NOT EXISTS file_parents (
  child_path TEXT NOT NULL,
  parent_path TEXT NOT NULL,
  PRIMARY KEY (child_path, parent_path)
);
CREATE INDEX IF NOT EXISTS parents_by_parent ON file_parents(parent_path);
CREATE TABLE IF NOT EXISTS tasks (
  task_key TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  partition_key TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  last_attempt_at TEXT,
  next_retry_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_by_dataset ON tasks(dataset_id, symbol, state);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  code_version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0,
  data_manifest TEXT,
  summary TEXT
);
CREATE TABLE IF NOT EXISTS deletions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deleted_at TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  data_class TEXT NOT NULL,
  code_version TEXT NOT NULL,
  run_id TEXT
);
CREATE TABLE IF NOT EXISTS gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  reason TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  run_id TEXT,
  UNIQUE (dataset_id, start_time, end_time, reason)
);
CREATE TABLE IF NOT EXISTS disk_snapshots (
  taken_at TEXT NOT NULL,
  zone TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  PRIMARY KEY (taken_at, zone)
);
CREATE TABLE IF NOT EXISTS reconciliations (
  check_name TEXT NOT NULL,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  PRIMARY KEY (check_name, venue, symbol, date)
);
CREATE TABLE IF NOT EXISTS poll_state (
  symbol TEXT PRIMARY KEY,
  cursor_ns TEXT NOT NULL,
  last_trade_id INTEGER,
  emitted_end_us INTEGER,
  last_trade_us INTEGER,
  rebuilding INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_name TEXT NOT NULL,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL,
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_path TEXT NOT NULL,
  old_sha256 TEXT NOT NULL,
  new_sha256 TEXT NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exclusions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  reason TEXT NOT NULL,
  boundary_window_ms REAL,
  excluded_at TEXT NOT NULL,
  resolved_at TEXT,
  fault_day TEXT,
  UNIQUE (venue, symbol, date, reason)
);
CREATE TABLE IF NOT EXISTS allowance_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  venue TEXT NOT NULL,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  needed_ms REAL NOT NULL,
  allowance_ms REAL NOT NULL,
  found_at TEXT NOT NULL,
  UNIQUE (venue, symbol, date)
);
"""
_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class FileRecord:
    rel_path: str
    dataset_id: str
    kind: str
    partition_key: str | None
    date_start: str | None
    date_end: str | None
    size_bytes: int
    sha256: str
    row_count: int | None
    source_url: str | None
    created_at: str
    code_version: str
    check_status: str
    check_detail: dict[str, Any] | None = None
    checked_at: str | None = None
    status: str = "present"


@dataclass(frozen=True)
class TaskRecord:
    task_key: str
    dataset_id: str
    symbol: str
    partition_key: str
    state: str
    attempts: int
    last_error: str | None
    last_attempt_at: str | None
    next_retry_at: str | None


@dataclass(frozen=True)
class PollState:
    symbol: str
    cursor_ns: int
    last_trade_id: int | None
    emitted_end_us: int | None
    last_trade_us: int | None
    rebuilding: bool = False


def _manifest_path(entry: Any) -> str:
    return str(entry["path"]) if isinstance(entry, dict) else str(entry)


def _file_from_row(row: sqlite3.Row) -> FileRecord:
    detail = row["check_detail"]
    return FileRecord(
        rel_path=row["rel_path"],
        dataset_id=row["dataset_id"],
        kind=row["kind"],
        partition_key=row["partition_key"],
        date_start=row["date_start"],
        date_end=row["date_end"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        row_count=row["row_count"],
        source_url=row["source_url"],
        created_at=row["created_at"],
        code_version=row["code_version"],
        check_status=row["check_status"],
        check_detail=None if detail is None else json.loads(detail),
        checked_at=row["checked_at"],
        status=row["status"],
    )


class Catalog:
    """Thin typed wrapper. Each public method is one committed transaction."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=30.0)
        self._db.row_factory = sqlite3.Row
        # No write-ahead log: the file is carried in a cache between runs, and one file is safer to carry.
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        # Only when needed, because opening a catalog just to read it must leave the file untouched.
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version != _SCHEMA_VERSION:
            with self._db:
                self._db.executescript(_SCHEMA)
                # A catalog restored from an older cache has this table without the column.
                columns = {row[1] for row in self._db.execute("PRAGMA table_info(exclusions)")}
                if "fault_day" not in columns:
                    self._db.execute("ALTER TABLE exclusions ADD COLUMN fault_day TEXT")
                self._db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Catalog:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ---- datasets and files ----------------------------------------------------------------------------

    def upsert_dataset(
        self,
        dataset_id: str,
        *,
        zone: str,
        kind: str,
        tier: str | None,
        source: str | None,
        venue: str | None,
        symbol: str | None,
        terms_note: str | None,
        now: str,
    ) -> None:
        with self._db:
            self._db.execute(
                """INSERT INTO datasets
                   (dataset_id, zone, kind, tier, source, venue, symbol, terms_note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(dataset_id) DO UPDATE SET
                     tier=excluded.tier, source=excluded.source, terms_note=excluded.terms_note""",
                (dataset_id, zone, kind, tier, source, venue, symbol, terms_note, now),
            )

    def register_file(self, record: FileRecord, parents: Iterable[str] = ()) -> None:
        parents = tuple(parents)
        canonical_rel_path(record.rel_path)
        for parent in parents:
            canonical_rel_path(parent)
        detail = None if record.check_detail is None else json.dumps(record.check_detail, sort_keys=True)
        previous = self.get_file(record.rel_path)
        with self._db:
            if previous is not None and previous.sha256 != record.sha256:
                self._db.execute(
                    """INSERT INTO file_history (rel_path, old_sha256, new_sha256, changed_at)
                       VALUES (?,?,?,?)""",
                    (record.rel_path, previous.sha256, record.sha256, record.created_at),
                )
            self._db.execute(
                """INSERT OR REPLACE INTO files
                   (rel_path, dataset_id, kind, partition_key, date_start, date_end, size_bytes, sha256,
                    row_count, source_url, created_at, code_version, check_status, check_detail,
                    checked_at, status, gone_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                (
                    record.rel_path,
                    record.dataset_id,
                    record.kind,
                    record.partition_key,
                    record.date_start,
                    record.date_end,
                    record.size_bytes,
                    record.sha256,
                    record.row_count,
                    record.source_url,
                    record.created_at,
                    record.code_version,
                    record.check_status,
                    detail,
                    record.checked_at,
                    record.status,
                ),
            )
            self._db.execute("DELETE FROM file_parents WHERE child_path=?", (record.rel_path,))
            self._db.executemany(
                "INSERT OR IGNORE INTO file_parents (child_path, parent_path) VALUES (?,?)",
                [(record.rel_path, parent) for parent in parents],
            )

    def changed_files(self, prefix: str) -> list[dict[str, Any]]:
        """Files whose content changed after being recorded. On a delivered file that deserves an alert."""
        rows = self._db.execute("SELECT * FROM file_history ORDER BY id")
        return [dict(row) for row in rows if str(row["rel_path"]).startswith(prefix)]

    def get_file(self, rel_path: str) -> FileRecord | None:
        row = self._db.execute("SELECT * FROM files WHERE rel_path=?", (rel_path,)).fetchone()
        return None if row is None else _file_from_row(row)

    def files(self, *, status: str | None = "present", prefix: str | None = None) -> list[FileRecord]:
        query = "SELECT * FROM files WHERE 1=1"
        args: list[str] = []
        if status is not None:
            query += " AND status=?"
            args.append(status)
        if prefix is not None:
            query += " AND rel_path LIKE ? ESCAPE '!'"
            escaped = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            args.append(escaped + "%")
        query += " ORDER BY rel_path"
        return [_file_from_row(row) for row in self._db.execute(query, args)]

    def parents_of(self, rel_path: str) -> list[str]:
        rows = self._db.execute(
            "SELECT parent_path FROM file_parents WHERE child_path=? ORDER BY parent_path", (rel_path,)
        )
        return [row["parent_path"] for row in rows]

    def descendants_of(self, rel_path: str) -> list[FileRecord]:
        """Return every file built from this one, directly or indirectly, present or not."""
        rows = self._db.execute(
            """WITH RECURSIVE below(path) AS (
                 SELECT child_path FROM file_parents WHERE parent_path=?
                 UNION
                 SELECT p.child_path FROM file_parents p JOIN below b ON p.parent_path=b.path
               )
               SELECT f.* FROM files f JOIN below b ON f.rel_path=b.path ORDER BY f.rel_path""",
            (rel_path,),
        )
        return [_file_from_row(row) for row in rows]

    def ancestors_of(self, rel_path: str) -> list[FileRecord]:
        rows = self._db.execute(
            """WITH RECURSIVE above(path) AS (
                 SELECT parent_path FROM file_parents WHERE child_path=?
                 UNION
                 SELECT p.parent_path FROM file_parents p JOIN above a ON p.child_path=a.path
               )
               SELECT f.* FROM files f JOIN above a ON f.rel_path=a.path ORDER BY f.rel_path""",
            (rel_path,),
        )
        return [_file_from_row(row) for row in rows]

    def set_file_status(self, rel_path: str, status: str, at: str) -> None:
        with self._db:
            self._db.execute("UPDATE files SET status=?, gone_at=? WHERE rel_path=?", (status, at, rel_path))

    # ---- tasks -----------------------------------------------------------------------------------------

    def get_task(self, task_key: str) -> TaskRecord | None:
        row = self._db.execute("SELECT * FROM tasks WHERE task_key=?", (task_key,)).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_key=row["task_key"],
            dataset_id=row["dataset_id"],
            symbol=row["symbol"],
            partition_key=row["partition_key"],
            state=row["state"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            last_attempt_at=row["last_attempt_at"],
            next_retry_at=row["next_retry_at"],
        )

    def set_task(
        self,
        task_key: str,
        *,
        dataset_id: str,
        symbol: str,
        partition_key: str,
        state: str,
        now: str,
        attempts: int | None = None,
        last_error: str | None = None,
        next_retry_at: str | None = None,
    ) -> None:
        current = self.get_task(task_key)
        count = attempts if attempts is not None else (current.attempts if current else 0)
        with self._db:
            self._db.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_key, dataset_id, symbol, partition_key, state, attempts, last_error,
                    last_attempt_at, next_retry_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_key,
                    dataset_id,
                    symbol,
                    partition_key,
                    state,
                    count,
                    last_error,
                    now,
                    next_retry_at,
                    now,
                ),
            )

    def task_states(self, dataset_id: str, symbol: str) -> dict[str, str]:
        rows = self._db.execute(
            "SELECT partition_key, state FROM tasks WHERE dataset_id=? AND symbol=?",
            (dataset_id, symbol),
        )
        return {row["partition_key"]: row["state"] for row in rows}

    def tasks_in_state(self, state: str) -> list[TaskRecord]:
        rows = self._db.execute(
            "SELECT task_key FROM tasks WHERE state=? ORDER BY task_key", (state,)
        ).fetchall()
        found = [self.get_task(row["task_key"]) for row in rows]
        return [task for task in found if task is not None]

    # ---- runs ------------------------------------------------------------------------------------------

    def start_run(self, run_id: str, kind: str, *, now: str, code_version: str, config_hash: str) -> None:
        with self._db:
            self._db.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, kind, started_at, status, code_version, config_hash)
                   VALUES (?,?,?,?,?,?)""",
                (run_id, kind, now, "running", code_version, config_hash),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        now: str,
        status: str,
        summary: dict[str, Any] | None = None,
        data_manifest: list[Any] | None = None,
        published: bool = False,
    ) -> None:
        with self._db:
            self._db.execute(
                """UPDATE runs SET finished_at=?, status=?, summary=?, data_manifest=?, published=?
                   WHERE run_id=?""",
                (
                    now,
                    status,
                    None if summary is None else json.dumps(summary, sort_keys=True),
                    None if data_manifest is None else json.dumps(data_manifest),
                    int(published),
                    run_id,
                ),
            )

    def last_runs(self, limit_per_kind: int = 1) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        kinds = [row["kind"] for row in self._db.execute("SELECT DISTINCT kind FROM runs")]
        for kind in sorted(kinds):
            rows = self._db.execute(
                "SELECT * FROM runs WHERE kind=? ORDER BY started_at DESC LIMIT ?",
                (kind, limit_per_kind),
            )
            output[kind] = [dict(row) for row in rows]
        return output

    def last_success(self, kind: str) -> str | None:
        row = self._db.execute(
            """SELECT finished_at FROM runs WHERE kind=? AND status IN ('ok','partial')
               AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1""",
            (kind,),
        ).fetchone()
        return None if row is None else str(row["finished_at"])

    def published_runs_depending_on(self, rel_path: str) -> list[str]:
        rows = self._db.execute(
            "SELECT run_id, data_manifest FROM runs WHERE published=1 AND data_manifest IS NOT NULL"
        )
        return [
            row["run_id"]
            for row in rows
            if any(_manifest_path(entry) == rel_path for entry in json.loads(row["data_manifest"]))
        ]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return None if row is None else dict(row)

    # ---- deletions, gaps, disk -------------------------------------------------------------------------

    def record_deletion(
        self,
        *,
        deleted_at: str,
        rel_path: str,
        size_bytes: int,
        sha256: str,
        rule_id: str,
        data_class: str,
        code_version: str,
        run_id: str | None,
    ) -> None:
        with self._db:
            self._db.execute(
                """INSERT INTO deletions
                   (deleted_at, rel_path, size_bytes, sha256, rule_id, data_class, code_version, run_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (deleted_at, rel_path, size_bytes, sha256, rule_id, data_class, code_version, run_id),
            )
            self._db.execute(
                "UPDATE files SET status='deleted', gone_at=? WHERE rel_path=?", (deleted_at, rel_path)
            )

    def deletions_since(self, moment: str) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM deletions WHERE deleted_at>=? ORDER BY id", (moment,))
        return [dict(row) for row in rows]

    def add_gap(
        self,
        dataset_id: str,
        start_time: str,
        end_time: str,
        reason: str,
        *,
        now: str,
        run_id: str | None,
    ) -> None:
        with self._db:
            self._db.execute(
                """INSERT OR IGNORE INTO gaps
                   (dataset_id, start_time, end_time, reason, detected_at, run_id)
                   VALUES (?,?,?,?,?,?)""",
                (dataset_id, start_time, end_time, reason, now, run_id),
            )

    def gaps(self, dataset_id: str | None = None) -> list[dict[str, Any]]:
        if dataset_id is None:
            rows = self._db.execute("SELECT * FROM gaps ORDER BY start_time")
        else:
            rows = self._db.execute(
                "SELECT * FROM gaps WHERE dataset_id=? ORDER BY start_time", (dataset_id,)
            )
        return [dict(row) for row in rows]

    def add_disk_snapshot(self, taken_at: str, sizes: dict[str, int]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO disk_snapshots (taken_at, zone, bytes) VALUES (?,?,?)",
                [(taken_at, zone, size) for zone, size in sizes.items()],
            )

    def disk_history(self, zone: str, since: str) -> list[tuple[str, int]]:
        rows = self._db.execute(
            "SELECT taken_at, bytes FROM disk_snapshots WHERE zone=? AND taken_at>=? ORDER BY taken_at",
            (zone, since),
        )
        return [(row["taken_at"], row["bytes"]) for row in rows]

    # ---- reconciliations -------------------------------------------------------------------------------

    def put_reconciliation(
        self,
        check_name: str,
        venue: str,
        symbol: str,
        date: str,
        status: str,
        detail: dict[str, Any],
        *,
        now: str,
    ) -> None:
        with self._db:
            text = json.dumps(detail, sort_keys=True)
            self._db.execute(
                """INSERT OR REPLACE INTO reconciliations
                   (check_name, venue, symbol, date, status, detail, checked_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (check_name, venue, symbol, date, status, text, now),
            )
            # The latest result replaces the row above, so the evidence of a past failure is kept here.
            self._db.execute(
                """INSERT INTO reconciliation_history
                   (check_name, venue, symbol, date, status, detail, checked_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (check_name, venue, symbol, date, status, text, now),
            )

    def get_reconciliation(
        self, check_name: str, venue: str, symbol: str, date: str
    ) -> dict[str, Any] | None:
        row = self._db.execute(
            """SELECT * FROM reconciliations
               WHERE check_name=? AND venue=? AND symbol=? AND date=?""",
            (check_name, venue, symbol, date),
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["detail"] = json.loads(item["detail"])
        return item

    def reconciliation_history(self, venue: str, symbol: str, date: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """SELECT * FROM reconciliation_history
               WHERE venue=? AND symbol=? AND date=? ORDER BY id""",
            (venue, symbol, date),
        )
        return [dict(row) for row in rows]

    def add_exclusion(
        self,
        venue: str,
        symbol: str,
        date: str,
        reason: str,
        window_ms: float | None,
        *,
        now: str,
        fault_day: str | None = None,
    ) -> bool:
        """Record a day left out of results. Return whether this reason is new for that day."""
        with self._db:
            cursor = self._db.execute(
                """INSERT OR IGNORE INTO exclusions
                   (venue, symbol, date, reason, boundary_window_ms, excluded_at, fault_day)
                   VALUES (?,?,?,?,?,?,?)""",
                (venue, symbol, date, reason, window_ms, now, fault_day),
            )
            self._db.execute(
                "UPDATE exclusions SET resolved_at=NULL WHERE venue=? AND symbol=? AND date=? AND reason=?",
                (venue, symbol, date, reason),
            )
        return cursor.rowcount > 0

    def add_allowance_event(
        self, venue: str, symbol: str, date: str, needed_ms: float, allowance_ms: float, *, now: str
    ) -> bool:
        """A row ran longer than the declared allowance. Return whether this day is new."""
        with self._db:
            cursor = self._db.execute(
                """INSERT OR IGNORE INTO allowance_events
                   (venue, symbol, date, needed_ms, allowance_ms, found_at)
                   VALUES (?,?,?,?,?,?)""",
                (venue, symbol, date, needed_ms, allowance_ms, now),
            )
        return cursor.rowcount > 0

    def allowance_events(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._db.execute("SELECT * FROM allowance_events ORDER BY date, id")]

    def resolve_exclusions(self, venue: str, symbol: str, date: str, *, now: str) -> None:
        """A later good file settled it. The record of the exclusion stays, marked as resolved."""
        with self._db:
            self._db.execute(
                """UPDATE exclusions SET resolved_at=?
                   WHERE venue=? AND symbol=? AND date=? AND resolved_at IS NULL""",
                (now, venue, symbol, date),
            )

    def exclusions(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM exclusions"
        if active_only:
            query += " WHERE resolved_at IS NULL"
        return [dict(row) for row in self._db.execute(query + " ORDER BY date, venue, symbol, id")]

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def holds_generated_data(self) -> bool:
        """Whether this catalog says its root holds generated data, whatever files sit beside it."""
        stored = self.get_meta("data_kind") == "SYNTHETIC"
        return stored or any(venue.startswith("synthetic") for venue in self.dataset_venues())

    def dataset_venues(self) -> set[str]:
        rows = self._db.execute("SELECT DISTINCT venue FROM datasets WHERE venue IS NOT NULL")
        return {str(row["venue"]) for row in rows}

    def reconciliations(self, check_name: str | None = None) -> list[dict[str, Any]]:
        if check_name is None:
            rows = self._db.execute("SELECT * FROM reconciliations ORDER BY date, venue, symbol")
        else:
            rows = self._db.execute(
                "SELECT * FROM reconciliations WHERE check_name=? ORDER BY date, venue, symbol",
                (check_name,),
            )
        output = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"])
            output.append(item)
        return output

    # ---- poll state ------------------------------------------------------------------------------------

    def get_poll_state(self, symbol: str) -> PollState | None:
        row = self._db.execute("SELECT * FROM poll_state WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            return None
        return PollState(
            symbol=row["symbol"],
            cursor_ns=int(row["cursor_ns"]),
            last_trade_id=row["last_trade_id"],
            emitted_end_us=row["emitted_end_us"],
            last_trade_us=row["last_trade_us"],
            rebuilding=bool(row["rebuilding"]),
        )

    def set_poll_state(self, state: PollState, *, now: str) -> None:
        with self._db:
            self._db.execute(
                """INSERT OR REPLACE INTO poll_state
                   (symbol, cursor_ns, last_trade_id, emitted_end_us, last_trade_us, rebuilding, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    state.symbol,
                    str(state.cursor_ns),
                    state.last_trade_id,
                    state.emitted_end_us,
                    state.last_trade_us,
                    int(state.rebuilding),
                    now,
                ),
            )
