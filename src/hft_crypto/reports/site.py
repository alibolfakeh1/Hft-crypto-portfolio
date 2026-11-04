"""The static page. Self-contained and plain on purpose, because ui-designer will restyle it later.

One HTML file: no scripts from elsewhere, no web fonts, no images. It is UTF-8 and works with Persian text.
The chart is inline SVG with one shared time axis, equity above and underwater drawdown below. A small script
adds a crosshair and tooltip, and the same values are in tables, so nothing depends on it.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from hft_crypto.config import NO_APPROVED_SOURCE
from hft_crypto.timeutil import from_us, parse_iso

if TYPE_CHECKING:
    from hft_crypto.reports.report import Benchmark

_LABEL_FA = "معیار مقایسه، نه نتیجهٔ یک استراتژی"
_SYNTHETIC_FA = "داده‌های ساختگی برای آزمایش. این داده‌ها واقعی نیستند و نتیجهٔ بازار یا استراتژی نیستند"

_CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --plane: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --warn-bg: #fff4d6; --warn-ink: #5c4300;
  --crit-bg: #fde8e8; --crit-ink: #7a1414;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface: #1a1a19; --plane: #0d0d0d; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #a3a29b;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --warn-bg: #3a2e0a; --warn-ink: #f7dc8f;
    --crit-bg: #3d1414; --crit-ink: #f7b4b4;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --plane: #0d0d0d; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #a3a29b;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --warn-bg: #3a2e0a; --warn-ink: #f7dc8f;
  --crit-bg: #3d1414; --crit-ink: #f7b4b4;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--plane); color: var(--ink); line-height: 1.5;
  font-family: system-ui, -apple-system, "Segoe UI", Tahoma, "Vazirmatn", sans-serif;
}
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 56px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.1rem; margin: 32px 0 8px; }
p { margin: 6px 0; color: var(--ink-2); }
section, .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.label { display: inline-block; font-weight: 700; padding: 6px 10px; border-radius: 6px;
  background: var(--warn-bg); color: var(--warn-ink); margin: 8px 0; }
.notice { padding: 8px 12px; border-radius: 6px; margin: 8px 0; background: var(--warn-bg); color: var(--warn-ink); }
.notice.critical { background: var(--crit-bg); color: var(--crit-ink); }
.fa { direction: rtl; text-align: right; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.875rem; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink-2); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.legend { display: flex; gap: 16px; margin: 4px 0 8px; font-size: 0.875rem; color: var(--ink-2); }
.key { display: inline-block; width: 14px; height: 2px; vertical-align: middle; margin-right: 6px; }
svg { display: block; width: 100%; height: auto; }
svg text { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.tip { position: fixed; display: none; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 0.8125rem; box-shadow: 0 2px 8px rgba(0,0,0,.18); }
footer { margin-top: 32px; font-size: 0.8125rem; color: var(--ink-2); }
"""

_SCRIPT = """
(function () {
  var data = JSON.parse(document.getElementById('chart-data').textContent);
  var svg = document.getElementById('chart'); var tip = document.getElementById('tip');
  var cross = document.getElementById('cross');
  if (!svg || !data.times.length) return;
  function show(evt) {
    var box = svg.getBoundingClientRect();
    var scale = data.width / box.width;
    var x = (evt.clientX - box.left) * scale;
    if (x < data.left || x > data.right) { hide(); return; }
    var t = data.tmin + (x - data.left) / (data.right - data.left) * (data.tmax - data.tmin);
    var best = 0, bestGap = Infinity;
    for (var i = 0; i < data.times.length; i++) {
      var gap = Math.abs(data.times[i] - t);
      if (gap < bestGap) { best = i; bestGap = gap; }
    }
    var cx = data.left + (data.times[best] - data.tmin) / (data.tmax - data.tmin) * (data.right - data.left);
    cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.style.display = '';
    var lines = [new Date(data.times[best] / 1000).toISOString().slice(0, 16).replace('T', ' ') + ' UTC'];
    data.series.forEach(function (s) {
      var v = s.values[best];
      if (v) lines.push(s.name + ': equity ' + v[0].toFixed(2) + ', drawdown ' + (v[1] * 100).toFixed(2) + '%');
    });
    tip.textContent = ''; lines.forEach(function (l) { var d = document.createElement('div'); d.textContent = l; tip.appendChild(d); });
    tip.style.display = 'block';
    tip.style.left = Math.min(evt.clientX + 14, window.innerWidth - 300) + 'px';
    tip.style.top = (evt.clientY + 14) + 'px';
  }
  function hide() { tip.style.display = 'none'; cross.style.display = 'none'; }
  svg.addEventListener('mousemove', show); svg.addEventListener('mouseleave', hide);
})();
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _pct(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _bytes(value: float | None) -> str:
    if value is None:
        return "n/a"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1000.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1000.0
    return f"{size:.2f} TB"


def _table(headers: Sequence[tuple[str, bool]], rows: Iterable[Sequence[object]]) -> str:
    head = "".join(f'<th class="{"num" if numeric else ""}">{_e(text)}</th>' for text, numeric in headers)
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if headers[i][1] else ""}">{_e(cell)}</td>' for i, cell in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    span = high - low
    if span <= 0:
        return [low]
    raw = span / max(1, count - 1)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = next((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), raw)
    first = math.floor(low / step) * step
    ticks = []
    value = first
    while value <= high + step * 1e-6:
        if value >= low - step * 1e-6:
            ticks.append(round(value, 10))
        value += step
    return ticks


def _time_ticks(tmin: int, tmax: int) -> list[int]:
    """Whole UTC days, thinned so labels do not collide at this chart's width."""
    day = 86_400_000_000
    spans = (1, 2, 5, 7, 14, 30, 61, 91, 182, 365)
    total_days = (tmax - tmin) / day
    step = next((s for s in spans if total_days / s <= 8), spans[-1])
    first = (tmin // day + (1 if tmin % day else 0)) * day
    ticks = list(range(first, tmax + 1, step * day))
    return ticks if ticks else [tmin]


def _path(points: Sequence[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)


def render_chart(benchmarks: Sequence[Benchmark], *, synthetic: bool = False) -> tuple[str, str]:
    """Return the SVG and the JSON behind its tooltip."""
    series = [b for b in benchmarks if b.points]
    if not series:
        return "<p>No complete days are available yet, so there is nothing to chart.</p>", "{}"
    width, left, right = 960.0, 56.0, 924.0
    top_a, bottom_a = 16.0, 300.0
    top_b, bottom_b = 332.0, 452.0
    height = 484.0
    tmin = min(b.points[0].time_us for b in series)
    tmax = max(b.points[-1].time_us for b in series)
    tspan = max(1, tmax - tmin)
    equity_low = min(min(p.equity for p in b.points) for b in series)
    equity_high = max(max(p.equity for p in b.points) for b in series)
    pad = max(0.5, (equity_high - equity_low) * 0.06)
    equity_low -= pad
    equity_high += pad
    draw_low = min(min(p.drawdown for p in b.points) for b in series) * 1.08
    draw_low = min(draw_low, -0.01)

    def sx(t: int) -> float:
        return left + (t - tmin) / tspan * (right - left)

    def sy_a(v: float) -> float:
        return bottom_a - (v - equity_low) / (equity_high - equity_low) * (bottom_a - top_a)

    def sy_b(v: float) -> float:
        return top_b + (0.0 - v) / (0.0 - draw_low) * (bottom_b - top_b)

    parts: list[str] = [
        f'<svg id="chart" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        'aria-label="Equity normalised to 100 above underwater drawdown, on a shared time axis. '
        'The same statistics are in the table below.">'
    ]
    for tick in _nice_ticks(equity_low, equity_high):
        y = sy_a(tick)
        parts.append(
            f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>'
        )
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{tick:g}</text>')
    for tick in _nice_ticks(draw_low, 0.0, 4):
        y = sy_b(tick)
        parts.append(
            f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>'
        )
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{tick * 100 + 0.0:g}%</text>')
    for tick in _time_ticks(tmin, tmax):
        x = sx(tick)
        parts.append(
            f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top_a}" y2="{bottom_b}" stroke="var(--grid)" stroke-width="1" opacity="0.6"/>'
        )
        label = from_us(tick).strftime("%b %d")
        parts.append(f'<text x="{x:.1f}" y="{bottom_b + 18}" text-anchor="middle">{label}</text>')
    if synthetic:
        parts.append(
            f'<text x="{(left + right) / 2}" y="{(top_a + bottom_a) / 2}" text-anchor="middle" '
            'style="font-size:64px;font-weight:700;opacity:0.18">SYNTHETIC</text>'
        )
    parts.append(f'<text x="{left}" y="{top_a - 4}">Equity, start = 100</text>')
    parts.append(f'<text x="{left}" y="{top_b - 6}">Underwater drawdown</text>')
    parts.append(
        f'<line x1="{left}" x2="{right}" y1="{sy_b(0.0):.1f}" y2="{sy_b(0.0):.1f}" stroke="var(--axis)" stroke-width="1"/>'
    )
    for index, benchmark in enumerate(series):
        colour = f"var(--series-{index % 2 + 1})"
        equity_line = [(sx(p.time_us), sy_a(p.equity)) for p in benchmark.points]
        draw_line = [(sx(p.time_us), sy_b(p.drawdown)) for p in benchmark.points]
        parts.append(
            f'<path d="{_path(equity_line)}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>'
        )
        parts.append(
            f'<path d="{_path(draw_line)}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>'
        )
    parts.append(
        f'<line id="cross" x1="0" x2="0" y1="{top_a}" y2="{bottom_b}" stroke="var(--muted)" stroke-width="1" style="display:none"/>'
    )
    parts.append("</svg>")

    # One tooltip row per shared time. A symbol missing at a time shows nothing for it.
    times = sorted({p.time_us for b in series for p in b.points})
    payload = {
        "width": width,
        "left": left,
        "right": right,
        "tmin": tmin,
        "tmax": tmax,
        "times": times,
        "series": [
            {
                "name": b.symbol,
                "values": [
                    (lambda found: None if found is None else [found.equity, found.drawdown])(
                        {p.time_us: p for p in b.points}.get(t)
                    )
                    for t in times
                ],
            }
            for b in series
        ],
    }
    return "".join(parts), json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


def _notices(status: dict[str, Any]) -> str:
    items: list[str] = []
    if status["data_kind"] == "SYNTHETIC":
        items.append(
            '<div class="notice critical"><strong>SYNTHETIC.</strong> Every number on this page comes from '
            "generated test data on a made-up calendar. None of it is market data or a result of any kind.</div>"
        )
    if status["data_as_of"] is None:
        if status["source_state"] == NO_APPROVED_SOURCE:
            items.append(
                f'<div class="notice critical">{_e(NO_APPROVED_SOURCE.capitalize())}. '
                "No market data is being collected, so there are no benchmarks yet.</div>"
            )
        else:
            items.append(
                '<div class="notice critical">No benchmark data yet. Coverage below shows the rebuild.</div>'
            )
    elif status["stale"]:
        items.append(
            f'<div class="notice critical">STALE: the newest bar is {_e(status["data_age_hours"])} '
            "hours old. These figures are not current.</div>"
        )
    if status["partial_coverage"]:
        items.append(
            '<div class="notice">PARTIAL COVERAGE: backfill is still running, or a lost cache is being rebuilt. '
            "Statistics use only the newest unbroken run of days.</div>"
        )
    for alert in status["health"]["alerts"]:
        if NO_APPROVED_SOURCE in alert.lower():
            continue
        kind = "critical" if alert.startswith("URGENT") else ""
        items.append(f'<div class="notice {kind}">{_e(alert)}</div>')
    return "".join(items)


def _benchmark_section(status: dict[str, Any], benchmarks: Sequence[Benchmark]) -> str:
    chart, _ = render_chart(benchmarks, synthetic=status["data_kind"] == "SYNTHETIC")
    legend = "".join(
        f'<span><span class="key" style="background:var(--series-{i % 2 + 1})"></span>{_e(b.symbol)}</span>'
        for i, b in enumerate(benchmarks)
    )
    rows = []
    for symbol, item in status["benchmarks"].items():
        rows.append(
            [
                symbol,
                f"{item['start'][:10]} to {item['end'][:10]}",
                f"{item['days']:.0f}",
                _pct(item["total_return"]),
                _pct(item["cagr"]),
                _pct(item["annualised_volatility"]),
                _num(item["sharpe"]),
                _pct(item["max_drawdown"]),
                item["daily_returns"],
            ]
        )
    table = _table(
        [
            ("Symbol", False),
            ("Period, UTC", False),
            ("Days", True),
            ("Total return", True),
            ("CAGR, 365 days", True),
            ("Volatility, annualised", True),
            ("Sharpe", True),
            ("Max drawdown", True),
            ("Daily returns (n)", True),
        ],
        rows,
    )
    short = any(item["days"] < 365 for item in status["benchmarks"].values())
    caution = (
        "<p>This period is under a year, so CAGR extrapolates a short stretch and Sharpe has a wide margin of "
        "error. Read the sample size next to each figure.</p>"
        if short
        else ""
    )
    return (
        f'<section><div class="legend">{legend}</div>{chart}{table}'
        "<p>Buy and hold from the first traded price of the period. No fees, funding or slippage. "
        "Volatility and Sharpe use daily close-to-close returns with a zero risk-free rate, annualised on "
        f"365 days. Max drawdown uses hourly marks, as charted.</p>{caution}</section>"
    )


def _coverage_section(status: dict[str, Any]) -> str:
    health = status["health"]
    rows = [
        [
            c["dataset"],
            c["symbol"],
            c["tier"],
            f"{c['done']} of {c['expected']}",
            f"{c['coverage_pct']:.1f}%",
            c["pending"],
            c["overdue"],
            c["failed"],
            c["first_done"] or "none",
            c["last_done"] or "none",
        ]
        for c in health["coverage"]
    ]
    bars = [
        [
            b["dataset"],
            b["symbol"],
            "bars",
            f"{b['final'] + b['provisional']} of {b['expected']}",
            f"{b['coverage_pct']:.1f}%",
            b["provisional"],
            0,
            b["failed"],
            b["first_built"] or "none",
            b["last_built"] or "none",
        ]
        for b in health["bars_coverage"]
    ]
    return _table(
        [
            ("Dataset", False),
            ("Symbol", False),
            ("Tier", False),
            ("Partitions", True),
            ("Coverage", True),
            ("Pending", True),
            ("Overdue", True),
            ("Failed", True),
            ("First", False),
            ("Last", False),
        ],
        [*rows, *bars],
    )


def _storage_section(status: dict[str, Any]) -> str:
    disk = status["health"]["disk"]
    cache = status["health"].get("actions_cache") or {}
    days = disk["days_until_full"]
    cache_used = cache.get("active_caches_size_in_bytes")
    rows = [
        ["Kept between runs (Actions cache)", _bytes(disk["persisted_bytes"])],
        ["Quota", _bytes(disk["quota_bytes"])],
        ["Use of quota, all zones", f"{disk['used_pct']:.2f}%"],
        ["Watermark", disk["watermark_level"]],
        ["Growth per day (measured)", _bytes(disk["growth_bytes_per_day"])],
        ["Days until full at that rate", "not measured yet" if days is None else f"{days:.0f}"],
        [
            "All caches of this repository, per GitHub",
            "not reported" if cache_used is None else _bytes(cache_used),
        ],
    ]
    zones = [[zone, _bytes(size)] for zone, size in disk["zones_bytes"].items() if size]
    return _table([("Storage", False), ("Value", True)], rows) + _table(
        [("Zone", False), ("Size", True)], zones
    )


def _poll_section(status: dict[str, Any]) -> str:
    poll = status["live_poll"]
    if not poll.get("runs"):
        return "<p>No hourly poll runs have been recorded yet.</p>"
    timing = _table(
        [("Hourly poll", False), ("Value", True)],
        [
            ["Runs recorded", poll["runs"]],
            ["Scheduled runs", poll["scheduled_runs"]],
            ["Delay after the scheduled minute, median", _seconds(poll["delay_median_s"])],
            ["Delay, 90th percentile", _seconds(poll["delay_p90_s"])],
            ["Delay, largest", _seconds(poll["delay_max_s"])],
            ["Scheduled slots with no run", poll["missed_slots_total"]],
            ["Failed runs", poll["failed_runs"]],
            ["Trade id gaps found", poll["gaps"]],
            ["Last run", poll["last_run"]],
            ["Last run status", poll["last_status"]],
        ],
    )
    rows = [
        [
            symbol,
            item["last_bar_close"] or "none",
            _seconds(item["data_age_s_at_run"]),
            "yes" if item["caught_up"] else "no",
            item["late_trades_total"],
        ]
        for symbol, item in poll["symbols"].items()
    ]
    symbols = _table(
        [
            ("Symbol", False),
            ("Last closed bar", False),
            ("Data age at that run", True),
            ("Caught up", False),
            ("Late trades", True),
        ],
        rows,
    )
    return (
        timing
        + symbols
        + "<p>A run later than one hour is matched to a later slot, so these delays are a lower bound. "
        "Slots with no run cover that case. No strategy runs yet, so there are no positions.</p>"
    )


def _seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 120:
        return f"{value:.0f} s"
    if value < 7200:
        return f"{value / 60:.1f} min"
    return f"{value / 3600:.1f} h"


def _reconciliation_section(status: dict[str, Any]) -> str:
    official = status["reconciliation"]["official_candles"]
    text = (
        f"<p>Canonical bars against official candles: {official['days']} symbol-days checked, "
        f"{official['pass']} pass, {official['warn']} warn, {official['fail']} fail. "
        "The daily totals must match. Single bars may differ slightly, because the official bars use a "
        "different boundary.</p>"
    )
    cross = status["reconciliation"]["cross_venue"]
    if cross:
        text += "<p>The next table compares two different markets as a sanity check. They are not expected to match.</p>"
        text += _table(
            [
                ("Date", False),
                ("Symbol", False),
                ("Status", False),
                ("Median close difference, bps", True),
                ("1-minute return correlation", True),
            ],
            [
                [
                    r["date"],
                    r["symbol"],
                    r["status"],
                    _num(r["median_abs_close_diff_bps"]),
                    _num(r["one_minute_return_corr"], 3),
                ]
                for r in cross
            ],
        )
    rebuild = status["reconciliation"]["poll_rebuild"]
    if rebuild:
        text += "<p>Polled bars as first emitted, against a later rebuild from all stored trades.</p>"
        text += _table(
            [
                ("Date", False),
                ("Symbol", False),
                ("Status", False),
                ("Bars compared", True),
                ("Bars different", True),
            ],
            [[r["date"], r["symbol"], r["status"], r["bars_compared"], r["bars_different"]] for r in rebuild],
        )
    book = status["book_replay"]
    if book:
        text += "<p>Order book files validated by replay, as summary statistics only.</p>"
        text += _table(
            [
                ("Date", False),
                ("Dataset", False),
                ("Lines", True),
                ("Update id breaks", True),
                ("Crossed", True),
                ("Snapshot mismatches", True),
            ],
            [
                [
                    r["date"],
                    r["dataset"],
                    r["lines"],
                    r["update_id_breaks"],
                    r["crossed"],
                    r["snapshot_mismatches"],
                ]
                for r in book
            ],
        )
    return text


def _age_text(status: dict[str, Any]) -> str:
    if status["data_as_of"] is None:
        return "No benchmark data yet."
    moment: dt.datetime = parse_iso(status["data_as_of"])
    return f"Data as of {moment.strftime('%Y-%m-%d %H:%M')} UTC, {status['data_age_hours']} hours old."


def render_site(status: dict[str, Any], benchmarks: Sequence[Benchmark]) -> str:
    """Render the whole page. Every value passes through an escape, or is built from numbers."""
    synthetic = status["data_kind"] == "SYNTHETIC"
    _, payload = render_chart(benchmarks, synthetic=synthetic)
    label = status["label"]
    title = "SYNTHETIC test output" if synthetic else "HFT Crypto Status"
    heading = "SYNTHETIC test output, not market data" if synthetic else "Data status and benchmarks"
    tag = "SYNTHETIC: " if synthetic else ""
    note_fa = _SYNTHETIC_FA if synthetic else _LABEL_FA
    return f"""<!doctype html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="Data coverage and buy and hold benchmarks. Not a strategy result.">
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>{_e(heading)}</h1>
<div class="label">{_e(label)}</div>
<p class="fa" lang="fa" dir="rtl">{_e(note_fa)}. این صفحه توصیهٔ سرمایه‌گذاری نیست و هیچ سفارش واقعی ارسال نمی‌شود.</p>
<p>{_e(_age_text(status))} Generated {_e(status["generated_at"])}.</p>
<p>No strategy has been tested. This is not investment advice, and this project sends no orders.</p>
{_notices(status)}
<h2>{tag}Buy and hold</h2>
{_benchmark_section(status, benchmarks)}
<h2>{tag}Data coverage</h2>
<section>{_coverage_section(status)}</section>
<h2>{tag}Reconciliation</h2>
<section>{_reconciliation_section(status)}</section>
<h2>{tag}Hourly poll: how late is the schedule?</h2>
<section>{_poll_section(status)}</section>
<h2>{tag}Storage</h2>
<section>{_storage_section(status)}</section>
<footer>
<p>Code {_e(status["code_version"])}. Config {_e(status["config_hash"][:12])}. Run {_e(status["run_id"])}.</p>
<p>All times are UTC. Only statistics derived from market data are shown here.</p>
</footer>
</main>
<div id="tip" class="tip" role="status"></div>
<script id="chart-data" type="application/json">{payload}</script>
<script>{_SCRIPT}</script>
</body>
</html>
"""
