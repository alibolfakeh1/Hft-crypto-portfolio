"""C16's dated tick and C7's trade-through margin, as amended at ecc5e49. Every price here is invented.

A price is rounded with the tick in force when it is set: the setup's `S0` and targets, each stop and target
update and `BE+` at their decision close, and a target computed from the fill at the fill. A price set before
a change keeps its value. An update is rounded before C8 compares it, so a coarser tick never loosens a stop.
A target fills on a trade through it by its own `tick_i`. The change instant is BTCUSDT's, 2022-02-15 03:30
UTC.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, ClassVar

import numpy as np
import polars as pl
import pytest

from engine_helpers import DELAY_US, REPO_ROOT, costs, sim_params, utc
from hft_crypto.bars.core import TimingContractError
from hft_crypto.config import ConfigError
from hft_crypto.engine.config import DateRange, TickTable, load_engine_config, parse_engine_config
from hft_crypto.engine.exits import ratchet
from hft_crypto.engine.fills import round_to_tick, tick_at, traded_through
from hft_crypto.engine.market import MarketView, TradeSlice
from hft_crypto.engine.simulator import Simulator, StreamResult
from hft_crypto.engine.tape import Bar, MinuteTape
from hft_crypto.strategies.base import (
    REST,
    Management,
    PositionView,
    Proposal,
    StopCandidate,
    Strategy,
    TargetMove,
    TargetPlan,
)
from hft_crypto.strategies.s08_volume_profile_value_area import S08VolumeProfileValueArea, value_area

DAY0 = utc(2022, 2, 15)
MINUTE = 60_000_000
HOUR = 60 * MINUTE
CHANGE = utc(2022, 2, 15, 3, 30)
BTC = TickTable((utc(2020, 1, 1), CHANGE), (0.01, 0.1))
UTC_US = pl.Datetime("us", "UTC")


# ---- the table and the configuration -----------------------------------------------------------------------


def test_the_tick_in_force_before_at_and_after_the_change() -> None:
    assert BTC.at(CHANGE - 1) == 0.01
    assert BTC.at(CHANGE) == 0.1
    assert BTC.at(CHANGE + 1) == 0.1
    assert BTC.at(utc(2020, 1, 1)) == 0.01
    with pytest.raises(ConfigError, match="before the first row"):
        BTC.at(utc(2020, 1, 1) - 1)
    assert tick_at(0.01, CHANGE) == 0.01
    assert tick_at(BTC, CHANGE) == 0.1


def test_rounding_with_the_tick_in_force_before_at_and_after_the_instant() -> None:
    """A long stop or target rounds down, a short one up, each with `tick(t)`."""
    for moment, long_s0, short_s0 in (
        (CHANGE - HOUR, 90.03, 110.04),
        (CHANGE, 90.0, 110.1),
        (CHANGE + HOUR, 90.0, 110.1),
    ):
        tick = BTC.at(moment)
        assert round_to_tick(90.037, 1, tick) == long_s0
        assert round_to_tick(110.031, -1, tick) == short_s0


def _generated_raw() -> dict[str, Any]:
    with (REPO_ROOT / "configs" / "engine_generated.toml").open("rb") as handle:
        return tomllib.load(handle)


def _with_btc_ticks(rows: Any) -> dict[str, Any]:
    raw = _generated_raw()
    raw["ticks"]["SYNTHBTC"] = rows
    return raw


def test_a_plain_number_and_a_dated_table_are_both_valid() -> None:
    plain = parse_engine_config(_generated_raw())
    assert plain.tick("SYNTHBTC").at(0) == 0.01
    dated = parse_engine_config(
        _with_btc_ticks(
            [{"from": "2020-01-01T00:00:00Z", "tick": 0.01}, {"from": "2022-02-15T03:30:00Z", "tick": 0.1}]
        )
    )
    assert dated.tick("SYNTHBTC") == BTC


def test_the_market_configuration_holds_the_venue_s_dated_table() -> None:
    engine = load_engine_config(REPO_ROOT / "configs" / "engine.toml")
    assert engine.tick("BTCUSDT") == BTC
    assert engine.tick("ETHUSDT") == TickTable((utc(2020, 1, 1),), (0.01,))
    engine.check_ticks_cover(DateRange(dt.date(2020, 1, 1), dt.date(2023, 12, 31)))


@pytest.mark.parametrize(
    ("rows", "words"),
    [
        (
            [{"from": "2022-02-15T03:30:00Z", "tick": 0.1}, {"from": "2020-01-01T00:00:00Z", "tick": 0.01}],
            "time order",
        ),
        (
            [{"from": "2020-01-01T00:00:00Z", "tick": 0.01}, {"from": "2020-01-01T00:00:00Z", "tick": 0.1}],
            "time order",
        ),
        ([{"from": "2020-01-01T00:00:00Z", "tick": 0.0}], "out of range"),
        ([{"from": "2020-01-01T00:00:00Z", "tick": -0.01}], "out of range"),
        ([{"from": "2020-01-01T00:00:00Z", "tick": True}], "must be a number"),
        ([{"from": "2020-01-01T00:00:00", "tick": 0.01}], "ending in Z"),
        ([{"from": "soon Z", "tick": 0.01}], "not an instant"),
        ([{"from": "2020-01-01T00:00:00Z"}], "required"),
        ([{"from": "2020-01-01T00:00:00Z", "tick": 0.01, "note": "x"}], "unknown keys"),
        ([], "at least one row"),
        (0, "out of range"),
    ],
    ids=[
        "unsorted",
        "duplicate",
        "zero",
        "negative",
        "not a number",
        "not UTC",
        "not an instant",
        "no tick",
        "unknown key",
        "empty",
        "plain zero",
    ],
)
def test_a_tick_table_is_refused_when_it_is_malformed(rows: Any, words: str) -> None:
    with pytest.raises(ConfigError, match=words):
        parse_engine_config(_with_btc_ticks(rows))


def test_a_range_starting_before_the_first_row_is_refused() -> None:
    engine = parse_engine_config(_with_btc_ticks([{"from": "2020-01-02T00:00:00Z", "tick": 0.01}]))
    with pytest.raises(ConfigError, match="before the first row of the tick table"):
        engine.check_ticks_cover(DateRange(dt.date(2020, 1, 1), dt.date(2020, 1, 5)))
    engine.check_ticks_cover(DateRange(dt.date(2020, 1, 2), dt.date(2020, 1, 5)))


# ---- rule 9: a coarser tick never loosens a stop -----------------------------------------------------------


def test_rule_9_an_update_rounded_at_the_coarser_tick_never_loosens_the_stop() -> None:
    """A long stop of 90.03, set at 0.01. After the change a candidate of 90.07 rounds down to 90.0, below the
    stop in force, so the stop stays. 90.17 rounds to 90.1 and moves it. A short mirrors it.
    """
    stay = ratchet(
        side=1, old_stop=90.03, candidates=[StopCandidate(90.07, "T")], close=100.0, atr=2.0, tick=0.1
    )
    assert (stay.stop, stay.reason) == (90.03, None)
    move = ratchet(
        side=1, old_stop=90.03, candidates=[StopCandidate(90.17, "T")], close=100.0, atr=2.0, tick=0.1
    )
    assert (move.stop, move.reason) == (90.1, "T")
    short = ratchet(
        side=-1, old_stop=109.97, candidates=[StopCandidate(109.93, "T")], close=100.0, atr=2.0, tick=0.1
    )
    assert (short.stop, short.reason) == (109.97, None)


# ---- through the simulator ---------------------------------------------------------------------------------


class _Script(Strategy):
    """30m bars. Proposes once at `enter_at`, asks for stops and target moves at named closes, and writes down
    the `BE+` it is shown at each close."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {30: 1000.0}

    def __init__(
        self,
        enter_at: int,
        *,
        side: int = 1,
        s0: float = 90.037,
        targets: tuple[float | None, ...] = (None,),
        stops: dict[int, float] | None = None,
        moves: dict[int, float] | None = None,
        from_fill: float | None = None,
    ) -> None:
        super().__init__({"timeframe_minutes": 30})
        self.enter_at = enter_at
        self.side = side
        self.s0 = s0
        self.targets = targets
        self.stops = stops or {}
        self.moves = moves or {}
        self.from_fill = from_fill
        self.seen_be_plus: dict[int, float] = {}

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.enter_at:
            return []
        plans = tuple(TargetPlan(f"T{index + 1}", price, REST) for index, price in enumerate(self.targets))
        return [Proposal(self.side, self.s0, plans, {}, 4, None)]

    def on_fill(self, position: PositionView) -> list[TargetMove]:
        if self.from_fill is None:
            return []
        return [TargetMove("T1", position.side * (position.fill_side + self.from_fill * position.r), "FILL")]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        self.seen_be_plus[market.now_us] = position.be_plus
        decision = Management()
        if market.now_us in self.stops:
            decision.stops.append(StopCandidate(self.stops[market.now_us], "TEST_TRAIL"))
        if market.now_us in self.moves:
            decision.targets.append(TargetMove("T1", self.moves[market.now_us], "TEST_MOVE"))
        return decision


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [
            replace(bar, atr=2.0, atr_last=2.0, complete=True, gap=False) for bar in self.tape.frame(minutes)
        ]


def _tape(hours: int, rows: dict[int, tuple[float, float, float, float]] | None = None) -> MinuteTape:
    """Minutes from 00:00 at 100, high 100.5 and low 99.5, with named minutes given as (o, h, l, c)."""
    rows = rows or {}
    opens = [DAY0 + index * MINUTE for index in range(hours * 60)]
    values = [rows.get(index, (100.0, 100.5, 99.5, 100.0)) for index in range(hours * 60)]
    frame = pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(UTC_US),
            "open": [item[0] for item in values],
            "high": [item[1] for item in values],
            "low": [item[2] for item in values],
            "close": [item[3] for item in values],
            "volume": [10.0] * len(opens),
            "trade_count": [5] * len(opens),
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(UTC_US),
        }
    )
    return MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)


def _run(
    strategy: Strategy, tape: MinuteTape, *, tick: float | TickTable = BTC, rt_bps: float = 0.0
) -> StreamResult:
    params = sim_params(
        risk_budget=100.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        tick=tick,  # type: ignore[arg-type]
        cost=costs(rt_bps=rt_bps, slip_bps=rt_bps / 12.0, stop_slip_bps=0.0),
    )
    return _FlatAtr(strategy, tape, params).run()


def _minute(hour: int, minute: int = 0) -> int:
    """The index of a minute row from 00:00."""
    return hour * 60 + minute


@pytest.mark.parametrize(
    ("enter_at", "long_s0", "short_s0", "t1"),
    [
        (CHANGE - 30 * MINUTE, 90.03, 110.04, 110.03),
        (CHANGE, 90.0, 110.1, 110.0),
        (CHANGE + 30 * MINUTE, 90.0, 110.1, 110.0),
    ],
    ids=["before", "at", "after"],
)
def test_a_setup_s_stop_and_target_are_rounded_with_the_tick_at_its_decision(
    enter_at: int, long_s0: float, short_s0: float, t1: float
) -> None:
    tape = _tape(8)
    long = _run(_Script(enter_at, targets=(110.037,)), tape)
    created = next(event for event in long.events if event["type"] == "SETUP_CREATED")
    assert (created["s0"], created["targets"][0][1]) == (long_s0, t1)
    short = _run(_Script(enter_at, side=-1, s0=110.031, targets=(89.961,)), tape)
    created = next(event for event in short.events if event["type"] == "SETUP_CREATED")
    assert created["s0"] == short_s0
    assert created["targets"][0][1] == (89.97 if enter_at < CHANGE else 90.0)


def test_a_stop_set_before_the_change_keeps_its_value_after_it() -> None:
    """S0 90.03, set at 03:00 at 0.01. At 05:00 a low of exactly 90.03 stops the trade at 90.03. Rounded again
    at 0.1 it would read 90.0, and that low would not reach it.
    """
    tape = _tape(8, {_minute(5): (100.0, 100.5, 90.03, 100.0)})
    trade = _run(_Script(CHANGE - 30 * MINUTE), tape).trades[0]
    assert trade.s0 == 90.03
    assert (trade.exit_reason, trade.legs[-1].reference) == ("STOP", 90.03)


def test_rule_9_across_the_change_in_the_simulator() -> None:
    """The stop of 90.03 rests across 03:30. At 04:00 a candidate of 90.07 rounds to 90.0 at the new tick, and
    the stop stays. At 04:30 a candidate of 90.17 rounds to 90.1, and the stop moves up to it."""
    tape = _tape(8)
    stream = _run(
        _Script(CHANGE - 30 * MINUTE, stops={CHANGE + 30 * MINUTE: 90.07, CHANGE + HOUR: 90.17}), tape
    )
    path = stream.trades[0].stop_path
    assert [(row["computed_at_us"], row["old"], row["new"]) for row in path] == [(CHANGE + HOUR, 90.03, 90.1)]
    stops = [stream.trades[0].s0, *(row["new"] for row in path)]
    assert stops == sorted(stops)


def test_be_plus_is_rounded_at_each_decision_with_that_close_s_tick() -> None:
    """RT 12 bp and slip 1 bp: the fill is 100 * 1.0001 = 100.01, and `BE+` is 100.01 * 1.0012 = 100.130012. A
    long rounds it down: 100.13 at 0.01 before 03:30 and 100.1 from then on."""
    strategy = _Script(utc(2022, 2, 15, 2, 0))
    _run(strategy, _tape(6), rt_bps=12.0)
    seen = strategy.seen_be_plus
    assert seen[utc(2022, 2, 15, 2, 30)] == 100.13
    assert seen[utc(2022, 2, 15, 3, 0)] == 100.13
    assert seen[CHANGE] == 100.1
    assert seen[CHANGE + 30 * MINUTE] == 100.1


@pytest.mark.parametrize(("enter_at", "target"), [(utc(2022, 2, 15, 2, 0), 112.34), (CHANGE, 112.3)])
def test_a_target_computed_from_the_fill_is_rounded_with_the_tick_at_the_fill(
    enter_at: int, target: float
) -> None:
    """S0 90.0 and a fill at 100, so `R` is 10, and `fill + 1.2345 R` is 112.345. The fill at 02:01 rounds it
    at 0.01, and the fill at 03:31 at 0.1."""
    stream = _run(_Script(enter_at, s0=90.0, from_fill=1.2345), _tape(6))
    row = stream.trades[0].target_path[0]
    assert (row["name"], row["new"]) == ("T1", target)


def test_a_target_from_the_fill_takes_the_fill_s_tick_and_not_the_decision_s() -> None:
    """A made-up change 30 s after the 03:30 close, so the decision is at 0.01 and the fill at 03:31 at 0.1.
    `S0` 90.037 is set at the decision, so 90.03, and `R` is 100 - 90.03 = 9.97. `fill + 1.3 R` is 112.961:
    112.9 at the fill's tick, where the decision's would give 112.96.
    """
    straddle = TickTable((utc(2020, 1, 1), CHANGE + 30_000_000), (0.01, 0.1))
    stream = _run(_Script(CHANGE, from_fill=1.3), _tape(6), tick=straddle)
    trade = stream.trades[0]
    assert trade.s0 == 90.03
    assert trade.target_path[0]["new"] == 112.9


# ---- C7: a target fills on a trade through it by its own tick ----------------------------------------------


@pytest.mark.parametrize(
    ("side", "extreme", "fills"),
    [(1, 101.01, True), (1, 101.005, False), (-1, 98.99, True), (-1, 98.995, False)],
    ids=["long one tick", "long half a tick", "short one tick", "short half a tick"],
)
def test_a_target_fills_one_tick_through_and_not_half_a_tick(side: int, extreme: float, fills: bool) -> None:
    """One tick of 0.01 throughout. A long target of 101 and a short one of 99, set at the 02:00 setup."""
    target = 101.0 if side > 0 else 99.0
    row = (100.0, extreme, 99.5, 100.0) if side > 0 else (100.0, 100.5, extreme, 100.0)
    tape = _tape(6, {_minute(4): row})
    trade = _run(
        _Script(utc(2022, 2, 15, 2, 0), side=side, s0=90.0 if side > 0 else 110.0, targets=(target,)),
        tape,
        tick=0.01,
    ).trades[0]
    if fills:
        assert (trade.exit_reason, trade.legs[-1].reference, trade.legs[-1].price) == (
            "TARGET_T1",
            target,
            target,
        )
    else:
        assert trade.status == "open"


def test_a_target_set_at_0_01_before_the_change_keeps_its_own_tick_after_it() -> None:
    """BTCUSDT. T1 101.03 is set at 03:00 at 0.01. At 05:00 a high of 101.04 is one of its own ticks through,
    so it fills, though the tick in force is then 0.1."""
    tape = _tape(8, {_minute(5): (100.0, 101.04, 99.5, 100.0)})
    trade = _run(_Script(CHANGE - 30 * MINUTE, s0=90.0, targets=(101.03,)), tape).trades[0]
    assert (trade.exit_reason, trade.legs[-1].reference) == ("TARGET_T1", 101.03)


@pytest.mark.parametrize(("high", "fills"), [(101.15, False), (101.2, True)])
def test_a_target_set_after_the_change_needs_a_whole_0_1_through(high: float, fills: bool) -> None:
    """T1 101.1 is set at 04:00 at 0.1. A high of 101.15, off the new grid and 0.05 through, does not fill it.
    101.2 does."""
    tape = _tape(8, {_minute(5): (100.0, high, 99.5, 100.0)})
    trade = _run(_Script(CHANGE + 30 * MINUTE, s0=90.0, targets=(101.1,)), tape).trades[0]
    assert (trade.status == "closed") is fills


def test_a_target_moved_after_the_change_takes_the_new_tick_as_its_own() -> None:
    """T1 101.03 set at 03:00, moved at 04:00 to 101.17, which rounds down to 101.1 at 0.1. A high of 101.15
    at 05:00 is 0.05 through, short of the moved target's own tick, so it does not fill."""
    tape = _tape(8, {_minute(5): (100.0, 101.15, 99.5, 100.0)})
    stream = _run(
        _Script(CHANGE - 30 * MINUTE, s0=90.0, targets=(101.03,), moves={CHANGE + 30 * MINUTE: 101.17}), tape
    )
    trade = stream.trades[0]
    assert [row["new"] for row in trade.target_path] == [101.1]
    assert trade.status == "open"


def test_traded_through_holds_against_binary_error() -> None:
    """At BTC prices one tick of 0.1 through is never missed in binary, and a hair short never fills."""
    for target in (40_000.1, 61_234.5, 69_000.0):
        assert traded_through(round(target + 0.1, 1), target, 0.1)
        assert not traded_through(target + 0.09, target, 0.1)
        assert not traded_through(target + 0.05, target, 0.1)


# ---- S08: the profile's tick is the one at its end ---------------------------------------------------------


def test_the_view_gives_the_tick_at_its_close_and_at_any_earlier_instant_only() -> None:
    view = MarketView(symbol="BTCUSDT", tick=BTC, rt=0.0012, minutes=60, higher=(), trades=None)
    view.now_us = CHANGE + HOUR
    assert view.tick == 0.1
    assert view.tick_at(CHANGE - HOUR) == 0.01
    with pytest.raises(TimingContractError):
        view.tick_at(CHANGE + 2 * HOUR)


def test_s08_bins_a_profile_with_the_tick_in_force_at_its_end() -> None:
    """A day ending at 00:00 on the 15th, read at a close after the change. Prices near 10, so the bin width
    is the tick: 0.01 at the profile's end, where the close's 0.1 would bin 10.01 and 10.04 together."""
    trades = TradeSlice(np.array([10.01, 10.04, 10.13, 10.27]), np.array([5.0, 3.0, 1.0, 1.0]))
    end = DAY0
    strategy = S08VolumeProfileValueArea({"timeframe_minutes": 60, "profile_days": 1})
    strategy._complete.add(end)
    strategy._placed = lambda area, _bar: area  # type: ignore[method-assign]
    market = SimpleNamespace(
        bar=None,
        tick=BTC.at(CHANGE + HOUR),
        tick_at=BTC.at,
        trades_between=lambda _after, _through: trades,
    )
    area = strategy._area_ending(market, end)  # type: ignore[arg-type]
    assert area == value_area(trades, 0.01)
    assert area != value_area(trades, 0.1)
