"""An end-to-end run on generated data, labelled SYNTHETIC everywhere, with no network at all.

It drives the real code from file delivery to the published page: adapters, checksums, catalog, bars, higher
timeframes, reconciliation, raw deletion, the hourly poll, retention planning, health and the report.

So that its output can never be mistaken for market results:
- The root is marked, and any report from a marked root is labelled SYNTHETIC and cannot be marked published.
- Symbols are invented, and the calendar is set in a year before either asset existed.
- Every number comes from a seeded generator here. No market file is read, and no value is copied from one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import random
import re
import urllib.parse
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from hft_crypto.config import (
    ConfigError,
    DatasetSpec,
    PipelineConfig,
    PollPair,
    ReconTolerance,
    RetentionPolicy,
    SourceSpec,
    quota_bytes,
)
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.context import JobContext
from hft_crypto.data.fetch import NotPublishedError
from hft_crypto.data.ingest import IngestOptions, run_ingest
from hft_crypto.data.live_checks import run_live_checks
from hft_crypto.data.poll import KrakenClient, read_poll_log, run_poll
from hft_crypto.data.retention import build_plan, evaluate_watermarks
from hft_crypto.data.zones import SYNTHETIC_MARKER, DataRoot, measure_zones
from hft_crypto.reports.report import write_report
from hft_crypto.timeutil import day_start_us, iso, month_key, next_month, to_us

SYNTHETIC_VENUE = "synthetic"
SYNTHETIC_POLL_VENUE = "synthetic-poll"
SYMBOLS = ("SYNTHBTC", "SYNTHETH")
START_PRICES = {"SYNTHBTC": 1000.0, "SYNTHETH": 100.0}
# Before either asset existed, so these dates can only ever mean generated data.
FIRST_DAY = dt.date(2000, 1, 17)
DEFAULT_SEED = 20000117
_BASE_URL = "https://synthetic.invalid"
_MINUTE_MS = 60_000
_DAY_MS = 86_400_000
_TRADES_PER_MINUTE = 1.2
_DAILY_VOLATILITY = 0.03
_POLL_DAYS = 3
_POLL_HOURS = 48
# One aggregate on one day spills further than the placeholder window explains, so a run always exercises the
# failing path: the day fails, its bars stay, it is logged as excluded, and results leave it out.
_FAULT_DAY_INDEX = 3
_FAULT_MINUTE = 600
_FAULT_SPILL_MS = 400


@dataclass(frozen=True)
class GeneratedTrade:
    stamp_ms: int
    price: float
    qty_thousandths: int
    taker_buy: bool
    trade_id: int
    # Thousandths counted by the official candle of the minute after the stamp, to mimic an aggregate whose
    # fills run past a boundary. Zero for most trades.
    spills_next_minute: int = 0


class SyntheticMarket:
    """A seeded price path and trades for each symbol, built up front so that every file agrees."""

    def __init__(self, seed: int, first_day: dt.date, days: int) -> None:
        self.first_day = first_day
        self.days = days
        self.seed = seed
        self.trades: dict[str, list[GeneratedTrade]] = {}
        for index, symbol in enumerate(SYMBOLS):
            generator = random.Random(seed + index)  # noqa: S311
            with_fault = index == 0 and days > _FAULT_DAY_INDEX + 2
            self.trades[symbol] = self._generate(generator, START_PRICES[symbol], with_fault=with_fault)

    def day_range_ms(self, day: dt.date) -> tuple[int, int]:
        start = day_start_us(day) // 1000
        return start, start + _DAY_MS

    def last_day(self) -> dt.date:
        return self.first_day + dt.timedelta(days=self.days - 1)

    def _generate(self, rng: random.Random, start_price: float, *, with_fault: bool) -> list[GeneratedTrade]:
        first_ms = day_start_us(self.first_day) // 1000
        total_minutes = self.days * 1440
        step = _DAILY_VOLATILITY / (_TRADES_PER_MINUTE * 1440) ** 0.5
        price = start_price
        trades: list[GeneratedTrade] = []
        next_id = 1000
        for minute in range(total_minutes):
            minute_start = first_ms + minute * _MINUTE_MS
            stamps = sorted(rng.randrange(1, _MINUTE_MS) for _ in range(_poisson(rng, _TRADES_PER_MINUTE)))
            # The dataset's first minute has a trade, because nothing before it could prove that minute empty.
            if minute == 0 and not stamps:
                stamps = [rng.randrange(1, _MINUTE_MS)]
            # Now and then a trade lands exactly on the boundary, which is where a bar could go wrong.
            if rng.random() < 0.03:
                stamps.insert(0, minute_start)
            for stamp in stamps:
                price *= 1.0 + rng.gauss(0.0, step)
                trades.append(
                    GeneratedTrade(
                        stamp_ms=minute_start + stamp if stamp < _MINUTE_MS else stamp,
                        price=round(price, 2),
                        qty_thousandths=rng.randint(1, 3000),
                        taker_buy=rng.random() < 0.5,
                        trade_id=next_id,
                    )
                )
                next_id += 1
            # Close some minutes with an aggregate that spills past the boundary, including some midnights.
            spills = rng.random() < 0.02 or (minute % 1440 == 1439 and (minute // 1440) % 3 == 1)
            fault = with_fault and minute == _FAULT_DAY_INDEX * 1440 + _FAULT_MINUTE
            if spills or fault:
                price *= 1.0 + rng.gauss(0.0, step)
                qty = rng.randint(100, 3000)
                trades.append(
                    GeneratedTrade(
                        stamp_ms=minute_start
                        + _MINUTE_MS
                        - (_FAULT_SPILL_MS if fault else rng.randint(1, 80)),
                        price=round(price, 2),
                        qty_thousandths=qty,
                        taker_buy=rng.random() < 0.5,
                        trade_id=next_id,
                        spills_next_minute=rng.randint(1, qty - 1),
                    )
                )
                next_id += 1
        trades.sort(key=lambda t: (t.stamp_ms, t.trade_id))
        return [replace(t, trade_id=1000 + i) for i, t in enumerate(trades)]

    def day_trades(self, symbol: str, day: dt.date) -> list[GeneratedTrade]:
        start, end = self.day_range_ms(day)
        return [t for t in self.trades[symbol] if start <= t.stamp_ms < end]

    # ---- files in the delivered formats ------------------------------------------------------------------

    def agg_trades_csv(self, symbol: str, day: dt.date) -> str:
        lines = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
        for t in self.day_trades(symbol, day):
            maker = "false" if t.taker_buy else "true"
            fill = t.trade_id * 3
            lines.append(
                f"{t.trade_id},{t.price:.2f},{t.qty_thousandths / 1000:.3f},"
                f"{fill},{fill + 2},{t.stamp_ms},{maker}"
            )
        return "\n".join(lines) + "\n"

    def klines_csv(self, symbol: str, day: dt.date) -> str:
        """Official candles count each fill in its own minute, so they differ a little from our bars."""
        start, end = self.day_range_ms(day)
        volume: dict[int, int] = {}
        buys: dict[int, int] = {}
        counts: dict[int, int] = {}
        prices: dict[int, list[float]] = {}

        def add(minute_ms: int, qty: int, taker_buy: bool, price: float, fills: int) -> None:
            volume[minute_ms] = volume.get(minute_ms, 0) + qty
            if taker_buy:
                buys[minute_ms] = buys.get(minute_ms, 0) + qty
            counts[minute_ms] = counts.get(minute_ms, 0) + fills
            prices.setdefault(minute_ms, []).append(price)

        last_price = START_PRICES[symbol]
        for t in self.trades[symbol]:
            minute_ms = t.stamp_ms - t.stamp_ms % _MINUTE_MS
            if t.stamp_ms < start and minute_ms + _MINUTE_MS == start and t.spills_next_minute:
                add(start, t.spills_next_minute, t.taker_buy, t.price, 1)
            if t.stamp_ms < start:
                last_price = t.price
                continue
            if t.stamp_ms >= end:
                break
            # Every row is three fills. A spilling row has one of them in the next minute, so none counts
            # twice.
            kept = t.qty_thousandths - t.spills_next_minute
            add(minute_ms, kept, t.taker_buy, t.price, 2 if t.spills_next_minute else 3)
            spill_minute = minute_ms + _MINUTE_MS
            if t.spills_next_minute and spill_minute < end:
                add(spill_minute, t.spills_next_minute, t.taker_buy, t.price, 1)
        header = (
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
            "taker_buy_quote_volume,ignore"
        )
        lines = [header]
        for minute in range(1440):
            minute_ms = start + minute * _MINUTE_MS
            seen = prices.get(minute_ms)
            if seen:
                open_, high, low, close = seen[0], max(seen), min(seen), seen[-1]
                last_price = close
            else:
                open_ = high = low = close = last_price
            qty = volume.get(minute_ms, 0) / 1000
            buy = buys.get(minute_ms, 0) / 1000
            lines.append(
                f"{minute_ms},{open_:.2f},{high:.2f},{low:.2f},{close:.2f},{qty:.3f},{minute_ms + 59_999},"
                f"{qty * close:.5f},{counts.get(minute_ms, 0)},{buy:.3f},{buy * close:.5f},0"
            )
        return "\n".join(lines) + "\n"

    def book_depth_csv(self, symbol: str, day: dt.date) -> str:
        rng = random.Random(f"{self.seed}-{symbol}-{day.isoformat()}-depth")  # noqa: S311
        lines = ["timestamp,percentage,depth,notional"]
        levels = (-5.0, -4.0, -3.0, -2.0, -1.0, -0.2, 0.2, 1.0, 2.0, 3.0, 4.0, 5.0)
        moment = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
        for slot in range(96):
            stamp = (moment + dt.timedelta(minutes=15 * slot, seconds=6)).strftime("%Y-%m-%d %H:%M:%S")
            for level in levels:
                depth = abs(level) * rng.uniform(50.0, 100.0)
                lines.append(f"{stamp},{level:.2f},{depth:.8f},{depth * START_PRICES[symbol]:.8f}")
        return "\n".join(lines) + "\n"

    def funding_csv(self, symbol: str, month_start: dt.date) -> str:
        rng = random.Random(f"{self.seed}-{symbol}-{month_key(month_start)}-funding")  # noqa: S311
        lines = ["calc_time,funding_interval_hours,last_funding_rate"]
        day = month_start
        end = next_month(month_start)
        while day < end:
            for hour in (0, 8, 16):
                stamp = day_start_us(day) // 1000 + hour * 3_600_000 + rng.randint(0, 9)
                lines.append(f"{stamp},8,{rng.uniform(-0.0002, 0.0002):.8f}")
            day += dt.timedelta(days=1)
        return "\n".join(lines) + "\n"

    def book_lines(self, symbol: str, day: dt.date) -> str:
        """A small order book file in the delivered format, with a restating snapshot in the middle."""
        rng = random.Random(f"{self.seed}-{symbol}-{day.isoformat()}-book")  # noqa: S311
        mid = START_PRICES[symbol]
        bids = {round(mid - 0.5 - i * 0.5, 1): round(rng.uniform(0.1, 5.0), 3) for i in range(10)}
        asks = {round(mid + 0.5 + i * 0.5, 1): round(rng.uniform(0.1, 5.0), 3) for i in range(10)}
        start = day_start_us(day) // 1000

        def message(kind: str, update: int, bid_rows: list[list[str]], ask_rows: list[list[str]]) -> str:
            return json.dumps(
                {
                    "topic": f"orderbook.200.{symbol}",
                    "type": kind,
                    "ts": start + update * 100,
                    "data": {"s": symbol, "b": bid_rows, "a": ask_rows, "u": update, "seq": update * 7},
                    "cts": start + update * 100 - 5,
                }
            )

        def rows(side: dict[float, float]) -> list[list[str]]:
            return [[f"{price:.1f}", f"{qty:.3f}"] for price, qty in side.items()]

        lines = [message("snapshot", 1, rows(bids), rows(asks))]
        for update in range(2, 200):
            price = rng.choice(list(bids))
            bids[price] = round(rng.uniform(0.1, 5.0), 3)
            lines.append(message("delta", update, [[f"{price:.1f}", f"{bids[price]:.3f}"]], []))
            if update == 100:
                lines.append(message("snapshot", update, rows(bids), rows(asks)))
        return "\n".join(lines) + "\n"


def _poisson(rng: random.Random, mean: float) -> int:
    """Number of events in a period, by Knuth's method. Enough for a small mean."""
    threshold = 2.718281828459045 ** (-mean)
    count = 0
    product = rng.random()
    while product > threshold:
        count += 1
        product *= rng.random()
    return count


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, text)
    return buffer.getvalue()


class SyntheticArchive:
    """Stands in for the network, delivering generated files. It opens no connection of any kind."""

    _PATTERNS = (
        (re.compile(r"/daily/klines/(\w+)/1m/\1-1m-(\d{4}-\d{2}-\d{2})\.zip$"), "klines"),
        (re.compile(r"/daily/aggTrades/(\w+)/\1-aggTrades-(\d{4}-\d{2}-\d{2})\.zip$"), "trades"),
        (re.compile(r"/daily/bookDepth/(\w+)/\1-bookDepth-(\d{4}-\d{2}-\d{2})\.zip$"), "depth"),
        (re.compile(r"/monthly/fundingRate/(\w+)/\1-fundingRate-(\d{4}-\d{2})\.zip$"), "funding"),
        (re.compile(r"/book/(\w+)/(\d{4}-\d{2}-\d{2})_\1_ob200\.data\.zip$"), "book"),
    )

    def __init__(self, market: SyntheticMarket, *, published_through: dt.date) -> None:
        self.market = market
        self.published_through = published_through
        self.downloads = 0
        self.bytes_served = 0

    def _build(self, url: str) -> bytes:
        for pattern, kind in self._PATTERNS:
            match = pattern.search(url)
            if match is None:
                continue
            symbol, period = match.group(1), match.group(2)
            name = url.rsplit("/", 1)[1].removesuffix(".zip")
            if kind == "funding":
                month = dt.date.fromisoformat(f"{period}-01")
                if next_month(month) > self.published_through:
                    raise NotPublishedError(url)
                return _zip(f"{name}.csv", self.market.funding_csv(symbol, month))
            day = dt.date.fromisoformat(period)
            if not self.market.first_day <= day <= min(self.published_through, self.market.last_day()):
                raise NotPublishedError(url)
            if kind == "klines":
                return _zip(f"{name}.csv", self.market.klines_csv(symbol, day))
            if kind == "trades":
                return _zip(f"{name}.csv", self.market.agg_trades_csv(symbol, day))
            if kind == "depth":
                return _zip(f"{name}.csv", self.market.book_depth_csv(symbol, day))
            return _zip(name, self.market.book_lines(symbol, day))
        raise NotPublishedError(url)

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        body = self._build(url)
        dest.write_bytes(body)
        self.downloads += 1
        self.bytes_served += len(body)
        return len(body)

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        if url.endswith(".CHECKSUM"):
            target = url.removesuffix(".CHECKSUM")
            digest = hashlib.sha256(self._build(target)).hexdigest()
            return f"{digest}  {target.rsplit('/', 1)[1]}\n".encode()
        return self._build(url)


class SyntheticTradesApi:
    """Stands in for a public trades API with an inclusive `since` cursor. Opens no connection."""

    def __init__(self, market: SyntheticMarket, page_size: int) -> None:
        self.market = market
        self.page_size = page_size
        self.now_ms = 0
        self.calls = 0
        rng = random.Random(market.seed + 99)  # noqa: S311
        # Another market with the same underlying path: a small basis, and only some of the trades.
        self.rows: dict[str, list[list[Any]]] = {}
        for symbol in SYMBOLS:
            rows: list[list[Any]] = []
            trade_id = 500
            for trade in market.trades[symbol]:
                if rng.random() < 0.7:
                    seconds = f"{trade.stamp_ms // 1000}.{trade.stamp_ms % 1000:03d}"
                    side = "b" if trade.taker_buy else "s"
                    price = round(trade.price * 1.0004, 2)
                    rows.append(
                        [
                            f"{price:.2f}",
                            f"{trade.qty_thousandths / 1000:.3f}",
                            seconds,
                            side,
                            "l",
                            "",
                            trade_id,
                        ]
                    )
                    trade_id += 1
            self.rows[symbol] = rows

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        raise NotPublishedError(url)

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        self.calls += 1
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        since_ms = int(query["since"]) // 1_000_000
        found: list[list[Any]] = []
        for row in self.rows[query["pair"]]:
            whole, _, fraction = str(row[2]).partition(".")
            stamp = int(whole) * 1000 + int(fraction)
            if stamp < since_ms:
                continue
            if stamp > self.now_ms or len(found) >= self.page_size:
                break
            found.append(row)
        if found:
            whole, _, fraction = str(found[-1][2]).partition(".")
            last = (int(whole) * 1000 + int(fraction)) * 1_000_000
        else:
            last = since_ms * 1_000_000
        return json.dumps(
            {"error": [], "result": {f"X{query['pair']}": found, "last": str(last)}},
            separators=(",", ":"),
        ).encode()


def synthetic_config(base: PipelineConfig, *, first_day: dt.date, days: int) -> PipelineConfig:
    """The real configuration, with only generated sources enabled and everything else removed."""
    last_day = first_day + dt.timedelta(days=days - 1)
    note = "Generated by this program. Not a data source."
    sources = {
        SYNTHETIC_VENUE: SourceSpec(
            SYNTHETIC_VENUE,
            True,
            False,
            {"archive_base": f"{_BASE_URL}/archive", "book_base": f"{_BASE_URL}/book"},
            note,
            stamp_kind="aggregate_one_price",
            fill_span_allowance_ms=250.0,
            allowance_state="placeholder",
            continuity="trade_id",
        ),
        SYNTHETIC_POLL_VENUE: SourceSpec(
            SYNTHETIC_POLL_VENUE,
            True,
            False,
            {"trades_url": f"{_BASE_URL}/poll"},
            note,
            stamp_kind="exact",
            fill_span_allowance_ms=250.0,
            allowance_state="placeholder",
            continuity="trade_id",
        ),
    }
    # The adapters are the real ones, reading the delivered formats. Only the data behind them is generated.
    keep = {
        "binance_klines": "klines",
        "binance_funding": "funding",
        "binance_book_depth": "book_depth",
        "binance_agg_trades": "trades",
        "bybit_book": "orderbook",
    }
    datasets: list[DatasetSpec] = [
        replace(
            spec,
            id=f"{SYNTHETIC_VENUE}.{keep[spec.adapter]}",
            venue=SYNTHETIC_VENUE,
            start=first_day,
            light=spec.adapter != "bybit_book",
        )
        for spec in base.datasets
        if spec.adapter in keep
    ]
    tolerance = ReconTolerance(
        daily_total_abs=1e-6, boundary_window_ms=250.0, bar_price_rel=0.02, fill_count_rel=0.01
    )
    return replace(
        base,
        symbols=SYMBOLS,
        sources=sources,
        datasets=tuple(datasets),
        reconcile=dict.fromkeys(SYMBOLS, tolerance),
        poll=replace(
            base.poll,
            venue=SYNTHETIC_POLL_VENUE,
            base_url=f"{_BASE_URL}/poll",
            start_date=last_day - dt.timedelta(days=_POLL_DAYS - 1),
            pairs=tuple(PollPair(symbol, symbol, symbol) for symbol in SYMBOLS),
        ),
        report=replace(base.report, benchmark_venue=SYNTHETIC_VENUE, benchmark_symbols=SYMBOLS),
    )


def _prepare_root(path: Path) -> DataRoot:
    """A root is either generated from the start or never. Refuse to mix generated data into anything else."""
    existing_catalog = path / "catalog" / "catalog.sqlite"
    marker = path / SYNTHETIC_MARKER
    if existing_catalog.exists() and not marker.exists():
        raise ConfigError("this DATA_ROOT already holds other data, so a SYNTHETIC run is refused here")
    root = DataRoot(path)
    root.guard.check(SYNTHETIC_MARKER).write_text("Generated test data. Not market data.\n", encoding="utf-8")
    # Also in the catalog, so that losing the marker stops a report instead of removing its label.
    catalog = Catalog(root.catalog_path)
    catalog.set_meta("data_kind", "SYNTHETIC")
    catalog.close()
    return root


def _generated_policy(policy: RetentionPolicy) -> RetentionPolicy:
    """The deletion path has to run here, so its rule counts as reviewed for this generated root, in memory
    only.

    The shipped rule stays unreviewed until data-steward confirms it.
    """
    rules = tuple(
        replace(rule, reviewed=True) if rule.id == "raw-archive-after-curated" else rule
        for rule in policy.rules
    )
    return replace(policy, rules=rules)


def _context(
    root: DataRoot, config: PipelineConfig, policy: RetentionPolicy, moment: dt.datetime, run_id: str
) -> JobContext:
    return JobContext(
        root=root,
        catalog=Catalog(root.catalog_path),
        config=config,
        policy=policy,
        now=lambda: moment,
        run_id=run_id,
    )


def run_synthetic(
    data_root: Path,
    live_root: Path,
    out_dir: Path,
    *,
    base_config: PipelineConfig,
    policy: RetentionPolicy,
    days: int = 30,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Run everything once, on a simulated clock. The same seed gives byte-identical output."""
    first_day = FIRST_DAY
    policy = _generated_policy(policy)
    config = synthetic_config(base_config, first_day=first_day, days=days)
    market = SyntheticMarket(seed, first_day, days)
    last_day = market.last_day()
    midnight_after = dt.datetime(last_day.year, last_day.month, last_day.day, tzinfo=dt.UTC) + dt.timedelta(
        days=1
    )
    root = _prepare_root(data_root)
    poll_root = _prepare_root(live_root)

    # 1. The newest file is not published yet, so it stays pending. That is not an error.
    early = midnight_after + dt.timedelta(hours=1)
    archive = SyntheticArchive(market, published_through=last_day - dt.timedelta(days=1))
    context = _context(root, config, policy, early, "synth-ingest-1")
    first_pass = run_ingest(context, archive, IngestOptions(delete_raw=True))
    context.catalog.close()

    # 2. It appears, and the next run catches up. One opt-in day of book files goes through the validator.
    now = midnight_after + dt.timedelta(hours=10)
    archive = SyntheticArchive(market, published_through=last_day)
    context = _context(root, config, policy, now, "synth-ingest-2")
    second_pass = run_ingest(context, archive, IngestOptions(delete_raw=True, include_book=True))
    context.catalog.close()

    # 3. The hourly poll, with generated lateness and the odd dropped slot.
    api = SyntheticTradesApi(market, config.poll.page_size)
    rng = random.Random(seed + 7)  # noqa: S311
    cron = f"{config.poll.nominal_minute} * * * *"
    polls = 0
    for hours_back in range(_POLL_HOURS, 0, -1):
        minute = config.poll.nominal_minute
        slot = now.replace(minute=minute, second=0, microsecond=0) - dt.timedelta(hours=hours_back)
        if rng.random() < 0.05:
            continue
        delay = dt.timedelta(seconds=rng.randint(30, 1800))
        moment = slot + delay
        api.now_ms = to_us(moment) // 1000
        run = _context(poll_root, config, policy, moment, f"synth-poll-{hours_back:03d}")
        client = KrakenClient(api, config.poll, sleep=lambda _: None)
        run_poll(run, client, cron=cron, job_started_at=moment, event_name="schedule")
        run.catalog.close()
        polls += 1

    # 4. The daily checks, the retention plan and the report.
    context = _context(root, config, policy, now, "synth-report")
    poll_context = _context(poll_root, config, policy, now, "synth-report")
    live_results = run_live_checks(context, poll_context, days=3)
    poll_context.catalog.close()
    used = sum(measure_zones(root).values())
    state = evaluate_watermarks(used, quota_bytes(config.default_quota_gb), policy.watermarks)
    plan = build_plan(root, context.catalog, policy, state, now)
    status = write_report(context, out_dir=out_dir, poll_logs=(poll_root.poll_log,))
    context.catalog.close()
    runs = read_poll_log(poll_root.poll_log)
    return {
        "data_kind": status["data_kind"],
        "label": status["label"],
        "seed": seed,
        "days": days,
        "first_day": first_day.isoformat(),
        "last_day": last_day.isoformat(),
        "simulated_now": iso(now),
        "first_pass": {"done": first_pass.done, "pending": first_pass.pending, "status": first_pass.status},
        "second_pass": {
            "done": second_pass.done,
            "pending": second_pass.pending,
            "status": second_pass.status,
            "bars_built": second_pass.bars_built,
            "raw_deleted_files": first_pass.raw_deleted_files + second_pass.raw_deleted_files,
            "book_days_left": second_pass.book_days_left,
            "errors": second_pass.errors,
        },
        "raw_files_left": sum(1 for p in root.guard.check("raw").rglob("*") if p.is_file()),
        "exclusions": status["reconciliation"]["exclusions"],
        "poll_runs": polls,
        "poll_api_calls": api.calls,
        "poll_runs_logged": len(runs),
        "live_checks": live_results,
        "retention_plan": plan.to_dict()["summary"],
        "benchmarks": status["benchmarks"],
        "reconciliation": status["reconciliation"]["official_candles"],
        "book_replay": status["book_replay"],
        "live_poll": status["live_poll"],
        "storage_bytes": status["health"]["disk"]["zones_bytes"],
    }
