"""One test per finding of docs/reviews/code/engine_review_2026-11-05.md, each with its case worked by hand.

Each of these fails without its fix. That was shown by reverting each fix in a copy and running its test.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import numpy as np
import polars as pl
import pytest

from engine_helpers import (
    DELAY_US,
    costs,
    day_bar,
    generated_trades,
    run_stream,
    sim_params,
    tape_and_trades,
    utc,
)
from hft_crypto.engine.accounting import ExitLeg, FundingGap
from hft_crypto.engine.config import DateRange
from hft_crypto.engine.funding import FundingRow, funding_schedule, missing_settlements
from hft_crypto.engine.indicators import clv
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.run import _funding_note, build_manifest, read_symbol
from hft_crypto.engine.simulator import FundingEvent, Simulator, StreamResult, TradeRecord
from hft_crypto.engine.tape import Bar, MinuteTape
from hft_crypto.reports.portfolio import _cost_lines, _current_position, _full_section, _tally
from hft_crypto.strategies.base import (
    REST,
    Management,
    PositionView,
    Proposal,
    Strategy,
    TargetPlan,
    sided_clv,
)
from hft_crypto.strategies.levels import Level, floor_pivots
from hft_crypto.strategies.registers import HIGH, LOW, Swing, SwingList
from hft_crypto.strategies.s01_floor_pivot_rejection import S01FloorPivotRejection
from hft_crypto.strategies.s02_pivot_breakout_retest import S02PivotBreakoutRetest, _Sequence
from hft_crypto.strategies.s03_market_structure import S03MarketStructure
from hft_crypto.strategies.s03_market_structure import _Memo as S03Memo
from hft_crypto.strategies.s04_supply_demand_zones import S04SupplyDemandZones
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip, _Flip
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim, _Sweep, _swing_id
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression
from hft_crypto.strategies.s10_volatility_compression import _Memo as S10Memo
from hft_crypto.strategies.zones import Zone

START = utc(2000, 3, 6)  # a Monday
MINUTE = 60_000_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


# ---- a held position, with funding -------------------------------------------------------------------------


class _Hold(Strategy):
    """Goes long once, at a stated close, with a stop far below, and holds to the end or to a stated exit."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}

    def __init__(self, enter_at: int, *, s0: float = 50.0, exit_at: int | None = None, side: int = 1) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.enter_at = enter_at
        self.s0 = s0
        self.exit_at = exit_at
        self.side = side

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.enter_at:
            return []
        return [Proposal(self.side, self.s0, (TargetPlan("T1", None, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        del position
        if market.now_us == self.exit_at:
            return Management(exit_reason="INVALIDATION")
        return Management()


def _flat_rows(hours: int, *, price: float = 100.0, leave_out: tuple[int, ...] = ()) -> pl.DataFrame:
    """One row a minute at one price, with a small range, leaving out the named minutes."""
    return _frame(
        [START + minute * MINUTE for minute in range(hours * 60) if minute not in leave_out],
        price,
    )


def _frame(opens: list[int], price: float) -> pl.DataFrame:
    size = len(opens)
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(pl.Datetime("us", "UTC")),
            "open": [price] * size,
            "high": [price + 0.5] * size,
            "low": [price - 0.5] * size,
            "close": [price] * size,
            "volume": [10.0] * size,
            "trade_count": [5] * size,
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(
                pl.Datetime("us", "UTC")
            ),
        }
    )


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [
            replace(bar, atr=2.0, atr_last=2.0, complete=True, gap=False) for bar in self.tape.frame(minutes)
        ]


def _hold(
    frame: pl.DataFrame,
    strategy: Strategy,
    funding: tuple[FundingEvent, ...],
    *,
    stop_slip: float = 0.0,
    risk_budget: float = 500.0,
) -> StreamResult:
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=risk_budget,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=stop_slip),
    )
    return _FlatAtr(strategy, tape, params, funding=funding).run()


# ---- E-01 --------------------------------------------------------------------------------------------------


def test_e01_a_settlement_with_no_rate_is_logged_counted_and_never_assumed() -> None:
    """The review's case. Long at price 100, stop 50: `q0` = 500 / 50 = 10, notional 1,000. Six settlements at
    10 bp, with only the first two rates. It pays 2 * 1.00 = 2.00, and four are unresolved at 1,000 each.
    """
    enter = START + HOUR
    settles = [START + (2 + index) * HOUR for index in range(6)]
    funding = (
        FundingEvent(settles[0], 0.001),
        FundingEvent(settles[1], 0.001),
        *(FundingEvent(moment, None) for moment in settles[2:]),
    )
    stream = _hold(_flat_rows(10), _Hold(enter), funding)
    trade = stream.trades[0]
    assert trade.q0 == pytest.approx(10.0)
    assert trade.book()[1].funding == 200
    assert stream.counters["funding_rate_missing"] == 4
    assert [item.settle_us for item in trade.funding_gaps] == settles[2:]
    assert all(item.notional == pytest.approx(1000.0) for item in trade.funding_gaps)
    logged = [event for event in stream.events if event["type"] == "DATA_GAP"]
    assert [event["settle_us"] for event in logged] == settles[2:]
    assert all(event["source"] == "funding" for event in logged)


def test_e01_a_gap_before_the_fill_or_after_the_exit_is_not_this_trade_s() -> None:
    enter = START + 2 * HOUR
    exit_at = START + 4 * HOUR
    funding = (
        FundingEvent(START + HOUR, None),
        FundingEvent(START + 3 * HOUR, None),
        FundingEvent(START + 6 * HOUR, None),
    )
    stream = _hold(_flat_rows(8), _Hold(enter, exit_at=exit_at), funding)
    assert [item.settle_us for item in stream.trades[0].funding_gaps] == [START + 3 * HOUR]


def test_e01_the_cadence_of_the_file_finds_each_missing_settlement() -> None:
    """Every 8 h. Rows at 00, 08 and 40: 16, 24 and 32 have no row. The range opens 8 h before and runs on, so
    one before the first row and those up to its end are missing too.
    """
    base = START
    rows = [FundingRow(base + hour * HOUR, 0.0001, 8) for hour in (8, 16, 48)]
    events = funding_schedule(rows, first_open_us=base - HOUR, end_us=base + 72 * HOUR)
    assert [(event.settle_us - base) // HOUR for event in events if event.rate is None] == [
        0,
        24,
        32,
        40,
        56,
        64,
    ]
    assert [(event.settle_us - base) // HOUR for event in events if event.rate is not None] == [8, 16, 48]


def test_e01_a_settlement_exactly_at_the_range_s_end_is_not_counted_missing() -> None:
    rows = [FundingRow(START + 8 * HOUR, 0.0001, 8)]
    events = funding_schedule(rows, first_open_us=START + HOUR, end_us=START + 16 * HOUR)
    assert missing_settlements(events) == ()


def test_e01_nor_is_one_exactly_at_the_range_s_first_instant() -> None:
    """No position exists then, so nothing can be owed for it."""
    rows = [FundingRow(START + 8 * HOUR, 0.0001, 8)]
    events = funding_schedule(rows, first_open_us=START, end_us=START + 16 * HOUR)
    assert missing_settlements(events) == ()


def test_e01_a_late_stamp_and_a_change_of_interval_are_not_holes() -> None:
    late = START + 16 * HOUR + 3_000
    rows = [
        FundingRow(START, 0.0001, 8),
        FundingRow(START + 8 * HOUR, 0.0001, 8),
        FundingRow(late, 0.0001, 4),
        FundingRow(late + 4 * HOUR, 0.0001, 4),
    ]
    events = funding_schedule(rows, first_open_us=START, end_us=late + 4 * HOUR + 1)
    assert missing_settlements(events) == ()


def _candle_rows(first: dt.date) -> pl.DataFrame:
    return _frame([utc(first.year, first.month, first.day) + index * MINUTE for index in range(2880)], 100.0)


def test_e01_the_count_reaches_the_manifest_and_the_note_from_the_rows_a_run_reads() -> None:
    """One symbol, two days, 8 h cadence, a settlement dropped at 16:00 on day 1."""
    first = dt.date(2000, 3, 6)
    start = utc(2000, 3, 6)
    kept = [8, 24, 32, 40]
    funding_frame = pl.DataFrame(
        {
            "settle_time": pl.Series([start + h * HOUR for h in kept], dtype=pl.Int64).cast(
                pl.Datetime("us", "UTC")
            ),
            "funding_rate": [0.0001] * 4,
            "funding_interval_hours": pl.Series([8] * 4, dtype=pl.Int32),
        }
    )
    reader = SimpleNamespace(
        candles=lambda *_a, **_k: _candle_rows(first), funding=lambda *_a, **_k: funding_frame
    )
    engine = cast(
        Any, SimpleNamespace(minute_source="official_candles", venue="v", tier="T0", funding="required")
    )
    date_range = DateRange(first, dt.date(2000, 3, 7))
    item = read_symbol(
        cast(Any, reader), engine, "S", date_range, delay_us=DELAY_US, last_opened=dt.date(2000, 3, 7)
    )
    assert missing_settlements(item.funding) == (start + 16 * HOUR,)
    manifest = build_manifest({"S": item}, engine, date_range)["symbols"]["S"]
    assert manifest["funding_rows"] == 4
    assert manifest["funding_settlements_with_no_rate"] == 1
    assert "no rate" in _funding_note(engine, {"S": 2})
    assert "DATA_GAP" in _funding_note(engine, {"S": 2})
    assert "Every settlement in the range has a rate" in _funding_note(engine, {"S": 0})


# ---- E-02 --------------------------------------------------------------------------------------------------


def _falls_after(frame: pl.DataFrame, minute: int, price: float) -> pl.DataFrame:
    """From a minute on the price stands at a new level, so stopping at the gap is the better way to read
    it."""
    return frame.with_columns(
        pl.when(pl.col("open_time").dt.timestamp("us") >= START + minute * MINUTE)
        .then(pl.lit(price))
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )


def test_e02_a_settlement_inside_a_hole_in_the_rows_is_still_owed() -> None:
    """Rows 198 to 201 are missing, and a settlement falls at the end of row 199. Long 10 at 100, stop 90, 10
    bp: 1.00 is owed. The price then falls to 80, so the recorded path is the worse way and is the headline.
    """
    enter = START + HOUR
    settle = START + 200 * MINUTE
    frame = _falls_after(_flat_rows(6, leave_out=(198, 199, 200, 201)), 240, 80.0)
    stream = _hold(frame, _Hold(enter, s0=90.0), (FundingEvent(settle, 0.001),), risk_budget=100.0)
    trade = stream.trades[0]
    assert trade.gap_unresolved is True
    assert trade.legs[-1].reason == "STOP_GAP"
    assert trade.book()[1].funding == 100


def test_e02_an_exit_at_the_open_after_the_hole_still_pays_it() -> None:
    """Decided at minute 180. Rows 181 to 201 are missing, so it fills at the open of minute 202, at 80."""
    enter = START + HOUR
    settle = START + 200 * MINUTE
    exit_decided = START + 3 * HOUR
    frame = _falls_after(_flat_rows(6, leave_out=tuple(range(181, 202))), 202, 80.0)
    stream = _hold(
        frame, _Hold(enter, s0=85.0, exit_at=exit_decided), (FundingEvent(settle, 0.001),), risk_budget=150.0
    )
    trade = stream.trades[0]
    assert trade.legs[-1].reason == "INVALIDATION"
    assert trade.legs[-1].reference == 80.0
    assert trade.book()[1].funding == 100


def test_e02_a_stop_gapped_through_at_an_open_owes_nothing_later_in_that_minute() -> None:
    """Fills at the open, as a pending exit does, so C10's boundary treats it the same way."""
    opens = [START + minute * MINUTE for minute in range(180)]
    frame = _frame(opens, 100.0).with_columns(
        pl.when(pl.col("open_time").dt.timestamp("us") >= START + 120 * MINUTE)
        .then(pl.lit(40.0))
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )
    settle = START + 121 * MINUTE  # the close of the minute that gapped through the stop at 50
    stream = _hold(frame, _Hold(START + HOUR), (FundingEvent(settle, 0.001),))
    trade = stream.trades[0]
    assert trade.exit_reason == "STOP_GAP"
    assert trade.funding == ()


# ---- E-03 --------------------------------------------------------------------------------------------------


def test_e03_a_trade_taken_as_stopped_at_a_gap_pays_no_later_funding() -> None:
    """The review's case. Long `q0` 10, stop 90, fill 100. A gap at minute 200, a 1% settlement at minute 300,
    and the price still at 100. Stopped at the gap: 10 * (90 - 100) = -100.00. Paid after it: nothing.
    """
    frame = _flat_rows(8, leave_out=(200,))
    settle = START + 300 * MINUTE
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=100.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )
    stream = _FlatAtr(_Hold(START + HOUR, s0=90.0), tape, params, funding=(FundingEvent(settle, 0.01),)).run()
    trade = stream.trades[0]
    assert trade.gap_unresolved is True
    assert trade.q0 == pytest.approx(10.0)
    assert trade.funding == ()
    assert trade.book()[1].net == -10_000


def test_e03_a_short_paid_funding_is_not_flattered_by_what_came_after_the_gap() -> None:
    """Short 10 at 100, stop 110, the price flat. Receiving 1% after the gap would make -100.00 read as
    -90.00."""
    frame = _flat_rows(8, leave_out=(200,))
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=100.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )
    stream = _FlatAtr(
        _Hold(START + HOUR, s0=110.0, side=-1),
        tape,
        params,
        funding=(FundingEvent(START + 300 * MINUTE, 0.01),),
    ).run()
    assert stream.trades[0].book()[1].net == -10_000


def test_e03_the_worse_way_is_chosen_without_what_came_after_the_gap() -> None:
    """Long 10 at 100, stop 90. After the gap it receives 10.00 of funding, and later gaps through to 89.5, so
    the recorded way is -105.00 + 10.00 = -95.00. Stopped at the gap is -100.00, with nothing after it. That
    is the worse, and the headline. Counting the 10.00 on both ways would read -90.00 against -95.00, and
    choose wrongly.
    """
    frame = _falls_after(_flat_rows(8, leave_out=(200,)), 360, 89.5)
    stream = _hold(
        frame, _Hold(START + HOUR, s0=90.0), (FundingEvent(START + 300 * MINUTE, -0.01),), risk_budget=100.0
    )
    trade = stream.trades[0]
    assert trade.as_recorded_legs[-1].reason == "STOP_GAP"
    assert trade.legs[-1].reason == "GAP_UNRESOLVED_STOP"
    assert trade.funding == ()
    assert trade.book()[1].net == -10_000


# ---- E-04 --------------------------------------------------------------------------------------------------


def _hourly(hours: list[int], *, price: float = 100.0) -> pl.DataFrame:
    return _frame([START + hour * HOUR + minute * MINUTE for hour in hours for minute in range(60)], price)


def test_e04_an_hour_with_no_rows_is_a_gap_bar_on_the_grid() -> None:
    """Hours 0 to 9, with hour 5 empty. Ten bars, not nine, and the empty one is a gap with no price."""
    hours = [hour for hour in range(10) if hour != 5]
    tape = MinuteTape.from_frame(_hourly(hours), symbol="S", delay_us=DELAY_US)
    bars = tape.frame(60)
    assert [bar.close_us for bar in bars] == [START + (hour + 1) * HOUR for hour in range(10)]
    assert [bar.index for bar in bars] == list(range(10))
    hole = bars[5]
    assert (hole.gap, hole.complete, hole.has_price, hole.v) == (True, False, False, 0.0)
    assert hole.c == bars[4].c
    assert hole.atr is None
    assert bars[6].gap is False
    assert bars[6].tr is None  # its true range needs the close before it, which is missing


def test_e04_a_swing_across_a_missing_bar_is_not_computed() -> None:
    """The review's case: a swing high whose right-hand window crosses the empty hour. C2: not computed."""
    rows = []
    for hour in range(14):
        if hour == 8:
            continue
        price = 100.0 + (5.0 if hour == 6 else 0.0)
        rows.append(_hourly([hour], price=price))
    tape = MinuteTape.from_frame(pl.concat(rows), symbol="S", delay_us=DELAY_US)
    bars = [replace(bar, atr=2.0, atr_last=2.0) for bar in tape.frame(60)]
    swings = SwingList(3, 3, 0.1)
    added = [swing for end in range(1, len(bars) + 1) for swing in swings.update(bars[:end])]
    assert [swing for swing in added if swing.price == pytest.approx(105.5)] == []


# ---- E-06 --------------------------------------------------------------------------------------------------


def _bar(
    index: int,
    o: float,
    h: float,
    l: float,  # noqa: E741
    c: float,
    *,
    atr: float = 10.0,
    close_us: int | None = None,
    srv: float | None = 1.5,
    minutes: int = 60,
) -> Bar:
    return Bar(
        index=index,
        minutes=minutes,
        open_us=START + index * minutes * MINUTE,
        close_us=START + (index + 1) * minutes * MINUTE if close_us is None else close_us,
        o=o,
        h=h,
        l=l,
        c=c,
        v=1.0,
        has_price=True,
        complete=True,
        pending_tail=False,
        gap=False,
        late_gap=False,
        tr=h - l,
        atr=atr,
        atr_last=atr,
        vr=1.0,
        srv=srv,
        clv=clv(h, l, c),
        atrd=None,
        day=None,
        week=None,
        day_at_close=None,
        week_at_close=None,
        day_open=None,
    )


def _market(minutes: int, bars: list[Bar], higher: tuple[int, ...] = ()) -> MarketView:
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=minutes, higher=higher, trades=None)
    for bar in bars:
        market._release(bar, {})
    return market


def test_e06_a_zone_does_not_trade_on_the_bar_that_creates_it() -> None:
    """Base bars 3 and 4, `prox` 1002, `dist` 996. Departure bars 5 and 6, and bar 6 dips to 1001.5 and closes
    1018.

    Net 16 clears 1.5 * ATR 10, so the zone is born at bar 6, and Q = 100 * (0.5 * 16/30 + 0.3 * 0.6 + 0.2) =
    64.67. Everything else in section 5 holds at that close, and `S0` = 996 - 2.5 = 993.5 is within 2.5 ATR of
    the close. 7.9 says the bar that creates it is not affected.
    """
    rows = [
        (1030, 1031, 1020, 1021),
        (1021, 1022, 1011, 1012),
        (1012, 1013, 1002, 1003),
        (1001, 1004, 997, 1002),
        (1002, 1003, 996, 1001),
        (1003, 1014, 1002.5, 1013),
        (1013, 1020, 1001.5, 1018),
    ]
    strategy = S04SupplyDemandZones({"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0})
    bars = [_bar(index, *row) for index, row in enumerate(rows)]
    found: list[Proposal] = []
    market = _market(60, [])
    for bar in bars:
        market._release(bar, {})
        found = strategy.on_close(market)
    zones = [zone for zone in strategy.book.entry if zone.side == 1]
    assert [(zone.prox, zone.birth_index) for zone in zones] == [(1002.0, 6)]
    assert strategy.book.quality(zones[0], bars[6]) == pytest.approx(64.67, abs=0.01)
    assert found == []


def test_e06_the_same_zone_can_trade_on_the_next_bar() -> None:
    """The guard against a test that only ever says no: bar 7 dips into the zone and closes back above it."""
    rows = [
        (1030, 1031, 1020, 1021),
        (1021, 1022, 1011, 1012),
        (1012, 1013, 1002, 1003),
        (1001, 1004, 997, 1002),
        (1002, 1003, 996, 1001),
        (1003, 1014, 1002.5, 1013),
        (1013, 1020, 1004, 1019),
        (1019, 1020, 1001, 1015),
    ]
    strategy = S04SupplyDemandZones({"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0})
    market = _market(60, [])
    found: list[Proposal] = []
    for index, row in enumerate(rows):
        market._release(_bar(index, *row), {})
        found = strategy.on_close(market)
    assert [proposal.side for proposal in found] == [1]


# ---- E-07 --------------------------------------------------------------------------------------------------


def test_e07_a_first_retest_bar_closing_below_mid_kills_the_flip() -> None:
    """Top 1000, bottom 980, mid 990, X 1030. A bar with low 985 and close 986 opens the retest and closes
    below `mid`, so the flip is dead, and the next bar closing 1010 is no trigger.
    """
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    flip = _Flip("flip", 1, 1000.0, 980.0, 990.0, 1030.0, 0, travelled=True)
    strategy.flips.append(flip)
    assert strategy._advance_flips(_bar(5, 1005, 1006, 985, 986)) == []
    assert flip.dead_at is not None
    assert strategy._advance_flips(_bar(6, 986, 1012, 985, 1010)) == []


def test_e07_a_first_retest_bar_closing_above_mid_lives_and_can_trigger() -> None:
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    flip = _Flip("flip", 1, 1000.0, 980.0, 990.0, 1030.0, 0, travelled=True)
    strategy.flips.append(flip)
    assert strategy._advance_flips(_bar(5, 1005, 1006, 985, 992)) == []
    assert flip.dead_at is None
    assert strategy._advance_flips(_bar(6, 992, 1012, 991, 1010)) == [flip]


# ---- E-08 --------------------------------------------------------------------------------------------------


def _s06_with_swing(price: float, confirmed_index: int) -> tuple[S06LiquiditySweepReclaim, Swing]:
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": True})
    confirmed = START + (confirmed_index + 1) * 15 * MINUTE
    swing = Swing(LOW, price, 0, confirmed - 3 * HOUR, confirmed)
    strategy.swings.entries.append(swing)
    strategy._watch(swing, _bar(confirmed_index, price, price, price, price, atr=4.0, minutes=15))
    return strategy, swing


def _drive(strategy: S06LiquiditySweepReclaim, rows: list[tuple[float, float, float, float]]) -> None:
    market = _market(15, [], (60,))
    for index, row in enumerate(rows):
        market._release(_bar(index, *row, atr=4.0, minutes=15), {})
        strategy.on_close(market)


def test_e08_a_close_beyond_a_swing_pool_during_its_wait_consumes_it() -> None:
    """Swing low 1000, confirmed at bar 0, and tradable after 8 bars. Bar 3 closes at 990. By section 3 the
    pool is spent, and a later sweep of it is no sweep.
    """
    strategy, swing = _s06_with_swing(1000.0, 0)
    quiet = (1010.0, 1011.0, 1009.0, 1010.0)
    rows = [quiet, quiet, quiet, (1010.0, 1010.0, 989.0, 990.0)] + [quiet] * 8
    _drive(strategy, rows)
    pool = strategy._pools[_swing_id(swing)]
    assert pool.consumed_at == START + 4 * 15 * MINUTE


def test_e08_a_sweep_during_the_wait_consumes_it_and_gives_no_trade() -> None:
    """Bar 3 wicks to 999, 0.25 * ATR below, and closes back at 1005. It meets the sweep but cannot trade."""
    strategy, swing = _s06_with_swing(1000.0, 0)
    quiet = (1010.0, 1011.0, 1009.0, 1010.0)
    rows = [quiet, quiet, quiet, (1008.0, 1009.0, 999.0, 1005.0)]
    _drive(strategy, rows)
    assert strategy._pools[_swing_id(swing)].consumed_at == START + 4 * 15 * MINUTE
    assert strategy._sweeps == []


def test_e08_an_untouched_pool_is_still_fresh_once_ready() -> None:
    strategy, swing = _s06_with_swing(1000.0, 0)
    quiet = (1010.0, 1011.0, 1009.0, 1010.0)
    _drive(strategy, [quiet] * 12)
    assert strategy._pools[_swing_id(swing)].consumed_at is None


def test_s06_its_short_list_of_swing_pools_gives_what_the_whole_register_gives() -> None:
    """The list exists for speed, because this runs at every close for years. So it must change nothing."""
    start = utc(2000, 1, 3)
    trades = generated_trades(seed=7, start_us=start, days=60)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 60 * DAY)
    compared = 0

    def probe(strategy: Strategy, market: MarketView) -> None:
        nonlocal compared
        assert isinstance(strategy, S06LiquiditySweepReclaim)
        bar = market.bar
        oldest = bar.close_us - 7 * DAY
        ready = bar.close_us - 8 * 15 * MINUTE
        for waiting in (False, True):
            expected = [
                (_swing_id(swing), side, swing.price)
                for kind, side in ((LOW, 1), (HIGH, -1))
                for swing in strategy.swings.visible(kind)
                if swing.extreme_close_us >= oldest and (swing.valid_from > ready) == waiting
            ]
            assert strategy._swing_pools(bar, waiting=waiting) == expected
            compared += len(expected)

    run_stream("S06", tape, tape_trades, probe=probe)
    assert compared > 1000, "too few pools stood for this test to prove anything"


# ---- E-09 --------------------------------------------------------------------------------------------------


def test_e09_a_roll_at_the_first_close_after_entry_recomputes_t2() -> None:
    """The setup saw no opposing pool, so `T2` is `C + 3D`. At `n = 1` the roll gives a new day with high 106,
    which is at least 0.5 * ATR above the close of 100, so `T2` moves to it. Before the fix it did not.
    """
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 0, "swing_pools": False})
    setup_bar = replace(
        _bar(0, 98.0, 101.0, 97.0, 100.0, atr=2.0, minutes=15),
        atrd=50.0,
        day_open=100.0,
    )
    sweep = _Sweep("pool", 1, 98.0, 0, 97.0, 99.0)
    proposal = strategy._setup(_market(15, [setup_bar]), setup_bar, sweep, [])
    assert proposal is not None
    next_day = day_bar(START + DAY, 106.0, 90.0, 100.0)
    bar = replace(_bar(1, 100.0, 101.0, 99.0, 100.0, atr=2.0, minutes=15), day_at_close=next_day)
    decision = Management()
    position = cast(Any, SimpleNamespace(side=1, n=1, fill_side=100.0, r=5.0))
    strategy._recompute_t2(bar, position, proposal.memo, decision, 2.0, 100.0)
    assert [(move.name, move.price) for move in decision.targets] == [("T2", 106.0)]


def test_e09_nothing_new_at_the_first_close_moves_nothing() -> None:
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 0, "swing_pools": False})
    day = day_bar(START, 130.0, 90.0, 100.0)
    setup_bar = replace(
        _bar(0, 98.0, 101.0, 97.0, 100.0, atr=2.0, minutes=15), atrd=50.0, day_open=100.0, day=day
    )
    proposal = strategy._setup(
        _market(15, [setup_bar]), setup_bar, _Sweep("pool", 1, 98.0, 0, 97.0, 99.0), []
    )
    assert proposal is not None
    bar = replace(_bar(1, 100.0, 101.0, 99.0, 100.0, atr=2.0, minutes=15), day_at_close=day)
    decision = Management()
    position = cast(Any, SimpleNamespace(side=1, n=1, fill_side=100.0, r=5.0))
    strategy._recompute_t2(bar, position, proposal.memo, decision, 2.0, 100.0)
    assert decision.targets == []


# ---- E-10, E-15, E-16 --------------------------------------------------------------------------------------


def _s02_week() -> tuple[S02PivotBreakoutRetest, Level]:
    strategy = S02PivotBreakoutRetest({"timeframe_minutes": 60, "acc": 3, "weekly_levels": True})
    return strategy, Level("W:1:P", 100.0)


def _retest_market(close_us: int, *, index: int = 20) -> MarketView:
    bars = [
        _bar(index - 1, 103.0, 104.0, 102.0, 103.0, atr=4.0, close_us=close_us - HOUR),
        _bar(index, 103.0, 105.0, 100.5, 104.5, atr=4.0, close_us=close_us),
    ]
    return _market(60, bars)


def test_e10_a_weekly_level_can_trade_again_on_the_next_utc_day_and_not_the_same_one() -> None:
    """Band 0.4. A bar with low 100.5 and close 104.5 retests level 100, on an accepted sequence, on any
    day."""
    strategy, level = _s02_week()
    close = START + 10 * HOUR
    strategy._sequences[(level.id, 1)] = _Sequence(accepted_at=19)
    assert strategy._advance_sequences(_retest_market(close), [level]) == [(level, 1)]
    strategy._traded.add((level.id, (close - 1) // DAY))
    strategy._sequences[(level.id, 1)] = _Sequence(accepted_at=19)
    assert strategy._advance_sequences(_retest_market(close + HOUR), [level]) == []
    strategy._sequences[(level.id, 1)] = _Sequence(accepted_at=19)
    assert strategy._advance_sequences(_retest_market(close + DAY), [level]) == [(level, 1)]


def test_e10_the_bar_closing_at_midnight_belongs_to_the_day_it_ends() -> None:
    """C2: a UTC day is (00:00, 24:00]."""
    strategy, level = _s02_week()
    midnight = START + DAY
    strategy._traded.add((level.id, (midnight - 1) // DAY))
    strategy._sequences[(level.id, 1)] = _Sequence(accepted_at=19)
    assert strategy._advance_sequences(_retest_market(midnight), [level]) == []


def test_e10_a_trade_sent_is_booked_under_its_own_utc_day() -> None:
    strategy, level = _s02_week()
    bar = _bar(20, 103.0, 105.0, 100.5, 104.5, atr=4.0, close_us=START + 10 * HOUR)
    bar = replace(bar, day=day_bar(START, 200.0, 50.0, 110.0))
    market = _market(60, [bar])
    proposal = strategy._setup(market, bar, level, 1)
    assert proposal is not None
    strategy.notify_sent(proposal)
    assert strategy._traded == {(level.id, (START + 10 * HOUR - 1) // DAY)}


def test_e15_a_sequence_ends_when_its_setup_is_sent_so_no_retest_is_never_logged_for_it() -> None:
    strategy, level = _s02_week()
    strategy._sequences[(level.id, 1)] = _Sequence(accepted_at=19)
    bar = _bar(20, 103.0, 105.0, 100.5, 104.5, atr=4.0, close_us=START + 10 * HOUR)
    bar = replace(bar, day=day_bar(START, 200.0, 50.0, 110.0))
    proposal = strategy._setup(_market(60, [bar]), bar, level, 1)
    assert proposal is not None
    strategy.notify_sent(proposal)
    assert (level.id, 1) not in strategy._sequences


def test_e15_a_retest_that_came_but_was_not_sent_logs_no_no_retest() -> None:
    """Section 5: log it if no retest comes. One came at age 1, and was held back, so at age 12 nothing
    logs."""
    strategy, level = _s02_week()
    key = (level.id, 1)
    close = START + 10 * HOUR
    strategy._traded.add((level.id, (close - 1) // DAY))
    strategy._sequences[key] = _Sequence(accepted_at=19)
    strategy._advance_sequences(_retest_market(close), [level])
    assert strategy._sequences[key].retested is True
    quiet = [
        _bar(30, 110.0, 111.0, 109.0, 110.0, atr=4.0, close_us=close + 10 * HOUR),
        _bar(31, 110.0, 111.0, 109.0, 110.0, atr=4.0, close_us=close + 11 * HOUR),
    ]
    strategy._advance_sequences(_market(60, quiet), [level])
    assert key not in strategy._sequences
    assert strategy.log_buffer == []


def test_e15_with_no_retest_it_still_logs() -> None:
    strategy, level = _s02_week()
    key = (level.id, 1)
    strategy._sequences[key] = _Sequence(accepted_at=19)
    quiet = [
        _bar(30, 110.0, 111.0, 109.0, 110.0, atr=4.0),
        _bar(31, 110.0, 111.0, 109.0, 110.0, atr=4.0),
    ]
    strategy._advance_sequences(_market(60, quiet), [level])
    assert [row["type"] for row in strategy.log_buffer] == ["NO_RETEST"]


def _s02_ready(level_prices: dict[str, float], *, srv: float | None) -> tuple[S02PivotBreakoutRetest, Bar]:
    """A retest bar at close 104.5 on the named daily levels, with the set in force for that bar."""
    strategy = S02PivotBreakoutRetest({"timeframe_minutes": 60, "acc": 3, "weekly_levels": False})
    day = day_bar(START, 120.0, 90.0, 100.0)
    bar = replace(_bar(20, 103.0, 105.0, 100.5, 104.5, atr=4.0, close_us=START + 10 * HOUR, srv=srv), day=day)
    strategy.sets.observe(bar)
    pivots = floor_pivots(day)
    for name in level_prices:
        strategy._sequences[(f"D:{day.end_us}:{name}", 1)] = _Sequence(accepted_at=19)
    del pivots
    return strategy, bar


def test_e16_a_retest_bar_needs_no_srv_of_its_own() -> None:
    """P is (120 + 90 + 100) / 3 = 103.33. Section 3's retest has no `SRV` condition, and acceptance has."""
    strategy, bar = _s02_ready({"P": 0.0}, srv=None)
    prior = _bar(19, 106.0, 107.0, 105.0, 106.0, atr=4.0, close_us=START + 9 * HOUR)
    closing = replace(bar, l=103.0)
    closing = replace(closing, clv=clv(closing.h, closing.l, closing.c))
    market = _market(60, [prior, closing])
    found = strategy.on_close(market)
    assert "SRV_UNDEFINED" not in strategy.reasons
    assert [proposal.side for proposal in found] == [1]


def test_e16_when_the_nearest_level_s_setup_fails_no_other_level_is_tried() -> None:
    """Section 3: use the one nearest the close. A wider stop on that one is not a reason to try the next."""
    strategy = S02PivotBreakoutRetest({"timeframe_minutes": 60, "acc": 3, "weekly_levels": False})
    near, far = Level("near", 104.0), Level("far", 95.0)
    bar = _bar(20, 100.0, 105.0, 94.0, 104.5, atr=4.0, close_us=START + 10 * HOUR)
    calls: list[str] = []

    def refuse(market: MarketView, seen: Bar, level: Level, side: int) -> Proposal | None:
        del market, seen, side
        calls.append(level.id)
        return None

    strategy._setup = refuse  # type: ignore[method-assign,assignment]
    strategy._advance_sequences = lambda *_a: [(far, 1), (near, 1)]  # type: ignore[method-assign]
    strategy.sets.levels = lambda *_a: [far, near]  # type: ignore[method-assign]
    assert strategy.on_close(_market(60, [bar])) == []
    assert calls == ["near"]


# ---- E-17 --------------------------------------------------------------------------------------------------


def test_e17_a_clv_of_exactly_a_half_is_a_half_on_both_sides() -> None:
    """In decimal (1217.34 - 1200.12) / (1234.56 - 1200.12) = 17.22 / 34.44 = 0.5. In binary it can miss by a
    hair, and a threshold of 0.50 would then pass one side of the mirror and fail the other.
    """
    found = None
    for high, low, close in ((1234.56, 1200.12, 1217.34), (67_123.45, 66_123.45, 66_623.45), (0.3, 0.1, 0.2)):
        raw = (close - low) / (high - low)
        if raw != 0.5:
            found = (high, low, close)
    assert found is not None, "no case misses by a hair, so this test would prove nothing"
    value = clv(*found)
    assert value == 0.5
    bar = replace(_bar(0, found[2], found[0], found[1], found[2]), clv=value)
    assert sided_clv(bar, 1) == 0.5
    assert sided_clv(bar, -1) == 0.5


def test_e17_rounding_keeps_real_differences() -> None:
    assert clv(110.0, 100.0, 106.0) == pytest.approx(0.6)
    assert clv(110.0, 100.0, 105.999) < 0.6


# ---- E-11, E-12, E-13 --------------------------------------------------------------------------------------


def _record(
    *, side: int = 1, q0: float = 10.0, fill: float = 100.0, legs: tuple[ExitLeg, ...], status: str = "closed"
) -> TradeRecord:
    return TradeRecord(
        strategy="S",
        version="1",
        symbol="A",
        side=side,
        tag=None,
        signal_us=START,
        decided_as_of_us=START + DELAY_US,
        decision_price=fill,
        collar_limit=fill,
        fill_us=START + MINUTE,
        fill_event_us=START + 2 * MINUTE,
        fill_reference=fill,
        fill=fill,
        q0=q0,
        uncapped_q0=q0,
        leverage_capped=False,
        risk_budget=250.0,
        s0=fill - 5.0,
        r_dec=5.0,
        r=5.0,
        targets_at_setup=(),
        level={},
        entry_fee_rate=0.0,
        legs=legs,
        funding=(),
        stop_path=(),
        target_path=(),
        exit_reason=legs[-1].reason,
        stop_kind="initial",
        status=status,
        bars_held=1,
        best=fill,
        worst=fill,
        through_stop=False,
        gap_unresolved=False,
        gap_start_us=None,
        as_recorded_legs=legs,
        line="",
        is_default=True,
        in_portfolio=True,
    )


def test_e11_the_break_even_multiple_counts_funding() -> None:
    """Gross 400.00, costs 11.20, funding 100.00. Net is 400 - m * 11.20 - 100, so zero at m = 300 / 11.20."""
    tally = SimpleNamespace(gross=40_000, slippage=0, fees=1_120, funding=10_000)
    lines = _cost_lines(cast(Any, tally), 12.0)
    assert lines["break_even_cost_multiple"] == pytest.approx(26.7857, abs=0.0001)
    assert lines["break_even_rt_bps"] == pytest.approx(26.7857 * 12.0, abs=0.01)


def test_e12_a_part_closed_trade_values_only_what_is_still_open() -> None:
    """Half of 10 out at +1,000 total. The other 5 are open at the fill, so 0.00 is open, at 0 `R`. At a mark
    of 102 the 5 hold 10.00, and in `R` that is (2 / 5) * (5 / 10) = 0.2 of the position.
    """
    out = ExitLeg(START + HOUR, 300.0, 300.0, 5.0, 0.0, "TARGET_T1")
    at_fill = ExitLeg(START + 2 * HOUR, 100.0, 100.0, 5.0, 0.0, "OPEN_AT_END", True)
    assert _current_position([_record(legs=(out, at_fill), status="open")]) == {
        "state": "long",
        "open_r": 0.0,
        "unrealised_pnl": 0.0,
    }
    marked = ExitLeg(START + 2 * HOUR, 102.0, 102.0, 5.0, 0.0, "OPEN_AT_END", True)
    row = _current_position([_record(legs=(out, marked), status="open")])
    assert row["unrealised_pnl"] == 10.0
    assert row["open_r"] == pytest.approx(0.2)


def test_e13_a_refused_trade_has_no_exit_reason_on_the_capped_row() -> None:
    one = ExitLeg(START + HOUR, 101.0, 101.0, 10.0, 0.0, "STOP")
    other = ExitLeg(START + HOUR, 102.0, 102.0, 10.0, 0.0, "TIME_STOP")
    kept = _record(legs=(one,))
    refused = _record(legs=(other,))
    axis = np.array([START, START + 2 * HOUR], dtype=np.int64)
    section = _full_section(
        [kept, refused],
        axis=axis,
        marks={"A": np.array([100.0, 100.0])},
        capital_cents=100_000,
        rt_bps=12.0,
        scale_of=lambda trade: 1.0 if trade is kept else 0.0,
    )
    assert section["exit_reasons"] == {"STOP_INITIAL": 1}
    assert _tally([kept, refused], lambda trade: 1.0 if trade is kept else 0.0).count == 1


class _TrailOnce(Strategy):
    """Enters at one close, and at the next asks for a tighter stop, which acts only from the next minute
    on."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}

    def __init__(self, enter_at: int) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.enter_at = enter_at

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.enter_at:
            return []
        return [Proposal(1, 90.0, (TargetPlan("T1", None, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        del market, position
        from hft_crypto.strategies.base import StopCandidate

        return Management(stops=[StopCandidate(95.0, "TRAIL")])


def _path(price_by_minute: dict[int, float], minutes: int) -> pl.DataFrame:
    opens = [START + minute * MINUTE for minute in range(minutes)]
    prices = [price_by_minute.get(minute, 100.0) for minute in range(minutes)]
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(pl.Datetime("us", "UTC")),
            "open": [100.0] * minutes,
            "high": [100.5] * minutes,
            "low": prices,
            "close": [100.0] * minutes,
            "volume": [10.0] * minutes,
            "trade_count": [5] * minutes,
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(
                pl.Datetime("us", "UTC")
            ),
        }
    )


def test_e13_a_stop_is_named_for_the_one_in_force_and_not_the_newest_planned() -> None:
    """Entry decided at hour 1, and a new stop asked at hour 2, acting from the minute after. In the minute
    that closes at hour 2 + 1 minute it has not reached its first minute, so a touch of 90 there is the
    initial stop.
    """
    enter = START + HOUR
    frame = _path({120: 89.0}, 240)
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    stream = _FlatAtr(_TrailOnce(enter), tape, sim_params()).run()
    trade = stream.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.legs[-1].reference == 90.0
    assert trade.stop_path  # a tighter stop had been planned by then
    assert trade.stop_kind == "initial"


def test_e13_once_the_new_stop_acts_a_touch_is_named_for_it() -> None:
    enter = START + HOUR
    frame = _path({125: 94.0}, 240)
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    trade = _FlatAtr(_TrailOnce(enter), tape, sim_params()).run().trades[0]
    assert trade.legs[-1].reference == 95.0
    assert trade.stop_kind == "trailed"


# ---- the author's rulings on the review's readings -----------------------------------------------------


def _s01_bars(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [_bar(index, *row, atr=10.0, minutes=15) for index, row in enumerate(rows)]


def _touches(
    strategy: S01FloorPivotRejection, level: Level, rows: list[tuple[float, float, float, float]]
) -> int:
    from hft_crypto.strategies.s01_floor_pivot_rejection import _LevelState

    strategy._states = {level.id: _LevelState(level.price)}
    bars = _s01_bars(rows)
    for end in range(1, len(bars) + 1):
        strategy._count_touches([level], bars[end - 1], bars[:end])
    return strategy._states[level.id].index[1]


_S01 = {"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"}
_BELOW = (90.0, 91.0, 89.0, 90.0)
_ABOVE = (104.0, 105.0, 103.0, 104.0)
_DIP = (104.0, 105.0, 100.5, 104.0)


def test_s01_a_level_first_seen_above_the_price_has_no_touch_of_support() -> None:
    """Level 100, band 1. Lows of 89 are well below 101, and with no support role not one of them is a
    touch."""
    assert _touches(S01FloorPivotRejection(_S01), Level("L", 100.0), [_BELOW] * 6) == 0


def test_s01_price_must_hold_above_for_the_role_s_four_closes_and_come_back() -> None:
    """Closes of 104 clear 100 + 1. After 3 of them there is no role, so a dip is no touch. After 4 it is."""
    level = Level("L", 100.0)
    assert _touches(S01FloorPivotRejection(_S01), level, [_BELOW, *[_ABOVE] * 3, _DIP]) == 0
    assert _touches(S01FloorPivotRejection(_S01), level, [_BELOW, *[_ABOVE] * 4, _DIP]) == 1


def test_s01_consecutive_touching_bars_count_as_one_and_a_later_return_as_another() -> None:
    level = Level("L", 100.0)
    assert _touches(S01FloorPivotRejection(_S01), level, [*[_ABOVE] * 4, _DIP, _DIP, _DIP]) == 1
    assert _touches(S01FloorPivotRejection(_S01), level, [*[_ABOVE] * 4, _DIP, _ABOVE, _DIP]) == 2


def test_s01_the_first_touch_default_can_now_trade_a_level_price_has_crossed() -> None:
    """Price starts below the level, climbs through it, holds for 4 closes and comes back. Under the old count
    the lows below it had already used the first touch, so this setup could never exist.
    """
    level = Level("L", 100.0)
    above = Level("U", 140.0)
    strategy = S01FloorPivotRejection(_S01)
    from hft_crypto.strategies.s01_floor_pivot_rejection import _LevelState

    strategy._states = {level.id: _LevelState(level.price), above.id: _LevelState(above.price)}
    rows = [_BELOW, _BELOW, *[_ABOVE] * 4, (104.0, 106.0, 100.5, 105.5)]
    bars = _s01_bars(rows)
    for end in range(1, len(bars) + 1):
        strategy._count_touches([level, above], bars[end - 1], bars[:end])
    last = replace(bars[-1], day=day_bar(START, 110.0, 90.0, 100.0), atrd=100.0, day_open=100.0)
    proposal = strategy._setup(_market(15, [*bars[:-1], last]), last, [level, above], 1)
    assert proposal is not None
    assert proposal.level["id"] == "L"


def _s03_ready(*lows: tuple[float, int]) -> tuple[S03MarketStructure, MarketView, Bar, Swing]:
    strategy = S03MarketStructure({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2})
    for price, valid_from in lows:
        strategy.sigma.entries.append(Swing(LOW, price, 0, valid_from - HOUR, valid_from))
    close = START + 20 * HOUR
    bar = replace(_bar(19, 104.0, 112.0, 103.0, 111.0, close_us=close))
    broken = Swing("H", 110.0, 0, close - 5 * HOUR, close - 3 * HOUR)
    market = _market(60, [bar], (240,))
    return strategy, market, bar, broken


def test_s03_a_swing_low_confirmed_at_the_bos_close_means_no_setup_and_no_earlier_one_stands_in() -> None:
    """Lows 90, 95, and 100 confirmed at this very close. Before the ruling 95 stood in, over 90, and
    traded."""
    close = START + 20 * HOUR
    strategy, market, bar, broken = _s03_ready(
        (90.0, close - 10 * HOUR), (95.0, close - 5 * HOUR), (100.0, close)
    )
    assert strategy._setup(market, bar, 1, broken) is None
    assert strategy.reasons["NO_HIGHER_LOW"] == 1


def test_s03_a_swing_low_confirmed_earlier_is_still_the_higher_low() -> None:
    close = START + 20 * HOUR
    strategy, market, bar, broken = _s03_ready((90.0, close - 10 * HOUR), (95.0, close - 5 * HOUR))
    proposal = strategy._setup(market, bar, 1, broken)
    assert proposal is not None
    assert proposal.level["base_swing"] == 95.0


def _position(n: int, *, fill: float = 100.0, r: float = 10.0, memo: Any) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            side=1,
            n=n,
            memo=memo,
            fill_side=fill,
            r=r,
            highest=fill,
            filled=lambda _name: False,
            be_plus=fill,
            stop=fill - r,
        ),
    )


def _s03_stall(checks: list[tuple[int, float, bool]]) -> list[str | None]:
    """(n, close, has a price) for each close. Stall bar 30 on 1h, with no BOS since entry, and 1R = 110."""
    strategy = S03MarketStructure({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2})
    memo = S03Memo()
    found: list[str | None] = []
    for n, close, priced in checks:
        bar = replace(_bar(n, close, close + 1, close - 1, close), has_price=priced)
        found.append(
            strategy.manage(cast(Any, SimpleNamespace(bar=bar)), _position(n, memo=memo)).exit_note or None
        )
    return found


def test_e05_s03_the_stall_exit_is_one_check_at_its_bar() -> None:
    assert _s03_stall([(29, 100.0, True), (30, 105.0, True)]) == [None, "STALL"]
    assert _s03_stall([(30, 115.0, True), (35, 105.0, True), (40, 101.0, True)]) == [None, None, None]


def test_e05_s03_with_no_close_at_that_bar_the_check_falls_at_the_next_close_that_has_one() -> None:
    assert _s03_stall([(30, 105.0, False), (31, 105.0, True)]) == [None, "STALL"]
    assert _s03_stall([(30, 105.0, False), (31, 115.0, True), (32, 105.0, True)]) == [None, None, None]


def _s10_memo() -> S10Memo:
    return S10Memo(box_high=100.0, box_height=4.0, box_mid=98.0, atr_e=2.0)


def _s10(checks: list[tuple[int, float, bool]], *, atr: float = 2.0) -> list[str | None]:
    """(n, close, has a price) on 4h: thesis at 6, stall at 18, and 1R = 110. ATR 2 is no rise on `ATR_e`."""
    strategy = S10VolatilityCompression({"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12})
    memo = _s10_memo()
    found: list[str | None] = []
    for n, close, priced in checks:
        bar = replace(_bar(n, close, close + 0.5, close - 0.5, close, atr=atr, minutes=240), has_price=priced)
        found.append(
            strategy.manage(cast(Any, SimpleNamespace(bar=bar)), _position(n, memo=memo)).exit_note or None
        )
    return found


def test_e05_s10_the_stall_exit_is_one_check_at_its_bar() -> None:
    """ATR 3 is 1.5 times `ATR_e`, so the thesis check at bar 6 passes. Only the stall is under test."""
    assert _s10([(6, 115.0, True), (18, 105.0, True)], atr=3.0) == [None, "STALL"]
    assert _s10([(6, 115.0, True), (18, 115.0, True), (24, 105.0, True)], atr=3.0) == [None, None, None]


def test_e05_s10_with_no_close_at_a_check_s_bar_it_falls_at_the_next_close_that_has_one() -> None:
    assert _s10([(6, 115.0, False), (7, 115.0, True)]) == [None, "THESIS_CHECK"]
    assert _s10([(6, 115.0, True), (18, 105.0, False), (19, 105.0, True)], atr=3.0) == [None, None, "STALL"]


def test_e05_s10_a_thesis_check_passed_is_not_made_again() -> None:
    """Passed at 6 with ATR 3. A later bar with no rise on `ATR_e` does not trigger it."""
    strategy = S10VolatilityCompression({"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12})
    memo = _s10_memo()
    passed = replace(_bar(6, 115.0, 115.5, 114.5, 115.0, atr=3.0, minutes=240))
    assert (
        strategy.manage(cast(Any, SimpleNamespace(bar=passed)), _position(6, memo=memo)).exit_reason is None
    )
    later = replace(_bar(7, 115.0, 115.5, 114.5, 115.0, atr=2.0, minutes=240))
    assert strategy.manage(cast(Any, SimpleNamespace(bar=later)), _position(7, memo=memo)).exit_reason is None


def test_s05_the_bar_that_completes_travel_cannot_open_the_retest() -> None:
    """Top 1000, X 1005, ATR 10. A bar with high 1015 completes travel and also dips to 995. One bar does not
    show which came first, so the retest opens only on the next bar with `L <= top`.
    """
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    flip = _Flip("flip", 1, 1000.0, 980.0, 990.0, 1005.0, 0)
    strategy.flips.append(flip)
    assert strategy._advance_flips(_bar(5, 1005, 1015, 995, 1010)) == []
    assert flip.travelled is True
    assert flip.retest_start is None
    assert strategy._advance_flips(_bar(6, 1010, 1012, 998, 1008)) == [flip]
    assert flip.retest_start == 6


def test_s05_travel_at_the_break_bar_lets_the_next_bar_open_the_retest() -> None:
    """A flip born with a break bar's high already 1 ATR over `top` has completed travel on that bar."""
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    zone = Zone("E:-1:1", -1, 980.0, 1000.0, 10.0, 1.0, 1.0, 0, START, 0, True)
    strategy.book.broken_now = [zone]
    strategy._new_flips(_bar(1, 990, 1020, 989, 1005))
    flip = strategy.flips[0]
    assert (flip.top, flip.extreme, flip.travelled) == (1000.0, 1020.0, True)
    assert strategy._advance_flips(_bar(2, 1005, 1006, 998, 1004)) == [flip]


def test_e16_s04_when_the_highest_q_zone_fails_no_other_zone_is_tried() -> None:
    strategy = S04SupplyDemandZones({"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0})
    low_q = Zone("low", 1, 100.0, 95.0, 10.0, 0.2, 0.2, 0, START, 0, True)
    high_q = Zone("high", 1, 100.0, 95.0, 10.0, 1.0, 1.0, 0, START, 0, True)
    strategy.book.entry = [low_q, high_q]
    strategy.book.update = lambda _bars: None  # type: ignore[method-assign,assignment]
    strategy._qualifies = lambda *_a: True  # type: ignore[method-assign]
    calls: list[str] = []

    def refuse(market: MarketView, bar: Bar, zone: Zone) -> Proposal | None:
        del market, bar
        calls.append(zone.id)
        return None

    strategy._setup = refuse  # type: ignore[method-assign]
    bar = _bar(5, 100.0, 101.0, 99.0, 100.0)
    assert strategy.on_close(_market(60, [_bar(4, 100.0, 101.0, 99.0, 100.0), bar])) == []
    assert calls == ["high"]


def test_e16_s05_when_the_nearest_flip_fails_no_other_flip_is_tried() -> None:
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    near = _Flip("near", 1, 99.0, 95.0, 97.0, 120.0, 0)
    far = _Flip("far", 1, 80.0, 75.0, 77.0, 120.0, 0)
    strategy._advance_flips = lambda _bar: [far, near]  # type: ignore[method-assign,assignment]
    calls: list[str] = []

    def refuse(market: MarketView, bar: Bar, flip: _Flip) -> Proposal | None:
        del market, bar
        calls.append(flip.id)
        return None

    strategy._setup = refuse  # type: ignore[method-assign]
    assert strategy.on_close(_market(60, [_bar(5, 100.0, 101.0, 99.0, 100.0)])) == []
    assert calls == ["near"]


def test_e16_s06_takes_one_pool_per_side_and_a_failed_setup_tries_no_other_pool() -> None:
    """Checked because the author did not. Section 3: the highest pool the close reclaimed, for each side."""
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": False})
    high = _Sweep("high", 1, 99.0, 0, 97.0, 110.0)
    low = _Sweep("low", 1, 90.0, 0, 88.0, 110.0)
    strategy._advance_sweeps = lambda *_a: [low, high]  # type: ignore[method-assign]
    calls: list[str] = []

    def refuse(market: MarketView, bar: Bar, sweep: _Sweep, pools: Any) -> Proposal | None:
        del market, bar, pools
        calls.append(sweep.pool_id)
        return None

    strategy._setup = refuse  # type: ignore[method-assign]
    bar = replace(
        _bar(5, 100.0, 101.0, 99.0, 100.0, minutes=15),
        atrd=50.0,
        day_open=100.0,
        day=day_bar(START, 110.0, 90.0, 100.0),
    )
    assert strategy.on_close(_market(15, [bar])) == []
    assert calls == ["high"]


def test_a_funding_gap_states_what_a_rate_would_apply_to() -> None:
    assert FundingGap(START, 2.0, 50.0).notional == 100.0
