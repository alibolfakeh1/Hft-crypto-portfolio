"""DATA_ROOT layout from docs/08_DATA_CENTER.md section 3, and the class of each zone."""

from __future__ import annotations

import datetime as dt
import os
import re
from enum import StrEnum
from pathlib import Path

from hft_crypto.data.guard import PathGuard, canonical_rel_path, is_link
from hft_crypto.timeutil import month_key

ZONE_DIRS = (
    "raw/archive",
    "raw/live",
    "curated",
    "features",
    "results/runs",
    "ledger",
    "decisions",
    "quarantine",
    "catalog",
)
SYNTHETIC_MARKER = "catalog/SYNTHETIC"
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class DataRootError(Exception):
    """DATA_ROOT is unset, or is somewhere it must not be."""


class DataClass(StrEnum):
    IRREPLACEABLE = "IRREPLACEABLE"
    RE_DOWNLOADABLE = "RE-DOWNLOADABLE"
    DERIVED = "DERIVED"


def classify(rel_path: str) -> DataClass | None:
    """Return the class given by the zone. None means the zone's class depends on the source.

    The class comes from the location, never from a catalog column, so that a bad catalog row cannot make
    irreplaceable data look deletable. A path that is not canonical is refused, not classified.
    """
    canonical_rel_path(rel_path)
    if rel_path.startswith(("raw/live/", "ledger/", "decisions/")):
        return DataClass.IRREPLACEABLE
    if rel_path.startswith("raw/archive/"):
        return DataClass.RE_DOWNLOADABLE
    if rel_path.startswith(("curated/", "features/", "results/")):
        return DataClass.DERIVED
    return None


MEASURED_ZONES = (
    "raw/archive",
    "raw/live",
    "curated",
    "features",
    "results",
    "ledger",
    "decisions",
    "quarantine",
    "catalog",
)


def _directory_size(path: Path) -> int:
    total = 0
    for current, directories, files in os.walk(path, followlinks=False):
        # os.walk enters a Windows junction, so links are removed by hand. Their targets are not ours.
        directories[:] = [d for d in directories if not is_link(Path(current, d))]
        for name in files:
            candidate = Path(current, name)
            try:
                if not is_link(candidate):
                    total += candidate.stat().st_size
            except OSError:
                continue
    return total


def measure_zones(root: DataRoot) -> dict[str, int]:
    """Bytes in each zone."""
    return {zone: _directory_size(root.guard.check(zone)) for zone in MEASURED_ZONES}


def _safe(component: str) -> str:
    if _COMPONENT.match(component) is None:
        raise DataRootError(f"unsafe path component: {component!r}")
    return component


class DataRoot:
    """Knows where everything goes. Each path it returns has passed the guard."""

    def __init__(self, root: str | Path, *, create: bool = True) -> None:
        path = Path(root)
        _refuse_inside_repository(path)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        self.guard = PathGuard(path)
        self.path = self.guard.root
        if create:
            for zone in ZONE_DIRS:
                self.guard.check(zone).mkdir(parents=True, exist_ok=True)

    @property
    def is_synthetic(self) -> bool:
        """True for a root holding generated data. Every output from it is labelled SYNTHETIC."""
        return self.guard.check(SYNTHETIC_MARKER).is_file()

    @property
    def catalog_path(self) -> Path:
        return self.guard.check("catalog/catalog.sqlite")

    @property
    def deletions_log(self) -> Path:
        return self.guard.check("catalog/deletions.jsonl")

    @property
    def poll_log(self) -> Path:
        return self.guard.check("catalog/poll_runs.jsonl")

    @property
    def pipeline_log(self) -> Path:
        return self.guard.check("catalog/pipeline_runs.jsonl")

    def heartbeat_path(self, service: str) -> Path:
        return self.guard.check(f"catalog/heartbeats/{_safe(service)}.json")

    def raw_archive_path(self, venue: str, dataset: str, symbol: str, day: dt.date, filename: str) -> Path:
        return self.guard.check(
            f"raw/archive/{_safe(venue)}/{_safe(dataset)}/{_safe(symbol)}"
            f"/date={day.isoformat()}/{_safe(filename)}"
        )

    def curated_dir(self, dataset: str, venue: str, symbol: str, day: dt.date) -> Path:
        return self.guard.check(
            f"curated/{_safe(dataset)}/venue={_safe(venue)}/symbol={_safe(symbol)}/month={month_key(day)}"
        )

    def curated_part(self, dataset: str, venue: str, symbol: str, day: dt.date) -> Path:
        return self.curated_dir(dataset, venue, symbol, day) / f"part-{day.isoformat()}.parquet"

    def curated_month_part(self, dataset: str, venue: str, symbol: str, day: dt.date) -> Path:
        return self.curated_dir(dataset, venue, symbol, day) / f"part-{month_key(day)}.parquet"

    def curated_parts(self, dataset: str, venue: str, symbol: str) -> list[Path]:
        """Return every finished part of a dataset, oldest first."""
        base = self.guard.check(f"curated/{_safe(dataset)}/venue={_safe(venue)}/symbol={_safe(symbol)}")
        if not base.is_dir():
            return []
        return sorted(base.glob("month=*/part-*.parquet"))

    def run_dir(self, run_id: str) -> Path:
        return self.guard.check(f"results/runs/{_safe(run_id)}")

    def quarantine_path(self, source_rel_path: str, stamp: str) -> Path:
        name = Path(source_rel_path)
        return self.guard.check(Path("quarantine") / name.parent / f"{stamp}-{name.name}")


def _refuse_inside_repository(path: Path) -> None:
    """Refuse a DATA_ROOT inside a git work tree, because market data must never get near a commit."""
    # Both the path as written and where it really leads, so a link into a work tree cannot get past this.
    for start in (Path(os.path.normpath(path.absolute())), Path(os.path.realpath(path))):
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                raise DataRootError(
                    "DATA_ROOT must be outside the repository, because the repository is public."
                )


def resolve_data_root(explicit: str | None = None, *, create: bool = True) -> DataRoot:
    """create=False is for commands that only look, so a mistyped path is an error and not a new data
    center."""
    value = explicit or os.environ.get("DATA_ROOT", "").strip()
    if not value:
        raise DataRootError("DATA_ROOT is not set. Set the environment variable or pass --data-root.")
    if not create and not Path(value).is_dir():
        raise DataRootError("DATA_ROOT does not exist. Run `init` or `ingest` first, or check the path.")
    return DataRoot(value, create=create)
