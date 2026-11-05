"""The exit layer's one rule for moving a stop: C8.

    long:  S_new = max(S_old, min(S_cand, C_b - 0.10 * ATR_b))
    short: S_new = min(S_old, max(S_cand, C_b + 0.10 * ATR_b))

Charter section 7 rule 1: a stop only tightens. No strategy can do otherwise, because a strategy only proposes
candidates, and this function is the only thing that produces a new stop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from hft_crypto.engine.fills import round_to_tick
from hft_crypto.strategies.base import StopCandidate

_CLAMP_ATR = 0.10


@dataclass(frozen=True)
class RatchetResult:
    stop: float
    reason: str | None


def ratchet(
    *,
    side: int,
    old_stop: float,
    candidates: Sequence[StopCandidate],
    close: float,
    atr: float | None,
    tick: float,
) -> RatchetResult:
    """The stop after one close. If several candidates fire, the tightest one is used.

    With no defined ATR the clamp cannot be computed, so no update happens and the stop holds, under C3.
    """
    if not candidates or atr is None:
        return RatchetResult(old_stop, None)
    best = max(candidates, key=lambda item: side * item.value)
    limit = side * close - _CLAMP_ATR * atr
    wanted = min(side * best.value, limit)
    rounded = side * round_to_tick(side * wanted, side, tick)
    if rounded <= side * old_stop:
        return RatchetResult(old_stop, None)
    return RatchetResult(side * rounded, best.reason)
