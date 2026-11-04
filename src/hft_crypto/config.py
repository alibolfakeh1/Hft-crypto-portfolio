"""Versioned configuration, read from TOML files under configs/."""

from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from hft_crypto.timeutil import parse_date
from hft_crypto.versioning import stable_hash


class ConfigError(ValueError):
    """The configuration is missing, malformed or breaks a hard rule."""


Granularity = Literal["day", "month"]


@dataclass(frozen=True)
class DatasetSpec:
    id: str
    venue: str
    kind: str
    curated: str
    tier: str
    granularity: Granularity
    start: dt.date
    overdue_hours: float
    light: bool
    opt_in: bool
    priority: int
    terms_note: str


@dataclass(frozen=True)
class ReconTolerance:
    daily_total_abs: float
    boundary_window_ms: float
    bar_price_abs: float


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
    bar_grace_s: float
    default_time_budget_s: float
    missed_slots_alert: int
    default_quota_gb: float
    terms_note: str
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
    benchmark_venue: str
    benchmark_symbols: tuple[str, ...]


@dataclass(frozen=True)
class PipelineConfig:
    symbols: tuple[str, ...]
    timeframes_minutes: tuple[int, ...]
    default_quota_gb: float
    persisted_zones: tuple[str, ...]
    binance_base: str
    bybit_trades_base: str
    bybit_book_base: str
    bybit_book_depths: tuple[int, ...]
    fetch: FetchConfig
    routine_window_days: int
    retry_base_minutes: float
    retry_max_hours: float
    max_book_days_per_run: int
    book_depth_allowance_s: float
    reconcile: dict[str, ReconTolerance]
    datasets: tuple[DatasetSpec, ...]
    poll: PollConfig
    report: ReportConfig
    config_hash: str = field(default="")

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
    """Locate configs/: explicit argument, then HFT_CONFIG_DIR, then the working directory, then the repo."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("HFT_CONFIG_DIR")
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(Path.cwd() / "configs")
    candidates.append(Path(__file__).resolve().parents[2] / "configs")
    for candidate in candidates:
        if (candidate / "pipeline.toml").is_file():
            return candidate
    raise ConfigError("cannot find configs/pipeline.toml. Pass --config-dir or set HFT_CONFIG_DIR.")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path.name}: {exc}") from exc


def _dataset(raw: dict[str, Any]) -> DatasetSpec:
    granularity = raw["granularity"]
    if granularity not in ("day", "month"):
        raise ConfigError(f"dataset {raw['id']}: bad granularity {granularity}")
    return DatasetSpec(
        id=raw["id"],
        venue=raw["venue"],
        kind=raw["kind"],
        curated=raw["curated"],
        tier=raw["tier"],
        granularity=cast(Granularity, granularity),
        start=parse_date(raw["start"]),
        overdue_hours=float(raw["overdue_hours"]),
        light=bool(raw["light"]),
        opt_in=bool(raw["opt_in"]),
        priority=int(raw["priority"]),
        terms_note=raw["terms_note"],
    )


def load_pipeline_config(config_dir: str | Path | None = None) -> PipelineConfig:
    raw = _read_toml(find_config_dir(config_dir) / "pipeline.toml")
    try:
        poll = raw["poll"]
        timeframes = tuple(int(v) for v in raw["bars"]["timeframes_minutes"])
        for minutes in timeframes:
            if minutes < 2 or 1440 % minutes != 0:
                raise ConfigError(f"timeframe {minutes}m must be above 1m and divide a UTC day")
        return PipelineConfig(
            symbols=tuple(raw["universe"]["symbols"]),
            timeframes_minutes=timeframes,
            default_quota_gb=float(raw["storage"]["default_quota_gb"]),
            persisted_zones=tuple(raw["storage"]["persisted_zones"]),
            binance_base=raw["sources"]["binance_base"],
            bybit_trades_base=raw["sources"]["bybit_trades_base"],
            bybit_book_base=raw["sources"]["bybit_book_base"],
            bybit_book_depths=tuple(int(v) for v in raw["sources"]["bybit_book_depths"]),
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
            reconcile={
                symbol: ReconTolerance(
                    daily_total_abs=float(values["daily_total_abs"]),
                    boundary_window_ms=float(values["boundary_window_ms"]),
                    bar_price_abs=float(values["bar_price_abs"]),
                )
                for symbol, values in raw["reconcile"].items()
            },
            datasets=tuple(_dataset(item) for item in raw["datasets"]),
            poll=PollConfig(
                venue=poll["venue"],
                base_url=poll["base_url"],
                start_date=parse_date(poll["start_date"]),
                page_size=int(poll["page_size"]),
                min_interval_s=float(poll["min_interval_s"]),
                bar_grace_s=float(poll["bar_grace_s"]),
                default_time_budget_s=float(poll["default_time_budget_s"]),
                missed_slots_alert=int(poll["missed_slots_alert"]),
                default_quota_gb=float(poll["default_quota_gb"]),
                terms_note=poll["terms_note"],
                pairs=tuple(PollPair(p["symbol"], p["pair"], p["archive_symbol"]) for p in poll["pairs"]),
                median_abs_close_diff_bps_warn=float(poll["cross_venue"]["median_abs_close_diff_bps_warn"]),
                min_return_corr_warn=float(poll["cross_venue"]["min_return_corr_warn"]),
            ),
            report=ReportConfig(
                stale_after_hours=float(raw["report"]["stale_after_hours"]),
                equity_timeframe_minutes=int(raw["report"]["equity_timeframe_minutes"]),
                benchmark_venue=raw["report"]["benchmark_venue"],
                benchmark_symbols=tuple(raw["report"]["benchmark_symbols"]),
            ),
            config_hash=stable_hash(raw),
        )
    except KeyError as exc:
        raise ConfigError(f"pipeline.toml is missing {exc}") from exc


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


def _rule(raw: dict[str, Any]) -> RetentionRule:
    zone = str(raw["zone"]).strip("/")
    rule_id = raw["id"]
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
    return RetentionRule(
        id=rule_id,
        zone=zone,
        kinds=tuple(raw["kinds"]),
        min_age_days=min_age,
        reviewed=bool(raw.get("reviewed", False)),
        requires=_parse_requires(raw.get("requires", {})),
        watermark_bypass_pct=None if bypass is None else float(bypass),
        watermark_min_age_days=float(raw.get("watermark_min_age_days", 0.0)),
        unpublished_only=bool(raw.get("unpublished_only", False)),
        rebuildable_from_archive=bool(raw.get("rebuildable_from_archive", False)),
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
