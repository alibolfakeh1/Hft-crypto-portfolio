"""The report layer on invented trades. Every expected figure here is worked out by hand in a comment."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hft_crypto.engine.accounting import ExitLeg
from hft_crypto.engine.simulator import TradeRecord
from hft_crypto.reports.portfolio import (
    _cost_lines,
    _drawdown,
    _overlap,
    _tally,
    _unit,
    build_axis,
    equity_curve,
)

HOUR = 3_600_000_000
MINUTE = 60_000_000
START = 946_684_800_000_000  # 2000-01-01


def _trade(*, side: int = 1, symbol: str = "A", exit_hour: int = 3) -> TradeRecord:
    """10 units filled at 100 at hour 1, with no fees and no slippage, leaving at 110 at the stated hour."""
    leg = ExitLeg(START + exit_hour * HOUR, 110.0, 110.0, 10.0, 0.0, "TARGET_T1")
    return TradeRecord(
        strategy="S",
        version="1",
        symbol=symbol,
        side=side,
        tag=None,
        signal_us=START,
        decided_as_of_us=START + 10_000_000,
        decision_price=100.0,
        collar_limit=101.0,
        fill_us=START + HOUR - MINUTE,
        fill_event_us=START + HOUR,
        fill_reference=100.0,
        fill=100.0,
        q0=10.0,
        uncapped_q0=10.0,
        leverage_capped=False,
        risk_budget=50.0,
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
        exit_reason="TARGET_T1",
        stop_kind="initial",
        status="closed",
        bars_held=2,
        best=110.0,
        worst=100.0,
        through_stop=False,
        gap_unresolved=False,
        gap_start_us=None,
        as_recorded_legs=(leg,),
        line="",
        is_default=True,
        in_portfolio=True,
    )


AXIS = np.array([START + index * HOUR for index in range(5)], dtype=np.int64)


def test_the_axis_is_a_grid_with_the_last_moment_as_its_final_point() -> None:
    axis = build_axis(START + 30 * MINUTE, START + 2 * HOUR + 10 * MINUTE, 60)
    assert axis.tolist() == [START + HOUR, START + 2 * HOUR, START + 2 * HOUR + 10 * MINUTE]


def test_equity_marks_an_open_position_and_then_books_it_by_hand() -> None:
    """Capital 1,000. Marks 100, 100, 105, 110, 110. Long 10 from hour 1, out at 110 at hour 3.

    Hour 0: flat, 1,000. Hour 1: open, mark 100, so 1,000. Hour 2: mark 105, up 50. Hour 3: booked at 110, up
    100.
    """
    marks = {"A": np.array([100.0, 100.0, 105.0, 110.0, 110.0])}
    curve = equity_curve([_trade()], axis=AXIS, marks=marks, capital_cents=100_000)
    assert curve.tolist() == [100_000, 100_000, 105_000, 110_000, 110_000]


def test_a_short_marks_the_other_way() -> None:
    """Short 10 at 100, out at 110 at hour 3. At hour 2 the mark of 105 is 50 against it."""
    marks = {"A": np.array([100.0, 100.0, 105.0, 110.0, 110.0])}
    curve = equity_curve([_trade(side=-1)], axis=AXIS, marks=marks, capital_cents=100_000)
    assert curve.tolist() == [100_000, 100_000, 95_000, 90_000, 90_000]


def test_a_scale_of_a_half_marks_half_and_a_refused_trade_marks_nothing() -> None:
    marks = {"A": np.array([100.0, 100.0, 105.0, 110.0, 110.0])}
    half = equity_curve([_trade()], axis=AXIS, marks=marks, capital_cents=100_000, scale_of=lambda _: 0.5)
    assert half.tolist() == [100_000, 100_000, 102_500, 105_000, 105_000]
    none = equity_curve([_trade()], axis=AXIS, marks=marks, capital_cents=100_000, scale_of=lambda _: 0.0)
    assert none.tolist() == [100_000] * 5


def test_drawdown_by_hand() -> None:
    """Peak 110 at hour 1, trough 88 at hour 2: 22 down, which is 20 percent. Below the peak from hour 2 to
    hour 4.
    """
    equity = np.array([100_00, 110_00, 88_00, 99_00, 111_00], dtype=np.int64)
    result = _drawdown(equity, AXIS)
    assert result["max_drawdown_money"] == 22.0
    assert result["max_drawdown_pct"] == pytest.approx(-20.0)
    assert result["max_drawdown_duration_hours"] == 2.0


def test_costs_multiply_on_the_same_trade_list_and_funding_does_not() -> None:
    """Fills 100 and 110 on 10 units, reference 100 and 110. Slippage nil. Fees 5 and 5.5, so 10.50. Funding
    none.

    Gross 100.00. Net at 1x is 89.50, at 2x 79.00, at 3x 68.50. Break even at 100 / 10.5 of the cost.
    """
    leg = ExitLeg(START + 3 * HOUR, 110.0, 110.0, 10.0, 0.005, "TARGET_T1")
    trade = replace(_trade(), entry_fee_rate=0.005, legs=(leg,), as_recorded_legs=(leg,))
    tally = _tally([trade], _unit)
    assert (tally.gross, tally.fees, tally.slippage, tally.net) == (10_000, 1_050, 0, 8_950)
    lines = _cost_lines(tally, 12.0)
    assert lines["net_pnl_cost_2x"] == 79.0
    assert lines["net_pnl_cost_3x"] == 68.5
    assert lines["break_even_cost_multiple"] == pytest.approx(10_000 / 1_050, abs=1e-4)
    assert lines["break_even_rt_bps"] == pytest.approx(12.0 * 10_000 / 1_050, abs=1e-3)


def test_r_statistics_leave_out_a_trade_through_its_stop_and_count_it() -> None:
    """C10. Money always includes it, and every R figure prints the number it leaves out."""
    through = replace(_trade(), through_stop=True)
    tally = _tally([_trade(), through], _unit)
    assert tally.net == 20_000
    # 100.00 on 10 units with R of 5 is 2 R.
    assert tally.net_r == [2.0]
    assert tally.r_excluded == 1


def test_r_does_not_change_with_the_portfolios_scale() -> None:
    assert _tally([_trade()], lambda _: 0.25).net_r == _tally([_trade()], _unit).net_r


def test_overlap_by_hand() -> None:
    """A long from hour 1 to 3, and B long or short over the same hours. Marks 0 to 4, so open at marks 1 and
    2.
    """
    prices = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    marks = {"A": prices, "B": prices}
    together = _overlap(
        [_trade(), _trade(symbol="B")],
        axis=AXIS,
        marks=marks,
        symbols=("A", "B"),
        capital=1_000.0,
        scale_of=_unit,
    )
    assert together["marks"] == 5
    assert together["open_together_marks"] == 2
    assert together["open_together_share"] == 0.4
    assert together["same_direction_marks"] == 2
    assert together["same_direction_share_of_open_together"] == 1.0
    # Two positions of 10 at 100, on capital of 1,000: gross 2x at most.
    assert together["gross_exposure_max"] == 2.0
    opposed = _overlap(
        [_trade(), _trade(side=-1, symbol="B")],
        axis=AXIS,
        marks=marks,
        symbols=("A", "B"),
        capital=1_000.0,
        scale_of=_unit,
    )
    assert opposed["open_together_marks"] == 2
    assert opposed["same_direction_marks"] == 0
    apart = _overlap(
        [_trade(exit_hour=1), _trade(symbol="B")],
        axis=AXIS,
        marks=marks,
        symbols=("A", "B"),
        capital=1_000.0,
        scale_of=_unit,
    )
    assert apart["open_together_marks"] == 0
    assert apart["same_direction_share_of_open_together"] is None
