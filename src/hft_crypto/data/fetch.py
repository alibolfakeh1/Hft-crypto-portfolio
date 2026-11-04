"""HTTP reads from public hosts only.

There is deliberately no way to send a request body, a header carrying a credential, or any method but
GET. Exchange order endpoints live on hosts that are not on this list, and an allowlist check runs on
every request and on every redirect.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from hft_crypto import __version__
from hft_crypto.config import FetchConfig

ALLOWED_HOSTS = frozenset(
    {
        "data.binance.vision",
        "public.bybit.com",
        "quote-saver.bycsi.com",
        "api.kraken.com",
    }
)
_USER_AGENT = f"hft-crypto/{__version__} (public research data pipeline)"
_CHUNK = 1024 * 1024


class FetchError(Exception):
    """A transient failure. The task stays open and a later run tries again."""


class NotPublishedError(FetchError):
    """The host says this file does not exist yet. That is pending, not an error, until it is overdue."""


class ForbiddenHostError(Exception):
    """A URL or a redirect points at a host that is not on the allowlist."""


class Fetcher(Protocol):
    """What the pipeline needs from a network client. Tests supply a fake one."""

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        """Stream a URL to a file and return the byte count."""
        ...

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        """Fetch a small response into memory."""
        ...


def check_url(url: str, allowed: frozenset[str] = ALLOWED_HOSTS) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise ForbiddenHostError(f"refused URL: {parsed.scheme}://{parsed.hostname}")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        check_url(newurl, self._allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


class HttpFetcher:
    """GET with bounded retries and an allowlist. Only HTTPS to known public hosts."""

    def __init__(
        self,
        config: FetchConfig,
        *,
        allowed_hosts: frozenset[str],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """allowed_hosts has no default on purpose: it comes from the sources enabled in configuration."""
        self._config = config
        self._sleep = sleep
        self._allowed = allowed_hosts & ALLOWED_HOSTS
        self._opener = urllib.request.build_opener(_CheckedRedirects(self._allowed))

    def _open(self, url: str) -> object:
        check_url(url, self._allowed)
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")  # noqa: S310
        return self._opener.open(request, timeout=self._config.timeout_s)

    def _attempt[T](self, url: str, action: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(self._config.attempts):
            if attempt:
                self._sleep(self._config.backoff_s * (2 ** (attempt - 1)))
            try:
                return action()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise NotPublishedError(url) from exc
                if exc.code in (403, 451):
                    raise FetchError(f"HTTP {exc.code} from {_host(url)}") from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
        raise FetchError(f"{_host(url)}: {last_error}") from last_error

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        def action() -> int:
            total = 0
            with self._open(url) as response, dest.open("wb") as output:  # type: ignore[attr-defined]
                declared = response.headers.get("Content-Length")
                while chunk := response.read(_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(f"{_host(url)}: response exceeds {max_bytes} bytes")
                    output.write(chunk)
            if declared is not None and int(declared) != total:
                raise FetchError(f"{_host(url)}: got {total} of {declared} bytes")
            return total

        return self._attempt(url, action)

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        def action() -> bytes:
            with self._open(url) as response:  # type: ignore[attr-defined]
                body: bytes = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FetchError(f"{_host(url)}: response exceeds {max_bytes} bytes")
            return body

        return self._attempt(url, action)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "unknown host"
