#!/usr/bin/env python3
"""`showtime pr-video` (lib/st/pr_video.py, cli_release.py): a pull request -> a video for its description.

Pure Python, no browser and no network: the diff parser, secret masking (the diff, the title and the
description; nothing secret reaches the page or the project files), the description parser (PR templates:
comments, checklists, test plans), the hunk picker, the plan and the page (every word traceable to the PR or a
flag), the gh path with a stand-in gh on PATH (capped file lists read with a paginated gh api call), the no-gh
fallbacks (--diff/--body/--title, --base on a local repo) and their errors, and the 10 MB GitHub copy (the
export is stubbed). The render itself is covered on the box (check + render + qa).

usage: python tests/test_pr_video.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import html
import json
import os
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
FIX = TESTS_DIR / "fixtures" / "pr"
sys.path.insert(0, str(SKILL / "lib"))

from st import pr_video as pv  # noqa: E402
from st.common import ShowtimeError  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
DIFF = (FIX / "acme-482.diff").read_text(encoding="utf-8")
PR = json.loads((FIX / "acme-482.json").read_text(encoding="utf-8"))
SECRETS = ("notarealkey", "AKIAIOSFODNN7EXAMPLE", "not-a-real-token")

# the cli/cli template's shape (comments, a Description section, a test section holding only an uploaded
# video, reviewer notes, an authorship checklist)
TEMPLATE_BODY = """<!--
Thank you for contributing!
-->

<!-- List related issues here. -->

Fixes #14521

### Description

<!--
What's the problem?
-->

`gh repo set-default --unset` required a repository argument when stdin was not interactive. The command does not use one.

### How did you test this change?

https://github.com/user-attachments/assets/ff8cfc24-563a-4c92-a1b7-e1e50763b6b0

### Notes for reviewers

Start with the validation condition in `NewCmdSetDefault`.

### Authorship and follow-up

Who wrote this:

- [ ] A human wrote it.
- [x] An agent wrote it.
"""


def showtime(*args, check=True, env=None, cwd=None, stdin=None, timeout=120):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def parsed():
    files = pv.parse_diff(DIFF)
    masked = pv.mask_diff(files)
    return files, masked


def with_gh(gh) -> dict:
    """The environment with SHOWTIME_GH pointing at a stand-in gh (or at a file that does not exist: no gh)."""
    return dict(ENV, SHOWTIME_GH=str(gh))


def fake_gh(bin_dir: Path, *, view: str = "", diff: str = "", api: str = "", fail: str = "") -> Path:
    """A stand-in gh: prints `view` for pr view, `diff` for pr diff, `api` for api; logs its arguments."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    data = bin_dir / "gh-data.json"
    data.write_text(json.dumps({"view": view, "diff": diff, "api": api, "fail": fail}), encoding="utf-8")
    script = bin_dir / "gh"
    script.write_text(
        "#!%s\nimport json, sys\nd = json.load(open(%r))\nopen(%r, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if d['fail']:\n    sys.stderr.write(d['fail'])\n    sys.exit(1)\n"
        "cmd = sys.argv[1:3]\n"
        "out = d['view'] if cmd == ['pr', 'view'] else d['diff'] if cmd == ['pr', 'diff'] else "
        "d['api'] if sys.argv[1] == 'api' else ''\nsys.stdout.write(out)\n"
        % (sys.executable, str(data), str(bin_dir / "gh-calls.log")), encoding="utf-8")
    script.chmod(0o755)
    return script


class FakeApi:
    """A local stand-in for api.github.com: {path: (status, body[, headers])}; "<path>#diff" answers the diff
    media type. Records each request's headers."""

    def __init__(self, routes):
        import http.server
        import threading
        self.seen = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(dict(self.headers))
                key = self.path + ("#diff" if "diff" in (self.headers.get("Accept") or "") else "")
                status, body, *hdrs = routes.get(key, (404, '{"message": "Not Found"}'))
                self.send_response(status)
                for k, v in (hdrs[0] if hdrs else {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestDiff(unittest.TestCase):
    def test_parse_matches_gh_counts(self):
        files = pv.parse_diff(DIFF)
        got = {f["path"]: (f["additions"], f["deletions"]) for f in files}
        want = {f["path"]: (f["additions"], f["deletions"]) for f in PR["files"]}
        self.assertEqual(got, want)
        self.assertEqual(files[0]["status"], "added")
        export = next(f for f in files if f["path"] == "src/acme/export.py")
        self.assertEqual(export["hunks"][0]["context"], "def export(project, out, *, max_mb=None):")
        self.assertEqual(export["hunks"][0]["new_start"], 40)

    def test_plain_unified_diff(self):
        files = pv.parse_diff("--- a/x.py\t2026-01-01\n+++ b/x.py\t2026-01-02\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n"
                              "--- a/y.py\n+++ b/y.py\n@@ -3 +3 @@\n-c\n+d\n")
        self.assertEqual([(f["path"], f["additions"], f["deletions"]) for f in files], [("x.py", 1, 1), ("y.py", 1, 1)])


class TestSecrets(unittest.TestCase):
    def test_fixture_secrets_are_masked(self):
        files, masked = parsed()
        self.assertEqual(masked, [{"path": "config/.env.example", "lines": 2}, {"path": "src/acme/client.py", "lines": 2}])
        blob = json.dumps(files)
        for s in ("notarealkey", "AKIAIOSFODNN7EXAMPLE", "not-a-real-token"):
            self.assertNotIn(s, blob)
        client = next(f for f in files if f["path"] == "src/acme/client.py")
        self.assertIn(["+", 'API_KEY = "%s"' % pv.MASK], client["hunks"][0]["lines"])
        self.assertIn(["+", 'DEFAULT_REGION = "eu-west-1"'], client["hunks"][0]["lines"])   # not a secret
        env = next(f for f in files if f["path"] == "config/.env.example")
        self.assertEqual(env["hunks"][0]["lines"][0], ["+", "# copy to .env"])

    def test_token_shapes(self):
        tok = "ghp_" + "a1B2" * 9
        cases = {
            "headers = {'Authorization': 'token %s'}" % tok: True,
            'password: "correct-horse-battery"': True,
            "DATABASE_URL=postgres://admin:s3cret@db.internal/app": True,
            "export STRIPE_SECRET=sk_live_" + "0" * 24: True,
            "SECRET_KEY=8f2a9c1e7b3d4a6f": True,
            "token = get_token(session)": False,
            "password_field = forms.CharField()": False,
            "def rotate_secret(name: str) -> None:": False,
            "MAX_TOKENS = 4096": False,
        }
        for line, hit in cases.items():
            out, did = pv.mask_line(line)
            self.assertEqual(did, hit, line)
            if hit:
                self.assertNotIn("s3cret", out)
                self.assertNotIn(tok, out)
                self.assertNotIn("correct-horse", out)

    def test_private_key_block_and_description(self):
        body = "Rotates the key.\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----\nDone."
        out, n = pv.mask_text(body)
        self.assertEqual(n, 4)
        self.assertNotIn("MIIEow", out)
        self.assertTrue(out.startswith("Rotates the key.") and out.endswith("Done."))
        self.assertTrue(pv.is_secret_file("deploy/.env.production"))
        self.assertTrue(pv.is_secret_file("keys/server.pem"))
        self.assertFalse(pv.is_secret_file("src/environment.py"))


class TestBodyPlanPage(unittest.TestCase):
    def test_description_sections(self):
        b = pv.parse_body(PR["body"])
        self.assertEqual(b["summary"], [
            "Exports can now be capped to a size, so a video fits where it is going.",
            "The bitrate is computed from the duration instead of failing.",
            "`acme export --max-mb N` picks a bitrate that lands under N MB",
            "The cap leaves 5% headroom for the container"])
        self.assertEqual(b["impact"], {"title": "User-facing changes",
                                       "lines": ["`acme export --max-mb 10` makes a file you can attach to a GitHub PR"]})
        self.assertEqual(b["refs"], ["Fixes #470"])

    def test_template_chrome_is_left_out(self):
        b = pv.parse_body(TEMPLATE_BODY)
        self.assertEqual(b["summary"], [
            "`gh repo set-default --unset` required a repository argument when stdin was not interactive.",
            "The command does not use one."])
        self.assertIsNone(b["impact"])
        self.assertEqual(b["refs"], ["Fixes #14521"])

    def test_hunks_skip_lockfiles_and_secrets(self):
        files, _m = parsed()
        hs = pv.pick_hunks(files)
        self.assertEqual([h["path"] for h in hs], ["src/acme/export.py"])
        h = hs[0]
        self.assertEqual(h["lines"][0], ["-", "if max_mb and size > max_mb:"])            # dedented; the context
        self.assertEqual(h["lines"][1], ["-", "    raise ExportError(\"too big\")"])      # line did not fit
        cols, rows = pv.CODE_FIT["16:9"]
        self.assertLessEqual(sum(pv._rows(x, cols) for _t, x in h["lines"]), rows)
        self.assertEqual(h["hidden"], 4)                         # a line that did not fit and the second block
        for f in files:
            if f["path"] in ("package-lock.json", "config/.env.example"):
                self.assertEqual(pv.hunk_score(f, f["hunks"][0]), 0.0)
        tall = pv.pick_hunks(files, aspect="9:16")[0]
        cols, rows = pv.CODE_FIT["9:16"]
        self.assertLessEqual(sum(pv._rows(x, cols) for _t, x in tall["lines"]), rows)

    def test_plan_scales_with_the_pr(self):
        files, _m = parsed()
        meta = pv.normalize_meta(PR)
        stats = pv.file_stats(files, meta["files"])
        body = pv.parse_body(meta["body"])
        p = pv.plan(meta, body, stats, pv.pick_hunks(files))
        self.assertEqual(p["budget"], pv.length_budget(6, 24))
        self.assertEqual([s["id"] for s in p["scenes"]], ["hook", "sum1", "files", "diff1", "end"])
        self.assertEqual((p["shown"], p["more"]), (1, 3))                               # a small PR keeps one line
        self.assertLessEqual(sum(s["dur"] for s in p["scenes"]), p["budget"])
        self.assertEqual((p["name"], p["version"], p["files"], p["additions"], p["deletions"]),
                         ("acme/tool", "#482", 6, 20, 4))
        files_sc = p["scenes"][2]
        self.assertIn("tests/test_export.py", [r.get("path") for r in files_sc["rows"]])  # tagged in the tree
        self.assertEqual(files_sc["tests"], [])                                         # so no extra line
        tall = pv.plan(meta, body, stats, pv.pick_hunks(files, aspect="9:16"), aspect="9:16")
        self.assertEqual(tall["scenes"][2]["tests"], ["test_export.py"])               # tall frames hide the tag
        sum1 = p["scenes"][1]
        self.assertAlmostEqual(sum1["dur"], max(2.0, pv.LEAD + pv.ENTER + pv.read_time(sum1["text"]) + pv.OUT), 2)
        big = pv.plan(dict(meta, changed_files=120, additions=4000, deletions=900), body, stats, pv.pick_hunks(files))
        self.assertGreater(big["budget"], 40)
        self.assertEqual(big["shown"], 4)                                               # a big PR has room for all
        self.assertLessEqual(sum(s["dur"] for s in big["scenes"]), 45.0)

    def test_length_budget_and_holds(self):
        self.assertTrue(16 <= pv.length_budget(2, 18) <= 20)
        self.assertEqual(pv.length_budget(400, 20000), 45.0)
        self.assertEqual(pv.read_time("ok"), 1.0)
        self.assertAlmostEqual(pv.read_time("x" * 34), 2.3)                            # 17 characters a second
        self.assertAlmostEqual(pv.read_time("a b c d e f g h i"), 3.3)                  # 3 words a second

    def test_long_sentences_become_phrases(self):
        s = "`gh repo set-default --unset` incorrectly required a repository argument when stdin was not interactive."
        self.assertEqual(pv.chunks(s), ["`gh repo set-default --unset` incorrectly required a repository argument",
                                        "when stdin was not interactive."])
        s2 = "This exempts `--unset` from the non-interactive repository requirement, matching the behavior for `--view`."
        self.assertEqual(pv.chunks(s2)[0], "This exempts `--unset` from the non-interactive repository requirement,")
        self.assertEqual(pv.chunks("Short enough."), ["Short enough."])
        for text in (s, s2, "word " * 60):
            parts = pv.chunks(text.strip())
            self.assertEqual(" ".join(parts), text.strip())                           # every word, in order
            self.assertTrue(all(len(x) <= pv.CHUNK_CHARS[1] for x in parts))
        self.assertEqual(pv.chunks("`" + "a " * 60 + "`"), ["`" + "a " * 60 + "`"])    # never inside a code span

    def test_tree_rows(self):
        stats = [{"path": "packages/core/src/deep/folder/name/here/file%d.py" % i, "additions": i, "deletions": 0,
                  "test": False} for i in range(9)]
        rows, more = pv.tree_rows(stats, max_files=6)
        self.assertEqual(more, 3)
        self.assertTrue(rows[0]["dir"].startswith("\u2026"))
        self.assertLessEqual(len(rows[0]["dir"]), 34)
        self.assertEqual([r["name"] for r in rows[1:]], ["file%d.py" % i for i in range(3, 9)])
        spread = [{"path": "d%d/f.py" % i, "additions": 10 - i, "deletions": 0, "test": False} for i in range(6)]
        rows, more = pv.tree_rows(spread, max_files=6, max_rows=7)                     # 3 files + their 3 folders
        self.assertEqual((len(rows), more), (6, 3))

    def test_page_says_only_what_the_pr_says(self):
        files, _m = parsed()
        meta = pv.normalize_meta(PR)
        p = pv.plan(meta, pv.parse_body(meta["body"]), pv.file_stats(files, meta["files"]), pv.pick_hunks(files))
        page = pv.build_page(p)
        body = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", body))
        words = set(re.findall(r"[A-Za-z]{4,}", text))
        allowed = set(re.findall(r"[A-Za-z]{4,}", "\n".join([DIFF, PR["title"], PR["body"], json.dumps(PR)])))
        allowed |= {"Pull", "request", "files", "changed", "Tests", "test", "more", "description", "Thanks", "line",
                    "lines"}
        self.assertEqual(sorted(words - allowed), [])
        for s in SECRETS:
            self.assertNotIn(s, page)
        self.assertIn("Cap <code class=\"nw\">acme export</code> at a size", page)
        self.assertIn("User-facing changes", page)
        self.assertIn("github.com/acme/tool/pull/482", page)
        self.assertIn('data-start="#hook"', page)
        self.assertNotIn("grain", page)                                                 # no film grain: smaller files

    def test_capped_file_list(self):
        self.assertFalse(pv.files_look_capped(pv.normalize_meta(PR)))
        big = dict(PR, files=[{"path": "f%d" % i, "additions": 1, "deletions": 0} for i in range(100)], changedFiles=150)
        self.assertTrue(pv.files_look_capped(pv.normalize_meta(big)))
        pages = json.dumps([{"filename": "a", "additions": 1, "deletions": 2}]) + "\n" + \
            json.dumps([{"filename": "b", "additions": 3, "deletions": 0}])
        self.assertEqual([f["filename"] for f in pv.parse_json_stream(pages)], ["a", "b"])
        rest = pv.normalize_meta({"html_url": "https://github.com/o/r/pull/9", "user": {"login": "bob"},
                                  "head": {"ref": "x"}, "changed_files": 3, "number": 9, "title": "T"})
        self.assertEqual((rest["repo"], rest["number"], rest["author"], rest["head"], rest["changed_files"]),
                         ("o/r", 9, "bob", "x", 3))


class TestGithubCopy(unittest.TestCase):
    def test_under_the_cap(self):
        calls = []

        def export(src, targets, out_dir):
            calls.append((src, targets, out_dir))
            return {"exports": [{"output": os.path.join(out_dir, "pr-482.github.mp4"), "size_bytes": 6_200_000,
                                 "width": 1920, "height": 1080, "duration": 31.0}]}
        r = pv.deliver_github(Path("/x/pr-482.mp4"), Path("/x"), export=export)
        self.assertEqual(calls, [(str(Path("/x/pr-482.mp4")), "github", str(Path("/x")))])
        self.assertEqual((Path(r["output"]).name, r["size_mb"]), ("pr-482.github.mp4", 6.2))
        md = pv.markdown_line("pr-482.github.mp4", 31.0, r["size_mb"])
        self.assertIn("in 31 s", md)
        self.assertIn("drag pr-482.github.mp4 (6.2 MB)", md)

    def test_over_the_cap_is_an_error(self):
        def export(src, targets, out_dir):
            return {"exports": [{"output": "/x/pr-1.github.mp4", "size_bytes": 10_400_000}]}
        with self.assertRaises(ShowtimeError) as cm:
            pv.deliver_github(Path("/x/pr-1.mp4"), Path("/x"), export=export)
        self.assertIn("over the 10 MB attachment limit", str(cm.exception))

    def test_github_target_is_capped_at_10_mb(self):
        from st.deliver import exports
        self.assertEqual(exports.TARGETS["github"].max_mb, pv.GITHUB_MAX_MB)
        self.assertLess(exports.cap_bitrate_kbps(10, 45, 160) * 45 + 160 * 45, 10e6 * 8 / 1000)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-pr-cli-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def no_secret_anywhere(self, folder: Path):
        for f in folder.rglob("*"):
            if f.is_file():
                data = f.read_text(encoding="utf-8", errors="replace")
                for s in SECRETS:
                    self.assertNotIn(s, data, "%s holds a secret" % f)

    def test_without_gh_and_no_repo_is_a_clear_error(self):
        env = dict(with_gh(self.tmp / "no-such-gh"), SHOWTIME_GITHUB_API="http://127.0.0.1:9")
        cp = showtime("pr-video", "482", "--out", self.tmp / "o", check=False, env=env, cwd=self.tmp)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("gh (the GitHub CLI) is not installed", cp.stderr)
        self.assertIn("no github.com repository to read it from without gh", cp.stderr)
        self.assertIn("--diff pr.diff --body pr.md --title", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = showtime("pr-video", "--out", self.tmp / "o", check=False, env=env)
        self.assertIn("no pull request given", cp.stderr)
        cp = showtime("pr-video", "nope", check=False, env=env)
        self.assertIn("is not a PR number or URL", cp.stderr)

    @unittest.skipIf(os.name == "nt", "the stand-in gh is a POSIX script")
    def test_gh_not_signed_in(self):
        bin_dir = self.tmp / "bin"
        env = with_gh(fake_gh(bin_dir, fail="To get started with GitHub CLI, please run:  gh auth login\n"))
        cp = showtime("pr-video", "482", check=False, env=env, cwd=self.tmp)
        self.assertIn("gh is not signed in", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)

    def test_public_pr_from_the_rest_api(self):
        rest = {"number": 482, "title": PR["title"], "body": PR["body"], "user": {"login": "alice"},
                "html_url": PR["url"], "additions": 20, "deletions": 4, "changed_files": 6, "commits": 2,
                "head": {"ref": "alice/export-cap"}, "base": {"ref": "main"}}
        with FakeApi({"/repos/acme/tool/pulls/482": (200, json.dumps(rest)),
                      "/repos/acme/tool/pulls/482#diff": (200, DIFF)}) as api:
            env = dict(with_gh(self.tmp / "no-such-gh"), SHOWTIME_GITHUB_API=api.url)
            cp = showtime("pr-video", PR["url"], "--out", self.tmp / "a", "--no-render", env=env)
            self.assertIn("reading the public PR from GitHub's REST API", cp.stdout)
            self.assertIn("masked 4 secret-looking lines", cp.stdout)
            page = (self.tmp / "a" / "project" / "index.html").read_text(encoding="utf-8")
            self.assertIn("#482 \u00b7 @alice", page)
            self.assertIn("6 files changed", page)
            self.no_secret_anywhere(self.tmp / "a")
            self.assertEqual([h.get("Accept") for h in api.seen],
                             ["application/vnd.github+json", "application/vnd.github.diff"])
            self.assertFalse(any("Authorization" in h for h in api.seen))              # no token is ever sent

    def test_rest_api_errors_are_clear(self):
        env0 = with_gh(self.tmp / "no-such-gh")
        with FakeApi({"/repos/acme/secret/pulls/1": (404, '{"message": "Not Found"}')}) as api:
            cp = showtime("pr-video", "https://github.com/acme/secret/pull/1", "--no-render", check=False,
                          env=dict(env0, SHOWTIME_GITHUB_API=api.url), cwd=self.tmp)
            self.assertIn("GitHub has no public pull request at acme/secret/pulls/1", cp.stderr)
            self.assertIn("private", cp.stderr)
        limit = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"}
        with FakeApi({"/repos/acme/tool/pulls/2": (403, '{"message": "API rate limit exceeded"}', limit)}) as api:
            cp = showtime("pr-video", "2", "--repo", "acme/tool", "--no-render", check=False,
                          env=dict(env0, SHOWTIME_GITHUB_API=api.url), cwd=self.tmp)
            self.assertIn("rate limit for requests without sign-in (60 an hour) is used up", cp.stderr)
            self.assertIn("gh auth login", cp.stderr)
        rest = {"number": 3, "title": "Huge", "body": "", "user": {"login": "bob"}, "changed_files": 150,
                "html_url": "https://github.com/acme/tool/pull/3", "additions": 9000, "deletions": 10}
        pages = [[{"filename": "src/f%03d.py" % i, "additions": 60, "deletions": 0} for i in range(k, k + n)]
                 for k, n in ((0, 100), (100, 50))]
        with FakeApi({"/repos/acme/tool/pulls/3": (200, json.dumps(rest)),
                      "/repos/acme/tool/pulls/3#diff": (406, '{"message": "diff too large"}'),
                      "/repos/acme/tool/pulls/3/files?per_page=100&page=1": (200, json.dumps(pages[0])),
                      "/repos/acme/tool/pulls/3/files?per_page=100&page=2": (200, json.dumps(pages[1]))}) as api:
            cp = showtime("pr-video", "3", "--repo", "acme/tool", "--out", self.tmp / "h", "--no-render", "--json",
                          env=dict(env0, SHOWTIME_GITHUB_API=api.url), cwd=self.tmp)
            res = json.loads(cp.stdout)
            self.assertEqual((res["files"], res["hunks"]), (150, 0))
            self.assertIn("too big to show in full: GitHub would not send its diff (HTTP 406)", res["notes"][0])

    def test_work_folder_removed_after_export(self):
        video = self.tmp / "pr-1.mp4"
        work = self.tmp / "pr-1.work"
        (work / "audio").mkdir(parents=True)
        (work / "render.json").write_text("{}", encoding="utf-8")
        self.assertEqual(pv.remove_work(video), work)
        self.assertFalse(work.exists())
        other = self.tmp / "pr-2.work"
        other.mkdir()
        self.assertIsNone(pv.remove_work(self.tmp / "pr-2.mp4"))                     # not a render's folder: kept
        self.assertTrue(other.exists())

    def test_fallback_files(self):
        body = self.tmp / "pr.md"
        body.write_text(PR["body"], encoding="utf-8")
        out = self.tmp / "o"
        cp = showtime("pr-video", "482", "--diff", FIX / "acme-482.diff", "--body", body, "--title", PR["title"],
                      "--repo", "acme/tool", "--author", "@alice", "--out", out, "--no-render")
        self.assertIn("masked 4 secret-looking lines (config/.env.example, src/acme/client.py)", cp.stdout)
        self.assertIn("next: showtime check", cp.stdout)
        page = (out / "project" / "index.html").read_text(encoding="utf-8")
        self.assertIn("#482 \u00b7 @alice", page)
        self.assertIn("github.com/acme/tool/pull/482", page)
        cfg = json.loads((out / "project" / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["title"], cfg["width"], cfg["poster"], cfg["render"]), ("acme/tool #482", 1920, 0,
                                                                                    {"crf": 22}))
        self.no_secret_anywhere(out)
        cp = showtime("pr-video", "482", "--diff", FIX / "acme-482.diff", "--title", "t", "--out", out,
                      "--no-render", check=False)
        self.assertIn("is not empty", cp.stderr)
        stdin = showtime("pr-video", "--diff", "-", "--title", "Square", "--repo", "acme/tool", "--aspect", "1:1",
                         "--out", self.tmp / "sq", "--no-render", "--json", stdin=DIFF)
        res = json.loads(stdin.stdout)
        self.assertEqual(res["files"], 6)
        cfg = json.loads((self.tmp / "sq" / "project" / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["width"], cfg["height"]), (1080, 1080))

    def test_never_inherits_the_job_of_the_current_folder(self):
        # dogfood 0.4.0: run inside showtime-out/<job>/..., the render was logged into that unrelated job
        from st.job import ledger
        other = self.tmp / "showtime-out" / "launch-20261005-101500"
        (other / "work" / "notes").mkdir(parents=True)
        (other / "job.json").write_text(json.dumps({"schema": 1, "slug": "launch", "history": []}), encoding="utf-8")
        before = (other / "job.json").read_bytes()
        flags = ["--diff", FIX / "acme-482.diff", "--title", PR["title"], "--repo", "acme/tool", "--no-render"]
        cp = showtime("pr-video", "482", *flags, cwd=other / "work" / "notes")
        out = self.tmp / "showtime-out" / "pr-482-video"                       # beside the job, not inside it
        self.assertIn("inside job launch-20261005-101500; writing beside it", cp.stdout)
        self.assertEqual([p.name for p in other.rglob("pr-*")], [])
        data = json.loads((out / "job.json").read_text(encoding="utf-8"))
        self.assertEqual((data["slug"], data["pointers"]["project"]), ("pr-482", str((out / "project").resolve())))
        # render logs into the nearest job.json above its output (enclosingJob): now pr-video's own job
        self.assertEqual(ledger.enclosing_job(out / "pr-482.mp4"), out.resolve())
        # an --out inside the other job is still its own job
        res = json.loads(showtime("pr-video", "482", *flags, "--out", "pr", "--json", cwd=other / "work").stdout)
        self.assertEqual(res["job"], str((other / "work" / "pr").resolve()))
        self.assertEqual(ledger.enclosing_job(other / "work" / "pr" / "pr-482.mp4"), (other / "work" / "pr").resolve())
        self.assertEqual((other / "job.json").read_bytes(), before)
        # an --out that is a job folder is used as it is (no second ledger written over it)
        res = json.loads(showtime("pr-video", "482", *flags, "--out", other, "--json", cwd=self.tmp).stdout)
        self.assertEqual(res["job"], str(other.resolve()))
        self.assertEqual((other / "job.json").read_bytes(), before)

    def test_base_on_a_local_repo(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        repo = self.tmp / "repo"
        repo.mkdir()
        g = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]

        def run(*a):
            subprocess.run(list(a), cwd=str(repo), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        run("git", "init", "-q", "-b", "main")
        (repo / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
        run(*g, "add", ".")
        run(*g, "commit", "-q", "-m", "first")
        run("git", "checkout", "-q", "-b", "feature/wave")
        (repo / "app.py").write_text("def greet(name):\n    return 'hi ' + name\n", encoding="utf-8")
        run(*g, "commit", "-q", "-am", "Greet people by name", "-m", "The greeting now says who it is for.")
        cp = showtime("pr-video", "--base", "main", "--no-render", "--json", cwd=repo)
        res = json.loads(cp.stdout)
        self.assertEqual(Path(res["out"]).name, "pr-feature-wave-video")
        page = (repo / "pr-feature-wave-video" / "project" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Greet people by name", page)
        self.assertIn("The greeting now says who it is for.", page)
        self.assertIn("return &#x27;hi &#x27; + name", page)
        (repo / "app.py").write_text("def greet(name, loud=False):\n    return 'hi ' + name\n", encoding="utf-8")
        run(*g, "commit", "-q", "-am", "Loud")
        cp = showtime("pr-video", "--base", "main", "--no-render", "--out", "x", check=False, cwd=repo)
        self.assertIn("--title is needed", cp.stderr)

    @unittest.skipIf(os.name == "nt", "the stand-in gh is a POSIX script")
    def test_gh_path_and_a_capped_file_list(self):
        bin_dir = self.tmp / "bin"
        env = with_gh(fake_gh(bin_dir, view=json.dumps(PR), diff=DIFF))
        cp = showtime("pr-video", "https://github.com/acme/tool/pull/482", "--out", self.tmp / "a", "--no-render",
                      "--json", env=env)
        res = json.loads(cp.stdout)
        self.assertEqual((res["title"], res["files"], len(res["masked"])), ("acme/tool #482", 6, 2))
        calls = [json.loads(x) for x in (bin_dir / "gh-calls.log").read_text().splitlines()]
        self.assertEqual(calls[0][:3], ["pr", "view", "https://github.com/acme/tool/pull/482"])
        self.assertIn("changedFiles", calls[0][4])
        self.assertEqual(calls[1][:2], ["pr", "diff"])
        self.no_secret_anywhere(self.tmp / "a")

        listed = [{"path": "src/f%03d.py" % i, "additions": 1, "deletions": 0} for i in range(100)]
        pages = "".join(json.dumps([{"filename": "src/f%03d.py" % i, "additions": 1, "deletions": 0, "status": "added"}
                                    for i in range(k, k + 75)]) for k in (0, 75))
        fake_gh(bin_dir, view=json.dumps(dict(PR, files=listed, changedFiles=150)), diff=DIFF, api=pages)
        (bin_dir / "gh-calls.log").unlink()
        cp = showtime("pr-video", "482", "--repo", "acme/tool", "--out", self.tmp / "b", "--no-render", "--json",
                      env=env)
        res = json.loads(cp.stdout)
        self.assertEqual((res["files"], res["notes"]), (150, []))
        calls = [json.loads(x) for x in (bin_dir / "gh-calls.log").read_text().splitlines()]
        self.assertIn(["api", "repos/acme/tool/pulls/482/files?per_page=100", "--paginate"], calls)
        self.assertIn(["-R", "acme/tool"], [c[-2:] for c in calls if c[:2] == ["pr", "view"]])

        fake_gh(bin_dir, view=json.dumps(dict(PR, files=listed, changedFiles=3400)), diff=DIFF, api=pages)
        cp = showtime("pr-video", "482", "--repo", "acme/tool", "--out", self.tmp / "c", "--no-render", env=env)
        self.assertIn("note: this PR is too big to show in full: it changes 3400 files and GitHub lists 150", cp.stdout)
        page = (self.tmp / "c" / "project" / "index.html").read_text(encoding="utf-8")
        self.assertIn("3400 files changed", page)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
