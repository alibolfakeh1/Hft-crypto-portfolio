"""Layer 5: the cap on gross exposure across the portfolio, decision D-28.

Streams run on their own, so a strategy's own record never depends on another strategy. This pass then goes
through every entry in the order it was decided, and asks what the portfolio held at that moment. An entry
that would take gross exposure past the cap is scaled to what is left, and an entry with nothing left is
refused at this level. It stays on the stream's own record, and carries no weight in the portfolio's.

Entries decided at one moment are taken in strategy and symbol order. That order is arbitrary. It is written
down here so that it stays visible, because the first in line gets the room.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from hft_crypto.engine.simulator import TradeRecord

TradeKey = tuple[str, str, str, int]


def trade_key(trade: TradeRecord) -> TradeKey:
    return (trade.strategy, trade.line, trade.symbol, trade.signal_us)


@dataclass(frozen=True)
class CapDecision:
    scale: float
    gross_before: float
    notional: float

    @property
    def refused(self) -> bool:
        return self.scale <= 0.0


def _open_qty(trade: TradeRecord, at_us: int) -> float:
    left = trade.q0
    for leg in trade.legs:
        if leg.event_us <= at_us and not leg.open_at_end:
            left -= leg.qty
    return max(left, 0.0)


def _finished_by(trade: TradeRecord, at_us: int) -> bool:
    return all(leg.event_us <= at_us and not leg.open_at_end for leg in trade.legs)


def apply_gross_cap(
    trades: Sequence[TradeRecord],
    *,
    capital: float,
    gross_cap: float,
    mark: Callable[[str, int], float | None],
) -> dict[TradeKey, CapDecision]:
    """A size factor for every trade counted in the portfolio, using only what was held at its decision."""
    limit = gross_cap * capital
    ordered = sorted(trades, key=lambda item: (item.decided_as_of_us, item.strategy, item.symbol))
    decisions: dict[TradeKey, CapDecision] = {}
    held: list[tuple[TradeRecord, float]] = []
    for trade in ordered:
        moment = trade.decided_as_of_us
        held = [(item, scale) for item, scale in held if not _finished_by(item, moment)]
        gross = 0.0
        for item, scale in held:
            if item.fill_us > moment:
                gross += scale * item.q0 * item.decision_price
                continue
            price = mark(item.symbol, moment)
            gross += scale * _open_qty(item, moment) * (item.fill if price is None else price)
        notional = trade.q0 * trade.decision_price
        room = limit - gross
        scale = 1.0 if notional <= room else max(room, 0.0) / notional
        decisions[trade_key(trade)] = CapDecision(scale, gross, notional)
        if scale > 0.0:
            held.append((trade, scale))
    return decisions
