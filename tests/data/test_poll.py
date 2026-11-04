"""The hourly poll: cursor catch-up, the run clock of C17, proof of empty minutes, gaps, late trades, timing
log."""

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
from hft_crypto.config import ConfigError, PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.catalog import PollState
from hft_crypto.data.context import JobContext
from hft_crypto.data.fetch import FetchError, NotPublishedError
from hft_crypto.data.parsers import ValidationError
from hft_crypto.data.poll import (
    BARS_1M_LIVE,
    TRADES_LIVE,
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
    return read_parquet(ctx.root.curated_part(BARS_1M_LIVE, "kraken", SYMBOL, day))


def trades_of(ctx: JobContext, day: dt.date) -> pl.DataFrame:
    return read_parquet(ctx.root.curated_part(TRADES_LIVE, "kraken", SYMBOL, day))


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
        (
            b'{"error":[],"result":{"A":[["NaN","1",1700000000.5,"b","l","",1]],"last":"1"}}',
            ValidationError,
            "finite",
        ),
        (
            b'{"error":[],"result":{"A":[["1","inf",1700000000.5,"b","l","",1]],"last":"1"}}',
            ValidationError,
            "finite",
        ),
        (
            b'{"error":[],"result":{"A":[["1","1",99999999999999.5,"b","l","",1]],"last":"1"}}',
            ValidationError,
            "out of range",
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
    ctx = context(tmp_path / "r", "2026-03-01T00:01:30")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["new_trades"] == 10
    assert result["caught_up"] is True
    assert result["repeated_rows"] == result["pages"] - 1  # the inclusive cursor repeats one row per page
    trades = trades_of(ctx, START)
    assert trades.height == 10
    assert trades["trade_id"].to_list() == list(range(100, 110))
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
    assert [gap["reason"] for gap in record["gaps"]] == ["no rows before the first"]
    assert trades_of(ctx, START)["trade_id"].to_list() == [100, 101, 102, 103, 104]


def test_a_row_repeated_inside_one_page_is_not_a_gap_and_counts_once(tmp_path: Path) -> None:
    """F-23. It used to raise a false DATA_GAP and overcount the new trades."""
    fake = FakeKraken(page_size=10)
    stamp = START_US + 10_000_000
    fake.rows[PAIR] = [row(100, stamp), row(101, stamp + 5), row(101, stamp + 5), row(102, stamp + 9)]
    ctx = context(tmp_path / "r", "2026-03-01T00:00:30", config_one_pair(page_size=10))
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["new_trades"] == 3
    assert result["repeated_rows"] == 1
    assert not any("jump" in gap["reason"] for gap in record["gaps"])


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
    assert not any("jump" in gap["reason"] for gap in record["gaps"])
    bars = bars_of(ctx, START)
    # The newest row is stamped exactly 05:00:00, so the minute it closes is not yet shown to be over.
    assert bars["close_time"][-1].isoformat() == "2026-03-01T04:59:00+00:00"
    assert bars["trade_count"].sum() == 20


def test_trades_cross_midnight_into_their_own_parts(tmp_path: Path) -> None:
    fake = FakeKraken()
    midnight = us("2026-03-02T00:00:00")
    fake.rows[PAIR] = [row(100, midnight - 5), row(101, midnight), row(102, midnight + 5)]
    ctx = context(tmp_path / "r", "2026-03-02T00:00:15")
    run(ctx, fake)
    assert trades_of(ctx, START).height == 1
    assert trades_of(ctx, dt.date(2026, 3, 2)).height == 2
    last_of_day_one = bars_of(ctx, START).row(-1, named=True)
    assert last_of_day_one["close_time"].isoformat() == "2026-03-02T00:00:00+00:00"
    # Stamped 5 microseconds before midnight, and exactly at midnight: both close that bar.
    assert last_of_day_one["trade_count"] == 2


# ---- the run clock of C17
# ------------------------------------------------------------------------------------


def test_the_cut_comes_from_the_start_of_the_attempt_and_the_allowance(tmp_path: Path) -> None:
    """Run at 14:21:05: 10 s back is 14:20:55, so the cut is 14:20, and a record after it is the evidence."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, us("2026-03-01T14:19:30")), row(101, us("2026-03-01T14:20:30"))]
    ctx = context(tmp_path / "r", "2026-03-01T14:21:05")
    result = run(ctx, fake)["symbols"][SYMBOL]
    assert result["t_poll"] == "2026-03-01T14:21:05Z"
    assert result["t_cut"] == "2026-03-01T14:20:00Z"
    assert result["stepped_back"] is False
    assert result["evidence"] == "record"
    assert result["data_gap"] is False
    assert result["caught_up"] is True
    assert result["last_bar_close"] == "2026-03-01T14:20:00Z"


def test_a_source_with_no_server_time_says_so_in_every_run(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, us("2026-03-01T14:20:30"))]
    result = run(context(tmp_path / "r", "2026-03-01T14:21:05"), fake)["symbols"][SYMBOL]
    assert result["skew_s"] is None
    assert result["passed_on_server_time"] is False


def test_with_no_record_after_the_cut_it_steps_back_one_minute(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, us("2026-03-01T14:18:30")), row(101, us("2026-03-01T14:19:30"))]
    ctx = context(tmp_path / "r", "2026-03-01T14:21:05")
    result = run(ctx, fake)["symbols"][SYMBOL]
    assert result["t_cut"] == "2026-03-01T14:19:00Z"
    assert result["stepped_back"] is True
    assert result["data_gap"] is False
    assert result["last_bar_close"] == "2026-03-01T14:19:00Z"


def test_with_no_record_after_the_step_back_the_run_logs_a_data_gap_and_stops_at_the_newest_trade(
    tmp_path: Path,
) -> None:
    """F-07 and DC-01 b. Last trade 13:03:10, run 13:23:05. Nothing shows the next 19 minutes were quiet."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, us("2026-03-01T13:02:30")), row(101, us("2026-03-01T13:03:10"))]
    ctx = context(tmp_path / "r", "2026-03-01T13:23:05")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["data_gap"] is True
    assert result["evidence"] is None
    assert result["caught_up"] is False
    assert record["data_gap_symbols"] == [SYMBOL]
    assert result["last_bar_close"] == "2026-03-01T13:03:00Z"
    assert bars_of(ctx, START)["close_time"][-1].isoformat() == "2026-03-01T13:03:00+00:00"


def test_an_empty_answer_is_not_a_quiet_market(tmp_path: Path) -> None:
    """F-07. An empty result with no error, while the market traded, used to give 119 clean empty bars."""
    fake = FakeKraken()
    ctx = context(tmp_path / "r", "2026-03-01T02:00:00")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["status"] == "ok"
    assert result["caught_up"] is False
    assert result["data_gap"] is True
    assert result["new_bars"] == 0
    assert not ctx.root.curated_part(BARS_1M_LIVE, "kraken", SYMBOL, START).exists()


def test_a_short_page_mid_history_is_not_caught_up(tmp_path: Path) -> None:
    """F-07. A host returning 2 rows when 1000 are asked for, with 60 waiting, used to fill in 119 bars."""

    class Short(FakeKraken):
        def get_bytes(self, url: str, max_bytes: int) -> bytes:
            self.page_size = 2
            return super().get_bytes(url, max_bytes)

    fake = Short(page_size=2)
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 1) for i in range(60)]
    config = config_one_pair(page_size=1000)
    first = context(tmp_path / "r", "2026-03-01T01:00:30", config)
    record = run(first, fake)
    result = record["symbols"][SYMBOL]
    assert result["new_trades"] == 2
    assert result["caught_up"] is False
    assert result["data_gap"] is True
    # Two rows held, so one minute is shown to be over.
    assert bars_of(first, START)["close_time"][-1].isoformat() == "2026-03-01T00:01:00+00:00"
    # Every row that comes next is in a minute that was not emitted, so none is late.
    later = context(tmp_path / "r", "2026-03-01T01:01:30", config)
    assert run(later, fake)["symbols"][SYMBOL]["late_trades"] == 0


def test_a_slow_write_cannot_move_the_cut_past_the_start_of_the_attempt(tmp_path: Path) -> None:
    """F-07. Writes taking 150 s after a fetch ending 01:00:30 used to emit a bar closing 01:02."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, us("2026-03-01T00:58:30") + i * MINUTE) for i in range(4)]
    moments = iter(
        dt.datetime(2026, 3, 1, 1, 0, 30, tzinfo=dt.UTC) + dt.timedelta(seconds=150 * min(i, 1))
        for i in range(10_000)
    )
    ctx = context(tmp_path / "r", "2026-03-01T01:00:30")
    first = next(moments)
    ticks = {"count": 0}

    def clock() -> dt.datetime:
        # The run's start and its one page read the first time. Everything after reads 150 s later.
        ticks["count"] += 1
        return first if ticks["count"] <= 3 else next(moments)

    ctx.now = clock
    result = run(ctx, fake)["symbols"][SYMBOL]
    assert result["t_cut"] == "2026-03-01T01:00:00Z"
    assert bars_of(ctx, START)["close_time"][-1].isoformat() == "2026-03-01T01:00:00+00:00"


def test_a_row_stamped_ahead_of_the_clock_is_refused(tmp_path: Path) -> None:
    """F-07. One row 3 days ahead used to emit 4,319 bars into the future."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, us("2026-03-04T00:00:00"))]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    result = record["symbols"][SYMBOL]
    assert result["status"] == "failed"
    assert "ahead of the clock" in result["error"]
    assert not ctx.root.curated_part(BARS_1M_LIVE, "kraken", SYMBOL, START).exists()
    assert not ctx.root.curated_part(TRADES_LIVE, "kraken", SYMBOL, START).exists()


def test_a_run_refuses_an_allowance_shorter_than_the_span(tmp_path: Path) -> None:
    config = config_one_pair()
    short = replace(config, poll=replace(config.poll, allowance_a_s=0.1))
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00", short)
    with pytest.raises(ConfigError, match="allowance"):
        run(ctx, FakeKraken())


# ---- bars --------------------------------------------------------------------------------------------------


def test_only_closed_minutes_are_emitted_and_knowable_when_received(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 5 * MINUTE + 1_000_000)]
    # Fetch at 00:05:30. The cut is 00:05, and the 00:05:01 trade is the record after it.
    ctx = context(tmp_path / "r", "2026-03-01T00:05:30")
    record = run(ctx, fake)
    bars = bars_of(ctx, START)
    assert bars["close_time"][-1].isoformat() == "2026-03-01T00:05:00+00:00"
    assert bars.height == 5
    assert bars["trade_count"].sum() == 1
    assert (bars["knowable_time"].dt.timestamp("us") == us("2026-03-01T00:05:30")).all()
    assert record["symbols"][SYMBOL]["last_bar_close"] == "2026-03-01T00:05:00Z"
    assert record["symbols"][SYMBOL]["data_age_s"] == 30.0
    # The later minutes appear in a later run, knowable then, and earlier rows do not change.
    fake.rows[PAIR].append(row(102, us("2026-03-01T00:59:55")))
    later = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(later, fake)
    updated = bars_of(later, START)
    assert updated.head(5).equals(bars)
    assert updated.filter(pl.col("close_time").dt.minute() == 6)["trade_count"].to_list() == [1]
    row_after = updated.row(5, named=True)
    assert row_after["knowable_time"].isoformat() == "2026-03-01T01:00:00+00:00"


def test_bars_use_the_same_values_as_the_historical_code(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [
        row(100, START_US + 1_000_000, price=100.0, qty=2.0, side="b"),
        row(101, START_US + 2_000_000, price=103.0, qty=1.0, side="s"),
        row(102, START_US + MINUTE, price=101.0, qty=1.0, side="b"),  # exactly on the boundary
        row(103, START_US + 2 * MINUTE, price=101.0, qty=1.0, side="b"),
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
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 11 * MINUTE + 5)]
    ctx = context(tmp_path / "r", "2026-03-01T00:12:30")  # newest close 00:11
    run(ctx, fake)
    five = read_parquet(ctx.root.curated_part("bars_5m_live", "kraken", SYMBOL, START))
    assert five["close_time"].dt.minute().to_list() == [5, 10]
    hourly = read_parquet(ctx.root.curated_part("bars_1h_live", "kraken", SYMBOL, START))
    assert hourly.is_empty()


def test_a_trade_arriving_after_its_minute_was_emitted_is_logged_and_does_not_repaint(tmp_path: Path) -> None:
    """DC-01 b. A print at 95 reaches history late. No bar changes, and the correction log says when it
    came."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 5 * MINUTE + 5)]
    first = context(tmp_path / "r", "2026-03-01T00:05:30")
    run(first, fake)
    emitted = bars_of(first, START)
    # An id that runs on, stamped inside an already emitted minute, shows up in history only now.
    fake.rows[PAIR].insert(1, row(102, START_US + 2 * MINUTE + 5, price=95.0))
    fake.rows[PAIR].append(row(103, START_US + 30 * MINUTE))
    later = context(tmp_path / "r", "2026-03-01T01:00:00")
    # The fake's cursor is by time, so it serves the late row only when asked from before it.
    later.catalog.set_poll_state(
        PollState(SYMBOL, START_US * 1000, 101, START_US + 5 * MINUTE, START_US + 5 * MINUTE + 5),
        now="2026-03-01T00:30:00Z",
    )
    record = run(later, fake)
    assert record["symbols"][SYMBOL]["late_trades"] == 1
    assert bars_of(later, START).head(emitted.height).equals(emitted)
    lines = later.root.guard.check("catalog/bar_corrections.jsonl").read_text(encoding="utf-8").splitlines()
    correction = json.loads(lines[0])
    assert correction["bar_close"] == "2026-03-01T00:03:00Z"
    assert correction["price"] == 95.0
    assert correction["received_at"] == "2026-03-01T01:00:00Z"
    # The daily check against a rebuild finds it.
    rebuilt = rebuild_day_bars(later, later.config.poll, SYMBOL, START)
    comparison = compare_emitted_with_rebuild(bars_of(later, START), rebuilt)
    assert comparison["bars_different"] >= 1
    assert comparison["late_trades"] == 1


def _stepping_clock() -> Callable[[], float]:
    state = {"now": 0.0}

    def clock() -> float:
        state["now"] += 1.0
        return state["now"]

    return clock


def test_not_caught_up_emits_only_minutes_known_to_be_complete(tmp_path: Path) -> None:
    fake = FakeKraken(page_size=3)
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 1) for i in range(30)]
    ctx = context(tmp_path / "r", "2026-03-01T12:00:00")
    clock = _stepping_clock()
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    record = run_poll(ctx, client, time_budget_s=8.0, clock=clock)
    result = record["symbols"][SYMBOL]
    assert result["caught_up"] is False
    assert 0 < result["new_trades"] < 30
    bars = bars_of(ctx, START)
    newest = trades_of(ctx, START)["ts"].dt.timestamp("us").max()
    assert bars["close_time"].dt.timestamp("us").max() < newest  # type: ignore[operator]
    assert bars["trade_count"].sum() == trades_of(ctx, START).height - 1


def test_the_budget_also_bounds_emission_and_the_next_pass_carries_on(tmp_path: Path) -> None:
    """F-21. The fetch stops at its share and emission between days, so a job's hard timeout cannot cut a
    write."""
    fake = FakeKraken(page_size=1000)
    first_day = us("2026-03-01T00:00:30")
    fake.rows[PAIR] = [row(100 + i, first_day + i * 12 * 60 * MINUTE) for i in range(10)]
    ctx = context(tmp_path / "r", "2026-03-05T12:30:00", config_one_pair(page_size=1000))
    clock = _stepping_clock()
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    record = run_poll(ctx, client, time_budget_s=5.0, clock=clock)
    result = record["symbols"][SYMBOL]
    assert result["bars_left_by_budget"] is True
    assert result["caught_up"] is False
    # One day got through, at least. The state says how far, and the rest comes next time.
    state = ctx.catalog.get_poll_state(SYMBOL)
    assert state is not None
    assert state.emitted_end_us is not None
    assert us("2026-03-02T00:00:00") <= state.emitted_end_us < us("2026-03-05T12:00:00")
    ctx.run_id = "second"
    finished = run(ctx, fake)["symbols"][SYMBOL]
    assert finished["bars_left_by_budget"] is False
    assert finished["last_bar_close"] == "2026-03-05T12:00:00Z"


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
    # Ids run on from the row before to the row after, across a whole day, so this is proved and not assumed.
    assert quiet_day["empty_proof"].unique().to_list() == ["id_run"]
    assert quiet_day["gap"].sum() == 0


def test_the_poll_writes_only_its_own_datasets(tmp_path: Path) -> None:
    """DC-06. Archive code has no name that reaches these, so one root for both is harmless."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 6 * MINUTE)]
    ctx = context(tmp_path / "r", "2026-03-01T00:06:30")
    run(ctx, fake)
    curated = {path.name for path in ctx.root.guard.check("curated").iterdir()}
    assert curated == {"trades_live", "bars_1m_live", "bars_5m_live", "bars_1h_live"}


# ---- gaps and failures -------------------------------------------------------------------------------------


def test_a_jump_in_trade_ids_is_recorded_and_flags_the_bars(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [
        row(100, START_US + 1_000_000),
        row(150, START_US + 3 * MINUTE + 1),
        row(151, START_US + 5 * MINUTE + 1),
    ]
    ctx = context(tmp_path / "r", "2026-03-01T00:05:30")
    record = run(ctx, fake)
    jump = next(gap for gap in record["gaps"] if "jump" in gap["reason"])
    assert jump["after_trade_id"] == 100
    assert jump["next_trade_id"] == 150
    assert "gap_found" in record["state_changes"]
    assert any("100" in gap["reason"] for gap in ctx.catalog.gaps())
    bars = bars_of(ctx, START)
    assert bars.filter(pl.col("gap"))["close_time"].dt.minute().to_list() == [1, 2, 3, 4]
    assert bars["close_time"].dt.minute().to_list() == [1, 2, 3, 4, 5]


def test_dc01a_a_gap_found_in_a_failed_pass_flags_bars_emitted_by_a_later_pass(tmp_path: Path) -> None:
    """F-08 and DC-01 a. The flag used to be a local variable, and died with the run that found it."""
    fake = FakeKraken(page_size=2)
    fake.rows[PAIR] = [
        row(100, START_US + 1_000_000),
        row(150, START_US + 3 * MINUTE + 1),
        row(151, START_US + 5 * MINUTE + 1),
    ]
    fake.error = FetchError("connection reset")
    fake.error_after = 1
    config = config_one_pair(page_size=2)
    ctx = context(tmp_path / "r", "2026-03-01T00:05:30", config)
    failed = run(ctx, fake)
    assert failed["status"] == "failed"
    assert not ctx.root.curated_part(BARS_1M_LIVE, "kraken", SYMBOL, START).exists()
    assert any("jump" in gap["reason"] for gap in ctx.catalog.gaps())

    fake.error = None
    later = context(tmp_path / "r", "2026-03-01T00:06:30", config)
    recovered = run(later, fake)
    assert recovered["status"] == "ok"
    assert not any("jump" in gap["reason"] for gap in recovered["gaps"])
    bars = bars_of(later, START)
    assert bars.filter(pl.col("gap"))["close_time"].dt.minute().to_list() == [1, 2, 3, 4]


def test_dc01d_a_jump_past_the_budget_still_flags_its_last_minute_in_the_next_pass(tmp_path: Path) -> None:
    """F-08. The bar holding the first trade after a gap came out clean, because it lay past that pass's
    end."""
    fake = FakeKraken(page_size=2)
    fake.rows[PAIR] = [
        row(100, START_US + 1_000_000),
        row(150, START_US + 3 * MINUTE + 1),
        row(151, START_US + 3 * MINUTE + 2),
        row(152, START_US + 9 * MINUTE),
    ]
    ctx = context(tmp_path / "r", "2026-03-01T00:09:30", config_one_pair(page_size=2))
    clock = _stepping_clock()
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    run_poll(ctx, client, time_budget_s=8.0, clock=clock)
    first = bars_of(ctx, START)
    assert first["close_time"][-1].isoformat() == "2026-03-01T00:03:00+00:00"
    ctx.run_id = "second"
    run(ctx, fake)
    bars = bars_of(ctx, START)
    assert bars.filter(pl.col("gap"))["close_time"].dt.minute().to_list() == [1, 2, 3, 4]
    assert bars["gap"].sum() == 4


def test_dc01c_minutes_before_the_first_row_anyone_can_reach_are_gaps(tmp_path: Path) -> None:
    """DC-01 c. A lost cache starts the cursor before the source's history, and that used to look like quiet
    days."""
    fake = FakeKraken()
    first_row = us("2026-03-03T00:00:30")
    fake.rows[PAIR] = [row(100, first_row), row(101, first_row + MINUTE)]
    ctx = context(tmp_path / "r", "2026-03-03T00:01:45")
    record = run(ctx, fake)
    assert any(gap["reason"] == "no rows before the first" for gap in record["gaps"])
    quiet = bars_of(ctx, dt.date(2026, 3, 1))
    assert quiet.height == 1440
    assert quiet["gap"].all()
    assert quiet["empty_proof"].unique().to_list() == ["none"]


def test_c17_a_stop_inside_a_hole_cannot_pass_as_a_quiet_market(tmp_path: Path) -> None:
    """C17's required test. Every minute of a hole is flagged, in the 1m bars and in the higher bar that holds
    it."""
    fake = FakeKraken(page_size=100)
    before = us("2026-03-01T12:00:20")
    after = us("2026-03-01T12:30:30")
    fake.rows[PAIR] = [row(101, before), row(150, after), row(151, us("2026-03-01T13:30:00"))]
    ctx = context(tmp_path / "r", "2026-03-01T13:30:30")
    run(ctx, fake)
    bars = bars_of(ctx, START)
    hole = bars.filter(
        (pl.col("close_time").dt.timestamp("us") > before)
        & (pl.col("close_time").dt.timestamp("us") <= after + MINUTE)
    )
    assert hole.height == 31
    assert hole["gap"].all()
    hourly = read_parquet(ctx.root.curated_part("bars_1h_live", "kraken", SYMBOL, START))
    affected = hourly.filter(pl.col("close_time").dt.hour() == 13).row(0, named=True)
    assert affected["gap"] is True
    assert affected["complete"] is False


def test_a_failed_fetch_keeps_the_cursor_and_the_next_run_recovers(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, START_US + (i + 1) * MINUTE) for i in range(7)]
    fake.error = FetchError("connection reset")
    fake.error_after = 1
    ctx = context(tmp_path / "r", "2026-03-01T00:07:30")
    record = run(ctx, fake)
    assert record["status"] == "failed"
    assert record["symbols"][SYMBOL]["error"] == "connection reset"
    # What arrived before the failure is kept. No bars come out of a failed pass.
    assert trades_of(ctx, START).height == 3
    assert not ctx.root.curated_part(BARS_1M_LIVE, "kraken", SYMBOL, START).exists()

    fake.error = None
    later = context(tmp_path / "r", "2026-03-01T00:07:30")
    recovered = run(later, fake)
    assert recovered["status"] == "ok"
    assert trades_of(later, START)["trade_id"].to_list() == list(range(100, 107))
    assert not any("jump" in gap["reason"] for gap in recovered["gaps"])
    assert any(change.startswith("status_failed_to_ok") for change in recovered["state_changes"])


def test_rate_limiting_is_a_failed_pass_not_a_crash(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.error = RateLimitedError("EGeneral:Too many requests")
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    record = run(ctx, fake)
    assert record["status"] == "failed"
    assert "Too many" in record["symbols"][SYMBOL]["error"]


def test_a_format_change_fails_the_pass_without_writing_bad_data(tmp_path: Path) -> None:
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")

    class Raw(FakeKraken):
        def get_bytes(self, url: str, max_bytes: int) -> bytes:
            return b'{"error":[],"result":{"XXBTZUSD":[["bad","row"]],"last":"1"}}'

    record = run(ctx, Raw())
    assert record["status"] == "failed"
    assert "validation" in record["symbols"][SYMBOL]["error"]
    assert not ctx.root.curated_part(TRADES_LIVE, "kraken", SYMBOL, START).exists()


def test_a_lost_cache_rebuilds_through_the_cursor_and_says_so_on_every_bar(tmp_path: Path) -> None:
    """DC-10. A rebuilt bar is not what a run saw, so it is marked, and the daily check does not call it a
    pass."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, START_US + (i + 1) * MINUTE) for i in range(5)]
    first = context(tmp_path / "first", "2026-03-01T00:05:30")
    run(first, fake)
    original = bars_of(first, START)
    assert original["emission"].unique().to_list() == ["first"]

    rebuilt = context(tmp_path / "second", "2026-03-01T00:05:30")
    record = run(rebuilt, fake, published_before=True)
    assert "cache_lost" in record["state_changes"]
    again = bars_of(rebuilt, START)
    assert again["emission"].unique().to_list() == ["rebuild"]
    assert again.drop("emission").equals(original.drop("emission"))
    comparison = compare_emitted_with_rebuild(
        again, rebuild_day_bars(rebuilt, rebuilt.config.poll, SYMBOL, START)
    )
    assert comparison["status"] == "not_applicable"
    # Rows emitted once the run has its data through the cut are what the runs see.
    fake.rows[PAIR].append(row(105, START_US + 6 * MINUTE + 5))
    fake.rows[PAIR].append(row(106, START_US + 7 * MINUTE + 5))
    fake.rows[PAIR].append(row(107, START_US + 8 * MINUTE + 5))
    rebuilt.run_id = "third"
    rebuilt.now = lambda: dt.datetime(2026, 3, 1, 0, 8, 15, tzinfo=dt.UTC)
    run(rebuilt, fake, published_before=True)
    assert bars_of(rebuilt, START)["emission"][-1] == "first"


def test_each_run_logs_a_hash_of_what_it_emitted(tmp_path: Path) -> None:
    """DC-10. The log is on the results branch, so what a run saw can be shown after a cache is lost."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 5 * MINUTE + 5)]
    one = run(context(tmp_path / "a", "2026-03-01T00:05:30"), fake)["symbols"][SYMBOL]
    two = run(context(tmp_path / "b", "2026-03-01T00:05:30"), fake)["symbols"][SYMBOL]
    assert one["emitted_hash"] == two["emitted_hash"]
    assert len(one["emitted_hash"]) == 64
    fake.rows[PAIR][0] = row(100, START_US + 1_000_000, price=101.0)
    other = run(context(tmp_path / "c", "2026-03-01T00:05:30"), fake)["symbols"][SYMBOL]
    assert other["emitted_hash"] != one["emitted_hash"]


def test_a_rebuild_for_comparison_cannot_be_read_by_time(tmp_path: Path) -> None:
    """DC-05. With default arguments it used to say knowable at the close, on trades received an hour
    later."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 5 * MINUTE)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    rebuilt = rebuild_day_bars(ctx, ctx.config.poll, SYMBOL, START)
    assert "knowable_time" not in rebuilt.columns


def test_a_replayed_page_after_a_crash_keeps_the_first_receipt(tmp_path: Path) -> None:
    """The merge keeps the first row of a trade. No test held this, so `keep="last"` survived mutation."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000), row(101, START_US + 2_000_000)]
    first = context(tmp_path / "r", "2026-03-01T00:30:00")
    run(first, fake)
    # A crash after the trades were written and before the cursor was saved.
    first.catalog.set_poll_state(
        PollState(SYMBOL, START_US * 1000, None, None, None), now="2026-03-01T00:30:00Z"
    )
    later = context(tmp_path / "r", "2026-03-01T01:30:00")
    run(later, fake)
    trades = trades_of(later, START)
    assert trades.height == 2
    assert trades["knowable_time"].dt.timestamp("us").to_list() == [us("2026-03-01T00:30:00")] * 2


# ---- timing log and state changes --------------------------------------------------------------------------


def test_each_run_logs_its_timing(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1), row(101, us("2026-03-01T12:31:20"))]
    started = dt.datetime(2026, 3, 1, 12, 31, 5, tzinfo=dt.UTC)
    ctx = context(tmp_path / "r", "2026-03-01T12:31:30")
    record = run(ctx, fake, cron="7 * * * *", job_started_at=started, event_name="schedule")
    assert record["scheduled_time"] == "2026-03-01T12:07:00Z"
    assert record["job_started_at"] == "2026-03-01T12:31:05Z"
    assert record["delay_s"] == 1445.0
    assert record["event"] == "schedule"
    assert record["data_kind"] == "MARKET"
    assert record["symbols"][SYMBOL]["data_age_s"] > 0
    assert record["state_changes"][0] == "first_run"
    logged = [json.loads(line) for line in ctx.root.poll_log.read_text(encoding="utf-8").splitlines()]
    assert logged[0]["run_id"] == record["run_id"]


def test_missed_slots_are_counted_between_runs(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 7, tzinfo=dt.UTC))
    ctx.run_id = "second"
    record = run(ctx, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 5, 9, tzinfo=dt.UTC))
    assert record["since_previous_run_s"] == 4 * 3600 + 120
    assert record["missed_slots"] == 3


def _first_hour(fake: FakeKraken) -> None:
    fake.rows[PAIR] = [row(100, us("2026-03-01T00:59:50")), row(101, us("2026-03-01T01:06:55"))]


def test_an_ordinary_hour_is_not_a_state_change(tmp_path: Path) -> None:
    fake = FakeKraken()
    _first_hour(fake)
    first = context(tmp_path / "r", "2026-03-01T01:07:01")
    run(first, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 7, tzinfo=dt.UTC))
    fake.rows[PAIR].append(row(102, us("2026-03-01T02:06:55")))
    second = context(tmp_path / "r", "2026-03-01T02:07:01")
    second.run_id = "second"
    record = run(second, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 2, 7, tzinfo=dt.UTC))
    assert record["state_changes"] == []


def test_an_hour_with_no_evidence_is_a_state_change_once(tmp_path: Path) -> None:
    fake = FakeKraken()
    _first_hour(fake)
    first = context(tmp_path / "r", "2026-03-01T01:07:01")
    run(first, fake)
    second = context(tmp_path / "r", "2026-03-01T03:07:01")
    second.run_id = "second"
    changed = run(second, fake)
    assert "data_gap_started" in changed["state_changes"]
    third = context(tmp_path / "r", "2026-03-01T04:07:01")
    third.run_id = "third"
    assert "data_gap_started" not in run(third, fake)["state_changes"]
    fake.rows[PAIR].append(row(103, us("2026-03-01T05:06:55")))
    fourth = context(tmp_path / "r", "2026-03-01T05:07:01")
    fourth.run_id = "fourth"
    assert "data_gap_ended" in run(fourth, fake)["state_changes"]


def test_many_missed_slots_are_a_state_change(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 1, 7, tzinfo=dt.UTC))
    ctx.run_id = "second"
    record = run(ctx, fake, cron="7 * * * *", job_started_at=dt.datetime(2026, 3, 1, 9, 7, tzinfo=dt.UTC))
    assert record["missed_slots"] == 7
    assert "many_slots_missed" in record["state_changes"]


def test_falling_behind_and_catching_up_are_state_changes(tmp_path: Path) -> None:
    fake = FakeKraken(page_size=3)
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 1) for i in range(12)]
    ctx = context(tmp_path / "r", "2026-03-01T00:11:30")
    clock = _stepping_clock()
    client = KrakenClient(fake, ctx.config.poll, sleep=lambda _: None, clock=clock)
    first = run_poll(ctx, client, time_budget_s=4.0, clock=clock)
    assert first["caught_up"] is False
    ctx.run_id = "second"
    second = run(ctx, fake)
    assert second["caught_up"] is True
    assert "caught_up" in second["state_changes"]


def test_the_live_state_file_holds_no_prices(tmp_path: Path) -> None:
    fake = FakeKraken()
    fake.rows[PAIR] = [
        row(100, START_US + 1, price=123.45678),
        row(101, us("2026-03-01T00:59:55"), price=123.45678),
    ]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    text = ctx.root.guard.check("catalog/live_state.json").read_text(encoding="utf-8")
    assert "123.45" not in text
    state = json.loads(text)
    assert state["symbols"][SYMBOL]["last_bar_close"] == "2026-03-01T00:59:00Z"
    assert state["data_kind"] == "MARKET"
    assert set(state["symbols"][SYMBOL]) == {"last_bar_close", "data_age_s", "status"}


def test_the_poll_keeps_running_at_the_critical_watermark_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-22. The lifecycle says live paper keeps running at 95%. It used to stop, and on its own root, for
    good."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100, START_US + 1_000_000)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    (ctx.root.path / "curated" / "filler.bin").write_bytes(b"x" * 2000)
    monkeypatch.setenv("DATA_QUOTA_GB", "0.000001")
    record = run(ctx, fake)
    assert record["status"] == "ok"
    assert fake.calls != []
    assert record["watermark_level"] == "critical"
    assert record["alerts"]
    assert "storage_critical" in record["state_changes"]


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


def test_a_polled_trade_is_never_knowable_before_its_stamp_plus_the_allowance(tmp_path: Path) -> None:
    fake = FakeKraken()
    stamp = us("2026-03-01T01:00:00")
    fake.rows[PAIR] = [row(100, stamp)]
    ctx = context(tmp_path / "r", "2026-03-01T01:00:00")
    run(ctx, fake)
    assert trades_of(ctx, START)["knowable_time"].dt.timestamp("us").to_list() == [stamp + 250_000]


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
    assert record["data_kind"] == "NONE"
    assert fake.calls == []
    assert record["symbols"] == {}
    assert not ctx.root.curated_part(TRADES_LIVE, "kraken", SYMBOL, START).exists()
    # Nothing was tried, so nothing failed.
    assert ctx.catalog.last_runs()["live_poll"][0]["status"] == "no_approved_source"


def test_iso_formatting_is_stable() -> None:
    assert iso_us(START_US) == "2026-03-01T00:00:00Z"


def test_one_page_cannot_take_a_whole_run_budget() -> None:
    """F-21. One page could take 186 s against a budget of 120 s, as the fetch settings were shared."""
    config = base_config()
    poll = config.poll
    worst = poll.timeout_s * poll.attempts + config.fetch.backoff_s * (poll.attempts - 1)
    assert worst < poll.default_time_budget_s


def test_the_poll_command_gives_its_client_the_polls_own_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from helpers import REPO_ROOT
    from hft_crypto import cli
    from hft_crypto.data.fetch import HttpFetcher

    seen: list[Any] = []

    def recording(limits: Any, **kwargs: Any) -> Any:
        seen.append(limits)
        return HttpFetcher(limits, **kwargs)

    monkeypatch.setattr("hft_crypto.cli.HttpFetcher", recording)
    args = ["--config-dir", str(REPO_ROOT / "configs"), "--data-root", str(tmp_path / "r"), "poll"]
    assert cli.main(args) == 0
    capsys.readouterr()
    poll = base_config().poll
    assert (seen[0].timeout_s, seen[0].attempts) == (poll.timeout_s, poll.attempts)


def test_a_gap_in_the_catalog_flags_bars_whatever_the_rows_show(tmp_path: Path) -> None:
    """F-08. Flags come from the catalog, which outlives a pass. Here only the catalog knows about the
    hole."""
    fake = FakeKraken()
    fake.rows[PAIR] = [row(100 + i, START_US + i * MINUTE + 30_000_000) for i in range(6)]
    ctx = context(tmp_path / "r", "2026-03-01T00:05:50")
    ctx.catalog.add_gap(
        f"curated.{TRADES_LIVE}.kraken.{SYMBOL}",
        iso_us(START_US + 2 * MINUTE + 1),
        iso_us(START_US + 3 * MINUTE + 1),
        "recorded by an earlier pass",
        now="2026-03-01T00:00:00Z",
        run_id=None,
    )
    run(ctx, fake)
    bars = bars_of(ctx, START)
    # 00:01 holds the first row anyone can reach, so nothing shows the minute was whole.
    assert bars.filter(pl.col("gap"))["close_time"].dt.minute().to_list() == [1, 3, 4]
