"""Imported first by every test file: the test runs from a fresh scratch folder.

showtime writes ./showtime-out/ (and a few other outputs) relative to the current folder when no job
or -o is given. A test started from the repository root would leave renders inside the repository, so
each test process moves to its own temporary folder, removed when it exits. Tests use absolute paths
(SKILL, TMP, ...) for everything they read.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

SCRATCH = tempfile.mkdtemp(prefix="st-test-cwd-")
os.chdir(SCRATCH)
atexit.register(shutil.rmtree, SCRATCH, True)
# the look history (st.variety.history) of test jobs stays in the scratch folder, never in the user's
# ~/.showtime/history (qa records a job's look when it passes)
os.environ.setdefault("SHOWTIME_HISTORY_DIR", os.path.join(SCRATCH, ".look-history"))
