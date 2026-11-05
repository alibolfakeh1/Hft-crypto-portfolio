"""The engine on bars shaped as ruling 7 of the leak recheck states, built from generated trades.

An official candle covers `[open, close)`. It is knowable at its close plus the candle allowance. A
zero-trade row is proof of an empty minute and has null prices, and a missing row is a gap. S07 and S08 give
no result here, and the other eight run. The real converter is the data layer's, and this only checks that the
engine reads such rows correctly.
"""

from __future__ import annotations

from dataclasses import replace
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
    generated_trades,
    run_stream,
    sim_params,
    utc,
)
from hft_crypto.bars.core import UTC_TIME, bars_from_official
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.simulator import Simulator, StreamResult
from hft_crypto.engine.tape import MinuteTape
from hft_crypto.strategies.base import Management, PositionView, Proposal, Strategy

START = utc(2000, 1, 1)
DAYS = 150
# S05 is rare, so it runs on a longer market with a seed that reaches it. A seed is picked for coverage only.
SEEDS = {"S05": (10, 200)}
# D-33. It equals A here, so a candle closing at t is known exactly at the decision.
CANDLE_ALLOWANCE_US = 10_000_000
RUNNING = ("S01", "S02", "S03", "S04", "S05", "S06", "S09", "S10")
NOT_ON_CANDLES = ("S07", "S08")
NOT_DECISIONS = frozenset({"GAP_UNRESOLVED", "ENTRY_UNFILLED_AT_END"})


def bars_from(candles: pl.DataFrame, *, first_close_us: int, last_close_us: int) -> pl.DataFrame:
    return bars_from_official(
        candles,
        venue="generated",
        symbol="S",
        first_close_us=first_close_us,
        last_close_us=last_close_us,
        candle_allowance_us=CANDLE_ALLOWANCE_US,
    )


def _tape_through(candles: pl.DataFrame, through_us: int) -> MinuteTape:
    """Candles known by a moment: closed, and past their allowance."""
    last_close = (through_us - CANDLE_ALLOWANCE_US) // MINUTE * MINUTE
    held = candles.filter(pl.col("open_time").dt.timestamp("us") + MINUTE <= last_close)
    bars = bars_from(held, first_close_us=START + MINUTE, last_close_us=last_close)
    return MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)


@lru_cache(maxsize=2)
def _generated(seed: int, days: int) -> pl.DataFrame:
    trades = generated_trades(seed=seed, start_us=START, days=days)
    return candles_from(trades, first_open_us=START, minutes=days * 1440)


def _market(strategy: str) -> pl.DataFrame:
    return _generated(*SEEDS.get(strategy, (7, DAYS)))


def _end(strategy: str) -> int:
    return START + SEEDS.get(strategy, (7, DAYS))[1] * DAY


def _params() -> Any:
    return sim_params(fill_span_allowance_us=CANDLE_ALLOWANCE_US)


def _decisions(stream: StreamResult, cut_us: int) -> list[dict[str, Any]]:
    return [
        event
        for event in stream.events
        if event["knowable_us"] <= cut_us and event["type"] not in NOT_DECISIONS
    ]


@lru_cache(maxsize=12)
def _full(strategy: str) -> StreamResult:
    return run_stream(strategy, _tape_through(_market(strategy), _end(strategy)), None, sim=_params())


def test_a_candle_bar_has_the_shape_ruling_7_states() -> None:
    bars = bars_from(_market("S01"), first_close_us=START + MINUTE, last_close_us=START + 3 * MINUTE)
    assert bars["bar_source"].to_list() == ["official_1m"] * 3
    assert bars["boundary"].to_list() == ["[open, close)"] * 3
    closes = bars["close_time"].dt.timestamp("us").to_list()
    assert closes == [START + MINUTE, START + 2 * MINUTE, START + 3 * MINUTE]
    knowable = bars["knowable_time"].dt.timestamp("us").to_list()
    assert knowable == [close + CANDLE_ALLOWANCE_US for close in closes]


def test_a_zero_trade_row_has_null_prices_and_is_no_gap() -> None:
    candles = pl.DataFrame(
        {
            "open_time": pl.Series([START, START + MINUTE], dtype=pl.Int64).cast(UTC_TIME),
            "open": [100.0, 100.0],
            "high": [101.0, 100.0],
            "low": [99.0, 100.0],
            "close": [100.0, 100.0],
            "volume": [1.0, 0.0],
            "quote_volume": [100.0, 0.0],
            "taker_buy_volume": [0.5, 0.0],
            "trade_count": pl.Series([3, 0], dtype=pl.Int64),
        }
    )
    tape = MinuteTape.from_frame(
        bars_from(candles, first_close_us=START + MINUTE, last_close_us=START + 2 * MINUTE),
        symbol="S",
        delay_us=DELAY_US,
    )
    assert bool(np.isnan(tape.high[1])) and bool(np.isnan(tape.low[1])) and bool(np.isnan(tape.close[1]))
    assert not bool(tape.gap[1])
    assert tape.standing(0, 2, START + 2 * MINUTE + DELAY_US).pending_tail is False


class _Hold(Strategy):
    id = "TEST"
    h_max_hours = {60: 100.0}  # noqa: RUF012

    def __init__(self, at_close: int, s0: float) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.at_close = at_close
        self.s0 = s0

    def on_close(self, market: MarketView) -> list[Proposal]:
        return [Proposal(1, self.s0, (), {}, 4, {})] if market.now_us == self.at_close else []

    def manage(self, market: MarketView, position: PositionView) -> Management:
        return Management()


def _row(open_us: int, price: float, *, count: int = 2, low: float | None = None) -> dict[str, Any]:
    return {
        "open_time": open_us,
        "open": price,
        "high": price,
        "low": price if low is None else low,
        "close": price,
        "volume": float(count),
        "quote_volume": price * count,
        "taker_buy_volume": float(count) / 2.0,
        "trade_count": count,
    }


def _rows_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    frame = pl.DataFrame(rows, schema_overrides={"trade_count": pl.Int64})
    return frame.with_columns(pl.col("open_time").cast(pl.Int64).cast(UTC_TIME))


class _Flat(Simulator):
    def _bars(self, minutes: int) -> list[Any]:
        return [
            replace(bar, atr=2.0, atr_last=2.0, complete=True, gap=False) for bar in self.tape.frame(minutes)
        ]


def test_a_carried_price_on_a_zero_trade_row_cannot_touch_a_stop() -> None:
    """Long, stop 95. The venue carries a close of 90 on a minute with no trades. With its price null,
    nothing stops.
    """
    hour = 60 * MINUTE
    rows = [_row(START + index * MINUTE, 100.0) for index in range(120)]
    rows[80] = _row(START + 80 * MINUTE, 90.0, count=0)
    bars = bars_from(_rows_frame(rows), first_close_us=START + MINUTE, last_close_us=START + 120 * MINUTE)
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    trade = _Flat(_Hold(START + hour, 95.0), tape, sim_params()).run().trades[0]
    assert trade.status == "open"
    assert all(leg.open_at_end for leg in trade.legs)


def test_a_traded_row_at_the_same_price_does_stop() -> None:
    """The guard for the test above: with trades at that price, the stop is touched."""
    hour = 60 * MINUTE
    rows = [_row(START + index * MINUTE, 100.0) for index in range(120)]
    rows[80] = _row(START + 80 * MINUTE, 90.0)
    bars = bars_from(_rows_frame(rows), first_close_us=START + MINUTE, last_close_us=START + 120 * MINUTE)
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    trade = _Flat(_Hold(START + hour, 95.0), tape, sim_params()).run().trades[0]
    assert trade.status == "closed"
    assert trade.exit_reason == "STOP_GAP"


def test_a_missing_row_is_a_gap_in_its_bar_and_a_position_across_it_is_reported_both_ways() -> None:
    """A minute with no candle at all is a gap, whichever way the rows arrive. Here it is left out of the
    frame.
    """
    hour = 60 * MINUTE
    rows = [_row(START + index * MINUTE, 100.0 + index * 0.1) for index in range(180) if index != 90]
    frame = _rows_frame(rows)
    # Through the converter a missing candle becomes a flagged row, and without it there is simply no row.
    converted = bars_from(frame, first_close_us=START + MINUTE, last_close_us=START + 180 * MINUTE)
    assert bool(converted.filter(pl.col("empty_proof") == "none")["gap"].all())
    tape = MinuteTape.from_frame(converted, symbol="S", delay_us=DELAY_US)
    assert bool(tape.gap[90])
    bar = tape.frame(60)[1]
    assert (bar.gap is False and bar.complete is False) or bar.gap is True
    assert tape.frame(60)[1].atr is None
    trade = _Flat(_Hold(START + hour, 95.0), tape, sim_params()).run().trades[0]
    assert trade.gap_unresolved is True
    assert trade.gap_start_us == START + 90 * MINUTE

    no_row = converted.filter(pl.col("empty_proof") != "none")
    missing_tape = MinuteTape.from_frame(no_row, symbol="S", delay_us=DELAY_US)
    assert missing_tape.size == 179
    assert missing_tape.frame(60)[1].gap is True
    jumped = _Flat(_Hold(START + hour, 95.0), missing_tape, sim_params()).run().trades[0]
    assert jumped.gap_unresolved is True
    assert jumped.gap_start_us == START + 90 * MINUTE


def test_a_row_exactly_on_a_boundary_is_in_the_later_bar() -> None:
    """`[open, close)`: a candle opening at 01:00 is the first minute of the bar closing 02:00."""
    hour = 60 * MINUTE
    rows = [_row(START + index * MINUTE, 100.0) for index in range(120)]
    rows[60] = _row(START + 60 * MINUTE, 150.0)
    bars = bars_from(_rows_frame(rows), first_close_us=START + MINUTE, last_close_us=START + 120 * MINUTE)
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    first, second = tape.frame(60)
    assert (first.close_us, first.h) == (START + hour, 100.0)
    assert (second.close_us, second.h) == (START + 2 * hour, 150.0)


@pytest.mark.parametrize("strategy", NOT_ON_CANDLES)
def test_a_strategy_that_needs_trades_gives_no_result_on_candles(strategy: str) -> None:
    stream = _full(strategy)
    assert stream.setups == 0
    assert stream.reasons == {"NEEDS_T1_TRADES": stream.closes}


@pytest.mark.parametrize("strategy", RUNNING)
def test_truncation_invariance_on_candle_bars(strategy: str) -> None:
    full = _full(strategy)
    created = [event for event in full.events if event["type"] == "SETUP_CREATED"]
    assert created, f"{strategy} made no setup on candles here, so this test would prove nothing"
    candles = _market(strategy)
    for event in created[:2]:
        decided = event["computed_at_us"] + DELAY_US
        for cut in (decided, decided - 1, decided + 90 * MINUTE):
            other = run_stream(strategy, _tape_through(candles, cut), None, sim=_params())
            assert _decisions(full, cut) == _decisions(other, cut), f"{strategy} at {cut}"


@pytest.mark.parametrize("strategy", RUNNING)
def test_future_perturbation_on_candle_bars(strategy: str) -> None:
    full = _full(strategy)
    created = [event for event in full.events if event["type"] == "SETUP_CREATED"]
    assert created
    candles = _market(strategy)
    cut = created[0]["computed_at_us"] + DELAY_US
    last_known = (cut - CANDLE_ALLOWANCE_US) // MINUTE * MINUTE
    is_future = pl.col("open_time").dt.timestamp("us") + MINUTE > last_known
    rng = np.random.default_rng(55)
    size = candles.height
    noise = pl.Series("noise", rng.uniform(1.0, 100_000.0, size))
    changed = (
        candles.with_columns(noise)
        .with_columns(
            *[
                pl.when(is_future).then(pl.col("noise")).otherwise(pl.col(name)).alias(name)
                for name in ("open", "high", "low", "close")
            ]
        )
        .drop("noise")
    )
    other = run_stream(strategy, _tape_through(changed, _end(strategy)), None, sim=_params())
    assert _decisions(full, cut) == _decisions(other, cut)


def test_trade_built_and_candle_bars_are_never_joined_in_one_tape() -> None:
    """Condition 6: every row of a sample has one source, and the frame says which."""
    bars = bars_from(_market("S01"), first_close_us=START + MINUTE, last_close_us=START + 1440 * MINUTE)
    assert bars["bar_source"].n_unique() == 1
