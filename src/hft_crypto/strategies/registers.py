"""Swing pivots and the swing register of convention C4.

The register is event-sourced and only ever appended to, one close at a time. A swing is knowable at the
close of its last right bar, and nothing about it exists before that. Because bars arrive in order, the
register as it stands at a close is the as-of state at that close. Truncation invariance is tested for every
strategy that uses one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hft_crypto.engine.tape import Bar

HIGH = "H"
LOW = "L"


def against(side: int) -> str:
    """The kind of swing behind a position of this side: a long stands on lows."""
    return LOW if side > 0 else HIGH


def towards(side: int) -> str:
    return HIGH if side > 0 else LOW


@dataclass
class Swing:
    kind: str
    price: float
    bar_index: int
    extreme_close_us: int
    valid_from: int
    valid_to: int | None = None
    broken_at: int | None = None
    # The price of the entry of this kind before it, when this one was added.
    previous_price: float | None = None


class SwingList:
    """`Sigma(Lf, Rt, a)`, with the amplitude test on the list's own timeframe."""

    def __init__(self, lf: int, rt: int, a: float) -> None:
        self.lf = lf
        self.rt = rt
        self.a = a
        self.entries: list[Swing] = []

    def update(self, bars: list[Bar]) -> list[Swing]:
        """Add any swing confirmed at the newest close. Returns those added."""
        k = len(bars) - 1
        i = k - self.rt
        if i - self.lf < 0:
            return []
        window = bars[i - self.lf : k + 1]
        # A bar a formula needs is missing, so the object is not computed, under C2.
        if any(bar.gap for bar in window):
            return []
        atr = bars[k].atr_last
        if atr is None:
            return []  # Before the first seed no such value exists, so the swing is ignored, under C3.
        center = bars[i]
        left = bars[i - self.lf : i]
        right = bars[i + 1 : k + 1]
        is_high = center.h > max(bar.h for bar in left) and center.h >= max(bar.h for bar in right)
        is_low = center.l < min(bar.l for bar in left) and center.l <= min(bar.l for bar in right)
        order = (HIGH, LOW) if center.c >= center.o else (LOW, HIGH)
        added: list[Swing] = []
        for kind in order:
            if (kind == HIGH and is_high) or (kind == LOW and is_low):
                price = center.h if kind == HIGH else center.l
                swing = self._add(kind, price, i, center.close_us, bars[k].close_us, atr)
                if swing is not None:
                    added.append(swing)
        return added

    def _add(self, kind: str, price: float, index: int, extreme: int, now: int, atr: float) -> Swing | None:
        last = self.entries[-1] if self.entries else None
        previous = self.latest(kind)
        swing = Swing(
            kind, price, index, extreme, now, previous_price=None if previous is None else previous.price
        )
        if last is None:
            self.entries.append(swing)
            return swing
        if last.kind == kind:
            more_extreme = price > last.price if kind == HIGH else price < last.price
            if not more_extreme:
                return None
            last.valid_to = now
            self.entries.append(swing)
            return swing
        if abs(price - last.price) >= self.a * atr:
            self.entries.append(swing)
            return swing
        return None

    def visible(self, kind: str) -> list[Swing]:
        """Entries of a kind that stand now, oldest first."""
        return [entry for entry in self.entries if entry.kind == kind and entry.valid_to is None]

    def latest(self, kind: str) -> Swing | None:
        for entry in reversed(self.entries):
            if entry.kind == kind and entry.valid_to is None:
                return entry
        return None

    def latest_two(self, kind: str, before_us: int | None = None) -> tuple[Swing | None, Swing | None]:
        """The two latest of a kind, optionally only those confirmed before a moment."""
        found: list[Swing] = []
        for entry in reversed(self.entries):
            if entry.kind != kind or entry.valid_to is not None:
                continue
            if before_us is not None and entry.valid_from >= before_us:
                continue
            found.append(entry)
            if len(found) == 2:
                break
        return (found[0] if found else None, found[1] if len(found) > 1 else None)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "kind": entry.kind,
                "price": entry.price,
                "index": entry.bar_index,
                "valid_from": entry.valid_from,
                "valid_to": entry.valid_to,
                "broken_at": entry.broken_at,
            }
            for entry in self.entries
        ]
