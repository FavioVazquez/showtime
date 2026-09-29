#!/usr/bin/env python3
"""The test runner's own tests (stdlib only, a few seconds): the impact map behind `run_all.py --changed`
(tests/_impact.py), the splitter that runs long files in parts (tests/_split.py, tests/_part.py), the
recording hooks (tests/_trace/) and -j auto sizing.

Synthetic repositories and test files live in temp folders; the real repository is only read.

usage: python tests/test_run_all.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))
sys.path.insert(0, str(TESTS_DIR))

import _impact as I  # noqa: E402
import _split as S  # noqa: E402

GIT = shutil.which("git")
NODE = shutil.which("node")
SK = I.SKILL


def load_run_all():
    spec = importlib.util.spec_from_file_location("st_run_all_t", str(TESTS_DIR / "run_all.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ------------------------------------------------------------------ a small synthetic repository

MINI = {
    SK + "/lib/st/__init__.py": "",
    SK + "/lib/st/common.py": "import os\n",
    SK + "/lib/st/launcher.py": "from st import common\n\ndef route():\n    from st import doctor\n",
    SK + "/lib/st/doctor.py": "from st.voice import tts\n",
    SK + "/lib/st/cli.py": "from .common import os\n",
    SK + "/lib/st/cli_audio.py": "COMMANDS = {'audio': 'music and sound'}\n\ndef run():\n    from .audio import mix\n",
    SK + "/lib/st/cli_core.py": "COMMANDS = {'new': 'a project', 'render': 'shadowed by the node script'}\n",
    SK + "/lib/st/audio/__init__.py": "",
    SK + "/lib/st/audio/mix.py": "from . import synth\nfrom ..common import os\n",
    SK + "/lib/st/audio/synth.py": "import json\n",
    SK + "/lib/st/voice/__init__.py": "",
    SK + "/lib/st/voice/tts.py": "import json\n",
    SK + "/lib/st/brand/draft.py": ("import subprocess, sys\nLAUNCHER = 'x'\n"
                                    "def cap():\n    subprocess.run([sys.executable, LAUNCHER, 'site', 'capture'])\n"),
    SK + "/scripts/render.mjs": "import { a } from './lib/cli.mjs';\nimport './lib/stagehost';\n",
    SK + "/scripts/site.mjs": "import { a } from './lib/cli.mjs';\n",
    SK + "/scripts/lib/cli.mjs": "export const a = 1; runPyCli(['audio', 'mix']);\n",
    SK + "/scripts/lib/stagehost.mjs": "const p = path.join(SKILL, 'runtime', 'stage.js');\n",
    SK + "/runtime/stage.js": "/* stage */\n",
    SK + "/runtime/components/index.js": "import './chart.js';\n",
    SK + "/runtime/components/chart.js": "",
    SK + "/templates/dom/index.html": '<script src="/_st/components/index.js"></script>\n',
    SK + "/templates/dom/showtime.json": "{}\n",
    SK + "/tests/_isolate.py": "",
    SK + "/tests/fixtures/capture/index.html": "<p>hi</p>\n",
    SK + "/tests/test_alpha.py": ("import _isolate\nfrom st.launcher import route\n"
                                  "def t():\n    showtime('render', 'x')\n    showtime('new', 'dom', 'p')\n"),
    SK + "/tests/test_beta.py": ("import _isolate\nfrom st.audio import mix\n"
                                 "FIX = TESTS_DIR / 'fixtures' / 'capture'\n"),
    SK + "/tests/test_gamma.py": "import _isolate\nprint('poster.jpg', 'index.js')\n",
    SK + "/tests/test_skill_structure.py": "import _isolate\n",
    SK + "/SKILL.md": "# skill\n",
    "README.md": "# readme\n",
    "examples/01/final.mp4": "",
    "weird/new-thing.bin": "",
}
TESTS = ["test_alpha.py", "test_beta.py", "test_gamma.py", "test_skill_structure.py"]


def mini_map():
    return I.ImpactMap(list(MINI), reader=lambda rel: MINI[rel])


class TestStaticMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = mini_map()

    def reach(self, test):
        return set(self.m.reach(SK + "/tests/" + test))

    def test_python_imports_absolute_relative_and_lazy(self):
        e = self.m.edges
        self.assertIn(SK + "/lib/st/audio/synth.py", e[SK + "/lib/st/audio/mix.py"])     # from . import synth
        self.assertIn(SK + "/lib/st/common.py", e[SK + "/lib/st/audio/mix.py"])          # from ..common import
        self.assertIn(SK + "/lib/st/audio/mix.py", e[SK + "/lib/st/cli_audio.py"])       # import inside a function
        self.assertIn(SK + "/lib/st/__init__.py", e[SK + "/lib/st/audio/mix.py"])        # parent packages run too
        self.assertIn(SK + "/tests/_isolate.py", e[SK + "/tests/test_beta.py"])           # a test helper

    def test_commands_route_to_node_scripts_first(self):
        alpha = self.m.edges[SK + "/tests/test_alpha.py"]
        self.assertIn(SK + "/scripts/render.mjs", alpha)
        self.assertNotIn(SK + "/lib/st/cli_core.py", {f for f in self.m.commands["render"]})
        self.assertIn(SK + "/lib/st/cli_core.py", alpha)                                  # 'new'
        self.assertIn(SK + "/lib/st/cli_audio.py", self.m.edges[SK + "/scripts/lib/cli.mjs"])   # runPyCli
        self.assertIn(SK + "/scripts/site.mjs", self.m.edges[SK + "/lib/st/brand/draft.py"])  # launcher call

    def test_paths_templates_and_fixtures(self):
        self.assertIn(SK + "/runtime/stage.js", self.m.edges[SK + "/scripts/lib/stagehost.mjs"])  # path.join
        self.assertIn(SK + "/scripts/lib/stagehost.mjs", self.m.edges[SK + "/scripts/render.mjs"])  # no extension
        self.assertIn(SK + "/runtime/components/index.js", self.m.edges[SK + "/templates/dom/index.html"])  # /_st/
        alpha = self.reach("test_alpha.py")
        self.assertIn(SK + "/templates/dom/index.html", alpha)                            # template by name
        self.assertIn(SK + "/runtime/components/chart.js", alpha)                         # ... and what it loads
        self.assertIn(SK + "/tests/fixtures/capture/index.html", self.reach("test_beta.py"))  # a fixture folder

    def test_lone_data_names_and_common_names_match_nothing(self):
        self.assertEqual(self.m.edges[SK + "/tests/test_gamma.py"], {SK + "/tests/_isolate.py"})
        self.assertEqual(self.m.match_path(["poster.jpg"]), set())
        self.assertEqual(self.m.match_path(["index.js"]), set())
        self.assertEqual(self.m.match_path(["components", "index.js"]), {SK + "/runtime/components/index.js"})

    def test_test_files_and_runner_files_are_never_dependencies(self):
        m = I.ImpactMap(list(MINI) + [SK + "/tests/run_all.py"], reader=lambda rel: dict(
            MINI, **{SK + "/tests/fixtures/capture/index.html": "see tests/test_alpha.py and tests/run_all.py",
                     SK + "/tests/run_all.py": ""})[rel])
        self.assertEqual(m.edges[SK + "/tests/fixtures/capture/index.html"], set())

    def test_dispatch_only_edges_are_dropped(self):
        # importing the launcher is not a use of everything the doctor checks
        self.assertNotIn(SK + "/lib/st/voice/tts.py", self.reach("test_alpha.py"))

    def test_real_repository_places_every_skill_file(self):
        # in a child process without the recording hooks: reading every file to build the map is not a use
        # of those files by this test (else any change would pick this test through its recorded run)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ST_TRACE_")}
        cp = subprocess.run([sys.executable, "-c", REAL_REPO_CHECK], env=env, capture_output=True, text=True,
                            cwd=str(TESTS_DIR), timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        rep = json.loads(cp.stdout)
        if rep.get("skip"):
            self.skipTest(rep["skip"])
        print("  impact map: %.2fs cold, %.2fs cached (%d files)" % (rep["cold"], rep["warm"], rep["files"]),
              file=sys.stderr)
        self.assertLess(rep["warm"], 2.0)
        self.assertEqual(rep["unplaced"], [], "files no test reaches and no override names: add them to "
                                              "tests/_impact.py OVERRIDES (or a test that uses them)")


REAL_REPO_CHECK = r"""
import json, shutil, tempfile, time
from pathlib import Path
import _impact as I
files = I.repo_files()
SK = I.SKILL
if not any(f.startswith(SK + "/") for f in files):
    print(json.dumps({"skip": "no repository file list"}))
    raise SystemExit(0)
cache = Path(tempfile.mkdtemp(prefix="st-impact-")) / "scan.json"
try:
    t0 = time.time()
    m = I.ImpactMap(files, cache=cache)
    cold = time.time() - t0
    t0 = time.time()
    m = I.ImpactMap(I.repo_files(), cache=cache)
    warm = time.time() - t0
finally:
    shutil.rmtree(str(cache.parent), ignore_errors=True)
tests = [f for f in files if f.startswith(SK + "/tests/test_") and f.endswith(".py")]
reach = [m.reach(t) for t in tests]
tracked = set((I.git(I.REPO, "ls-files") or "").splitlines()) or set(files)   # work in progress may wait
unplaced = [f for f in files if f.startswith(SK + "/") and f in tracked and not I.overrides_for(f)
            and not any(f in r for r in reach)]
print(json.dumps({"cold": cold, "warm": warm, "files": len(files), "unplaced": unplaced}))
"""


class TestSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = mini_map()

    def sel(self, changed, deleted=(), traces=None):
        return I.select(TESTS, changed, list(deleted), self.m, traces)

    def test_static_selection_with_reasons(self):
        s = self.sel([SK + "/lib/st/audio/synth.py"])
        self.assertFalse(s["all"])
        # beta imports st.audio.mix; alpha runs `showtime render`, whose Node script mixes through
        # runPyCli(['audio', ...]) -> cli_audio -> st.audio.mix; gamma uses neither
        self.assertEqual(sorted(s["tests"]), ["test_alpha.py", "test_beta.py", "test_skill_structure.py"])
        f, chain, how = s["tests"]["test_beta.py"][0]
        self.assertEqual(f, SK + "/lib/st/audio/synth.py")
        self.assertEqual(chain, [SK + "/lib/st/audio/mix.py"])            # beta -> mix -> synth
        self.assertIn("static scan", how)
        self.assertIn(SK + "/scripts/render.mjs", s["tests"]["test_alpha.py"][0][1])
        text = "\n".join(I.explain_lines(s))
        self.assertIn("lib/st/audio/synth.py", text)

    def test_node_change_reaches_the_python_it_calls(self):
        s = self.sel([SK + "/lib/st/audio/mix.py"])
        self.assertIn("test_alpha.py", s["tests"])   # alpha -> render.mjs -> lib/cli.mjs -> audio -> cli_audio -> mix
        self.assertIn("test_beta.py", s["tests"])

    def test_test_file_itself_override_and_hygiene(self):
        s = self.sel([SK + "/tests/test_gamma.py", "README.md", SK + "/SKILL.md"])
        self.assertFalse(s["all"])
        self.assertEqual(sorted(s["tests"]), ["test_gamma.py", "test_skill_structure.py"])
        self.assertEqual(s["tests"]["test_gamma.py"][0][2], "the test file itself")
        self.assertEqual(self.sel([])["tests"], {})                       # no change: nothing at all

    def test_unplaced_and_deleted_files_run_everything(self):
        s = self.sel(["weird/new-thing.bin"])
        self.assertTrue(s["all"])
        self.assertEqual(s["unplaced"][0][0], "weird/new-thing.bin")
        s = self.sel([], deleted=[SK + "/lib/st/gone.py"])
        self.assertTrue(s["all"])
        self.assertIn("deleted", s["unplaced"][0][1])
        s = self.sel([], deleted=["docs/old.md"])                         # an override still places it
        self.assertFalse(s["all"])

    def test_recorded_use_beats_the_static_closure(self):
        rec = {"fast:test_alpha.py": {SK + "/scripts/render.mjs", SK + "/lib/st/common.py"},
               "fast:test_beta.py": {SK + "/lib/st/audio/mix.py", SK + "/lib/st/common.py"}}
        # statically alpha reaches mix.py (render -> cli.mjs -> audio); its recorded run never did
        s = self.sel([SK + "/lib/st/audio/mix.py"], traces=rec)
        self.assertEqual(sorted(s["tests"]), ["test_beta.py", "test_skill_structure.py"])
        s = self.sel([SK + "/lib/st/common.py"], traces=rec)
        self.assertIn("recorded", s["tests"]["test_alpha.py"][0][2])
        # a file no recorded run used falls back to the static closure, with a note
        s = self.sel([SK + "/lib/st/audio/synth.py"], traces=rec)
        self.assertIn("test_beta.py", s["tests"])
        self.assertTrue(s["notes"])
        # what the test names itself still counts (a template ffmpeg or Chrome reads is never recorded)
        s = self.sel([SK + "/templates/dom/showtime.json"], traces=rec)
        self.assertIn("test_alpha.py", s["tests"])
        # a test without a recorded run keeps its static closure
        s = self.sel([SK + "/lib/st/common.py"], traces={"fast:test_alpha.py": {SK + "/lib/st/common.py"}})
        self.assertIn("test_beta.py", s["tests"])

    def test_override_patterns(self):
        self.assertTrue(I.match_pattern("docs/a/b.md", "docs/**"))
        self.assertTrue(I.match_pattern(SK + "/templates/dom/README.md", SK + "/templates/**/*.md"))
        self.assertFalse(I.match_pattern(SK + "/templates/dom/index.html", SK + "/templates/**/*.md"))
        self.assertTrue(I.match_pattern("CHANGELOG.md", "*.md"))
        self.assertFalse(I.match_pattern("docs/README.md", "*.md"))
        self.assertTrue(I.match_pattern(SK + "/lib/st/cli_voice.py", SK + "/lib/st/cli_*.py"))
        self.assertFalse(I.match_pattern(SK + "/lib/st/voice/cli_x.py", SK + "/lib/st/cli_*.py"))


@unittest.skipUnless(GIT, "git not installed")
class TestChangedFiles(unittest.TestCase):
    def git(self, *args):
        cp = subprocess.run([GIT, "-C", str(self.repo)] + list(args), capture_output=True, text=True,
                            env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
                                     GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org"))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return cp.stdout

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="st-changed-"))
        self.git("init", "-q", "-b", "main")
        for name in ("a.py", "b.py", "c.py", "d.py"):
            (self.repo / name).write_text(name + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")

    def tearDown(self):
        shutil.rmtree(str(self.repo), ignore_errors=True)

    def test_committed_uncommitted_untracked_deleted_renamed(self):
        (self.repo / "a.py").write_text("changed\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "a")
        (self.repo / "b.py").write_text("uncommitted\n", encoding="utf-8")
        (self.repo / "new.py").write_text("untracked\n", encoding="utf-8")
        self.git("rm", "-q", "c.py")
        self.git("mv", "d.py", "e.py")
        changed, deleted, desc = I.changed_files("main", root=self.repo)
        self.assertEqual(changed, ["a.py", "b.py", "e.py", "new.py"])
        self.assertEqual(deleted, ["c.py"])
        self.assertIn("main", desc)
        # the default base: the first integration branch that exists (here main)
        self.assertEqual(I.changed_files(None, root=self.repo)[0], changed)

    def test_merge_base_ignores_the_base_branch_moving_on(self):
        self.git("checkout", "-q", "main")
        (self.repo / "b.py").write_text("main moved\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "main")
        self.git("checkout", "-q", "work")
        (self.repo / "a.py").write_text("mine\n", encoding="utf-8")
        self.assertEqual(I.changed_files("main", root=self.repo)[0], ["a.py"])

    def test_default_base_prefers_the_newer_copy_of_the_branch(self):
        (self.repo / "a.py").write_text("x\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "work 1")
        self.git("branch", "-f", "v0.2.0", "main")                 # a stale local integration branch
        self.git("update-ref", "refs/remotes/origin/v0.2.0", "HEAD")   # the fetched one already has work 1
        (self.repo / "b.py").write_text("y\n", encoding="utf-8")
        self.assertEqual(I.default_base(self.repo), "origin/v0.2.0")
        self.assertEqual(I.changed_files(None, root=self.repo)[0], ["b.py"])

    def test_bad_ref_is_a_clear_error(self):
        with self.assertRaises(RuntimeError) as cm:
            I.changed_files("no-such-branch", root=self.repo)
        self.assertIn("no-such-branch", str(cm.exception))


# ------------------------------------------------------------------ splitting

SAMPLE = textwrap.dedent('''
    import tempfile, unittest
    from pathlib import Path
    TMP = Path(tempfile.mkdtemp())
    SITE = TMP / "site"

    class Base(unittest.TestCase):
        def test_inherited(self):
            pass

    class A(Base):
        @classmethod
        def setUpClass(cls):
            cls.tmp = Path(tempfile.mkdtemp())

        def test_01_make(self):
            type(self).made = 1
            (self.tmp / "canvas").mkdir()

        def test_02_use(self):
            getattr(self, "made", None)

        def test_03_snap(self):
            if not (self.tmp / "canvas").exists():
                self.skipTest("needs test_01")

        def test_04_alone(self):
            (self.tmp / "own").mkdir()

        def test_05_calls(self):
            self.test_04_alone()

        def test_06_free(self):
            pass

    class B(unittest.TestCase):
        def test_x(self):
            (SITE / "sheet").mkdir()

    class C(unittest.TestCase):
        def test_y(self):
            (SITE / "sheet").exists()

        def test_z(self):
            pass

    class Helper:
        def test_not_a_case(self):
            pass
''')


class TestSplitter(unittest.TestCase):
    def ft(self, mode="methods", **kw):
        return S.FileTests(Path("test_sample.py"), mode, text=SAMPLE, **kw)

    def test_ids_include_inherited_tests_and_skip_non_cases(self):
        ids = self.ft().ids
        self.assertIn("A.test_inherited", ids)
        self.assertIn("Base.test_inherited", ids)
        self.assertNotIn("Helper.test_not_a_case", ids)
        self.assertEqual(len(ids), 11)

    def test_couplings_keep_tests_together(self):
        units = self.ft().units()
        flat = [i for u in units for i in u]
        self.assertEqual(sorted(flat), self.ft().ids)                      # every test exactly once
        self.assertEqual(len(flat), len(set(flat)))
        grp = {i: tuple(u) for u in units for i in u}
        self.assertEqual(grp["A.test_01_make"], grp["A.test_02_use"])      # class attribute
        self.assertEqual(grp["A.test_01_make"], grp["A.test_03_snap"])     # skipTest("needs test_01") + path
        self.assertEqual(grp["A.test_04_alone"], grp["A.test_05_calls"])   # a call
        self.assertEqual(grp["B.test_x"], grp["C.test_y"])                 # module scratch path, across classes
        self.assertNotEqual(grp["A.test_06_free"], grp["A.test_01_make"])
        self.assertNotEqual(grp["C.test_z"], grp["C.test_y"])

    def test_classes_mode_and_whole_classes(self):
        grp = {i: tuple(u) for u in self.ft("classes").units() for i in u}
        self.assertEqual(grp["A.test_06_free"], grp["A.test_01_make"])
        self.assertEqual(grp["C.test_z"], grp["B.test_x"])                  # C joined to B by the shared path
        grp = {i: tuple(u) for u in self.ft(whole_classes=["A"]).units() for i in u}
        self.assertEqual(grp["A.test_06_free"], grp["A.test_04_alone"])
        grp = {i: tuple(u) for u in self.ft(keep_together=[["A.test_06_free", "C.test_z"]]).units() for i in u}
        self.assertEqual(grp["A.test_06_free"], grp["C.test_z"])

    def test_assign_is_balanced_and_stable(self):
        units = [["a"], ["b"], ["c"], ["d", "e"]]
        w = {"a": 10, "b": 9, "c": 4, "d": 2, "e": 1}
        parts = S.assign(units, w, 2)
        self.assertEqual(parts, [["a", "d", "e"], ["b", "c"]])
        self.assertEqual(parts, S.assign(list(reversed(units)), w, 2))
        self.assertEqual(S.assign(units, w, 9), [["a"], ["b"], ["c"], ["d", "e"]])   # no empty parts
        self.assertEqual(S.part_count(100, 30, 10, 8), 4)
        self.assertEqual(S.part_count(100, 30, 2, 8), 2)
        self.assertEqual(S.part_count(100, 30, 10, 3), 3)
        self.assertEqual(S.part_count(20, 30, 10, 8), 1)

    def test_weights_use_recorded_times(self):
        ft = self.ft()
        times = {"fast:test_sample.py::A.test_01_make": 30.0}
        w = S.test_weights(ft, 40.0, times, "fast")
        self.assertEqual(w["A.test_01_make"], 30.0)
        self.assertAlmostEqual(sum(w.values()), 40.0, places=5)

    def test_every_split_file_parses_and_covers_its_tests(self):
        for name in S.SPLIT:
            ft = S.file_tests(TESTS_DIR / name)
            self.assertTrue(ft.ids, name)
            flat = [i for u in ft.units() for i in u]
            self.assertEqual(sorted(flat), ft.ids, name)
            self.assertEqual(len(flat), len(set(flat)), name)
            self.assertGreater(len(ft.units()), 1, "%s is in SPLIT but cannot split" % name)


PART_SAMPLE = textwrap.dedent('''
    import json, os, sys, unittest
    LOG = os.environ["PART_LOG"]

    def note(x):
        with open(LOG, "a") as fh:
            fh.write(x + "\\n")

    class A(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            note("setup A")
        def test_1(self):
            note("A.test_1")
        def test_2(self):
            note("A.test_2")

    class B(unittest.TestCase):
        def test_3(self):
            note("B.test_3")
            if os.environ.get("PART_FAIL"):
                self.fail("asked to fail")

    def make():
        class Dyn(unittest.TestCase):
            def test_dynamic(self):
                note("Dyn.test_dynamic")
        return Dyn
    Dyn = make()

    if __name__ == "__main__":
        assert sys.argv[1:] == ["--fast"], sys.argv
        argv = [a for a in sys.argv if a != "--fast"]
        prog = unittest.main(argv=argv, exit=False)
        sys.exit(0 if prog.result.wasSuccessful() else 1)
''')


class TestPartRunner(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="st-part-"))
        self.test = self.d / "test_sample.py"
        self.test.write_text(PART_SAMPLE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(str(self.d), ignore_errors=True)

    def run_part(self, plan=None, fail=False, tag="p"):
        log = self.d / ("%s.log" % tag)
        env = dict(os.environ, PART_LOG=str(log), ST_TEST_TIMES=str(self.d / ("%s.times.json" % tag)))
        if fail:
            env["PART_FAIL"] = "1"
        if plan is not None:
            (self.d / ("%s.plan.json" % tag)).write_text(json.dumps(plan), encoding="utf-8")
            env["ST_TEST_PLAN"] = str(self.d / ("%s.plan.json" % tag))
        cp = subprocess.run([sys.executable, str(TESTS_DIR / "_part.py"), str(self.test), "--fast"], env=env,
                            capture_output=True, text=True, cwd=str(self.d), timeout=120)
        ran = log.read_text().split("\n") if log.exists() else []
        times = json.loads((self.d / ("%s.times.json" % tag)).read_text())
        return cp, [x for x in ran if x], times

    def test_whole_file_runs_like_the_file_itself(self):
        cp, ran, times = self.run_part()
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(ran, ["setup A", "A.test_1", "A.test_2", "B.test_3", "Dyn.test_dynamic"])
        self.assertEqual(sorted(times), ["A.test_1", "A.test_2", "B.test_3", "Dyn.test_dynamic"])
        cp, _, _ = self.run_part(fail=True, tag="f")
        self.assertEqual(cp.returncode, 1)                 # the file's own exit code comes through

    def test_parts_cover_everything_once_and_catch_unknown_tests(self):
        known = ["A.test_1", "A.test_2", "B.test_3"]       # the scan missed Dyn.test_dynamic
        cp1, ran1, t1 = self.run_part({"ids": ["A.test_2"], "known": known, "catch_all": True}, tag="p1")
        cp2, ran2, t2 = self.run_part({"ids": ["A.test_1", "B.test_3"], "known": known, "catch_all": False},
                                      tag="p2")
        self.assertEqual((cp1.returncode, cp2.returncode), (0, 0), cp1.stderr + cp2.stderr)
        self.assertEqual(ran1, ["setup A", "A.test_2", "Dyn.test_dynamic"])   # class setup once per part
        self.assertEqual(ran2, ["setup A", "A.test_1", "B.test_3"])
        self.assertEqual(sorted(list(t1) + list(t2)), ["A.test_1", "A.test_2", "B.test_3", "Dyn.test_dynamic"])

    def test_stale_plan_fails_loudly(self):
        cp, ran, _ = self.run_part({"ids": ["A.test_1", "A.test_gone"], "known": ["A.test_1", "A.test_gone"],
                                    "catch_all": False})
        self.assertEqual(cp.returncode, 1)
        self.assertIn("A.test_gone", cp.stderr)
        self.assertIn("A.test_1", ran)


# ------------------------------------------------------------------ recording hooks

class TestTrace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="st-trace-root-"))
        self.out = Path(tempfile.mkdtemp(prefix="st-trace-out-"))
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "pkg" / "used.py").write_text("X = 1\n", encoding="utf-8")
        (self.root / "pkg" / "unused.py").write_text("Y = 1\n", encoding="utf-8")
        (self.root / "data.json").write_text("{}", encoding="utf-8")
        (self.root / "lib.mjs").write_text("export const a = 1;\n", encoding="utf-8")
        (self.root / "main.mjs").write_text(
            "import fs from 'node:fs';\nimport { a } from './lib.mjs';\n"
            "import { readFileSync } from 'node:fs';\n"
            "readFileSync(new URL('./served.css', import.meta.url));\n", encoding="utf-8")
        (self.root / "served.css").write_text("body{}", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(str(self.root), ignore_errors=True)
        shutil.rmtree(str(self.out), ignore_errors=True)

    def env(self):
        env = I.trace_env(dict(os.environ), self.out, root=self.root)
        env["PYTHONPATH"] = env["PYTHONPATH"] + os.pathsep + str(self.root)
        return env

    def test_python_imports_and_opens_are_recorded(self):
        code = ("import pkg.used, json; json.load(open(%r)); import pkg.used" % str(self.root / "data.json"))
        cp = subprocess.run([sys.executable, "-c", code], env=self.env(), capture_output=True, text=True,
                            cwd=str(self.out), timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stderr, "")                       # the hook never prints
        got = I.read_trace(self.out, root=self.root)
        self.assertEqual(got, {"pkg/__init__.py", "pkg/used.py", "data.json"})
        # a second run finds the imports cached (__pycache__/*.pyc): still recorded as the .py
        shutil.rmtree(str(self.out))
        subprocess.run([sys.executable, "-c", code], env=self.env(), capture_output=True, text=True,
                       cwd=str(self.root), timeout=60)
        self.assertEqual(I.read_trace(self.out, root=self.root), {"pkg/__init__.py", "pkg/used.py", "data.json"})

    @unittest.skipUnless(NODE, "node not found")
    def test_node_imports_and_reads_are_recorded(self):
        cp = subprocess.run([NODE, str(self.root / "main.mjs")], env=self.env(), capture_output=True, text=True,
                            cwd=str(self.out), timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stderr, "")                       # no warnings from the hook
        self.assertEqual(I.read_trace(self.out, root=self.root), {"main.mjs", "lib.mjs", "served.css"})

    def test_runner_files_are_not_recorded(self):
        (self.out / "py-1.txt").write_text("\n".join(str(I.REPO / x) for x in (
            I.TESTS + "/_part.py", I.TESTS + "/_trace/sitecustomize.py", I.SKILL + "/lib/st/common.py")) + "\n",
            encoding="utf-8")
        self.assertEqual(I.read_trace(self.out), {I.SKILL + "/lib/st/common.py"})

    def test_store_keeps_recent_runs(self):
        p = self.out / "store.json"
        I.save_traces(p, {"fast:test_a.py": {"x.py", "old.py"}})
        I.save_traces(p, {"fast:test_a.py": {"x.py", "y.py"}, "full:test_a.py": {"z.py"}})
        self.assertEqual(I.load_traces(p), {"fast:test_a.py": {"x.py", "y.py", "old.py"}, "full:test_a.py": {"z.py"}})
        for _ in range(I.TRACE_KEEP_RUNS - 1):
            I.save_traces(p, {"fast:test_a.py": {"x.py"}})
        self.assertEqual(I.load_traces(p)["fast:test_a.py"], {"x.py", "y.py"})    # old.py: unused for 5 runs
        I.save_traces(p, {"fast:test_a.py": {"x.py"}})
        self.assertEqual(I.load_traces(p)["fast:test_a.py"], {"x.py"})
        self.assertEqual(I.load_traces(p)["full:test_a.py"], {"z.py"})           # other keys untouched


# ------------------------------------------------------------------ run_all planning and sizing

class TestRunAllPlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ra = load_run_all()

    def test_auto_jobs_small_machines_unchanged(self):
        ra = self.ra
        for cpus, want in ((2, 1), (4, 2), (6, 3), (8, 4), (16, 8)):
            self.assertEqual(ra.machine_jobs(cpus, mem_gb=None), want, cpus)
        self.assertEqual(ra.machine_jobs(64, mem_gb=123), 32)
        self.assertEqual(ra.machine_jobs(64, mem_gb=40), 16)          # memory caps it
        self.assertEqual(ra.machine_jobs(64, mem_gb=4), 8)            # never below the small-machine rule
        self.assertEqual(ra.machine_jobs(192, mem_gb=None), ra.BIG_MAX_AUTO_JOBS)
        self.assertIsNone(ra.thread_share(8, 64))
        self.assertIsNone(ra.thread_share(4, 8))
        self.assertEqual(ra.thread_share(32, 64), 4)
        self.assertEqual(ra.thread_share(16, 64), 8)
        mem = ra.available_memory_gb()
        self.assertTrue(mem is None or mem > 0, mem)

    def test_plan_splits_only_long_files_and_never_serial(self):
        ra = self.ra
        tests = [TESTS_DIR / n for n in ("test_render.py", "test_film.py", "test_export.py", "test_runtime.py")]
        times = {"fast:test_render.py": 200.0, "fast:test_film.py": 2.0, "fast:test_export.py": 300.0}
        items = ra.plan_items(tests, 16, "fast", times)
        by = {}
        for it in items:
            by.setdefault(it["file"], []).append(it)
        self.assertGreater(len(by["test_render.py"]), 1)
        self.assertEqual(len(by["test_film.py"]), 1)
        self.assertEqual(len(by["test_export.py"]), 1)                # SERIAL: never split
        self.assertIsNone(by["test_runtime.py"][0]["est"])            # no timing yet: starts first
        parts = by["test_render.py"]
        ids = [i for it in parts for i in it["ids"]]
        self.assertEqual(sorted(ids), parts[0]["known"])              # each test in exactly one part
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([it["catch_all"] for it in parts], [True] + [False] * (len(parts) - 1))
        self.assertTrue(all(it["wrap"] for it in parts))
        # one job at a time, or --no-split: whole files only
        self.assertTrue(all(it["part"] is None for it in ra.plan_items(tests, 1, "fast", times)))
        self.assertTrue(all(it["part"] is None for it in ra.plan_items(tests, 16, "fast", times, split=False)))
        # fewer jobs than a big machine runs (a laptop, a CI runner): whole files, as before
        self.assertTrue(all(it["part"] is None for it in ra.plan_items(tests, ra.SPLIT_MIN_JOBS - 1, "fast", times)))
        order = [it["label"] for it in ra.lpt_items(items)]
        self.assertEqual(order[0], "test_runtime.py")

    def test_verify_split_catches_lost_and_repeated_tests(self):
        ra = self.ra
        items = [{"file": "test_x.py", "label": "test_x.py[1/2]", "part": (1, 2), "known": ["A.a", "A.b", "A.c"]},
                 {"file": "test_x.py", "label": "test_x.py[2/2]", "part": (2, 2), "known": ["A.a", "A.b", "A.c"]}]
        ok = [{"test": "test_x.py[1/2]", "ok": True, "test_times": {"A.a": 1, "A.extra": 1}},
              {"test": "test_x.py[2/2]", "ok": True, "test_times": {"A.b": 1, "A.c": 1}}]
        self.assertEqual(ra.verify_split(items, ok), [])
        bad = [{"test": "test_x.py[1/2]", "ok": True, "test_times": {"A.a": 1, "A.b": 1}},
               {"test": "test_x.py[2/2]", "ok": True, "test_times": {"A.b": 1}}]
        (label, note), = ra.verify_split(items, bad)
        self.assertIn("A.c", note)
        self.assertIn("A.b", note)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
