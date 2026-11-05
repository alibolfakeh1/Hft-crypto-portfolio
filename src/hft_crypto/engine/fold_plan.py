"""The dates of docs/decisions/FOLD_PLAN_2026-11-05.md, and the one rule that keeps a run inside them.

A run names its date range, and its configuration names the blocks opened so far. A range outside those
blocks is refused. Naming a block here is not enough to read it: test blocks open in calendar order with no
skipping, and the locked block opens only after them. Who may open a block is the owner's written decision,
under section 3 of the plan. Code cannot see that decision, so it holds the order and the configuration holds
the claim, in versioned text.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from hft_crypto.config import ConfigError
from hft_crypto.engine.config import DateRange


@dataclass(frozen=True)
class Block:
    name: str
    first: dt.date
    last: dt.date
    label: str


def _quarter(name: str, first: dt.date, last: dt.date) -> Block:
    return Block(name, first, last, f"TEST BLOCK {name}")


FIRST_TRAINING_SPAN = Block(
    "first_training_span", dt.date(2020, 1, 1), dt.date(2023, 12, 31), "FIRST TRAINING SPAN, IN-SAMPLE"
)
PLAN_ORDER = (
    FIRST_TRAINING_SPAN,
    _quarter("2024-Q1", dt.date(2024, 1, 1), dt.date(2024, 3, 31)),
    _quarter("2024-Q2", dt.date(2024, 4, 1), dt.date(2024, 6, 30)),
    _quarter("2024-Q3", dt.date(2024, 7, 1), dt.date(2024, 9, 30)),
    _quarter("2024-Q4", dt.date(2024, 10, 1), dt.date(2024, 12, 31)),
    _quarter("2025-Q1", dt.date(2025, 1, 1), dt.date(2025, 3, 31)),
    _quarter("2025-Q2", dt.date(2025, 4, 1), dt.date(2025, 6, 30)),
    _quarter("2025-Q3", dt.date(2025, 7, 1), dt.date(2025, 9, 30)),
    Block(
        "locked_block",
        dt.date(2025, 10, 1),
        dt.date(2026, 9, 30),
        "LOCKED BLOCK, read on 10 listed days (D-27)",
    ),
)
# Generated dates sit before either asset existed, so they can only ever mean generated data.
GENERATED_BLOCK = Block("generated", dt.date(1990, 1, 1), dt.date(2019, 12, 31), "")


def opened_blocks(names: tuple[str, ...], data_kind: str) -> tuple[Block, ...]:
    """The blocks a configuration claims are open, checked against the plan's order."""
    if not names:
        raise ConfigError("run: opened_blocks names no block, so no date can be read")
    if data_kind == "SYNTHETIC":
        if names != (GENERATED_BLOCK.name,):
            raise ConfigError("a generated run opens only the generated block, and no block of the plan")
        return (GENERATED_BLOCK,)
    if GENERATED_BLOCK.name in names:
        raise ConfigError("the generated block is not a block of the plan")
    order = [block.name for block in PLAN_ORDER]
    unknown = sorted(set(names) - set(order))
    if unknown:
        raise ConfigError(f"run: opened_blocks names blocks the plan does not have: {unknown}")
    if list(names) != order[: len(names)]:
        raise ConfigError("run: blocks open in the plan's calendar order, with no skipping")
    return PLAN_ORDER[: len(names)]


def check_range(date_range: DateRange, names: tuple[str, ...], data_kind: str) -> tuple[Block, ...]:
    """Refuse a range reaching outside what is open. Returns the blocks it touches."""
    blocks = opened_blocks(names, data_kind)
    first, last = blocks[0].first, blocks[-1].last
    if date_range.start < first or date_range.end > last:
        raise ConfigError(
            f"the range {date_range.start} to {date_range.end} reaches outside the opened dates, "
            f"{first} to {last}, so this run is refused"
        )
    return tuple(
        block for block in blocks if block.first <= date_range.end and block.last >= date_range.start
    )


def span_labels(blocks: tuple[Block, ...]) -> tuple[str, ...]:
    return tuple(block.label for block in blocks if block.label)
