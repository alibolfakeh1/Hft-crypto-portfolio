"""Data shorter than a strategy's requirements gives no setup, and says why. It never gives a loosened rule.

The shape is the one the coordinator named: one separate day a month, for 12 days. Under C3, a condition on
an undefined value fails, and `VR` needs at least 15 days of bars in its last 30 days. Any count other than
zero here is a bug or an undeclared rule change.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from engine_helpers import (
    DAY,
    DELAY_US,
    MINUTE,
    engine_config,
    generated_trades,
    minute_bars,
    run_stream,
    utc,
)
from hft_crypto.engine.simulator import StreamResult
from hft_crypto.engine.tape import MinuteTape, TradeTape
from hft_crypto.reports.portfolio import stream_status
from hft_crypto.strategies import available_strategies

STRATEGIES = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")
FIRST_OF_MONTH = [dt.date(2000, month, 1) for month in range(1, 13)]
# The inputs a strategy names when it cannot make a setup for lack of history.
UNDEFINED = frozenset(
    {
        "VR_UNDEFINED",
        "ATR_UNDEFINED",
        "SRV_UNDEFINED",
        "ATRD_UNDEFINED",
        "PR_UNDEFINED",
        "PRIOR_PERIOD_LEVELS_UNDEFINED",
        "SEASONAL_PROFILE_UNDEFINED",
        "NEEDS_T1_TRADES",
    }
)


def _twelve_separate_days(*, candles_only: bool) -> tuple[MinuteTape, TradeTape | None]:
    """Twelve whole days, one a month, with ids running on inside each day and not between months."""
    bars = []
    trades = []
    first_id = 1000
    for index, day in enumerate(FIRST_OF_MONTH):
        start = utc(day.year, day.month, day.day)
        one_day = generated_trades(seed=500 + index, start_us=start, days=1, first_id=first_id)
        first_id += one_day.height + 1000
        bars.append(minute_bars(one_day, first_close_us=start + MINUTE, last_close_us=start + DAY))
        trades.append(one_day)
    tape = MinuteTape.from_frame(pl.concat(bars), symbol="S", delay_us=DELAY_US)
    return tape, None if candles_only else TradeTape.from_frame(pl.concat(trades))


@pytest.fixture(scope="module")
def with_trades() -> tuple[MinuteTape, TradeTape | None]:
    return _twelve_separate_days(candles_only=False)


@pytest.fixture(scope="module")
def candles_only() -> tuple[MinuteTape, TradeTape | None]:
    return _twelve_separate_days(candles_only=True)


def _assert_no_setups_with_a_reason(stream: StreamResult) -> None:
    assert stream.setups == 0, f"{stream.strategy}: {stream.setups} setups"
    assert stream.trades == []
    assert stream_status(stream) == "NO_SETUPS"
    assert not [event for event in stream.events if event["type"] in ("SETUP_CREATED", "ENTRY")]
    assert stream.reasons, f"{stream.strategy} made no setup and logged no reason"
    assert set(stream.reasons) & UNDEFINED, f"{stream.strategy} names no undefined input: {stream.reasons}"
    assert sum(stream.reasons.values()) >= stream.closes


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_exactly_zero_setups_with_trades_held(
    strategy: str, with_trades: tuple[MinuteTape, TradeTape | None]
) -> None:
    tape, trades = with_trades
    _assert_no_setups_with_a_reason(run_stream(strategy, tape, trades))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_exactly_zero_setups_on_candles_alone(
    strategy: str, candles_only: tuple[MinuteTape, TradeTape | None]
) -> None:
    tape, _ = candles_only
    _assert_no_setups_with_a_reason(run_stream(strategy, tape, None))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_grid_line_is_also_zero(
    strategy: str, with_trades: tuple[MinuteTape, TradeTape | None]
) -> None:
    tape, trades = with_trades
    for line in engine_config().strategies[strategy].lines():
        stream = run_stream(strategy, tape, trades, params=line.params)
        assert stream.setups == 0, f"{strategy} {line.line_id}"
        assert stream.reasons


def test_all_ten_are_covered() -> None:
    assert available_strategies() == STRATEGIES


def test_the_days_really_are_separate(with_trades: tuple[MinuteTape, TradeTape | None]) -> None:
    tape, _ = with_trades
    assert tape.size == 12 * 1440
    bars = tape.frame(60)
    traded = [bar for bar in bars if bar.has_price]
    assert len(traded) == 12 * 24
    # Each hour between the days is on the grid as a gap, under C2, and carries nothing.
    assert all(bar.gap and not bar.complete for bar in bars if not bar.has_price)
    # Nothing carries across a month: no prior day, and ATR starts again each day.
    first_of_each_day = [bar for bar in traded if bar.open_us % DAY == 0]
    assert all(bar.day is None and bar.atr is None and bar.atrd is None for bar in first_of_each_day)
    assert all(bar.vr is None and bar.srv is None for bar in bars)


def test_trades_are_refused_to_a_strategy_on_candles(
    candles_only: tuple[MinuteTape, TradeTape | None],
) -> None:
    """S07 and S08 give no result on candles, and say so at every close. Nothing stands in for trades."""
    tape, _ = candles_only
    for strategy in ("S07", "S08"):
        stream = run_stream(strategy, tape, None)
        assert stream.reasons == {"NEEDS_T1_TRADES": stream.closes}
