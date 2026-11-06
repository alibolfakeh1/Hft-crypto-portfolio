"""Checks on the funding and candle files after the fetch.

Section 3 of docs/reviews/data/venue_facts_2026-11-05.md: F1 to F5 on funding files and K1 to K5 on candle
files, on the first span, in stage one. Each file is checked in `data/ingest.py` right after its checksum,
before anything parses it, and its result joins its manifest entry. `funding_span` and `candle_span` add the
files up at the end of the run. Prices are read as decimals from the file's text and never as binary floats: a
price is on a grid when its text has no non-zero digit past that grid's last place.

**What leaves:** pass or fail, counts, the largest offset in ms, and times of minutes or settlements. Never a
price, a volume, a rate or anything per day. **What stops the run:** a header that is not F1's (F1), an
interval other than 8 hours (F2), a settlement held twice (F4), and a price off the 0.01 grid (K1). The rest
is reported: F3 and F5 fail and are reviewed, a missing settlement stays a `DATA_GAP` under C17, K3 is not a
failure, and K5 decides nothing, which is the coverage check's job.

**The ticks.** K2 to K4 test the tick table in `configs/engine.toml` against the files. The grids are powers
of ten, as both symbols' ticks are, so a grid is a count of decimal places.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from hft_crypto.data.parsers import (
    FUNDING_HEADER,
    KLINES_HEADER,
    ValidationError,
    _read_csv,
    _split_header,
    read_zip_member,
)
from hft_crypto.ticks import TickTable
from hft_crypto.timeutil import day_start_us, iso_us, month_starts, next_month

FUNDING_KIND = "fundingRate"
CANDLE_KIND = "klines"
# The first span, which is the only one these checks are written for (venue facts, section 3).
FIRST_SPAN = (dt.date(2020, 1, 1), dt.date(2023, 12, 1))
EXPECTED_INTERVAL_HOURS = 8
# FAQ S7: "a 15-second deviation in the actual funding fee transaction time".
MAX_OFFSET_MS = 15_000
_HOUR_MS = 3_600_000
_SETTLE_MS = EXPECTED_INTERVAL_HOURS * _HOUR_MS
_MINUTE_MS = 60_000
_PRICES = ("open", "high", "low", "close")
_FINE_PLACES = 2  # K1: 0.01
_COARSE_PLACES = 1  # K2 to K4: 0.1
_NOT_A_PLAIN_DECIMAL = 99

STOP_F1_HEADER = "F1_HEADER"
STOP_F2_INTERVAL = "F2_INTERVAL_NOT_8"
STOP_F4_DUPLICATE = "F4_DUPLICATE_SETTLEMENT"
STOP_K1_OFF_GRID = "K1_PRICE_OFF_0_01"


class VenueCheckStop(ValidationError):
    """A check after the fetch that stops the run. It names a fixed code, and times at most."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}{': ' + detail if detail else ''}")
        self.code = code


def _ms_iso(value: int) -> str:
    return iso_us(value * 1000)


def _month_end_ms(month: dt.date) -> int:
    return day_start_us(next_month(month)) // 1000


def _grid_slots(month: dt.date) -> range:
    """Every 00:00, 08:00 and 16:00 UTC settlement in a month, in ms."""
    start = day_start_us(month) // 1000
    return range(start, _month_end_ms(month), _SETTLE_MS)


# ---- funding, F1 to F5 ------------------------------------------------------------------------------------


def funding_file_facts(raw: Path, month: dt.date, limit: int) -> dict[str, Any]:
    """One month's funding file. A settlement is the whole hour nearest its `calc_time`."""
    data = read_zip_member(raw, limit)
    first_line = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
    if first_line != FUNDING_HEADER:
        return {"header_ok": False}
    text = _read_csv(data, FUNDING_HEADER, True)
    try:
        calc = text["calc_time"].cast(pl.Int64, strict=True).to_numpy()
        hours = text["funding_interval_hours"].cast(pl.Int64, strict=True).to_numpy()
    except pl.exceptions.PolarsError as exc:
        raise ValidationError("a funding time or interval is not a whole number") from exc
    nearest = np.rint(calc / _SETTLE_MS).astype(np.int64) * _SETTLE_MS
    settles = np.rint(calc / _HOUR_MS).astype(np.int64) * _HOUR_MS
    on_grid = settles % _SETTLE_MS == 0
    start, end = day_start_us(month) // 1000, _month_end_ms(month)
    inside = on_grid & (settles >= start) & (settles < end)
    held = settles[inside]
    unique = set(held.tolist())
    return {
        "header_ok": True,
        "rows": int(calc.size),
        "interval_not_8": [
            [_ms_iso(int(when)), int(hour)]
            for when, hour in zip(calc.tolist(), hours.tolist(), strict=True)
            if hour != EXPECTED_INTERVAL_HOURS
        ],
        "max_offset_ms": int(np.abs(calc - nearest).max()) if calc.size else 0,
        "rows_over_15_s": int((np.abs(calc - nearest) > MAX_OFFSET_MS).sum()),
        "duplicates": int(held.size - len(unique)),
        "missing": [_ms_iso(slot) for slot in _grid_slots(month) if slot not in unique],
        "outside_month": sorted(_ms_iso(int(slot)) for slot in settles[on_grid & ~inside].tolist()),
        "off_grid": sorted(_ms_iso(int(slot)) for slot in settles[~on_grid].tolist()),
    }


def funding_stops(facts: Mapping[str, Any]) -> list[str]:
    """The stops one file decides on its own: F1, F2 and a settlement held twice in it."""
    if not facts.get("header_ok"):
        return [STOP_F1_HEADER]
    found = []
    if facts["interval_not_8"]:
        found.append(STOP_F2_INTERVAL)
    if facts["duplicates"]:
        found.append(STOP_F4_DUPLICATE)
    return found


def funding_span(facts: Mapping[dt.date, Mapping[str, Any] | None]) -> dict[str, Any]:
    """F1 to F5 for one symbol over the first span. A month with no file has all its settlements missing."""
    months = list(month_starts(*FIRST_SPAN))
    held = {month: facts.get(month) for month in months}
    present = [item for item in held.values() if item is not None]
    readable = [item for item in present if item.get("header_ok")]
    missing = {slot for item in readable for slot in item["missing"]}
    missing |= {_ms_iso(slot) for month, item in held.items() if item is None for slot in _grid_slots(month)}
    unreadable = [month for month, item in held.items() if item is not None and not item.get("header_ok")]
    missing |= {_ms_iso(slot) for month in unreadable for slot in _grid_slots(month)}
    duplicates = sum(item["duplicates"] for item in readable)
    # A settlement whose row sits in a neighbouring month's file fills that month's gap, or is held twice.
    seen_outside: set[str] = set()
    for item in readable:
        for slot in item["outside_month"]:
            if slot in missing and slot not in seen_outside:
                missing.discard(slot)
            else:
                duplicates += 1
            seen_outside.add(slot)
    expected = sum(len(_grid_slots(month)) for month in months)
    interval_rows = [row for item in readable for row in item["interval_not_8"]]
    off_grid = sorted(slot for item in readable for slot in item["off_grid"])
    max_offset = max((item["max_offset_ms"] for item in readable), default=0)
    return {
        "F1": {"pass": not unreadable, "files_with_another_header": len(unreadable)},
        "F2": {"pass": not interval_rows, "rows": interval_rows},
        "F3": {"pass": max_offset <= MAX_OFFSET_MS, "max_offset_ms": max_offset},
        "F4": {
            "pass": duplicates == 0,
            "expected": expected,
            "missing": len(missing),
            "duplicates": duplicates,
            "files": len(present),
        },
        "F5": {"pass": not off_grid, "other_gaps": len(off_grid), "at": off_grid},
    }


# ---- candles, K1 to K5 ------------------------------------------------------------------------------------


def _places(column: str) -> pl.Expr:
    """Decimal places a price's text needs, after trailing zeros. Anything not a plain decimal is never on a
    grid."""
    text = pl.col(column).str.strip_chars()
    fraction = text.str.extract(r"\.(\d+)$", 1).fill_null("").str.strip_chars_end("0")
    plain = text.str.contains(r"^-?\d+(\.\d+)?$")
    return pl.when(plain).then(fraction.str.len_chars()).otherwise(_NOT_A_PLAIN_DECIMAL).cast(pl.Int64)


def _tick_places(tick: float) -> int:
    places = -math.log10(tick)
    if abs(places - round(places)) > 1e-9:
        raise ValidationError("the checks after the fetch need ticks that are powers of ten")
    return round(places)


def candle_file_facts(raw: Path, month: dt.date, limit: int, ticks: TickTable | None) -> dict[str, Any]:
    """One month's candle file. A minute's tick is the one in force at its open."""
    data = read_zip_member(raw, limit)
    has_header, line = _split_header(data, KLINES_HEADER, 12)
    text = _read_csv(data, line, has_header)
    try:
        opens = text["open_time"].cast(pl.Int64, strict=True).to_numpy()
    except pl.exceptions.PolarsError as exc:
        raise ValidationError("a candle open time is not a whole number") from exc
    places = text.select(pl.max_horizontal(*(_places(name) for name in _PRICES))).to_series().to_numpy()
    start, end = day_start_us(month) // 1000, _month_end_ms(month)
    unique = set(opens.tolist())
    facts: dict[str, Any] = {
        "rows": int(opens.size),
        "duplicate_minutes": int(opens.size - len(unique)),
        "missing_minutes": sum(1 for minute in range(start, end, _MINUTE_MS) if minute not in unique),
        "minutes_off_0_01": int((places > _FINE_PLACES).sum()),
    }
    if ticks is None:
        return facts
    tick_places = np.array(
        [_tick_places(ticks.at(int(when) * 1000)) for when in opens.tolist()], dtype=np.int64
    )
    fine = tick_places == _FINE_PLACES
    coarse = tick_places == _COARSE_PLACES
    off_coarse = places > _COARSE_PLACES
    late = opens[coarse & off_coarse]
    facts.update(
        {
            "minutes_at_0_01": int(fine.sum()),
            "minutes_at_0_01_off_0_1": int((fine & off_coarse).sum()),
            "minutes_at_0_1_off_0_1": int(late.size),
            "first_at_0_1_off_0_1": _ms_iso(int(late.min())) if late.size else None,
            "last_at_0_1_off_0_1": _ms_iso(int(late.max())) if late.size else None,
        }
    )
    return facts


def candle_stops(facts: Mapping[str, Any]) -> list[str]:
    return [STOP_K1_OFF_GRID] if facts["minutes_off_0_01"] else []


def candle_span(facts: Mapping[dt.date, Mapping[str, Any] | None], ticks: TickTable | None) -> dict[str, Any]:
    """K1 to K5 for one symbol over the first span."""
    months = list(month_starts(*FIRST_SPAN))
    present = {month: item for month in months if (item := facts.get(month)) is not None}
    expected = sum((_month_end_ms(month) - day_start_us(month) // 1000) // _MINUTE_MS for month in months)
    absent = [month for month in months if month not in present]
    result: dict[str, Any] = {
        "K1": {
            "pass": not any(item["minutes_off_0_01"] for item in present.values()),
            "minutes": sum(item["minutes_off_0_01"] for item in present.values()),
        },
        "K5": {
            "expected": expected,
            "rows": sum(item["rows"] for item in present.values()),
            "missing": sum(item["missing_minutes"] for item in present.values())
            + sum((_month_end_ms(month) - day_start_us(month) // 1000) // _MINUTE_MS for month in absent),
            "duplicates": sum(item["duplicate_minutes"] for item in present.values()),
        },
    }
    if ticks is None:
        result["K2_K4"] = {"pass": None, "note": "no tick table was given, so the ticks were not tested"}
        return result
    # K2 on a symbol whose tick later becomes coarser, K4 on one with a single tick. Both ask that every month
    # at 0.01 shows a price off the 0.1 grid, or a 0.01 tick is not shown for it.
    at_fine = [month for month, item in present.items() if item["minutes_at_0_01"]]
    shown = [month for month in at_fine if present[month]["minutes_at_0_01_off_0_1"]]
    name = "K2" if any(tick > min(ticks.ticks) for tick in ticks.ticks) else "K4"
    result[name] = {
        "pass": len(shown) == len(at_fine),
        "months_at_0_01": len(at_fine),
        "months_showing_0_01": len(shown),
    }
    if any(_tick_places(tick) == _COARSE_PLACES for tick in ticks.ticks):
        firsts = [item["first_at_0_1_off_0_1"] for item in present.values() if item["first_at_0_1_off_0_1"]]
        lasts = [item["last_at_0_1_off_0_1"] for item in present.values() if item["last_at_0_1_off_0_1"]]
        result["K3"] = {
            "reported_not_failed": True,
            "minutes": sum(item["minutes_at_0_1_off_0_1"] for item in present.values()),
            "first": min(firsts) if firsts else None,
            "last": max(lasts) if lasts else None,
        }
    return result


def file_facts(kind: str, raw: Path, month: dt.date, limit: int, ticks: TickTable | None) -> dict[str, Any]:
    if kind == FUNDING_KIND:
        return funding_file_facts(raw, month, limit)
    return candle_file_facts(raw, month, limit, ticks)


def file_stops(kind: str, facts: Mapping[str, Any]) -> list[str]:
    return funding_stops(facts) if kind == FUNDING_KIND else candle_stops(facts)


def in_first_span(month: dt.date) -> bool:
    return FIRST_SPAN[0] <= month <= FIRST_SPAN[1]
