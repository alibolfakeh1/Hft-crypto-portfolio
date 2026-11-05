"""Curated bars for one UTC day: canonical one-minute bars, higher timeframes and reconciliation.

A bar covers (open, close], while a delivered file covers its UTC day [00:00, 24:00). So the bar ending at
midnight can need a trade stamped exactly 00:00:00.000 from the next day's file, and a minute's proof of
continuity can need the rows on either side of midnight. Until the next file exists, the last bar of the day
is flagged gap=True, the day stays provisional, and a later run rebuilds it.

A day that fails a check keeps its bars. Only the minutes the check cannot explain are flagged. Each such day
is logged as an exclusion, counted in every result, and fetched again later in case a good file has been
published.

A source can declare `bar_source = "official_1m"`, the tier T0 path under ruling 7 of the leak recheck. Its
bars come from its candle files, with no trades. They state their source and boundary and live in datasets of
their own, so they can never be read as trade-built bars, and the reconciliation says it is not available,
because the only thing it could compare those candles with is themselves.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.core import (
    PROOF_NONE,
    SOURCE_OFFICIAL,
    UTC_TIME,
    DateGuardError,
    aggregate_bars,
    bars_from_official,
    build_bars_1m,
    closes_between,
    find_id_skips,
    find_long_quiets,
)
from hft_crypto.bars.reconcile import (
    STATUS_FAIL,
    STATUS_NOT_AVAILABLE,
    STATUS_WARN,
    DayFlow,
    reconcile_official,
)
from hft_crypto.config import DatasetSpec, SourceSpec
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
# A clean day that nothing outside its own files has checked. It is never reported as passed, under charter
# G1.
STATUS_UNRECONCILED = "unreconciled"
# What a day's raw file, or a report, may rely on, as far as its own checks can say.
USABLE_DAY_STATUSES = frozenset({"pass", STATUS_UNRECONCILED})
ALLOWANCE_EVENTS = "catalog/allowance_events.jsonl"


def timeframe_dataset(minutes: int) -> str:
    """Return the dataset name for a timeframe: 5 gives bars_5m, 60 bars_1h, 1440 bars_1d."""
    if minutes == 1:
        return BARS_1M
    if minutes % 1440 == 0:
        return f"bars_{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"bars_{minutes // 60}h"
    return f"bars_{minutes}m"


def official_dataset(minutes: int) -> str:
    """The dataset of a timeframe of bars from official candles, as the poll's _live sets have their own
    names."""
    return f"{timeframe_dataset(minutes)}_official"


def bars_dataset(source: SourceSpec, minutes: int) -> str:
    """Where a source's bars of one timeframe are stored."""
    return official_dataset(minutes) if source.official_bars else timeframe_dataset(minutes)


def derive_task_key(venue: str, symbol: str, day: dt.date) -> str:
    return f"derive:{venue}:{symbol}:{day.isoformat()}"


def derive_dataset_id(venue: str) -> str:
    return f"derived.bars.{venue}"


def base_dataset(source: SourceSpec) -> str:
    """The curated dataset a source's bars are built from."""
    return OFFICIAL if source.official_bars else TRADES


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
    if row is None or row["status"] == STATUS_NOT_AVAILABLE:
        return None
    return DayFlow.from_detail(row["detail"])


def _is_first_day(spec: DatasetSpec | None, day: dt.date) -> bool:
    return spec is not None and day <= spec.start


def _record_holes(
    ctx: JobContext, venue: str, symbol: str, window: pl.DataFrame, day: dt.date, spec: DatasetSpec | None
) -> tuple[set[int], list[str], list[str]]:
    """Record every hole the rows themselves show. Return the minutes to flag, then skips, then silences.

    A skip in the ids is a defect in the file, so it sets a status. A silence alone is a state of the market.
    It is recorded, its minutes stay flagged by a declared constant until evidence shows ids are consecutive
    by design, and it never sets a status or leaves a day out of results. Otherwise quiet days would leave the
    sample.
    """
    low = day_start_us(day)
    high = low + MICROS_PER_DAY
    dataset = f"curated.{TRADES}.{venue}.{symbol}"
    closes: set[int] = set()
    skips: list[str] = []
    silences: list[str] = []
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
        skips.append(f"trade ids jump from {skip.after_id} to {skip.next_id}")
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
            silences.append(f"no trades from {iso_us(start)} to {iso_us(end)}")
    return closes, skips, silences


def _data_kind(ctx: JobContext) -> str:
    return "SYNTHETIC" if ctx.root.is_synthetic else "MARKET"


def _record_exclusion(
    ctx: JobContext,
    venue: str,
    symbol: str,
    day: dt.date,
    reason: str,
    window_ms: float | None,
    *,
    fault_day: dt.date | None = None,
) -> None:
    """A day left out of results is logged, once per reason, in a file that is only appended to.

    fault_day names the day whose own break left this one unconfirmed, so one fault is not counted as several.
    """
    fault = None if fault_day is None else fault_day.isoformat()
    if ctx.catalog.add_exclusion(
        venue, symbol, day.isoformat(), reason, window_ms, now=ctx.now_iso(), fault_day=fault
    ):
        append_jsonl(
            ctx.root.guard.check("catalog/exclusions.jsonl"),
            {
                "time": ctx.now_iso(),
                "venue": venue,
                "symbol": symbol,
                "date": day.isoformat(),
                "reason": reason,
                "boundary_window_ms": window_ms,
                "fault_day": fault,
                "data_kind": _data_kind(ctx),
            },
            guard=ctx.root.guard,
        )


def _record_allowance_false(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, needed_ms: float, allowance_ms: float
) -> None:
    """A row ran longer than declared, so the allowance is false. The record stays, and the reader honours
    it."""
    if ctx.catalog.add_allowance_event(
        venue, symbol, day.isoformat(), needed_ms, allowance_ms, now=ctx.now_iso()
    ):
        append_jsonl(
            ctx.root.guard.check(ALLOWANCE_EVENTS),
            {
                "time": ctx.now_iso(),
                "venue": venue,
                "symbol": symbol,
                "date": day.isoformat(),
                "needed_ms": needed_ms,
                "allowance_ms": allowance_ms,
                "data_kind": _data_kind(ctx),
            },
            guard=ctx.root.guard,
        )


def _write_day_outputs(
    ctx: JobContext,
    venue: str,
    symbol: str,
    day: dt.date,
    bars: pl.DataFrame,
    *,
    last_close: int,
    check_status: str,
    detail: dict[str, Any],
    parents: list[str],
    tier: str,
) -> None:
    """Higher timeframes first and one-minute bars last, so the one-minute file is the mark that a build
    finished."""
    day_text = day.isoformat()
    source = ctx.config.source(venue)
    one_minute = bars_dataset(source, 1)
    bars_part = ctx.root.curated_part(one_minute, venue, symbol, day)
    bars_rel = ctx.relative(bars_part)
    for minutes in ctx.config.timeframes_minutes:
        higher = aggregate_bars(bars, minutes, through_close_us=last_close)
        dataset = bars_dataset(source, minutes)
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
            tier=tier,
        )
    atomic_write_parquet(bars_part, bars, guard=ctx.root.guard)
    ctx.register_output(
        bars_part,
        dataset_id=f"curated.{one_minute}.{venue}.{symbol}",
        kind=one_minute,
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
        tier=tier,
    )


def _candle_part(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> Path:
    """The candles holding a day, stored by day or by month as the dataset says."""
    daily = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
    return daily if daily.is_file() else ctx.root.curated_month_part(OFFICIAL, venue, symbol, day)


def _derive_from_candles(
    ctx: JobContext, venue: str, symbol: str, day: dt.date, source: SourceSpec
) -> DeriveOutcome:
    """The tier T0 path. A candle row is complete when it exists, so a day is final once its file is here."""
    part = _candle_part(ctx, venue, symbol, day)
    candles = read_parquet(part)
    low = day_start_us(day)
    last_close = low + MICROS_PER_DAY
    bars = bars_from_official(
        candles,
        venue=venue,
        symbol=symbol,
        first_close_us=low + MICROS_PER_MINUTE,
        last_close_us=last_close,
        candle_allowance_us=source.candle_allowance_us,
    )
    reasons: list[str] = []
    missing = bars.filter(pl.col("empty_proof") == PROOF_NONE)["close_time"].dt.timestamp("us").to_list()
    faulty = bars.filter(pl.col("gap") & (pl.col("empty_proof") != PROOF_NONE)).height
    if faulty:
        reasons.append(f"{faulty} minutes failed a check at the row")
    if missing:
        reasons.append(f"{len(missing)} minutes have no official candle")
        start = previous = int(missing[0])
        for close in [*(int(value) for value in missing[1:]), None]:
            if close is not None and close == previous + MICROS_PER_MINUTE:
                previous = close
                continue
            ctx.catalog.add_gap(
                f"curated.{OFFICIAL}.{venue}.{symbol}",
                iso_us(start - MICROS_PER_MINUTE),
                iso_us(previous),
                "no official candle for these minutes",
                now=ctx.now_iso(),
                run_id=ctx.run_id,
            )
            if close is not None:
                start = previous = close
    # Nothing outside these candles has checked them, so this is reported as not available, and never as
    # passed.
    ctx.catalog.put_reconciliation(
        CHECK_OFFICIAL,
        venue,
        symbol,
        day.isoformat(),
        STATUS_NOT_AVAILABLE,
        {"reason": "the bars are the official candles, so there is nothing to check them against"},
        now=ctx.now_iso(),
    )
    if reasons:
        _record_exclusion(ctx, venue, symbol, day, "; ".join(reasons), None)
    else:
        ctx.catalog.resolve_exclusions(venue, symbol, day.isoformat(), now=ctx.now_iso())
    _write_day_outputs(
        ctx,
        venue,
        symbol,
        day,
        bars,
        last_close=last_close,
        check_status=STATUS_WARN if reasons else STATUS_UNRECONCILED,
        detail={
            "final_boundary": True,
            "reconciled": False,
            "bar_source": SOURCE_OFFICIAL,
            "reasons": reasons,
        },
        parents=[ctx.relative(part)],
        tier="T0",
    )
    return DeriveOutcome(STATE_DONE, bars.height, None)


def derive_day(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> DeriveOutcome:
    """Build and check all bars of one day. Running it twice gives the same files."""
    ctx.root.refuse_unopened("a bar build")
    if day > ctx.config.last_opened_date:
        raise DateGuardError(f"{day} is after the last opened date, so no bars are built for it")
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
    if source.official_bars:
        return _derive_from_candles(ctx, venue, symbol, day, source)
    allowance_us = source.fill_span_allowance_us
    spec = _trade_spec(ctx, venue)
    file_trades, window, parents, next_available, previous_tail = load_day_window(
        ctx, venue, symbol, day, allowance_us=allowance_us
    )
    _refuse_rows_from_another_path(window, allowance_us)
    low = day_start_us(day)
    first_close = low + MICROS_PER_MINUTE
    last_close = low + MICROS_PER_DAY
    gap_closes, skip_notes, silence_notes = _record_holes(ctx, venue, symbol, window, day, spec)
    if not next_available:
        gap_closes.add(last_close)

    def build(extra: set[int], late: dict[int, int]) -> pl.DataFrame:
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
            late_gap_close_us=late,
        )

    bars = build(set(), {})
    reconciliation: dict[str, Any] | None = None
    reasons: list[str] = list(skip_notes)
    failed = False
    warned = bool(skip_notes)
    official_part = ctx.root.curated_part(OFFICIAL, venue, symbol, day)
    tolerance = ctx.config.reconcile.get(symbol)
    needs_official = ctx.config.has_official_candles(venue)
    open_neighbours = False
    fault_day: dt.date | None = None
    if needs_official and official_part.is_file() and tolerance is not None:
        official = read_parquet(official_part)
        is_first = _is_first_day(spec, day)
        result = reconcile_official(
            file_trades,
            bars,
            official,
            tolerance,
            window_ms=source.fill_span_allowance_ms,
            previous_tail=previous_tail,
            previous_flow=_neighbour_flow(ctx, venue, symbol, day - dt.timedelta(days=1)),
            next_flow=_neighbour_flow(ctx, venue, symbol, day + dt.timedelta(days=1)),
            is_first_day=is_first,
        )
        reconciliation = result.to_dict()
        before = _neighbour_flow(ctx, venue, symbol, day)
        if before is not None and before != DayFlow.from_detail(reconciliation):
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
        if result.unconfirmed_previous:
            fault_day = day - dt.timedelta(days=1)
            reasons.append(
                f"the previous day's own figures broke, so the fault is on {fault_day.isoformat()}"
            )
        if result.unconfirmed_next:
            fault_day = day + dt.timedelta(days=1)
            reasons.append(f"the next day's own figures broke, so the fault is on {fault_day.isoformat()}")
        # Ruling 2 of the leak audit. If a row ran longer than declared, the allowance is false. It says so,
        # the reader honours it, and that does not remove the day.
        if result.largest_window_needed_ms > source.fill_span_allowance_ms:
            warned = True
            _record_allowance_false(
                ctx, venue, symbol, day, result.largest_window_needed_ms, source.fill_span_allowance_ms
            )
            reasons.append(
                f"a row ran {result.largest_window_needed_ms} ms past its stamp, above the declared "
                f"allowance of {source.fill_span_allowance_ms} ms, so that allowance is false"
            )
        # The bars stay, and only the minutes the walk marks bad are flagged. A disagreement at the far
        # midnight rests on the next day's first candle, so that flag is not known before then.
        flagged: set[int] = set(result.flag_close_us)
        if result.flag_first_bar:
            flagged.add(first_close)
        late = {last_close: last_close + MICROS_PER_MINUTE + allowance_us} if result.flag_last_bar else {}
        if flagged or late:
            bars = build(flagged, late)

    provisional = not next_available or (needs_official and reconciliation is None) or open_neighbours
    detail = {
        "final_boundary": next_available,
        "reconciled": reconciliation is not None,
        "needs_previous_day": bool(reconciliation and reconciliation["needs_previous_day"]),
        "needs_next_day": bool(reconciliation and reconciliation["needs_next_day"]),
        "reasons": reasons,
        "silences": silence_notes,
    }
    if failed:
        check_status = STATUS_FAIL
    elif provisional:
        check_status = "provisional"
    elif warned:
        check_status = STATUS_WARN
    elif reconciliation is None:
        check_status = STATUS_UNRECONCILED
    else:
        check_status = "pass"

    window_ms = source.fill_span_allowance_ms if tolerance is not None else None
    if failed or (warned and not provisional):
        _record_exclusion(ctx, venue, symbol, day, "; ".join(reasons), window_ms, fault_day=fault_day)
    elif not provisional:
        ctx.catalog.resolve_exclusions(venue, symbol, day.isoformat(), now=ctx.now_iso())

    _write_day_outputs(
        ctx,
        venue,
        symbol,
        day,
        bars,
        last_close=last_close,
        check_status=check_status,
        detail=detail,
        parents=parents,
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
    source = ctx.config.source(venue)
    base = (
        _candle_part(ctx, venue, symbol, day)
        if source.official_bars
        else ctx.root.curated_part(TRADES, venue, symbol, day)
    )
    if not base.is_file():
        return False
    task = ctx.catalog.get_task(derive_task_key(venue, symbol, day))
    bars_part = ctx.root.curated_part(bars_dataset(ctx.config.source(venue), 1), venue, symbol, day)
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
