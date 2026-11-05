"""Plain JSON rows for a dashboard, from finished streams, following docs/04_PORTFOLIO_OUTPUTS.md.

Nothing here reads market data or decides anything. Every money figure is a sum of whole cents booked once by
`engine.accounting`, so a row, its trades and its equity marks agree exactly.

Every row states `SIMULATED`, plus `SYNTHETIC` on generated data, or the block it read on market data. Every
file opens with a header that prints the date range, the costs, the funding status, the three risk limits and
the data credit.

**No line is ranked.** Rows come in the configuration's fixed order, with the declared default first. Nothing
in this file sorts by a result, and the portfolio uses each strategy's default line because it needs one, not
because it did well.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from hft_crypto.engine.accounting import ExitLeg, from_cents, to_cents
from hft_crypto.engine.config import EngineConfig
from hft_crypto.engine.portfolio import CapDecision, TradeKey, apply_gross_cap, trade_key
from hft_crypto.engine.simulator import MODE, VARIANT, StreamResult, TradeRecord
from hft_crypto.reports.benchmark import DAYS_PER_YEAR, cagr, sharpe
from hft_crypto.timeutil import iso_us

_IntArray = npt.NDArray[np.int64]
_FloatArray = npt.NDArray[np.float64]
_Scale = Callable[[TradeRecord], float]
MICROS_PER_HOUR = 3_600_000_000
MICROS_PER_DAY = 86_400_000_000
NOT_LIVE_COMPARABLE = "NOT LIVE-COMPARABLE"
LABEL_SIMULATED = "SIMULATED"
LABEL_SYNTHETIC = "SYNTHETIC"
NO_ADVICE = "Not a test result, not a gate verdict, not investment advice. This project sends no orders."
DEFAULT_LINE_NOTE = (
    "The default line is a display order from C18. It is not a selection and makes no claim to be best"
)


def _unit(_: TradeRecord) -> float:
    return 1.0


def run_labels(config: EngineConfig, labels: Sequence[str]) -> tuple[str, ...]:
    if config.data_kind == LABEL_SYNTHETIC:
        return (LABEL_SIMULATED, LABEL_SYNTHETIC)
    return (LABEL_SIMULATED, *labels)


def row_label(config: EngineConfig, labels: Sequence[str]) -> str:
    return " ".join(run_labels(config, labels))


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


# ---- equity marks
# ---------------------------------------------------------------------------------------------


def equity_curve(
    trades: Iterable[TradeRecord],
    *,
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    capital_cents: int,
    scale_of: _Scale = _unit,
) -> _IntArray:
    """Mark-to-market equity in cents at each axis point, including open positions, fees and funding."""
    realised: _IntArray = np.zeros(axis.size, dtype=np.int64)
    unrealised: _IntArray = np.zeros(axis.size, dtype=np.int64)
    last_index = axis.size - 1
    for trade in trades:
        scale = scale_of(trade)
        if scale <= 0.0:
            continue
        events, _ = trade.book(scale)
        prices = marks[trade.symbol]
        for position, event in enumerate(events):
            first = int(np.searchsorted(axis, event.event_us, side="left"))
            if first > last_index:
                raise ValueError("a trade event lies after the end of the equity axis")
            realised[first] += event.net
            following = events[position + 1].event_us if position + 1 < len(events) else None
            stop = last_index + 1 if following is None else int(np.searchsorted(axis, following, side="left"))
            if event.qty_after <= 0.0:
                continue
            for index in range(first, min(stop, last_index + 1)):
                unrealised[index] += to_cents(
                    trade.side * event.qty_after * (float(prices[index]) - trade.fill)
                )
    equity: _IntArray = capital_cents + np.cumsum(realised) + unrealised
    return equity


def _drawdown(equity: _IntArray, axis: _IntArray) -> dict[str, Any]:
    if equity.size == 0:
        return {"max_drawdown_money": 0.0, "max_drawdown_pct": 0.0, "max_drawdown_duration_hours": 0.0}
    peak = np.maximum.accumulate(equity)
    depth = equity - peak
    longest = 0
    start: int | None = None
    for index, below in enumerate((depth < 0).tolist()):
        if below and start is None:
            start = index
        elif not below and start is not None:
            longest = max(longest, int(axis[index]) - int(axis[start]))
            start = None
    if start is not None:
        longest = max(longest, int(axis[-1]) - int(axis[start]))
    return {
        "max_drawdown_money": from_cents(-int(depth.min())),
        "max_drawdown_pct": _round(float((equity / peak - 1.0).min()) * 100.0, 4),
        "max_drawdown_duration_hours": round(longest / MICROS_PER_HOUR, 2),
    }


def _daily_returns(equity: _IntArray, axis: _IntArray) -> list[float]:
    if equity.size < 2:
        return []
    boundaries = np.arange(
        (int(axis[0]) // MICROS_PER_DAY + 1) * MICROS_PER_DAY,
        int(axis[-1]) + 1,
        MICROS_PER_DAY,
        dtype=np.int64,
    )
    if boundaries.size < 2:
        return []
    positions = np.searchsorted(axis, boundaries, side="right") - 1
    values = equity[positions].astype(np.float64)
    returns: list[float] = (values[1:] / values[:-1] - 1.0).tolist()
    return returns


# ---- statistics of a set of trades
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tally:
    gross: int
    slippage: int
    fees: int
    funding: int
    net: int
    closed_net: list[int]
    closed_gross: list[int]
    net_r: list[float]
    gross_r: list[float]
    net_b: float
    gross_b: float
    r_excluded: int
    count: int
    closed: int
    bps: list[float]


def _r_values(trade: TradeRecord, net: int, gross: int) -> tuple[float | None, float | None]:
    """C10. No `R` figure exists for a trade that filled at or through its stop, or with no distance."""
    if trade.through_stop or trade.r <= 0.0 or trade.q0 <= 0.0:
        return None, None
    denominator = trade.q0 * trade.r
    return from_cents(net) / denominator, from_cents(gross) / denominator


def _tally(trades: Sequence[TradeRecord], scale_of: _Scale) -> _Tally:
    gross = slippage = fees = funding = net = 0
    closed_net: list[int] = []
    closed_gross: list[int] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    net_b = gross_b = 0.0
    bps: list[float] = []
    excluded = counted = closed = 0
    for trade in trades:
        scale = scale_of(trade)
        if scale <= 0.0:
            continue
        counted += 1
        _, booked = trade.book(scale)
        gross += booked.gross
        slippage += booked.slippage
        fees += booked.fees
        funding += booked.funding
        net += booked.net
        net_b += from_cents(booked.net) / trade.risk_budget
        gross_b += from_cents(booked.gross) / trade.risk_budget
        if trade.status != "closed":
            continue
        closed += 1
        closed_net.append(booked.net)
        closed_gross.append(booked.gross)
        bps.append(from_cents(booked.net) / (trade.q0 * scale * trade.fill) * 10_000.0)
        # R is per unit of size, so the portfolio's scale must not change it.
        _, unscaled = trade.book()
        one_net, one_gross = _r_values(trade, unscaled.net, unscaled.gross)
        if one_net is None or one_gross is None:
            excluded += 1
            continue
        net_r.append(one_net)
        gross_r.append(one_gross)
    return _Tally(
        gross,
        slippage,
        fees,
        funding,
        net,
        closed_net,
        closed_gross,
        net_r,
        gross_r,
        net_b,
        gross_b,
        excluded,
        counted,
        closed,
        bps,
    )


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _trade_stats(tally: _Tally) -> dict[str, Any]:
    wins = [value for value in tally.closed_net if value > 0]
    losses = [value for value in tally.closed_net if value < 0]
    win_total = sum(wins)
    loss_total = -sum(losses)
    return {
        "trades": tally.count,
        "trades_closed": tally.closed,
        "open_at_end": tally.count - tally.closed,
        "gross_pnl": from_cents(tally.gross),
        "net_pnl": from_cents(tally.net),
        "slippage": from_cents(tally.slippage),
        "fees": from_cents(tally.fees),
        "funding": from_cents(tally.funding),
        "gross_r_total": _round(sum(tally.gross_r)),
        "net_r_total": _round(sum(tally.net_r)),
        "avg_gross_r": _round(_mean(tally.gross_r)),
        "avg_net_r": _round(_mean(tally.net_r)),
        "r_statistics_exclude_trades": tally.r_excluded,
        "gross_result_b_total": _round(tally.gross_b),
        "net_result_b_total": _round(tally.net_b),
        "win_rate": _round(len(wins) / tally.closed) if tally.closed else None,
        "profit_factor": _round(win_total / loss_total) if loss_total else None,
        "avg_trade_net": from_cents(round(sum(tally.closed_net) / tally.closed)) if tally.closed else None,
        "avg_trade_gross": from_cents(round(sum(tally.closed_gross) / tally.closed))
        if tally.closed
        else None,
        "avg_trade_net_bps": _round(_mean(tally.bps), 3),
        "avg_win": from_cents(round(win_total / len(wins))) if wins else None,
        "avg_loss": from_cents(round(-loss_total / len(losses))) if losses else None,
        "largest_win": from_cents(max(wins)) if wins else None,
        "largest_loss": from_cents(min(losses)) if losses else None,
    }


def _cost_lines(tally: _Tally, rt_bps: float) -> dict[str, Any]:
    """Charter section 6. The trade list stays as it is, under C9. Fees, `slip` and `stop_slip` scale, and
    funding not.
    """
    costs = tally.slippage + tally.fees
    multiple = tally.gross / costs if costs > 0 else None
    return {
        "net_pnl_cost_2x": from_cents(tally.gross - 2 * costs - tally.funding),
        "net_pnl_cost_3x": from_cents(tally.gross - 3 * costs - tally.funding),
        "break_even_cost_multiple": _round(multiple, 4),
        "break_even_rt_bps": _round(None if multiple is None else multiple * rt_bps, 3),
    }


def _equity_stats(equity: _IntArray, axis: _IntArray, capital_cents: int) -> dict[str, Any]:
    final = int(equity[-1]) if equity.size else capital_cents
    days = (int(axis[-1]) - int(axis[0])) / MICROS_PER_DAY if axis.size > 1 else 0.0
    total = final / capital_cents - 1.0
    returns = _daily_returns(equity, axis)
    return {
        "equity_start": from_cents(capital_cents),
        "equity_final": from_cents(final),
        "net_pnl_pct": _round(total * 100.0, 4),
        "days": round(days, 3),
        "cagr": _round(cagr(total, days), 6) if days > 0 and total > -1.0 else None,
        "sharpe": _round(sharpe(returns), 4),
        "sharpe_daily_returns_n": len(returns),
        "days_per_year": DAYS_PER_YEAR,
        **_drawdown(equity, axis),
    }


def _sided(trades: Sequence[TradeRecord], side: int) -> list[TradeRecord]:
    return [trade for trade in trades if trade.side == side]


def _current_position(trades: Sequence[TradeRecord]) -> dict[str, Any]:
    held = [trade for trade in trades if trade.status == "open"]
    if not held:
        return {"state": "flat", "open_r": None, "unrealised_pnl": 0.0}
    net = 0
    open_r = 0.0
    for trade in held:
        _, booked = trade.book()
        net += booked.net
        last = trade.legs[-1]
        if trade.r > 0:
            open_r += trade.side * (last.price - trade.fill) / trade.r
    longs = sum(1 for trade in held if trade.side > 0)
    state = "long" if longs == len(held) else "short" if longs == 0 else "mixed"
    return {"state": state, "open_r": _round(open_r, 4), "unrealised_pnl": from_cents(net)}


def _section(
    trades: Sequence[TradeRecord],
    *,
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    capital_cents: int,
    rt_bps: float,
    scale_of: _Scale = _unit,
) -> dict[str, Any]:
    tally = _tally(trades, scale_of)
    equity = equity_curve(trades, axis=axis, marks=marks, capital_cents=capital_cents, scale_of=scale_of)
    return {
        **_trade_stats(tally),
        **_cost_lines(tally, rt_bps),
        **_equity_stats(equity, axis, capital_cents),
    }


def _exit_label(trade: TradeRecord) -> str:
    if trade.exit_reason == "STOP":
        return f"STOP_{trade.stop_kind.upper()}"
    return trade.exit_reason


def _full_section(
    trades: Sequence[TradeRecord],
    *,
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    capital_cents: int,
    rt_bps: float,
    scale_of: _Scale = _unit,
) -> dict[str, Any]:
    """Headline figures, with the long and the short side reported separately."""

    def section(items: Sequence[TradeRecord]) -> dict[str, Any]:
        return _section(
            items, axis=axis, marks=marks, capital_cents=capital_cents, rt_bps=rt_bps, scale_of=scale_of
        )

    tags = sorted({trade.tag for trade in trades if trade.tag is not None})
    return {
        **section(trades),
        "long": section(_sided(trades, 1)),
        "short": section(_sided(trades, -1)),
        # S08 section 5: its two branches are reported separately.
        "branches": {tag: section([trade for trade in trades if trade.tag == tag]) for tag in tags},
        "exit_reasons": dict(sorted(Counter(_exit_label(trade) for trade in trades).items())),
    }


# ---- rows
# -----------------------------------------------------------------------------------------------------


def stream_status(stream: StreamResult) -> str:
    """Too little history gives no result. The row says so, and its zeros are not a result of the rule."""
    if stream.setups == 0:
        return "NO_SETUPS"
    if not stream.trades:
        return "NO_TRADES"
    return "RAN"


@dataclass(frozen=True)
class OutputRows:
    strategy_asset: list[dict[str, Any]]
    strategy: list[dict[str, Any]]
    portfolio: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    equity: list[dict[str, Any]]
    events: list[dict[str, Any]]


def build_axis(first_us: int, last_us: int, minutes: int) -> _IntArray:
    """One time axis for every series: a grid, with the last moment of the data as its final point."""
    step = minutes * 60_000_000
    start = ((first_us - 1) // step + 1) * step
    grid: _IntArray = np.arange(start, last_us + 1, step, dtype=np.int64)
    if grid.size == 0 or int(grid[-1]) != last_us:
        grid = np.append(grid, np.int64(last_us))
    return grid


def _overlap(
    trades: Sequence[TradeRecord],
    *,
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    symbols: tuple[str, ...],
    capital: float,
    scale_of: _Scale,
) -> dict[str, Any]:
    """How often the assets are open together and in the same direction, on the equity axis."""
    signed = {symbol: np.zeros(axis.size) for symbol in symbols}
    gross = np.zeros(axis.size)
    open_flags = {symbol: np.zeros(axis.size, dtype=bool) for symbol in symbols}
    last_index = axis.size - 1
    for trade in trades:
        scale = scale_of(trade)
        if scale <= 0.0:
            continue
        events, _ = trade.book(scale)
        prices = marks[trade.symbol]
        for position, event in enumerate(events):
            first = int(np.searchsorted(axis, event.event_us, side="left"))
            following = events[position + 1].event_us if position + 1 < len(events) else None
            stop = last_index + 1 if following is None else int(np.searchsorted(axis, following, side="left"))
            if event.qty_after <= 0.0 or first >= stop:
                continue
            notional = event.qty_after * prices[first:stop]
            signed[trade.symbol][first:stop] += trade.side * notional
            gross[first:stop] += notional
            open_flags[trade.symbol][first:stop] = True
    together = np.ones(axis.size, dtype=bool)
    for flags in open_flags.values():
        together &= flags
    both = int(together.sum())
    same = 0
    if len(symbols) >= 2:
        same = int((together & (np.sign(signed[symbols[0]]) * np.sign(signed[symbols[1]]) > 0)).sum())
    return {
        "assets": list(symbols),
        "marks": int(axis.size),
        "open_together_marks": both,
        "open_together_share": _round(both / axis.size) if axis.size else None,
        "same_direction_marks": same,
        "same_direction_share_of_open_together": _round(same / both) if both else None,
        "direction_is": "the sign of each asset's net notional at the mark",
        "gross_exposure_max": _round(float(gross.max()) / capital, 4) if axis.size else 0.0,
        "gross_exposure_mean": _round(float(gross.mean()) / capital, 4) if axis.size else 0.0,
    }


def _stream_labels(config: EngineConfig, labels: Sequence[str], live_comparable: bool) -> str:
    extra = () if live_comparable else (NOT_LIVE_COMPARABLE,)
    return " ".join((*run_labels(config, labels), *extra))


def build_rows(
    streams: Sequence[StreamResult],
    *,
    config: EngineConfig,
    labels: Sequence[str],
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    mark_at: Callable[[str, int], float | None],
) -> OutputRows:
    """Every row, from finished streams, in the order they ran. Nothing here is sorted by an outcome."""
    capital = config.risk.capital
    capital_cents = to_cents(capital)
    rt_bps = config.costs.rt_bps
    label = row_label(config, labels)
    # S01 and S06 say `NOT LIVE-COMPARABLE` on every table, under section 14 of their documents.
    label_of = {stream.strategy: _stream_labels(config, labels, stream.live_comparable) for stream in streams}
    all_trades = [trade for stream in streams for trade in stream.trades]
    counted = [trade for trade in all_trades if trade.in_portfolio]
    cap = apply_gross_cap(counted, capital=capital, gross_cap=config.risk.gross_cap, mark=mark_at)
    scale_of = _scaler(cap)
    shared: dict[str, Any] = {"axis": axis, "marks": marks, "capital_cents": capital_cents, "rt_bps": rt_bps}

    strategy_asset = [
        {
            "label": _stream_labels(config, labels, stream.live_comparable),
            "mode": MODE,
            "variant": VARIANT,
            "strategy": stream.strategy,
            "version": stream.version,
            "line": stream.line,
            "is_default": stream.is_default,
            "in_portfolio": stream.in_portfolio,
            "asset": stream.symbol,
            "timeframe_minutes": stream.timeframe_minutes,
            "gate": "none: no reviewer has given a verdict",
            "status": stream_status(stream),
            "has_result": stream_status(stream) == "RAN",
            "closes": stream.closes,
            "setups": stream.setups,
            "no_setup_reasons": stream.reasons,
            "requirements": list(stream.requirements),
            **_full_section(stream.trades, **shared),
            "current_position": _current_position(stream.trades),
            "risk_per_trade_pct": config.risk.per_trade_pct[stream.strategy][stream.symbol],
            "counters": stream.counters,
        }
        for stream in streams
    ]

    keys: list[tuple[str, str]] = []
    for stream in streams:
        if (stream.strategy, stream.line) not in keys:
            keys.append((stream.strategy, stream.line))
    strategy_rows: list[dict[str, Any]] = []
    for strategy, line in keys:
        members = [stream for stream in streams if stream.strategy == strategy and stream.line == line]
        trades = [trade for stream in members for trade in stream.trades]
        statuses = sorted({stream_status(stream) for stream in members})
        reasons: Counter[str] = Counter()
        for stream in members:
            reasons.update(stream.reasons)
        strategy_rows.append(
            {
                "label": _stream_labels(config, labels, members[0].live_comparable),
                "mode": MODE,
                "variant": VARIANT,
                "strategy": strategy,
                "line": line,
                "is_default": members[0].is_default,
                "in_portfolio": members[0].in_portfolio,
                "assets": [stream.symbol for stream in members],
                "gate": "none: no reviewer has given a verdict",
                "status": statuses[0] if len(statuses) == 1 else "MIXED",
                "has_result": any(stream_status(stream) == "RAN" for stream in members),
                "setups": sum(stream.setups for stream in members),
                "no_setup_reasons": dict(sorted(reasons.items())),
                **_full_section(trades, **shared),
                "current_position": _current_position(trades),
                "overlap_between_assets": _overlap(
                    trades, axis=axis, marks=marks, symbols=config.symbols, capital=capital, scale_of=_unit
                ),
            }
        )

    members_of_portfolio = [stream for stream in streams if stream.in_portfolio]
    left_out = {
        key.removeprefix("setups_left_out_"): sum(
            stream.counters.get(key, 0) for stream in members_of_portfolio
        )
        for key in sorted(
            {
                key
                for stream in members_of_portfolio
                for key in stream.counters
                if key.startswith("setups_left_out_")
            }
        )
    }
    portfolio_row = {
        "label": label,
        "mode": MODE,
        "variant": VARIANT,
        "row": "portfolio of one declared line per strategy, gross exposure cap applied",
        "line_note": DEFAULT_LINE_NOTE,
        "strategies_included": sorted({stream.strategy for stream in members_of_portfolio}),
        "lines_used": sorted({f"{stream.strategy}: {stream.line}" for stream in members_of_portfolio}),
        "setups_left_out": left_out,
        **_full_section(counted, scale_of=scale_of, **shared),
        "gross_cap": {
            "entries_seen": len(cap),
            "entries_scaled": sum(1 for item in cap.values() if 0.0 < item.scale < 1.0),
            "entries_refused": sum(1 for item in cap.values() if item.refused),
            "tie_order": "entries decided at one moment are taken in strategy and symbol order",
        },
        "overlap_between_assets": _overlap(
            counted, axis=axis, marks=marks, symbols=config.symbols, capital=capital, scale_of=scale_of
        ),
    }
    uncapped_row = {
        "label": label,
        "mode": MODE,
        "variant": VARIANT,
        "row": "sum of separate streams of the same lines, no gross exposure cap",
        "line_note": DEFAULT_LINE_NOTE,
        **_full_section(counted, **shared),
    }

    return OutputRows(
        strategy_asset=strategy_asset,
        strategy=strategy_rows,
        portfolio=[portfolio_row, uncapped_row],
        trades=[_trade_row(trade, label_of[trade.strategy], cap) for trade in all_trades],
        equity=_equity_rows(
            members_of_portfolio,
            axis=axis,
            marks=marks,
            capital_cents=capital_cents,
            scale_of=scale_of,
            label=label,
        ),
        events=_event_rows(streams, label_of),
    )


def _scaler(cap: dict[TradeKey, CapDecision]) -> _Scale:
    def scale_of(trade: TradeRecord) -> float:
        decision = cap.get(trade_key(trade))
        return 0.0 if decision is None else decision.scale

    return scale_of


def _leg_row(leg: ExitLeg) -> dict[str, Any]:
    return {
        "time": iso_us(leg.event_us),
        "reference": leg.reference,
        "price": leg.price,
        "qty": leg.qty,
        "fee_rate": leg.fee_rate,
        "reason": leg.reason,
        "open_at_end": leg.open_at_end,
    }


def _path_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "computed_at": iso_us(row["computed_at_us"]),
        "effective_from": iso_us(row["effective_from_us"]),
        **{key: value for key, value in row.items() if not key.endswith("_us")},
    }


def _trade_row(trade: TradeRecord, label: str, cap: dict[TradeKey, CapDecision]) -> dict[str, Any]:
    _, booked = trade.book()
    net_r, gross_r = _r_values(trade, booked.net, booked.gross)
    decision = cap.get(trade_key(trade))
    scaled = trade.book(decision.scale)[1] if decision is not None and decision.scale > 0 else None
    alternative = None
    if trade.gap_unresolved:
        alternative = {
            "gap_start": None if trade.gap_start_us is None else iso_us(trade.gap_start_us),
            "as_recorded_exit": [_leg_row(leg) for leg in trade.as_recorded_legs],
            "headline_exit": [_leg_row(leg) for leg in trade.legs],
            "headline": "the worse of the two, under C2",
        }
    mfe = (trade.best - trade.side * trade.fill) / trade.r if trade.r > 0 else None
    mae = (trade.worst - trade.side * trade.fill) / trade.r if trade.r > 0 else None
    return {
        "label": label,
        "mode": MODE,
        "variant": VARIANT,
        "strategy": trade.strategy,
        "version": trade.version,
        "line": trade.line,
        "is_default": trade.is_default,
        "asset": trade.symbol,
        "side": "long" if trade.side > 0 else "short",
        "branch": trade.tag,
        "status": trade.status,
        "signal_time": iso_us(trade.signal_us),
        "decided_as_of": iso_us(trade.decided_as_of_us),
        "fill_time": iso_us(trade.fill_us),
        "fill_event_time": iso_us(trade.fill_event_us),
        "exit_time": None if trade.status == "open" else iso_us(trade.legs[-1].event_us),
        "decision_price": trade.decision_price,
        "collar_limit": trade.collar_limit,
        "fill_reference": trade.fill_reference,
        "fill_price": trade.fill,
        "exit_legs": [_leg_row(leg) for leg in trade.legs],
        "exit_reason": _exit_label(trade),
        "initial_stop": trade.s0,
        "targets_at_setup": [
            {"name": item.name, "price": item.price, "fraction": item.fraction}
            for item in trade.targets_at_setup
        ],
        "stop_path": [_path_row(row) for row in trade.stop_path],
        "target_path": [_path_row(row) for row in trade.target_path],
        "level": trade.level,
        "qty": trade.q0,
        "leverage_capped": trade.leverage_capped,
        "risk_budget": trade.risk_budget,
        "r": trade.r,
        "r_dec": trade.r_dec,
        "gross_pnl": from_cents(booked.gross),
        "net_pnl": from_cents(booked.net),
        "costs": {
            "slippage": from_cents(booked.slippage),
            "fees": from_cents(booked.fees),
            "funding": from_cents(booked.funding),
        },
        "gross_r": _round(gross_r),
        "net_r": _round(net_r),
        "gross_result_b": _round(from_cents(booked.gross) / trade.risk_budget),
        "net_result_b": _round(from_cents(booked.net) / trade.risk_budget),
        "mfe_r": _round(mfe),
        "mae_r": _round(mae),
        "bars_held": trade.bars_held,
        "entry_through_stop": trade.through_stop,
        "gap_unresolved": trade.gap_unresolved,
        "both_ways": alternative,
        "in_portfolio": trade.in_portfolio,
        "portfolio_scale": None if decision is None else _round(decision.scale, 8),
        "portfolio_refused": None if decision is None else decision.refused,
        "portfolio_net_pnl": None if scaled is None else from_cents(scaled.net),
        "portfolio_gross_pnl": None if scaled is None else from_cents(scaled.gross),
    }


def _equity_rows(
    defaults: Sequence[StreamResult],
    *,
    axis: _IntArray,
    marks: dict[str, _FloatArray],
    capital_cents: int,
    scale_of: _Scale,
    label: str,
) -> list[dict[str, Any]]:
    """One row per moment on the axis, with one value per series. All series share the one axis."""
    series: dict[str, _IntArray] = {}
    names: list[str] = []
    for stream in defaults:
        series[f"{stream.strategy}:{stream.symbol}"] = equity_curve(
            stream.trades, axis=axis, marks=marks, capital_cents=capital_cents
        )
        if stream.strategy not in names:
            names.append(stream.strategy)
    for name in names:
        trades = [trade for stream in defaults if stream.strategy == name for trade in stream.trades]
        series[name] = equity_curve(trades, axis=axis, marks=marks, capital_cents=capital_cents)
    counted = [trade for stream in defaults for trade in stream.trades]
    series["portfolio"] = equity_curve(
        counted, axis=axis, marks=marks, capital_cents=capital_cents, scale_of=scale_of
    )
    series["portfolio:long"] = equity_curve(
        _sided(counted, 1), axis=axis, marks=marks, capital_cents=capital_cents, scale_of=scale_of
    )
    series["portfolio:short"] = equity_curve(
        _sided(counted, -1), axis=axis, marks=marks, capital_cents=capital_cents, scale_of=scale_of
    )
    series["portfolio:uncapped"] = equity_curve(counted, axis=axis, marks=marks, capital_cents=capital_cents)
    ordered = sorted(series)
    columns = {name: series[name].tolist() for name in ordered}
    times = axis.tolist()
    return [
        {
            "label": label,
            "time": iso_us(times[index]),
            "equity": {name: from_cents(columns[name][index]) for name in ordered},
        }
        for index in range(axis.size)
    ]


def _event_rows(streams: Sequence[StreamResult], label_of: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in streams:
        for event in stream.events:
            row: dict[str, Any] = {
                "label": label_of[stream.strategy],
                "mode": MODE,
                "strategy": stream.strategy,
                "line": stream.line,
                "asset": stream.symbol,
            }
            for key, value in event.items():
                if key.endswith("_us") and isinstance(value, int):
                    row[key.removesuffix("_us")] = iso_us(value)
                else:
                    row[key] = value
            rows.append(row)
    return rows


def data_credit(config: EngineConfig) -> str:
    """The credit is true only of data from the credited source, so a generated output says which it is."""
    if config.data_kind == LABEL_SYNTHETIC:
        return (
            f"This output holds generated data and none from any venue. On market data: {config.credit_line}"
        )
    return config.credit_line


def output_header(
    *,
    config: EngineConfig,
    labels: Sequence[str],
    date_range: dict[str, str],
    code_version: str,
    manifest_hash: str,
    funding_note: str,
    modes: dict[str, str],
    registry_distinct_trials: int,
    bar_allowance_ms: float,
) -> dict[str, Any]:
    """Printed at the top of every file."""
    return {
        "labels": list(run_labels(config, labels)),
        "notice": NO_ADVICE,
        "data_kind": config.data_kind,
        "data_credit": data_credit(config),
        "date_range": date_range,
        "date_range_note": "UTC days, both included, by a bar's close. Nothing outside was opened",
        "opened_blocks": list(config.opened_blocks),
        "read_days": [day.isoformat() for day in config.read_days],
        "not_live_comparable": ["S01", "S06"],
        "portfolio_lines": {
            name: {"line": grid.portfolio_line, "state": grid.portfolio_state}
            for name, grid in sorted(config.strategies.items())
        },
        "mode": MODE,
        "variant": VARIANT,
        "tier": config.tier,
        "modes": modes,
        "lines": config.line_set,
        "line_note": DEFAULT_LINE_NOTE,
        "costs": {
            "rt_bps": config.costs.rt_bps,
            "slip_bps": config.costs.slip_bps,
            "stop_slip_bps": config.costs.stop_slip_bps,
            "stop_slip_state": config.costs.stop_slip_state,
            "target_fee_bps": config.costs.target_fee_bps,
            "taker_fee_bps": round(config.costs.fee_taker * 10_000.0, 6),
            "basis": config.costs.basis,
            "cost_multiples": "2x and 3x multiply fees, slip and stop_slip, on the same trade list",
        },
        "bar_allowance_ms": bar_allowance_ms,
        "bar_allowance_note": "The source's declared allowance. UNVERIFIED until measured",
        "funding": {"status": config.funding, "note": funding_note},
        "risk": config.risk.as_output(),
        "registry_distinct_trials": registry_distinct_trials,
        "code_version": code_version,
        "config_hash": config.config_hash,
        "data_manifest_hash": manifest_hash,
    }
