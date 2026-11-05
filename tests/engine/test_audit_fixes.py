"""Findings of docs/reviews/leak/engine_2026-11-05.md, each on the auditor's own scenario where it gives
one."""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

import polars as pl
import pytest

from engine_helpers import DELAY_US, costs, sim_params, utc
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.portfolio import apply_gross_cap, trade_key
from hft_crypto.engine.simulator import (
    ENTRY_ACROSS_GAP,
    ENTRY_COLLAR,
    FundingEvent,
    RefusedEntry,
    Simulator,
    StreamResult,
    TradeRecord,
)
from hft_crypto.engine.tape import Bar, MinuteTape
from hft_crypto.strategies.base import REST, Management, PositionView, Proposal, Strategy, TargetPlan

START = utc(2000, 3, 6)
MINUTE = 60_000_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
UTC_US = pl.Datetime("us", "UTC")


class _Hold(Strategy):
    """Goes long once, at a stated close, with a stop far below, and holds to the end of the data."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 100_000.0}

    def __init__(self, enter_at: int, *, s0: float = 50.0, name: str = "TEST", limit: bool = True) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.id = name
        self.enter_at = enter_at
        self.s0 = s0
        self.limit = limit

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.enter_at:
            return []
        return [Proposal(1, self.s0, (TargetPlan("T1", None, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        del market, position
        return Management()


def _rows(
    opens: list[int], price: float | dict[int, float], *, gap: frozenset[int] = frozenset()
) -> pl.DataFrame:
    """One row a minute. A dict maps a row's open to its price, and a row not named takes the default of
    100."""
    prices = [price.get(item, 100.0) if isinstance(price, dict) else price for item in opens]
    size = len(opens)
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(UTC_US),
            "open": prices,
            "high": [value + 0.5 for value in prices],
            "low": [value - 0.5 for value in prices],
            "close": prices,
            "volume": [10.0] * size,
            "trade_count": [5] * size,
            "gap": [item in gap for item in opens],
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(UTC_US),
        }
    )


def _minutes(count: int, *, leave_out: range | tuple[int, ...] = ()) -> list[int]:
    return [START + index * MINUTE for index in range(count) if index not in leave_out]


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [
            replace(bar, atr=2.0, atr_last=2.0, complete=True, gap=False) for bar in self.tape.frame(minutes)
        ]


def _run(
    frame: pl.DataFrame,
    strategy: Strategy,
    *,
    funding: tuple[FundingEvent, ...] = (),
    risk_budget: float = 500.0,
    capital: float = 1_000_000.0,
) -> StreamResult:
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=risk_budget,
        capital=capital,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )
    return _FlatAtr(strategy, tape, params, funding=funding).run()


# ---- EN-01 -------------------------------------------------------------------------------------------------


def _cap_worlds(price_later: float) -> tuple[TradeRecord, TradeRecord, MinuteTape, MinuteTape]:
    """The auditor's case on real simulator output. A enters on a first symbol and holds across a flagged
    minute. B decides at hour 3 on another symbol. Every row up to hour 4 is the same in both worlds, and
    the only difference is the price after that.
    """
    hours = 8 * 60
    flagged = START + 100 * MINUTE
    a_prices = {item: (100.0 if item < START + 4 * HOUR else price_later) for item in _minutes(hours)}
    a_frame = _rows(_minutes(hours), a_prices, gap=frozenset({flagged}))
    a_tape = MinuteTape.from_frame(a_frame, symbol="A", delay_us=DELAY_US)
    b_tape = MinuteTape.from_frame(_rows(_minutes(hours), 100.0), symbol="B", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=500.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )
    a = _FlatAtr(_Hold(START + HOUR, s0=50.0, name="A"), a_tape, params).run().trades[0]
    b = _FlatAtr(_Hold(START + 3 * HOUR, s0=99.0, name="B"), b_tape, params).run().trades[0]
    return a, b, a_tape, b_tape


def _scale_of_b(a: TradeRecord, b: TradeRecord, a_tape: MinuteTape, b_tape: MinuteTape) -> float:
    def mark(symbol: str, at_us: int) -> float | None:
        return (a_tape if symbol == "A" else b_tape).mark_price(at_us)

    return apply_gross_cap([a, b], capital=1000.0, gross_cap=26.0, mark=mark)[trade_key(b)].scale


def test_en01_a_later_entry_s_size_does_not_rest_on_prices_after_its_decision() -> None:
    """A: 500 / 50 = 10 at 100, so 1,000 of gross. B: 500 / 1 = 500 at 100, so 50,000 of notional. The limit
    is 26 * 1,000 = 26,000. If A counts as held, B has 25,000 of room and a scale of 0.50.

    After hour 4 one world rises, where the headline is the stop at the flagged minute and A would look gone.
    The other falls through the stop, where the recorded path stands. Either way A was held at hour 3.
    """
    rising = _cap_worlds(120.0)
    falling = _cap_worlds(40.0)
    assert rising[0].legs[-1].reason == "GAP_UNRESOLVED_STOP"
    assert falling[0].legs[-1].reason != "GAP_UNRESOLVED_STOP"
    rose = _scale_of_b(*rising)
    fell = _scale_of_b(*falling)
    assert rose == pytest.approx(0.5)
    assert fell == pytest.approx(0.5)


# ---- EN-02 -------------------------------------------------------------------------------------------------


def test_en02_the_auditor_s_case_a_settlement_inside_missing_rows_is_charged() -> None:
    """Long from minute 60, settlement at minute 120, rows 110 to 129 missing. The position was open, so one
    charge is made, at the mark before the hole. 10 at 100, 10 bp: 1.00.
    """
    frame = _rows(_minutes(240, leave_out=range(110, 130)), 100.0)
    stream = _run(frame, _Hold(START + HOUR), funding=(FundingEvent(START + 120 * MINUTE, 0.001),))
    logged = [event for event in stream.events if event["type"] == "FUNDING"]
    assert [event["settle_us"] for event in logged] == [START + 120 * MINUTE]
    assert logged[0]["mark"] == 100.0
    assert logged[0]["qty"] == pytest.approx(10.0)


@pytest.mark.parametrize("days_missing", [1, 31], ids=["a whole day", "a whole month"])
def test_en02_a_whole_day_or_month_absent_across_a_settlement_is_charged(days_missing: int) -> None:
    """As a failed monthly file leaves. The price falls below the stop afterwards, so the recorded path is the
    worse way and is the headline, and its funding shows on the trade. 10 at 100, 10 bp: 1.00 for each
    settlement every 8 hours, of which `3 * days_missing` fall in the hole.
    """
    missing = range(24 * 60, (1 + days_missing) * 24 * 60)
    total = (3 + days_missing) * 24 * 60
    opens = _minutes(total, leave_out=missing)
    after_hole = START + (1 + days_missing) * DAY + 6 * HOUR
    frame = _rows(opens, {item: 40.0 for item in opens if item >= after_hole})
    settles = tuple(
        FundingEvent(START + DAY + (index + 1) * 8 * HOUR, 0.001) for index in range(3 * days_missing - 1)
    )
    stream = _run(frame, _Hold(START + HOUR), funding=settles)
    trade = stream.trades[0]
    assert trade.gap_unresolved is True
    assert trade.legs[-1].reason == "STOP_GAP"
    assert len(trade.funding) == len(settles)
    assert trade.book()[1].funding == 100 * len(settles)


# ---- EN-06 -------------------------------------------------------------------------------------------------


def test_en06_the_auditor_s_case_an_entry_does_not_wait_across_missing_rows() -> None:
    """Decided at minute 60 at 100. Rows 61 to 99 are missing and the price drifts to 99.20. It used to fill
    there, with nothing on the record. A marketable limit sent at 60:10 would have met a price nobody has.
    """
    opens = _minutes(180, leave_out=range(61, 100))
    frame = _rows(opens, {item: 99.2 for item in opens if item >= START + 100 * MINUTE})
    stream = _run(frame, _Hold(START + HOUR))
    assert stream.trades == []
    assert stream.counters["entry_across_gap"] == 1
    logged = [event for event in stream.events if event["type"] == ENTRY_ACROSS_GAP]
    assert [event["first_allowed_us"] for event in logged] == [START + 61 * MINUTE]
    assert [item.reason for item in stream.refused_entries] == [ENTRY_ACROSS_GAP]


def test_en06_a_flagged_first_minute_gives_no_fill_even_with_a_price_on_it() -> None:
    """A row that failed its checks. Keeping the fill off it is the point."""
    frame = _rows(_minutes(180), 100.0, gap=frozenset({START + 61 * MINUTE}))
    stream = _run(frame, _Hold(START + HOUR))
    assert stream.trades == []
    assert stream.counters["entry_across_gap"] == 1


def _proved_empty(frame: pl.DataFrame, minutes: tuple[int, ...]) -> pl.DataFrame:
    empty = pl.col("open_time").dt.timestamp("us").is_in([START + item * MINUTE for item in minutes])
    return frame.with_columns(
        pl.when(empty).then(0).otherwise(pl.col("trade_count")).alias("trade_count"),
        pl.when(empty).then(None).otherwise(pl.col("open")).alias("open"),
        pl.when(empty).then(None).otherwise(pl.col("high")).alias("high"),
        pl.when(empty).then(None).otherwise(pl.col("low")).alias("low"),
        pl.when(empty).then(None).otherwise(pl.col("close")).alias("close"),
    )


def test_en06_a_minute_proved_empty_is_different_so_the_first_print_fills() -> None:
    """Nothing printed in minutes 61 and 62, so the first print is right, and the record is clean."""
    frame = _proved_empty(_rows(_minutes(180), 100.0), (61, 62))
    stream = _run(frame, _Hold(START + HOUR))
    assert stream.counters.get("entry_across_gap", 0) == 0
    assert stream.trades[0].fill_us == START + 63 * MINUTE


def test_en06_a_hole_after_a_minute_proved_empty_still_stops_the_fill() -> None:
    frame = _proved_empty(_rows(_minutes(180, leave_out=(62,)), 100.0), (61,))
    stream = _run(frame, _Hold(START + HOUR))
    assert stream.trades == []
    assert stream.refused_entries[0].refused_from_us == START + 62 * MINUTE


def test_en06_a_flag_known_only_later_cannot_stop_a_fill() -> None:
    """A flag resting on a later row is not known at the fill's minute, so reading it would be a leak."""
    frame = _rows(_minutes(180), 100.0, gap=frozenset({START + 61 * MINUTE})).with_columns(
        pl.when(pl.col("open_time").dt.timestamp("us") == START + 61 * MINUTE)
        .then(pl.col("knowable_time") + pl.duration(hours=1))
        .otherwise(pl.col("knowable_time"))
        .alias("knowable_time")
    )
    stream = _run(frame, _Hold(START + HOUR))
    assert stream.counters.get("entry_across_gap", 0) == 0
    assert stream.trades[0].fill_us == START + 61 * MINUTE


# ---- EN-03 -------------------------------------------------------------------------------------------------


def _refused(name: str, decided: int, *, notional: float, until: int) -> RefusedEntry:
    return RefusedEntry(name, name, decided - DELAY_US, decided, notional / 100.0, 100.0, until, ENTRY_COLLAR)


def _entry(name: str, decided: int, *, notional: float) -> TradeRecord:
    from hft_crypto.engine.accounting import ExitLeg

    fill_at = decided + MINUTE
    legs = (ExitLeg(decided + DAY, 100.0, 100.0, notional / 100.0, 0.0, "TEST"),)
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
        fill_us=fill_at,
        fill_event_us=fill_at + MINUTE,
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
        legs=legs,
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
        as_recorded_legs=legs,
        line="",
        is_default=True,
        in_portfolio=True,
    )


def test_en03_the_auditor_s_case_a_later_refusal_gives_no_room_at_the_decision() -> None:
    """A and B both decide at 12:00:10, with a limit of 1,000. A is first in line and takes 800, so B has 200
    of its 400: scale 0.5. At 12:01:00 A's open is past its collar. B's size was settled before anyone could
    know that.
    """
    decided = utc(2000, 3, 6, 12) + DELAY_US
    refused = _refused("A", decided, notional=800.0, until=utc(2000, 3, 6, 12, 1))
    b = _entry("B", decided, notional=400.0)
    found = apply_gross_cap([b], capital=1000.0, gross_cap=1.0, mark=lambda _s, _t: 100.0, refused=[refused])
    assert found[trade_key(b)].scale == pytest.approx(0.5)


def test_en03_the_room_comes_back_at_the_open_of_the_minute_that_refused_it() -> None:
    """C decides before that open and sees A's 800 still reserved. D decides at it and sees all the room."""
    decided = utc(2000, 3, 6, 12) + DELAY_US
    until = utc(2000, 3, 6, 12, 1)
    refused = _refused("A", decided, notional=800.0, until=until)
    c = _entry("C", until - 1, notional=400.0)
    found = apply_gross_cap([c], capital=1000.0, gross_cap=1.0, mark=lambda _s, _t: 100.0, refused=[refused])
    assert found[trade_key(c)].scale == pytest.approx(0.5)
    d = _entry("D", until, notional=400.0)
    found = apply_gross_cap([d], capital=1000.0, gross_cap=1.0, mark=lambda _s, _t: 100.0, refused=[refused])
    assert found[trade_key(d)].scale == 1.0


def test_en03_a_refused_entry_is_scaled_too_so_it_holds_only_what_it_was_given() -> None:
    """E holds 500 of 1,000, so a refused A of 1,000 is scaled to 0.5 and reserves 500. E leaves 30 s
    later. B, of 400, decides 40 s after A and before A's fill minute: A's 500 is reserved, so B has 500
    of room and full size.
    """
    decided = utc(2000, 3, 6, 12) + DELAY_US
    e = _entry("E", decided - HOUR, notional=500.0)
    e = replace(e, legs=(replace(e.legs[0], event_us=decided + 30_000_000),))
    e = replace(e, as_recorded_legs=e.legs)
    refused = _refused("A", decided, notional=1000.0, until=utc(2000, 3, 6, 12, 1))
    b = _entry("B", decided + 40_000_000, notional=400.0)
    found = apply_gross_cap(
        [e, b], capital=1000.0, gross_cap=1.0, mark=lambda _s, _t: 100.0, refused=[refused]
    )
    assert found[trade_key(b)].scale == 1.0
