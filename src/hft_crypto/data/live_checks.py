"""Daily checks on polled bars, run from the daily pipeline.

Same venue, two checks. Emitted bars against a rebuild from all stored trades, which finds trades that arrived
after their minute was emitted. Emitted bars against that venue's archive, when it has one, which finds what
the poll never received: this is what a backtest could see that a live run did not. Other venue: a sanity
check against the benchmark venue's bars, which are a different market and not expected to match.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl

from hft_crypto.bars.reconcile import (
    STATUS_NOT_AVAILABLE,
    compare_emitted_with_rebuild,
    compare_live_with_archive,
    cross_venue_check,
)
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import bars_dataset
from hft_crypto.data.poll import BARS_1M_LIVE, rebuild_day_bars
from hft_crypto.data.zones import part_period


def _day_is_whole(bars: pl.DataFrame) -> bool:
    return bars.height == 1440


def _store(
    ctx: JobContext, name: str, venue: str, symbol: str, day: dt.date, result: dict[str, Any]
) -> dict[str, Any]:
    ctx.catalog.put_reconciliation(
        name, venue, symbol, day.isoformat(), result["status"], result, now=ctx.now_iso()
    )
    return {"check": name, "symbol": symbol, "date": str(day), **result}


def _whole_days(poll_ctx: JobContext, venue: str, symbol: str, today: dt.date, days: int) -> list[dt.date]:
    """The newest days that exist and are over. By what exists, so a history that arrives late still gets
    checked."""
    found = []
    for part in poll_ctx.root.curated_parts(BARS_1M_LIVE, venue, symbol):
        period = part_period(part)
        if period is not None and period[0] == period[1] and period[0] < today:
            found.append(period[0])
    return sorted(found)[-days:]


def run_live_checks(ctx: JobContext, poll_ctx: JobContext, *, days: int = 3) -> list[dict[str, Any]]:
    """Check the newest whole days of each polled symbol. Results go to the main catalog."""
    poll = ctx.config.poll
    today = ctx.now().date()
    results: list[dict[str, Any]] = []
    for pair in poll.pairs:
        for day in _whole_days(poll_ctx, poll.venue, pair.symbol, today, days):
            emitted = read_parquet(poll_ctx.root.curated_part(BARS_1M_LIVE, poll.venue, pair.symbol, day))
            if not _day_is_whole(emitted):
                continue
            rebuilt = rebuild_day_bars(poll_ctx, poll, pair.symbol, day)
            same = compare_emitted_with_rebuild(emitted, rebuilt)
            results.append(_store(ctx, "poll_rebuild", poll.venue, pair.symbol, day, same))
            # The archive names its symbol its own way, and the pair says how. A day it cannot check says so.
            own_archive = _archive_bars(ctx, poll.venue, pair.archive_symbol, day)
            against = (
                {"status": STATUS_NOT_AVAILABLE, "bars_compared": 0, "bars_different": 0}
                if own_archive is None
                else compare_live_with_archive(emitted, own_archive)
            )
            results.append(_store(ctx, "live_archive", poll.venue, pair.symbol, day, against))
            venue = ctx.config.report.benchmark_venue
            if venue is None or venue == poll.venue:
                continue
            archive = _archive_bars(ctx, venue, pair.archive_symbol, day)
            if archive is None:
                continue
            other = cross_venue_check(
                emitted,
                archive,
                median_bps_warn=poll.median_abs_close_diff_bps_warn,
                min_corr_warn=poll.min_return_corr_warn,
            )
            results.append(_store(ctx, "cross_venue", poll.venue, pair.symbol, day, other))
    return results


def _archive_bars(ctx: JobContext, venue: str, symbol: str, day: dt.date) -> pl.DataFrame | None:
    if day > ctx.config.last_opened_date or venue not in ctx.config.sources:
        return None
    dataset = bars_dataset(ctx.config.source(venue), 1)
    part = ctx.root.curated_part(dataset, venue, symbol, day)
    return read_parquet(part) if part.is_file() else None
