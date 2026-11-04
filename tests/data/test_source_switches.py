"""Every route to a prohibited host, the source switches, and the HTTP client past its refusal path.

No test here reaches a network. The client runs against a handler that records what it was asked for.
"""

from __future__ import annotations

import http.client
import io
import shutil
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

import pytest

from helpers import REPO_ROOT, base_config
from hft_crypto.config import ConfigError, is_prohibited_host, load_pipeline_config, load_retention_policy
from hft_crypto.data.fetch import (
    ALLOWED_HOSTS,
    FetchError,
    ForbiddenHostError,
    HttpFetcher,
    NotPublishedError,
    _CheckedRedirects,
    check_url,
)

SHIPPED = (REPO_ROOT / "configs" / "pipeline.toml").read_text(encoding="utf-8")
BANNED_URL = "https://data.binance.vision/data/futures/um"
ALLOWED = frozenset({"public.bybit.com"})


def load(tmp_path: Path, text: str) -> Any:
    (tmp_path / "pipeline.toml").write_text(text, encoding="utf-8")
    shutil.copy(REPO_ROOT / "configs" / "retention.toml", tmp_path / "retention.toml")
    return load_pipeline_config(tmp_path)


def _section(name: str) -> tuple[int, int]:
    start = SHIPPED.index(f"[sources.{name}]\n")
    end = SHIPPED.index("\n[", start + 1)
    return start, end


def _edit_source(name: str, old: str, new: str) -> str:
    start, end = _section(name)
    block = SHIPPED[start:end]
    assert old in block, old
    return SHIPPED[:start] + block.replace(old, new, 1) + SHIPPED[end:]


def test_the_shipped_file_loads_and_enables_nothing() -> None:
    config = base_config()
    assert config.enabled_sources() == ()
    assert config.enabled_hosts() == frozenset()


# ---- each route in F-10's table
# --------------------------------------------------------------------------------


def test_route_0_flipping_the_flag_alone_is_a_config_error(tmp_path: Path) -> None:
    text = _edit_source("binance", "enabled = false", "enabled = true")
    with pytest.raises(ConfigError, match="prohibited"):
        load(tmp_path, text)


def test_route_1_deleting_the_ban_and_enabling_is_a_config_error(tmp_path: Path) -> None:
    """The ban is in code too. Removing the line from a file cannot lift it."""
    text = _edit_source("binance", "enabled = false", "enabled = true")
    start, end = text.index("[sources.binance]\n"), text.index("\n[", text.index("[sources.binance]\n") + 1)
    block = "\n".join(line for line in text[start:end].splitlines() if not line.startswith("prohibited"))
    with pytest.raises(ConfigError):
        load(tmp_path, text[:start] + block + text[end:])


def test_route_1b_setting_the_ban_to_false_is_a_config_error(tmp_path: Path) -> None:
    text = _edit_source("binance", "enabled = false", "enabled = true")
    text = text.replace("prohibited = true", "prohibited = false", 1)
    with pytest.raises(ConfigError):
        load(tmp_path, text)


def test_route_2_a_string_for_the_ban_is_a_config_error(tmp_path: Path) -> None:
    """`bool("")` is false, so this used to lift the ban."""
    text = _edit_source("binance", "prohibited = true", 'prohibited = ""')
    with pytest.raises(ConfigError, match="true or false"):
        load(tmp_path, text)


def test_route_3_another_source_on_a_prohibited_host_is_a_config_error(tmp_path: Path) -> None:
    start, end = _section("bybit")
    block = SHIPPED[start:end].replace("enabled = false", "enabled = true", 1)
    block = block.replace("https://public.bybit.com", "https://data.binance.vision", 1)
    assert "data.binance.vision" in block
    with pytest.raises(ConfigError, match="prohibited"):
        load(tmp_path, SHIPPED[:start] + block + SHIPPED[end:])


@pytest.mark.parametrize(
    "host",
    ["data.binance.vision", "DATA.BINANCE.VISION", "api.binance.com", "x.binance.us", "binancefuture.com"],
)
def test_route_4_a_new_source_on_a_prohibited_host_is_a_config_error(tmp_path: Path, host: str) -> None:
    start, end = _section("bybit")
    mirror = SHIPPED[start:end].replace("[sources.bybit]", "[sources.mirror]", 1)
    mirror = mirror.replace("enabled = false", "enabled = true", 1)
    mirror = mirror.replace("https://public.bybit.com", f"https://{host}", 1)
    text = SHIPPED[:end] + "\n" + mirror + SHIPPED[end:]
    with pytest.raises(ConfigError, match="prohibited"):
        load(tmp_path, text)


def test_route_5_a_config_folder_in_the_working_directory_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever sits in the working directory cannot replace the shipped file."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "pipeline.toml").write_text("not = 'a config'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HFT_CONFIG_DIR", raising=False)
    assert load_pipeline_config().enabled_sources() == ()


def test_route_5b_a_file_named_by_the_variable_gets_every_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pipeline.toml").write_text(
        _edit_source("binance", "enabled = false", "enabled = true"), encoding="utf-8"
    )
    monkeypatch.setenv("HFT_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="prohibited"):
        load_pipeline_config()


@pytest.mark.parametrize(
    "hosts", [ALLOWED_HOSTS, frozenset({"data.binance.vision"}), ALLOWED_HOSTS | {"data.binance.vision"}]
)
def test_route_6_code_cannot_hand_the_client_a_prohibited_host(tmp_path: Path, hosts: frozenset[str]) -> None:
    fetcher = HttpFetcher(base_config().fetch, allowed_hosts=hosts)
    url = f"{BANNED_URL}/daily/x.zip"
    with pytest.raises(ForbiddenHostError):
        fetcher.get_bytes(url, 10)
    with pytest.raises(ForbiddenHostError):
        fetcher.download(url, tmp_path / "x", 10)


@pytest.mark.parametrize("value", ['"false"', '"true"', '"no"', "0", "1"])
def test_route_7_a_flag_must_be_a_real_boolean(tmp_path: Path, value: str) -> None:
    """A typo fails closed. `bool("false")` is true, and that used to enable the source."""
    text = _edit_source("bybit", "enabled = false", f"enabled = {value}")
    with pytest.raises(ConfigError, match="true or false"):
        load(tmp_path, text)


def test_an_unknown_key_in_a_source_is_a_config_error(tmp_path: Path) -> None:
    text = _edit_source("bybit", "enabled = false", "enabled = false\nenabeld = true")
    with pytest.raises(ConfigError, match="enabeld"):
        load(tmp_path, text)


@pytest.mark.parametrize("key", ["stamp_kind", "fill_span_allowance_ms", "allowance_state", "continuity"])
def test_a_source_must_declare_its_timing_with_no_default(tmp_path: Path, key: str) -> None:
    """DC-02, DC-03. A required key: leaving it out gets no optimistic reading."""
    start, end = _section("bybit")
    block = "\n".join(line for line in SHIPPED[start:end].splitlines() if not line.startswith(key))
    with pytest.raises(ConfigError):
        load(tmp_path, SHIPPED[:start] + block + SHIPPED[end:])


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("continuity", '"maybe"'),
        ("stamp_kind", '"whatever"'),
        ("allowance_state", '"guessed"'),
        ("fill_span_allowance_ms", "-1.0"),
    ],
)
def test_a_declared_timing_value_is_checked(tmp_path: Path, key: str, value: str) -> None:
    start, end = _section("bybit")
    lines = [
        f"{key} = {value}" if line.startswith(f"{key} =") else line
        for line in SHIPPED[start:end].splitlines()
    ]
    with pytest.raises(ConfigError):
        load(tmp_path, SHIPPED[:start] + "\n".join(lines) + SHIPPED[end:])


def test_the_benchmark_venue_must_be_usable(tmp_path: Path) -> None:
    """F-12. The report and the source switches used to be unconnected."""
    assert 'benchmark_venue = ""' in SHIPPED
    with pytest.raises(ConfigError, match="benchmark"):
        load(tmp_path, SHIPPED.replace('benchmark_venue = ""', 'benchmark_venue = "binance"', 1))
    with pytest.raises(ConfigError, match="benchmark"):
        load(tmp_path, SHIPPED.replace('benchmark_venue = ""', 'benchmark_venue = "bybit"', 1))


def test_a_shipped_source_with_every_flag_as_given_cannot_reach_a_prohibited_host_by_name() -> None:
    config = base_config()
    from dataclasses import replace

    enabled_but_named = replace(
        config,
        sources={
            **config.sources,
            "binance": replace(config.source("binance"), enabled=True, prohibited=False),
        },
    )
    assert not enabled_but_named.source_usable("binance")
    assert "data.binance.vision" not in enabled_but_named.enabled_hosts()


@pytest.mark.parametrize(
    ("host", "banned"),
    [
        ("data.binance.vision", True),
        ("DATA.binance.VISION.", True),
        ("binance.com", True),
        ("fapi.binance.com", True),
        ("notbinance.com", False),
        ("binance.com.evil.example", False),
        ("public.bybit.com", False),
        (None, False),
    ],
)
def test_prohibited_host_matching(host: str | None, banned: bool) -> None:
    assert is_prohibited_host(host) is banned


# ---- URLs
# ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example\\@public.bybit.com/x",
        "https://user@public.bybit.com/x",
        "https://user:pw@public.bybit.com/x",
        "https://public.bybit.com:8443/x",
        "https://public.bybit.com:443/x",
        "https://public.bybit.com:notaport/x",
        "https://public.bybit.com/a b",
        "https://public.bybit.com/\nx",
        "http://public.bybit.com/x",
        "ftp://public.bybit.com/x",
        "file:///public.bybit.com/x",
        "https://public.bybit.com.evil.example/x",
        "https://evil.example/public.bybit.com",
        "//public.bybit.com/x",
    ],
)
def test_netloc_tricks_are_refused(url: str) -> None:
    with pytest.raises(ForbiddenHostError):
        check_url(url, ALLOWED)


def test_a_plain_allowed_url_passes() -> None:
    check_url("https://public.bybit.com/trading/BTCUSDT/x.csv.gz", ALLOWED)


def test_a_prohibited_host_is_refused_even_if_someone_puts_it_on_the_list() -> None:
    with pytest.raises(ForbiddenHostError, match="prohibited"):
        check_url(f"{BANNED_URL}/x", frozenset({"data.binance.vision"}))


# ---- redirects, which no test used to cover: removing the check survived mutation
# -----------------------------


class _Response(io.BytesIO):
    """What urllib hands back, far enough for the client."""

    def __init__(
        self,
        body: bytes = b"",
        *,
        code: int = 200,
        url: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(body)
        self.code = code
        self.status = code
        self.msg = "x"
        self.url = url
        self.headers = http.client.HTTPMessage()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def close(self) -> None:
        """The client closes each response, and a route can be asked for again."""
        self.seek(0)

    def info(self) -> http.client.HTTPMessage:
        return self.headers

    def getcode(self) -> int:
        return self.code

    def geturl(self) -> str:
        return self.url


class _Network(urllib.request.BaseHandler):
    """Stands in for HTTPS, HTTP and files. It records every URL asked for, and that is all it can do."""

    def __init__(self, routes: dict[str, _Response | Exception]) -> None:
        self.routes = routes
        self.seen: list[str] = []

    def _serve(self, request: urllib.request.Request) -> _Response:
        url = request.full_url
        self.seen.append(url)
        route = self.routes.get(url)
        if isinstance(route, Exception):
            raise route
        if route is None:
            raise urllib.error.HTTPError(url, 404, "no", http.client.HTTPMessage(), None)
        route.seek(0)
        return route

    https_open = _serve
    http_open = _serve
    file_open = _serve


def offline_opener(network: _Network) -> urllib.request.OpenerDirector:
    """Built by hand. `build_opener` adds the real HTTPS handler, which would answer ahead of the fake one."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        network,
        _CheckedRedirects(ALLOWED),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
    ):
        opener.add_handler(handler)
    handlers = opener.handlers  # type: ignore[attr-defined]
    assert not any(isinstance(item, urllib.request.HTTPSHandler) for item in handlers)
    return opener


def client(routes: dict[str, _Response | Exception], *, attempts: int = 3) -> tuple[HttpFetcher, _Network]:
    from dataclasses import replace

    network = _Network(routes)
    limits = replace(base_config().fetch, attempts=attempts, backoff_s=0.0)
    fetcher = HttpFetcher(limits, allowed_hosts=ALLOWED, sleep=lambda _: None)
    fetcher._opener = offline_opener(network)
    return fetcher, network


GOOD = "https://public.bybit.com/x"


def test_the_guard_below_every_http_library_is_on() -> None:
    """The suite's own network guard, in tests/conftest.py. A real client gets no further than this."""
    fetcher = HttpFetcher(base_config().fetch, allowed_hosts=ALLOWED, sleep=lambda _: None)
    with pytest.raises(FetchError, match="network"):
        fetcher.get_bytes(GOOD, 100)


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/x",
        "http://public.bybit.com/x",
        f"{BANNED_URL}/x",
        "https://public.bybit.com:8443/x",
    ],
)
def test_a_redirect_off_the_list_is_refused_before_anything_is_asked_of_it(target: str) -> None:
    fetcher, network = client(
        {
            GOOD: _Response(code=302, url=GOOD, headers={"Location": target}),
            target: _Response(b"should never be read", url=target),
        }
    )
    with pytest.raises(ForbiddenHostError):
        fetcher.get_bytes(GOOD, 100)
    assert network.seen == [GOOD]


def test_a_redirect_to_a_file_is_never_followed() -> None:
    """The standard library refuses this scheme first, as an HTTP error, so it fails like any other bad
    response."""
    target = "file:///etc/passwd"
    fetcher, network = client(
        {
            GOOD: _Response(code=302, url=GOOD, headers={"Location": target}),
            target: _Response(b"should never be read", url=target),
        },
        attempts=1,
    )
    with pytest.raises(FetchError):
        fetcher.get_bytes(GOOD, 100)
    assert network.seen == [GOOD]


def test_a_redirect_within_the_list_is_followed_and_read() -> None:
    other = "https://public.bybit.com/y"
    fetcher, network = client(
        {
            GOOD: _Response(code=302, url=GOOD, headers={"Location": other}),
            other: _Response(b"body", url=other),
        }
    )
    assert fetcher.get_bytes(GOOD, 100) == b"body"
    assert network.seen == [GOOD, other]


# ---- the client past its refusal path
# --------------------------------------------------------------------------


def test_a_successful_read_and_a_successful_download(tmp_path: Path) -> None:
    fetcher, _ = client({GOOD: _Response(b"hello", url=GOOD, headers={"Content-Length": "5"})})
    assert fetcher.get_bytes(GOOD, 100) == b"hello"
    target = tmp_path / "out"
    assert fetcher.download(GOOD, target, 100) == 5
    assert target.read_bytes() == b"hello"


def test_a_404_is_not_published_and_is_not_retried() -> None:
    fetcher, network = client({})
    with pytest.raises(NotPublishedError):
        fetcher.get_bytes(GOOD, 100)
    assert network.seen == [GOOD]


@pytest.mark.parametrize("code", [403, 451])
def test_a_refusal_by_the_host_is_not_retried(code: int) -> None:
    error = urllib.error.HTTPError(GOOD, code, "no", http.client.HTTPMessage(), None)
    fetcher, network = client({GOOD: error})
    with pytest.raises(FetchError, match=str(code)):
        fetcher.get_bytes(GOOD, 100)
    assert network.seen == [GOOD]


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"partial"),
        http.client.BadStatusLine("garbage"),
        urllib.error.URLError("no route"),
        TimeoutError("slow"),
        ConnectionResetError("reset"),
        OSError("disk or socket"),
        ValueError("not a number"),
        zlib.error("not this layer, but it must not end the run"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_every_kind_of_broken_response_is_retried_and_then_a_fetch_error(error: Exception) -> None:
    """F-05. IncompleteRead, BadStatusLine and a non-numeric length used to escape and kill the run."""
    fetcher, network = client({GOOD: error}, attempts=3)
    with pytest.raises(FetchError):
        fetcher.get_bytes(GOOD, 100)
    assert len(network.seen) == 3


def test_a_retry_succeeds_when_the_host_recovers() -> None:
    class Flaky(_Network):
        def _serve(self, request: urllib.request.Request) -> _Response:
            self.seen.append(request.full_url)
            if len(self.seen) == 1:
                raise http.client.IncompleteRead(b"x")
            return _Response(b"good", url=request.full_url)

        https_open = _serve

    from dataclasses import replace

    network = Flaky({})
    fetcher = HttpFetcher(
        replace(base_config().fetch, attempts=2), allowed_hosts=ALLOWED, sleep=lambda _: None
    )
    fetcher._opener = offline_opener(network)
    assert fetcher.get_bytes(GOOD, 100) == b"good"
    assert len(network.seen) == 2


def test_the_size_cap_holds_on_both_paths_and_is_not_retried(tmp_path: Path) -> None:
    fetcher, network = client({GOOD: _Response(b"x" * 50, url=GOOD)})
    with pytest.raises(FetchError, match="exceeds"):
        fetcher.get_bytes(GOOD, 10)
    with pytest.raises(FetchError, match="exceeds"):
        fetcher.download(GOOD, tmp_path / "out", 10)
    assert len(network.seen) == 2


@pytest.mark.parametrize("declared", ["5", "not a number"])
def test_a_short_or_unreadable_length_fails_the_attempt(tmp_path: Path, declared: str) -> None:
    """F-23. get_bytes had no such check, unlike download, so a short body returned as if whole."""
    fetcher, _ = client({GOOD: _Response(b"xx", url=GOOD, headers={"Content-Length": declared})})
    with pytest.raises(FetchError):
        fetcher.get_bytes(GOOD, 100)
    with pytest.raises(FetchError):
        fetcher.download(GOOD, tmp_path / "out", 100)


def test_the_retention_rule_for_raw_ships_unreviewed() -> None:
    """A writer does not approve its own rule. data-steward confirms it after the fixes are reviewed."""
    assert load_retention_policy(REPO_ROOT / "configs").rule("raw-archive-after-curated").reviewed is False
