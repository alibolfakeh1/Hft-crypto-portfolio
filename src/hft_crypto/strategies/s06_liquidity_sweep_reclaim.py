"""S06 Liquidity sweep and reclaim, `V0`. See docs/01_strategies/S06_liquidity_sweep_reclaim.md.

Backtest only. Every output carries `NOT LIVE-COMPARABLE`, under section 14 of the document.

Readings the document leaves open, each reported:
- A swing pool's age of at most 7 days runs from the close of its extreme bar.
- The tradable delay of 8 bars also applies to swings used as opposing pools, as the table's mirror.

Left out, and reported: the round-number and equal-low tags, which are log-only, and the `CYCLE` control run,
which C-10 holds back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.indicators import MICROS_PER_DAY
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar, PeriodBar, weekday
from hft_crypto.strategies.base import (
    BAR_GAP,
    BREAK_EVEN,
    INVALIDATION,
    NO_LEVELS,
    NO_PATTERN,
    REST,
    SIDES,
    TIME_STOP,
    Management,
    PositionView,
    Proposal,
    StopCandidate,
    Strategy,
    TargetMove,
    TargetPlan,
    clip,
    sided,
    sided_clv,
)
from hft_crypto.strategies.registers import HIGH, LOW, Swing, SwingList

_SWING_MINUTES = 60
_SWING_AGE_DAYS = 7
_TRADABLE_BARS = 8
_PRE_SWEEP_BARS = 12
_SCALE_T1 = 0.5
_T1_DEADLINE = {15: 12, 5: 24}
_ABSOLUTE = {15: 48, 5: 96}
SATURDAY = 5


@dataclass
class _Pool:
    id: str
    price: float
    consumed_at: int | None = None
    traded: bool = False


@dataclass
class _Sweep:
    pool_id: str
    side: int
    level: float
    start_index: int
    sweep_low: float
    pre_sweep_high: float


@dataclass
class _Memo:
    pool_id: str
    level: float
    closes: list[float] = field(default_factory=list)
    pools_seen: tuple[str, ...] = ()


class S06LiquiditySweepReclaim(Strategy):
    id = "S06"
    live_comparable = False
    h_max_hours: ClassVar[dict[int, float]] = {15: 12.0, 5: 8.0}
    requirements = (
        "ATR(14) on the decision timeframe, and on 1h for swing pools",
        "VR: at least 15 days of decision bars in the last 30 days, under C3",
        "SRV: the same weekly slot in at least 4 of the previous 8 weeks",
        "ATRD: 14 true ranges from consecutive completed UTC days",
        "The UTC day before the current one, complete",
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.n_r = int(params["n_r"])
        self.use_swings = bool(params["swing_pools"])
        self.swings = SwingList(5, 3, 1.0)
        self._pools: dict[str, _Pool] = {}
        self._sweeps: list[_Sweep] = []

    @property
    def higher_minutes(self) -> tuple[int, ...]:
        return (_SWING_MINUTES,) if self.use_swings else ()

    def _period_pools(self, day: PeriodBar | None, week: PeriodBar | None) -> list[tuple[str, int, float]]:
        """(id, side of the trade it serves, price). A long is served by a low."""
        rows: list[tuple[str, int, float]] = []
        for label, period in (("D", day), ("W", week)):
            if period is None:
                continue
            rows.append((f"{label}:{period.end_us}:L", 1, period.low))
            rows.append((f"{label}:{period.end_us}:H", -1, period.high))
        return rows

    def _swing_pools(self, bar: Bar, *, for_target: bool) -> list[tuple[str, int, float]]:
        if not self.use_swings:
            return []
        del for_target
        rows: list[tuple[str, int, float]] = []
        oldest = bar.close_us - _SWING_AGE_DAYS * MICROS_PER_DAY
        ready = bar.close_us - _TRADABLE_BARS * self.timeframe_minutes * 60_000_000
        for kind, side in ((LOW, 1), (HIGH, -1)):
            for swing in self.swings.visible(kind):
                if swing.extreme_close_us >= oldest and swing.valid_from <= ready:
                    rows.append((_swing_id(swing), side, swing.price))
        return rows

    def on_close(self, market: MarketView) -> list[Proposal]:
        bar = market.bar
        if self.use_swings:
            frame = market.higher(_SWING_MINUTES)
            if frame.has_new_bar:
                self.swings.update(frame.bars)
        pools = self._period_pools(bar.day, bar.week) + self._swing_pools(bar, for_target=False)
        for pool_id, _, price in pools:
            self._pools.setdefault(pool_id, _Pool(pool_id, price))
        reclaimed = self._advance_sweeps(market, pools)
        if bar.gap:
            self.note(BAR_GAP)
            return []
        missing = self.missing(bar, "atr", "vr", "srv", "atrd")
        if missing:
            self.note(missing)
            return []
        if bar.day is None:
            self.note(NO_LEVELS)
            return []
        if bar.day_open is None:
            self.note("DAY_OPEN_UNDEFINED")
            return []
        if bar.vr is not None and bar.vr > 1.75:
            self.note("VR_BLOCK")
            return []
        for side in SIDES:
            sweeps = [item for item in reclaimed if item.side == side]
            if not sweeps:
                continue
            # 3: if several pools were swept, the highest one the close reclaimed.
            chosen = max(sweeps, key=lambda item: item.level)
            proposal = self._setup(market, bar, chosen, pools)
            if proposal is not None:
                return [proposal]
        self.note(NO_PATTERN)
        return []

    def _advance_sweeps(self, market: MarketView, pools: list[tuple[str, int, float]]) -> list[_Sweep]:
        bars = market.bars
        bar = bars[-1]
        atr = bar.atr if bar.atr is not None else bar.atr_last
        reclaimed: list[_Sweep] = []
        if atr is None or len(bars) < 2:
            return reclaimed
        band = 0.10 * atr
        # Sweeps already running: they die by depth or by the clock, or are reclaimed at this close.
        still: list[_Sweep] = []
        for sweep in self._sweeps:
            _, _, low, close = sided(bar, sweep.side)
            if low < sweep.level - 1.50 * atr or bar.index - sweep.start_index > self.n_r:
                continue
            sweep.sweep_low = min(sweep.sweep_low, low)
            if close > sweep.level + band and sided_clv(bar, sweep.side) >= 0.60:
                pool = self._pools.get(sweep.pool_id)
                if pool is None or not pool.traded:
                    reclaimed.append(sweep)
                continue
            still.append(sweep)
        self._sweeps = still
        weekend = weekday(bar.close_us - 1) >= SATURDAY
        needed = 1.5 if weekend else 1.0
        for pool_id, side, price in pools:
            pool = self._pools[pool_id]
            if pool.consumed_at is not None:
                continue
            level = side * price
            _, _, low, close = sided(bar, side)
            prior_close = side * bars[-2].c
            is_sweep = (
                bar.atr is not None
                and prior_close >= level
                and low < level - 0.10 * atr
                and low >= level - 1.50 * atr
                and bar.h - bar.l <= 4.0 * atr
                and bar.srv is not None
                and bar.srv >= needed
            )
            if is_sweep:
                pool.consumed_at = bar.close_us
                lookback = [sided(item, side)[1] for item in bars[-1 - _PRE_SWEEP_BARS : -1]]
                sweep = _Sweep(pool_id, side, level, bar.index, low, max(lookback) if lookback else close)
                if close > level + band and sided_clv(bar, side) >= 0.60:
                    reclaimed.append(sweep)
                elif self.n_r > 0:
                    self._sweeps.append(sweep)
            elif close < level:
                pool.consumed_at = bar.close_us
        return reclaimed

    def _opposing(self, side: int, day: PeriodBar | None, week: PeriodBar | None, bar: Bar) -> list[float]:
        """Unconsumed pools on the far side, as this side sees them."""
        rows = self._period_pools(day, week) + self._swing_pools(bar, for_target=True)
        prices: list[float] = []
        for pool_id, pool_side, price in rows:
            if pool_side != -side:
                continue
            pool = self._pools.get(pool_id)
            if pool is None or pool.consumed_at is None:
                prices.append(side * price)
        return sorted(prices)

    def _setup(
        self, market: MarketView, bar: Bar, sweep: _Sweep, pools: list[tuple[str, int, float]]
    ) -> Proposal | None:
        atr, vr, atrd, day_open = bar.atr, bar.vr, bar.atrd, bar.day_open
        if atr is None or vr is None or atrd is None or day_open is None:
            return None
        del pools
        side = sweep.side
        close = side * bar.c
        if side * day_open - close > 1.25 * atrd:
            self.note("DAY_MOVE_FILTER")
            return None
        struct = sweep.sweep_low - 0.25 * clip(vr, 0.8, 1.5) * atr
        r_min = market.r_min(0.75)
        s0 = min(struct, close - r_min)
        distance = close - s0
        if distance > 2.25 * atr:
            self.note("STOP_TOO_WIDE")
            return None
        if r_min > 3.0 * atr:
            self.note("COST_VETO")
            return None
        t1 = (
            sweep.pre_sweep_high
            if sweep.pre_sweep_high >= close + 1.0 * distance
            else close + 1.25 * distance
        )
        floor = max(t1 + 1e-12, close + 2.0 * distance)
        beyond = [price for price in self._opposing(side, bar.day, bar.week, bar) if price >= floor]
        t2 = beyond[0] if beyond else close + 3.0 * distance
        memo = _Memo(sweep.pool_id, sweep.level)
        return Proposal(
            side=side,
            s0=side * s0,
            targets=(TargetPlan("T1", side * t1, _SCALE_T1), TargetPlan("T2", side * t2, REST)),
            level={"pool": sweep.pool_id, "price": side * sweep.level, "sweep_low": side * sweep.sweep_low},
            expiry_bars=3,
            memo=memo,
        )

    def notify_sent(self, proposal: Proposal) -> None:
        pool = self._pools.get(proposal.memo.pool_id)
        if pool is not None:
            pool.traded = True

    def manage(self, market: MarketView, position: PositionView) -> Management:
        bar = market.bar
        side = position.side
        memo: _Memo = position.memo
        open_, high, low, close = sided(bar, side)
        memo.closes.append(close)
        n = position.n
        t1_filled = position.filled("T1")
        frozen = bar.atr if bar.atr is not None else bar.atr_last
        if frozen is not None:
            if n <= 4 and close < memo.level - 0.10 * frozen:
                return Management(exit_reason=INVALIDATION, exit_note="RECLAIM_LOST")
            if n == 6:
                near = sum(1 for value in memo.closes[:6] if abs(value - memo.level) <= 0.25 * frozen)
                if near >= 4:
                    return Management(exit_reason=INVALIDATION, exit_note="LINGER")
            if not t1_filled and high - low >= 3.0 * frozen and close < open_:
                return Management(exit_reason=INVALIDATION, exit_note="AFTERSHOCK")
        minutes = self.timeframe_minutes
        if not t1_filled and n >= _T1_DEADLINE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="T1_NOT_HIT")
        if n >= _ABSOLUTE[minutes]:
            return Management(exit_reason=TIME_STOP, exit_note="ABSOLUTE_LIMIT")
        decision = Management()
        atr = bar.atr
        if atr is None:
            return decision
        if close >= position.fill_side + 1.0 * position.r:
            decision.stops.append(StopCandidate(side * (memo.level - 0.25 * atr), "RECLAIM_LOCK"))
        if t1_filled:
            decision.stops.append(StopCandidate(position.be_plus, BREAK_EVEN))
            lows = [sided(item, side)[2] for item in market.bars[-5:]]
            decision.stops.append(StopCandidate(side * (min(lows) - 0.50 * atr), "TRAIL"))
        self._recompute_t2(bar, position, memo, decision, atr, close)
        return decision

    def _recompute_t2(
        self,
        bar: Bar,
        position: PositionView,
        memo: _Memo,
        decision: Management,
        atr: float,
        close: float,
    ) -> None:
        """At each UTC roll, when the opposing pools change, and when a new 1h swing high is confirmed."""
        side = position.side
        pools = tuple(str(price) for price in self._opposing(side, bar.day_at_close, bar.week_at_close, bar))
        if pools == memo.pools_seen:
            return
        first_look = not memo.pools_seen
        memo.pools_seen = pools
        if first_look and position.n == 1:
            return  # the pools the setup itself saw are not a change
        floor = close + 0.5 * atr
        beyond = [
            price
            for price in self._opposing(side, bar.day_at_close, bar.week_at_close, bar)
            if price >= floor
        ]
        if beyond:
            decision.targets.append(TargetMove("T2", side * beyond[0], "OPPOSING_POOLS_CHANGED"))

    def snapshot(self) -> dict[str, Any]:
        return {
            "swings": self.swings.snapshot(),
            "pools": {
                key: [item.price, item.consumed_at, item.traded] for key, item in sorted(self._pools.items())
            },
            "sweeps": [[item.pool_id, item.side, item.start_index, item.sweep_low] for item in self._sweeps],
        }


def _swing_id(swing: Swing) -> str:
    return f"S:{swing.kind}:{swing.extreme_close_us}"
