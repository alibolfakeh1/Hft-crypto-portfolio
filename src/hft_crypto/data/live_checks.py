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
    compare_emitted_with_rebuild,
    compare_live_with_archive,
    cross_venue_check,
)
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M
from hft_crypto.data.poll import BARS_1M_LIVE, rebuild_day_bars
from hft_crypto.data.zones import DataRoot


def _day_is_whole(bars: pl.DataFrame) -> bool:
    return bars.height == 1440


def _store(
    ctx: JobContext, name: str, venue: str, symbol: str, day: dt.date, result: dict[str, Any]
) -> dict[str, Any]:
    ctx.catalog.put_reconciliation(
        name, venue, symbol, day.isoformat(), result["status"], result, now=ctx.now_iso()
    )
    return {"check": name, "symbol": symbol, "date": str(day), **result}


def run_live_checks(ctx: JobContext, poll_ctx: JobContext, *, days: int = 3) -> list[dict[str, Any]]:
    """Check the newest whole days of each polled symbol. Results go to the main catalog."""
    poll = ctx.config.poll
    today = ctx.now().date()
    results: list[dict[str, Any]] = []
    for pair in poll.pairs:
        for back in range(1, days + 1):
            day = today - dt.timedelta(days=back)
            part = poll_ctx.root.curated_part(BARS_1M_LIVE, poll.venue, pair.symbol, day)
            if not part.is_file():
                continue
            emitted = read_parquet(part)
            if not _day_is_whole(emitted):
                continue
            rebuilt = rebuild_day_bars(poll_ctx, poll, pair.symbol, day)
            same = compare_emitted_with_rebuild(emitted, rebuilt)
            results.append(_store(ctx, "poll_rebuild", poll.venue, pair.symbol, day, same))
            own_archive = _archive_bars(ctx.root, poll.venue, pair.symbol, day)
            if own_archive is not None:
                against = compare_live_with_archive(emitted, own_archive)
                results.append(_store(ctx, "live_archive", poll.venue, pair.symbol, day, against))
            venue = ctx.config.report.benchmark_venue
            if venue is None or venue == poll.venue:
                continue
            archive = _archive_bars(ctx.root, venue, pair.archive_symbol, day)
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


def _archive_bars(root: DataRoot, venue: str, symbol: str, day: dt.date) -> pl.DataFrame | None:
    part = root.curated_part(BARS_1M, venue, symbol, day)
    return read_parquet(part) if part.is_file() else None
