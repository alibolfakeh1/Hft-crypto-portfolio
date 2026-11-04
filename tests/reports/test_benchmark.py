"""Benchmark statistics against values worked out by hand."""

from __future__ import annotations

import math

import pytest

from hft_crypto.reports.benchmark import (
    annualised_volatility,
    cagr,
    compute_stats,
    max_drawdown,
    normalise_to_100,
    sharpe,
    simple_returns,
    underwater,
)


def test_normalise_starts_at_100() -> None:
    assert normalise_to_100([50.0, 55.0, 25.0]) == [100.0, 110.0, 50.0]
    assert normalise_to_100([]) == []
    with pytest.raises(ValueError, match="positive"):
        normalise_to_100([0.0, 1.0])


def test_underwater_hand_computed() -> None:
    # Peak 100, then 80 (-20%), 90 (-10%), new peak 120 (0), then 60 (-50%).
    assert underwater([100.0, 80.0, 90.0, 120.0, 60.0]) == pytest.approx([0.0, -0.2, -0.1, 0.0, -0.5])
    assert max_drawdown([100.0, 80.0, 90.0, 120.0, 60.0]) == pytest.approx(-0.5)


def test_drawdown_of_a_rising_series_is_zero() -> None:
    assert max_drawdown([1.0, 2.0, 3.0]) == 0.0
    assert max_drawdown([]) == 0.0


def test_simple_returns() -> None:
    assert simple_returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])


def test_cagr_uses_365_days() -> None:
    assert cagr(0.10, 365.0) == pytest.approx(0.10)
    # Doubling in half a year is quadrupling in a year.
    assert cagr(1.0, 182.5) == pytest.approx(3.0)
    # 1% in 30 days: 1.01^(365/30) - 1
    assert cagr(0.01, 30.0) == pytest.approx(1.01 ** (365.0 / 30.0) - 1.0)
    assert cagr(-0.5, 365.0) == pytest.approx(-0.5)
    with pytest.raises(ValueError, match="positive"):
        cagr(0.1, 0.0)


def test_volatility_hand_computed() -> None:
    # Returns 0.01 and 0.03: mean 0.02, sample variance ((0.01)^2 + (0.01)^2) / 1 = 0.0002
    expected = math.sqrt(0.0002) * math.sqrt(365.0)
    assert annualised_volatility([0.01, 0.03]) == pytest.approx(expected)
    assert annualised_volatility([0.01]) is None


def test_sharpe_hand_computed() -> None:
    expected = 0.02 / math.sqrt(0.0002) * math.sqrt(365.0)
    assert sharpe([0.01, 0.03]) == pytest.approx(expected)
    assert sharpe([0.01]) is None
    assert sharpe([0.01, 0.01]) is None


def test_annualisation_is_365_and_not_252() -> None:
    returns = [0.01, -0.02, 0.03, 0.0]
    volatility = annualised_volatility(returns)
    assert volatility is not None
    daily = math.sqrt(sum((r - 0.005) ** 2 for r in returns) / 3)
    assert volatility / daily == pytest.approx(math.sqrt(365.0))
    assert volatility / daily != pytest.approx(math.sqrt(252.0))


def test_compute_stats_hand_computed() -> None:
    # Daily 100 -> 110 -> 99 -> 108.9. Returns +10%, -10%, +10%.
    daily = [100.0, 110.0, 99.0, 108.9]
    equity = [100.0, 105.0, 110.0, 88.0, 99.0, 108.9]
    stats = compute_stats(daily, equity)
    assert stats.total_return == pytest.approx(0.089)
    assert stats.days == 3.0
    assert stats.daily_returns == 3
    assert stats.equity_marks == 6
    assert stats.cagr == pytest.approx(1.089 ** (365.0 / 3.0) - 1.0)
    # Mean 1/30, deviations of about 0.0667, 0.1333, 0.0667. Sample variance 0.01333...
    assert stats.annualised_volatility == pytest.approx(math.sqrt(0.04 / 3.0) * math.sqrt(365.0))
    assert stats.sharpe == pytest.approx((0.1 / 3.0) / math.sqrt(0.04 / 3.0) * math.sqrt(365.0))
    # Max drawdown comes from the finer marks: 110 to 88 is -20%, deeper than any daily close shows.
    assert stats.max_drawdown == pytest.approx(-0.2)


def test_compute_stats_needs_at_least_one_return() -> None:
    with pytest.raises(ValueError, match="two daily"):
        compute_stats([100.0], [100.0])
