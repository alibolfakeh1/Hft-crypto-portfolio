"""EN-04: cuts over the whole run, so a leak that starts late in a run cannot hide.

The earlier tests cut a run at its first two setups only, so a filter that reads the next bar from the third
setup on passed everything. Here each line is cut at setups spread over the whole run, at the decision and a
microsecond before it, and at random closes, and each cut is both truncated and perturbed after it.

- **Markets.** Two seeds or more, for every strategy that runs: candle-shaped rows from the real converter,
  with runs of missing rows and rows that fail a check, for S01 to S06, S09 and S10. Bars from trades with
  holes in the ids, for all ten. S05 is rare, so it has three seeds picked to reach it, for coverage only.
  S09's holes come after its first profile fit, or it would never trade.
- **Lines.** The default line and one other.
- **What is compared.** Every decision knowable by the cut, and the registers at the last decided close.
  Every bar of every timeframe, on its own.
- **The back door stays open on purpose.** A simulator that keeps a setup from the third on only if the
  next bar moves its way is run through the same harness, for every strategy, and the harness must see it.
  No generated S05 run reaches a second setup on a line, so a filter from the third cannot act on it, and
  a dropped setup that is a run's only one leaves no event for a cut to land on. For S05 the back door
  reads the next bar into the stop instead, from the first setup on. A filter from the third is not shown
  for S05.

All data is generated, and all prices are invented.
"""

from __future__ import annotations

import dataclasses
import json
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import polars as pl
import pytest

from engine_helpers import (
    DAY,
    DELAY_US,
    MINUTE,
    candles_from,
    engine_config,
    generated_trades,
    minute_bars,
    perturb_after,
    sim_params,
    trades_through,
    utc,
)
from hft_crypto.bars.core import bars_from_official
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.simulator import SimParams, Simulator, StreamResult
from hft_crypto.engine.tape import Bar, MinuteTape, TradeTape
from hft_crypto.strategies import build_strategy
from hft_crypto.strategies.base import Proposal, Strategy

START = utc(2000, 1, 1)
DAYS = 150
CANDLE_ALLOWANCE_US = 10_000_000
ON_CANDLES = ("S01", "S02", "S03", "S04", "S05", "S06", "S09", "S10")
ALL = (*ON_CANDLES, "S07", "S08")
# A seed is picked for how much of the rule it exercises, and for nothing else. S05's flips are rare: of
# seeds 1 to 30 over 230 days with these holes, none gave more than one setup on a line, and its second line
# gave none. These three give one each on the default line, on candles and on trades.
SEEDS = {"S05": ((3, 230), (5, 230), (6, 230))}
DEFAULT_SEEDS = ((7, DAYS), (11, DAYS))
# S09 fits its profile once a quarter and fails closed on any flagged hour in the window (as
# test_s09_a_flagged_hour_never_enters_the_profile_so_the_fit_fails_closed holds), so with the early holes it
# never trades. Its holes and bad rows come after the 2000-04-01 fit.
LAYOUT = {"S09": "late"}
# Fills, exits and funding carry their minute's close as their time, and a candle is readable only past its
# allowance, so these are compared once that minute can be read.
WALK = frozenset(
    {
        "ENTRY",
        "EXIT",
        "SCALE_OUT",
        "FUNDING",
        "DATA_GAP",
        "EXIT_SUPERSEDED",
        "ENTRY_COLLAR",
        "ENTRY_ACROSS_GAP",
    }
)
NOT_DECISIONS = frozenset({"GAP_UNRESOLVED", "ENTRY_UNFILLED_AT_END"})
TIMEFRAMES = (5, 15, 30, 60, 240, 1440)


# ---- markets -----------------------------------------------------------------------------------------------


def _holes(days: int, layout: str = "early") -> list[tuple[int, int]]:
    """A run of 40 minutes, a whole hour and a whole day, in minutes from the start."""
    if layout == "late":
        return [(105 * 1440 + 600, 40), (118 * 1440 + 840, 60), (min(135, days - 10) * 1440, 1440)]
    return [(30 * 1440 + 600, 40), (61 * 1440 + 840, 60), (min(95, days - 10) * 1440, 1440)]


def _bad_rows(layout: str = "early") -> list[int]:
    """Three candle rows that fail a check at the row, in minutes from the start."""
    if layout == "late":
        return [108 * 1440 + 785, 125 * 1440 + 10, 140 * 1440 + 1439]
    return [50 * 1440 + 785, 70 * 1440 + 10, 120 * 1440 + 1439]


@lru_cache(maxsize=4)
def _trades(seed: int, days: int) -> pl.DataFrame:
    return generated_trades(seed=seed, start_us=START, days=days)


@lru_cache(maxsize=4)
def _candles(seed: int, days: int, layout: str) -> pl.DataFrame:
    """Candles with runs of missing rows, and three rows that fail a check at the row."""
    candles = candles_from(_trades(seed, days), first_open_us=START, minutes=days * 1440)
    minute = (pl.col("open_time").dt.timestamp("us") - START) // MINUTE
    for first, length in _holes(days, layout):
        candles = candles.filter((minute < first) | (minute >= first + length))
    bad = _bad_rows(layout)
    return candles.with_columns(
        pl.when(minute.is_in(bad)).then(pl.col("low") - 5.0).otherwise(pl.col("high")).alias("high")
    )


def _candle_tape(candles: pl.DataFrame, through_us: int) -> MinuteTape:
    last_close = (through_us - CANDLE_ALLOWANCE_US) // MINUTE * MINUTE
    held = candles.filter(pl.col("open_time").dt.timestamp("us") + MINUTE <= last_close)
    bars = bars_from_official(
        held,
        venue="generated",
        symbol="S",
        first_close_us=START + MINUTE,
        last_close_us=last_close,
        candle_allowance_us=CANDLE_ALLOWANCE_US,
    )
    return MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)


@lru_cache(maxsize=4)
def _holed_trades(seed: int, days: int, layout: str) -> pl.DataFrame:
    """Trades with the same holes, which skip trade ids, so the bars that span them are flagged."""
    trades = _trades(seed, days)
    minute = (pl.col("ts").dt.timestamp("us") - START) // MINUTE
    for first, length in _holes(days, layout):
        trades = trades.filter((minute < first) | (minute >= first + length))
    return trades


def _trade_tape(trades: pl.DataFrame, through_us: int) -> tuple[MinuteTape, TradeTape]:
    held = trades_through(trades, through_us)
    last_close = through_us // MINUTE * MINUTE
    bars = minute_bars(held, first_close_us=START + MINUTE, last_close_us=last_close)
    return MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US), TradeTape.from_frame(held)


@dataclass(frozen=True)
class Market:
    kind: str
    seed: int
    days: int
    layout: str = "early"

    @property
    def end(self) -> int:
        return START + self.days * DAY

    def tape(self, through_us: int, data: pl.DataFrame | None = None) -> tuple[MinuteTape, TradeTape | None]:
        if self.kind == "candles":
            return _candle_tape(self.data() if data is None else data, through_us), None
        return _trade_tape(self.data() if data is None else data, through_us)

    def data(self) -> pl.DataFrame:
        if self.kind == "candles":
            return _candles(self.seed, self.days, self.layout)
        return _holed_trades(self.seed, self.days, self.layout)

    def truncated(self, cut_us: int) -> tuple[MinuteTape, TradeTape | None]:
        return self.tape(cut_us)

    def perturbed(self, cut_us: int, seed: int) -> tuple[MinuteTape, TradeTape | None]:
        if self.kind == "trades":
            return self.tape(self.end, perturb_after(self.data(), cut_us, seed))
        return self.tape(self.end, _scramble_candles_after(self.data(), cut_us, seed))

    @property
    def allowance(self) -> int:
        return CANDLE_ALLOWANCE_US if self.kind == "candles" else 0


def _scramble_candles_after(candles: pl.DataFrame, cut_us: int, seed: int) -> pl.DataFrame:
    """After the cut, wild prices, rows dropped, and rows that fail a check. Nothing before it changes."""
    rng = np.random.default_rng(seed)
    opening = candles["open_time"].dt.timestamp("us").to_numpy()
    after = opening + MINUTE > cut_us - CANDLE_ALLOWANCE_US
    keep = ~after | (rng.random(opening.size) > 0.02)
    noise = rng.uniform(0.5, 1.5, opening.size)
    frame = candles.with_columns(pl.Series("_after", after), pl.Series("_noise", noise)).filter(
        pl.Series(keep)
    )
    scaled = [
        pl.when(pl.col("_after")).then(pl.col(name) * pl.col("_noise")).otherwise(pl.col(name)).alias(name)
        for name in ("open", "close")
    ]
    frame = frame.with_columns(scaled)
    return frame.with_columns(
        pl.when(pl.col("_after"))
        .then(pl.max_horizontal("open", "close") * 1.01)
        .otherwise(pl.col("high"))
        .alias("high"),
        pl.when(pl.col("_after"))
        .then(pl.min_horizontal("open", "close") * 0.99)
        .otherwise(pl.col("low"))
        .alias("low"),
    ).drop("_after", "_noise")


def _markets(strategy: str) -> list[Market]:
    seeds = SEEDS.get(strategy, DEFAULT_SEEDS)
    kinds = ("candles", "trades") if strategy in ON_CANDLES else ("trades",)
    layout = LAYOUT.get(strategy, "early")
    return [Market(kind, seed, days, layout) for kind in kinds for seed, days in seeds]


def _lines(strategy: str) -> list[tuple[str, dict[str, Any]]]:
    lines = engine_config().lines(strategy)
    return [("default", dict(lines[0].params)), ("other", dict(lines[1].params))]


# ---- runs --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    events: list[dict[str, Any]]
    snapshots: dict[int, str]
    stream: StreamResult


def _params(market: Market) -> SimParams:
    return sim_params(fill_span_allowance_us=max(market.allowance, 250_000))


def _run(
    strategy: str,
    params: dict[str, Any],
    tape: MinuteTape,
    trades: TradeTape | None,
    market: Market,
    simulator: type[Simulator] = Simulator,
) -> Run:
    snapshots: dict[int, str] = {}

    def probe(held: Strategy, view: MarketView) -> None:
        snapshots[view.now_us] = json.dumps(held.snapshot(), sort_keys=True, default=str)

    built = build_strategy(strategy, {**params, "tier": "T0" if trades is None else "T1"})
    stream = simulator(built, tape, _params(market), trades=trades, probe=probe).run()
    return Run(stream.events, snapshots, stream)


def _known_by(events: list[dict[str, Any]], cut_us: int, allowance: int) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event["type"] not in NOT_DECISIONS
        and event["knowable_us"] + (allowance if event["type"] in WALK else 0) <= cut_us
    ]


def _cuts(run: Run, name: str) -> tuple[list[int], list[int]]:
    """(truncation cuts, perturbation cuts): setups from the third on, spread over the run, and random
    closes."""
    created = [event["computed_at_us"] for event in run.events if event["type"] == "SETUP_CREATED"]
    picked = sorted(
        {created[index] for index in (2, len(created) // 2, len(created) - 1) if 0 <= index < len(created)}
    )
    decided = [close + DELAY_US for close in picked]
    rng = random.Random(name)
    closes = sorted(run.snapshots)
    random_cuts = [closes[rng.randrange(len(closes))] + DELAY_US for _ in range(2)] if closes else []
    truncation = [*decided, *(cut - 1 for cut in decided[:1]), *random_cuts]
    return truncation, decided


def _compare(full: Run, other: Run, cut_us: int, allowance: int, label: str) -> None:
    assert _known_by(full.events, cut_us, allowance) == _known_by(other.events, cut_us, allowance), label
    decided = [close for close in full.snapshots if close + DELAY_US <= cut_us]
    if decided:
        close = max(decided)
        assert full.snapshots[close] == other.snapshots[close], f"{label}: registers at {close}"


def _check_line(
    strategy: str, params: dict[str, Any], market: Market, simulator: type[Simulator] = Simulator
) -> tuple[int, list[str]]:
    """Every cut for one line on one market. Returns the setups seen and every difference found."""
    tape, trades = market.tape(market.end)
    full = _run(strategy, params, tape, trades, market, simulator)
    name = f"{strategy}|{market}|{sorted(params.items())}"
    truncation, perturbation = _cuts(full, name)
    differences: list[str] = []
    for cut in truncation:
        other = _run(strategy, params, *market.truncated(cut), market, simulator)
        try:
            _compare(full, other, cut, market.allowance, f"{name} cut at {cut}")
        except AssertionError as failure:
            differences.append(str(failure)[:200])
    for index, cut in enumerate(perturbation):
        other = _run(strategy, params, *market.perturbed(cut, 101 + index), market, simulator)
        try:
            _compare(full, other, cut, market.allowance, f"{name} perturbed at {cut}")
        except AssertionError as failure:
            differences.append(str(failure)[:200])
    setups = sum(1 for event in full.events if event["type"] == "SETUP_CREATED")
    return setups, differences


@pytest.mark.parametrize("strategy", ALL)
def test_every_cut_over_the_whole_run_leaves_the_past_unchanged(strategy: str) -> None:
    setups = 0
    for market in _markets(strategy):
        for _, params in _lines(strategy):
            found, differences = _check_line(strategy, params, market)
            assert differences == []
            setups += found
    assert setups >= 6, f"{strategy} made {setups} setups across its markets, so this would prove too little"


# ---- the back door, held open ------------------------------------------------------------------------------


class _NextBarFilter(Simulator):
    """The leak the old tests missed: from the third setup on, keep one only if the next bar moves its way."""

    seen = 0

    def _take(self, proposal: Proposal, bar: Bar, strategy: Strategy, decided_as_of: int) -> None:
        self.seen += 1
        if self.seen >= 3:
            frame = self.tape.frame(bar.minutes)
            if bar.index + 1 < len(frame) and proposal.side * (frame[bar.index + 1].c - bar.c) < 0:
                return
        super()._take(proposal, bar, strategy, decided_as_of)


class _NextBarPeek(Simulator):
    """For S05: from the first setup on, the stop moves out by how far the next bar's close went."""

    def _take(self, proposal: Proposal, bar: Bar, strategy: Strategy, decided_as_of: int) -> None:
        frame = self.tape.frame(bar.minutes)
        if bar.index + 1 < len(frame):
            moved = abs(frame[bar.index + 1].c - bar.c)
            proposal = dataclasses.replace(proposal, s0=proposal.s0 - proposal.side * moved)
        super()._take(proposal, bar, strategy, decided_as_of)


FILTERS: dict[str, type[Simulator]] = {"S05": _NextBarPeek}


@pytest.mark.parametrize("strategy", ALL)
def test_the_harness_catches_a_next_bar_filter_from_the_third_setup_on(strategy: str) -> None:
    """If this did not fail on a real leak, the test above would be worth nothing. The filter only acts on a
    third setup whose next bar goes the wrong way, so markets are tried in order until one shows it.
    """
    found: list[str] = []
    for market in _markets(strategy):
        for _, params in _lines(strategy):
            found += _check_line(strategy, params, market, FILTERS.get(strategy, _NextBarFilter))[1]
        if found:
            break
    assert found, f"{strategy}: a next-bar filter from the third setup on went unseen on every market"


# ---- every bar of every timeframe --------------------------------------------------------------------------


def _bar_cuts(market: Market) -> list[int]:
    rng = random.Random(f"bars|{market}")
    first, length = _holes(market.days, market.layout)[0]
    named = [
        START + 91 * DAY + DELAY_US,  # a quarter boundary
        START + (first + length) * MINUTE + DELAY_US,  # just after a hole
        # just after a row that failed its check
        START + (_bad_rows(market.layout)[0] + 1) * MINUTE + DELAY_US,
    ]
    return [
        *named,
        *(START + rng.randrange(20 * 1440, market.days * 1440) * MINUTE + DELAY_US for _ in range(3)),
    ]


def _as_compared(bar: Bar) -> tuple[Any, ...]:
    """Every field, except `late_gap` on a bar that is already a gap.

    `late_gap` does two things, both in the tape: it resets `ATR` and it makes the bar incomplete. A gap bar
    has both already, so there `late_gap` changes nothing, and nothing outside the tape reads it. It records
    only when an earlier tail flag arrived, and that time is not the same in two builds: a build at the cut
    flags the minutes after its last trade at their own close, and the full build flags the same minutes
    when the trade that shows the skip arrives. `complete`, `atr`, `atr_last` and `tr` are still compared on
    every bar, so a difference that could reach a decision is still seen. On a bar that is not a gap,
    `late_gap` is compared as it is.
    """
    return dataclasses.astuple(dataclasses.replace(bar, late_gap=False) if bar.gap else bar)


@pytest.mark.parametrize(
    "market", [Market(kind, seed, DAYS) for kind in ("candles", "trades") for seed in (7, 11)], ids=str
)
def test_every_bar_of_every_timeframe_is_the_same_up_to_the_cut(market: Market) -> None:
    full, _ = market.tape(market.end)
    compared = 0
    for index, cut in enumerate(_bar_cuts(market)):
        for other, _ in (market.truncated(cut), market.perturbed(cut, 303 + index)):
            for minutes in TIMEFRAMES:
                mine = [bar for bar in full.frame(minutes) if bar.close_us + DELAY_US <= cut]
                theirs = [bar for bar in other.frame(minutes) if bar.close_us + DELAY_US <= cut]
                assert [_as_compared(bar) for bar in mine] == [_as_compared(bar) for bar in theirs], (
                    f"{market} {minutes}m at {cut}"
                )
                compared += len(mine)
    assert compared > 100_000


def test_a_late_gap_on_a_bar_with_no_gap_is_compared() -> None:
    """The exception above must not hide a late flag on a bar that is not a gap."""
    bar = _hand_bar(gap=False, late_gap=True)
    assert _as_compared(bar) != _as_compared(dataclasses.replace(bar, late_gap=False))
    gap_bar = _hand_bar(gap=True, late_gap=True)
    assert _as_compared(gap_bar) == _as_compared(dataclasses.replace(gap_bar, late_gap=False))


def _hand_bar(*, gap: bool, late_gap: bool) -> Bar:
    return Bar(
        index=0,
        minutes=60,
        open_us=START,
        close_us=START + 60 * MINUTE,
        o=100.0,
        h=101.0,
        l=99.0,
        c=100.0,
        v=1.0,
        has_price=True,
        complete=False,
        pending_tail=False,
        gap=gap,
        late_gap=late_gap,
        tr=None,
        atr=None,
        atr_last=None,
        vr=None,
        srv=None,
        clv=0.5,
        atrd=None,
        day=None,
        week=None,
        day_at_close=None,
        week_at_close=None,
        day_open=None,
    )
