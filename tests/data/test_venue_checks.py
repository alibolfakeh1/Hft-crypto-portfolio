"""Section 3 of docs/reviews/data/venue_facts_2026-11-05.md: F1 to F5 and K1 to K5, on generated files.

Every file here is generated and every price invented. Each case is worked by hand in its docstring.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from helpers import FakeFetcher, base_config, make_context, with_binance_enabled, zip_bytes
from hft_crypto.config import PipelineConfig
from hft_crypto.data.ingest import IngestOptions, IngestSummary, run_ingest
from hft_crypto.data.sources import archive_candidates
from hft_crypto.data.venue_checks import (
    SPAN_MONTHS,
    STOP_F1_HEADER,
    STOP_F2_INTERVAL,
    STOP_F4_DUPLICATE,
    STOP_K1_OFF_GRID,
    VenueCheckStop,
    candle_file_facts,
    candle_span,
    candle_stops,
    funding_file_facts,
    funding_span,
    funding_stops,
)
from hft_crypto.ticks import TickTable
from hft_crypto.timeutil import day_start_us, next_month, to_us

BTC = "BTCUSDT"
NOW = dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC)
NOV = dt.date(2023, 11, 1)
DEC = dt.date(2023, 12, 1)
HOUR_MS = 3_600_000
LIMIT = 50_000_000
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"
KLINES_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
    "taker_buy_quote_volume,ignore"
)
CHANGE_MS = to_us(dt.datetime(2022, 2, 15, 3, 30, tzinfo=dt.UTC)) // 1000
BTC_TICKS = TickTable((to_us(dt.datetime(2020, 1, 1, tzinfo=dt.UTC)), CHANGE_MS * 1000), (0.01, 0.1))
ETH_TICKS = TickTable((to_us(dt.datetime(2020, 1, 1, tzinfo=dt.UTC)),), (0.01,))


def _days_in(month: dt.date) -> int:
    following = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (following - month).days


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / f"{name}.zip"
    path.write_bytes(zip_bytes(f"{name}.csv", text))
    return path


def _funding_rows(month: dt.date) -> list[tuple[int, int]]:
    start = day_start_us(month) // 1000
    return [(start + step * 8 * HOUR_MS, 8) for step in range(_days_in(month) * 3)]


def _funding_text(rows: list[tuple[int, int]], header: str = FUNDING_HEADER) -> str:
    return "\n".join([header, *(f"{when},{hours},0.00010000" for when, hours in rows)]) + "\n"


def _funding(
    tmp_path: Path, month: dt.date, rows: list[tuple[int, int]], header: str = FUNDING_HEADER
) -> Any:
    return funding_file_facts(_write(tmp_path, f"f{month}", _funding_text(rows, header)), month, LIMIT)


# ---- funding -----------------------------------------------------------------------------------------------


def test_f1_a_header_that_is_not_the_expected_one_stops_the_run(tmp_path: Path) -> None:
    facts = _funding(tmp_path, NOV, _funding_rows(NOV), header="calc_time,interval,rate")
    assert facts == {"header_ok": False}
    assert funding_stops(facts) == [STOP_F1_HEADER]


def test_f2_an_interval_of_4_stops_the_run_and_names_the_row(tmp_path: Path) -> None:
    rows = _funding_rows(NOV)
    rows[5] = (rows[5][0], 4)
    facts = _funding(tmp_path, NOV, rows)
    assert facts["interval_not_8"] == [["2023-11-02T16:00:00Z", 4]]
    assert funding_stops(facts) == [STOP_F2_INTERVAL]


@pytest.mark.parametrize(("late_ms", "passes"), [(15_000, True), (15_001, False)])
def test_f3_an_offset_past_15_s_fails_and_the_largest_is_recorded(
    tmp_path: Path, late_ms: int, passes: bool
) -> None:
    rows = _funding_rows(NOV)
    rows[7] = (rows[7][0] + late_ms, 8)
    rows[9] = (rows[9][0] - 3, 8)
    facts = _funding(tmp_path, NOV, rows)
    assert (facts["max_offset_ms"], facts["rows_over_15_s"]) == (late_ms, 0 if passes else 1)
    assert funding_stops(facts) == []
    # One month of 48 checked, so a pass is not shown, and a failure is.
    assert funding_span({NOV: facts})["F3"] == {
        "pass": None if passes else False,
        "max_offset_ms": late_ms,
        "months_checked": 1,
    }


def test_f4_a_duplicate_settlement_stops_the_run_and_a_missing_one_is_only_counted(tmp_path: Path) -> None:
    """November has 90 settlements. The 11th, 2023-11-04 08:00, is stamped twice, 5 ms apart, and the 40th,
    2023-11-14 00:00, is absent."""
    rows = _funding_rows(NOV)
    rows.insert(11, (rows[10][0] + 5, 8))
    del rows[40]
    facts = _funding(tmp_path, NOV, rows)
    assert (facts["duplicates"], facts["missing"]) == (1, ["2023-11-14T00:00:00Z"])
    assert funding_stops(facts) == [STOP_F4_DUPLICATE]
    alone = _funding(tmp_path, DEC, [row for index, row in enumerate(_funding_rows(DEC)) if index != 3])
    assert funding_stops(alone) == []
    span = funding_span({DEC: alone})
    # 1,461 days of three settlements, and every month but December has no file.
    assert span["F4"]["expected"] == 4_383
    assert span["F4"]["missing"] == 4_383 - 93 + 1
    assert (span["F4"]["pass"], span["F4"]["months_checked"]) == (None, 1)


def test_f4_a_settlement_held_by_two_months_is_a_duplicate_across_the_boundary(tmp_path: Path) -> None:
    """November's last row is stamped 5 ms before midnight, so its settlement is 2023-12-01 00:00, which
    December's file holds too."""
    november = [*_funding_rows(NOV), (day_start_us(DEC) // 1000 - 5, 8)]
    first = _funding(tmp_path, NOV, november)
    assert first["outside_month"] == ["2023-12-01T00:00:00Z"]
    second = _funding(tmp_path, DEC, _funding_rows(DEC))
    assert funding_stops(first) == funding_stops(second) == []
    span = funding_span({NOV: first, DEC: second})
    assert (span["F4"]["pass"], span["F4"]["duplicates"]) == (False, 1)
    # Had December lost that row, the November one would fill it, and nothing is held twice.
    gap = _funding(tmp_path, DEC, _funding_rows(DEC)[1:])
    filled = funding_span({NOV: first, DEC: gap})
    assert (filled["F4"]["pass"], filled["F4"]["duplicates"]) == (None, 0)
    assert filled["F4"]["missing"] == span["F4"]["missing"]


def test_f5_a_row_settling_off_the_8_hour_grid_is_another_gap(tmp_path: Path) -> None:
    rows = _funding_rows(NOV)
    rows.insert(2, (rows[1][0] + 4 * HOUR_MS, 8))
    facts = _funding(tmp_path, NOV, rows)
    assert facts["off_grid"] == ["2023-11-01T12:00:00Z"]
    assert funding_span({NOV: facts})["F5"] == {
        "pass": False,
        "other_gaps": 1,
        "at": ["2023-11-01T12:00:00Z"],
        "months_checked": 1,
    }


# ---- candles -----------------------------------------------------------------------------------------------


def _candle_text(month: dt.date, prices: dict[int, str], *, minutes: int = 3, extra: str = "") -> str:
    """`minutes` rows from the month's first minute, priced "100.00" unless named."""
    start = day_start_us(month) // 1000
    lines = [KLINES_HEADER]
    for minute in range(minutes):
        stamp = start + minute * 60_000
        price = prices.get(minute, "100.00")
        lines.append(f"{stamp},{price},{price},{price},{price},2.0,{stamp + 59_999},200.0,3,1.0,100.0,0")
    return "\n".join(lines) + "\n" + extra


def _candles(
    tmp_path: Path, month: dt.date, prices: dict[int, str], ticks: TickTable | None, **kwargs: Any
) -> Any:
    path = _write(tmp_path, f"k{month}", _candle_text(month, prices, **kwargs))
    return candle_file_facts(path, month, LIMIT, ticks)


def test_k1_a_price_off_the_0_01_grid_stops_the_run(tmp_path: Path) -> None:
    facts = _candles(tmp_path, NOV, {1: "100.125"}, None)
    assert facts["minutes_off_0_01"] == 1
    assert candle_stops(facts) == [STOP_K1_OFF_GRID]


def test_prices_are_compared_as_decimals_from_the_text(tmp_path: Path) -> None:
    """1.1 and 100.10 sit on the 0.1 grid, though `1.1 % 0.1` is not zero in binary. 100.050 sits on 0.01.
    A price written in exponent form is never taken as on a grid."""
    assert 1.1 % 0.1 != 0.0
    facts = _candles(tmp_path, NOV, {0: "1.1", 1: "100.10", 2: "100.050"}, ETH_TICKS)
    assert facts["minutes_off_0_01"] == 0
    assert facts["minutes_at_0_01_off_0_1"] == 1
    odd = _candles(tmp_path, DEC, {0: "1e2"}, ETH_TICKS)
    assert odd["minutes_off_0_01"] == 1


def test_k2_a_btc_month_before_the_change_with_no_price_off_the_0_1_grid_fails(tmp_path: Path) -> None:
    january = dt.date(2021, 1, 1)
    coarse = _candles(tmp_path, january, {0: "100.1", 1: "100.2", 2: "100.0"}, BTC_TICKS)
    fine = _candles(tmp_path, dt.date(2021, 2, 1), {0: "100.13"}, BTC_TICKS)
    assert (coarse["minutes_at_0_01"], coarse["minutes_at_0_01_off_0_1"]) == (3, 0)
    span = candle_span({january: coarse, dt.date(2021, 2, 1): fine}, BTC_TICKS)
    assert span["K2"] == {"pass": False, "months_at_0_01": 2, "months_showing_0_01": 1, "months_checked": 2}
    assert "K4" not in span


def test_k3_minutes_off_the_0_1_grid_after_the_change_are_reported_and_not_failed(tmp_path: Path) -> None:
    """February 2022. The change is at 03:30 on the 15th: minutes before it are at 0.01, and later 0.1."""
    february = dt.date(2022, 2, 1)
    before = (CHANGE_MS - day_start_us(february) // 1000) // 60_000 - 1
    text = _candle_text(february, {}, minutes=0)
    start = day_start_us(february) // 1000
    for minute, price in ((before, "40000.05"), (before + 1, "40000.15"), (before + 3, "40000.25")):
        stamp = start + minute * 60_000
        text += f"{stamp},{price},{price},{price},{price},2.0,{stamp + 59_999},200.0,3,1.0,100.0,0\n"
    facts = candle_file_facts(_write(tmp_path, "feb", text), february, LIMIT, BTC_TICKS)
    assert (facts["minutes_at_0_01"], facts["minutes_at_0_01_off_0_1"]) == (1, 1)
    assert facts["minutes_at_0_1_off_0_1"] == 2
    assert (facts["first_at_0_1_off_0_1"], facts["last_at_0_1_off_0_1"]) == (
        "2022-02-15T03:30:00Z",
        "2022-02-15T03:32:00Z",
    )
    assert candle_stops(facts) == []
    span = candle_span({february: facts}, BTC_TICKS)
    assert span["K3"] == {
        "reported_not_failed": True,
        "minutes": 2,
        "first": "2022-02-15T03:30:00Z",
        "last": "2022-02-15T03:32:00Z",
    }
    assert "pass" not in span["K3"]


def test_k4_an_eth_month_with_no_price_off_the_0_1_grid_fails(tmp_path: Path) -> None:
    coarse = _candles(tmp_path, NOV, {0: "2000.1", 1: "2000.0", 2: "2000.3"}, ETH_TICKS)
    span = candle_span({NOV: coarse}, ETH_TICKS)
    assert span["K4"] == {"pass": False, "months_at_0_01": 1, "months_showing_0_01": 0, "months_checked": 1}
    assert "K2" not in span and "K3" not in span


def test_k5_rows_missing_and_duplicate_minutes_are_counted(tmp_path: Path) -> None:
    """Three minutes of November, the second twice. November has 43,200 minutes, so 43,197 are missing."""
    start = day_start_us(NOV) // 1000 + 60_000
    again = f"{start},100.00,100.00,100.00,100.00,2.0,{start + 59_999},200.0,3,1.0,100.0,0\n"
    facts = _candles(tmp_path, NOV, {}, None, extra=again)
    assert (facts["rows"], facts["duplicate_minutes"], facts["missing_minutes"]) == (4, 1, 43_197)
    span = candle_span({NOV: facts}, None)
    assert span["K5"]["expected"] == 1_461 * 1_440
    assert span["K5"]["duplicates"] == 1
    assert span["K5"]["rows"] == 4
    assert span["K2_K4"]["pass"] is None


def test_nothing_that_leaves_holds_a_price_volume_or_rate(tmp_path: Path) -> None:
    funding = _funding(tmp_path, NOV, _funding_rows(NOV))
    candles = _candles(tmp_path, NOV, {0: "123.45", 1: "123.4"}, ETH_TICKS)
    text = json.dumps(
        [funding_span({NOV: funding}), candle_span({NOV: candles}, ETH_TICKS), funding, candles]
    )
    for word in ("123.45", "123.4", "0.0001", "200.0", "2.0,"):
        assert word not in text


# ---- in stage one: after the checksum, in the manifest, and the stops --------------------------------------


def _config() -> PipelineConfig:
    base = with_binance_enabled(base_config())
    return replace(base, datasets=tuple(replace(spec, start=NOV) for spec in base.datasets), symbols=(BTC,))


def _full_candles(month: dt.date) -> str:
    start = day_start_us(month) // 1000
    lines = [KLINES_HEADER]
    for minute in range(_days_in(month) * 1440):
        stamp = start + minute * 60_000
        price = "37000.15" if minute % 7 == 0 else "37000.1"
        lines.append(f"{stamp},{price},{price},{price},{price},2.0,{stamp + 59_999},200.0,3,1.0,100.0,0")
    return "\n".join(lines) + "\n"


def _publish(
    fetcher: FakeFetcher, config: PipelineConfig, month: dt.date, funding: str, candles: str | None = None
) -> None:
    pairs = (("binance.klines", candles or _full_candles(month)), ("binance.fundingRate", funding))
    for dataset, text in pairs:
        target = archive_candidates(config, config.dataset(dataset), BTC, month)[0]
        fetcher.publish(
            target.url, zip_bytes(target.filename.replace(".zip", ".csv"), text), name=target.filename
        )


def test_stage_one_records_each_file_s_result_in_the_manifest_and_adds_up_the_span(tmp_path: Path) -> None:
    config = _config()
    fetcher = FakeFetcher()
    for month in (NOV, DEC):
        _publish(fetcher, config, month, _funding_text(_funding_rows(month)))
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    # Every flag is null on 2 of 48 months, and null stops nothing.
    summary = _ingest_or_stop(ctx, fetcher, IngestOptions(ticks={BTC: BTC_TICKS}))
    assert isinstance(summary, IngestSummary), f"the run stopped on {summary}"
    assert summary.errors == []
    raw = [
        record
        for record in ctx.catalog.files(status=None, prefix=f"raw/archive/binance/fundingRate/{BTC}/")
        if record.check_detail is not None
    ]
    assert len(raw) == 2
    assert all("venue_checks" in (record.check_detail or {}) for record in raw)
    assert all((record.check_detail or {})["venue_checks"]["header_ok"] for record in raw)
    assert list(summary.venue_checks) == [BTC]
    result = summary.venue_checks[BTC]
    # Both months pass, but 2 of 48 is not the span, so no flag says pass and none says fail.
    flags = ("F1", "F2", "F3", "F4", "F5", "K1", "K2")
    assert {key: (result[key]["pass"], result[key]["months_checked"]) for key in flags} == dict.fromkeys(
        flags, (None, 2)
    )
    assert result["F4"]["missing"] == 4_383 - 90 - 93
    # After the change, so no month is at 0.01, and every seventh minute is off the 0.1 grid.
    assert result["K2"]["months_at_0_01"] == 0
    assert result["K3"]["minutes"] == sum(-(-_days_in(month) * 1440 // 7) for month in (NOV, DEC))
    assert json.loads(ctx.catalog.get_meta("venue_checks") or "{}") == summary.venue_checks


@pytest.mark.parametrize(
    ("change", "code"),
    [("interval", STOP_F2_INTERVAL), ("header", STOP_F1_HEADER), ("duplicate", STOP_F4_DUPLICATE)],
)
def test_a_stop_after_the_fetch_ends_the_run_and_quarantines_the_file(
    tmp_path: Path, change: str, code: str
) -> None:
    config = _config()
    fetcher = FakeFetcher()
    rows = _funding_rows(DEC)
    text = _funding_text(rows)
    if change == "interval":
        text = _funding_text([(rows[0][0], 4), *rows[1:]])
    elif change == "header":
        text = _funding_text(rows, header="calc_time,funding_interval_hours,funding_rate")
    else:
        text = _funding_text([*rows[:5], (rows[4][0] + 9, 8), *rows[5:]])
    _publish(fetcher, config, DEC, text)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    with pytest.raises(VenueCheckStop) as caught:
        run_ingest(ctx, fetcher, IngestOptions())
    assert caught.value.code == code
    runs = ctx.catalog._db.execute("SELECT status, summary FROM runs").fetchall()
    assert [(row["status"], json.loads(row["summary"])["stop_reason"]) for row in runs] == [("failed", code)]
    assert list((ctx.root.path / "quarantine").rglob("*fundingRate*.zip"))


# ---- the recheck at be20ee7: RC2-01 and RC2-02 -------------------------------------------------------------

JAN_2024_MS = day_start_us(dt.date(2024, 1, 1)) // 1000


def _span_funding(tmp_path: Path, rows_of: Any) -> dict[dt.date, Any]:
    return {month: _funding(tmp_path, month, rows_of(month)) for month in SPAN_MONTHS}


def test_rc2_01_a_settlement_after_the_span_is_listed_and_decides_nothing(tmp_path: Path) -> None:
    """48 clean months, and the 2023-12 file also holds 2024-01-01 00:00, stamped 10 ms early. No file of the
    span can hold that settlement twice, so it is no duplicate and stops nothing. It is listed."""
    facts = _span_funding(
        tmp_path,
        lambda month: (
            [*_funding_rows(month), (JAN_2024_MS - 10, 8)] if month == DEC else _funding_rows(month)
        ),
    )
    assert facts[DEC]["outside_month"] == ["2024-01-01T00:00:00Z"]
    assert (facts[DEC]["duplicates"], funding_stops(facts[DEC])) == (0, [])
    f4 = funding_span(facts)["F4"]
    assert f4 == {
        "pass": True,
        "expected": 4_383,
        "missing": 0,
        "duplicates": 0,
        "files": 48,
        "outside_span": ["2024-01-01T00:00:00Z"],
        "months_checked": 48,
    }


def test_rc2_01_an_early_stamp_at_every_boundary_inside_the_span_stays_correct(tmp_path: Path) -> None:
    """Each month's first settlement after 2020-01 is stamped 10 ms early, so its row sits in the month
    before. The 2023-12 file holds 2024-01-01 00:00 the same way. Each row inside the span fills its own
    month's gap, so nothing is missing and nothing is held twice, and the one past the span is listed only."""

    def rows(month: dt.date) -> list[tuple[int, int]]:
        own = _funding_rows(month)[0 if month == SPAN_MONTHS[0] else 1 :]
        return [*own, (day_start_us(next_month(month)) // 1000 - 10, 8)]

    span = funding_span(_span_funding(tmp_path, rows))
    assert {key: span[key]["pass"] for key in ("F1", "F2", "F3", "F4", "F5")} == dict.fromkeys(
        ("F1", "F2", "F3", "F4", "F5"), True
    )
    assert (span["F3"]["max_offset_ms"], span["F4"]["missing"], span["F4"]["duplicates"]) == (10, 0, 0)
    assert span["F4"]["outside_span"] == ["2024-01-01T00:00:00Z"]
    # A boundary settlement held by both months is still a duplicate.
    held_twice = funding_span(
        _span_funding(tmp_path, lambda month: [*_funding_rows(month), *rows(month)[-1:]])
    )
    assert (held_twice["F4"]["pass"], held_twice["F4"]["duplicates"]) == (False, 47)


def test_rc2_02_a_funding_flag_passes_only_when_every_month_was_checked(tmp_path: Path) -> None:
    """The same clean months: 48 of 48 pass. 10 of 48 is not the span, so each flag is null, with its count. A
    failure found in part of the span still fails."""
    full = _span_funding(tmp_path, _funding_rows)
    flags = ("F1", "F2", "F3", "F4", "F5")
    span = funding_span(full)
    assert {key: (span[key]["pass"], span[key]["months_checked"]) for key in flags} == dict.fromkeys(
        flags, (True, 48)
    )
    part = {month: full[month] for month in SPAN_MONTHS[:10]}
    span = funding_span(part)
    assert {key: (span[key]["pass"], span[key]["months_checked"]) for key in flags} == dict.fromkeys(
        flags, (None, 10)
    )
    rows = _funding_rows(SPAN_MONTHS[0])
    part[SPAN_MONTHS[0]] = _funding(tmp_path, SPAN_MONTHS[0], [(rows[0][0], 4), *rows[1:]])
    assert funding_span(part)["F2"]["pass"] is False


def test_rc2_02_k1_and_k2_pass_only_when_every_month_was_checked(tmp_path: Path) -> None:
    """Three minutes a month, the first at 100.13, which is on 0.01 and off 0.1. BTCUSDT's months from 2020-01
    to 2022-02 open at 0.01, so K2 counts 26 of them. With 10 of 48 months checked, K1 and K2 are null."""
    full = {month: _candles(tmp_path, month, {0: "100.13"}, BTC_TICKS) for month in SPAN_MONTHS}
    span = candle_span(full, BTC_TICKS)
    assert span["K1"] == {"pass": True, "minutes": 0, "months_checked": 48}
    assert span["K2"] == {"pass": True, "months_at_0_01": 26, "months_showing_0_01": 26, "months_checked": 48}
    part = candle_span({month: full[month] for month in SPAN_MONTHS[:10]}, BTC_TICKS)
    assert part["K1"] == {"pass": None, "minutes": 0, "months_checked": 10}
    assert part["K2"] == {"pass": None, "months_at_0_01": 10, "months_showing_0_01": 10, "months_checked": 10}


def test_rc2_02_a_month_checked_without_a_tick_table_is_not_checked_for_k2(tmp_path: Path) -> None:
    full = {month: _candles(tmp_path, month, {0: "100.13"}, BTC_TICKS) for month in SPAN_MONTHS}
    full[NOV] = _candles(tmp_path, NOV, {0: "100.13"}, None)
    span = candle_span(full, BTC_TICKS)
    assert (span["K1"]["pass"], span["K1"]["months_checked"]) == (True, 48)
    assert (span["K2"]["pass"], span["K2"]["months_checked"]) == (None, 47)


def _ingest_or_stop(ctx: Any, fetcher: FakeFetcher, options: IngestOptions) -> IngestSummary | str:
    try:
        return run_ingest(ctx, fetcher, options)
    except VenueCheckStop as stop:
        return stop.code


_ROWS = _funding_rows(DEC)
# For each check: what is published wrong in December, the code it stops on, the dataset, what its file's
# result holds, and its span flag while the result is kept and after a good file replaces it.
_KEPT_CASES: dict[str, tuple[Any, ...]] = {
    "F2": (
        {"funding": _funding_text([(_ROWS[0][0], 4), *_ROWS[1:]])},
        STOP_F2_INTERVAL,
        "fundingRate",
        ("interval_not_8", [["2023-12-01T00:00:00Z", 4]]),
        {"pass": False, "rows": [["2023-12-01T00:00:00Z", 4]], "months_checked": 2},
        {"pass": None, "rows": [], "months_checked": 2},
    ),
    "K1": (
        {"candles": _full_candles(DEC).replace("37000.15,", "37000.155,", 1)},
        STOP_K1_OFF_GRID,
        "klines",
        ("minutes_off_0_01", 1),
        {"pass": False, "minutes": 1, "months_checked": 2},
        {"pass": None, "minutes": 0, "months_checked": 2},
    ),
}


@pytest.mark.parametrize("check", sorted(_KEPT_CASES))
def test_rc2_02_a_kept_failure_stops_every_run_until_its_month_passes(tmp_path: Path, check: str) -> None:
    """The reviewer's case, and the same for K1. December's file fails, so the first run stops on it and the
    task waits 30 minutes for its retry. A run one minute later skips that task, but the span still fails on
    the kept result, so that run ends `failed` with the check's code too, and no other flag passes on 2 of 48
    months. After the wait a good file replaces the result, and the run ends `ok`."""
    bad, code, dataset, (fact, held), failing, cleared = _KEPT_CASES[check]
    config = _config()
    fetcher = FakeFetcher()
    _publish(fetcher, config, NOV, _funding_text(_funding_rows(NOV)))
    _publish(fetcher, config, DEC, bad.get("funding", _funding_text(_ROWS)), bad.get("candles"))
    options = IngestOptions(ticks={BTC: BTC_TICKS})
    first = make_context(tmp_path / "r", now=NOW, config=config)
    assert _ingest_or_stop(first, fetcher, options) == code
    records = first.catalog.files(status=None, prefix=f"raw/archive/binance/{dataset}/{BTC}/")
    assert [(record.status, record.check_status) for record in records] == [("quarantined", "fail")]
    detail = records[0].check_detail or {}
    assert (detail["venue_stop"], detail["venue_checks"][fact]) == (code, held)

    soon = make_context(tmp_path / "r", now=NOW + dt.timedelta(minutes=1), config=config)
    assert _ingest_or_stop(soon, fetcher, options) == code
    runs = soon.catalog._db.execute("SELECT status, summary FROM runs").fetchall()
    assert len(runs) == 1
    stored = json.loads(runs[0]["summary"])
    assert (runs[0]["status"], stored["stop_reason"], stored["skipped_retry_wait"]) == ("failed", code, 1)
    result = stored["venue_checks"][BTC]
    assert result[check] == failing
    others = [key for key in ("F1", "F2", "F3", "F4", "F5", "K1", "K2") if key != check]
    assert {key: result[key]["pass"] for key in others} == dict.fromkeys(others, None)
    assert json.loads(soon.catalog.get_meta("venue_checks") or "{}") == stored["venue_checks"]

    _publish(fetcher, config, DEC, _funding_text(_ROWS))
    later = make_context(tmp_path / "r", now=NOW + dt.timedelta(minutes=31), config=config)
    summary = _ingest_or_stop(later, fetcher, options)
    assert isinstance(summary, IngestSummary), f"the run stopped on {summary}"
    assert (summary.status, summary.done, summary.stop_reason) == ("ok", 1, "none")
    assert summary.venue_checks[BTC][check] == cleared
