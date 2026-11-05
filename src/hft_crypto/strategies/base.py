"""The interface between a strategy and the engine, and the helpers every strategy shares.

A strategy has two jobs at each close of its timeframe. `on_close` updates its registers and proposes setups.
`manage` looks at one open position and says what the document's rules want: an exit, stop candidates, and
target moves. It decides nothing else. It cannot apply a stop, because only the engine moves a stop, through
the C8 ratchet, from the next minute on.

**Both sides from one code path.** Rules are written once for a long, on prices multiplied by the side: `s *
p`. A short's high is then `-L`, its low is `-H`, and every "above" reads the same way, so a mirror cannot
drift. Values are converted back with the same multiplication before they reach the engine.

**A close with no setup says why.** Each close adds one reason to a count: an input that is undefined, or a
pattern that did not appear. Too little history therefore gives zero setups and a logged reason, under C3, and
never a loosened version of the rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, ClassVar

from hft_crypto.engine.market import MarketView
from hft_crypto.engine.tape import Bar

LONG = 1
SHORT = -1
SIDES = (LONG, SHORT)
# A target's quantity. A fraction of the original position, or everything still open.
REST = None

UNDEFINED_ATR = "ATR_UNDEFINED"
UNDEFINED_VR = "VR_UNDEFINED"
UNDEFINED_SRV = "SRV_UNDEFINED"
UNDEFINED_ATRD = "ATRD_UNDEFINED"
NO_LEVELS = "PRIOR_PERIOD_LEVELS_UNDEFINED"
NO_PATTERN = "NO_PATTERN"
NOT_ON_T0 = "NEEDS_T1_TRADES"
BAR_GAP = "BAR_HAS_A_GAP"
BREAK_EVEN = "BREAK_EVEN"
INVALIDATION = "INVALIDATION"
TIME_STOP = "TIME_STOP"


@dataclass(frozen=True)
class TargetPlan:
    name: str
    price: float | None
    fraction: float | None


@dataclass(frozen=True)
class Proposal:
    """A setup under C5, in real prices. `memo` is the strategy's own record for this trade."""

    side: int
    s0: float
    targets: tuple[TargetPlan, ...]
    level: dict[str, Any]
    expiry_bars: int
    memo: Any
    tag: str | None = None


@dataclass(frozen=True)
class StopCandidate:
    value: float
    reason: str


@dataclass(frozen=True)
class TargetMove:
    name: str
    price: float | None
    reason: str
    # False leaves the planned quantity as it is.
    set_fraction: bool = False
    fraction: float | None = None


@dataclass
class Management:
    exit_reason: str | None = None
    exit_note: str = ""
    stops: list[StopCandidate] = field(default_factory=list)
    targets: list[TargetMove] = field(default_factory=list)


class PositionView:
    """A strategy's read-only view of its own open position, as of the current close."""

    __slots__ = ("_position",)

    def __init__(self, position: Any) -> None:
        self._position = position

    @property
    def side(self) -> int:
        return int(self._position.side)

    @property
    def fill(self) -> float:
        return float(self._position.fill)

    @property
    def r(self) -> float:
        return float(self._position.r)

    @property
    def n(self) -> int:
        return int(self._position.n)

    @property
    def stop(self) -> float:
        return float(self._position.stop_planned)

    @property
    def memo(self) -> Any:
        return self._position.memo

    @property
    def fill_us(self) -> int:
        return int(self._position.fill_us)

    @property
    def highest(self) -> float:
        """Highest price seen since the fill, for this side: `s * p` at its largest."""
        return float(self._position.best)

    @property
    def fill_side(self) -> float:
        """The fill as this side sees it: `s * fill`."""
        return float(self._position.side * self._position.fill)

    def target(self, name: str) -> float | None:
        price: float | None = self._position.planned_target(name)
        return price

    def filled(self, name: str) -> bool:
        result: bool = self._position.target_filled(name)
        return result

    @property
    def be_plus(self) -> float:
        """C8, in real price."""
        value: float = self._position.be_plus
        return value


class Strategy(ABC):
    """One strategy, for one symbol, for one run. It holds its registers and nothing else."""

    id: str = ""
    version: str = "1"
    # What this strategy needs before a setup can exist. Printed with every result.
    requirements: tuple[str, ...] = ()
    live_comparable: bool = True
    # C18, by decision timeframe in minutes.
    h_max_hours: ClassVar[dict[int, float]] = {}

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params
        self.timeframe_minutes = int(params["timeframe_minutes"])
        self.reasons: Counter[str] = Counter()
        self.log_buffer: list[dict[str, Any]] = []

    @property
    def higher_minutes(self) -> tuple[int, ...]:
        return ()

    @property
    def h_max_us(self) -> int:
        """C18's maximum possible hold. The fold plan leaves out a setup that would pass the span's end."""
        return int(self.h_max_hours[self.timeframe_minutes] * 3_600_000_000)

    def note(self, reason: str) -> None:
        self.reasons[reason] += 1

    def log(self, kind: str, **fields: Any) -> None:
        self.log_buffer.append({"type": kind, **fields})

    def missing(self, bar: Bar, *names: str) -> str | None:
        """The first required input undefined at this close, which then fails the setup under C3."""
        for name in names:
            if name == "atr" and bar.atr is None:
                return UNDEFINED_ATR
            if name == "vr" and bar.vr is None:
                return UNDEFINED_VR
            if name == "srv" and bar.srv is None:
                return UNDEFINED_SRV
            if name == "atrd" and bar.atrd is None:
                return UNDEFINED_ATRD
        return None

    @abstractmethod
    def on_close(self, market: MarketView) -> list[Proposal]:
        """Update registers from the newly closed bar, and return any setups."""

    @abstractmethod
    def manage(self, market: MarketView, position: PositionView) -> Management:
        """C7's three steps at a close: invalidation, time stops, and stop and target updates."""

    def missing_tier(self, market: MarketView) -> bool:
        """A strategy that needs trades gives no result on candles, and nothing stands in for them."""
        if market.tier == "T0":
            self.note(NOT_ON_T0)
            return True
        return False

    def on_fill(self, position: PositionView) -> list[TargetMove]:
        """Targets set from the real fill, which rule the fill bar. Only S10 uses this, and it says so."""
        del position
        return []

    def notify_sent(self, proposal: Proposal) -> None:
        """The engine has sent this setup's entry, so a one-trade-per-level rule can count it."""
        del proposal

    def snapshot(self) -> dict[str, Any]:
        """The registers as of now, in plain values, for the truncation test that C4 requires."""
        return {}


def clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def sided(bar: Bar, side: int) -> tuple[float, float, float, float]:
    """(open, high, low, close) as this side sees them."""
    if side == LONG:
        return bar.o, bar.h, bar.l, bar.c
    return -bar.o, -bar.l, -bar.h, -bar.c


def sided_clv(bar: Bar, side: int) -> float:
    return bar.clv if side == LONG else 1.0 - bar.clv


def ratio_buffer(k: float, vr: float | None) -> float | None:
    """The common `k * clip(VR, 0.8, 1.5)`. Undefined when VR is."""
    return None if vr is None else k * clip(vr, 0.8, 1.5)
