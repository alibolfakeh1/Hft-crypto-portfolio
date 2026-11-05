"""The engine's own versioned configuration, read from a TOML file under configs/.

Every key is required, and an unknown key is an error, so a typo can never read as a default. In particular
`rt_bps`, `stop_slip_bps` and all three risk limits have no default anywhere in the code, so a run that does
not state them does not start. The candle allowance is the source's own required key, in the pipeline
configuration, and this file holds no second copy of it.
"""

from __future__ import annotations

import datetime as dt
import itertools
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hft_crypto.config import ConfigError
from hft_crypto.timeutil import day_start_us
from hft_crypto.versioning import stable_hash

DATA_KINDS = frozenset({"SYNTHETIC", "MARKET"})
TIERS = frozenset({"T0", "T1"})
MINUTE_SOURCES = frozenset({"bars_1m", "official_candles"})
FUNDING_MODES = frozenset({"absent", "required"})
VALUE_STATES = frozenset({"placeholder", "declared"})
LINE_SETS = frozenset({"all", "default_only"})
STRATEGY_IDS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")
_TOP_KEYS = frozenset({"schema_version", "run", "timing", "costs", "risk", "strategies", "ticks", "placebo"})
_RUN_KEYS = frozenset(
    {
        "data_kind",
        "venue",
        "symbols",
        "tier",
        "minute_source",
        "funding",
        "credit_line",
        "opened_blocks",
        "read_days",
        "lines",
    }
)
_TIMING_KEYS = frozenset({"latency_ms"})
_COST_KEYS = frozenset({"rt_bps", "slip_bps", "stop_slip_bps", "stop_slip_state", "target_fee_bps", "basis"})
_RISK_KEYS = frozenset({"state", "basis", "capital", "leverage_cap", "gross_cap", "per_trade_pct"})
_STRATEGY_KEYS = frozenset({"default_line", "default_state", "portfolio_line", "portfolio_state", "grid"})
_PLACEBO_KEYS = frozenset({"draws"})
# C15 declares this in advance, so a market run may not state another count. A generated run may, for tests.
DECLARED_PLACEBO_DRAWS = 200


def _table(raw: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: table {key} is required")
    return value


def _keys(raw: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown keys {unknown}")
    missing = sorted(allowed - set(raw))
    if missing:
        raise ConfigError(f"{where}: {', '.join(missing)} required, with no default")


def _number(raw: dict[str, Any], key: str, where: str, *, positive: bool = False) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{where}: {key} must be a number, not {value!r}")
    number = float(value)
    if number < 0 or (positive and number == 0):
        raise ConfigError(f"{where}: {key} is out of range: {value!r}")
    return number


def _text(raw: dict[str, Any], key: str, where: str, allowed: frozenset[str] | None = None) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: {key} must be text, not {value!r}")
    if allowed is not None and value not in allowed:
        raise ConfigError(f"{where}: {key} must be one of {sorted(allowed)}, not {value!r}")
    return value


@dataclass(frozen=True)
class CostConfig:
    """C9, C7 and C16, in basis points. Fractions come from the properties.

    `stop_slip` is not part of `RT`, so it prices stop exits and changes no setup, floor or trade list.
    """

    rt_bps: float
    slip_bps: float
    stop_slip_bps: float
    target_fee_bps: float
    basis: str
    stop_slip_state: str = "declared"

    @property
    def rt(self) -> float:
        return self.rt_bps / 10_000.0

    @property
    def slip(self) -> float:
        return self.slip_bps / 10_000.0

    @property
    def stop_slip(self) -> float:
        return self.stop_slip_bps / 10_000.0

    @property
    def fee_taker(self) -> float:
        """RT = 2 * (fee_taker + slip), read the other way round."""
        return self.rt / 2.0 - self.slip

    @property
    def target_fee(self) -> float:
        return self.target_fee_bps / 10_000.0

    def declared_values(self) -> dict[str, float]:
        """The values C12 requires in the trial registry before the first run."""
        return {
            "rt_bps": self.rt_bps,
            "slip_bps": self.slip_bps,
            "stop_slip_bps": self.stop_slip_bps,
            "target_fee_bps": self.target_fee_bps,
        }


@dataclass(frozen=True)
class RiskConfig:
    """Layer 5 inputs, decision D-28. Risk and leverage act per position, gross at the portfolio."""

    state: str
    basis: str
    capital: float
    leverage_cap: float
    gross_cap: float
    per_trade_pct: dict[str, dict[str, float]]

    def risk_budget(self, strategy: str, symbol: str) -> float:
        """Money at risk per trade: a fixed share of starting capital, not compounded."""
        try:
            return self.capital * self.per_trade_pct[strategy][symbol] / 100.0
        except KeyError as exc:
            raise ConfigError(f"no risk per trade is stated for {strategy} on {symbol}") from exc

    def as_output(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "basis": self.basis,
            "capital": self.capital,
            "risk_per_trade_pct": self.per_trade_pct,
            "leverage_cap_per_position": self.leverage_cap,
            "gross_exposure_cap_portfolio": self.gross_cap,
            "sizing": "Risk per trade is a share of starting capital and does not compound",
        }


def _line_id(params: dict[str, Any]) -> str:
    def text(value: Any) -> str:
        return "/".join(str(item) for item in value) if isinstance(value, list) else str(value)

    return ",".join(f"{key}={text(params[key])}" for key in sorted(params))


@dataclass(frozen=True)
class GridLine:
    """One configuration a document declares. The default is a display order, and never chosen by outcome."""

    strategy: str
    line_id: str
    params: dict[str, Any]
    is_default: bool
    in_portfolio: bool


@dataclass(frozen=True)
class StrategyGrid:
    strategy: str
    default_state: str
    default_line: dict[str, Any]
    grid: dict[str, list[Any]]
    # FP-05: the one line the portfolio figure uses. An input declared before a run, and never chosen by
    # outcome.
    portfolio_line: dict[str, Any] = field(default_factory=dict)
    portfolio_state: str = "placeholder"

    def lines(self) -> list[GridLine]:
        """The default first, as C18 shows it, and the others in a fixed grid order. Nothing here reads a
        result.
        """
        names = sorted(self.grid)
        default_id = _line_id(self.default_line)
        portfolio_id = _line_id(self.portfolio_line or self.default_line)
        rows: list[GridLine] = []
        for values in itertools.product(*(self.grid[name] for name in names)):
            params = dict(zip(names, values, strict=True))
            line_id = _line_id(params)
            rows.append(
                GridLine(self.strategy, line_id, params, line_id == default_id, line_id == portfolio_id)
            )
        rows.sort(key=lambda line: not line.is_default)
        return rows

    def default(self) -> GridLine:
        return self.lines()[0]


@dataclass(frozen=True)
class EngineConfig:
    data_kind: str
    venue: str
    symbols: tuple[str, ...]
    tier: str
    minute_source: str
    funding: str
    credit_line: str
    latency_us: int
    costs: CostConfig
    risk: RiskConfig
    ticks: dict[str, float]
    strategies: dict[str, StrategyGrid]
    opened_blocks: tuple[str, ...]
    read_days: tuple[dt.date, ...]
    line_set: str
    placebo_draws: int = DECLARED_PLACEBO_DRAWS
    config_hash: str = field(default="")

    def tick(self, symbol: str) -> float:
        try:
            return self.ticks[symbol]
        except KeyError as exc:
            raise ConfigError(f"no tick is stated for {symbol}") from exc

    def lines(self, strategy: str) -> list[GridLine]:
        try:
            grid = self.strategies[strategy]
        except KeyError as exc:
            raise ConfigError(f"no grid is stated for {strategy}") from exc
        if self.line_set == "all":
            return grid.lines()
        return [line for line in grid.lines() if line.is_default or line.in_portfolio]


@dataclass(frozen=True)
class DateRange:
    """The UTC days a run may read, both ends included. It is required, so nothing later can be read."""

    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ConfigError("the date range ends before it starts")

    @property
    def first_open_us(self) -> int:
        return day_start_us(self.start)

    @property
    def end_us(self) -> int:
        """Midnight at the end of the last day."""
        return day_start_us(self.end + dt.timedelta(days=1))

    def as_output(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def _strategy_grid(strategy: str, raw: dict[str, Any]) -> StrategyGrid:
    where = f"strategies.{strategy}"
    _keys(raw, _STRATEGY_KEYS, where)
    default = _table(raw, "default_line", where)
    grid = _table(raw, "grid", where)
    if "timeframe_minutes" not in grid:
        raise ConfigError(f"{where}: the grid must state timeframe_minutes")
    if set(default) != set(grid):
        raise ConfigError(f"{where}: default_line and grid must name the same parameters")
    for key, values in grid.items():
        if not isinstance(values, list) or not values:
            raise ConfigError(f"{where}: grid.{key} must be a list of values")
        if default[key] not in values:
            raise ConfigError(f"{where}: the default {key} is not on its grid")
    portfolio = _table(raw, "portfolio_line", where)
    if set(portfolio) != set(grid) or any(portfolio[key] not in grid[key] for key in grid):
        raise ConfigError(f"{where}: portfolio_line is not on the grid")
    return StrategyGrid(
        strategy,
        _text(raw, "default_state", where, VALUE_STATES),
        dict(default),
        dict(grid),
        dict(portfolio),
        _text(raw, "portfolio_state", where, VALUE_STATES),
    )


def parse_engine_config(raw: dict[str, Any]) -> EngineConfig:
    _keys(raw, _TOP_KEYS, "engine config")
    if raw["schema_version"] != 1:
        raise ConfigError(f"engine config: unknown schema version {raw['schema_version']!r}")

    run = _table(raw, "run", "engine config")
    _keys(run, _RUN_KEYS, "run")
    symbols = run["symbols"]
    if not isinstance(symbols, list) or not symbols or not all(isinstance(s, str) for s in symbols):
        raise ConfigError("run: symbols must be a list of names")
    opened = run["opened_blocks"]
    if not isinstance(opened, list) or not all(isinstance(item, str) for item in opened):
        raise ConfigError("run: opened_blocks must be a list of block names")
    read_days = run["read_days"]
    if not isinstance(read_days, list) or not all(isinstance(item, dt.date) for item in read_days):
        raise ConfigError("run: read_days must be a list of dates, and an empty list if there are none")

    timing = _table(raw, "timing", "engine config")
    _keys(timing, _TIMING_KEYS, "timing")

    cost = _table(raw, "costs", "engine config")
    _keys(cost, _COST_KEYS, "costs")
    costs = CostConfig(
        rt_bps=_number(cost, "rt_bps", "costs", positive=True),
        slip_bps=_number(cost, "slip_bps", "costs"),
        stop_slip_bps=_number(cost, "stop_slip_bps", "costs"),
        target_fee_bps=_number(cost, "target_fee_bps", "costs"),
        basis=_text(cost, "basis", "costs"),
        stop_slip_state=_text(cost, "stop_slip_state", "costs", VALUE_STATES),
    )
    if costs.fee_taker < 0:
        raise ConfigError("costs: slip_bps exceeds half of rt_bps, which leaves a negative taker fee")

    risk_raw = _table(raw, "risk", "engine config")
    _keys(risk_raw, _RISK_KEYS, "risk")
    per_trade = _table(risk_raw, "per_trade_pct", "risk")
    table: dict[str, dict[str, float]] = {}
    for strategy in STRATEGY_IDS:
        row = _table(per_trade, strategy, "risk.per_trade_pct")
        table[strategy] = {
            symbol: _number(row, symbol, f"risk.per_trade_pct.{strategy}", positive=True)
            for symbol in symbols
        }
    risk = RiskConfig(
        state=_text(risk_raw, "state", "risk", VALUE_STATES),
        basis=_text(risk_raw, "basis", "risk"),
        capital=_number(risk_raw, "capital", "risk", positive=True),
        leverage_cap=_number(risk_raw, "leverage_cap", "risk", positive=True),
        gross_cap=_number(risk_raw, "gross_cap", "risk", positive=True),
        per_trade_pct=table,
    )

    ticks_raw = _table(raw, "ticks", "engine config")
    ticks = {symbol: _number(ticks_raw, symbol, "ticks", positive=True) for symbol in symbols}
    strategies_raw = _table(raw, "strategies", "engine config")
    missing = sorted(set(STRATEGY_IDS) - set(strategies_raw))
    if missing:
        raise ConfigError(f"strategies: no grid for {missing}")
    strategies = {
        strategy: _strategy_grid(strategy, _table(strategies_raw, strategy, "strategies"))
        for strategy in STRATEGY_IDS
    }

    placebo = _table(raw, "placebo", "engine config")
    _keys(placebo, _PLACEBO_KEYS, "placebo")
    placebo_draws = placebo["draws"]
    if isinstance(placebo_draws, bool) or not isinstance(placebo_draws, int) or placebo_draws < 1:
        raise ConfigError(f"placebo: draws must be a whole number above zero, not {placebo_draws!r}")
    data_kind = _text(run, "data_kind", "run", DATA_KINDS)
    if data_kind == "MARKET":
        # D-35: the portfolio figure uses each strategy's C18 default line, so an edit cannot pick another.
        moved = [name for name, grid in strategies.items() if grid.portfolio_line != grid.default_line]
        if moved:
            raise ConfigError(
                f"D-35: on market data portfolio_line must be the default line, not so for {moved}"
            )
    if data_kind == "MARKET" and placebo_draws != DECLARED_PLACEBO_DRAWS:
        raise ConfigError(
            f"placebo: C15 declares {DECLARED_PLACEBO_DRAWS} draws, and a change is a new document version"
        )

    return EngineConfig(
        data_kind=data_kind,
        venue=_text(run, "venue", "run"),
        symbols=tuple(symbols),
        tier=_text(run, "tier", "run", TIERS),
        minute_source=_text(run, "minute_source", "run", MINUTE_SOURCES),
        funding=_text(run, "funding", "run", FUNDING_MODES),
        credit_line=_text(run, "credit_line", "run"),
        latency_us=round(_number(timing, "latency_ms", "timing") * 1000.0),
        costs=costs,
        risk=risk,
        ticks=ticks,
        strategies=strategies,
        opened_blocks=tuple(opened),
        read_days=tuple(read_days),
        line_set=_text(run, "lines", "run", LINE_SETS),
        placebo_draws=placebo_draws,
        config_hash=stable_hash(raw),
    )


def load_engine_config(path: str | Path) -> EngineConfig:
    try:
        with Path(path).open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read the engine configuration: {exc}") from exc
    return parse_engine_config(raw)
