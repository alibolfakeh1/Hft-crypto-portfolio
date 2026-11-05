"""One strategy on one symbol, in `IDEAL-1M` mode, walked through time one 1m bar at a time.

Timing, in order of what happens around a close at t, with `delay = max(latency, A)`:

1. Every 1m bar up to t is walked first, under the stops and targets then in force.
2. The closed decision bar is released to the strategy, which decides with what was knowable at t + delay.
3. An entry, a close-based exit and every stop or target update act from the first 1m bar with
   `open_time >= t + delay`. Every 1m bar before that keeps the old values. So a decision never fills before
   itself, and an update never acts on the bar that produced it. This is timing contract items 7 and 12.

Inside a 1m bar, C7's order holds: a pending exit, a gap through the stop, a touch of the stop, then targets.
So a bar holding both a stop and a target is a stop.

Decisions never read a position's future, because the bars have not been released. The one step that runs
after the walk is the report of a gap under C2, which only labels a finished trade and changes no decision.
"""

from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hft_crypto.bars.core import TimingContractError
from hft_crypto.engine.accounting import Booked, CashEvent, ExitLeg, FundingCharge, book_trade
from hft_crypto.engine.config import CostConfig
from hft_crypto.engine.exits import ratchet
from hft_crypto.engine.fills import (
    EntryPlan,
    beyond_collar,
    entry_fill_price,
    exit_price,
    plan_entry,
    round_to_tick,
)
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, MinuteTape, TradeTape, ceil_minute
from hft_crypto.strategies.base import (
    BREAK_EVEN,
    Management,
    PositionView,
    Proposal,
    Strategy,
    TargetMove,
    TargetPlan,
)
from hft_crypto.timeutil import MICROS_PER_MINUTE

MODE = "IDEAL-1M"
VARIANT = "V0"
BAR_NOT_COMPLETE = "BAR_NOT_COMPLETE_AS_OF_CLOSE"
LEFT_OUT_UNOPENED = "LEFT_OUT_REACHES_UNOPENED_DATE"
LEFT_OUT_READ_DAY = "LEFT_OUT_REACHES_READ_DAY"
_QTY_EPSILON = 1e-9


@dataclass(frozen=True)
class SimParams:
    costs: CostConfig
    latency_us: int
    allowance_us: int
    fill_span_allowance_us: int
    risk_budget: float
    capital: float
    leverage_cap: float
    tick: float
    # The first unopened instant, and the days already read. A setup whose maximum hold reaches either is
    # left out.
    span_end_us: int | None = None
    read_days_us: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if self.allowance_us < self.fill_span_allowance_us:
            raise TimingContractError(
                "the mode table requires A >= fill_span_allowance_ms, compared in one unit"
            )

    @property
    def delay_us(self) -> int:
        return max(self.latency_us, self.allowance_us)


@dataclass(frozen=True)
class FundingEvent:
    """One settlement: its time, the rate published then, and when that rate became knowable."""

    settle_us: int
    rate: float


@dataclass
class _Leg:
    name: str
    price: float | None
    fraction: float | None
    filled: bool = False


@dataclass
class _Scheduled:
    effective_us: int
    stop: float | None = None
    move: TargetMove | None = None


@dataclass
class _Pending:
    proposal: Proposal
    plan: EntryPlan
    signal_us: int
    decided_as_of_us: int
    not_before_us: int


@dataclass
class _Position:
    """Held by the simulator. A strategy reads this only through `PositionView`."""

    proposal: Proposal
    plan: EntryPlan
    signal_us: int
    side: int
    fill_us: int
    fill_row: int
    fill_reference: float
    fill: float
    r: float
    q0: float
    stop: float
    stop_planned: float
    legs: list[_Leg]
    be_plus: float
    memo: Any
    qty: float
    n: int = 0
    best: float = 0.0
    worst: float = 0.0
    pending_exit_us: int | None = None
    pending_exit_reason: str = ""
    pending_exit_at: int = 0
    scheduled: list[_Scheduled] = field(default_factory=list)
    exits: list[ExitLeg] = field(default_factory=list)
    funding: list[FundingCharge] = field(default_factory=list)
    stop_path: list[dict[str, Any]] = field(default_factory=list)
    target_path: list[dict[str, Any]] = field(default_factory=list)
    last_row: int = 0

    def planned_target(self, name: str) -> float | None:
        price = next((leg.price for leg in self.legs if leg.name == name), None)
        for item in self.scheduled:
            if item.move is not None and item.move.name == name:
                price = item.move.price
        return price

    def target_filled(self, name: str) -> bool:
        return any(leg.name == name and leg.filled for leg in self.legs)


@dataclass(frozen=True)
class TradeRecord:
    """One finished or still open trade. Plain values, so the report layer needs nothing else."""

    strategy: str
    version: str
    symbol: str
    side: int
    tag: str | None
    signal_us: int
    decided_as_of_us: int
    decision_price: float
    collar_limit: float
    fill_us: int
    fill_event_us: int
    fill_reference: float
    fill: float
    q0: float
    uncapped_q0: float
    leverage_capped: bool
    risk_budget: float
    s0: float
    r_dec: float
    r: float
    targets_at_setup: tuple[TargetPlan, ...]
    level: dict[str, Any]
    entry_fee_rate: float
    legs: tuple[ExitLeg, ...]
    funding: tuple[FundingCharge, ...]
    stop_path: tuple[dict[str, Any], ...]
    target_path: tuple[dict[str, Any], ...]
    exit_reason: str
    stop_kind: str
    status: str
    bars_held: int
    best: float
    worst: float
    through_stop: bool
    gap_unresolved: bool
    gap_start_us: int | None
    as_recorded_legs: tuple[ExitLeg, ...]
    line: str
    is_default: bool
    in_portfolio: bool

    def book(self, scale: float = 1.0) -> tuple[list[CashEvent], Booked]:
        return book_trade(
            side=self.side,
            entry_us=self.fill_event_us,
            fill_reference=self.fill_reference,
            fill=self.fill,
            q0=self.q0,
            entry_fee_rate=self.entry_fee_rate,
            legs=self.legs,
            funding=self.funding,
            scale=scale,
        )


@dataclass
class StreamResult:
    strategy: str
    line: str
    is_default: bool
    in_portfolio: bool
    params: dict[str, Any]
    version: str
    symbol: str
    timeframe_minutes: int
    closes: int
    setups: int
    live_comparable: bool
    requirements: tuple[str, ...]
    reasons: dict[str, int]
    counters: dict[str, int]
    trades: list[TradeRecord]
    events: list[dict[str, Any]]


class Simulator:
    def __init__(
        self,
        strategy: Strategy,
        tape: MinuteTape,
        params: SimParams,
        *,
        trades: TradeTape | None = None,
        funding: Sequence[FundingEvent] = (),
        probe: Callable[[Strategy, MarketView], None] | None = None,
        line: str = "",
        is_default: bool = True,
        in_portfolio: bool = True,
    ) -> None:
        if tape.delay_us != params.delay_us:
            raise TimingContractError("the tape's standing was built for another decision delay")
        self.strategy = strategy
        self.params = params
        self.tape = tape
        self._trades = trades
        self._funding = sorted(funding, key=lambda item: item.settle_us)
        self._funding_cursor = 0
        self._probe = probe
        self._line = line
        self._is_default = is_default
        self._in_portfolio = in_portfolio
        self._position: _Position | None = None
        self._pending: _Pending | None = None
        self._cursor = 0
        self.events: list[dict[str, Any]] = []
        self.finished: list[TradeRecord] = []
        self.counters: Counter[str] = Counter()
        self.setups = 0
        # A memoryview reads one plain value at a time far faster than an array, and copies nothing.
        self._open_us = memoryview(tape.open_us)
        self._close_us = memoryview(tape.close_us)
        self._o = memoryview(tape.open)
        self._h = memoryview(tape.high)
        self._l = memoryview(tape.low)

    def _bars(self, minutes: int) -> list[Bar]:
        return self.tape.frame(minutes)

    # ---- the run ------------------------------------------------------------------------------------------

    def run(self) -> StreamResult:
        strategy = self.strategy
        minutes = strategy.timeframe_minutes
        bars = self._bars(minutes)
        higher = {value: self._bars(value) for value in strategy.higher_minutes}
        higher_cursor = dict.fromkeys(higher, 0)
        market = MarketView(
            symbol=self.tape.symbol,
            tick=self.params.tick,
            rt=self.params.costs.rt,
            minutes=minutes,
            higher=strategy.higher_minutes,
            trades=self._trades,
        )
        for bar in bars:
            self._walk_through(bar.close_us)
            released: dict[int, Bar | None] = {}
            for value, series in higher.items():
                position = higher_cursor[value]
                if position < len(series) and series[position].close_us <= bar.close_us:
                    released[value] = series[position]
                    higher_cursor[value] = position + 1
            market._release(bar, released)
            self._at_close(bar, market)
            if self._probe is not None:
                self._probe(strategy, market)
        self._walk_through(self._close_us[-1] if self.tape.size else 0)
        self._finish_open_position()
        return StreamResult(
            strategy=strategy.id,
            line=self._line,
            is_default=self._is_default,
            in_portfolio=self._in_portfolio,
            params=dict(strategy.params),
            version=strategy.version,
            symbol=self.tape.symbol,
            timeframe_minutes=minutes,
            closes=len(bars),
            setups=self.setups,
            live_comparable=strategy.live_comparable,
            requirements=strategy.requirements,
            reasons=dict(sorted(strategy.reasons.items())),
            counters=dict(sorted(self.counters.items())),
            trades=self.finished,
            events=self.events,
        )

    def _log(self, kind: str, *, knowable_us: int, **fields: Any) -> None:
        self.events.append({"type": kind, "knowable_us": knowable_us, **fields})

    # ---- a close ------------------------------------------------------------------------------------------

    def _at_close(self, bar: Bar, market: MarketView) -> None:
        strategy = self.strategy
        decided_as_of = bar.close_us + self.params.delay_us
        proposals = strategy.on_close(market)
        for item in strategy.log_buffer:
            self._log(
                item["type"],
                knowable_us=decided_as_of,
                computed_at_us=bar.close_us,
                **{key: value for key, value in item.items() if key != "type"},
            )
        strategy.log_buffer.clear()

        position = self._position
        if position is not None:
            position.n += 1
            self._manage(position, bar, market, decided_as_of)

        for proposal in proposals:
            if not bar.complete:
                # Ruling 4: a bar not complete as of its close creates no setup, and a later proof adds
                # nothing.
                strategy.note(BAR_NOT_COMPLETE)
                self.counters["setups_lost_bar_not_complete"] += 1
                self._log(
                    "SETUP_LOST",
                    knowable_us=decided_as_of,
                    computed_at_us=bar.close_us,
                    reason=BAR_NOT_COMPLETE,
                    side=proposal.side,
                )
                continue
            self._take(proposal, bar, strategy, decided_as_of)

    def _take(self, proposal: Proposal, bar: Bar, strategy: Strategy, decided_as_of: int) -> None:
        if bar.atr is None:
            raise TimingContractError(f"{strategy.id} proposed a setup at a close with no ATR")
        out_because = self._left_out(bar.close_us, strategy.h_max_us)
        if out_because is not None:
            # FP-06: never simulated, so the strategy stays flat across it and no later setup's fate rests on
            # it. FP-07: by C18's `reaches`, on the maximum hold, so leaving it out does not depend on how it
            # would end.
            strategy.note(out_because)
            self.counters[f"setups_{out_because.lower()}"] += 1
            self._log(
                "SETUP_LEFT_OUT",
                knowable_us=decided_as_of,
                computed_at_us=bar.close_us,
                side=proposal.side,
                h_max_us=strategy.h_max_us,
                reason=out_because,
            )
            return
        tick = self.params.tick
        side = proposal.side
        s0 = round_to_tick(proposal.s0, side, tick)
        targets = tuple(
            TargetPlan(
                plan.name,
                None if plan.price is None else round_to_tick(plan.price, side, tick),
                plan.fraction,
            )
            for plan in proposal.targets
        )
        self.setups += 1
        self._log(
            "SETUP_CREATED",
            knowable_us=decided_as_of,
            computed_at_us=bar.close_us,
            side=side,
            s0=s0,
            targets=[(item.name, item.price, item.fraction) for item in targets],
            level=proposal.level,
            expiry_bars=proposal.expiry_bars,
            tag=proposal.tag,
            decision_price=bar.c,
        )
        if self._position is not None or self._pending is not None:
            self.counters["skipped_open"] += 1
            self._log("SKIPPED_OPEN", knowable_us=decided_as_of, computed_at_us=bar.close_us, side=side)
            return
        plan = plan_entry(
            side=side,
            decision_price=bar.c,
            s0=s0,
            atr=bar.atr,
            risk_budget=self.params.risk_budget,
            capital=self.params.capital,
            leverage_cap=self.params.leverage_cap,
        )
        if plan.q0 < plan.uncapped_q0:
            self.counters["size_capped_by_leverage"] += 1
            self._log(
                "SIZE_CAPPED",
                knowable_us=decided_as_of,
                computed_at_us=bar.close_us,
                old=plan.uncapped_q0,
                new=plan.q0,
                reason="LEVERAGE_CAP",
            )
        self._pending = _Pending(
            proposal=Proposal(
                side=side,
                s0=s0,
                targets=targets,
                level=proposal.level,
                expiry_bars=proposal.expiry_bars,
                memo=proposal.memo,
                tag=proposal.tag,
            ),
            plan=plan,
            signal_us=bar.close_us,
            decided_as_of_us=decided_as_of,
            not_before_us=decided_as_of,
        )
        strategy.notify_sent(proposal)

    def _left_out(self, signal_us: int, h_max_us: int) -> str | None:
        reach = signal_us + h_max_us
        span_end = self.params.span_end_us
        if span_end is not None and reach >= span_end:
            return LEFT_OUT_UNOPENED
        for start, end in self.params.read_days_us:
            if start <= reach and signal_us < end:
                return LEFT_OUT_READ_DAY
        return None

    def _manage(self, position: _Position, bar: Bar, market: MarketView, decided_as_of: int) -> None:
        if position.pending_exit_us is not None:
            return  # an exit is already on its way, and nothing below can act before it does
        view = PositionView(position)
        decision: Management = self.strategy.manage(market, view)
        effective = ceil_minute(decided_as_of)
        if decision.exit_reason is not None:
            position.pending_exit_us = effective
            position.pending_exit_reason = decision.exit_reason
            position.pending_exit_at = bar.close_us
            self._log(
                decision.exit_reason,
                knowable_us=decided_as_of,
                computed_at_us=bar.close_us,
                effective_from_us=effective,
                reason=decision.exit_note,
                n=position.n,
            )
            return
        result = ratchet(
            side=position.side,
            old_stop=position.stop_planned,
            candidates=decision.stops,
            close=bar.c,
            atr=bar.atr,
            tick=self.params.tick,
        )
        if result.reason is not None:
            old = position.stop_planned
            position.stop_planned = result.stop
            position.scheduled.append(_Scheduled(effective, stop=result.stop))
            row = {
                "computed_at_us": bar.close_us,
                "effective_from_us": effective,
                "old": old,
                "new": result.stop,
                "reason": result.reason,
            }
            position.stop_path.append(row)
            self._log("STOP_UPDATE", knowable_us=decided_as_of, **row)
        for move in decision.targets:
            self._schedule_target(position, move, bar.close_us, effective, decided_as_of)

    def _schedule_target(
        self, position: _Position, move: TargetMove, computed_at: int, effective: int, knowable: int
    ) -> None:
        price = None if move.price is None else round_to_tick(move.price, position.side, self.params.tick)
        old = position.planned_target(move.name)
        if old == price and not move.set_fraction:
            return
        rounded = TargetMove(move.name, price, move.reason, move.set_fraction, move.fraction)
        position.scheduled.append(_Scheduled(effective, move=rounded))
        row = {
            "computed_at_us": computed_at,
            "effective_from_us": effective,
            "name": move.name,
            "old": old,
            "new": price,
            "reason": move.reason,
        }
        position.target_path.append(row)
        self._log("TARGET_UPDATE", knowable_us=knowable, **row)

    # ---- the 1m walk --------------------------------------------------------------------------------------

    def _walk_through(self, close_us: int) -> None:
        """Walk every 1m row with a close at or before this moment, in time order."""
        rows = self.tape.size
        close_times = self._close_us
        row = self._cursor
        while row < rows and close_times[row] <= close_us:
            if self._position is None and self._pending is None:
                # Nothing to resolve, so skip ahead without reading a single price.
                row = bisect.bisect_right(close_times, close_us, lo=row)
                break
            self._step(row)
            row += 1
        self._cursor = row

    def _step(self, row: int) -> None:
        pending = self._pending
        if pending is not None and self._open_us[row] >= pending.not_before_us:
            self._try_fill(pending, row)
        position = self._position
        if position is not None:
            self._walk_position(position, row)

    def _try_fill(self, pending: _Pending, row: int) -> None:
        reference = self._o[row]
        if reference != reference:  # NaN: this minute has no price, so the fill uses the first that does
            return
        self._pending = None
        plan = pending.plan
        proposal = pending.proposal
        event_us = self._close_us[row]
        if beyond_collar(plan, reference):
            self.counters["entry_collar"] += 1
            self._log(
                "ENTRY_COLLAR",
                knowable_us=event_us,
                computed_at_us=pending.signal_us,
                reference=reference,
                limit=plan.limit,
                side=plan.side,
            )
            return
        fill = entry_fill_price(reference, plan.side, self.params.costs)
        r = abs(fill - plan.s0)
        rt = self.params.costs.rt
        position = _Position(
            proposal=proposal,
            plan=plan,
            signal_us=pending.signal_us,
            side=plan.side,
            fill_us=self._open_us[row],
            fill_row=row,
            fill_reference=reference,
            fill=fill,
            r=r,
            q0=plan.q0,
            stop=plan.s0,
            stop_planned=plan.s0,
            legs=[_Leg(item.name, item.price, item.fraction) for item in proposal.targets],
            be_plus=round_to_tick(fill * (1.0 + plan.side * rt), plan.side, self.params.tick),
            memo=proposal.memo,
            qty=plan.q0,
            best=plan.side * reference,
            worst=plan.side * reference,
        )
        self._position = position
        self._log(
            "ENTRY",
            knowable_us=event_us,
            computed_at_us=pending.signal_us,
            fill_us=position.fill_us,
            reference=reference,
            fill=fill,
            q0=plan.q0,
            r=r,
            r_dec=plan.r_dec,
            side=plan.side,
        )
        # C7 uses the setup's targets on the fill bar. A strategy that says otherwise is the named exception.
        for move in self.strategy.on_fill(PositionView(position)):
            price = None if move.price is None else round_to_tick(move.price, plan.side, self.params.tick)
            for leg in position.legs:
                if leg.name == move.name:
                    position.target_path.append(
                        {
                            "computed_at_us": position.fill_us,
                            "effective_from_us": position.fill_us,
                            "name": move.name,
                            "old": leg.price,
                            "new": price,
                            "reason": move.reason,
                        }
                    )
                    leg.price = price

    def _walk_position(self, position: _Position, row: int) -> None:
        open_us = self._open_us[row]
        if position.scheduled:
            due = [item for item in position.scheduled if item.effective_us <= open_us]
            if due:
                position.scheduled = [item for item in position.scheduled if item.effective_us > open_us]
                for item in due:
                    self._apply(position, item)
        position.last_row = row
        open_ = self._o[row]
        if (
            open_ != open_
        ):  # NaN: a minute with no trades touches nothing, and the position stays open across it
            self._charge_funding(position, row)
            return
        side = position.side
        close_us = self._close_us[row]
        costs = self.params.costs
        if position.pending_exit_us is not None and open_us >= position.pending_exit_us:
            # This exit fills at the open, so a settlement later in this minute falls after it and is not
            # owed.
            price = exit_price(open_, side, costs.slip)
            self._exit_rest(position, close_us, open_, price, position.pending_exit_reason, costs.fee_taker)
            return
        self._charge_funding(position, row)
        stop = position.stop
        high = self._h[row] if side > 0 else -self._l[row]
        low = self._l[row] if side > 0 else -self._h[row]
        s_open = side * open_
        s_stop = side * stop
        position.best = max(position.best, high)
        position.worst = min(position.worst, low)
        if s_open <= s_stop:
            reason = "ENTRY_THROUGH_STOP" if row == position.fill_row else "STOP_GAP"
            price = exit_price(open_, side, costs.stop_slip)
            self._exit_rest(position, close_us, open_, price, reason, costs.fee_taker)
            return
        if low <= s_stop:
            price = exit_price(stop, side, costs.stop_slip)
            self._exit_rest(position, close_us, stop, price, "STOP", costs.fee_taker)
            return
        for leg in sorted(
            (leg for leg in position.legs if not leg.filled and leg.price is not None),
            key=lambda item: side * (item.price if item.price is not None else 0.0),
        ):
            price_level = leg.price
            if price_level is None or high <= side * price_level:
                continue
            self._fill_target(position, leg, close_us, price_level)
            if position.qty <= _QTY_EPSILON * position.q0:
                self._close_position(position)
                return

    def _apply(self, position: _Position, item: _Scheduled) -> None:
        if item.stop is not None:
            # A second guard. `ratchet` already refuses this, and nothing may ever get past both.
            if position.side * (item.stop - position.stop) < 0:
                raise TimingContractError("a stop was about to move away from the market")
            position.stop = item.stop
        move = item.move
        if move is not None:
            for leg in position.legs:
                if leg.name == move.name and not leg.filled:
                    leg.price = move.price
                    if move.set_fraction:
                        leg.fraction = move.fraction

    def _charge_funding(self, position: _Position, row: int) -> None:
        schedule = self._funding
        cursor = self._funding_cursor
        open_us = self._open_us[row]
        close_us = self._close_us[row]
        while cursor < len(schedule) and schedule[cursor].settle_us <= open_us:
            cursor += 1
        while cursor < len(schedule) and schedule[cursor].settle_us <= close_us:
            event = schedule[cursor]
            # C10: charged when entry fill time < settlement <= exit fill time.
            if position.fill_us < event.settle_us:
                mark = self._mark_for_funding(row)
                position.funding.append(FundingCharge(event.settle_us, event.rate, position.qty, mark))
                self._log(
                    "FUNDING",
                    knowable_us=close_us,
                    settle_us=event.settle_us,
                    rate=event.rate,
                    qty=position.qty,
                    mark=mark,
                )
            cursor += 1
        self._funding_cursor = cursor

    def _mark_for_funding(self, row: int) -> float:
        mark = self.tape.mark_price(self._open_us[row])
        if mark is not None:
            return mark
        return self._o[row]

    def _fill_target(self, position: _Position, leg: _Leg, event_us: int, price: float) -> None:
        planned = position.qty if leg.fraction is None else min(leg.fraction * position.q0, position.qty)
        leg.filled = True
        position.qty -= planned
        fee = self.params.costs.target_fee
        position.exits.append(ExitLeg(event_us, price, price, planned, fee, f"TARGET_{leg.name}"))
        self._log(
            "SCALE_OUT",
            knowable_us=event_us,
            name=leg.name,
            price=price,
            qty=planned,
            remaining=position.qty,
        )

    def _exit_rest(
        self, position: _Position, event_us: int, reference: float, price: float, reason: str, fee: float
    ) -> None:
        if position.pending_exit_us is not None and reason != position.pending_exit_reason:
            self._log(
                "EXIT_SUPERSEDED",
                knowable_us=event_us,
                computed_at_us=position.pending_exit_at,
                superseded=position.pending_exit_reason,
                by=reason,
            )
        position.exits.append(ExitLeg(event_us, reference, price, position.qty, fee, reason))
        position.qty = 0.0
        self._close_position(position)

    def _close_position(self, position: _Position) -> None:
        last = position.exits[-1]
        self._log("EXIT", knowable_us=last.event_us, reason=last.reason, price=last.price, n=position.n)
        self.finished.append(self._record(position, status="closed"))
        self._position = None

    def _finish_open_position(self) -> None:
        """The data ended. What is still held is valued at the last price, and stays marked as open."""
        pending = self._pending
        if pending is not None:
            self.counters["entry_unfilled_at_end"] += 1
            self._log(
                "ENTRY_UNFILLED_AT_END",
                knowable_us=self._close_us[-1] if self.tape.size else 0,
                computed_at_us=pending.signal_us,
            )
            self._pending = None
        position = self._position
        if position is None:
            return
        final_us = self._close_us[-1]
        mark = self.tape.mark_price(final_us)
        price = position.fill_reference if mark is None else mark
        position.exits.append(ExitLeg(final_us, price, price, position.qty, 0.0, "OPEN_AT_END", True))
        position.qty = 0.0
        self.finished.append(self._record(position, status="open"))
        self._position = None

    # ---- a finished trade ---------------------------------------------------------------------------------

    def _record(self, position: _Position, *, status: str) -> TradeRecord:
        plan = position.plan
        recorded = tuple(position.exits)
        legs, gap_start = self._apply_gap_rule(position, recorded)
        final_reason = legs[-1].reason
        status = "open" if legs[-1].open_at_end else "closed"
        return TradeRecord(
            strategy=self.strategy.id,
            version=self.strategy.version,
            symbol=self.tape.symbol,
            side=position.side,
            tag=position.proposal.tag,
            signal_us=position.signal_us,
            decided_as_of_us=position.signal_us + self.params.delay_us,
            decision_price=plan.decision_price,
            collar_limit=plan.limit,
            fill_us=position.fill_us,
            fill_event_us=self._close_us[position.fill_row],
            fill_reference=position.fill_reference,
            fill=position.fill,
            q0=plan.q0,
            uncapped_q0=plan.uncapped_q0,
            leverage_capped=plan.q0 < plan.uncapped_q0,
            risk_budget=plan.risk_budget,
            s0=plan.s0,
            r_dec=plan.r_dec,
            r=position.r,
            targets_at_setup=position.proposal.targets,
            level=position.proposal.level,
            entry_fee_rate=self.params.costs.fee_taker,
            legs=legs,
            funding=tuple(position.funding),
            stop_path=tuple(position.stop_path),
            target_path=tuple(position.target_path),
            exit_reason=final_reason,
            stop_kind=_stop_kind(position),
            status=status,
            bars_held=position.n,
            best=position.best,
            worst=position.worst,
            through_stop=any(leg.reason == "ENTRY_THROUGH_STOP" for leg in recorded),
            gap_unresolved=gap_start is not None,
            gap_start_us=gap_start,
            as_recorded_legs=recorded,
            line=self._line,
            is_default=self._is_default,
            in_portfolio=self._in_portfolio,
        )

    def _apply_gap_rule(
        self, position: _Position, recorded: tuple[ExitLeg, ...]
    ) -> tuple[tuple[ExitLeg, ...], int | None]:
        """C2, in IDEAL-1M: a position open across a gap is reported both ways, and the worse is the headline.

        This labels a finished trade. No decision reads it.
        """
        gap = self.tape.gap
        first = position.fill_row
        last = max(position.last_row, first)
        flagged = np.flatnonzero(gap[first : last + 1])
        # A missing row is a gap too. On candles a minute with no row has no flag to carry.
        jumps = np.flatnonzero(np.diff(self.tape.close_us[first : last + 1]) > MICROS_PER_MINUTE)
        if flagged.size == 0 and jumps.size == 0:
            return recorded, None
        flagged_at = self._open_us[first + int(flagged[0])] if flagged.size else None
        jump_at = self._close_us[first + int(jumps[0])] if jumps.size else None
        gap_start = min(value for value in (flagged_at, jump_at) if value is not None)
        gap_row = first + (int(flagged[0]) if flagged.size and gap_start == flagged_at else int(jumps[0]))
        stop = position.plan.s0
        for row_item in position.stop_path:
            if row_item["effective_from_us"] <= gap_start:
                stop = float(row_item["new"])
        kept = tuple(leg for leg in recorded if leg.event_us <= gap_start and not leg.open_at_end)
        rest = position.q0 - sum(leg.qty for leg in kept)
        if rest <= _QTY_EPSILON * position.q0:
            return recorded, None
        costs = self.params.costs
        alternative = (
            *kept,
            ExitLeg(
                gap_start,
                stop,
                exit_price(stop, position.side, costs.stop_slip),
                rest,
                costs.fee_taker,
                "GAP_UNRESOLVED_STOP",
            ),
        )
        self.counters["gap_unresolved"] += 1
        self._log(
            "GAP_UNRESOLVED",
            knowable_us=int(self.tape.knowable_us[gap_row]),
            gap_start_us=gap_start,
            stop_in_force=stop,
            signal_us=position.signal_us,
        )
        as_recorded = self._net_of(position, recorded)
        touched = self._net_of(position, alternative)
        return (alternative if touched < as_recorded else recorded), gap_start

    def _net_of(self, position: _Position, legs: tuple[ExitLeg, ...]) -> int:
        _, booked = book_trade(
            side=position.side,
            entry_us=self._close_us[position.fill_row],
            fill_reference=position.fill_reference,
            fill=position.fill,
            q0=position.q0,
            entry_fee_rate=self.params.costs.fee_taker,
            legs=legs,
            funding=tuple(position.funding),
        )
        return booked.net


def _stop_kind(position: _Position) -> str:
    """Which kind of stop was in force at the end, for the exit reasons in section 5 of the outputs."""
    if not position.stop_path:
        return "initial"
    final = position.stop_path[-1]
    if final["reason"] == BREAK_EVEN:
        return "break_even"
    return "trailed"
