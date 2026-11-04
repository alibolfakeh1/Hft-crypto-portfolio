"""Bars from trades, following the timing contract in docs/00_CHARTER.md section 3.

- A bar covers (open_time, close_time], so a trade exactly on a boundary closes the bar ending there.
- A bar is knowable at close_time, or later when its data reached us later.
- A higher-timeframe bar is emitted only when it has closed, and is knowable only then.
- A minute with no trades is a real row: prices null, volumes zero. Nothing is forward filled, because
  a missing price must not look like a traded one.

Sums run in NumPy on rows sorted by time and trade id. Their result depends only on that order, not on how
many threads a data frame engine happens to use, which keeps the output byte-identical between runs.
"""

from __future__ import annotations

from typing import cast

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.timeutil import MICROS_PER_MINUTE

UTC_TIME = pl.Datetime("us", "UTC")

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
    "trade_count": pl.Int64(),
    "fill_count": pl.Int64(),
    "gap": pl.Boolean(),
    "knowable_time": UTC_TIME,
}
HIGHER_BAR_SCHEMA: dict[str, pl.DataType] = {
    **BAR_SCHEMA,
    "n_1m": pl.Int32(),
    "complete": pl.Boolean(),
}
TRADE_INPUT_COLUMNS = ("ts", "price", "qty", "is_taker_buy", "trade_id", "n_fills")

# Decimal places kept on summed quantities. The inputs have far fewer, so this removes only float noise.
_QTY_DECIMALS = 10
_QUOTE_DECIMALS = 6

_IntArray = npt.NDArray[np.int64]
_FloatArray = npt.NDArray[np.float64]


class TimingContractError(Exception):
    """A value was used before its knowable time."""


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


def build_bars_1m(
    trades: pl.DataFrame,
    *,
    venue: str,
    symbol: str,
    first_close_us: int | None = None,
    last_close_us: int | None = None,
    knowable_at_us: int | None = None,
    gap_close_us: set[int] | None = None,
) -> pl.DataFrame:
    """Build one-minute bars from trades.

    The grid runs from first_close_us to last_close_us. Without them, it spans the trades given. Trades
    outside the grid are ignored. knowable_at_us is the moment this data actually reached us, used by the
    poll path: a bar is then knowable at the later of that moment and its close. gap_close_us marks bars
    known to be incomplete.
    """
    for column in TRADE_INPUT_COLUMNS:
        if column not in trades.columns:
            raise ValueError(f"trades are missing column {column}")
    if first_close_us is not None and first_close_us % MICROS_PER_MINUTE != 0:
        raise ValueError("first_close_us is not on a minute boundary")
    if last_close_us is not None and last_close_us % MICROS_PER_MINUTE != 0:
        raise ValueError("last_close_us is not on a minute boundary")

    ts_us = trades["ts"].dt.timestamp("us").to_numpy().astype(np.int64)
    closes = minute_close_us(ts_us)
    first = int(closes.min()) if first_close_us is None and closes.size else first_close_us
    last = int(closes.max()) if last_close_us is None and closes.size else last_close_us
    if first is None or last is None or first > last:
        return _empty(BAR_SCHEMA)

    grid: _IntArray = np.arange(first, last + 1, MICROS_PER_MINUTE, dtype=np.int64)
    size = grid.size
    open_: _FloatArray = np.full(size, np.nan)
    high: _FloatArray = np.full(size, np.nan)
    low: _FloatArray = np.full(size, np.nan)
    close: _FloatArray = np.full(size, np.nan)
    volume: _FloatArray = np.zeros(size)
    quote: _FloatArray = np.zeros(size)
    buy: _FloatArray = np.zeros(size)
    sell: _FloatArray = np.zeros(size)
    count: _IntArray = np.zeros(size, dtype=np.int64)
    fills: _IntArray = np.zeros(size, dtype=np.int64)

    keep = (closes >= first) & (closes <= last)
    if keep.any():
        trade_ids = trades["trade_id"].to_numpy().astype(np.int64)
        order = np.lexsort((trade_ids[keep], ts_us[keep]))
        sorted_close = closes[keep][order]
        price: _FloatArray = trades["price"].to_numpy().astype(np.float64)[keep][order]
        qty: _FloatArray = trades["qty"].to_numpy().astype(np.float64)[keep][order]
        taker_buy = trades["is_taker_buy"].to_numpy().astype(bool)[keep][order]
        n_fills: _IntArray = trades["n_fills"].to_numpy().astype(np.int64)[keep][order]

        starts = np.concatenate(([0], np.flatnonzero(np.diff(sorted_close)) + 1))
        ends = np.concatenate((starts[1:], [sorted_close.size]))
        slots = (sorted_close[starts] - first) // MICROS_PER_MINUTE
        open_[slots] = price[starts]
        close[slots] = price[ends - 1]
        high[slots] = np.maximum.reduceat(price, starts)
        low[slots] = np.minimum.reduceat(price, starts)
        volume[slots] = np.add.reduceat(qty, starts)
        quote[slots] = np.add.reduceat(price * qty, starts)
        buy[slots] = np.add.reduceat(np.where(taker_buy, qty, 0.0), starts)
        sell[slots] = np.add.reduceat(np.where(taker_buy, 0.0, qty), starts)
        count[slots] = ends - starts
        fills[slots] = np.add.reduceat(n_fills, starts)

    knowable = grid if knowable_at_us is None else np.maximum(grid, knowable_at_us)
    gaps = np.isin(grid, list(gap_close_us)) if gap_close_us else np.zeros(size, dtype=bool)
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
            pl.Series("trade_count", count, dtype=pl.Int64),
            pl.Series("fill_count", fills, dtype=pl.Int64),
            pl.Series("gap", gaps, dtype=pl.Boolean),
            _time_series("knowable_time", knowable),
        ]
    )


def _first_valid(values: _FloatArray) -> float:
    valid = values[~np.isnan(values)]
    return float(valid[0]) if valid.size else float("nan")


def _last_valid(values: _FloatArray) -> float:
    valid = values[~np.isnan(values)]
    return float(valid[-1]) if valid.size else float("nan")


def aggregate_bars(bars_1m: pl.DataFrame, minutes: int) -> pl.DataFrame:
    """Aggregate one-minute bars into a higher timeframe aligned to the UTC epoch.

    A higher bar appears only once its closing minute is among the input, so an unfinished bar can never
    be seen. A closed bar with minutes missing is emitted with complete=False and gap=True, because hiding
    it would look like a clean series. It is knowable at the later of its close and its newest input.
    """
    if minutes < 2 or 1440 % minutes != 0:
        raise ValueError(f"timeframe {minutes}m must be above 1m and divide a UTC day")
    if bars_1m.is_empty():
        return _empty(HIGHER_BAR_SCHEMA)
    ordered = bars_1m.sort("close_time")
    close_us = ordered["close_time"].dt.timestamp("us").to_numpy().astype(np.int64)
    width = minutes * MICROS_PER_MINUTE
    buckets: _IntArray = ((close_us - 1) // width + 1) * width
    newest_known = int(close_us.max())

    def floats(name: str) -> _FloatArray:
        return ordered[name].fill_null(np.nan).to_numpy().astype(np.float64)

    open_, high, low, close = floats("open"), floats("high"), floats("low"), floats("close")
    volume, quote = floats("volume"), floats("quote_volume")
    buy, sell = floats("buy_volume"), floats("sell_volume")
    count = ordered["trade_count"].to_numpy().astype(np.int64)
    fills = ordered["fill_count"].to_numpy().astype(np.int64)
    gaps = ordered["gap"].to_numpy().astype(bool)
    knowable = ordered["knowable_time"].dt.timestamp("us").to_numpy().astype(np.int64)

    starts = np.concatenate(([0], np.flatnonzero(np.diff(buckets)) + 1))
    ends = np.concatenate((starts[1:], [buckets.size]))
    rows: list[dict[str, object]] = []
    for start, end in zip(starts, ends, strict=True):
        bucket_close = int(buckets[start])
        if bucket_close > newest_known:
            continue  # still open as far as the input knows
        span_high = high[start:end]
        span_low = low[start:end]
        has_price = bool((~np.isnan(span_high)).any())
        n_1m = int(end - start)
        complete = n_1m == minutes
        rows.append(
            {
                "close_us": bucket_close,
                "open": _first_valid(open_[start:end]),
                "high": float(np.nanmax(span_high)) if has_price else float("nan"),
                "low": float(np.nanmin(span_low)) if has_price else float("nan"),
                "close": _last_valid(close[start:end]),
                "volume": float(np.round(np.sum(volume[start:end]), _QTY_DECIMALS)),
                "quote_volume": float(np.round(np.sum(quote[start:end]), _QUOTE_DECIMALS)),
                "buy_volume": float(np.round(np.sum(buy[start:end]), _QTY_DECIMALS)),
                "sell_volume": float(np.round(np.sum(sell[start:end]), _QTY_DECIMALS)),
                "trade_count": int(np.sum(count[start:end])),
                "fill_count": int(np.sum(fills[start:end])),
                "gap": bool(gaps[start:end].any()) or not complete,
                "knowable_us": max(bucket_close, int(knowable[start:end].max())),
                "n_1m": n_1m,
                "complete": complete,
            }
        )
    if not rows:
        return _empty(HIGHER_BAR_SCHEMA)

    close_values = np.array([r["close_us"] for r in rows], dtype=np.int64)
    knowable_values = np.array([r["knowable_us"] for r in rows], dtype=np.int64)

    def float_column(name: str) -> pl.Series:
        return pl.Series(name, np.array([r[name] for r in rows], dtype=np.float64))

    size = len(rows)
    venue = str(ordered["venue"][0])
    symbol = str(ordered["symbol"][0])
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
            pl.Series("trade_count", [r["trade_count"] for r in rows], dtype=pl.Int64),
            pl.Series("fill_count", [r["fill_count"] for r in rows], dtype=pl.Int64),
            pl.Series("gap", [r["gap"] for r in rows], dtype=pl.Boolean),
            _time_series("knowable_time", knowable_values),
            pl.Series("n_1m", [r["n_1m"] for r in rows], dtype=pl.Int32),
            pl.Series("complete", [r["complete"] for r in rows], dtype=pl.Boolean),
        ]
    )


def visible_bars(bars: pl.DataFrame, as_of_us: int) -> pl.DataFrame:
    """Return only the bars knowable by the given moment."""
    limit = pl.lit(as_of_us, dtype=pl.Int64).cast(UTC_TIME)
    return bars.filter(pl.col("knowable_time") <= limit)


def assert_knowable(bars: pl.DataFrame, as_of_us: int) -> None:
    """Raise if any row was not yet knowable at the given moment. For use at joins."""
    if bars.is_empty():
        return
    newest = cast(int, bars["knowable_time"].dt.timestamp("us").max())
    if newest > as_of_us:
        raise TimingContractError(f"bar knowable at {newest} used at {as_of_us}")
