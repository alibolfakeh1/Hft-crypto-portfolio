"""Buy and hold benchmark statistics. All annualisation uses 365 days, because crypto trades every day.

These are not strategy results. They apply no fees, no funding and no slippage.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise
from typing import Any

import numpy as np

DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class BenchmarkStats:
    total_return: float
    cagr: float
    annualised_volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    days: float
    daily_returns: int
    equity_marks: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_to_100(prices: Sequence[float]) -> list[float]:
    """Equity of holding one unit from the first price, scaled so it starts at 100."""
    if not prices:
        return []
    first = prices[0]
    if first <= 0:
        raise ValueError("the first price must be positive")
    return [100.0 * price / first for price in prices]


def underwater(equity: Sequence[float]) -> list[float]:
    """Drawdown from the running peak at each mark, as a fraction: 0 at a peak, -0.1 for 10% below."""
    if not equity:
        return []
    series = np.asarray(equity, dtype=np.float64)
    peak = np.maximum.accumulate(series)
    return [float(value) for value in series / peak - 1.0]


def max_drawdown(equity: Sequence[float]) -> float:
    marks = underwater(equity)
    return min(marks) if marks else 0.0


def simple_returns(prices: Sequence[float]) -> list[float]:
    return [b / a - 1.0 for a, b in pairwise(prices)]


def cagr(total_return: float, days: float) -> float:
    """Compound annual growth rate on a 365-day year."""
    if days <= 0:
        raise ValueError("days must be positive")
    return float(math.pow(1.0 + total_return, DAYS_PER_YEAR / days) - 1.0)


def annualised_volatility(daily_returns: Sequence[float]) -> float | None:
    """Sample standard deviation of daily returns, times the square root of 365."""
    if len(daily_returns) < 2:
        return None
    return float(np.std(np.asarray(daily_returns), ddof=1) * math.sqrt(DAYS_PER_YEAR))


def sharpe(daily_returns: Sequence[float]) -> float | None:
    """Annualised Sharpe ratio with a zero risk-free rate. None when it is undefined."""
    if len(daily_returns) < 2:
        return None
    values = np.asarray(daily_returns)
    deviation = float(np.std(values, ddof=1))
    if deviation == 0.0:
        return None
    return float(np.mean(values) / deviation * math.sqrt(DAYS_PER_YEAR))


def compute_span_stats(
    first_price: float,
    last_price: float,
    one_day_returns: Sequence[float],
    days: float,
    equity_prices: Sequence[float],
) -> BenchmarkStats:
    """Statistics over a span that may hold holes.

    Total return and CAGR run from the first price to the last across any hole, over the calendar days between
    them. Volatility and Sharpe use only one-day returns, so a return across a hole never counts as one day.
    Max drawdown uses the marks that exist.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    total = last_price / first_price - 1.0
    equity = normalise_to_100(equity_prices)
    return BenchmarkStats(
        total_return=total,
        cagr=cagr(total, days),
        annualised_volatility=annualised_volatility(one_day_returns),
        sharpe=sharpe(one_day_returns),
        max_drawdown=max_drawdown(equity),
        days=days,
        daily_returns=len(one_day_returns),
        equity_marks=len(equity),
    )


def compute_stats(daily_prices: Sequence[float], equity_prices: Sequence[float]) -> BenchmarkStats:
    """Statistics from daily marks with no holes, and from finer equity marks over the same span.

    Total return, CAGR, volatility and Sharpe use the daily marks. Max drawdown uses the finer marks, so it
    agrees with the chart. Both series must start and end on the same price.
    """
    if len(daily_prices) < 2:
        raise ValueError("at least two daily prices are needed")
    return compute_span_stats(
        daily_prices[0],
        daily_prices[-1],
        simple_returns(daily_prices),
        float(len(daily_prices) - 1),
        equity_prices,
    )
