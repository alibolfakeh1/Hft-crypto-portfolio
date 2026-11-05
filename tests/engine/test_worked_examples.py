"""S02 to S10 against section 7.12 of each document. Every expected value is the document's own, so none
comes from this code.

Each example is written in `IDEAL` terms, with no delay, `ATR` held as its table says, and exit prices before
slippage. A setup is handed in at the trigger close, and the real strategy then manages the position through
the real simulator. So this checks the stop model, the targets, the invalidation and the time stops, row by
row.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

from engine_helpers import (
    MINUTE,
    ExampleSimulator,
    TableBar,
    day_bar,
    example_params,
    rows_from_table,
    scripted,
    utc,
)
from hft_crypto.engine.simulator import StreamResult
from hft_crypto.engine.tape import MinuteTape, TradeTape
from hft_crypto.strategies.base import REST, Proposal, Strategy, TargetPlan
from hft_crypto.strategies.levels import floor_pivots
from hft_crypto.strategies.registers import HIGH, LOW, Swing
from hft_crypto.strategies.s02_pivot_breakout_retest import S02PivotBreakoutRetest
from hft_crypto.strategies.s02_pivot_breakout_retest import _Memo as S02Memo
from hft_crypto.strategies.s03_market_structure import S03MarketStructure
from hft_crypto.strategies.s03_market_structure import _Memo as S03Memo
from hft_crypto.strategies.s04_supply_demand_zones import S04SupplyDemandZones
from hft_crypto.strategies.s04_supply_demand_zones import _Memo as S04Memo
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip
from hft_crypto.strategies.s05_zone_polarity_flip import _Memo as S05Memo
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import _Memo as S06Memo
from hft_crypto.strategies.s07_anchored_vwap_pullback import Anchor, S07AnchoredVwapPullback
from hft_crypto.strategies.s07_anchored_vwap_pullback import _Memo as S07Memo
from hft_crypto.strategies.s08_volume_profile_value_area import (
    REJECTION,
    S08VolumeProfileValueArea,
    ValueArea,
)
from hft_crypto.strategies.s08_volume_profile_value_area import _Memo as S08Memo
from hft_crypto.strategies.s09_session_range_breakout import S09SessionRangeBreakout
from hft_crypto.strategies.s09_session_range_breakout import _Memo as S09Memo
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression
from hft_crypto.strategies.s10_volatility_compression import _Memo as S10Memo

Row = tuple[float, float, float, float]
HOUR = 60 * MINUTE


def _closes(first: int, count: int, minutes: int) -> list[int]:
    return [first + index * minutes * MINUTE for index in range(count)]


def _tape(rows: Sequence[Row], closes: Sequence[int], minutes: int) -> MinuteTape:
    bars = [TableBar(close, *row) for close, row in zip(closes, rows, strict=True)]
    return MinuteTape.from_frame(rows_from_table(bars, minutes), symbol="S", delay_us=0)


def _stops_after(stream: StreamResult, closes: Sequence[int], s0: float) -> list[float]:
    trade = stream.trades[0]
    path = {row["computed_at_us"]: row["new"] for row in trade.stop_path}
    current = s0
    result = []
    for close in closes:
        current = path.get(close, current)
        result.append(float(current))
    return result


def _targets_after(stream: StreamResult, name: str, closes: Sequence[int], start: float) -> list[float]:
    trade = stream.trades[0]
    path = {row["computed_at_us"]: row["new"] for row in trade.target_path if row["name"] == name}
    current = start
    result = []
    for close in closes:
        current = path.get(close, current)
        result.append(float(current))
    return result


def _in_b(stream: StreamResult) -> float:
    """Result_B before costs: exits at their reference prices, against the fill, over `R_dec`."""
    trade = stream.trades[0]
    value = sum(leg.qty * trade.side * (leg.reference - trade.fill) for leg in trade.legs)
    return value / trade.q0 / trade.r_dec


def _in_r(stream: StreamResult) -> float:
    trade = stream.trades[0]
    value = sum(leg.qty * trade.side * (leg.reference - trade.fill) for leg in trade.legs)
    return value / trade.q0 / trade.r


# ---- S02
# ------------------------------------------------------------------------------------------------------------

S02_ROWS: list[Row] = [
    (3528, 3530, 3510, 3526),
    (3527, 3536, 3522, 3533),
    (3533, 3541, 3529, 3538),
    (3538, 3552, 3534, 3549),
    (3549, 3560, 3544, 3558),
    (3558, 3565, 3551, 3562),
    (3562, 3570, 3556, 3568),
    (3568, 3592, 3563, 3588),
    (3588, 3604, 3584, 3600),
    (3600, 3612, 3596, 3608),
    (3608, 3626, 3603, 3618),
    (3618, 3640, 3614, 3636),
    (3636, 3650, 3630, 3646),
    (3646, 3655, 3622, 3628),
    (3628, 3632, 3609, 3615),
]


def _s02() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 18), len(S02_ROWS), 60)
    tape = _tape(S02_ROWS, closes, 60)
    roll = utc(2000, 1, 20)
    prior = day_bar(utc(2000, 1, 19), 3480.0, 3320.0, 3440.0)
    finished = day_bar(roll, 3570.0, 3405.0, 3568.0)
    levels = floor_pivots(prior)
    memo = S02Memo("D:example:R1", levels["R1"], roll_end_us=prior.end_us)
    proposal = Proposal(
        1,
        levels["R1"] - 9.0,
        (TargetPlan("T1", levels["R2"], 0.5), TargetPlan("T2", levels["R3"], REST)),
        {},
        4,
        memo,
    )
    strategy = scripted(
        S02PivotBreakoutRetest,
        {"timeframe_minutes": 60, "acc": 3, "weekly_levels": False},
        closes[0],
        proposal,
    )
    stream = ExampleSimulator(
        strategy,
        tape,
        example_params(tick=0.01),
        atr=18.0,
        vr=1.0,
        srv=1.5,
        days_at_close={close: finished for close in closes if close >= roll},
        # The bar closing at the roll opened before it, so it reads the old set, under C2.
        days_at_open={close: finished if close > roll else prior for close in closes},
    ).run()
    return stream, closes


def test_s02_entry_figures() -> None:
    stream, _ = _s02()
    trade = stream.trades[0]
    assert trade.s0 == 3497.66
    assert trade.r_dec == pytest.approx(28.34)
    assert trade.collar_limit == pytest.approx(3535.0)
    assert trade.fill == pytest.approx(3527.35, abs=0.01)
    assert trade.r == pytest.approx(29.69, abs=0.01)


def test_s02_every_stop_in_the_table() -> None:
    stream, closes = _s02()
    expected = [
        3497.66,
        3497.66,
        3497.66,
        3502.16,
        3502.16,
        3502.16,
        3531.58,
        3531.58,
        3531.58,
        3596.66,
        3596.66,
        3614.66,
        3614.66,
    ]
    assert _stops_after(stream, closes[1:14], 3497.66) == expected


def test_s02_the_roll_moves_both_targets_and_the_exits_match() -> None:
    stream, closes = _s02()
    roll = closes[6]
    moves = [
        (row["name"], row["new"]) for row in stream.trades[0].target_path if row["computed_at_us"] == roll
    ]
    assert moves == [("T1", pytest.approx(3623.67, abs=0.011)), ("T2", pytest.approx(3679.33, abs=0.011))]
    legs = stream.trades[0].legs
    assert [leg.reason for leg in legs] == ["TARGET_T1", "STOP"]
    assert legs[0].reference == pytest.approx(3623.66)
    assert legs[1].reference == pytest.approx(3614.66)
    assert _in_r(stream) == pytest.approx(3.09, abs=0.01)
    assert _in_b(stream) == pytest.approx(3.24, abs=0.01)


# ---- S03
# ------------------------------------------------------------------------------------------------------------

S03_ROWS: list[Row] = [
    (66380, 66600, 66360, 66560),
    (66565, 66690, 66520, 66640),
    (66640, 66820, 66610, 66790),
    (66790, 66950, 66740, 66900),
    (66900, 67060, 66850, 66980),
    (66980, 67100, 66870, 66930),
    (66930, 66950, 66680, 66720),
    (66720, 66760, 66560, 66610),
    (66610, 66700, 66530, 66660),
    (66660, 66760, 66620, 66740),
    (66740, 66830, 66700, 66800),
    (66800, 66930, 66770, 66900),
    (66900, 67090, 66880, 67060),
    (67060, 67240, 67030, 67210),
    (67210, 67420, 67180, 67390),
    (67390, 67640, 67350, 67610),
    (67610, 67930, 67580, 67880),
    (67880, 68180, 67850, 68140),
    (68140, 68420, 68090, 68380),
    (68380, 68520, 68220, 68290),
    (68290, 68330, 68010, 68060),
    (68060, 68120, 67820, 67870),
    (67870, 68000, 67790, 67960),
    (67960, 68060, 67920, 68030),
    (68030, 68130, 67990, 68090),
    (68090, 68210, 68060, 68180),
    (68180, 68230, 67860, 67900),
    (67900, 67950, 67720, 67740),
    (67735, 67800, 67700, 67750),
    (67750, 67800, 67700, 67750),
]


def _s03() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 18, 23), len(S03_ROWS), 60)
    tape = _tape(S03_ROWS, closes, 60)
    proposal = Proposal(
        1,
        65_560.0,
        (TargetPlan("T1", 67_875.3, 0.30), TargetPlan("T2", 68_725.3, REST)),
        {},
        3,
        S03Memo(),
    )
    params = {"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2}
    strategy = scripted(S03MarketStructure, params, closes[0], proposal)
    assert isinstance(strategy, S03MarketStructure)
    before = closes[0] - 40 * HOUR
    strategy.sigma.entries = [
        Swing(LOW, 64_900.0, -30, before, before),
        Swing(HIGH, 66_500.0, -20, before, before, broken_at=closes[0]),
        Swing(LOW, 65_650.0, -10, before, before, previous_price=64_900.0),
    ]
    strategy.state = "UP"
    strategy.bos_count = 1
    strategy.sigma_h.entries = [Swing(HIGH, 67_900.0, -1, before, before)]
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.1), atr=300.0, vr=1.0).run()
    return stream, closes


def test_s03_entry_figures() -> None:
    stream, _ = _s03()
    trade = stream.trades[0]
    assert trade.s0 == 65_560.0
    assert trade.r_dec == pytest.approx(1000.0)
    assert trade.collar_limit == pytest.approx(66_710.0)
    assert trade.fill == pytest.approx(66_571.7, abs=0.05)
    assert trade.r == pytest.approx(1011.7, abs=0.05)


def test_s03_every_stop_in_the_table() -> None:
    stream, closes = _s03()
    expected = [65_560.0] * 10 + [66_440.0, 66_440.0] + [66_800.0] * 12 + [67_700.0, 67_700.0]
    assert _stops_after(stream, closes[1:27], 65_560.0) == expected


def test_s03_a_swing_low_never_acts_before_its_confirmation() -> None:
    """The document's note on bar 8: the low has printed, and the stop stays until bar 11."""
    stream, closes = _s03()
    first_move = stream.trades[0].stop_path[0]
    assert first_move["computed_at_us"] == closes[11]
    assert first_move["reason"] == "HIGHER_LOW_STEP"


def test_s03_the_recompute_at_the_bos_and_the_exits() -> None:
    stream, closes = _s03()
    trade = stream.trades[0]
    moves = {row["name"]: row["new"] for row in trade.target_path if row["computed_at_us"] == closes[13]}
    assert moves == {"T1": 67_900.0, "T2": 68_592.2}
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "INVALIDATION"]
    assert trade.legs[0].reference == 67_900.0
    assert trade.legs[0].qty == pytest.approx(0.30 * trade.q0)
    # The pending exit is first in the loop at bar 28, at that bar's open.
    assert trade.legs[1].reference == 67_735.0
    assert trade.legs[1].event_us > closes[27]
    assert _in_r(stream) == pytest.approx(1.20, abs=0.01)
    assert _in_b(stream) == pytest.approx(1.21, abs=0.01)


# ---- S04
# ------------------------------------------------------------------------------------------------------------

S04_ROWS: list[Row] = [
    (3222, 3225, 3203, 3216),
    (3215.5, 3222, 3211, 3219),
    (3219, 3228, 3216, 3226),
    (3226, 3233, 3221, 3231),
    (3231, 3244, 3229, 3241),
    (3241, 3249, 3236, 3238),
    (3238, 3243, 3233, 3236),
    (3236, 3240, 3230, 3238),
    (3238, 3258, 3236, 3255),
    (3255, 3268, 3253, 3266),
    (3266, 3276, 3264, 3274),
    (3274, 3286, 3272, 3284),
    (3284, 3287, 3280, 3282),
    (3282, 3285, 3279, 3281),
    (3281, 3282, 3258, 3260),
    (3260, 3262, 3248, 3250),
    (3250, 3262, 3246, 3258),
    (3258, 3270, 3255, 3268),
    (3268, 3283, 3266, 3279),
]


def _s04() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 14), len(S04_ROWS), 60)
    tape = _tape(S04_ROWS, closes, 60)
    memo = S04Memo(prox=3207.0, dist=3196.0, mid=3201.5, extreme=3290.0, sources={"T1": None, "T2": None})
    proposal = Proposal(
        1, 3191.5, (TargetPlan("T1", 3262.0, 0.5), TargetPlan("T2", 3290.0, REST)), {}, 4, memo
    )
    params = {"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0}
    strategy = scripted(S04SupplyDemandZones, params, closes[0], proposal)
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.01), atr=18.0, vr=1.0).run()
    return stream, closes


def test_s04_entry_figures() -> None:
    stream, _ = _s04()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(24.5)
    assert trade.collar_limit == pytest.approx(3225.0)
    assert trade.fill == pytest.approx(3215.82, abs=0.01)
    assert trade.r == pytest.approx(24.32, abs=0.01)


def test_s04_every_stop_in_the_table() -> None:
    stream, closes = _s04()
    expected = [3191.5] * 3 + [3201.5] * 5 + [3219.68] + [3225.5] * 8
    assert _stops_after(stream, closes[1:18], 3191.5) == expected


def test_s04_a_new_opposing_zone_pulls_in_the_far_target_and_the_exits_match() -> None:
    stream, closes = _s04()
    trade = stream.trades[0]
    assert [(row["name"], row["new"], row["computed_at_us"]) for row in trade.target_path] == [
        ("T2", 3281.0, closes[15])
    ]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "TARGET_T2"]
    assert trade.legs[1].reference == 3281.0
    assert _in_r(stream) == pytest.approx(2.29, abs=0.01)
    assert _in_b(stream) == pytest.approx(2.27, abs=0.01)


# ---- S05
# ------------------------------------------------------------------------------------------------------------

S05_ROWS: list[Row] = [
    (66480, 66510, 66300, 66440),
    (66445, 66520, 66420, 66500),
    (66500, 66610, 66470, 66580),
    (66580, 66700, 66560, 66680),
    (66680, 66760, 66640, 66720),
    (66720, 66850, 66700, 66820),
    (66820, 66930, 66790, 66900),
    (66900, 67020, 66880, 67000),
    (67000, 67060, 66850, 66880),
    (66880, 66930, 66780, 66830),
    (66830, 66950, 66810, 66930),
    (66930, 67080, 66900, 67060),
    (67060, 67240, 67040, 67210),
    (67210, 67390, 67180, 67360),
]


def _s05() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 20), len(S05_ROWS), 60)
    tape = _tape(S05_ROWS, closes, 60)
    memo = S05Memo("flip", top=66_350.0, bottom=66_100.0, mid=66_225.0, extreme=66_900.0)
    proposal = Proposal(
        1, 66_030.0, (TargetPlan("T1", 66_900.0, 1.0 / 3.0), TargetPlan("T2", 67_500.0, REST)), {}, 4, memo
    )
    strategy = scripted(S05ZonePolarityFlip, {"timeframe_minutes": 60, "rw": 48}, closes[0], proposal)
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.1), atr=280.0, vr=1.0).run()
    return stream, closes


def test_s05_entry_figures() -> None:
    stream, _ = _s05()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(410.0)
    assert trade.collar_limit == pytest.approx(66_580.0)
    assert trade.fill == pytest.approx(66_451.6, abs=0.05)
    assert trade.r == pytest.approx(421.6, abs=0.05)


def test_s05_every_stop_in_the_table() -> None:
    stream, closes = _s05()
    expected = [66_030.0] * 5 + [66_280.0] + [66_531.3] * 4 + [66_710.0, 66_710.0]
    assert _stops_after(stream, closes[1:13], 66_030.0) == expected


def test_s05_the_rebase_and_the_exits() -> None:
    stream, closes = _s05()
    trade = stream.trades[0]
    moves = [(row["name"], row["new"], row["computed_at_us"]) for row in trade.target_path]
    assert moves == [("T2", 67_340.0, closes[11])]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "TARGET_T2"]
    assert trade.legs[0].qty == pytest.approx(trade.q0 / 3.0)
    assert trade.legs[1].reference == 67_340.0
    assert _in_r(stream) == pytest.approx(1.76, abs=0.01)
    assert _in_b(stream) == pytest.approx(1.81, abs=0.01)


# ---- S06
# ------------------------------------------------------------------------------------------------------------

S06_ROWS: list[Row] = [
    (3306, 3309, 3292, 3302.5),
    (3303, 3309, 3300.5, 3307),
    (3307, 3312, 3304, 3310),
    (3310, 3316, 3308, 3314),
    (3314, 3321, 3312, 3320.5),
    (3320.5, 3327, 3318, 3325),
    (3325, 3331, 3322, 3329),
    (3329, 3334, 3324, 3330),
    (3330, 3337, 3327, 3335),
    (3335, 3342, 3331, 3339),
    (3339, 3346, 3336, 3344),
]


def _s06() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 22, 15), len(S06_ROWS), 15)
    tape = _tape(S06_ROWS, closes, 15)
    proposal = Proposal(
        1,
        3286.64,
        (TargetPlan("T1", 3325.0, 0.5), TargetPlan("T2", 3352.0, REST)),
        {},
        3,
        S06Memo("pool", 3300.0),
    )
    params = {"timeframe_minutes": 15, "n_r": 2, "swing_pools": False}
    strategy = scripted(S06LiquiditySweepReclaim, params, closes[0], proposal)
    roll = utc(2000, 1, 20)
    # The finished day's high is the nearer opposing pool from the 00:00 close on, as the document's table
    # has it.
    finished = day_bar(roll, 3345.0, 3200.0, 3330.0)
    stream = ExampleSimulator(
        strategy,
        tape,
        example_params(tick=0.01),
        atr=9.0,
        vr=1.0,
        days_at_close={close: finished for close in closes if close >= roll},
    ).run()
    return stream, closes


def test_s06_entry_figures() -> None:
    stream, _ = _s06()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(15.86)
    assert trade.collar_limit == pytest.approx(3307.0)
    assert trade.fill == pytest.approx(3303.33, abs=0.01)
    assert trade.r == pytest.approx(16.69, abs=0.01)


def test_s06_every_stop_in_the_table() -> None:
    stream, closes = _s06()
    expected = [3286.64] * 3 + [3297.75] + [3307.29] * 3 + [3307.5, 3313.5]
    assert _stops_after(stream, closes[1:10], 3286.64) == expected


def test_s06_the_roll_moves_the_far_target_and_the_exits_match() -> None:
    stream, closes = _s06()
    trade = stream.trades[0]
    assert [(row["name"], row["new"], row["computed_at_us"]) for row in trade.target_path] == [
        ("T2", 3345.0, closes[7])
    ]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "TARGET_T2"]
    assert trade.legs[1].reference == 3345.0
    assert _in_r(stream) == pytest.approx(1.90, abs=0.01)
    assert _in_b(stream) == pytest.approx(2.00, abs=0.01)


# ---- S07
# ------------------------------------------------------------------------------------------------------------

S07_ROWS: list[Row] = [
    (64050, 64120, 63760, 64010),
    (64015, 64190, 63980, 64150),
    (64150, 64330, 64120, 64300),
    (64300, 64520, 64270, 64480),
    (64480, 64650, 64440, 64620),
    (64620, 64700, 64480, 64530),
    (64530, 64560, 64240, 64330),
    (64330, 64520, 64290, 64490),
    (64490, 64680, 64450, 64640),
    (64640, 64850, 64610, 64810),
    (64810, 65010, 64780, 64970),
    (64970, 65180, 64940, 65140),
    (65140, 65300, 64980, 65020),
    (65020, 65040, 64700, 64760),
    (64760, 64800, 64440, 64480),
]
S07_VWAP = [
    64090.0,
    64230.0,
    64400.0,
    64560.0,
    64590.0,
    64400.0,
    64420.0,
    64570.0,
    64740.0,
    64900.0,
    65060.0,
    65130.0,
    64850.0,
    64600.0,
]


def _s07() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 12), len(S07_ROWS), 60)
    tape = _tape(S07_ROWS, closes, 60)
    # Every bar has q = 300, at its table VWAP, in one trade inside the bar.
    stamps = np.array([close - 30 * MINUTE for close in closes[1:]], dtype=np.int64)
    trades = TradeTape(stamps, np.array(S07_VWAP), np.full(len(S07_VWAP), 300.0))
    a0 = Anchor(
        "L",
        63_000.0,
        closes[0],
        closes[0],
        n=12_000.0,
        pq=12_000.0 * 63_800.0,
        ppq=12_000.0 * (520.0**2 + 63_800.0**2),
    )
    proposal = Proposal(
        1, 63_445.0, (TargetPlan("T1", 64_580.0, 0.5), TargetPlan("T2", 65_360.0, REST)), {}, 4, S07Memo(a0)
    )
    params = {"timeframe_minutes": 60, "major": [10, 5, 2.0], "max_touch": 2}
    strategy = scripted(S07AnchoredVwapPullback, params, closes[0], proposal)
    assert isinstance(strategy, S07AnchoredVwapPullback)
    strategy._anchors[0] = a0
    stream = ExampleSimulator(
        strategy, tape, example_params(tick=0.1), atr=380.0, vr=1.0, trades=trades
    ).run()
    return stream, closes


def test_s07_entry_figures() -> None:
    stream, _ = _s07()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(565.0)
    assert trade.collar_limit == pytest.approx(64_200.0)
    assert trade.fill == pytest.approx(64_021.4, abs=0.05)
    assert trade.r == pytest.approx(576.4, abs=0.05)


def test_s07_every_stop_in_the_table() -> None:
    stream, closes = _s07()
    expected = [
        63_454.2,
        63_465.4,
        63_478.2,
        64_098.2,
        64_098.2,
        64_098.2,
        64_098.2,
        64_098.2,
        64_247.5,
        64_321.0,
        64_396.6,
        64_460.7,
        64_473.7,
    ]
    assert _stops_after(stream, closes[1:14], 63_445.0) == pytest.approx(expected, abs=0.11)


def test_s07_the_bands_move_at_every_close_and_the_exits_match() -> None:
    stream, closes = _s07()
    t2 = _targets_after(stream, "T2", closes[1:14], 65_360.0)
    assert t2 == pytest.approx(
        [
            65_353.7,
            65_357.5,
            65_375.6,
            65_409.0,
            65_442.6,
            65_454.5,
            65_466.9,
            65_491.7,
            65_532.2,
            65_588.0,
            65_659.1,
            65_732.8,
            65_768.4,
        ],
        abs=0.15,
    )
    trade = stream.trades[0]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "STOP"]
    assert trade.legs[0].reference == pytest.approx(64_603.1, abs=0.15)
    assert trade.legs[1].reference == pytest.approx(64_473.7, abs=0.11)
    assert _in_r(stream) == pytest.approx(0.90, abs=0.01)
    assert _in_b(stream) == pytest.approx(0.92, abs=0.01)


def test_s07_on_candles_gives_no_result_and_says_so() -> None:
    closes = _closes(utc(2000, 1, 19, 12), len(S07_ROWS), 60)
    tape = _tape(S07_ROWS, closes, 60)
    strategy: Strategy = S07AnchoredVwapPullback(
        {"timeframe_minutes": 60, "major": [10, 5, 2.0], "max_touch": 2}
    )
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.1), atr=380.0).run()
    assert stream.setups == 0
    assert stream.reasons == {"NEEDS_T1_TRADES": stream.closes}


# ---- S08
# ------------------------------------------------------------------------------------------------------------

S08_ROWS: list[Row] = [
    (66560, 66640, 66540, 66610),
    (66615, 66760, 66570, 66730),
    (66730, 66900, 66700, 66860),
    (66860, 67050, 66820, 67010),
    (67010, 67190, 66960, 67170),
    (67170, 67310, 67130, 67280),
    (67280, 67400, 67220, 67370),
    (67370, 67470, 67300, 67440),
    (67440, 67520, 67360, 67400),
    (67400, 67450, 67250, 67290),
    (67290, 67340, 67120, 67170),
    (67170, 67220, 66940, 66990),
]
S08_DEVELOPING = {5: 66_540.0, 6: 66_640.0, 7: 66_780.0, 8: 66_900.0, 9: 66_990.0, 10: 67_060.0}


def _s08() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 6), len(S08_ROWS), 60)
    tape = _tape(S08_ROWS, closes, 60)
    values = {closes[n]: value for n, value in S08_DEVELOPING.items()}

    class WithDeveloping(S08VolumeProfileValueArea):
        """Section 7.12 invents these values, because they would come from trades."""

        def _developing(self, market: Any, bar: Any) -> ValueArea | None:
            value = values.get(bar.close_us)
            return None if value is None else ValueArea(poc=0.0, vah=0.0, val=value)

    memo = S08Memo(
        branch=REJECTION,
        val=66_500.0,
        poc=67_200.0,
        far=67_900.0,
        edge=66_500.0,
        vaw=1400.0,
        roll_end_us=utc(2000, 1, 19),
    )
    proposal = Proposal(
        1, 66_092.5, (TargetPlan("T1", 67_200.0, 0.5), TargetPlan("T2", 67_900.0, REST)), {}, 3, memo
    )
    params = {"timeframe_minutes": 60, "profile_days": 1}
    strategy = scripted(WithDeveloping, params, closes[0], proposal)
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.1), atr=350.0, vr=1.0).run()
    return stream, closes


def test_s08_entry_figures() -> None:
    stream, _ = _s08()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(517.5)
    assert trade.collar_limit == pytest.approx(66_785.0)
    assert trade.fill == pytest.approx(66_621.7, abs=0.05)
    assert trade.r == pytest.approx(529.2, abs=0.05)


def test_s08_every_stop_in_the_table() -> None:
    stream, closes = _s08()
    expected = [66_092.5] * 3 + [66_412.5] + [66_701.6] * 3 + [66_812.5, 66_902.5, 66_972.5]
    assert _stops_after(stream, closes[1:11], 66_092.5) == expected


def test_s08_the_far_target_decays_with_each_bar_and_the_exits_match() -> None:
    stream, closes = _s08()
    assert _targets_after(stream, "T2", closes[5:11], 67_900.0) == pytest.approx(
        [67_900.0, 67_841.6, 67_783.3, 67_725.0, 67_666.6, 67_608.3], abs=0.11
    )
    trade = stream.trades[0]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "STOP"]
    assert trade.legs[1].reference == 66_972.5
    assert trade.tag is None or trade.tag == REJECTION
    assert _in_r(stream) == pytest.approx(0.88, abs=0.01)
    assert _in_b(stream) == pytest.approx(0.90, abs=0.01)


# ---- S09
# ------------------------------------------------------------------------------------------------------------

S09_ROWS: list[Row] = [
    (67360, 67620, 67330, 67590),
    (67595, 67760, 67540, 67720),
    (67720, 67930, 67680, 67890),
    (67890, 68090, 67850, 68060),
    (68060, 68210, 68020, 68180),
    (68180, 68340, 68140, 68310),
    (68310, 68420, 68250, 68390),
    (68390, 68460, 68280, 68330),
    (68330, 68360, 68160, 68200),
    (68200, 68250, 68090, 68120),
]


def _s09() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 14), len(S09_ROWS), 60)
    tape = _tape(S09_ROWS, closes, 60)
    memo = S09Memo(67_480.0, 500.0, utc(2000, 1, 19, 16), utc(2000, 1, 19, 23))
    proposal = Proposal(
        1, 67_165.0, (TargetPlan("T1", 68_121.25, 0.5), TargetPlan("T2", 68_652.5, REST)), {}, 3, memo
    )
    params = {"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0}
    strategy = scripted(S09SessionRangeBreakout, params, closes[0], proposal)
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.1), atr=260.0, vr=1.0, srv=1.7).run()
    return stream, closes


def test_s09_entry_figures() -> None:
    stream, _ = _s09()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(425.0)
    assert trade.collar_limit == pytest.approx(67_720.0)
    assert trade.fill == pytest.approx(67_601.8, abs=0.05)
    assert trade.r == pytest.approx(436.8, abs=0.05)


def test_s09_every_stop_in_the_table() -> None:
    stream, closes = _s09()
    expected = [
        67_165.0,
        67_165.0,
        67_682.9,
        67_690.0,
        67_820.0,
        68_095.0,
        68_135.0,
        68_135.0,
    ]
    # The table takes BE+ from a fill shown rounded to 67,601.8, which gives 67,682.92. C6 does not round a
    # fill, so the exact 67,601.76 gives 67,682.88, and C16 floors that to 67,682.8: one tick from the table,
    # and reported.
    assert _stops_after(stream, closes[1:9], 67_165.0) == pytest.approx(expected, abs=0.11)


def test_s09_the_session_clock_moves_the_far_target_and_the_exits_match() -> None:
    stream, closes = _s09()
    trade = stream.trades[0]
    assert [(row["name"], row["new"], row["computed_at_us"]) for row in trade.target_path] == [
        ("T2", 68_980.0, closes[2]),
        ("T2", 68_680.0, closes[6]),
    ]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "STOP"]
    assert trade.legs[0].reference == pytest.approx(68_121.2)
    assert trade.legs[1].reference == 68_135.0
    assert _in_r(stream) == pytest.approx(1.21, abs=0.01)
    assert _in_b(stream) == pytest.approx(1.24, abs=0.01)


# ---- S10
# ------------------------------------------------------------------------------------------------------------

S10_ROWS: list[Row] = [
    (3172, 3204, 3168, 3198),
    (3199, 3226, 3192, 3220),
    (3220, 3256, 3214, 3250),
    (3250, 3272, 3240, 3262),
    (3262, 3302, 3258, 3296),
    (3296, 3338, 3290, 3332),
    (3332, 3360, 3326, 3351),
    (3351, 3412, 3345, 3405),
    (3405, 3470, 3396, 3462),
    (3462, 3538, 3450, 3525),
    (3525, 3560, 3480, 3498),
    (3498, 3512, 3440, 3452),
    (3452, 3470, 3418, 3430),
]
S10_ATR = [28.0, 28.43, 29.40, 29.59, 30.62, 31.86, 32.01, 34.51, 37.33, 40.95, 43.74, 45.76, 45.76]


def _s10() -> tuple[StreamResult, list[int]]:
    closes = _closes(utc(2000, 1, 19, 8), len(S10_ROWS), 240)
    tape = _tape(S10_ROWS, closes, 240)
    memo = S10Memo(box_high=3180.0, box_height=90.0, box_mid=3135.0, atr_e=28.0)
    proposal = Proposal(
        1, 3128.0, (TargetPlan("T1", 3338.0, 0.25), TargetPlan("T2", None, REST)), {}, 2, memo
    )
    params = {"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12}
    strategy = scripted(S10VolatilityCompression, params, closes[0], proposal)
    atr = dict(zip(closes, S10_ATR, strict=True))
    stream = ExampleSimulator(strategy, tape, example_params(tick=0.01), atr=atr, vr=1.0).run()
    return stream, closes


def test_s10_the_fill_sets_t1_which_rules_the_fill_bar() -> None:
    """7.3, the named exception to C7."""
    stream, _ = _s10()
    trade = stream.trades[0]
    assert trade.r_dec == pytest.approx(70.0)
    assert trade.collar_limit == pytest.approx(3212.0)
    assert trade.fill == pytest.approx(3199.32, abs=0.01)
    assert trade.r == pytest.approx(71.32, abs=0.01)
    first = trade.target_path[0]
    assert (first["name"], first["old"]) == ("T1", 3338.0)
    assert first["new"] == pytest.approx(3341.96, abs=0.011)
    assert first["effective_from_us"] == trade.fill_us


def test_s10_every_stop_in_the_table() -> None:
    stream, closes = _s10()
    expected = [
        3128.0,
        3128.0,
        3128.0,
        3197.70,
        3230.88,
        3252.55,
        3299.24,
        3351.78,
        3413.61,
        3431.50,
        3431.50,
    ]
    # The document prints ATR to two places, so a stop can differ in its last cent or two.
    assert _stops_after(stream, closes[1:12], 3128.0) == pytest.approx(expected, abs=0.06)


def test_s10_the_climax_target_moves_every_bar_after_t1_and_the_exits_match() -> None:
    stream, closes = _s10()
    moves = [
        row["new"]
        for row in stream.trades[0].target_path
        if row["name"] == "T2" and row["computed_at_us"] in closes
    ]
    assert moves == pytest.approx([3424.02, 3481.02, 3544.66, 3619.90, 3647.48, 3651.52], abs=0.03)
    trade = stream.trades[0]
    assert [leg.reason for leg in trade.legs] == ["TARGET_T1", "STOP"]
    assert trade.legs[0].qty == pytest.approx(0.25 * trade.q0)
    assert trade.legs[1].reference == pytest.approx(3431.50, abs=0.06)
    assert _in_r(stream) == pytest.approx(2.94, abs=0.01)
    assert _in_b(stream) == pytest.approx(3.00, abs=0.01)
