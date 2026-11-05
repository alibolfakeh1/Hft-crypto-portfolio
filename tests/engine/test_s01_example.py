"""S01 against the worked example in section 7.12 of its document. Expected values are the document's own."""

from __future__ import annotations

from typing import Any

import pytest

from engine_helpers import (
    MINUTE,
    ExampleSimulator,
    TableBar,
    day_bar,
    example_params,
    rows_from_table,
    scripted,
    stops_after_each_close,
    utc,
)
from hft_crypto.engine.tape import MinuteTape
from hft_crypto.strategies.base import REST, Proposal, TargetPlan
from hft_crypto.strategies.levels import floor_pivots
from hft_crypto.strategies.s01_floor_pivot_rejection import S01FloorPivotRejection, _Memo

T = 15
# Wednesday, then Thursday from n = 13.
START = utc(2000, 1, 19, 21, 0)
PARAMS: dict[str, Any] = {"timeframe_minutes": T, "touch_limit": 1, "level_set": "full"}
LEVEL = 66_616.67
ROWS = [
    (66_700, 66_810, 66_590, 66_790),
    (66_795, 66_880, 66_760, 66_850),
    (66_850, 66_960, 66_830, 66_900),
    (66_900, 66_985, 66_860, 66_930),
    (66_930, 66_970, 66_850, 66_880),
    (66_880, 66_950, 66_840, 66_905),
    (66_905, 67_120, 66_895, 67_095),
    (67_095, 67_260, 67_060, 67_240),
    (67_240, 67_420, 67_200, 67_400),
    (67_400, 67_560, 67_380, 67_510),
    (67_510, 67_640, 67_470, 67_600),
    (67_600, 67_690, 67_540, 67_650),
    (67_650, 67_720, 67_580, 67_700),
    (67_700, 67_880, 67_680, 67_860),
    (67_860, 67_900, 67_700, 67_720),
    (67_720, 67_760, 67_510, 67_540),
]
STOPS = [
    66_469.4,
    66_469.4,
    66_469.4,
    66_510.9,
    66_552.4,
    66_571.6,
    66_571.6,
    66_571.6,
    67_015.0,
    67_155.0,
    67_335.0,
    67_425.0,
    67_495.0,
    67_535.0,
]


def _run() -> tuple[Any, list[int]]:
    closes = [START + index * T * MINUTE for index in range(len(ROWS))]
    bars = [TableBar(close, *map(float, row)) for close, row in zip(closes, ROWS, strict=True)]
    tape = MinuteTape.from_frame(rows_from_table(bars, T), symbol="S", delay_us=0)
    # R_min = max(144, 4 * 0.0012 * 66,790) = 320.59, so the cost floor binds.
    proposal = Proposal(
        side=1,
        s0=66_790.0 - 320.592,
        targets=(TargetPlan("T1", 67_533.33, 0.5), TargetPlan("T2", 68_816.67, REST)),
        level={"id": "D:example:S1", "price": LEVEL},
        expiry_bars=4,
        memo=_Memo("D:example:S1", LEVEL, 68_816.67, 0, False),
    )
    strategy = scripted(S01FloorPivotRejection, PARAMS, closes[0], proposal)
    roll = closes[12]  # the bar closing 00:00, n = 12
    days = {roll: day_bar(roll, 67_950.0, 66_590.0, 67_700.0)}
    stream = ExampleSimulator(
        strategy, tape, example_params(tick=0.1), atr=180.0, vr=1.0, days_at_close=days
    ).run()
    return stream, closes


def test_the_floor_pivots_of_the_example() -> None:
    values = floor_pivots(day_bar(0, 68_450.0, 66_250.0, 67_900.0))
    assert values["P"] == pytest.approx(67_533.33, abs=0.01)
    assert values["R1"] == pytest.approx(68_816.67, abs=0.01)
    assert values["S1"] == pytest.approx(66_616.67, abs=0.01)


def test_entry_fill_and_risk_figures() -> None:
    stream, _ = _run()
    trade = stream.trades[0]
    assert trade.s0 == pytest.approx(66_469.4)
    assert trade.r_dec == pytest.approx(320.6, abs=0.001)
    assert trade.collar_limit == pytest.approx(66_880.0)
    assert trade.fill_reference == pytest.approx(66_795.0)
    assert trade.fill == pytest.approx(66_801.68, abs=0.01)
    assert trade.r == pytest.approx(332.3, abs=0.05)


def test_the_stop_path_matches_every_row_of_the_table() -> None:
    stream, closes = _run()
    # The trigger bar's close comes first, and the table's rows run n = 1 to 14 after it.
    assert stops_after_each_close(stream, closes[1:15], 66_469.4) == STOPS


def test_the_reasons_for_each_stop_move() -> None:
    stream, _ = _run()
    reasons = [row["reason"] for row in stream.trades[0].stop_path]
    assert reasons[:3] == ["REACTION_CLOCK", "REACTION_CLOCK", "LEVEL_LOCK"]
    assert reasons[3:] == ["FAST_TRAIL"] * 6


def test_the_target_rolls_at_the_utc_close_only() -> None:
    stream, closes = _run()
    path = stream.trades[0].target_path
    assert [(row["name"], row["new"], row["computed_at_us"]) for row in path] == [
        ("T2", 68_236.6, closes[12])
    ]


def test_the_exit_legs_and_the_result() -> None:
    stream, closes = _run()
    trade = stream.trades[0]
    first, second = trade.legs
    assert (first.reason, first.reference, first.event_us // MINUTE) == (
        "TARGET_T1",
        pytest.approx(67_533.3),
        first.event_us // MINUTE,
    )
    assert first.qty == pytest.approx(trade.q0 * 0.5)
    assert second.reason == "STOP"
    assert second.reference == pytest.approx(67_535.0)
    assert second.event_us <= closes[15]
    fill = trade.fill
    in_r = (0.5 * (first.reference - fill) + 0.5 * (second.reference - fill)) / trade.r
    in_b = (0.5 * (first.reference - fill) + 0.5 * (second.reference - fill)) / trade.r_dec
    # The document's figures are before costs: 2.20R and Result_B 2.28.
    assert in_r == pytest.approx(2.20, abs=0.01)
    assert in_b == pytest.approx(2.28, abs=0.01)
