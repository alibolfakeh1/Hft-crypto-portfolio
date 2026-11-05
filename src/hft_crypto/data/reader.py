"""The one way later code reads market data, so that timing never depends on a consumer remembering it.

Strategy and feature code gets frames from here and holds no root. A test fails if such code imports
`read_parquet`. Every read names a run clock, and the answer is what C17 says that run could have: closed by
t_cut, and knowable by t_dec. A bar this run could not yet have had raises an error, because the alternative
is a run reading its own future.

A read goes through the approved route only. A source that is unknown, disabled or prohibited gets an error,
whatever files are on disk. A source whose terms cover an archive for research has no live read at all.

No read reaches a date after the last opened date of the fold plan: bars by close time, trades by stamp and
funding by settlement time, all through the run's cut. A knowable time may fall after that, so the last bar of
the span stays readable. A root of unopened dates cannot be opened at all.

Bars from official candles are read with `candles`, and never with `bars`, so they cannot pass for trade-built
bars.

`as_of_bars` and `ideal_bars` return standing as of the read, under the leak audit's ruling 4: a gap, a proof
or a completeness counts from its own knowable time, higher bars are aggregated from that view and not read
from stored ones, and `knowable_time` is not in the view, because it would hand the reader the time of the
next trade.

What is deferred: `settle`, the modelled fetch of a backtest and the ledger do not exist in this layer. A run
clock comes from the fetch stage in `data/poll.py` or from that modelled fetch.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from hft_crypto.bars.core import (
    BAR_SCHEMA,
    HIGHER_BAR_SCHEMA,
    UTC_TIME,
    DateGuardError,
    TimingContractError,
    as_of_view,
    bars_for_run,
    ideal_view,
    trades_for_run,
)
from hft_crypto.config import ARCHIVE_ONLY_SOURCES, ConfigError, PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.derive import ALLOWANCE_EVENTS, TRADES, bars_dataset
from hft_crypto.data.parsers import TRADE_SCHEMA
from hft_crypto.data.poll import BARS_1M_LIVE, TRADES_LIVE, live_dataset
from hft_crypto.data.zones import DataRoot, part_period
from hft_crypto.timeutil import date_of_us, day_start_us, iso_us

FUNDING = "funding"
FUNDING_SCHEMA: dict[str, pl.DataType] = {
    "venue": pl.String(),
    "symbol": pl.String(),
    "settle_time": UTC_TIME,
    "funding_interval_hours": pl.Int32(),
    "funding_rate": pl.Float64(),
    "knowable_time": UTC_TIME,
}


class SourceNotApproved(ConfigError):
    """A read named a source that is unknown, disabled or prohibited, or a route its terms do not allow."""


def _moment(value_us: int) -> pl.Expr:
    return pl.lit(value_us, dtype=pl.Int64).cast(UTC_TIME)


@dataclass(frozen=True)
class RunClock:
    """The two moments of one run, in integer microseconds."""

    t_cut_us: int
    t_dec_us: int


def _bars_schema(minutes: int) -> dict[str, pl.DataType]:
    return BAR_SCHEMA if minutes == 1 else HIGHER_BAR_SCHEMA


class MarketReader:
    def __init__(self, root: DataRoot, config: PipelineConfig) -> None:
        root.refuse_unopened("a market read")
        self._root = root
        self._config = config
        self._frames: dict[Path, pl.DataFrame] = {}

    def _check_route(self, venue: str) -> None:
        if venue not in self._config.sources:
            raise SourceNotApproved(f"unknown source: {venue}")
        if not self._config.source_usable(venue):
            raise SourceNotApproved(f"source {venue} is not approved and enabled, so it is not read")

    def _check_opened(self, moment_us: int) -> None:
        """Bars by close, trades by stamp and funding by settlement all stop at the run's cut, so this is the
        guard."""
        if moment_us > self._config.opened_through_us:
            raise DateGuardError(
                f"{iso_us(moment_us)} is after the last opened date, {self._config.last_opened_date}, "
                "so it is not read"
            )

    def _check_live_route(self, venue: str) -> None:
        self._check_route(venue)
        if venue in ARCHIVE_ONLY_SOURCES:
            raise SourceNotApproved(f"source {venue} is for archive research only, so it has no live read")

    def _part(self, part: Path) -> pl.DataFrame:
        frame = self._frames.get(part)
        if frame is None:
            frame = read_parquet(part)
            self._frames[part] = frame
        return frame

    def _load(
        self, dataset: str, venue: str, symbol: str, last_us: int, since: dt.date | None
    ) -> pl.DataFrame | None:
        # The part holding the moment is the last one read. A trade or a settlement stamped exactly at
        # midnight is in the part of the day it starts. A part after the last opened date is never opened,
        # whatever the moment.
        last = min(date_of_us(last_us), self._config.last_opened_date)
        frames = []
        for part in self._root.curated_parts(dataset, venue, symbol):
            period = part_period(part)
            if period is None or period[0] > last or (since is not None and period[1] < since):
                continue
            frames.append(self._part(part))
        return pl.concat(frames) if frames else None

    def _ideal_allowed(self, venue: str) -> bool:
        """A source's class is a declared value that can be revoked: a row seen running past the allowance
        does."""
        if not self._config.source(venue).ideal_allowed:
            return False
        path = self._root.guard.check(ALLOWANCE_EVENTS)
        if not path.is_file():
            return True
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("venue") == venue:
                return False
        return True

    def bars(
        self, minutes: int, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Archive bars built from trades, for a run that models its fetch."""
        self._check_route(venue)
        source = self._config.source(venue)
        if source.official_bars:
            raise SourceNotApproved(
                f"source {venue} has bars from official candles, so read them with candles"
            )
        return self._read_bars(bars_dataset(source, minutes), minutes, venue, symbol, clock, since)

    def _read_bars(
        self, dataset: str, minutes: int, venue: str, symbol: str, clock: RunClock, since: dt.date | None
    ) -> pl.DataFrame:
        self._check_opened(clock.t_cut_us)
        # A bar closing exactly at midnight sits in the part of the day it opens, so a cut at midnight needs
        # nothing from the next day's part, and leaves it shut.
        frame = self._load(dataset, venue, symbol, clock.t_cut_us - 1, since)
        if frame is None:
            return pl.DataFrame(schema=_bars_schema(minutes))
        return bars_for_run(frame.sort("close_time"), clock.t_cut_us, clock.t_dec_us)

    def candles(
        self, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None, minutes: int = 1
    ) -> pl.DataFrame:
        """Bars on a tier T0 path, which come from official candles and say so on every row."""
        self._check_route(venue)
        source = self._config.source(venue)
        if not source.official_bars:
            raise SourceNotApproved(f"source {venue} builds its bars from trades, so it has no candle read")
        return self._read_bars(bars_dataset(source, minutes), minutes, venue, symbol, clock, since)

    def funding(
        self, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Funding settled by the cut. A row this run could not yet have had raises, as for bars."""
        self._check_route(venue)
        self._check_opened(clock.t_cut_us)
        frame = self._load(FUNDING, venue, symbol, clock.t_cut_us, since)
        if frame is None:
            return pl.DataFrame(schema=FUNDING_SCHEMA)
        if clock.t_dec_us < clock.t_cut_us:
            raise TimingContractError("a run cannot commit before its own data cut-off")
        selected = frame.sort("settle_time").filter(pl.col("settle_time") <= _moment(clock.t_cut_us))
        if since is not None:
            selected = selected.filter(pl.col("settle_time") >= _moment(day_start_us(since)))
        late = selected.filter(pl.col("knowable_time") > _moment(clock.t_dec_us))
        if late.height:
            raise TimingContractError("a funding row this run could not yet have had was asked for")
        return selected

    def _one_minute(self, venue: str, symbol: str, last_us: int, since: dt.date | None) -> pl.DataFrame:
        dataset = bars_dataset(self._config.source(venue), 1)
        frame = self._load(dataset, venue, symbol, last_us - 1, since)
        return pl.DataFrame(schema=BAR_SCHEMA) if frame is None else frame.sort("close_time")

    def as_of_bars(
        self,
        minutes: int,
        venue: str,
        symbol: str,
        t_us: int,
        read_at_us: int,
        *,
        since: dt.date | None = None,
    ) -> pl.DataFrame:
        """Bars for IDEAL-1M: closed by t, with their standing as of the read, at t + max(latency, A).

        This never raises on a quiet tail, because an empty minute whose proof comes later reads as what it
        was at the read: unproven, and a gap. The read must be late enough for the plain volume to be known.
        """
        self._check_route(venue)
        self._check_opened(t_us)
        allowance = self._config.source(venue).bar_allowance_us
        if read_at_us < t_us + allowance:
            raise TimingContractError("this read comes before the source's allowance has passed")
        bars = self._one_minute(venue, symbol, t_us, since)
        return as_of_view(bars, minutes, read_at_us, through_us=t_us)

    def ideal_bars(
        self, minutes: int, venue: str, symbol: str, at_us: int, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Bars for IDEAL mode, a decision at a close with no allowance. A source that cannot give that is
        refused.

        The settled columns replace the plain ones, because they hold only what had printed by the close. The
        read at a moment on full data equals the read at that moment on data truncated there, on every column.
        """
        self._check_route(venue)
        self._check_opened(at_us)
        allowed = self._ideal_allowed(venue)
        bars = self._one_minute(venue, symbol, at_us, since)
        view = as_of_view(bars, minutes, at_us)
        return ideal_view(
            view, ideal_allowed=allowed, keep_fill_count=self._config.source(venue).official_bars
        )

    def trades(
        self, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        self._check_route(venue)
        self._check_opened(clock.t_cut_us)
        frame = self._load(TRADES, venue, symbol, clock.t_cut_us, since)
        if frame is None:
            return pl.DataFrame(schema=TRADE_SCHEMA)
        return trades_for_run(frame.sort(["ts", "trade_id", "file_row"]), clock.t_cut_us, clock.t_dec_us)

    def live_bars(
        self, minutes: int, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Bars a live run received, from the poll's own datasets."""
        venue = self._config.poll.venue
        self._check_live_route(venue)
        self._check_opened(clock.t_cut_us)
        dataset = BARS_1M_LIVE if minutes == 1 else live_dataset(minutes)
        frame = self._load(dataset, venue, symbol, clock.t_cut_us - 1, since)
        if frame is None:
            return pl.DataFrame(schema=_bars_schema(minutes))
        return bars_for_run(frame.sort("close_time"), clock.t_cut_us, clock.t_dec_us)

    def live_trades(self, symbol: str, clock: RunClock, *, since: dt.date | None = None) -> pl.DataFrame:
        venue = self._config.poll.venue
        self._check_live_route(venue)
        self._check_opened(clock.t_cut_us)
        frame = self._load(TRADES_LIVE, venue, symbol, clock.t_cut_us, since)
        if frame is None:
            return pl.DataFrame(schema=TRADE_SCHEMA)
        return trades_for_run(frame.sort(["ts", "trade_id"]), clock.t_cut_us, clock.t_dec_us)

    def live_dataset(
        self, dataset_id: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Any other dataset for a live gate. C17 says a run sees no book, so most datasets are refused
        here."""
        spec = next((item for item in self._config.datasets if item.id == dataset_id), None)
        if spec is None or not spec.live_eligible:
            raise TimingContractError(f"{dataset_id} is not eligible for a live read")
        self._check_live_route(spec.venue)
        self._check_opened(clock.t_cut_us)
        frame = self._load(spec.curated, spec.venue, symbol, clock.t_cut_us, since)
        if frame is None:
            return pl.DataFrame()
        return frame.filter(pl.col("knowable_time") <= _moment(clock.t_cut_us))
