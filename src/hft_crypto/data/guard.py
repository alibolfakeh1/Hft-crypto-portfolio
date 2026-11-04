"""Path guard: nothing under DATA_ROOT may touch a path outside it or pass through a link."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class PathGuardError(Exception):
    """A path resolves outside DATA_ROOT or passes through a symbolic link or junction."""


def _is_link(path: str) -> bool:
    """True for a symbolic link, a Windows junction, or any other reparse point."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


class PathGuard:
    """Checks paths against one root.

    The root is resolved once when the guard is created, so a root that itself sits behind a link is
    fine. Below the root, each existing component is inspected with lstat and no link is followed.
    """

    def __init__(self, root: str | Path) -> None:
        resolved = Path(os.path.realpath(root))
        if not resolved.is_dir():
            raise PathGuardError(f"DATA_ROOT is not a directory: {resolved}")
        self.root = resolved

    def check(self, path: str | Path) -> Path:
        """Return the absolute path, or raise when it is outside the root or crosses a link."""
        raw = Path(path)
        candidate = raw if raw.is_absolute() else self.root / raw
        normal = os.path.normpath(candidate)
        root_text = os.path.normcase(str(self.root))
        normal_case = os.path.normcase(normal)
        try:
            inside = os.path.commonpath([root_text, normal_case]) == root_text
        except ValueError:  # different drives on Windows
            inside = False
        if not inside:
            raise PathGuardError(f"path is outside DATA_ROOT: {path}")
        current = str(self.root)
        for part in Path(os.path.relpath(normal, self.root)).parts:
            if part == os.curdir:
                continue
            current = str(Path(current, part))
            if _is_link(current):
                raise PathGuardError(f"path passes through a link: {current}")
        return Path(normal)

    def relative(self, path: str | Path) -> str:
        """Return the checked path relative to the root, with forward slashes."""
        checked = self.check(path)
        return Path(os.path.relpath(checked, self.root)).as_posix()

    def unlink(self, path: str | Path) -> None:
        """Delete one regular file after checking it."""
        checked = self.check(path)
        info = os.lstat(checked)
        if not stat.S_ISREG(info.st_mode):
            raise PathGuardError(f"refusing to delete something that is not a file: {path}")
        checked.unlink()

    def remove_empty_parents(self, path: str | Path, stop_at: str) -> None:
        """Remove now-empty directories above a deleted file, stopping at a zone directory."""
        current = self.check(path).parent
        stop = self.check(stop_at)
        while current != stop and current != self.root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
