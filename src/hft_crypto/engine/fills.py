"""The order layer, in arithmetic only. Nothing here reaches any venue.

C6: the entry is modelled as a marketable limit fixed at the decision, filled at the first 1m open that the
mode table allows. Size comes from the distance between the decision price and the initial stop, and the
leverage cap of decision D-28 is applied per position at the same moment, because the fill is not known yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hft_crypto.engine.config import CostConfig


def round_to_tick(price: float, side: int, tick: float) -> float:
    """C16: a long stop or target rounds down, and a short stop or target rounds up."""
    decimals = max(0, -math.floor(math.log10(tick)) + 1)
    steps = price / tick
    # A value already on a tick can sit just under it in binary, and must not lose a whole tick.
    nearest = round(steps)
    if abs(steps - nearest) < 1e-7:
        return round(nearest * tick, decimals)
    whole = math.floor(steps) if side > 0 else math.ceil(steps)
    return round(whole * tick, decimals)


@dataclass(frozen=True)
class EntryPlan:
    """Everything fixed at the decision, before any later price is known."""

    side: int
    decision_price: float
    s0: float
    r_dec: float
    limit: float
    q0: float
    uncapped_q0: float
    risk_budget: float


def plan_entry(
    *,
    side: int,
    decision_price: float,
    s0: float,
    atr: float,
    risk_budget: float,
    capital: float,
    leverage_cap: float,
) -> EntryPlan:
    """C6: `R_dec`, the collar and the size. Size is capped at the position's leverage limit."""
    r_dec = abs(decision_price - s0)
    if r_dec <= 0 or side * (decision_price - s0) <= 0:
        raise ValueError(f"an initial stop must lie beyond the decision price: {decision_price} and {s0}")
    uncapped = risk_budget / r_dec
    cap = leverage_cap * capital / decision_price
    return EntryPlan(
        side=side,
        decision_price=decision_price,
        s0=s0,
        r_dec=r_dec,
        limit=decision_price + side * 0.5 * atr,
        q0=min(uncapped, cap),
        uncapped_q0=uncapped,
        risk_budget=risk_budget,
    )


def beyond_collar(plan: EntryPlan, reference: float) -> bool:
    """The test is on the reference, before slippage."""
    return plan.side * (reference - plan.limit) > 0


def entry_fill_price(reference: float, side: int, costs: CostConfig) -> float:
    return reference * (1.0 + side * costs.slip)


def exit_price(reference: float, side: int, slip: float) -> float:
    """A long sells lower and a short buys back higher."""
    return reference * (1.0 - side * slip)
