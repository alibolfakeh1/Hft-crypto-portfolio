"""The trial registry, rule 6 of CLAUDE.md and C12. Every stream of every run is logged, before it starts and
when it ends.

The file is append-only and lives under DATA_ROOT, in a zone no retention rule may select. A run that dies
still counts, because its start was written first, so a run cannot be tried quietly and registered only if it
looks good.

`trial_key` names what was tried, so repeating an identical run shows as a repeat and not as a new trial. A
generated run is logged too, with `counts_as_trial` false, because C12 says synthetic engineering tests do not
count.

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
) -> dict[str, Any]:
    """What identifies one trial. No clock in here, so this row is the same on every identical run."""
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
    }
    return {
        **identity,
        "trial_key": stable_hash(identity),
        "is_default": is_default,
        "in_portfolio": in_portfolio,
        "data_kind": data_kind,
        "counts_as_trial": data_kind == "MARKET",
        "risk_state": risk_state,
        "code_version": code_version,
        "control": False,
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

    def distinct_trials(self) -> int:
        """Distinct trials that count, so generated runs add none and a repeat adds none."""
        return len(
            {
                row["trial_key"]
                for row in self._rows()
                if row.get("event") == "trial_started" and row.get("counts_as_trial")
            }
        )

    def started(self, row: dict[str, Any], *, logged_at: str) -> None:
        self._append({**row, "event": "trial_started", "logged_at": logged_at})

    def finished(self, row: dict[str, Any], *, logged_at: str, result: dict[str, Any]) -> None:
        self._append({**row, "event": "trial_finished", "logged_at": logged_at, "result": result})
