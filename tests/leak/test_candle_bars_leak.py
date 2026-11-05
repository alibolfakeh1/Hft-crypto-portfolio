"""Bars from official candles under ruling 7 of the leak recheck, against truncation and perturbation.

Every minute is a cut. What a run could know at that moment cannot depend on any candle after it. All data is
generated, and all prices are invented.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

import polars as pl
import pytest

from helpers import MINUTE, us
from hft_crypto.bars.core import (
    UTC_TIME,
    TimingContractError,
    aggregate_bars,
    as_of_view,
    bars_for_run,
    bars_from_official,
    ideal_view,
    visible_bars,
)

START = us("2023-06-01T00:00:00")
MINUTES = 180
ALLOWANCE_US = 2_000_000
# Prints, each (stamp in microseconds, price, quantity, is taker buy).
Print = tuple[int, float, float, bool]


def candles_from_prints(prints: Sequence[Print], *, skip: frozenset[int] = frozenset()) -> pl.DataFrame:
    """Candles as a venue makes them: each print falls in [open, open + 60 s). A minute in `skip` has no row
    at all, and a minute with no prints has a row with zero trades that carries the last close forward."""
    rows: dict[int, list[Print]] = {}
    for item in prints:
        rows.setdefault(item[0] // MINUTE * MINUTE, []).append(item)
    last = 100.0
    columns: dict[str, list[float | int]] = {
        name: []
        for name in (
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trade_count",
            "taker_buy_volume",
        )
    }
    for minute in range(MINUTES):
        opening = START + minute * MINUTE
        inside = rows.get(opening, [])
        if inside:
            prices = [item[1] for item in inside]
            values = (prices[0], max(prices), min(prices), prices[-1])
            last = prices[-1]
        else:
            values = (last, last, last, last)
        if minute in skip:
            continue
        columns["open_time"].append(opening)
        for name, value in zip(("open", "high", "low", "close"), values, strict=True):
            columns[name].append(value)
        columns["volume"].append(float(sum(item[2] for item in inside)))
        columns["quote_volume"].append(float(sum(item[1] * item[2] for item in inside)))
        columns["trade_count"].append(len(inside))
        columns["taker_buy_volume"].append(float(sum(item[2] for item in inside if item[3])))
    frame = pl.DataFrame(columns)
    return frame.with_columns(pl.col("open_time").cast(pl.Int64).cast(UTC_TIME))


def _prints(seed: int, *, sparse: bool) -> list[Print]:
    rng = random.Random(seed)
    found: list[Print] = []
    for minute in range(MINUTES):
        if sparse and rng.random() < 0.4:
            continue
        for _ in range(rng.randint(1, 4)):
            stamp = START + minute * MINUTE + rng.randrange(MINUTE)
            found.append((stamp, 100.0 + rng.uniform(-2, 2), rng.uniform(0.1, 3.0), rng.random() < 0.5))
    return sorted(found)


def _bars(candles: pl.DataFrame, last_close: int) -> pl.DataFrame:
    return bars_from_official(
        candles,
        venue="v",
        symbol="S",
        first_close_us=START + MINUTE,
        last_close_us=last_close,
        candle_allowance_us=ALLOWANCE_US,
    )


SKIP = frozenset({7, 8, 50})
CASES = [
    pytest.param(False, frozenset(), id="dense"),
    pytest.param(True, frozenset(), id="sparse"),
    pytest.param(True, SKIP, id="missing rows"),
]


def _scramble_after(prints: list[Print], moment: int, seed: int) -> list[Print]:
    rng = random.Random(seed)
    return [
        item
        if item[0] < moment
        else (item[0], rng.uniform(1, 100000), rng.uniform(0.1, 50.0), rng.random() < 0.5)
        for item in prints
    ]


@pytest.mark.parametrize(("sparse", "skip"), CASES)
def test_truncating_at_any_minute_changes_nothing_a_run_could_know(
    sparse: bool, skip: frozenset[int]
) -> None:
    prints = _prints(1, sparse=sparse)
    full = _bars(candles_from_prints(prints, skip=skip), START + MINUTES * MINUTE)
    for minute in range(1, MINUTES + 1):
        close = START + minute * MINUTE
        kept = [item for item in prints if item[0] < close]
        cut = _bars(
            candles_from_prints(kept, skip=skip).filter(pl.col("open_time").dt.timestamp("us") < close), close
        )
        moment = close + ALLOWANCE_US
        assert visible_bars(full, moment).equals(visible_bars(cut, moment)), minute
        assert as_of_view(full, 1, moment, through_us=close).equals(
            as_of_view(cut, 1, moment, through_us=close)
        ), minute


@pytest.mark.parametrize(("sparse", "skip"), CASES)
def test_changing_every_later_print_changes_nothing_a_run_could_know(
    sparse: bool, skip: frozenset[int]
) -> None:
    prints = _prints(2, sparse=sparse)
    full = _bars(candles_from_prints(prints, skip=skip), START + MINUTES * MINUTE)
    for minute in range(1, MINUTES + 1):
        close = START + minute * MINUTE
        other = _bars(
            candles_from_prints(_scramble_after(prints, close, minute), skip=skip), START + MINUTES * MINUTE
        )
        moment = close + ALLOWANCE_US
        assert visible_bars(full, moment).equals(visible_bars(other, moment)), minute


@pytest.mark.parametrize("minutes", [5, 15, 30, 60])
@pytest.mark.parametrize(("sparse", "skip"), CASES)
def test_higher_bars_are_known_at_the_latest_of_their_inputs_and_hold_nothing_later(
    sparse: bool, skip: frozenset[int], minutes: int
) -> None:
    prints = _prints(3, sparse=sparse)
    last = START + MINUTES * MINUTE
    full = _bars(candles_from_prints(prints, skip=skip), last)
    higher = aggregate_bars(full, minutes, through_close_us=last)
    assert (higher["knowable_time"] >= higher["close_time"]).all()
    spread = higher["knowable_time"].dt.timestamp("us") - higher["close_time"].dt.timestamp("us")
    assert spread.unique().to_list() == [ALLOWANCE_US]
    for bar in range(1, MINUTES // minutes + 1):
        close = START + bar * minutes * MINUTE
        other = _bars(candles_from_prints(_scramble_after(prints, close, bar), skip=skip), last)
        moment = close + ALLOWANCE_US
        one = visible_bars(higher, moment)
        two = visible_bars(aggregate_bars(other, minutes, through_close_us=last), moment)
        assert one.equals(two), bar
        assert as_of_view(full, minutes, moment, through_us=close).equals(
            as_of_view(other, minutes, moment, through_us=close)
        ), bar


@pytest.mark.parametrize("minutes", [1, 5, 60])
def test_the_ideal_view_at_a_close_holds_nothing_later(minutes: int) -> None:
    prints = _prints(4, sparse=True)
    last = START + MINUTES * MINUTE
    full = _bars(candles_from_prints(prints), last)
    for bar in range(1, MINUTES // minutes + 1):
        close = START + bar * minutes * MINUTE
        other = _bars(candles_from_prints(_scramble_after(prints, close, bar)), last)
        one = ideal_view(as_of_view(full, minutes, close), ideal_allowed=True, keep_fill_count=True)
        two = ideal_view(as_of_view(other, minutes, close), ideal_allowed=True, keep_fill_count=True)
        assert one.equals(two), bar


def test_a_bar_is_invisible_until_its_close_plus_the_allowance() -> None:
    bars = _bars(candles_from_prints(_prints(5, sparse=False)), START + MINUTES * MINUTE)
    for minute in (1, 2, 60, MINUTES):
        close = START + minute * MINUTE
        assert visible_bars(bars, close + ALLOWANCE_US).height == minute
        assert visible_bars(bars, close + ALLOWANCE_US - 1).height == minute - 1
        with pytest.raises(TimingContractError):
            bars_for_run(bars, close, close + ALLOWANCE_US - 1)
        assert bars_for_run(bars, close, close + ALLOWANCE_US).height == minute


def test_a_stamp_exactly_on_a_boundary_falls_in_the_later_bar() -> None:
    """The boundary is [open, close), the reverse of a trade-built bar, and each bar states it."""
    boundary = START + 3 * MINUTE
    prints: list[Print] = [(boundary - 1, 100.0, 1.0, True), (boundary, 200.0, 5.0, True)]
    bars = _bars(candles_from_prints(prints), START + 5 * MINUTE)
    before = bars.filter(pl.col("close_time").dt.timestamp("us") == boundary).row(0, named=True)
    after = bars.filter(pl.col("open_time").dt.timestamp("us") == boundary).row(0, named=True)
    assert (before["volume"], before["close"]) == (1.0, 100.0)
    assert (after["volume"], after["close"]) == (5.0, 200.0)
    assert after["boundary"] == "[open, close)"


def test_a_missing_row_is_a_gap_and_a_zero_row_has_no_price() -> None:
    prints: list[Print] = [(START + 30_000_000, 100.0, 1.0, True), (START + 4 * MINUTE, 101.0, 1.0, True)]
    bars = _bars(candles_from_prints(prints, skip=frozenset({2})), START + 5 * MINUTE)
    assert bars["gap"].to_list() == [False, False, True, False, False]
    assert bars["empty_proof"].to_list() == ["traded", "official", "none", "official", "traded"]
    # The venue carries the last close forward here, and it never reaches the bar, or it could touch a stop.
    assert bars["close"].to_list() == [100.0, None, None, None, 101.0]
    assert bars["high"].to_list() == [100.0, None, None, None, 101.0]
    assert bars["volume"].to_list() == [1.0, 0.0, 0.0, 0.0, 1.0]
