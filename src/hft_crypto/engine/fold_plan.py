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
# Fold plan section 4, and D-41: the days already read. Their bars stay for continuity, and a range touching
# one is refused unless the configuration lists it, so a setup reaching it is left out under FP-07.
READ_DAYS = (
    dt.date(2024, 6, 1),
    dt.date(2025, 12, 1),
    dt.date(2026, 1, 1),
    dt.date(2026, 2, 1),
    dt.date(2026, 3, 1),
    dt.date(2026, 4, 1),
    dt.date(2026, 5, 1),
    dt.date(2026, 6, 1),
    dt.date(2026, 7, 1),
    dt.date(2026, 8, 1),
    dt.date(2026, 9, 1),
    *(dt.date(2026, 10, 5) + dt.timedelta(days=offset) for offset in range(30)),
    dt.date(2026, 10, 1),
    dt.date(2026, 11, 1),
)
# D-38. Every report on test or locked dates carries this sentence.
D38_SENTENCE = "About 137 MB of D-18 could not be dated. Whether it touched these dates is UNVERIFIED (D-38)"
# Fold plan section 5. A run on market data outside the candidate family, counted beside the registry's lines.
COUNTED_OUTSIDE_REGISTRY = {"D-32": 2}
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


def check_range(
    date_range: DateRange,
    names: tuple[str, ...],
    data_kind: str,
    read_days: tuple[dt.date, ...] = (),
) -> tuple[Block, ...]:
    """Refuse a range reaching outside what is open, or touching a day already read that the configuration
    does not list (EN-05). Returns the blocks it touches. What is open is checked first, so a range outside
    it is refused for that, whatever days it touches.
    """
    blocks = opened_blocks(names, data_kind)
    first, last = blocks[0].first, blocks[-1].last
    if date_range.start < first or date_range.end > last:
        raise ConfigError(
            f"the range {date_range.start} to {date_range.end} reaches outside the opened dates, "
            f"{first} to {last}, so this run is refused"
        )
    unlisted = sorted(
        day for day in READ_DAYS if date_range.start <= day <= date_range.end and day not in read_days
    )
    if unlisted:
        raise ConfigError(
            f"the range touches days already read under section 4 of the fold plan, {unlisted}, and the "
            "configuration's read_days does not list them, so this run is refused"
        )
    return tuple(
        block for block in blocks if block.first <= date_range.end and block.last >= date_range.start
    )


def span_labels(blocks: tuple[Block, ...]) -> tuple[str, ...]:
    """Each block's label. A test or locked block also carries D-38's sentence, beside the D-27 label."""
    labels = tuple(block.label for block in blocks if block.label)
    if any(block.name != FIRST_TRAINING_SPAN.name and block.label for block in blocks):
        labels = (*labels, D38_SENTENCE)
    return labels
