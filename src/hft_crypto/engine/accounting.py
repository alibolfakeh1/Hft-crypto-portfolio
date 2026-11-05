"""Every cash flow is booked once, in whole cents, so that trades and equity reconcile exactly.

Money is an integer here. Price profit and loss, fees and funding are each rounded to the cent when they are
booked, and every total is a sum of those integers. Nothing is summed in floating point and rounded
afterwards, because that is how a report ends up a few cents away from its own trade list.

C10: `money P&L = q0 * sum(f_i * (X_i - fill)) - fees - funding`, with price slippage already inside `fill`
and
`X_i`, so it is never counted twice. Gross here is the same trade before any cost: entry at the fill reference
and exit at the exit reference, before slippage. So for every trade, and every total:

    net = gross - slippage - fees - funding
"""

from __future__ import annotations

from dataclasses import dataclass


def to_cents(money: float) -> int:
    return round(money * 100.0)


def from_cents(cents: int) -> float:
    return cents / 100.0


@dataclass(frozen=True, slots=True)
class ExitLeg:
    """Part of a position leaving. `open_at_end` marks a valuation of what is still held at the end of the
    data.
    """

    event_us: int
    reference: float
    price: float
    qty: float
    fee_rate: float
    reason: str
    open_at_end: bool = False


@dataclass(frozen=True, slots=True)
class FundingCharge:
    """A settlement passed while the position was open. Positive `rate` means longs pay."""

    settle_us: int
    rate: float
    qty: float
    mark: float


@dataclass(frozen=True, slots=True)
class CashEvent:
    """One booked flow. `gross` is before slippage, `price_pnl` after it, and fees and funding are costs."""

    event_us: int
    qty_after: float
    gross: int
    price_pnl: int
    fees: int
    funding: int

    @property
    def net(self) -> int:
        return self.price_pnl - self.fees - self.funding


@dataclass(frozen=True, slots=True)
class Booked:
    """A trade's totals in cents, at one size."""

    gross: int
    slippage: int
    fees: int
    funding: int
    net: int


def book_trade(
    *,
    side: int,
    entry_us: int,
    fill_reference: float,
    fill: float,
    q0: float,
    entry_fee_rate: float,
    legs: tuple[ExitLeg, ...],
    funding: tuple[FundingCharge, ...],
    scale: float = 1.0,
) -> tuple[list[CashEvent], Booked]:
    """All of a trade's cash events in time order, and its totals. `scale` is the portfolio's size factor."""
    entry_fee = to_cents(q0 * scale * fill * entry_fee_rate)
    events = [CashEvent(entry_us, q0 * scale, 0, 0, entry_fee, 0)]
    timeline: list[tuple[int, int, ExitLeg | FundingCharge]] = [(leg.event_us, 1, leg) for leg in legs] + [
        (charge.settle_us, 0, charge) for charge in funding
    ]
    timeline.sort(key=lambda item: (item[0], item[1]))
    qty = q0
    for event_us, _, item in timeline:
        if isinstance(item, FundingCharge):
            paid = to_cents(side * item.qty * scale * item.mark * item.rate)
            events.append(CashEvent(event_us, qty * scale, 0, 0, 0, paid))
            continue
        qty -= item.qty
        leg_qty = item.qty * scale
        events.append(
            CashEvent(
                event_us,
                max(qty, 0.0) * scale,
                to_cents(side * leg_qty * (item.reference - fill_reference)),
                to_cents(side * leg_qty * (item.price - fill)),
                to_cents(leg_qty * item.price * item.fee_rate),
                0,
            )
        )
    gross = sum(event.gross for event in events)
    price_pnl = sum(event.price_pnl for event in events)
    fees = sum(event.fees for event in events)
    paid_funding = sum(event.funding for event in events)
    return events, Booked(
        gross=gross,
        slippage=gross - price_pnl,
        fees=fees,
        funding=paid_funding,
        net=price_pnl - fees - paid_funding,
    )


def unrealised_cents(side: int, qty: float, fill: float, mark: float) -> int:
    """What the open quantity would book at a mark, with the same rounding a closing leg gets."""
    return to_cents(side * qty * (mark - fill))
