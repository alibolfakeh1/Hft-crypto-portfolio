"""Leak tests for every strategy: truncation invariance and future perturbation, on generated data.

What a run knew at a moment must not depend on anything after it. So each strategy is run on the whole market,
and again on data cut at a moment or with everything after that moment replaced by noise. Up to that moment,
every decision, every fill and every register must be exactly the same.

The cuts are the strategy's own decision moments, taken from its full run: exactly when a setup becomes
knowable, one microsecond before, and inside the trade that follows. A leak at a decision shows there, and on
no fixed date. Each test first requires that the run did something, because a test on a strategy that never
traded proves nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

import polars as pl
import pytest

from engine_helpers import (
    DAY,
    DELAY_US,
    MINUTE,
    generated_trades,
    perturb_after,
    run_stream,
    tape_and_trades,
    utc,
)
from hft_crypto.engine.market import MarketView
from hft_crypto.engine.simulator import StreamResult
from hft_crypto.strategies.base import Proposal, Strategy
from hft_crypto.strategies.s03_market_structure import S03MarketStructure

START = utc(2000, 1, 1)
STRATEGIES = ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")
# A seed is picked for how much of the rule it exercises, and for nothing else. S05 is rare, so it runs
# longer.
SEEDS = dict.fromkeys(STRATEGIES, 7) | {"S05": 10, "S04": 6}
DAYS = dict.fromkeys(STRATEGIES, 150) | {"S05": 200}
# These two happen at the end of the data or describe a finished trade, so they are reports and not decisions.
NOT_DECISIONS = frozenset({"GAP_UNRESOLVED", "ENTRY_UNFILLED_AT_END"})


@dataclass(frozen=True)
class Run:
    events: list[dict[str, Any]]
    snapshots: dict[int, str]
    stream: StreamResult


def _market(strategy: str) -> pl.DataFrame:
    return _trades(SEEDS[strategy], DAYS[strategy])


@lru_cache(maxsize=4)
def _trades(seed: int, days: int) -> pl.DataFrame:
    return generated_trades(seed=seed, start_us=START, days=days)


def _decisions(events: list[dict[str, Any]], cut_us: int) -> list[dict[str, Any]]:
    return [
        event for event in events if event["knowable_us"] <= cut_us and event["type"] not in NOT_DECISIONS
    ]


def _run(strategy: str, trades: pl.DataFrame, through_us: int) -> Run:
    tape, tape_trades = tape_and_trades(trades, start_us=START, through_us=through_us)
    snapshots: dict[int, str] = {}

    def probe(held: Strategy, market: MarketView) -> None:
        snapshots[market.now_us] = json.dumps(held.snapshot(), sort_keys=True)

    stream = run_stream(strategy, tape, tape_trades, probe=probe)
    return Run(stream.events, snapshots, stream)


@lru_cache(maxsize=12)
def _full(strategy: str) -> Run:
    return _run(strategy, _market(strategy), START + DAYS[strategy] * DAY)


def _cuts(strategy: str) -> list[int]:
    """Moments around this strategy's own first setups, and one inside the trade after each."""
    created = [event for event in _full(strategy).events if event["type"] == "SETUP_CREATED"]
    assert created, f"{strategy} made no setup on this market, so this test would prove nothing"
    cuts: list[int] = []
    for event in created[:2]:
        decided = event["computed_at_us"] + DELAY_US
        cuts += [decided, decided - 1, decided + 90 * MINUTE]
    return cuts


def _last_decided_close(snapshots: dict[int, str], cut_us: int) -> int | None:
    closes = [close for close in snapshots if close + DELAY_US <= cut_us]
    return max(closes) if closes else None


def _assert_same_up_to(full: Run, other: Run, cut_us: int, label: str) -> None:
    assert _decisions(full.events, cut_us) == _decisions(other.events, cut_us), label
    close = _last_decided_close(full.snapshots, cut_us)
    if close is not None:
        assert full.snapshots[close] == other.snapshots[close], f"{label}: register at {close}"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_truncation_invariance(strategy: str) -> None:
    """C4 and C17: decisions and registers, with all data after a moment removed, are the same as of that
    moment."""
    full = _full(strategy)
    for cut in _cuts(strategy):
        truncated = _run(strategy, _market(strategy).filter(pl.col("ts").dt.timestamp("us") <= cut), cut)
        _assert_same_up_to(full, truncated, cut, f"{strategy} cut at {cut}")


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("seed", [101, 202])
def test_future_perturbation(strategy: str, seed: int) -> None:
    """Replacing everything after a moment with wild noise changes nothing known at that moment."""
    full = _full(strategy)
    trades = _market(strategy)
    last = START + DAYS[strategy] * DAY
    for cut in _cuts(strategy)[::2]:
        changed = _run(strategy, perturb_after(trades, cut, seed), last)
        _assert_same_up_to(full, changed, cut, f"{strategy} perturbed after {cut}")


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_run_is_not_vacuous(strategy: str) -> None:
    """A setup, a fill, and something after the first cut, on the market each test above uses."""
    full = _full(strategy)
    kinds = {event["type"] for event in full.events}
    assert "SETUP_CREATED" in kinds
    assert "ENTRY" in kinds
    first_cut = _cuts(strategy)[0]
    assert len(full.events) > len(_decisions(full.events, first_cut))


class _Peeker(S03MarketStructure):
    """A strategy with a leak planted in it: it shifts its stop by the next bar's close, which it must not
    know."""

    def __init__(self, params: dict[str, Any], closes: dict[int, float]) -> None:
        super().__init__(params)
        self.closes = closes

    def on_close(self, market: MarketView) -> list[Proposal]:
        proposals = super().on_close(market)
        next_close = self.closes.get(market.now_us + self.timeframe_minutes * MINUTE)
        if next_close is None:
            return proposals
        return [replace(item, s0=item.s0 - item.side * 1e-3 * next_close) for item in proposals]


def test_the_harness_catches_a_strategy_that_reads_the_next_bar() -> None:
    """If this did not fail on a real leak, the tests above would be worth nothing."""
    from engine_helpers import engine_config, sim_params
    from hft_crypto.engine.simulator import Simulator

    trades = _market("S03")
    last = START + DAYS["S03"] * DAY
    tape, tape_trades = tape_and_trades(trades, start_us=START, through_us=last)
    params = {**engine_config().strategies["S03"].default().params}
    closes = {bar.close_us: bar.c for bar in tape.frame(60)}
    full = Simulator(_Peeker(params, closes), tape, sim_params(), trades=tape_trades).run()
    created = [event for event in full.events if event["type"] == "SETUP_CREATED"]
    assert created
    decided = created[0]["computed_at_us"] + DELAY_US
    held = trades.filter(pl.col("ts").dt.timestamp("us") <= decided)
    cut_tape, cut_trades = tape_and_trades(held, start_us=START, through_us=decided)
    cut_closes = {bar.close_us: bar.c for bar in cut_tape.frame(60)}
    truncated = Simulator(_Peeker(params, cut_closes), cut_tape, sim_params(), trades=cut_trades).run()
    assert _decisions(full.events, decided) != _decisions(truncated.events, decided)


def test_changing_the_past_changes_the_decisions() -> None:
    """The other guard against a vacuous test: data before a moment must be able to change what follows it."""
    trades = _market("S03")
    last = START + DAYS["S03"] * DAY
    full = _full("S03")
    first = next(event for event in full.events if event["type"] == "SETUP_CREATED")["computed_at_us"]
    earlier = first - 20 * 3_600_000_000
    changed = trades.with_columns(
        pl.when(pl.col("ts").dt.timestamp("us").is_between(earlier, first))
        .then(pl.col("price") * 1.05)
        .otherwise(pl.col("price"))
        .alias("price")
    )
    other = _run("S03", changed, last)
    cut = first + DELAY_US
    assert _decisions(full.events, cut) != _decisions(other.events, cut)
