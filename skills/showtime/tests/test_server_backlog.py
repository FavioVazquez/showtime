#!/usr/bin/env python3
"""The test servers listen with a backlog of 128, not the default 5 that Windows refuses past (a browser or a
parallel fetch opens many connects at once). Every test file that starts an HTTP server subclasses
ThreadingHTTPServer with request_queue_size = 128; none starts a bare one.

Stdlib only. usage: python tests/test_server_backlog.py [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


class TestBacklog(unittest.TestCase):
    def test_no_bare_threading_http_server(self):
        bare = []
        for p in sorted(TESTS_DIR.glob("test_*.py")):
            if p.name == Path(__file__).name:
                continue
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"ThreadingHTTPServer\s*\(", line):
                    bare.append("%s:%d" % (p.name, n))
        self.assertEqual(bare, [], "start the server through the file's _Server (request_queue_size = 128)")

    def test_each_subclass_sets_the_backlog(self):
        for p in sorted(TESTS_DIR.glob("test_*.py")):
            if p.name == Path(__file__).name:
                continue
            src = p.read_text(encoding="utf-8")
            for m in re.finditer(r"class\s+\w+\(\s*(?:http\.server\.)?ThreadingHTTPServer\s*\):\n((?:[ \t]+.*\n|\n)*)", src):
                self.assertIn("request_queue_size = 128", m.group(1), p.name)


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"], verbosity=2 if "-v" in sys.argv else 1)
