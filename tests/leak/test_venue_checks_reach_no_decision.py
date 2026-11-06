"""Leak re-audit at be20ee7, RB-03: a venue check's result may only stop an ingest.

The checks after the fetch (`data/venue_checks.py`) leave their results in the manifest, in the catalog's
`venue_checks` meta and in the ingest summary. A strategy, the engine, a placebo or a report that read them
would let a fact about the whole span reach a decision: a tick dated from K3's last minute (RB-02), or a
symbol left out because a check failed. So no module may import the checks or name their results, except the
two that run them. The list says who may, and not who may not, so a new module cannot escape it.
"""

from __future__ import annotations

import ast

from engine_helpers import REPO_ROOT

PACKAGE = REPO_ROOT / "src" / "hft_crypto"
CHECKS = "venue_checks"
# The checks themselves, and stage one, which runs them and stops on them.
ALLOWED_TO_TOUCH_CHECKS = {"data/venue_checks.py", "data/ingest.py"}


def touches_checks(source: str) -> list[str]:
    """What in one module's source imports the checks or names their results."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if CHECKS in alias.name.split(".")]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if CHECKS in module.split("."):
                found.append(module)
            found += [alias.name for alias in node.names if alias.name == CHECKS]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and CHECKS in node.value:
            found.append(repr(node.value))
        elif isinstance(node, ast.Attribute) and node.attr == CHECKS:
            found.append(f".{CHECKS}")
        elif isinstance(node, ast.Name) and node.id == CHECKS:
            found.append(CHECKS)
    return found


def test_the_scanner_finds_each_way_in() -> None:
    """Otherwise the next test would pass by finding nothing. The auditor's VC1 read the catalog's meta, and
    VC2 a symbol's result."""
    ways_in = [
        "import hft_crypto.data.venue_checks",
        "import hft_crypto.data.venue_checks as checks",
        "from hft_crypto.data.venue_checks import funding_span",
        "from hft_crypto.data import venue_checks",
        "from .venue_checks import candle_span",
        "meta = catalog.get_meta('venue_checks')",
        "flag = summary.venue_checks['BTCUSDT']['F3']['pass']",
        "facts = record.check_detail.get('venue_checks')",
        "module = importlib.import_module('hft_crypto.data.venue_checks')",
        "result = venue_checks",
    ]
    assert [bool(touches_checks(line)) for line in ways_in] == [True] * len(ways_in)
    harmless = (
        "from hft_crypto.bars.reconcile import cross_venue_check\n"
        "from hft_crypto.data.ingest import QUARANTINE_LOG\n"
        "tick = engine.tick('BTCUSDT').at(now)\n"
    )
    assert touches_checks(harmless) == []


def test_no_module_but_stage_one_imports_the_checks_or_reads_their_results() -> None:
    """Every module in the package is scanned: the engine, the strategies, both placebos and the reports among
    them, and any module added later."""
    scanned = {path.relative_to(PACKAGE).as_posix(): path for path in PACKAGE.rglob("*.py")}
    assert {"engine/simulator.py", "engine/placebo.py", "strategies/placebo.py", "reports/report.py"} <= set(
        scanned
    )
    offenders = {
        name: found
        for name, path in scanned.items()
        if name not in ALLOWED_TO_TOUCH_CHECKS and (found := touches_checks(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}
    # Stage one is found, so the scan reads real modules.
    assert touches_checks(scanned["data/ingest.py"].read_text(encoding="utf-8"))
