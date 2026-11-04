"""Daily checks on polled bars, run from the daily pipeline.

A polled venue may have no archive of its own here, so its bars may not reconcile against archive bars of
the same venue. Two checks stand in. Same venue: emitted bars against a rebuild from all stored trades, which
finds trades that arrived after their minute was emitted. Other venue: a sanity check against the benchmark
venue's bars, which may be a different market and are then not expected to match.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import polars as pl

from hft_crypto.bars.reconcile import compare_emitted_with_rebuild, cross_venue_check
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.context import JobContext
from hft_crypto.data.derive import BARS_1M
from hft_crypto.data.poll import rebuild_day_bars
from hft_crypto.data.zones import DataRoot


def _day_is_whole(bars: pl.DataFrame) -> bool:
    return bars.height == 1440


def run_live_checks(ctx: JobContext, poll_ctx: JobContext, *, days: int = 3) -> list[dict[str, Any]]:
    """Check the newest whole days of each polled symbol. Results go to the main catalog."""
    poll = ctx.config.poll
    today = ctx.now().date()
    results: list[dict[str, Any]] = []
    for pair in poll.pairs:
        for back in range(1, days + 1):
            day = today - dt.timedelta(days=back)
            part = poll_ctx.root.curated_part(BARS_1M, poll.venue, pair.symbol, day)
            if not part.is_file():
                continue
            emitted = read_parquet(part)
            if not _day_is_whole(emitted):
                continue
            rebuilt = rebuild_day_bars(poll_ctx, poll, pair.symbol, day)
            same = compare_emitted_with_rebuild(emitted, rebuilt)
            ctx.catalog.put_reconciliation(
                "poll_rebuild",
                poll.venue,
                pair.symbol,
                day.isoformat(),
                same["status"],
                same,
                now=ctx.now_iso(),
            )
            results.append({"check": "poll_rebuild", "symbol": pair.symbol, "date": str(day), **same})
            venue = ctx.config.report.benchmark_venue
            archive = None if venue is None else _archive_bars(ctx.root, venue, pair.archive_symbol, day)
            if archive is None:
                continue
            other = cross_venue_check(
                emitted,
                archive,
                median_bps_warn=poll.median_abs_close_diff_bps_warn,
                min_corr_warn=poll.min_return_corr_warn,
            )
            ctx.catalog.put_reconciliation(
                "cross_venue",
                poll.venue,
                pair.symbol,
                day.isoformat(),
                other["status"],
                other,
                now=ctx.now_iso(),
            )
            results.append({"check": "cross_venue", "symbol": pair.symbol, "date": str(day), **other})
    return results


def _archive_bars(root: DataRoot, venue: str, symbol: str, day: dt.date) -> pl.DataFrame | None:
    part = root.curated_part(BARS_1M, venue, symbol, day)
    return read_parquet(part) if part.is_file() else None
