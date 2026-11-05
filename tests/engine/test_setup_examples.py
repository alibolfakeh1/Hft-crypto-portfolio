"""Each strategy finds its own setup from bars, and `S0` and the targets match section 7.12 of its document.

The other example tests hand a setup in, to check the management. Here the real rule has to detect it. Bars
around the trigger bar are invented where a document only gives the trigger, and they keep to what its text
says about them. Inputs a document states as given, such as a prior day or a zone, are placed where the
strategy reads them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

from engine_helpers import ExampleSimulator, TableBar, day_bar, example_params, rows_from_table, utc
from hft_crypto.engine.simulator import StreamResult
from hft_crypto.engine.tape import Bar, MinuteTape, TradeTape
from hft_crypto.strategies.levels import floor_pivots
from hft_crypto.strategies.registers import HIGH, LOW, Swing
from hft_crypto.strategies.s01_floor_pivot_rejection import S01FloorPivotRejection
from hft_crypto.strategies.s02_pivot_breakout_retest import S02PivotBreakoutRetest
from hft_crypto.strategies.s03_market_structure import S03MarketStructure
from hft_crypto.strategies.s04_supply_demand_zones import S04SupplyDemandZones
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim
from hft_crypto.strategies.s07_anchored_vwap_pullback import Anchor, S07AnchoredVwapPullback
from hft_crypto.strategies.s08_volume_profile_value_area import S08VolumeProfileValueArea, ValueArea
from hft_crypto.strategies.s09_session_range_breakout import S09SessionRangeBreakout, SeasonalProfile
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression
from hft_crypto.strategies.zones import Zone

Row = tuple[float, float, float, float]
MINUTE = 60_000_000


def _closes(first: int, count: int, minutes: int) -> list[int]:
    return [first + index * minutes * MINUTE for index in range(count)]


def _tape(rows: Sequence[Row], closes: Sequence[int], minutes: int) -> MinuteTape:
    bars = [TableBar(close, *row) for close, row in zip(closes, rows, strict=True)]
    return MinuteTape.from_frame(rows_from_table(bars, minutes), symbol="S", delay_us=0)


def _setup(stream: StreamResult) -> dict[str, Any]:
    created = [event for event in stream.events if event["type"] == "SETUP_CREATED"]
    assert created, f"no setup found: {stream.reasons}"
    first: dict[str, Any] = created[0]
    return first


def _target(event: dict[str, Any], name: str) -> float | None:
    found: float | None = next(price for key, price, _ in event["targets"] if key == name)
    return found


def test_s01_finds_its_rejection_at_the_first_touch() -> None:
    prior = day_bar(utc(2000, 1, 19), 68_450.0, 66_250.0, 67_900.0)
    closes = _closes(utc(2000, 1, 19, 20), 5, 15)
    rows: Sequence[Row] = [(66_850, 66_900, 66_800, 66_850)] * 4 + [(66_700, 66_810, 66_590, 66_790)]
    strategy = S01FloorPivotRejection({"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 15),
        example_params(tick=0.1),
        atr=180.0,
        vr=1.0,
        days_at_open=dict.fromkeys(closes, prior),
        fields={"atrd": 2000.0, "day_open": 66_900.0},
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[4]
    assert event["side"] == 1
    assert event["s0"] == 66_469.4
    assert _target(event, "T1") == 67_533.3
    assert _target(event, "T2") == 68_816.6
    assert event["level"]["price"] == pytest.approx(floor_pivots(prior)["S1"])


def test_s01_refuses_a_day_already_down_too_far_and_says_nothing_is_there() -> None:
    prior = day_bar(utc(2000, 1, 19), 68_450.0, 66_250.0, 67_900.0)
    closes = _closes(utc(2000, 1, 19, 20), 5, 15)
    rows: Sequence[Row] = [(66_850, 66_900, 66_800, 66_850)] * 4 + [(66_700, 66_810, 66_590, 66_790)]
    strategy = S01FloorPivotRejection({"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 15),
        example_params(tick=0.1),
        atr=180.0,
        vr=1.0,
        days_at_open=dict.fromkeys(closes, prior),
        # DayOpen - C is 1,000, and 0.8 * ATRD is 800, so the filter refuses it.
        fields={"atrd": 1000.0, "day_open": 67_790.0},
    ).run()
    assert stream.setups == 0
    assert stream.reasons["NO_PATTERN"] >= 1


def test_s02_finds_the_break_the_acceptance_and_the_retest() -> None:
    prior = day_bar(utc(2000, 1, 19), 3480.0, 3320.0, 3440.0)
    closes = _closes(utc(2000, 1, 19, 12), 7, 60)
    rows: Sequence[Row] = [
        (3490, 3506, 3488, 3500),
        (3500, 3514, 3499, 3512),
        (3512, 3522, 3510, 3520),
        (3520, 3533, 3518, 3531),
        (3531, 3535, 3525, 3530),
        (3530, 3532, 3526, 3528),
        (3528, 3530, 3510, 3526),
    ]
    strategy = S02PivotBreakoutRetest({"timeframe_minutes": 60, "acc": 3, "weekly_levels": False})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 60),
        example_params(tick=0.01),
        atr=18.0,
        vr=1.0,
        srv=1.3,
        days_at_open=dict.fromkeys(closes, prior),
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[6]
    assert event["s0"] == 3497.66
    assert _target(event, "T1") == pytest.approx(3573.33, abs=0.011)
    assert _target(event, "T2") == pytest.approx(3666.67, abs=0.011)


def test_s02_acceptance_fails_on_thin_seasonal_volume() -> None:
    prior = day_bar(utc(2000, 1, 19), 3480.0, 3320.0, 3440.0)
    closes = _closes(utc(2000, 1, 19, 12), 7, 60)
    rows: Sequence[Row] = [
        (3490, 3506, 3488, 3500),
        (3500, 3514, 3499, 3512),
        (3512, 3522, 3510, 3520),
        (3520, 3533, 3518, 3531),
        (3531, 3535, 3525, 3530),
        (3530, 3532, 3526, 3528),
        (3528, 3530, 3510, 3526),
    ]
    strategy = S02PivotBreakoutRetest({"timeframe_minutes": 60, "acc": 3, "weekly_levels": False})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 60),
        example_params(tick=0.01),
        atr=18.0,
        vr=1.0,
        srv=0.9,
        days_at_open=dict.fromkeys(closes, prior),
    ).run()
    assert stream.setups == 0


def test_s03_enters_on_the_bos_and_not_on_the_choch() -> None:
    closes = _closes(utc(2000, 1, 18, 22), 2, 60)
    rows: Sequence[Row] = [(66_300, 66_400, 66_280, 66_380), (66_380, 66_600, 66_360, 66_560)]
    strategy = S03MarketStructure({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2})
    before = closes[0] - 40 * 60 * MINUTE
    strategy.sigma.entries = [
        Swing(LOW, 64_900.0, -30, before, before),
        Swing(HIGH, 66_500.0, -20, before, before),
        Swing(LOW, 65_650.0, -10, before, before, previous_price=64_900.0),
    ]
    strategy.sigma_h.entries = [Swing(HIGH, 67_900.0, -1, before, before)]
    strategy.state = "UP"
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 60), example_params(tick=0.1), atr=300.0, vr=1.0
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[1]
    assert event["s0"] == 65_560.0
    assert _target(event, "T1") == 67_875.3
    assert _target(event, "T2") == 68_725.3

    choch = S03MarketStructure({"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2})
    choch.sigma.entries = list(strategy.sigma.entries)
    choch.sigma.entries = [
        Swing(LOW, 64_900.0, -30, before, before),
        Swing(HIGH, 66_500.0, -20, before, before),
        Swing(LOW, 65_650.0, -10, before, before, previous_price=64_900.0),
    ]
    choch.state = "DOWN"
    flipped = ExampleSimulator(
        choch, _tape(rows, closes, 60), example_params(tick=0.1), atr=300.0, vr=1.0
    ).run()
    assert flipped.setups == 0
    assert choch.state == "UP"


def _zone(side: int, prox: float, dist: float, *, birth: int, index: int = 0) -> Zone:
    return Zone(
        id=f"E:{side}:{prox}",
        side=side,
        prox=prox,
        dist=dist,
        atr_base=20.0,
        departure=0.75,
        tightness=0.633,
        birth_index=index,
        birth_us=birth,
        base_end=index - 1,
        is_entry=True,
    )


def test_s04_takes_the_first_return_to_a_fresh_zone() -> None:
    closes = _closes(utc(2000, 1, 19, 12), 3, 60)
    rows: Sequence[Row] = [(3240, 3250, 3232, 3238), (3238, 3240, 3222, 3224), (3222, 3225, 3203, 3216)]
    strategy = S04SupplyDemandZones({"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0})
    demand = _zone(1, 3207.0, 3196.0, birth=closes[0] - 48 * 60 * MINUTE)
    demand.extreme = 3290.0
    supply = _zone(-1, 3262.0, 3270.0, birth=closes[0] - 24 * 60 * MINUTE)
    strategy.book.entry = [demand, supply]
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 60), example_params(tick=0.01), atr=18.0, vr=1.0
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[2]
    assert event["s0"] == 3191.5
    assert _target(event, "T1") == 3262.0
    assert _target(event, "T2") == 3290.0
    assert demand.touches_before(closes[2]) == 0


def test_s04_does_not_take_a_second_touch_at_the_default_limit() -> None:
    closes = _closes(utc(2000, 1, 19, 12), 3, 60)
    rows: Sequence[Row] = [(3240, 3250, 3232, 3238), (3238, 3240, 3222, 3224), (3222, 3225, 3203, 3216)]
    strategy = S04SupplyDemandZones({"timeframe_minutes": 60, "q_min": 60.0, "touch_limit": 0})
    demand = _zone(1, 3207.0, 3196.0, birth=closes[0] - 48 * 60 * MINUTE)
    demand.touch_starts = [closes[0] - 10 * 60 * MINUTE]
    strategy.book.entry = [demand]
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 60), example_params(tick=0.01), atr=18.0, vr=1.0
    ).run()
    assert stream.setups == 0


def test_s05_makes_a_flip_from_a_broken_zone_and_trades_its_retest() -> None:
    closes = _closes(utc(2000, 1, 19, 10), 11, 60)
    rows: Sequence[Row] = [
        (66_240, 66_580, 66_230, 66_560),
        (66_560, 66_700, 66_540, 66_680),
        (66_680, 66_800, 66_660, 66_780),
        (66_780, 66_850, 66_760, 66_830),
        (66_830, 66_880, 66_800, 66_860),
        (66_860, 66_900, 66_820, 66_840),
        (66_840, 66_850, 66_700, 66_720),
        (66_720, 66_730, 66_600, 66_620),
        (66_620, 66_630, 66_500, 66_520),
        (66_520, 66_530, 66_470, 66_480),
        (66_480, 66_510, 66_300, 66_440),
    ]
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    zone = _zone(-1, 66_100.0, 66_350.0, birth=closes[0] - 24 * 60 * MINUTE)
    zone.departure = 0.5
    strategy.book.entry = [zone]
    srv = {closes[0]: 1.6}
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 60), example_params(tick=0.1), atr=280.0, vr=1.0, srv=srv
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[10]
    assert event["s0"] == 66_030.0
    assert _target(event, "T1") == 66_900.0
    assert _target(event, "T2") == 67_500.0
    assert strategy.flips[0].top == 66_350.0
    assert strategy.flips[0].bottom == 66_100.0


def test_s05_a_break_on_thin_volume_makes_no_flip() -> None:
    closes = _closes(utc(2000, 1, 19, 10), 2, 60)
    rows: Sequence[Row] = [(66_240, 66_580, 66_230, 66_560), (66_560, 66_700, 66_540, 66_680)]
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    strategy.book.entry = [_zone(-1, 66_100.0, 66_350.0, birth=closes[0] - 24 * 60 * MINUTE)]
    ExampleSimulator(
        strategy, _tape(rows, closes, 60), example_params(tick=0.1), atr=280.0, vr=1.0, srv=1.0
    ).run()
    assert strategy.flips == []


def test_s06_finds_a_sweep_and_its_reclaim_on_one_bar() -> None:
    prior = day_bar(utc(2000, 1, 19), 3352.0, 3300.0, 3320.0)
    closes = _closes(utc(2000, 1, 19, 19), 13, 15)
    # PSH is the highest high in the 12 bars before the sweep, and the document's is 3,325.
    rows: Sequence[Row] = (
        [(3315, 3325, 3312, 3318)] + [(3318, 3320, 3310, 3312)] * 11 + [(3306, 3309, 3292, 3302.5)]
    )
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": False})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 15),
        example_params(tick=0.01),
        atr=9.0,
        vr=1.0,
        srv=1.4,
        days_at_open=dict.fromkeys(closes, prior),
        fields={"atrd": 80.0, "day_open": 3340.0},
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[12]
    assert event["s0"] == pytest.approx(3286.64, abs=0.011)
    assert _target(event, "T1") == 3325.0
    assert _target(event, "T2") == 3352.0
    assert event["level"]["price"] == 3300.0
    assert event["level"]["sweep_low"] == 3292.0


def test_s06_a_pool_gives_at_most_one_trade_and_a_close_beyond_it_consumes_it() -> None:
    prior = day_bar(utc(2000, 1, 19), 3352.0, 3300.0, 3320.0)
    closes = _closes(utc(2000, 1, 19, 19), 3, 15)
    rows: Sequence[Row] = [(3315, 3325, 3312, 3318), (3318, 3319, 3290, 3295), (3295, 3312, 3294, 3310)]
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 0, "swing_pools": False})
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 15),
        example_params(tick=0.01),
        atr=9.0,
        vr=1.0,
        srv=1.4,
        days_at_open=dict.fromkeys(closes, prior),
        fields={"atrd": 80.0, "day_open": 3340.0},
    ).run()
    # N_r of 0: the close of the sweep bar stays below the pool, and with no later bars allowed, nothing is
    # reclaimed.
    assert stream.setups == 0
    assert strategy.snapshot()["pools"][f"D:{prior.end_us}:L"][1] == closes[1]


def test_s07_takes_a_pullback_to_the_line_and_refuses_with_no_excursion() -> None:
    closes = _closes(utc(2000, 1, 19, 12), 1, 60)
    rows: Sequence[Row] = [(64_050, 64_120, 63_760, 64_010)]
    trades = TradeTape(np.empty(0, dtype=np.int64), np.empty(0), np.empty(0))

    def build(*, excursion: bool) -> tuple[S07AnchoredVwapPullback, StreamResult]:
        strategy = S07AnchoredVwapPullback({"timeframe_minutes": 60, "major": [10, 5, 2.0], "max_touch": 2})
        confirmed = closes[0] - 10 * 60 * MINUTE
        swing = Swing(LOW, 63_000.0, -15, confirmed - 5 * 60 * MINUTE, confirmed)
        strategy.major.entries = [swing]
        anchor = Anchor(
            "L",
            63_000.0,
            swing.extreme_close_us,
            confirmed,
            n=12_000.0,
            pq=12_000.0 * 63_800.0,
            ppq=12_000.0 * (520.0**2 + 63_800.0**2),
            excursion=excursion,
        )
        anchor.values[-6] = 63_700.0
        strategy._anchors[confirmed * 2] = anchor
        stream = ExampleSimulator(
            strategy, _tape(rows, closes, 60), example_params(tick=0.1), atr=380.0, vr=1.0, trades=trades
        ).run()
        return strategy, stream

    _, stream = build(excursion=True)
    event = _setup(stream)
    assert event["s0"] == 63_445.0
    assert _target(event, "T1") == 64_580.0
    assert _target(event, "T2") == 65_360.0
    _, refused = build(excursion=False)
    assert refused.setups == 0


def test_s08_classifies_a_rejection_in_time_order() -> None:
    day = day_bar(utc(2000, 1, 19), 68_000.0, 66_000.0, 67_000.0)
    closes = _closes(utc(2000, 1, 19, 3), 4, 60)
    rows: Sequence[Row] = [
        (66_520, 66_530, 66_430, 66_440),
        (66_440, 66_450, 66_180, 66_300),
        (66_300, 66_580, 66_290, 66_560),
        (66_560, 66_640, 66_540, 66_610),
    ]

    class WithProfile(S08VolumeProfileValueArea):
        def _area_ending(self, market: Any, end_us: int) -> ValueArea | None:
            return ValueArea(poc=67_200.0, vah=67_900.0, val=66_500.0)

    strategy = WithProfile({"timeframe_minutes": 60, "profile_days": 1})
    trades = TradeTape(np.empty(0, dtype=np.int64), np.empty(0), np.empty(0))
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 60),
        example_params(tick=0.1),
        atr=350.0,
        vr=1.0,
        srv=1.0,
        days_at_open=dict.fromkeys(closes, day),
        trades=trades,
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[3]
    assert event["tag"] == "REJECTION"
    assert event["side"] == 1
    assert event["s0"] == 66_092.5
    assert _target(event, "T1") == 67_200.0
    assert _target(event, "T2") == 67_900.0


def test_s08_an_accepted_excursion_cannot_become_a_rejection() -> None:
    """Three closes out with volume is acceptance, and a later return gives no rejection trade."""
    day = day_bar(utc(2000, 1, 19), 68_000.0, 66_000.0, 67_000.0)
    closes = _closes(utc(2000, 1, 19, 3), 5, 60)
    rows: Sequence[Row] = [
        (66_520, 66_530, 66_430, 66_440),
        (66_440, 66_450, 66_180, 66_300),
        (66_300, 66_320, 66_250, 66_280),
        (66_280, 66_580, 66_270, 66_560),
        (66_560, 66_640, 66_540, 66_610),
    ]

    class WithProfile(S08VolumeProfileValueArea):
        def _area_ending(self, market: Any, end_us: int) -> ValueArea | None:
            return ValueArea(poc=67_200.0, vah=67_900.0, val=66_500.0)

    strategy = WithProfile({"timeframe_minutes": 60, "profile_days": 1})
    trades = TradeTape(np.empty(0, dtype=np.int64), np.empty(0), np.empty(0))
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 60),
        example_params(tick=0.1),
        atr=350.0,
        vr=1.0,
        srv=1.0,
        days_at_open=dict.fromkeys(closes, day),
        trades=trades,
    ).run()
    assert stream.setups == 0
    assert strategy.snapshot()["machines"]["1"][0] == "ACCEPTED"


def test_s09_builds_its_range_and_trades_the_first_break() -> None:
    closes = _closes(utc(2000, 1, 19, 5), 10, 60)
    rows: Sequence[Row] = [
        (67_200, 67_300, 67_100, 67_250),
        (67_250, 67_480, 67_200, 67_300),
        (67_300, 67_350, 66_980, 67_100),
        (67_100, 67_200, 67_050, 67_150),
        (67_150, 67_250, 67_100, 67_200),
        (67_200, 67_300, 67_150, 67_250),
        (67_250, 67_350, 67_200, 67_300),
        (67_300, 67_400, 67_250, 67_350),
        (67_350, 67_450, 67_300, 67_360),
        (67_360, 67_620, 67_330, 67_590),
    ]
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    # The profile from section 7.12, fitted before this quarter, and held for it.
    strategy._profile = SeasonalProfile(4, 16, utc(2000, 1, 1))
    strategy._fitted_for = utc(2000, 1, 1)
    stream = ExampleSimulator(
        strategy,
        _tape(rows, closes, 60),
        example_params(tick=0.1),
        atr=260.0,
        vr=1.0,
        srv=1.6,
        fields={"atrd": 1600.0},
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[9]
    assert event["s0"] == 67_165.0
    assert _target(event, "T1") == pytest.approx(68_121.2, abs=0.11)
    assert _target(event, "T2") == 68_652.5


def test_s09_with_no_profile_makes_no_setup_and_says_so() -> None:
    closes = _closes(utc(2000, 1, 19, 5), 2, 60)
    rows: Sequence[Row] = [(67_200, 67_300, 67_100, 67_250), (67_250, 67_480, 67_200, 67_300)]
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    stream = ExampleSimulator(strategy, _tape(rows, closes, 60), example_params(tick=0.1), atr=260.0).run()
    assert stream.setups == 0
    assert stream.reasons["SEASONAL_PROFILE_UNDEFINED"] == 2
    assert stream.reasons["PROFILE_FIT_MISSING_HOUR"] == 1


class _AlwaysCompressed(S10VolatilityCompression):
    """The rank is tested on its own. Here the example's compressed state is given, so the breakout rule is
    what runs.
    """

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self._pr_minimum = 0.0
        self._widths.push(0, 0.0)

    def _rank(self, bars: list[Bar]) -> bool:
        return True


def _s10_rows() -> list[Row]:
    quiet: Sequence[Row] = [(3135, 3180, 3090, 3135)] + [(3135, 3150, 3120, 3135)] * 11
    return [(3135, 3150, 3120, 3135), *quiet, (3172, 3204, 3168, 3198)]


def test_s10_takes_the_first_close_out_of_the_box() -> None:
    rows = _s10_rows()
    closes = _closes(utc(2000, 1, 17, 8), len(rows), 240)
    strategy = _AlwaysCompressed({"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12})
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 240), example_params(tick=0.01), atr=28.0, srv=1.4
    ).run()
    event = _setup(stream)
    assert event["computed_at_us"] == closes[-1]
    assert event["s0"] == 3128.0
    assert _target(event, "T1") == 3338.0
    assert _target(event, "T2") is None
    assert event["level"]["box_height"] == 90.0


def test_s10_a_breakout_with_undefined_rank_fails_and_says_why() -> None:
    rows = _s10_rows()
    closes = _closes(utc(2000, 1, 17, 8), len(rows), 240)
    strategy = S10VolatilityCompression({"timeframe_minutes": 240, "pr_max": 0.10, "box_bars": 12})
    stream = ExampleSimulator(
        strategy, _tape(rows, closes, 240), example_params(tick=0.01), atr=28.0, srv=1.4
    ).run()
    assert stream.setups == 0
    assert stream.reasons["PR_UNDEFINED"] == len(rows)
