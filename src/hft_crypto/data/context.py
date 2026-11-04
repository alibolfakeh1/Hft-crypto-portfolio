"""What a running job needs, and the shared bookkeeping for files it produces."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hft_crypto.config import PipelineConfig, RetentionPolicy
from hft_crypto.data.atomic import atomic_write_json, sha256_file
from hft_crypto.data.catalog import Catalog, FileRecord
from hft_crypto.data.zones import DataRoot
from hft_crypto.timeutil import iso, utcnow
from hft_crypto.versioning import code_version


@dataclass
class JobContext:
    root: DataRoot
    catalog: Catalog
    config: PipelineConfig
    policy: RetentionPolicy
    now: Callable[[], dt.datetime] = field(default=utcnow)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def now_iso(self) -> str:
        return iso(self.now())

    def relative(self, path: str | Path) -> str:
        return self.root.guard.relative(path)

    def register_output(
        self,
        path: Path,
        *,
        dataset_id: str,
        kind: str,
        zone: str,
        partition_key: str | None,
        date_start: str | None,
        date_end: str | None,
        rows: int | None,
        check_status: str,
        check_detail: dict[str, Any] | None = None,
        parents: Iterable[str] = (),
        source_url: str | None = None,
        tier: str | None = None,
        venue: str | None = None,
        symbol: str | None = None,
        terms_note: str | None = None,
    ) -> FileRecord:
        """Enter one finished file into the manifest."""
        now = self.now_iso()
        self.catalog.upsert_dataset(
            dataset_id,
            zone=zone,
            kind=kind,
            tier=tier,
            source=source_url.rsplit("/", 1)[0] if source_url else None,
            venue=venue,
            symbol=symbol,
            terms_note=terms_note,
            now=now,
        )
        record = FileRecord(
            rel_path=self.relative(path),
            dataset_id=dataset_id,
            kind=kind,
            partition_key=partition_key,
            date_start=date_start,
            date_end=date_end,
            size_bytes=path.stat().st_size,
            sha256=sha256_file(path),
            row_count=rows,
            source_url=source_url,
            created_at=now,
            code_version=code_version(),
            check_status=check_status,
            check_detail=check_detail,
            checked_at=now,
        )
        self.catalog.register_file(record, parents)
        return record


def write_heartbeat(root: DataRoot, service: str, *, now: dt.datetime, detail: dict[str, Any]) -> None:
    """Record that a service ran. An outside check reads the age of what it publishes."""
    atomic_write_json(
        root.heartbeat_path(service),
        {"service": service, "at": iso(now), "code_version": code_version(), **detail},
        guard=root.guard,
    )
