"""No test in this suite may reach a network, whatever it builds. Every test runs behind this guard.

The guard itself is tests/child_guard/sitecustomize.py. It is loaded here, as this file is imported, so it
holds from collection on and also covers module-level code and session fixtures. An audit hook cannot be
removed once set, which is the point.

Children: a dead proxy stops anything that respects one, git may use local paths only, and a Python child gets
the same hook through PYTHONPATH.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_GUARD_DIR = Path(__file__).resolve().parent / "child_guard"
# Nothing listens on this port, and it is on this machine.
_DEAD_PROXY = "http://127.0.0.1:9"

if "network_guard" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("network_guard", _GUARD_DIR / "sitecustomize.py")
    assert _spec is not None
    assert _spec.loader is not None
    _guard = importlib.util.module_from_spec(_spec)
    sys.modules["network_guard"] = _guard
    _spec.loader.exec_module(_guard)

for _name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ[_name] = _DEAD_PROXY
for _name in ("NO_PROXY", "no_proxy"):
    os.environ.pop(_name, None)
os.environ["GIT_ALLOW_PROTOCOL"] = "file"
_inherited = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = str(_GUARD_DIR) if not _inherited else f"{_GUARD_DIR}{os.pathsep}{_inherited}"
