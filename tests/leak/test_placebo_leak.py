"""Leak tests for the C15 placebos: what a draw decided up to a moment must not depend on anything after it.

Two groups, because C15 itself separates them.

- **A level placebo and S09's shift** draw at the close, from earlier blocks or from nothing. They must be
  the same at any moment, including the moments around their own decisions.
- **S03, S07 and S10** take their counts, their side share and their eligible bars from the block they fall
  in. C15 declares that as same-block information, so inside a block these are not causal by design. They must
  still be the same at any **block boundary**: nothing in a later block may change a draw in an earlier one.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import polars as pl
import pytest

from engine_helpers import (
    DAY,
    DELAY_US,
    MINUTE,
    engine_config,
    generated_trades,
    perturb_after,
    run_stream,
    sim_params,
    tape_and_trades,
    utc,
)
from hft_crypto.engine.placebo import build_plan, simulate_draw
from hft_crypto.engine.simulator import StreamResult, SymbolData
from hft_crypto.strategies.sources import quarter_of

START = utc(2000, 1, 3)
DAYS = 230
END = START + DAYS * DAY
Q3_STARTS = utc(2000, 7, 1)
ANY_MOMENT = ("S01", "S02", "S04", "S05", "S06", "S08", "S09")
BLOCK_BOUNDARY = ("S03", "S07", "S10")
NOT_DECISIONS = frozenset({"GAP_UNRESOLVED", "ENTRY_UNFILLED_AT_END"})
# A seed is picked for how much of the rule it exercises, and for nothing else. S05's flips are rare.
SEEDS = {"S04": 6, "S05": 13}
DEFAULT_SEED = 7


@dataclass(frozen=True)
class Draw:
    events: list[dict[str, Any]]
    stream: StreamResult


@lru_cache(maxsize=3)
def _seeded(seed: int) -> pl.DataFrame:
    return generated_trades(seed=seed, start_us=START, days=DAYS)


def _trades(strategy: str) -> pl.DataFrame:
    return _seeded(SEEDS.get(strategy, DEFAULT_SEED))


def _quarters(through_us: int) -> list[int]:
    return list(range(quarter_of(START), quarter_of(through_us - 1) + 1))


def _draw(strategy: str, trades: pl.DataFrame, through_us: int, draw: int = 1) -> Draw:
    tape, tape_trades = tape_and_trades(trades, start_us=START, through_us=through_us)
    item = SymbolData(tape, tape_trades, ())
    line = engine_config().strategies[strategy].default()
    real = run_stream(strategy, tape, tape_trades)
    plan = build_plan(
        strategy,
        "S",
        line,
        item=item,
        sim=sim_params(),
        quarters=_quarters(through_us),
        real=real,
    )
    stream, _ = simulate_draw(plan, draw, item)
    return Draw(stream.events, stream)


@lru_cache(maxsize=12)
def _full(strategy: str) -> Draw:
    return _draw(strategy, _trades(strategy), END)


def _decisions(events: list[dict[str, Any]], cut_us: int) -> list[dict[str, Any]]:
    return [
        event for event in events if event["knowable_us"] <= cut_us and event["type"] not in NOT_DECISIONS
    ]


def _own_moments(strategy: str) -> list[int]:
    """Around this draw's first setups, since a leak at a decision shows there and on no fixed date."""
    created = [event for event in _full(strategy).events if event["type"] == "SETUP_CREATED"]
    assert created, f"{strategy}: this draw made no setup, so this test would prove nothing"
    moments: list[int] = []
    for event in created[:2]:
        decided = event["computed_at_us"] + DELAY_US
        moments += [decided, decided - 1, decided + 90 * MINUTE]
    return moments


@pytest.mark.parametrize("strategy", ANY_MOMENT)
def test_truncation_invariance_at_any_moment(strategy: str) -> None:
    full = _full(strategy)
    for cut in _own_moments(strategy):
        held = _trades(strategy).filter(pl.col("ts").dt.timestamp("us") <= cut)
        truncated = _draw(strategy, held, cut)
        assert _decisions(full.events, cut) == _decisions(truncated.events, cut), f"{strategy} cut at {cut}"


@pytest.mark.parametrize("strategy", ANY_MOMENT)
def test_future_perturbation_at_any_moment(strategy: str) -> None:
    full = _full(strategy)
    for cut in _own_moments(strategy)[::2]:
        changed = _draw(strategy, perturb_after(_trades(strategy), cut, 101), END)
        assert _decisions(full.events, cut) == _decisions(changed.events, cut), (
            f"{strategy} perturbed at {cut}"
        )


@pytest.mark.parametrize("strategy", BLOCK_BOUNDARY)
def test_truncation_invariance_at_a_block_boundary(strategy: str) -> None:
    full = _full(strategy)
    cut = Q3_STARTS
    held = _trades(strategy).filter(pl.col("ts").dt.timestamp("us") <= cut)
    truncated = _draw(strategy, held, cut)
    before = _decisions(full.events, cut)
    assert any(event["type"] == "SETUP_CREATED" for event in before), f"{strategy} did nothing before the cut"
    assert before == _decisions(truncated.events, cut)


@pytest.mark.parametrize("strategy", BLOCK_BOUNDARY)
def test_future_perturbation_at_a_block_boundary(strategy: str) -> None:
    full = _full(strategy)
    cut = Q3_STARTS
    changed = _draw(strategy, perturb_after(_trades(strategy), cut, 202), END)
    before = _decisions(full.events, cut)
    assert any(event["type"] == "SETUP_CREATED" for event in before), f"{strategy} did nothing before the cut"
    assert before == _decisions(changed.events, cut)


def test_changing_a_later_block_changes_the_draws_in_that_block() -> None:
    """The other guard: a draw must actually respond to the data it is allowed to read."""
    cut = Q3_STARTS
    changed = _draw("S01", perturb_after(_trades("S01"), cut, 303), END)
    assert _decisions(_full("S01").events, END) != _decisions(changed.events, END)


def test_a_level_placebo_draws_nothing_in_the_first_quarter() -> None:
    """2020-Q1's rule, on generated dates: no earlier block, so no level, so no setup."""
    for strategy in ("S01", "S02", "S04", "S05", "S06", "S08"):
        created = [event for event in _full(strategy).events if event["type"] == "SETUP_CREATED"]
        assert created
        assert all(quarter_of(event["computed_at_us"]) > quarter_of(START) for event in created)
