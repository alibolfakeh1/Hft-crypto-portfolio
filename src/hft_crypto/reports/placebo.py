"""The C15 row for each strategy and symbol, as plain JSON for a dashboard.

A rank here places a real line among its own placebo draws. It does not rank lines against each other, and a
good rank is evidence for continuing research and nothing more. Every row states the quarters it covers and
names the ones with no placebo, and the real figure uses the covered quarters alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np

from hft_crypto.engine.config import EngineConfig
from hft_crypto.engine.placebo import (
    FIRST_QUARTER,
    METHOD_ANCHORS,
    METHOD_ENTRIES,
    METHOD_LEVELS,
    METHOD_SHIFT,
    RANK_RULE,
    SEED_RULE,
    STATUS_NOT_RUN,
    DrawStat,
    MeanResult,
    PlaceboResult,
    rank_among,
)
from hft_crypto.reports.portfolio import row_label

_METHOD_NOTES = {
    METHOD_LEVELS: (
        "Levels are drawn at the real level's knowable time, in ATR units from the close then, from earlier "
        "quarters only. Kinds are not pooled, a set born together draws one earlier set's whole vector, and "
        "a band keeps the real object's width"
    ),
    METHOD_ENTRIES: (
        "Entry bars are drawn over bars passing the non-signal filters, with the real setups' long and short "
        "counts per quarter. That is same-block information. It gives the placebo the quarter's direction, "
        "which can only make it harder to beat"
    ),
    METHOD_SHIFT: (
        "Each day's whole schedule moves by a shift drawn for that day, from 1 to 23 hours, so the real "
        "window cannot occur"
    ),
    METHOD_ANCHORS: (
        "Anchors are drawn over the quarter's bars, with as many per side as its real major swings, which is "
        "same-block information"
    ),
}
_STRATEGY_NOTES = {
    "S07": "AVERAGE-PRICE, the named extra in section 10, is not built",
    "S10": "The unconditional breakout, the named extra in section 10, is not built",
}
# C15, "What a draw replaces, and what stays real". Printed beside the rank: a draw measures what the object
# adds, and says nothing of the rules that read these, which V0 against V0S reads.
_STAYS_REAL = {
    "S01": "Every trail and price extreme its rules name stays real, as in every draw",
    "S02": "Every trail and price extreme its rules name stays real, as in every draw",
    "S03": "Its swing lists, BOS and CHoCH, and every trail its rules name stay real, as in every draw",
    "S04": "HHz, the highest high since a zone's birth, and every trail its rules name stay real",
    "S05": "X and its later swings, which set its stops and its rebased target, stay real",
    "S06": "PSH and every trail its rules name stay real, as in every draw",
    "S07": "Its minor anchors, which stack its stops, stay real",
    "S08": "Its developing profile stays real, so its VALUE_MIGRATION stop and its T2 raise read real trades",
    "S09": "Its seasonal profile, range and every trail its rules name stay real, as in every draw",
    "S10": "Its band widths and every trail its rules name stay real, as in every draw",
}


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _distribution(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return dict.fromkeys(("min", "p05", "p50", "p95", "max"))
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": _round(float(array.min())),
        "p05": _round(float(np.percentile(array, 5))),
        "p50": _round(float(np.percentile(array, 50))),
        "p95": _round(float(np.percentile(array, 95))),
        "max": _round(float(array.max())),
    }


def _mean_row(mean: MeanResult) -> dict[str, Any]:
    return {
        "trades": mean.trades,
        "gross_mean_result_b": _round(mean.gross_mean),
        "net_mean_result_b": _round(mean.net_mean),
    }


def _comparison(real: MeanResult, means: Sequence[MeanResult]) -> dict[str, Any]:
    """The real line's place among the draws, gross and net, over the same quarters."""
    gross = [item.gross_mean for item in means if item.gross_mean is not None]
    net = [item.net_mean for item in means if item.net_mean is not None]
    no_trade = sum(1 for item in means if item.trades == 0)
    has_real = real.gross_mean is not None and real.net_mean is not None
    return {
        "real": _mean_row(real),
        "gross_rank": rank_among(real.gross_mean, gross) if real.gross_mean is not None else None,
        "net_rank": rank_among(real.net_mean, net) if real.net_mean is not None else None,
        "rank_of": len(gross),
        "draws_with_no_trade": no_trade,
        "rank_note": None if has_real else "The real line has no trade in these quarters, so it has no rank",
        "gross_mean_result_b": _distribution(gross),
        "net_mean_result_b": _distribution(net),
        "trades_per_draw": _distribution([float(item.trades) for item in means]),
    }


def _sum(rows: Sequence[dict[str, int]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for row in rows:
        total.update(row)
    return dict(sorted(total.items()))


def _quarter_rows(result: PlaceboResult) -> list[dict[str, Any]]:
    return [
        {
            "quarter": row.name,
            "has_placebo": row.has_placebo,
            "reason": row.reason,
            "real_setups": result.real_setups_by_quarter.get(row.quarter, 0),
            "real_trades": result.real_trades_by_quarter.get(row.quarter, 0),
        }
        for row in result.quarters
    ]


def _draw_row(stat: DrawStat) -> dict[str, Any]:
    return {
        "draw": stat.draw,
        "seed": f"{stat.seed:016x}",
        "setups": stat.setups,
        **_mean_row(stat.overall),
        "entry_shortfall": dict(sorted(stat.shortfall.items())),
    }


def _notes(result: PlaceboResult) -> list[str]:
    notes = [_METHOD_NOTES[result.swap]]
    first = [row for row in result.quarters if row.reason == FIRST_QUARTER]
    if first:
        notes.append(f"{first[0].name} is the first quarter, so it has no earlier block and no level placebo")
    if result.strategy in _STRATEGY_NOTES:
        notes.append(_STRATEGY_NOTES[result.strategy])
    return notes


def placebo_row(result: PlaceboResult, label: str) -> dict[str, Any]:
    """One row per strategy and symbol. A draw with no result is never left out without being counted."""
    without = [row.name for row in result.quarters if not row.has_placebo]
    compared_trades = sum(
        result.real_trades_by_quarter.get(row.quarter, 0) for row in result.quarters if row.has_placebo
    )
    all_trades = sum(result.real_trades_by_quarter.values())
    row: dict[str, Any] = {
        "label": label,
        "strategy": result.strategy,
        "asset": result.symbol,
        "line": result.line,
        "is_default": True,
        "params": result.params,
        "method": result.swap,
        "status": result.status,
        "reason": result.reason,
        "draws": len(result.draws),
        "quarters": _quarter_rows(result),
        "quarters_without_placebo": without,
        "real_trades_not_compared": all_trades - compared_trades,
        "seed_rule": SEED_RULE,
        "rank_rule": RANK_RULE,
        "notes": [] if result.status == STATUS_NOT_RUN else _notes(result),
        "stays_real": _STAYS_REAL[result.strategy],
        **_comparison(result.real, [stat.overall for stat in result.draws]),
        "entries_failed_and_not_replaced": _sum([stat.failures for stat in result.draws]),
        "counters": _sum([stat.counters for stat in result.draws]),
        "levels_not_placed": _sum([stat.missing for stat in result.draws]),
        # R-02: a quarter and side where a draw placed fewer entries than the real setups, summed over draws.
        "entry_shortfall": _sum([stat.shortfall for stat in result.draws]),
        "draws_with_an_entry_shortfall": sum(1 for stat in result.draws if stat.shortfall),
        "draw_rows": [_draw_row(stat) for stat in result.draws],
    }
    if result.real_by_branch or any(stat.by_branch for stat in result.draws):
        names = sorted({*result.real_by_branch, *(name for stat in result.draws for name in stat.by_branch)})
        empty = MeanResult(0, None, None)
        row["branches"] = {
            name: _comparison(
                result.real_by_branch.get(name, empty),
                [stat.by_branch.get(name, empty) for stat in result.draws],
            )
            for name in names
        }
    return row


def placebo_rows(
    results: Sequence[PlaceboResult], *, config: EngineConfig, labels: Sequence[str]
) -> list[dict[str, Any]]:
    label = row_label(config, labels)
    return [placebo_row(result, label) for result in results]


def not_requested_rows(
    *, config: EngineConfig, labels: Sequence[str], strategies: Sequence[str]
) -> list[dict[str, Any]]:
    """A dashboard reads a row that says so, and never an empty file it could take for a pass."""
    label = row_label(config, labels)
    return [
        {
            "label": label,
            "strategy": strategy,
            "asset": symbol,
            "line": config.strategies[strategy].default().line_id,
            "is_default": True,
            "status": STATUS_NOT_RUN,
            "reason": "THIS_COMMAND_DID_NOT_ASK_FOR_PLACEBOS",
            "draws": 0,
            "gross_rank": None,
            "net_rank": None,
            "rank_of": 0,
        }
        for strategy in strategies
        for symbol in config.symbols
    ]
