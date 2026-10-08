#!/usr/bin/env python3
"""The repository's GitHub files (stdlib + PyYAML, about a second, no network).

Covers:
  - .github/ISSUE_TEMPLATE/: the bug, feature, example-request and docs forms parse and follow GitHub's issue
    form schema (unique ids, known field types, dropdown options, only labels of the repository's label set);
    config.yml turns blank issues off and links Q&A, Show and tell, the docs site and private security reporting
  - .github/DISCUSSION_TEMPLATE/show-and-tell.yml: the video, the request, the agent, version, OS, render time
    and the "may feature it" checkbox
  - .github/release.yml: skip-notes is honoured, every category label is a known one
  - CODE_OF_CONDUCT.md: Contributor Covenant 2.1 with a private contact and no e-mail address
  - ci.yml's nightly-report job: after the nightly matrix, always(), on main only, issues: write with only the
    workflow token, no expression inside its script
  - scripts/nightly_report.py: the log parser on a real run's lines, the comment it builds, the open / comment /
    close decision and the gh calls it makes (a fake gh: nothing is posted)

usage: python tests/test_github.py [--fast] [-v]
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent.parent.parent
GH_DIR = REPO / ".github"
FORMS = GH_DIR / "ISSUE_TEMPLATE"
CI = GH_DIR / "workflows" / "ci.yml"
SCRIPT = REPO / "scripts" / "nightly_report.py"

try:
    import yaml  # type: ignore
except ImportError:  # the showtime venv has PyYAML; a bare system Python may not
    yaml = None
SKIP_YAML = "PyYAML is not installed in this Python (it is in the showtime venv); the YAML checks are skipped"
SKIP_REPO = "the repository's .github folder is not here (the skill was copied without its repository)"

sys.dont_write_bytecode = True   # importing the script must not leave a __pycache__ in the repository
nr = None
if SCRIPT.is_file():
    _spec = importlib.util.spec_from_file_location("nightly_report", str(SCRIPT))
    nr = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["nightly_report"] = nr
    _spec.loader.exec_module(nr)  # type: ignore[union-attr]

# The repository's label set (created on GitHub; the forms may only name these)
LABELS = {
    "type: bug", "type: feature", "type: docs", "type: example", "type: perf", "type: chore",
    "area: render", "area: voice", "area: audio", "area: edit", "area: export", "area: qa", "area: install",
    "area: site", "platform: macos", "platform: windows", "platform: linux", "status: triage",
    "status: needs-owner", "status: needs-info", "status: ready", "status: blocked", "ci: nightly",
    "out-of-scope", "breaking", "skip-notes", "good first issue", "help wanted", "accessibility", "duplicate",
}
FIELD_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
OS_OPTIONS = {"macOS, Apple Silicon", "macOS, Intel", "Windows 10/11, x64", "Windows on Arm", "Linux"}


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_body(tc: unittest.TestCase, body, where: str) -> dict:
    """GitHub's form schema rules that a typo breaks silently (the form then falls back to a blank issue)."""
    tc.assertIsInstance(body, list, where)
    ids, fields = set(), {}
    for el in body:
        tc.assertIn(el.get("type"), FIELD_TYPES, "%s: unknown field type %r" % (where, el.get("type")))
        attrs = el.get("attributes") or {}
        if el["type"] == "markdown":
            tc.assertTrue(attrs.get("value"), "%s: a markdown field needs a value" % where)
            continue
        tc.assertTrue(attrs.get("label"), "%s: field without a label" % where)
        fid = el.get("id")
        tc.assertTrue(fid and ID_RE.match(fid), "%s: field id %r" % (where, fid))
        tc.assertNotIn(fid, ids, "%s: id %s used twice" % (where, fid))
        ids.add(fid)
        if el["type"] == "dropdown":
            opts = attrs.get("options") or []
            tc.assertTrue(opts, "%s: dropdown %s has no options" % (where, fid))
            tc.assertEqual(len(opts), len(set(map(str, opts))), "%s: dropdown %s repeats an option" % (where, fid))
            tc.assertTrue(all(isinstance(o, str) for o in opts), "%s: dropdown %s: options must be strings "
                                                                 "(quote 16:9)" % (where, fid))
        if el["type"] == "checkboxes":
            opts = attrs.get("options") or []
            tc.assertTrue(opts and all(o.get("label") for o in opts), "%s: checkboxes %s" % (where, fid))
        req = (el.get("validations") or {}).get("required")
        tc.assertIn(req, (None, True, False), "%s: %s required must be a bool" % (where, fid))
        fields[fid] = el
    tc.assertTrue(fields, "%s: a form needs at least one field that is not markdown" % where)
    return fields


@unittest.skipIf(yaml is None, SKIP_YAML)
@unittest.skipUnless(GH_DIR.is_dir(), SKIP_REPO)
class IssueForms(unittest.TestCase):
    def test_four_forms_parse_and_follow_the_schema(self):
        names = sorted(p.name for p in FORMS.glob("*.yml") if p.name != "config.yml")
        self.assertEqual(names, ["bug.yml", "docs.yml", "example-request.yml", "feature.yml"])
        for name in names:
            d = load(FORMS / name)
            for key in ("name", "description", "body"):
                self.assertTrue(d.get(key), "%s: no %s" % (name, key))
            self.assertLessEqual(len(d["description"]), 200, name)
            for lab in d.get("labels") or []:
                self.assertIn(lab, LABELS, "%s names label %r, which the repository does not have" % (name, lab))
            self.assertIn("status: triage", d["labels"], name)
            check_body(self, d["body"], name)

    def test_bug_form_asks_for_what_triage_needs(self):
        f = check_body(self, load(FORMS / "bug.yml")["body"], "bug.yml")
        for fid in ("what", "steps", "doctor", "version", "os"):
            self.assertTrue(f[fid].get("validations", {}).get("required"), "bug.yml: %s should be required" % fid)
        self.assertEqual(set(f["os"]["attributes"]["options"]), OS_OPTIONS)
        self.assertEqual(f["doctor"]["attributes"].get("render"), "text")
        text = (FORMS / "bug.yml").read_text(encoding="utf-8")
        self.assertIn("showtime report", text)   # the redacted bug-report.md

    def test_config_turns_blank_issues_off_and_links_the_right_places(self):
        d = load(FORMS / "config.yml")
        self.assertIs(d["blank_issues_enabled"], False)
        urls = [c["url"] for c in d["contact_links"]]
        for c in d["contact_links"]:
            self.assertTrue(c.get("name") and c.get("about"), c)
            self.assertTrue(c["url"].startswith("https://"), c)
        for want in ("/discussions/categories/q-a", "/discussions/categories/show-and-tell",
                     "/security/advisories/new", "faviovazquez.github.io/showtime"):
            self.assertTrue(any(want in u for u in urls), "config.yml links no %s" % want)

    def test_show_and_tell_form(self):
        p = GH_DIR / "DISCUSSION_TEMPLATE" / "show-and-tell.yml"
        d = load(p)
        f = check_body(self, d["body"], p.name)
        self.assertNotIn("labels", d, "discussion labels must exist first; the category is enough")
        for fid in ("video", "request", "agent", "version", "os", "render-time", "consent"):
            self.assertIn(fid, f, "show-and-tell.yml: no %s field" % fid)
        self.assertTrue(f["video"]["validations"]["required"])
        consent = f["consent"]["attributes"]["options"][0]
        self.assertIn("may feature", consent["label"])
        self.assertIn("credited to me", consent["label"])
        self.assertFalse(consent.get("required"), "featuring is opt-in")

    def test_release_notes_config(self):
        d = load(GH_DIR / "release.yml")["changelog"]
        self.assertIn("skip-notes", d["exclude"]["labels"])
        for cat in d["categories"]:
            for lab in cat["labels"]:
                self.assertTrue(lab == "*" or lab in LABELS, "release.yml: unknown label %r" % lab)
        self.assertEqual(d["categories"][-1]["labels"], ["*"], "the catch-all category goes last")

    def test_forms_say_nothing_private(self):
        for p in sorted(GH_DIR.rglob("*.yml")):
            if "workflows" in p.parts or "actions" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)/Users/|/home/|[A-Z]:\\|\blane\b|@[\w.-]+\.(?:com|org|net)\b", p.name)


@unittest.skipUnless((REPO / "CODE_OF_CONDUCT.md").is_file(), SKIP_REPO)
class CodeOfConduct(unittest.TestCase):
    def test_contributor_covenant_with_a_private_contact(self):
        text = (REPO / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        self.assertIn("Contributor Covenant", text)
        self.assertIn("version 2.1", text)
        self.assertIn("/security/advisories/new", text)
        self.assertIn("https://github.com/FavioVazquez", text)
        self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "no e-mail address in the code of conduct")
        self.assertNotIn("[INSERT", text)
        self.assertIn("CODE_OF_CONDUCT.md", (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8"))


@unittest.skipIf(yaml is None, SKIP_YAML)
@unittest.skipUnless(CI.is_file(), SKIP_REPO)
class NightlyReportJob(unittest.TestCase):
    def setUp(self):
        self.doc = load(CI)
        self.job = self.doc["jobs"]["nightly-report"]

    def test_runs_after_the_nightly_matrix_on_main(self):
        self.assertEqual(self.job["needs"], ["nightly"])
        cond = self.job["if"]
        self.assertTrue(cond.startswith("always() && "), cond)
        self.assertIn("github.ref == 'refs/heads/main'", cond)
        self.assertIn("github.event_name == 'schedule'", cond)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.full", cond)
        self.assertIn("!github.event.repository.private", cond)
        on = self.doc.get("on", self.doc.get(True))   # PyYAML reads the bare key `on` as True
        self.assertIn("schedule", on)
        self.assertIn("workflow_dispatch", on)

    def test_least_privilege_and_only_the_workflow_token(self):
        self.assertEqual(self.job["permissions"], {"contents": "read", "actions": "read", "issues": "write"})
        self.assertEqual(self.doc["permissions"], {"contents": "read"}, "the workflow default stays read-only")
        blob = yaml.safe_dump(self.job)
        self.assertNotIn("secrets.", blob)
        steps = self.job["steps"]
        envs = [s.get("env", {}) for s in steps]
        self.assertIn("${{ github.token }}", [e.get("GH_TOKEN") for e in envs])
        for s in steps:
            if "run" in s:
                self.assertNotIn("${{", s["run"], "expressions go through env:, never into the script")
                self.assertIn("scripts/nightly_report.py", s["run"])

    def test_pins_match_the_rest_of_the_workflow(self):
        text = CI.read_text(encoding="utf-8")
        pins = set(re.findall(r"uses:\s*actions/checkout@(\S+)", text))
        self.assertEqual(len(pins), 1, "every checkout in ci.yml uses the same pin: %s" % pins)
        self.assertTrue(SCRIPT.is_file())


# A real failed nightly's lines (trimmed): run_all.py -j 2 on two images
LOG_WIN = """\
2026-10-07T11:59:05.0294618Z [56/64] FAIL test_signatures.py             900.7s rc=124 timed out after 900s
2026-10-07T12:01:17.8061457Z [59/64] PASS test_studio.py                  64.9s
2026-10-07T12:06:27.9524780Z ============================== test_signatures.py FAIL (rc=124) timed out after 900s ==============================
2026-10-07T12:06:27.9525501Z ...
2026-10-07T12:06:27.9525944Z test file                      result   seconds
2026-10-07T12:06:27.9560363Z test_signatures.py               FAIL     900.7  timed out after 900s
2026-10-07T12:06:27.9566089Z 63/64 test files passed in 3497.7s wall (2 at a time); failed: test_signatures.py
"""
LOG_MAC = """\
2026-10-07T11:24:24.2978030Z [18/64] FAIL test_cut_frames.py             376.9s rc=1
2026-10-07T12:09:46.3813690Z [54/64] FAIL test_showreel.py[2/3]          441.5s rc=1
2026-10-07T12:23:30.8992460Z ============================== test_cut_frames.py FAIL (rc=1)  ==============================
2026-10-07T12:23:30.8999020Z ..F..
2026-10-07T12:23:30.9000700Z ======================================================================
2026-10-07T12:23:30.9002810Z FAIL: test_default_render_draws_every_first_frame (__main__.CutFrames.test_default_render_draws_every_first_frame)
2026-10-07T12:23:30.9004780Z ----------------------------------------------------------------------
2026-10-07T12:23:30.9006240Z Traceback (most recent call last):
2026-10-07T12:23:30.9008270Z   File "/Users/runner/work/showtime/showtime/skills/showtime/tests/test_cut_frames.py", line 164, in t
2026-10-07T12:23:30.9014740Z     self.assertEqual(wrong, [], "frames without their scene's colour (frame, rgb)")
2026-10-07T12:23:30.9022470Z AssertionError: Lists differ: [(10, (255, 255, 255))] != []
2026-10-07T12:23:30.9029300Z FAILED (failures=1)
2026-10-07T12:23:30.9030650Z ============================== test_showreel.py[2/3] FAIL (rc=1)  ==============================
2026-10-07T12:23:30.9050800Z .......E............
2026-10-07T12:23:30.9054200Z ERROR: test_template_checks_clean_at_every_aspect (__main__.CheckTests.test_template_checks_clean_at_every_aspect)
2026-10-07T12:23:30.9056540Z The showreel template lays out for 16:9 and recomposes for tall and square frames
2026-10-07T12:23:30.9059700Z Traceback (most recent call last):
2026-10-07T12:23:30.9087980Z     raise TimeoutExpired(
2026-10-07T12:23:30.9092950Z subprocess.TimeoutExpired: Command '['/Users/runner/.showtime/venv/bin/python', 'check']' timed out
2026-10-07T12:23:30.9101160Z FAILED (errors=1)
2026-10-07T12:23:30.9102240Z test file                      result   seconds
2026-10-07T12:23:30.9118910Z test_cut_frames.py               FAIL     376.9
2026-10-07T12:23:30.9174670Z 62/64 test files passed in 4526.6s wall; failed: test_cut_frames.py, test_showreel.py
"""
SERVER = "https://github.com/o/r"
JOBS = [
    {"id": 1, "name": "nightly (macos-14)", "conclusion": "success", "head_sha": "a" * 40, "steps": []},
    {"id": 2, "name": "nightly (windows-2022)", "conclusion": "failure", "head_sha": "a" * 40,
     "html_url": SERVER + "/actions/runs/9/job/2",
     "steps": [{"name": "Setup (core tier)", "conclusion": "success"},
               {"name": "Full test suite", "conclusion": "failure"}]},
    {"id": 3, "name": "nightly (macos-15-intel)", "conclusion": "failure", "head_sha": "a" * 40,
     "html_url": SERVER + "/actions/runs/9/job/3",
     "steps": [{"name": "Full test suite", "conclusion": "failure"}]},
    {"id": 4, "name": "fast (${{ matrix.os }}, ${{ matrix.shard }}/3)", "conclusion": "skipped", "steps": []},
]


class FakeGh:
    """Answers the gh calls nightly_report.py makes; records every call (nothing reaches GitHub)."""

    def __init__(self, labelled=(), titled=(), fail_labelled_create=False):
        self.calls, self.labelled, self.titled = [], list(labelled), list(titled)
        self.fail_labelled_create = fail_labelled_create

    def __call__(self, args, stdin=None):
        self.calls.append((list(args), stdin))
        if args[:2] == ["issue", "list"]:
            if "--label" in args:
                return json.dumps([{"number": n, "title": nr.TITLE} for n in self.labelled])
            who = args[args.index("--author") + 1] if "--author" in args else None
            return json.dumps([{"number": x[0], "title": x[1]} for x in self.titled
                               if who is None or (x[2] if len(x) > 2 else nr.BOT) == who])
        if args[0] == "api" and args[1].endswith("/logs"):
            return {"2": LOG_WIN, "3": LOG_MAC}[args[1].split("/")[-2]]
        if args[0] == "api":
            return json.dumps({"jobs": JOBS})
        if args[:2] == ["issue", "create"] and "--label" in args and self.fail_labelled_create:
            raise RuntimeError("could not add label: 'ci: nightly' not found")
        return "https://github.com/o/r/issues/30\n"

    def writes(self):
        return [(a, s) for a, s in self.calls if a[0] == "issue" and a[1] in ("create", "comment", "close")]


def run_main(argv, gh):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = nr.main(["--repo", "o/r", "--run-id", "9", "--server", "https://github.com"] + argv, gh=gh)
    return rc, out.getvalue()


@unittest.skipIf(nr is None, SKIP_REPO)
class NightlyReportScript(unittest.TestCase):
    def test_parse_log_finds_files_tests_and_exception_types(self):
        win = nr.parse_log(LOG_WIN)
        self.assertEqual(list(win), ["test_signatures.py"])
        self.assertEqual(win["test_signatures.py"]["note"], "timed out after 900s")
        self.assertEqual(win["test_signatures.py"]["seconds"], 900.7)
        self.assertEqual(win["test_signatures.py"]["tests"], [])
        mac = nr.parse_log(LOG_MAC)
        self.assertEqual(sorted(mac), ["test_cut_frames.py", "test_showreel.py[2/3]"])
        self.assertEqual(mac["test_cut_frames.py"]["tests"],
                         [["FAIL", "test_default_render_draws_every_first_frame", "AssertionError"]])
        self.assertEqual(mac["test_showreel.py[2/3]"]["tests"],
                         [["ERROR", "test_template_checks_clean_at_every_aspect", "subprocess.TimeoutExpired"]])
        self.assertEqual(mac["test_cut_frames.py"]["note"], "")

    def test_parse_log_serial_runner_and_noise(self):
        # -j 1: each file's output streams between its start line and its result line
        log = ("=== test_a.py (--fast)\nFAIL: test_one (__main__.A.test_one)\nValueError: bad\n"
               "=== test_a.py FAIL (rc=1) in 3.2s \n"
               "=== test_b.py (--fast)\nFAIL: a_test_that_printed_this (x)\n=== test_b.py PASS in 1.0s\n"
               "FAIL: not_in_a_file (x)\n")
        got = nr.parse_log(log)
        self.assertEqual(list(got), ["test_a.py"])
        self.assertEqual(got["test_a.py"]["tests"], [["FAIL", "test_one", "ValueError"]])
        self.assertEqual(got["test_a.py"]["seconds"], 3.2)
        self.assertEqual(nr.parse_log(""), {})
        self.assertEqual(nr.parse_log("random text\nFAIL: x (y)\n"), {})

    def test_comment_names_jobs_steps_files_and_tests(self):
        body = nr.build_comment(JOBS, {2: LOG_WIN, 3: LOG_MAC}, SERVER + "/actions/runs/9", SERVER + "/commit/abc")
        self.assertIn(SERVER + "/actions/runs/9", body)
        self.assertIn("**windows-2022**: failure, failed step: Full test suite ([log](%s/actions/runs/9/job/2))"
                      % SERVER, body)
        self.assertIn("- `test_signatures.py` (timed out after 900s, 901 s)", body)
        self.assertIn("- `test_cut_frames.py` (377 s): `test_default_render_draws_every_first_frame` AssertionError",
                      body)
        self.assertIn("`test_template_checks_clean_at_every_aspect` subprocess.TimeoutExpired", body)
        self.assertIn("Passed: macos-14.", body)
        self.assertNotIn("matrix.os", body)            # the skipped fast jobs are not nightly jobs
        self.assertNotIn("/Users/runner", body)        # nothing but names comes out of a log
        self.assertNotIn("Lists differ", body)

    def test_comment_without_logs_or_failed_jobs(self):
        body = nr.build_comment(JOBS, {}, "U")
        self.assertIn("**macos-15-intel**: failure, failed step: Full test suite", body)
        self.assertNotIn("test_cut_frames", body)
        body = nr.build_comment([JOBS[0]], {}, "U")
        self.assertIn("No nightly job reported a failure", body)

    def test_comment_is_capped_and_inert(self):
        log = "[1/2] FAIL test_x.py 1.0s rc=1 `boom` | <b>[x](y)</b>\n========== test_x.py FAIL (rc=1)\n"
        log += "".join("FAIL: test_%d (m.C.test_%d)\n" % (i, i) for i in range(25))
        files = nr.parse_log(log)
        self.assertEqual(files["test_x.py"]["note"], "boom  bx(y)/b")
        body = nr.build_comment([JOBS[2]], {3: log}, "U")
        self.assertIn("and 15 more", body)
        self.assertNotIn("<b>", body)

    def test_decide(self):
        self.assertEqual(nr.decide("failure", True, None), "create")
        self.assertEqual(nr.decide("failure", False, 30), "comment")
        self.assertEqual(nr.decide("success", True, 30), "close")
        self.assertEqual(nr.decide("success", False, 30), "none")   # a run on fewer images never closes it
        self.assertEqual(nr.decide("success", True, None), "none")
        self.assertEqual(nr.decide("cancelled", True, 30), "none")
        self.assertEqual(nr.decide("skipped", True, None), "none")

    def test_failure_opens_the_issue_with_its_labels(self):
        gh = FakeGh()
        rc, _ = run_main(["--result", "failure", "--full"], gh)
        self.assertEqual(rc, 0)
        (args, body), = gh.writes()
        self.assertEqual(args[:2], ["issue", "create"])
        self.assertIn("Nightly failing on main", args)
        self.assertEqual([args[i + 1] for i, a in enumerate(args) if a == "--label"], ["ci: nightly", "type: chore"])
        self.assertIn("--body-file", args)
        self.assertIn("https://github.com/o/r/actions/runs/9", body)
        self.assertIn("https://github.com/o/r/commit/" + "a" * 40, body)
        self.assertIn("test_signatures.py", body)

    def test_failure_comments_on_the_open_issue(self):
        gh = FakeGh(labelled=[30])
        run_main(["--result", "failure"], gh)
        (args, body), = gh.writes()
        self.assertEqual(args[:3], ["issue", "comment", "30"])
        self.assertIn("test_cut_frames.py", body)

    def test_green_full_run_closes_it(self):
        gh = FakeGh(labelled=[30])
        run_main(["--result", "success", "--full"], gh)
        (args, _), = gh.writes()
        self.assertEqual(args[:3], ["issue", "close", "30"])
        self.assertIn("Green again: https://github.com/o/r/actions/runs/9\n", args)
        gh = FakeGh(labelled=[30])
        run_main(["--result", "success"], gh)
        self.assertEqual(gh.writes(), [])
        gh = FakeGh(labelled=[30])
        run_main(["--result", "cancelled", "--full"], gh)
        self.assertEqual(gh.writes(), [])

    def test_missing_label_falls_back_to_the_title(self):
        gh = FakeGh(fail_labelled_create=True)
        run_main(["--result", "failure"], gh)
        creates = [a for a, _ in gh.calls if a[:2] == ["issue", "create"]]
        self.assertEqual(len(creates), 2)
        self.assertNotIn("--label", creates[1])
        # found again by its exact title (another issue whose title only contains it does not count)
        gh = FakeGh(titled=[(31, "Re: Nightly failing on main?"), (32, nr.TITLE)])
        run_main(["--result", "failure"], gh)
        (args, _), = gh.writes()
        self.assertEqual(args[:3], ["issue", "comment", "32"])
        # someone else's issue with that title is never adopted (commented on, closed on green)
        gh = FakeGh(titled=[(33, nr.TITLE, "a-stranger")])
        run_main(["--result", "failure"], gh)
        (args, _), = gh.writes()
        self.assertEqual(args[:2], ["issue", "create"])
        search = [a for a, _ in gh.calls if a[:2] == ["issue", "list"] and "--search" in a][0]
        self.assertEqual(search[search.index("--author") + 1], "app/github-actions")
        gh = FakeGh(titled=[(33, nr.TITLE, "a-stranger")])
        run_main(["--result", "success", "--full"], gh)
        self.assertEqual(gh.writes(), [])

    def test_dry_run_writes_nothing(self):
        for labelled, result in (([], "failure"), ([30], "failure"), ([30], "success")):
            gh = FakeGh(labelled=labelled)
            rc, out = run_main(["--result", result, "--full", "--dry-run"], gh)
            self.assertEqual(rc, 0)
            self.assertEqual(gh.writes(), [])
            self.assertIn("would run: gh issue", out)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
