"""Code version and configuration hash, recorded by every run."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from hft_crypto import __version__


@lru_cache(maxsize=1)
def code_version() -> str:
    """Return the package version plus the git commit, marked dirty when the tree has changes."""
    sha = os.environ.get("GITHUB_SHA", "")
    dirty = ""
    if not sha:
        repo = Path(__file__).resolve().parent
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
            changed = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
            dirty = "-dirty" if changed else ""
        except (OSError, subprocess.SubprocessError):
            sha = "unknown"
    return f"{__version__}+{sha[:12]}{dirty}"


def stable_hash(value: Any) -> str:
    """Hash any JSON-compatible value independently of key order."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
