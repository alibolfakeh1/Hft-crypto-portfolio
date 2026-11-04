"""Checks on bars: against official candles, against a rebuild, and between venues."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import polars as pl

from hft_crypto.config import ReconTolerance

STATUS_PASS = "pass"  # noqa: S105
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
# Quantities are compared as whole units of this fraction of a coin.
_QTY_SCALE = 100_000_000


@dataclass(frozen=True)
class OfficialReconciliation:
    """Our trades and bars against official candles for one UTC day."""

    status: str
    needs_previous_day: bool
    trades_volume: float
    official_volume: float
    volume_diff: float
    volume_explainable_up: float
    volume_explainable_down: float | None
    trades_taker_buy: float
    official_taker_buy: float
    taker_buy_diff: float
    trades_fills: int
    official_count: int
    bars_compared: int
    bars_volume_diff_over_0_001: int
    max_bar_volume_diff: float
    boundaries_unexplained: int
    implied_carry_in: float
    largest_window_needed_ms: float
    bars_price_over_tolerance: int
    max_bar_price_diff: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floats(frame: pl.DataFrame, name: str) -> np.ndarray[Any, np.dtype[np.float64]]:
    return frame[name].fill_null(np.nan).to_numpy().astype(np.float64)


def _scaled(values: np.ndarray[Any, np.dtype[np.float64]]) -> np.ndarray[Any, np.dtype[np.int64]]:
    """Quantities as integers, so sums over millions of trades carry no floating point noise."""
    result: np.ndarray[Any, np.dtype[np.int64]] = np.rint(values * _QTY_SCALE).astype(np.int64)
    return result


def _trailing(ts_us: Any, qty: Any, end_us: int, window_us: int) -> int:
    """Quantity stamped in the window just before an instant."""
    return int(qty[(ts_us >= end_us - window_us) & (ts_us < end_us)].sum())


def reconcile_official(
    file_trades: pl.DataFrame,
    bars: pl.DataFrame,
    official: pl.DataFrame,
    tolerance: ReconTolerance,
    *,
    previous_tail: pl.DataFrame | None = None,
) -> OfficialReconciliation:
    """Compare one day.

    An aggregate trade file gives each aggregate one timestamp, while its fills can run on for a moment, and
    official candles count each fill in its own minute. So volume stamped just before a boundary can appear in
    the official minute after it. It only moves that way, never the other. Across midnight this also moves
    volume between official days, and the two days' differences cancel.

    That gives a rule with no arbitrary size. A day's difference must be covered by trades near its two
    midnights: positive by the end of this file, negative by the end of the previous one. Anything else is an
    error, because trades have been lost or invented. Without the previous day's file a negative difference
    cannot be judged yet, so it stays open instead of failing. Single bars may differ by this mechanism, and a
    boundary it cannot explain is a warning.

    previous_tail holds the previous file's trades, at least those in the window before this day. None means
    that file is not available.
    """
    window_us = int(tolerance.boundary_window_ms * 1000)
    ts_us = file_trades["ts"].dt.timestamp("us").to_numpy().astype(np.int64)
    qty = _scaled(_floats(file_trades, "qty"))
    buy_mask = file_trades["is_taker_buy"].to_numpy().astype(bool)
    buy_qty = np.where(buy_mask, qty, 0)
    official_sorted = official.sort("open_time")
    official_qty = _scaled(_floats(official_sorted, "volume"))
    official_buy = _scaled(_floats(official_sorted, "taker_buy_volume"))
    boundaries = official_sorted["open_time"].dt.timestamp("us").to_numpy().astype(np.int64) + 60_000_000
    day_end = int(boundaries[-1]) if boundaries.size else 0

    volume_diff = int(qty.sum()) - int(official_qty.sum())
    buy_diff = int(buy_qty.sum()) - int(official_buy.sum())
    up_allowed = _trailing(ts_us, qty, day_end, window_us)
    up_allowed_buy = _trailing(ts_us, buy_qty, day_end, window_us)
    down_allowed: int | None = None
    down_allowed_buy: int | None = None
    if previous_tail is not None and boundaries.size:
        day_start = day_end - 86_400_000_000
        tail_ts = previous_tail["ts"].dt.timestamp("us").to_numpy().astype(np.int64)
        tail_qty = _scaled(_floats(previous_tail, "qty"))
        tail_buy = np.where(previous_tail["is_taker_buy"].to_numpy().astype(bool), tail_qty, 0)
        down_allowed = _trailing(tail_ts, tail_qty, day_start, window_us)
        down_allowed_buy = _trailing(tail_ts, tail_buy, day_start, window_us)

    # The running difference at each minute: volume stamped before it, less volume officially counted by it.
    positions = np.searchsorted(ts_us, boundaries, side="left")
    cumulative = np.concatenate(([0], np.cumsum(qty)))
    running = cumulative[positions] - np.cumsum(official_qty)
    implied_carry = max(0, -int(running.min())) if running.size else 0
    adjusted = running + implied_carry
    window_start = np.searchsorted(ts_us, boundaries - window_us, side="left")
    explainable = cumulative[positions] - cumulative[window_start]
    unexplained = int((adjusted > explainable).sum())
    largest_window_us = 0
    for index in np.flatnonzero(adjusted > 0):
        cursor = int(positions[index]) - 1
        covered = 0
        while cursor >= 0 and covered < int(adjusted[index]):
            covered += int(qty[cursor])
            cursor -= 1
        largest_window_us = max(largest_window_us, int(boundaries[index]) - int(ts_us[cursor + 1]))

    joined = bars.select(
        "open_time",
        pl.col("open").alias("o"),
        pl.col("high").alias("h"),
        pl.col("low").alias("l"),
        pl.col("close").alias("c"),
        pl.col("volume").alias("v"),
    ).join(
        official_sorted.select(
            "open_time",
            pl.col("open").alias("oo"),
            pl.col("high").alias("oh"),
            pl.col("low").alias("ol"),
            pl.col("close").alias("oc"),
            pl.col("volume").alias("ov"),
        ),
        on="open_time",
        how="inner",
    )
    volume_gaps = np.abs(_floats(joined, "v") - _floats(joined, "ov"))
    # Prices are compared only where we have a traded price. A minute with no trades has null prices here.
    price_gaps = np.nanmax(
        np.vstack(
            [
                np.abs(_floats(joined, "o") - _floats(joined, "oo")),
                np.abs(_floats(joined, "h") - _floats(joined, "oh")),
                np.abs(_floats(joined, "l") - _floats(joined, "ol")),
                np.abs(_floats(joined, "c") - _floats(joined, "oc")),
                np.zeros(joined.height),
            ]
        ),
        axis=0,
    )
    max_volume = float(volume_gaps.max()) if joined.height else 0.0
    max_price = float(price_gaps.max()) if joined.height else 0.0
    over_0_001 = int((volume_gaps > 0.001 + 1e-9).sum())
    over_price = int((price_gaps > tolerance.bar_price_abs).sum())

    eps = round(tolerance.daily_total_abs * _QTY_SCALE)
    reasons: list[str] = []
    status = STATUS_PASS
    needs_previous = False
    for name, diff, up, down in (
        ("volume", volume_diff, up_allowed, down_allowed),
        ("taker buy volume", buy_diff, up_allowed_buy, down_allowed_buy),
    ):
        if diff > up + eps:
            status = STATUS_FAIL
            reasons.append(
                f"daily {name} is {diff / _QTY_SCALE:+.8f} above official, not explained by midnight"
            )
        elif diff < -eps:
            if down is None:
                needs_previous = True
            elif -diff > down + eps:
                status = STATUS_FAIL
                reasons.append(
                    f"daily {name} is {diff / _QTY_SCALE:+.8f} below official, not explained by midnight"
                )
    if implied_carry > eps:
        # A carry across midnight is in the official candles from the first minute. A deficit that first
        # appears later in the day is lost or invented volume, and no previous file could explain it.
        if adjusted.size and int(adjusted[0]) > int(explainable[0]) + eps:
            status = STATUS_FAIL
            needs_previous = False
            reasons.append(
                f"deficit of {implied_carry / _QTY_SCALE:.8f} appears later in the day, "
                "not explained by midnight"
            )
        elif down_allowed is None:
            needs_previous = True
        elif implied_carry > down_allowed + eps:
            status = STATUS_FAIL
            reasons.append(
                f"carry into the day of {implied_carry / _QTY_SCALE:.8f} is not explained by midnight"
            )
    if status != STATUS_FAIL and unexplained:
        status = STATUS_WARN
        reasons.append(f"{unexplained} minute boundaries differ by more than nearby trades explain")
    if status != STATUS_FAIL and over_price:
        status = STATUS_WARN
        reasons.append(f"{over_price} bars outside the price tolerance")
    return OfficialReconciliation(
        status=status,
        needs_previous_day=needs_previous,
        trades_volume=round(float(qty.sum()) / _QTY_SCALE, 6),
        official_volume=round(float(official_qty.sum()) / _QTY_SCALE, 6),
        volume_diff=round(volume_diff / _QTY_SCALE, 8),
        volume_explainable_up=round(up_allowed / _QTY_SCALE, 8),
        volume_explainable_down=None if down_allowed is None else round(down_allowed / _QTY_SCALE, 8),
        trades_taker_buy=round(float(buy_qty.sum()) / _QTY_SCALE, 6),
        official_taker_buy=round(float(official_buy.sum()) / _QTY_SCALE, 6),
        taker_buy_diff=round(buy_diff / _QTY_SCALE, 8),
        trades_fills=int(file_trades["n_fills"].sum()),
        official_count=int(official_sorted["trade_count"].sum()),
        bars_compared=joined.height,
        bars_volume_diff_over_0_001=over_0_001,
        max_bar_volume_diff=round(max_volume, 6),
        boundaries_unexplained=unexplained,
        implied_carry_in=round(implied_carry / _QTY_SCALE, 8),
        largest_window_needed_ms=round(largest_window_us / 1000.0, 3),
        bars_price_over_tolerance=over_price,
        max_bar_price_diff=round(max_price, 6),
        reasons=tuple(reasons),
    )


def compare_emitted_with_rebuild(emitted: pl.DataFrame, rebuilt: pl.DataFrame) -> dict[str, Any]:
    """Compare bars as first emitted by the poll with bars rebuilt later from all stored trades.

    Emitted bars are never rewritten, so a trade that reached the venue's history after its minute was
    emitted shows up here. Same venue and same code, so any difference is a real late arrival.
    """
    joined = emitted.select(
        "close_time",
        pl.col("volume").alias("v"),
        pl.col("close").alias("c"),
        pl.col("trade_count").alias("n"),
    ).join(
        rebuilt.select(
            "close_time",
            pl.col("volume").alias("rv"),
            pl.col("close").alias("rc"),
            pl.col("trade_count").alias("rn"),
        ),
        on="close_time",
        how="inner",
    )
    if joined.is_empty():
        return {
            "status": STATUS_WARN,
            "bars_compared": 0,
            "bars_different": 0,
            "reasons": ["no bars"],
        }
    different = joined.filter(
        (pl.col("n") != pl.col("rn"))
        | ((pl.col("v") - pl.col("rv")).abs() > 1e-9)
        | (pl.col("c").fill_null(-1.0) != pl.col("rc").fill_null(-1.0))
    )
    return {
        "status": STATUS_PASS if different.is_empty() else STATUS_WARN,
        "bars_compared": joined.height,
        "bars_different": different.height,
        "late_trades": int((different["rn"] - different["n"]).sum()) if different.height else 0,
        "reasons": [] if different.is_empty() else ["trades arrived after their minute was emitted"],
    }


def cross_venue_check(
    poll_bars: pl.DataFrame,
    archive_bars: pl.DataFrame,
    *,
    median_bps_warn: float,
    min_corr_warn: float,
) -> dict[str, Any]:
    """Sanity check between two different markets, such as Kraken spot and a Binance perpetual.

    They are not expected to agree bar for bar, and volume is not comparable at all. A large price basis or
    a loss of co-movement means one side is broken.
    """
    joined = (
        poll_bars.select("close_time", pl.col("close").alias("a"))
        .join(
            archive_bars.select("close_time", pl.col("close").alias("b")),
            on="close_time",
            how="inner",
        )
        .drop_nulls()
        .sort("close_time")
    )
    if joined.height < 30:
        return {"status": STATUS_WARN, "bars_compared": joined.height, "reasons": ["too few bars"]}
    a = joined["a"].to_numpy()
    b = joined["b"].to_numpy()
    basis = 1e4 * (a - b) / b
    median_abs = float(np.median(np.abs(basis)))
    return_a = np.diff(np.log(a))
    return_b = np.diff(np.log(b))
    corr = float(np.corrcoef(return_a, return_b)[0, 1])
    reasons: list[str] = []
    if median_abs > median_bps_warn:
        reasons.append(f"median absolute basis {median_abs:.1f} bps above {median_bps_warn:.1f}")
    if not corr >= min_corr_warn:
        reasons.append(f"return correlation {corr:.3f} below {min_corr_warn:.3f}")
    return {
        "status": STATUS_WARN if reasons else STATUS_PASS,
        "bars_compared": joined.height,
        "median_abs_close_diff_bps": round(median_abs, 3),
        "max_abs_close_diff_bps": round(float(np.max(np.abs(basis))), 3),
        "one_minute_return_corr": round(corr, 4),
        "reasons": reasons,
    }
