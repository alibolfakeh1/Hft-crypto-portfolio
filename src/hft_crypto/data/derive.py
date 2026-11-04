"""Curated bars for one UTC day: canonical one-minute bars, higher timeframes and reconciliation.

A bar covers (open, close], while a delivered file covers its UTC day [00:00, 24:00). So the bar ending at
midnight can need a trade stamped exactly 00:00:00.000 from the next day's file, and a minute's proof of
continuity can need the rows on either side of midnight. Until the next file exists, the last bar of the day
is flagged gap=True, the day stays provisional, and a later run rebuilds it.

A day that fails a check keeps its bars. They are flagged from the first minute the check cannot explain,
which is the only way to make sure a minute's standing does not depend on what happened later in the day. Each
such day is logged as an exclusion, counted in every result, and fetched again later in case a good file has
been published.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import polars as pl

from hft_crypto.bars.core import (
    UTC_TIME,
    aggregate_bars,
    build_bars_1m,
    closes_between,
    find_id_skips,
    find_long_quiets,
)
from hft_crypto.bars.reconcile import STATUS_FAIL, STATUS_WARN, DayFlow, reconcile_official
from hft_crypto.config import DatasetSpec
from hft_crypto.data.atomic import append_jsonl, atomic_write_parquet, read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.parsers import ValidationError
from hft_crypto.timeutil import (
    MICROS_PER_DAY,
    MICROS_PER_MINUTE,
    MICROS_PER_SECOND,
    day_start_us,
    iso,
    iso_us,
)

TRADES = "trades"
BARS_1M = "bars_1m"
OFFICIAL = "candles_official"
CHECK_OFFICIAL = "official_candles"

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


def _time(value_us: int) -> pl.Expr:
    return pl.lit(value_us, dtype=pl.Int64).cast(UTC_TIME)


def load_day_window(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, *, allowance_us: int
) -> tuple[pl.DataFrame, pl.DataFrame, list[str], bool, pl.DataFrame | None]:
    """Return the file's own trades, the rows the bars need, their parents, next-day availability and the
    prior tail.

    Beyond the bar window, the rows hold the previous file's last row and the next file's first row, because
    those prove continuity at the day's edges, and any row just before the day that could carry into its first
    bar.
    """
    part = ctx.root.curated_part(TRADES, venue, symbol, day)
    file_trades = read_parquet(part)
    low = day_start_us(day)
    high = low + MICROS_PER_DAY
    frames = [file_trades]
    parents = [ctx.relative(part)]
    previous_tail: pl.DataFrame | None = None

    previous_part = ctx.root.curated_part(TRADES, venue, symbol, day - dt.timedelta(days=1))
    if previous_part.is_file():
        rows = read_parquet(previous_part)
        tail_from = low - max(allowance_us, MICROS_PER_MINUTE)
        strays_or_tail = rows.filter(pl.col("ts") > _time(tail_from))
        last_row = rows.sort(["ts", "trade_id", "file_row"], maintain_order=True).tail(1)
        previous_tail = strays_or_tail
        frames.extend([strays_or_tail, last_row])
        parents.append(ctx.relative(previous_part))
    next_part = ctx.root.curated_part(TRADES, venue, symbol, day + dt.timedelta(days=1))
    next_available = next_part.is_file()
    if next_available:
        rows = read_parquet(next_part)
        strays = rows.filter(pl.col("ts") <= _time(high))
        first_row = rows.sort(["ts", "trade_id", "file_row"], maintain_order=True).head(1)
        frames.extend([strays, first_row])
        parents.append(ctx.relative(next_part))
    combined = pl.concat(frames)
    if combined["trade_id"].null_count() == 0:
        # The same trade delivered by two files counts once, whichever day it is in.
        window = combined.unique(subset=["trade_id"], keep="first", maintain_order=True)
    else:
        window = combined.unique(subset=["ts", "file_row", "price", "qty"], keep="first", maintain_order=True)
    return file_trades, window, parents, next_available, previous_tail


def _refuse_rows_from_another_path(trades: pl.DataFrame, allowance_us: int) -> None:
    """Rows received later than their stamp plus the allowance came from the poll, and must keep their
    receipt."""
    latest = (trades["knowable_time"].dt.timestamp("us") - trades["ts"].dt.timestamp("us")).max()
    if latest is not None and int(str(latest)) > allowance_us:
        raise ValidationError(
            "these rows were received after their stamp, so archive bars cannot be built from them"
        )


def _trade_spec(ctx: JobContext, venue: str) -> DatasetSpec | None:
    for spec in ctx.config.datasets:
        if spec.venue == venue and spec.curated == TRADES:
            return spec
    return None


def _neighbour_flow(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> DayFlow | None:
    row = ctx.catalog.get_reconciliation(CHECK_OFFICIAL, venue, symbol, day.isoformat())
    return None if row is None else DayFlow.from_detail(row["detail"])


def _is_first_day(spec: DatasetSpec | None, day: dt.date) -> bool:
    return spec is not None and day <= spec.start


def _record_holes(
    ctx: JobContext, venue: str, symbol: str, window: pl.DataFrame, day: dt.date, spec: DatasetSpec | None
) -> tuple[set[int], list[str]]:
    """Record every hole the rows themselves show. Return the minutes to flag, and what to say about them."""
    low = day_start_us(day)
    high = low + MICROS_PER_DAY
    dataset = f"curated.{TRADES}.{venue}.{symbol}"
    closes: set[int] = set()
    notes: list[str] = []
    for skip in find_id_skips(window):
        if skip.to_us <= low or skip.from_us > high:
            continue
        ctx.catalog.add_gap(
            dataset,
            iso_us(skip.from_us),
            iso_us(skip.to_us),
            f"trade ids jump from {skip.after_id} to {skip.next_id}",
            now=ctx.now_iso(),
            run_id=ctx.run_id,
        )
        notes.append(f"trade ids jump from {skip.after_id} to {skip.next_id}")
    if spec is not None and spec.max_quiet_s is not None:
        for start, end in find_long_quiets(window, round(spec.max_quiet_s * MICROS_PER_SECOND)):
            if end <= low or start > high:
                continue
            # From the bar after the last row. That bar's standing cannot depend on how long the silence went
            # on.
            closes |= closes_between(start, end) - closes_between(start, start)
            ctx.catalog.add_gap(
                dataset,
                iso_us(start),
                iso_us(end),
                f"no trades for more than {spec.max_quiet_s:g} s",
                now=ctx.now_iso(),
                run_id=ctx.run_id,
            )
            notes.append(f"no trades from {iso_us(start)} to {iso_us(end)}")
    return closes, notes


def _record_exclusion(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, reason: str, window_ms: float | None
) -> None:
    """A day left out of results is logged, once per reason, in a file that is only appended to."""
    if ctx.catalog.add_exclusion(venue, symbol, day.isoformat(), reason, window_ms, now=ctx.now_iso()):
        append_jsonl(
            ctx.root.guard.check("catalog/exclusions.jsonl"),
            {
                "time": ctx.now_iso(),
                "venue": venue,
                "symbol": symbol,
                "date": day.isoformat(),
                "reason": reason,
                "boundary_window_ms": window_ms,
                "data_kind": "SYNTHETIC" if ctx.root.is_synthetic else "MARKET",
            },
            guard=ctx.root.guard,
        )


def derive_day(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> DeriveOutcome:
    """Build and check all bars of one day. Running it twice gives the same files."""
    key = derive_task_key(venue, symbol, day)
    # Before the first write, so that a crash during a rebuild leaves a day that is rebuilt, not one that
    # looks done.
    ctx.catalog.set_task(
        key,
        dataset_id=derive_dataset_id(venue),
        symbol=symbol,
        partition_key=day.isoformat(),
        state=STATE_PENDING,
        now=ctx.now_iso(),
    )
    source = ctx.config.source(venue)
    allowance_us = source.fill_span_allowance_us
    spec = _trade_spec(ctx, venue)
    file_trades, window, parents, next_available, previous_tail = load_day_window(
        ctx, venue, symbol, day, allowance_us=allowance_us
    )
    _refuse_rows_from_another_path(window, allowance_us)
    low = day_start_us(day)
    first_close = low + MICROS_PER_MINUTE
    last_close = low + MICROS_PER_DAY
    gap_closes, hole_notes = _record_holes(ctx, venue, symbol, window, day, spec)
    if not next_available:
        gap_closes.add(last_close)

    def build(extra: set[int]) -> pl.DataFrame:
        return build_bars_1m(
            window,
            venue=venue,
            symbol=symbol,
            first_close_us=first_close,
            last_close_us=last_close,
            continuity=source.continuity,
            fill_span_allowance_us=allowance_us,
            received_at_us=None,
            gap_close_us=gap_closes | extra,
        )

    bars = build(set())
    reconciliation: dict[str, Any] | None = None
    reasons: list[str] = list(hole_notes)
    failed = False
    warned = bool(hole_notes)
    official_part = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
    tolerance = ctx.config.reconcile.get(symbol)
    needs_official = ctx.config.has_official_candles(venue)
    open_neighbours = False
    if needs_official and official_part.is_file() and tolerance is not None:
        official = read_parquet(official_part)
        is_first = _is_first_day(spec, day)
        result = reconcile_official(
            file_trades,
            bars,
            official,
            tolerance,
            previous_tail=previous_tail,
            previous_flow=_neighbour_flow(ctx, venue, symbol, day - dt.timedelta(days=1)),
            next_flow=_neighbour_flow(ctx, venue, symbol, day + dt.timedelta(days=1)),
            is_first_day=is_first,
        )
        reconciliation = result.to_dict()
        before = ctx.catalog.get_reconciliation(CHECK_OFFICIAL, venue, symbol, day.isoformat())
        if before is not None and DayFlow.from_detail(before["detail"]) != DayFlow.from_detail(
            reconciliation
        ):
            # The neighbours judged this day by the old figures, so they have to look again.
            for neighbour in (day - dt.timedelta(days=1), day + dt.timedelta(days=1)):
                reopen_day(ctx, venue, symbol, neighbour)
        ctx.catalog.put_reconciliation(
            CHECK_OFFICIAL,
            venue,
            symbol,
            day.isoformat(),
            result.status,
            reconciliation,
            now=ctx.now_iso(),
        )
        parents.append(ctx.relative(official_part))
        open_neighbours = result.needs_previous_day or result.needs_next_day
        reasons.extend(result.reasons)
        failed = result.status == STATUS_FAIL
        warned = warned or result.status == STATUS_WARN
        # Ruling 2 of the leak audit. If a row ran longer than declared, the allowance is false. It says so,
        # and that does not remove the day.
        if result.largest_window_needed_ms > source.fill_span_allowance_ms:
            warned = True
            reasons.append(
                f"a row ran {result.largest_window_needed_ms} ms past its stamp, above the declared "
                f"allowance of {source.fill_span_allowance_ms} ms, so that allowance is false"
            )
        # The bars stay. A minute the check cannot explain, and every minute after it, is flagged.
        flagged: set[int] = set()
        if result.flag_from_close_us is not None:
            flagged |= set(range(result.flag_from_close_us, last_close + 1, MICROS_PER_MINUTE))
        if result.flag_first_bar:
            flagged.add(first_close)
        if result.flag_last_bar:
            flagged.add(last_close)
        if flagged:
            bars = build(flagged)

    provisional = not next_available or (needs_official and reconciliation is None) or open_neighbours
    detail = {
        "final_boundary": next_available,
        "reconciled": reconciliation is not None,
        "needs_previous_day": bool(reconciliation and reconciliation["needs_previous_day"]),
        "needs_next_day": bool(reconciliation and reconciliation["needs_next_day"]),
        "reasons": reasons,
    }
    if failed:
        check_status = STATUS_FAIL
    elif provisional:
        check_status = "provisional"
    elif warned:
        check_status = STATUS_WARN
    else:
        check_status = "pass"

    window_ms = None if tolerance is None else tolerance.boundary_window_ms
    if failed or (warned and not provisional):
        _record_exclusion(ctx, venue, symbol, day, "; ".join(reasons), window_ms)
    elif not provisional:
        ctx.catalog.resolve_exclusions(venue, symbol, day.isoformat(), now=ctx.now_iso())

    day_text = day.isoformat()
    bars_part = ctx.root.curated_part(BARS_1M, venue, symbol, day)
    bars_rel = ctx.relative(bars_part)
    for minutes in ctx.config.timeframes_minutes:
        higher = aggregate_bars(bars, minutes, through_close_us=last_close)
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
    atomic_write_parquet(bars_part, bars, guard=ctx.root.guard)
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
    if failed:
        return DeriveOutcome(STATE_FAILED, bars.height, reconciliation, "; ".join(reasons))
    return DeriveOutcome(STATE_PROVISIONAL if provisional else STATE_DONE, bars.height, reconciliation)


def reopen_day(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> None:
    """A day's inputs changed, so its bars must be rebuilt, whatever state they were left in."""
    key = derive_task_key(venue, symbol, day)
    if ctx.catalog.get_task(key) is not None:
        ctx.catalog.set_task(
            key,
            dataset_id=derive_dataset_id(venue),
            symbol=symbol,
            partition_key=day.isoformat(),
            state=STATE_PENDING,
            now=ctx.now_iso(),
        )


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
        next_day = day + dt.timedelta(days=1)
        previous_day = day - dt.timedelta(days=1)
        if (
            not detail.get("final_boundary")
            and ctx.root.curated_part(TRADES, venue, symbol, next_day).is_file()
        ):
            return True
        if detail.get("needs_previous_day") and ctx.catalog.get_reconciliation(
            CHECK_OFFICIAL, venue, symbol, previous_day.isoformat()
        ):
            return True
        if detail.get("needs_next_day") and ctx.catalog.get_reconciliation(
            CHECK_OFFICIAL, venue, symbol, next_day.isoformat()
        ):
            return True
        official = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
        return bool(not detail.get("reconciled") and official.is_file())
    return False
