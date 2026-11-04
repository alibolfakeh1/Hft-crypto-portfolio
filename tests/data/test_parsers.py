"""Parsers treat every file as untrusted. Fixtures are generated here, with values worked out by hand."""

from __future__ import annotations

import datetime as dt
import gzip
import io
import zipfile
from pathlib import Path

import pytest

from helpers import agg_trades_csv, gz_bytes, klines_csv, us, zip_bytes
from hft_crypto.data.parsers import (
    ValidationError,
    parse_agg_trades,
    parse_book_depth,
    parse_bybit_trades,
    parse_checksum_sidecar,
    parse_funding,
    parse_klines,
    read_gzip,
    read_zip_member,
)

DAY = dt.date(2026, 3, 1)
DAY_MS = us("2026-03-01T00:00:00") // 1000
LIMIT = 100_000_000
BYBIT_HEAD = (
    "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional,RPI\n"
)


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def agg_zip(tmp_path: Path, text: str) -> Path:
    return write(tmp_path, "a.zip", zip_bytes("a.csv", text))


def test_agg_trades_values_and_side(tmp_path: Path) -> None:
    text = agg_trades_csv([(DAY_MS + 5, 100.5, 2.0, True), (DAY_MS + 9, 101.5, 3.0, False)])
    result = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)
    frame = result.frame
    assert frame["venue"].to_list() == ["binance", "binance"]
    # is_buyer_maker false means the taker bought.
    assert frame["is_taker_buy"].to_list() == [True, False]
    assert frame["price"].to_list() == [100.5, 101.5]
    assert frame["qty"].to_list() == [2.0, 3.0]
    assert frame["ts"].dt.timestamp("us").to_list() == [(DAY_MS + 5) * 1000, (DAY_MS + 9) * 1000]
    assert result.checks["rows"] == 2
    assert result.checks["id_breaks"] == 0
    assert result.checks["out_of_order"] == 0


def test_fill_count_comes_from_the_id_range(tmp_path: Path) -> None:
    text = (
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        f"7,100,1,10,12,{DAY_MS},true\n"
    )
    result = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)
    assert result.frame["n_fills"].to_list() == [3]


def test_older_files_without_a_header_are_read(tmp_path: Path) -> None:
    text = f"7,100.5,1.5,10,10,{DAY_MS + 1},false\n8,100.6,2.5,11,11,{DAY_MS + 2},true\n"
    result = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)
    assert result.frame.height == 2
    assert result.frame["qty"].to_list() == [1.5, 2.5]


def test_is_buyer_maker_accepts_either_case(tmp_path: Path) -> None:
    text = f"1,100,1,1,1,{DAY_MS},True\n2,100,1,2,2,{DAY_MS},False\n"
    frame = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT).frame
    assert frame["is_taker_buy"].to_list() == [False, True]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (f"1,100,1,1,1,{DAY_MS},maybe\n", "true or false"),
        (f"1,-5,1,1,1,{DAY_MS},true\n", "non-positive"),
        (f"1,100,0,1,1,{DAY_MS},true\n", "non-positive"),
        (f"1,100,1,5,1,{DAY_MS},true\n", "below first_trade_id"),
        (f"1,100,1,1,1,{DAY_MS},true\n1,100,1,1,1,{DAY_MS},true\n", "duplicate"),
        (f"1,abc,1,1,1,{DAY_MS},true\n", "bad value"),
    ],
)
def test_bad_agg_trades_are_refused(tmp_path: Path, rows: str, message: str) -> None:
    head = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
    with pytest.raises(ValidationError, match=message):
        parse_agg_trades(agg_zip(tmp_path, head + rows), "BTCUSDT", DAY, LIMIT)


def test_timestamps_in_another_unit_are_treated_as_a_format_change(tmp_path: Path) -> None:
    """Microseconds instead of milliseconds would land thousands of years away."""
    head = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
    text = head + f"1,100,1,1,1,{DAY_MS * 1000},true\n"
    with pytest.raises(ValidationError, match="outside the partition"):
        parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)


def test_id_breaks_warn_without_refusing_the_file(tmp_path: Path) -> None:
    head = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
    text = head + f"1,100,1,1,1,{DAY_MS},true\n5,100,1,5,5,{DAY_MS + 1},true\n"
    result = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)
    assert result.checks["id_breaks"] == 1
    assert result.warnings


def test_out_of_order_rows_are_counted_and_sorted(tmp_path: Path) -> None:
    text = agg_trades_csv([(DAY_MS + 9, 100.0, 1.0, True), (DAY_MS + 5, 101.0, 1.0, True)])
    result = parse_agg_trades(agg_zip(tmp_path, text), "BTCUSDT", DAY, LIMIT)
    assert result.checks["out_of_order"] == 1
    assert result.frame["price"].to_list() == [101.0, 100.0]


def test_bybit_timestamp_digits_are_kept_exactly(tmp_path: Path) -> None:
    """1772323200.0001 as a float would not survive. Near a boundary, that could move a trade between bars."""
    seconds = us("2026-03-01T00:00:00") // 1_000_000
    text = BYBIT_HEAD + (
        f"{seconds}.0001,BTCUSDT,Buy,0.5,100.5,ZeroPlusTick,id-1,1,0.5,50,0\n"
        f"{seconds + 60}.0000,BTCUSDT,Sell,1.5,100.6,ZeroMinusTick,id-2,1,1.5,150,1\n"
        f"{seconds + 61},BTCUSDT,Sell,1.0,100.7,ZeroMinusTick,id-3,1,1.0,100,0\n"
    )
    result = parse_bybit_trades(write(tmp_path, "b.csv.gz", gz_bytes(text)), "BTCUSDT", DAY, LIMIT)
    frame = result.frame
    assert frame["ts"].dt.timestamp("us").to_list() == [
        seconds * 1_000_000 + 100,
        (seconds + 60) * 1_000_000,
        (seconds + 61) * 1_000_000,
    ]
    assert frame["is_taker_buy"].to_list() == [True, False, False]
    assert frame["is_rpi"].to_list() == [False, True, False]
    assert frame["venue"][0] == "bybit"


def test_bybit_files_before_rpi_are_accepted(tmp_path: Path) -> None:
    seconds = us("2026-03-01T00:00:00") // 1_000_000
    head = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional\n"
    )
    text = head + f"{seconds}.5,BTCUSDT,Buy,0.5,100.5,ZeroPlusTick,id-1,1,0.5,50\n"
    frame = parse_bybit_trades(write(tmp_path, "b.csv.gz", gz_bytes(text)), "BTCUSDT", DAY, LIMIT).frame
    assert frame["is_rpi"].to_list() == [False]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("{s}.5,ETHUSDT,Buy,0.5,100,x,id,1,1,1,0\n", "another symbol"),
        ("{s}.5,BTCUSDT,Hold,0.5,100,x,id,1,1,1,0\n", "Buy or Sell"),
        ("{s}.5,BTCUSDT,Buy,0,100,x,id,1,1,1,0\n", "non-positive"),
        ("{s}.5,BTCUSDT,Buy,1,100,x,id,1,1,1,0\n{s}.6,BTCUSDT,Buy,1,100,x,id,1,1,1,0\n", "duplicate"),
    ],
)
def test_bad_bybit_rows_are_refused(tmp_path: Path, row: str, message: str) -> None:
    seconds = us("2026-03-01T00:00:00") // 1_000_000
    text = BYBIT_HEAD + row.format(s=seconds)
    with pytest.raises(ValidationError, match=message):
        parse_bybit_trades(write(tmp_path, "b.csv.gz", gz_bytes(text)), "BTCUSDT", DAY, LIMIT)


def test_klines_values(tmp_path: Path) -> None:
    text = klines_csv(
        [(DAY_MS, 10.0, 12.0, 9.0, 11.0, 5.0, 2.0), (DAY_MS + 60_000, 11.0, 11.0, 11.0, 11.0, 1.0, 1.0)]
    )
    result = parse_klines(write(tmp_path, "k.zip", zip_bytes("k.csv", text)), "BTCUSDT", DAY, LIMIT)
    row = result.frame.row(0, named=True)
    assert (row["open"], row["high"], row["low"], row["close"]) == (10.0, 12.0, 9.0, 11.0)
    assert row["taker_buy_volume"] == 2.0
    assert row["knowable_time"].isoformat() == "2026-03-01T00:01:00+00:00"
    assert result.warnings == ("2 candles instead of 1440",)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([(DAY_MS + 1, 10.0, 12.0, 9.0, 11.0, 5.0, 2.0)], "minute boundary"),
        ([(DAY_MS, 10.0, 8.0, 9.0, 11.0, 5.0, 2.0)], "high is below"),
        ([(DAY_MS + 86_400_000, 10.0, 12.0, 9.0, 11.0, 5.0, 2.0)], "outside their UTC day"),
    ],
)
def test_bad_klines_are_refused(
    tmp_path: Path, rows: list[tuple[int, float, float, float, float, float, float]], message: str
) -> None:
    path = write(tmp_path, "k.zip", zip_bytes("k.csv", klines_csv(rows)))
    with pytest.raises(ValidationError, match=message):
        parse_klines(path, "BTCUSDT", DAY, LIMIT)


def test_book_depth_is_knowable_after_its_truncated_second(tmp_path: Path) -> None:
    text = (
        "timestamp,percentage,depth,notional\n"
        "2026-03-01 00:00:06,-5.00,10.5,1000.25\n"
        "2026-03-01 00:00:06,5.00,11.5,1100.25\n"
    )
    result = parse_book_depth(write(tmp_path, "d.zip", zip_bytes("d.csv", text)), "BTCUSDT", DAY, LIMIT, 1.0)
    row = result.frame.row(0, named=True)
    assert row["ts"].isoformat() == "2026-03-01T00:00:06+00:00"
    assert row["knowable_time"].isoformat() == "2026-03-01T00:00:07+00:00"
    assert result.checks["snapshots"] == 1
    assert result.checks["percentage_levels"] == [-5.0, 5.0]


def test_book_depth_refuses_a_bad_timestamp(tmp_path: Path) -> None:
    text = "timestamp,percentage,depth,notional\nyesterday,-5,1,1\n"
    with pytest.raises(ValidationError, match="bad timestamp"):
        parse_book_depth(write(tmp_path, "d.zip", zip_bytes("d.csv", text)), "BTCUSDT", DAY, LIMIT, 1.0)


def test_funding_uses_actual_settlement_times(tmp_path: Path) -> None:
    month = dt.date(2026, 3, 1)
    stamp = us("2026-03-01T08:00:00") // 1000 + 5
    text = f"calc_time,funding_interval_hours,last_funding_rate\n{stamp},8,0.0001\n"
    result = parse_funding(write(tmp_path, "f.zip", zip_bytes("f.csv", text)), "BTCUSDT", month, LIMIT)
    row = result.frame.row(0, named=True)
    assert row["settle_time"].isoformat() == "2026-03-01T08:00:00.005000+00:00"
    assert row["knowable_time"] == row["settle_time"]
    assert row["funding_rate"] == 0.0001
    assert row["funding_interval_hours"] == 8


def test_checksum_sidecar_parsing() -> None:
    digest = "a" * 64
    assert parse_checksum_sidecar(f"{digest}  x.zip\n", "x.zip") == digest
    assert parse_checksum_sidecar(f"{digest.upper()}  *x.zip\n", "x.zip") == digest
    with pytest.raises(ValidationError, match="different file"):
        parse_checksum_sidecar(f"{digest}  y.zip\n", "x.zip")
    with pytest.raises(ValidationError, match="unexpected format"):
        parse_checksum_sidecar("not a checksum", "x.zip")


def test_a_zip_with_several_members_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", "x")
        archive.writestr("b.csv", "y")
    with pytest.raises(ValidationError, match="one zip member"):
        read_zip_member(write(tmp_path, "z.zip", buffer.getvalue()), LIMIT)


def test_a_decompression_bomb_stops_at_the_limit(tmp_path: Path) -> None:
    bomb = write(tmp_path, "b.zip", zip_bytes("a.csv", "0" * 5_000_000))
    with pytest.raises(ValidationError, match="declares"):
        read_zip_member(bomb, 1000)
    gz_bomb = write(tmp_path, "b.gz", gzip.compress(b"0" * 5_000_000))
    with pytest.raises(ValidationError, match="expands beyond"):
        read_gzip(gz_bomb, 1000)


def test_truncated_or_garbage_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unreadable zip"):
        read_zip_member(write(tmp_path, "g.zip", b"this is not a zip"), LIMIT)
    good = zip_bytes("a.csv", "x" * 1000)
    with pytest.raises(ValidationError, match="unreadable zip"):
        read_zip_member(write(tmp_path, "t.zip", good[: len(good) // 2]), LIMIT)
    with pytest.raises(ValidationError, match="unreadable gzip"):
        read_gzip(write(tmp_path, "g.gz", b"this is not gzip"), LIMIT)
    packed = gzip.compress(b"y" * 100000)
    with pytest.raises(ValidationError, match="unreadable gzip"):
        read_gzip(write(tmp_path, "t.gz", packed[: len(packed) // 2]), LIMIT)


def test_zip_member_names_are_never_used_as_paths(tmp_path: Path) -> None:
    """A hostile member name cannot write anywhere, because nothing is extracted."""
    data = zip_bytes("../../evil.csv", "payload")
    assert read_zip_member(write(tmp_path, "z.zip", data), LIMIT) == b"payload"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["z.zip"]
    assert not (tmp_path.parent.parent / "evil.csv").exists()
