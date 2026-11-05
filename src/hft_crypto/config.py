"""Versioned configuration, read from TOML files under configs/."""

from __future__ import annotations

import datetime as dt
import os
import re
import tomllib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from hft_crypto.timeutil import day_start_us, parse_date
from hft_crypto.versioning import stable_hash


class ConfigError(ValueError):
    """The configuration is missing, malformed or breaks a hard rule."""


Granularity = Literal["day", "month"]
Continuity = Literal["trade_id", "none"]
BarSource = Literal["trades", "official_1m"]
CandleCheck = Literal["not_shown", "shown"]
NO_APPROVED_SOURCE = "no approved source configured"
# Fold plan section 3: nothing reads a date after this one. It holds in code, so no configuration file or
# environment variable can move it. Opening a block is the owner's written decision: a new entry in the log
# and a change here, and a test compares the two.
LAST_OPENED_DATE = dt.date(2023, 12, 31)
LAST_OPENED_DECISION = "D-34"
UNDECLARED = "UNDECLARED"
# Decision D-23. These hold in code, so no configuration file, environment variable or copied URL can reach
# them.
PROHIBITED_SOURCES = frozenset({"kraken"})
# Whole domains, and everything under them. Only an approved route below opens one door in one of them.
PROHIBITED_HOSTS = frozenset(
    {"binance.vision", "binance.com", "binance.us", "binancefuture.com", "kraken.com"}
)
STAMP_KINDS = frozenset({"exact", "aggregate_one_price", "taker_many_prices", "floored", "batched"})
# Only these row shapes keep every price in a bar from before its close. See the leak audit, ruling 2.
IDEAL_STAMP_KINDS = frozenset({"exact", "aggregate_one_price"})
ACCEPTED_ALLOWANCE_STATES = frozenset({"placeholder", "measured"})
# A deferral moves a row one bar, so an allowance of a minute or more would settle wrongly (DR-07).
MAX_FILL_SPAN_ALLOWANCE_MS = 60_000.0


@dataclass(frozen=True)
class ApprovedRoute:
    """One source's only way into a prohibited domain: one host, and only files under one path."""

    source: str
    path_prefix: str
    file_path: re.Pattern[str]


# Decision D-29: for non-commercial research, Binance Vision's USD-M perpetual archive and nothing else there.
# No other Binance host, and no spot, coin-margined or option path. A dated future has an underscore in its
# symbol, so its files do not match either.
APPROVED_ROUTES = {
    "data.binance.vision": ApprovedRoute(
        source="binance",
        path_prefix="/data/futures/um",
        file_path=re.compile(
            r"/data/futures/um/(?:daily|monthly)/[A-Za-z]+/[A-Z0-9]+(?:/[0-9a-z]+)?/[A-Z0-9]+-[A-Za-z0-9-]+"
            r"\.zip(?:\.CHECKSUM)?"
        ),
    )
}
# D-29: its terms cover the archive for research. They bar live proprietary execution and signals for
# compensation, and nothing here has read its API terms, so no live path may read from it.
ARCHIVE_ONLY_SOURCES = frozenset({"binance"})


def is_prohibited_host(host: str | None) -> bool:
    """True for a prohibited domain or anything under it, however it is written. An approved route's host is
    open."""
    if not host:
        return False
    name = host.lower().rstrip(".")
    if host in APPROVED_ROUTES:
        return False
    return any(name == banned or name.endswith(f".{banned}") for banned in PROHIBITED_HOSTS)


def route_problem(source: str, url: str) -> str | None:
    """Why this source may not use this address, or None. It is checked at load and again when a source is
    used."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if is_prohibited_host(host):
        return f"{host} is prohibited by a recorded decision"
    route = APPROVED_ROUTES.get(host or "")
    if route is None:
        return None
    if source != route.source:
        return f"{host} is open only to source {route.source}"
    path = parts.path.rstrip("/")
    walks_out = ".." in path or "%" in path or parts.query or parts.fragment
    if walks_out or (path != route.path_prefix and not path.startswith(f"{route.path_prefix}/")):
        return f"{parts.path} is outside the approved route {route.path_prefix} of {host}"
    return None


@dataclass(frozen=True)
class SourceSpec:
    """One place data may come from. Nothing is downloaded from it unless it is enabled."""

    name: str
    enabled: bool
    prohibited: bool
    urls: dict[str, str]
    terms_note: str
    stamp_kind: str
    fill_span_allowance_ms: float
    allowance_state: str
    continuity: Continuity
    bar_source: BarSource = "trades"
    # Goes on everything published from this source's data, where its terms ask for that.
    attribution: str = ""
    # When an allowance is declared measured: the dates, the stressed days among them, and who signed.
    allowance_evidence: str = ""
    # Ruling 7: how long after its close an official candle is final. Its own key, since
    # fill_span_allowance_ms describes trade rows. None until project-manager declares it, and a source cannot
    # be enabled until then.
    candle_allowance_ms: float | None = None
    # declared, as D-33 says, or measured. An archive gives no receipt time, so it is not measured yet.
    candle_allowance_state: str = "declared"
    # Ruling 7 condition 2: whether a candle holding no print from after its close has been shown, on declared
    # sample days outside any test block. This is what IDEAL rests on for these bars.
    candle_check: CandleCheck = "not_shown"
    candle_check_evidence: str = ""

    def hosts(self) -> frozenset[str]:
        return frozenset(
            host for host in (urllib.parse.urlsplit(url).hostname for url in self.urls.values()) if host
        )

    @property
    def fill_span_allowance_us(self) -> int:
        return round(self.fill_span_allowance_ms * 1000)

    @property
    def official_bars(self) -> bool:
        return self.bar_source == "official_1m"

    @property
    def candle_allowance_us(self) -> int:
        if self.candle_allowance_ms is None:
            raise ConfigError(f"source {self.name}: candle_allowance_ms is not declared")
        return round(self.candle_allowance_ms * 1000)

    @property
    def bar_allowance_us(self) -> int:
        """How long after a close this source's bars are knowable."""
        return self.candle_allowance_us if self.official_bars else self.fill_span_allowance_us

    @property
    def ideal_allowed(self) -> bool:
        if self.official_bars:
            # The trade rows' state is the wrong test for these bars (ruling 7 condition 7).
            return self.candle_check == "shown"
        # An allowance nobody has measured cannot say what had printed by a close.
        return self.stamp_kind in IDEAL_STAMP_KINDS and self.allowance_state == "measured"

    def route_problems(self) -> list[str]:
        return [problem for url in self.urls.values() if (problem := route_problem(self.name, url))]

    def use_problems(self) -> list[str]:
        """Why this source cannot be used, apart from its switches."""
        problems = self.route_problems()
        if self.official_bars and self.candle_allowance_ms is None:
            problems.append("candle_allowance_ms is not declared, and project-manager declares it")
        return problems


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    venue: str
    adapter: str
    kind: str
    curated: str
    tier: str
    granularity: Granularity
    start: dt.date
    overdue_hours: float
    light: bool
    opt_in: bool
    priority: int
    live_eligible: bool
    max_quiet_s: float | None


@dataclass(frozen=True)
class ReconTolerance:
    daily_total_abs: float
    bar_price_rel: float
    fill_count_rel: float


@dataclass(frozen=True)
class PollPair:
    symbol: str
    pair: str
    archive_symbol: str


@dataclass(frozen=True)
class PollConfig:
    venue: str
    base_url: str
    start_date: dt.date
    page_size: int
    min_interval_s: float
    allowance_a_s: float
    nominal_minute: int
    timeout_s: float
    attempts: int
    default_time_budget_s: float
    missed_slots_alert: int
    default_quota_gb: float
    pairs: tuple[PollPair, ...]
    median_abs_close_diff_bps_warn: float
    min_return_corr_warn: float


@dataclass(frozen=True)
class FetchConfig:
    timeout_s: float
    attempts: int
    backoff_s: float
    max_download_bytes: int
    max_uncompressed_bytes: int


@dataclass(frozen=True)
class ReportConfig:
    stale_after_hours: float
    equity_timeframe_minutes: int
    benchmark_venue: str | None
    benchmark_symbols: tuple[str, ...]
    # Declared in advance and common to all symbols, so that no fault can decide where a benchmark starts.
    span_start: dt.date


@dataclass(frozen=True)
class PipelineConfig:
    symbols: tuple[str, ...]
    timeframes_minutes: tuple[int, ...]
    default_quota_gb: float
    persisted_zones: tuple[str, ...]
    sources: dict[str, SourceSpec]
    bybit_book_depths: tuple[int, ...]
    fetch: FetchConfig
    routine_window_days: int
    retry_base_minutes: float
    retry_max_hours: float
    max_book_days_per_run: int
    book_depth_allowance_s: float
    max_future_skew_s: float
    reconcile: dict[str, ReconTolerance]
    datasets: tuple[DatasetSpec, ...]
    poll: PollConfig
    report: ReportConfig
    config_hash: str = field(default="")
    # Only code can change this, and only a test builds one that differs. No key in a file reaches it.
    last_opened_date: dt.date = LAST_OPENED_DATE

    @property
    def opened_through_us(self) -> int:
        """24:00 on the last opened date. The bar closing then is the last one readable."""
        return day_start_us(self.last_opened_date + dt.timedelta(days=1))

    def source(self, name: str) -> SourceSpec:
        try:
            return self.sources[name]
        except KeyError as exc:
            raise ConfigError(f"unknown source: {name}") from exc

    def source_usable(self, name: str) -> bool:
        """Enabled, not prohibited, and only on its approved route. A second check, kept after loading."""
        source = self.sources.get(name)
        if source is None or not source.enabled or source.prohibited or name in PROHIBITED_SOURCES:
            return False
        return not source.use_problems()

    def enabled_sources(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in self.sources if self.source_usable(name)))

    def enabled_hosts(self) -> frozenset[str]:
        """The only hosts the network client may contact. Empty until a source is approved."""
        hosts: set[str] = set()
        for name in self.enabled_sources():
            hosts |= self.sources[name].hosts()
        return frozenset(hosts)

    def source_state(self) -> str:
        enabled = self.enabled_sources()
        return ", ".join(enabled) if enabled else NO_APPROVED_SOURCE

    def dataset_enabled(self, spec: DatasetSpec) -> bool:
        return self.source_usable(spec.venue)

    def has_official_candles(self, venue: str) -> bool:
        return any(spec.venue == venue and spec.curated == "candles_official" for spec in self.datasets)

    def dataset(self, dataset_id: str) -> DatasetSpec:
        for spec in self.datasets:
            if spec.id == dataset_id:
                return spec
        raise ConfigError(f"unknown dataset: {dataset_id}")


@dataclass(frozen=True)
class RetentionRule:
    id: str
    zone: str
    kinds: tuple[str, ...]
    min_age_days: float
    reviewed: bool
    requires: dict[str, tuple[tuple[str, frozenset[str]], ...]]
    watermark_bypass_pct: float | None = None
    watermark_min_age_days: float = 0.0
    unpublished_only: bool = False
    rebuildable_from_archive: bool = False


@dataclass(frozen=True)
class Watermarks:
    warn_pct: float
    stop_backfill_pct: float
    purge_raw_pct: float
    purge_runs_pct: float
    critical_pct: float
    headroom_alert_days: float


@dataclass(frozen=True)
class SampleDays:
    day_of_month: int
    kinds: tuple[str, ...]
    protect_raw: bool


@dataclass(frozen=True)
class RetentionPolicy:
    policy_version: str
    watermarks: Watermarks
    sample_days: SampleDays
    rules: tuple[RetentionRule, ...]
    config_hash: str = field(default="")

    def rule(self, rule_id: str) -> RetentionRule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise ConfigError(f"unknown retention rule: {rule_id}")


# Zones no retention rule may ever select, whatever a configuration file says.
FORBIDDEN_RETENTION_ZONES = ("ledger", "decisions", "catalog")
# Zones holding data that only exists because we recorded it.
IRREPLACEABLE_ZONES = ("raw/live", "ledger", "decisions")


def find_config_dir(explicit: str | Path | None = None) -> Path:
    """Locate configs/: explicit argument, then HFT_CONFIG_DIR, then the repository's own."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("HFT_CONFIG_DIR")
    if env_value:
        candidates.append(Path(env_value))
    # Not the working directory: a stray configs/ folder must not be picked up by accident.
    candidates.append(Path(__file__).resolve().parents[2] / "configs")
    for candidate in candidates:
        if (candidate / "pipeline.toml").is_file():
            return candidate
    raise ConfigError("cannot find configs/pipeline.toml. Pass --config-dir or set HFT_CONFIG_DIR.")


def _check_keys(raw: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    """A misspelt key would otherwise read as its default, and a default can be the unsafe value."""
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown keys {unknown}")


def _bool_key(raw: dict[str, Any], key: str, where: str, *, default: bool | None = None) -> bool:
    """Read a real TOML boolean. bool("false") is True, so a string here would silently mean the opposite."""
    if key not in raw:
        if default is None:
            raise ConfigError(f"{where}: {key} is required")
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: {key} must be true or false, not {value!r}")
    return value


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path.name}: {exc}") from exc


_DATASET_KEYS = frozenset(
    {
        "id",
        "venue",
        "adapter",
        "kind",
        "curated",
        "tier",
        "granularity",
        "start",
        "overdue_hours",
        "light",
        "opt_in",
        "priority",
        "live_eligible",
        "max_quiet_s",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "enabled",
        "prohibited",
        "terms_note",
        "stamp_kind",
        "fill_span_allowance_ms",
        "allowance_state",
        "continuity",
        "bar_source",
        "attribution",
        "allowance_evidence",
        "candle_allowance_ms",
        "candle_allowance_state",
        "candle_check",
        "candle_check_evidence",
        "archive_base",
        "trades_base",
        "book_base",
        "book_depths",
        "trades_url",
    }
)


def _dataset(raw: dict[str, Any]) -> DatasetSpec:
    where = f"dataset {raw.get('id')}"
    _check_keys(raw, _DATASET_KEYS, where)
    granularity = raw["granularity"]
    if granularity not in ("day", "month"):
        raise ConfigError(f"{where}: bad granularity {granularity}")
    quiet = raw["max_quiet_s"]
    return DatasetSpec(
        id=raw["id"],
        venue=raw["venue"],
        adapter=raw["adapter"],
        kind=raw["kind"],
        curated=raw["curated"],
        tier=raw["tier"],
        granularity=cast(Granularity, granularity),
        start=parse_date(raw["start"]),
        overdue_hours=float(raw["overdue_hours"]),
        light=_bool_key(raw, "light", where),
        opt_in=_bool_key(raw, "opt_in", where),
        priority=int(raw["priority"]),
        live_eligible=_bool_key(raw, "live_eligible", where),
        # Zero means this dataset has no trades to fall quiet, such as candles or funding.
        max_quiet_s=None if float(quiet) == 0.0 else float(quiet),
    )


def _source(name: str, raw: dict[str, Any]) -> SourceSpec:
    """Read one source. Anything unclear or misspelt is an error, because it must fail closed."""
    where = f"source {name}"
    _check_keys(raw, _SOURCE_KEYS, where)
    enabled = _bool_key(raw, "enabled", where)
    prohibited = _bool_key(raw, "prohibited", where)
    urls = {key: str(value) for key, value in raw.items() if key.endswith(("_base", "_url"))}
    bar_source = cast(BarSource, _choice(raw, "bar_source", frozenset({"trades", "official_1m"}), where))
    candle_allowance, candle_check = _candle_keys(raw, bar_source, where)
    source = SourceSpec(
        name=name,
        enabled=enabled,
        prohibited=prohibited,
        urls=urls,
        terms_note=str(raw["terms_note"]),
        stamp_kind=_choice(raw, "stamp_kind", STAMP_KINDS, where),
        fill_span_allowance_ms=_non_negative(raw, "fill_span_allowance_ms", where),
        allowance_state=_choice(raw, "allowance_state", ACCEPTED_ALLOWANCE_STATES, where),
        continuity=cast(Continuity, _choice(raw, "continuity", frozenset({"trade_id", "none"}), where)),
        bar_source=bar_source,
        attribution=str(raw.get("attribution", "")),
        allowance_evidence=str(raw.get("allowance_evidence", "")),
        candle_allowance_ms=candle_allowance,
        candle_allowance_state=str(raw.get("candle_allowance_state", "declared")),
        candle_check=candle_check,
        candle_check_evidence=str(raw.get("candle_check_evidence", "")),
    )
    if source.fill_span_allowance_ms >= MAX_FILL_SPAN_ALLOWANCE_MS:
        raise ConfigError(f"{where}: fill_span_allowance_ms must be under {MAX_FILL_SPAN_ALLOWANCE_MS:g}")
    if source.allowance_state == "measured" and not source.allowance_evidence.strip():
        raise ConfigError(f"{where}: a measured allowance must name its evidence in allowance_evidence")
    problems = source.route_problems()
    if name in PROHIBITED_SOURCES and not prohibited:
        raise ConfigError(f"{where} is prohibited by a recorded decision, and the flag cannot be removed")
    if problems and not prohibited:
        raise ConfigError(f"{where}: {problems[0]}")
    if enabled and (prohibited or problems or name in PROHIBITED_SOURCES):
        raise ConfigError(f"{where} is prohibited by a recorded decision and cannot be enabled")
    if enabled and source.use_problems():
        raise ConfigError(f"{where} cannot be enabled: {source.use_problems()[0]}")
    return source


def _candle_keys(raw: dict[str, Any], bar_source: BarSource, where: str) -> tuple[float | None, CandleCheck]:
    """Required with no default on a source whose bars are official candles, so nothing can read as
    declared."""
    if bar_source != "official_1m":
        return None, "not_shown"
    for key in ("candle_allowance_ms", "candle_allowance_state", "candle_check"):
        if key not in raw:
            raise ConfigError(f"{where}: bars from official candles need {key}")
    _choice(raw, "candle_allowance_state", frozenset({"declared", "measured"}), where)
    allowance: float | None = None
    if raw["candle_allowance_ms"] != UNDECLARED:
        allowance = _non_negative(raw, "candle_allowance_ms", where)
        if allowance >= MAX_FILL_SPAN_ALLOWANCE_MS:
            raise ConfigError(f"{where}: candle_allowance_ms must be under {MAX_FILL_SPAN_ALLOWANCE_MS:g}")
    check = cast(CandleCheck, _choice(raw, "candle_check", frozenset({"not_shown", "shown"}), where))
    if check == "shown" and not str(raw.get("candle_check_evidence", "")).strip():
        raise ConfigError(f"{where}: candle_check of shown must name its evidence in candle_check_evidence")
    return allowance, check


def _choice(raw: dict[str, Any], key: str, allowed: frozenset[str], where: str) -> str:
    value = raw.get(key)
    if value not in allowed:
        raise ConfigError(f"{where}: {key} must be one of {sorted(allowed)}, not {value!r}")
    return str(value)


def _non_negative(raw: dict[str, Any], key: str, where: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value < float("inf"):
        raise ConfigError(f"{where}: {key} must be a number at or above zero, not {value!r}")
    return float(value)


def _check_references(config: PipelineConfig) -> None:
    """Names that point at a source must point at a real one, and a report may use only an approved one."""
    for spec in config.datasets:
        if spec.venue not in config.sources:
            raise ConfigError(f"dataset {spec.id}: unknown source {spec.venue}")
        if spec.live_eligible and spec.venue in ARCHIVE_ONLY_SOURCES:
            raise ConfigError(f"dataset {spec.id}: its source is for archive research only, so no live read")
    if config.poll.venue not in config.sources:
        raise ConfigError(f"poll: unknown source {config.poll.venue}")
    if config.poll.venue in ARCHIVE_ONLY_SOURCES:
        raise ConfigError(f"poll: source {config.poll.venue} is for archive research only")
    for name, source in config.sources.items():
        if source.official_bars and not config.has_official_candles(name):
            raise ConfigError(f"source {name}: bars from official candles need a candle dataset")
        allowance = source.candle_allowance_ms
        if source.official_bars and allowance is not None and config.poll.allowance_a_s * 1000 < allowance:
            raise ConfigError(f"source {name}: the allowance A must cover its candle allowance")
    venue = config.report.benchmark_venue
    if venue is not None and not config.source_usable(venue):
        raise ConfigError(f"report: benchmark venue {venue} is not an enabled, approved source")
    window = config.source(config.poll.venue).fill_span_allowance_ms
    if config.poll.allowance_a_s * 1000 < window:
        raise ConfigError("poll: the allowance A must cover the source's declared fill span")


def load_pipeline_config(config_dir: str | Path | None = None) -> PipelineConfig:
    raw = _read_toml(find_config_dir(config_dir) / "pipeline.toml")
    try:
        poll = raw["poll"]
        sources = {name: _source(name, values) for name, values in raw["sources"].items()}
        timeframes = tuple(int(v) for v in raw["bars"]["timeframes_minutes"])
        for minutes in timeframes:
            if minutes < 2 or 1440 % minutes != 0:
                raise ConfigError(f"timeframe {minutes}m must be above 1m and divide a UTC day")
        minute = int(poll["nominal_minute"])
        config = PipelineConfig(
            symbols=tuple(raw["universe"]["symbols"]),
            timeframes_minutes=timeframes,
            default_quota_gb=float(raw["storage"]["default_quota_gb"]),
            persisted_zones=tuple(raw["storage"]["persisted_zones"]),
            sources=sources,
            bybit_book_depths=tuple(int(v) for v in raw["sources"]["bybit"]["book_depths"]),
            fetch=FetchConfig(
                timeout_s=float(raw["fetch"]["timeout_s"]),
                attempts=int(raw["fetch"]["attempts"]),
                backoff_s=float(raw["fetch"]["backoff_s"]),
                max_download_bytes=int(raw["fetch"]["max_download_bytes"]),
                max_uncompressed_bytes=int(raw["fetch"]["max_uncompressed_bytes"]),
            ),
            routine_window_days=int(raw["catchup"]["routine_window_days"]),
            retry_base_minutes=float(raw["catchup"]["retry_base_minutes"]),
            retry_max_hours=float(raw["catchup"]["retry_max_hours"]),
            max_book_days_per_run=int(raw["catchup"]["max_book_days_per_run"]),
            book_depth_allowance_s=float(raw["latency"]["book_depth_allowance_s"]),
            max_future_skew_s=float(raw["latency"]["max_future_skew_s"]),
            reconcile={
                symbol: ReconTolerance(
                    daily_total_abs=float(values["daily_total_abs"]),
                    bar_price_rel=float(values["bar_price_rel"]),
                    fill_count_rel=float(values["fill_count_rel"]),
                )
                for symbol, values in raw["reconcile"].items()
            },
            datasets=tuple(_dataset(item) for item in raw["datasets"]),
            poll=PollConfig(
                venue=poll["venue"],
                base_url=sources[poll["venue"]].urls["trades_url"],
                start_date=parse_date(poll["start_date"]),
                page_size=int(poll["page_size"]),
                min_interval_s=float(poll["min_interval_s"]),
                allowance_a_s=float(poll["allowance_a_s"]),
                nominal_minute=minute,
                timeout_s=float(poll["timeout_s"]),
                attempts=int(poll["attempts"]),
                default_time_budget_s=float(poll["default_time_budget_s"]),
                missed_slots_alert=int(poll["missed_slots_alert"]),
                default_quota_gb=float(poll["default_quota_gb"]),
                pairs=tuple(PollPair(p["symbol"], p["pair"], p["archive_symbol"]) for p in poll["pairs"]),
                median_abs_close_diff_bps_warn=float(poll["cross_venue"]["median_abs_close_diff_bps_warn"]),
                min_return_corr_warn=float(poll["cross_venue"]["min_return_corr_warn"]),
            ),
            report=ReportConfig(
                stale_after_hours=float(raw["report"]["stale_after_hours"]),
                equity_timeframe_minutes=int(raw["report"]["equity_timeframe_minutes"]),
                benchmark_venue=raw["report"]["benchmark_venue"] or None,
                benchmark_symbols=tuple(raw["report"]["benchmark_symbols"]),
                span_start=parse_date(raw["report"]["span_start"]),
            ),
            config_hash=stable_hash(raw),
        )
    except KeyError as exc:
        raise ConfigError(f"pipeline.toml is missing {exc}") from exc
    for symbol, values in raw["reconcile"].items():
        _check_keys(
            values, frozenset({"daily_total_abs", "bar_price_rel", "fill_count_rel"}), f"reconcile {symbol}"
        )
    _check_references(config)
    return config


def _parse_requires(raw: dict[str, Any]) -> dict[str, tuple[tuple[str, frozenset[str]], ...]]:
    parsed: dict[str, tuple[tuple[str, frozenset[str]], ...]] = {}
    for kind, entries in raw.items():
        items: list[tuple[str, frozenset[str]]] = []
        for entry in entries:
            derived, _, statuses = str(entry).partition(":")
            if not derived or not statuses:
                raise ConfigError(f"bad requires entry {entry!r}: use kind:status[,status]")
            items.append((derived, frozenset(statuses.split(","))))
        parsed[kind] = tuple(items)
    return parsed


_RULE_KEYS = frozenset(
    {
        "id",
        "zone",
        "kinds",
        "min_age_days",
        "reviewed",
        "reviewed_note",
        "requires",
        "watermark_bypass_pct",
        "watermark_min_age_days",
        "unpublished_only",
        "rebuildable_from_archive",
    }
)


def _rule(raw: dict[str, Any]) -> RetentionRule:
    rule_id = raw["id"]
    _check_keys(raw, _RULE_KEYS, f"rule {rule_id}")
    zone = str(raw["zone"]).strip("/")
    if any(zone == z or zone.startswith(f"{z}/") for z in FORBIDDEN_RETENTION_ZONES):
        raise ConfigError(f"rule {rule_id}: zone {zone} can never be selected for deletion")
    bypass = raw.get("watermark_bypass_pct")
    if bypass is not None and any(zone == z or zone.startswith(f"{z}/") for z in IRREPLACEABLE_ZONES):
        raise ConfigError(
            f"rule {rule_id}: IRREPLACEABLE data inside retention is never deleted at a watermark"
        )
    min_age = float(raw["min_age_days"])
    if min_age <= 0 and any(zone == z or zone.startswith(f"{z}/") for z in IRREPLACEABLE_ZONES):
        raise ConfigError(f"rule {rule_id}: IRREPLACEABLE data needs a retention period above zero")
    requires = _parse_requires(raw.get("requires", {}))
    if zone == "raw" or zone.startswith("raw/"):
        # Raw data goes only when its derived data passes, so each kind must say what that derived data is.
        for kind in raw["kinds"]:
            if kind not in requires and "*" not in requires:
                raise ConfigError(f"rule {rule_id}: raw kind {kind} has no derived-data requirement")
    return RetentionRule(
        id=rule_id,
        zone=zone,
        kinds=tuple(raw["kinds"]),
        min_age_days=min_age,
        reviewed=_bool_key(raw, "reviewed", f"rule {rule_id}", default=False),
        requires=requires,
        watermark_bypass_pct=None if bypass is None else float(bypass),
        watermark_min_age_days=float(raw.get("watermark_min_age_days", 0.0)),
        unpublished_only=_bool_key(raw, "unpublished_only", f"rule {rule_id}", default=False),
        rebuildable_from_archive=_bool_key(raw, "rebuildable_from_archive", f"rule {rule_id}", default=False),
    )


def parse_retention_policy(raw: dict[str, Any]) -> RetentionPolicy:
    try:
        marks = raw["watermarks"]
        sample = raw["sample_days"]
        return RetentionPolicy(
            policy_version=raw["policy_version"],
            watermarks=Watermarks(
                warn_pct=float(marks["warn_pct"]),
                stop_backfill_pct=float(marks["stop_backfill_pct"]),
                purge_raw_pct=float(marks["purge_raw_pct"]),
                purge_runs_pct=float(marks["purge_runs_pct"]),
                critical_pct=float(marks["critical_pct"]),
                headroom_alert_days=float(marks["headroom_alert_days"]),
            ),
            sample_days=SampleDays(
                day_of_month=int(sample["day_of_month"]),
                kinds=tuple(sample["kinds"]),
                protect_raw=bool(sample["protect_raw"]),
            ),
            rules=tuple(_rule(item) for item in raw.get("rules", [])),
            config_hash=stable_hash(raw),
        )
    except KeyError as exc:
        raise ConfigError(f"retention policy is missing {exc}") from exc


def load_retention_policy(config_dir: str | Path | None = None) -> RetentionPolicy:
    return parse_retention_policy(_read_toml(find_config_dir(config_dir) / "retention.toml"))


def quota_bytes(default_gb: float) -> int:
    """DATA_QUOTA_GB wins over the configured default."""
    env_value = os.environ.get("DATA_QUOTA_GB", "").strip()
    value = default_gb
    if env_value:
        try:
            value = float(env_value)
        except ValueError as exc:
            raise ConfigError(f"DATA_QUOTA_GB is not a number: {env_value!r}") from exc
    if value <= 0:
        raise ConfigError("the data quota must be above zero")
    return int(value * 1_000_000_000)
