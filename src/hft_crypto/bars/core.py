"""Bars from trades, following the timing contract in docs/00_CHARTER.md section 3 and conventions C2 and C17.

- A bar covers (open_time, close_time], so a trade exactly on a boundary closes the bar ending there.
- A minute with no trades is a real row with null prices and zero volume, and it says how we know that.
  `empty_proof` is `traded` for a minute with trades, `id_run` when the rows on either side have consecutive
  ids, `official` when the venue's own candle says no trade happened, and `none` otherwise. Unproven means a
  gap: a hole must never pass as a quiet market. Nothing is forward filled.
- A row carrying one stamp over an interval can hold fills from after that stamp, so nothing built from it is
  known at the stamp. A trade is knowable at its stamp plus the source's declared allowance, and a bar at its
  close plus that allowance, or when this system received it if that was later. See the leak audit's ruling 2.
- `volume` and its relatives put a whole row in the bar of its stamp. The `settled_*` columns count a row in a
  bar only when it was stamped at least the allowance before that bar's close, so they read the stamp and
  nothing else. A row's fill count cannot decide this, because it includes fills from after the close. IDEAL
  mode reads only them.
- A flag can rest on something later: a skip shows only in the row after it, and a midnight only in the next
  day's first candle. Such a flag is a state event with its own time, so `knowable_time` waits for it,
  `gap_at_close` holds what was known without it, and a read as of a moment gets the standing of that moment.
- A higher-timeframe bar is emitted only when it has closed, by a closing time the caller states.
- Under decision D-12 bars come from trades. `bar_source` says so on every row, and a tier T0 path on a
  source's official candles says `official_1m` there, because those bars are not what D-12 describes.

Every argument that decides timing is required, so that no caller gets the optimistic reading by leaving one
out.

Sums run in NumPy on rows sorted by time and trade id. Their result depends only on that order, not on how
many threads a data frame engine happens to use, which keeps the output byte-identical between runs.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.timeutil import MICROS_PER_MINUTE

UTC_TIME = pl.Datetime("us", "UTC")
Continuity = Literal["trade_id", "none"]

PROOF_TRADED = "traded"
PROOF_ID_RUN = "id_run"
PROOF_OFFICIAL = "official"
PROOF_NONE = "none"
SOURCE_TRADES = "trades"
SOURCE_OFFICIAL = "official_1m"
BOUNDARY_TRADES = "(open, close]"
BOUNDARY_OFFICIAL = "[open, close)"

BAR_SCHEMA: dict[str, pl.DataType] = {
    "venue": pl.String(),
    "symbol": pl.String(),
    "open_time": UTC_TIME,
    "close_time": UTC_TIME,
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
    "quote_volume": pl.Float64(),
    "buy_volume": pl.Float64(),
    "sell_volume": pl.Float64(),
    "settled_volume": pl.Float64(),
    "settled_quote_volume": pl.Float64(),
    "settled_buy_volume": pl.Float64(),
    "settled_sell_volume": pl.Float64(),
    "trade_count": pl.Int64(),
    "fill_count": pl.Int64(),
    "empty_proof": pl.String(),
    "gap": pl.Boolean(),
    "gap_at_close": pl.Boolean(),
    "bar_source": pl.String(),
    "boundary": pl.String(),
    "knowable_time": UTC_TIME,
}
_HIGHER_COLUMNS = {
    key: value for key, value in BAR_SCHEMA.items() if key not in ("empty_proof", "gap_at_close")
}
HIGHER_BAR_SCHEMA: dict[str, pl.DataType] = {
    **_HIGHER_COLUMNS,
    "n_1m": pl.Int32(),
    "complete": pl.Boolean(),
}
TRADE_INPUT_COLUMNS = (
    "ts",
    "price",
    "qty",
    "is_taker_buy",
    "trade_id",
    "file_row",
    "n_fills",
    "knowable_time",
)
_FLOW_COLUMNS = ("volume", "quote_volume", "buy_volume", "sell_volume")

# A candle's taker buy volume may sit this far above its volume by rounding alone.
_TAKER_SLACK = 1.000001
# Decimal places kept on summed quantities. The inputs have far fewer, so this removes only float noise.
_QTY_DECIMALS = 10
_QUOTE_DECIMALS = 6

_IntArray = npt.NDArray[np.int64]
_FloatArray = npt.NDArray[np.float64]
_BoolArray = npt.NDArray[np.bool_]


class TimingContractError(Exception):
    """A value was used before its knowable time, or a run asked for something it could not have."""


class DateGuardError(TimingContractError):
    """A read reached a date after the last opened date. Fold plan section 3."""


@dataclass(frozen=True)
class IdSkip:
    """A place where consecutive rows do not have consecutive trade ids, so rows may be missing."""

    after_id: int
    next_id: int
    from_us: int
    to_us: int
    known_at_us: int


def minute_close_us(ts_us: _IntArray) -> _IntArray:
    """Return the close of the (open, close] minute holding each timestamp.

    12:00:00.000000 closes the bar ending 12:00. 12:00:00.000001 belongs to the bar ending 12:01.
    """
    result: _IntArray = ((ts_us - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE
    return result


def _time_series(name: str, values: _IntArray) -> pl.Series:
    return pl.Series(name, values, dtype=pl.Int64).cast(UTC_TIME)


def _empty(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _us(series: pl.Series) -> _IntArray:
    return cast(_IntArray, series.dt.timestamp("us").to_numpy().astype(np.int64))


def _sorted_view(trades: pl.DataFrame) -> tuple[_IntArray, _IntArray, _IntArray]:
    """Return row order, sorted stamps and sorted ids. A row with no trade id sorts by its file position."""
    ts_us = _us(trades["ts"])
    rows = trades["file_row"].to_numpy().astype(np.int64)
    ids = trades["trade_id"].fill_null(-1).to_numpy().astype(np.int64)
    # A null id means the row has no sequence, so its position in the file decides ties.
    tie_break = np.where(trades["trade_id"].is_null().to_numpy().astype(bool), rows, ids)
    order = np.lexsort((tie_break, ts_us))
    return order, ts_us[order], ids[order]


def find_id_skips(trades: pl.DataFrame) -> list[IdSkip]:
    """Every place where the rows' own ids show that something between them is missing."""
    if trades.height < 2 or trades["trade_id"].null_count() == trades.height:
        return []
    order, ts_us, ids = _sorted_view(trades)
    known = _us(trades["knowable_time"])[order]
    positions = np.flatnonzero(np.diff(ids) != 1)
    return [
        IdSkip(int(ids[i]), int(ids[i + 1]), int(ts_us[i]), int(ts_us[i + 1]), int(known[i + 1]))
        for i in positions.tolist()
    ]


def find_long_quiets(trades: pl.DataFrame, max_quiet_us: int) -> list[tuple[int, int]]:
    """Silences longer than a source's declared limit, as (from, to) stamps."""
    if trades.height < 2:
        return []
    _, ts_us, _ = _sorted_view(trades)
    positions = np.flatnonzero(np.diff(ts_us) > max_quiet_us)
    return [(int(ts_us[i]), int(ts_us[i + 1])) for i in positions.tolist()]


def closes_between(from_us: int, to_us: int) -> set[int]:
    """Every minute close whose minute touches a stretch, from the bar holding its start to the bar holding
    its end."""
    first = ((from_us - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE
    last = ((to_us - 1) // MICROS_PER_MINUTE + 1) * MICROS_PER_MINUTE
    return set(range(first, last + 1, MICROS_PER_MINUTE))


def build_bars_1m(
    trades: pl.DataFrame,
    *,
    venue: str,
    symbol: str,
    first_close_us: int,
    last_close_us: int,
    continuity: Continuity,
    fill_span_allowance_us: int,
    received_at_us: int | None,
    gap_close_us: Collection[int] = frozenset(),
    late_gap_close_us: Mapping[int, int] | None = None,
) -> pl.DataFrame:
    """Build one-minute bars on an explicit grid, from first_close_us through last_close_us.

    The grid is required, so a bar's existence never depends on whether a later trade is in the data. trades
    may hold rows outside the grid: they add nothing to a bar's prices or volume, but the row before and after
    the grid prove continuity at its edges, and a row just before it can carry into the first bar's settled
    columns.

    continuity says whether trade ids can prove an empty minute. fill_span_allowance_us is how long after its
    stamp a row can run. received_at_us is when this system had the data, or None for an archive. gap_close_us
    marks bars known to be incomplete for reasons outside the rows, known by the time the bar is.
    late_gap_close_us does the same for a flag that rests on something later, as close -> when it became
    known.
    """
    for column in TRADE_INPUT_COLUMNS:
        if column not in trades.columns:
            raise ValueError(f"trades are missing column {column}")
    if continuity not in ("trade_id", "none"):
        raise ValueError(f"unknown continuity: {continuity!r}")
    if first_close_us % MICROS_PER_MINUTE != 0 or last_close_us % MICROS_PER_MINUTE != 0:
        raise ValueError("the grid is not on a minute boundary")
    if fill_span_allowance_us < 0:
        raise ValueError("a fill span allowance cannot be negative")
    if first_close_us > last_close_us:
        return _empty(BAR_SCHEMA)
    if continuity == "trade_id" and trades["trade_id"].null_count():
        raise ValueError("continuity by trade id needs an id on every row")

    grid: _IntArray = np.arange(first_close_us, last_close_us + 1, MICROS_PER_MINUTE, dtype=np.int64)
    size = grid.size
    open_: _FloatArray = np.full(size, np.nan)
    high: _FloatArray = np.full(size, np.nan)
    low: _FloatArray = np.full(size, np.nan)
    close: _FloatArray = np.full(size, np.nan)
    volume: _FloatArray = np.zeros(size)
    quote: _FloatArray = np.zeros(size)
    buy: _FloatArray = np.zeros(size)
    sell: _FloatArray = np.zeros(size)
    settled_volume: _FloatArray = np.zeros(size)
    settled_quote: _FloatArray = np.zeros(size)
    settled_buy: _FloatArray = np.zeros(size)
    settled_sell: _FloatArray = np.zeros(size)
    count: _IntArray = np.zeros(size, dtype=np.int64)
    fills: _IntArray = np.zeros(size, dtype=np.int64)
    knowable: _IntArray = grid + fill_span_allowance_us
    if received_at_us is not None:
        knowable = np.maximum(knowable, received_at_us)
    proof = np.full(size, PROOF_NONE, dtype=object)
    gaps: _BoolArray = np.isin(grid, list(gap_close_us)) if gap_close_us else np.zeros(size, dtype=bool)
    at_close = gaps.copy()

    if trades.height:
        order, ts_us, ids = _sorted_view(trades)
        closes = minute_close_us(ts_us)
        price: _FloatArray = trades["price"].to_numpy().astype(np.float64)[order]
        qty: _FloatArray = trades["qty"].to_numpy().astype(np.float64)[order]
        taker_buy = trades["is_taker_buy"].to_numpy().astype(bool)[order]
        n_fills: _IntArray = trades["n_fills"].to_numpy().astype(np.int64)[order]
        row_knowable = _us(trades["knowable_time"])[order]

        keep = (closes >= first_close_us) & (closes <= last_close_us)
        if keep.any():
            kept_close = closes[keep]
            starts = np.concatenate(([0], np.flatnonzero(np.diff(kept_close)) + 1))
            ends = np.concatenate((starts[1:], [kept_close.size]))
            slots = (kept_close[starts] - first_close_us) // MICROS_PER_MINUTE
            kept_price, kept_qty = price[keep], qty[keep]
            kept_buy = taker_buy[keep]
            open_[slots] = kept_price[starts]
            close[slots] = kept_price[ends - 1]
            high[slots] = np.maximum.reduceat(kept_price, starts)
            low[slots] = np.minimum.reduceat(kept_price, starts)
            volume[slots] = np.add.reduceat(kept_qty, starts)
            quote[slots] = np.add.reduceat(kept_price * kept_qty, starts)
            buy[slots] = np.add.reduceat(np.where(kept_buy, kept_qty, 0.0), starts)
            sell[slots] = np.add.reduceat(np.where(kept_buy, 0.0, kept_qty), starts)
            count[slots] = ends - starts
            fills[slots] = np.add.reduceat(n_fills[keep], starts)
            knowable[slots] = np.maximum(knowable[slots], np.maximum.reduceat(row_knowable[keep], starts))
            proof[slots] = PROOF_TRADED

        _add_settled(
            settled_volume,
            settled_quote,
            settled_buy,
            settled_sell,
            grid_first=first_close_us,
            grid_last=last_close_us,
            ts_us=ts_us,
            closes=closes,
            price=price,
            qty=qty,
            taker_buy=taker_buy,
            allowance_us=fill_span_allowance_us,
        )
        if continuity == "trade_id":
            _mark_proven_empty(grid, count, proof, knowable, closes, ids, row_knowable)
            # A skip shows only in the row after it, so nothing it flags is known before that row is.
            for skip in find_id_skips(trades):
                touched = np.isin(grid, list(closes_between(skip.from_us, skip.to_us)))
                gaps |= touched
                knowable[touched] = np.maximum(knowable[touched], skip.known_at_us)

    if late_gap_close_us:
        for close_us, known_at_us in late_gap_close_us.items():
            slot = (close_us - first_close_us) // MICROS_PER_MINUTE
            if first_close_us <= close_us <= last_close_us and close_us % MICROS_PER_MINUTE == 0:
                gaps[slot] = True
                knowable[slot] = max(int(knowable[slot]), known_at_us)
    gaps |= proof == PROOF_NONE
    # An empty minute's proof comes from a later row, so at its close nothing yet vouches for it.
    at_close |= count == 0
    return _bars_frame(
        venue,
        symbol,
        grid,
        open_,
        high,
        low,
        close,
        (volume, quote, buy, sell),
        (settled_volume, settled_quote, settled_buy, settled_sell),
        count,
        fills,
        proof,
        gaps,
        at_close,
        SOURCE_TRADES,
        knowable,
    )


def _bars_frame(
    venue: str,
    symbol: str,
    grid: _IntArray,
    open_: _FloatArray,
    high: _FloatArray,
    low: _FloatArray,
    close: _FloatArray,
    flows: tuple[_FloatArray, _FloatArray, _FloatArray, _FloatArray],
    settled: tuple[_FloatArray, _FloatArray, _FloatArray, _FloatArray],
    count: _IntArray,
    fills: _IntArray,
    proof: npt.NDArray[np.object_],
    gaps: _BoolArray,
    at_close: _BoolArray,
    bar_source: str,
    knowable: _IntArray,
) -> pl.DataFrame:
    volume, quote, buy, sell = flows
    settled_volume, settled_quote, settled_buy, settled_sell = settled
    size = grid.size
    return pl.DataFrame(
        [
            pl.repeat(venue, size, eager=True, dtype=pl.String).alias("venue"),
            pl.repeat(symbol, size, eager=True, dtype=pl.String).alias("symbol"),
            _time_series("open_time", grid - MICROS_PER_MINUTE),
            _time_series("close_time", grid),
            pl.Series("open", open_).fill_nan(None),
            pl.Series("high", high).fill_nan(None),
            pl.Series("low", low).fill_nan(None),
            pl.Series("close", close).fill_nan(None),
            pl.Series("volume", np.round(volume, _QTY_DECIMALS)),
            pl.Series("quote_volume", np.round(quote, _QUOTE_DECIMALS)),
            pl.Series("buy_volume", np.round(buy, _QTY_DECIMALS)),
            pl.Series("sell_volume", np.round(sell, _QTY_DECIMALS)),
            pl.Series("settled_volume", np.round(settled_volume, _QTY_DECIMALS)),
            pl.Series("settled_quote_volume", np.round(settled_quote, _QUOTE_DECIMALS)),
            pl.Series("settled_buy_volume", np.round(settled_buy, _QTY_DECIMALS)),
            pl.Series("settled_sell_volume", np.round(settled_sell, _QTY_DECIMALS)),
            pl.Series("trade_count", count, dtype=pl.Int64),
            pl.Series("fill_count", fills, dtype=pl.Int64),
            pl.Series("empty_proof", proof.tolist(), dtype=pl.String),
            pl.Series("gap", gaps, dtype=pl.Boolean),
            pl.Series("gap_at_close", at_close, dtype=pl.Boolean),
            pl.repeat(bar_source, size, eager=True, dtype=pl.String).alias("bar_source"),
            pl.repeat(_boundary_of(bar_source), size, eager=True, dtype=pl.String).alias("boundary"),
            _time_series("knowable_time", knowable),
        ]
    )


def _boundary_of(bar_source: str) -> str:
    return BOUNDARY_OFFICIAL if bar_source == SOURCE_OFFICIAL else BOUNDARY_TRADES


def candle_row_faults(candles: pl.DataFrame) -> _BoolArray:
    """Which candle rows break a check at the row (ruling 7 condition 5). A failure flags that minute.

    A row with zero trades carries no print, so its prices are not checked: they are removed in any case.
    """
    if candles.is_empty():
        return np.zeros(0, dtype=bool)
    traded = pl.col("trade_count") > 0
    faults = candles.select(
        (
            (
                traded
                & (
                    (pl.col("high") < pl.max_horizontal("open", "close"))
                    | (pl.col("low") > pl.min_horizontal("open", "close"))
                )
            )
            | (pl.col("taker_buy_volume") > pl.col("volume") * _TAKER_SLACK + 1e-9)
            | ((pl.col("trade_count") == 0) & (pl.col("volume") > 0))
        ).alias("fault")
    )
    result: _BoolArray = faults["fault"].to_numpy().astype(bool)
    return result


def bars_from_official(
    candles: pl.DataFrame,
    *,
    venue: str,
    symbol: str,
    first_close_us: int,
    last_close_us: int,
    candle_allowance_us: int,
) -> pl.DataFrame:
    """One-minute bars from a venue's official candles, for a tier T0 path with no trades. They say so on
    every row.

    This is ruling 7 of the leak recheck, and not what decision D-12 describes, where bars come from trades.
    Each row states `bar_source` of `official_1m` and `boundary` of `[open, close)`, and they live in their
    own datasets, so they can never be read as trade-built bars. A candle covers [open, open + 60 s), so a
    print exactly on a boundary is in the later bar.

    `close_time` is `open_time + 60 s` on the grid, and is known at `close_time + candle_allowance`. The
    file's own close field has already been checked and is not used, and neither is the date a file was
    published: the contract asks when a live system could have had the value.

    A row with no trades has null prices, whether or not the venue carries the last close forward
    (`UNVERIFIED`), because a carried price could touch a stop. Its `empty_proof` is `official`, and the proof
    is the row itself, so nothing here rests on a later row. A missing row is a gap, and so is a row that
    fails a check at the row. Nothing has checked these values against anything else, so reconciliation is
    reported as not available.
    """
    if first_close_us % MICROS_PER_MINUTE != 0 or last_close_us % MICROS_PER_MINUTE != 0:
        raise ValueError("the grid is not on a minute boundary")
    if candle_allowance_us < 0:
        raise ValueError("a candle allowance cannot be negative")
    if first_close_us > last_close_us:
        return _empty(BAR_SCHEMA)
    grid: _IntArray = np.arange(first_close_us, last_close_us + 1, MICROS_PER_MINUTE, dtype=np.int64)
    size = grid.size
    faulty: _BoolArray = np.zeros(size, dtype=bool)
    open_: _FloatArray = np.full(size, np.nan)
    high: _FloatArray = np.full(size, np.nan)
    low: _FloatArray = np.full(size, np.nan)
    close: _FloatArray = np.full(size, np.nan)
    volume: _FloatArray = np.zeros(size)
    quote: _FloatArray = np.zeros(size)
    buy: _FloatArray = np.zeros(size)
    count: _IntArray = np.zeros(size, dtype=np.int64)
    proof = np.full(size, PROOF_NONE, dtype=object)
    if candles.height:
        closes = _us(candles["open_time"]) + MICROS_PER_MINUTE
        inside = (closes >= first_close_us) & (closes <= last_close_us)
        slots = (closes[inside] - first_close_us) // MICROS_PER_MINUTE
        traded = candles["trade_count"].to_numpy().astype(np.int64)[inside] > 0

        def field(name: str) -> _FloatArray:
            values: _FloatArray = candles[name].to_numpy().astype(np.float64)[inside]
            return values

        for target, name in ((open_, "open"), (high, "high"), (low, "low"), (close, "close")):
            target[slots[traded]] = field(name)[traded]
        volume[slots] = field("volume")
        quote[slots] = field("quote_volume")
        buy[slots] = field("taker_buy_volume")
        count[slots] = candles["trade_count"].to_numpy().astype(np.int64)[inside]
        proof[slots] = np.where(traded, PROOF_TRADED, PROOF_OFFICIAL)
        faulty[slots] = candle_row_faults(candles)[inside]
    gaps: _BoolArray = (proof == PROOF_NONE) | faulty
    sell: _FloatArray = np.maximum(volume - buy, 0.0)
    flows = (volume, quote, buy, sell)
    return _bars_frame(
        venue,
        symbol,
        grid,
        open_,
        high,
        low,
        close,
        flows,
        flows,
        count,
        count,
        proof,
        gaps,
        gaps,
        SOURCE_OFFICIAL,
        grid + candle_allowance_us,
    )


def _add_settled(
    settled_volume: _FloatArray,
    settled_quote: _FloatArray,
    settled_buy: _FloatArray,
    settled_sell: _FloatArray,
    *,
    grid_first: int,
    grid_last: int,
    ts_us: _IntArray,
    closes: _IntArray,
    price: _FloatArray,
    qty: _FloatArray,
    taker_buy: _BoolArray,
    allowance_us: int,
) -> None:
    """Fill the columns holding only what had printed by each close.

    A row counts in a bar only when it was stamped at least the allowance before that bar's close, and
    otherwise in the next bar. The test reads the stamp alone. A row's fill count includes fills from after
    the close, so a rule that looked at it would read the future, which is the leak audit's correction to its
    own ruling 2. With an allowance of zero, nothing moves.
    """
    defer = (closes - ts_us) < allowance_us
    settle_close = closes + np.where(defer, MICROS_PER_MINUTE, 0)
    inside = (settle_close >= grid_first) & (settle_close <= grid_last)
    if not inside.any():
        return
    slots = (settle_close[inside] - grid_first) // MICROS_PER_MINUTE
    weights = qty[inside]
    is_buy = taker_buy[inside]
    size = settled_volume.size
    # bincount adds in row order on one thread, so the result depends only on the sorted rows.
    settled_volume += np.bincount(slots, weights=weights, minlength=size)
    settled_quote += np.bincount(slots, weights=price[inside] * weights, minlength=size)
    settled_buy += np.bincount(slots, weights=np.where(is_buy, weights, 0.0), minlength=size)
    settled_sell += np.bincount(slots, weights=np.where(is_buy, 0.0, weights), minlength=size)


def _mark_proven_empty(
    grid: _IntArray,
    count: _IntArray,
    proof: npt.NDArray[np.object_],
    knowable: _IntArray,
    closes: _IntArray,
    ids: _IntArray,
    row_knowable: _IntArray,
) -> None:
    """An empty minute is proven only by the rows around it having consecutive ids.

    That proof comes from the next row, so the minute is not known to be empty until that row is known.
    """
    empty_slots = np.flatnonzero(count == 0)
    if empty_slots.size == 0:
        return
    next_row = np.searchsorted(closes, grid[empty_slots], side="left")
    has_both = (next_row > 0) & (next_row < ids.size)
    proven_slots = empty_slots[has_both]
    after = next_row[has_both]
    consecutive = ids[after] == ids[after - 1] + 1
    slots = proven_slots[consecutive]
    proof[slots] = PROOF_ID_RUN
    knowable[slots] = np.maximum(knowable[slots], row_knowable[after[consecutive]])


def _first_valid(values: _FloatArray) -> float:
    valid = values[~np.isnan(values)]
    return float(valid[0]) if valid.size else float("nan")


def _last_valid(values: _FloatArray) -> float:
    valid = values[~np.isnan(values)]
    return float(valid[-1]) if valid.size else float("nan")


def aggregate_bars(bars_1m: pl.DataFrame, minutes: int, *, through_close_us: int) -> pl.DataFrame:
    """Aggregate one-minute bars into a higher timeframe aligned to the UTC epoch.

    through_close_us is the last minute the caller knows to be closed. It is required, so an unfinished bar
    can never be seen, whatever the input holds. A closed bar with minutes missing or flagged is emitted with
    complete=False and gap=True, because hiding it would look like a clean series. It is knowable at the
    latest of its inputs.
    """
    if minutes < 2 or 1440 % minutes != 0:
        raise ValueError(f"timeframe {minutes}m must be above 1m and divide a UTC day")
    if bars_1m.is_empty():
        return _empty(HIGHER_BAR_SCHEMA)
    # Prices from different venues are never merged into one bar, under C1.
    if bars_1m["venue"].n_unique() != 1 or bars_1m["symbol"].n_unique() != 1:
        raise ValueError("one venue and one symbol at a time")
    # Trade bars and candle bars have different boundaries, so one bar cannot hold both.
    if bars_1m["bar_source"].n_unique() != 1:
        raise ValueError("one bar source at a time")
    ordered = bars_1m.sort("close_time")
    close_us = _us(ordered["close_time"])
    width = minutes * MICROS_PER_MINUTE
    buckets: _IntArray = ((close_us - 1) // width + 1) * width

    def floats(name: str) -> _FloatArray:
        return cast(_FloatArray, ordered[name].fill_null(np.nan).to_numpy().astype(np.float64))

    open_, high, low, close = floats("open"), floats("high"), floats("low"), floats("close")
    flows = {name: floats(name) for name in _FLOW_COLUMNS}
    settled = {f"settled_{name}": floats(f"settled_{name}") for name in _FLOW_COLUMNS}
    count = ordered["trade_count"].to_numpy().astype(np.int64)
    fills = ordered["fill_count"].to_numpy().astype(np.int64)
    gaps = ordered["gap"].to_numpy().astype(bool)
    knowable = _us(ordered["knowable_time"])

    starts = np.concatenate(([0], np.flatnonzero(np.diff(buckets)) + 1))
    ends = np.concatenate((starts[1:], [buckets.size]))
    rows: list[dict[str, object]] = []
    for start, end in zip(starts, ends, strict=True):
        bucket_close = int(buckets[start])
        if bucket_close > through_close_us:
            continue  # still open as far as the caller knows
        span_high = high[start:end]
        span_low = low[start:end]
        has_price = bool((~np.isnan(span_high)).any())
        n_1m = int(end - start)
        any_gap = bool(gaps[start:end].any())
        complete = n_1m == minutes and not any_gap
        row: dict[str, object] = {
            "close_us": bucket_close,
            "open": _first_valid(open_[start:end]),
            "high": float(np.nanmax(span_high)) if has_price else float("nan"),
            "low": float(np.nanmin(span_low)) if has_price else float("nan"),
            "close": _last_valid(close[start:end]),
            "trade_count": int(np.sum(count[start:end])),
            "fill_count": int(np.sum(fills[start:end])),
            "gap": not complete,
            "knowable_us": max(bucket_close, int(knowable[start:end].max())),
            "n_1m": n_1m,
            "complete": complete,
        }
        for name, values in {**flows, **settled}.items():
            decimals = _QUOTE_DECIMALS if "quote" in name else _QTY_DECIMALS
            row[name] = float(np.round(np.sum(values[start:end]), decimals))
        rows.append(row)
    if not rows:
        return _empty(HIGHER_BAR_SCHEMA)

    close_values = np.array([r["close_us"] for r in rows], dtype=np.int64)
    knowable_values = np.array([r["knowable_us"] for r in rows], dtype=np.int64)

    def float_column(name: str) -> pl.Series:
        return pl.Series(name, np.array([r[name] for r in rows], dtype=np.float64))

    size = len(rows)
    venue = str(ordered["venue"][0])
    symbol = str(ordered["symbol"][0])
    bar_source = str(ordered["bar_source"][0])
    return pl.DataFrame(
        [
            pl.repeat(venue, size, eager=True, dtype=pl.String).alias("venue"),
            pl.repeat(symbol, size, eager=True, dtype=pl.String).alias("symbol"),
            _time_series("open_time", close_values - width),
            _time_series("close_time", close_values),
            float_column("open").fill_nan(None),
            float_column("high").fill_nan(None),
            float_column("low").fill_nan(None),
            float_column("close").fill_nan(None),
            float_column("volume"),
            float_column("quote_volume"),
            float_column("buy_volume"),
            float_column("sell_volume"),
            float_column("settled_volume"),
            float_column("settled_quote_volume"),
            float_column("settled_buy_volume"),
            float_column("settled_sell_volume"),
            pl.Series("trade_count", [r["trade_count"] for r in rows], dtype=pl.Int64),
            pl.Series("fill_count", [r["fill_count"] for r in rows], dtype=pl.Int64),
            pl.Series("gap", [r["gap"] for r in rows], dtype=pl.Boolean),
            pl.repeat(bar_source, size, eager=True, dtype=pl.String).alias("bar_source"),
            pl.repeat(_boundary_of(bar_source), size, eager=True, dtype=pl.String).alias("boundary"),
            _time_series("knowable_time", knowable_values),
            pl.Series("n_1m", [r["n_1m"] for r in rows], dtype=pl.Int32),
            pl.Series("complete", [r["complete"] for r in rows], dtype=pl.Boolean),
        ]
    )


def _time_literal(value_us: int) -> pl.Expr:
    return pl.lit(value_us, dtype=pl.Int64).cast(UTC_TIME)


def visible_bars(bars: pl.DataFrame, as_of_us: int) -> pl.DataFrame:
    """Return only the bars knowable by the given moment."""
    return bars.filter(pl.col("knowable_time") <= _time_literal(as_of_us))


def assert_knowable(frame: pl.DataFrame, as_of_us: int) -> None:
    """Raise if any row was not yet knowable at the given moment. For use at joins."""
    if frame.is_empty():
        return
    newest = cast(int, frame["knowable_time"].dt.timestamp("us").max())
    if newest > as_of_us:
        raise TimingContractError(f"a row knowable at {newest} was used at {as_of_us}")


def bars_for_run(bars: pl.DataFrame, t_cut_us: int, t_dec_us: int) -> pl.DataFrame:
    """What one run may read, under the run clock of C17. Later code reads bars through this, or `ideal_view`.

    Contract item 1 says when a value could exist, and receipt says when this system had it. So a run needs
    both conditions at once: a close at or before t_cut, and knowable by t_dec. A bar past t_cut is simply not
    returned. A bar at or before t_cut that this run could not yet have had is an error, because it means the
    run is being given data from its own future. That is never quietly dropped.
    """
    if t_dec_us < t_cut_us:
        raise TimingContractError("a run cannot commit before its own data cut-off")
    selected = bars.filter(pl.col("close_time") <= _time_literal(t_cut_us))
    assert_knowable(selected, t_dec_us)
    return selected


def trades_for_run(trades: pl.DataFrame, t_cut_us: int, t_dec_us: int) -> pl.DataFrame:
    """The trades one run may read, by the same two conditions as bars_for_run."""
    if t_dec_us < t_cut_us:
        raise TimingContractError("a run cannot commit before its own data cut-off")
    selected = trades.filter(pl.col("ts") <= _time_literal(t_cut_us))
    assert_knowable(selected, t_dec_us)
    return selected


def standing_as_of(bars_1m: pl.DataFrame, at_us: int) -> pl.DataFrame:
    """One-minute bars closed by a moment, each with its standing as known at that moment.

    A `gap`, a proof or a completeness is a state event with its own time, and does not exist before the row
    that shows it is knowable. So a minute whose standing rests on something later reads as a build with no
    later row would give: an empty minute is unproven and a gap, and a traded minute has only the flags known
    at its close. The result on full data equals the result on data truncated at the moment, on every column
    but `knowable_time`, and that is why the views built on this drop `knowable_time`: it would hand the
    reader the time of the next trade.
    """
    moment = _time_literal(at_us)
    closed = bars_1m.filter(pl.col("close_time") <= moment)
    # A candle's proof is the row itself, so on these bars nothing rests on a later row (ruling 7 condition
    # 4).
    late = (pl.col("knowable_time") > moment) & (pl.col("bar_source") != SOURCE_OFFICIAL)
    return closed.with_columns(
        pl.when(late).then(pl.col("gap_at_close")).otherwise(pl.col("gap")).alias("gap"),
        pl.when(late & (pl.col("trade_count") == 0))
        .then(pl.lit(PROOF_NONE))
        .otherwise(pl.col("empty_proof"))
        .alias("empty_proof"),
    )


def as_of_view(
    bars_1m: pl.DataFrame, minutes: int, at_us: int, *, through_us: int | None = None
) -> pl.DataFrame:
    """Closed bars of a timeframe as they stood at a moment. Higher bars come from that view, not from stored
    ones.

    through_us limits the closes when a read comes after the decision it serves, as in IDEAL-1M.
    """
    last = at_us if through_us is None else through_us
    standing = standing_as_of(bars_1m, at_us).filter(pl.col("close_time") <= _time_literal(last))
    if minutes == 1:
        return standing.drop("knowable_time", "gap_at_close")
    return aggregate_bars(standing, minutes, through_close_us=last).drop("knowable_time")


def ideal_view(bars: pl.DataFrame, *, ideal_allowed: bool, keep_fill_count: bool = False) -> pl.DataFrame:
    """Bars as IDEAL mode may read them: only what had printed by each close.

    A decision at a close with no allowance cannot use a volume that might include later fills, so the settled
    columns replace the plain ones and the plain ones are gone, along with `fill_count`, which has no settled
    form and moves with a fill after the close. A source whose prices can carry an after-close print gets no
    IDEAL view at all.

    On official candles, once ruling 7's condition 2 is shown, the plain columns are already settled and
    `fill_count` holds only what printed in the minute, so the reader keeps it.
    """
    if not ideal_allowed:
        raise TimingContractError(
            "this source's row shape can put later prints in a bar, or its allowance is not measured, "
            "so it has no IDEAL view"
        )
    renamed = {f"settled_{name}": name for name in _FLOW_COLUMNS}
    extras = [name for name in ("knowable_time", "gap_at_close") if name in bars.columns]
    dropped = [*_FLOW_COLUMNS, *extras] if keep_fill_count else [*_FLOW_COLUMNS, "fill_count", *extras]
    return bars.drop(dropped).rename(renamed)
