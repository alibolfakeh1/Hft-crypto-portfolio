"""P-1 of docs/reviews/data/first_span_fetch_plan_2026-11-06.md: every request `ingest` makes waits at least
2 s after the one before it ended, the pace the coverage check keeps (coverage record, section 4.2).

No test here reaches a network or waits. Time is a fake clock that moves only when something sleeps or a
request takes time, and each sleep is kept with the name of whoever asked for it. Every file is generated and
every price invented.
"""

from __future__ import annotations

import datetime as dt
import http.client
import io
import json
import shutil
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from helpers import REPO_ROOT, FakeFetcher, base_config, make_context, with_binance_enabled, zip_bytes
from hft_crypto import cli
from hft_crypto.config import PipelineConfig
from hft_crypto.data import coverage
from hft_crypto.data.coverage import MIN_REQUEST_GAP_S, init_check_root, run_coverage_check
from hft_crypto.data.fetch import Fetcher, FetchError, HttpFetcher, NotPublishedError, PacedFetcher
from hft_crypto.data.ingest import HostRefusalStop, IngestOptions, IngestSummary, run_ingest
from hft_crypto.data.sources import ArchiveFile, archive_candidates, monthly_candle_file
from hft_crypto.timeutil import day_start_us

BTC = "BTCUSDT"
NOW = dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC)
DEC = dt.date(2023, 12, 1)
DEC_DAYS = 31
DATASETS = ("binance.klines", "binance.fundingRate")
HOST = "https://data.binance.vision/data/futures/um"
A, B, C, D, E = (f"{HOST}/{name}.zip" for name in "abcde")
KLINES_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
    "taker_buy_quote_volume,ignore"
)
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"


class FakeClock:
    """Seconds that move only when a sleep or a request moves them. Each sleep is kept, with who asked."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[tuple[str, float]] = []

    def __call__(self) -> float:
        return self.now

    def sleeper(self, who: str) -> Callable[[float], None]:
        def sleep(seconds: float) -> None:
            self.slept.append((who, seconds))
            self.now += seconds

        return sleep


@dataclass
class TimedFetcher:
    """FakeFetcher's files, where each request takes `took` seconds on the clock and is logged with its start
    and its end, whether it succeeded or not."""

    clock: FakeClock
    files: FakeFetcher = field(default_factory=FakeFetcher)
    took: float = 0.5
    log: list[tuple[str, float, float]] = field(default_factory=list)

    def _timed[T](self, url: str, request: Callable[[], T]) -> T:
        start = self.clock.now
        self.clock.now += self.took
        try:
            return request()
        finally:
            self.log.append((url, start, self.clock.now))

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        return self._timed(url, lambda: self.files.download(url, dest, max_bytes))

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        return self._timed(url, lambda: self.files.get_bytes(url, max_bytes))

    def urls(self) -> list[str]:
        return [url for url, _, _ in self.log]

    def gaps(self) -> list[float]:
        """From the end of each request to the start of the next."""
        return [after[1] - before[2] for before, after in pairwise(self.log)]


def paced(inner: Fetcher, clock: FakeClock) -> PacedFetcher:
    return PacedFetcher(inner, min_gap_s=MIN_REQUEST_GAP_S, clock=clock, sleep=clock.sleeper("gap"))


# ---- the pacer on its own ----------------------------------------------------------------------------------


def test_the_gap_is_the_coverage_check_s_own_constant_of_2_s() -> None:
    """One value for both, so they cannot drift. The ingest command passes this one (test at the end)."""
    assert MIN_REQUEST_GAP_S == 2.0


def test_each_request_after_the_first_waits_the_gap_from_the_end_of_the_one_before(tmp_path: Path) -> None:
    """A takes 0.5 s from 1000.0 and waits for nothing. B comes straight after, so it waits the whole 2 s.
    0.75 s of work passes before C, so C waits 1.25 s. C takes 5 s, and D still waits 2 s after C ended,
    because a long request is no gap. 3 s pass before E, which is more than the gap, so E waits nothing."""
    clock = FakeClock()
    inner = TimedFetcher(clock)
    for url in (A, B, C, D, E):
        inner.files.files[url] = b"body"
    fetcher = paced(inner, clock)
    fetcher.get_bytes(A, 100)
    fetcher.get_bytes(B, 100)
    clock.now += 0.75
    inner.took = 5.0
    assert fetcher.download(C, tmp_path / "c", 100) == 4
    inner.took = 0.5
    fetcher.get_bytes(D, 100)
    clock.now += 3.0
    fetcher.get_bytes(E, 100)
    assert clock.slept == [("gap", 2.0), ("gap", 1.25), ("gap", 2.0)]
    assert inner.log == [
        (A, 1000.0, 1000.5),
        (B, 1002.5, 1003.0),
        (C, 1005.0, 1010.0),
        (D, 1012.0, 1012.5),
        (E, 1015.5, 1016.0),
    ]
    assert inner.gaps() == [2.0, 2.0, 2.0, 3.0]


@pytest.mark.parametrize(
    "error",
    [
        NotPublishedError("not there"),
        FetchError("refused", reason="http_429"),
        FetchError("reset", reason="connection"),
    ],
    ids=["404", "429", "connection"],
)
def test_a_failed_request_still_counts_and_its_error_passes_through_as_it_was(error: FetchError) -> None:
    clock = FakeClock()
    inner = TimedFetcher(clock)
    inner.files.failures[A] = error
    inner.files.files[B] = b"body"
    fetcher = paced(inner, clock)
    with pytest.raises(FetchError) as caught:
        fetcher.get_bytes(A, 100)
    assert caught.value is error
    assert fetcher.get_bytes(B, 100) == b"body"
    assert clock.slept == [("gap", 2.0)]
    assert inner.log == [(A, 1000.0, 1000.5), (B, 1002.5, 1003.0)]


@pytest.mark.parametrize("gap", [0.0, -2.0, float("nan"), float("inf")])
def test_a_gap_that_is_not_a_positive_number_of_seconds_is_refused(gap: float) -> None:
    with pytest.raises(ValueError, match="min_gap_s"):
        PacedFetcher(FakeFetcher(), min_gap_s=gap)


# ---- the pacer around the real client: retries and refusals -----------------------------------------------


class _Body(io.BytesIO):
    """A response that declares no length."""

    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.headers: dict[str, str] = {}


def client(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[Exception | bytes]]
) -> tuple[HttpFetcher, list[tuple[str, float]]]:
    """The real client, with its retries and its backoff, and its connection replaced. Each attempt is logged
    with its start, takes 0.5 s, and gives the next answer for its URL."""
    fetcher = HttpFetcher(
        replace(base_config().fetch, attempts=3, backoff_s=2.0),
        allowed_hosts=frozenset({"data.binance.vision"}),
        sleep=clock.sleeper("backoff"),
    )
    wire: list[tuple[str, float]] = []

    def connect(url: str) -> _Body:
        wire.append((url, clock.now))
        clock.now += 0.5
        answer = answers[url].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Body(answer)

    monkeypatch.setattr(fetcher, "_open", connect)
    return fetcher, wire


@pytest.mark.parametrize(
    ("breaks", "slept", "wire"),
    [
        (
            1,
            [("backoff", 2.0), ("gap", 2.0)],
            [(A, 1000.0), (A, 1002.5), (B, 1005.0)],
        ),
        (
            2,
            [("backoff", 2.0), ("backoff", 4.0), ("gap", 2.0)],
            [(A, 1000.0), (A, 1002.5), (A, 1007.0), (B, 1009.5)],
        ),
    ],
    ids=["one retry", "two retries"],
)
def test_a_retry_inside_the_client_neither_doubles_the_gap_nor_uses_it_up(
    monkeypatch: pytest.MonkeyPatch,
    breaks: int,
    slept: list[tuple[str, float]],
    wire: list[tuple[str, float]],
) -> None:
    """A's first attempts break off. Before each retry the client waits only its own backoff, 2 s and then
    4 s, and no gap is added on top. A is one request here, so B waits the whole 2 s from the end of A's last
    attempt: the backoff, spent inside A, does not count towards it."""
    clock = FakeClock()
    broken: list[Exception | bytes] = [http.client.IncompleteRead(b"x") for _ in range(breaks)]
    inner, seen = client(clock, monkeypatch, {A: [*broken, b"a"], B: [b"b"]})
    fetcher = paced(inner, clock)
    assert fetcher.get_bytes(A, 100) == b"a"
    assert fetcher.get_bytes(B, 100) == b"b"
    assert clock.slept == slept
    assert seen == wire


@pytest.mark.parametrize("code", [403, 429, 451])
def test_a_refusal_is_still_one_attempt_and_reaches_the_caller_with_its_word(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    clock = FakeClock()
    refusal = urllib.error.HTTPError(A, code, "no", http.client.HTTPMessage(), None)
    inner, seen = client(clock, monkeypatch, {A: [refusal]})
    with pytest.raises(FetchError) as caught:
        paced(inner, clock).get_bytes(A, 100)
    assert caught.value.reason == f"http_{code}"
    assert seen == [(A, 1000.0)]
    assert clock.slept == []


def test_each_retry_also_starts_at_least_the_gap_after_the_attempt_that_failed() -> None:
    """Inside one request the client's backoff is the only wait, and the pacer adds nothing to it. The shipped
    backoff starts at the gap and doubles, so a retry keeps the pace as well."""
    assert base_config().fetch.backoff_s >= MIN_REQUEST_GAP_S


# ---- ingest, paced, on one first-span month ----------------------------------------------------------------


@cache
def _candle_zip() -> bytes:
    """December 2023, every minute, on the 0.01 grid."""
    start = day_start_us(DEC) // 1000
    lines = [KLINES_HEADER]
    for minute in range(DEC_DAYS * 1440):
        stamp = start + minute * 60_000
        lines.append(f"{stamp},37000.1,37000.1,37000.1,37000.1,2.0,{stamp + 59_999},200.0,3,1.0,100.0,0")
    return zip_bytes(f"{BTC}-1m-2023-12.csv", "\n".join(lines) + "\n")


@cache
def _funding_zip() -> bytes:
    """December 2023, every 8 hours."""
    start = day_start_us(DEC) // 1000
    rows = [f"{start + step * 8 * 3_600_000},8,0.00010000" for step in range(DEC_DAYS * 3)]
    return zip_bytes(f"{BTC}-fundingRate-2023-12.csv", "\n".join([FUNDING_HEADER, *rows]) + "\n")


def _config() -> PipelineConfig:
    return replace(with_binance_enabled(base_config()), symbols=(BTC,))


def _options() -> IngestOptions:
    """The plan's own flags, on one month."""
    return IngestOptions(dataset_ids=DATASETS, symbols=(BTC,), start=DEC, end=dt.date(2023, 12, 31))


def _publish_december(files: FakeFetcher, config: PipelineConfig) -> tuple[ArchiveFile, ArchiveFile]:
    candles = archive_candidates(config, config.dataset("binance.klines"), BTC, DEC)[0]
    funding = archive_candidates(config, config.dataset("binance.fundingRate"), BTC, DEC)[0]
    files.publish(candles.url, _candle_zip(), name=candles.filename)
    files.publish(funding.url, _funding_zip(), name=funding.filename)
    return candles, funding


def test_ingest_paces_every_request_zip_and_sidecar_alike_for_candles_and_funding(tmp_path: Path) -> None:
    """Two tasks, candles first, each a zip and then its sidecar: four requests. Each of the last three waits
    the whole 2 s after the one before it ended, across the task boundary too. Nothing else changes: both
    files pass their checksum against the sidecar and are curated, and the run ends `ok`."""
    config = _config()
    clock = FakeClock()
    inner = TimedFetcher(clock)
    candles, funding = _publish_december(inner.files, config)
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    summary = run_ingest(ctx, paced(inner, clock), _options())
    assert (summary.status, summary.stop_reason, summary.planned, summary.done) == ("ok", "none", 2, 2)
    assert inner.urls() == [candles.url, candles.checksum_url, funding.url, funding.checksum_url]
    assert clock.slept == [("gap", 2.0)] * 3
    assert inner.gaps() == [2.0] * 3
    raw = ctx.catalog.files(status="present", prefix="raw/archive/binance/")
    assert sorted((record.kind, (record.check_detail or {})["checksum_source"]) for record in raw) == [
        ("fundingRate", "sidecar"),
        ("klines", "sidecar"),
    ]


@pytest.mark.parametrize("code", [403, 429, 451])
@pytest.mark.parametrize("where", ["zip", "sidecar"])
def test_a_refusal_on_a_zip_or_on_its_sidecar_still_ends_the_run_at_once(
    tmp_path: Path, where: str, code: int
) -> None:
    config = _config()
    clock = FakeClock()
    inner = TimedFetcher(clock)
    candles, _ = _publish_december(inner.files, config)
    refused = candles.url if where == "zip" else candles.checksum_url
    assert refused is not None
    inner.files.failures[refused] = FetchError(f"HTTP {code}", reason=f"http_{code}")
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    with pytest.raises(HostRefusalStop) as caught:
        run_ingest(ctx, paced(inner, clock), _options())
    assert caught.value.code == f"http_{code}"
    asked = [candles.url] if where == "zip" else [candles.url, candles.checksum_url]
    assert inner.urls() == asked
    assert clock.slept == [("gap", 2.0)] * (len(asked) - 1)
    [run] = ctx.catalog._db.execute("SELECT status, summary FROM runs").fetchall()
    assert (run["status"], json.loads(run["summary"])["stop_reason"]) == ("failed", f"http_{code}")


def test_a_checksum_mismatch_still_quarantines_the_zip_and_the_run_goes_on_at_the_same_pace(
    tmp_path: Path,
) -> None:
    config = _config()
    clock = FakeClock()
    inner = TimedFetcher(clock)
    candles, funding = _publish_december(inner.files, config)
    assert candles.checksum_url is not None
    inner.files.files[candles.checksum_url] = f"{'0' * 64}  {candles.filename}\n".encode()
    ctx = make_context(tmp_path / "r", now=NOW, config=config)
    summary = run_ingest(ctx, paced(inner, clock), _options())
    assert (summary.status, summary.stop_reason, summary.done, summary.failed) == ("partial", "none", 1, 1)
    assert inner.urls() == [candles.url, candles.checksum_url, funding.url, funding.checksum_url]
    assert clock.slept == [("gap", 2.0)] * 3
    assert list((ctx.root.path / "quarantine").rglob(f"*{candles.filename}*"))


# ---- the commands: ingest is paced, and the coverage check keeps its own pace ------------------------------


def test_the_ingest_command_puts_its_client_inside_a_pacer_at_the_coverage_check_s_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one way from `ingest` to a network. The client is the real one, so its retries and refusals are
    those above."""
    seen: list[Any] = []

    def recording(ctx: Any, fetcher: Any, options: Any) -> IngestSummary:
        seen.append(fetcher)
        return IngestSummary(run_id=ctx.run_id)

    monkeypatch.setattr("hft_crypto.cli.run_ingest", recording)
    args = ["--config-dir", str(REPO_ROOT / "configs"), "--data-root", str(tmp_path / "r"), "ingest"]
    assert cli.main(args) == 0
    capsys.readouterr()
    [fetcher] = seen
    assert isinstance(fetcher, PacedFetcher)
    assert fetcher.min_gap_s == coverage.MIN_REQUEST_GAP_S == 2.0
    assert type(fetcher.inner) is HttpFetcher


def test_the_coverage_check_keeps_its_pace_sidecar_then_zip_with_2_s_after_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three months: six requests, sidecar then zip, and 2 s slept after each one, so each request starts
    exactly 2 s after the one before it ended. These files hold no candles, which fails their quarter and
    leaves the pace as it is."""
    monkeypatch.setitem(coverage.FROZEN_LISTS, "first-span", (dt.date(2020, 1, 1), dt.date(2020, 3, 1)))
    config = _config()
    clock = FakeClock()
    inner = TimedFetcher(clock)
    targets = [monthly_candle_file(config, "binance", BTC, dt.date(2020, month, 1)) for month in (1, 2, 3)]
    for target in targets:
        inner.files.publish(target.url, zip_bytes("x.csv", "no candles\n"), name=target.filename)
    root = init_check_root(tmp_path / "check", data_root=str(tmp_path / "data-root"))
    document = run_coverage_check(
        root,
        config,
        inner,
        venue="binance",
        list_name="first-span",
        now=lambda: NOW,
        sleep=clock.sleeper("check"),
    )
    assert document["stopped"] == "none"
    assert inner.urls() == [url for target in targets for url in (target.checksum_url, target.url)]
    assert clock.slept == [("check", 2.0)] * 6
    assert inner.gaps() == [2.0] * 5


def test_the_coverage_check_command_gives_its_client_no_second_pace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The coverage check sleeps after each request itself, as before, so its client is the bare one."""
    shipped = (REPO_ROOT / "configs" / "pipeline.toml").read_text(encoding="utf-8")
    start = shipped.index("[sources.binance]\n")
    end = shipped.index("\n[", start + 1)
    switched = shipped[start:end].replace("enabled = false", "enabled = true", 1)
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "pipeline.toml").write_text(shipped[:start] + switched + shipped[end:], encoding="utf-8")
    shutil.copy(REPO_ROOT / "configs" / "retention.toml", folder / "retention.toml")
    seen: list[Any] = []

    def recording(check_root: Path, config: PipelineConfig, fetcher: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(fetcher)
        return {}

    monkeypatch.setattr("hft_crypto.cli.run_coverage_check", recording)
    check = ["coverage-check", "--check-root", str(tmp_path / "check"), "--list", "first-span"]
    assert cli.main(["--config-dir", str(folder), "--data-root", str(tmp_path / "r"), *check]) == 0
    capsys.readouterr()
    assert [type(fetcher) for fetcher in seen] == [HttpFetcher]
