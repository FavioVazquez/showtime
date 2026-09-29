"""Run one test file, or one part of it, for run_all.py. Stdlib only.

    python tests/_part.py tests/test_render.py [--fast] [unittest args ...]

The test file runs exactly as `python tests/test_render.py ...` would (as __main__, same argv, same folder
on sys.path), with two additions:

ST_TEST_PLAN   a JSON file {"ids": [...], "known": [...], "catch_all": bool}: run only the tests whose id
               ("Class.test_method") is in "ids". With catch_all, also every test "known" does not list (a
               test the planner's scan missed, a load error), so a split never drops a test. A planned id the
               file does not have fails the run (the plan is stale).
ST_TEST_TIMES  a JSON file to write {"Class.test_method": seconds}: each test's time, counted from the end
               of the test before it (so a class's setUpClass counts toward its first test).
"""
from __future__ import annotations

import atexit
import json
import os
import runpy
import sys
import time
import unittest


def _short_id(test) -> str:
    tid = test.id()
    parts = tid.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else tid


def _flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flatten(t)
        else:
            yield t


def install_plan(plan: dict, loader=None) -> None:
    """Make unittest.main() load only this part's tests (see the module docstring)."""
    loader = loader or unittest.defaultTestLoader
    want = list(plan.get("ids") or [])
    want_set = set(want)
    known = set(plan.get("known") or []) | want_set
    catch_all = bool(plan.get("catch_all"))
    orig = loader.loadTestsFromModule

    def load(module, *args, **kwargs):
        suite = orig(module, *args, **kwargs)
        kept, found = [], set()
        for t in _flatten(suite):
            sid = _short_id(t) if isinstance(t, unittest.TestCase) else None
            if sid in want_set:
                kept.append(t)
                found.add(sid)
            elif catch_all and (sid is None or sid not in known):
                kept.append(t)
        missing = [i for i in want if i not in found]
        if missing:
            msg = ("the split plan names tests this file does not have: %s (run_all.py planned from an older "
                   "copy of the file; run again)" % ", ".join(missing[:5]))

            def stale():
                raise AssertionError(msg)
            kept.append(unittest.FunctionTestCase(stale, description="split plan"))
        return unittest.TestSuite(kept)

    loader.loadTestsFromModule = load


def install_timer(out_path: str) -> None:
    """Record each test's seconds into out_path when the process ends."""
    times = {}
    mark = [time.time()]
    base = unittest.TextTestRunner.resultclass or unittest.TextTestResult

    class TimedResult(base):
        def startTest(self, test):
            self._st_t0 = mark[0]
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            now = time.time()
            if isinstance(test, unittest.TestCase):
                times[_short_id(test)] = round(now - getattr(self, "_st_t0", now), 2)
            mark[0] = now

    unittest.TextTestRunner.resultclass = TimedResult

    def write():
        try:
            tmp = out_path + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(times, fh)
            os.replace(tmp, out_path)
        except OSError:
            pass

    atexit.register(write)


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write("usage: python tests/_part.py TEST_FILE [args ...]\n")
        raise SystemExit(2)
    path = os.path.abspath(argv[0])
    plan_file = os.environ.pop("ST_TEST_PLAN", "")
    times_file = os.environ.pop("ST_TEST_TIMES", "")
    if plan_file:
        with open(plan_file, encoding="utf-8") as fh:
            install_plan(json.load(fh))
    if times_file:
        install_timer(times_file)
    sys.argv = [path] + argv[1:]
    sys.path[0] = os.path.dirname(path)
    runpy.run_path(path, run_name="__main__")


if __name__ == "__main__":
    main()
