"""HTTP reads from public hosts only.

There is deliberately no way to send a request body, a header carrying a credential, or any method but
GET. Exchange order endpoints live on hosts that are not on this list, and an allowlist check runs on
every request and on every redirect.
"""

from __future__ import annotations

import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from http.client import HTTPException
from pathlib import Path
from typing import Protocol

from hft_crypto import __version__
from hft_crypto.config import APPROVED_ROUTES, FetchConfig, is_prohibited_host

# The outer limit, whatever a configuration says. A prohibited host is refused separately, and first. A host
# with an approved route is open only along that route.
ALLOWED_HOSTS = frozenset(
    {
        "data.binance.vision",
        "public.bybit.com",
        "quote-saver.bycsi.com",
    }
)
_USER_AGENT = f"hft-crypto/{__version__} (public research data pipeline)"
_CHUNK = 1024 * 1024

# What kind of failure a FetchError is, as one fixed word. It never holds text from the host or a file, so
# the coverage check may print it (leak recheck, section 17.6).
REASON_HTTP_403 = "http_403"
REASON_HTTP_451 = "http_451"
REASON_HTTP_429 = "http_429"
REASON_TIMEOUT = "timeout"
# Every other failure of the transfer, after its attempts: a refused or reset connection, a failed lookup, a
# short or broken response, or an HTTP status not named here.
REASON_CONNECTION = "connection"
REASON_SIZE_LIMIT = "size_limit"
REASON_NOT_FOUND = "not_found"
# The host's own answers that stop at once and are never retried. Coverage record, section 4.2: stop on a 403
# or a 429 rather than retry around it. A 451 is the host's refusal too.
_STOP_AT_ONCE = {403: REASON_HTTP_403, 429: REASON_HTTP_429, 451: REASON_HTTP_451}


class FetchError(Exception):
    """A transient failure. The task stays open and a later run tries again. `reason` is one fixed word."""

    def __init__(self, message: str = "", *, reason: str = REASON_CONNECTION) -> None:
        super().__init__(message)
        self.reason = reason


class NotPublishedError(FetchError):
    """The host says this file does not exist yet. That is pending, not an error, until it is overdue."""

    def __init__(self, message: str = "", *, reason: str = REASON_NOT_FOUND) -> None:
        super().__init__(message, reason=reason)


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


def check_url(url: str, allowed: frozenset[str]) -> None:
    """Refuse anything but plain HTTPS to an allowed host. There is no way to widen this for a prohibited
    host."""
    if "\\" in url or any(ord(character) < 33 for character in url):
        raise ForbiddenHostError("refused URL: it holds a backslash, a space or a control character")
    parsed = urllib.parse.urlsplit(url)
    if "@" in parsed.netloc:
        raise ForbiddenHostError("refused URL: it names a user")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ForbiddenHostError("refused URL: bad port") from exc
    if port is not None:
        raise ForbiddenHostError("refused URL: it names a port")
    if is_prohibited_host(parsed.hostname):
        raise ForbiddenHostError(f"refused URL: {parsed.hostname} is prohibited")
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise ForbiddenHostError(f"refused URL: {parsed.scheme}://{parsed.hostname}")
    route = APPROVED_ROUTES.get(parsed.hostname)
    if route is not None and (parsed.query or parsed.fragment or not route.file_path.fullmatch(parsed.path)):
        raise ForbiddenHostError(
            f"refused URL: {parsed.path} is outside the approved route of {parsed.hostname}"
        )


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
                if exc.code in _STOP_AT_ONCE:
                    raise FetchError(
                        f"HTTP {exc.code} from {_host(url)}", reason=_STOP_AT_ONCE[exc.code]
                    ) from exc
                last_error = exc
            except (OSError, EOFError, ValueError, HTTPException) as exc:
                # A broken response, in each of the families it can come from. Anything else is a bug in our
                # own code, and must not read as a host failing.
                last_error = exc
        raise FetchError(f"{_host(url)}: {last_error}", reason=_reason_of(last_error)) from last_error

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        def action() -> int:
            total = 0
            with self._open(url) as response, dest.open("wb") as output:  # type: ignore[attr-defined]
                declared = response.headers.get("Content-Length")
                while chunk := response.read(_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(
                            f"{_host(url)}: response exceeds {max_bytes} bytes", reason=REASON_SIZE_LIMIT
                        )
                    output.write(chunk)
            if declared is not None and int(declared) != total:
                raise OSError(f"got {total} of {declared} bytes")
            return total

        return self._attempt(url, action)

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        def action() -> bytes:
            with self._open(url) as response:  # type: ignore[attr-defined]
                declared = response.headers.get("Content-Length")
                body: bytes = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FetchError(
                    f"{_host(url)}: response exceeds {max_bytes} bytes", reason=REASON_SIZE_LIMIT
                )
            if declared is not None and int(declared) != len(body):
                raise OSError(f"got {len(body)} of {declared} bytes")
            return body

        return self._attempt(url, action)


class PacedFetcher:
    """At least `min_gap_s` from the end of one request to the start of the next, for every request it passes.

    Coverage record, section 4.2: one connection, at least 2 seconds between requests. A zip and its sidecar
    are two requests. A request that failed was still a request, so the next one waits too. The client's own
    retries stay inside one call here, spaced by its backoff: no gap is added before a retry, and a backoff
    does not count towards the next gap, which runs from the moment the call returned or raised.
    """

    def __init__(
        self,
        inner: Fetcher,
        *,
        min_gap_s: float,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """min_gap_s has no default on purpose: the caller names the pace. The clock must be monotonic.
        `perf_counter` is, and on Windows it resolves to 100 ns, where `monotonic` steps by about 16 ms."""
        if not 0.0 < min_gap_s < math.inf:
            raise ValueError("min_gap_s must be a positive, finite number of seconds")
        self._inner = inner
        self._min_gap_s = min_gap_s
        self._clock = clock
        self._sleep = sleep
        self._last_end: float | None = None

    @property
    def inner(self) -> Fetcher:
        return self._inner

    @property
    def min_gap_s(self) -> float:
        return self._min_gap_s

    def _paced[T](self, request: Callable[[], T]) -> T:
        if self._last_end is not None:
            # Again until the clock shows the whole gap, since a sleep can end a little early.
            while (left := self._min_gap_s - (self._clock() - self._last_end)) > 0:
                self._sleep(left)
        try:
            return request()
        finally:
            self._last_end = self._clock()

    def download(self, url: str, dest: Path, max_bytes: int) -> int:
        return self._paced(lambda: self._inner.download(url, dest, max_bytes))

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        return self._paced(lambda: self._inner.get_bytes(url, max_bytes))


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or "unknown host"


def _reason_of(error: Exception | None) -> str:
    """`timeout` for a timed-out connect or read, and `connection` for every other failed transfer."""
    if isinstance(error, TimeoutError):
        return REASON_TIMEOUT
    if isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError):
        return REASON_TIMEOUT
    return REASON_CONNECTION
