"""EN-04: one named test for each injected leak that passed every test in section 5 of
docs/reviews/leak/engine_2026-11-05.md.

The two the auditor calls unreachable or redundant on candles are not here: a pending tail finishing a day,
which needs bars from trades and stage 2, and a zero-trade price kept in the tape, which the converter already
nulls. The next-bar filter and the walk past a close are also held by tests/leak/test_whole_run_cuts.py.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, ClassVar

import numpy as np
import polars as pl
import pytest

from engine_helpers import DELAY_US, costs, engine_config, generated_trades, sim_params, tape_and_trades, utc
from hft_crypto.engine.accounting import ExitLeg, FundingCharge, book_trade
from hft_crypto.engine.indicators import clv
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.portfolio import apply_gross_cap, trade_key
from hft_crypto.engine.simulator import Simulator, StreamResult, TradeRecord
from hft_crypto.engine.tape import Bar, MinuteTape
from hft_crypto.reports.portfolio import build_rows
from hft_crypto.strategies import build_strategy
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
from hft_crypto.strategies.s09_session_range_breakout import DAY as S09_DAY
from hft_crypto.strategies.s09_session_range_breakout import S09SessionRangeBreakout, _Range
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression
from hft_crypto.strategies.zones import ZoneBook

START = utc(2000, 3, 6)
MINUTE = 60_000_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
UTC_US = pl.Datetime("us", "UTC")


def _rows(prices: list[tuple[float, float, float, float]], *, start: int = START) -> pl.DataFrame:
    """One 1m row per (open, high, low, close)."""
    opens = [start + index * MINUTE for index in range(len(prices))]
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(UTC_US),
            "open": [row[0] for row in prices],
            "high": [row[1] for row in prices],
            "low": [row[2] for row in prices],
            "close": [row[3] for row in prices],
            "volume": [10.0] * len(prices),
            "trade_count": [5] * len(prices),
            "gap": [False] * len(prices),
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(UTC_US),
        }
    )


FLAT = (100.0, 100.5, 99.5, 100.0)


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [replace(bar, atr=2.0, atr_last=2.0, complete=True) for bar in self.tape.frame(minutes)]


def _params() -> Any:
    return sim_params(
        risk_budget=100.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )


# ---- the walk and a position's own figures -----------------------------------------------------------------


class _Watched(Simulator):
    """Asserts at each close that no row after it has been walked."""

    def _at_close(self, bar: Bar, market: MarketView) -> None:
        walked = self._cursor
        assert walked == 0 or self._close_us[walked - 1] <= bar.close_us, "a row after the close was walked"
        super()._at_close(bar, market)


def test_no_row_after_a_close_is_walked_at_that_close() -> None:
    start = utc(2000, 1, 3)
    trades = generated_trades(seed=7, start_us=start, days=40)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 40 * DAY)
    params = dict(engine_config().strategies["S03"].default().params)
    stream = _Watched(build_strategy("S03", params), tape, sim_params(), trades=tape_trades).run()
    assert stream.trades, "nothing was held, so the walk was never stepped row by row"


class _Recorder(Strategy):
    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}

    def __init__(self) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.seen: dict[int, float] = {}

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != START + HOUR:
            return []
        return [Proposal(1, 90.0, (TargetPlan("T1", None, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        self.seen[market.now_us] = position.highest
        return Management()


def test_a_position_s_best_price_holds_nothing_after_the_close_it_is_read_at() -> None:
    """The highest high through hour 2 is 101. The minute after hour 2 spikes to 150, and must not show at
    hour 2."""
    prices = [FLAT] * 240
    prices[100] = (100.0, 101.0, 99.5, 100.0)
    prices[120] = (100.0, 150.0, 99.5, 100.0)
    strategy = _Recorder()
    _FlatAtr(strategy, MinuteTape.from_frame(_rows(prices), symbol="S", delay_us=DELAY_US), _params()).run()
    assert strategy.seen[START + 2 * HOUR] == 101.0
    assert strategy.seen[START + 3 * HOUR] == 150.0


def test_mark_price_and_mark_series_never_return_a_later_close() -> None:
    """Closes 10, 20 and 30 at the ends of minutes 1, 2 and 3. A moment just before minute 2's close sees
    10."""
    tape = MinuteTape.from_frame(
        _rows([(10.0, 10.0, 10.0, 10.0), (20.0, 20.0, 20.0, 20.0), (30.0, 30.0, 30.0, 30.0)]),
        symbol="S",
        delay_us=DELAY_US,
    )
    assert tape.mark_price(START + 2 * MINUTE - 1) == 10.0
    assert tape.mark_price(START + 2 * MINUTE) == 20.0
    assert tape.mark_price(START) is None
    moments = np.array([START + MINUTE, START + 2 * MINUTE - 1, START + 3 * MINUTE], dtype=np.int64)
    assert tape.mark_series(moments).tolist() == [10.0, 10.0, 30.0]


# ---- the cap, in two worlds that differ only after the decision --------------------------------------------


def _held(name: str, decided: int, notional: float, exit_at: int, exit_price: float) -> TradeRecord:
    leg = ExitLeg(exit_at, exit_price, exit_price, notional / 100.0, 0.0, "TEST")
    return TradeRecord(
        strategy=name,
        version="1",
        symbol=name,
        side=1,
        tag=None,
        signal_us=decided - DELAY_US,
        decided_as_of_us=decided,
        decision_price=100.0,
        collar_limit=100.0,
        fill_us=decided + MINUTE,
        fill_event_us=decided + 2 * MINUTE,
        fill_reference=100.0,
        fill=100.0,
        q0=notional / 100.0,
        uncapped_q0=notional / 100.0,
        leverage_capped=False,
        risk_budget=250.0,
        s0=95.0,
        r_dec=5.0,
        r=5.0,
        targets_at_setup=(),
        level={},
        entry_fee_rate=0.0,
        legs=(leg,),
        funding=(),
        stop_path=(),
        target_path=(),
        exit_reason="TEST",
        stop_kind="initial",
        status="closed",
        bars_held=1,
        best=100.0,
        worst=100.0,
        through_stop=False,
        gap_unresolved=False,
        gap_start_us=None,
        as_recorded_legs=(leg,),
        line="line",
        is_default=True,
        in_portfolio=True,
    )


DECIDED = START + 10 * HOUR


def _world(later: float) -> list[TradeRecord]:
    """A is held from hour 1. B and C both decide at hour 10, B first in line. After that everything differs:
    the marks, every exit and its price, which of B and C ends first, and so which wins.
    """
    exit_at = START + (20 if later > 100 else 30) * HOUR
    return [
        _held("A", START + HOUR, 600.0, exit_at, later),
        _held("B", DECIDED, 600.0, DECIDED + (5 if later > 100 else 1) * HOUR, later),
        _held("C", DECIDED, 300.0, DECIDED + (2 if later > 100 else 9) * HOUR, 2.0 * later),
    ]


def _price(later: float) -> Any:
    def mark(symbol: str, at_us: int) -> float | None:
        del symbol
        return 100.0 if at_us <= DECIDED else later

    return mark


@pytest.mark.parametrize("later", [200.0, 50.0], ids=["rise after", "fall after"])
def test_the_cap_reads_nothing_after_a_decision(later: float) -> None:
    """Limit 1,000. A holds 600 at a mark of 100 at hour 10, so B, of 600, has 400 of room: 2/3. Whatever
    comes after, whatever the marks, the exits and their order, and whoever wins, the scales stay those.
    """
    trades = _world(later)
    found = apply_gross_cap(trades, capital=1000.0, gross_cap=1.0, mark=_price(later))
    assert found[trade_key(trades[1])].scale == pytest.approx(400.0 / 600.0)
    assert found[trade_key(trades[2])].scale == 0.0


# ---- the portfolio figure takes the declared line only (D-35) ----------------------------------------------


def _stream(line: str, *, in_portfolio: bool, exit_price: float) -> StreamResult:
    trade = replace(
        _held("S01", DECIDED, 600.0, DECIDED + 5 * HOUR, exit_price), line=line, in_portfolio=in_portfolio
    )
    trade = replace(trade, symbol="SYNTHBTC")
    return StreamResult(
        strategy="S01",
        line=line,
        is_default=in_portfolio,
        in_portfolio=in_portfolio,
        params={},
        version="1",
        symbol="SYNTHBTC",
        timeframe_minutes=15,
        closes=1,
        setups=1,
        live_comparable=False,
        requirements=(),
        reasons={},
        counters={},
        trades=[trade],
        events=[],
    )


def test_the_portfolio_figure_counts_the_declared_line_and_never_a_better_one() -> None:
    """The declared line loses 60.00 on 6 at 100 to 90. Another line gains 600.00. The figure is -60.00."""
    streams = [
        _stream("declared", in_portfolio=True, exit_price=90.0),
        _stream("better", in_portfolio=False, exit_price=200.0),
    ]
    axis = np.array([DECIDED, DECIDED + 10 * HOUR], dtype=np.int64)
    rows = build_rows(
        streams,
        config=engine_config(),
        labels=(),
        axis=axis,
        marks={"SYNTHBTC": np.array([100.0, 100.0])},
        mark_at=lambda _symbol, _at: 100.0,
    )
    figure = rows.portfolio[0]
    assert figure["net_pnl"] == -60.0
    assert figure["trades"] == 1


def test_funding_reaches_net_through_a_whole_trade() -> None:
    """Long 10 at 100, out at 110: gross 100.00. A 1% charge on 10 at a mark of 105 is 10.50. Net 89.50."""
    leg = ExitLeg(START + 2 * HOUR, 110.0, 110.0, 10.0, 0.0, "TEST")
    _, booked = book_trade(
        side=1,
        entry_us=START,
        fill_reference=100.0,
        fill=100.0,
        q0=10.0,
        entry_fee_rate=0.0,
        legs=(leg,),
        funding=(FundingCharge(START + HOUR, 0.01, 10.0, 105.0),),
    )
    assert (booked.gross, booked.funding, booked.net) == (10_000, 1_050, 8_950)


# ---- timing of updates, and the order inside a minute ------------------------------------------------------


class _Update(Strategy):
    """Enters at hour 1, S0 90 and T1 130. At the close of hour 2 it asks for a stop of 95 or a T1 of 101."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}

    def __init__(self, what: str) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.what = what

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != START + HOUR:
            return []
        return [Proposal(1, 90.0, (TargetPlan("T1", 130.0, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        if market.now_us != START + 2 * HOUR:
            return Management()
        if self.what == "stop":
            return Management(stops=[StopCandidate(95.0, "TEST")])
        return Management(targets=[TargetMove("T1", 101.0, "TEST")])


@pytest.mark.parametrize("what", ["stop", "target"])
def test_an_update_first_acts_in_the_minute_opening_at_or_after_its_close_plus_the_delay(what: str) -> None:
    """Decided at hour 2. With a delay of 10 s the first minute it may act in opens at hour 2 + 1 minute. The
    minute opening at hour 2 straddles the decision and keeps the old values, so a touch there does nothing.
    """
    touch = (100.0, 101.5, 94.5, 100.0) if what == "target" else (100.0, 100.5, 94.5, 100.0)
    early = [FLAT] * 240
    early[120] = touch
    stream = _FlatAtr(
        _Update(what), MinuteTape.from_frame(_rows(early), symbol="S", delay_us=DELAY_US), _params()
    ).run()
    assert stream.trades[0].status == "open"
    due = [FLAT] * 240
    due[121] = touch
    stream = _FlatAtr(
        _Update(what), MinuteTape.from_frame(_rows(due), symbol="S", delay_us=DELAY_US), _params()
    ).run()
    leg = stream.trades[0].legs[0]
    assert leg.event_us == START + 122 * MINUTE
    assert leg.reference == (101.0 if what == "target" else 95.0)


@pytest.mark.parametrize("minute", [61, 90], ids=["on the fill minute", "later"])
def test_a_minute_touching_both_the_stop_and_a_target_is_a_stop(minute: int) -> None:
    """C7: inside one bar the stop comes first, on the fill minute as later. Low 89 is under the stop of 90
    and high 131 over the target of 130.
    """
    prices = [FLAT] * 180
    prices[minute] = (100.0, 131.0, 89.0, 100.0)
    stream = _FlatAtr(
        _Update("none"), MinuteTape.from_frame(_rows(prices), symbol="S", delay_us=DELAY_US), _params()
    ).run()
    trade = stream.trades[0]
    assert trade.fill_us == START + 61 * MINUTE
    assert [leg.reason for leg in trade.legs] == ["STOP"]


# ---- rules that moved with no future data ------------------------------------------------------------------


def test_a_bucket_not_yet_closed_gives_no_bar() -> None:
    """Rows through 1:30. The hour closing at 2:00 has not closed, so the 1h frame stops at 1:00."""
    tape = MinuteTape.from_frame(_rows([FLAT] * 90), symbol="S", delay_us=DELAY_US)
    assert [bar.close_us for bar in tape.frame(60)] == [START + HOUR]


_ZONE = [
    (1030, 1031, 1020, 1021),
    (1021, 1022, 1011, 1012),
    (1012, 1013, 1002, 1003),
    (1001, 1004, 997, 1002),
    (1002, 1003, 996, 1001),
    (1003, 1014, 1002.5, 1013),
    (1013, 1020, 1001.5, 1018),
    (1018, 1019, 1001, 1015),
]


def _zone_bars() -> list[Bar]:
    def bar(index: int, o: float, h: float, low: float, c: float) -> Bar:
        return Bar(
            index=index,
            minutes=60,
            open_us=START + index * HOUR,
            close_us=START + (index + 1) * HOUR,
            o=o,
            h=h,
            l=low,
            c=c,
            v=1.0,
            has_price=True,
            complete=True,
            pending_tail=False,
            gap=False,
            late_gap=False,
            tr=h - low,
            atr=10.0,
            atr_last=10.0,
            vr=1.0,
            srv=1.5,
            clv=clv(h, low, c),
            atrd=None,
            day=None,
            week=None,
            day_at_close=None,
            week_at_close=None,
            day_open=None,
        )

    return [bar(index, *row) for index, row in enumerate(_ZONE)]


def _book(count: int) -> ZoneBook:
    book = ZoneBook(60)
    bars = _zone_bars()
    for end in range(1, count + 1):
        book.update(bars[:end])
    return book


def test_a_zone_is_dated_at_its_last_departure_close_and_not_by_its_base() -> None:
    zone = next(zone for zone in _book(7).entry if zone.side == 1)
    assert (zone.birth_index, zone.birth_us) == (6, START + 7 * HOUR)


def test_a_zone_is_not_touched_by_the_bar_that_creates_it() -> None:
    """Bar 6 dips to 1001.5, under `prox` 1002, and creates the zone. Bar 7 dips to 1001, and is its first
    touch."""
    assert next(zone for zone in _book(7).entry if zone.side == 1).touch_starts == []
    assert next(zone for zone in _book(8).entry if zone.side == 1).touch_starts == [START + 8 * HOUR]


def test_a_zone_s_score_counts_its_touches() -> None:
    """D = 16/30, T = 0.6. With one touch before the close, F = 0.5 * (1 - 2/336). Q = 100 * (0.5 D + 0.3 T +
    0.2 F)."""
    book = _book(8)
    zone = next(zone for zone in book.entry if zone.side == 1)
    later = replace(_zone_bars()[7], index=8, close_us=START + 9 * HOUR)
    fresh = 0.5 * (1.0 - 2.0 / 336.0)
    assert book.quality(zone, later) == pytest.approx(100.0 * (0.5 * 16 / 30 + 0.3 * 0.6 + 0.2 * fresh))


def _weekday_hours(days: int, *, gap_at: int | None = None) -> list[Bar]:
    """Hourly bars over whole days from START, a Monday, with one flagged bar if asked."""
    found = []
    for index in range(days * 24):
        flagged = index == gap_at
        found.append(
            replace(
                _zone_bars()[0],
                index=index,
                open_us=START + index * HOUR,
                close_us=START + (index + 1) * HOUR,
                o=100.0,
                h=101.0,
                l=99.0,
                c=100.0,
                v=10.0 + (index % 24),
                gap=flagged,
                complete=not flagged,
            )
        )
    return found


def _feed(strategy: S09SessionRangeBreakout, bars: list[Bar]) -> None:
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=60, higher=(), trades=None)
    for bar in bars:
        market._release(bar, {})
        strategy.on_close(market)


def test_s09_a_flagged_hour_never_enters_the_profile_so_the_fit_fails_closed() -> None:
    """The strict rule: one flagged weekday hour in the 90 days before the date, and that quarter has no
    profile."""
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    start_day = START // S09_DAY
    first_date = (start_day + 120) * S09_DAY
    del first_date
    bars = _weekday_hours(120, gap_at=30 * 24 + 10)
    _feed(strategy, bars)
    logged = [row for row in strategy.log_buffer if row["type"] == "SEASONAL_PROFILE_NOT_COMPUTED"]
    assert logged and logged[-1]["reason"] == "MISSING_HOUR"
    assert strategy._profile is None


def test_s09_an_old_profile_is_not_carried_on_into_a_quarter_whose_fit_fails() -> None:
    """A clean quarter fits a profile. The next calendar date's window has a flagged hour, so it has none."""
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    days = 210
    bars = _weekday_hours(days, gap_at=150 * 24 + 10)
    _feed(strategy, bars)
    fitted = [row for row in strategy.log_buffer if row["type"] == "SEASONAL_PROFILE_FITTED"]
    failed = [row for row in strategy.log_buffer if row["type"] == "SEASONAL_PROFILE_NOT_COMPUTED"]
    assert fitted
    assert failed and failed[-1]["fitted_at_us"] > fitted[-1]["fitted_at_us"]
    assert strategy._profile is None


def test_s09_the_first_break_spends_the_day_s_break_even_when_its_setup_fails() -> None:
    """Range 99 to 101 and ATR 1. Bar one breaks with VR undefined, so its setup fails. Bar two breaks again
    with VR defined, and is no setup, because the day's break is spent.
    """
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    end = START + 8 * HOUR
    item = _Range(START, end, end + 4 * HOUR, end + 11 * HOUR, highs=[101.0] * 8, lows=[99.0] * 8)
    strategy._qualified = [item]
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=60, higher=(), trades=None)
    first = replace(
        _zone_bars()[0], close_us=end + HOUR, o=101.0, h=103.0, l=101.0, c=103.0, atr=1.0, vr=None
    )
    second = replace(first, close_us=end + 2 * HOUR, vr=1.0)
    market._release(first, {})
    assert strategy._look_for_break(market, first) is None
    market._release(second, {})
    assert strategy._look_for_break(market, second) is None
    assert item.broken is True


def test_s10_a_bar_is_not_in_its_own_compression_window() -> None:
    """Armed needs `CF` on 3 of bars k - 6 to k - 1. Two of them and bar k itself make three, which is not
    armed."""
    strategy = S10VolatilityCompression({"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12})
    bars = [
        replace(_zone_bars()[0], index=index, o=100.0, h=101.0, l=99.0, c=100.0, atr=2.0)
        for index in range(15)
    ]
    strategy._compressed = [False] * 12 + [True, True, True]
    assert strategy._armed_box(bars) is None
    strategy._compressed = [False] * 11 + [True, True, True, False]
    assert strategy._armed_box(bars) is not None
