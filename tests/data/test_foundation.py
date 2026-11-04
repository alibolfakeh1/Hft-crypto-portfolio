"""Zones, path guard, atomic writes and the catalog."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import polars as pl
import pytest

from hft_crypto.data.atomic import (
    VerificationError,
    append_jsonl,
    atomic_write,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_parquet,
    read_parquet,
    sweep_temp_files,
)
from hft_crypto.data.catalog import Catalog, FileRecord
from hft_crypto.data.guard import PathGuard, PathGuardError
from hft_crypto.data.zones import ZONE_DIRS, DataClass, DataRoot, DataRootError, classify, resolve_data_root


def make_junction(link: Path, target: Path) -> bool:
    """Make a directory link without needing privileges. Windows uses a junction."""
    if os.name == "nt":
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
        )
        return done.returncode == 0
    link.symlink_to(target, target_is_directory=True)
    return True


def make_file_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target)
    except OSError:
        return False
    return True


# ---- zones -------------------------------------------------------------------------------------------------


def test_zones_are_exactly_those_of_the_data_center_document(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "root")
    found = {p.relative_to(root.path).as_posix() for p in root.path.rglob("*") if p.is_dir()}
    assert set(ZONE_DIRS) <= found
    assert found - set(ZONE_DIRS) == {"raw", "results"}


def test_partition_paths_follow_the_layout(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "root")
    day = dt.date(2026, 11, 3)
    archive = root.raw_archive_path("binance", "aggTrades", "BTCUSDT", day, "x.zip")
    assert root.guard.relative(archive) == "raw/archive/binance/aggTrades/BTCUSDT/date=2026-11-03/x.zip"
    curated = root.curated_part("trades", "binance", "BTCUSDT", day)
    assert (
        root.guard.relative(curated)
        == "curated/trades/venue=binance/symbol=BTCUSDT/month=2026-11/part-2026-11-03.parquet"
    )


@pytest.mark.parametrize("bad", ["../evil", "a/b", "..", ".hidden", "a b", "", "x\\y"])
def test_unsafe_path_components_are_refused(tmp_path: Path, bad: str) -> None:
    root = DataRoot(tmp_path / "root")
    with pytest.raises(DataRootError):
        root.curated_part("trades", bad, "BTCUSDT", dt.date(2026, 1, 1))


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("raw/live/kraken/book/BTCUSD/date=2026-01-01/x.gz", DataClass.IRREPLACEABLE),
        ("ledger/events.jsonl", DataClass.IRREPLACEABLE),
        ("decisions/x.json", DataClass.IRREPLACEABLE),
        ("raw/archive/binance/klines/BTCUSDT/date=2026-01-01/x.zip", DataClass.RE_DOWNLOADABLE),
        ("curated/trades/venue=a/symbol=b/month=2026-01/part.parquet", DataClass.DERIVED),
        ("features/f/1/symbol=b/month=2026-01/part.parquet", DataClass.DERIVED),
        ("results/runs/r/status.json", DataClass.DERIVED),
        ("quarantine/x", None),
        ("catalog/catalog.sqlite", None),
        ("somewhere/else", None),
    ],
)
def test_class_comes_from_the_zone(path: str, expected: DataClass | None) -> None:
    assert classify(path) is expected


def test_data_root_inside_a_repository_is_refused(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(DataRootError, match="outside the repository"):
        DataRoot(tmp_path / "repo" / "data")


def test_missing_data_root_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_ROOT", raising=False)
    with pytest.raises(DataRootError, match="not set"):
        resolve_data_root(None)


# ---- path guard --------------------------------------------------------------------------------------------


def test_guard_accepts_paths_inside(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    assert guard.check("curated/x.parquet") == tmp_path.resolve() / "curated" / "x.parquet"
    assert guard.relative(tmp_path / "a" / "b.txt") == "a/b.txt"


@pytest.mark.parametrize("escape", ["../outside.txt", "a/../../outside.txt", "..", "a/../.."])
def test_guard_refuses_relative_escapes(tmp_path: Path, escape: str) -> None:
    (tmp_path / "root").mkdir()
    guard = PathGuard(tmp_path / "root")
    with pytest.raises(PathGuardError, match="outside"):
        guard.check(escape)


def test_guard_refuses_absolute_path_elsewhere(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    (tmp_path / "rootsibling").mkdir()
    guard = PathGuard(tmp_path / "root")
    with pytest.raises(PathGuardError, match="outside"):
        guard.check(tmp_path / "rootsibling" / "x")
    with pytest.raises(PathGuardError, match="outside"):
        guard.check(tmp_path / "x")


def test_guard_refuses_a_directory_link_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep me")
    if not make_junction(tmp_path / "root" / "link", outside):
        pytest.skip("cannot create a directory link here")
    guard = PathGuard(tmp_path / "root")
    with pytest.raises(PathGuardError, match="link"):
        guard.check("link/secret.txt")
    with pytest.raises(PathGuardError, match="link"):
        guard.unlink("link/secret.txt")
    assert (outside / "secret.txt").read_text() == "keep me"


def test_guard_refuses_a_file_symlink(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    target = tmp_path / "target.txt"
    target.write_text("keep me")
    if not make_file_symlink(tmp_path / "root" / "link.txt", target):
        pytest.skip("creating file symlinks needs a privilege on this machine")
    guard = PathGuard(tmp_path / "root")
    with pytest.raises(PathGuardError, match="link"):
        guard.check("link.txt")
    assert target.read_text() == "keep me"


def test_guard_allows_a_root_that_sits_behind_a_link(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    if not make_junction(tmp_path / "via", real):
        pytest.skip("cannot create a directory link here")
    guard = PathGuard(tmp_path / "via")
    assert guard.check("x.txt").parent == Path(os.path.realpath(real))


def test_guard_unlink_refuses_a_directory(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    with pytest.raises(PathGuardError, match="not a file"):
        PathGuard(tmp_path).unlink("dir")


# ---- atomic writes -----------------------------------------------------------------------------------------


def test_atomic_write_publishes_only_after_verification(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    target = tmp_path / "x.bin"

    def bad_verify(path: Path) -> None:
        raise VerificationError("no")

    def write(path: Path) -> None:
        path.write_bytes(b"new")

    with pytest.raises(VerificationError):
        atomic_write(target, write, guard=guard, verify=bad_verify)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_rewrite_keeps_the_old_file(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    target = tmp_path / "x.bin"
    atomic_write_bytes(target, b"old", guard=guard)

    def boom(path: Path) -> None:
        path.write_bytes(b"half")
        raise OSError("disk trouble")

    with pytest.raises(OSError, match="disk trouble"):
        atomic_write(target, boom, guard=guard)
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["x.bin"]


def test_crash_during_rename_step_leaves_no_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    guard = PathGuard(tmp_path)
    target = tmp_path / "x.bin"

    def fail(*_: object) -> None:
        raise OSError("crash at the last moment")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="crash"):
        atomic_write_bytes(target, b"data", guard=guard)
    assert not target.exists()


def test_a_hard_process_kill_leaves_no_partition_that_looks_complete(tmp_path: Path) -> None:
    """A real crash: the process dies mid-write with no chance to clean up."""
    script = textwrap.dedent(
        f"""
        import os, pathlib, sys
        from hft_crypto.data.atomic import atomic_write
        from hft_crypto.data.guard import PathGuard

        root = pathlib.Path({str(tmp_path)!r})
        def write(path):
            with path.open("wb") as handle:
                handle.write(b"half a file")
                handle.flush()
                os._exit(9)

        atomic_write(root / "part-2026-01-01.parquet", write, guard=PathGuard(root))
        """
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, check=False, timeout=60)
    assert done.returncode == 9
    assert not (tmp_path / "part-2026-01-01.parquet").exists()
    leftovers = list(tmp_path.iterdir())
    assert len(leftovers) == 1
    # A reader's glob does not see it, and the next run removes it.
    assert list(tmp_path.glob("part-*.parquet")) == []
    assert sweep_temp_files(PathGuard(tmp_path), (".",)) == [leftovers[0].name]
    assert list(tmp_path.iterdir()) == []


def test_sweep_leaves_ordinary_files_alone(tmp_path: Path) -> None:
    (tmp_path / "part-1.parquet").write_bytes(b"x")
    (tmp_path / ".hidden").write_bytes(b"x")
    assert sweep_temp_files(PathGuard(tmp_path), (".",)) == []
    assert len(list(tmp_path.iterdir())) == 2


def test_parquet_round_trip_is_verified_and_repeatable(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    frame = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", None]})
    atomic_write_parquet(tmp_path / "one.parquet", frame, guard=guard)
    atomic_write_parquet(tmp_path / "two.parquet", frame, guard=guard)
    assert read_parquet(tmp_path / "one.parquet").equals(frame)
    assert (tmp_path / "one.parquet").read_bytes() == (tmp_path / "two.parquet").read_bytes()


def test_a_parquet_file_can_be_replaced_right_after_reading_it(tmp_path: Path) -> None:
    """On Windows a memory-mapped read would block this."""
    guard = PathGuard(tmp_path)
    target = tmp_path / "x.parquet"
    atomic_write_parquet(target, pl.DataFrame({"a": [1]}), guard=guard)
    held = read_parquet(target)
    atomic_write_parquet(target, pl.DataFrame({"a": [2]}), guard=guard)
    assert held["a"][0] == 1
    assert read_parquet(target)["a"][0] == 2


def test_writes_outside_the_root_are_refused(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    guard = PathGuard(tmp_path / "root")
    with pytest.raises(PathGuardError):
        atomic_write_bytes(tmp_path / "outside.bin", b"x", guard=guard)
    assert not (tmp_path / "outside.bin").exists()


def test_json_keeps_persian_text_readable(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    atomic_write_json(tmp_path / "x.json", {"متن": "معیار"}, guard=guard)
    assert "معیار" in (tmp_path / "x.json").read_text(encoding="utf-8")


def test_jsonl_only_appends(tmp_path: Path) -> None:
    guard = PathGuard(tmp_path)
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"a": 1}, guard=guard)
    append_jsonl(path, {"a": 2}, guard=guard)
    assert path.read_text().splitlines() == ['{"a": 1}', '{"a": 2}']


# ---- catalog -----------------------------------------------------------------------------------------------


def record(path: str, **changes: object) -> FileRecord:
    values: dict[str, object] = {
        "rel_path": path,
        "dataset_id": "d",
        "kind": "k",
        "partition_key": "2026-01-01",
        "date_start": "2026-01-01",
        "date_end": "2026-01-01",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "row_count": 1,
        "source_url": None,
        "created_at": "2026-01-02T00:00:00Z",
        "code_version": "test",
        "check_status": "pass",
        **changes,
    }
    return FileRecord(**values)  # type: ignore[arg-type]


def test_catalog_survives_reopening_and_is_one_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with Catalog(path) as catalog:
        catalog.register_file(record("a"))
    assert [p.name for p in tmp_path.iterdir()] == ["catalog.sqlite"]
    with Catalog(path) as catalog:
        found = catalog.get_file("a")
    assert found is not None
    assert found.size_bytes == 10


def test_opening_a_catalog_to_read_it_leaves_the_file_untouched(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    with Catalog(path) as catalog:
        catalog.register_file(record("a"))
    before = path.read_bytes()
    with Catalog(path) as catalog:
        assert catalog.get_file("a") is not None
        assert catalog.files() != []
    assert path.read_bytes() == before


def test_manifest_fields_of_the_lifecycle_document_are_stored(tmp_path: Path) -> None:
    with Catalog(tmp_path / "c.sqlite") as catalog:
        catalog.upsert_dataset(
            "d",
            zone="curated",
            kind="k",
            tier="T1",
            source="https://example/x",
            venue="v",
            symbol="s",
            terms_note="n",
            now="2026-01-01T00:00:00Z",
        )
        catalog.register_file(record("a", source_url="https://example/x/a.zip", check_detail={"rows": 5}))
        found = catalog.get_file("a")
    assert found is not None
    assert found.source_url == "https://example/x/a.zip"
    assert found.check_detail == {"rows": 5}
    assert found.sha256 == "a" * 64
    assert found.code_version == "test"


def test_descendants_and_ancestors_follow_the_chain(tmp_path: Path) -> None:
    with Catalog(tmp_path / "c.sqlite") as catalog:
        catalog.register_file(record("raw"))
        catalog.register_file(record("trades"), ["raw"])
        catalog.register_file(record("bars"), ["trades"])
        catalog.register_file(record("higher"), ["bars"])
        assert [f.rel_path for f in catalog.descendants_of("raw")] == ["bars", "higher", "trades"]
        assert [f.rel_path for f in catalog.ancestors_of("higher")] == ["bars", "raw", "trades"]


def test_reregistering_a_file_replaces_its_row_and_parents(tmp_path: Path) -> None:
    with Catalog(tmp_path / "c.sqlite") as catalog:
        catalog.register_file(record("a", size_bytes=1), ["x"])
        catalog.register_file(record("a", size_bytes=2), ["y"])
        found = catalog.get_file("a")
        assert found is not None
        assert found.size_bytes == 2
        assert catalog.parents_of("a") == ["y"]


def test_prefix_search_treats_wildcards_literally(tmp_path: Path) -> None:
    with Catalog(tmp_path / "c.sqlite") as catalog:
        catalog.register_file(record("raw/a_b/x"))
        catalog.register_file(record("raw/aXb/x"))
        assert [f.rel_path for f in catalog.files(prefix="raw/a_b/")] == ["raw/a_b/x"]
