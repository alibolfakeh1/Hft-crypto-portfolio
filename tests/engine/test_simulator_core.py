"""The simulator's own rules, on small hand-built bars. Every expected value here is worked out by hand in a
comment.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from engine_helpers import (
    DAY,
    DELAY_US,
    MINUTE,
    TableBar,
    costs,
    engine_config,
    generated_trades,
    rows_from_table,
    run_stream,
    sim_params,
    tape_and_trades,
    utc,
)
from hft_crypto.bars.core import TimingContractError
from hft_crypto.engine.accounting import ExitLeg, FundingCharge, book_trade, to_cents
from hft_crypto.engine.exits import ratchet
from hft_crypto.engine.fills import plan_entry, round_to_tick
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.portfolio import apply_gross_cap, trade_key
from hft_crypto.engine.simulator import (
    LEFT_OUT_READ_DAY,
    LEFT_OUT_UNOPENED,
    FundingEvent,
    Simulator,
    StreamResult,
    TradeRecord,
)
from hft_crypto.engine.tape import MinuteTape
from hft_crypto.strategies.base import (
    REST,
    Management,
    PositionView,
    Proposal,
    StopCandidate,
    Strategy,
    TargetPlan,
)

T = 60
START = utc(2000, 1, 5, 12, 0)
HOUR = 60 * MINUTE
STRATEGIES = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")


class _Script(Strategy):
    """A test double: one setup at one close, and whatever stop candidates the test hands it."""

    id = "TEST"

    h_max_hours = {60: 10.0}  # noqa: RUF012

    def __init__(
        self,
        at_close: int,
        *,
        side: int = 1,
        s0: float = 95.0,
        targets: tuple[TargetPlan, ...] = (),
        stops: dict[int, list[float]] | None = None,
        exit_at: int | None = None,
    ) -> None:
        super().__init__({"timeframe_minutes": T})
        self.at_close = at_close
        self.side = side
        self.s0 = s0
        self.targets = targets
        self.stops = stops or {}
        self.exit_at = exit_at
        self.seen_positions: list[tuple[int, float]] = []

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.at_close:
            return []
        return [Proposal(self.side, self.s0, self.targets, {}, 4, {})]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        self.seen_positions.append((market.now_us, position.stop))
        if self.exit_at == market.now_us:
            return Management(exit_reason="INVALIDATION", exit_note="TEST")
        return Management(stops=[StopCandidate(value, "TEST") for value in self.stops.get(market.now_us, [])])


def _bars(*rows: tuple[float, float, float, float]) -> list[TableBar]:
    return [TableBar(START + index * HOUR, *row) for index, row in enumerate(rows)]


def _tape(bars: list[TableBar], *, delay_us: int = DELAY_US) -> MinuteTape:
    return MinuteTape.from_frame(rows_from_table(bars, T), symbol="S", delay_us=delay_us)


def _run(strategy: Strategy, bars: list[TableBar], **kwargs: Any) -> StreamResult:
    atr = kwargs.pop("atr", 2.0)
    funding = kwargs.pop("funding", ())
    tape = _tape(bars)

    class Flat(Simulator):
        def _bars(self, minutes: int) -> list[Any]:
            from dataclasses import replace

            return [replace(bar, atr=atr, atr_last=atr, complete=True) for bar in self.tape.frame(minutes)]

    return Flat(strategy, tape, sim_params(risk_budget=250.0, **kwargs), funding=funding).run()


# ---- timing
# --------------------------------------------------------------------------------------------------


def test_a_fill_comes_after_its_decision_at_the_next_allowed_minute() -> None:
    """Decided at the close t. With A of 10 s, the first 1m bar opening at or after t + 10 s opens at t + 60
    s.
    """
    bars = _bars((100, 101, 99, 100), (100, 102, 99, 101), (101, 102, 100, 101))
    stream = _run(_Script(bars[0].close_us), bars)
    trade = stream.trades[0]
    assert trade.signal_us == bars[0].close_us
    assert trade.fill_us == bars[0].close_us + MINUTE
    assert trade.fill_us >= trade.decided_as_of_us > trade.signal_us


def test_every_fill_on_every_strategy_comes_after_its_decision() -> None:
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=7, start_us=start, days=150)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 150 * DAY)
    seen = 0
    for strategy in STRATEGIES:
        for trade in run_stream(strategy, tape, tape_trades).trades:
            seen += 1
            assert trade.fill_us >= trade.signal_us + DELAY_US
            assert trade.fill_us > trade.signal_us
            assert trade.fill_event_us > trade.fill_us
            for leg in trade.legs:
                assert leg.event_us >= trade.fill_event_us
    assert seen > 50


def test_a_stop_update_acts_only_from_the_minute_after_the_delay() -> None:
    """The update at close c1 is effective from c1 + 60 s. A dip in the first minute after c1 hits the old
    stop only.
    """
    bars = _bars((100, 101, 99, 100), (100, 110, 100, 110), (110, 111, 105, 110))
    stream = _run(_Script(bars[0].close_us, s0=90.0, stops={bars[1].close_us: [107.0]}), bars)
    row = stream.trades[0].stop_path[0]
    assert row["computed_at_us"] == bars[1].close_us
    assert row["effective_from_us"] == bars[1].close_us + MINUTE


def test_a_pending_exit_fills_after_the_old_stop_has_had_its_minute() -> None:
    """An exit decided at c1 fills at the open of the minute after c1 + delay. The minute before is walked
    first.
    """
    bars = _bars((100, 101, 99, 100), (100, 102, 99, 101), (101, 102, 100, 101), (101, 102, 100, 101))
    stream = _run(_Script(bars[0].close_us, s0=90.0, exit_at=bars[1].close_us), bars)
    leg = stream.trades[0].legs[0]
    assert leg.reason == "INVALIDATION"
    assert leg.event_us == bars[1].close_us + 2 * MINUTE
    # Close-based exits pay `slip`, here 1 bp, on the open of that minute.
    assert leg.price == pytest.approx(leg.reference * (1 - 0.0001))


def test_the_mode_table_refuses_a_too_short_allowance() -> None:
    with pytest.raises(TimingContractError, match="A >= fill_span"):
        sim_params(allowance_us=100, fill_span_allowance_us=200)


def test_a_tape_built_for_another_delay_is_refused() -> None:
    bars = _bars((100, 101, 99, 100))
    tape = _tape(bars, delay_us=0)
    with pytest.raises(TimingContractError, match="another decision delay"):
        Simulator(_Script(bars[0].close_us), tape, sim_params())


# ---- stops only tighten
# -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("side", [1, -1])
def test_the_ratchet_never_moves_a_stop_away_from_the_market(side: int) -> None:
    old = 100.0 if side > 0 else 110.0
    away = old - side * 5.0
    result = ratchet(
        side=side, old_stop=old, candidates=[StopCandidate(away, "AWAY")], close=105.0, atr=1.0, tick=0.01
    )
    assert result.stop == old and result.reason is None


def test_the_ratchet_clamps_at_close_less_a_tenth_of_atr_and_takes_the_tightest() -> None:
    """C8: long, S_new = max(100, min(104.5, 105 - 0.1)). The tightest candidate is 104.5."""
    candidates = [StopCandidate(101.0, "A"), StopCandidate(104.5, "B")]
    result = ratchet(side=1, old_stop=100.0, candidates=candidates, close=105.0, atr=1.0, tick=0.01)
    assert (result.stop, result.reason) == (104.5, "B")
    clamped = ratchet(
        side=1, old_stop=100.0, candidates=[StopCandidate(200.0, "C")], close=105.0, atr=1.0, tick=0.01
    )
    assert clamped.stop == pytest.approx(104.9)


def test_the_ratchet_holds_when_atr_is_undefined() -> None:
    result = ratchet(
        side=1, old_stop=100.0, candidates=[StopCandidate(104.0, "A")], close=105.0, atr=None, tick=0.01
    )
    assert result.stop == 100.0


def test_a_strategy_asking_to_widen_a_stop_is_ignored() -> None:
    bars = _bars((100, 101, 99, 100), (100, 102, 99, 101), (101, 102, 100, 101))
    stream = _run(_Script(bars[0].close_us, s0=95.0, stops={bars[1].close_us: [90.0]}), bars)
    assert stream.trades[0].stop_path == ()


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_no_stop_moved_away_on_any_strategy(strategy: str) -> None:
    """Across every update of every trade, on a generated market."""
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=7, start_us=start, days=150)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 150 * DAY)
    stream = run_stream(strategy, tape, tape_trades)
    for trade in stream.trades:
        for row in trade.stop_path:
            assert trade.side * (row["new"] - row["old"]) > 0
            assert row["effective_from_us"] > row["computed_at_us"]
        stops = [trade.s0, *(row["new"] for row in trade.stop_path)]
        assert all(trade.side * (b - a) >= 0 for a, b in pairwise(stops))


# ---- the order of things inside a minute
# -----------------------------------------------------------------------


def test_a_minute_touching_stop_and_target_is_a_stop() -> None:
    """C7, timing item 8. Long, stop 95, target 105. One minute trades through both, so it is the stop, all
    of it.
    """
    bars = _bars((100, 101, 99, 100), (100, 106, 94, 100))
    from dataclasses import replace

    frame = rows_from_table(bars, T)
    # Put the whole range in one minute.
    import polars as pl

    index = pl.col("open_time").dt.timestamp("us") == bars[1].close_us - T * MINUTE + 2 * MINUTE
    frame = frame.with_columns(
        pl.when(index).then(106.0).otherwise(pl.col("high")).alias("high"),
        pl.when(index).then(94.0).otherwise(pl.col("low")).alias("low"),
    )
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    del replace
    targets = (TargetPlan("T1", 105.0, REST),)

    class Flat(Simulator):
        def _bars(self, minutes: int) -> list[Any]:
            from dataclasses import replace as swap

            return [swap(bar, atr=2.0, atr_last=2.0, complete=True) for bar in self.tape.frame(minutes)]

    stream = Flat(_Script(bars[0].close_us, s0=95.0, targets=targets), tape, sim_params(), funding=()).run()
    trade = stream.trades[0]
    assert [leg.reason for leg in trade.legs] == ["STOP"]
    assert trade.legs[0].reference == 95.0
    # Stop slippage is its own value: C16's 5 bp on the level.
    assert trade.legs[0].price == pytest.approx(95.0 * (1 - 0.0005))


def test_a_target_needs_a_trade_through_it() -> None:
    """C7: H > T, not H >= T. A high exactly at the target fills nothing."""
    bars = _bars((100, 101, 99, 100), (100, 105, 99, 101), (101, 106, 100, 101))
    targets = (TargetPlan("T1", 105.0, REST),)
    stream = _run(_Script(bars[0].close_us, s0=90.0, targets=targets), bars)
    leg = stream.trades[0].legs[0]
    assert leg.reason == "TARGET_T1"
    assert leg.event_us > bars[1].close_us


def test_a_target_fills_at_its_price_with_no_slippage_and_the_declared_fee() -> None:
    bars = _bars((100, 101, 99, 100), (100, 110, 99, 101))
    targets = (TargetPlan("T1", 105.0, REST),)
    stream = _run(_Script(bars[0].close_us, s0=90.0, targets=targets), bars, cost=costs())
    leg = stream.trades[0].legs[0]
    assert (leg.reference, leg.price) == (105.0, 105.0)
    assert leg.fee_rate == pytest.approx(0.0005)


def test_scale_out_takes_the_planned_share_and_the_rest_goes_at_the_second_target() -> None:
    bars = _bars((100, 101, 99, 100), (100, 106, 99, 101), (101, 111, 100, 101))
    targets = (TargetPlan("T1", 105.0, 0.25), TargetPlan("T2", 110.0, REST))
    trade = _run(_Script(bars[0].close_us, s0=90.0, targets=targets), bars).trades[0]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "TARGET_T2"]
    assert trade.legs[0].qty == pytest.approx(0.25 * trade.q0)
    assert trade.legs[1].qty == pytest.approx(0.75 * trade.q0)


def test_the_collar_refuses_a_fill_beyond_it_on_the_reference() -> None:
    """Long at 100, ATR 2, so the limit is 101. A reference of 102 is no fill, logged, and no trade."""
    bars = _bars((100, 101, 99, 100), (102, 103, 101, 102))
    stream = _run(_Script(bars[0].close_us), bars)
    assert stream.trades == []
    assert stream.counters["entry_collar"] == 1
    assert [event["type"] for event in stream.events][-1] == "ENTRY_COLLAR"


def test_an_entry_gapping_through_its_stop_exits_at_once_and_has_no_r_figure() -> None:
    """C6. The trade exists, is stopped on its fill bar at the reference less stop slippage."""
    bars = _bars((100, 101, 99, 100), (94, 95, 93, 94))
    trade = _run(_Script(bars[0].close_us, s0=95.0), bars).trades[0]
    assert trade.legs[0].reason == "ENTRY_THROUGH_STOP"
    assert trade.legs[0].reference == 94.0
    assert trade.through_stop is True


def test_a_setup_while_a_position_is_open_is_skipped_and_logged() -> None:
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100))

    class Twice(_Script):
        def on_close(self, market: MarketView) -> list[Proposal]:
            return (
                [Proposal(1, 95.0, (), {}, 4, {})]
                if market.now_us in {bars[0].close_us, bars[1].close_us}
                else []
            )

    stream = _run(Twice(bars[0].close_us), bars)
    assert stream.counters["skipped_open"] == 1
    assert len(stream.trades) == 1


def test_a_setup_at_a_bar_not_complete_as_of_its_close_is_lost_and_counted() -> None:
    """Ruling 4. The last minute of the bar is empty and unproven at the decision, so no setup is created."""
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=7, start_us=start, days=150)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 150 * DAY)
    stream = run_stream("S03", tape, tape_trades)
    lost = [event for event in stream.events if event["type"] == "SETUP_LOST"]
    assert lost
    assert stream.counters["setups_lost_bar_not_complete"] == len(lost)
    assert stream.reasons["BAR_NOT_COMPLETE_AS_OF_CLOSE"] == len(lost)


# ---- left out, and never simulated
# -------------------------------------------------------------------------------


def test_a_setup_reaching_the_first_unopened_instant_is_out_at_equality() -> None:
    """FP-07, C18's `reaches`. H_max is 10 h. A setup at span end minus 10 h has t_k + H_max at it, so it is
    out.
    """
    bars = _bars(*[(100, 101, 99, 100)] * 14)
    signal = bars[0].close_us
    out = _run(_Script(signal), bars, span_end_us=signal + 10 * HOUR)
    assert out.setups == 0 and out.trades == []
    assert out.counters["setups_left_out_reaches_unopened_date"] == 1
    assert out.reasons[LEFT_OUT_UNOPENED] == 1
    kept = _run(_Script(signal), bars, span_end_us=signal + 10 * HOUR + 1)
    assert kept.setups == 1


def test_a_setup_reaching_a_read_day_is_never_simulated_and_the_strategy_stays_flat() -> None:
    """FP-06. The first setup reaches the read day, so it is out. The second must then trade, and not be
    skipped.
    """
    bars = _bars(*[(100, 101, 99, 100)] * 30)
    first = bars[0].close_us
    second = bars[1].close_us

    class Two(_Script):
        def on_close(self, market: MarketView) -> list[Proposal]:
            return [Proposal(1, 95.0, (), {}, 4, {})] if market.now_us in {first, second} else []

    read_day = (first + 10 * HOUR, first + 10 * HOUR + DAY)
    # The first reaches the read day, and the second is written to fall after it, so only the read day
    # decides.
    stream = _run(Two(first), bars, read_days_us=(read_day,))
    assert stream.reasons[LEFT_OUT_READ_DAY] == 2
    assert stream.trades == []
    assert not [
        event for event in stream.events if event["type"] in ("ENTRY", "EXIT", "STOP_UPDATE", "SKIPPED_OPEN")
    ]


def test_a_setup_after_a_read_day_stays_in_and_is_not_skipped_for_one_left_out_before_it() -> None:
    bars = _bars(*[(100, 101, 99, 100)] * 30)
    first = bars[0].close_us
    later = bars[28].close_us

    class Two(_Script):
        def on_close(self, market: MarketView) -> list[Proposal]:
            return [Proposal(1, 95.0, (), {}, 4, {})] if market.now_us in {first, later} else []

    read_day = (first + 5 * HOUR, first + 6 * HOUR)
    stream = _run(Two(first), bars, read_days_us=(read_day,))
    assert stream.reasons[LEFT_OUT_READ_DAY] == 1
    assert stream.counters.get("skipped_open", 0) == 0
    assert len(stream.trades) == 1
    assert stream.trades[0].signal_us == later


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_no_fill_touch_or_exit_is_evaluated_inside_a_read_day(strategy: str) -> None:
    """FP-06's test, on every strategy. Bars stay for indicators. Nothing is evaluated for a position on
    those days.
    """
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=7, start_us=start, days=150)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 150 * DAY)
    day_starts = [start + offset * DAY for offset in range(95, 150, 5)]
    read = tuple((day, day + DAY) for day in day_starts)
    stream = run_stream(strategy, tape, tape_trades, sim=sim_params(read_days_us=read))
    for event in stream.events:
        if event["type"] in ("ENTRY", "SCALE_OUT", "EXIT", "FUNDING", "GAP_UNRESOLVED"):
            moment = event["knowable_us"]
            assert not any(low < moment <= high for low, high in read), event
    for trade in stream.trades:
        reach = trade.signal_us + int(_h_max(strategy) * HOUR)
        assert not any(low <= reach and trade.signal_us < high for low, high in read)


def _h_max(strategy: str) -> float:
    from hft_crypto.strategies import build_strategy

    built = build_strategy(strategy, engine_config().strategies[strategy].default().params)
    return built.h_max_us / HOUR


# ---- funding
# -----------------------------------------------------------------------------------------------------


def test_funding_is_charged_at_settlement_on_the_quantity_then_open() -> None:
    """Long q0 = 250 / 5 = 50. A settlement inside the second bar, mark 100, rate 0.0001: pays 50 * 100 *
    0.0001 = 0.50.
    """
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100))
    settle = bars[1].close_us - 30 * MINUTE
    stream = _run(_Script(bars[0].close_us), bars, funding=(FundingEvent(settle, 0.0001),))
    trade = stream.trades[0]
    assert trade.q0 == pytest.approx(50.0)
    assert len(trade.funding) == 1
    assert trade.book()[1].funding == 50


def test_a_short_receives_funding_when_longs_pay() -> None:
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100))
    settle = bars[1].close_us - 30 * MINUTE
    stream = _run(_Script(bars[0].close_us, side=-1, s0=105.0), bars, funding=(FundingEvent(settle, 0.0001),))
    assert stream.trades[0].book()[1].funding == -50


def test_an_entry_at_a_settlement_instant_pays_nothing_for_it() -> None:
    """Condition 9. The fill's time is its minute's open, and the settlement falls exactly there."""
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100))
    settle = bars[0].close_us + MINUTE
    stream = _run(_Script(bars[0].close_us), bars, funding=(FundingEvent(settle, 0.0001),))
    assert stream.trades[0].fill_us == settle
    assert stream.trades[0].funding == ()


def test_an_exit_at_a_settlement_instant_pays_it() -> None:
    """Condition 9. A pending exit fills at the open of a minute, and the settlement falls exactly on that
    open.
    """
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100))
    decided = bars[1].close_us
    exit_open = decided + MINUTE
    stream = _run(
        _Script(bars[0].close_us, s0=90.0, exit_at=decided), bars, funding=(FundingEvent(exit_open, 0.0001),)
    )
    trade = stream.trades[0]
    assert trade.legs[-1].reason == "INVALIDATION"
    assert len(trade.funding) == 1


def test_an_exit_before_a_settlement_in_its_own_minute_pays_nothing() -> None:
    """The exit fills at the open, and the settlement comes 5 ms later, in that same minute."""
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100))
    decided = bars[1].close_us
    settle = decided + MINUTE + 5_000
    stream = _run(
        _Script(bars[0].close_us, s0=90.0, exit_at=decided), bars, funding=(FundingEvent(settle, 0.0001),)
    )
    assert stream.trades[0].funding == ()


def test_no_funding_rate_means_none_charged() -> None:
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100))
    assert _run(_Script(bars[0].close_us), bars).trades[0].book()[1].funding == 0


# ---- size, the leverage cap and the gross cap
# ---------------------------------------------------------------------


def test_size_comes_from_the_decision_price_and_the_initial_stop() -> None:
    """C6. Risk 250, P_D 100, S0 95: R_dec 5, so q0 = 50."""
    plan = plan_entry(
        side=1, decision_price=100.0, s0=95.0, atr=2.0, risk_budget=250.0, capital=100_000.0, leverage_cap=2.0
    )
    assert (plan.r_dec, plan.q0, plan.limit) == (5.0, 50.0, 101.0)
    assert plan.q0 == plan.uncapped_q0


def test_the_leverage_cap_limits_a_position_and_is_recorded() -> None:
    """Capital 1,000 at 2x allows 2,000 of notional, so 20 units at 100, where the risk alone asks for 50."""
    plan = plan_entry(
        side=1, decision_price=100.0, s0=95.0, atr=2.0, risk_budget=250.0, capital=1_000.0, leverage_cap=2.0
    )
    assert plan.q0 == pytest.approx(20.0)
    assert plan.uncapped_q0 == pytest.approx(50.0)
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100))
    stream = _run(_Script(bars[0].close_us), bars, capital=1_000.0, leverage_cap=2.0)
    assert stream.trades[0].leverage_capped is True
    assert stream.counters["size_capped_by_leverage"] == 1


def _record(strategy: str, signal: int, *, qty: float, price: float, exit_at: int) -> TradeRecord:
    legs = (ExitLeg(exit_at, price, price, qty, 0.0, "TEST"),)
    return TradeRecord(
        strategy=strategy,
        version="1",
        symbol="S",
        side=1,
        tag=None,
        signal_us=signal,
        decided_as_of_us=signal + DELAY_US,
        decision_price=price,
        collar_limit=price,
        fill_us=signal + MINUTE,
        fill_event_us=signal + 2 * MINUTE,
        fill_reference=price,
        fill=price,
        q0=qty,
        uncapped_q0=qty,
        leverage_capped=False,
        risk_budget=250.0,
        s0=price - 5.0,
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
        best=price,
        worst=price,
        through_stop=False,
        gap_unresolved=False,
        gap_start_us=None,
        as_recorded_legs=legs,
        line="",
        is_default=True,
        in_portfolio=True,
    )


def test_the_gross_cap_scales_an_entry_to_the_room_left_and_refuses_when_none_is_left() -> None:
    """Capital 1,000, cap 3x: 3,000 of room. Two entries of 1,200 fit 2,400. The third gets 600 of 1,200, so
    half.
    """
    a = _record("A", START, qty=12.0, price=100.0, exit_at=START + 20 * HOUR)
    b = _record("B", START + HOUR, qty=12.0, price=100.0, exit_at=START + 20 * HOUR)
    c = _record("C", START + 2 * HOUR, qty=12.0, price=100.0, exit_at=START + 20 * HOUR)
    d = _record("D", START + 3 * HOUR, qty=12.0, price=100.0, exit_at=START + 20 * HOUR)
    decisions = apply_gross_cap([d, b, a, c], capital=1_000.0, gross_cap=3.0, mark=lambda _, __: 100.0)
    assert decisions[trade_key(a)].scale == 1.0
    assert decisions[trade_key(b)].scale == 1.0
    assert decisions[trade_key(c)].scale == pytest.approx(0.5)
    assert decisions[trade_key(d)].refused


def test_the_gross_cap_frees_room_when_a_position_has_closed() -> None:
    a = _record("A", START, qty=30.0, price=100.0, exit_at=START + HOUR)
    b = _record("B", START + 2 * HOUR, qty=30.0, price=100.0, exit_at=START + 3 * HOUR)
    decisions = apply_gross_cap([a, b], capital=1_000.0, gross_cap=3.0, mark=lambda _, __: 100.0)
    assert decisions[trade_key(a)].scale == 1.0
    assert decisions[trade_key(b)].scale == 1.0


def test_the_gross_cap_uses_only_what_was_held_at_the_decision() -> None:
    """Two entries a minute apart: the later one's fate depends on the earlier, and never the reverse."""
    a = _record("A", START, qty=30.0, price=100.0, exit_at=START + HOUR)
    b = _record("B", START + MINUTE, qty=30.0, price=100.0, exit_at=START + HOUR)
    decisions = apply_gross_cap([b, a], capital=1_000.0, gross_cap=3.0, mark=lambda _, __: 100.0)
    assert decisions[trade_key(a)].scale == 1.0
    assert decisions[trade_key(b)].refused


# ---- accounting
# ---------------------------------------------------------------------------------------------------


def test_a_trade_books_by_hand_to_the_cent() -> None:
    """Long 10 at a fill of 100.01, reference 100. Half out at 110, half stopped at 105 less 5 bp.

    Entry fee: 10 * 100.01 * 0.0005 = 0.50005, so 50 cents.
    Target leg: price 5 * (110 - 100.01) = 49.95. Fee 5 * 110 * 0.0005 = 0.275, so 28 cents (round half to
    even: 27.5). Stop leg: price 104.9475. 5 * (104.9475 - 100.01) = 24.6875, so 2469 cents. Fee 5 * 104.9475
    * 0.0005 =
    0.2624.
    Gross: 5 * 10 + 5 * 5 = 75.00. Slippage is gross less price P&L: 75.00 - 49.95 - 24.69 = 0.36.
    """
    legs = (
        ExitLeg(10, 110.0, 110.0, 5.0, 0.0005, "TARGET_T1"),
        ExitLeg(20, 105.0, 104.9475, 5.0, 0.0005, "STOP"),
    )
    events, booked = book_trade(
        side=1,
        entry_us=1,
        fill_reference=100.0,
        fill=100.01,
        q0=10.0,
        entry_fee_rate=0.0005,
        legs=legs,
        funding=(),
    )
    assert booked.gross == 7500
    assert booked.slippage == 36
    assert booked.fees == 50 + 28 + 26
    assert booked.funding == 0
    assert booked.net == 4995 + 2469 - booked.fees
    assert booked.net == booked.gross - booked.slippage - booked.fees - booked.funding
    assert sum(event.net for event in events) == booked.net
    assert [event.qty_after for event in events] == [10.0, 5.0, 0.0]


def test_funding_books_with_its_sign_at_a_scale() -> None:
    charge = (FundingCharge(5, 0.001, 10.0, 100.0),)
    _, long_book = book_trade(
        side=1,
        entry_us=1,
        fill_reference=100.0,
        fill=100.0,
        q0=10.0,
        entry_fee_rate=0.0,
        legs=(),
        funding=charge,
    )
    _, short_half = book_trade(
        side=-1,
        entry_us=1,
        fill_reference=100.0,
        fill=100.0,
        q0=10.0,
        entry_fee_rate=0.0,
        legs=(),
        funding=charge,
        scale=0.5,
    )
    assert long_book.funding == to_cents(1.0)
    assert short_half.funding == to_cents(-0.5)


def test_stop_slippage_changes_only_the_price_of_stop_exits_never_the_trade_list() -> None:
    """C16. The same generated market at 5 bp and at 50 bp gives the same trades, and differs only in stop
    prices.
    """
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=7, start_us=start, days=150)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 150 * DAY)
    for strategy in ("S01", "S03", "S07"):
        low = run_stream(strategy, tape, tape_trades, sim=sim_params(cost=costs(stop_slip_bps=5.0)))
        high = run_stream(strategy, tape, tape_trades, sim=sim_params(cost=costs(stop_slip_bps=50.0)))
        assert [(t.signal_us, t.fill, t.s0, t.r) for t in low.trades] == [
            (t.signal_us, t.fill, t.s0, t.r) for t in high.trades
        ]
        stops = 0
        for one, other in zip(low.trades, high.trades, strict=True):
            assert [leg.event_us for leg in one.legs] == [leg.event_us for leg in other.legs]
            for left, right in zip(one.legs, other.legs, strict=True):
                if left.reason in ("STOP", "STOP_GAP", "ENTRY_THROUGH_STOP"):
                    stops += 1
                    assert right.price != left.price
                else:
                    assert right.price == left.price
        assert stops > 0


def test_ticks_round_a_long_down_and_a_short_up_and_leave_a_value_on_the_tick() -> None:
    assert round_to_tick(66_469.408, 1, 0.1) == 66_469.4
    assert round_to_tick(66_469.408, -1, 0.1) == 66_469.5
    assert round_to_tick(3_497.6667, 1, 0.01) == 3_497.66
    assert round_to_tick(66_469.4, 1, 0.1) == 66_469.4
    assert round_to_tick(66_469.4, -1, 0.1) == 66_469.4


# ---- gaps
# -----------------------------------------------------------------------------------------------------------


def _with_flag(frame: Any, at_us: int) -> Any:
    import polars as pl

    return frame.with_columns(
        pl.when(pl.col("open_time").dt.timestamp("us") == at_us)
        .then(True)
        .otherwise(pl.col("gap"))
        .alias("gap")
    )


def test_a_gap_during_a_position_is_reported_both_ways_and_the_worse_is_the_headline() -> None:
    """C2. Long at about 100, stop 95. The gap starts in the second bar, and the trade later runs up to a
    target at 110.

    As recorded it wins. If the stop was touched at the start of the gap it loses, so that is the headline.
    """
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (100, 111, 100, 111))
    frame = _with_flag(rows_from_table(bars, T), bars[1].close_us - 30 * MINUTE)
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    targets = (TargetPlan("T1", 110.0, REST),)

    class Flat(Simulator):
        def _bars(self, minutes: int) -> list[Any]:
            from dataclasses import replace

            return [replace(bar, atr=2.0, atr_last=2.0, complete=True) for bar in self.tape.frame(minutes)]

    stream = Flat(_Script(bars[0].close_us, s0=95.0, targets=targets), tape, sim_params()).run()
    trade = stream.trades[0]
    assert trade.gap_unresolved is True
    assert trade.as_recorded_legs[-1].reason == "TARGET_T1"
    assert trade.legs[-1].reason == "GAP_UNRESOLVED_STOP"
    assert trade.legs[-1].reference == 95.0
    assert trade.book()[1].net < 0
    assert stream.counters["gap_unresolved"] == 1


def test_a_gap_that_a_worse_recorded_result_covers_keeps_the_recorded_result() -> None:
    """If what happened is worse than the stop at the gap, what happened is the headline."""
    bars = _bars((100, 101, 99, 100), (100, 101, 99, 100), (90, 91, 89, 90))
    frame = _with_flag(rows_from_table(bars, T), bars[1].close_us - 30 * MINUTE)
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)

    class Flat(Simulator):
        def _bars(self, minutes: int) -> list[Any]:
            from dataclasses import replace

            return [replace(bar, atr=2.0, atr_last=2.0, complete=True) for bar in self.tape.frame(minutes)]

    trade = Flat(_Script(bars[0].close_us, s0=95.0), tape, sim_params()).run().trades[0]
    assert trade.gap_unresolved is True
    assert trade.legs[-1].reason == "STOP_GAP"


def test_a_position_still_open_at_the_end_is_valued_at_the_last_price_and_marked_open() -> None:
    bars = _bars((100, 101, 99, 100), (100, 103, 99, 103))
    trade = _run(_Script(bars[0].close_us, s0=90.0), bars).trades[0]
    assert trade.status == "open"
    assert trade.exit_reason == "OPEN_AT_END"
    assert trade.legs[-1].open_at_end is True
    assert trade.legs[-1].price == 103.0
