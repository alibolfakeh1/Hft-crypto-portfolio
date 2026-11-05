"""Registers and estimated objects, by hand: swings, zones, the value area and S09's seasonal profile."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from engine_helpers import DAY, MINUTE, utc
from hft_crypto.engine.market import TradeSlice
from hft_crypto.engine.tape import Bar
from hft_crypto.strategies.registers import HIGH, LOW, Swing, SwingList
from hft_crypto.strategies.s08_volume_profile_value_area import value_area
from hft_crypto.strategies.s09_session_range_breakout import (
    HOUR,
    S09SessionRangeBreakout,
    calendar_date_at_or_before,
    fit_profile,
)
from hft_crypto.strategies.zones import ZoneBook

START = utc(2000, 1, 19)


def _bar(index: int, o: float, h: float, l: float, c: float, *, atr: float | None = 20.0) -> Bar:  # noqa: E741
    return Bar(
        index=index,
        minutes=60,
        open_us=START + (index - 1) * HOUR,
        close_us=START + index * HOUR,
        o=o,
        h=h,
        l=l,
        c=c,
        v=1.0,
        has_price=True,
        complete=True,
        pending_tail=False,
        gap=False,
        late_gap=False,
        tr=h - l,
        atr=atr,
        atr_last=atr,
        vr=1.0,
        srv=1.0,
        clv=(c - l) / (h - l) if h != l else 0.5,
        atrd=None,
        day=None,
        week=None,
        day_at_close=None,
        week_at_close=None,
        day_open=None,
    )


def _flat(index: int, price: float) -> Bar:
    return _bar(index, price, price + 1.0, price - 1.0, price)


# ---- swings, C4
# ---------------------------------------------------------------------------------------------------


def _feed(swings: SwingList, bars: list[Bar]) -> list[list[tuple[str, float]]]:
    seen: list[list[tuple[str, float]]] = []
    for end in range(1, len(bars) + 1):
        seen.append([(item.kind, item.price) for item in swings.update(bars[:end])])
    return seen


def test_a_swing_is_known_at_its_last_right_bar_and_never_at_its_extreme() -> None:
    """Lf 2, Rt 2. The high at bar 2 confirms at bar 4, and nothing is known at bars 2 or 3."""
    bars = [_flat(0, 100), _flat(1, 100), _flat(2, 110), _flat(3, 100), _flat(4, 100), _flat(5, 100)]
    swings = SwingList(2, 2, 0.1)
    seen = _feed(swings, bars)
    assert seen[2] == [] and seen[3] == []
    assert seen[4] == [(HIGH, 111.0)]
    entry = swings.entries[0]
    assert entry.valid_from == bars[4].close_us
    assert entry.extreme_close_us == bars[2].close_us


def test_the_left_side_is_strict_and_the_right_side_may_equal() -> None:
    """C4: H_i > left, and H_i >= right."""
    equal_left = [_flat(0, 110), _flat(1, 100), _flat(2, 110), _flat(3, 100), _flat(4, 100)]
    assert _feed(SwingList(2, 2, 0.1), equal_left)[4] == []
    equal_right = [_flat(0, 100), _flat(1, 100), _flat(2, 110), _flat(3, 110), _flat(4, 100)]
    assert _feed(SwingList(2, 2, 0.1), equal_right)[4] == [(HIGH, 111.0)]


def test_a_more_extreme_swing_of_the_same_kind_replaces_the_last_from_its_own_time() -> None:
    """The low between them fails the amplitude test at 2 * ATR of 20, so the last entry stays a high."""
    swings = SwingList(1, 1, 2.0)
    bars = [_flat(0, 100), _flat(1, 110), _flat(2, 105), _flat(3, 120), _flat(4, 100)]
    _feed(swings, bars)
    first, second = swings.entries[0], swings.entries[1]
    assert (first.price, second.price) == (111.0, 121.0)
    assert first.valid_to == second.valid_from == bars[4].close_us
    # The replaced one stays in the list. A read before its valid_to still sees it.
    assert [item.price for item in swings.visible(HIGH)] == [121.0]


def test_a_less_extreme_swing_of_the_same_kind_is_ignored() -> None:
    swings = SwingList(1, 1, 2.0)
    bars = [_flat(0, 100), _flat(1, 120), _flat(2, 105), _flat(3, 110), _flat(4, 100)]
    _feed(swings, bars)
    assert [item.price for item in swings.entries] == [121.0]


def test_the_amplitude_test_uses_atr_at_the_confirmation_bar() -> None:
    """A low 10 from the last high, against 1.0 * ATR of 20, is ignored. Against ATR of 5 it is added."""
    bars = [_flat(0, 100), _flat(1, 110), _flat(2, 104), _flat(3, 103), _flat(4, 105), _flat(5, 106)]
    assert all(item.kind == HIGH for item in _wide(bars, 20.0))
    assert [item.kind for item in _wide(bars, 3.0)][:2] == [HIGH, LOW]


def _wide(bars: list[Bar], atr: float) -> list[Swing]:
    swings = SwingList(1, 1, 1.0)
    _feed(swings, [replace(bar, atr=atr, atr_last=atr) for bar in bars])
    return list(swings.entries)


def test_before_the_first_atr_seed_a_swing_is_ignored() -> None:
    swings = SwingList(1, 1, 1.0)
    bars = [
        replace(_flat(index, price), atr=None, atr_last=None)
        for index, price in enumerate((100, 110, 100, 100))
    ]
    _feed(swings, bars)
    assert swings.entries == []


def test_a_missing_bar_in_the_window_means_no_swing() -> None:
    swings = SwingList(1, 1, 0.1)
    bars = [_flat(0, 100), _flat(1, 110), replace(_flat(2, 100), gap=True)]
    _feed(swings, bars)
    assert swings.entries == []


def test_a_bar_that_is_both_takes_the_high_first_on_an_up_close_and_the_low_first_otherwise() -> None:
    up = [_flat(0, 100), _bar(1, 100, 120, 80, 110), _flat(2, 100)]
    swings = SwingList(1, 1, 0.1)
    _feed(swings, up)
    assert [item.kind for item in swings.entries] == [HIGH, LOW]
    down = [_flat(0, 100), _bar(1, 100, 120, 80, 90), _flat(2, 100)]
    swings = SwingList(1, 1, 0.1)
    _feed(swings, down)
    assert [item.kind for item in swings.entries] == [LOW, HIGH]


# ---- zones, S04 section 3 and its worked example
# -------------------------------------------------------------------

_ARRIVAL = [(3250, 3252, 3238, 3240), (3240, 3242, 3225, 3228), (3228, 3230, 3208, 3210)]
_BASE = [(3205, 3212, 3198, 3204), (3204, 3209, 3196, 3207), (3207, 3213, 3201, 3205)]
_DEPARTURE = [(3205, 3232, 3203, 3230), (3230, 3256, 3228, 3252)]


def _zone_bars(*extra: tuple[float, float, float, float]) -> list[Bar]:
    rows = [*_ARRIVAL, *_BASE, *_DEPARTURE, *extra]
    return [_bar(index, *row) for index, row in enumerate(rows)]


def _run_book(bars: list[Bar]) -> ZoneBook:
    book = ZoneBook(60)
    for end in range(1, len(bars) + 1):
        book.update(bars[:end])
    return book


def test_the_worked_example_zone_and_its_score() -> None:
    """S04 7.12. prox 3,207, dist 3,196, D 0.75, T 0.633, F 1, so Q = 76.5."""
    book = _run_book(_zone_bars())
    demand = [zone for zone in book.entry if zone.side == 1]
    assert len(demand) == 1
    zone = demand[0]
    assert (zone.prox, zone.dist) == (3207.0, 3196.0)
    assert zone.mid == 3201.5
    assert zone.birth_index == 7
    assert zone.departure == pytest.approx(0.75)
    assert zone.tightness == pytest.approx(1.0 - 11.0 / 30.0)
    assert book.quality(zone, _zone_bars()[-1]) == pytest.approx(76.5, abs=0.01)


def test_a_zone_does_not_exist_before_its_departure_is_complete() -> None:
    """At the first departure bar the net move is 23, below the required 30, so nothing is born yet."""
    book = _run_book(_zone_bars()[:-1])
    assert [zone for zone in book.entry if zone.side == 1] == []


def test_touches_count_from_the_first_bar_and_only_before_the_bar_being_read() -> None:
    """S04 section 3. A touch that begins at k is not counted at k, and is counted from k + 1."""
    bars = _zone_bars((3252, 3255, 3250, 3253), (3253, 3254, 3205, 3220), (3220, 3225, 3204, 3222))
    book = _run_book(bars)
    zone = next(zone for zone in book.entry if zone.side == 1)
    assert zone.touch_starts == [bars[9].close_us]
    assert zone.touches_before(bars[9].close_us) == 0
    assert zone.touches_before(bars[10].close_us) == 1


def test_freshness_decays_with_age_and_with_touches() -> None:
    """F = 0.5 ^ touches * (1 - age / MaxAge), with MaxAge of 14 days of 1h bars, so 336."""
    bars = _zone_bars()
    book = _run_book(bars)
    zone = next(zone for zone in book.entry if zone.side == 1)
    later = replace(bars[-1], index=zone.birth_index + 48, close_us=bars[-1].close_us + 48 * HOUR)
    expected = 100.0 * (0.5 * 0.75 + 0.3 * zone.tightness + 0.2 * (1.0 - 48.0 / 336.0))
    assert book.quality(zone, later) == pytest.approx(expected)
    assert expected == pytest.approx(73.6, abs=0.1)


def test_a_zone_breaks_at_a_close_beyond_it_and_stays_in_the_register() -> None:
    bars = _zone_bars((3252, 3255, 3250, 3253), (3253, 3254, 3180, 3185))
    book = _run_book(bars)
    zone = next(zone for zone in book.entry if zone.side == 1)
    assert zone.broken_at == bars[-1].close_us
    assert zone.active is False
    assert zone in book.entry


def test_a_stack_zone_needs_no_arrival_and_an_entry_zone_does() -> None:
    no_arrival = [_bar(index, *row) for index, row in enumerate((*_BASE, *_DEPARTURE))]
    book = _run_book(no_arrival)
    assert [zone for zone in book.entry if zone.side == 1] == []
    assert len([zone for zone in book.stack if zone.side == 1]) == 1


def test_a_stronger_new_zone_supersedes_an_older_one_only_from_its_own_birth() -> None:
    """S04's overlap rule. The older zone stays usable for every read before that moment."""
    book = _run_book(_zone_bars())
    old = next(zone for zone in book.entry if zone.side == 1)
    before = old.superseded_at
    new = replace(
        old, id="new", departure=1.0, tightness=1.0, birth_us=old.birth_us + HOUR, superseded_at=None
    )
    book._register_entry(new, replace(_zone_bars()[-1], index=old.birth_index + 1))
    assert before is None
    assert old.superseded_at == new.birth_us
    assert new.superseded_at is None


def test_an_older_zone_wins_a_tie() -> None:
    book = _run_book(_zone_bars())
    old = next(zone for zone in book.entry if zone.side == 1)
    new = replace(old, id="new", birth_us=old.birth_us, superseded_at=None)
    book._register_entry(new, _zone_bars()[-1])
    assert old.superseded_at is None
    assert new.superseded_at == new.birth_us


# ---- the value area, S08 section 3
# -----------------------------------------------------------------------------------


def _slice(rows: list[tuple[float, float]]) -> TradeSlice:
    return TradeSlice(np.array([row[0] for row in rows]), np.array([row[1] for row in rows]))


def test_a_value_area_by_hand() -> None:
    """A tick of 1 sets the bin width. Bins 9 to 13 hold 10, 40, 30, 15, 5, so 100 in all.

    The POC is the bin with 40. Next: above 30, below 10, so add 30, to 70, which is 70 percent. Done.
    """
    rows = [(10.5, 40.0), (9.5, 10.0), (11.5, 30.0), (12.5, 15.0), (13.5, 5.0)]
    area = value_area(_slice(rows), 1.0)
    assert area is not None
    assert (area.poc, area.val, area.vah, area.vaw) == (10.5, 10.0, 12.0, 2.0)


def test_the_value_area_adds_both_sides_on_a_tie_and_the_other_side_when_one_runs_out() -> None:
    width = 1.0
    rows = [(0.5, 10.0), (1.5, 50.0), (2.5, 10.0), (3.5, 30.0)]
    # A tick above the share rule, so the bin width is exactly 1. POC is bin 1. Below 10, above 10: a tie
    # adds both, to 70 of 100, which is exactly 70 percent.
    area = value_area(_slice(rows), width)
    assert area is not None
    assert (area.val, area.vah) == (0.0, 3.0)
    one_side = [(0.5, 90.0), (1.5, 10.0)]
    area = value_area(_slice(one_side), width)
    assert area is not None
    assert (area.val, area.vah) == (0.0, 1.0)


def test_a_tie_for_the_poc_goes_to_the_bin_nearest_the_middle_of_the_range() -> None:
    rows = [(0.5, 10.0), (2.5, 1.0), (4.5, 10.0), (5.5, 10.0)]
    area = value_area(_slice(rows), 1.0)
    assert area is not None
    # The range is 0.5 to 5.5, so the middle is 3. Bins at 0.5, 4.5 and 5.5 tie, and 4.5 is nearest.
    assert area.poc == 4.5


def test_no_trades_means_no_value_area() -> None:
    assert value_area(_slice([]), 1.0) is None


# ---- S09's seasonal profile, section 3 and C12
# ---------------------------------------------------------------------


DATE = utc(2000, 4, 1)


def _samples(volume_of_hour: dict[int, float] | None = None) -> dict[int, float]:
    rows: dict[int, float] = {}
    open_us = DATE - 90 * DAY
    while open_us < DATE:
        hour = (open_us % DAY) // HOUR
        rows[open_us] = (volume_of_hour or {}).get(hour, 100.0)
        open_us += HOUR
    return rows


def test_the_calendar_is_the_quarter_dates_of_c12() -> None:
    assert calendar_date_at_or_before(utc(2000, 3, 31, 23)) == utc(2000, 1, 1)
    assert calendar_date_at_or_before(utc(2000, 4, 1)) == utc(2000, 4, 1)
    assert calendar_date_at_or_before(utc(2000, 12, 31, 23)) == utc(2000, 10, 1)
    assert calendar_date_at_or_before(utc(2001, 1, 1)) == utc(2001, 1, 1)


def test_the_profile_finds_the_quietest_window_and_the_busiest_hour_after_it() -> None:
    """Hours 4 to 11 are quietest, so h_s is 4 and h_end is 12. In the 8 hours from it, hour 16 is busiest."""
    volumes = dict.fromkeys(range(4, 12), 10.0) | {16: 1000.0}
    profile, why = fit_profile(_samples(volumes), fitted_at_us=DATE, window_hours=8)
    assert why is None
    assert profile is not None
    assert (profile.window_start_hour, profile.peak_hour) == (4, 16)


def test_the_window_wraps_at_midnight() -> None:
    volumes = dict.fromkeys((22, 23, 0, 1, 2, 3), 10.0)
    profile, _ = fit_profile(_samples(volumes), fitted_at_us=DATE, window_hours=6)
    assert profile is not None
    assert profile.window_start_hour == 22


def test_a_weekend_bar_does_not_enter_the_profile() -> None:
    """Weekend hours can be empty or absent, and change nothing. Hour 3's weekend bars are huge here."""
    rows = _samples(dict.fromkeys(range(4, 12), 10.0) | {16: 1000.0})
    plain, _ = fit_profile(rows, fitted_at_us=DATE, window_hours=8)
    weekend = {
        key: 1e9 if (key % DAY) // HOUR == 5 and ((key - 4 * DAY) // DAY) % 7 >= 5 else value
        for key, value in rows.items()
    }
    changed, _ = fit_profile(weekend, fitted_at_us=DATE, window_hours=8)
    assert plain == changed
    without_weekends = {key: value for key, value in rows.items() if ((key - 4 * DAY) // DAY) % 7 < 5}
    absent, why = fit_profile(without_weekends, fitted_at_us=DATE, window_hours=8)
    assert why is None
    assert absent == plain


def test_a_missing_weekday_hour_means_no_profile_and_says_why() -> None:
    """Fail closed, under C2. The document does not yet say what `m_h` does here, and nothing is invented."""
    rows = _samples()
    first_monday = next(key for key in sorted(rows) if ((key - 4 * DAY) // DAY) % 7 == 0)
    del rows[first_monday + 3 * HOUR]
    profile, why = fit_profile(rows, fitted_at_us=DATE, window_hours=8)
    assert profile is None
    assert why == "MISSING_HOUR"


def test_a_zero_volume_weekday_hour_means_no_profile_and_says_why() -> None:
    """`m_h` takes a log of volume, so an hour with none has no value. Fail closed, for the same reason."""
    rows = _samples()
    first_monday = next(key for key in sorted(rows) if ((key - 4 * DAY) // DAY) % 7 == 0)
    rows[first_monday] = 0.0
    profile, why = fit_profile(rows, fitted_at_us=DATE, window_hours=8)
    assert profile is None
    assert why == "ZERO_VOLUME_HOUR"


def test_a_bar_before_the_ninety_days_or_at_the_date_itself_is_not_in_the_window() -> None:
    rows = _samples(dict.fromkeys(range(4, 12), 10.0))
    plain, _ = fit_profile(rows, fitted_at_us=DATE, window_hours=8)
    outside = {**rows, DATE - 90 * DAY - HOUR: 1e9, DATE: 1e-9, DATE + 5 * HOUR: 1e-9}
    changed, _ = fit_profile(outside, fitted_at_us=DATE, window_hours=8)
    assert plain == changed


def test_too_little_history_gives_no_profile_at_the_first_date_and_logs_it() -> None:
    """2000-04-01's window starts on 2 January, a Sunday, so its first bars that count open on 3 January."""
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    assert strategy.h_max_us == 11 * HOUR
    assert MINUTE < HOUR
    first_day = utc(2000, 1, 2)
    assert first_day == DATE - 90 * DAY
    samples = _samples()
    from_monday = {key: value for key, value in samples.items() if key >= first_day + DAY}
    assert fit_profile(from_monday, fitted_at_us=DATE, window_hours=8)[1] is None
    from_tuesday = {key: value for key, value in samples.items() if key >= first_day + 2 * DAY}
    assert fit_profile(from_tuesday, fitted_at_us=DATE, window_hours=8)[1] == "MISSING_HOUR"
    assert fit_profile(samples, fitted_at_us=DATE, window_hours=8)[1] is None
