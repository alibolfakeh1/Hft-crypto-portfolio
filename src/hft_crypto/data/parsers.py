"""Turn delivered archive files into curated frames. Input is untrusted: parsed, never executed.

Each parser validates the header instead of assuming it, checks that timestamps belong to the partition,
and raises ValidationError on anything it does not recognise, which sends the file to quarantine. Older
Binance files carry no header row, so that case is recognised explicitly.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import re
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from hft_crypto.bars.core import UTC_TIME
from hft_crypto.timeutil import MICROS_PER_DAY, MICROS_PER_SECOND, day_start_us, next_month

_CHUNK = 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")

AGG_TRADES_HEADER = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"
KLINES_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
    "taker_buy_quote_volume,ignore"
)
BOOK_DEPTH_HEADER = "timestamp,percentage,depth,notional"
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"
BYBIT_TRADE_HEADERS = (
    "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional,RPI",
    "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional",
)
BYBIT_BASE_COLUMNS = BYBIT_TRADE_HEADERS[1].split(",")

TRADE_SCHEMA: dict[str, pl.DataType] = {
    "venue": pl.String(),
    "symbol": pl.String(),
    "ts": UTC_TIME,
    "price": pl.Float64(),
    "qty": pl.Float64(),
    "is_taker_buy": pl.Boolean(),
    "trade_id": pl.Int64(),
    "file_row": pl.Int64(),
    "n_fills": pl.Int32(),
    "is_rpi": pl.Boolean(),
    "knowable_time": UTC_TIME,
}


class ValidationError(Exception):
    """A delivered file failed validation. It goes to quarantine and is downloaded again later."""


@dataclass(frozen=True)
class CuratedResult:
    frame: pl.DataFrame
    checks: dict[str, Any]
    warnings: tuple[str, ...] = ()


def parse_checksum_sidecar(text: str, filename: str) -> str:
    """Read a `<sha256>  <filename>` sidecar. It must name the file it is said to describe."""
    parts = text.split()
    if len(parts) != 2 or _SHA256.match(parts[0]) is None:
        raise ValidationError("checksum sidecar has an unexpected format")
    if parts[1].lstrip("*") != filename:
        raise ValidationError("checksum sidecar names a different file")
    return parts[0].lower()


def _read_capped(stream: Any, limit: int, what: str) -> bytes:
    """Read a decompressing stream with a hard limit, so a decompression bomb stops early."""
    pieces: list[bytes] = []
    total = 0
    while chunk := stream.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise ValidationError(f"{what} expands beyond {limit} bytes")
        pieces.append(chunk)
    return b"".join(pieces)


def read_zip_member(path: Path, limit: int) -> bytes:
    """Read the only member of a zip into memory. Member names are ignored, so nothing is extracted."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) != 1:
                raise ValidationError(f"expected one zip member, found {len(members)}")
            if members[0].file_size > limit:
                raise ValidationError(f"zip member declares {members[0].file_size} bytes")
            with archive.open(members[0]) as stream:
                return _read_capped(stream, limit, "zip member")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, ValueError) as exc:
        raise ValidationError(f"unreadable zip: {exc}") from exc


def read_gzip(path: Path, limit: int) -> bytes:
    try:
        with gzip.open(path, "rb") as stream:
            return _read_capped(stream, limit, "gzip file")
    except (gzip.BadGzipFile, zlib.error, EOFError, OSError, ValueError) as exc:
        raise ValidationError(f"unreadable gzip: {exc}") from exc


def _split_header(raw: bytes, expected: str | tuple[str, ...], columns: int) -> tuple[bool, str]:
    """Return whether a header row is present and which one. Anything unknown is a validation failure."""
    first_line = raw.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
    options = (expected,) if isinstance(expected, str) else expected
    if first_line in options:
        return True, first_line
    fields = first_line.split(",")
    if len(fields) == columns and fields[0].replace(".", "", 1).isdigit():
        return False, options[0]
    raise ValidationError(f"unexpected header: {first_line[:120]!r}")


def _read_csv(raw: bytes, header_line: str, has_header: bool) -> pl.DataFrame:
    """Read every column as text. Each is then converted strictly, so bad values cannot slip through."""
    columns = header_line.split(",")
    try:
        return pl.read_csv(
            io.BytesIO(raw),
            has_header=has_header,
            new_columns=columns,
            schema_overrides=dict.fromkeys(columns, pl.String),
            infer_schema=False,
            truncate_ragged_lines=False,
        )
    except pl.exceptions.PolarsError as exc:
        raise ValidationError(f"unreadable CSV: {exc}") from exc


def _strict_cast(frame: pl.DataFrame, types: dict[str, pl.DataType]) -> pl.DataFrame:
    try:
        return frame.with_columns([pl.col(name).cast(kind, strict=True) for name, kind in types.items()])
    except pl.exceptions.PolarsError as exc:
        raise ValidationError(f"bad value in file: {exc}") from exc


def _require_finite(frame: pl.DataFrame, columns: list[str]) -> None:
    """`price <= 0` is false for NaN, so a NaN or an infinity would otherwise pass every check and reach a
    bar."""
    for name in columns:
        if not frame[name].is_finite().all():
            raise ValidationError(f"a value in column {name} is not a finite number")


def _require_no_nulls(frame: pl.DataFrame, columns: list[str]) -> None:
    for name in columns:
        count = frame[name].null_count()
        if count:
            raise ValidationError(f"{count} missing values in column {name}")


def _us_time(name: str) -> pl.Expr:
    return pl.col(name).cast(pl.Int64).cast(UTC_TIME)


def _time_checks(ts_us: np.ndarray[Any, Any], first_us: int, end_us: int) -> dict[str, Any]:
    """Range and order checks. A file holding other days' data means the format or the file is wrong."""
    if ts_us.size == 0:
        raise ValidationError("file holds no rows")
    low = int(ts_us.min())
    high = int(ts_us.max())
    if low < first_us - MICROS_PER_DAY or high > end_us + MICROS_PER_DAY:
        raise ValidationError("timestamps fall outside the partition, so the format may have changed")
    outside = int(((ts_us < first_us) | (ts_us >= end_us)).sum())
    sorted_ts = np.sort(ts_us)
    largest_gap = int(np.diff(sorted_ts).max()) if ts_us.size > 1 else 0
    return {
        "rows": int(ts_us.size),
        "first_ts_us": low,
        "last_ts_us": high,
        "rows_outside_partition": outside,
        "out_of_order": int((np.diff(ts_us) < 0).sum()),
        "largest_time_gap_s": round(largest_gap / MICROS_PER_SECOND, 3),
    }


def _knowable_after(column: str, allowance_us: int) -> pl.Expr:
    """A row is knowable its stamp plus the source's declared allowance, so no consumer has to remember
    that."""
    return (pl.col(column).dt.timestamp("us") + allowance_us).cast(UTC_TIME).alias("knowable_time")


def _time_warnings(checks: dict[str, Any]) -> list[str]:
    warnings = []
    if checks["rows_outside_partition"]:
        warnings.append(f"{checks['rows_outside_partition']} rows stamped outside the partition")
    if checks["out_of_order"]:
        warnings.append(f"{checks['out_of_order']} rows out of order")
    return warnings


def _finish_trades(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(list(TRADE_SCHEMA)).sort(["ts", "trade_id", "file_row"], maintain_order=True)


def parse_agg_trades(
    path: Path, symbol: str, day: dt.date, limit: int, *, venue: str, allowance_us: int
) -> CuratedResult:
    raw = read_zip_member(path, limit)
    has_header, line = _split_header(raw, AGG_TRADES_HEADER, 7)
    text = _read_csv(raw, line, has_header)
    if text.is_empty():
        raise ValidationError("file holds no rows")
    typed = _strict_cast(
        text.with_columns(pl.col("is_buyer_maker").str.to_lowercase().alias("maker_text")),
        {
            "agg_trade_id": pl.Int64(),
            "price": pl.Float64(),
            "quantity": pl.Float64(),
            "first_trade_id": pl.Int64(),
            "last_trade_id": pl.Int64(),
            "transact_time": pl.Int64(),
        },
    )
    _require_no_nulls(
        typed,
        [
            "agg_trade_id",
            "price",
            "quantity",
            "first_trade_id",
            "last_trade_id",
            "transact_time",
            "maker_text",
        ],
    )
    _require_finite(typed, ["price", "quantity"])
    if not typed["maker_text"].is_in(["true", "false"]).all():
        raise ValidationError("is_buyer_maker holds a value other than true or false")
    if (typed["price"] <= 0).any() or (typed["quantity"] <= 0).any():
        raise ValidationError("non-positive price or quantity")
    if (typed["last_trade_id"] < typed["first_trade_id"]).any():
        raise ValidationError("last_trade_id is below first_trade_id")

    ts_us = typed["transact_time"].to_numpy() * 1000
    first_us = day_start_us(day)
    checks = _time_checks(ts_us, first_us, first_us + MICROS_PER_DAY)
    ids = typed["agg_trade_id"].to_numpy()
    checks["id_breaks"] = int((np.diff(ids) != 1).sum())
    checks["duplicate_ids"] = int(ids.size - np.unique(ids).size)
    frame = typed.with_columns(
        pl.lit(venue).alias("venue"),
        pl.lit(symbol).alias("symbol"),
        (pl.col("transact_time") * 1000).cast(pl.Int64).cast(UTC_TIME).alias("ts"),
        pl.col("quantity").alias("qty"),
        (pl.col("maker_text") == "false").alias("is_taker_buy"),
        pl.col("agg_trade_id").alias("trade_id"),
        pl.Series("file_row", np.arange(typed.height, dtype=np.int64)),
        (pl.col("last_trade_id") - pl.col("first_trade_id") + 1).cast(pl.Int32).alias("n_fills"),
        pl.lit(False).alias("is_rpi"),
    ).with_columns(_knowable_after("ts", allowance_us))
    warnings = _time_warnings(checks)
    if checks["id_breaks"]:
        warnings.append(f"{checks['id_breaks']} breaks in aggregate trade ids")
    if checks["duplicate_ids"]:
        raise ValidationError(f"{checks['duplicate_ids']} duplicate aggregate trade ids")
    return CuratedResult(_finish_trades(frame), checks, tuple(warnings))


def parse_bybit_trades(
    path: Path, symbol: str, day: dt.date, limit: int, *, venue: str, allowance_us: int
) -> CuratedResult:
    raw = read_gzip(path, limit)
    has_header, line = _split_header(raw, BYBIT_TRADE_HEADERS, 11)
    if not has_header:
        raise ValidationError("Bybit trade file without a header row")
    text = _read_csv(raw, line, True)
    if text.is_empty():
        raise ValidationError("file holds no rows")
    typed = _strict_cast(text, {"size": pl.Float64(), "price": pl.Float64()})
    _require_no_nulls(typed, ["timestamp", "symbol", "side", "size", "price", "trdMatchID"])
    _require_finite(typed, ["size", "price"])
    if not (typed["symbol"] == symbol).all():
        raise ValidationError("file holds another symbol")
    if not typed["side"].is_in(["Buy", "Sell"]).all():
        raise ValidationError("side holds a value other than Buy or Sell")
    if (typed["price"] <= 0).any() or (typed["size"] <= 0).any():
        raise ValidationError("non-positive price or size")

    # Seconds with a fraction, converted on the digits so no float can move a trade across a boundary.
    parts = typed["timestamp"].str.split_exact(".", 1).struct.rename_fields(["whole", "fraction"])
    digits = parts.struct.field("fraction").fill_null("").str.pad_end(6, "0").str.slice(0, 6)
    try:
        ts_series = (
            parts.struct.field("whole").cast(pl.Int64, strict=True) * MICROS_PER_SECOND
            + digits.cast(pl.Int64, strict=True)
        ).rename("ts_us")
    except pl.exceptions.PolarsError as exc:
        raise ValidationError(f"bad timestamp in file: {exc}") from exc
    ts_us = ts_series.to_numpy()
    first_us = day_start_us(day)
    checks = _time_checks(ts_us, first_us, first_us + MICROS_PER_DAY)
    checks["duplicate_ids"] = int(text.height - typed["trdMatchID"].n_unique())
    if checks["duplicate_ids"]:
        raise ValidationError(f"{checks['duplicate_ids']} duplicate trade match ids")
    rpi = typed["RPI"].cast(pl.Int8, strict=False) == 1 if "RPI" in typed.columns else None
    frame = typed.with_columns(
        pl.lit(venue).alias("venue"),
        pl.lit(symbol).alias("symbol"),
        ts_series.cast(UTC_TIME).alias("ts"),
        pl.col("size").alias("qty"),
        (pl.col("side") == "Buy").alias("is_taker_buy"),
        # These rows carry only a random match id, so no id can show that a row is missing between them. The
        # row number is kept for ordering, under its own name, so it can never pass as a continuity proof.
        pl.lit(None, dtype=pl.Int64).alias("trade_id"),
        pl.Series("file_row", np.arange(typed.height, dtype=np.int64)),
        pl.lit(1, dtype=pl.Int32).alias("n_fills"),
        (rpi.fill_null(False).alias("is_rpi") if rpi is not None else pl.lit(False).alias("is_rpi")),
    ).with_columns(_knowable_after("ts", allowance_us))
    return CuratedResult(_finish_trades(frame), checks, tuple(_time_warnings(checks)))


def parse_klines(
    path: Path, symbol: str, day: dt.date, limit: int, *, venue: str, allowance_us: int
) -> CuratedResult:
    raw = read_zip_member(path, limit)
    has_header, line = _split_header(raw, KLINES_HEADER, 12)
    text = _read_csv(raw, line, has_header)
    if text.is_empty():
        raise ValidationError("file holds no rows")
    typed = _strict_cast(
        text,
        {
            "open_time": pl.Int64(),
            "open": pl.Float64(),
            "high": pl.Float64(),
            "low": pl.Float64(),
            "close": pl.Float64(),
            "volume": pl.Float64(),
            "close_time": pl.Int64(),
            "quote_volume": pl.Float64(),
            "count": pl.Int64(),
            "taker_buy_volume": pl.Float64(),
            "taker_buy_quote_volume": pl.Float64(),
        },
    )
    _require_no_nulls(
        typed,
        ["open_time", "open", "high", "low", "close", "volume", "close_time", "count", "taker_buy_volume"],
    )
    _require_finite(typed, ["open", "high", "low", "close", "volume", "taker_buy_volume"])
    open_us = typed["open_time"].to_numpy() * 1000
    first_us = day_start_us(day)
    checks = _time_checks(open_us, first_us, first_us + MICROS_PER_DAY)
    if checks["rows_outside_partition"]:
        raise ValidationError("candles outside their UTC day")
    if (open_us % 60_000_000 != 0).any():
        raise ValidationError("candle open times are not on a minute boundary")
    if (typed["high"] < typed["low"]).any():
        raise ValidationError("candle high is below its low")
    checks["expected_rows"] = 1440
    frame = (
        typed.with_columns(
            pl.lit(venue).alias("venue"),
            pl.lit(symbol).alias("symbol"),
            (pl.col("open_time") * 1000).cast(pl.Int64).cast(UTC_TIME).alias("open_time"),
            # Official candles run [open, open + 59.999 s]. They are knowable once that minute is over, plus
            # the source's allowance.
            ((pl.col("open_time") + 60_000) * 1000 + allowance_us)
            .cast(pl.Int64)
            .cast(UTC_TIME)
            .alias("knowable_time"),
            pl.col("count").alias("trade_count"),
        )
        .select(
            "venue",
            "symbol",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trade_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "knowable_time",
        )
        .sort("open_time")
    )
    warnings = []
    if frame.height != 1440:
        warnings.append(f"{frame.height} candles instead of 1440")
    return CuratedResult(frame, checks, tuple(warnings))


def parse_book_depth(
    path: Path, symbol: str, day: dt.date, limit: int, allowance_s: float, *, venue: str
) -> CuratedResult:
    raw = read_zip_member(path, limit)
    has_header, line = _split_header(raw, BOOK_DEPTH_HEADER, 4)
    if not has_header:
        raise ValidationError("bookDepth file without a header row")
    text = _read_csv(raw, line, True)
    if text.is_empty():
        raise ValidationError("file holds no rows")
    typed = _strict_cast(text, {"percentage": pl.Float64(), "depth": pl.Float64(), "notional": pl.Float64()})
    try:
        stamped = typed.with_columns(
            pl.col("timestamp")
            .str.to_datetime("%Y-%m-%d %H:%M:%S", time_unit="us", time_zone="UTC", strict=True)
            .alias("ts")
        )
    except pl.exceptions.PolarsError as exc:
        raise ValidationError(f"bad timestamp in file: {exc}") from exc
    _require_no_nulls(stamped, ["ts", "percentage", "depth", "notional"])
    _require_finite(stamped, ["percentage", "depth", "notional"])
    if (stamped["depth"] < 0).any() or (stamped["notional"] < 0).any():
        raise ValidationError("negative depth or notional")
    ts_us = stamped["ts"].dt.timestamp("us").to_numpy()
    first_us = day_start_us(day)
    checks = _time_checks(ts_us, first_us, first_us + MICROS_PER_DAY)
    checks["snapshots"] = stamped["ts"].n_unique()
    checks["percentage_levels"] = sorted(stamped["percentage"].unique().to_list())
    allowance_us = int(allowance_s * MICROS_PER_SECOND)
    frame = (
        stamped.with_columns(
            pl.lit(venue).alias("venue"),
            pl.lit(symbol).alias("symbol"),
            (pl.col("ts").dt.timestamp("us") + allowance_us).cast(UTC_TIME).alias("knowable_time"),
        )
        .select("venue", "symbol", "ts", "percentage", "depth", "notional", "knowable_time")
        .sort(["ts", "percentage"])
    )
    return CuratedResult(frame, checks)


def parse_funding(
    path: Path, symbol: str, month_start: dt.date, limit: int, *, venue: str, allowance_us: int
) -> CuratedResult:
    raw = read_zip_member(path, limit)
    has_header, line = _split_header(raw, FUNDING_HEADER, 3)
    if not has_header:
        raise ValidationError("funding file without a header row")
    text = _read_csv(raw, line, True)
    if text.is_empty():
        raise ValidationError("file holds no rows")
    typed = _strict_cast(
        text,
        {
            "calc_time": pl.Int64(),
            "funding_interval_hours": pl.Int32(),
            "last_funding_rate": pl.Float64(),
        },
    )
    _require_no_nulls(typed, ["calc_time", "funding_interval_hours", "last_funding_rate"])
    _require_finite(typed, ["last_funding_rate"])
    ts_us = typed["calc_time"].to_numpy() * 1000
    first_us = day_start_us(month_start)
    end_us = day_start_us(next_month(month_start))
    checks = _time_checks(ts_us, first_us, end_us)
    if (typed["funding_interval_hours"] <= 0).any():
        raise ValidationError("funding interval is not positive")
    frame = (
        typed.with_columns(
            pl.lit(venue).alias("venue"),
            pl.lit(symbol).alias("symbol"),
            (pl.col("calc_time") * 1000).cast(pl.Int64).cast(UTC_TIME).alias("settle_time"),
            pl.col("last_funding_rate").alias("funding_rate"),
        )
        .with_columns(_knowable_after("settle_time", allowance_us))
        .select(
            "venue",
            "symbol",
            "settle_time",
            "funding_interval_hours",
            "funding_rate",
            "knowable_time",
        )
        .sort("settle_time")
    )
    return CuratedResult(frame, checks)
