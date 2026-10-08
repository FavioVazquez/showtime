#!/usr/bin/env python3
"""Reading the references by the piece, and starting a job in one command.

  * st.guide: sections and sub-sections (headings in code blocks ignored), line ranges, the section
    table (inserted at the end of the Essentials block, idempotent, current after an edit), section
    lookup by number, §number, name, part of a name, a `###` sub-heading, or position; topic lookup;
    --find across references;
  * `showtime guide` from the launcher without the venv (it is stdlib only): a topic's Essentials and
    sections, one section, several, a line range, --find, the topic list, --all, errors that say what exists;
  * scripts/check_release.py `guides`: every shipped reference has Essentials within budget, pointers that
    name real sections and a current table; the rule fails on bad samples and fixes a stale table;
  * the MCP `guide` tool (a section, find, bad input);
  * `showtime check` names a missing character of a loaded page font instead of advising another font;
  * doctor's quick-check cache (reused only when healthy, same key, fresh; `--fresh` bypasses it) and
    `showtime job init` printing the setup verdict on stderr while stdout stays the job folder.

Stdlib only; no setup needed except the job init case (it skips without the showtime environment).
usage: python tests/test_guide.py [--fast] [-v]
"""
from __future__ import annotations

import re
import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
REFS = SKILL / "references"
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import guide  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

HOME = showtime_home()
TMP = Path(tempfile.mkdtemp(prefix="st-guide-"))

SAMPLE = """# Sample reference

Read this when you test the guide.

## Essentials

- Always do the first thing (§1).
- Mind the speed (§ Speed).

## 1. First part

Text one.

```bash
## not a heading (inside a code block)
```

### alpha-widget
Alpha options.

### beta-widget
Beta options.

## 2. Second part

Text two.

## Speed

Fast.
"""


def tearDownModule():
    shutil.rmtree(str(TMP), ignore_errors=True)


def load_checker():
    spec = importlib.util.spec_from_file_location("check_release", str(REPO / "scripts" / "check_release.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def showtime(*args, env=None, cwd=None, check=True):
    e = dict(env or os.environ)
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=e, cwd=str(cwd or TMP),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=300)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                     cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def bare_env(home: Path):
    """An environment with an empty showtime home: no venv, so only stdlib commands can run."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHOWTIME_")}
    env["SHOWTIME_HOME"] = str(home)
    env["SHOWTIME_PROGRESS"] = "off"
    return env


class TestParse(unittest.TestCase):
    def test_sections_ranges_and_code_blocks(self):
        doc = guide.Doc(Path("s.md"), SAMPLE)
        self.assertEqual(doc.title, "Sample reference")
        self.assertEqual([s.title for s in doc.sections], ["Essentials", "1. First part", "2. Second part", "Speed"])
        first = doc.sections[1]
        self.assertEqual([c.name for c in first.children], ["alpha-widget", "beta-widget"])
        lines = SAMPLE.splitlines()
        for s in doc.sections + first.children:
            self.assertTrue(lines[s.start - 1].startswith("#"), s.title)
            self.assertTrue(lines[s.end - 1].strip(), "a range ends on content: %s" % s.title)
        self.assertEqual(lines[first.end - 1], "Beta options.")
        self.assertEqual(doc.intro, ["Read this when you test the guide."])
        self.assertEqual(doc.essentials_body(), ["- Always do the first thing (§1).", "- Mind the speed (§ Speed)."])

    def test_table_inserted_idempotent_and_current(self):
        new = guide.with_table(SAMPLE)
        self.assertIn(guide.TABLE_MARK, new)
        self.assertEqual(guide.with_table(new), new, "a second pass changes nothing")
        self.assertTrue(guide.table_current(new))
        doc = guide.Doc(Path("s.md"), new)
        lines = new.splitlines()
        rows = [l for l in lines if l.startswith("| ") and l.rstrip().endswith("|") and "Section" not in l]
        self.assertEqual(len(rows), 3)
        self.assertIn("1. First part: alpha-widget, beta-widget", rows[0])
        for row, sec in zip(rows, doc.body_sections()):
            a, b = row.rstrip(" |").rsplit("| ", 1)[1].split("-")
            self.assertEqual((int(a), int(b)), (sec.start, sec.end))
            self.assertEqual(lines[int(a) - 1].lstrip("# ").rstrip(), sec.title)
        self.assertEqual(doc.essentials_body(), ["- Always do the first thing (§1).", "- Mind the speed (§ Speed)."])
        # an edit above a section makes the table stale; the fix makes it current again
        edited = new.replace("Text one.", "Text one.\n\nMore text.\nAnd more.")
        self.assertFalse(guide.table_current(edited))
        fixed = guide.with_table(edited)
        d2 = guide.Doc(Path("s.md"), fixed)
        speed = d2.sections[-1]
        self.assertIn("| Speed | %d-%d |" % (speed.start, speed.end), fixed)
        self.assertEqual(guide.with_table("# T\n\nNo essentials.\n\n## One\n\nx\n"), "# T\n\nNo essentials.\n\n## One\n\nx\n")

    def test_find_section(self):
        doc = guide.Doc(Path("s.md"), guide.with_table(SAMPLE))
        pick = lambda sel: (guide.find_section(doc, sel)[0] or guide.Section(0, "-", 0)).title  # noqa: E731
        self.assertEqual(pick("2"), "2. Second part")
        self.assertEqual(pick("§2"), "2. Second part")
        self.assertEqual(pick("2."), "2. Second part")
        self.assertEqual(pick("second"), "2. Second part")
        self.assertEqual(pick("SPEED"), "Speed")
        self.assertEqual(pick("beta"), "beta-widget")
        self.assertEqual(pick("essentials"), "Essentials")
        self.assertIsNone(guide.find_section(doc, "9")[0])
        self.assertIsNone(guide.find_section(doc, "gamma")[0])
        sec, others = guide.find_section(doc, "widget")
        self.assertEqual((sec.title, [o.title for o in others]), ("alpha-widget", ["beta-widget"]))
        plain = guide.Doc(Path("p.md"), "# P\n\n## Alpha\n\na\n\n## Beta\n\nb\n")
        self.assertEqual(guide.find_section(plain, "2")[0].title, "Beta", "unnumbered: the n-th section")

    def test_topics_and_find(self):
        refs = TMP / "refs"
        (refs / "workflows").mkdir(parents=True, exist_ok=True)
        (refs / "crew").mkdir(exist_ok=True)
        for name in ("audio", "audio-extra", "workflows/launch-video", "workflows/data-story", "crew/critic"):
            (refs / (name + ".md")).write_text(SAMPLE.replace("Sample", name), encoding="utf-8")
        self.assertEqual(guide.resolve("audio", refs), ("audio", []))
        self.assertEqual(guide.resolve("references/audio.md", refs), ("audio", []))
        self.assertEqual(guide.resolve("launch", refs), ("workflows/launch-video", []))
        self.assertEqual(guide.resolve("launch-video", refs), ("workflows/launch-video", []))
        self.assertEqual(guide.resolve("critic", refs), ("crew/critic", []))
        self.assertEqual(guide.resolve("aud", refs), (None, ["audio", "audio-extra"]))
        self.assertEqual(guide.resolve("nothing", refs), (None, []))
        self.assertFalse(guide.needs_essentials("crew/critic"))
        self.assertFalse(guide.needs_essentials("index"))
        self.assertTrue(guide.needs_essentials("workflows/data-story"))
        docs = [(n, guide.Doc(p, p.read_text(encoding="utf-8"))) for n, p in guide.topics(refs).items()]
        hits, total = guide.find_lines(docs, "beta options")
        self.assertEqual(total, 5)
        self.assertTrue(any(h.startswith("audio §1 > beta-widget (line") for h in hits), hits)
        hits, total = guide.find_lines(docs[:1], "widget")
        self.assertTrue(hits[0].startswith(docs[0][0] + " §1 > alpha-widget (line "), hits)   # headings first

    def test_real_topics_resolve(self):
        for q, want in (("launch", "workflows/launch-video"), ("components", "components"), ("manim", "manim"),
                        ("data-story", "workflows/data-story"), ("looking", "looking")):
            self.assertEqual(guide.resolve(q, REFS)[0], want, q)


class TestRouter(unittest.TestCase):
    def test_skill_tables_name_topics_that_resolve(self):
        """SKILL.md routes by topic name (`showtime guide <topic>`): every name resolves to exactly one file,
        and every workflow is routed."""
        import re
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        a, b = text.index("## Situation"), text.index("## Red flags")
        names = set()
        for line in text[a:b].splitlines():
            if line.startswith("| ") and not line.startswith("|---"):
                cell = line.rstrip(" |").rsplit(" | ", 1)[-1] if "| The user wants" not in line else ""
                if line.startswith("| `"):              # the References table: topics in the first cell
                    cell = line.split(" | ")[0]
                names.update(n for n in re.findall(r"`([a-z][a-z0-9-]*)`", cell))
        self.assertGreaterEqual(len(names), 30, names)
        for n in sorted(names):
            got, cands = guide.resolve(n, REFS)
            self.assertIsNotNone(got, "SKILL.md names `%s`, which is not one reference (%s)" % (n, cands))
        routed = {guide.resolve(n, REFS)[0] for n in names}
        for wf in sorted(t for t in guide.topics(REFS) if t.startswith("workflows/")):
            self.assertIn(wf, routed, "SKILL.md does not route %s" % wf)


class TestCli(unittest.TestCase):
    """`showtime guide` runs without the venv (a fresh home), like before setup or from the MCP server."""

    @classmethod
    def setUpClass(cls):
        cls.env = bare_env(TMP / "no-setup-home")

    def test_topic_overview(self):
        cp = showtime("guide", "components", env=self.env)
        out = cp.stdout
        self.assertIn("references/components.md", out.splitlines()[0])
        self.assertIn("## Essentials", out)
        self.assertIn("Sections (showtime guide components", out)
        self.assertIn("count-up", out)
        self.assertNotIn(guide.TABLE_MARK, out)
        full = (REFS / "components.md").read_text(encoding="utf-8")
        self.assertLess(len(out), len(full) / 2, "the overview is a fraction of the file")

    def test_sections(self):
        out = showtime("guide", "components", "count-up", env=self.env).stdout
        self.assertTrue(out.startswith("components > count-up (references/components.md lines "), out[:200])
        self.assertIn("### count-up", out)
        self.assertNotIn("### steps", out)
        out = showtime("guide", "render", "showtime check", env=self.env).stdout
        self.assertIn("## `showtime check <project>`", out)
        two = showtime("guide", "manim", "1", "§2", env=self.env).stdout
        self.assertIn("## 1. ", two)
        self.assertIn("## 2. ", two)
        rng = showtime("guide", "story", "1-3", env=self.env).stdout
        self.assertEqual(rng.splitlines()[0], "references/story.md lines 1-3")
        self.assertEqual(rng.splitlines()[2], (REFS / "story.md").read_text(encoding="utf-8").splitlines()[0])

    def test_find_list_all_and_errors(self):
        out = showtime("guide", "--find", "count-up", env=self.env).stdout
        self.assertIn("components §3 > count-up", out)
        self.assertIn("print one: showtime guide", out)
        scoped = showtime("guide", "audio", "--find", "loudnorm", env=self.env, check=False)
        self.assertTrue(all(l.startswith("audio") for l in scoped.stdout.splitlines()[:-1] if " (line " in l))
        # several words after --find, unquoted: all of them are searched ("at" is not read as a topic)
        two = showtime("guide", "--find", "typewriter", "at", env=self.env)
        quoted = showtime("guide", "--find", "typewriter at", env=self.env)
        self.assertEqual(two.stdout, quoted.stdout)
        self.assertIn("components §2 > typewriter", two.stdout)
        self.assertNotIn("matches several references", two.stderr)
        self.assertEqual(showtime("guide", "audio", "--find", "loudnorm", "engine", env=self.env).stdout,
                         showtime("guide", "audio", "--find=loudnorm engine", env=self.env).stdout)   # the MCP form
        listing = showtime("guide", env=self.env).stdout
        self.assertIn("workflows/launch-video", listing)
        self.assertIn("crew/critic", listing)
        whole = showtime("guide", "receipt", "--all", env=self.env).stdout
        self.assertEqual(whole.rstrip("\n"), (REFS / "receipt.md").read_text(encoding="utf-8").rstrip("\n"))
        bad = showtime("guide", "no-such-topic", env=self.env, check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("no reference called 'no-such-topic'", bad.stderr)
        self.assertIn("showtime guide --find", bad.stderr)
        amb = showtime("guide", "s", env=self.env, check=False)
        self.assertEqual(amb.returncode, 1)
        self.assertIn("matches several references", amb.stderr)
        miss = showtime("guide", "manim", "no such section", env=self.env, check=False)
        self.assertEqual(miss.returncode, 1)
        self.assertIn("has no section 'no such section'", miss.stderr)
        self.assertIn("its sections: 1. When Manim, and which engine; 2. Quick path;", miss.stderr)
        none = showtime("guide", "--find", "zzqq-never-written", env=self.env, check=False)
        self.assertEqual(none.returncode, 1)
        self.assertIn("no line mentions", none.stdout)


class TestShippedReferences(unittest.TestCase):
    def test_every_reference_passes_the_guides_check(self):
        cr = load_checker()
        f = cr.Findings()
        cr.check_guides(f, fix=False)
        self.assertEqual(f.errors(), [], "\n".join("%s: %s" % (i["where"], i["message"]) for i in f.errors()))
        names = [n for n in guide.topics(REFS) if guide.needs_essentials(n)]
        self.assertGreaterEqual(len(names), 50)
        self.assertIn("workflows/launch-video", names)

    def test_checker_bites_and_fixes(self):
        cr = load_checker()
        refs = TMP / "bad-refs"
        (refs / "crew").mkdir(parents=True, exist_ok=True)
        (refs / "crew" / "role.md").write_text("# Role\n\nNo essentials needed.\n", encoding="utf-8")
        (refs / "index.md").write_text("# Index\n\n## A\n\nx\n", encoding="utf-8")
        (refs / "none.md").write_text("# None\n\nRead this.\n\n## 1. A\n\nx\n", encoding="utf-8")
        (refs / "long.md").write_text(guide.with_table(SAMPLE.replace(
            "- Mind the speed (§ Speed).", "\n".join("- rule %d" % i for i in range(45)))), encoding="utf-8")
        (refs / "pointer.md").write_text(guide.with_table(SAMPLE.replace("(§ Speed)", "(§7, § Nowhere)")),
                                         encoding="utf-8")
        stale = guide.with_table(SAMPLE).replace("Text two.", "Text two.\n\nand a new paragraph.")
        (refs / "stale.md").write_text(stale, encoding="utf-8")
        (refs / "late.md").write_text("# Late\n\nRead.\n\n## 1. A\n\nx\n\n## Essentials\n\n- y (§1)\n",
                                      encoding="utf-8")
        f = cr.Findings()
        cr.check_guides(f, fix=False, refs=refs)
        got = sorted((Path(re.sub(r":\d+$", "", i["where"])).name, i["message"][:30]) for i in f.errors())   # a Windows path has a drive colon
        where = [w for w, _ in got]
        self.assertNotIn("role.md", where)
        self.assertNotIn("index.md", where)
        self.assertIn(("none.md", "no `## Essentials` block after"), got)
        self.assertTrue(any(w == "long.md" and "is 46 lines" in m for w, m in
                            [(Path(i["where"]).name, i["message"]) for i in f.errors()]), got)
        msgs = [i["message"] for i in f.errors() if "pointer.md" in i["where"]]
        self.assertEqual(sorted(msgs), ["Essentials points at §7, which is not a section of this file",
                                        "Essentials points at §Nowhere, which is not a section of this file"])
        self.assertIn(("stale.md", "the section table is missing o"), got)
        self.assertIn(("late.md", "the Essentials block must be t"), got)
        f = cr.Findings()
        cr.check_guides(f, fix=True, refs=refs)
        self.assertTrue(guide.table_current((refs / "stale.md").read_text(encoding="utf-8")))
        self.assertFalse([i for i in f.errors() if "stale.md" in i["where"]])


class TestMcpGuide(unittest.TestCase):
    def test_guide_tool(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not found")
        from test_mcp import call, mcp, text_of
        env = {"SHOWTIME_HOME": str(TMP / "mcp-home")}
        out = mcp([{"method": "tools/list"},
                   call("guide", {"topic": "components", "section": "count-up"}),
                   call("guide", {"find": "count-up"}),
                   call("guide", {"section": "2"}),
                   call("guide", {"topic": "-h"})], TMP, env=env)
        r = out["results"]                               # r[0] answers initialize
        tools = {t["name"]: t for t in r[1]["response"]["result"]["tools"]}
        self.assertIn("guide", tools)
        self.assertFalse(r[2]["response"]["result"].get("isError"), text_of(r[2]))
        self.assertIn("### count-up", text_of(r[2]))
        self.assertNotIn("Files:", text_of(r[2]))
        self.assertIn("components §3 > count-up", text_of(r[3]))
        self.assertIn("section needs a topic", text_of(r[4]))
        self.assertIn('"topic" is not in the expected form', text_of(r[5]))


class TestDoctorCache(unittest.TestCase):
    def setUp(self):
        self.home = TMP / ("dc-home-%d" % time.time_ns())
        self.home.mkdir(parents=True)
        self._env = dict(os.environ)
        os.environ["SHOWTIME_HOME"] = str(self.home)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def result(self, fail=0, warn=0):
        rows = [{"check": "ffmpeg", "status": "pass", "detail": "ok", "hint": ""}]
        rows += [{"check": "models", "status": "warn", "detail": "one missing", "hint": "showtime setup"}] * warn
        rows += [{"check": "node", "status": "fail", "detail": "no node", "hint": "install Node.js 20+"}] * fail
        counts = {"pass": 1, "warn": warn, "fail": fail, "skip": 0}
        return {"ok": fail == 0, "version": "x", "counts": counts, "seconds": 1.2, "checks": rows}

    def test_cache_rules(self):
        from st import doctor
        self.assertIsNone(doctor.cached_quick())
        doctor.save_quick(self.result(warn=1))
        hit = doctor.cached_quick()
        self.assertIsNotNone(hit)
        self.assertLess(hit["cached_age_s"], 60)
        lines = doctor.quick_lines(hit)
        self.assertEqual(lines[0], "setup: ready (checked just now): 1 pass, 1 warn")
        self.assertEqual(lines[1:], ["  WARN  models  one missing", "        fix: showtime setup"])
        self.assertIsNone(doctor.cached_quick(max_age=-1), "too old")
        cwd = os.getcwd()
        try:
            os.chdir(str(self.home))                      # another working folder: another key
            self.assertIsNone(doctor.cached_quick())
        finally:
            os.chdir(cwd)
        doctor.save_quick(self.result(fail=1))            # a failing setup is never reused
        self.assertIsNone(doctor.cached_quick())
        self.assertFalse((self.home / "cache" / "doctor-quick.json").exists())
        bad = doctor.quick_lines(self.result(fail=1))
        self.assertTrue(bad[0].startswith("setup: NOT READY: 1 fail"))
        self.assertIn("        fix: install Node.js 20+", bad)

    def test_doctor_quick_reuses_and_fresh_rechecks(self):
        from st import doctor
        doctor.save_quick(self.result())
        env = dict(os.environ)
        env["SHOWTIME_OUTPUT"] = "brief"
        cp = showtime("doctor", "--quick", env=env, cwd=os.getcwd(), check=False)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("checked just now; --fresh checks again", cp.stdout)
        js = json.loads(showtime("doctor", "--quick", "--json", env=env, cwd=os.getcwd(), check=False).stdout)
        self.assertIn("cached_age_s", js)
        fresh = showtime("doctor", "--quick", "--fresh", "--json", env=env, cwd=os.getcwd(), check=False)
        self.assertNotIn("cached_age_s", json.loads(fresh.stdout))


GLYPH_HTML = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/editorial.css">
<style>
  html,body{margin:0;width:960px;height:540px;background:#f4efe6;color:#1b1b1b;overflow:hidden}
  .k{position:absolute;left:60px;top:200px;font:600 40px/1.2 "IBM Plex Mono", ui-monospace, monospace}
</style></head><body><p class="k">ANNUAL MEAN CO<sub>\u2082</sub></p>
<p class="k" style="top:320px">plain text</p></body></html>"""


class TestGlyphFallbackMessage(unittest.TestCase):
    """A loaded page font that lacks one character (CO + subscript 2) is named as a glyph fallback with the
    character, not as "load a font file" (that advice sent agents searching the disk for font files)."""

    def test_names_the_missing_character(self):
        env = build_env(HOME)
        if not (HOME / "node" / "node_modules" / "playwright").is_dir():
            self.skipTest("needs Node + Playwright (showtime setup)")
        proj = TMP / "glyph"
        proj.mkdir(exist_ok=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 960, "height": 540, "fps": 30, "duration": 2}),
                                            encoding="utf-8")
        (proj / "index.html").write_text(GLYPH_HTML, encoding="utf-8")
        cp = showtime("check", proj, "--json", "--no-timeline", "--no-determinism", "--samples", "2", env=env,
                      check=False)
        found = [f for f in json.loads(cp.stdout)["findings"] if f["code"] == "font_not_embedded"]
        self.assertTrue(found, cp.stdout[-2000:])
        msg = " ".join(f["message"] for f in found)
        self.assertIn("the page font is loaded", msg)
        self.assertIn("U+2082", msg)
        self.assertNotIn("is drawn with the system font", msg)


class TestJobInit(unittest.TestCase):
    def test_setup_verdict_on_stderr_job_on_stdout(self):
        from st import platform as plat
        if not plat.venv_python(HOME / "venv").exists():
            self.skipTest("needs the showtime environment (showtime setup)")
        env = build_env(HOME)
        env["SHOWTIME_PROGRESS"] = "off"
        work = TMP / "jobs"
        work.mkdir(exist_ok=True)
        cp = showtime("job", "init", "guide-test", "--goal", "a test", env=env, cwd=work)
        out = cp.stdout.strip().splitlines()
        self.assertEqual(len(out), 1, cp.stdout)
        self.assertTrue(Path(out[0]).is_dir())
        self.assertRegex(cp.stderr, r"setup: (ready|NOT READY)")
        cp2 = showtime("job", "init", "guide-test", "--no-check", env=env, cwd=work)
        self.assertNotIn("setup:", cp2.stderr)
        js = json.loads(showtime("job", "init", "guide-test", "--json", env=env, cwd=work).stdout)
        self.assertIn("setup", js)
        self.assertIn(js["setup"]["ok"], (True, False))


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_guide: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
