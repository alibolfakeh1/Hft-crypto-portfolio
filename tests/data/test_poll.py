"""The hourly poll: cursor catch-up, deduplication, gaps, late trades, timing log, state changes."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from helpers import MINUTE, base_config, make_context, us, with_sources_enabled
from hft_crypto.bars.reconcile import compare_emitted_with_rebuild
from hft_crypto.config import PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.fetch import FetchError, NotPublishedError
from hft_crypto.data.parsers import ValidationError
from hft_crypto.data.poll import (
    KrakenClient,
    RateLimitedError,
    cron_period_s,
    parse_trades_response,
    read_poll_log,
    rebuild_day_bars,
    run_poll,
    scheduled_time,
)
from hft_crypto.timeutil import decimal_seconds_to_us, iso_us

START = dt.date(2026, 3, 1)
START_US = us("2026-03-01T00:00:00")
SYMBOL = "BTCUSD"
PAIR = "XBTUSD"


def row(trade_id: int, ts_us: int, price: float = 100.0, qty: float = 1.0, side: str = "b") -> list[Any]:
    seconds = f"{ts_us // 1_000_000}.{ts_us % 1_000_000:06d}"
    return [f"{price:.5f}", f"{qty:.8f}", seconds, side, "l", "", trade_id]


class FakeKraken:
    """The API as assumed: `since` includes the trade at the cursor, and pages run oldest first."""

    def __init__(self, page_size: int = 3) -> None:
        self.rows: dict[str, list[list[Any]]] = {PAIR: []}
        self.page_size = page_size
        self.calls: list[tuple[str, int]] = []
        self.error: Exception | None = None
        self.error_after: int | None = None

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        pair = query["pair"]
        since = int(query["since"])
        self.calls.append((pair, since))
        if self.error is not None and (self.error_after is None or len(self.calls) > self.error_after):
            raise self.error
        rows = [r for r in self.rows.get(pair, []) if decimal_seconds_to_us(r[2]) * 1000 >= since]
        page = rows[: self.page_size]
        last = decimal_seconds_to_us(page[-1][2]) * 1000 if page else since
        body = {"error": [], "result": {"XXBTZUSD": page, "last": str(last)}}
        return json.dumps(body).encode()

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        raise NotPublishedError(url)


def config_one_pair(start: dt.date = START, page_size: int = 3) -> PipelineConfig:
    config = base_config()
    poll = replace(
        config.poll,
        start_date=start,
        page_size=page_size,
        pairs=(config.poll.pairs[0],),
    )
    return with_sources_enabled(replace(config, poll=poll, timeframes_minutes=(5, 60)))


def context(path: Path, now: str, config: PipelineConfig | None = None) -> JobContext:
    moment = dt.datetime.fromisoformat(now).replace(tzinfo=dt.UTC)
    return make_context(path, now=moment, config=config or config_one_pair())


def run(ctx: JobContext, fake: FakeKraken, **kwargs: Any) -> dict[str, Any]:
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None)
    return run_poll(ctx, client, **kwargs)


def bars_of(ctx: JobContext, day: dt.date) -> pl.DataFrame:
    return read_parquet(ctx.root.curated_part("bars_1m", "kraken", SYMBOL, day))


def trades_of(ctx: JobContext, day: dt.date) -> pl.DataFrame:
    return read_parquet(ctx.root.curated_part("trades", "kraken", SYMBOL, day))


# ---- response parsing --------------------------------------------------------------------------------------


def test_response_parsing_keeps_every_digit_of_time() -> None:
    body = json.dumps(
        {
            "error": [],
            "result": {
                "XXBTZUSD": [["123.25", "0.00012345", 1700000000.123456, "b", "l", "", 42]],
                "last": "1700000000123456000",
            },
        }
    ).encode()
    page = parse_trades_response(body)
    trade = page.trades[0]
    assert trade.trade_id == 42
    assert trade.ts_us == 1700000000123456
    assert trade.price == 123.25
    assert trade.qty == 0.00012345
    assert trade.is_taker_buy is True
    assert page.cursor_ns == 1700000000123456000


@pytest.mark.parametrize(
    ("body", "error", "message"),
    [
        (b"not json", ValidationError, "not JSON"),
        (b"[]", ValidationError, "not an object"),
        (b'{"error":[]}', ValidationError, "no result"),
        (b'{"error":["EGeneral:Too many requests"]}', RateLimitedError, "Too many"),
        (b'{"error":["EService:Unavailable"]}', FetchError, "Unavailable"),
        (b'{"error":["EQuery:Unknown asset pair"]}', ValidationError, "Unknown asset"),
        (b'{"error":[],"result":{"A":[],"B":[],"last":"1"}}', ValidationError, "one pair"),
        (b'{"error":[],"result":{"A":[["1","1",1.5,"x","l","",1]],"last":"1"}}', ValidationError, "side"),
        (
            b'{"error":[],"result":{"A":[["0","1",1.5,"b","l","",1]],"last":"1"}}',
            ValidationError,
            "non-positive",
        ),
        (
            b'{"error":[],"result":{"A":[["1","1"]],"last":"1"}}',
            ValidationError,
            "unexpected Kraken trade row",
        ),
        (b'{"error":[],"result":{"A":[],"last":"soon"}}', ValidationError, "cursor"),
    ],
)
def test_bad_responses_are_recognised(body: bytes, error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        parse_trades_response(body)


def test_decimal_seconds_are_converted_on_the_digits() -> None:
    assert decimal_seconds_to_us("1700000000.1234") == 1700000000123400
    assert decimal_seconds_to_us("1700000000") == 1700000000000000
    # Seven digits floor to six, deterministically, rather than rounding.
    assert decimal_seconds_to_us("1700000000.1234569") == 1700000000123456
    with pytest.raises(ValueError, match="decimal seconds"):
        decimal_seconds_to_us("12a.5")


# ---- schedule arithmetic -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cron", "start", "expected"),
    [
        ("23 * * * *", "2026-03-01T12:25:10", "2026-03-01T12:23:00"),
        ("23 * * * *", "2026-03-01T12:23:00", "2026-03-01T12:23:00"),
        ("23 * * * *", "2026-03-01T12:22:59", "2026-03-01T11:23:00"),
        ("23 * * * *", "2026-03-01T00:05:00", "2026-02-28T23:23:00"),
        ("17 9 * * *", "2026-03-01T09:40:00", "2026-03-01T09:17:00"),
        ("17 9 * * *", "2026-03-01T08:00:00", "2026-02-28T09:17:00"),
        ("*/15 * * * *", "2026-03-01T12:20:00", "2026-03-01T12:15:00"),
    ],
)
def test_scheduled_time(cron: str, start: str, expected: str) -> None:
    moment = dt.datetime.fromisoformat(start).replace(tzinfo=dt.UTC)
    found = scheduled_time(cron, moment)
    assert found == dt.datetime.fromisoformat(expected).replace(tzinfo=dt.UTC)


@pytest.mark.parametrize("cron", [None, "", "23 * * * 1", "bad", "a b c d e"])
def test_scheduled_time_refuses_what_it_cannot_read(cron: str | None) -> None:
    assert scheduled_time(cron, dt.datetime(2026, 3, 1, tzinfo=dt.UTC)) is None


def test_cron_period() -> None:
    assert cron_period_s("23 * * * *") == 3600.0
    assert cron_period_s("17 9 * * *") == 86400.0
    assert cron_period_s(None) is None


# ---- catch-up ----------------------------------------------------------------------------------------------


def test_the_cursor_catches_up_over_many_pages_without_duplicates(tmp_path: Path) -> None:
    fake = FakeKraken(page_size=3)
    fake.rows[PAIR] = [row(100 + i, START_US + (i + 1) * 10_000_000) for i in range(10)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["new_trades"] == 10
    assert result["caught_up"] is True
    assert result["repeated_rows"] == result["pages"] - 1  # the inclusive cursor repeats one row per page
    trades = trades_of(ctx, START)
    assert trades.height == 10
    assert trades["trade_id"].to_list() == list(range(100, 110))
    assert record["gaps"] == []
    assert record["status"] == "ok"


def test_trades_sharing_a_timestamp_across_a_page_boundary_are_all_kept(tmp_path: Path) -> None:
    """One taker's fills can share a timestamp, so a tie can straddle a page boundary.

    With three rows a page, the first page ends on the first of two rows stamped s + 5. The inclusive cursor
    then repeats that row, and the second row must still arrive, exactly once.
    """
    fake = FakeKraken(page_size=3)
    stamp = START_US + 10_000_000
    fake.rows[PAIR] = [
        row(100, stamp),
        row(101, stamp),
        row(102, stamp + 5),
        row(103, stamp + 5),
        row(104, stamp + 9),
    ]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["new_trades"] == 5
    # Row 102 repeats on page 2. Page 2 is full, so page 3 runs, and row 104 repeats there.
    assert result["repeated_rows"] == 2
    assert record["gaps"] == []
    assert trades_of(ctx, START)["trade_id"].to_list() == [100, 101, 102, 103, 104]


def test_a_stuck_cursor_stops_instead_of_looping(tmp_path: Path) -> None:
    """More rows at one timestamp than fit on a page would never advance."""
    fake = FakeKraken(page_size=3)
    stamp = START_US + 10_000_000
    fake.rows[PAIR] = [row(100 + i, stamp) for i in range(6)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["status"] == "failed"
    assert "no progress" in result["error"]
    assert len(fake.calls) < 10


def test_a_second_run_continues_from_the_cursor(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 2_000_000)]
    run(context(tmp_path / "r", "2026-03-01T00:30:00"), fake)
    fake.calls.clear()
    fake.rows[PAIR].append(row(102, START_US + 3_000_000 + 40 * MINUTE))
    ctx = context(tmp_path / "r", "2026-03-01T01:30:00")
    record = run(ctx, fake)
    assert record["symbols"][SYMBOL]["new_trades"] == 1
    assert fake.calls[0][1] == (START_US + 2_000_000) * 1000
    assert trades_of(ctx, START).height == 3


def test_a_late_run_loses_nothing(tmp_path: Path) -> None:
    """Hours of missed schedule: the next run fetches everything since the cursor."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000)]
    run(context(tmp_path / "r", "2026-03-01T00:10:00"), fake)
    fake.rows[PAIR].extend(row(101 + i, START_US + (i + 1) * 15 * MINUTE) for i in range(20))
    ctx = context(tmp_path / "r", "2026-03-01T07:30:00")
    record = run(ctx, fake)
    assert record["symbols"][SYMBOL]["new_trades"] == 20
    assert record["gaps"] == []
    bars = bars_of(ctx, START)
    assert bars["trade_count"].sum() == 21


def test_trades_cross_midnight_into_their_own_parts(tmp_path: Path) -> None:
    fake = FakeKraken()
    midnight = us("2026-03-02T00:00:00")
    fake.rows[PAIR] = [row(100, midnight - 5), row(101, midnight), row(102, midnight + 5)]
    ctx = context(tmp_path / "r", "2026-03-02T02:00:00")
    run(ctx, fake)
    assert trades_of(ctx, START).height == 1
    assert trades_of(ctx, dt.date(2026, 3, 2)).height == 2
    last_of_day_one = bars_of(ctx, START).row(-1, named=True)
    assert last_of_day_one["close_time"].isoformat() == "2026-03-02T00:00:00+00:00"
    # Stamped 5 microseconds before midnight, and exactly at midnight: both close that bar.
    assert last_of_day_one["trade_count"] == 2


# ---- bars --------------------------------------------------------------------------------------------------


def test_only_closed_minutes_are_emitted_and_knowable_when_received(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 5 * MINUTE + 1_000_000)]
    # Fetch at 00:05:30. With 60 s of grace, the newest safe close is 00:04, so the 00:05:01 trade waits.
    ctx = context(tmp_path / "r", "2026-03-01T00:05:30")
    record = run(ctx, fake)
    bars = bars_of(ctx, START)
    assert bars["close_time"][-1].isoformat() == "2026-03-01T00:04:00+00:00"
    assert bars.height == 4
    assert bars["trade_count"].sum() == 1
    assert (bars["knowable_time"].dt.timestamp("us") == us("2026-03-01T00:05:30")).all()
    assert record["symbols"][SYMBOL]["last_bar_close"] == "2026-03-01T00:04:00Z"
    assert record["symbols"][SYMBOL]["data_age_s"] == 90.0
    # The later minutes appear in a later run, knowable then, and earlier rows do not change.
    later = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(later, fake)
    updated = bars_of(later, START)
    assert updated.head(4).equals(bars)
    assert updated.filter(pl.col("close_time").dt.minute() == 6)["trade_count"].to_list() == [1]
    row_after = updated.row(5, named=True)
    assert row_after["knowable_time"].isoformat() == "2026-03-01T01:00:00+00:00"


def test_bars_use_the_same_values_as_the_historical_code(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [
        row(100, START_US + 1_000_000, price=100.0, qty=2.0, side="b"),
        row(101, START_US + 2_000_000, price=103.0, qty=1.0, side="s"),
        row(102, START_US + MINUTE, price=101.0, qty=1.0, side="b"),  # exactly on the boundary
    ]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    first = bars_of(ctx, START).row(0, named=True)
    assert (first["open"], first["high"], first["low"], first["close"]) == (100.0, 103.0, 100.0, 101.0)
    assert first["volume"] == 4.0
    assert first["buy_volume"] == 3.0
    assert first["sell_volume"] == 1.0


def test_higher_timeframes_appear_only_when_closed(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000)]
    ctx = context(tmp_path / "r", "2026-03-01T00:12:30")  # newest close 00:11
    run(ctx, fake)
    five = read_parquet(ctx.root.curated_part("bars_5m", "kraken", SYMBOL, START))
    assert five["close_time"].dt.minute().to_list() == [5, 10]
    hourly = read_parquet(ctx.root.curated_part("bars_1h", "kraken", SYMBOL, START))
    assert hourly.is_empty()


def test_a_trade_arriving_after_its_minute_was_emitted_is_counted_and_does_not_repaint(
    tmp_path: Path,
) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000)]
    first = context(tmp_path / "r", "2026-03-01T00:10:00")
    run(first, fake)
    emitted = bars_of(first, START)
    # A trade stamped inside an already emitted minute shows up in history only now.
    fake.rows[PAIR].append(row(101, START_US + 2 * MINUTE + 5))
    later = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(later, fake)
    assert record["symbols"][SYMBOL]["late_trades"] == 1
    assert bars_of(later, START).head(emitted.height).equals(emitted)
    # The daily check against a rebuild finds it.
    rebuilt = rebuild_day_bars(later, later.config.poll, SYMBOL, START)
    comparison = compare_emitted_with_rebuild(bars_of(later, START), rebuilt)
    assert comparison["bars_different"] == 1
    assert comparison["late_trades"] == 1


def test_not_caught_up_emits_only_minutes_known_to_be_complete(tmp_path: Path) -> None:
    fake = FakeKraken(page_size=3)
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 1) for i in range(30)]
    ctx = context(tmp_path / "r", "2026-03-01T12:00:00")
    # A budget of two calls' worth of a fake clock.
    ticks = iter([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])

    def clock() -> float:
        return next(ticks, 5.0)

    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    record = run_poll(ctx, client, time_budget_s=2.0, clock=clock)
    result = record["symbols"][SYMBOL]
    assert result["caught_up"] is False
    bars = bars_of(ctx, START)
    # Newest trade held is at minute 5 (+1 us). Bars end at the minute boundary before it.
    newest = trades_of(ctx, START)["ts"].dt.timestamp("us").max()
    assert bars["close_time"].dt.timestamp("us").max() < newest  # type: ignore[operator]
    assert bars["trade_count"].sum() == trades_of(ctx, START).height - 1


def test_days_with_no_trades_still_have_their_empty_bars(tmp_path: Path) -> None:
    fake = FakeKraken()
    day_three = us("2026-03-03T00:30:00")
    fake.rows[PAIR] = [row(100, START_US + 1), row(101, day_three)]
    ctx = context(tmp_path / "r", "2026-03-03T01:00:00")
    run(ctx, fake)
    quiet_day = bars_of(ctx, dt.date(2026, 3, 2))
    assert quiet_day.height == 1440
    assert quiet_day["trade_count"].sum() == 0
    assert quiet_day["close"].null_count() == 1440


# ---- gaps and failures -------------------------------------------------------------------------------------


def test_a_jump_in_trade_ids_is_recorded_and_flags_the_bars(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(150, START_US + 3 * MINUTE + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T00:30:00")
    record = run(ctx, fake)
    assert record["gaps"][0]["after_trade_id"] == 100
    assert record["gaps"][0]["next_trade_id"] == 150
    assert "gap_found" in record["state_changes"]
    catalog_gaps = ctx.catalog.gaps()
    assert len(catalog_gaps) == 1
    assert "100" in catalog_gaps[0]["reason"]
    bars = bars_of(ctx, START)
    assert bars.filter(pl.col("gap"))["close_time"].dt.minute().to_list() == [1, 2, 3, 4]


def test_a_failed_fetch_keeps_the_cursor_and_the_next_run_recovers(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, START_US + (i + 1) * MINUTE) for i in range(7)]
    fake.error = FetchError("connection reset")
    fake.error_after = 1
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    assert record["status"] == "failed"
    assert record["symbols"][SYMBOL]["error"] == "connection reset"
    # What arrived before the failure is kept. No bars come out of a failed pass.
    assert trades_of(ctx, START).height == 3
    assert not ctx.root.curated_part("bars_1m", "kraken", SYMBOL, START).exists()

    fake.error = None
    later = context(tmp_path / "r", "2026-03-01T02:00:00")
    recovered = run(later, fake)
    assert recovered["status"] == "ok"
    assert trades_of(later, START)["trade_id"].to_list() == list(range(100, 107))
    assert recovered["gaps"] == []
    assert any(change.startswith("status_failed_to_ok") for change in recovered["state_changes"])


def test_rate_limiting_is_a_failed_pass_not_a_crash(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.error = RateLimitedError("EGeneral:Too many requests")
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    assert record["status"] == "failed"
    assert "Too many" in record["symbols"][SYMBOL]["error"]


def test_a_format_change_fails_the_pass_without_writing_bad_data(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [["bad", "row"]]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")

    class Raw(FakeKraken):
        def get_bytes(self, url: str, max_bytes: int) -> bytes:
            return b'{"error":[],"result":{"XXBTZUSD":[["bad","row"]],"last":"1"}}'

    record = run(ctx, Raw())
    assert record["status"] == "failed"
    assert "validation" in record["symbols"][SYMBOL]["error"]
    assert not ctx.root.curated_part("trades", "kraken", SYMBOL, START).exists()


def test_a_lost_cache_rebuilds_through_the_cursor(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, START_US + (i + 1) * MINUTE) for i in range(5)]
    first = context(tmp_path / "first", "2026-03-01T01:00:00")
    run(first, fake)
    original = bars_of(first, START)

    rebuilt = context(tmp_path / "second", "2026-03-01T01:00:00")
    record = run(rebuilt, fake, published_before=True)
    assert record["state_changes"] == ["cache_lost"]
    assert bars_of(rebuilt, START).equals(original)


# ---- timing log and state changes --------------------------------------------------------------------------


def test_each_run_logs_its_timing(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    started = dt.datetime(2026, 3, 1, 12, 31, 5, tzinfo=dt.UTC)
    ctx = context(tmp_path / "r", "2026-03-01T12:31:30")
    record = run(ctx, fake, cron="23 * * * *", job_started_at=started, event_name="schedule")
    assert record["scheduled_time"] == "2026-03-01T12:23:00Z"
    assert record["job_started_at"] == "2026-03-01T12:31:05Z"
    assert record["delay_s"] == 485.0
    assert record["event"] == "schedule"
    assert record["symbols"][SYMBOL]["data_age_s"] > 0
    assert record["state_changes"] == ["first_run"]
    logged = [json.loads(line) for line in ctx.root.poll_log.read_text(encoding="utf-8").splitlines()]
    assert logged[0]["run_id"] == record["run_id"]


def test_missed_slots_are_counted_between_runs(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 23, tzinfo=dt.UTC))
    ctx.run_id = "second"
    record = run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 5, 25, tzinfo=dt.UTC))
    assert record["since_previous_run_s"] == 4 * 3600 + 120
    assert record["missed_slots"] == 3


def test_an_ordinary_hour_is_not_a_state_change(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 23, tzinfo=dt.UTC))
    ctx.run_id = "second"
    record = run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 2, 23, tzinfo=dt.UTC))
    assert record["state_changes"] == []


def test_many_missed_slots_are_a_state_change(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 23, tzinfo=dt.UTC))
    ctx.run_id = "second"
    record = run(ctx, fake, cron="23 * * * *", job_started_at=dt.datetime(2026, 3, 1, 9, 23, tzinfo=dt.UTC))
    assert record["missed_slots"] == 7
    assert "many_slots_missed" in record["state_changes"]


def test_falling_behind_and_catching_up_are_state_changes(tmp_path: Path) -> None:
    fake = FakeKraken(page_size=3)
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 1) for i in range(12)]
    ctx = context(tmp_path / "r", "2026-03-01T12:00:00")
    ticks: list[float] = []

    def stepping_clock() -> Callable[[], float]:
        state = {"now": 0.0}

        def clock() -> float:
            state["now"] += 1.0
            ticks.append(state["now"])
            return state["now"]

        return clock

    clock = stepping_clock()
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    first = run_poll(ctx, client, time_budget_s=4.0, clock=clock)
    assert first["caught_up"] is False
    ctx.run_id = "second"
    second = run(ctx, fake)
    assert second["caught_up"] is True
    assert "caught_up" in second["state_changes"]


def test_the_live_state_file_holds_no_prices(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1, price=123.45678)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    text = ctx.root.guard.check("catalog/live_state.json").read_text(encoding="utf-8")
    assert "123.45" not in text
    state = json.loads(text)
    assert state["symbols"][SYMBOL]["last_bar_close"] == "2026-03-01T00:59:00Z"
    assert set(state["symbols"][SYMBOL]) == {"last_bar_close", "data_age_s", "status"}


def test_storage_at_the_critical_watermark_blocks_the_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeKraken()
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    (ctx.root.path / "curated" / "filler.bin").write_bytes(b"x" * 2000)
    monkeypatch.setenv("DATA_QUOTA_GB", "0.000001")
    record = run(ctx, fake)
    assert record["status"] == "blocked"
    assert fake.calls == []


def test_logs_from_several_places_merge_into_one_per_run(tmp_path: Path) -> None:
    one = tmp_path / "one.jsonl"
    two = tmp_path / "two.jsonl"
    one.write_text('{"run_id":"a","job_started_at":"2026-03-01T01:00:00Z"}\nnot json\n', encoding="utf-8")
    two.write_text(
        '{"run_id":"a","job_started_at":"2026-03-01T01:00:00Z"}\n{"run_id":"b","job_started_at":"2026-03-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    runs = read_poll_log(one, two, None, tmp_path / "missing.jsonl")
    assert [r["run_id"] for r in runs] == ["b", "a"]


def test_polled_trades_are_knowable_when_received_not_when_they_traded(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    trades = trades_of(ctx, START)
    assert trades["ts"].dt.timestamp("us").to_list() == [START_US + 1_000_000]
    assert trades["knowable_time"].dt.timestamp("us").to_list() == [us("2026-03-01T01:00:00")]
    # Fetched again later by a repeated cursor, the first receipt stands.
    later = context(tmp_path / "r", "2026-03-01T02:00:00")
    run(later, fake)
    assert trades_of(later, START)["knowable_time"].dt.timestamp("us").to_list() == [
        us("2026-03-01T01:00:00")
    ]


def test_with_no_approved_source_the_poll_contacts_nothing(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    config = replace(
        config_one_pair(),
        sources={k: replace(v, enabled=False) for k, v in config_one_pair().sources.items()},
    )
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00", config)
    record = run(ctx, fake)
    assert record["status"] == "no_approved_source"
    assert record["source_state"] == "no approved source configured"
    assert fake.calls == []
    assert record["symbols"] == {}
    assert not ctx.root.curated_part("trades", "kraken", SYMBOL, START).exists()


def test_iso_formatting_is_stable() -> None:
    assert iso_us(START_US) == "2026-03-01T00:00:00Z"
