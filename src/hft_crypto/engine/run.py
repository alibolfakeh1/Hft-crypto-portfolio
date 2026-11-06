"""One whole run: from a data root and a date range to JSON rows. Reads through `MarketReader` only.

**The range is required, and nothing outside it is opened.** The run first checks it against the blocks of the
fold plan that its configuration names as opened. See `read_cut` for how the file after the range stays shut.

**Every grid line runs, and none is picked.** The default line is an input, shown first. It is a display
order, and the portfolio uses it because a portfolio needs one line per strategy. Nothing here reads a result
to choose anything.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from hft_crypto.bars.core import UTC_TIME, TimingContractError
from hft_crypto.config import BarSource, ConfigError, PipelineConfig, SourceSpec, load_pipeline_config
from hft_crypto.data.atomic import atomic_write_json
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.guard import PathGuard
from hft_crypto.data.reader import MarketReader, RunClock
from hft_crypto.data.zones import DataRoot, DataRootError, resolve_data_root
from hft_crypto.engine.config import DateRange, EngineConfig, load_engine_config
from hft_crypto.engine.fold_plan import COUNTED_OUTSIDE_REGISTRY, check_range, span_labels
from hft_crypto.engine.funding import (
    FUNDING_INTERVAL_CHANGED,
    FundingRow,
    funding_schedule,
    interval_changes,
    missing_settlements,
)
from hft_crypto.engine.placebo import ControlLog, DrawStat, Plan, run_placebos
from hft_crypto.engine.registry import TrialRegistry, trial_row
from hft_crypto.engine.simulator import (
    MODE,
    VARIANT,
    FundingEvent,
    FundingIntervalChange,
    SimParams,
    Simulator,
    StreamResult,
    SymbolData,
)
from hft_crypto.engine.tape import MinuteTape, TradeTape
from hft_crypto.reports.placebo import not_requested_rows, placebo_rows
from hft_crypto.reports.portfolio import (
    OutputRows,
    build_axis,
    build_rows,
    output_header,
    row_label,
    stream_status,
)
from hft_crypto.reports.v0s import v0s_rows, v0s_trade_rows
from hft_crypto.strategies import available_strategies, build_strategy, strategy_class
from hft_crypto.strategies.v0s import VARIANT_V0S, V0SControl
from hft_crypto.synthetic import FIRST_DAY, SYNTHETIC_VENUE, synthetic_config
from hft_crypto.timeutil import day_start_us, iso, iso_us, utcnow
from hft_crypto.versioning import code_version, stable_hash

_FloatArray = npt.NDArray[np.float64]
# A stored row can take its knowable time from a later row. The as-of view handles that, so this bound only
# has to let such a row through the reader's check. It reads nothing further, because the cut-off holds.
_READ_SLACK_DAYS = 400


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    out_dir: Path
    labels: tuple[str, ...]
    streams: tuple[StreamResult, ...]
    rows: OutputRows
    header: dict[str, Any]
    placebo: tuple[dict[str, Any], ...] = ()


def _refuse_inside_repository(path: Path) -> None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            raise DataRootError("the output folder must be outside the repository, because it is public")


def resolve_source(root: DataRoot, pipeline: PipelineConfig, engine: EngineConfig) -> PipelineConfig:
    """Refuse a root with no approved source, as the data layer does, and a configuration for other data."""
    stored = None
    if root.catalog_path.is_file():
        catalog = Catalog(root.catalog_path)
        stored = catalog.get_meta("data_kind")
        catalog.close()
    if stored == "SYNTHETIC" and not root.is_synthetic:
        raise ConfigError("this root's catalog holds generated data and its SYNTHETIC marker is missing")
    if root.is_synthetic:
        if engine.data_kind != "SYNTHETIC":
            raise ConfigError("this root holds SYNTHETIC data, and the configuration is for market data")
        if engine.venue != SYNTHETIC_VENUE:
            raise ConfigError(f"a SYNTHETIC root has only the venue {SYNTHETIC_VENUE}")
        bar_source: BarSource = "official_1m" if engine.minute_source == "official_candles" else "trades"
        return synthetic_config(pipeline, first_day=FIRST_DAY, days=1, bar_source=bar_source)
    if engine.data_kind == "SYNTHETIC":
        raise ConfigError("this configuration is for generated runs, and this root is not generated")
    if not pipeline.enabled_sources():
        raise ConfigError(f"{pipeline.source_state()}, so this run is refused")
    if engine.venue not in pipeline.enabled_sources():
        raise ConfigError(f"the source {engine.venue} is not approved, so this run is refused")
    return pipeline


def required_allowance(source: SourceSpec, allowance_us: int) -> int:
    """The mode table's assertion, in one unit. On official candles this reads `A >= candle_allowance`.

    The value is the source's own required key. It raises while undeclared, so it has no default anywhere.
    """
    minimum = source.bar_allowance_us
    if allowance_us < minimum:
        raise TimingContractError("the mode table requires A to cover this source's allowance, in one unit")
    return minimum


def _inside_range(frame: pl.DataFrame, date_range: DateRange, column: str, what: str) -> None:
    """A second guard on the reader's own cut. A row outside the range is an error, never a quiet drop."""
    if frame.is_empty():
        return
    values = frame[column].dt.timestamp("us")
    first = int(str(values.min()))
    last = int(str(values.max()))
    if first < date_range.first_open_us or last >= date_range.end_us:
        raise TimingContractError(f"{what} came back from outside the run's date range")


def read_cut(date_range: DateRange, last_opened: dt.date) -> int:
    """The run's cut-off, one value for every read.

    The reader never opens a part past the last opened date, so a range ending on that date can cut at
    midnight, which reads every bar closing inside it. Any other range cuts a microsecond earlier, because
    trades and funding still read the part named by the cut's date, and that part is outside the range. Such
    a range gives up its last minute. No position feels it, since a setup reaching the range's end is left
    out under FP-07.
    """
    return date_range.end_us if date_range.end == last_opened else date_range.end_us - 1


def read_symbol(
    reader: MarketReader,
    engine: EngineConfig,
    symbol: str,
    date_range: DateRange,
    *,
    delay_us: int,
    last_opened: dt.date,
) -> SymbolData:
    """Everything this run will ever hold for one symbol, all of it inside the range."""
    cut = read_cut(date_range, last_opened)
    clock = RunClock(cut, cut + _READ_SLACK_DAYS * 86_400_000_000)
    since = date_range.start
    if engine.minute_source == "official_candles":
        minutes = reader.candles(engine.venue, symbol, clock, since=since)
    else:
        minutes = reader.bars(1, engine.venue, symbol, clock, since=since)
    if minutes.is_empty():
        raise ConfigError(f"no 1m rows for {symbol} in {date_range.start} to {date_range.end}")
    _inside_range(minutes, date_range, "open_time", "a 1m row")
    tape = MinuteTape.from_frame(minutes, symbol=symbol, delay_us=delay_us)
    trades: TradeTape | None = None
    if engine.tier == "T1":
        frame = reader.trades(engine.venue, symbol, clock, since=since)
        # A trade exactly on the first midnight belongs to the minute before the range.
        first = pl.lit(date_range.first_open_us, dtype=pl.Int64).cast(UTC_TIME)
        frame = frame.filter(pl.col("ts") > first) if not frame.is_empty() else frame
        _inside_range(frame, date_range, "ts", "a trade")
        trades = TradeTape.from_frame(frame)
    funding: tuple[FundingEvent, ...] = ()
    changes: tuple[FundingIntervalChange, ...] = ()
    if engine.funding == "required":
        rows = reader.funding(engine.venue, symbol, clock, since=since)
        if rows.is_empty():
            raise ConfigError(f"funding is required, and none was read for {symbol}")
        _inside_range(rows, date_range, "settle_time", "a funding row")
        ordered = rows.sort("settle_time")
        funding_rows = [
            FundingRow(int(when), float(rate), int(hours))
            for when, rate, hours in zip(
                ordered["settle_time"].dt.timestamp("us").to_list(),
                ordered["funding_rate"].to_list(),
                ordered["funding_interval_hours"].to_list(),
                strict=True,
            )
        ]
        funding = funding_schedule(
            funding_rows, first_open_us=date_range.first_open_us, end_us=date_range.end_us
        )
        changes = interval_changes(funding_rows)
    return SymbolData(tape, trades, funding, changes)


def _first_last(moments: tuple[int, ...]) -> list[str]:
    return [iso_us(moments[0]), iso_us(moments[-1])] if moments else []


def build_manifest(
    data: dict[str, SymbolData], engine: EngineConfig, date_range: DateRange
) -> dict[str, Any]:
    """What this run actually read, by content: the range, and a hash of each symbol's rows."""
    symbols: dict[str, Any] = {}
    for symbol in sorted(data):
        item = data[symbol]
        tape = item.tape
        symbols[symbol] = {
            "minute_rows": tape.size,
            "minute_rows_sha256": tape.digest(),
            "first_close": None if tape.size == 0 else int(tape.close_us[0]),
            "last_close": None if tape.size == 0 else int(tape.close_us[-1]),
            "flagged_gap_rows": int(tape.gap.sum()),
            "trade_rows": None if item.trades is None else int(item.trades.ts_us.size),
            "trade_rows_sha256": None if item.trades is None else item.trades.digest(),
            "funding_rows": sum(1 for event in item.funding if event.rate is not None),
            "funding_settlements_with_no_rate": len(missing_settlements(item.funding)),
            "funding_settlements_with_no_rate_first_last": _first_last(missing_settlements(item.funding)),
            # R-01: a stretch whose two rows state different intervals names no settlement, so it is listed.
            "funding_interval_changes": [
                {
                    "event": FUNDING_INTERVAL_CHANGED,
                    "from": iso_us(change.from_us),
                    "to": iso_us(change.to_us),
                    "interval_hours_before": change.hours_before,
                    "interval_hours_after": change.hours_after,
                }
                for change in item.funding_interval_changes
            ],
        }
    return {
        "venue": engine.venue,
        "minute_source": engine.minute_source,
        "tier": engine.tier,
        "date_range": date_range.as_output(),
        "symbols": symbols,
    }


def _sim_params(
    engine: EngineConfig,
    *,
    allowance_us: int,
    minimum_allowance_us: int,
    date_range: DateRange,
) -> Callable[[str, str], SimParams]:
    """The same parameters for a real stream and for its placebo, since C15 keeps configuration and mode."""
    read_days_us = tuple((day_start_us(day), day_start_us(day) + 86_400_000_000) for day in engine.read_days)

    def params_for(strategy_id: str, symbol: str) -> SimParams:
        return SimParams(
            costs=engine.costs,
            latency_us=engine.latency_us,
            allowance_us=allowance_us,
            fill_span_allowance_us=minimum_allowance_us,
            risk_budget=engine.risk.risk_budget(strategy_id, symbol),
            capital=engine.risk.capital,
            leverage_cap=engine.risk.leverage_cap,
            tick=engine.tick(symbol),
            span_end_us=date_range.end_us,
            read_days_us=read_days_us,
        )

    return params_for


def simulate_streams(
    engine: EngineConfig,
    data: dict[str, SymbolData],
    *,
    allowance_us: int,
    minimum_allowance_us: int,
    strategies: Sequence[str],
    date_range: DateRange,
    registry: TrialRegistry | None = None,
    manifest_hash: str = "",
    logged_at: str = "",
    version: str = "",
) -> list[StreamResult]:
    """Each grid line of each strategy on each symbol, in a fixed order, each registered before it starts."""
    streams: list[StreamResult] = []
    params_for = _sim_params(
        engine, allowance_us=allowance_us, minimum_allowance_us=minimum_allowance_us, date_range=date_range
    )
    for strategy_id in strategies:
        for line in engine.lines(strategy_id):
            for symbol in engine.symbols:
                item = data[symbol]
                strategy = build_strategy(strategy_id, line.params)
                row = None
                if registry is not None:
                    row = trial_row(
                        strategy=strategy_id,
                        line=line.line_id,
                        is_default=line.is_default,
                        in_portfolio=line.in_portfolio,
                        symbol=symbol,
                        params=line.params,
                        mode=MODE,
                        variant=VARIANT,
                        tier=engine.tier,
                        date_range=date_range.as_output(),
                        costs=engine.costs.declared_values(),
                        risk_state=engine.risk.state,
                        data_kind=engine.data_kind,
                        code_version=version,
                        config_hash=engine.config_hash,
                        manifest_hash=manifest_hash,
                        lines_counted=strategy.lines_on(engine.tier),
                    )
                    registry.started(row, logged_at=logged_at)
                result = Simulator(
                    strategy,
                    item.tape,
                    params_for(strategy_id, symbol),
                    trades=item.trades,
                    funding=item.funding,
                    line=line.line_id,
                    is_default=line.is_default,
                    in_portfolio=line.in_portfolio,
                ).run()
                streams.append(result)
                if registry is not None and row is not None:
                    registry.finished(
                        row,
                        logged_at=logged_at,
                        result={
                            "status": stream_status(result),
                            "setups": result.setups,
                            "trades": len(result.trades),
                        },
                    )
    return streams


def _modes(engine: EngineConfig) -> dict[str, str]:
    tier_note = f"{engine.tier}."
    if engine.tier == "T0":
        tier_note = (
            "T0. S07 and S08 need trades, so on candles they give no result, and nothing stands in for them."
        )
    return {
        MODE: "ran",
        "IDEAL": "not available. It stays off until condition 2 of ruling 7 is shown, so it has no result",
        "CYCLE": "not run. C-10 holds back every CYCLE run until the trade feed values are filled",
        "tier": tier_note,
        "selection": (
            "off. S02, S03, S04, S05, S09 and S10 cannot select on this stage, and C18's selection for S01 "
            "and S06 is not built. Every line is shown, and none is ranked"
        ),
    }


def _funding_note(
    engine: EngineConfig, missing: dict[str, int], changes: dict[str, int] | None = None
) -> str:
    if engine.funding == "absent":
        return "Funding is absent from this run: no funding was charged, so net figures leave it out"
    changed = ""
    if changes is not None and any(changes.values()):
        # R-01. Which period a row's interval describes is UNVERIFIED, so such a stretch names no settlement.
        changed = (
            f". At {sum(changes.values())} stretches the funding rows on either side state different "
            "intervals. No settlement is named missing inside one, because which period a row's interval "
            "describes is UNVERIFIED, so a position open across one may owe a settlement that is not "
            f"counted. Each is listed as {FUNDING_INTERVAL_CHANGED} in the manifest"
        )
    if any(missing.values()):
        return (
            "Funding is charged at actual settlement times, under C10. Some settlements have no rate, and "
            "none is assumed under C17. A position open across one logs DATA_GAP and carries it as "
            f"unresolved, and net figures leave it out{changed}"
        )
    if changed:
        return f"Funding is charged at actual settlement times, under C10{changed}"
    return (
        "Funding is charged at actual settlement times, under C10. Every settlement in the range has a rate"
    )


def simulate_v0s(
    engine: EngineConfig,
    data: dict[str, SymbolData],
    *,
    allowance_us: int,
    minimum_allowance_us: int,
    strategies: Sequence[str],
    date_range: DateRange,
    registry: TrialRegistry | None = None,
    manifest_hash: str = "",
    logged_at: str = "",
    version: str = "",
) -> list[StreamResult]:
    """C13: the `V0S` control on every line `V0` ran, each logged in the registry as a control."""
    params_for = _sim_params(
        engine, allowance_us=allowance_us, minimum_allowance_us=minimum_allowance_us, date_range=date_range
    )
    streams: list[StreamResult] = []
    for strategy_id in strategies:
        for line in engine.lines(strategy_id):
            for symbol in engine.symbols:
                item = data[symbol]
                row = None
                if registry is not None:
                    row = trial_row(
                        strategy=strategy_id,
                        line=line.line_id,
                        is_default=line.is_default,
                        in_portfolio=False,
                        symbol=symbol,
                        params=line.params,
                        mode=MODE,
                        variant=VARIANT_V0S,
                        tier=engine.tier,
                        date_range=date_range.as_output(),
                        costs=engine.costs.declared_values(),
                        risk_state=engine.risk.state,
                        data_kind=engine.data_kind,
                        code_version=version,
                        config_hash=engine.config_hash,
                        manifest_hash=manifest_hash,
                        lines_counted=0,
                        control=True,
                    )
                    registry.started(row, logged_at=logged_at)
                result = Simulator(
                    V0SControl(build_strategy(strategy_id, line.params)),
                    item.tape,
                    params_for(strategy_id, symbol),
                    trades=item.trades,
                    funding=item.funding,
                    line=line.line_id,
                    is_default=line.is_default,
                    in_portfolio=False,
                ).run()
                streams.append(result)
                if registry is not None and row is not None:
                    registry.finished(
                        row,
                        logged_at=logged_at,
                        result={"setups": result.setups, "trades": len(result.trades)},
                    )
    return streams


def _control_log(
    engine: EngineConfig,
    registry: TrialRegistry,
    *,
    date_range: DateRange,
    manifest_hash: str,
    logged_at: str,
    version: str,
) -> ControlLog:
    """C15: placebo runs go in the trial registry as controls, each before it starts."""

    def row(plan: Plan, draw: int) -> dict[str, Any]:
        return trial_row(
            strategy=plan.strategy,
            line=plan.line,
            is_default=True,
            in_portfolio=False,
            symbol=plan.symbol,
            params=plan.params,
            mode=MODE,
            variant=VARIANT,
            tier=engine.tier,
            date_range=date_range.as_output(),
            costs=engine.costs.declared_values(),
            risk_state=engine.risk.state,
            data_kind=engine.data_kind,
            code_version=version,
            config_hash=engine.config_hash,
            manifest_hash=manifest_hash,
            lines_counted=0,
            draw=draw,
        )

    def started(plan: Plan, draw: int) -> None:
        registry.started(row(plan, draw), logged_at=logged_at)

    def finished(plan: Plan, stat: DrawStat) -> None:
        registry.finished(
            row(plan, stat.draw),
            logged_at=logged_at,
            result={"setups": stat.setups, "trades": stat.overall.trades},
        )

    return ControlLog(started, finished)


def _not_built(*, placebo: bool) -> dict[str, str]:
    return {
        "selection": "C18 selection for S01 and S06 is not built. No line is picked by outcome anywhere",
        "IDEAL_comparison": "Not reported, see modes",
        "counterfactuals": "SKIPPED_OPEN and ENTRY_COLLAR are logged. C14's counterfactuals are not built",
        "NO_RETEST_counterfactual": "S02 logs NO_RETEST. Its counterfactual at acceptance is not built",
        "G5_target_stress": "The two target stress cases in C7 are not built",
        **(
            {}
            if placebo
            else {
                "placebo": "This command did not ask for C15 placebos. Ask with --placebo. See placebo.json"
            }
        ),
        "placebo_named_extras": "Not built: S07's AVERAGE-PRICE and S10's unconditional breakout",
        "closed_trade_equity": "docs/04 section 1's closed-trade equity series is not built",
        "monthly_and_rolling_tables": "docs/04's monthly and rolling tables are not built",
        "confidence_intervals": "Headline figures carry a sample size and no confidence interval",
        "s01_confluence_log": "Not built, because S01 does not say how close two levels must be to coincide",
        "netted_portfolio": "Section 9 also asks for positions netted by symbol. Only their sum is built",
        "deflated_sharpe": "Not computed. It needs the registry's pooled trial count",
        "share_of_risk": "Not computed. Layer 5 has no method for it yet",
        "benchmarks": "Not joined here. reports/benchmark.py has them",
        "equity_of_other_lines": "equity.json holds the portfolio's lines. Others have rows and trades only",
    }


def write_outputs(
    outcome_rows: OutputRows,
    *,
    guard: PathGuard,
    out_dir: Path,
    header: dict[str, Any],
    manifest: dict[str, Any],
    trials: list[dict[str, Any]],
    streams: Sequence[StreamResult],
    placebo: list[dict[str, Any]],
    placebo_ran: bool,
    v0s: list[dict[str, Any]],
    v0s_trades: list[dict[str, Any]],
) -> None:
    def write(name: str, rows: list[dict[str, Any]]) -> None:
        atomic_write_json(out_dir / name, {"header": header, "rows": rows}, guard=guard)

    write("strategy_asset.json", outcome_rows.strategy_asset)
    write("strategy.json", outcome_rows.strategy)
    write("portfolio.json", outcome_rows.portfolio)
    write("trades.json", outcome_rows.trades)
    write("equity.json", outcome_rows.equity)
    write("events.json", outcome_rows.events)
    write("trials.json", trials)
    write("placebo.json", placebo)
    write("v0s.json", v0s)
    write("v0s_trades.json", v0s_trades)
    atomic_write_json(
        out_dir / "run.json",
        {
            "header": header,
            "manifest": manifest,
            "not_built": _not_built(placebo=placebo_ran),
            "strategies": sorted({stream.strategy for stream in streams}),
            "streams": [
                {
                    "strategy": stream.strategy,
                    "line": stream.line,
                    "is_default": stream.is_default,
                    "in_portfolio": stream.in_portfolio,
                    "asset": stream.symbol,
                    "status": stream_status(stream),
                    "setups": stream.setups,
                    "trades": len(stream.trades),
                    "no_setup_reasons": stream.reasons,
                }
                for stream in streams
            ],
        },
        guard=guard,
    )


def run_engine(
    *,
    data_root: str | None,
    config_path: str | Path,
    date_range: DateRange,
    out_dir: str | Path | None = None,
    pipeline_config_dir: str | None = None,
    logged_at: dt.datetime | None = None,
    placebo: bool = False,
    placebo_workers: int = 1,
    progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    """The whole run. The same files and the same configuration give byte-identical output files."""
    engine = load_engine_config(config_path)
    root = resolve_data_root(data_root, create=False)
    pipeline = load_pipeline_config(pipeline_config_dir)
    source_config = resolve_source(root, pipeline, engine)
    blocks = check_range(date_range, engine.opened_blocks, engine.data_kind, engine.read_days)
    engine.check_ticks_cover(date_range)
    registry = TrialRegistry(root)
    moment = iso(logged_at if logged_at is not None else utcnow())
    # C12: market runs need the declared costs in the registry, and the same values here. Generated runs do
    # not count.
    if engine.data_kind == "MARKET":
        registry.require_declared(engine.costs.declared_values())

    source = source_config.source(engine.venue)
    allowance_us = round(source_config.poll.allowance_a_s * 1_000_000)
    delay_us = max(engine.latency_us, allowance_us)
    minimum = required_allowance(source, allowance_us)

    reader = MarketReader(root, source_config)
    data = {
        symbol: read_symbol(
            reader,
            engine,
            symbol,
            date_range,
            delay_us=delay_us,
            last_opened=source_config.last_opened_date,
        )
        for symbol in engine.symbols
    }
    manifest = build_manifest(data, engine, date_range)
    manifest_hash = stable_hash(manifest)
    version = code_version()
    streams = simulate_streams(
        engine,
        data,
        allowance_us=allowance_us,
        minimum_allowance_us=minimum,
        strategies=available_strategies(),
        date_range=date_range,
        registry=registry,
        manifest_hash=manifest_hash,
        logged_at=moment,
        version=version,
    )
    controls = simulate_v0s(
        engine,
        data,
        allowance_us=allowance_us,
        minimum_allowance_us=minimum,
        strategies=available_strategies(),
        date_range=date_range,
        registry=registry,
        manifest_hash=manifest_hash,
        logged_at=moment,
        version=version,
    )

    first_us = min(int(item.tape.close_us[0]) for item in data.values())
    last_us = max(int(item.tape.close_us[-1]) for item in data.values())
    axis = build_axis(first_us, last_us, source_config.report.equity_timeframe_minutes)
    marks: dict[str, _FloatArray] = {symbol: item.tape.mark_series(axis) for symbol, item in data.items()}

    def mark_at(symbol: str, at_us: int) -> float | None:
        return data[symbol].tape.mark_price(at_us)

    labels = span_labels(blocks)
    funding_missing = {symbol: len(missing_settlements(item.funding)) for symbol, item in data.items()}
    funding_changes = {symbol: len(item.funding_interval_changes) for symbol, item in data.items()}
    rows = build_rows(streams, config=engine, labels=labels, axis=axis, marks=marks, mark_at=mark_at)
    if placebo:
        placebo_results = run_placebos(
            engine,
            data,
            streams,
            date_range=date_range,
            sim_for=_sim_params(
                engine, allowance_us=allowance_us, minimum_allowance_us=minimum, date_range=date_range
            ),
            workers=placebo_workers,
            log=_control_log(
                engine,
                registry,
                date_range=date_range,
                manifest_hash=manifest_hash,
                logged_at=moment,
                version=version,
            ),
            progress=progress,
        )
        placebo_output = placebo_rows(placebo_results, config=engine, labels=labels)
    else:
        placebo_output = not_requested_rows(config=engine, labels=labels, strategies=available_strategies())
    v0s_output = v0s_rows(streams, controls, config=engine, labels=labels, axis=axis, marks=marks)
    v0s_trade_output = v0s_trade_rows(controls, config=engine, labels=labels)
    header = output_header(
        config=engine,
        labels=labels,
        date_range=date_range.as_output(),
        code_version=version,
        manifest_hash=manifest_hash,
        funding_note=_funding_note(engine, funding_missing, funding_changes),
        modes=_modes(engine),
        registry_distinct_trials=registry.distinct_trials(),
        counted_outside_registry=COUNTED_OUTSIDE_REGISTRY,
        registry_distinct_runs=registry.distinct_runs(),
        registry_placebo_readings=registry.placebo_readings(),
        bar_allowance_ms=minimum / 1000.0,
        placebo_ran=placebo,
        funding_missing=funding_missing,
        equity_timeframe_minutes=source_config.report.equity_timeframe_minutes,
    )
    run_id = f"engine-{stable_hash([engine.config_hash, manifest_hash, version])[:16]}"
    target = Path(out_dir) if out_dir is not None else root.run_dir(run_id)
    target.mkdir(parents=True, exist_ok=True)
    if out_dir is not None:
        _refuse_inside_repository(target.resolve())
    guard = PathGuard(target)
    trials = [
        {
            "label": row_label(engine, labels),
            "strategy": stream.strategy,
            "line": stream.line,
            "is_default": stream.is_default,
            "in_portfolio": stream.in_portfolio,
            "asset": stream.symbol,
            "mode": MODE,
            "variant": VARIANT,
            "params": stream.params,
            "status": stream_status(stream),
            "setups": stream.setups,
            "trades": len(stream.trades),
            "lines_counted": strategy_class(stream.strategy).lines_on(engine.tier),
            "counts_as_trial": engine.data_kind == "MARKET"
            and strategy_class(stream.strategy).lines_on(engine.tier) > 0,
            "control": False,
            "used_for_selection": False,
        }
        for stream in streams
    ] + [
        {
            "label": row_label(engine, labels),
            "strategy": stream.strategy,
            "line": stream.line,
            "is_default": stream.is_default,
            "in_portfolio": False,
            "asset": stream.symbol,
            "mode": MODE,
            "variant": VARIANT_V0S,
            "params": stream.params,
            "status": stream_status(stream),
            "setups": stream.setups,
            "trades": len(stream.trades),
            "lines_counted": 0,
            "counts_as_trial": False,
            "control": True,
            "used_for_selection": False,
        }
        for stream in controls
    ]
    write_outputs(
        rows,
        guard=guard,
        out_dir=guard.root,
        header=header,
        manifest=manifest,
        trials=trials,
        streams=streams,
        placebo=placebo_output,
        placebo_ran=placebo,
        v0s=v0s_output,
        v0s_trades=v0s_trade_output,
    )
    return RunOutcome(
        run_id=run_id,
        out_dir=guard.root,
        labels=tuple(header["labels"]),
        streams=tuple(streams),
        rows=rows,
        header=header,
        placebo=tuple(placebo_output),
    )


def declare_costs(
    *, data_root: str | None, config_path: str | Path, logged_at: dt.datetime | None = None
) -> None:
    """C12: log the declared values before the first run. A later difference is refused, and is a counted
    trial.
    """
    engine = load_engine_config(config_path)
    root = resolve_data_root(data_root, create=False)
    moment = iso(logged_at if logged_at is not None else utcnow())
    TrialRegistry(root).declare(engine.costs.declared_values(), basis=engine.costs.basis, logged_at=moment)
