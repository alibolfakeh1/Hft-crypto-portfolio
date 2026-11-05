"""C15 placebos, on generated data, with expected values worked out by hand in each test."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import random
from collections.abc import Iterator
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from engine_helpers import (
    DAY,
    GENERATED_CONFIG,
    default_only_config,
    engine_config,
    generated_trades,
    run_stream,
    sim_params,
    tape_and_trades,
    utc,
    write_generated_root,
)
from hft_crypto.config import ConfigError
from hft_crypto.data.zones import DataRoot
from hft_crypto.engine.accounting import Booked
from hft_crypto.engine.config import DateRange, load_engine_config, parse_engine_config
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.placebo import (
    FIRST_QUARTER,
    METHODS,
    STATUS_NOT_RUN,
    DrawStat,
    MeanResult,
    PlaceboResult,
    QuarterRow,
    build_plan,
    draw_anchors,
    draw_entries,
    draw_seed,
    mean_result_b,
    rank_among,
    run_placebos,
    simulate_draw,
)
from hft_crypto.engine.registry import REGISTRY_PATH, TrialRegistry, trial_row
from hft_crypto.engine.run import run_engine
from hft_crypto.engine.simulator import Simulator, SymbolData
from hft_crypto.engine.tape import Bar, PeriodBar
from hft_crypto.reports.placebo import placebo_row
from hft_crypto.strategies import available_strategies, build_level_strategy, strategy_class
from hft_crypto.strategies.levels import floor_pivots
from hft_crypto.strategies.placebo import S03Placebo, S09Placebo, S10Placebo, _DrawnSwings
from hft_crypto.strategies.registers import HIGH, LOW, Swing
from hft_crypto.strategies.s03_market_structure import BOS, S03MarketStructure
from hft_crypto.strategies.s03_market_structure import _Memo as S03Memo
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim
from hft_crypto.strategies.s08_volume_profile_value_area import S08VolumeProfileValueArea, ValueArea
from hft_crypto.strategies.s09_session_range_breakout import HOUR, SeasonalProfile
from hft_crypto.strategies.sources import (
    ATR_UNDEFINED_AT_BIRTH,
    NO_EARLIER_BLOCK,
    Birth,
    DistancePool,
    PlaceboSource,
    RecordingSource,
    quarter_name,
    quarter_of,
    sample_without_replacement,
)
from hft_crypto.strategies.v0s import VARIANT_V0S
from hft_crypto.strategies.zones import Zone, ZoneBook

Q1 = utc(2000, 2, 1)
Q2 = utc(2000, 4, 3)
Q3 = utc(2000, 7, 3)
LEVEL_STRATEGIES = ("S01", "S02", "S04", "S05", "S06", "S08")


def _bar(
    close_us: int,
    c: float,
    *,
    atr: float | None = 10.0,
    o: float | None = None,
    h: float | None = None,
    l: float | None = None,  # noqa: E741
    index: int = 0,
    srv: float | None = 1.5,
    gap: bool = False,
    minutes: int = 60,
) -> Bar:
    high = c if h is None else h
    low = c if l is None else l
    return Bar(
        index=index,
        minutes=minutes,
        open_us=close_us - minutes * 60_000_000,
        close_us=close_us,
        o=c if o is None else o,
        h=high,
        l=low,
        c=c,
        v=1.0,
        has_price=True,
        complete=not gap,
        pending_tail=False,
        gap=gap,
        late_gap=False,
        tr=high - low,
        atr=atr,
        atr_last=atr,
        vr=1.0,
        srv=srv,
        clv=(c - low) / (high - low) if high != low else 0.5,
        atrd=None,
        day=None,
        week=None,
        day_at_close=None,
        week_at_close=None,
        day_open=None,
    )


def _pool(*births: Birth) -> DistancePool:
    return DistancePool(list(births))


def _source(*births: Birth, seed: int = 1) -> PlaceboSource:
    return PlaceboSource(_pool(*births), random.Random(seed))


# ---- seeds, blocks and ranks ------------------------------------------------------------------------------


def test_a_draw_s_seed_is_the_first_eight_bytes_of_the_hash_of_its_identity() -> None:
    """The expected values come from `sha256sum`, run outside this code on the same text."""
    assert draw_seed("S01", "BTCUSDT", "level_set=full,timeframe_minutes=15,touch_limit=1", 1) == int(
        "a6dfc19fea9938c0", 16
    )
    assert draw_seed("S03", "ETHUSDT", "max_bos=2,swing=5/3,timeframe_minutes=60", 200) == int(
        "e9e78e24ccb1c293", 16
    )


def test_a_quarter_starts_on_its_first_instant() -> None:
    assert quarter_name(quarter_of(utc(2020, 3, 31, 23, 59))) == "2020-Q1"
    assert quarter_name(quarter_of(utc(2020, 4, 1))) == "2020-Q2"
    assert quarter_name(quarter_of(utc(2020, 12, 31))) == "2020-Q4"
    assert quarter_name(quarter_of(utc(2021, 1, 1))) == "2021-Q1"


def test_the_rank_counts_draws_at_or_above_so_a_tie_goes_against_the_real_line() -> None:
    assert rank_among(0.9, [0.1, 0.2, 0.3]) == 1
    assert rank_among(0.2, [0.1, 0.2, 0.3]) == 3
    assert rank_among(0.0, [0.1, 0.2, 0.3]) == 4
    assert rank_among(0.5, []) == 1


def test_sampling_rests_on_random_alone() -> None:
    """`Random(1).random()` gives 0.1343..., then 0.8474... From four items that picks index 0, then 1 + 2."""
    assert sample_without_replacement(random.Random(1), [10, 20, 30, 40], 2) == [10, 40]
    assert sample_without_replacement(random.Random(1), [10, 20], 5) == [10, 20]


# ---- level sources ----------------------------------------------------------------------------------------


def test_recording_keeps_the_real_value_and_notes_a_signed_distance_in_atr_units() -> None:
    source = RecordingSource()
    bar = _bar(Q1, 100.0, atr=2.0)
    assert source.vector("D", {"P": 104.0, "S1": 97.0}, bar) == {"P": 104.0, "S1": 97.0}
    assert source.births == [Birth("D", Q1, {"P": 2.0, "S1": -1.5})]


def test_a_level_with_no_atr_at_its_birth_gives_no_distance() -> None:
    source = RecordingSource()
    assert source.vector("D", {"P": 104.0}, _bar(Q1, 100.0, atr=None)) == {"P": 104.0}
    assert source.births == []
    placebo = _source(Birth("D", Q1, {"P": 1.0}))
    assert placebo.vector("D", {"P": 104.0}, _bar(Q2, 100.0, atr=None)) is None
    assert placebo.missing == {ATR_UNDEFINED_AT_BIRTH: 1}


def test_a_set_draws_one_earlier_vector_whole_so_it_keeps_its_order_and_spacing() -> None:
    """Close 200 and ATR 5 turn the distances -1, 0.5 and 2 into 195, 202.5 and 210."""
    source = _source(Birth("D", Q1, {"S1": -1.0, "P": 0.5, "R1": 2.0}))
    real = {"S1": 1.0, "P": 2.0, "R1": 3.0}
    assert source.vector("D", real, _bar(Q2, 200.0, atr=5.0)) == {"S1": 195.0, "P": 202.5, "R1": 210.0}


def test_only_an_earlier_quarter_can_be_drawn() -> None:
    source = _source(
        Birth("D", Q1, {"P": 1.0}),
        Birth("D", Q2, {"P": 99.0}),
        Birth("D", Q3, {"P": 1000.0}),
    )
    assert source.vector("D", {"P": 0.0}, _bar(Q1 + DAY, 0.0)) is None
    assert source.missing == {NO_EARLIER_BLOCK: 1}
    in_q2 = {_placed(source, Q2 + DAY) for _ in range(200)}
    assert in_q2 == {10.0}  # 1.0 * ATR 10, never the row born in this same quarter
    in_q3 = {_placed(source, Q3 + DAY) for _ in range(200)}
    assert in_q3 == {10.0, 990.0}  # both earlier rows are reached, and never the later one


def _placed(source: PlaceboSource, close_us: int) -> float:
    placed = source.vector("D", {"P": 0.0}, _bar(close_us, 0.0))
    assert placed is not None
    return placed["P"]


def test_kinds_are_not_pooled() -> None:
    source = _source(Birth("SWING:L", Q1, {"price": -3.0}), Birth("SWING:H", Q1, {"price": 3.0}))
    bar = _bar(Q2, 100.0, atr=1.0)
    assert {source.vector("SWING:L", {"price": 0.0}, bar)["price"] for _ in range(50)} == {97.0}  # type: ignore[index]
    assert {source.vector("SWING:H", {"price": 0.0}, bar)["price"] for _ in range(50)} == {103.0}  # type: ignore[index]
    assert source.vector("D", {"P": 0.0}, bar) is None


def test_a_pivot_set_is_fixed_at_its_first_close_and_replaces_the_real_levels() -> None:
    """The set is drawn once, at the roll, from the close then, and a later close reads the same prices."""
    source = _source(Birth("D", Q1, {name: float(place) for place, name in enumerate(floor_pivots(_day()))}))
    strategy = build_level_strategy(
        "S01", {"timeframe_minutes": 15, "touch_limit": 1, "level_set": "daily_core"}, source
    )
    first = replace(_bar(Q2, 500.0, atr=2.0), day_at_close=_day())
    strategy.sets.observe(first)  # type: ignore[attr-defined]
    later = replace(_bar(Q2 + HOUR, 900.0, atr=7.0), day=_day())
    levels = strategy.sets.levels("D", later.day, ("P", "R1", "S1"), later)  # type: ignore[attr-defined]
    # Places in the set are P 0, R1 1, S1 2, so the prices are 500, 502 and 504.
    assert [level.price for level in levels] == [500.0, 502.0, 504.0]


def _day() -> PeriodBar:
    return PeriodBar(Q2 - DAY, Q2, 100.0, 110.0, 90.0, 105.0)


def test_s02_target_only_levels_are_replaced_too() -> None:
    names = list(floor_pivots(_day()))
    source = _source(Birth("D", Q1, {name: 1.0 + place for place, name in enumerate(names)}))
    strategy = build_level_strategy(
        "S02", {"timeframe_minutes": 60, "acc": 3, "weekly_levels": False}, source
    )
    bar = replace(_bar(Q2, 1000.0, atr=1.0), day_at_close=_day())
    strategy.sets.observe(bar)  # type: ignore[attr-defined]
    prices = strategy._target_prices(_day(), None, 1, bar)  # type: ignore[attr-defined]
    real = set(floor_pivots(_day()).values())
    assert not real.intersection(prices)
    # R3 is the sixth name, so its distance is 6, and 1000 + 6 * 1. It is the one target-only level on a long.
    assert 1006.0 in prices


def test_s06_a_day_s_low_and_high_draw_together_and_a_swing_draws_alone() -> None:
    source = _source(Birth("D", Q1, {"L": -2.0, "H": 3.0}), Birth("SWING:L", Q1, {"price": -4.0}))
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": True}, source)
    bar = replace(_bar(Q2, 100.0, atr=2.0, minutes=15), day_at_close=_day())
    assert strategy.sets.at("D", _day(), bar) == {"L": 96.0, "H": 106.0}
    placed = source.vector("SWING:L", {"price": 1.0}, bar)
    assert placed == {"price": 92.0}


# ---- bands ------------------------------------------------------------------------------------------------

_ARRIVAL = [(3250, 3252, 3238, 3240), (3240, 3242, 3225, 3228), (3228, 3230, 3208, 3210)]
_BASE = [(3205, 3212, 3198, 3204), (3204, 3209, 3196, 3207), (3207, 3213, 3201, 3205)]
_DEPARTURE = [(3205, 3232, 3203, 3230), (3230, 3256, 3228, 3252)]


def _zone_bars() -> list[Bar]:
    return [
        _bar(Q2 + index * HOUR, float(c), atr=20.0, o=float(o), h=float(h), l=float(low), index=index)
        for index, (o, h, low, c) in enumerate([*_ARRIVAL, *_BASE, *_DEPARTURE])
    ]


def test_a_zone_moves_as_one_band_and_keeps_its_real_width_and_scores() -> None:
    """S04 7.12's zone: prox 3207, dist 3196, born at close 3252 with ATR 20. A distance of -2 puts prox at
    3212, and its real width of 11 puts dist at 3201. Stack and entry lists hold the same band.
    """
    source = _source(Birth("ZONE:1", Q1, {"prox": -2.0}))
    book = ZoneBook(60, source)
    bars = _zone_bars()
    for end in range(1, len(bars) + 1):
        book.update(bars[:end])
    entry = [zone for zone in book.entry if zone.side == 1]
    stack = [zone for zone in book.stack if zone.side == 1]
    assert [(zone.prox, zone.dist) for zone in entry] == [(3212.0, 3201.0)]
    assert [(zone.prox, zone.dist) for zone in stack] == [(3212.0, 3201.0)]
    assert entry[0].departure == pytest.approx(0.75)
    assert entry[0].tightness == pytest.approx(1.0 - 11.0 / 30.0)


def test_with_no_earlier_distance_no_zone_exists() -> None:
    book = ZoneBook(60, _source())
    bars = _zone_bars()
    for end in range(1, len(bars) + 1):
        book.update(bars[:end])
    assert book.entry == []
    assert book.stack == []


def test_a_flip_is_a_band_of_the_real_width_drawn_at_the_break() -> None:
    """A supply zone 100 to 110 breaks upward at close 120, ATR 10. A distance of 1.5 puts `top` at 135, and
    the real width of 10 puts `bottom` at 125, so `mid` is 130. `X` still comes from the path: the bar's high,
    121.
    """
    source = _source(Birth("FLIP:1", Q1, {"top": 1.5}))
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48}, source)
    zone = Zone("E:-1:1", -1, 100.0, 110.0, 10.0, 1.0, 1.0, 0, Q2 - HOUR, 0, True)
    strategy.book.broken_now = [zone]
    strategy._new_flips(_bar(Q2, 120.0, o=112.0, h=121.0, l=111.0, index=1))
    flip = strategy.flips[0]
    assert (flip.top, flip.bottom, flip.mid, flip.extreme) == (135.0, 125.0, 130.0, 121.0)


def test_a_value_area_moves_whole_so_its_poc_keeps_its_place() -> None:
    """Middle 105 goes to 200 + (-1) * 10 = 190, a move of 85. POC is 40% into the band before and after."""
    source = _source(Birth("VALUE_AREA", Q1, {"middle": -1.0}))
    strategy = S08VolumeProfileValueArea({"timeframe_minutes": 60, "profile_days": 1}, source)
    moved = strategy._placed(ValueArea(poc=104.0, vah=110.0, val=100.0), _bar(Q2, 200.0))
    assert moved == ValueArea(poc=189.0, vah=195.0, val=185.0)
    assert moved is not None
    assert (moved.poc - moved.val) / moved.vaw == pytest.approx((104.0 - 100.0) / 10.0)


# ---- S03 and S10 ------------------------------------------------------------------------------------------


def _market(minutes: int, higher: tuple[int, ...] = ()) -> MarketView:
    return MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=minutes, higher=higher, trades=None)


def test_s03_the_placebo_stop_comes_from_the_list_and_its_targets_are_the_section_10_fallback() -> None:
    """Close 100, ATR 10, VR 1, swing low 90: struct = 90 - 0.30 * 10 = 87, and C - R_min = 90, so S0 = 87 and
    the distance is 13. T1 = 100 + 1.5 * 13 = 119.5 and T2 = 100 + 3 * 13 = 139. The short mirrors it from a
    swing high at 110: S0 = 113, T1 = 80.5, T2 = 61.
    """
    params = {"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2}
    bar = _bar(Q2, 100.0)
    for side, swing, expected in (
        (1, Swing(LOW, 90.0, 0, 0, Q2 - HOUR), (87.0, 119.5, 139.0)),
        (-1, Swing(HIGH, 110.0, 0, 0, Q2 - HOUR), (113.0, 80.5, 61.0)),
    ):
        strategy = S03Placebo(params, {Q2: side})
        strategy.sigma.entries.append(swing)
        market = _market(60, (240,))
        market._release(bar, {})
        proposal = strategy.on_close(market)[0]
        assert proposal.side == side
        assert proposal.s0 == pytest.approx(expected[0])
        assert [plan.price for plan in proposal.targets] == pytest.approx(list(expected[1:]))


def test_s03_a_placebo_exits_on_either_break_against_it_and_the_real_rule_does_not() -> None:
    event = [(BOS, -1, Swing(LOW, 90.0, 0, 0, 0))]
    market = cast(Any, SimpleNamespace(bar=_bar(Q2, 100.0)))
    position = cast(
        Any, SimpleNamespace(side=1, memo=S03Memo(), n=1, fill_side=100.0, r=5.0, filled=lambda _: False)
    )
    placebo = S03Placebo({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2}, {})
    placebo.events = list(event)
    assert placebo.manage(market, position).exit_reason == "INVALIDATION"
    real = S03MarketStructure({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2})
    real.events = list(event)
    assert real.manage(market, position).exit_reason is None


class _Compressed(S10Placebo):
    def _rank(self, bars: list[Bar]) -> bool:
        del bars
        return True


def test_s10_the_placebo_uses_the_box_as_of_the_drawn_bar() -> None:
    """Twelve bars from 99 to 101, close 100, ATR 2. Long: BoxH 2, mid 100, R_min 2.5, so S0 = 97.5, and
    T1 = max(101 + 2, 100 + 2 * 2.5) = 105. Short mirrors it: S0 = 102.5 and T1 = max-side 95.
    """
    params = {"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12}
    last = Q2 + 14 * 4 * HOUR
    for side, s0, t1 in ((1, 97.5, 105.0), (-1, 102.5, 95.0)):
        strategy = _Compressed(params, {last: side})
        market = _market(240)
        found: list[Any] = []
        for index in range(15):
            bar = _bar(Q2 + index * 4 * HOUR, 100.0, atr=2.0, h=101.0, l=99.0, index=index, minutes=240)
            market._release(bar, {})
            found = strategy.on_close(market)
        assert found[0].side == side
        assert found[0].s0 == pytest.approx(s0)
        assert found[0].targets[0].price == pytest.approx(t1)


def test_entries_keep_the_real_counts_per_block_and_side_and_use_a_bar_once() -> None:
    eligible = {
        10: {1: [1, 2, 3, 4], -1: [3, 4, 5]},
        11: {1: [7, 8], -1: [7, 8, 9]},
    }
    counts = {10: {1: 2, -1: 2}, 11: {1: 1, -1: 0}}
    for seed in range(50):
        entries = draw_entries(random.Random(seed), eligible, counts)
        assert sum(1 for close, side in entries.items() if side == 1 and close <= 5) == 2
        assert sum(1 for close, side in entries.items() if side == -1 and close <= 5) == 2
        assert sum(1 for close, side in entries.items() if side == 1 and close > 5) == 1
        assert not any(side == -1 and close > 5 for close, side in entries.items())
        for close, side in entries.items():
            quarter = 10 if close <= 5 else 11
            assert close in eligible[quarter][side]


def test_with_too_few_eligible_bars_a_draw_takes_what_there_is_and_does_not_replace() -> None:
    entries = draw_entries(random.Random(3), {10: {1: [1], -1: []}}, {10: {1: 4, -1: 2}})
    assert entries == {1: 1}


# ---- S09 and S07 ------------------------------------------------------------------------------------------


def test_s09_a_shift_runs_from_1_to_23_hours_and_the_whole_schedule_moves_with_it() -> None:
    """Window from 04:00, W 8: end 12:00. Peak hour 16 is 4 hours on, and flat is 11 hours after the end."""
    params = {"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0}
    start = utc(2000, 4, 3, 4)
    seen: set[int] = set()
    for seed in range(400):
        strategy = S09Placebo(params, random.Random(seed))
        strategy._profile = SeasonalProfile(4, 16, 0)
        strategy._start_range(_bar(start + HOUR, 100.0))
        shift = strategy.shifts_hours[0]
        seen.add(shift)
        moved = strategy._waiting[0]
        assert moved.start_us == start + shift * HOUR
        assert moved.end_us == start + (8 + shift) * HOUR
        assert moved.peak_us == start + (12 + shift) * HOUR
        assert moved.flat_us == start + (19 + shift) * HOUR
        assert strategy._ranges == []
    assert seen == set(range(1, 24))


def test_s09_a_moved_window_opens_on_its_own_bar_and_a_missing_first_bar_cancels_it() -> None:
    params = {"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0}
    strategy = S09Placebo(params, random.Random(0))
    strategy._profile = SeasonalProfile(4, 16, 0)
    start = utc(2000, 4, 3, 4)
    strategy._start_range(_bar(start + HOUR, 100.0))
    moved = strategy._waiting[0]
    assert strategy._schedule_from(_bar(moved.start_us + HOUR, 100.0)) is None or strategy.shifts_hours
    strategy._profile = None
    strategy._start_range(_bar(moved.start_us + HOUR, 100.0))
    assert strategy._ranges == [moved]
    assert strategy._waiting == []
    other = S09Placebo(params, random.Random(0))
    other._profile = SeasonalProfile(4, 16, 0)
    other._start_range(_bar(start + HOUR, 100.0))
    gone = other._waiting[0]
    other._profile = None
    other._start_range(_bar(gone.start_us + 2 * HOUR, 100.0))
    assert other._ranges == []
    assert other._waiting == []


def test_s07_anchors_keep_the_real_count_per_side_and_quarter() -> None:
    bars = {10: [1, 2, 3, 4, 5], 11: [6, 7, 8]}
    counts = {10: {LOW: 2, HIGH: 1}, 11: {LOW: 0, HIGH: 3}}
    anchors = draw_anchors(random.Random(5), bars, counts)
    assert sum(1 for close, kind in anchors if kind == LOW and close <= 5) == 2
    assert sum(1 for close, kind in anchors if kind == HIGH and close <= 5) == 1
    assert {close for close, kind in anchors if kind == HIGH and close > 5} == {6, 7, 8}


def test_s07_a_drawn_anchor_becomes_usable_rt_bars_later_at_that_bar_s_extreme() -> None:
    """With `Lf` 2 and `Rt` 1, an anchor on bar 3 is confirmed at bar 4, at bar 3's low, and not before."""
    bars = [
        _bar(Q2 + index * HOUR, 100.0 + index, h=105.0 + index, l=95.0 + index, index=index)
        for index in range(6)
    ]
    swings = _DrawnSwings(2, 1, 2.0, frozenset({(bars[3].close_us, LOW)}))
    added = [
        [(item.kind, item.price, item.valid_from) for item in swings.update(bars[: end + 1])]
        for end in range(6)
    ]
    assert added[3] == []
    assert added[4] == [(LOW, 98.0, bars[4].close_us)]
    assert added[5] == []
    assert swings.latest(LOW) is not None


def test_s07_a_gap_in_the_window_gives_no_anchor_under_c2() -> None:
    bars = [_bar(Q2 + index * HOUR, 100.0, index=index, gap=index == 2) for index in range(6)]
    swings = _DrawnSwings(2, 1, 2.0, frozenset({(bars[3].close_us, LOW)}))
    assert swings.update(bars[:5]) == []


# ---- figures ----------------------------------------------------------------------------------------------


def _trade(signal_us: int, gross: int, net: int) -> Any:
    booked = Booked(gross=gross, slippage=0, fees=gross - net, funding=0, net=net)
    return SimpleNamespace(signal_us=signal_us, risk_budget=250.0, tag=None, book=lambda: ([], booked))


def test_mean_result_b_is_per_trade_over_the_compared_quarters_only() -> None:
    """$250 and -$125 gross on a $250 budget are 1.0 and -0.5, mean 0.25. Net $200 and -$150 are 0.8 and -0.6,
    mean 0.1. The trade signalled in the other quarter is left out.
    """
    trades = [_trade(Q2, 25_000, 20_000), _trade(Q2 + DAY, -12_500, -15_000), _trade(Q1, 999_900, 999_900)]
    mean = mean_result_b(trades, frozenset({quarter_of(Q2)}))
    assert mean.trades == 2
    assert mean.gross_mean == pytest.approx(0.25)
    assert mean.net_mean == pytest.approx(0.1)
    assert mean_result_b(trades, frozenset()) == MeanResult(0, None, None)


def _stat(draw: int, trades: int, gross: float | None, net: float | None) -> DrawStat:
    return DrawStat(
        draw, draw, trades, MeanResult(trades, gross, net), {}, {"skipped_open": 1}, {"STOP_TOO_WIDE": 2}, {}
    )


def test_a_row_ranks_gross_and_net_on_their_own_and_counts_a_draw_with_no_trade() -> None:
    q1, q2 = quarter_of(Q1), quarter_of(Q2)
    result = PlaceboResult(
        strategy="S01",
        symbol="BTC",
        line="line",
        params={},
        swap=METHODS["S01"],
        status="RAN",
        reason=None,
        quarters=(QuarterRow(q1, False, FIRST_QUARTER), QuarterRow(q2, True)),
        real=MeanResult(5, 0.25, -0.1),
        real_by_branch={},
        real_setups_by_quarter={q1: 3, q2: 6},
        real_trades_by_quarter={q1: 2, q2: 5},
        draws=(
            _stat(1, 4, 0.1, 0.2),
            _stat(2, 6, 0.25, -0.3),
            _stat(3, 5, 0.9, -0.1),
            _stat(4, 0, None, None),
        ),
    )
    row = placebo_row(result, "SIMULATED SYNTHETIC")
    assert row["gross_rank"] == 3  # 0.25 and 0.9 are at or above 0.25
    assert row["net_rank"] == 3  # 0.2 and -0.1 are at or above -0.1
    assert row["rank_of"] == 3
    assert row["draws"] == 4
    assert row["draws_with_no_trade"] == 1
    assert row["quarters_without_placebo"] == ["2000-Q1"]
    assert row["real_trades_not_compared"] == 2
    assert row["entries_failed_and_not_replaced"] == {"STOP_TOO_WIDE": 8}
    assert any("2000-Q1 is the first quarter" in note for note in row["notes"])
    assert row["quarters"][1] == {
        "quarter": "2000-Q2",
        "has_placebo": True,
        "reason": None,
        "real_setups": 6,
        "real_trades": 5,
    }


def test_the_entry_placebo_says_what_its_same_block_share_does() -> None:
    result = PlaceboResult(
        "S03", "BTC", "line", {}, METHODS["S03"], "RAN", None, (), MeanResult(0, None, None), {}, {}, {}, ()
    )
    assert any("harder to beat" in note for note in placebo_row(result, "x")["notes"])


# ---- a recording changes nothing ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def market() -> tuple[Any, Any]:
    trades = generated_trades(seed=7, start_us=utc(2000, 1, 3), days=200)
    return tape_and_trades(trades, start_us=utc(2000, 1, 3), through_us=utc(2000, 1, 3) + 200 * DAY)


@lru_cache(maxsize=1)
def _s05_market() -> tuple[Any, Any]:
    trades = generated_trades(seed=13, start_us=utc(2000, 1, 3), days=230)
    return tape_and_trades(trades, start_us=utc(2000, 1, 3), through_us=utc(2000, 1, 3) + 230 * DAY)


@pytest.mark.parametrize("strategy", LEVEL_STRATEGIES)
def test_recording_a_real_run_changes_no_decision(strategy: str, market: tuple[Any, Any]) -> None:
    tape, trades = market
    params = dict(engine_config().strategies[strategy].default().params)
    real = run_stream(strategy, tape, trades)
    recorder = RecordingSource()
    seen = Simulator(
        build_level_strategy(strategy, params, recorder), tape, sim_params(), trades=trades
    ).run()
    assert seen.events == real.events
    assert recorder.births


@pytest.mark.parametrize("strategy", LEVEL_STRATEGIES)
def test_no_real_level_stays_in_a_placebo(strategy: str, market: tuple[Any, Any]) -> None:
    """Every target must differ from the real run's own, on a draw that traded."""
    # S05's flips are rare, so it has a seed picked to give it a flip, and for nothing else.
    tape, trades = _s05_market() if strategy == "S05" else market
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies[strategy].default()
    real = run_stream(strategy, tape, trades)
    plan = build_plan(
        strategy,
        "S",
        line,
        item=item,
        sim=sim_params(),
        quarters=[quarter_of(utc(2000, 1, 3)), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))],
        real=real,
    )
    found, _ = simulate_draw(plan, 1, item)
    real_prices = {
        plan_row.price
        for trade in real.trades
        for plan_row in trade.targets_at_setup
        if plan_row.name == "T1"
    }
    assert found.trades, f"{strategy}: the draw traded nothing, so this test would prove nothing"
    placed = {
        plan_row.price
        for trade in found.trades
        for plan_row in trade.targets_at_setup
        if plan_row.name == "T1"
    }
    assert placed != real_prices
    assert all(quarter_of(trade.signal_us) != quarter_of(utc(2000, 1, 3)) for trade in found.trades)


def test_a_draw_is_the_same_each_time_and_differs_from_the_next(market: tuple[Any, Any]) -> None:
    tape, trades = market
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies["S01"].default()
    quarters = [quarter_of(utc(2000, 1, 3)), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))]
    plan = build_plan(
        "S01", "S", line, item=item, sim=sim_params(), quarters=quarters, real=run_stream("S01", tape, trades)
    )
    assert simulate_draw(plan, 1, item)[0].events == simulate_draw(plan, 1, item)[0].events
    assert simulate_draw(plan, 1, item)[0].events != simulate_draw(plan, 2, item)[0].events


def test_no_distance_is_taken_from_a_read_day(market: tuple[Any, Any]) -> None:
    """FP-07: a read day's bars stay for continuity, and nothing born on it enters the pool. The pool with
    2000-02-10 read holds exactly the births of the run without it, less those knowable on that day.
    """
    tape, trades = market
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies["S01"].default()
    quarters = [quarter_of(utc(2000, 1, 3)), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))]
    day = (utc(2000, 2, 10), utc(2000, 2, 11))
    recorder = RecordingSource()
    recording = build_level_strategy("S01", dict(line.params), recorder)
    Simulator(recording, tape, sim_params(), trades=trades).run()
    on_the_day = [birth for birth in recorder.births if day[0] <= birth.knowable_us < day[1]]
    assert on_the_day, "nothing was born on the day, so this would prove nothing"
    real = run_stream("S01", tape, trades)
    plain = build_plan("S01", "S", line, item=item, sim=sim_params(), quarters=quarters, real=real)
    read = build_plan(
        "S01", "S", line, item=item, sim=sim_params(read_days_us=(day,)), quarters=quarters, real=real
    )
    assert plain.pool is not None and read.pool is not None
    later = quarter_of(utc(2100, 1, 1))
    for kind in plain.pool.kinds():
        lost = sum(1 for birth in on_the_day if birth.kind == kind)
        assert read.pool.count_before(kind, later) == plain.pool.count_before(kind, later) - lost


@pytest.mark.parametrize("strategy", METHODS)
def test_every_placebo_fills_after_its_decision_and_its_stops_only_tighten(
    strategy: str, market: tuple[Any, Any]
) -> None:
    tape, trades = market
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies[strategy].default()
    plan = build_plan(
        strategy,
        "S",
        line,
        item=item,
        sim=sim_params(),
        quarters=[quarter_of(utc(2000, 1, 3)), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))],
        real=run_stream(strategy, tape, trades),
    )
    found, _ = simulate_draw(plan, 1, item)
    for trade in found.trades:
        assert trade.fill_us >= trade.decided_as_of_us
        stops = [trade.s0, *(row["new"] for row in trade.stop_path)]
        assert all(trade.side * (after - before) >= 0 for before, after in itertools.pairwise(stops))


# ---- entries through the real scan --------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["S03", "S10"])
def test_a_draw_enters_only_on_eligible_bars_with_the_real_counts(
    strategy: str, market: tuple[Any, Any]
) -> None:
    tape, trades = market
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies[strategy].default()
    real = run_stream(strategy, tape, trades)
    plan = build_plan(
        strategy,
        "S",
        line,
        item=item,
        sim=sim_params(),
        quarters=[quarter_of(utc(2000, 1, 3)), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))],
        real=real,
    )
    assert plan.counts, "the real line made no setup, so this test would prove nothing"
    found, _ = simulate_draw(plan, 3, item)
    drawn = [event for event in found.events if event["type"] == "SETUP_CREATED"]
    assert drawn
    # The entries are the ones this draw's own hashed seed gives, and no other.
    seeded = random.Random(draw_seed(strategy, "S", plan.line, 3))
    expected = draw_entries(seeded, plan.eligible, plan.counts)
    assert {(event["computed_at_us"], event["side"]) for event in drawn} <= set(expected.items())
    for event in drawn:
        quarter = quarter_of(event["computed_at_us"])
        assert event["computed_at_us"] in plan.eligible[quarter][event["side"]]
    by_block: dict[tuple[int, int], int] = {}
    for event in drawn:
        key = (quarter_of(event["computed_at_us"]), event["side"])
        by_block[key] = by_block.get(key, 0) + 1
    for (quarter, side), count in by_block.items():
        assert count <= plan.counts[quarter][side]


def test_the_s03_scan_keeps_only_bars_passing_its_non_signal_filters(market: tuple[Any, Any]) -> None:
    """Conditions c to f of section 5: a climax bar, an extended close, chop or VR above 2 is not eligible."""
    from hft_crypto.strategies.placebo import S03Scan
    from hft_crypto.strategies.registers import against

    tape, trades = market
    params = dict(engine_config().strategies["S03"].default().params)
    checked: list[bool] = []

    class _Checked(S03Scan):
        def on_close(self, market_view: MarketView) -> list[Any]:
            before = len(self.eligible)
            found = super().on_close(market_view)
            bar = market_view.bar
            if bar.atr is None or bar.vr is None or not bar.complete:
                return found
            added = self.eligible[before:]
            for side in (1, -1):
                base, _ = self.sigma.latest_two(against(side))
                failure = None if base is None else self.non_signal_failure(bar, side, base, bar.atr, bar.vr)
                passes = base is not None and failure is None
                kept = any(row.close_us == bar.close_us and row.side == side for row in added)
                assert kept == passes
                checked.append(passes)
            return found

    Simulator(_Checked(params), tape, sim_params(), trades=trades).run()
    assert True in checked and False in checked, "no bar failed a filter, so this would prove nothing"


# ---- the trial registry -----------------------------------------------------------------------------------


def _row_args(strategy: str, lines: int, draw: int | None, symbol: str) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "line": "line",
        "is_default": True,
        "in_portfolio": True,
        "symbol": symbol,
        "params": {},
        "mode": "IDEAL-1M",
        "variant": "V0",
        "tier": "T1",
        "date_range": {"start": "2020-01-01", "end": "2023-12-31"},
        "costs": {"rt_bps": 12.0},
        "risk_state": "placeholder",
        "data_kind": "MARKET",
        "code_version": "test",
        "config_hash": "c",
        "manifest_hash": "m",
        "lines_counted": lines,
        "draw": draw,
    }


def _row(strategy: str, lines: int, *, draw: int | None = None, symbol: str = "BTC") -> dict[str, Any]:
    return trial_row(**_row_args(strategy, lines, draw, symbol))


def test_a_run_of_all_ten_is_60_runs_for_64_lines_and_candles_stay_at_52() -> None:
    engine = engine_config()
    runs = sum(len(engine.lines(strategy)) for strategy in available_strategies())
    lines_t1 = sum(
        len(engine.lines(strategy)) * strategy_class(strategy).lines_on("T1")
        for strategy in available_strategies()
    )
    lines_t0 = sum(
        len(engine.lines(strategy)) * strategy_class(strategy).lines_on("T0")
        for strategy in available_strategies()
    )
    assert (runs, lines_t1, lines_t0) == (60, 64, 52)


def test_the_registry_counts_lines_and_runs_and_no_control(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "root")
    registry = TrialRegistry(root)
    s08 = _row("S08", 2)
    registry.started(s08, logged_at="t")
    registry.started(s08, logged_at="t2")  # an identical repeat adds nothing
    registry.started(_row("S01", 1), logged_at="t")
    registry.started(_row("S07", 0), logged_at="t")  # on candles it ran nothing and is no line
    for draw in (1, 2):
        registry.started(_row("S01", 0, draw=draw), logged_at="t")
        registry.started(_row("S01", 0, draw=draw, symbol="ETH"), logged_at="t")
    assert registry.distinct_trials() == 3
    assert registry.distinct_runs() == 2
    assert registry.placebo_readings() == 1


def test_a_v0s_control_is_no_placebo_reading(tmp_path: Path) -> None:
    """`V0S` runs are controls too, with no draw. On market data they count as no trial and no C15 reading."""
    registry = TrialRegistry(DataRoot(tmp_path / "root"))
    v0s = trial_row(**{**_row_args("S01", 0, None, "BTC"), "variant": VARIANT_V0S, "control": True})
    assert (v0s["control"], v0s["counts_as_trial"], v0s["lines_counted"]) == (True, False, 0)
    registry.started(v0s, logged_at="t")
    assert (registry.distinct_trials(), registry.placebo_readings()) == (0, 0)
    registry.started(_row("S01", 0, draw=1), logged_at="t")
    assert registry.placebo_readings() == 1


def test_a_control_row_says_so_and_never_counts() -> None:
    row = _row("S01", 1, draw=7)
    assert (row["control"], row["counts_as_trial"], row["lines_counted"], row["draw"]) == (True, False, 0, 7)
    assert _row("S01", 1, draw=7)["trial_key"] != _row("S01", 1, draw=8)["trial_key"]
    assert _row("S01", 1)["trial_key"] != _row("S01", 1, draw=8)["trial_key"]


# ---- the configuration ------------------------------------------------------------------------------------


def _raw_config(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_the_shipped_files_declare_200_draws() -> None:
    assert load_engine_config(GENERATED_CONFIG).placebo_draws == 200
    assert load_engine_config(GENERATED_CONFIG.parent / "engine.toml").placebo_draws == 200


def test_a_market_run_may_not_state_another_count() -> None:
    raw = _raw_config(GENERATED_CONFIG.parent / "engine.toml")
    raw["placebo"]["draws"] = 100
    with pytest.raises(ConfigError, match="declares 200"):
        parse_engine_config(raw)


def test_the_placebo_table_is_required() -> None:
    raw = _raw_config(GENERATED_CONFIG)
    del raw["placebo"]
    with pytest.raises(ConfigError, match="placebo"):
        parse_engine_config(raw)


# ---- the whole command ----------------------------------------------------------------------------------

FIRST = dt.date(2000, 1, 3)
ROOT_DAYS = 130
DRAWS = 2


@pytest.fixture(scope="module")
def placebo_run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base = tmp_path_factory.mktemp("placebo")
    root = base / "root"
    write_generated_root(root, first=FIRST, days=ROOT_DAYS)
    config = default_only_config(base, draws=DRAWS)
    value = DateRange(FIRST, FIRST + dt.timedelta(days=ROOT_DAYS - 1))
    outcome = run_engine(
        data_root=str(root), config_path=config, date_range=value, out_dir=base / "one", placebo=True
    )
    yield {
        "base": base,
        "root": root,
        "config": config,
        "range": value,
        "outcome": outcome,
        "out": base / "one",
    }


def _rows(out: Path) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads((out / "placebo.json").read_text(encoding="utf-8"))["rows"]
    return loaded


def test_there_is_a_row_per_strategy_and_symbol_each_labelled(placebo_run: dict[str, Any]) -> None:
    rows = _rows(placebo_run["out"])
    assert [(row["strategy"], row["asset"]) for row in rows] == [
        (strategy, symbol) for symbol in ("SYNTHBTC", "SYNTHETH") for strategy in available_strategies()
    ]
    assert all(row["label"] == "SIMULATED SYNTHETIC" for row in rows)
    header = json.loads((placebo_run["out"] / "placebo.json").read_text(encoding="utf-8"))["header"]
    assert header["labels"] == ["SIMULATED", "SYNTHETIC"]
    assert header["placebo"]["ran"] is True
    assert header["date_range"] == {"start": "2000-01-03", "end": "2000-05-11"}


def test_the_header_names_the_marks_behind_drawdown_and_the_run_lists_what_is_not_built(
    placebo_run: dict[str, Any],
) -> None:
    run = json.loads((placebo_run["out"] / "run.json").read_text(encoding="utf-8"))
    assert run["header"]["equity_timeframe_minutes"] == 60
    assert "this grid" in run["header"]["equity_note"]
    for name in (
        "closed_trade_equity",
        "monthly_and_rolling_tables",
        "confidence_intervals",
        "s01_confluence_log",
        "placebo_named_extras",
    ):
        assert name in run["not_built"]
    assert run["header"]["funding"]["status"] == "absent"
    assert run["header"]["funding"]["settlements_with_no_rate"] == {"SYNTHBTC": 0, "SYNTHETH": 0}


def test_en07_the_count_names_d32_beside_the_registry_s_lines(placebo_run: dict[str, Any]) -> None:
    header = json.loads((placebo_run["out"] / "run.json").read_text(encoding="utf-8"))["header"]
    count = header["trial_count"]
    assert count["counted_outside_registry"] == {"D-32": 2}
    assert count["total"] == count["registry_lines"] + 2
    assert count["registry_lines"] == 0  # a generated run counts none


def test_c15_each_row_says_what_stays_real_beside_its_rank(placebo_run: dict[str, Any]) -> None:
    rows = {(row["strategy"], row["asset"]): row for row in _rows(placebo_run["out"])}
    assert "developing profile stays real" in rows[("S08", "SYNTHBTC")]["stays_real"]
    assert all(row["stays_real"] for row in rows.values() if row["status"] == "RAN")


def test_v0s_has_its_own_rows_beside_v0_and_never_enters_the_portfolio(placebo_run: dict[str, Any]) -> None:
    out = placebo_run["out"]
    rows = json.loads((out / "v0s.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 20
    assert all(row["variant"] == "V0S" and row["in_portfolio"] is False for row in rows)
    compared = [row["setups_taken"] for row in rows if row["setups_taken"] is not None]
    assert compared and all(
        set(item) == {"taken_in_both", "taken_in_v0_only", "taken_in_v0s_only"} for item in compared
    )
    trades = json.loads((out / "trades.json").read_text(encoding="utf-8"))["rows"]
    assert all(row["variant"] == "V0" for row in trades)
    trials = json.loads((out / "trials.json").read_text(encoding="utf-8"))["rows"]
    controls = [row for row in trials if row["variant"] == "V0S"]
    assert len(controls) == 20 and all(row["control"] and not row["counts_as_trial"] for row in controls)


def test_the_ranks_can_be_rebuilt_from_the_row_s_own_draws(placebo_run: dict[str, Any]) -> None:
    ranked = 0
    for row in _rows(placebo_run["out"]):
        if row["status"] != "RAN" or row["real"]["trades"] == 0:
            continue
        for kind in ("gross", "net"):
            real = row["real"][f"{kind}_mean_result_b"]
            values = [
                draw[f"{kind}_mean_result_b"]
                for draw in row["draw_rows"]
                if draw[f"{kind}_mean_result_b"] is not None
            ]
            # Six decimals in the file, so this rebuild tolerates a tie made only by that rounding.
            assert row[f"{kind}_rank"] in (
                1 + sum(value > real for value in values),
                1 + sum(value >= real for value in values),
            )
        ranked += 1
    assert ranked, "no row had a rank, so this test would prove nothing"


def test_level_rows_name_their_first_quarter_and_entry_rows_do_not_lose_it(
    placebo_run: dict[str, Any],
) -> None:
    for row in _rows(placebo_run["out"]):
        if row["strategy"] in LEVEL_STRATEGIES:
            assert "2000-Q1" in row["quarters_without_placebo"]
            assert row["quarters"][0]["reason"] == FIRST_QUARTER
        if row["strategy"] in ("S03", "S10"):
            assert "2000-Q1" not in row["quarters_without_placebo"]


def test_each_draw_is_logged_as_a_control_before_and_after_it_runs(placebo_run: dict[str, Any]) -> None:
    rows = _registry_rows(placebo_run["root"])
    controls = [row for row in rows if row["control"]]
    # The V0S streams are controls too, logged without a draw number. They are checked apart below.
    started = [row for row in controls if row["event"] == "trial_started" and row.get("draw") is not None]
    finished = [row for row in controls if row["event"] == "trial_finished" and row.get("draw") is not None]
    ran = [row for row in _rows(placebo_run["out"]) if row["status"] == "RAN"]
    assert len(started) == len(finished) == len(ran) * DRAWS
    assert all(row["counts_as_trial"] is False and row["lines_counted"] == 0 for row in started)
    assert {row["draw"] for row in started} == {1, 2}
    v0s = [row for row in controls if row["variant"] == VARIANT_V0S]
    assert v0s and all(row["counts_as_trial"] is False and row["lines_counted"] == 0 for row in v0s)
    assert TrialRegistry(DataRoot(placebo_run["root"], create=False)).distinct_trials() == 0


def _registry_rows(root: Path) -> list[dict[str, Any]]:
    path = root / REGISTRY_PATH
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_s08_counts_two_lines_on_every_output_of_a_run_with_trades(placebo_run: dict[str, Any]) -> None:
    rows = json.loads((placebo_run["out"] / "trials.json").read_text(encoding="utf-8"))["rows"]
    lines = {row["strategy"]: row["lines_counted"] for row in rows if not row["control"]}
    assert lines["S08"] == 2
    assert lines["S01"] == 1
    # A V0S control counts no line, whatever its strategy.
    assert {row["lines_counted"] for row in rows if row["variant"] == VARIANT_V0S} == {0}


def test_s08_shows_each_branch_beside_its_placebo(placebo_run: dict[str, Any]) -> None:
    rows = [row for row in _rows(placebo_run["out"]) if row["strategy"] == "S08" and row["status"] == "RAN"]
    assert rows
    assert any("branches" in row for row in rows)


def test_the_same_inputs_give_identical_bytes_and_workers_change_nothing(placebo_run: dict[str, Any]) -> None:
    base = placebo_run["base"]
    for name, workers in (("again", 1), ("two_workers", 2)):
        run_engine(
            data_root=str(placebo_run["root"]),
            config_path=placebo_run["config"],
            date_range=placebo_run["range"],
            out_dir=base / name,
            placebo=True,
            placebo_workers=workers,
        )
        first = (placebo_run["out"] / "placebo.json").read_bytes()
        assert (base / name / "placebo.json").read_bytes() == first


def test_a_run_that_did_not_ask_says_so_on_each_row(tmp_path: Path, placebo_run: dict[str, Any]) -> None:
    run_engine(
        data_root=str(placebo_run["root"]),
        config_path=placebo_run["config"],
        date_range=placebo_run["range"],
        out_dir=tmp_path / "none",
    )
    rows = _rows(tmp_path / "none")
    assert len(rows) == 20
    assert all(row["status"] == STATUS_NOT_RUN and row["gross_rank"] is None for row in rows)
    assert "placebo" in json.loads((tmp_path / "none" / "run.json").read_text(encoding="utf-8"))["not_built"]


def test_on_candles_s07_and_s08_have_no_placebo_and_say_why(market: tuple[Any, Any]) -> None:
    tape, _ = market
    engine = replace(engine_config(), tier="T0", placebo_draws=1, line_set="default_only", symbols=("S",))
    item = SymbolData(tape, None, ())
    streams = [
        replace(run_stream(strategy, tape, None), is_default=True, symbol="S")
        for strategy in available_strategies()
    ]
    found = run_placebos(
        engine,
        {"S": item},
        streams,
        date_range=DateRange(dt.date(2000, 1, 3), dt.date(2000, 7, 20)),
        sim_for=lambda _strategy, _symbol: sim_params(),
    )
    by_name = {result.strategy: result for result in found}
    for name in ("S07", "S08"):
        assert by_name[name].status == STATUS_NOT_RUN
        assert by_name[name].reason == "NEEDS_T1_TRADES"
        assert by_name[name].draws == ()
    assert by_name["S01"].status == "RAN"
    assert len(by_name["S01"].draws) == 1
