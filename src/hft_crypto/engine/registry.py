"""The trial registry, rule 6 of CLAUDE.md and C12. Every stream of every run is logged, before it starts and
when it ends.

The file is append-only and lives under DATA_ROOT, in a zone no retention rule may select. A run that dies
still counts, because its start was written first, so a run cannot be tried quietly and registered only if it
looks good.

`trial_key` names what was tried, so repeating an identical run shows as a repeat and not as a new trial. A
generated run is logged too, with `counts_as_trial` false, because C12 says synthetic engineering tests do not
count.

**A run is not always one line.** S08's two branches are read separately, so one S08 run counts as two lines
and a run of all ten is 60 runs for 64 lines per symbol. On candles S07 and S08 run nothing, and count as no
line, so the candle stage stays 52 lines per symbol. `lines_counted` holds this on every row.

**A C15 draw is a control.** It is logged like any run and is not a trial. A run of a line's draws is one
counted `V0` against C15 reading, per strategy, under section 5 of the fold plan.

C12 also holds `RT` and stop slippage here: they are declared before the first market run, and a market run
refuses to start without them, or with values that differ.
"""

from __future__ import annotations

import json
from typing import Any

from hft_crypto.config import ConfigError
from hft_crypto.data.atomic import append_jsonl
from hft_crypto.data.zones import DataRoot
from hft_crypto.versioning import stable_hash

REGISTRY_PATH = "catalog/trial_registry.jsonl"
DECLARED = "costs_declared"


def trial_row(
    *,
    strategy: str,
    line: str,
    is_default: bool,
    in_portfolio: bool,
    symbol: str,
    params: dict[str, Any],
    mode: str,
    variant: str,
    tier: str,
    date_range: dict[str, str],
    costs: dict[str, Any],
    risk_state: str,
    data_kind: str,
    code_version: str,
    config_hash: str,
    manifest_hash: str,
    lines_counted: int,
    draw: int | None = None,
    control: bool = False,
) -> dict[str, Any]:
    """What identifies one trial. No clock in here, so this row is the same on every identical run. A C15 draw
    and a `V0S` run are controls, and count as no trial.
    """
    control = control or draw is not None
    identity = {
        "strategy": strategy,
        "line": line,
        "symbol": symbol,
        "params": params,
        "mode": mode,
        "variant": variant,
        "tier": tier,
        "date_range": date_range,
        "costs": costs,
        "config_hash": config_hash,
        "manifest_hash": manifest_hash,
        **({"draw": draw} if control else {}),
    }
    return {
        **identity,
        "trial_key": stable_hash(identity),
        "is_default": is_default,
        "in_portfolio": in_portfolio,
        "data_kind": data_kind,
        "counts_as_trial": data_kind == "MARKET" and lines_counted > 0 and not control,
        "lines_counted": 0 if control else lines_counted,
        "risk_state": risk_state,
        "code_version": code_version,
        "control": control,
        "used_for_selection": False,
    }


class TrialRegistry:
    def __init__(self, root: DataRoot) -> None:
        self._root = root
        self._path = root.guard.check(REGISTRY_PATH)

    def _rows(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        return [
            json.loads(line) for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    def _append(self, row: dict[str, Any]) -> None:
        append_jsonl(self._path, row, guard=self._root.guard)

    def declared(self) -> dict[str, float] | None:
        rows = [row for row in self._rows() if row.get("event") == DECLARED]
        return None if not rows else dict(rows[-1]["values"])

    def declare(self, values: dict[str, float], *, basis: str, logged_at: str) -> None:
        """Log the declared values once. The same values again add nothing, and others are refused."""
        current = self.declared()
        if current == values:
            return
        if current is not None:
            raise ConfigError(
                f"the registry holds other declared costs, {current}. A change is a new document version "
                "and a counted trial, so it is not made here"
            )
        self._append({"event": DECLARED, "values": values, "basis": basis, "logged_at": logged_at})

    def require_declared(self, values: dict[str, float]) -> None:
        current = self.declared()
        if current is None:
            raise ConfigError(
                "the registry holds no declared costs, so this market run is refused under C12. Log them "
                "first with --declare-costs"
            )
        if current != values:
            raise ConfigError(
                f"this run's costs {values} differ from the registry's {current}, so it is refused"
            )

    def _distinct(self) -> dict[str, dict[str, Any]]:
        return {
            row["trial_key"]: row
            for row in self._rows()
            if row.get("event") == "trial_started" and row.get("counts_as_trial")
        }

    def distinct_trials(self) -> int:
        """Distinct lines that count, so generated runs add none, a repeat adds none, and S08 adds two."""
        return sum(int(row["lines_counted"]) for row in self._distinct().values())

    def distinct_runs(self) -> int:
        """Distinct runs behind those lines. A run of all ten is 60 of these for 64 lines, per symbol."""
        return len(self._distinct())

    def placebo_readings(self) -> int:
        """Counted `V0` against C15 readings: one per strategy, line and data, whatever the symbols. Only a
        row with a draw is a C15 reading. A `V0S` run is a control with no draw, and is none.
        """
        return len(
            {
                (row["strategy"], row["line"], row["config_hash"], row["manifest_hash"])
                for row in self._rows()
                if row.get("event") == "trial_started"
                and row.get("control")
                and row.get("draw") is not None
                and row.get("data_kind") == "MARKET"
            }
        )

    def started(self, row: dict[str, Any], *, logged_at: str) -> None:
        self._append({**row, "event": "trial_started", "logged_at": logged_at})

    def finished(self, row: dict[str, Any], *, logged_at: str, result: dict[str, Any]) -> None:
        self._append({**row, "event": "trial_finished", "logged_at": logged_at, "result": result})
