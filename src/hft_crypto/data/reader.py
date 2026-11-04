"""The one way later code reads market data, so that timing never depends on a consumer remembering it.

Strategy and feature code gets frames from here and holds no root. A test fails if such code imports
`read_parquet`. Every read names a run clock, and the answer is what C17 says that run could have: closed by
t_cut, and knowable by t_dec. A bar this run could not yet have had raises an error, because the alternative
is a run reading its own future.

What is deferred: `decide`, `settle`, the modelled fetch of a backtest and the ledger do not exist yet. This
is the interface they will use, and a run clock comes from the fetch stage in `data/poll.py` or from that
modelled fetch.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import polars as pl

from hft_crypto.bars.core import (
    BAR_SCHEMA,
    UTC_TIME,
    TimingContractError,
    bars_for_run,
    ideal_view,
    trades_for_run,
)
from hft_crypto.config import PipelineConfig
from hft_crypto.data.atomic import read_parquet
from hft_crypto.data.derive import BARS_1M, TRADES, timeframe_dataset
from hft_crypto.data.poll import BARS_1M_LIVE, TRADES_LIVE, live_dataset
from hft_crypto.data.zones import DataRoot
from hft_crypto.timeutil import date_of_us


def _moment(value_us: int) -> pl.Expr:
    return pl.lit(value_us, dtype=pl.Int64).cast(UTC_TIME)


@dataclass(frozen=True)
class RunClock:
    """The two moments of one run, in integer microseconds."""

    t_cut_us: int
    t_dec_us: int


class MarketReader:
    def __init__(self, root: DataRoot, config: PipelineConfig) -> None:
        self._root = root
        self._config = config

    def _load(
        self, dataset: str, venue: str, symbol: str, clock: RunClock, since: dt.date | None
    ) -> pl.DataFrame | None:
        # A row at exactly midnight sits in the part of the day it opens, so one part past the cut is read
        # too.
        last = date_of_us(clock.t_cut_us)
        frames = [
            read_parquet(part)
            for part in self._root.curated_parts(dataset, venue, symbol)
            if (since is None or part.stem.removeprefix("part-") >= since.isoformat())
            and part.stem.removeprefix("part-") <= last.isoformat()
        ]
        return pl.concat(frames) if frames else None

    def bars(
        self, minutes: int, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Archive bars for a run that models its fetch."""
        dataset = BARS_1M if minutes == 1 else timeframe_dataset(minutes)
        frame = self._load(dataset, venue, symbol, clock, since)
        if frame is None:
            return pl.DataFrame()
        return bars_for_run(frame.sort("close_time"), clock.t_cut_us, clock.t_dec_us)

    def ideal_bars(
        self, minutes: int, venue: str, symbol: str, at_us: int, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Bars for IDEAL mode, a decision at a close with no allowance. A source that cannot give that is
        refused.

        This reads by close time and not by knowable time, because the settled columns that replace the plain
        ones hold only what had printed by the close. How `decide` treats an empty minute whose proof comes
        from a later row belongs to that code, which does not exist yet.
        """
        allowed = self._config.source(venue).ideal_allowed
        dataset = BARS_1M if minutes == 1 else timeframe_dataset(minutes)
        frame = self._load(dataset, venue, symbol, RunClock(at_us, at_us), since)
        if frame is None:
            return ideal_view(pl.DataFrame(schema=BAR_SCHEMA), ideal_allowed=allowed)
        closed = frame.sort("close_time").filter(pl.col("close_time") <= _moment(at_us))
        return ideal_view(closed, ideal_allowed=allowed)

    def trades(
        self, venue: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        frame = self._load(TRADES, venue, symbol, clock, since)
        if frame is None:
            return pl.DataFrame()
        return trades_for_run(frame.sort(["ts", "trade_id", "file_row"]), clock.t_cut_us, clock.t_dec_us)

    def live_bars(
        self, minutes: int, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Bars a live run received, from the poll's own datasets."""
        dataset = BARS_1M_LIVE if minutes == 1 else live_dataset(minutes)
        frame = self._load(dataset, self._config.poll.venue, symbol, clock, since)
        if frame is None:
            return pl.DataFrame()
        return bars_for_run(frame.sort("close_time"), clock.t_cut_us, clock.t_dec_us)

    def live_trades(self, symbol: str, clock: RunClock, *, since: dt.date | None = None) -> pl.DataFrame:
        frame = self._load(TRADES_LIVE, self._config.poll.venue, symbol, clock, since)
        if frame is None:
            return pl.DataFrame()
        return trades_for_run(frame.sort(["ts", "trade_id"]), clock.t_cut_us, clock.t_dec_us)

    def live_dataset(
        self, dataset_id: str, symbol: str, clock: RunClock, *, since: dt.date | None = None
    ) -> pl.DataFrame:
        """Any other dataset for a live gate. C17 says a run sees no book, so most datasets are refused
        here."""
        spec = next((item for item in self._config.datasets if item.id == dataset_id), None)
        if spec is None or not spec.live_eligible:
            raise TimingContractError(f"{dataset_id} is not eligible for a live read")
        frame = self._load(spec.curated, spec.venue, symbol, clock, since)
        if frame is None:
            return pl.DataFrame()
        return frame.filter(pl.col("knowable_time") <= _moment(clock.t_cut_us))
