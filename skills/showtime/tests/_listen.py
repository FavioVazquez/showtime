"""Whether a test may listen on a local port. Stdlib only.

Some agent sandboxes refuse listen() (bind fails with EPERM, or node prints `listen EPERM`). A test that
serves fixtures over HTTP, or starts showtime's own server (preview, render, check, snap, export, site
capture --serve), skips there instead of failing, so run_all.py reports only real failures.

    from _listen import LISTEN_BLOCKED, needs_listen, skip_if_listen_refused

    @needs_listen                          # a class or a test that serves something
    class T(unittest.TestCase): ...
    need_listen()                          # inside a helper that is about to bind (raises SkipTest)
    skip_if_listen_refused(cp)             # after a subprocess: its server was refused -> SkipTest

SHOWTIME_TEST_NO_LISTEN=1 simulates such a sandbox (test_run_all checks the skips with it).
"""
from __future__ import annotations

import os
import re
import socket
import unittest
from typing import Optional


def _probe() -> Optional[str]:
    if os.environ.get("SHOWTIME_TEST_NO_LISTEN"):
        return "local servers are off (SHOWTIME_TEST_NO_LISTEN)"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
    except PermissionError as e:   # EPERM / EACCES: the sandbox forbids it (EADDRINUSE and co. are real errors)
        return "this sandbox does not allow listening on a local port (%s)" % e
    finally:
        s.close()
    return None


# why local servers cannot run here, or None when they can (checked once, at import)
LISTEN_BLOCKED: Optional[str] = _probe()

needs_listen = unittest.skipIf(LISTEN_BLOCKED, LISTEN_BLOCKED or "")

REFUSED_RX = re.compile(r"\blisten (EPERM|EACCES)\b|PermissionError: \[Errno (1|13)\]")


def need_listen() -> None:
    if LISTEN_BLOCKED:
        raise unittest.SkipTest(LISTEN_BLOCKED)


def skip_if_listen_refused(cp) -> None:
    """A subprocess (showtime render/check/snap/export, a node host) failed because its local server was
    refused: skip, as for a test that binds one itself."""
    out = "%s\n%s" % (getattr(cp, "stdout", "") or "", getattr(cp, "stderr", "") or "")
    if getattr(cp, "returncode", 0) != 0 and REFUSED_RX.search(out):
        raise unittest.SkipTest("this sandbox does not allow listening on a local port (%s)"
                                % REFUSED_RX.search(out).group(0))
