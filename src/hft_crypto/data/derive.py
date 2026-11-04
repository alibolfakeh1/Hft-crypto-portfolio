"""Curated bars for one UTC day: canonical one-minute bars, higher timeframes and reconciliation.

A bar covers (open, close], while a delivered file covers its UTC day [00:00, 24:00). So the bar ending at
midnight can need a trade stamped exactly 00:00:00.000 from the next day's file. Until that file exists, the
last bar of the day is flagged gap=True, the day stays provisional, and a later run rebuilds it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import polars as pl

from hft_crypto.bars.core import UTC_TIME, aggregate_bars, build_bars_1m
from hft_crypto.bars.reconcile import STATUS_FAIL, STATUS_WARN, reconcile_official
from hft_crypto.data.atomic import atomic_write_parquet, read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.timeutil import MICROS_PER_DAY, MICROS_PER_MINUTE, day_start_us, iso

TRADES = "trades"
BARS_1M = "bars_1m"
OFFICIAL = "candles_official"

STATE_DONE = "done"
STATE_PROVISIONAL = "provisional"
STATE_FAILED = "failed"
STATE_PENDING = "pending"


def timeframe_dataset(minutes: int) -> str:
    """Return the dataset name for a timeframe: 5 gives bars_5m, 60 bars_1h, 1440 bars_1d."""
    if minutes == 1:
        return BARS_1M
    if minutes % 1440 == 0:
        return f"bars_{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"bars_{minutes // 60}h"
    return f"bars_{minutes}m"


def derive_task_key(venue: str, symbol: str, day: dt.date) -> str:
    return f"derive:{venue}:{symbol}:{day.isoformat()}"


def derive_dataset_id(venue: str) -> str:
    return f"derived.bars.{venue}"


@dataclass(frozen=True)
class DeriveOutcome:
    state: str
    bars_rows: int
    reconciliation: dict[str, Any] | None
    reason: str | None = None


def _neighbour_rows(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, low: int, high: int
) -> tuple[pl.DataFrame | None, str | None]:
    """Rows from another day's file that belong in the (low, high] window."""
    part = ctx.root.curated_part(TRADES, venue, symbol, day)
    if not part.is_file():
        return None, None
    low_time = pl.lit(low, dtype=pl.Int64).cast(UTC_TIME)
    high_time = pl.lit(high, dtype=pl.Int64).cast(UTC_TIME)
    rows = read_parquet(part).filter((pl.col("ts") > low_time) & (pl.col("ts") <= high_time))
    return rows, ctx.relative(part)


def load_day_window(
    ctx: JobContext, venue: str, symbol: str, day: dt.date
) -> tuple[pl.DataFrame, pl.DataFrame, list[str], bool]:
    """Return the file's own trades, the bar window's trades, their parents, and next-day availability."""
    part = ctx.root.curated_part(TRADES, venue, symbol, day)
    file_trades = read_parquet(part)
    low = day_start_us(day)
    high = low + MICROS_PER_DAY
    low_time = pl.lit(low, dtype=pl.Int64).cast(UTC_TIME)
    high_time = pl.lit(high, dtype=pl.Int64).cast(UTC_TIME)
    frames = [file_trades.filter((pl.col("ts") > low_time) & (pl.col("ts") <= high_time))]
    parents = [ctx.relative(part)]
    next_rows, next_parent = _neighbour_rows(ctx, venue, symbol, day + dt.timedelta(days=1), low, high)
    next_available = next_rows is not None
    if next_rows is not None and next_parent is not None:
        frames.append(next_rows)
        parents.append(next_parent)
    previous_rows, previous_parent = _neighbour_rows(
        ctx, venue, symbol, day - dt.timedelta(days=1), low, high
    )
    if previous_rows is not None and previous_parent is not None and previous_rows.height:
        frames.append(previous_rows)
        parents.append(previous_parent)
    window = pl.concat(frames).unique(subset=["ts", "trade_id", "price", "qty"], keep="first")
    return file_trades, window, parents, next_available


def _remove_day_outputs(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> None:
    """A day that failed its checks must not stay readable under curated, so its bars move to quarantine."""
    stamp = ctx.now().strftime("%Y%m%dT%H%M%SZ")
    for dataset in [BARS_1M, *(timeframe_dataset(m) for m in ctx.config.timeframes_minutes)]:
        part = ctx.root.curated_part(dataset, venue, symbol, day)
        if part.is_file():
            target = ctx.root.quarantine_path(ctx.relative(part), stamp)
            target.parent.mkdir(parents=True, exist_ok=True)
            part.replace(target)
            ctx.catalog.set_file_status(ctx.relative(part), "quarantined", ctx.now_iso())


def derive_day(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> DeriveOutcome:
    """Build and check all bars of one day. Running it twice gives the same files."""
    file_trades, window, parents, next_available = load_day_window(ctx, venue, symbol, day)
    low = day_start_us(day)
    last_close = low + MICROS_PER_DAY
    bars = build_bars_1m(
        window,
        venue=venue,
        symbol=symbol,
        first_close_us=low + MICROS_PER_MINUTE,
        last_close_us=last_close,
        gap_close_us=None if next_available else {last_close},
    )

    reconciliation: dict[str, Any] | None = None
    status = "pass"
    reasons: list[str] = []
    official_part = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
    tolerance = ctx.config.reconcile.get(symbol)
    needs_official = ctx.config.has_official_candles(venue)
    if needs_official and official_part.is_file() and tolerance is not None:
        official = read_parquet(official_part)
        previous_part = ctx.root.curated_part(TRADES, venue, symbol, day - dt.timedelta(days=1))
        previous_tail = None
        if previous_part.is_file():
            # Only the end of that file matters, and it is what a carry across midnight came from.
            tail_from = pl.lit(low - 60_000_000, dtype=pl.Int64).cast(UTC_TIME)
            previous_tail = read_parquet(previous_part).filter(pl.col("ts") >= tail_from)
            parents.append(ctx.relative(previous_part))
        result = reconcile_official(file_trades, bars, official, tolerance, previous_tail=previous_tail)
        reconciliation = result.to_dict()
        ctx.catalog.put_reconciliation(
            "official_candles",
            venue,
            symbol,
            day.isoformat(),
            result.status,
            reconciliation,
            now=ctx.now_iso(),
        )
        parents.append(ctx.relative(official_part))
        if result.status == STATUS_FAIL:
            _remove_day_outputs(ctx, venue, symbol, day)
            return DeriveOutcome(STATE_FAILED, bars.height, reconciliation, "; ".join(result.reasons))
        if result.status == STATUS_WARN:
            status = STATUS_WARN
            reasons.extend(result.reasons)
    open_carry = bool(reconciliation and reconciliation["needs_previous_day"])
    provisional = not next_available or (needs_official and reconciliation is None) or open_carry
    detail = {
        "final_boundary": next_available,
        "reconciled": reconciliation is not None,
        "needs_previous_day": open_carry,
        "reasons": reasons,
    }
    check_status = "provisional" if provisional else status
    bars_part = ctx.root.curated_part(BARS_1M, venue, symbol, day)
    atomic_write_parquet(bars_part, bars, guard=ctx.root.guard)
    day_text = day.isoformat()
    ctx.register_output(
        bars_part,
        dataset_id=f"curated.{BARS_1M}.{venue}.{symbol}",
        kind=BARS_1M,
        zone="curated",
        partition_key=day_text,
        date_start=day_text,
        date_end=day_text,
        rows=bars.height,
        check_status=check_status,
        check_detail=detail,
        parents=parents,
        venue=venue,
        symbol=symbol,
        tier="T1",
    )
    bars_rel = ctx.relative(bars_part)
    for minutes in ctx.config.timeframes_minutes:
        higher = aggregate_bars(bars, minutes)
        dataset = timeframe_dataset(minutes)
        part = ctx.root.curated_part(dataset, venue, symbol, day)
        atomic_write_parquet(part, higher, guard=ctx.root.guard)
        ctx.register_output(
            part,
            dataset_id=f"curated.{dataset}.{venue}.{symbol}",
            kind=dataset,
            zone="curated",
            partition_key=day_text,
            date_start=day_text,
            date_end=day_text,
            rows=higher.height,
            check_status=check_status,
            check_detail=detail,
            parents=[bars_rel],
            venue=venue,
            symbol=symbol,
            tier="T1",
        )
    return DeriveOutcome(STATE_PROVISIONAL if provisional else STATE_DONE, bars.height, reconciliation)


def needs_derive(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> bool:
    """Decide whether a day's bars must be (re)built, given what exists now."""
    if not ctx.root.curated_part(TRADES, venue, symbol, day).is_file():
        return False
    task = ctx.catalog.get_task(derive_task_key(venue, symbol, day))
    bars_part = ctx.root.curated_part(BARS_1M, venue, symbol, day)
    if task is None or task.state == STATE_PENDING:
        return True
    if task.state == STATE_FAILED:
        return task.next_retry_at is None or task.next_retry_at <= iso(ctx.now())
    if not bars_part.is_file():
        return True
    if task.state == STATE_PROVISIONAL:
        record = ctx.catalog.get_file(ctx.relative(bars_part))
        detail = record.check_detail if record and record.check_detail else {}
        next_part = ctx.root.curated_part(TRADES, venue, symbol, day + dt.timedelta(days=1))
        if not detail.get("final_boundary") and next_part.is_file():
            return True
        previous_part = ctx.root.curated_part(TRADES, venue, symbol, day - dt.timedelta(days=1))
        if detail.get("needs_previous_day") and previous_part.is_file():
            return True
        official = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
        return bool(not detail.get("reconciled") and official.is_file())
    return False
