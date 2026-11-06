"""Follow-ups from the code recheck and the leak re-audit at `1c2dc23`, each worked by hand.

docs/reviews/code/engine_recheck_2026-11-05.md (R-01, R-02) and the re-audit at the top of
docs/reviews/leak/engine_2026-11-05.md (item 0, and section 2's table of what still passed). All data is
invented here.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import replace
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import polars as pl
import pytest

from engine_helpers import (
    DELAY_US,
    costs,
    engine_config,
    generated_trades,
    run_stream,
    sim_params,
    tape_and_trades,
    utc,
)
from hft_crypto.engine import placebo as placebo_module
from hft_crypto.engine.config import DateRange
from hft_crypto.engine.funding import (
    FUNDING_INTERVAL_CHANGED,
    FundingRow,
    funding_schedule,
    interval_changes,
    missing_settlements,
)
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.placebo import (
    FIRST_QUARTER,
    METHOD_ENTRIES,
    NO_EARLIER_DISTANCE,
    STATUS_RAN,
    MeanResult,
    PlaceboResult,
    Plan,
    QuarterRow,
    build_plan,
    draw_entries,
    drawn_entries,
    entry_shortfall,
    run_draw,
)
from hft_crypto.engine.run import _funding_note, build_manifest, read_symbol
from hft_crypto.engine.simulator import (
    FundingEvent,
    FundingIntervalChange,
    Simulator,
    StreamResult,
    SymbolData,
    left_out_reason,
)
from hft_crypto.engine.tape import Bar, MinuteTape
from hft_crypto.reports.placebo import placebo_row
from hft_crypto.reports.portfolio import build_axis, build_rows
from hft_crypto.strategies.base import REST, Management, PositionView, Proposal, Strategy, TargetPlan
from hft_crypto.strategies.placebo import S03Scan, S10Scan
from hft_crypto.strategies.sources import (
    Birth,
    RecordingSource,
    quarter_name,
    quarter_of,
    sample_without_replacement,
)

START = utc(2000, 3, 6)
MINUTE = 60_000_000
HOUR = 60 * MINUTE
UTC_US = pl.Datetime("us", "UTC")
SYMBOL = "SYNTHBTC"


def _cents(value: float) -> int:
    return round(value * 100)


# ---- item 0 of the re-audit: a funding charge reaches net --------------------------------------------------


class _RoundTrip(Strategy):
    """One trade: in at the close of hour 1, out at the close of hour 4. The stop is 50 away and never near.

    Its id is one the generated configuration knows, so the report rows can be built from its stream.
    """

    id = "S01"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}

    def __init__(self, side: int) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.side = side

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != START + HOUR:
            return []
        return [Proposal(self.side, 100.0 - self.side * 50.0, (TargetPlan("T1", None, REST),), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        del position
        if market.now_us == START + 4 * HOUR:
            return Management(exit_reason="INVALIDATION")
        return Management()


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [
            replace(bar, atr=2.0, atr_last=2.0, complete=True, gap=False) for bar in self.tape.frame(minutes)
        ]


def _rising_tape_frame(count: int) -> pl.DataFrame:
    """Minutes from START at 100, and at 110 from minute 180 on."""
    opens = [START + index * MINUTE for index in range(count)]
    prices = [100.0 if index < 180 else 110.0 for index in range(count)]
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(UTC_US),
            "open": prices,
            "high": [value + 0.5 for value in prices],
            "low": [value - 0.5 for value in prices],
            "close": prices,
            "volume": [10.0] * count,
            "trade_count": [5] * count,
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(UTC_US),
        }
    )


def _rising_tape() -> MinuteTape:
    """Six hours."""
    return MinuteTape.from_frame(_rising_tape_frame(360), symbol=SYMBOL, delay_us=DELAY_US)


def _round_trip(side: int, rate: float) -> tuple[StreamResult, MinuteTape]:
    """No fee and no slippage, so gross minus net is the funding alone."""
    tape = _rising_tape()
    params = sim_params(
        risk_budget=500.0,
        capital=1_000_000.0,
        leverage_cap=100.0,
        cost=costs(rt_bps=0.0, slip_bps=0.0, stop_slip_bps=0.0),
    )
    funding = (FundingEvent(START + 120 * MINUTE, rate),)
    stream = _FlatAtr(_RoundTrip(side), tape, params, funding=funding, line="default").run()
    return stream, tape


# Side, rate, gross in cents, funding in cents. 10 units filled at 100 at minute 61 and out at 110 at minute
# 241, so the long makes 10 * 10 = 100.00 and the short loses it. The settlement at minute 120 marks at 100:
# 10 * 100 * 0.1% = 1.00. A long pays a positive rate and a short receives it, and the other way round.
FUNDING_CASES = [
    (1, 0.001, 10_000, 100),
    (1, -0.001, 10_000, -100),
    (-1, 0.001, -10_000, -100),
    (-1, -0.001, -10_000, 100),
]
FUNDING_IDS = ["long pays", "long receives", "short receives", "short pays"]


@pytest.mark.parametrize(("side", "rate", "gross", "funding"), FUNDING_CASES, ids=FUNDING_IDS)
def test_a_funding_charge_reaches_net_through_the_booked_trade(
    side: int, rate: float, gross: int, funding: int
) -> None:
    stream, _ = _round_trip(side, rate)
    trade = stream.trades[0]
    assert (trade.q0, trade.fill, trade.legs[-1].price) == cast(object, (pytest.approx(10.0), 100.0, 110.0))
    events, booked = trade.book()
    assert (booked.gross, booked.slippage, booked.fees, booked.funding) == (gross, 0, 0, funding)
    assert booked.gross - booked.net == funding
    # The equity curve books each cash event's own net, so those must carry the charge too.
    assert sum(event.net for event in events) == gross - funding
    assert [event.funding for event in events] == [0, funding, 0]
    _, half = trade.book(0.5)
    assert half.gross - half.net == funding // 2


@pytest.mark.parametrize(("side", "rate", "gross", "funding"), FUNDING_CASES, ids=FUNDING_IDS)
def test_a_funding_charge_reaches_net_through_every_row(
    side: int, rate: float, gross: int, funding: int
) -> None:
    """Every row that prints net: the stream, the strategy, both portfolio rows, the trade, the cost lines, R,
    `Result_B` and the equity that ends each series. With no fee and no slippage each shows net as gross less
    the funding, and the cost multiples leave the funding as it is.
    """
    stream, tape = _round_trip(side, rate)
    config = engine_config()
    axis = build_axis(int(tape.close_us[0]), int(tape.close_us[-1]), 60)
    rows = build_rows(
        [stream],
        config=config,
        labels=(),
        axis=axis,
        marks={SYMBOL: tape.mark_series(axis)},
        mark_at=lambda _symbol, at_us: tape.mark_price(at_us),
    )
    net = gross - funding
    side_name = "long" if side > 0 else "short"
    sections: list[dict[str, Any]] = [
        rows.strategy_asset[0],
        rows.strategy_asset[0][side_name],
        rows.strategy[0],
        rows.portfolio[0],
        rows.portfolio[0][side_name],
        rows.portfolio[1],
    ]
    for section in sections:
        assert _cents(section["gross_pnl"]) == gross
        assert _cents(section["funding"]) == funding
        assert _cents(section["gross_pnl"]) - _cents(section["net_pnl"]) == funding
        assert _cents(section["net_pnl_cost_2x"]) == net
        assert _cents(section["net_pnl_cost_3x"]) == net
        assert section["net_result_b_total"] == pytest.approx(net / 100 / 500.0)
        assert section["gross_r_total"] - section["net_r_total"] == pytest.approx(funding / 100 / 500.0)
        assert _cents(section["equity_final"]) - _cents(section["equity_start"]) == net
    trade_row = rows.trades[0]
    assert trade_row["portfolio_scale"] == 1.0
    assert _cents(trade_row["gross_pnl"]) - _cents(trade_row["net_pnl"]) == funding
    assert _cents(trade_row["portfolio_gross_pnl"]) - _cents(trade_row["portfolio_net_pnl"]) == funding
    assert _cents(trade_row["costs"]["funding"]) == funding
    assert trade_row["gross_r"] - trade_row["net_r"] == pytest.approx(funding / 100 / 500.0)
    assert trade_row["gross_result_b"] - trade_row["net_result_b"] == pytest.approx(funding / 100 / 500.0)
    last = rows.equity[-1]["equity"]
    for name in ("portfolio", "portfolio:uncapped", f"portfolio:{side_name}", "S01", f"S01:{SYMBOL}"):
        assert _cents(last[name]) == _cents(config.risk.capital) + net


# ---- R-01: a change of funding interval names no settlement, and is logged ---------------------------------


def _hours(rows: list[tuple[int, int]]) -> list[FundingRow]:
    """(settlement hour from START, interval hours) to rows, each at a 0.01% rate."""
    return [FundingRow(START + hour * HOUR, 0.0001, interval) for hour, interval in rows]


def test_r01_a_lengthening_interval_invents_no_settlement() -> None:
    """The reviewer's case: rows at 4 h and 8 h stating 4, then 16 h and 24 h stating 8. The schedule used to
    name 12 h, read from the row before the stretch. Under the other reading of the column nothing is missing.
    """
    rows = _hours([(4, 4), (8, 4), (16, 8), (24, 8)])
    events = funding_schedule(rows, first_open_us=START, end_us=START + 24 * HOUR + 1)
    assert missing_settlements(events) == ()
    assert [event.settle_us for event in events] == [START + hour * HOUR for hour in (4, 8, 16, 24)]
    assert interval_changes(rows) == (FundingIntervalChange(START + 8 * HOUR, START + 16 * HOUR, 4, 8),)


def test_r01_a_shortening_interval_with_a_row_missing_is_logged_not_hidden() -> None:
    """The reviewer's other case: 8 h and 16 h state 8, and 24 h and 28 h state 4. If the change took effect
    at 20 h, its row is missing. `round(8 / 8)` is one step, so the old schedule saw nothing and said nothing.
    Now it still names nothing, and the stretch from 16 h to 24 h is logged.
    """
    rows = _hours([(8, 8), (16, 8), (24, 4), (28, 4)])
    events = funding_schedule(rows, first_open_us=START, end_us=START + 28 * HOUR + 1)
    assert missing_settlements(events) == ()
    assert interval_changes(rows) == (FundingIntervalChange(START + 16 * HOUR, START + 24 * HOUR, 8, 4),)


def test_r01_rows_that_agree_still_name_their_missing_settlements() -> None:
    """8 h stretches around a missing 16 h, then a change to 4 h at 32 h. The first is counted, the second
    logged."""
    rows = _hours([(0, 8), (8, 8), (24, 8), (32, 4), (36, 4)])
    events = funding_schedule(rows, first_open_us=START - HOUR, end_us=START + 36 * HOUR + 1)
    assert missing_settlements(events) == (START + 16 * HOUR,)
    assert interval_changes(rows) == (FundingIntervalChange(START + 24 * HOUR, START + 32 * HOUR, 8, 4),)


def test_r01_the_logged_stretch_reaches_the_manifest_and_the_note() -> None:
    """Two days of rows as a run reads them: 8 h until 16:00 on day 1, then 4 h with the 20:00 row absent."""
    first = dt.date(2000, 3, 6)
    kept = [(8, 8), (16, 8), *((hour, 4) for hour in range(24, 48, 4))]
    funding_frame = pl.DataFrame(
        {
            "settle_time": pl.Series([START + hour * HOUR for hour, _ in kept], dtype=pl.Int64).cast(UTC_US),
            "funding_rate": [0.0001] * len(kept),
            "funding_interval_hours": pl.Series([interval for _, interval in kept], dtype=pl.Int32),
        }
    )
    candles = _rising_tape_frame(2880)
    reader = SimpleNamespace(candles=lambda *_a, **_k: candles, funding=lambda *_a, **_k: funding_frame)
    engine = cast(
        Any, SimpleNamespace(minute_source="official_candles", venue="v", tier="T0", funding="required")
    )
    date_range = DateRange(first, dt.date(2000, 3, 7))
    item = read_symbol(
        cast(Any, reader), engine, "S", date_range, delay_us=DELAY_US, last_opened=dt.date(2000, 3, 7)
    )
    assert missing_settlements(item.funding) == ()
    manifest = build_manifest({"S": item}, engine, date_range)["symbols"]["S"]
    assert manifest["funding_settlements_with_no_rate"] == 0
    assert manifest["funding_interval_changes"] == [
        {
            "event": FUNDING_INTERVAL_CHANGED,
            "from": "2000-03-06T16:00:00Z",
            "to": "2000-03-07T00:00:00Z",
            "interval_hours_before": 8,
            "interval_hours_after": 4,
        }
    ]
    note = _funding_note(engine, {"S": 0}, {"S": 1})
    assert FUNDING_INTERVAL_CHANGED in note
    assert "UNVERIFIED" in note
    assert "Every settlement in the range has a rate" not in note
    assert FUNDING_INTERVAL_CHANGED not in _funding_note(engine, {"S": 0}, {"S": 0})


# ---- C15, before the first reading: the eligible entry bars, and which quarters are compared ---------------

DAY = 24 * HOUR
FIRST = utc(2000, 1, 3)


@lru_cache(maxsize=1)
def _placebo_market() -> tuple[Any, Any]:
    trades = generated_trades(seed=7, start_us=FIRST, days=200)
    return tape_and_trades(trades, start_us=FIRST, through_us=FIRST + 200 * DAY)


@pytest.mark.parametrize("strategy", ["S03", "S10"])
def test_c15_eligible_entry_bars_leave_out_any_whose_setup_would_reach_the_end_or_a_read_day(
    strategy: str,
) -> None:
    """Re-audit section 2. A real setup on such a bar is left out (FP-06, FP-07), so the real counts never
    hold one, and a draw must not enter there either. Range end at day 150, and a read day at day 60.
    """
    tape, trades = _placebo_market()
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies[strategy].default()
    end = FIRST + 150 * DAY
    read_day = (FIRST + 60 * DAY, FIRST + 61 * DAY)
    sim = sim_params(span_end_us=end, read_days_us=(read_day,))
    scan: S03Scan | S10Scan = S03Scan(line.params) if strategy == "S03" else S10Scan(line.params)
    Simulator(scan, tape, sim_params(), trades=trades).run()
    every = {(row.close_us, row.side) for row in scan.eligible}
    reaching_end = {(close, side) for close, side in every if close + scan.h_max_us >= end}
    reaching_read = {
        (close, side) for close, side in every if read_day[0] <= close + scan.h_max_us and close < read_day[1]
    }
    assert reaching_end and reaching_read, "no eligible bar reaches either, so this would prove nothing"
    plan = build_plan(
        strategy,
        "S",
        line,
        item=item,
        sim=sim,
        quarters=[quarter_of(FIRST), quarter_of(utc(2000, 4, 3)), quarter_of(utc(2000, 7, 3))],
        real=run_stream(strategy, tape, trades),
    )
    kept = {
        (close, side)
        for by_side in plan.eligible.values()
        for side, closes in by_side.items()
        for close in closes
    }
    assert kept == every - reaching_end - reaching_read
    assert all(left_out_reason(close, scan.h_max_us, end, sim.read_days_us) is None for close, _ in kept)


def _births(rows: list[tuple[str, int]]) -> list[Birth]:
    return [Birth(kind, moment, {"p": 0.5}) for kind, moment in rows]


def test_c15_a_quarter_is_not_compared_when_a_kind_born_in_it_has_no_earlier_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule stated at 47c0dc8, which the re-audit holds the code to. Daily sets from 2000-Q1, a weekly
    set first born in Q3, and Q4 holds both kinds. Q1 is the first quarter. Q2 is compared, since its daily
    set has an earlier one. Q3 is not: its weekly set has no earlier distance, though its daily set has. Q4
    is, and so is 2001-Q1, where nothing is born at all.
    """
    births = _births(
        [
            ("DAILY", utc(2000, 1, 10)),
            ("DAILY", utc(2000, 4, 10)),
            ("WEEKLY", utc(2000, 7, 10)),
            ("DAILY", utc(2000, 7, 11)),
            ("DAILY", utc(2000, 10, 10)),
            ("WEEKLY", utc(2000, 10, 11)),
        ]
    )

    class _Recorded(RecordingSource):
        def __init__(self) -> None:
            super().__init__()
            self.births = list(births)

    monkeypatch.setattr(placebo_module, "RecordingSource", _Recorded)
    monkeypatch.setattr(placebo_module, "build_level_strategy", lambda *_args: None)
    monkeypatch.setattr(placebo_module, "_simulate", lambda *_args: None)
    starts = ((2000, 1), (2000, 4), (2000, 7), (2000, 10), (2001, 1))
    quarters = [quarter_of(utc(year, month, 3)) for year, month in starts]
    plan = placebo_module._level_plan(
        strategy="S01",
        symbol="S",
        line=engine_config().strategies["S01"].default(),
        item=cast(Any, None),
        sim=sim_params(),
        quarters=quarters,
    )
    assert [(row.has_placebo, row.reason) for row in plan.quarters] == [
        (False, FIRST_QUARTER),
        (True, None),
        (False, NO_EARLIER_DISTANCE),
        (True, None),
        (True, None),
    ]
    assert plan.compared == frozenset({quarters[1], quarters[3], quarters[4]})


# ---- R-02: an entry draw meets both counts whenever the bars allow, and says when it cannot ----------------

Q = quarter_of(FIRST)


def _old_draw_entries(
    rng: random.Random, eligible: dict[int, dict[int, list[int]]], counts: dict[int, dict[int, int]]
) -> dict[int, int]:
    """The draw at 1c2dc23, kept here to show the fix leaves a draw with room to spare as it was."""
    entries: dict[int, int] = {}
    for quarter in sorted(counts):
        found = eligible.get(quarter, {})
        for side in sorted((1, -1), key=lambda value: (len(found.get(value, [])), -value)):
            open_bars = [close for close in found.get(side, []) if close not in entries]
            for close in sample_without_replacement(rng, open_bars, counts[quarter].get(side, 0)):
                entries[close] = side
    return entries


def test_r02_the_reviewer_s_case_meets_both_counts_on_every_seed() -> None:
    """Long needs 1 of bars {1, 2}, short needs 2 of {2, 3}. Both have two bars, so long draws first. When it
    took bar 2, short got one entry. Now long may not take bar 2, since short needs it, and every seed meets
    both.
    """
    eligible = {Q: {1: [1, 2], -1: [2, 3]}}
    counts = {Q: {1: 1, -1: 2}}
    old_met = 0
    for seed in range(500):
        entries = draw_entries(random.Random(seed), eligible, counts)
        assert entries == {1: 1, 2: -1, 3: -1}
        assert entry_shortfall(entries, eligible, counts) == {}
        old = _old_draw_entries(random.Random(seed), eligible, counts)
        old_met += entry_shortfall(old, eligible, counts) == {}
    # The old draw missed on some seeds, as the reviewer found, so the case does test something.
    assert 0 < old_met < 500


def test_r02_with_bars_to_spare_every_draw_is_the_one_it_was() -> None:
    """The limit binds only when the other side would run short, so a draw with room is unchanged, number for
    number, and draws made before the fix stay as they were wherever bars were not scarce."""
    eligible = {
        Q: {1: list(range(0, 40)), -1: list(range(20, 70))},
        Q + 1: {1: list(range(100, 130)), -1: list(range(100, 130))},
    }
    counts = {Q: {1: 4, -1: 6}, Q + 1: {1: 3, -1: 2}}
    for seed in range(300):
        assert draw_entries(random.Random(seed), eligible, counts) == _old_draw_entries(
            random.Random(seed), eligible, counts
        )


def test_r02_each_bar_once_and_from_its_own_side_when_shared_bars_are_scarce() -> None:
    """Six shared bars, two only long, one only short. Long needs 5 and short 4, which the 9 bars allow."""
    eligible = {Q: {1: [1, 2, 3, 4, 5, 6, 7, 8], -1: [3, 4, 5, 6, 7, 8, 9]}}
    counts = {Q: {1: 5, -1: 4}}
    old_met = 0
    for seed in range(500):
        entries = draw_entries(random.Random(seed), eligible, counts)
        assert entry_shortfall(entries, eligible, counts) == {}
        assert all(close in eligible[Q][side] for close, side in entries.items())
        assert sum(side == 1 for side in entries.values()) == 5
        old_met += (
            entry_shortfall(_old_draw_entries(random.Random(seed), eligible, counts), eligible, counts) == {}
        )
    assert old_met < 500


def test_r02_a_count_the_bars_cannot_meet_is_recorded_by_quarter_and_side() -> None:
    eligible = {Q: {1: [1], -1: []}, Q + 1: {1: [5, 6], -1: [5, 6]}}
    counts = {Q: {1: 4, -1: 2}, Q + 1: {1: 2, -1: 1}}
    entries = draw_entries(random.Random(3), eligible, counts)
    assert entry_shortfall(entries, eligible, counts) == {
        "2000-Q1:long": 3,
        "2000-Q1:short": 2,
        f"{quarter_name(Q + 1)}:long": 1,
    }


def test_r02_the_shortfall_of_each_draw_reaches_placebo_json() -> None:
    """Through `run_draw` and the row: a plan whose quarter has one bar for two longs."""
    tape, trades = _placebo_market()
    item = SymbolData(tape, trades, ())
    line = engine_config().strategies["S10"].default()
    close = FIRST + 30 * DAY
    plan = Plan(
        strategy="S10",
        symbol="S",
        line=line.line_id,
        params=dict(line.params),
        swap=METHOD_ENTRIES,
        sim=sim_params(),
        quarters=(QuarterRow(Q, True),),
        eligible={Q: {1: [close], -1: []}},
        counts={Q: {1: 2, -1: 0}},
    )
    stats = [run_draw(plan, draw, item) for draw in (1, 2)]
    assert [stat.shortfall for stat in stats] == [{"2000-Q1:long": 1}] * 2
    assert drawn_entries(plan, 1) == {close: 1}
    result = PlaceboResult(
        strategy="S10",
        symbol="S",
        line=plan.line,
        params=plan.params,
        swap=METHOD_ENTRIES,
        status=STATUS_RAN,
        reason=None,
        quarters=plan.quarters,
        real=MeanResult(0, None, None),
        real_by_branch={},
        real_setups_by_quarter={Q: 2},
        real_trades_by_quarter={},
        draws=tuple(stats),
    )
    row = placebo_row(result, "label")
    assert row["entry_shortfall"] == {"2000-Q1:long": 2}
    assert row["draws_with_an_entry_shortfall"] == 2
    assert [draw["entry_shortfall"] for draw in row["draw_rows"]] == [{"2000-Q1:long": 1}] * 2
