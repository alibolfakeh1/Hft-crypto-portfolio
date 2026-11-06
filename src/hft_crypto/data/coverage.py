"""The coverage check: counts over dates nobody may read yet, in a root of their own.

Under section 3 of the fold plan a check may use values inside itself, as long as only names, sizes,
checksums, counts and flags leave it. One scheduled report over these dates would read the locked block, and
that cannot be undone (leak recheck, FP-01). So these files never enter DATA_ROOT. This follows section 5 of
the coverage record.

- `CHECK_ROOT` is new and empty each run, and outside the repository and DATA_ROOT. It holds `ROOT_KIND`, the
  raw files of one frozen list, and one output file, and it has no curated, features, results, ledger or
  decisions zone.
- `DataRoot` refuses a folder holding `ROOT_KIND`, so `MarketReader`, the report and bar building cannot open
  it. The date guard of each of those also holds, because a root can lose a marker.
- What leaves is `coverage/coverage_check.json`, which `check_output` holds to exact keys and types. There is
  no float in it, no free text, and nothing per hour, day or month. An error is a fixed code, and never text
  from a row.
- The file list is frozen in code and cannot be widened by a flag. Whether the job may run at all is for
  `project-manager` and `leak-auditor`. No workflow starts it, and with no enabled source the client refuses
  every host.

On candles, a row with zero trades is proof of an empty minute (leak recheck, ruling 7 condition 4), so an
unproved empty minute is a missing row. Trades per hour stay inside the check, as the plan says, and only pass
or fail leaves it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.candle_check import (
    CODES,
    FAIL,
    INCONCLUSIVE,
    PASS,
    DayVerdict,
    check_candle_day,
    condition_2_shown,
    declared_sample_days,
)
from hft_crypto.bars.core import candle_row_faults
from hft_crypto.config import ConfigError, PipelineConfig
from hft_crypto.data.atomic import sha256_file
from hft_crypto.data.fetch import (
    REASON_CONNECTION,
    REASON_HTTP_403,
    REASON_HTTP_429,
    REASON_HTTP_451,
    REASON_NOT_FOUND,
    REASON_SIZE_LIMIT,
    REASON_TIMEOUT,
    Fetcher,
    FetchError,
    NotPublishedError,
)
from hft_crypto.data.parsers import (
    ValidationError,
    parse_agg_trades,
    parse_checksum_sidecar,
    parse_klines,
)
from hft_crypto.data.sources import ArchiveFile, archive_candidates, monthly_candle_file
from hft_crypto.data.zones import (
    CANDLE_CHECK_OUTPUT,
    COVERAGE_OUTPUT,
    ROOT_KIND,
    DataRootError,
    refuse_inside_repository,
)
from hft_crypto.timeutil import iso, month_starts, next_month
from hft_crypto.versioning import code_version

CHECK_NAME = "coverage-check-v1"
CHECK_ROOT_VARIABLE = "CHECK_ROOT"
# Coverage record, section 5. Each list is frozen here, so no flag can reach a month outside it.
FROZEN_LISTS = {
    "closed-dates": (dt.date(2024, 1, 1), dt.date(2026, 9, 1)),
    "first-span": (dt.date(2020, 1, 1), dt.date(2023, 12, 1)),
}
# Fold plan section 2. These are the figures of GATE_SPEC.md 8.2.
MAX_UNPROVED_EMPTY_SHARE = 0.01
MIN_BUSY_HOUR_SHARE = 0.90
BUSY_HOUR_TRADES = 100
MINUTES_PER_DAY = 1440
HOURS_PER_DAY = 24
MAX_SIDECAR_BYTES = 4096
# Coverage record, section 4.2: one connection, at least this long between requests.
MIN_REQUEST_GAP_S = 2.0

TOP_LEVEL_TYPES: dict[str, type] = {
    "check": str,
    "code_version": str,
    "run_at": str,
    "file_list_sha256": str,
    "stopped": str,
    "stop_reason": str,
    "quarters": list,
}
QUARTER_TYPES: dict[str, type] = {
    "quarter": str,
    "symbol": str,
    "files": int,
    "files_checksum_ok": int,
    "rows": int,
    "empty_minutes_unproved": int,
    "empty_minutes_proved": int,
    "row_checks_pass": bool,
    "passes": bool,
}
CANDLE_CHECK_NAME = "candle-check-v1"
SAMPLE_DAY_OF_MONTH = 15
CANDLE_TOP_LEVEL_TYPES: dict[str, type] = {
    "check": str,
    "code_version": str,
    "run_at": str,
    "days_sha256": str,
    "stopped": str,
    "days": list,
    "symbols": list,
}
CANDLE_DAY_TYPES: dict[str, type] = {"day": str, "symbol": str, "result": str, "code": str}
CANDLE_SYMBOL_TYPES: dict[str, type] = {
    "symbol": str,
    "days_pass": int,
    "days_fail": int,
    "days_inconclusive": int,
    "shown": bool,
}
CODE_FILE_MISSING = "file_missing"
CODE_FILE_UNREADABLE = "file_unreadable"
CANDLE_RUN_CODES = CODES | {CODE_FILE_MISSING, CODE_FILE_UNREADABLE}
# Fixed codes only. Exception text can carry a row, and plan section 3 counts a log as a read.
STOP_NONE = "none"
STOP_FETCH_REFUSED = "fetch_refused"
# RA-02: the only words `stopped` may hold. A run that stopped decides nothing: it is not the plan's
# application, its output holds no quarter, day or symbol to be read as a result, and it is rerun in a new
# root.
STOP_WORDS = frozenset({STOP_NONE, STOP_FETCH_REFUSED})
# Leak recheck 17.6: a `fetch_refused` stop says why in one of these words, so a block can be told from an
# outage. Each is about the host or the transfer and none about the market. A run that did not stop says none.
REASON_CHECKSUM_MISMATCH = "checksum_mismatch"
STOP_REASONS = frozenset(
    {
        REASON_HTTP_403,
        REASON_HTTP_451,
        REASON_HTTP_429,
        REASON_TIMEOUT,
        REASON_CONNECTION,
        REASON_SIZE_LIMIT,
        REASON_NOT_FOUND,
        REASON_CHECKSUM_MISMATCH,
    }
)


def _check_stopped(document: dict[str, Any], what: str, results: tuple[str, ...]) -> None:
    if document["stopped"] not in STOP_WORDS:
        raise ValidationError(f"{what}: stopped holds a word off the list")
    if document["stopped"] != STOP_NONE and any(document[key] for key in results):
        raise ValidationError(f"{what}: a stopped run decides nothing, so it holds no result")


def _check_stop_reason(document: dict[str, Any], what: str) -> None:
    """`none` exactly when the run did not stop, and one word of `STOP_REASONS` when it did."""
    if document["stopped"] == STOP_NONE:
        if document["stop_reason"] != STOP_NONE:
            raise ValidationError(f"{what}: stop_reason holds a word off the list")
    elif document["stop_reason"] not in STOP_REASONS:
        raise ValidationError(f"{what}: stop_reason holds a word off the list")


def init_check_root(path: str | Path, *, data_root: str | None = None) -> Path:
    """A new, empty root for one run of the check. It can never be a root that holds anything else."""
    target = Path(path).resolve()
    refuse_inside_repository(target)
    if target.exists() and any(target.iterdir()):
        raise DataRootError("CHECK_ROOT must be new and empty on each run")
    other = data_root if data_root is not None else os.environ.get("DATA_ROOT")
    if other:
        named = Path(other).resolve()
        if target == named or named in target.parents or target in named.parents:
            raise DataRootError("CHECK_ROOT and DATA_ROOT must not hold one another")
    target.mkdir(parents=True, exist_ok=True)
    (target / ROOT_KIND).write_text("check-only\n", encoding="utf-8")
    return target


def check_output(document: dict[str, Any]) -> None:
    """Exact keys and exact types, and no float anywhere. Refusals name a key, never a value."""
    if set(document) != set(TOP_LEVEL_TYPES):
        raise ValidationError("coverage output has the wrong keys")
    for key, kind in TOP_LEVEL_TYPES.items():
        if type(document[key]) is not kind:
            raise ValidationError(f"coverage output: {key} has the wrong type")
    _check_stopped(document, "coverage output", ("quarters",))
    _check_stop_reason(document, "coverage output")
    for row in document["quarters"]:
        if set(row) != set(QUARTER_TYPES):
            raise ValidationError("coverage output: a quarter has the wrong keys")
        for key, kind in QUARTER_TYPES.items():
            if type(row[key]) is not kind:
                raise ValidationError(f"coverage output: {key} has the wrong type")


def frozen_file_list(
    config: PipelineConfig, venue: str, list_name: str
) -> list[tuple[dt.date, str, ArchiveFile]]:
    """The files of one frozen list, from the calendar alone, with no listing and no date ending at today."""
    if list_name not in FROZEN_LISTS:
        raise ConfigError(f"no frozen file list called {list_name}")
    first, last = FROZEN_LISTS[list_name]
    return [
        (month, symbol, monthly_candle_file(config, venue, symbol, month))
        for month in month_starts(first, last)
        for symbol in config.symbols
    ]


def file_list_sha256(files: list[tuple[dt.date, str, ArchiveFile]]) -> str:
    names = "\n".join(item[2].filename for item in files)
    return hashlib.sha256(names.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _FileCounts:
    """What one month of candles gives. Only `rows` and the empty minutes are ever summed into what leaves."""

    rows: int
    expected_rows: int
    proved: int
    unproved: int
    faults: int
    busy_hours: int
    hours: int


def _count_candles(raw: Path, symbol: str, month: dt.date, limit: int, venue: str) -> _FileCounts:
    """Reads the zip into memory, and nothing is unzipped to disk. Its values go no further than this
    function."""
    last_day = next_month(month) - dt.timedelta(days=1)
    frame = parse_klines(raw, symbol, month, limit, venue=venue, allowance_us=0, last_day=last_day).frame
    days = (last_day - month).days + 1
    expected = days * MINUTES_PER_DAY
    hourly = frame.group_by(pl.col("open_time").dt.truncate("1h")).agg(pl.col("trade_count").sum().alias("n"))
    return _FileCounts(
        rows=frame.height,
        expected_rows=expected,
        proved=frame.filter(pl.col("trade_count") == 0).height,
        unproved=max(0, expected - frame.height),
        faults=int(candle_row_faults(frame).sum()),
        busy_hours=hourly.filter(pl.col("n") >= BUSY_HOUR_TRADES).height,
        hours=days * HOURS_PER_DAY,
    )


def _quarter_of(month: dt.date) -> str:
    return f"{month.year}-Q{(month.month - 1) // 3 + 1}"


@dataclass
class _Quarter:
    files: int = 0
    checksums_ok: int = 0
    parsed: int = 0
    rows: int = 0
    expected_rows: int = 0
    proved: int = 0
    unproved: int = 0
    faults: int = 0
    busy_hours: int = 0
    hours: int = 0

    def add(self, counts: _FileCounts) -> None:
        self.parsed += 1
        self.rows += counts.rows
        self.expected_rows += counts.expected_rows
        self.proved += counts.proved
        self.unproved += counts.unproved
        self.faults += counts.faults
        self.busy_hours += counts.busy_hours
        self.hours += counts.hours

    def row_checks_pass(self) -> bool:
        return self.files > 0 and self.parsed == self.files and self.faults == 0

    def passes(self) -> bool:
        """Plan section 2: every month here and readable, unproved empty minutes under 1%, and 90% of hours
        busy."""
        if self.parsed != 3 or self.checksums_ok != 3:
            return False
        return (
            self.unproved < MAX_UNPROVED_EMPTY_SHARE * self.expected_rows
            and self.busy_hours >= MIN_BUSY_HOUR_SHARE * self.hours
        )


def declared_days(text: str) -> tuple[dt.date, ...]:
    """The days for `candle-check`: the word `declared`, or named days. Only 15ths, because the sample comes
    from the calendar with no replacements (coverage record, section 6). A day picked from anything else would
    be a selection."""
    if text == "declared":
        return declared_sample_days()
    try:
        days = tuple(dt.date.fromisoformat(item.strip()) for item in text.split(","))
    except ValueError as exc:
        raise ConfigError("name the days as dates, separated by commas, or say declared") from exc
    if len(set(days)) != len(days):
        raise ConfigError("the same day was named twice")
    if any(day.day != SAMPLE_DAY_OF_MONTH for day in days):
        raise ConfigError("sample days are the 15th of a month, and only those")
    return days


def check_candle_output(document: dict[str, Any]) -> None:
    """Exact keys and exact types, no float, and only fixed words. Refusals name a key, never a value."""
    if set(document) != set(CANDLE_TOP_LEVEL_TYPES):
        raise ValidationError("candle check output has the wrong keys")
    for key, kind in CANDLE_TOP_LEVEL_TYPES.items():
        if type(document[key]) is not kind:
            raise ValidationError(f"candle check output: {key} has the wrong type")
    _check_stopped(document, "candle check output", ("days", "symbols"))
    for row in document["days"]:
        if set(row) != set(CANDLE_DAY_TYPES):
            raise ValidationError("candle check output: a day has the wrong keys")
        for key, kind in CANDLE_DAY_TYPES.items():
            if type(row[key]) is not kind:
                raise ValidationError(f"candle check output: {key} has the wrong type")
        if row["result"] not in (PASS, FAIL, INCONCLUSIVE) or row["code"] not in CANDLE_RUN_CODES:
            raise ValidationError("candle check output: a day holds a word off the list")
    for row in document["symbols"]:
        if set(row) != set(CANDLE_SYMBOL_TYPES):
            raise ValidationError("candle check output: a symbol has the wrong keys")
        for key, kind in CANDLE_SYMBOL_TYPES.items():
            if type(row[key]) is not kind:
                raise ValidationError(f"candle check output: {key} has the wrong type")


def _fetch_one(
    fetcher: Fetcher, target: ArchiveFile, raw: Path, max_bytes: int, sleep: Callable[[float], None]
) -> bool:
    """Sidecar, then zip, as section 4.2 says. Says whether the zip matches its sidecar."""
    raw.parent.mkdir(parents=True, exist_ok=True)
    sidecar = b""
    if target.checksum_url is not None:
        sidecar = fetcher.get_bytes(target.checksum_url, MAX_SIDECAR_BYTES)
        raw.with_name(f"{raw.name}.CHECKSUM").write_bytes(sidecar)
        sleep(MIN_REQUEST_GAP_S)
    fetcher.download(target.url, raw, max_bytes)
    sleep(MIN_REQUEST_GAP_S)
    try:
        return parse_checksum_sidecar(sidecar.decode("utf-8"), target.filename) == sha256_file(raw)
    except (ValidationError, UnicodeDecodeError):
        return False


def run_coverage_check(
    check_root: Path,
    config: PipelineConfig,
    fetcher: Fetcher,
    *,
    venue: str,
    list_name: str,
    now: Callable[[], dt.datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch one frozen list into a check root, count it, write the one output file, and end.

    The raw files stay where they are and leave with the runner, because a deletion here would need its own
    review (coverage record, section 5). The output decides coverage and storage only (FP-08).
    """
    if not (check_root / ROOT_KIND).is_file():
        raise DataRootError("the coverage check runs only in a root that says it is check-only")
    if not config.source_usable(venue):
        raise ConfigError(f"source {venue} is not approved and enabled, so the coverage check does not run")
    files = frozen_file_list(config, venue, list_name)
    limit = config.fetch.max_uncompressed_bytes
    max_bytes = config.fetch.max_download_bytes
    quarters: dict[tuple[str, str], _Quarter] = {
        (_quarter_of(month), symbol): _Quarter() for month, symbol, _ in files
    }
    stopped = STOP_NONE
    stop_reason = STOP_NONE
    for month, symbol, target in files:
        quarter = quarters[(_quarter_of(month), symbol)]
        raw = check_root / "raw" / "archive" / venue / "klines" / symbol / f"date={month}" / target.filename
        try:
            matches = _fetch_one(fetcher, target, raw, max_bytes, sleep)
        except FetchError as error:
            # Section 4.2: stop on a refusal, and do not retry around it. Leak recheck 17.6: a 404 stops
            # too, since every file of a frozen list was in the coverage record's listing, so a 404 now is an
            # outage and not a gap in the archive. Failing its quarter instead would lose it for good,
            # because the plan applies once. `NotPublishedError` is a `FetchError` whose word is `not_found`.
            stopped, stop_reason = STOP_FETCH_REFUSED, error.reason
            break
        if not matches:
            # Leak recheck 17.6: a transfer error is transient, so a mismatch stops the run, and the rerun
            # rule applies. A sidecar that cannot be read is the same. A mismatch that repeats is then a
            # coverage fact.
            stopped, stop_reason = STOP_FETCH_REFUSED, REASON_CHECKSUM_MISMATCH
            break
        quarter.files += 1
        quarter.checksums_ok += 1
        try:
            quarter.add(_count_candles(raw, symbol, month, limit, venue))
        except Exception:  # noqa: S112
            # A file that cannot be read fails its quarter. Why stays here, whatever raised it, because the
            # text can quote a row, and a log counts as a read. The failed flag is what someone then looks
            # into.
            continue
    document: dict[str, Any] = {
        "check": CHECK_NAME,
        "code_version": code_version(),
        "run_at": iso(now()),
        "file_list_sha256": file_list_sha256(files),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "quarters": [
            {
                "quarter": name,
                "symbol": symbol,
                "files": quarter.files,
                "files_checksum_ok": quarter.checksums_ok,
                "rows": quarter.rows,
                "empty_minutes_unproved": quarter.unproved,
                "empty_minutes_proved": quarter.proved,
                "row_checks_pass": quarter.row_checks_pass(),
                "passes": quarter.passes(),
            }
            for (name, symbol), quarter in sorted(quarters.items())
            if stopped == STOP_NONE
        ],
    }
    check_output(document)
    output = check_root / COVERAGE_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def _candle_month(
    config: PipelineConfig,
    fetcher: Fetcher,
    check_root: Path,
    venue: str,
    symbol: str,
    day: dt.date,
    held: dict[tuple[str, dt.date], pl.DataFrame | None],
    sleep: Callable[[float], None],
) -> pl.DataFrame | None:
    """One month of candles, fetched once for all its sample days. The files the first run reads, so the test
    covers them."""
    month = day.replace(day=1)
    if (symbol, month) in held:
        return held[(symbol, month)]
    target = monthly_candle_file(config, venue, symbol, month)
    raw = _raw_path(check_root, venue, "klines", symbol, month, target.filename)
    frame: pl.DataFrame | None = None
    if _fetch_one(fetcher, target, raw, config.fetch.max_download_bytes, sleep):
        last_day = next_month(month) - dt.timedelta(days=1)
        limit = config.fetch.max_uncompressed_bytes
        frame = parse_klines(raw, symbol, month, limit, venue=venue, allowance_us=0, last_day=last_day).frame
    held[(symbol, month)] = frame
    return frame


def _trade_rows(
    config: PipelineConfig,
    fetcher: Fetcher,
    check_root: Path,
    venue: str,
    symbol: str,
    day: dt.date,
    sleep: Callable[[float], None],
) -> pl.DataFrame | None:
    """One day's aggregate rows, read into memory from the zip. No trades are curated, and no bars are
    built."""
    spec = next(item for item in config.datasets if item.venue == venue and item.kind == "aggTrades")
    target = archive_candidates(config, spec, symbol, day)[0]
    raw = _raw_path(check_root, venue, "aggTrades", symbol, day, target.filename)
    if not _fetch_one(fetcher, target, raw, config.fetch.max_download_bytes, sleep):
        return None
    limit = config.fetch.max_uncompressed_bytes
    return parse_agg_trades(raw, symbol, day, limit, venue=venue, allowance_us=0).frame


def _raw_path(check_root: Path, venue: str, kind: str, symbol: str, day: dt.date, name: str) -> Path:
    return check_root / "raw" / "archive" / venue / kind / symbol / f"date={day}" / name


def _check_one_day(
    config: PipelineConfig,
    fetcher: Fetcher,
    check_root: Path,
    venue: str,
    symbol: str,
    day: dt.date,
    held: dict[tuple[str, dt.date], pl.DataFrame | None],
    sleep: Callable[[float], None],
) -> DayVerdict:
    """A file that cannot be had or read drops its day, by name, and nothing takes its place. Why stays
    here."""
    try:
        previous = _trade_rows(config, fetcher, check_root, venue, symbol, day - dt.timedelta(days=1), sleep)
        rows = _trade_rows(config, fetcher, check_root, venue, symbol, day, sleep)
        candles = _candle_month(config, fetcher, check_root, venue, symbol, day, held, sleep)
    except NotPublishedError:
        return DayVerdict(INCONCLUSIVE, CODE_FILE_MISSING)
    except FetchError:
        raise
    except Exception:
        # The text of a parsing error can quote a row, and a log counts as a read.
        return DayVerdict(INCONCLUSIVE, CODE_FILE_UNREADABLE)
    if rows is None or previous is None or candles is None:
        return DayVerdict(INCONCLUSIVE, CODE_FILE_UNREADABLE)
    return check_candle_day(rows, candles, previous, day)


def run_candle_check(
    check_root: Path,
    config: PipelineConfig,
    fetcher: Fetcher,
    *,
    venue: str,
    days: Sequence[dt.date],
    now: Callable[[], dt.datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Condition 2 of ruling 7, on declared sample days, in a check root. It needs no outcome, and only flags
    leave.

    It writes `coverage/candle_check.json` and sets nothing. `candle_check` in the configuration stays as it
    is until someone with the evidence changes it. If the condition is not shown, IDEAL is not reported and
    nothing else stops. A changed form after a failure is a new dated decision, and it does not rerun quietly.
    """
    if not (check_root / ROOT_KIND).is_file():
        raise DataRootError("the candle check runs only in a root that says it is check-only")
    if not config.source_usable(venue):
        raise ConfigError(f"source {venue} is not approved and enabled, so the candle check does not run")
    results: dict[str, list[tuple[dt.date, DayVerdict]]] = {symbol: [] for symbol in config.symbols}
    held: dict[tuple[str, dt.date], pl.DataFrame | None] = {}
    stopped = STOP_NONE
    for day in sorted(days):
        for symbol in config.symbols:
            try:
                verdict = _check_one_day(config, fetcher, check_root, venue, symbol, day, held, sleep)
            except FetchError:
                # Section 4.2 of the coverage record: stop on a refusal, and do not retry around it.
                stopped = STOP_FETCH_REFUSED
                break
            results[symbol].append((day, verdict))
        if stopped != STOP_NONE:
            break
    document: dict[str, Any] = {
        "check": CANDLE_CHECK_NAME,
        "code_version": code_version(),
        "run_at": iso(now()),
        "days_sha256": hashlib.sha256(
            "\n".join(day.isoformat() for day in sorted(days)).encode()
        ).hexdigest(),
        "stopped": stopped,
        "days": [
            {"day": day.isoformat(), "symbol": symbol, "result": verdict.result, "code": verdict.code}
            for symbol, rows in sorted(results.items())
            for day, verdict in rows
            if stopped == STOP_NONE
        ],
        "symbols": [
            {
                "symbol": symbol,
                "days_pass": sum(verdict.result == PASS for _, verdict in rows),
                "days_fail": sum(verdict.result == FAIL for _, verdict in rows),
                "days_inconclusive": sum(verdict.result == INCONCLUSIVE for _, verdict in rows),
                "shown": condition_2_shown([(day, verdict.result) for day, verdict in rows]),
            }
            for symbol, rows in sorted(results.items())
            if stopped == STOP_NONE
        ],
    }
    check_candle_output(document)
    output = check_root / CANDLE_CHECK_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document
