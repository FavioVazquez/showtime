#!/usr/bin/env python3
"""`showtime release-video` (lib/st/release_video.py): release notes -> a renderable project, no agent.

Pure Python, no browser: the notes parser (GitHub's generated notes, Keep-a-Changelog sections,
conventional commits, wrapped bullets, bots and dependency bumps left out), the plan (reading-time holds,
the length budget, the "+ N more" count), the page (escaped, every word traceable to the notes or a flag),
the project files, and the CLI's errors. The render itself is covered on the box (check + render + qa).

usage: python tests/test_release_video.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import release_video as rv  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())

GH_NOTES = """<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* Add `--watch` mode to the dev server by @alice in https://github.com/acme/tool/pull/412
* feat(cli): colour output can be turned off with NO_COLOR by @bob in https://github.com/acme/tool/pull/415
### Bug Fixes
* Fix a crash when the config file is empty by @carol in https://github.com/acme/tool/pull/419
### Other Changes
* Bump lodash from 4.17.20 to 4.17.21 by @dependabot[bot] in https://github.com/acme/tool/pull/420

## New Contributors
* @carol made their first contribution in https://github.com/acme/tool/pull/419

**Full Changelog**: https://github.com/acme/tool/compare/v1.4.0...v1.5.0
"""

CHANGELOG = """# Changelog

## [Unreleased]
- Nothing yet

## [2.3.0] - 2026-09-01
Faster exports and a new `--dry-run` flag.

### Added
- `acme export --dry-run` shows what would be written, without writing it
  (the plan is printed as a table). (#88)
- A **Spanish** translation of the [docs](https://acme.dev/docs/es) (thanks @dani)

### Fixed
- Exports no longer hang on files larger than 2 GB (#91)

### Dependencies
- Bump pillow from 10.0 to 10.4

## [2.2.0] - 2026-07-10
### Added
- Something older
"""

FLAT = """Small release.

- feat: add a `--json` flag to `acme ls`
- fix!: `acme rm` now asks before deleting a folder
- chore: tidy the Makefile
- docs: fix typos
"""


def showtime(*args, check=True, cwd=None, stdin=None, timeout=120):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd, input=stdin,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def texts(sections):
    return [(s["key"], [i["text"] for i in s["items"]]) for s in sections]


class TestParse(unittest.TestCase):
    def test_github_generated_notes(self):
        n = rv.parse_notes(GH_NOTES)
        self.assertEqual(texts(n["sections"]), [
            ("new", ["Add `--watch` mode to the dev server", "Colour output can be turned off with NO_COLOR"]),
            ("fixed", ["Fix a crash when the config file is empty"])])
        first = n["sections"][0]["items"][0]
        self.assertEqual((first["refs"], first["authors"]), (["#412"], ["@alice"]))
        self.assertEqual(n["authors"], ["@alice", "@bob", "@carol"])          # the bot is not thanked
        self.assertEqual(n["compare"], "https://github.com/acme/tool/compare/v1.4.0...v1.5.0")
        self.assertEqual(n["skipped"], 2)                                     # the bump and "new contributors"

    def test_changelog_section_and_wrapped_bullets(self):
        sec = rv.changelog_section(CHANGELOG, "2.3.0")
        self.assertTrue(sec.startswith("# [2.3.0] - 2026-09-01"))
        self.assertNotIn("Something older", sec)
        self.assertEqual(rv.changelog_section(CHANGELOG, "v2.3.0"), sec)
        self.assertEqual(rv.changelog_section(CHANGELOG, "9.9.9"), "")
        n = rv.parse_notes(sec)
        self.assertEqual((n["version"], n["date"]), ("2.3.0", "2026-09-01"))
        self.assertEqual(n["summary"], "Faster exports and a new `--dry-run` flag.")
        self.assertEqual(texts(n["sections"]), [
            ("new", ["`acme export --dry-run` shows what would be written, without writing it "
                     "(the plan is printed as a table).",
                     "A Spanish translation of the docs"]),
            ("fixed", ["Exports no longer hang on files larger than 2 GB"])])
        self.assertEqual(n["sections"][0]["items"][0]["refs"], ["#88"])
        self.assertEqual(n["sections"][0]["items"][1]["authors"], ["@dani"])

    def test_conventional_commits_without_headings(self):
        n = rv.parse_notes(FLAT)
        self.assertEqual(texts(n["sections"]), [
            ("breaking", ["`acme rm` now asks before deleting a folder"]),
            ("new", ["Add a `--json` flag to `acme ls`"])])
        self.assertEqual(n["skipped"], 2)
        self.assertEqual(n["summary"], "Small release.")

    def test_html_in_code_spans_survives(self):
        n = rv.parse_notes("### Added\n- `showtime install --agent <name>` <b>installs</b> the skill\n")
        self.assertEqual(n["sections"][0]["items"][0]["text"], "`showtime install --agent <name>` installs the skill")

    def test_shorten_marks_the_cut(self):
        long = "word " * 40
        s = rv.shorten(long.strip(), 60)
        self.assertLessEqual(len(s), 60)
        self.assertTrue(s.endswith("…"))
        self.assertTrue(long.startswith(s[:-1]))
        self.assertEqual(rv.shorten("short", 60), "short")


class TestPlanAndPage(unittest.TestCase):
    def test_holds_follow_reading_time_and_budget(self):
        n = rv.parse_notes(GH_NOTES)
        p = rv.plan(n, name="acme-tool", version="1.5.0")
        ids = [s["id"] for s in p["scenes"]]
        self.assertEqual(ids, ["hook", "s1", "s2", "end"])
        for sc in p["scenes"][1:-1]:
            need = sum(rv.reading_time(i["text"]) for i in sc["section"]["items"])
            self.assertGreaterEqual(sc["dur"], need)
        self.assertEqual((p["shown"], p["total"], p["more"]), (3, 3, 0))
        many = {"sections": [{"key": "new", "title": "New", "items": [
            {"text": "A change described in a fairly long sentence number %d, as notes often are" % i,
             "refs": [], "authors": []} for i in range(12)]}], "authors": [], "summary": ""}
        p2 = rv.plan(many, name="x", max_seconds=30)
        self.assertLessEqual(rv.total_duration(p2) - 1.6, 30)
        self.assertGreaterEqual(p2["shown"], 1)
        self.assertEqual(p2["more"], 12 - p2["shown"])

    def test_page_says_only_what_the_notes_say(self):
        n = rv.parse_notes(rv.changelog_section(CHANGELOG, "2.3.0"))
        p = rv.plan(n, name="acme <tool>", version="2.3.0")
        page = rv.build_page(p, n, install="pip install -U acme", url="https://acme.dev", date="2026-09-01")
        self.assertIn("acme &lt;tool&gt;", page)                  # escaped
        self.assertNotIn("<tool>", page)
        body = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        words = set(re.findall(r"[A-Za-z]{4,}", html.unescape(re.sub(r"<[^>]+>", " ", body))))
        allowed = set(re.findall(r"[A-Za-z]{4,}", CHANGELOG + " acme tool pip install acme.dev"))
        allowed |= {"Release", "Thanks", "more", "release", "notes"}  # the page's own labels
        self.assertEqual(sorted(words - allowed), [])
        self.assertIn('data-start="#hook"', page)
        self.assertIn('data-st="camera"', page)
        self.assertIn("Thanks to @dani", page)
        self.assertIn('<code class="nw">--dry-run</code>', page)

    def test_write_project(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-rv-"))
        try:
            n = rv.parse_notes(GH_NOTES)
            p = rv.plan(n, name="acme-tool", version="1.5.0")
            res = rv.write_project(tmp / "p", n, p, aspect="9:16")
            cfg = json.loads((tmp / "p" / "showtime.json").read_text(encoding="utf-8"))
            self.assertEqual((cfg["width"], cfg["height"], cfg["poster"]), (1080, 1920, 0))
            self.assertAlmostEqual(cfg["duration"], res["duration"])
            self.assertEqual(cfg["expect"]["must_show"], ["acme-tool"])
            mix = json.loads((tmp / "p" / "audio" / "mix.json").read_text(encoding="utf-8"))
            self.assertEqual(mix["tracks"][0]["compose"]["style"], "minimal-pulse")
            self.assertEqual(len([t for t in mix["tracks"] if t["kind"] == "sfx"]), len(p["scenes"]) - 1)
            scenes = re.findall(r'data-dur="([\d.]+)"', (tmp / "p" / "index.html").read_text(encoding="utf-8"))
            self.assertAlmostEqual(sum(map(float, scenes)), cfg["duration"], places=1)
            with self.assertRaises(FileExistsError):
                rv.write_project(tmp / "p", n, p)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-rv-cli-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_changelog_and_stdin(self):
        log = self.tmp / "CHANGELOG.md"
        log.write_text(CHANGELOG, encoding="utf-8")
        cp = showtime("release-video", log, "--changelog-version", "2.3.0", "--name", "acme", "-o",
                      self.tmp / "a", "--json")
        res = json.loads(cp.stdout)
        self.assertEqual((res["shown"], res["title"]), (3, "acme v2.3.0"))
        cp = showtime("release-video", "-", "--kind", "pr", "--version", "482", "--name", "acme", "-o",
                      self.tmp / "b", stdin=FLAT)
        self.assertIn("wrote", cp.stdout)
        page = (self.tmp / "b" / "index.html").read_text(encoding="utf-8")
        self.assertIn("#482", page)
        self.assertIn("Pull request", page)

    def test_errors_are_friendly(self):
        cp = showtime("release-video", self.tmp / "missing.md", "-o", self.tmp / "x", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("notes file not found", cp.stderr)
        empty = self.tmp / "empty.md"
        empty.write_text("## Dependencies\n- Bump x from 1 to 2\n", encoding="utf-8")
        cp = showtime("release-video", empty, "-o", self.tmp / "y", check=False)
        self.assertIn("no user-facing changes", cp.stderr)
        log = self.tmp / "CHANGELOG.md"
        log.write_text(CHANGELOG, encoding="utf-8")
        cp = showtime("release-video", log, "--changelog-version", "7.0", "-o", self.tmp / "z", check=False)
        self.assertIn("no section for version 7.0", cp.stderr)
        showtime("release-video", log, "--changelog-version", "2.3.0", "-o", self.tmp / "w")
        cp = showtime("release-video", log, "--changelog-version", "2.3.0", "-o", self.tmp / "w", check=False)
        self.assertIn("is not empty", cp.stderr)
        for c in (cp,):
            self.assertNotIn("Traceback", c.stderr)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
