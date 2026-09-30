import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from keelson import cli, envfile, rules  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_lines(self):
        got = envfile.parse('# c\n\nA=1\nexport B="two words"\nC=\'x\'\nD=3 # note\n')
        self.assertEqual([(e.key, e.value, e.line) for e in got],
                         [("A", "1", 3), ("B", "two words", 4), ("C", "x", 5), ("D", "3", 6)])

    def test_bad_line(self):
        with self.assertRaises(envfile.ParseError):
            envfile.parse("not a pair\n")


class RulesTest(unittest.TestCase):
    def test_check(self):
        env = envfile.parse("A=1\nB=\nA=2\nX=9\n")
        ex = envfile.parse("A=\nB=\nC=\n")
        got = {(f.severity, f.rule, f.key) for f in rules.check(env, ex)}
        self.assertEqual(got, {("error", "missing", "C"), ("error", "duplicate", "A"),
                               ("warning", "extra", "X"), ("warning", "empty", "B")})

    def test_strict(self):
        got = rules.check(envfile.parse("A=\n"), envfile.parse("A=\n"), strict=True)
        self.assertEqual([(f.severity, f.rule) for f in got], [("error", "empty")])

    def test_diff(self):
        d = rules.diff(envfile.parse("A=1\nB=2\n"), envfile.parse("B=3\nC=4\n"))
        self.assertEqual(d, {"only_in_first": ["A"], "only_in_second": ["C"], "different_values": ["B"]})


class CliTest(unittest.TestCase):
    def test_example_folder(self):
        here = os.path.join(os.path.dirname(__file__), "..", "examples")
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(["check", "--env", os.path.join(here, ".env"),
                             "--example", os.path.join(here, ".env.example"), "--format", "json"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(data["errors"], 2)      # DATABASE_URL missing, API_TIMEOUT duplicated
        self.assertEqual(data["warnings"], 2)    # SENTRY_DSN empty, DEBUG_SQL extra

    def test_init_blanks_values(self):
        with tempfile.TemporaryDirectory() as d:
            env, ex = os.path.join(d, ".env"), os.path.join(d, ".env.example")
            with open(env, "w") as fh:
                fh.write("# keep\nTOKEN=secret\nexport PORT=8080\n")
            with redirect_stdout(StringIO()):
                self.assertEqual(cli.main(["init", "--env", env, "--example", ex]), 0)
            with open(ex) as fh:
                self.assertEqual(fh.read(), "# keep\nTOKEN=\nexport PORT=\n")


if __name__ == "__main__":
    unittest.main()
