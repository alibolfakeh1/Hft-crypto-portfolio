"""Where each archive file lives, by adapter. Which sources may be used at all is decided by configuration.

Binance Vision's USD-M perpetual archive is the research history under decision D-29, and it ships disabled.
No partition after the last opened date of the fold plan is ever expected from here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from hft_crypto.config import DatasetSpec, PipelineConfig
from hft_crypto.timeutil import date_range, month_key, month_starts, next_month


@dataclass(frozen=True)
class ArchiveFile:
    url: str
    filename: str
    checksum_url: str | None


def archive_candidates(
    config: PipelineConfig, spec: DatasetSpec, symbol: str, partition: dt.date
) -> list[ArchiveFile]:
    """Return the possible locations of one partition, in the order to try them.

    There is more than one only where a venue changed its file name over time.
    """
    day = partition.isoformat()
    month = month_key(partition)
    urls = config.source(spec.venue).urls
    if spec.adapter == "binance_klines":
        if spec.granularity == "month":
            return [monthly_candle_file(config, spec.venue, symbol, partition)]
        name = f"{symbol}-1m-{day}.zip"
        url = f"{urls['archive_base']}/daily/klines/{symbol}/1m/{name}"
    elif spec.adapter == "binance_agg_trades":
        name = f"{symbol}-aggTrades-{day}.zip"
        url = f"{urls['archive_base']}/daily/aggTrades/{symbol}/{name}"
    elif spec.adapter == "binance_book_depth":
        name = f"{symbol}-bookDepth-{day}.zip"
        url = f"{urls['archive_base']}/daily/bookDepth/{symbol}/{name}"
    elif spec.adapter == "binance_funding":
        name = f"{symbol}-fundingRate-{month}.zip"
        url = f"{urls['archive_base']}/monthly/fundingRate/{symbol}/{name}"
    elif spec.adapter == "bybit_trades":
        name = f"{symbol}{day}.csv.gz"
        return [ArchiveFile(f"{urls['trades_base']}/{symbol}/{name}", name, None)]
    elif spec.adapter == "bybit_book":
        files = []
        for depth in config.bybit_book_depths:
            name = f"{day}_{symbol}_ob{depth}.data.zip"
            files.append(ArchiveFile(f"{urls['book_base']}/{symbol}/{name}", name, None))
        return files
    else:
        raise ValueError(f"no adapter called {spec.adapter}")
    return [ArchiveFile(url, name, f"{url}.CHECKSUM")]


def monthly_candle_file(config: PipelineConfig, venue: str, symbol: str, month: dt.date) -> ArchiveFile:
    """One month of 1-minute candles, for a monthly dataset and for the coverage check in its own root."""
    base = config.source(venue).urls["archive_base"]
    name = f"{symbol}-1m-{month_key(month)}.zip"
    url = f"{base}/monthly/klines/{symbol}/1m/{name}"
    return ArchiveFile(url, name, f"{url}.CHECKSUM")


def last_complete_partition(spec: DatasetSpec, now: dt.datetime) -> dt.date:
    """The newest partition whose data has finished. Today and this month are still being written."""
    today = now.astimezone(dt.UTC).date()
    if spec.granularity == "month":
        this_month = today.replace(day=1)
        return (this_month - dt.timedelta(days=1)).replace(day=1)
    return today - dt.timedelta(days=1)


def last_partition_within(spec: DatasetSpec, ceiling: dt.date) -> dt.date:
    """The newest partition that lies wholly on or before a date. A month reaching past it does not count."""
    if spec.granularity == "month":
        after = ceiling + dt.timedelta(days=1)
        return (after.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    return ceiling


def partition_last_day(spec: DatasetSpec, partition: dt.date) -> dt.date:
    if spec.granularity == "month":
        return next_month(partition) - dt.timedelta(days=1)
    return partition


def expected_partitions(
    spec: DatasetSpec,
    now: dt.datetime,
    start: dt.date | None = None,
    end: dt.date | None = None,
    *,
    ceiling: dt.date,
) -> list[dt.date]:
    """Every partition that should exist by now, oldest first, and none past the last opened date.

    The ceiling has no default, so a caller cannot leave it out by accident (coverage review, section 4.3).
    """
    first = max(spec.start, start) if start else spec.start
    if spec.granularity == "month":
        first = first.replace(day=1)
    last = min(last_complete_partition(spec, now), last_partition_within(spec, ceiling))
    if end is not None and end < last:
        last = end
    if first > last:
        return []
    if spec.granularity == "month":
        return list(month_starts(first, last))
    return list(date_range(first, last))
