"""The tape and indicators: what is known at a close, by hand, and against the data layer's own as-of view."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
import pytest

from engine_helpers import ALLOWANCE_US, DAY, DELAY_US, MINUTE, generated_trades, minute_bars, utc
from helpers import trades_frame
from hft_crypto.bars.core import as_of_view
from hft_crypto.engine.indicators import (
    RollingWindow,
    SeasonalVolume,
    VolatilityRatio,
    WilderAtr,
    clv,
    true_range,
)
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import MinuteTape, TradeTape, ceil_minute, floor_week, weekday

START = utc(2000, 1, 3)  # a Monday
HOUR = 60 * MINUTE


def _bars_from_rows(rows: list[tuple[int, float, float, bool]], minutes: int) -> Any:
    return minute_bars(
        trades_frame(rows, allowance_us=ALLOWANCE_US),
        first_close_us=START + MINUTE,
        last_close_us=START + minutes * MINUTE,
    )


def test_true_range_and_clv_by_hand() -> None:
    assert true_range(105.0, 100.0, 95.0) == 10.0
    assert true_range(105.0, 100.0, 103.0) == 5.0
    assert clv(110.0, 100.0, 106.0) == pytest.approx(0.6)
    assert clv(100.0, 100.0, 100.0) == 0.5


def test_atr_seeds_on_14_and_then_recurses() -> None:
    atr = WilderAtr()
    for _ in range(13):
        atr.update(1.0)
    before_seed = atr.value
    atr.update(1.0)
    seeded = atr.value
    atr.update(15.0)
    # (13 * 1 + 15) / 14 = 2
    recursed = atr.value
    atr.gap()
    assert before_seed is None
    assert seeded == 1.0
    assert recursed == pytest.approx(2.0)
    assert atr.value is None
    assert atr.last == pytest.approx(2.0)


def test_vr_is_undefined_below_half_the_window_and_reads_clock_time() -> None:
    ratio = VolatilityRatio(1440)
    # N is 30 at a daily timeframe, so 15 values are the least. Fourteen give nothing.
    results = [ratio.update(day * DAY, 2.0) for day in range(1, 16)]
    assert results[:14] == [None] * 14
    assert results[14] == 1.0
    # Thirty-one days later everything has left the window, so one new value is not enough.
    assert ratio.update(46 * DAY + DAY, 2.0) is None


def test_srv_needs_four_of_the_eight_previous_slots() -> None:
    seasonal = SeasonalVolume()
    week = 7 * DAY
    assert [seasonal.update(week * index, 10.0, usable=True) for index in range(4)] == [None] * 4
    # Slots of 10, 10, 10, 10, and the median over them is 10.
    assert seasonal.update(week * 4, 20.0, usable=True) == 2.0


def test_a_rolling_window_ranks_within_its_time() -> None:
    window = RollingWindow(10)
    for moment, value in ((1, 5.0), (2, 1.0), (3, 3.0)):
        window.push(moment, value)
    assert window.median() == 3.0
    assert window.share_at_or_below(3.0) == pytest.approx(2 / 3)
    window.advance(12)
    assert len(window) == 1
    assert window.median() == 3.0


def test_calendar_helpers() -> None:
    assert weekday(START) == 0
    assert weekday(START + 5 * DAY) == 5
    assert floor_week(START + 3 * DAY) == START
    assert ceil_minute(START + 1) == START + MINUTE
    assert ceil_minute(START) == START


def test_a_tail_unproven_at_the_decision_is_pending_and_a_proven_one_is_not() -> None:
    """The last trade of the hour is at 00:50. The next one decides whether the tail is proven by the
    decision.
    """
    close = START + HOUR
    # A trade in the first minute, because nothing before the first row could prove that minute empty.
    first = (START + 30_000_000, 100.0, 1.0, True)
    near = [first, (START + 50 * MINUTE, 100.0, 1.0, True), (close + 5_000_000, 100.0, 1.0, True)]
    far = [first, (START + 50 * MINUTE, 100.0, 1.0, True), (close + 40_000_000, 100.0, 1.0, True)]
    as_of = close + DELAY_US
    proven = MinuteTape.from_frame(_bars_from_rows(near, 120), symbol="S", delay_us=DELAY_US)
    assert proven.standing(0, 60, as_of).pending_tail is False
    unproven = MinuteTape.from_frame(_bars_from_rows(far, 120), symbol="S", delay_us=DELAY_US)
    assert unproven.standing(0, 60, as_of).pending_tail is True
    assert unproven.frame(60)[0].complete is False
    assert unproven.frame(60)[0].gap is False


def test_the_bar_keeps_its_prices_and_atr_while_its_tail_is_pending() -> None:
    far = [(START + 50 * MINUTE, 100.0, 1.0, True), (START + HOUR + 40_000_000, 100.0, 1.0, True)]
    tape = MinuteTape.from_frame(_bars_from_rows(far, 120), symbol="S", delay_us=DELAY_US)
    bar = tape.frame(60)[0]
    assert (bar.o, bar.h, bar.l, bar.c) == (100.0, 100.0, 100.0, 100.0)


def test_a_skip_found_later_takes_effect_from_its_own_knowable_time() -> None:
    """Ids skip between 00:50 and 02:30. Nothing shows at the 01:00 close, and the gap arrives at the 03:00
    close.
    """
    rows = trades_frame(
        [
            (START + 30_000_000, 100.0, 1.0, True),
            (START + 50 * MINUTE, 100.0, 1.0, True),
            (START + 150 * MINUTE, 100.0, 1.0, True),
        ],
        allowance_us=ALLOWANCE_US,
    ).with_columns(pl.Series("trade_id", [1, 2, 9], dtype=pl.Int64))
    bars = minute_bars(rows, first_close_us=START + MINUTE, last_close_us=START + 240 * MINUTE)
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    first, second, third, _ = tape.frame(60)
    assert first.gap is False
    assert first.complete is False  # its tail was unproven then
    assert third.has_price is True
    # Flags on earlier bars become known with the row that shows them, stamped 02:30.
    assert first.late_gap is False
    assert second.late_gap is False
    assert third.late_gap is True


def test_the_tape_agrees_with_the_data_layers_as_of_view() -> None:
    """Two readings of ruling 4 written apart: `complete` at each close, against `as_of_view` at the same
    moment.
    """
    start = utc(2000, 1, 1)
    trades = generated_trades(seed=11, start_us=start, days=6)
    bars = minute_bars(trades, first_close_us=start + MINUTE, last_close_us=start + 6 * DAY)
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    checked = 0
    for bar in tape.frame(60)[::5]:
        as_of = bar.close_us + DELAY_US
        view = as_of_view(bars, 60, as_of, through_us=bar.close_us)
        row = view.filter(pl.col("close_time").dt.timestamp("us") == bar.close_us)
        assert row["complete"].to_list() == [bar.complete], f"at {bar.close_us}"
        assert row["high"].to_list() == [bar.h]
        assert row["low"].to_list() == [bar.l]
        assert row["close"].to_list() == [bar.c]
        checked += 1
    assert checked > 20


def test_a_market_view_refuses_trades_after_its_own_close_and_on_candles() -> None:
    from hft_crypto.bars.core import TimingContractError

    tape = TradeTape(
        np.array([10, 20, 30], dtype=np.int64), np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 1.0])
    )
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=60, higher=(), trades=tape)
    market.now_us = 20
    assert market.tier == "T1"
    slice_ = market.trades_between(0, 20)
    assert slice_.price.tolist() == [1.0, 2.0]
    assert market.trades_between(10, 20).price.tolist() == [2.0]
    with pytest.raises(TimingContractError, match="after its own close"):
        market.trades_between(0, 21)
    candles = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=60, higher=(), trades=None)
    assert candles.tier == "T0"
    with pytest.raises(TimingContractError, match="T0"):
        candles.trades_between(0, 0)


def test_a_strategy_is_handed_no_frame_and_no_tape() -> None:
    """The view exposes released bars and asks for trades by time. It has no attribute holding a table."""
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=60, higher=(), trades=None)
    public = {name for name in dir(market) if not name.startswith("_")}
    assert public == {
        "symbol",
        "tick",
        "rt",
        "now_us",
        "tier",
        "bars",
        "bar",
        "higher",
        "r_min",
        "trades_between",
        # C16: the tick in force at an instant up to this close, refused after it as a trade read is.
        "tick_at",
    }
