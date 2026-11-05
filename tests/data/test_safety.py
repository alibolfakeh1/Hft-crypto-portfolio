"""Rules that protect the project: no orders, only public hosts, nothing private in the repository."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from helpers import REPO_ROOT, base_config
from hft_crypto.config import APPROVED_ROUTES, route_problem
from hft_crypto.data.fetch import ALLOWED_HOSTS, ForbiddenHostError, HttpFetcher, check_url

SOURCE = REPO_ROOT / "src"
PY_FILES = sorted(SOURCE.rglob("*.py"))


def test_there_is_source_to_check() -> None:
    assert len(PY_FILES) > 10


@pytest.mark.parametrize(
    "url",
    [
        "http://data.binance.vision/data/futures/um/x.zip",  # not HTTPS
        "https://data.binance.vision/data/spot/x.zip",  # not this project's product
        "https://api.binance.com/api/v3/order",  # order endpoints live on these hosts
        "https://fapi.binance.com/fapi/v1/order",
        "https://api.bybit.com/v5/order/create",
        "https://api.kraken.com.evil.example/0/public/Trades",
        "https://localhost/x",
        "file:///etc/passwd",
    ],
)
def test_only_https_to_allowed_hosts(url: str) -> None:
    with pytest.raises(ForbiddenHostError):
        check_url(url, ALLOWED_HOSTS)


def test_allowed_hosts_exclude_all_exchange_trading_hosts() -> None:
    assert {
        "data.binance.vision",
        "public.bybit.com",
        "quote-saver.bycsi.com",
    } == ALLOWED_HOSTS


def test_every_configured_source_is_on_the_allowlist() -> None:
    config = base_config()
    for source in config.sources.values():
        assert source.urls
        for url in source.urls.values():
            if source.prohibited:
                with pytest.raises(ForbiddenHostError):
                    check_url(url, ALLOWED_HOSTS)
            elif urlsplit(url).hostname in APPROVED_ROUTES:
                # A base address is not a file, so it is checked against the route and not fetched as a file.
                assert route_problem(source.name, url) is None
                with pytest.raises(ForbiddenHostError):
                    check_url(url, ALLOWED_HOSTS)
            else:
                check_url(url, ALLOWED_HOSTS)


def test_the_only_kraken_path_is_public_and_it_is_prohibited() -> None:
    config = base_config()
    assert "/0/public/" in config.poll.base_url
    assert config.source("kraken").prohibited is True
    assert not config.source_usable("kraken")


def test_every_source_ships_disabled() -> None:
    config = base_config()
    assert config.enabled_sources() == ()
    assert config.enabled_hosts() == frozenset()
    assert config.source_state() == "no approved source configured"
    assert config.report.benchmark_venue is None
    assert all(not source.enabled for source in config.sources.values())


def test_terms_notes_name_the_decision_and_are_not_stale() -> None:
    config = base_config()
    assert "D-29" in config.source("binance").terms_note
    assert "non-commercial" in config.source("binance").terms_note
    assert "Not approved" in config.source("bybit").terms_note
    assert "D-23" in config.source("kraken").terms_note
    for source in config.sources.values():
        assert "UNVERIFIED" not in source.terms_note


def test_with_no_approved_source_the_client_refuses_every_host(tmp_path: Path) -> None:
    config = base_config()
    fetcher = HttpFetcher(config.fetch, allowed_hosts=config.enabled_hosts())
    for url in (
        "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-03-01.zip",
        "https://public.bybit.com/trading/x.csv.gz",
        "https://quote-saver.bycsi.com/orderbook/linear/x.zip",
        "https://api.kraken.com/0/public/Trades",
    ):
        with pytest.raises(ForbiddenHostError):
            fetcher.get_bytes(url, 10)
        with pytest.raises(ForbiddenHostError):
            fetcher.download(url, tmp_path / "x", 10)
    assert not (tmp_path / "x").exists()


def test_enabling_a_source_opens_only_its_own_hosts() -> None:
    config = base_config()
    declared = replace(config.source("binance"), enabled=True, candle_allowance_ms=1000.0)
    binance_only = replace(config, sources={**config.sources, "binance": declared})
    assert binance_only.enabled_sources() == ("binance",)
    assert binance_only.enabled_hosts() == {"data.binance.vision"}
    bybit_only = replace(
        config, sources={**config.sources, "bybit": replace(config.source("bybit"), enabled=True)}
    )
    assert bybit_only.enabled_sources() == ("bybit",)
    assert bybit_only.enabled_hosts() == {"public.bybit.com", "quote-saver.bycsi.com"}


def test_a_client_cannot_exceed_the_fixed_allowlist() -> None:
    fetcher = HttpFetcher(base_config().fetch, allowed_hosts=frozenset({"example.com"}))
    with pytest.raises(ForbiddenHostError):
        fetcher.get_bytes("https://example.com/x", 10)


def test_the_http_client_refuses_before_touching_the_network(tmp_path: Path) -> None:
    fetcher = HttpFetcher(base_config().fetch, allowed_hosts=ALLOWED_HOSTS)
    with pytest.raises(ForbiddenHostError):
        fetcher.get_bytes("https://api.binance.com/x", 10)
    with pytest.raises(ForbiddenHostError):
        fetcher.download("https://api.binance.com/x", tmp_path / "x", 10)
    assert not (tmp_path / "x").exists()


_ORDER_WORDS = re.compile(
    r"place_order|create_order|new_order|cancel_order|submit_order|add_?order|AddOrder|"
    r"/private/|api[_-]?secret|api[_-]?key|hmac|X-MBX-APIKEY|API-Sign",
    re.IGNORECASE,
)


def test_no_source_file_mentions_order_placement_or_credentials() -> None:
    offenders = [p.name for p in PY_FILES if _ORDER_WORDS.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_nothing_in_the_source_sends_a_request_body_or_another_method() -> None:
    """The HTTP client is the only network code, and it only issues GET with no body."""
    network_modules = {
        "socket",
        "http.client",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "ftplib",
        "smtplib",
    }
    for path in PY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & network_modules, path
            if isinstance(node, ast.ImportFrom):
                # N-09: the one exception type a broken response raises, named so it can be caught exactly.
                names = {alias.name for alias in node.names}
                allowed = (
                    node.module == "http.client" and names == {"HTTPException"} and path.name == "fetch.py"
                )
                assert allowed or node.module not in network_modules, path
            if isinstance(node, ast.keyword) and node.arg == "method":
                assert isinstance(node.value, ast.Constant), path
                assert node.value.value == "GET", path
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Request":
                assert not any(keyword.arg == "data" for keyword in node.keywords), path


_URL_LIKE = re.compile(r"://|\burl\b|\bhttps?\b", re.IGNORECASE)


def polars_url_reads(tree: ast.AST) -> list[str]:
    """Polars readers open their own sockets in Rust, below the audit hook, so a URL must never reach one."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        reader = node.func.attr
        if not reader.startswith(("read_", "scan_")):
            continue
        owner = ast.unparse(node.func.value)
        if owner not in ("pl", "polars"):
            continue
        given = [*node.args, *[item.value for item in node.keywords]]
        if any(_URL_LIKE.search(ast.unparse(item)) for item in given):
            found.append(reader)
    return found


def test_the_polars_url_scan_finds_what_it_is_looking_for() -> None:
    bad = ast.parse("pl.read_parquet('https://x/y')\npl.scan_csv(url)\npolars.read_csv(f'http://{x}')\n")
    assert polars_url_reads(bad) == ["read_parquet", "scan_csv", "read_csv"]
    good = ast.parse("pl.read_parquet(path)\npl.read_csv(io.BytesIO(data))\nframe.read_x('https://y')\n")
    assert polars_url_reads(good) == []


def test_no_url_is_passed_to_a_polars_reader() -> None:
    """N-06. This is the one route below the guard in tests/child_guard."""
    files = [*PY_FILES, *sorted((REPO_ROOT / "tests").rglob("*.py"))]
    bad = {
        path.name: polars_url_reads(ast.parse(path.read_text(encoding="utf-8")))
        for path in files
        if path.name != "test_safety.py" and polars_url_reads(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert bad == {}


def test_no_shipped_file_says_a_placeholder_is_frozen() -> None:
    """Item 7 of the leak recheck. Both sentences were false: D-18 freezes nothing, and the roadmap has it
    pending."""
    roots = [REPO_ROOT / "src", REPO_ROOT / "configs", REPO_ROOT / ".github"]
    false_words = re.compile(r"frozen under decision D-18|stays frozen at", re.IGNORECASE)
    bad = [
        path.name
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and false_words.search(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert bad == []
    assert "not frozen" in (REPO_ROOT / "configs" / "pipeline.toml").read_text(encoding="utf-8")


def test_urllib_is_used_only_by_the_fetch_module() -> None:
    users = [
        p.name
        for p in PY_FILES
        if re.search(r"urllib\.request", p.read_text(encoding="utf-8")) and p.name != "fetch.py"
    ]
    assert users == []


def _tracked_files() -> list[Path]:
    done = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    return [REPO_ROOT / line for line in done.stdout.splitlines() if line]


def test_no_market_data_can_be_committed() -> None:
    forbidden = (".parquet", ".csv.gz", ".data.zip", ".sqlite", ".feather", ".arrow", ".zst")
    bad = [p.name for p in _tracked_files() if p.name.endswith(forbidden)]
    assert bad == []


def test_no_large_files_can_be_committed() -> None:
    large = [p.name for p in _tracked_files() if p.is_file() and p.stat().st_size > 1_000_000]
    assert large == []


def test_all_source_and_test_code_is_visible_to_git() -> None:
    """A broad ignore rule once hid the whole data package, so it was missing from what was pushed."""
    code = sorted((REPO_ROOT / "src").rglob("*.py")) + sorted((REPO_ROOT / "tests").rglob("*.py"))
    assert len(code) > 20
    done = subprocess.run(
        ["git", "check-ignore", *[str(path.relative_to(REPO_ROOT)) for path in code]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.split() == []


def test_generated_output_is_ignored_by_git() -> None:
    done = subprocess.run(
        ["git", "check-ignore", "site/index.html", "status.json", ".venv/x", "x.parquet"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.split() == ["site/index.html", "status.json", ".venv/x", "x.parquet"]


_LOCAL_PATH = re.compile(r"[A-Za-z]:\\Users\\|/home/[a-z]+/|/Users/[a-z]+/|AppData")


def test_no_local_paths_in_tracked_files_written_for_this_system() -> None:
    roots = ("src", "tests", "configs", ".github", "pyproject.toml")
    bad = []
    for path in _tracked_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if path.is_file() and relative.startswith(roots) and path.name != "test_safety.py":
            text = path.read_text(encoding="utf-8", errors="replace")
            if _LOCAL_PATH.search(text):
                bad.append(relative)
    assert bad == []
