"""Atomic file writes: temporary name, verify, rename.

A crash at any point leaves either the old file or no file. It can never leave a half-written file under
the final name. Temporary names start with a dot and hold `.tmp-`, and no reader's glob matches them.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.data.guard import PathGuard, is_link

TEMP_MARKER = ".tmp-"
_TEMP_NAME = re.compile(r"^\..*\.tmp-\d+-[0-9a-f]+$")


class VerificationError(Exception):
    """A freshly written file did not pass its check, so it was not published."""


def temp_path_for(target: Path) -> Path:
    return target.with_name(f".{target.name}{TEMP_MARKER}{os.getpid()}-{secrets.token_hex(4)}")


def is_temp_file(path: Path) -> bool:
    return _TEMP_NAME.match(path.name) is not None


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(
    target: str | Path,
    write: Callable[[Path], None],
    *,
    guard: PathGuard,
    verify: Callable[[Path], None] | None = None,
) -> Path:
    """Write through a temporary file in the target's directory, verify it, then rename it."""
    final = guard.check(target)
    final.parent.mkdir(parents=True, exist_ok=True)
    guard.check(final.parent)
    temporary = temp_path_for(final)
    try:
        write(temporary)
        _fsync_file(temporary)
        if verify is not None:
            verify(temporary)
        temporary.replace(final)
        _fsync_dir(final.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return final


def atomic_write_bytes(target: str | Path, data: bytes, *, guard: PathGuard) -> Path:
    expected = hashlib.sha256(data).hexdigest()

    def verify(path: Path) -> None:
        if sha256_file(path) != expected:
            raise VerificationError(f"bytes on disk differ from bytes written: {path.name}")

    def write(path: Path) -> None:
        path.write_bytes(data)

    return atomic_write(target, write, guard=guard, verify=verify)


def canonical_json_bytes(value: Any) -> bytes:
    """Stable, human-readable UTF-8 JSON. Persian text stays readable instead of being escaped."""
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def atomic_write_json(target: str | Path, value: Any, *, guard: PathGuard) -> Path:
    return atomic_write_bytes(target, canonical_json_bytes(value), guard=guard)


def atomic_write_parquet(target: str | Path, frame: pl.DataFrame, *, guard: PathGuard) -> Path:
    """Write Parquet and read it back. The row count and schema must match before it is published."""

    def verify(path: Path) -> None:
        written = read_parquet(path)
        if written.height != frame.height or written.schema != frame.schema:
            raise VerificationError(f"parquet read-back mismatch: {path.name}")

    def write(path: Path) -> None:
        frame.write_parquet(path, compression="zstd", compression_level=6, statistics=True)

    return atomic_write(target, write, guard=guard, verify=verify)


def read_parquet(path: str | Path) -> pl.DataFrame:
    """Read all of a Parquet file with no open handle left behind.

    A memory-mapped read holds the file open, and on Windows that blocks replacing the file later.
    """
    return pl.read_parquet(io.BytesIO(Path(path).read_bytes()), hive_partitioning=False)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_jsonl(path: str | Path, record: dict[str, Any], *, guard: PathGuard) -> None:
    """Append one line and force it to disk. This file is never rewritten."""
    checked = guard.check(path)
    checked.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with checked.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def sweep_temp_files(guard: PathGuard, zones: tuple[str, ...]) -> list[str]:
    """Remove temporary files left by a crash, so they do not count as disk use."""
    removed: list[str] = []
    for zone in zones:
        zone_path = guard.check(zone)
        if not zone_path.is_dir():
            continue
        for current, directories, files in os.walk(zone_path, followlinks=False):
            directories[:] = [d for d in directories if not is_link(Path(current, d))]
            for name in files:
                candidate = Path(current, name)
                if is_temp_file(candidate):
                    guard.unlink(candidate)
                    removed.append(guard.relative(candidate))
    return removed
