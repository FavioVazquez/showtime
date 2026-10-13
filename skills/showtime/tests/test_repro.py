#!/usr/bin/env python3
"""`showtime repro` (lib/st/repro.py, cli_repro.py): a failing Playwright test -> a narrated video for a bug report.

Pure Python, no browser: the trace parser on a real trace (fixtures/repro/trace.zip, written by
`playwright test --trace on` from fixtures/repro/login.spec.js against fixtures/repro/app/, machine paths replaced
by /home/user), a library-only trace (what `pytest --tracing on` writes) and an attack trace (the fixture edited:
keyboard.type, a type="password" field, secrets in console and error text, an error the test caught) built here;
the filters (typed values, query strings, paths, auth headers, NAME=value, e-mails, --redact everywhere it shows,
linear time), the limits on big traces, locators and captions, script.md and its edits, the plan, the captions
file, the runner (flags, environment, where traces are looked for), and the CLI without rendering (the review
gate, every file of the job, nothing left behind, a fake pytest for the command path). With a browser (skipped under --fast and when Playwright or its browser is missing): the
fixture test run with tracing on by `showtime repro -- node .../cli.js test` (a real trace, deleted after it was
read), and `showtime repro <trace.zip>` then `--yes --no-voice --preview` end to end (repro.mp4, steps.json,
repro.md, qa PASS or WARN, no path of the machine outside the ledger and qa's reports).

usage: python tests/test_repro.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

from _listen import needs_listen, skip_if_listen_refused

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
FIX = TESTS_DIR / "fixtures" / "repro"
TRACE = FIX / "trace.zip"
sys.path.insert(0, str(SKILL / "lib"))

from st import repro as rp  # noqa: E402
from st.common import ShowtimeError  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
HOME = showtime_home()
ENV = build_env(HOME)
NODE = shutil.which("node", path=ENV.get("PATH"))
NM = HOME / "node" / "node_modules"
BROWSERS = HOME / "browsers"
READY = bool(NODE) and (NM / "playwright" / "cli.js").is_file() and any(BROWSERS.glob("chromium*"))
# what the fixture test types and visits: none of it may reach a text the film, the captions or the reports show
SECRETS = ("hunter2-not-real", "tok-0000-not-real", "s3ss10n-n0t-real", "session=", "ada@example.test")
# what the attack trace (attack_trace) adds: typed with the keyboard, logged by the app, the machine's paths
ATTACK = SECRETS + ("kb-secret-77xy", "abcd1234efgh5678ijkl9999", "ERRTOK-7766-ab", "zz9988xx", "ada.lovelace",
                         "hunter3pw", "alice.smith", "/Users/alice", "/home/user", "Sup3rS3cretPw")
SCREENSHOTS = "screenshots are shown as captured; --redact does not touch pixels"


def showtime(*args, check=True, env=None, cwd=None, timeout=300, stdin=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def texts_of(folder: Path):
    """Every file under a folder, as text (screenshots too: no secret may sit in their bytes either)."""
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            yield f, f.read_bytes().decode("utf-8", errors="replace")


LEDGER = ("job.json", "SHOWTIME.md")         # showtime's own bookkeeping: the job's folder and its tools' paths


def assert_clean(test, job: Path, planted, machine=()):
    """No file of the job holds a planted secret or the trace's machine paths; no file but the ledger (and the
    reports qa keeps in work/) holds a path of this machine."""
    for f, text in texts_of(job):
        for s in planted:
            test.assertNotIn(s, text, "%s shows %r" % (f.relative_to(job), s))
        if f.name not in LEDGER and f.relative_to(job).parts[0] != "work":
            for s in machine:
                test.assertNotIn(s, text, "%s shows the path %r" % (f.relative_to(job), s))


def jpeg_bytes() -> bytes:
    with zipfile.ZipFile(str(TRACE)) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".jpeg")))


def library_trace(path: Path, n_steps: int, *, fail: bool = True, secret_field: bool = False,
                  keyboard: bool = False) -> Path:
    """A trace with only the library's events (what pytest --tracing on writes): goto, then clicks, then (failing)
    an expect; a frame per step; stacks pointing at tests/test_long.py. `keyboard`: step 2 clicks a password field
    known only by type="password" (label "Mot de passe") and step 3 types into it with page.keyboard.type."""
    ev = [{"version": 9, "type": "context-options", "origin": "library", "browserName": "chromium",
           "playwrightVersion": "1.63.0", "sdkLanguage": "python", "wallTime": 1, "monotonicTime": 0,
           "options": {"viewport": {"width": 1000, "height": 500}}}]
    stacks = []
    t = 100.0
    files = {}
    for i in range(n_steps):
        cid = 10 + 2 * i
        last = i == n_steps - 1
        cls = "Frame"
        if i == 0:
            before = {"method": "goto", "params": {"url": "https://shop.example.test/cart?coupon=SECRET-COUPON#top"}}
        elif last:
            before = {"method": "expect", "title": 'Expect "toHaveText"',
                      "params": {"selector": "internal:testid=[data-testid=\"total\"s]", "expression": "to.have.text",
                                 "expectedText": [{"string": "$10.00"}], "isNot": False}}
        elif secret_field and i == 1:
            before = {"method": "fill", "params": {"selector": "#otp", "value": "918273"}}
        elif keyboard and i == 1:
            before = {"method": "click", "params": {"selector": "internal:label=\"Mot de passe\"i"}}
        elif keyboard and i == 2:
            before, cls = {"method": "keyboardType", "params": {"text": "kb-secret-77xy"}}, "Page"
        else:
            before = {"method": "click", "params": {"selector": "internal:role=button[name=\"Add %d\"i]" % i}}
        ev.append(dict({"type": "before", "callId": "call@%d" % cid, "startTime": t, "class": cls}, **before))
        if secret_field and i == 1:
            ev.append({"type": "log", "callId": "call@%d" % cid, "time": t + 1,
                       "message": "  locator resolved to <input id=\"otp\" name=\"code\" autocomplete=\"one-time-code\"/>"})
        if keyboard and i == 1:
            ev.append({"type": "log", "callId": "call@%d" % cid, "time": t + 1,
                       "message": "  locator resolved to <input id=\"mdp\" type=\"password\"/>"})
            ev.append({"type": "input", "callId": "call@%d" % cid, "point": {"x": 500, "y": 150},
                       "box": {"x": 300, "y": 130, "width": 400, "height": 40}})
        elif before["method"] == "click":
            ev.append({"type": "log", "callId": "call@%d" % cid, "time": t + 1,
                       "message": "waiting for getByRole('button', { name: 'Add %d' })" % i})
            ev.append({"type": "input", "callId": "call@%d" % cid, "point": {"x": 500, "y": 250},
                       "box": {"x": 450, "y": 230, "width": 100, "height": 40}})
        if last and fail:
            ev.append({"type": "log", "callId": "call@%d" % cid, "time": t + 2, "message": '  unexpected value "$12.00"'})
        name = "resources/frame-%03d.jpeg" % i
        files[name] = jpeg_bytes()
        ev.append({"type": "screencast-frame", "pageId": "page@1", "file": name, "width": 1000, "height": 500,
                   "timestamp": t + 5})
        ev.append(dict({"type": "after", "callId": "call@%d" % cid, "endTime": t + 20},
                       **({"error": {"message": "Expect failed"}} if last and fail else {})))
        stacks.append([cid, [[0, 5 + i, 4, ""]]])
        t += 100.0
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("trace.trace", "\n".join(json.dumps(e) for e in ev) + "\n")
        z.writestr("trace.stacks", json.dumps({"files": ["/home/user/shop/tests/test_long.py"], "stacks": stacks}))
        for k, v in files.items():
            z.writestr(k, v)
    return path


def built_trace(path: Path, calls) -> Path:
    """A library-only trace from call specs: {method, cls, params, resolved (the element the locator resolved
    to), box, error, snaps: [(phase, html)]}, a 1000x500 page, one screencast frame after each call."""
    ev = [{"version": 9, "type": "context-options", "origin": "library", "browserName": "chromium",
           "playwrightVersion": "1.63.0", "sdkLanguage": "python", "wallTime": 1, "monotonicTime": 0,
           "options": {"viewport": {"width": 1000, "height": 500}}}]
    files = {}
    t = 100.0
    for i, c in enumerate(calls):
        cid = "call@%d" % (10 + 2 * i)
        ev.append({"type": "before", "callId": cid, "startTime": t, "class": c.get("cls", "Frame"),
                   "method": c["method"], "params": c.get("params") or {}, **({"title": c["title"]} if "title" in c else {})})
        if c.get("resolved"):
            ev.append({"type": "log", "callId": cid, "time": t + 1, "message": "  locator resolved to " + c["resolved"]})
        if c.get("box"):
            x, y, w, h = c["box"]
            ev.append({"type": "input", "callId": cid, "point": {"x": x + w / 2, "y": y + h / 2},
                       "box": {"x": x, "y": y, "width": w, "height": h}})
        for phase, html in c.get("snaps") or ():
            ev.append({"type": "frame-snapshot", "snapshot": {
                "callId": cid, "phase": phase, "pageId": "page@1", "frameId": "frame@1",
                "frameUrl": "https://app.example.test/form", "isMainFrame": True, "html": html}})
        name = "resources/frame-%03d.jpeg" % i
        files[name] = jpeg_bytes()
        ev.append({"type": "after", "callId": cid, "endTime": t + 20, **({"error": c["error"]} if c.get("error") else {})})
        ev.append({"type": "screencast-frame", "pageId": "page@1", "file": name, "width": 1000, "height": 500,
                   "timestamp": t + 30})
        t += 100.0
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr("trace.trace", "\n".join(json.dumps(e) for e in ev) + "\n")
        for k, v in files.items():
            z.writestr(k, v)
    return path


def form(token="", scroll=0, target=None, other=True):
    """A page's DOM snapshot: the API token field (its value, as Playwright records it), a button, and maybe
    another field; `scroll`: the page scrolled down that many pixels; `target`: the element the call acts on."""
    tgt = lambda name: {"__playwright_target__": ""} if target == name else {}  # noqa: E731
    body = ["BODY", {}, ["INPUT", dict({"id": "token", "name": "api_token", "type": "text",
                                        "__playwright_value_": token}, **tgt("token"))],
            ["BUTTON", dict({"id": "go"}, **tgt("go")), "Go"]]
    if other:
        body.append(["INPUT", dict({"id": "email", "type": "email", "__playwright_value_": ""}, **tgt("email"))])
    return ["HTML", {"__playwright_scroll_top_": str(scroll)} if scroll else {}, ["HEAD", {}], body]


def node_count(html) -> int:
    """How many nodes a snapshot numbers (strings and elements; references are not numbered)."""
    if isinstance(html, str):
        return 1
    if html and isinstance(html[0], list):
        return 0
    return 1 + sum(node_count(c) for c in html[2:])


def boxes(step):
    """A step's covers, as boxes (without the step each one is for)."""
    return [{k: c[k] for k in ("x", "y", "w", "h")} for c in step["covers"]]


EXPECT_FAIL = {"method": "expect", "title": 'Expect "toHaveText"', "error": {"message": "Expect failed"},
               "params": {"selector": "#out", "expression": "to.have.text", "expectedText": [{"string": "ok"}]}}


ATTACK_LOG = ("GET https://admin:Sup3rS3cretPw@staging.acme.test/login?next=/x&sid=s3ss10n-n0t-real#access_token=zz "
              "failed: Authorization: Bearer abcd1234efgh5678ijkl9999 token ERRTOK-7766-ab) api_key=zz9988xx rejected "
              "for ada.lovelace@corp.example password: hunter3pw at /Users/alice.smith/acme/app.js:3")


def attack_trace(path: Path, *, caught: bool = False, passing: bool = False, same: bool = False) -> Path:
    """The fixture trace, edited: the machine's paths are /Users/alice.smith/; the password field is known only
    by type="password" (label "Mot de passe"); step 4 types with page.keyboard.type (no locator) instead of
    filling the API token field; the console error and the failure carry a Bearer token, `token X`, NAME=value
    secrets, an e-mail and a home path. `caught`: step 2 also has an error the test caught. `passing`: the test
    passed (no error event, the expect passed), with step 2's caught error left. `same`: the caught error has
    the same first line as the test's own (a retry loop in try/catch)."""
    with zipfile.ZipFile(str(TRACE)) as src:
        final = next(json.loads(x)["message"] for x in src.read("test.trace").decode("utf-8").splitlines()
                     if x.strip() and json.loads(x).get("type") == "error")
    with zipfile.ZipFile(str(TRACE)) as src, zipfile.ZipFile(str(path), "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".trace"):
                out = []
                for line in data.decode("utf-8").splitlines():
                    if not line.strip():
                        continue
                    e = json.loads(line)
                    cid = e.get("callId") or e.get("stepId")
                    if e.get("type") == "before" and cid == "pw:api@46":
                        e["subtitle"] = e["params"]["locator"] = "getByLabel('Mot de passe')"
                    if e.get("type") == "before" and cid == "call@15":
                        e["params"]["selector"] = "internal:label=\"Mot de passe\"i"
                    if e.get("type") == "log" and cid == "call@15" and "locator resolved" in e["message"]:
                        e["message"] = "  locator resolved to <input id=\"mdp\" type=\"password\"/>"
                    if e.get("type") == "before" and cid == "pw:api@47":
                        e.update(title='Type "kb-secret-77xy"', subtitle="", params={"text": "kb-secret-77xy"})
                    if e.get("type") == "before" and cid == "call@17":
                        e.update({"class": "Page", "method": "keyboardType", "params": {"text": "kb-secret-77xy"}})
                    if cid == "call@17" and (e.get("type") == "input" or e.get("type") == "log"
                                             and ("waiting for" in e["message"] or "resolved" in e["message"])):
                        continue
                    if e.get("type") == "console":
                        e["text"] = ATTACK_LOG
                        e["args"] = []
                    if e.get("type") == "error" or (e.get("type") == "after" and e.get("error")):
                        target = e if e.get("type") == "error" else e["error"]
                        target["message"] = target["message"].replace(
                            "Timeout:  1500ms\n", "Timeout:  1500ms\nServer said: " + ATTACK_LOG + "\n")
                        if passing:
                            if e.get("type") == "error":
                                continue
                            e.pop("error")
                    if caught or passing or same:
                        if e.get("type") == "after" and cid in ("pw:api@45", "call@13"):
                            e["error"] = {"message": final if same else "TimeoutError: locator.click: Timeout 500ms "
                                                     "exceeded.\nCall log:\n  - waiting for getByLabel('Email')"}
                    out.append(json.dumps(e))
                data = ("\n".join(out) + "\n").encode("utf-8")
            data = data.replace(b"tok-0000-not-real", b"kb-secret-77xy").replace(b"/home/user/", b"/Users/alice.smith/")
            dst.writestr(info, data)
    return path


def fake_pytest(folder: Path, *, into_cwd: bool = False) -> Path:
    """An executable named pytest that copies the fixture trace (a failing test) to <--output>/t1/trace.zip, as
    `pytest --tracing retain-on-failure` would; `into_cwd`: into ./elsewhere/ instead (where showtime never looks)."""
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "pytest"
    exe.write_text("#!%s\nimport os, shutil, sys\nargs = sys.argv[1:]\nout = args[args.index('--output') + 1]\n"
                   "dst = os.path.join(%s, 't1')\nos.makedirs(dst, exist_ok=True)\n"
                   "shutil.copyfile(%r, os.path.join(dst, 'trace.zip'))\nsys.exit(1)\n"
                   % (sys.executable, "'elsewhere'" if into_cwd else "out", str(TRACE)), encoding="utf-8")
    exe.chmod(0o755)
    return exe


class TestParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = rp.parse(TRACE)

    def test_steps(self):
        steps = self.rep["steps"]
        self.assertEqual([s["kind"] for s in steps], ["goto", "fill", "fill", "fill", "click", "expect"])
        self.assertEqual([s["caption"] for s in steps], [
            "Open app/index.html",
            "Type 16 characters into the 'Email' field",
            "Type 16 characters into the 'Password' field",
            "Type 17 characters into the 'API token' field",
            "Click the 'Sign in' button",
            "Expect the level-1 heading to have text \u201cWelcome, Ada!\u201d"])
        self.assertEqual([s["line"] for s in steps], [7, 8, 9, 10, 11, 12])
        self.assertTrue(all(s["file"] == "login.spec.js" for s in steps))
        self.assertEqual([s["status"] for s in steps], ["passed"] * 5 + ["failed"])
        click = steps[4]
        self.assertEqual(click["point"], {"x": 50.0, "y": 65.96})                 # 640, 474.9 in a 1280x720 page
        self.assertEqual(click["box"], {"x": 33.59, "y": 62.54, "w": 32.81, "h": 6.83})
        self.assertTrue(all(s["shot"] for s in steps))
        self.assertEqual(self.rep["viewport"], {"width": 1280, "height": 720})
        self.assertEqual((self.rep["browser"], self.rep["playwright"], self.rep["language"]),
                         ("chromium", "1.63.0", "javascript"))

    def test_fill_scenes_show_the_page_after_the_fill(self):
        """Screencast frames lag: a fill's screenshot is one taken after it ended, not the empty field."""
        with zipfile.ZipFile(str(TRACE)) as z:
            raw = rp.read_raw(z)
        at = {e["file"]: e["timestamp"] for e in raw["lib"] if e.get("type") == "screencast-frame"}
        ends = sorted(e["endTime"] for e in raw["lib"] if e.get("type") == "after" and e.get("callId") in
                      ("call@13", "call@15", "call@17"))
        fills = [s for s in self.rep["steps"] if s["kind"] == "fill"]
        for s, end in zip(fills, ends):
            self.assertGreater(at[s["shot"]], end, "step %d shows a frame from before its fill" % s["n"])

    def test_test_and_failure(self):
        self.assertEqual(self.rep["test"], {"title": "signs in and greets the user", "file": "login.spec.js", "line": 6,
                                            "location": "login.spec.js:6"})
        f = self.rep["failure"]
        self.assertEqual((f["step"], f["file"], f["line"]), (6, "login.spec.js", 12))
        self.assertEqual(f["headline"], "expect(locator).toHaveText(expected) failed")
        self.assertEqual(f["expected"]["text"], '"Welcome, Ada!"')
        self.assertEqual(f["received"]["text"], '"Welcome back, Ada"')
        # the parts Playwright marks as different (inverse video in its message)
        self.assertEqual(f["expected"]["parts"], [['"Welcome, Ada', False], ["!", True], ['"', False]])
        self.assertEqual(f["received"]["parts"], [['"Welcome', False], [" back", True], [', Ada"', False]])
        self.assertEqual(f["details"], ["Timeout: 1500ms"])
        self.assertEqual(f["call_log"], 'unexpected value "Welcome back, Ada"')
        self.assertEqual(f["source"], {"line": 12, "text": "await expect(page.getByRole('heading', { level: 1 }))"
                                                            ".toHaveText('Welcome, Ada!', { timeout: 1500 });"})
        self.assertEqual(self.rep["console"], [{"at": 0.799, "text": "Failed to load avatar for Ada: 404"}])

    def test_a_caught_error_is_not_the_failure(self):
        """An error the test caught (step 2's .catch()) neither is the failing step nor makes a passing test fail."""
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-caught-"))
        try:
            rep = rp.parse(attack_trace(tmp / "t.zip", caught=True))
            self.assertEqual(rep["failure"]["step"], 6)
            self.assertEqual(rep["failure"]["expected"]["text"], '"Welcome, Ada!"')
            self.assertEqual([s["status"] for s in rep["steps"]], ["passed"] * 5 + ["failed"])
            self.assertTrue(rep["steps"][1].get("caught"))
            p = rp.plan(rep, rerun="")
            self.assertIn("fail", [sc["id"] for sc in p["scenes"]])
            self.assertEqual(p["shown_steps"], 6)
            self.assertIn("2. Type 16 characters into the 'Email' field (`login.spec.js:8`) (an error the test caught)",
                          rp.markdown(rep, p))
            self.assertEqual(rp.has_failure(tmp / "t.zip")[0], True)
            self.assertEqual(rp.has_failure(attack_trace(tmp / "ok.zip", passing=True))[0], False)
            # a caught error with the test's own first line (a retry loop): the last step that raised it failed
            same = rp.parse(attack_trace(tmp / "same.zip", same=True))
            self.assertEqual(same["failure"]["step"], 6)
            self.assertEqual([s["status"] for s in same["steps"]], ["passed"] * 5 + ["failed"])
            self.assertTrue(same["steps"][1].get("caught"))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_library_only_trace(self):
        """pytest --tracing on: no runner steps, so the library's calls, stacks and expect params are used."""
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-lib-"))
        try:
            rep = rp.parse(library_trace(tmp / "trace.zip", 4))
            self.assertEqual([s["caption"] for s in rep["steps"]], [
                "Open shop.example.test/cart", "Click the 'Add 1' button", "Click the 'Add 2' button",
                "Expect test id 'total' to have text \u201c$10.00\u201d"])
            f = rep["failure"]
            self.assertEqual((f["step"], f["file"], f["line"]), (4, "test_long.py", 8))
            self.assertEqual((f["expected"]["text"], f["received"]["text"]), ("$10.00", "$12.00"))
            self.assertEqual(f["headline"], "expect(...).toHaveText() failed")
            self.assertEqual(rep["language"], "python")
            self.assertEqual(rep["test"]["title"], "Playwright test")
            self.assertNotIn("SECRET-COUPON", json.dumps(rep))
            passing = rp.parse(library_trace(tmp / "ok.zip", 3, fail=False))
            self.assertIsNone(passing["failure"])
            self.assertEqual(rp.has_failure(tmp / "trace.zip")[0], True)
            self.assertEqual(rp.has_failure(tmp / "ok.zip")[0], False)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_not_a_trace(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-bad-"))
        try:
            (tmp / "a.zip").write_text("not a zip", encoding="utf-8")
            with zipfile.ZipFile(str(tmp / "b.zip"), "w") as z:
                z.writestr("readme.txt", "hi")
            for name, msg in (("a.zip", "is not a zip file"), ("b.zip", "holds no Playwright trace"),
                              ("none.zip", "trace not found")):
                with self.assertRaises(ShowtimeError) as cm:
                    rp.parse(tmp / name)
                self.assertIn(msg, str(cm.exception))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_limits_on_big_traces(self):
        """Members are counted, event lines are streamed with a length cap (a long DOM snapshot keeps only its
        callId and frame URL) and big attachments are not opened."""
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-big-"))
        saved = (rp.MAX_MEMBERS, rp.MAX_LINE, rp.MAX_ATTACHMENT)
        try:
            rp.MAX_MEMBERS = 5
            with self.assertRaises(ShowtimeError) as cm:
                rp.parse(TRACE)
            self.assertIn("too large to read safely", str(cm.exception))
            rp.MAX_MEMBERS = saved[0]
            rp.MAX_LINE = 2000                         # every frame snapshot of the fixture is longer
            rep = rp.parse(TRACE)
            self.assertEqual(rep["steps"][1]["url"], "app/index.html")       # the snapshot's frame URL was kept
            rp.MAX_LINE, rp.MAX_ATTACHMENT = saved[1], 100
            self.assertEqual(rp.parse(TRACE, label="the-folder")["test"]["title"], "signs in and greets the user")
        finally:
            rp.MAX_MEMBERS, rp.MAX_LINE, rp.MAX_ATTACHMENT = saved
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_the_event_cap_is_counted_while_reading(self):
        """The cap stops the read at the first event past it, not after a whole .trace member is in memory."""
        real, read = rp._jsonl, []

        def counting(*a, **k):
            for e in real(*a, **k):
                read.append(1)
                yield e
        with mock.patch.object(rp, "MAX_EVENTS", 10), mock.patch.object(rp, "_jsonl", counting):
            with self.assertRaises(ShowtimeError) as cm:
                rp.parse(TRACE)
        self.assertIn("more than 10 events", str(cm.exception))
        self.assertEqual(len(read), 11)
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-cap-"))
        try:                                                            # the stacks are still read
            self.assertEqual(rp.parse(library_trace(tmp / "t.zip", 3))["failure"]["file"], "test_long.py")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class TestRedaction(unittest.TestCase):
    def test_secret_fields(self):
        for yes in ("Password", "password_confirm", "api_key", "API key", "apiKey", "otp", "OTP code", "otpCode",
                    "client secret", "token", "x-auth-token", "license-keys"):
            self.assertTrue(rp.is_sensitive(yes), yes)
        for no in ("Email", "Keyword", "monkey", "footprint", "Search", "hockey team"):
            self.assertFalse(rp.is_sensitive(no), no)
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-otp-"))
        try:                                     # by the element: autocomplete="one-time-code" on #otp
            rep = rp.parse(library_trace(tmp / "t.zip", 3, secret_field=True))
            self.assertEqual(rep["steps"][1]["caption"], "Type 6 characters into #otp")
            self.assertTrue(rep["steps"][1]["secret_field"])
            self.assertNotIn("918273", json.dumps(rep))
            # --show-typed never shows a secret field's value
            rep = rp.parse(tmp / "t.zip", show_typed=True)
            self.assertNotIn("918273", json.dumps(rep))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_password_type_alone_marks_a_field_secret(self):
        """type="password" with a label that says nothing (Mot de passe): the field is secret by its type."""
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-pw-"))
        try:
            rep = rp.parse(attack_trace(tmp / "t.zip"), show_typed=True)
            pw = rep["steps"][2]
            self.assertEqual((pw["caption"], pw["secret_field"]), ("Type 16 characters into the 'Mot de passe' field", True))
            self.assertNotIn("hunter2-not-real", json.dumps(rep))
            self.assertEqual(rep["steps"][1]["caption"], "Fill the 'Email' field with \u201c%s@example.test\u201d" % rp.MASK)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_typed_values_never_shown_or_spoken(self):
        """Any field, any API: fill, and page.keyboard.type with no locator (after clicking a password field) show
        how many characters were typed, never what; the field is covered on screen from then on."""
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-typed-"))
        try:
            for trace, kb in ((library_trace(tmp / "lib.zip", 5, keyboard=True), 2),
                              (attack_trace(tmp / "run.zip"), 3)):
                rep = rp.parse(trace)
                s = rep["steps"][kb]
                self.assertEqual((s["kind"], s["caption"], s["value"]), ("type", "Type 14 characters into the page", None))
                self.assertTrue(s["masked"] and s["secret_field"])
                p = rp.plan(rep, rerun="")
                lines = rp.narration(rep, p)
                self.assertEqual(lines.get("step%d" % (kb + 1)), "Type into the page.")
                outputs = [json.dumps(rp.steps_json(rep, p)), rp.markdown(rep, p), rp.build_srt(p, lines),
                           rp.build_page(rep, p, {}), json.dumps(lines), rp.write_script(rep, "", "")]
                for text in outputs:
                    for secret in ("kb-secret-77xy", "hunter2-not-real", "ada@example.test"):
                        self.assertNotIn(secret, text)
                prev = rep["steps"][kb - 1]
                self.assertIn(prev["box"], boxes(s))                    # the field it typed into is covered
                self.assertIn('class="cover"', rp.build_page(rep, p, {}))
            # no DOM snapshots: the cover stays on the same page; the runner's trace: the form is gone at the end
            lib = rp.parse(tmp / "lib.zip")
            self.assertIn(lib["steps"][1]["box"], boxes(lib["steps"][-1]))
            self.assertEqual(rep["steps"][-1]["covers"], [])
            fx = rp.parse(TRACE)
            self.assertEqual(len(fx["steps"][3]["covers"]), 3)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_covers_follow_their_field(self):
        """A cover follows its field through the DOM snapshots: it moves with the page's scroll (with a second
        chip at the old place, unless that would hide the step's own target: a fixed field does not scroll), is
        re-anchored when a step acts on the field again, and goes when the field is emptied or gone."""
        fx = rp.parse(TRACE)
        self.assertEqual(len(fx["steps"][4]["covers"]), 3)          # the Sign in click: the form is still there
        self.assertEqual(fx["steps"][5]["covers"], [])              # the welcome page replaced it (the failure)
        self.assertEqual(boxes(fx["steps"][0]), [fx["steps"][1]["box"]])  # its shot was taken during the fill
        tok, email, go = ('<input id="token" name="api_token" type="text"/>', '<input id="email" type="email"/>',
                          '<button id="go">')
        val = "tok-SECRET-1"
        calls = [
            {"method": "goto", "params": {"url": "https://app.example.test/form"}, "snaps": [("after", form())]},
            {"method": "fill", "params": {"selector": "#token", "value": val}, "resolved": tok, "box": (300, 300, 400, 40),
             "snaps": [("before", form()), ("action", form(target="token")), ("after", form(val, target="token"))]},
            # the page scrolls 200 px to bring the button where the field was: the cover moves up with the field
            {"method": "click", "params": {"selector": "#go"}, "resolved": go, "box": (300, 300, 400, 40),
             "snaps": [("before", form(val, 200)), ("action", form(val, 200, target="go")), ("after", form(val, 200))]},
            {"method": "click", "params": {"selector": "#email"}, "resolved": email, "box": (300, 50, 400, 40),
             "snaps": [("before", form(val, 200)), ("action", form(val, 200, target="email"))]},
            {"method": "click", "params": {"selector": "#token"}, "resolved": tok, "box": (300, 120, 400, 40),
             "snaps": [("before", form(val, 200)), ("action", form(val, 200, target="token"))]},
            {"method": "click", "params": {"selector": "#go"}, "resolved": go, "box": (300, 200, 400, 40),
             "snaps": [("before", form(val, 200)), ("after", form("", 200))]},           # this click empties it
            {"method": "click", "params": {"selector": "#email"}, "resolved": email, "box": (300, 50, 400, 40),
             "snaps": [("before", [[1, node_count(form("", 200)) - 1]]), ("after", form("", 200, target="email"))]},
            dict(EXPECT_FAIL, snaps=[("before", ["HTML", {}, ["BODY", {}, "Done"]])]),
        ]
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-cover-"))
        try:
            rep = rp.parse(built_trace(tmp / "t.zip", calls))
            field = {"x": 30.0, "y": 60.0, "w": 40.0, "h": 8.0}
            up = dict(field, y=20.0)                                   # 200 px of a 500 px page
            self.assertEqual([boxes(s) for s in rep["steps"]], [
                [], [field], [up], [up, field], [dict(field, y=24.0)], [dict(field, y=24.0)], [], []])
            self.assertTrue(all(c["step"] == 2 for s in rep["steps"] for c in s["covers"]))
            self.assertIn("# step 2: Type 12 characters into #token (a secret field); the value is not shown or spoken; "
                          "its field is covered on screen in steps 2-6", rp.write_script(rep, "", ""))
            self.assertNotIn(val, json.dumps(rep))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_typing_into_a_field_it_cannot_name_is_secret(self):
        """--show-typed shows what page.keyboard typed into a field it can name that is not secret; after a Tab,
        or a hover after clicking a password field (a hover moves no focus), the field is unknown or secret:
        hidden, and script.md says it is not covered."""
        email, pw = '<input id="email" type="email"/>', '<input id="pw" type="password"/>'
        click = lambda sel, el: {"method": "click", "params": {"selector": sel}, "resolved": el,  # noqa: E731
                                 "box": (300, 100, 400, 40)}
        kb = lambda text: {"method": "keyboardType", "cls": "Page", "params": {"text": text}}  # noqa: E731
        tab = {"method": "keyboardPress", "cls": "Page", "params": {"key": "Tab"}}
        hover = {"method": "hover", "params": {"selector": "#email"}, "resolved": email, "box": (300, 200, 400, 40)}
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-tab-"))
        try:
            for i, (calls, secret) in enumerate((([click("#email", email), tab, kb("kb-secret-77xy")], "kb-secret-77xy"),
                                                 ([click("#pw", pw), hover, kb("kb-secret-77xy")], "kb-secret-77xy"),
                                                 ([click("#email", email), kb("hello there")], None))):
                rep = rp.parse(built_trace(tmp / ("t%d.zip" % i), calls + [EXPECT_FAIL]), show_typed=True)
                s = next(x for x in rep["steps"] if x["kind"] == "type")
                script = rp.write_script(rep, "", "")
                if secret is None:
                    self.assertEqual((s["value"], s["masked"]), ("hello there", False))
                    continue
                self.assertEqual((s["caption"], s["value"], s["masked"], s["secret_field"]),
                                 ("Type 14 characters into the page", None, True, True))
                for text in (json.dumps(rep), script):
                    self.assertNotIn(secret, text)
            self.assertIn("(a secret field)", rp.write_script(rp.parse(tmp / "t1.zip", show_typed=True), "", ""))
            tabbed = rp.write_script(rp.parse(tmp / "t0.zip", show_typed=True), "", "")
            self.assertIn("(typed into a field showtime cannot name, so it counts as secret); the value is not shown "
                          "or spoken; it is NOT covered on screen", tabbed)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_values_and_urls_never_shown(self):
        rep = rp.parse(TRACE)
        self.assertEqual([s["masked"] for s in rep["steps"]], [False, True, True, True, False, False])
        self.assertEqual(rep["privacy"]["masked_values"], 3)
        blob = json.dumps(rep)
        for s in SECRETS:
            self.assertNotIn(s, blob)
        self.assertNotIn("/home/user/", blob)
        self.assertEqual(rp.display_url("https://u:p@app.example.test/a/b?token=x#frag"), "app.example.test/a/b")
        self.assertEqual(rp.display_url("file:///Users/someone/proj/app/index.html?x=1"), "app/index.html")
        red = rp.Redactor()
        self.assertEqual(red("see http://localhost:3000/login?next=/admin&t=abc#x now"), "see http://localhost:3000/login now")
        self.assertEqual(red("navigating to /api/users?id=7"), "navigating to /api/users")
        self.assertEqual(red("expected /^Welcome?/i"), "expected /^Welcome?/i")
        self.assertIn(rp.MASK, red("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijklmno"))

    def test_paths_show_their_last_part(self):
        red = rp.Redactor()
        self.assertEqual(red("at /Users/someone/proj/x.spec.ts:4"), "at x.spec.ts:4")
        self.assertEqual(red("at /home/runner/work/app/tests/a.py:9 and ~/proj/b.ts"), "at a.py:9 and b.ts")
        self.assertEqual(red("C:\\Users\\bob\\proj\\c.ts:3 and /pri" "vate/var/fold" "ers/x/T/d.zip"), "c.ts:3 and d.zip")
        self.assertEqual(red("GET http://localhost:3000/home/x 404"), "GET http://localhost:3000/home/x 404")

    def test_secrets_in_console_and_error_text(self):
        red = rp.Redactor()
        out = red(ATTACK_LOG)
        for s in ("Sup3rS3cretPw", "admin", "s3ss10n-n0t-real", "abcd1234efgh5678ijkl9999", "ERRTOK-7766-ab",
                  "zz9988xx", "ada.lovelace", "hunter3pw", "alice.smith", "access_token"):
            self.assertNotIn(s, out)
        self.assertIn(rp.MASK + "@corp.example", out)
        self.assertIn("app.js:3", out)
        self.assertEqual(red("session=abc123; Path=/"), "session=%s; Path=/" % rp.MASK)
        self.assertEqual(red("Invalid token verification failed"), "Invalid token verification failed")
        self.assertEqual(red('fill("ada@example.test")'), 'fill("%s")' % rp.MASK)
        self.assertEqual(red("bob:Hunt3rPw@db.local"), rp.MASK + "@db.local")
        self.assertEqual(rp.Redactor(show_emails=True)("mail ada@corp.example"), "mail ada@corp.example")
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-att-"))
        try:
            rep = rp.parse(attack_trace(tmp / "t.zip"))
            blob = json.dumps(rep)
            for s in ATTACK:
                self.assertNotIn(s, blob)
            self.assertIn("Server said: GET https://staging.acme.test/login failed", " ".join(rep["failure"]["details"]))
            self.assertEqual(rep["failure"]["expected"]["text"], '"Welcome, Ada!"')      # kept, filtered
            self.assertEqual(rep["failure"]["received"]["text"], '"Welcome back, Ada"')
            self.assertLessEqual(len(rep["console"][0]["text"]), 301)
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_console_lines_are_capped(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-cons-"))
        try:
            src = library_trace(tmp / "t.zip", 3)
            with zipfile.ZipFile(str(src)) as z:
                members = {n: z.read(n) for n in z.namelist()}
            extra = "".join(json.dumps({"type": "console", "messageType": "error", "time": 101 + i,
                                        "text": "boom %d " % i + "x" * 2000}) + "\n" for i in range(50))
            members["trace.trace"] += extra.encode("utf-8")
            with zipfile.ZipFile(str(tmp / "c.zip"), "w") as z:
                for n, d in members.items():
                    z.writestr(n, d)
            rep = rp.parse(tmp / "c.zip")
            self.assertEqual((len(rep["console"]), rep["console_more"]), (rp.MAX_CONSOLE, 50 - rp.MAX_CONSOLE))
            self.assertTrue(all(len(c["text"]) <= 301 for c in rep["console"]))
            p = rp.plan(rep, rerun="")
            self.assertIn("The console logged 50 errors.", rp.narration(rep, p)["fail"])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_filters_run_in_linear_time(self):
        """Untrusted trace text never stalls the filters (the old path pattern was quadratic, the shared masks
        worse): long inputs are cut, long words are cut before the shared masks run."""
        import time
        red = rp.Redactor()
        for text in ("/a" * 16000, "a." * 16000, ("a." * 120 + " ") * 60, "@" + "a." * 8000, "token=" + "a" * 9000):
            t = time.time()
            red(text)
            self.assertLess(time.time() - t, 1.0, text[:20])

    def test_redact_patterns_everywhere(self):
        red = rp.Redactor([r"Ada\b", r"example\.test"])
        rep = rp.parse(TRACE, red)
        p = rp.plan(rep, rerun=rp.rerun_command(rep, None, red))
        lines = rp.narration(rep, p)
        outputs = {"steps": json.dumps(rp.steps_json(rep, p)), "md": rp.markdown(rep, p),
                   "srt": rp.build_srt(p, lines), "page": rp.build_page(rep, p, {}), "narration": json.dumps(lines),
                   "script": rp.write_script(rep, p["rerun"], "")}
        for name, text in outputs.items():
            self.assertNotRegex(text, r"Ada\b", name)
            self.assertNotIn("example.test", text, name)
        self.assertEqual(rep["failure"]["received"]["text"], '"Welcome back, %s"' % rp.MASK)
        self.assertEqual(rep["failure"]["received"]["parts"], [['"Welcome back, %s"' % rp.MASK, False]])  # no diff marks
        self.assertEqual(rep["console"][0]["text"], "Failed to load avatar for %s: 404" % rp.MASK)
        with self.assertRaises(ShowtimeError) as cm:
            rp.Redactor(["(unclosed"])
        self.assertIn("not a valid regular expression", str(cm.exception))


class TestScript(unittest.TestCase):
    def test_script_lists_every_line_and_edits_go_through_the_filter(self):
        rep = rp.parse(TRACE)
        text = rp.write_script(rep, "npx playwright test login.spec.js:6", "npx playwright show-trace trace.zip")
        for want in ("show test.title: signs in and greets the user", "say step3: Type into the Password field.",
                     "show fail.received: \"Welcome back, Ada\"", "show console1: Failed to load avatar for Ada: 404",
                     "show end.rerun: npx playwright test login.spec.js:6", "# step 3: Type 16 characters into the "
                     "'Password' field (a secret field)", SCREENSHOTS):
            self.assertIn(want, text)
        text = text.replace("show step1.caption: Open app/index.html",
                            "show step1.caption: Open acct-12345 with Bearer abcdefghijklmnop123 as /Users/someone/x.html")
        text = "\n".join(x for x in text.splitlines() if not x.startswith(("say step2:", "show console1:")))
        edited, rerun, viewer = rp.apply_script(rep, "npx playwright test login.spec.js:6", "", rp.read_script(text),
                                                rp.Redactor([r"acct-[0-9]+"]))
        self.assertEqual(edited["steps"][0]["caption"], "Open %s with Bearer %s as x.html" % (rp.MASK, rp.MASK))
        self.assertEqual(edited["console"], [])
        p = rp.plan(edited, rerun=rerun)
        lines = rp.narration(edited, p)
        self.assertNotIn("step2", lines)                                 # a deleted spoken line: a silent scene
        self.assertEqual(lines["step3"], "Type into the Password field.")
        self.assertEqual(edited["failure"]["expected"]["parts"], rep["failure"]["expected"]["parts"])  # unedited

    def test_edits_reach_every_output(self):
        """An edited caption, locator and value line leave nothing of the old text in steps.json, the project's
        repro.json, repro.md, the page, the narration or the captions (the step's target is rebuilt from its
        locator); the test's file follows its location; nothing is kept that script.md did not list."""
        red = rp.Redactor(show_emails=True)
        rep = rp.parse(TRACE, red, show_typed=True)
        text = rp.write_script(rep, "npx playwright test login.spec.js:6", "")
        for want in ("show step2.value: ada@example.test", "show step6.matcher: toHaveText"):
            self.assertIn(want, text)
        edits = {"show step2.caption:": "show step2.caption: Fill the first field",
                 "show step2.locator:": "show step2.locator: the first field",
                 "say step2:": "say step2: Fill the first field.", "show test.location:": "show test.location: x.spec.js:3"}
        out = []
        for line in text.splitlines():
            if line.startswith("show step2.value:"):
                continue                                                   # deleted
            out.append(next((v for k, v in edits.items() if line.startswith(k)), line))
        edited, rerun, viewer = rp.apply_script(rep, "npx playwright test login.spec.js:6", "",
                                                rp.read_script("\n".join(out)), red)
        s = edited["steps"][1]
        self.assertEqual((s["caption"], s["locator"], s["target"], s["value"]),
                         ("Fill the first field", "the first field", "the first field", None))
        self.assertEqual((edited["test"]["file"], edited["test"]["line"]), ("x.spec.js", 3))
        p = rp.plan(edited, rerun=rerun)
        lines = rp.narration(edited, p)
        outputs = {"steps.json": json.dumps(rp.steps_json(edited, p)), "repro.md": rp.markdown(edited, p),
                   "page": rp.build_page(edited, p, {}), "narration": json.dumps(lines), "srt": rp.build_srt(p, lines)}
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-edit-"))
        try:
            rp.write_project(tmp / "project", edited, p, tmp)
            for f in ("repro.json", "index.html", "showtime.json"):
                outputs["project/" + f] = (tmp / "project" / f).read_text(encoding="utf-8")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
        for name, blob in outputs.items():
            for old in ("Email", "ada@example.test"):
                self.assertNotIn(old, blob, "%s keeps %r" % (name, old))
        self.assertEqual(json.loads(outputs["project/repro.json"])["test"],
                         {"title": "signs in and greets the user", "file": "x.spec.js", "line": 3, "location": "x.spec.js:3"})


class TestLocatorsAndCaptions(unittest.TestCase):
    def test_human_locator(self):
        cases = {
            "getByRole('button', { name: 'Sign in' })": "the 'Sign in' button",
            "getByRole('heading', { level: 1 })": "the level-1 heading",
            "getByRole('textbox')": "the field",
            "getByLabel('Email')": "the 'Email' field",
            "getByPlaceholder('Search docs')": "the 'Search docs' field",
            "getByText('Welcome')": "the text 'Welcome'",
            "getByTestId('total')": "test id 'total'",
            "getByRole('dialog').getByRole('link', { name: 'Docs' }).first()": "the 'Docs' link",
            "locator('#cart .count')": "#cart .count",
        }
        for api, want in cases.items():
            self.assertEqual(rp.human_locator(api), want, api)

    def test_selector_api(self):
        self.assertEqual(rp._selector_api('internal:role=button[name="Sign in"i]'), "getByRole('button', { name: 'Sign in' })")
        self.assertEqual(rp._selector_api("internal:role=heading[level=2]"), "getByRole('heading', { level: 2 })")
        self.assertEqual(rp._selector_api('internal:label="Email"i'), "getByLabel('Email')")
        self.assertEqual(rp._selector_api('internal:attr=[placeholder="Search"i]'), "getByPlaceholder('Search')")
        self.assertEqual(rp._selector_api('internal:testid=[data-testid="x"s]'), "getByTestId('x')")
        self.assertEqual(rp._selector_api("#a > b"), "locator('#a > b')")

    def test_captions(self):
        c = rp.caption
        self.assertEqual(c("press", "the 'Search' field", "Enter", "", "", None), "Press Enter in the 'Search' field")
        self.assertEqual(c("expect", "", None, "", "toHaveURL", "/dashboard"), "Expect the page to have the URL \u201c/dashboard\u201d")
        self.assertEqual(c("expect", "the 'Save' button", None, "", "not.toBeVisible", None),
                         "Expect the 'Save' button not to be visible")
        self.assertEqual(c("check", "the 'Terms' checkbox", None, "", "", None), "Check the 'Terms' checkbox")
        self.assertEqual(c("select", "the 'Size' dropdown", "L", "", "", None), "Select \u201cL\u201d in the 'Size' dropdown")
        self.assertEqual(c("fill", "the 'Name' field", None, "", "", None, typed=1), "Type 1 character into the 'Name' field")
        self.assertEqual(c("fill", "the 'Name' field", None, "", "", None, typed=0), "Clear the 'Name' field")
        self.assertEqual(c("press", "", None, "", "", None), "Press a key")


class TestSound(unittest.TestCase):
    def test_sound_differs_per_test_and_is_stable(self):
        """0.4.3: the bed and the effects come from the test: the same one sounds the same, another one not."""
        import copy
        from unittest import mock
        rep = rp.parse(TRACE)
        p = rp.plan(rep, rerun="")
        other = copy.deepcopy(rep)
        other["test"]["title"] = "another test entirely"

        def mix(r, **kw):
            with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": "/nonexistent-music"}):
                ch = rp.bed_for(p, r, (), kw.get("music"), True)
                return rp.build_mix(p, r, (), ch)["tracks"]
        a, b = mix(rep), mix(other)
        self.assertEqual(a, mix(rep))
        self.assertNotEqual(a[0], b[0])
        sfx = lambda t: [x["synth"] for x in t if x.get("kind") == "sfx"]           # noqa: E731
        self.assertNotEqual(sfx(a), sfx(b))
        self.assertTrue(any(x["synth"]["type"] in ("error", "power-down") for x in a if x.get("kind") == "sfx"))
        marks = ("click", "tick", "pop", "toggle", "error", "power-down")                # sounds that mark what happens
        self.assertTrue(all(x["synth"]["type"] in marks for x in a if x.get("kind") == "sfx"))   # none on the cuts
        with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": "/nonexistent-music"}):
            cuts = rp.build_mix(p, rep, (), rp.bed_for(p, rep, (), None, True), True)["tracks"]
        self.assertEqual(sum(1 for x in cuts if x.get("synth", {}).get("type") in ("swoosh-in", "swoosh-out")),
                         len(p["scenes"]) - 1)                                           # --cut-sounds: opt in
        self.assertEqual(mix(rep, music="deep-house")[0]["compose"]["style"], "deep-house")
        with mock.patch.dict(os.environ, {"SHOWTIME_OFFLINE": "1", "SHOWTIME_MUSIC_CACHE": "/nonexistent-music"}):
            voice = [{"id": "vo-x", "kind": "voice", "file": "voice/x.wav", "start": 1.0}]
            self.assertEqual(rp.build_mix(p, rep, voice, rp.bed_for(p, rep, voice, None, True))["tracks"][0]["duck"],
                             {"under": "voice", "depth_db": 10.0, "carve": 0.4})       # 10 dB, not 12 (0.4.3)
            self.assertNotIn("duck", mix(rep)[0])
        self.assertNotIn("music", [x["kind"] for x in mix(rep, music="none")])


class TestPlan(unittest.TestCase):
    def test_fixture_plan(self):
        rep = rp.parse(TRACE)
        p = rp.plan(rep, rerun="npx playwright test login.spec.js:6")
        self.assertEqual([s["id"] for s in p["scenes"]], ["title", "step1", "step2", "step3", "step4", "step5", "fail", "end"])
        self.assertTrue(rp.MIN_SECONDS <= p["duration"] <= rp.MAX_SECONDS, p["duration"])
        fail = next(s for s in p["scenes"] if s["id"] == "fail")
        self.assertGreater(fail["dur"], max(s["dur"] for s in p["scenes"] if s["kind"] == "step"))  # it slows down
        starts = [s["start"] for s in p["scenes"]]
        self.assertEqual(starts, sorted(starts))
        lines = rp.narration(rep, p)
        self.assertEqual(lines["step2"], "Type into the Email field.")                       # values are never spoken
        self.assertEqual(lines["step3"], "Type into the Password field.")
        self.assertEqual(lines["fail"], 'Step 6 fails. It expected "Welcome, Ada!", but got "Welcome back, Ada". '
                                        "The console logged an error.")
        # a masked e-mail is spoken as one, not as "a hidden value at" its domain
        title = rp.Redactor()("signs in as ada.lovelace@corp.example")
        self.assertEqual(rp.title_line(dict(rep, test=dict(rep["test"], title=title))),
                         "Signs in as a hidden email address. This test fails at step 6.")
        self.assertEqual(rp._say("Got %s and %s@corp.example." % (rp.MASK, rp.MASK)),
                         "Got a hidden value and a hidden email address.")

    def test_long_tests_compress_passing_steps(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-long-"))
        try:
            rep = rp.parse(library_trace(tmp / "t.zip", 30))
            p = rp.plan(rep, rerun="pytest tests/test_long.py")
            ids = [s["id"] for s in p["scenes"]]
            self.assertLessEqual(p["duration"], rp.MAX_SECONDS)
            self.assertEqual(ids[:3], ["title", "step1", "skip"])                              # the first step, then the sum
            self.assertEqual(ids[-2:], ["fail", "end"])
            skip = p["scenes"][2]
            self.assertEqual(skip["skipped"], list(range(2, 2 + len(skip["skipped"]))))
            kept = [s["step"] for s in p["scenes"] if s["kind"] == "step"]
            self.assertEqual(kept[1:], list(range(kept[1], 30)))                            # the steps before the failure
            self.assertEqual(sorted(kept + skip["skipped"]), list(range(1, 30)))
            page = rp.build_page(rep, p, {})
            self.assertIn("passing steps", page)
            self.assertEqual(rp.narration(rep, p)["skip"], "Then %d more steps pass." % len(skip["skipped"]))
            # a two-step test still runs past 10 s; narration makes a scene at least as long as its line
            short = rp.parse(library_trace(tmp / "s.zip", 2))
            ps = rp.plan(short, rerun="")
            self.assertGreaterEqual(ps["duration"], rp.MIN_SECONDS)
            pv = rp.plan(short, rerun="", speech={"step1": 6.0})
            s1 = next(s for s in pv["scenes"] if s["id"] == "step1")
            self.assertEqual(s1["dur"], round(rp.VOICE_PAD + 6.0 + rp.VOICE_TAIL, 2))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_captions_file(self):
        from st.captions_rules import MAX_CPS, MAX_LINE_CHARS
        rep = rp.parse(TRACE)
        p = rp.plan(rep, rerun="npx playwright test login.spec.js:6")
        srt = rp.build_srt(p, rp.narration(rep, p))
        cues = [c for c in srt.strip().split("\n\n") if c]
        self.assertGreaterEqual(len(cues), len(p["scenes"]))
        last_end = 0.0
        for c in cues:
            parts = c.split("\n")
            a, b = [rp_time(x) for x in parts[1].split(" --> ")]
            text = parts[2:]
            self.assertLessEqual(len(text), 2, c)
            self.assertTrue(all(len(x) <= MAX_LINE_CHARS for x in text), c)
            self.assertGreaterEqual(a, last_end - 1e-6)
            self.assertLessEqual(len(" ".join(text)) / (b - a), MAX_CPS + 0.01, c)
            last_end = b
        self.assertLessEqual(last_end, p["duration"])


def rp_time(s: str) -> float:
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0


class TestRunner(unittest.TestCase):
    def test_tracing_flags(self):
        out = Path("/tmp/x")
        cmd, kind = rp.tracing_command(["npx", "playwright", "test", "tests/login.spec.ts"], out)
        self.assertEqual((kind, cmd[-4:]), ("playwright", ["--trace", "retain-on-failure", "--output", str(out)]))
        cmd, kind = rp.tracing_command(["npx", "playwright", "test", "--trace=on", "--output", "o"], out)
        self.assertEqual(cmd, ["npx", "playwright", "test", "--trace=on", "--output", "o"])
        cmd, kind = rp.tracing_command(["python", "-m", "pytest", "tests/test_login.py"], out)
        self.assertEqual((kind, cmd[-4:]), ("pytest", ["--tracing", "retain-on-failure", "--output", str(out)]))
        self.assertEqual(rp.runner_of(["pytest", "-k", "login"]), "pytest")
        self.assertEqual(rp.runner_of(["node", "node_modules/playwright/cli.js", "test"]), "playwright")
        self.assertEqual(rp.runner_of(["pnpm", "exec", "playwright", "test"]), "playwright")
        self.assertEqual(rp.runner_of(["npm", "test"]), "")
        self.assertEqual(rp.tracing_command(["npm", "test"], out), (["npm", "test"], ""))

    def test_user_env_drops_what_the_launcher_adds(self):
        e = rp.user_env(ENV)
        self.assertEqual(e["PATH"], ENV["SHOWTIME_USER_PATH"])
        self.assertNotIn(str(SKILL / "lib"), (e.get("PYTHONPATH") or "").split(os.pathsep))
        self.assertNotIn(ENV["SHOWTIME_NODE_MODULES"], (e.get("NODE_PATH") or "").split(os.pathsep))
        self.assertNotEqual(e.get("PLAYWRIGHT_BROWSERS_PATH"), str(HOME / "browsers"))
        mine = dict(ENV, PLAYWRIGHT_BROWSERS_PATH="/opt/pw", PYTHONPATH=str(SKILL / "lib") + os.pathsep + "/my/src")
        e = rp.user_env(mine)
        self.assertEqual((e["PLAYWRIGHT_BROWSERS_PATH"], e["PYTHONPATH"]), ("/opt/pw", "/my/src"))
        # from a bare environment: nothing the launcher set for itself reaches the user's tests
        bare = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR")}
        bare["HTTPS_PROXY"] = "http://proxy.example.test:3128"
        with mock.patch.dict(os.environ, bare, clear=True):
            env = build_env(HOME)
        e = rp.user_env(env)
        for var in ("PYTHONUTF8", "PYTHONIOENCODING", "HF_HUB_DISABLE_TELEMETRY", "SUPERTONIC_CACHE_DIR", "U2NET_HOME",
                    "HF_HOME", "NODE_USE_ENV_PROXY", "NO_PROXY", "IMAGEIO_FFMPEG_EXE", "SHOWTIME_HOME",
                    "SHOWTIME_ADDED_ENV", "SHOWTIME_USER_PATH"):
            self.assertNotIn(var, e)
        self.assertEqual(e["HTTPS_PROXY"], "http://proxy.example.test:3128")

    def test_rerun_command(self):
        rep = rp.parse(TRACE)
        red = rp.Redactor()
        self.assertEqual(rp.rerun_command(rep, None, red), "npx playwright test login.spec.js:6")
        self.assertEqual(rp.rerun_command(rep, ["npx", "playwright", "test", "a b.spec.ts"], red),
                         "npx playwright test 'a b.spec.ts'")
        self.assertEqual(rp.viewer_command(rep, "t.zip"), "npx playwright show-trace t.zip")

    @unittest.skipIf(os.name == "nt", "a POSIX executable script")
    def test_traces_only_where_the_runner_was_told(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-where-"))
        try:
            exe = fake_pytest(tmp / "bin", into_cwd=True)
            run = rp.run_and_find([str(exe), "tests"], tmp / "out", cwd=tmp)
            self.assertTrue((tmp / "elsewhere" / "t1" / "trace.zip").is_file())
            self.assertEqual((run["trace"], run["traces"]), (None, []))     # the working tree is not searched
            run = rp.run_and_find([str(fake_pytest(tmp / "bin2")), "tests"], tmp / "out2", cwd=tmp)
            self.assertEqual(Path(run["trace"]).parent.parent, tmp / "out2")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    @unittest.skipIf(os.name == "nt", "a pseudo-terminal")
    def test_the_command_never_reads_the_terminal(self):
        """In a terminal, Playwright's html reporter serves its report and waits for Ctrl+C: the command gets an
        empty stdin and PLAYWRIGHT_HTML_OPEN=never (unless the user set it, or PW_TEST_HTML_REPORT_OPEN)."""
        import pty
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-tty-"))
        exe = tmp / "probe"
        exe.write_text("#!%s\nimport json, os, sys\njson.dump({'tty': os.isatty(0), 'open': os.environ.get("
                       "'PLAYWRIGHT_HTML_OPEN')}, open(%r, 'w'))\n" % (sys.executable, str(tmp / "seen.json")),
                       encoding="utf-8")
        exe.chmod(0o755)
        master, slave = pty.openpty()
        saved = os.dup(0)
        try:
            os.dup2(slave, 0)                                     # showtime itself runs in a terminal
            seen = []
            for env in ({}, {"PLAYWRIGHT_HTML_OPEN": "always"}, {"PW_TEST_HTML_REPORT_OPEN": "on-failure"}):
                with mock.patch.dict(os.environ, env):
                    for k in {"PLAYWRIGHT_HTML_OPEN", "PW_TEST_HTML_REPORT_OPEN"} - set(env):
                        os.environ.pop(k, None)
                    rp.run_and_find([str(exe)], tmp / "out", cwd=tmp, timeout=30)
                seen.append(json.loads((tmp / "seen.json").read_text(encoding="utf-8")))
        finally:
            os.dup2(saved, 0)
            for fd in (saved, master, slave):
                os.close(fd)
            shutil.rmtree(str(tmp), ignore_errors=True)
        self.assertEqual(seen, [{"tty": False, "open": "never"}, {"tty": False, "open": "always"},
                                {"tty": False, "open": None}])


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-repro-cli-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def test_review_gate_then_yes(self):
        """The first call writes script.md and renders nothing; --yes renders from the script as edited, every
        line through the filter again."""
        out = self.tmp / "bug"
        cp = showtime("repro", TRACE, "--out", out, "--json", cwd=self.tmp)
        res = json.loads(cp.stdout)
        self.assertEqual((res["rendered"], res["failed_step"], res["masked_values"]), (False, 6, 3))
        self.assertIn("then rerun with --yes", res["next"])
        self.assertEqual(sorted(x.name for x in out.iterdir()), ["SHOWTIME.md", "job.json", "report.json",
                                                                 "script.md", "shots"])
        cp = showtime("repro", TRACE, "--out", self.tmp / "bug2", cwd=self.tmp)
        self.assertIn("read %s" % (self.tmp / "bug2" / "script.md"), cp.stdout)
        self.assertIn("then rerun with --yes", cp.stdout)
        self.assertIn(SCREENSHOTS, cp.stderr)
        script = out / "script.md"
        text = script.read_text(encoding="utf-8").replace(
            "show step5.caption: Click the 'Sign in' button",
            "show step5.caption: Click Sign in for acct-12345 with token=ERRTOK-7766-ab and /Users/someone/notes.txt")
        script.write_text("\n".join(x for x in text.splitlines() if not x.startswith("say step2:")), encoding="utf-8")
        cp = showtime("repro", "--yes", "--out", out, "--no-voice", "--no-render", "--redact", "acct-[0-9]+",
                      "--json", cwd=self.tmp)
        res = json.loads(cp.stdout)
        self.assertEqual(res["privacy"]["screenshots"], "as captured")
        steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
        self.assertEqual(steps["steps"][4]["caption"], "Click Sign in for %s with token=%s and notes.txt"
                         % (rp.MASK, rp.MASK))
        srt = (out / "repro.srt").read_text(encoding="utf-8")
        self.assertNotIn("Type into the Email field", srt)
        self.assertIn("Type into the Password field", srt)
        self.assertIn("6. **FAILED:** Expect the level-1 heading", (out / "repro.md").read_text(encoding="utf-8"))
        # the same trace with --yes again finds its job (the newest made from it) and renders nothing new to
        # a script; a trace never seen with --yes writes its script and stops
        lib = library_trace(self.tmp / "lib.zip", 3)
        cp = showtime("repro", lib, "--yes", "--no-voice", "--no-render", "--json", cwd=self.tmp)
        first = json.loads(cp.stdout)
        self.assertEqual(first["rendered"], False)
        cp = showtime("repro", lib, "--yes", "--no-voice", "--no-render", "--json", cwd=self.tmp)
        second = json.loads(cp.stdout)
        self.assertEqual(Path(second["job"]).resolve(), Path(first["job"]).resolve())
        self.assertTrue((Path(second["job"]) / "steps.json").is_file())

    def test_every_file_of_the_job(self):
        """No file of the job holds the trace's machine paths or a planted secret, and no file but the ledger
        holds a path of this machine: report.json, script.md, steps.json, repro.md, repro.srt, project/ included."""
        trace = attack_trace(self.tmp / "attack.zip")
        out = self.tmp / "job"
        showtime("repro", trace, "--out", out, "--redact", "Mot de passe", cwd=self.tmp)
        showtime("repro", "--yes", "--out", out, "--no-voice", "--no-render", cwd=self.tmp)
        for name in ("steps.json", "repro.md", "repro.srt", "report.json", "script.md", "project/index.html",
                     "project/repro.json", "project/showtime.json"):
            self.assertTrue((out / name).is_file(), name)
        assert_clean(self, out, ATTACK + ("Mot de passe",),
                     machine=(str(Path.home()), str(self.tmp), str(self.tmp.resolve()), str(SKILL)))
        fixture_job = self.tmp / "fx"
        showtime("repro", TRACE, "--out", fixture_job, cwd=self.tmp)
        showtime("repro", "--yes", "--out", fixture_job, "--no-voice", "--no-render", cwd=self.tmp)
        assert_clean(self, fixture_job, SECRETS + ("/home/user",), machine=(str(Path.home()), str(self.tmp.resolve())))
        report = json.loads((fixture_job / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["viewer"], "npx playwright show-trace trace.zip")     # outside the folder: its name

    def test_errors(self):
        cp = showtime("repro", check=False, cwd=self.tmp)
        self.assertIn("no trace or test command given", cp.stderr)
        cp = showtime("repro", self.tmp / "missing.zip", check=False, cwd=self.tmp)
        self.assertIn("trace not found", cp.stderr)
        library_trace(self.tmp / "ok.zip", 3, fail=False)
        cp = showtime("repro", self.tmp / "ok.zip", check=False, cwd=self.tmp)
        self.assertIn("the trace records no failure", cp.stderr)
        cp = showtime("repro", TRACE, "--redact", "(", check=False, cwd=self.tmp)
        self.assertIn("not a valid regular expression", cp.stderr)
        cp = showtime("repro", "--", sys.executable, "-c", "print('ok')", check=False, cwd=self.tmp)
        self.assertIn("the command wrote no trace.zip (exit code 0)", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = showtime("repro", "--timeout", "2", "--", sys.executable, "-c", "import time; time.sleep(60)",
                      check=False, cwd=self.tmp, timeout=60)
        self.assertIn("ran longer than 2 s and was stopped", cp.stderr)
        self.assertFalse((self.tmp / "showtime-out").exists())             # a failed run leaves nothing behind

    @unittest.skipIf(os.name == "nt", "a POSIX executable script")
    def test_a_single_script_after_dashes_is_a_command(self):
        script = self.tmp / "e2e.sh"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        cp = showtime("repro", "--", "./e2e.sh", check=False, cwd=self.tmp)
        self.assertIn("the command wrote no trace.zip", cp.stderr)
        self.assertNotIn("not a zip file", cp.stderr)

    @unittest.skipIf(os.name == "nt", "a POSIX executable script")
    def test_command_traces_are_deleted_unless_kept(self):
        """A run's raw traces (they hold what was typed) never stay in the job, unless --keep-trace."""
        exe = fake_pytest(self.tmp / "bin")
        cp = showtime("repro", "--json", "--out", self.tmp / "a", "--", exe, "tests", cwd=self.tmp)
        res = json.loads(cp.stdout)
        self.assertEqual((res["run"]["runner"], res["privacy"]["raw_trace"]), ("pytest", "deleted"))
        self.assertEqual(list((self.tmp / "a").rglob("trace.zip")), [])
        self.assertEqual(list(Path(tempfile.gettempdir()).glob("showtime-repro-*")), [])
        assert_clean(self, self.tmp / "a", SECRETS)
        cp = showtime("repro", "--json", "--keep-trace", "--out", self.tmp / "b", "--", exe, "tests", cwd=self.tmp)
        self.assertEqual(len(list((self.tmp / "b" / "work" / "test-results").rglob("trace.zip"))), 1)
        self.assertIn("show-trace", json.loads((self.tmp / "b" / "report.json").read_text(encoding="utf-8"))["viewer"])


@unittest.skipIf(FAST, "--fast (runs Playwright's test runner)")
@unittest.skipIf(os.name == "nt", "a pseudo-terminal")
@unittest.skipUnless(bool(NODE) and (NM / "playwright" / "cli.js").is_file(), "needs Node and showtime setup's Playwright")
class TestWithPlaywright(unittest.TestCase):
    def test_html_reporter_in_a_terminal_does_not_wait(self):
        """`npm init playwright`'s config (reporter: 'html'), run from a terminal by a person (no coding agent
        variable): the reporter would serve its report until Ctrl+C. No browser: the test fails on expect(1)."""
        import pty
        import time
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-html-"))
        master, slave = pty.openpty()
        try:
            (tmp / "playwright.config.js").write_text("module.exports = { reporter: 'html' };\n", encoding="utf-8")
            (tmp / "a.spec.js").write_text(
                "const { test, expect } = require(%s);\ntest('one is two', async () => {\n  expect(1).toBe(2);\n});\n"
                % json.dumps(str(NM / "playwright" / "test")), encoding="utf-8")
            env = {k: v for k, v in ENV.items() if k not in ("CLAUDECODE", "COPILOT_CLI", "CI", "PLAYWRIGHT_HTML_OPEN",
                                                             "PW_TEST_HTML_REPORT_OPEN")}
            t = time.time()
            cp = showtime("repro", "--out", tmp / "job", "--timeout", "60", "--json", "--", NODE,
                          NM / "playwright" / "cli.js", "test", "a.spec.js", env=env, cwd=tmp, timeout=200, stdin=slave)
            self.assertLess(time.time() - t, 45, cp.stderr[-2000:])
            self.assertNotIn("Serving HTML report", cp.stderr)
            res = json.loads(cp.stdout)
            self.assertEqual((res["run"]["runner"], res["run"]["failing"], res["rendered"]), ("playwright", 1, False))
            self.assertTrue((tmp / "job" / "script.md").is_file())
        finally:
            os.close(master)
            os.close(slave)
            shutil.rmtree(str(tmp), ignore_errors=True)


@unittest.skipIf(FAST, "--fast (runs a browser)")
@unittest.skipUnless(READY, "needs Node, showtime setup's Playwright and its Chromium")
class TestWithBrowser(unittest.TestCase):
    """A real run: the fixture test with tracing on, then the film rendered and checked."""

    def test_command_writes_a_real_trace(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-run-"))
        try:
            shutil.copytree(str(FIX / "app"), str(tmp / "app"))
            spec = (FIX / "login.spec.js").read_text(encoding="utf-8")
            # a project would have playwright in its own node_modules; this one uses showtime's
            spec = spec.replace("require('playwright/test')", "require(%s)" % json.dumps(str(NM / "playwright" / "test")))
            (tmp / "login.spec.js").write_text(spec, encoding="utf-8")
            # showtime's browsers, spelled the way a user's own setting would be (user_env drops showtime's own)
            env = dict(ENV, PLAYWRIGHT_BROWSERS_PATH=str(BROWSERS) + os.sep)
            cp = showtime("repro", "--out", tmp / "job", "--json", "--",
                          NODE, NM / "playwright" / "cli.js", "test", "login.spec.js", "--reporter", "line",
                          env=env, cwd=tmp, timeout=240)
            res = json.loads(cp.stdout)
            self.assertEqual((res["run"]["runner"], res["run"]["failing"], res["rendered"]), ("playwright", 1, False))
            self.assertNotEqual(res["run"]["rc"], 0)
            self.assertEqual(list((tmp / "job").rglob("trace.zip")), [])              # the raw trace is gone
            fresh = json.loads((tmp / "job" / "report.json").read_text(encoding="utf-8"))["report"]
            fixed = rp.parse(TRACE)
            self.assertEqual([s["caption"] for s in fresh["steps"]], [s["caption"] for s in fixed["steps"]])
            self.assertEqual(fresh["failure"]["source"], fixed["failure"]["source"])        # the trace's own source
            self.assertEqual(fresh["test"], fixed["test"])
            showtime("repro", "--yes", "--out", tmp / "job", "--no-voice", "--no-render", env=env, cwd=tmp)
            steps = json.loads((tmp / "job" / "steps.json").read_text(encoding="utf-8"))
            self.assertIn("cli.js test login.spec.js", steps["rerun"])
            assert_clean(self, tmp / "job", SECRETS, machine=(str(Path.home()), str(tmp.resolve())))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    @needs_listen
    def test_end_to_end_preview(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-repro-e2e-"))
        try:
            showtime("repro", TRACE, "--out", tmp / "job", cwd=tmp)
            cp = showtime("repro", "--yes", "--out", tmp / "job", "--no-voice", "--preview", "--json",
                          "--music", "minimal-pulse", check=False,
                          cwd=tmp, timeout=900)
            skip_if_listen_refused(cp)
            self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
            res = json.loads(cp.stdout)
            job = tmp / "job"
            for name in ("repro.mp4", "repro.srt", "repro.poster.jpg", "steps.json", "repro.md"):
                self.assertTrue((job / name).is_file(), name)
            self.assertIn(res["qa"]["verdict"], ("PASS", "WARN"), res["qa"])
            from st import ff
            info = ff.probe(job / "repro.mp4")
            self.assertAlmostEqual(float(info["duration"]), res["duration"], delta=0.5)
            self.assertFalse((job / "repro.work").exists())                               # removed after qa
            self.assertFalse((job / "project" / "work").exists())
            data = json.loads((job / "job.json").read_text(encoding="utf-8"))
            self.assertIn("repro.mp4", json.dumps(data.get("outputs")))
            assert_clean(self, job, SECRETS + ("/home/user",), machine=(str(Path.home()), str(tmp.resolve())))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
