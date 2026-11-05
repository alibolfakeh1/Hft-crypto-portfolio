"""Hourly poll of closed trades from Kraken's public REST API, with a `since` cursor.

Short, and never a loop: one pass per scheduled run, then the job ends. A late or missed run loses nothing,
because the cursor catches up from where it stopped.

This adapter is disabled until its source is approved. With no approved source it contacts nothing and records
that fact. How it treats the API, which must be checked again against the source once approved:
- The cursor is inclusive. Each page starts by repeating the last trade of the page before, and trades can
  share one timestamp, so rows are deduplicated on trade id. Trade ids are expected to run without gaps.
- A lost cache rebuilds by starting the cursor over from the configured start date.

The `fetch` stage of C17 lives here. A run records `t_poll` when its fetch attempt starts, sets `t_cut` from
it, and must hold a record stamped after `t_cut`, or it steps back one minute and asks again, and otherwise
logs `DATA_GAP`. A source that gives a server time could also pass on that. No adapter here reads one yet, so
it is logged as absent.

The rules for what comes out, which keep the timing contract honest:
- This job writes its own datasets, `trades_live` and `bars_*_live`. Archive code has no name that reaches
  them, so an archive of the same venue can never replace what a run saw.
- A minute is emitted only through the earlier of `t_cut` and the minute before the newest trade held, because
  only a later record shows a minute is over. A short page or an empty answer says nothing about the market.
- An empty minute needs proof under C2. Trades on both sides with consecutive ids are proof. Anything else is
  a gap.
- A bar is knowable when this job received it, not when it closed, because this job is the only way a paper
  engine on GitHub could have it. That is usually about an hour after the close.
- A bar, once emitted, is never rewritten. A trade arriving after its minute was emitted goes in a corrections
  log, and the daily check against a rebuild from all stored trades reports the difference.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.core import UTC_TIME, aggregate_bars, build_bars_1m, closes_between
from hft_crypto.config import ConfigError, PollConfig, PollPair, quota_bytes
from hft_crypto.data.atomic import append_jsonl, atomic_write_json, atomic_write_parquet, read_parquet
from hft_crypto.data.catalog import PollState
from hft_crypto.data.context import JobContext, write_heartbeat
from hft_crypto.data.derive import timeframe_dataset
from hft_crypto.data.fetch import Fetcher, FetchError
from hft_crypto.data.parsers import TRADE_SCHEMA, ValidationError
from hft_crypto.data.retention import evaluate_watermarks
from hft_crypto.data.zones import measure_zones
from hft_crypto.timeutil import (
    MICROS_PER_DAY,
    MICROS_PER_MINUTE,
    MICROS_PER_SECOND,
    date_of_us,
    day_start_us,
    decimal_seconds_to_us,
    iso,
    iso_us,
    parse_iso,
    to_us,
)
from hft_crypto.versioning import code_version

TRADES_LIVE = "trades_live"
BARS_1M_LIVE = "bars_1m_live"
EMISSION_FIRST = "first"
EMISSION_REBUILD = "rebuild"
_CORRECTIONS = "catalog/bar_corrections.jsonl"
# Stamps outside this range cannot be real, and would overflow the date arithmetic further on.
_MIN_STAMP_US = day_start_us(dt.date(2000, 1, 1))
_MAX_STAMP_US = day_start_us(dt.date(2100, 1, 1))


def live_dataset(minutes: int) -> str:
    """The poll's dataset for a timeframe. It has its own names, so no archive code can write to it."""
    return f"{timeframe_dataset(minutes)}_live"


_MAX_RESPONSE_BYTES = 8_000_000
_CRON_FIELD = re.compile(r"^(\*|\d+|\*/\d+)$")


@dataclass(frozen=True)
class KrakenTrade:
    trade_id: int
    ts_us: int
    price: float
    qty: float
    is_taker_buy: bool
    received_us: int = 0


@dataclass(frozen=True)
class TradesPage:
    trades: tuple[KrakenTrade, ...]
    cursor_ns: int
    raw_rows: int


class RateLimitedError(FetchError):
    """Kraken asked us to slow down. The run stops, and the cursor continues next time."""


def _parse_row(row: Any) -> KrakenTrade:
    """A row is [price, volume, time, side, order type, misc, trade id].

    The side is read as the taker's side, which is UNVERIFIED until checked on the approved source. One check:
    within a group of fills sharing one timestamp, a taker's fills walk up in price on `b` and down on `s`.
    """
    if not isinstance(row, list) or len(row) < 7:
        raise ValidationError(f"unexpected Kraken trade row: {str(row)[:100]}")
    try:
        side = row[3]
        if side not in ("b", "s"):
            raise ValidationError(f"unexpected Kraken side: {side!r}")
        price = float(row[0])
        qty = float(row[1])
        if not (math.isfinite(price) and math.isfinite(qty)):
            raise ValidationError("a Kraken price or volume is not a finite number")
        if price <= 0 or qty <= 0:
            raise ValidationError("non-positive Kraken price or volume")
        ts_us = decimal_seconds_to_us(str(row[2]))
        if not _MIN_STAMP_US <= ts_us < _MAX_STAMP_US:
            raise ValidationError(f"a Kraken stamp is out of range: {str(row[2])[:30]}")
        return KrakenTrade(
            trade_id=int(row[6]),
            ts_us=ts_us,
            price=price,
            qty=qty,
            is_taker_buy=side == "b",
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError(f"bad Kraken trade row: {exc}") from exc


def parse_trades_response(body: bytes) -> TradesPage:
    """Parse one response. Times are kept as digits, because a float would blur them."""
    try:
        message = json.loads(body, parse_float=str)
    except ValueError as exc:
        raise ValidationError(f"Kraken response is not JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ValidationError("Kraken response is not an object")
    errors = message.get("error") or []
    if errors:
        text = "; ".join(str(e) for e in errors)
        if "Too many requests" in text or "Rate limit" in text:
            raise RateLimitedError(text)
        if text.startswith("EService"):
            raise FetchError(text)
        raise ValidationError(f"Kraken error: {text}")
    result = message.get("result")
    if not isinstance(result, dict) or "last" not in result:
        raise ValidationError("Kraken response has no result")
    keys = [key for key in result if key != "last"]
    if len(keys) != 1:
        raise ValidationError(f"expected one pair in the Kraken response, found {keys}")
    rows = result[keys[0]]
    if not isinstance(rows, list):
        raise ValidationError("Kraken trades are not a list")
    try:
        cursor = int(result["last"])
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"bad Kraken cursor: {result['last']!r}") from exc
    return TradesPage(tuple(_parse_row(row) for row in rows), cursor, len(rows))


class KrakenClient:
    """Reads public trades. It carries no credentials and has no way to send anything but a GET."""

    def __init__(
        self,
        fetcher: Fetcher,
        config: PollConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher = fetcher
        self._config = config
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def page(self, pair: str, since_ns: int) -> TradesPage:
        if self._last_call is not None:
            wait = self._config.min_interval_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        query = urllib.parse.urlencode(
            {"pair": pair, "since": str(since_ns), "count": self._config.page_size}
        )
        self._last_call = self._clock()
        body = self._fetcher.get_bytes(f"{self._config.base_url}?{query}", _MAX_RESPONSE_BYTES)
        return parse_trades_response(body)


def scheduled_time(cron: str | None, started: dt.datetime) -> dt.datetime | None:
    """The latest cron slot at or before the start, for a cron using only minute and hour.

    GitHub does not report which slot it was running. A run more than one period late is matched to a later
    slot, so the measured delay is a lower bound. missed_slots covers that case from the other side.
    """
    if not cron:
        return None
    fields = cron.split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        return None
    if not all(_CRON_FIELD.match(item) for item in fields[:2]):
        return None

    def values(item: str, top: int) -> list[int]:
        if item == "*":
            return list(range(top))
        if item.startswith("*/"):
            return list(range(0, top, int(item[2:])))
        return [int(item)]

    minutes = values(fields[0], 60)
    hours = values(fields[1], 24)
    moment = started.astimezone(dt.UTC).replace(second=0, microsecond=0)
    for _ in range(60 * 24 + 1):
        if moment.minute in minutes and moment.hour in hours:
            return moment
        moment -= dt.timedelta(minutes=1)
    return None


def cron_period_s(cron: str | None) -> float | None:
    """The interval between slots, for the simple crons this project uses."""
    if not cron:
        return None
    fields = cron.split()
    if len(fields) != 5 or fields[2:] != ["*", "*", "*"]:
        return None
    if fields[1] == "*" and fields[0].isdigit():
        return 3600.0
    if fields[1].isdigit() and fields[0].isdigit():
        return 86_400.0
    return None


@dataclass
class SymbolResult:
    symbol: str
    status: str = "ok"
    pages: int = 0
    new_trades: int = 0
    repeated_rows: int = 0
    late_trades: int = 0
    new_bars: int = 0
    caught_up: bool = False
    last_trade_time: str | None = None
    last_bar_close: str | None = None
    data_age_s: float | None = None
    gaps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    t_poll: str | None = None
    t_cut: str | None = None
    stepped_back: bool = False
    evidence: str | None = None
    data_gap: bool = False
    # No adapter here reads a source's server time, so these say so rather than leave it to be assumed.
    skew_s: float | None = None
    passed_on_server_time: bool = False
    emitted_hash: str | None = None
    # What a rebuild can reproduce, so a later rebuild can be checked against this line of the log. A match
    # proves values only. It never restores a first emission or a receipt time, and nothing in a decision
    # reads it.
    rebuild_digest: str | None = None
    first_close: str | None = None
    last_close: str | None = None
    first_trade_id: int | None = None
    last_trade_id: int | None = None
    bars_left_by_budget: bool = False
    rebuilding: bool = False


# Written down once. Scaled integers and not float text, so a library upgrade cannot read as a mismatch.
REBUILD_DIGEST_PRICE_COLUMNS = ("open", "high", "low", "close")
REBUILD_DIGEST_VOLUME_COLUMNS = (
    "volume",
    "quote_volume",
    "buy_volume",
    "sell_volume",
    "settled_volume",
    "settled_quote_volume",
    "settled_buy_volume",
    "settled_sell_volume",
)
_DIGEST_SCALE = 100_000_000


def rebuild_digest_lines(bars: pl.DataFrame) -> list[str]:
    """One line per bar, in close-time order, holding only what a rebuild from the same trades gives."""

    def scaled(name: str) -> list[str]:
        return ["n" if value is None else str(round(value * _DIGEST_SCALE)) for value in bars[name].to_list()]

    ordered = bars.sort("close_time")
    bars = ordered
    closes = [str(value) for value in ordered["close_time"].dt.timestamp("us").to_list()]
    columns = [
        closes,
        *(scaled(name) for name in (*REBUILD_DIGEST_PRICE_COLUMNS, *REBUILD_DIGEST_VOLUME_COLUMNS)),
    ]
    columns.append([str(value) for value in ordered["trade_count"].to_list()])
    return [",".join(items) for items in zip(*columns, strict=True)]


def _floor_minute(value_us: int) -> int:
    return (value_us // MICROS_PER_MINUTE) * MICROS_PER_MINUTE


def _trades_frame(trades: list[KrakenTrade], venue: str, symbol: str, allowance_us: int) -> pl.DataFrame:
    frame = pl.DataFrame(
        [
            pl.repeat(venue, len(trades), eager=True, dtype=pl.String).alias("venue"),
            pl.repeat(symbol, len(trades), eager=True, dtype=pl.String).alias("symbol"),
            pl.Series("ts", [t.ts_us for t in trades], dtype=pl.Int64).cast(UTC_TIME),
            pl.Series("price", [t.price for t in trades], dtype=pl.Float64),
            pl.Series("qty", [t.qty for t in trades], dtype=pl.Float64),
            pl.Series("is_taker_buy", [t.is_taker_buy for t in trades], dtype=pl.Boolean),
            pl.Series("trade_id", [t.trade_id for t in trades], dtype=pl.Int64),
            pl.Series("file_row", [t.trade_id for t in trades], dtype=pl.Int64),
            pl.repeat(1, len(trades), eager=True, dtype=pl.Int32).alias("n_fills"),
            pl.repeat(False, len(trades), eager=True, dtype=pl.Boolean).alias("is_rpi"),
            # This job can only have known a trade when it received it, usually long after the trade.
            pl.Series(
                "knowable_time",
                [max(t.ts_us + allowance_us, t.received_us) for t in trades],
                dtype=pl.Int64,
            ).cast(UTC_TIME),
        ]
    )
    return frame.select(list(TRADE_SCHEMA))


def _write_trades(
    ctx: JobContext, poll: PollConfig, symbol: str, trades: list[KrakenTrade], allowance_us: int
) -> set[dt.date]:
    """Merge new trades into their day parts. Safe to repeat: rows are unique on trade id, and first receipt
    stands."""
    by_day: dict[dt.date, list[KrakenTrade]] = {}
    for trade in trades:
        by_day.setdefault(date_of_us(trade.ts_us), []).append(trade)
    for day, rows in by_day.items():
        part = ctx.root.curated_part(TRADES_LIVE, poll.venue, symbol, day)
        frame = _trades_frame(rows, poll.venue, symbol, allowance_us)
        if part.is_file():
            frame = pl.concat([read_parquet(part), frame])
        merged = frame.unique(subset=["trade_id"], keep="first", maintain_order=True).sort(["ts", "trade_id"])
        atomic_write_parquet(part, merged, guard=ctx.root.guard)
        ctx.register_output(
            part,
            dataset_id=f"curated.{TRADES_LIVE}.{poll.venue}.{symbol}",
            kind=TRADES_LIVE,
            zone="curated",
            partition_key=day.isoformat(),
            date_start=day.isoformat(),
            date_end=day.isoformat(),
            rows=merged.height,
            check_status="pass",
            source_url=poll.base_url,
            venue=poll.venue,
            symbol=symbol,
            terms_note=ctx.config.source(poll.venue).terms_note,
        )
    return set(by_day)


def _window_trades(ctx: JobContext, poll: PollConfig, symbol: str, day: dt.date) -> pl.DataFrame:
    """Trades for the bars of one day, with the rows that prove continuity at its edges.

    A day's first minute can be proved empty only by the last row before it, and its last by the first row
    after it, however many days away those are. A trade stamped exactly at midnight belongs to the bar ending
    there.
    """
    parts = {
        dt.date.fromisoformat(path.stem.removeprefix("part-")): path
        for path in ctx.root.curated_parts(TRADES_LIVE, poll.venue, symbol)
    }
    high = pl.lit(day_start_us(day) + MICROS_PER_DAY, dtype=pl.Int64).cast(UTC_TIME)
    frames: list[pl.DataFrame] = []
    earlier = [item for item in parts if item < day]
    later = [item for item in parts if item > day]
    if earlier:
        frames.append(read_parquet(parts[max(earlier)]).sort(["ts", "trade_id"]).tail(1))
    if day in parts:
        frames.append(read_parquet(parts[day]))
    if later:
        rows = read_parquet(parts[min(later)]).sort(["ts", "trade_id"])
        frames.extend([rows.filter(pl.col("ts") <= high), rows.head(1)])
    if not frames:
        return pl.DataFrame(schema=TRADE_SCHEMA)
    return pl.concat(frames).unique(subset=["trade_id"], keep="first", maintain_order=True)


def _build_day(
    ctx: JobContext,
    poll: PollConfig,
    symbol: str,
    day: dt.date,
    first_close: int,
    last_close: int,
    received_us: int | None,
    gap_closes: set[int],
) -> pl.DataFrame:
    source = ctx.config.source(poll.venue)
    return build_bars_1m(
        _window_trades(ctx, poll, symbol, day),
        venue=poll.venue,
        symbol=symbol,
        first_close_us=first_close,
        last_close_us=last_close,
        continuity=source.continuity,
        fill_span_allowance_us=source.fill_span_allowance_us,
        received_at_us=received_us,
        gap_close_us=gap_closes,
    )


def rebuild_day_bars(ctx: JobContext, poll: PollConfig, symbol: str, day: dt.date) -> pl.DataFrame:
    """All bars of a day from every stored trade, for comparison with what was emitted.

    It has no knowable_time column, because nobody knew these values at any one time. A bar that says when it
    could be known has to come from the emitted dataset.
    """
    low = day_start_us(day)
    return _build_day(
        ctx,
        poll,
        symbol,
        day,
        low + MICROS_PER_MINUTE,
        low + MICROS_PER_DAY,
        None,
        _stored_gap_closes(ctx, poll, symbol),
    ).drop("knowable_time")


def _stored_gap_closes(ctx: JobContext, poll: PollConfig, symbol: str) -> set[int]:
    """Every minute touched by a recorded hole. The catalog outlives a pass, so a flag does too."""
    closes: set[int] = set()
    for gap in ctx.catalog.gaps(f"curated.{TRADES_LIVE}.{poll.venue}.{symbol}"):
        closes |= closes_between(to_us(parse_iso(gap["start_time"])), to_us(parse_iso(gap["end_time"])))
    return closes


@dataclass(frozen=True)
class _Emission:
    bars: int
    end_us: int
    digest: str | None
    rebuild_digest: str | None
    first_close_us: int | None
    left_by_budget: bool


def _emit_bars(
    ctx: JobContext,
    poll: PollConfig,
    symbol: str,
    after_us: int,
    through_us: int,
    received_us: int,
    *,
    emission: str,
    deadline: float,
    clock: Callable[[], float],
) -> _Emission:
    """Append newly closed minutes to their day parts. Existing rows are never changed.

    It stops between days when the budget ends, always getting through at least one. The rest wait for the
    next pass, which marks them knowable when that pass received them.
    """
    gap_closes = _stored_gap_closes(ctx, poll, symbol)
    digest = hashlib.sha256()
    values = hashlib.sha256()
    first_emitted: int | None = None
    emitted = 0
    end_us = after_us
    first_close = after_us + MICROS_PER_MINUTE
    day = date_of_us(first_close - 1)
    started = False
    while day_start_us(day) < through_us:
        if started and clock() >= deadline:
            return _Emission(
                emitted,
                end_us,
                digest.hexdigest() if emitted else None,
                values.hexdigest() if emitted else None,
                first_emitted,
                True,
            )
        started = True
        low = day_start_us(day)
        start = max(first_close, low + MICROS_PER_MINUTE)
        stop = min(through_us, low + MICROS_PER_DAY)
        if start <= stop:
            new = _build_day(ctx, poll, symbol, day, start, stop, received_us, gap_closes).with_columns(
                pl.lit(emission).alias("emission")
            )
            part = ctx.root.curated_part(BARS_1M_LIVE, poll.venue, symbol, day)
            if part.is_file():
                existing = read_parquet(part)
                new = new.join(existing.select("close_time"), on="close_time", how="anti")
                combined = pl.concat([existing, new]).sort("close_time")
            else:
                combined = new
            atomic_write_parquet(part, combined, guard=ctx.root.guard)
            emitted += new.height
            digest.update(new.write_csv().encode("utf-8"))
            if new.height:
                values.update("\n".join(rebuild_digest_lines(new)).encode("utf-8"))
                values.update(b"\n")
                if first_emitted is None:
                    first_emitted = min(int(v) for v in new["close_time"].dt.timestamp("us").to_list())
            parents = [ctx.relative(ctx.root.curated_part(TRADES_LIVE, poll.venue, symbol, day))]
            _register_bars(ctx, poll, symbol, day, part, BARS_1M_LIVE, combined.height, parents)
            bars_rel = ctx.relative(part)
            for minutes in ctx.config.timeframes_minutes:
                higher = aggregate_bars(combined, minutes, through_close_us=stop)
                dataset = live_dataset(minutes)
                higher_part = ctx.root.curated_part(dataset, poll.venue, symbol, day)
                atomic_write_parquet(higher_part, higher, guard=ctx.root.guard)
                _register_bars(ctx, poll, symbol, day, higher_part, dataset, higher.height, [bars_rel])
            end_us = stop
        day += dt.timedelta(days=1)
    return _Emission(
        emitted,
        end_us,
        digest.hexdigest() if emitted else None,
        values.hexdigest() if emitted else None,
        first_emitted,
        False,
    )


def _register_bars(
    ctx: JobContext,
    poll: PollConfig,
    symbol: str,
    day: dt.date,
    part: Path,
    dataset: str,
    rows: int,
    parents: list[str],
) -> None:
    ctx.register_output(
        part,
        dataset_id=f"curated.{dataset}.{poll.venue}.{symbol}",
        kind=dataset,
        zone="curated",
        partition_key=day.isoformat(),
        date_start=day.isoformat(),
        date_end=day.isoformat(),
        rows=rows,
        check_status="pass",
        parents=parents,
        venue=poll.venue,
        symbol=symbol,
    )


def _record_gap(
    ctx: JobContext,
    poll: PollConfig,
    symbol: str,
    result: SymbolResult,
    start_us: int,
    end_us: int,
    reason: str,
    **detail: Any,
) -> None:
    result.gaps.append(
        {"event": "DATA_GAP", "from": iso_us(start_us), "to": iso_us(end_us), "reason": reason, **detail}
    )
    ctx.catalog.add_gap(
        f"curated.{TRADES_LIVE}.{poll.venue}.{symbol}",
        iso_us(start_us),
        iso_us(end_us),
        reason,
        now=ctx.now_iso(),
        run_id=ctx.run_id,
    )


def _record_correction(ctx: JobContext, symbol: str, trade: KrakenTrade, close_us: int) -> None:
    """A trade received after its minute was emitted. C17's "bars that arrive later" reads this, and no bar
    changes."""
    append_jsonl(
        ctx.root.guard.check(_CORRECTIONS),
        {
            "symbol": symbol,
            "bar_close": iso_us(close_us),
            "trade_id": trade.trade_id,
            "ts": iso_us(trade.ts_us),
            "price": trade.price,
            "qty": trade.qty,
            "is_taker_buy": trade.is_taker_buy,
            "received_at": iso_us(trade.received_us),
            "run_id": ctx.run_id,
        },
        guard=ctx.root.guard,
    )


def poll_symbol(
    ctx: JobContext,
    poll: PollConfig,
    pair: PollPair,
    client: KrakenClient,
    deadline: float,
    clock: Callable[[], float],
    *,
    published_before: bool = False,
) -> SymbolResult:
    """Fetch trades since the cursor, store them, then emit the minutes that are shown to be over."""
    result = SymbolResult(symbol=pair.symbol)
    source = ctx.config.source(poll.venue)
    allowance_us = source.fill_span_allowance_us
    by_ids = source.continuity == "trade_id"
    skew_us = round(ctx.config.max_future_skew_s * MICROS_PER_SECOND)
    state = ctx.catalog.get_poll_state(pair.symbol)
    start_us = day_start_us(poll.start_date)
    cursor_ns = state.cursor_ns if state else start_us * 1000
    last_id = state.last_trade_id if state else None
    emitted_end = state.emitted_end_us if state and state.emitted_end_us is not None else start_us
    last_trade_us = state.last_trade_us if state else None
    # The cache is gone and this has been seen before: what comes out now is not what the runs saw.
    rebuilding = state.rebuilding if state else published_before
    result.rebuilding = rebuilding

    # C17: the clock at the start of the attempt that delivers the data, whatever the attempt then takes.
    t_poll_us = to_us(ctx.now())
    result.t_poll = iso_us(t_poll_us)
    page_received_us = t_poll_us
    now_clock = clock()
    fetch_deadline = now_clock + (deadline - now_clock) * 0.75
    new_trades: list[KrakenTrade] = []
    short_page = False
    try:
        while clock() < fetch_deadline:
            page = client.page(pair.pair, cursor_ns)
            page_received_us = to_us(ctx.now())
            result.pages += 1
            for row in page.trades:
                # A stamp ahead of the clock cannot be real, and would claim minutes that have not happened.
                if row.ts_us > page_received_us + skew_us:
                    raise ValidationError(f"a trade is stamped {iso_us(row.ts_us)}, ahead of the clock")
            fresh = 0
            # In id order, so that a page out of order cannot drop a trade as a repeat.
            for row in sorted(page.trades, key=lambda item: item.trade_id):
                if last_id is not None and row.trade_id <= last_id:
                    result.repeated_rows += 1
                    continue
                trade = replace(row, received_us=page_received_us)
                if by_ids and last_id is not None and trade.trade_id != last_id + 1:
                    _record_gap(
                        ctx,
                        poll,
                        pair.symbol,
                        result,
                        last_trade_us if last_trade_us is not None else trade.ts_us,
                        trade.ts_us,
                        f"trade ids jump from {last_id} to {trade.trade_id}",
                        after_trade_id=last_id,
                        next_trade_id=trade.trade_id,
                    )
                if last_id is None and trade.ts_us > start_us:
                    # Nothing says what happened between the start date and the first row anyone can reach.
                    _record_gap(
                        ctx, poll, pair.symbol, result, start_us, trade.ts_us, "no rows before the first"
                    )
                if trade.ts_us <= emitted_end:
                    result.late_trades += 1
                    close_us = ((trade.ts_us - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE
                    _record_correction(ctx, pair.symbol, trade, close_us)
                last_id = trade.trade_id
                last_trade_us = max(trade.ts_us, last_trade_us or trade.ts_us)
                new_trades.append(trade)
                fresh += 1
            if page.raw_rows and not fresh and page.raw_rows >= poll.page_size:
                raise ValidationError("the cursor made no progress on a full page")
            if page.raw_rows:
                cursor_ns = max(cursor_ns, page.cursor_ns)
            if page.raw_rows < poll.page_size:
                short_page = True
                break
    except FetchError as exc:
        result.status = "failed"
        result.error = str(exc)
    except ValidationError as exc:
        result.status = "failed"
        result.error = f"validation: {exc}"

    if new_trades:
        _write_trades(ctx, poll, pair.symbol, new_trades, allowance_us)
    result.new_trades = len(new_trades)
    if new_trades:
        result.first_trade_id = min(trade.trade_id for trade in new_trades)
        result.last_trade_id = max(trade.trade_id for trade in new_trades)

    # Completeness check of C17. Only a record stamped after the cut shows the data runs through it.
    a_us = round(poll.allowance_a_s * MICROS_PER_SECOND)
    t_cut = _floor_minute(t_poll_us - a_us)
    has_evidence = last_trade_us is not None and last_trade_us > t_cut
    if not has_evidence:
        t_cut -= MICROS_PER_MINUTE
        result.stepped_back = True
        has_evidence = last_trade_us is not None and last_trade_us > t_cut
    result.t_cut = iso_us(t_cut)
    result.evidence = "record" if has_evidence else None
    result.data_gap = not has_evidence
    result.caught_up = short_page and has_evidence

    # A minute is over only if a later record is held. So this can never be past the newest trade.
    through = emitted_end if last_trade_us is None else min(t_cut, _floor_minute(last_trade_us - 1))
    if result.status == "ok" and through > emitted_end:
        emission = _emit_bars(
            ctx,
            poll,
            pair.symbol,
            emitted_end,
            through,
            page_received_us,
            emission=EMISSION_REBUILD if rebuilding else EMISSION_FIRST,
            deadline=deadline,
            clock=clock,
        )
        result.new_bars = emission.bars
        result.emitted_hash = emission.digest
        result.rebuild_digest = emission.rebuild_digest
        if emission.bars:
            result.first_close = None if emission.first_close_us is None else iso_us(emission.first_close_us)
            result.last_close = iso_us(emission.end_us)
        result.bars_left_by_budget = emission.left_by_budget
        emitted_end = emission.end_us
        if emission.left_by_budget:
            result.caught_up = False
    # Once a run has its data through the cut, what comes after it is what the runs see.
    still_rebuilding = rebuilding and not (result.caught_up and result.status == "ok")
    ctx.catalog.set_poll_state(
        PollState(pair.symbol, cursor_ns, last_id, emitted_end, last_trade_us, still_rebuilding),
        now=ctx.now_iso(),
    )
    if last_trade_us is not None:
        result.last_trade_time = iso_us(last_trade_us)
    if emitted_end > start_us:
        result.last_bar_close = iso_us(emitted_end)
        result.data_age_s = round((page_received_us - emitted_end) / MICROS_PER_SECOND, 1)
    return result


def _previous_run(ctx: JobContext) -> dict[str, Any] | None:
    path = ctx.root.poll_log
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if line.strip():
            try:
                parsed: dict[str, Any] = json.loads(line)
                return parsed
            except ValueError:
                continue
    return None


def _state_changes(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    published_before: bool,
    missed_alert: int,
) -> list[str]:
    """What makes this run worth a commit. Ordinary successful hours are not."""
    changes = []
    if previous is None:
        changes.append("cache_lost" if published_before else "first_run")
    else:
        if current["status"] != previous.get("status"):
            changes.append(f"status_{previous.get('status')}_to_{current['status']}")
        if current["caught_up"] != previous.get("caught_up"):
            changes.append("caught_up" if current["caught_up"] else "fell_behind")
    if current["gaps"]:
        changes.append("gap_found")
    if current["watermark_level"] == "critical" and (previous or {}).get("watermark_level") != "critical":
        changes.append("storage_critical")
    before = set((previous or {}).get("data_gap_symbols") or [])
    now_gap = set(current["data_gap_symbols"])
    if now_gap - before:
        changes.append("data_gap_started")
    if before - now_gap:
        changes.append("data_gap_ended")
    if (current.get("missed_slots") or 0) >= missed_alert:
        changes.append("many_slots_missed")
    return changes


def run_poll(
    ctx: JobContext,
    client: KrakenClient,
    *,
    time_budget_s: float | None = None,
    cron: str | None = None,
    job_started_at: dt.datetime | None = None,
    event_name: str | None = None,
    published_before: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """One pass. Logs its timing, so we can measure how late GitHub's schedule really is."""
    poll = ctx.config.poll
    started_at = ctx.now()
    approved = ctx.config.source_usable(poll.venue)
    # A shorter wait than the span would let a run read a bar whose fills are not all in yet.
    if approved and poll.allowance_a_s * 1000.0 < ctx.config.source(poll.venue).fill_span_allowance_ms:
        raise ConfigError("poll.allowance_a_s is shorter than the source's fill span allowance")
    started_clock = clock()
    budget = poll.default_time_budget_s if time_budget_s is None else time_budget_s
    ctx.catalog.start_run(
        ctx.run_id,
        "live_poll",
        now=iso(started_at),
        code_version=code_version(),
        config_hash=ctx.config.config_hash,
    )
    previous = _previous_run(ctx)
    job_start = job_started_at or started_at
    slot = scheduled_time(cron, job_start)
    delay_s = None if slot is None else round((job_start - slot).total_seconds(), 1)
    since_previous_s = None
    missed_slots = None
    if previous is not None:
        previous_start = previous.get("job_started_at")
        if previous_start:
            since_previous_s = round((job_start - parse_iso(previous_start)).total_seconds(), 1)
            period = cron_period_s(cron)
            if period:
                missed_slots = max(0, round(since_previous_s / period) - 1)

    quota = quota_bytes(poll.default_quota_gb)
    used = sum(measure_zones(ctx.root).values())
    watermark = evaluate_watermarks(used, quota, ctx.policy.watermarks)
    results: list[SymbolResult] = []
    # Under the lifecycle, the live record keeps running when storage is short, and the owner is told.
    alerts = list(watermark.alerts)
    if approved:
        for index, pair in enumerate(poll.pairs):
            remaining = budget - (clock() - started_clock)
            share = max(0.0, remaining) / (len(poll.pairs) - index)
            results.append(
                poll_symbol(
                    ctx, poll, pair, client, clock() + share, clock, published_before=published_before
                )
            )

    failed = [r for r in results if r.status != "ok"]
    status = "no_approved_source" if not approved else "failed" if failed else "ok"
    caught_up = bool(results) and all(r.caught_up for r in results)
    gaps = [gap for r in results for gap in r.gaps]
    finished_at = ctx.now()
    record: dict[str, Any] = {
        "run_id": ctx.run_id,
        "kind": "live_poll",
        "event": event_name,
        "cron": cron,
        "scheduled_time": None if slot is None else iso(slot),
        "job_started_at": iso(job_start),
        "poll_started_at": iso(started_at),
        "finished_at": iso(finished_at),
        "delay_s": delay_s,
        "since_previous_run_s": since_previous_s,
        "missed_slots": missed_slots,
        "duration_s": round((finished_at - started_at).total_seconds(), 1),
        "status": status,
        "data_kind": "SYNTHETIC" if ctx.root.is_synthetic else "MARKET" if approved else "NONE",
        "source_state": ctx.config.source_state(),
        "caught_up": caught_up,
        "gaps": gaps,
        # DATA_GAP in the sense of C17: this run has no evidence its data is complete through its cut.
        "data_gap_symbols": [r.symbol for r in results if r.data_gap],
        "symbols": {r.symbol: asdict(r) for r in results},
        "storage_used_pct": watermark.used_pct,
        "watermark_level": watermark.level,
        "alerts": alerts,
        "code_version": code_version(),
    }
    record["state_changes"] = _state_changes(record, previous, published_before, poll.missed_slots_alert)
    append_jsonl(ctx.root.poll_log, record, guard=ctx.root.guard)
    atomic_write_json(
        ctx.root.guard.check("catalog/live_state.json"), _live_state(record), guard=ctx.root.guard
    )
    write_heartbeat(ctx.root, "live_poll", now=finished_at, detail={"status": status, "run_id": ctx.run_id})
    ctx.catalog.finish_run(
        ctx.run_id,
        now=iso(finished_at),
        # With nothing approved, nothing was tried, so nothing failed.
        status=status,
        summary={"status": status, "caught_up": caught_up},
    )
    return record


def _live_state(record: dict[str, Any]) -> dict[str, Any]:
    """The small file published on a state change. It holds no prices."""
    return {
        "updated_at": record["finished_at"],
        "run_id": record["run_id"],
        "status": record["status"],
        "data_kind": record["data_kind"],
        "caught_up": record["caught_up"],
        "state_changes": record["state_changes"],
        "symbols": {
            symbol: {
                "last_bar_close": item["last_bar_close"],
                "data_age_s": item["data_age_s"],
                "status": item["status"],
            }
            for symbol, item in record["symbols"].items()
        },
    }


def read_poll_log(*paths: Any) -> list[dict[str, Any]]:
    """Merge run logs from several places, such as the cache and the results branch, keeping one per run."""
    seen: dict[str, dict[str, Any]] = {}
    for path in paths:
        if path is None or not Path(path).is_file():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and "run_id" in item:
                seen.setdefault(str(item["run_id"]), item)
    return sorted(seen.values(), key=lambda row: str(row.get("job_started_at", "")))
