"""C13's `V0S` control, as rows of its own, each beside the `V0` line it shares its setups with.

A `V0S` row is a control. It is never in the portfolio figure, it ranks nothing, and it counts as no trial.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

from hft_crypto.engine.accounting import to_cents
from hft_crypto.engine.config import EngineConfig
from hft_crypto.engine.simulator import StreamResult
from hft_crypto.reports.portfolio import _full_section, _section, _trade_row, row_label, stream_status
from hft_crypto.strategies import strategy_class
from hft_crypto.strategies.v0s import VARIANT_V0S

_IntArray = npt.NDArray[np.int64]
_FloatArray = npt.NDArray[np.float64]
NOTE = (
    "V0S, C13: the same setups as V0, one fixed target at fill + m * R and a fixed hold, with no update of "
    "any kind. A control: never in the portfolio figure, and no trial"
)
BESIDE = (
    "trades",
    "gross_pnl",
    "net_pnl",
    "gross_result_b_total",
    "net_result_b_total",
    "avg_gross_r",
    "avg_net_r",
    "win_rate",
    "max_drawdown_pct",
)


def _taken(stream: StreamResult) -> set[tuple[int, int]]:
    """The setups a stream sent: created, and not skipped because a position was open."""
    created = {
        (event["computed_at_us"], event["side"])
        for event in stream.events
        if event["type"] == "SETUP_CREATED"
    }
    skipped = {
        (event["computed_at_us"], event["side"]) for event in stream.events if event["type"] == "SKIPPED_OPEN"
    }
    return created - skipped


def _compared(v0: StreamResult | None, v0s: StreamResult) -> dict[str, int] | None:
    """C13: each is its own stream, so a setup can be taken in one and skipped in the other. Printed as
    counts."""
    if v0 is None:
        return None
    first, second = _taken(v0), _taken(v0s)
    return {
        "taken_in_both": len(first & second),
        "taken_in_v0_only": len(first - second),
        "taken_in_v0s_only": len(second - first),
    }


def v0s_rows(
    v0: Sequence[StreamResult],
    v0s: Sequence[StreamResult],
    *,
    config: EngineConfig,
    labels: Sequence[str],
    axis: _IntArray,
    marks: dict[str, _FloatArray],
) -> list[dict[str, Any]]:
    """One row per line and asset, in the order they ran."""
    label = row_label(config, labels)
    shared: dict[str, Any] = {
        "axis": axis,
        "marks": marks,
        "capital_cents": to_cents(config.risk.capital),
        "rt_bps": config.costs.rt_bps,
    }
    beside = {(stream.strategy, stream.line, stream.symbol): stream for stream in v0}
    rows: list[dict[str, Any]] = []
    for stream in v0s:
        cls = strategy_class(stream.strategy)
        hold = cls.v0s_hold_bars.get(stream.timeframe_minutes)
        twin = beside.get((stream.strategy, stream.line, stream.symbol))
        twin_section = None if twin is None else _section(twin.trades, **shared)
        rows.append(
            {
                "label": label,
                "variant": VARIANT_V0S,
                "note": NOTE,
                "strategy": stream.strategy,
                "line": stream.line,
                "is_default": stream.is_default,
                "in_portfolio": False,
                "asset": stream.symbol,
                "status": stream_status(stream),
                "m": cls.v0s_m,
                "hold_bars": hold,
                "hold_rule": "the hard flat at T_flat"
                if hold is None
                else f"{hold} bars, then the next open",
                "setups": stream.setups,
                "no_setup_reasons": stream.reasons,
                "counters": stream.counters,
                **_full_section(stream.trades, **shared),
                "beside_v0": None if twin_section is None else {key: twin_section.get(key) for key in BESIDE},
                "setups_taken": _compared(twin, stream),
            }
        )
    return rows


def v0s_trade_rows(
    v0s: Sequence[StreamResult], *, config: EngineConfig, labels: Sequence[str]
) -> list[dict[str, Any]]:
    label = row_label(config, labels)
    rows = []
    for stream in v0s:
        for trade in stream.trades:
            row = _trade_row(trade, label, {})
            row["variant"] = VARIANT_V0S
            row["in_portfolio"] = False
            rows.append(row)
    return rows
