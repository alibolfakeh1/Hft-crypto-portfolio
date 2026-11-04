"""Builders for test fixtures. Everything is generated here. No market data is ever committed."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import polars as pl

from hft_crypto.bars.core import UTC_TIME
from hft_crypto.config import (
    PipelineConfig,
    RetentionPolicy,
    load_pipeline_config,
    load_retention_policy,
    parse_retention_policy,
)
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.context import JobContext
from hft_crypto.data.fetch import FetchError, NotPublishedError
from hft_crypto.data.zones import DataRoot
from hft_crypto.timeutil import day_start_us

REPO_ROOT = Path(__file__).resolve().parents[1]
MINUTE = 60_000_000
DAY = 86_400_000_000


def us(text: str) -> int:
    """Microseconds for a time such as 2026-01-01T00:01:00, read as UTC."""
    moment = dt.datetime.fromisoformat(text).replace(tzinfo=dt.UTC)
    delta = moment - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def trades_frame(rows: Sequence[tuple[int, float, float, bool]], *, first_id: int = 1) -> pl.DataFrame:
    """Trades from (ts_us, price, qty, is_taker_buy)."""
    return pl.DataFrame(
        {
            "ts": pl.Series([r[0] for r in rows], dtype=pl.Int64).cast(UTC_TIME),
            "price": pl.Series([r[1] for r in rows], dtype=pl.Float64),
            "qty": pl.Series([r[2] for r in rows], dtype=pl.Float64),
            "is_taker_buy": pl.Series([r[3] for r in rows], dtype=pl.Boolean),
            "trade_id": pl.Series(list(range(first_id, first_id + len(rows))), dtype=pl.Int64),
            "n_fills": pl.Series([1] * len(rows), dtype=pl.Int32),
        }
    )


def zip_bytes(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # A fixed date, or two identical files would differ by when they were zipped.
        info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, text)
    return buffer.getvalue()


def agg_trades_csv(rows: Iterable[tuple[int, float, float, bool]], *, first_id: int = 1000) -> str:
    """aggTrades rows from (ms, price, qty, is_taker_buy)."""
    lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
    for index, (stamp, price, qty, taker_buy) in enumerate(rows):
        maker = "false" if taker_buy else "true"
        identifier = first_id + index
        lines.append(f"{identifier},{price},{qty},{identifier},{identifier},{stamp},{maker}")
    return "\n".join(lines) + "\n"


def klines_csv(rows: Iterable[tuple[int, float, float, float, float, float, float]]) -> str:
    """Candles from (open_ms, open, high, low, close, volume, taker_buy_volume)."""
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
        "taker_buy_quote_volume,ignore"
    ]
    for stamp, open_, high, low, close, volume, buy in rows:
        lines.append(
            f"{stamp},{open_},{high},{low},{close},{volume},{stamp + 59_999},{volume * close},1,"
            f"{buy},{buy * close},0"
        )
    return "\n".join(lines) + "\n"


def make_day_files(day: dt.date, price: float = 100.0, qty: float = 1.0) -> tuple[str, str]:
    """A consistent aggTrades and klines pair: one taker buy in the middle of each minute of a day."""
    start_ms = day_start_us(day) // 1000
    trades = []
    candles = []
    for minute in range(1440):
        open_ms = start_ms + minute * 60_000
        trades.append((open_ms + 30_000, price, qty, True))
        candles.append((open_ms, price, price, price, price, qty, qty))
    return agg_trades_csv(trades), klines_csv(candles)


@dataclass
class FakeFetcher:
    """A network stand-in. Unknown URLs behave like a file that is not published yet."""

    files: dict[str, bytes] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def _body(self, url: str) -> bytes:
        self.requests.append(url)
        if url in self.failures:
            raise self.failures[url]
        if url not in self.files:
            raise NotPublishedError(url)
        return self.files[url]

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        body = self._body(url)
        if len(body) > max_bytes:
            raise FetchError("too large")
        dest.write_bytes(body)
        return len(body)

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        body = self._body(url)
        if len(body) > max_bytes:
            raise FetchError("too large")
        return body

    def publish(self, url: str, body: bytes, *, name: str, sidecar: bool = True) -> None:
        self.files[url] = body
        if sidecar:
            digest = hashlib.sha256(body).hexdigest()
            self.files[f"{url}.CHECKSUM"] = f"{digest}  {name}\n".encode()


BINANCE = "https://data.binance.vision/data/futures/um"


def publish_binance_day(
    fetcher: FakeFetcher,
    symbol: str,
    day: dt.date,
    trades_csv: str | None = None,
    candles_csv: str | None = None,
) -> None:
    default_trades, default_candles = make_day_files(day)
    trades_name = f"{symbol}-aggTrades-{day.isoformat()}"
    candles_name = f"{symbol}-1m-{day.isoformat()}"
    fetcher.publish(
        f"{BINANCE}/daily/aggTrades/{symbol}/{trades_name}.zip",
        zip_bytes(f"{trades_name}.csv", trades_csv or default_trades),
        name=f"{trades_name}.zip",
    )
    fetcher.publish(
        f"{BINANCE}/daily/klines/{symbol}/1m/{candles_name}.zip",
        zip_bytes(f"{candles_name}.csv", candles_csv or default_candles),
        name=f"{candles_name}.zip",
    )


def gz_bytes(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), mtime=0)


def book_lines(messages: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(m).encode() + b"\n" for m in messages)


def book_message(
    kind: str,
    update_id: int,
    bids: list[list[str]],
    asks: list[list[str]],
    *,
    ts: int = 1000,
    seq: int | None = None,
) -> dict[str, Any]:
    return {
        "topic": "orderbook.200.BTCUSDT",
        "type": kind,
        "ts": ts + update_id,
        "data": {
            "s": "BTCUSDT",
            "b": bids,
            "a": asks,
            "u": update_id,
            "seq": update_id if seq is None else seq,
        },
        "cts": ts,
    }


def base_config() -> PipelineConfig:
    return load_pipeline_config(REPO_ROOT / "configs")


def with_sources_enabled(config: PipelineConfig) -> PipelineConfig:
    """Every source switched on, for tests of the adapters. These only ever see generated files."""
    return replace(
        config,
        sources={
            name: replace(source, enabled=True, prohibited=False) for name, source in config.sources.items()
        },
    )


def base_policy() -> RetentionPolicy:
    return load_retention_policy(REPO_ROOT / "configs")


def policy_with_rules(rules: list[dict[str, Any]], **overrides: Any) -> RetentionPolicy:
    """A policy with the real watermarks and only the given rules."""
    raw: dict[str, Any] = {
        "policy_version": "test",
        "watermarks": {
            "warn_pct": 70.0,
            "stop_backfill_pct": 80.0,
            "purge_raw_pct": 85.0,
            "purge_runs_pct": 90.0,
            "critical_pct": 95.0,
            "headroom_alert_days": 3.0,
        },
        "sample_days": {"day_of_month": 1, "kinds": ["trades", "book_depth"], "protect_raw": False},
        "rules": rules,
    }
    raw.update(overrides)
    return parse_retention_policy(raw)


def make_context(
    root_path: Path,
    *,
    now: dt.datetime,
    policy: RetentionPolicy | None = None,
    config: PipelineConfig | None = None,
) -> JobContext:
    root = DataRoot(root_path)
    return JobContext(
        root=root,
        catalog=Catalog(root.catalog_path),
        config=config or base_config(),
        policy=policy or base_policy(),
        now=lambda: now,
        run_id="testrun",
    )
