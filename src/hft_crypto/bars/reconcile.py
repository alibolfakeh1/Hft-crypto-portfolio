"""Checks on bars: against official candles, against a rebuild, against an archive, and between venues.

A failed check never removes a bar. It says from which minute a day's bars can no longer be trusted, working
forward through the day, so a minute's standing never depends on what happened later. Removing the whole day
would let an event at 23:59 decide which bars exist at 08:00, and that would select the sample by something in
its own future.

The rule for official candles was designed after seeing files from a source now ruled out by D-17. Under D-18
it must be checked again on the approved source, and its window is a declared placeholder until then.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.config import ReconTolerance

STATUS_PASS = "pass"  # noqa: S105
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_NOT_APPLICABLE = "not_applicable"
# Quantities are compared as whole units of this fraction of a coin.
_QTY_SCALE = 100_000_000
_MINUTE_US = 60_000_000
_DAY_US = 86_400_000_000

_Floats = npt.NDArray[np.float64]
_Ints = npt.NDArray[np.int64]


@dataclass(frozen=True)
class DayFlow:
    """What one day's files say crossed its two midnights. A pure function of that day's files."""

    carry_in: float
    carry_out: float
    carry_in_buy: float
    carry_out_buy: float
    # False when the day's own path broke. Its figure for the far midnight is then not what crossed it.
    reliable: bool = True

    @classmethod
    def from_detail(cls, detail: dict[str, Any]) -> DayFlow:
        return cls(
            float(detail["carry_in"]),
            float(detail["carry_out"]),
            float(detail["carry_in_buy"]),
            float(detail["carry_out_buy"]),
            bool(detail["flow_reliable"]),
        )


@dataclass(frozen=True)
class OfficialReconciliation:
    """Our trades and bars against official candles for one UTC day."""

    status: str
    needs_previous_day: bool
    needs_next_day: bool
    flag_from_close_us: int | None
    flag_first_bar: bool
    flag_last_bar: bool
    carry_in: float
    carry_out: float
    carry_in_buy: float
    carry_out_buy: float
    flow_reliable: bool
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
    fill_count_diff_rel: float
    bars_compared: int
    bars_volume_diff_over_0_001: int
    max_bar_volume_diff: float
    boundaries_unexplained: int
    boundaries_unexplained_buy: int
    largest_window_needed_ms: float
    bars_price_over_tolerance: int
    max_bar_price_diff: float
    max_bar_price_diff_rel: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floats(frame: pl.DataFrame, name: str) -> _Floats:
    result: _Floats = frame[name].fill_null(np.nan).to_numpy().astype(np.float64)
    return result


def _scaled(values: _Floats) -> _Ints:
    """Quantities as integers, so sums over millions of trades carry no floating point noise."""
    result: _Ints = np.rint(values * _QTY_SCALE).astype(np.int64)
    return result


def _trailing(ts_us: _Ints, qty: _Ints, end_us: int, window_us: int) -> int:
    """Quantity stamped in the window just before an instant."""
    return int(qty[(ts_us >= end_us - window_us) & (ts_us < end_us)].sum())


@dataclass(frozen=True)
class _Path:
    carry_in: int
    carry_out: int
    bad: npt.NDArray[np.bool_]
    first_bad: int | None
    largest_window_us: int


def _walk(
    ts_us: _Ints,
    qty: _Ints,
    official: _Ints,
    boundaries: _Ints,
    window_us: int,
    eps: int,
    previous_carry_out: int | None,
) -> _Path:
    """Walk a day minute by minute. Each boundary's standing uses only what came at or before it.

    Volume can only be stamped before a boundary and counted after it, by a little. So at each boundary the
    difference between trades so far and candles so far must lie between zero and what was stamped in the
    window just before. Anything else cannot be that mechanism. A carry from the previous day shows at the
    first boundary.
    """
    positions = np.searchsorted(ts_us, boundaries, side="left")
    cumulative = np.concatenate(([0], np.cumsum(qty)))
    running = cumulative[positions] - np.cumsum(official)
    window_start = np.searchsorted(ts_us, boundaries - window_us, side="left")
    explainable = cumulative[positions] - cumulative[window_start]
    carry = max(0, -int(running[0]))
    # A straddle at the first boundary can hide part of a carry from that one reading. The previous day's own
    # figure settles it, when it is known and the difference is what that window can explain.
    if previous_carry_out is not None and 0 <= previous_carry_out - carry <= int(explainable[0]) + eps:
        carry = previous_carry_out
    adjusted = running + carry
    bad = (adjusted < -eps) | (adjusted > explainable + eps)
    hits = np.flatnonzero(bad)
    largest = 0
    for index in np.flatnonzero((adjusted > 0) & ~bad):
        cursor = int(positions[index]) - 1
        covered = 0
        while cursor >= 0 and covered < int(adjusted[index]):
            covered += int(qty[cursor])
            cursor -= 1
        largest = max(largest, int(boundaries[index]) - int(ts_us[cursor + 1]))
    return _Path(carry, int(adjusted[-1]), bad, int(hits[0]) if hits.size else None, largest)


def reconcile_official(
    file_trades: pl.DataFrame,
    bars: pl.DataFrame,
    official: pl.DataFrame,
    tolerance: ReconTolerance,
    *,
    previous_tail: pl.DataFrame | None,
    previous_flow: DayFlow | None,
    next_flow: DayFlow | None,
    is_first_day: bool,
) -> OfficialReconciliation:
    """Compare one day with its official candles, and with what its two neighbours say crossed midnight.

    An aggregate trade file gives each aggregate one timestamp, while its fills can run on for a moment, and
    official candles count each fill in its own minute. So volume stamped just before a boundary can appear in
    the official minute after it. It only moves that way, never the other. Across midnight this moves volume
    between official days, and what one day sends out, the next must take in.

    So a day's trades and its candles must agree at every minute, within what that mechanism can explain, for
    all volume and for taker buy volume separately. Fill counts and prices are compared too. The day is not
    final until both neighbours are known, because a difference near midnight can be excused only by a
    neighbour that agrees.

    previous_tail holds the end of the previous file. previous_flow and next_flow are what those days
    reported, or None if they are not known yet. is_first_day says that no previous file will ever exist.
    """
    window_us = round(tolerance.boundary_window_ms * 1000)
    eps = round(tolerance.daily_total_abs * _QTY_SCALE)
    order = np.argsort(file_trades["ts"].dt.timestamp("us").to_numpy().astype(np.int64), kind="stable")
    ts_us = file_trades["ts"].dt.timestamp("us").to_numpy().astype(np.int64)[order]
    qty = _scaled(_floats(file_trades, "qty"))[order]
    buy_mask = file_trades["is_taker_buy"].to_numpy().astype(bool)[order]
    buy_qty = np.where(buy_mask, qty, 0)
    official_sorted = official.sort("open_time")
    official_qty = _scaled(_floats(official_sorted, "volume"))
    official_buy = _scaled(_floats(official_sorted, "taker_buy_volume"))
    boundaries = official_sorted["open_time"].dt.timestamp("us").to_numpy().astype(np.int64) + _MINUTE_US
    day_end = int(boundaries[-1])
    day_start = day_end - _DAY_US

    trusted_previous = previous_flow is not None and previous_flow.reliable
    previous_in = round(previous_flow.carry_out * _QTY_SCALE) if previous_flow and trusted_previous else None
    previous_in_buy = (
        round(previous_flow.carry_out_buy * _QTY_SCALE) if previous_flow and trusted_previous else None
    )
    volume_path = _walk(ts_us, qty, official_qty, boundaries, window_us, eps, previous_in)
    buy_path = _walk(ts_us, buy_qty, official_buy, boundaries, window_us, eps, previous_in_buy)

    volume_diff = int(qty.sum()) - int(official_qty.sum())
    buy_diff = int(buy_qty.sum()) - int(official_buy.sum())
    up_allowed = _trailing(ts_us, qty, day_end, window_us)
    down_allowed: int | None = None
    if previous_tail is not None:
        tail_ts = previous_tail["ts"].dt.timestamp("us").to_numpy().astype(np.int64)
        tail_qty = _scaled(_floats(previous_tail, "qty"))
        down_allowed = _trailing(tail_ts, tail_qty, day_start, window_us)

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
    # Relative, because an absolute tolerance would mean something different at every price level.
    reference = np.abs(_floats(joined, "oc"))
    price_rel = np.divide(price_gaps, reference, out=np.zeros_like(price_gaps), where=reference > 0)
    over_price = price_rel > tolerance.bar_price_rel
    trades_fills = int(file_trades["n_fills"].sum())
    official_count = int(official_sorted["trade_count"].sum())
    fill_rel = abs(trades_fills - official_count) / max(official_count, 1)

    reasons: list[str] = []
    failed = False
    first_bad: list[int] = []
    flag_first = False
    flag_last = False
    cannot_confirm = False
    needs_previous = False
    needs_next = False

    if volume_path.first_bad is not None:
        failed = True
        first_bad.append(int(boundaries[volume_path.first_bad]))
        reasons.append(
            f"{int(volume_path.bad.sum())} minute boundaries differ by more than nearby trades explain"
        )
    if buy_path.first_bad is not None:
        failed = True
        first_bad.append(int(boundaries[buy_path.first_bad]))
        reasons.append(f"taker buy volume differs at {int(buy_path.bad.sum())} minute boundaries")
    if volume_diff > up_allowed + eps + volume_path.carry_in:
        failed = True
        reasons.append(
            f"daily volume is {volume_diff / _QTY_SCALE:+.8f} above official, not explained by midnight"
        )
    if volume_path.carry_in > eps and down_allowed is not None and volume_path.carry_in > down_allowed + eps:
        failed = True
        flag_first = True
        reasons.append(
            f"carry into the day of {volume_path.carry_in / _QTY_SCALE:.8f} is not explained by midnight"
        )
    if over_price.any():
        failed = True
        first_price = int(np.flatnonzero(over_price)[0])
        first_bad.append(int(joined["open_time"].dt.timestamp("us")[first_price]) + _MINUTE_US)
        reasons.append(f"{int(over_price.sum())} bars outside the price tolerance")

    # What the neighbours say must match. Neither day alone can tell which one is wrong, so both are flagged
    # at the boundary they share, and only there: the rest of each day stands on its own path.
    own_path_holds = volume_path.first_bad is None and buy_path.first_bad is None
    has_carry_in = volume_path.carry_in > eps or buy_path.carry_in > eps
    has_carry_out = volume_path.carry_out > eps or buy_path.carry_out > eps
    if previous_flow is not None and previous_flow.reliable:
        if (
            abs(volume_path.carry_in - round(previous_flow.carry_out * _QTY_SCALE)) > eps
            or abs(buy_path.carry_in - round(previous_flow.carry_out_buy * _QTY_SCALE)) > eps
        ):
            failed = True
            flag_first = True
            reasons.append(
                f"carry into the day is {volume_path.carry_in / _QTY_SCALE:.8f}, but the previous day sent "
                f"{previous_flow.carry_out:.8f}, not explained by midnight"
            )
    elif previous_flow is not None or is_first_day:
        # Nobody can confirm this midnight: there is no earlier file, or that day's own figures broke. Nothing
        # here contradicts it, so it cannot fail, and a carry nobody vouches for must not pass, so it warns.
        if has_carry_in:
            cannot_confirm = True
            flag_first = True
            reasons.append(
                f"carry into the day of {volume_path.carry_in / _QTY_SCALE:.8f} cannot be confirmed, "
                "not explained by midnight"
            )
    else:
        needs_previous = True
    if next_flow is not None and next_flow.reliable:
        if own_path_holds and (
            abs(volume_path.carry_out - round(next_flow.carry_in * _QTY_SCALE)) > eps
            or abs(buy_path.carry_out - round(next_flow.carry_in_buy * _QTY_SCALE)) > eps
        ):
            failed = True
            flag_last = True
            reasons.append(
                f"carry out of the day is {volume_path.carry_out / _QTY_SCALE:.8f}, but the next day took "
                f"{next_flow.carry_in:.8f}, not explained by midnight"
            )
    elif next_flow is not None:
        if own_path_holds and has_carry_out:
            cannot_confirm = True
            flag_last = True
            reasons.append(
                f"carry out of the day of {volume_path.carry_out / _QTY_SCALE:.8f} cannot be confirmed, "
                "not explained by midnight"
            )
    else:
        needs_next = True

    status = STATUS_FAIL if failed else STATUS_WARN if cannot_confirm else STATUS_PASS
    if not failed and fill_rel > tolerance.fill_count_rel:
        status = STATUS_WARN
        reasons.append(f"fill count differs by {fill_rel:.4%}")

    return OfficialReconciliation(
        status=status,
        needs_previous_day=needs_previous,
        needs_next_day=needs_next,
        flag_from_close_us=min(first_bad) if first_bad else None,
        flag_first_bar=flag_first,
        flag_last_bar=flag_last,
        carry_in=round(volume_path.carry_in / _QTY_SCALE, 8),
        carry_out=round(volume_path.carry_out / _QTY_SCALE, 8),
        carry_in_buy=round(buy_path.carry_in / _QTY_SCALE, 8),
        carry_out_buy=round(buy_path.carry_out / _QTY_SCALE, 8),
        flow_reliable=own_path_holds,
        trades_volume=round(float(qty.sum()) / _QTY_SCALE, 6),
        official_volume=round(float(official_qty.sum()) / _QTY_SCALE, 6),
        volume_diff=round(volume_diff / _QTY_SCALE, 8),
        volume_explainable_up=round(up_allowed / _QTY_SCALE, 8),
        volume_explainable_down=None if down_allowed is None else round(down_allowed / _QTY_SCALE, 8),
        trades_taker_buy=round(float(buy_qty.sum()) / _QTY_SCALE, 6),
        official_taker_buy=round(float(official_buy.sum()) / _QTY_SCALE, 6),
        taker_buy_diff=round(buy_diff / _QTY_SCALE, 8),
        trades_fills=trades_fills,
        official_count=official_count,
        fill_count_diff_rel=round(fill_rel, 6),
        bars_compared=joined.height,
        bars_volume_diff_over_0_001=int((volume_gaps > 0.001 + 1e-9).sum()),
        max_bar_volume_diff=round(float(volume_gaps.max()) if joined.height else 0.0, 6),
        boundaries_unexplained=int(volume_path.bad.sum()),
        boundaries_unexplained_buy=int(buy_path.bad.sum()),
        largest_window_needed_ms=round(
            max(volume_path.largest_window_us, buy_path.largest_window_us) / 1000.0, 3
        ),
        bars_price_over_tolerance=int(over_price.sum()),
        max_bar_price_diff=round(float(price_gaps.max()) if joined.height else 0.0, 6),
        max_bar_price_diff_rel=round(float(price_rel.max()) if joined.height else 0.0, 6),
        reasons=tuple(reasons),
    )


def compare_emitted_with_rebuild(emitted: pl.DataFrame, rebuilt: pl.DataFrame) -> dict[str, Any]:
    """Compare bars as first emitted by the poll with bars rebuilt later from all stored trades.

    Emitted bars are never rewritten, so a trade that reached the venue's history after its minute was emitted
    shows up here. Same venue and same code, so this finds late arrivals and nothing else: it cannot see a
    trade the poll never received. After a rebuild of the bars themselves it has nothing to say, and reports
    that.
    """
    if "emission" in emitted.columns and (emitted["emission"] == "rebuild").any():
        return {
            "status": STATUS_NOT_APPLICABLE,
            "bars_compared": 0,
            "bars_different": 0,
            "reasons": ["these bars were rebuilt after a lost cache, so they are not what the runs saw"],
        }
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


def compare_live_with_archive(live: pl.DataFrame, archive: pl.DataFrame) -> dict[str, Any]:
    """Each day's bars as the live path saw them, against the same venue's archive for that day.

    This is the reconciliation of docs/08_DATA_CENTER.md section 2. A backtest reads the archive and a live
    run read the poll, so any difference here is something one of them saw and the other did not.
    """
    if live.is_empty() or archive.is_empty():
        return {"status": STATUS_WARN, "bars_compared": 0, "bars_different": 0, "reasons": ["no bars"]}
    if set(live["venue"].unique().to_list()) != set(archive["venue"].unique().to_list()):
        raise ValueError("live bars can be reconciled only against the same venue's archive")
    joined = live.select(
        "close_time",
        pl.col("trade_count").alias("n"),
        pl.col("volume").alias("v"),
        pl.col("high").alias("h"),
        pl.col("low").alias("l"),
        pl.col("close").alias("c"),
    ).join(
        archive.select(
            "close_time",
            pl.col("trade_count").alias("an"),
            pl.col("volume").alias("av"),
            pl.col("high").alias("ah"),
            pl.col("low").alias("al"),
            pl.col("close").alias("ac"),
        ),
        on="close_time",
        how="full",
        coalesce=True,
    )
    fields = [("n", "an"), ("v", "av"), ("h", "ah"), ("l", "al"), ("c", "ac")]
    different = joined.filter(
        pl.any_horizontal(
            [
                (
                    pl.col(a).fill_null(-1.0).cast(pl.Float64) - pl.col(b).fill_null(-1.0).cast(pl.Float64)
                ).abs()
                > 1e-9
                for a, b in fields
            ]
        )
    )
    return {
        "status": STATUS_PASS if different.is_empty() else STATUS_WARN,
        "bars_compared": joined.height,
        "bars_different": different.height,
        "reasons": [] if different.is_empty() else ["live bars and archive bars differ"],
    }


def cross_venue_check(
    poll_bars: pl.DataFrame,
    archive_bars: pl.DataFrame,
    *,
    median_bps_warn: float,
    min_corr_warn: float,
) -> dict[str, Any]:
    """Sanity check between two different markets. It is not a reconciliation, and it cannot pass as one.

    They are not expected to agree bar for bar, and volume is not comparable at all. A large price basis or a
    loss of co-movement means one side is broken. Two bars of one venue must use compare_live_with_archive,
    which looks at every field, so this refuses them.
    """
    if "venue" in poll_bars.columns and "venue" in archive_bars.columns:
        same = set(poll_bars["venue"].unique().to_list()) & set(archive_bars["venue"].unique().to_list())
        if same:
            raise ValueError(f"same venue {sorted(same)}: use compare_live_with_archive")
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
