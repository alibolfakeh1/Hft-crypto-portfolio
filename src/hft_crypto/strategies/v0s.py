"""C13: the `V0S` control, the same setups with the simplest exit.

Same setup, same entry, same `S0` and `R` as `V0`. One fixed target at `fill + m * R`, set from the fill, so
the fill bar uses it, which is the exception C13 names to C7. A fixed maximum hold of `H` bars, closed at the
next open. No scale-out, no invalidation, and no update of any kind. Each strategy's `m` and `H` are the
constants of its section 7.10, and S09 holds to its hard flat in place of `H`.

It wraps the real strategy, so its setups come from the same code. The wrapped strategy's own exit rules are
never called. `V0S` reports beside `V0` and is never in the portfolio figure.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from hft_crypto.engine.market import MarketView
from hft_crypto.strategies.base import (
    REST,
    TIME_STOP,
    Management,
    PositionView,
    Proposal,
    Strategy,
    TargetMove,
    TargetPlan,
)

VARIANT_V0S = "V0S"
V0S_HOLD = "V0S_HOLD"


class V0SControl(Strategy):
    def __init__(self, inner: Strategy) -> None:
        super().__init__(inner.params)
        self.inner = inner
        self.id = inner.id
        self.version = inner.version
        self.requirements = inner.requirements
        self.live_comparable = inner.live_comparable
        # One count of reasons and one log for both, so what the setup code notes is what this run reports.
        self.reasons = inner.reasons
        self.log_buffer = inner.log_buffer
        self.m = type(inner).v0s_m

    @property
    def h_max_us(self) -> int:
        """The same `H_max` as `V0`, so the same setups are left out under FP-07."""
        return self.inner.h_max_us

    @property
    def higher_minutes(self) -> tuple[int, ...]:
        return self.inner.higher_minutes

    def on_close(self, market: MarketView) -> list[Proposal]:
        return [
            replace(proposal, targets=(TargetPlan("T1", None, REST),))
            for proposal in self.inner.on_close(market)
        ]

    def on_fill(self, position: PositionView) -> list[TargetMove]:
        target = position.fill_side + self.m * position.r
        return [TargetMove("T1", position.side * target, "V0S_FIXED_TARGET")]

    def manage(self, market: MarketView, position: PositionView) -> Management:
        if self.inner.v0s_time_up(market, position):
            return Management(exit_reason=TIME_STOP, exit_note=V0S_HOLD)
        return Management()

    def notify_sent(self, proposal: Proposal) -> None:
        self.inner.notify_sent(proposal)

    def snapshot(self) -> dict[str, Any]:
        return self.inner.snapshot()
