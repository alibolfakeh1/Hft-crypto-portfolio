"""EN-05, EN-07, sections 18.2 and 18.3 of the recheck, `V0S` under C13, and the rulings on bars with no
trade.

Each case is worked by hand in its docstring. A bar with no trade is a `T_d` bar whose minutes are missing or
proved empty: it counts in `n`, and it has no close (C2, C3).
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import polars as pl
import pytest

from engine_helpers import DELAY_US, GENERATED_CONFIG, REPO_ROOT, costs, generated_trades, sim_params, utc
from hft_crypto.config import ConfigError
from hft_crypto.engine.config import DateRange, parse_engine_config
from hft_crypto.engine.fold_plan import D38_SENTENCE, READ_DAYS, check_range, span_labels
from hft_crypto.engine.indicators import clv
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.simulator import Simulator, StreamResult
from hft_crypto.engine.tape import Bar, MinuteTape, PeriodBar
from hft_crypto.strategies import build_strategy
from hft_crypto.strategies.base import (
    ATRD_RESTART_CLOSES,
    REST,
    Management,
    PositionView,
    Proposal,
    Strategy,
    TargetPlan,
)
from hft_crypto.strategies.levels import Level
from hft_crypto.strategies.s01_floor_pivot_rejection import S01FloorPivotRejection, _LevelState
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip, _Flip
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import _Memo as S06Memo
from hft_crypto.strategies.s07_anchored_vwap_pullback import Anchor, S07AnchoredVwapPullback
from hft_crypto.strategies.s07_anchored_vwap_pullback import _Memo as S07Memo
from hft_crypto.strategies.s09_session_range_breakout import S09SessionRangeBreakout
from hft_crypto.strategies.s09_session_range_breakout import _Memo as S09Memo
from hft_crypto.strategies.v0s import V0SControl

START = utc(2000, 3, 6)
MINUTE = 60_000_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR
UTC_US = pl.Datetime("us", "UTC")
PLAN = REPO_ROOT / "docs" / "decisions" / "FOLD_PLAN_2026-11-05.md"


def _bar(
    index: int,
    c: float,
    *,
    priced: bool = True,
    h: float | None = None,
    l: float | None = None,  # noqa: E741
    atr: float | None = 4.0,
    minutes: int = 60,
    close_us: int | None = None,
) -> Bar:
    """A bar with no trade carries the last close as its four prices, and has no price of its own."""
    high = c if h is None else h
    low = c if l is None else l
    return Bar(
        index=index,
        minutes=minutes,
        open_us=START + index * minutes * MINUTE,
        close_us=START + (index + 1) * minutes * MINUTE if close_us is None else close_us,
        o=c,
        h=high,
        l=low,
        c=c,
        v=1.0 if priced else 0.0,
        has_price=priced,
        complete=priced,
        pending_tail=False,
        gap=not priced,
        late_gap=False,
        tr=None,
        atr=atr if priced else None,
        atr_last=atr,
        vr=1.0,
        srv=1.0,
        clv=clv(high, low, c),
        atrd=None,
        day=None,
        week=None,
        day_at_close=None,
        week_at_close=None,
        day_open=None,
    )


def _position(n: int, memo: Any, *, fill: float = 100.0, r: float = 10.0) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            side=1,
            n=n,
            memo=memo,
            fill_side=fill,
            fill=fill,
            r=r,
            highest=fill,
            filled=lambda _name: False,
            be_plus=fill,
            stop=fill - r,
            fill_us=START,
            target=lambda _name: None,
        ),
    )


def _notes(strategy: Strategy, memo: Any, bars: list[Bar], **position: Any) -> list[str | None]:
    found = []
    for bar in bars:
        market = cast(Any, SimpleNamespace(bar=bar, bars=[bar]))
        decision = strategy.manage(market, _position(bar.index, memo, **position))
        found.append(decision.exit_note or None)
    return found


# ---- the rulings on a bar with no trade --------------------------------------------------------------------


def test_s06_linger_counts_only_closes_that_exist() -> None:
    """Level 100 and ATR 4, so a close within 1.0 of it lingers. Bars 1 to 3 linger, bar 4 has no trade and
    carries 100.2, and bars 5 and 6 close at 103. Counting the carried close made four, and an exit at bar 6.
    There are three closes that linger, so it is no exit, and the one check is spent.
    """
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": False})
    memo = S06Memo("pool", 100.0)
    bars = [
        _bar(1, 100.5, minutes=15),
        _bar(2, 100.3, minutes=15),
        _bar(3, 100.2, minutes=15),
        _bar(4, 100.2, priced=False, minutes=15),
        _bar(5, 103.0, minutes=15),
        _bar(6, 103.0, minutes=15),
        _bar(7, 100.1, minutes=15),
    ]
    assert _notes(strategy, memo, bars) == [None] * 7


def test_s06_linger_with_no_trade_at_n_6_falls_at_the_next_close() -> None:
    """Closes 100.5, 100.4, 100.3, 103 and 103, then bar 6 has no trade, then 100.2 at bar 7: four of the six
    closes that exist linger, so it exits at bar 7, once.
    """
    strategy = S06LiquiditySweepReclaim({"timeframe_minutes": 15, "n_r": 2, "swing_pools": False})
    memo = S06Memo("pool", 100.0)
    bars = [
        _bar(1, 100.5, minutes=15),
        _bar(2, 100.4, minutes=15),
        _bar(3, 100.3, minutes=15),
        _bar(4, 103.0, minutes=15),
        _bar(5, 103.0, minutes=15),
        _bar(6, 103.0, priced=False, minutes=15),
        _bar(7, 100.2, minutes=15),
    ]
    assert _notes(strategy, memo, bars) == [None, None, None, None, None, None, "LINGER"]


def _s09_memo() -> S09Memo:
    return S09Memo(range_high=95.0, range_width=10.0, peak_us=START + 100 * DAY, flat_us=START + 100 * DAY)


def test_s09_the_n_4_check_reads_no_carried_close() -> None:
    """Fill 100 and 1R 10, so the check wants a close of 105. Bar 4 has no trade and carries 101, which used
    to exit on a stale price. It falls at bar 5, which closes 106, and passes.
    """
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    bars = [_bar(1, 110.0), _bar(2, 110.0), _bar(3, 110.0), _bar(4, 101.0, priced=False), _bar(5, 106.0)]
    assert _notes(strategy, _s09_memo(), bars) == [None] * 5


def test_s09_the_n_4_check_falls_once_at_the_next_close_that_has_one() -> None:
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    bars = [_bar(1, 110.0), _bar(2, 110.0), _bar(3, 110.0), _bar(4, 110.0, priced=False), _bar(5, 101.0)]
    assert _notes(strategy, _s09_memo(), bars) == [None, None, None, None, "NO_FOLLOW_THROUGH"]
    passed = [_bar(1, 110.0), _bar(2, 110.0), _bar(3, 110.0), _bar(4, 106.0), _bar(5, 101.0)]
    assert _notes(strategy, _s09_memo(), passed) == [None] * 5


def _s07() -> tuple[S07AnchoredVwapPullback, S07Memo]:
    strategy = S07AnchoredVwapPullback({"timeframe_minutes": 60, "major": [10, 5, 2.0], "max_touch": 2})
    anchor = Anchor("L", 90.0, START, START, n=1.0, pq=100.0, ppq=10_000.0)
    return strategy, S07Memo(anchor)


def test_s07_a_bar_with_no_trade_is_not_the_second_close_below_a0() -> None:
    """`A0` at 100. A close at 99, then a bar with no trade carrying 99. That was two closes below, and an
    exit. It is one, and a later close at 101 starts again.
    """
    strategy, memo = _s07()
    bars = [_bar(1, 99.0), _bar(2, 99.0, priced=False), _bar(3, 101.0), _bar(4, 99.0)]
    assert _notes(strategy, memo, bars) == [None, None, None, None]


def test_s07_nor_does_it_break_a_run_of_two() -> None:
    strategy, memo = _s07()
    bars = [_bar(1, 99.0), _bar(2, 101.0, priced=False), _bar(3, 98.0)]
    assert _notes(strategy, memo, bars) == [None, None, "TWO_CLOSES_BELOW_A0"]


def test_s05_a_bar_with_no_trade_cannot_open_the_retest_but_still_counts() -> None:
    """Top 1000 and travel complete. A bar with no trade carries 998, at or below the top. It touches
    nothing, so the retest waits for bar 7, which has a trade at 997. Window and death counts still
    include bar 6.
    """
    strategy = S05ZonePolarityFlip({"timeframe_minutes": 60, "rw": 48})
    flip = _Flip("flip", 1, 1000.0, 980.0, 990.0, 1030.0, 0, travelled=True)
    strategy.flips.append(flip)
    strategy._advance_flips(_bar(6, 998.0, priced=False))
    # Compared as a pair, so that mypy does not narrow the attributes to None for the lines below.
    assert (flip.retest_start, flip.dead_at) == (None, None)
    strategy._advance_flips(_bar(7, 1003.0, h=1004.0, l=997.0))
    assert flip.retest_start == 7
    assert flip.retest_low == 997.0


# ---- V0S, C13 ----------------------------------------------------------------------------------------------


class _Enter(Strategy):
    """One long setup at a stated close, S0 90 at a price of 100. Its own exits are never called under V0S."""

    id = "TEST"
    h_max_hours: ClassVar[dict[int, float]] = {60: 1000.0}
    v0s_m = 2.0
    v0s_hold_bars: ClassVar[dict[int, int]] = {60: 3}

    def __init__(self, enter_at: int) -> None:
        super().__init__({"timeframe_minutes": 60})
        self.enter_at = enter_at
        self.sent = 0

    def on_close(self, market: MarketView) -> list[Proposal]:
        if market.now_us != self.enter_at:
            return []
        return [Proposal(1, 90.0, (TargetPlan("T1", 105.0, 0.5), TargetPlan("T2", 130.0, REST)), {}, 4, None)]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        raise AssertionError("V0S must never call the strategy's own exit rules")

    def notify_sent(self, proposal: Proposal) -> None:
        self.sent += 1


def _rows(opens: list[int], prices: dict[int, float] | None = None) -> pl.DataFrame:
    values = [(prices or {}).get(item, 100.0) for item in opens]
    size = len(opens)
    return pl.DataFrame(
        {
            "open_time": pl.Series(opens, dtype=pl.Int64).cast(UTC_US),
            "open": values,
            "high": [value + 0.5 for value in values],
            "low": [value - 0.5 for value in values],
            "close": values,
            "volume": [10.0] * size,
            "trade_count": [5] * size,
            "gap": [False] * size,
            "knowable_time": pl.Series([item + MINUTE for item in opens], dtype=pl.Int64).cast(UTC_US),
        }
    )


class _FlatAtr(Simulator):
    def _bars(self, minutes: int) -> list[Bar]:
        return [replace(bar, atr=2.0, atr_last=2.0, complete=True) for bar in self.tape.frame(minutes)]


def _v0s(frame: pl.DataFrame, inner: Strategy) -> StreamResult:
    tape = MinuteTape.from_frame(frame, symbol="S", delay_us=DELAY_US)
    params = sim_params(
        risk_budget=100.0, capital=1_000_000.0, leverage_cap=100.0, cost=costs(rt_bps=0.0, slip_bps=0.0)
    )
    return _FlatAtr(V0SControl(inner), tape, params).run()


def test_v0s_one_fixed_target_at_fill_plus_m_r_and_no_update_of_any_kind() -> None:
    """Fill 100 and S0 90, so R is 10 and the target is 100 + 2.0 * 10 = 120, set from the fill. The setup's
    own two targets are gone. The price reaches 121 at minute 100, so it all leaves at 120.
    """
    opens = [START + index * MINUTE for index in range(6 * 60)]
    frame = _rows(opens, {item: 121.0 for item in opens if item >= START + 100 * MINUTE})
    trade = _v0s(frame, _Enter(START + HOUR)).trades[0]
    assert trade.fill == 100.0
    assert [(leg.reason, leg.price, leg.qty) for leg in trade.legs] == [("TARGET_T1", 120.0, trade.q0)]
    assert trade.stop_path == ()
    assert [(row["name"], row["new"]) for row in trade.target_path] == [("T1", 120.0)]


def test_v0s_holds_h_bars_and_closes_at_the_next_open() -> None:
    """Entry decided at hour 1 and filled in the minute after. `H` is 3, so the close of bar n = 3, at hour 4,
    ends the hold, and it leaves at the first minute that opens at or after hour 4 plus the delay.
    """
    opens = [START + index * MINUTE for index in range(8 * 60)]
    trade = _v0s(_rows(opens), _Enter(START + HOUR)).trades[0]
    assert trade.exit_reason == "TIME_STOP"
    assert trade.legs[-1].event_us == START + 4 * HOUR + 2 * MINUTE


def test_v0s_counts_a_bar_with_no_trade_in_h_and_reads_no_close() -> None:
    """Hour 3 has no rows at all. It still counts, so the hold ends at the close of hour 4, as it would with
    rows, and the exit fills at the first minute with a price after that. The headline stops it at the hole,
    under C2, so the hold shows in the path as recorded.
    """
    opens = [START + index * MINUTE for index in range(8 * 60) if not 3 * 60 <= index < 4 * 60]
    trade = _v0s(_rows(opens), _Enter(START + HOUR)).trades[0]
    assert trade.as_recorded_legs[-1].reason == "TIME_STOP"
    assert trade.as_recorded_legs[-1].event_us == START + 4 * HOUR + 2 * MINUTE


def test_v0s_sends_its_own_setups_so_a_one_trade_rule_counts_its_own() -> None:
    inner = _Enter(START + HOUR)
    _v0s(_rows([START + index * MINUTE for index in range(4 * 60)]), inner)
    assert inner.sent == 1


def test_v0s_on_s09_holds_to_the_hard_flat_of_the_schedule_it_entered_with() -> None:
    strategy = S09SessionRangeBreakout({"timeframe_minutes": 60, "window_hours": 8, "srv_min": 1.0})
    memo = S09Memo(range_high=95.0, range_width=10.0, peak_us=START, flat_us=START + 10 * HOUR)
    before = cast(Any, SimpleNamespace(bar=_bar(8, 100.0)))
    at_flat = cast(Any, SimpleNamespace(bar=_bar(9, 100.0, priced=False)))
    assert strategy.v0s_time_up(before, _position(8, memo)) is False
    assert strategy.v0s_time_up(at_flat, _position(9, memo)) is True


def test_v0s_takes_the_same_setups_as_v0_where_no_one_trade_rule_applies() -> None:
    start = utc(2000, 1, 3)
    from engine_helpers import tape_and_trades

    trades = generated_trades(seed=7, start_us=start, days=120)
    tape, tape_trades = tape_and_trades(trades, start_us=start, through_us=start + 120 * DAY)
    params = {"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2}
    real = Simulator(build_strategy("S03", params), tape, sim_params(), trades=tape_trades).run()
    control = Simulator(
        V0SControl(build_strategy("S03", params)), tape, sim_params(), trades=tape_trades
    ).run()

    def created(stream: StreamResult) -> list[tuple[int, int]]:
        return [
            (event["computed_at_us"], event["side"])
            for event in stream.events
            if event["type"] == "SETUP_CREATED"
        ]

    assert created(real)
    assert created(real) == created(control)
    assert all(trade.stop_path == () for trade in control.trades)


# ---- EN-07 -------------------------------------------------------------------------------------------------


def _market_raw() -> dict[str, Any]:
    with (GENERATED_CONFIG.parent / "engine.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_en07_the_market_configuration_states_d39() -> None:
    risk = _market_raw()["risk"]
    assert risk["state"] == "declared"
    assert "D-39" in risk["basis"]
    assert "owner decides" not in risk["basis"].lower()
    assert "placeholder" not in risk["basis"].lower()
    assert (risk["leverage_cap"], risk["gross_cap"]) == (2.0, 3.0)
    assert {value for row in risk["per_trade_pct"].values() for value in row.values()} == {0.25}


def test_en07_a_market_run_with_a_portfolio_line_off_the_default_is_refused() -> None:
    raw = _market_raw()
    raw["strategies"]["S04"]["portfolio_line"] = {**raw["strategies"]["S04"]["default_line"], "q_min": 45.0}
    with pytest.raises(ConfigError, match="D-35"):
        parse_engine_config(raw)


def test_en07_a_generated_run_may_name_another_portfolio_line() -> None:
    with GENERATED_CONFIG.open("rb") as handle:
        raw = tomllib.load(handle)
    raw["strategies"]["S04"]["portfolio_line"] = {**raw["strategies"]["S04"]["default_line"], "q_min": 45.0}
    assert parse_engine_config(raw).strategies["S04"].portfolio_line["q_min"] == 45.0


# ---- EN-05 -------------------------------------------------------------------------------------------------


def _plan_section_4() -> str:
    text = PLAN.read_text(encoding="utf-8")
    return text[text.index("## 4. Dates already read") : text.index("## 5. ")]


def _days_in_rows(section: str) -> set[dt.date]:
    """Each date the section's read rows name, with a short `MM-DD` taking the year before it."""
    found: set[dt.date] = set()
    for row in section.splitlines():
        cells = row.split("|")
        # The treatment, in the last column, says which rows are read days on this source.
        if not row.startswith("|") or len(cells) < 6 or "Read" not in cells[-2]:
            continue
        days = cells[2] if len(cells) > 2 else ""
        span = re.search(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2}), (\d+) dates", days)
        if span:
            first = dt.date.fromisoformat(span.group(1))
            found.update(first + dt.timedelta(days=offset) for offset in range(int(span.group(3))))
            continue
        year = None
        for token in re.findall(r"\d{4}-\d{2}-\d{2}|\b\d{2}-\d{2}\b", days):
            if len(token) == 10:
                found.add(dt.date.fromisoformat(token))
                year = token[:4]
            elif year is not None:
                found.add(dt.date.fromisoformat(f"{year}-{token}"))
    return found


def test_en05_the_plan_s_read_days_are_held_in_code_as_section_4_lists_them() -> None:
    """Section 4 names the demonstration's 10 locked days, 2026-10-01 and 11-01, and the 30 dates of D-18's
    run. 2024-06-01 is D-41's, from the `bookDepth` row whose day the plan infers.
    """
    from_plan = _days_in_rows(_plan_section_4())
    assert len([day for day in from_plan if dt.date(2025, 10, 1) <= day <= dt.date(2026, 9, 30)]) == 10
    assert set(READ_DAYS) == from_plan | {dt.date(2024, 6, 1)}
    assert "2024-06" in _plan_section_4()


def test_en05_a_range_touching_a_read_day_is_refused_unless_the_configuration_lists_it() -> None:
    names = ("first_training_span", "2024-Q1", "2024-Q2")
    q2 = DateRange(dt.date(2024, 4, 1), dt.date(2024, 6, 30))
    with pytest.raises(ConfigError, match="already read"):
        check_range(q2, names, "MARKET")
    assert check_range(q2, names, "MARKET", (dt.date(2024, 6, 1),))
    assert check_range(DateRange(dt.date(2024, 4, 1), dt.date(2024, 5, 31)), names, "MARKET")


# ---- sections 18.2 and 18.3 --------------------------------------------------------------------------------


def test_18_3_a_test_or_locked_block_carries_d38_s_sentence_beside_its_label() -> None:
    first = check_range(
        DateRange(dt.date(2020, 1, 1), dt.date(2020, 1, 2)), ("first_training_span",), "MARKET"
    )
    assert D38_SENTENCE not in span_labels(first)
    names = ("first_training_span", "2024-Q1")
    test = check_range(DateRange(dt.date(2024, 1, 1), dt.date(2024, 1, 2)), names, "MARKET")
    assert span_labels(test) == ("TEST BLOCK 2024-Q1", D38_SENTENCE)


def _day(end_us: int) -> PeriodBar:
    return PeriodBar(end_us - DAY, end_us, 100.0, 110.0, 90.0, 105.0)


def test_18_2_a_restart_of_atrd_is_counted_only_after_it_had_a_value() -> None:
    strategy = S01FloorPivotRejection({"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"})
    unseeded = _bar(0, 100.0, minutes=15)
    seeded = replace(unseeded, atrd=50.0)
    assert strategy.watch_atrd(unseeded) is False
    assert strategy.watch_atrd(seeded) is False
    assert strategy.watch_atrd(unseeded) is True


def test_18_2_a_setup_lost_to_the_restart_is_counted_and_the_dry_run_notes_nothing() -> None:
    """The S01 case of the role ruling: price crossed level 100, held above it, and came back. With ATRD
    defined this close is a setup, so with ATRD restarting it is one setup lost.
    """
    strategy = S01FloorPivotRejection({"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"})
    level, above = Level("L", 100.0), Level("U", 140.0)
    strategy._states = {level.id: _LevelState(level.price), above.id: _LevelState(above.price)}
    rows = [
        (90.0, 91.0, 89.0, 90.0),
        *[(104.0, 105.0, 103.0, 104.0)] * 4,
        (104.0, 106.0, 100.5, 105.5),
    ]
    bars = [
        replace(_bar(index, c, h=h, l=low, atr=10.0, minutes=15), o=o, clv=clv(h, low, c))
        for index, (o, h, low, c) in enumerate(rows)
    ]
    for end in range(1, len(bars) + 1):
        strategy._count_touches([level, above], bars[end - 1], bars[:end])
    last = replace(bars[-1], day=_day(START), atrd=None, day_open=100.0)
    market = MarketView(symbol="S", tick=0.01, rt=0.0012, minutes=15, higher=(), trades=None)
    for bar in [*bars[:-1], last]:
        market._release(bar, {})
    before = dict(strategy.reasons)
    assert strategy._lost_to_restart(market, last, [level, above]) is True
    assert dict(strategy.reasons) == before
    # With no level above for T1 the dry run fails and notes NO_T1_ROOM, and that note is put back too.
    assert strategy._lost_to_restart(market, last, [level]) is False
    assert dict(strategy.reasons) == before


def test_18_2_the_restart_reaches_the_count_on_a_run_with_a_flagged_minute() -> None:
    """A flagged minute on day 40 leaves that day uncomputed, so ATRD's seed starts again, and the closes
    until it reseeds are counted.
    """
    start = utc(2000, 1, 3)
    trades = generated_trades(seed=7, start_us=start, days=70)
    from engine_helpers import minute_bars

    bars = minute_bars(trades, first_close_us=start + MINUTE, last_close_us=start + 70 * DAY)
    flagged = start + 40 * DAY + 12 * HOUR
    bars = bars.with_columns(
        pl.when(pl.col("open_time").dt.timestamp("us") == flagged)
        .then(True)
        .otherwise(pl.col("gap"))
        .alias("gap")
    )
    tape = MinuteTape.from_frame(bars, symbol="S", delay_us=DELAY_US)
    params = {"timeframe_minutes": 15, "touch_limit": 1, "level_set": "full"}
    stream = Simulator(build_strategy("S01", params), tape, sim_params()).run()
    assert stream.reasons.get(ATRD_RESTART_CLOSES, 0) > 14 * 96
    assert "ATRD_RESTART_SETUPS_LOST" in stream.reasons or stream.reasons[ATRD_RESTART_CLOSES] > 0
