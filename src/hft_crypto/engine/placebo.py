"""C15: placebo draws on each strategy's default line, in the same mode, through the same simulator.

**No seed is picked.** A draw's seed is the first 8 bytes of the SHA-256 of
`C15|<strategy>|<symbol>|<line>|<draw>`, read as a big-endian number, with `draw` from 1 to the declared
count. So a draw cannot be redrawn or swapped, and running again gives the same result. Random numbers come
from `random()` alone, whose sequence Python promises to keep.

**Calendar quarters are the blocks.** Only dates inside the run's range are held, and those are the ones the
fold plan has opened, so no draw, distance or share can read a closed date. A level placebo draws from earlier
quarters only, so the first quarter has none. A real line is compared only over quarters where a placebo
exists, and each quarter without one is named with its reason. A trade belongs to the quarter of its signal.
Whether a quarter is compared is settled afterwards, for the report, and no draw reads it.

**What can read its own block.** The S03, S07 and S10 placebos take their counts and their side share from the
block they fall in, and S03 and S10 draw over that block's eligible bars. C15 and section 10 of each document
say so, and each report says what that does. Everything else holds to the close, as the leak tests show.

A draw depends on nothing but its plan and its seed, so the number of worker processes changes no result.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import random
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from hft_crypto.engine.accounting import from_cents
from hft_crypto.engine.config import DateRange, EngineConfig, GridLine
from hft_crypto.engine.simulator import (
    SimParams,
    Simulator,
    StreamResult,
    SymbolData,
    TradeRecord,
    left_out_reason,
)
from hft_crypto.strategies import available_strategies, build_level_strategy, strategy_class
from hft_crypto.strategies.base import NOT_ON_T0, SIDES, Strategy
from hft_crypto.strategies.placebo import (
    Eligible,
    S03Placebo,
    S03Scan,
    S07Placebo,
    S09Placebo,
    S10Placebo,
    S10Scan,
)
from hft_crypto.strategies.registers import HIGH, LOW
from hft_crypto.strategies.s07_anchored_vwap_pullback import S07AnchoredVwapPullback
from hft_crypto.strategies.sources import (
    Birth,
    DistancePool,
    PlaceboSource,
    RecordingSource,
    quarter_name,
    quarter_of,
    sample_without_replacement,
    uniform_index,
)

METHOD_LEVELS = "RANDOM_LEVELS"
METHOD_ENTRIES = "RANDOM_ENTRIES"
METHOD_SHIFT = "SHIFTED_SCHEDULE"
METHOD_ANCHORS = "RANDOM_ANCHORS"
METHODS = {
    "S01": METHOD_LEVELS,
    "S02": METHOD_LEVELS,
    "S03": METHOD_ENTRIES,
    "S04": METHOD_LEVELS,
    "S05": METHOD_LEVELS,
    "S06": METHOD_LEVELS,
    "S07": METHOD_ANCHORS,
    "S08": METHOD_LEVELS,
    "S09": METHOD_SHIFT,
    "S10": METHOD_ENTRIES,
}
STATUS_RAN = "RAN"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_NO_QUARTER = "NO_QUARTER_WITH_A_PLACEBO"
FIRST_QUARTER = "FIRST_QUARTER_HAS_NO_EARLIER_BLOCK"
NO_EARLIER_DISTANCE = "A_KIND_BORN_HERE_HAS_NO_EARLIER_DISTANCE"
NO_PROFILE = "NO_SEASONAL_PROFILE_IN_THIS_QUARTER"
NO_ELIGIBLE_BAR = "NO_ELIGIBLE_BAR_FOR_THE_REAL_SETUPS"
SEED_RULE = "First 8 bytes, big-endian, of the SHA-256 of C15|<strategy>|<symbol>|<line>|<draw>"
RANK_RULE = (
    "1 is above every draw. Rank is 1 plus the draws at or above the real line, so a tie counts against it. "
    "A draw with no trade has no mean, so it is left out of rank_of and counted"
)


def draw_seed(strategy: str, symbol: str, line: str, draw: int) -> int:
    digest = hashlib.sha256(f"C15|{strategy}|{symbol}|{line}|{draw}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def rank_among(real: float, draws: Sequence[float]) -> int:
    """The real line's rank among the draws, with 1 the highest and a tie counted against it."""
    return 1 + sum(1 for value in draws if value >= real)


@dataclass(frozen=True)
class MeanResult:
    """Mean `Result_B` per trade at 1x, gross and net, with its trade count. No trade means no mean."""

    trades: int
    gross_mean: float | None
    net_mean: float | None


def mean_result_b(trades: Sequence[TradeRecord], compared: frozenset[int]) -> MeanResult:
    gross = 0.0
    net = 0.0
    count = 0
    for trade in trades:
        if quarter_of(trade.signal_us) not in compared:
            continue
        _, booked = trade.book()
        gross += from_cents(booked.gross) / trade.risk_budget
        net += from_cents(booked.net) / trade.risk_budget
        count += 1
    if count == 0:
        return MeanResult(0, None, None)
    return MeanResult(count, gross / count, net / count)


@dataclass(frozen=True)
class QuarterRow:
    quarter: int
    has_placebo: bool
    reason: str | None = None

    @property
    def name(self) -> str:
        return quarter_name(self.quarter)


@dataclass(frozen=True)
class Plan:
    """All one strategy's draws on one symbol need, apart from the market. It holds no result of a draw."""

    strategy: str
    symbol: str
    line: str
    params: dict[str, Any]
    swap: str
    sim: SimParams
    quarters: tuple[QuarterRow, ...]
    pool: DistancePool | None = None
    # By quarter and side.
    eligible: dict[int, dict[int, list[int]]] = field(default_factory=dict)
    counts: dict[int, dict[int, int]] = field(default_factory=dict)
    # By quarter: the bars an anchor may fall on, and the real major swings by kind.
    anchor_bars: dict[int, list[int]] = field(default_factory=dict)
    anchor_counts: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def compared(self) -> frozenset[int]:
        return frozenset(row.quarter for row in self.quarters if row.has_placebo)


@dataclass(frozen=True)
class DrawStat:
    draw: int
    seed: int
    setups: int
    overall: MeanResult
    by_branch: dict[str, MeanResult]
    counters: dict[str, int]
    failures: dict[str, int]
    missing: dict[str, int]
    # R-02: entries an S03 or S10 draw could not place, by quarter and side. Empty when every count was met.
    shortfall: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaceboResult:
    strategy: str
    symbol: str
    line: str
    params: dict[str, Any]
    swap: str
    status: str
    reason: str | None
    quarters: tuple[QuarterRow, ...]
    real: MeanResult
    real_by_branch: dict[str, MeanResult]
    real_setups_by_quarter: dict[int, int]
    real_trades_by_quarter: dict[int, int]
    draws: tuple[DrawStat, ...]


def quarters_in(date_range: DateRange) -> list[int]:
    return list(range(quarter_of(date_range.first_open_us), quarter_of(date_range.end_us - 1) + 1))


# ---- plans ----------------------------------------------------------------------------------------------


def _simulate(strategy: Strategy, item: SymbolData, sim: SimParams, line: str) -> StreamResult:
    return Simulator(
        strategy,
        item.tape,
        sim,
        trades=item.trades,
        funding=item.funding,
        line=line,
        is_default=True,
        in_portfolio=False,
    ).run()


def _level_plan(
    *, strategy: str, symbol: str, line: GridLine, item: SymbolData, sim: SimParams, quarters: list[int]
) -> Plan:
    """A real run that writes down its levels. Registers read no position, so these are the real run's."""
    recorder = RecordingSource()
    _simulate(build_level_strategy(strategy, line.params, recorder), item, sim, line.line_id)
    # A read day's bars stay for continuity, and no distance is taken from it.
    births = [birth for birth in recorder.births if not _on_read_day(birth, sim)]
    pool = DistancePool(births)
    kinds_by_quarter: dict[int, set[str]] = {}
    for birth in births:
        kinds_by_quarter.setdefault(quarter_of(birth.knowable_us), set()).add(birth.kind)
    rows: list[QuarterRow] = []
    for position, quarter in enumerate(quarters):
        kinds = kinds_by_quarter.get(quarter, set())
        if position == 0:
            rows.append(QuarterRow(quarter, False, FIRST_QUARTER))
        elif any(pool.count_before(kind, quarter) == 0 for kind in kinds):
            rows.append(QuarterRow(quarter, False, NO_EARLIER_DISTANCE))
        else:
            rows.append(QuarterRow(quarter, True))
    return Plan(
        strategy=strategy,
        symbol=symbol,
        line=line.line_id,
        params=line.params,
        swap=METHOD_LEVELS,
        sim=sim,
        quarters=tuple(rows),
        pool=pool,
    )


def _on_read_day(birth: Birth, sim: SimParams) -> bool:
    return any(start <= birth.knowable_us < end for start, end in sim.read_days_us)


def _real_setups(real: StreamResult) -> dict[int, dict[int, int]]:
    counts: dict[int, dict[int, int]] = {}
    for event in real.events:
        if event["type"] == "SETUP_CREATED":
            row = counts.setdefault(quarter_of(event["computed_at_us"]), dict.fromkeys(SIDES, 0))
            row[event["side"]] += 1
    return counts


def _entry_plan(
    *,
    strategy: str,
    symbol: str,
    line: GridLine,
    item: SymbolData,
    sim: SimParams,
    quarters: list[int],
    real: StreamResult,
) -> Plan:
    """The bars that pass the non-signal filters, less any a setup could not use under the fold plan."""
    scan: S03Scan | S10Scan = S03Scan(line.params) if strategy == "S03" else S10Scan(line.params)
    _simulate(scan, item, sim, line.line_id)
    eligible: dict[int, dict[int, list[int]]] = {}
    for row in _usable(scan.eligible, scan.h_max_us, sim):
        by_side = eligible.setdefault(quarter_of(row.close_us), {side: [] for side in SIDES})
        by_side[row.side].append(row.close_us)
    counts = _real_setups(real)
    rows = []
    for quarter in quarters:
        wanted = sum(counts.get(quarter, {}).values())
        found = eligible.get(quarter)
        if wanted and (found is None or not any(found.values())):
            rows.append(QuarterRow(quarter, False, NO_ELIGIBLE_BAR))
        else:
            rows.append(QuarterRow(quarter, True))
    return Plan(
        strategy=strategy,
        symbol=symbol,
        line=line.line_id,
        params=line.params,
        swap=METHOD_ENTRIES,
        sim=sim,
        quarters=tuple(rows),
        eligible=eligible,
        counts=counts,
    )


def _usable(rows: list[Eligible], h_max_us: int, sim: SimParams) -> list[Eligible]:
    return [
        row
        for row in rows
        if left_out_reason(row.close_us, h_max_us, sim.span_end_us, sim.read_days_us) is None
    ]


def _shift_plan(
    *, strategy: str, symbol: str, line: GridLine, sim: SimParams, quarters: list[int], real: StreamResult
) -> Plan:
    """S09's placebo needs nothing from earlier blocks, and exists wherever the real profile does."""
    fitted = {
        quarter_of(event["fitted_at_us"])
        for event in real.events
        if event["type"] == "SEASONAL_PROFILE_FITTED"
    }
    rows = tuple(
        QuarterRow(quarter, True) if quarter in fitted else QuarterRow(quarter, False, NO_PROFILE)
        for quarter in quarters
    )
    return Plan(
        strategy=strategy,
        symbol=symbol,
        line=line.line_id,
        params=line.params,
        swap=METHOD_SHIFT,
        sim=sim,
        quarters=rows,
    )


def _anchor_plan(
    *, strategy: str, symbol: str, line: GridLine, item: SymbolData, sim: SimParams, quarters: list[int]
) -> Plan:
    held = S07AnchoredVwapPullback(line.params)
    _simulate(held, item, sim, line.line_id)
    counts: dict[int, dict[str, int]] = {}
    for entry in held.major.entries:
        row = counts.setdefault(quarter_of(entry.valid_from), {LOW: 0, HIGH: 0})
        row[entry.kind] += 1
    bars: dict[int, list[int]] = {}
    for bar in item.tape.frame(held.timeframe_minutes):
        bars.setdefault(quarter_of(bar.close_us), []).append(bar.close_us)
    return Plan(
        strategy=strategy,
        symbol=symbol,
        line=line.line_id,
        params=line.params,
        swap=METHOD_ANCHORS,
        sim=sim,
        quarters=tuple(QuarterRow(quarter, True) for quarter in quarters),
        anchor_bars=bars,
        anchor_counts=counts,
    )


def build_plan(
    strategy: str,
    symbol: str,
    line: GridLine,
    *,
    item: SymbolData,
    sim: SimParams,
    quarters: list[int],
    real: StreamResult,
) -> Plan:
    method = METHODS[strategy]
    if method == METHOD_LEVELS:
        return _level_plan(strategy=strategy, symbol=symbol, line=line, item=item, sim=sim, quarters=quarters)
    if method == METHOD_ENTRIES:
        return _entry_plan(
            strategy=strategy, symbol=symbol, line=line, item=item, sim=sim, quarters=quarters, real=real
        )
    if method == METHOD_SHIFT:
        return _shift_plan(strategy=strategy, symbol=symbol, line=line, sim=sim, quarters=quarters, real=real)
    return _anchor_plan(strategy=strategy, symbol=symbol, line=line, item=item, sim=sim, quarters=quarters)


# ---- one draw -------------------------------------------------------------------------------------------


def draw_entries(
    rng: random.Random, eligible: dict[int, dict[int, list[int]]], counts: dict[int, dict[int, int]]
) -> dict[int, int]:
    """C15: uniformly and without replacement over the eligible bars, as many longs and shorts per block as
    the real setups. A bar is used once, so a side comes from the draw and owes nothing to what follows.

    The side with fewer eligible bars draws first. Code recheck R-02: it takes a bar both sides can use only
    while the other side can still meet its count from the bars left, so the bars only one side can use
    are spent before the shared bars the other side needs, and both counts are met whenever the bars allow.
    With bars to spare that limit never binds, and the draw is the same uniform draw as before, number for
    number. A count that cannot be met is recorded by `entry_shortfall`.
    """
    entries: dict[int, int] = {}
    for quarter in sorted(counts):
        found = eligible.get(quarter, {})
        first, second = sorted(SIDES, key=lambda value: (len(found.get(value, [])), -value))
        first_bars = [close for close in found.get(first, []) if close not in entries]
        second_bars = [close for close in found.get(second, []) if close not in entries]
        shared = frozenset(first_bars) & frozenset(second_bars)
        want_first = counts[quarter].get(first, 0)
        want_second = counts[quarter].get(second, 0)
        # The shared bars the second side must keep to meet as much of its count as its bars allow.
        needed = max(0, min(want_second, len(second_bars)) - (len(second_bars) - len(shared)))
        for close in _sample_sparing(rng, first_bars, want_first, shared, len(shared) - needed):
            entries[close] = first
        open_bars = [close for close in second_bars if close not in entries]
        for close in sample_without_replacement(rng, open_bars, want_second):
            entries[close] = second
    return entries


def _sample_sparing(
    rng: random.Random, items: list[int], count: int, shared: frozenset[int], spare: int
) -> list[int]:
    """`sample_without_replacement`, which stops taking `shared` items once it has taken `spare` of them.

    Until then it makes the same calls on `rng` and gives the same items, so with `spare` never reached it is
    that function exactly.
    """
    pool = list(items)
    chosen: list[int] = []
    taken_shared = 0
    while len(chosen) < count:
        taken = len(chosen)
        if taken_shared >= spare:
            pool = pool[:taken] + [item for item in pool[taken:] if item not in shared]
        if taken >= len(pool):
            break
        pick = taken + uniform_index(rng, len(pool) - taken)
        pool[taken], pool[pick] = pool[pick], pool[taken]
        chosen.append(pool[taken])
        taken_shared += pool[taken] in shared
    return chosen


def entry_shortfall(
    entries: dict[int, int], eligible: dict[int, dict[int, list[int]]], counts: dict[int, dict[int, int]]
) -> dict[str, int]:
    """By quarter and side, how many of the real setups' entries a draw could not place. Empty when none."""
    short: dict[str, int] = {}
    for quarter in sorted(counts):
        found = eligible.get(quarter, {})
        for side in sorted(SIDES, reverse=True):
            drawn = sum(1 for close in found.get(side, []) if entries.get(close) == side)
            missed = counts[quarter].get(side, 0) - drawn
            if missed > 0:
                short[f"{quarter_name(quarter)}:{'long' if side > 0 else 'short'}"] = missed
    return short


def draw_anchors(
    rng: random.Random, bars: dict[int, list[int]], counts: dict[int, dict[str, int]]
) -> frozenset[tuple[int, str]]:
    """Section 10 of S07: uniformly over the block's bars, with as many per side as its real major swings."""
    anchors: set[tuple[int, str]] = set()
    for quarter in sorted(counts):
        for kind in (LOW, HIGH):
            chosen = sample_without_replacement(rng, bars.get(quarter, []), counts[quarter][kind])
            anchors.update((close, kind) for close in chosen)
    return frozenset(anchors)


def draw_strategy(plan: Plan, rng: random.Random) -> tuple[Strategy, PlaceboSource | None]:
    if plan.swap == METHOD_LEVELS:
        if plan.pool is None:
            raise ValueError(f"{plan.strategy} has no distance pool")
        source = PlaceboSource(plan.pool, rng)
        return build_level_strategy(plan.strategy, plan.params, source), source
    if plan.swap == METHOD_ENTRIES:
        entries = draw_entries(rng, plan.eligible, plan.counts)
        if plan.strategy == "S03":
            return S03Placebo(plan.params, entries), None
        return S10Placebo(plan.params, entries), None
    if plan.swap == METHOD_SHIFT:
        return S09Placebo(plan.params, rng), None
    return S07Placebo(plan.params, draw_anchors(rng, plan.anchor_bars, plan.anchor_counts)), None


def simulate_draw(plan: Plan, draw: int, item: SymbolData) -> tuple[StreamResult, PlaceboSource | None]:
    rng = random.Random(draw_seed(plan.strategy, plan.symbol, plan.line, draw))  # noqa: S311
    strategy, source = draw_strategy(plan, rng)
    return _simulate(strategy, item, plan.sim, plan.line), source


def by_branch(trades: Sequence[TradeRecord], compared: frozenset[int]) -> dict[str, MeanResult]:
    tags = sorted({trade.tag for trade in trades if trade.tag is not None})
    return {tag: mean_result_b([trade for trade in trades if trade.tag == tag], compared) for tag in tags}


def drawn_entries(plan: Plan, draw: int) -> dict[int, int]:
    """The entries `draw_strategy` gives this draw: the first numbers of its own seed, as there."""
    rng = random.Random(draw_seed(plan.strategy, plan.symbol, plan.line, draw))  # noqa: S311
    return draw_entries(rng, plan.eligible, plan.counts)


def run_draw(plan: Plan, draw: int, item: SymbolData) -> DrawStat:
    result, source = simulate_draw(plan, draw, item)
    shortfall = (
        entry_shortfall(drawn_entries(plan, draw), plan.eligible, plan.counts)
        if plan.swap == METHOD_ENTRIES
        else {}
    )
    return DrawStat(
        draw=draw,
        seed=draw_seed(plan.strategy, plan.symbol, plan.line, draw),
        setups=result.setups,
        overall=mean_result_b(result.trades, plan.compared),
        by_branch=by_branch(result.trades, plan.compared),
        counters=result.counters,
        failures={key: value for key, value in result.reasons.items() if key in _ENTRY_FAILURES},
        missing={} if source is None else dict(source.missing),
        shortfall=shortfall,
    )


_ENTRY_FAILURES = frozenset({"STOP_TOO_WIDE", "NO_T1_ROOM", "NO_ROOM_TO_X", "NO_ROOM_TO_POC", "COST_VETO"})


# ---- all of them ----------------------------------------------------------------------------------------

_WORKER: dict[str, Any] = {}


def _worker_start(item: SymbolData, plans: dict[str, Plan]) -> None:
    _WORKER["item"] = item
    _WORKER["plans"] = plans


def _worker_draw(task: tuple[str, int]) -> DrawStat:
    strategy, draw = task
    stat: DrawStat = run_draw(_WORKER["plans"][strategy], draw, _WORKER["item"])
    return stat


@dataclass(frozen=True)
class ControlLog:
    """The trial registry's two hooks. A draw is logged before it starts, and again when it ends."""

    started: Callable[[Plan, int], None]
    finished: Callable[[Plan, DrawStat], None]


def _draws_for_symbol(
    plans: dict[str, Plan],
    item: SymbolData,
    draws: int,
    workers: int,
    log: ControlLog | None,
    progress: Callable[[str], None] | None,
) -> dict[str, list[DrawStat]]:
    tasks = [(name, draw) for name in plans for draw in range(1, draws + 1)]
    if log is not None:
        for name, draw in tasks:
            log.started(plans[name], draw)
    results: dict[str, list[DrawStat]] = {name: [] for name in plans}

    def take(name: str, stat: DrawStat) -> None:
        results[name].append(stat)
        if log is not None:
            log.finished(plans[name], stat)
        if progress is not None and stat.draw == draws:
            progress(f"{name} {plans[name].symbol}: {draws} draws done")

    if workers <= 1:
        for name, draw in tasks:
            take(name, run_draw(plans[name], draw, item))
        return results
    # Spawned on every platform, so a worker starts from the same clean state whatever the system offers.
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_worker_start,
        initargs=(item, plans),
    ) as pool:
        for (name, _), stat in zip(tasks, pool.map(_worker_draw, tasks), strict=True):
            take(name, stat)
    return results


def _by_quarter(real: StreamResult) -> tuple[dict[int, int], dict[int, int]]:
    setups = {quarter: sum(row.values()) for quarter, row in _real_setups(real).items()}
    trades = Counter(quarter_of(trade.signal_us) for trade in real.trades)
    return setups, dict(trades)


def run_placebos(
    engine: EngineConfig,
    data: dict[str, SymbolData],
    streams: Sequence[StreamResult],
    *,
    date_range: DateRange,
    sim_for: Callable[[str, str], SimParams],
    workers: int = 1,
    log: ControlLog | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[PlaceboResult]:
    """One result per strategy and symbol, on the default line, in a fixed order. Nothing picks a draw."""
    quarters = quarters_in(date_range)
    draws = engine.placebo_draws
    real_of = {(stream.strategy, stream.symbol): stream for stream in streams if stream.is_default}
    results: list[PlaceboResult] = []
    for symbol in engine.symbols:
        item = data[symbol]
        plans: dict[str, Plan] = {}
        early: dict[str, PlaceboResult] = {}
        for strategy in available_strategies():
            line = engine.strategies[strategy].default()
            real = real_of[(strategy, symbol)]
            if strategy_class(strategy).lines_on(engine.tier) == 0:
                early[strategy] = _not_run(strategy, symbol, line, real, NOT_ON_T0)
                continue
            plan = build_plan(
                strategy,
                symbol,
                line,
                item=item,
                sim=sim_for(strategy, symbol),
                quarters=quarters,
                real=real,
            )
            if not plan.compared:
                early[strategy] = _result(plan, real, [], STATUS_NO_QUARTER)
                continue
            plans[strategy] = plan
        found = _draws_for_symbol(plans, item, draws, workers, log, progress)
        for strategy in available_strategies():
            if strategy in early:
                results.append(early[strategy])
            else:
                results.append(
                    _result(plans[strategy], real_of[(strategy, symbol)], found[strategy], STATUS_RAN)
                )
    return results


def _result(plan: Plan, real: StreamResult, draws: list[DrawStat], status: str) -> PlaceboResult:
    setups, trades = _by_quarter(real)
    return PlaceboResult(
        strategy=plan.strategy,
        symbol=plan.symbol,
        line=plan.line,
        params=plan.params,
        swap=plan.swap,
        status=status,
        reason=None,
        quarters=plan.quarters,
        real=mean_result_b(real.trades, plan.compared),
        real_by_branch=by_branch(real.trades, plan.compared),
        real_setups_by_quarter=setups,
        real_trades_by_quarter=trades,
        draws=tuple(draws),
    )


def _not_run(strategy: str, symbol: str, line: GridLine, real: StreamResult, reason: str) -> PlaceboResult:
    del real
    return PlaceboResult(
        strategy=strategy,
        symbol=symbol,
        line=line.line_id,
        params=line.params,
        swap=METHODS[strategy],
        status=STATUS_NOT_RUN,
        reason=reason,
        quarters=(),
        real=MeanResult(0, None, None),
        real_by_branch={},
        real_setups_by_quarter={},
        real_trades_by_quarter={},
        draws=(),
    )
