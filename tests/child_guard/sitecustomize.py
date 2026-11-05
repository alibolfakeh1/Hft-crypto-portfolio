"""The network guard. Python runs this file at the start of any child whose PYTHONPATH names this folder.

tests/conftest.py loads the same file for the test process, before collection, and points every child's
PYTHONPATH here.

An audit hook fires inside the C functions, so no patch, fixture scope or base class gets past it. It raises
from BaseException, because code under test catches Exception, and a broad catch must not turn this alarm into
an ordinary failure a test then expects. The suite makes no socket call at all, so it needs no allow-list for
addresses.

What this does not cover: Rust inside polars opens its own sockets, below the hook, so a source scan in
tests/data/test_safety.py refuses a URL passed to a polars reader. A raw socket in a non-Python child is
refused only by that child not being on the list of programs below.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REFUSED_EVENTS = frozenset(
    {
        "socket.connect",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    }
)
# git and bash for the publish script and the workflow tests, cmd for mklink, Python for one child.
_PROGRAMS = frozenset({"git", "bash", "sh", "cmd", "python", "python3", Path(sys.executable).stem.lower()})


class NetworkTouched(BaseException):
    """A test tried to reach a network, or to start a program that could."""


def _program(executable: object, args: object) -> str:
    """The name of what is being started. On Windows the event carries one command line, not a list."""
    if executable:
        first = str(executable)
    elif isinstance(args, str):
        text = args.strip()
        first = text[1:].split('"', 1)[0] if text.startswith('"') else (text.split() or [""])[0]
    else:
        items = list(args) if isinstance(args, list | tuple) else []
        first = str(items[0]) if items else ""
    return Path(first.replace("\\", "/")).stem.lower()


def _hook(event: str, args: tuple[object, ...]) -> None:
    if event in _REFUSED_EVENTS:
        raise NetworkTouched(f"a test tried to use the network: {event}")
    if event == "os.system":
        raise NetworkTouched("a test tried to start a shell command")
    if event == "subprocess.Popen":
        program = _program(args[0], args[1])
        if program not in _PROGRAMS:
            raise NetworkTouched(f"a test tried to start a program that is not on the list: {program}")


sys.addaudithook(_hook)
