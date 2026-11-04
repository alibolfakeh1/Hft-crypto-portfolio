"""Hourly poll of closed trades from Kraken's public REST API, with a `since` cursor.

Short, and never a loop: one pass per scheduled run, then the job ends. A late or missed run loses nothing,
because the cursor catches up from where it stopped.

This adapter is disabled until its source is approved. With no approved source it contacts nothing and records
that fact. How it treats the API, which must be checked again against the source once approved:
- The cursor is inclusive. Each page starts by repeating the last trade of the page before, and trades can
  share one timestamp, so rows are deduplicated on trade id. Trade ids are expected to run without gaps.
- A lost cache rebuilds by starting the cursor over from the configured start date.

Bars use the same code as the historical path, with two differences that keep the timing contract honest:
- A bar is knowable when this job received it, not when it closed, because this job is the only way a paper
  engine on GitHub could have it. That is usually about an hour after the close.
- A bar, once emitted, is never rewritten. A trade arriving after its minute was emitted is counted as late,
  and the daily check against a rebuild from all stored trades reports the difference.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.core import UTC_TIME, aggregate_bars, build_bars_1m
from hft_crypto.config import PollConfig, PollPair, quota_bytes
from hft_crypto.data.atomic import append_jsonl, atomic_write_json, atomic_write_parquet, read_parquet
from hft_crypto.data.catalog import PollState
from hft_crypto.data.context import JobContext, write_heartbeat
from hft_crypto.data.derive import BARS_1M, TRADES, timeframe_dataset
from hft_crypto.data.fetch import Fetcher, FetchError
from hft_crypto.data.health import measure_zones
from hft_crypto.data.parsers import TRADE_SCHEMA, ValidationError
from hft_crypto.data.retention import evaluate_watermarks
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
        if price <= 0 or qty <= 0:
            raise ValidationError("non-positive Kraken price or volume")
        return KrakenTrade(
            trade_id=int(row[6]),
            ts_us=decimal_seconds_to_us(str(row[2])),
            price=price,
            qty=qty,
            is_taker_buy=side == "b",
        )
    except (TypeError, ValueError) as exc:
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


def _trades_frame(trades: list[KrakenTrade], venue: str, symbol: str) -> pl.DataFrame:
    ts = pl.Series("ts", [t.ts_us for t in trades], dtype=pl.Int64).cast(UTC_TIME)
    frame = pl.DataFrame(
        [
            pl.repeat(venue, len(trades), eager=True, dtype=pl.String).alias("venue"),
            pl.repeat(symbol, len(trades), eager=True, dtype=pl.String).alias("symbol"),
            ts,
            pl.Series("price", [t.price for t in trades], dtype=pl.Float64),
            pl.Series("qty", [t.qty for t in trades], dtype=pl.Float64),
            pl.Series("is_taker_buy", [t.is_taker_buy for t in trades], dtype=pl.Boolean),
            pl.Series("trade_id", [t.trade_id for t in trades], dtype=pl.Int64),
            pl.repeat(1, len(trades), eager=True, dtype=pl.Int32).alias("n_fills"),
            pl.repeat(False, len(trades), eager=True, dtype=pl.Boolean).alias("is_rpi"),
            # This job can only have known a trade when it received it, usually long after the trade.
            pl.Series("knowable_time", [t.received_us for t in trades], dtype=pl.Int64).cast(UTC_TIME),
        ]
    )
    return frame.select(list(TRADE_SCHEMA))


def _write_trades(ctx: JobContext, poll: PollConfig, symbol: str, trades: list[KrakenTrade]) -> set[dt.date]:
    """Merge new trades into their day parts. Safe to repeat: rows are unique on trade id."""
    by_day: dict[dt.date, list[KrakenTrade]] = {}
    for trade in trades:
        by_day.setdefault(date_of_us(trade.ts_us), []).append(trade)
    for day, rows in by_day.items():
        part = ctx.root.curated_part(TRADES, poll.venue, symbol, day)
        frame = _trades_frame(rows, poll.venue, symbol)
        if part.is_file():
            frame = pl.concat([read_parquet(part), frame])
        merged = frame.unique(subset=["trade_id"], keep="first").sort(["ts", "trade_id"])
        atomic_write_parquet(part, merged, guard=ctx.root.guard)
        ctx.register_output(
            part,
            dataset_id=f"curated.{TRADES}.{poll.venue}.{symbol}",
            kind=TRADES,
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
    """Trades in the (day 00:00, next day 00:00] bar window, from the day's part and the next one."""
    low = day_start_us(day)
    high = low + MICROS_PER_DAY
    low_time = pl.lit(low, dtype=pl.Int64).cast(UTC_TIME)
    high_time = pl.lit(high, dtype=pl.Int64).cast(UTC_TIME)
    frames = []
    for candidate in (day, day + dt.timedelta(days=1)):
        part = ctx.root.curated_part(TRADES, poll.venue, symbol, candidate)
        if part.is_file():
            frames.append(read_parquet(part).filter((pl.col("ts") > low_time) & (pl.col("ts") <= high_time)))
    if not frames:
        return pl.DataFrame(schema=TRADE_SCHEMA)
    return pl.concat(frames)


def rebuild_day_bars(ctx: JobContext, poll: PollConfig, symbol: str, day: dt.date) -> pl.DataFrame:
    """All bars of a day rebuilt from stored trades. Used by the daily check against the emitted ones."""
    low = day_start_us(day)
    return build_bars_1m(
        _window_trades(ctx, poll, symbol, day),
        venue=poll.venue,
        symbol=symbol,
        first_close_us=low + MICROS_PER_MINUTE,
        last_close_us=low + MICROS_PER_DAY,
    )


def _emit_bars(
    ctx: JobContext,
    poll: PollConfig,
    symbol: str,
    after_us: int,
    through_us: int,
    received_us: int,
    gap_closes: set[int],
) -> int:
    """Append newly closed minutes to their day parts. Existing rows are never changed."""
    emitted = 0
    first_close = after_us + MICROS_PER_MINUTE
    day = date_of_us(first_close - 1)
    while day_start_us(day) < through_us:
        low = day_start_us(day)
        start = max(first_close, low + MICROS_PER_MINUTE)
        stop = min(through_us, low + MICROS_PER_DAY)
        if start <= stop:
            new = build_bars_1m(
                _window_trades(ctx, poll, symbol, day),
                venue=poll.venue,
                symbol=symbol,
                first_close_us=start,
                last_close_us=stop,
                knowable_at_us=received_us,
                gap_close_us=gap_closes,
            )
            part = ctx.root.curated_part(BARS_1M, poll.venue, symbol, day)
            if part.is_file():
                existing = read_parquet(part)
                new = new.join(existing.select("close_time"), on="close_time", how="anti")
                combined = pl.concat([existing, new]).sort("close_time")
            else:
                combined = new
            atomic_write_parquet(part, combined, guard=ctx.root.guard)
            emitted += new.height
            parents = [ctx.relative(ctx.root.curated_part(TRADES, poll.venue, symbol, day))]
            _register_bars(ctx, poll, symbol, day, part, BARS_1M, combined.height, parents)
            bars_rel = ctx.relative(part)
            for minutes in ctx.config.timeframes_minutes:
                higher = aggregate_bars(combined, minutes)
                dataset = timeframe_dataset(minutes)
                higher_part = ctx.root.curated_part(dataset, poll.venue, symbol, day)
                atomic_write_parquet(higher_part, higher, guard=ctx.root.guard)
                _register_bars(ctx, poll, symbol, day, higher_part, dataset, higher.height, [bars_rel])
        day += dt.timedelta(days=1)
    return emitted


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


def poll_symbol(
    ctx: JobContext,
    poll: PollConfig,
    pair: PollPair,
    client: KrakenClient,
    deadline: float,
    clock: Callable[[], float],
) -> SymbolResult:
    """Fetch trades since the cursor, store them, then emit the minutes that have closed."""
    result = SymbolResult(symbol=pair.symbol)
    state = ctx.catalog.get_poll_state(pair.symbol)
    start_us = day_start_us(poll.start_date)
    cursor_ns = state.cursor_ns if state else start_us * 1000
    last_id = state.last_trade_id if state else None
    emitted_end = state.emitted_end_us if state and state.emitted_end_us is not None else start_us
    last_trade_us = state.last_trade_us if state else None

    new_trades: list[KrakenTrade] = []
    gap_closes: set[int] = set()
    try:
        while clock() < deadline:
            page = client.page(pair.pair, cursor_ns)
            page_received_us = to_us(ctx.now())
            result.pages += 1
            fresh = [
                replace(t, received_us=page_received_us)
                for t in page.trades
                if last_id is None or t.trade_id > last_id
            ]
            result.repeated_rows += len(page.trades) - len(fresh)
            for trade in fresh:
                if last_id is not None and trade.trade_id != last_id + 1:
                    gap_to = iso_us(trade.ts_us)
                    gap_from = iso_us(last_trade_us) if last_trade_us else gap_to
                    result.gaps.append(
                        {
                            "event": "DATA_GAP",
                            "after_trade_id": last_id,
                            "next_trade_id": trade.trade_id,
                            "from": gap_from,
                            "to": gap_to,
                        }
                    )
                    ctx.catalog.add_gap(
                        f"curated.{TRADES}.{poll.venue}.{pair.symbol}",
                        gap_from,
                        gap_to,
                        f"trade ids jump from {last_id} to {trade.trade_id}",
                        now=ctx.now_iso(),
                        run_id=ctx.run_id,
                    )
                    low = last_trade_us if last_trade_us is not None else trade.ts_us
                    close = ((low - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE
                    while close <= ((trade.ts_us - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE:
                        gap_closes.add(close)
                        close += MICROS_PER_MINUTE
                if trade.ts_us <= emitted_end:
                    result.late_trades += 1
                last_id = trade.trade_id
                last_trade_us = trade.ts_us
            new_trades.extend(fresh)
            if page.raw_rows and not fresh and page.raw_rows >= poll.page_size:
                raise ValidationError("the cursor made no progress on a full page")
            if page.raw_rows:
                cursor_ns = max(cursor_ns, page.cursor_ns)
            if page.raw_rows < poll.page_size:
                result.caught_up = True
                break
    except FetchError as exc:
        result.status = "failed"
        result.error = str(exc)
    except ValidationError as exc:
        result.status = "failed"
        result.error = f"validation: {exc}"

    if new_trades:
        _write_trades(ctx, poll, pair.symbol, new_trades)
    received_us = to_us(ctx.now())
    result.new_trades = len(new_trades)

    if result.caught_up:
        grace_us = int(poll.bar_grace_s * MICROS_PER_SECOND)
        safe_end = ((received_us - grace_us) // MICROS_PER_MINUTE) * MICROS_PER_MINUTE
    elif last_trade_us is not None:
        # Not caught up: only minutes that end before the newest trade we hold are known to be complete.
        safe_end = ((last_trade_us - 1) // MICROS_PER_MINUTE) * MICROS_PER_MINUTE
    else:
        safe_end = emitted_end
    if result.status == "ok" and safe_end > emitted_end:
        result.new_bars = _emit_bars(ctx, poll, pair.symbol, emitted_end, safe_end, received_us, gap_closes)
        emitted_end = safe_end

    ctx.catalog.set_poll_state(
        PollState(pair.symbol, cursor_ns, last_id, emitted_end, last_trade_us), now=ctx.now_iso()
    )
    if last_trade_us is not None:
        result.last_trade_time = iso_us(last_trade_us)
    if emitted_end > start_us:
        result.last_bar_close = iso_us(emitted_end)
        result.data_age_s = round((received_us - emitted_end) / MICROS_PER_SECOND, 1)
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
    approved = ctx.config.source(poll.venue).enabled
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
    blocked = watermark.level == "critical"
    if approved and not blocked:
        for index, pair in enumerate(poll.pairs):
            remaining = budget - (clock() - started_clock)
            share = max(0.0, remaining) / (len(poll.pairs) - index)
            results.append(poll_symbol(ctx, poll, pair, client, clock() + share, clock))

    failed = [r for r in results if r.status != "ok"]
    status = "no_approved_source" if not approved else "blocked" if blocked else "failed" if failed else "ok"
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
        "source_state": ctx.config.source_state(),
        "caught_up": caught_up,
        "gaps": gaps,
        "symbols": {r.symbol: asdict(r) for r in results},
        "storage_used_pct": watermark.used_pct,
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
        status="ok" if status == "ok" else "failed",
        summary={"status": status, "caught_up": caught_up},
    )
    return record


def _live_state(record: dict[str, Any]) -> dict[str, Any]:
    """The small file published on a state change. It holds no prices."""
    return {
        "updated_at": record["finished_at"],
        "run_id": record["run_id"],
        "status": record["status"],
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
