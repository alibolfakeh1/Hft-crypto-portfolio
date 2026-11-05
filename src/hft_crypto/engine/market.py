"""What a strategy is given: a view that holds only what has been released to it.

The simulator appends one closed bar at a time to lists it owns, and hands the strategy this view. The rows
and bars still to come stay in the simulator's own local variables, so there is nothing here to reach for. A
trade read is refused past the current close. No frame or table is ever passed to a strategy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from hft_crypto.bars.core import TimingContractError
from hft_crypto.engine.tape import Bar, TradeTape

_FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class TradeSlice:
    """Trades in one stretch of time that has already passed."""

    price: _FloatArray
    qty: _FloatArray


class FrameView:
    """The closed bars of one timeframe, up to the current close."""

    def __init__(self, minutes: int) -> None:
        self.minutes = minutes
        self.bars: list[Bar] = []
        self.has_new_bar = False

    def _release(self, bar: Bar) -> None:
        self.bars.append(bar)
        self.has_new_bar = True

    def _settle(self) -> None:
        self.has_new_bar = False

    @property
    def last(self) -> Bar:
        return self.bars[-1]


class MarketView:
    """All a strategy may know at one close of its decision timeframe."""

    def __init__(
        self,
        *,
        symbol: str,
        tick: float,
        rt: float,
        minutes: int,
        higher: tuple[int, ...],
        trades: TradeTape | None,
    ) -> None:
        self.symbol = symbol
        self.tick = tick
        self.rt = rt
        self.now_us = 0
        self._primary = FrameView(minutes)
        self._higher = {value: FrameView(value) for value in higher}
        self._trades = trades

    @property
    def tier(self) -> str:
        return "T0" if self._trades is None else "T1"

    @property
    def bars(self) -> list[Bar]:
        return self._primary.bars

    @property
    def bar(self) -> Bar:
        return self._primary.bars[-1]

    def higher(self, minutes: int) -> FrameView:
        return self._higher[minutes]

    def r_min(self, a: float) -> float:
        """C9. Only called once ATR is known to be defined at this close."""
        atr = self.bar.atr
        if atr is None:
            raise TimingContractError("R_min was asked for at a close with no ATR")
        return max(a * atr, 4.0 * self.rt * self.bar.c)

    def trades_between(self, after_us: int, through_us: int) -> TradeSlice:
        """Trades stamped in (after, through]. Refused past the current close, and on a T0 run."""
        if through_us > self.now_us:
            raise TimingContractError("a strategy asked for trades after its own close")
        tape = self._trades
        if tape is None:
            raise TimingContractError("this run is tier T0 and holds no trades")
        first = int(np.searchsorted(tape.ts_us, after_us, side="right"))
        end = int(np.searchsorted(tape.ts_us, through_us, side="right"))
        return TradeSlice(tape.price[first:end], tape.qty[first:end])

    # ---- the simulator's side of the view -----------------------------------------------------------------

    def _release(self, bar: Bar, higher: dict[int, Bar | None]) -> None:
        self.now_us = bar.close_us
        self._primary._release(bar)
        for minutes, view in self._higher.items():
            view._settle()
            new_bar = higher.get(minutes)
            if new_bar is not None:
                view._release(new_bar)
