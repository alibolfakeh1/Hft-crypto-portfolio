"""Replay validator for Bybit order book files. It checks the file and builds no features.

The file is streamed from the zip and never extracted, because it holds over a gigabyte of JSON lines and
a runner has little disk. It checks update-id continuity, crossed books on every message, and that a
snapshot in the middle of the file agrees with the book rebuilt up to that point.
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from bisect import bisect_left, insort
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, cast

from hft_crypto.data.parsers import ValidationError


@dataclass
class BookReplayResult:
    lines: int = 0
    snapshots: int = 0
    deltas: int = 0
    update_id_breaks: int = 0
    update_id_resets: int = 0
    seq_regressions: int = 0
    crossed: int = 0
    crossed_checks: int = 0
    empty_side_checks: int = 0
    snapshot_comparisons: int = 0
    snapshot_mismatches: int = 0
    deletes_of_absent_level: int = 0
    depth_topic: str | None = None
    first_ts_ms: int | None = None
    last_ts_ms: int | None = None
    max_levels_per_side: int = 0
    malformed_lines: int = 0
    break_examples: list[dict[str, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.lines > 0
            and self.snapshots > 0
            and self.crossed_checks > 0
            and self.update_id_breaks == 0
            and self.crossed == 0
            and self.snapshot_mismatches == 0
            and self.malformed_lines == 0
        )

    def to_dict(self) -> dict[str, Any]:
        output = asdict(self)
        output["ok"] = self.ok
        return output


class _Side:
    """One side of the book: quantity by price, with a sorted price list for the best price."""

    __slots__ = ("levels", "prices")

    def __init__(self) -> None:
        self.levels: dict[float, float] = {}
        self.prices: list[float] = []

    def clear(self) -> None:
        self.levels = {}
        self.prices = []

    def set(self, price: float, qty: float) -> bool:
        """Apply one level. Return False when a delete names a level that is not there."""
        if qty == 0.0:
            if price not in self.levels:
                return False
            del self.levels[price]
            del self.prices[bisect_left(self.prices, price)]
            return True
        if price not in self.levels:
            insort(self.prices, price)
        self.levels[price] = qty
        return True


def _parse_levels(rows: list[list[str]]) -> list[tuple[float, float]]:
    levels = [(float(price), float(qty)) for price, qty in rows]
    for price, qty in levels:
        if not (math.isfinite(price) and math.isfinite(qty)) or price <= 0 or qty < 0:
            raise ValueError("a level is negative or not a finite number")
    return levels


def replay_stream(stream: BinaryIO) -> BookReplayResult:
    """Replay JSON lines from a binary stream."""
    result = BookReplayResult()
    bids = _Side()
    asks = _Side()
    previous_u: int | None = None
    previous_seq: int | None = None
    for raw_line in stream:
        if not raw_line.strip():
            continue
        result.lines += 1
        try:
            message = json.loads(raw_line)
            kind = message["type"]
            data = message["data"]
            update_id = int(data["u"])
            bid_rows = _parse_levels(data["b"])
            ask_rows = _parse_levels(data["a"])
            seq = int(data["seq"]) if "seq" in data else None
            stamp = int(message["ts"])
        except (ValueError, KeyError, TypeError):
            result.malformed_lines += 1
            continue
        if result.depth_topic is None:
            result.depth_topic = str(message.get("topic"))
        if result.first_ts_ms is None:
            result.first_ts_ms = stamp
        result.last_ts_ms = stamp
        if seq is not None and previous_seq is not None and seq < previous_seq:
            result.seq_regressions += 1
        previous_seq = seq

        if kind == "snapshot":
            result.snapshots += 1
            is_reset = update_id == 1 and previous_u is not None
            if is_reset:
                # A service restart: the counter starts again and a new book replaces the old one.
                result.update_id_resets += 1
            elif previous_u is not None and update_id not in (previous_u, previous_u + 1):
                # A periodic snapshot restates the book at the id of the delta before it, so the same
                # id is continuous, and the comparison below still checks that the book agrees.
                result.update_id_breaks += 1
                _note_break(result, previous_u, update_id)
            # After a restart the new book owes nothing to the old one, so comparing them proves nothing.
            if (bids.levels or asks.levels) and not is_reset:
                result.snapshot_comparisons += 1
                wanted_bids = dict(bid_rows)
                wanted_asks = dict(ask_rows)
                if wanted_bids != bids.levels or wanted_asks != asks.levels:
                    result.snapshot_mismatches += 1
            bids.clear()
            asks.clear()
        elif kind == "delta":
            result.deltas += 1
            if previous_u is not None and update_id != previous_u + 1:
                result.update_id_breaks += 1
                _note_break(result, previous_u, update_id)
        else:
            result.malformed_lines += 1
            continue
        previous_u = update_id

        for price, qty in bid_rows:
            if not bids.set(price, qty):
                result.deletes_of_absent_level += 1
        for price, qty in ask_rows:
            if not asks.set(price, qty):
                result.deletes_of_absent_level += 1

        if bids.prices and asks.prices:
            result.crossed_checks += 1
            if bids.prices[-1] >= asks.prices[0]:
                result.crossed += 1
        else:
            result.empty_side_checks += 1
        depth = max(len(bids.prices), len(asks.prices))
        if depth > result.max_levels_per_side:
            result.max_levels_per_side = depth
    return result


def _note_break(result: BookReplayResult, previous: int, current: int) -> None:
    if len(result.break_examples) < 10:
        result.break_examples.append({"previous_u": previous, "u": current})


def replay_zip(path: str | Path) -> BookReplayResult:
    """Replay a delivered book zip without extracting it."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) != 1:
                raise ValidationError(f"expected one zip member, found {len(members)}")
            with archive.open(members[0]) as raw:
                buffered = io.BufferedReader(cast(Any, raw), buffer_size=1024 * 1024)
                return replay_stream(buffered)
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as exc:
        raise ValidationError(f"unreadable zip: {exc}") from exc
