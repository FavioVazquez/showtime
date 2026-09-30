#!/usr/bin/env python3
"""The showtime-video GitHub Action (stdlib + PyYAML, a few seconds, no render).

Covers .github/actions/showtime-video/:
  - action.yml: composite, every run step has a shell, every inputs.X used is declared and every declared
    input is used, outputs map to real step ids, the pinned `uses:` versions are the ones e2e.yml / ci.yml pin
  - the example workflow docs/examples/showtime-release-video.yml parses and points at this action
  - run.py --dry-run in each mode (release from a release event and from a pull_request event, project,
    agent): the command sequence, the resolved notes/title/version, nothing written
  - run.py functions: notes resolution and its order, slug, GITHUB_OUTPUT writing, cache key, upload command
  - run.py end to end against a fake showtime checkout (a shim that writes the files the real commands
    write): outputs, staged upload files, the exit code of a qa FAIL, the agent mode's independent check

Nothing is written into the repository: every file goes to a temp folder.

usage: python tests/test_action.py [--fast] [-v]
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent.parent.parent
ACTION_DIR = REPO / ".github" / "actions" / "showtime-video"
ACTION_YML = ACTION_DIR / "action.yml"
RUN_PY = ACTION_DIR / "run.py"
EXAMPLE = REPO / "docs" / "examples" / "showtime-release-video.yml"
DOC = REPO / "docs" / "github-action.md"
E2E = REPO / ".github" / "workflows" / "e2e.yml"
CI = REPO / ".github" / "workflows" / "ci.yml"

try:
    import yaml  # type: ignore
except ImportError:  # the showtime venv has PyYAML; a bare system Python may not
    yaml = None

SKIP_YAML = "PyYAML is not installed in this Python (it is in the showtime venv); the YAML checks are skipped"

sys.dont_write_bytecode = True   # importing run.py must not leave a __pycache__ in the repository
spec = importlib.util.spec_from_file_location("showtime_video_run", str(RUN_PY))
run = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
sys.modules["showtime_video_run"] = run
spec.loader.exec_module(run)  # type: ignore[union-attr]

BANNED = ["br" + "ag", "video" + "-use", "video" + "skill", "hyper" + "frames", "re" + "motion", "matt" + "pocock",
          "super" + "powers"]

RELEASE_BODY = ("## What's new\n\n- Faster sync (#12) by @alice\n- New dark theme\n\n## Fixes\n\n"
                "- Crash on empty input\n")
CHANGELOG = ("# Changelog\n\n## 2.0.0 - 2026-09-01\n\n- Two point oh\n\n## 1.9.0 - 2026-08-01\n\n- Older change\n")


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def steps_of(doc):
    return doc["runs"]["steps"]


def env_for(tmp: Path, event_name: str = "", event: object = None, **inputs: str) -> dict:
    """A clean fake GitHub environment (only what run.py reads) plus INPUT_* values."""
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_REPOSITORY": "acme/widget", "RUNNER_TEMP": str(tmp / "runner"),
           "GITHUB_WORKSPACE": str(tmp / "ws"), "GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_OUTPUT": str(tmp / "out.txt"), "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"}
    (tmp / "ws").mkdir(exist_ok=True)
    if event is not None:
        env_for.count += 1
        ev = tmp / ("event-%d.json" % env_for.count)
        ev.write_text(json.dumps(event), encoding="utf-8")
        env["GITHUB_EVENT_PATH"] = str(ev)
        env["GITHUB_EVENT_NAME"] = event_name
    for k, v in inputs.items():
        env["INPUT_" + k.upper()] = v
    return env


env_for.count = 0


def release_event(body: str = RELEASE_BODY) -> dict:
    return {"action": "published", "release": {
        "tag_name": "v2.3.0", "name": "Widget 2.3", "body": body, "published_at": "2026-09-29T10:00:00Z",
        "html_url": "https://github.com/acme/widget/releases/tag/v2.3.0"}}


def pr_event(body: str = "- Adds a dark theme\n- Remembers the choice\n") -> dict:
    return {"action": "opened", "number": 42, "pull_request": {
        "number": 42, "title": "Add a dark theme", "body": body, "html_url": "https://github.com/acme/widget/pull/42"}}


def dry_run_commands(env: dict, sub: str = "run") -> list:
    """Run run.py --dry-run as a subprocess and return the `+ ` command lines (launcher shown as showtime)."""
    cp = subprocess.run([sys.executable, str(RUN_PY), sub, "--dry-run"], env=env, universal_newlines=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if cp.returncode != 0:
        raise AssertionError("run.py --dry-run exit %s\nstdout:\n%s\nstderr:\n%s" % (cp.returncode, cp.stdout, cp.stderr))
    return [ln[2:] for ln in cp.stdout.splitlines() if ln.startswith("+ ")], cp.stdout


# ---------------------------------------------------------------------------
# action.yml
# ---------------------------------------------------------------------------

@unittest.skipIf(yaml is None, SKIP_YAML)
class TestActionYaml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load_yaml(ACTION_YML)
        cls.text = ACTION_YML.read_text(encoding="utf-8")

    def test_no_top_level_action_yml(self):
        self.assertFalse((REPO / "action.yml").exists() or (REPO / "action.yaml").exists(),
                         "the action lives in .github/actions/showtime-video/ only")

    def test_metadata(self):
        d = self.doc
        self.assertTrue(d.get("name"))
        self.assertTrue(d.get("description"))
        self.assertEqual(d["runs"]["using"], "composite")
        if "branding" in d:
            self.assertIn("icon", d["branding"])
            self.assertIn("color", d["branding"])

    def test_every_run_step_has_a_shell(self):
        for i, st in enumerate(steps_of(self.doc)):
            if "run" in st:
                self.assertIn("shell", st, "step %d (%s) has run: but no shell:" % (i, st.get("name")))
            self.assertTrue("run" in st or "uses" in st, "step %d has neither run nor uses" % i)

    def test_inputs_declared_and_used(self):
        declared = set(self.doc["inputs"])
        used = set(re.findall(r"\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}", self.text))
        used |= set(re.findall(r"inputs\.([A-Za-z0-9_-]+)", self.text))
        self.assertEqual(sorted(used - declared), [], "inputs used but not declared")
        self.assertEqual(sorted(declared - used), [], "inputs declared but never used")
        for name, spec_ in self.doc["inputs"].items():
            self.assertTrue(spec_.get("description"), "input %s has no description" % name)
            self.assertIn("default", spec_, "input %s has no default (an unset input would be null)" % name)

    def test_outputs_map_to_step_ids(self):
        ids = {st["id"] for st in steps_of(self.doc) if "id" in st}
        outs = self.doc["outputs"]
        self.assertEqual(sorted(outs), ["html", "job", "poster", "qa", "vertical", "video"])
        for name, o in outs.items():
            m = re.fullmatch(r"\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)\s*\}\}", o["value"])
            self.assertTrue(m, "output %s: %r" % (name, o["value"]))
            self.assertIn(m.group(1), ids, "output %s reads step %s, which has no such id" % (name, m.group(1)))
            self.assertEqual(m.group(2), name)

    def test_step_references_exist_and_come_before(self):
        seen = set()
        for st in steps_of(self.doc):
            blob = json.dumps(st)
            for ref in re.findall(r"steps\.([A-Za-z0-9_-]+)\.", blob):
                self.assertIn(ref, seen, "step %r reads steps.%s before it runs" % (st.get("name"), ref))
            if "id" in st:
                seen.add(st["id"])

    def test_run_py_outputs_are_the_ones_read(self):
        src = RUN_PY.read_text(encoding="utf-8")
        for name in ("video", "html", "poster", "qa", "job", "vertical", "files", "key", "home", "path"):
            self.assertIn('"%s"' % name, src, "run.py never writes the output %s" % name)
        blob = self.text
        for out in set(re.findall(r"steps\.(?:prepare|run|setup)\.outputs\.([A-Za-z0-9_-]+)", blob)):
            self.assertIn('"%s"' % out, src, "action.yml reads output %s that run.py does not write" % out)

    def test_untrusted_text_never_goes_into_a_shell_script(self):
        # the only ${{ }} allowed inside run: scripts none; inputs and the action path go through env:
        for st in steps_of(self.doc):
            if "run" in st:
                self.assertNotIn("${{", st["run"], "step %r expands an expression inside its script" % st.get("name"))

    def test_uses_pins_match_the_repo_workflows(self):
        e2e = E2E.read_text(encoding="utf-8")
        ci = CI.read_text(encoding="utf-8")
        pins = {}
        for m in re.finditer(r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([A-Za-z0-9_.-]+)", e2e + "\n" + ci):
            pins.setdefault(m.group(1), set()).add(m.group(2))
        checked = 0
        for st in steps_of(self.doc):
            if "uses" not in st:
                continue
            action, _, ver = st["uses"].partition("@")
            self.assertTrue(ver, "%s is not pinned" % action)
            base = "/".join(action.split("/")[:2])  # actions/cache/restore -> actions/cache
            self.assertIn(base, pins, "%s is not used in e2e.yml or ci.yml: pin it there first" % base)
            self.assertIn(ver, pins[base], "%s@%s: the repo workflows pin %s" % (action, ver, sorted(pins[base])))
            checked += 1
        self.assertGreaterEqual(checked, 6)
        # the three toolchain steps come first, as in e2e.yml
        names = [st["uses"].split("@")[0] for st in steps_of(self.doc) if "uses" in st]
        for a in ("actions/setup-python", "astral-sh/setup-uv", "actions/setup-node", "actions/cache/restore",
                  "actions/cache/save", "actions/upload-artifact"):
            self.assertIn(a, names)

    def test_node_and_python_versions_match_e2e(self):
        e2e = load_yaml(E2E)
        node_v = py_v = None
        for st in e2e["jobs"]["e2e"]["steps"]:
            if str(st.get("uses", "")).startswith("actions/setup-node"):
                node_v = str(st["with"]["node-version"])
            if str(st.get("uses", "")).startswith("actions/setup-python"):
                py_v = str(st["with"]["python-version"])
        mine = {st["uses"].split("@")[0]: st.get("with", {}) for st in steps_of(self.doc) if "uses" in st}
        self.assertEqual(str(mine["actions/setup-node"]["node-version"]), node_v)
        self.assertEqual(str(mine["actions/setup-python"]["python-version"]), py_v)

    def test_upload_steps(self):
        by_name = {st.get("uses", "").split("@")[0] + "|" + st.get("name", ""): st for st in steps_of(self.doc)}
        art = [st for st in steps_of(self.doc) if str(st.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(art), 1)
        self.assertIn("always()", art[0]["if"])
        self.assertIn("inputs.upload == 'artifact'", art[0]["if"])
        rel = [st for st in steps_of(self.doc) if "INPUT_GITHUB_TOKEN" in st.get("env", {})]
        self.assertEqual(len(rel), 1, "the token reaches exactly one step")
        self.assertIn("inputs.upload == 'release'", rel[0]["if"])
        self.assertIn("success()", rel[0]["if"])
        self.assertTrue(by_name)

    def test_cache_save_follows_setup_and_only_on_a_miss(self):
        steps = steps_of(self.doc)
        names = [st.get("name", "") for st in steps]
        i_setup = names.index("Set up showtime")
        i_save = next(i for i, st in enumerate(steps) if str(st.get("uses", "")).startswith("actions/cache/save"))
        i_run = names.index("Make the video")
        self.assertTrue(i_setup < i_save < i_run)
        self.assertIn("cache-hit != 'true'", steps[i_save]["if"])
        self.assertIn("inputs.cache == 'true'", steps[i_save]["if"])

    def test_no_banned_names_or_emoji(self):
        for p in (ACTION_YML, RUN_PY, ACTION_DIR / "local-run.sh", EXAMPLE, DOC):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            for b in BANNED:
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_])" % re.escape(b), text, re.I),
                                  "%s mentions %s" % (p.name, b[:2] + "..."))
            for ch in text:
                self.assertFalse(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF,
                                 "%s has an emoji or pictograph: %r" % (p.name, ch))


# ---------------------------------------------------------------------------
# the example workflow and the docs
# ---------------------------------------------------------------------------

@unittest.skipIf(yaml is None, SKIP_YAML)
class TestExample(unittest.TestCase):
    def test_example_parses_and_points_at_the_action(self):
        self.assertTrue(EXAMPLE.is_file(), "docs/examples/showtime-release-video.yml is missing")
        doc = load_yaml(EXAMPLE)
        on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as True
        self.assertIn("release", on)
        self.assertIn("workflow_dispatch", on)
        self.assertEqual(on["release"]["types"], ["published"])
        uses = []
        for job in doc["jobs"].values():
            for st in job["steps"]:
                if "uses" in st:
                    uses.append(st["uses"])
        mine = [u for u in uses if "/.github/actions/showtime-video@" in u]
        self.assertEqual(len(mine), 1, uses)
        path = mine[0].split("@")[0].split("/", 2)[2]  # faviovazquez/showtime/<path>
        self.assertEqual(path, ".github/actions/showtime-video")
        self.assertTrue((REPO / path / "action.yml").is_file())
        # the with: keys it passes are inputs the action declares
        action_inputs = set(load_yaml(ACTION_YML)["inputs"])
        for job in doc["jobs"].values():
            for st in job["steps"]:
                if st.get("uses", "").find("/showtime-video@") >= 0:
                    self.assertLessEqual(set(st.get("with", {})), action_inputs)
        # permissions: contents: write only where a release upload is asked for
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("contents: write", text)
        self.assertNotIn("secrets.", text.split("\n# ----", 1)[0], "the default example uses no secret")

    def test_docs_link_and_pr_variant(self):
        self.assertTrue(DOC.is_file(), "docs/github-action.md is missing")
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("showtime-release-video.yml", text)
        for name in load_yaml(ACTION_YML)["inputs"]:
            self.assertIn("`%s`" % name, text, "docs/github-action.md does not describe the input %s" % name)
        for name in load_yaml(ACTION_YML)["outputs"]:
            self.assertIn("`%s`" % name, text, "docs/github-action.md does not describe the output %s" % name)
        self.assertIn("pull_request", EXAMPLE.read_text(encoding="utf-8"))
        notes = (REPO / "skills" / "showtime" / "references" / "harness-notes.md").read_text(encoding="utf-8")
        self.assertIn("github-action.md", notes, "harness-notes.md section 5 links docs/github-action.md")


# ---------------------------------------------------------------------------
# run.py: dry runs
# ---------------------------------------------------------------------------

class TestDryRun(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_release_event(self):
        env = env_for(self.tmp, "release", release_event(), install="pip install -U widget", vertical="true")
        cmds, out = dry_run_commands(env)
        work = str(self.tmp / "runner" / "showtime-work")
        self.assertEqual([c.split(" ", 1)[0] + " " + c.split(" ")[1] for c in cmds[:1]], ["showtime job"])
        self.assertIn("job init release-widget-v2-3-0 ", cmds[0])
        self.assertIn("--base", cmds[0])
        self.assertIn(work.replace("\\", "/"), cmds[0].replace("\\", "/"))
        self.assertTrue(cmds[0].endswith("--json"))
        kinds = [" ".join(c.split(" ")[:2]) for c in cmds]
        self.assertEqual(kinds, ["showtime job", "showtime release-video", "showtime check", "showtime render",
                                 "showtime qa", "showtime export", "showtime deliver", "showtime render", "showtime qa"])
        rv = cmds[1]
        for frag in ("--name widget", "--version v2.3.0", "--date 2026-09-29", "'pip install -U widget'",
                     "--url https://github.com/acme/widget/releases/tag/v2.3.0", "-o '<job>/project'"):
            self.assertIn(frag, rv)
        self.assertNotIn("--kind", rv)
        self.assertIn("render '<job>/project' --job '<job>'", cmds[3])
        self.assertIn("export html '<job>/project' -o '<job>/exports/release-widget-v2-3-0.html'", cmds[5])
        self.assertIn("--size 9:16", cmds[7])
        self.assertIn("--platform reels", cmds[8])
        # the resolved notes, title and version are shown, and nothing was written
        self.assertIn("source=release event", out)
        self.assertIn("version='v2.3.0'", out)
        self.assertIn("Faster sync", out)
        self.assertFalse((self.tmp / "runner").exists(), "a dry run must not create the work folder")
        self.assertFalse((self.tmp / "out.txt").exists(), "a dry run must not write GITHUB_OUTPUT")

    def test_pull_request_event(self):
        env = env_for(self.tmp, "pull_request", pr_event())
        cmds, out = dry_run_commands(env)
        self.assertIn("job init pr-widget-42 ", cmds[0].replace("#", ""))
        rv = cmds[1]
        self.assertIn("--kind pr", rv)
        self.assertIn("--version '#42'", rv)
        self.assertIn("--url https://github.com/acme/widget/pull/42", rv)
        self.assertNotIn("--date", rv)
        self.assertEqual(len(cmds), 7, cmds)  # no vertical
        self.assertTrue(cmds[-1].endswith("--targets github"), cmds[-1])
        self.assertIn("source=pull request event", out)
        self.assertIn("# Add a dark theme", out)

    def test_notes_input_workflow_dispatch(self):
        env = env_for(self.tmp, "workflow_dispatch", {}, notes="- One\n- Two\n", version="1.0.0", name="Acme",
                      max_items="5")
        cmds, _ = dry_run_commands(env)
        self.assertIn("--name Acme", cmds[1])
        self.assertIn("--version 1.0.0", cmds[1])
        self.assertIn("--max-items 5", cmds[1])
        self.assertIn("--url https://github.com/acme/widget", cmds[1])  # the repository, nothing invented

    def test_project_mode(self):
        env = env_for(self.tmp, mode="project", project="videos/launch")
        proj = self.tmp / "ws" / "videos" / "launch"
        cmds, _ = dry_run_commands(env)
        kinds = [" ".join(c.split(" ")[:2]) for c in cmds]
        self.assertEqual(kinds, ["showtime job", "showtime check", "showtime render", "showtime qa", "showtime export",
                                 "showtime deliver"])
        self.assertIn("--project", cmds[0])
        self.assertIn(str(proj), cmds[0])
        self.assertIn(str(proj), cmds[1])
        self.assertIn("job init project-launch ", cmds[0])

    def test_agent_mode(self):
        env = env_for(self.tmp, "release", release_event(), mode="agent",
                      agent_command='my-agent --print "$SHOWTIME_PROMPT"', prompt="Make a 20 s launch video")
        cmds, out = dry_run_commands(env)
        self.assertEqual([c.split(" ")[1] for c in cmds if c.startswith("showtime")], ["job", "qa", "export", "deliver"])
        self.assertTrue(any(c.startswith('my-agent --print "$SHOWTIME_PROMPT"') for c in cmds), cmds)
        self.assertIn("SHOWTIME_PROMPT", out)
        self.assertIn("SHOWTIME_NOTES", out)
        agent_line = next(c for c in cmds if c.endswith("# agent command"))
        self.assertNotIn("Make a 20 s launch video", agent_line, "the prompt goes in the environment, not the command")

    def test_missing_inputs_fail_clearly(self):
        cases = [
            (env_for(self.tmp, "push", {}), "no notes to make a video from"),
            (env_for(self.tmp, mode="project"), "needs the input 'project'"),
            (env_for(self.tmp, mode="agent", prompt="x"), "agent-command"),
            (env_for(self.tmp, mode="agent", agent_command="x"), "'prompt'"),
            (env_for(self.tmp, mode="bogus"), "mode must be one of"),
            (env_for(self.tmp, "release", release_event(body="  ")), "no description"),
            (env_for(self.tmp, "pull_request", pr_event(body="")), "no description"),
        ]
        for env, needle in cases:
            cp = subprocess.run([sys.executable, str(RUN_PY), "run", "--dry-run"], env=env, universal_newlines=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            self.assertEqual(cp.returncode, 1, (needle, cp.stdout, cp.stderr))
            self.assertIn(needle, cp.stderr)

    def test_setup_and_prepare_dry_run(self):
        env = env_for(self.tmp, tier="minimal", browser_deps="true")
        env["SHOWTIME_HOME"] = str(self.tmp / "home")
        cmds, out = dry_run_commands(env, "setup")
        self.assertEqual(cmds[0], "showtime setup --tier minimal")
        self.assertEqual(cmds[-1], "showtime doctor")
        if sys.platform.startswith("linux"):
            self.assertTrue(any(c.startswith("sudo -n node ") and c.endswith("install-deps chromium") for c in cmds), cmds)
        env["CACHE_HIT"] = "true"
        cmds, out = dry_run_commands(env, "setup")
        self.assertEqual(cmds[0], "showtime doctor --quick --json")
        self.assertIn("setup skipped", out)
        self.assertNotIn("showtime setup", "\n".join(cmds))

    def test_upload_release_dry_run(self):
        env = env_for(self.tmp, "release", release_event(), upload_files="/tmp/a.mp4\n/tmp/a.html\n",
                      github_token="ghs_fake")
        cmds, out = dry_run_commands(env, "upload")
        self.assertEqual(cmds, ["gh release upload v2.3.0 /tmp/a.mp4 /tmp/a.html --clobber"])
        self.assertNotIn("ghs_fake", out, "the token is never printed")
        env2 = env_for(self.tmp, upload_files="/tmp/a.mp4\n", github_token="x", release_tag="v9")
        self.assertEqual(dry_run_commands(env2, "upload")[0], ["gh release upload v9 /tmp/a.mp4 --clobber"])


# ---------------------------------------------------------------------------
# run.py: functions
# ---------------------------------------------------------------------------

class TestFunctions(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def test_slugify(self):
        self.assertEqual(run.slugify("release", "Acme Widgets!", "v2.3.0"), "release-acme-widgets-v2-3-0")
        self.assertEqual(run.slugify("pr", "w", "#42"), "pr-w-42")
        self.assertEqual(run.slugify("", ""), "release")
        self.assertLessEqual(len(run.slugify("x" * 200)), 40)
        self.assertFalse(run.slugify("a" * 39, "b").endswith("-"))

    def test_get_input(self):
        env = {"INPUT_NOTES_FILE": " docs/n.md ", "INPUT_BLANK": "  ", "INPUT_VERSION": "1"}
        self.assertEqual(run.get_input(env, "notes-file"), "docs/n.md")
        self.assertEqual(run.get_input(env, "blank", "d"), "d")
        self.assertEqual(run.get_input(env, "missing"), "")
        self.assertTrue(run.truthy("True") and run.truthy("1") and not run.truthy("false") and not run.truthy(""))

    def test_write_output(self):
        out = self.tmp / "o.txt"
        env = {"GITHUB_OUTPUT": str(out)}
        run.write_output(env, "qa", "PASS")
        run.write_output(env, "files", "a.mp4\nb.html")
        run.write_output(env, "empty", "")
        text = out.read_text(encoding="utf-8")
        self.assertIn("qa=PASS\n", text)
        m = re.search(r"files<<(ST_EOF_\d+)\na\.mp4\nb\.html\n\1\n", text)
        self.assertTrue(m, text)
        self.assertIn("empty=\n", text)
        run.write_output({}, "x", "y")  # no GITHUB_OUTPUT: nothing happens, no error

    def test_notes_order(self):
        ws = self.tmp / "ws"
        ws.mkdir()
        (ws / "n.md").write_text("- from file\n", encoding="utf-8")
        (ws / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        ev = release_event()
        # 1 the notes input beats everything
        env = env_for(self.tmp, "release", ev, notes="- typed\n", notes_file="n.md", changelog="CHANGELOG.md", version="2.0.0")
        n = run.resolve_notes(env)
        self.assertEqual((n.source, n.markdown), ("input notes", "- typed"))
        # 2 then the file
        env = env_for(self.tmp, "release", ev, notes_file="n.md", changelog="CHANGELOG.md", version="2.0.0")
        self.assertEqual(run.resolve_notes(env).markdown.strip(), "- from file")
        # 3 then the changelog (with the version input)
        env = env_for(self.tmp, "release", ev, changelog="CHANGELOG.md", version="2.0.0")
        n = run.resolve_notes(env)
        self.assertEqual((n.changelog_version, n.version), ("2.0.0", "2.0.0"))
        self.assertIn("Older change", n.markdown)  # the whole file goes to release-video, which picks the section
        # 4 then the event
        n = run.resolve_notes(env_for(self.tmp, "release", ev))
        self.assertEqual((n.source, n.version, n.date, n.kind), ("release event", "v2.3.0", "2026-09-29", "release"))
        self.assertEqual(n.name, "widget")
        self.assertEqual(n.url, "https://github.com/acme/widget/releases/tag/v2.3.0")
        n = run.resolve_notes(env_for(self.tmp, "pull_request", pr_event()))
        self.assertEqual((n.source, n.version, n.kind), ("pull request event", "#42", "pr"))
        self.assertTrue(n.markdown.startswith("# Add a dark theme"))
        # explicit inputs beat the event's values
        n = run.resolve_notes(env_for(self.tmp, "release", ev, version="9.9", name="Custom", url="https://x.dev"))
        self.assertEqual((n.version, n.name, n.url), ("9.9", "Custom", "https://x.dev"))

    def test_changelog_default_file_with_version_on_dispatch(self):
        ws = self.tmp / "ws"
        ws.mkdir()
        (ws / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        n = run.resolve_notes(env_for(self.tmp, "workflow_dispatch", {}, version="2.0.0"))
        self.assertEqual(n.source, "changelog CHANGELOG.md")
        with self.assertRaises(run.ActionError):
            run.resolve_notes(env_for(self.tmp, "workflow_dispatch", {}, changelog="CHANGELOG.md"))  # no version

    def test_missing_file_and_oversize(self):
        with self.assertRaises(run.ActionError) as cm:
            run.resolve_notes(env_for(self.tmp, notes_file="nope.md"))
        self.assertIn("file not found", str(cm.exception))
        with self.assertRaises(run.ActionError):
            run.resolve_notes(env_for(self.tmp, notes="x" * (run.NOTES_MAX_BYTES + 1)))

    def test_event_reading_is_forgiving(self):
        self.assertEqual(run.read_event({}), {})
        bad = self.tmp / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        self.assertEqual(run.read_event({"GITHUB_EVENT_PATH": str(bad)}), {})
        bom = self.tmp / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf" + json.dumps(release_event()).encode())
        self.assertIn("release", run.read_event({"GITHUB_EVENT_PATH": str(bom)}))

    def test_cache_key(self):
        env = {"RUNNER_OS": "Linux", "RUNNER_ARCH": "X64"}
        k1, h1 = run.cache_key(env)
        k2, h2 = run.cache_key(env)
        self.assertEqual((k1, h1), (k2, h2))
        self.assertIn("Linux-X64", k1)
        self.assertRegex(h1, r"^[0-9a-f]{16}$")
        self.assertNotEqual(k1, run.cache_key(dict(env, INPUT_TIER="core"))[0])
        self.assertNotEqual(k1, run.cache_key(dict(env, RUNNER_OS="macOS", RUNNER_ARCH="ARM64"))[0])
        # the hash follows the setup files' contents
        fake = self.tmp / "co" / "skills" / "showtime"
        (fake / "lib" / "st").mkdir(parents=True)
        (fake / "lib" / "st" / "launcher.py").write_text("", encoding="utf-8")
        (fake / "setup").mkdir()
        (fake / "setup" / "manifest.json").write_text("{}", encoding="utf-8")
        e = dict(env, INPUT_SHOWTIME_PATH=str(self.tmp / "co"))
        a = run.cache_key(e)[1]
        (fake / "setup" / "manifest.json").write_text('{"v": 2}', encoding="utf-8")
        self.assertNotEqual(a, run.cache_key(e)[1])
        (fake / "setup" / "requirements.txt").write_bytes(b"a\r\nb\r\n")
        b = run.cache_key(e)[1]
        (fake / "setup" / "requirements.txt").write_bytes(b"a\nb\n")
        self.assertEqual(b, run.cache_key(e)[1], "line endings do not change the key")

    def test_prepare_writes_outputs(self):
        env = env_for(self.tmp)
        env["SHOWTIME_HOME"] = str(self.tmp / "home")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_prepare(env, False), 0)
        text = (self.tmp / "out.txt").read_text(encoding="utf-8")
        self.assertRegex(text, r"key=showtime-action-Linux-X64-py[\d.]+-minimal-[0-9a-f]{16}\n")
        self.assertIn("home=%s\n" % (self.tmp / "home"), text)  # the home itself keeps the native spelling
        m = re.search(r"path<<(\S+)\n(.*?)\n\1\n", text, re.S)
        self.assertTrue(m)
        lines = m.group(2).splitlines()
        self.assertEqual(lines[0], (self.tmp / "home").as_posix())
        self.assertTrue(all(x.startswith("!") for x in lines[1:]) and len(lines) == 1 + len(run.CACHE_EXCLUDE))

    def test_skill_dir_resolution(self):
        self.assertEqual(run.skill_dir({}), (REPO / "skills" / "showtime").resolve())
        with self.assertRaises(run.ActionError):
            run.skill_dir({"INPUT_SHOWTIME_PATH": str(self.tmp)})
        fake = self.tmp / "sk"
        (fake / "lib" / "st").mkdir(parents=True)
        (fake / "lib" / "st" / "launcher.py").write_text("", encoding="utf-8")
        self.assertEqual(run.skill_dir({"INPUT_SHOWTIME_PATH": str(fake)}), fake.resolve())  # the skill folder itself

    def test_launcher_paths(self):
        env = {}
        if os.name == "nt":
            self.assertTrue(run.launcher_cmd(env)[-1].endswith("launcher.py"))
            self.assertTrue(run.shim_path(env).endswith("showtime.cmd"))
        else:
            self.assertEqual(run.launcher_cmd(env), [str(REPO / "skills" / "showtime" / "bin" / "showtime")])
        self.assertTrue(Path(run.shim_path(env)).is_file())

    def test_qa_verdict_and_files(self):
        job = self.tmp / "job"
        (job / "work" / "qa" / "final").mkdir(parents=True)
        (job / "work" / "qa" / "final" / "qa.json").write_text(json.dumps({
            "verdict": "WARN", "audio": {"loudness": {"integrated_lufs": -14.2, "true_peak_dbtp": -1.4}}}),
            encoding="utf-8")
        (job / "final.mp4").write_bytes(b"x")
        (job / "final.poster.jpg").write_bytes(b"x")
        self.assertEqual(run.qa_verdict(job, job / "final.mp4"), "WARN")
        self.assertEqual(run.qa_line(job, job / "final.mp4"), "-14.2 LUFS, -1.4 dBTP")
        (job / "final-2.mp4").write_bytes(b"y")
        self.assertEqual(run.latest_final(job).name, "final-2.mp4")
        (job / "final.captioned.mp4").write_bytes(b"z")
        self.assertNotIn("captioned", run.latest_final(job).name)


# ---------------------------------------------------------------------------
# run.py against a fake showtime checkout
# ---------------------------------------------------------------------------

FAKE_SHIM = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
a = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(a) + "\n")
def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default
cmd = a[0]
if cmd == "job" and a[1] == "init":
    base = Path(opt("--base")) / "showtime-out" / ("%s-%d" % (a[2], time.time() * 1000))
    base.mkdir(parents=True)
    (base / "job.json").write_text(json.dumps({"slug": a[2], "project": opt("--project")}))
    print(json.dumps({"job": str(base)}))
elif cmd == "release-video":
    out = Path(opt("-o")); out.mkdir(parents=True)
    (out / "showtime.json").write_text("{}"); (out / "index.html").write_text("<html></html>")
    print("wrote", out)
elif cmd == "check":
    sys.exit(int(os.environ.get("FAKE_CHECK", "0")))
elif cmd == "render":
    job = Path(opt("--job"))
    if "--size" in a:
        (job / "1080x1920.mp4").write_bytes(b"v")
    else:
        (job / "final.mp4").write_bytes(b"m" * 100); (job / "final.poster.jpg").write_bytes(b"p")
        (job / "share.txt").write_text("share")
elif cmd == "qa":
    target = Path(a[1])
    video = target if target.suffix == ".mp4" else max(target.glob("final*.mp4"))
    verdict = os.environ.get("FAKE_QA", "PASS") if video.name == "final.mp4" else "PASS"
    job = video.parent
    q = job / "work" / "qa" / video.stem; q.mkdir(parents=True, exist_ok=True)
    (q / "qa.json").write_text(json.dumps({"verdict": verdict, "loudness": {"integrated_lufs": -14.1, "true_peak_dbtp": -1.6}}))
    print("verdict:", verdict)
    sys.exit(1 if verdict == "FAIL" else 0)
elif cmd == "export":
    out = Path(opt("-o")); out.parent.mkdir(parents=True, exist_ok=True); out.write_text("<html>video</html>")
elif cmd == "deliver" and a[1] == "exports":
    job = Path(a[2]); ex = job / "exports"; ex.mkdir(parents=True, exist_ok=True)
    (ex / (max(job.glob("final*.mp4")).stem + ".github.mp4")).write_bytes(b"small")
else:
    sys.exit("fake showtime: unknown command %r" % cmd)
'''

FAKE_AGENT = r'''
import os, json, sys
from pathlib import Path
job = Path(os.environ["SHOWTIME_JOB"])
assert os.environ["SHOWTIME_PROMPT"] == "make a film", os.environ["SHOWTIME_PROMPT"]
assert Path(os.environ["SHOWTIME_BIN"]).name.startswith("showtime")
(job / "project").mkdir(exist_ok=True); (job / "project" / "showtime.json").write_text("{}")
if os.environ.get("AGENT_RENDERS", "1") == "1":
    (job / "final.mp4").write_bytes(b"agent-video")
print("agent done", file=sys.stderr)
'''


@unittest.skipIf(os.name == "nt", "the fake showtime shim is a POSIX script; Windows goes through launcher.py")
class TestEndToEndWithFakeShowtime(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        co = self.tmp / "co" / "skills" / "showtime"
        (co / "lib" / "st").mkdir(parents=True)
        (co / "lib" / "st" / "launcher.py").write_text("", encoding="utf-8")
        (co / "bin").mkdir()
        shim = co / "bin" / "showtime"
        shim.write_text(FAKE_SHIM.replace("#!/usr/bin/env python3", "#!%s" % sys.executable), encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        (co / "setup").mkdir()
        self.log = self.tmp / "calls.jsonl"

    def tearDown(self):
        self._t.cleanup()

    def env(self, event_name="release", event=None, **inputs):
        e = env_for(self.tmp, event_name, release_event() if event is None else event,
                    showtime_path=str(self.tmp / "co"), **inputs)
        e["FAKE_LOG"] = str(self.log)
        e["GITHUB_STEP_SUMMARY"] = str(self.tmp / "summary.md")
        e["GITHUB_ACTIONS"] = "true"
        return e

    def call(self, env, sub="run"):
        cp = subprocess.run([sys.executable, str(RUN_PY), sub], env=env, universal_newlines=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        return cp

    def outputs(self):
        out = {}
        text = (self.tmp / "out.txt").read_text(encoding="utf-8")
        for m in re.finditer(r"^(\w[\w-]*)<<(\S+)\n(.*?)\n\2\n", text, re.S | re.M):
            out[m.group(1)] = m.group(3)
        rest = re.sub(r"^(\w[\w-]*)<<(\S+)\n(.*?)\n\2\n", "", text, flags=re.S | re.M)
        for line in rest.splitlines():
            k, _, v = line.partition("=")
            out[k] = v
        return out

    def calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()]

    def test_release_run(self):
        cp = self.call(self.env(vertical="true", install="pip install -U widget"))
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        o = self.outputs()
        self.assertEqual(o["qa"], "PASS")
        self.assertTrue(o["video"].endswith("final.mp4") and Path(o["video"]).is_file())
        self.assertTrue(o["html"].endswith("release-widget-v2-3-0.html") and Path(o["html"]).is_file())
        self.assertTrue(o["poster"].endswith("final.poster.jpg"))
        self.assertTrue(o["vertical"].endswith("1080x1920.mp4"))
        self.assertTrue(Path(o["job"]).is_dir())
        files = [Path(p) for p in o["files"].splitlines()]
        names = sorted(p.name for p in files)
        self.assertEqual(names, sorted("release-widget-v2-3-0" + s for s in
                                       (".mp4", "-9x16.mp4", ".html", "-poster.jpg", "-github.mp4", "-qa.json", "-share.txt")))
        self.assertTrue(all(p.is_file() for p in files))
        self.assertTrue(all(str(p).startswith(str(self.tmp / "runner" / "showtime-work" / "upload")) for p in files))
        self.assertEqual([c[0] for c in self.calls()],
                         ["job", "release-video", "check", "render", "qa", "export", "deliver", "render", "qa"])
        summary = (self.tmp / "summary.md").read_text(encoding="utf-8")
        self.assertIn("qa: **PASS** (-14.1 LUFS, -1.6 dBTP)", summary)
        # the notes file the CLI read holds exactly the release body
        rv = self.calls()[1]
        self.assertEqual(Path(rv[1]).read_text(encoding="utf-8"), RELEASE_BODY)

    def test_qa_fail_exits_1_but_still_reports_outputs(self):
        env = self.env()
        env["FAKE_QA"] = "FAIL"
        cp = self.call(env)
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("qa found a FAIL", cp.stderr)
        self.assertIn("::error title=showtime-video::", cp.stdout)
        o = self.outputs()
        self.assertEqual(o["qa"], "FAIL")
        self.assertTrue(o["video"].endswith("final.mp4"), "the failing video is still reported so it can be uploaded")
        self.assertNotIn("export", [c[0] for c in self.calls()], "no export after a qa FAIL")
        self.assertIn("**Failed:**", (self.tmp / "summary.md").read_text(encoding="utf-8"))

    def test_check_failure_stops_before_render(self):
        env = self.env()
        env["FAKE_CHECK"] = "1"
        cp = self.call(env)
        self.assertEqual(cp.returncode, 1)
        self.assertNotIn("render", [c[0] for c in self.calls()])
        self.assertEqual(self.outputs()["video"], "")

    def test_warn_passes(self):
        env = self.env()
        env["FAKE_QA"] = "WARN"
        cp = self.call(env)
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(self.outputs()["qa"], "WARN")

    def test_project_mode(self):
        proj = self.tmp / "ws" / "videos" / "launch"
        proj.mkdir(parents=True)
        (proj / "showtime.json").write_text("{}", encoding="utf-8")
        cp = self.call(self.env("push", {}, mode="project", project="videos/launch"))
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertEqual([c[0] for c in self.calls()], ["job", "check", "render", "qa", "export", "deliver"])
        self.assertTrue(self.outputs()["html"].endswith("project-launch.html"))
        # a folder without showtime.json is refused with a clear message
        cp = self.call(self.env("push", {}, mode="project", project="videos/nothing"))
        self.assertEqual(cp.returncode, 1)
        self.assertIn("not a showtime project", cp.stderr)

    def test_agent_mode_checks_independently(self):
        script = self.tmp / "agent.py"
        script.write_text(FAKE_AGENT, encoding="utf-8")
        cmd = '"%s" "%s"' % (sys.executable, script)
        cp = self.call(self.env(mode="agent", agent_command=cmd, prompt="make a film"))
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        o = self.outputs()
        self.assertEqual(o["qa"], "PASS")
        self.assertTrue(o["video"].endswith("final.mp4"))
        self.assertTrue(o["html"].endswith(".html"))
        self.assertEqual([c[0] for c in self.calls()], ["job", "qa", "export", "deliver"])  # the Action ran its own qa + export
        # no video from the agent: fail, and say so
        env = self.env(mode="agent", agent_command=cmd, prompt="make a film")
        env["AGENT_RENDERS"] = "0"
        self.log.unlink()
        cp = self.call(env)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no final video exists", cp.stderr)
        # an agent command that itself fails: fail
        env = self.env(mode="agent", agent_command="exit 3", prompt="make a film")
        cp = self.call(env)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("failed", cp.stderr)

    def test_setup_skips_when_the_cache_is_good(self):
        env = self.env()
        env["SHOWTIME_HOME"] = str(self.tmp / "home")
        env["CACHE_HIT"] = "true"
        (self.tmp / "co" / "skills" / "showtime" / "bin" / "showtime").write_text(
            "#!%s\nimport json,sys,os\nopen(os.environ['FAKE_LOG'],'a').write(json.dumps(sys.argv[1:])+'\\n')\n"
            "print(json.dumps({'ok': True, 'checks': []}))\n" % sys.executable, encoding="utf-8")
        cp = self.call(env, "setup")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        subs = [c[0] for c in self.calls()]
        self.assertNotIn("setup", subs)
        self.assertIn("doctor", subs)
        self.assertEqual(self.outputs()["setup-skipped"], "true")
        env["CACHE_HIT"] = "false"
        self.log.unlink()
        self.assertEqual(self.call(env, "setup").returncode, 0)
        self.assertEqual(self.calls()[0][:3], ["setup", "--tier", "minimal"])


class TestRealLauncherShim(unittest.TestCase):
    def test_the_real_shim_is_what_run_py_would_call(self):
        # no run: only that the launcher run.py resolves from its own location is the repo's real entry point
        cmd = run.launcher_cmd({})
        self.assertTrue(Path(cmd[-1]).is_file(), cmd)
        self.assertTrue((REPO / "skills" / "showtime" / "bin" / "showtime").is_file())


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
