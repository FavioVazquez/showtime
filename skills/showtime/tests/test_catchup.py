#!/usr/bin/env python3
""""Since you last looked" (st.job.catchup) and the job folder's AGENTS.md / CLAUDE.md (no browser, no ffmpeg).

  * job init writes AGENTS.md and CLAUDE.md (the same short text: status first, SHOWTIME.md, never overwrite a
    hand edit) and a seen.json that takes what the job holds as seen
  * a hand edit made while the agent was away (or while a command ran) is unseen; the agent's own edit just
    before a command is taken in silently; a touch (same bytes, new mtime) is not an edit
  * the person's unread notes, new board events and open critic findings are unseen until `showtime status`
    shows them (then seen); `review notes --new` read marks and the board cursor count as seen too
  * safety: a notes file written for another job, a notes folder that is a symlink, a link inside the project
    and a moved or copied job folder are never "unseen"
  * the CLI: a job-scoped command ends with exactly one line (stderr), --json carries "since_last_looked"
    instead, status prints the block once and marks it seen

Stdlib only. usage: python tests/test_catchup.py [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

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
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.job import catchup, ledger  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
for k in ("SHOWTIME_OUT", "SHOWTIME_INTERNAL", "SHOWTIME_CATCHUP", "SHOWTIME_AWAY_MIN", "SHOWTIME_RUN_ID", "SHOWTIME_MCP"):
    ENV.pop(k, None)
    os.environ.pop(k, None)
LATER = 3600.0      # a command that starts an hour after an edit: the edit was made while the agent was away


def showtime(*args, env=None, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=180, stdin=subprocess.DEVNULL)
    if cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                     cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def can_symlink(tmp: Path) -> bool:
    try:
        (tmp / ".probe-target").write_text("x", encoding="utf-8")
        os.symlink(str(tmp / ".probe-target"), str(tmp / ".probe-link"))
        return True
    except (OSError, NotImplementedError):
        return False


class CatchupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="st-catchup-")))
        self.job, _data = ledger.init("demo", base=self.tmp)
        self.proj = self.job / "project"
        self.proj.mkdir()
        (self.proj / "showtime.json").write_text('{"duration": 2}\n', encoding="utf-8")
        self.index = self.proj / "index.html"
        self.index.write_text("<h1>first</h1>\n", encoding="utf-8")
        ledger.note(self.job, project=self.proj)
        # the first command after `showtime new`: the new project is the agent's start, nothing unseen
        self.assertIsNone(catchup.after_command(self.job, started=time.time() + LATER))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def seen(self):
        return json.loads((self.job / "work" / "seen.json").read_text(encoding="utf-8"))

    def later(self):
        return catchup.after_command(self.job, started=time.time() + LATER)

    def write_notes(self, notes, job_name=None):
        d = self.job / "review" / "notes"
        d.mkdir(parents=True, exist_ok=True)
        (d / "notes.json").write_text(json.dumps({"schema": "showtime.review.notes/1", "job": job_name or self.job.name,
                                                  "notes": notes}), encoding="utf-8")

    @staticmethod
    def note(i, author="person", updated="2026-10-07T10:00:00.000Z"):
        return {"id": "n%d" % i, "t": 1.5 * i, "region": None, "text": "make the logo bigger %d" % i, "author": author,
                "status": "open", "reply": "", "replied": None, "created": updated, "updated": updated}

    # ------------------------------------------------------------------ the job folder's note for agents
    def test_agents_md_written(self):
        a, c = self.job / "AGENTS.md", self.job / "CLAUDE.md"
        self.assertTrue(a.is_file() and c.is_file())
        text = a.read_text(encoding="utf-8")
        self.assertEqual(text, c.read_text(encoding="utf-8"))
        self.assertLess(len(text.strip().splitlines()), 15)
        self.assertIn("showtime status", text)
        self.assertNotIn("showtime status %s" % self.job.name, text, "the name goes stale when the folder is renamed")
        self.assertIn("SHOWTIME.md", text)
        self.assertIn("Never overwrite a hand edit without asking", text)
        # never replaced once there
        a.write_text("mine\n", encoding="utf-8")
        ledger.write_agent_notes(self.job)
        self.assertEqual(a.read_text(encoding="utf-8"), "mine\n")
        self.assertEqual(self.seen()["schema"], catchup.SCHEMA)

    # ------------------------------------------------------------------ files
    def test_hand_edit_detected_until_status(self):
        self.index.write_text("<h1>by hand</h1>\n", encoding="utf-8")
        s = self.later()
        self.assertIsNotNone(s)
        self.assertEqual([(f["path"], f["change"], f["why"]) for f in s["files"]], [("index.html", "edited", "away")])
        self.assertEqual(s["line"], "since you last looked: index.html edited by hand -> showtime status %s" % self.job.name)
        # a footer marks nothing seen: the next command (even right after the edit) still names it
        s2 = catchup.after_command(self.job, started=time.time())
        self.assertEqual([f["path"] for f in (s2 or {}).get("files", [])], ["index.html"])
        st = catchup.catch_up(self.job)
        self.assertEqual([f["path"] for f in st["files"]], ["index.html"])
        self.assertTrue(st["marked_seen"])
        self.assertTrue(any("caught up" in h["event"] for h in ledger.load(self.job)["history"]))
        block = "\n".join(catchup.block(st, self.job.name))
        self.assertIn("index.html edited", block)
        self.assertIn("likely by hand", block)
        self.assertIsNone(self.later())
        self.assertIsNone(catchup.catch_up(self.job))

    def test_touch_is_not_an_edit(self):
        t = time.time() - 50
        os.utime(str(self.index), (t, t))
        self.assertIsNone(self.later())
        rec = self.seen()["files"]["p/index.html"]
        self.assertAlmostEqual(rec[1], round(t, 3), places=2)       # the new mtime is recorded: no hashing next time

    def test_agents_own_recent_edit_taken_in(self):
        self.index.write_text("<h1>the agent's edit</h1>\n", encoding="utf-8")
        self.assertIsNone(catchup.after_command(self.job, started=time.time() + 1))
        self.assertIsNone(catchup.catch_up(self.job))
        (self.proj / "scene2.js").write_text("// new\n", encoding="utf-8")
        self.assertIsNone(catchup.after_command(self.job, started=time.time() + 1))

    def test_edit_while_the_command_ran(self):
        started = time.time() - 60
        (self.proj / "style.css").write_text("h1{color:red}\n", encoding="utf-8")
        s = catchup.after_command(self.job, started=started)
        self.assertEqual([(f["path"], f["change"], f["why"]) for f in s["files"]], [("style.css", "added", "during")])
        text = "\n".join(catchup.block(s, self.job.name))
        self.assertIn("by hand, or by you in parallel", text)
        self.assertNotIn("not by you", text)

    def test_renamed_job_keeps_its_notes(self):
        # notes.json records the folder's name when the first note was written; the folder is renamed after
        old_name = self.job.name
        new = self.job.with_name("demo-final")
        os.rename(str(self.job), str(new))
        self.job = new
        self.assertIsNone(self.later())                               # moved: catch-up starts from what it holds
        self.write_notes([self.note(1)], job_name=old_name)
        s = self.later()
        self.assertTrue(s and [n["id"] for n in s["notes"]] == ["n1"], s)
        self.assertIn("-> showtime status demo-final", s["line"])
        self.write_notes([self.note(1), self.note(2)], job_name="someone-elses-job")
        self.assertIsNone(self.later(), "notes copied from another job stay unseen-free")

    def test_edit_during_a_background_or_mcp_run_is_the_agents(self):
        # `render --background` (SHOWTIME_RUN_ID) and MCP tool calls (SHOWTIME_MCP=1) run while the agent edits
        for k, v in (("SHOWTIME_RUN_ID", "r-20261007-1"), ("SHOWTIME_MCP", "1")):
            old = os.environ.get(k)
            os.environ[k] = v
            try:
                started = time.time() - 60
                (self.proj / ("bg-%s.css" % k.lower())).write_text("h1{color:red}\n", encoding="utf-8")
                self.assertIsNone(catchup.after_command(self.job, started=started), k)
                self.assertIsNone(catchup.catch_up(self.job), "%s: the edit was taken in as the agent's" % k)
            finally:
                if old is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old

    def test_generated_folders_and_links_ignored(self):
        (self.proj / "work" / "check").mkdir(parents=True)
        (self.proj / "work" / "check" / "report.json").write_text("{}", encoding="utf-8")
        (self.proj / "render.json").write_text("{}", encoding="utf-8")
        (self.proj / ".index.html.swp").write_text("x", encoding="utf-8")
        self.assertIsNone(self.later())
        if not can_symlink(self.tmp):
            return
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.html").write_text("a", encoding="utf-8")
        os.symlink(str(outside / "secret.html"), str(self.proj / "linked.html"))
        os.symlink(str(outside), str(self.proj / "linked-dir"))
        self.assertIsNone(self.later())
        (outside / "secret.html").write_text("changed outside", encoding="utf-8")
        self.assertIsNone(self.later())
        self.assertFalse(any("linked" in k for k in self.seen()["files"]))

    def test_project_outside_the_job(self):
        repo = self.tmp / "repo" / "video"
        repo.mkdir(parents=True)
        (repo / "showtime.json").write_text('{"duration": 2}\n', encoding="utf-8")
        (repo / "index.html").write_text("<h1>repo</h1>\n", encoding="utf-8")
        ledger.note(self.job, project=repo)
        self.assertIsNone(self.later())                                 # a new project: the agent's start
        (repo / "index.html").write_text("<h1>edited in the repo</h1>\n", encoding="utf-8")
        self.assertEqual([f["path"] for f in self.later()["files"]], ["index.html"])

    def test_project_link_inside_the_job_is_not_followed(self):
        if not can_symlink(self.tmp):
            self.skipTest("no symlinks here")
        real = self.tmp / "real-project"
        real.mkdir()
        os.symlink(str(real), str(self.job / "linked-project"))
        self.assertIsNone(catchup.project_dir(self.job, {"project": str(self.job / "linked-project")}))
        self.assertIsNone(catchup.project_dir(self.job, {"project": str(self.job)}))
        self.assertEqual(catchup.project_dir(self.job, {"project": str(self.proj)}), self.proj)

    def test_showtime_md_notes_are_the_persons(self):
        md = self.job / "SHOWTIME.md"
        md.write_text(md.read_text(encoding="utf-8").replace("(free text; kept across updates)", "use the blue logo"),
                      encoding="utf-8")
        s = catchup.after_command(self.job, started=time.time())
        self.assertEqual([(f["path"], f["why"]) for f in s["files"]], [("SHOWTIME.md notes", "notes")])
        ledger.note(self.job, event="regenerates SHOWTIME.md")         # the text survives, so does its state
        self.assertIsNotNone(catchup.after_command(self.job, started=time.time()))
        catchup.catch_up(self.job)
        ledger.note(self.job, event="again")
        self.assertIsNone(catchup.after_command(self.job, started=time.time()))

    # ------------------------------------------------------------------ notes, board, findings
    def test_unread_notes_then_seen(self):
        self.write_notes([self.note(1), self.note(2, author="agent")])
        s = self.later()
        self.assertEqual([n["id"] for n in s["notes"]], ["n1"])
        self.assertIn("1 unread note", s["line"])
        self.assertIsNotNone(self.later())                              # still unread: footers mark nothing
        st = catchup.catch_up(self.job)
        self.assertEqual([n["id"] for n in st["notes"]], ["n1"])
        self.assertIn('n1 at 0:01.50 "make the logo bigger 1"', "\n".join(catchup.block(st, self.job.name)))
        self.assertIsNone(self.later())
        stretch = dict(self.note(3), to=8.25)                           # a note on a stretch of time
        self.write_notes([self.note(1), stretch])
        self.assertIn('n3 from 0:04.50 to 0:08.25 "make the logo bigger 3"',
                      "\n".join(catchup.block(catchup.catch_up(self.job), self.job.name)))
        # an edit by the person makes it unread again; `review notes --new` read marks make it seen
        self.write_notes([self.note(1, updated="2026-10-07T11:00:00.000Z")])
        self.assertEqual([n["id"] for n in self.later()["notes"]], ["n1"])
        st_dir = self.job / "review" / "notes" / ".state"
        st_dir.mkdir(parents=True, exist_ok=True)
        (st_dir / "read.json").write_text(json.dumps({"n1": "2026-10-07T11:00:00.000Z"}), encoding="utf-8")
        self.assertIsNone(self.later())

    def test_notes_for_another_job_are_not_unseen(self):
        self.write_notes([self.note(1)], job_name="someone-elses-job-20260101-000000")
        self.assertIsNone(self.later())
        self.assertIsNone(catchup.catch_up(self.job))

    def test_notes_through_a_symlink_are_not_read(self):
        if not can_symlink(self.tmp):
            self.skipTest("no symlinks here")
        elsewhere = self.tmp / "elsewhere" / "notes"
        elsewhere.mkdir(parents=True)
        (elsewhere / "notes.json").write_text(json.dumps({"job": self.job.name, "notes": [self.note(1)]}),
                                              encoding="utf-8")
        (self.job / "review").mkdir()
        os.symlink(str(elsewhere), str(self.job / "review" / "notes"))
        self.assertIsNone(self.later())

    def test_board_events_and_cursor(self):
        studio = self.job / "studio"
        (studio / ".state").mkdir(parents=True)
        ev = [{"id": "f1", "ts": "2026-10-07T10:00:00Z", "type": "pick", "slot": "concept", "target": "c2"},
              {"id": "f2", "ts": "2026-10-07T10:01:00Z", "type": "comment", "target": "c2", "text": "warmer, please"}]
        (studio / "feedback.json").write_text(json.dumps({"job": self.job.name, "events": ev}), encoding="utf-8")
        s = self.later()
        self.assertEqual([e["id"] for e in s["board"]], ["f1", "f2"])
        self.assertIn("1 new board pick, 1 new board comment", s["line"])
        (studio / ".state" / "feedback-cursor").write_text("f1", encoding="utf-8")   # studio feedback --new read f1
        self.assertEqual([e["id"] for e in self.later()["board"]], ["f2"])
        st = catchup.catch_up(self.job)
        self.assertIn('comment c2 "warmer, please"', "\n".join(catchup.block(st, self.job.name)))
        self.assertIsNone(self.later())

    def test_open_findings_until_shown(self):
        r1 = self.job / "review" / "round-1"
        r1.mkdir(parents=True)
        (r1 / "FINDINGS.md").write_text("VERDICT: not ready -- the hook\nWOULD I POST THIS: no -- black\n"
                                        "BLOCKERS:\n- t=0.00s frames/a.jpg the hook is black -> show the title\n"
                                        "SHOULD-FIX:\n- none\nPOLISH:\n- none\n", encoding="utf-8")
        s = self.later()
        self.assertEqual([f["id"] for f in s["findings"]], ["r1-B1"])
        self.assertIn("1 open critic finding", s["line"])
        catchup.mark_findings_seen(self.job)                            # review-respond listed it
        self.assertIsNone(self.later())

    def test_moved_job_starts_from_what_it_holds(self):
        self.write_notes([self.note(1)])
        self.index.write_text("<h1>by hand</h1>\n", encoding="utf-8")
        copy = self.tmp / "copied" / "showtime-out" / self.job.name
        shutil.copytree(str(self.job), str(copy), symlinks=True)
        self.assertIsNone(catchup.after_command(copy, started=time.time() + LATER))
        self.assertTrue(any("moved or copied" in h["event"] for h in ledger.load(copy)["history"]))
        self.assertIsNotNone(self.later())                              # the original still has them unseen

    def test_off_switch(self):
        self.write_notes([self.note(1)])
        os.environ["SHOWTIME_CATCHUP"] = "0"
        try:
            self.assertIsNone(self.later())
            self.assertIsNone(catchup.catch_up(self.job))
        finally:
            os.environ.pop("SHOWTIME_CATCHUP", None)
        self.assertIsNotNone(self.later())


class NodeWiringTests(unittest.TestCase):
    """render, check, snap and look (Node) end with the same line through scripts/lib/cli.mjs."""

    def test_node_commands_carry_the_line(self):
        for name in ("render", "check", "snap", "look"):
            src = (SKILL / "scripts" / (name + ".mjs")).read_text(encoding="utf-8")
            self.assertIn("await sinceLastLooked(", src, name)
            self.assertIn("printSince(since)", src, name)
            self.assertIn("since_last_looked", src, name)
        cli = (SKILL / "scripts" / "lib" / "cli.mjs").read_text(encoding="utf-8")
        self.assertIn("SHOWTIME_INTERNAL: '1'", cli)        # their own Python steps never print one
        self.assertIn("'job', 'catchup', job, '--footer', '--json', '--started'", cli)


class CatchupCliTests(unittest.TestCase):
    """The commands: one line at the end, a JSON field with --json, status shows and marks seen."""

    def test_footer_json_and_status(self):
        base = Path(os.path.realpath(tempfile.mkdtemp(prefix="st-catchup-cli-")))
        try:
            job = Path(json.loads(showtime("job", "init", "cli", "--no-check", "--json", cwd=base).stdout)["job"])
            proj = job / "project"
            proj.mkdir()
            (proj / "showtime.json").write_text('{"duration": 2}\n', encoding="utf-8")
            (proj / "index.html").write_text("<h1>first</h1>\n", encoding="utf-8")
            cp = showtime("job", "note", job.name, "--project", proj, cwd=base)
            self.assertNotIn("since you last looked", cp.stdout + cp.stderr)
            # a person edits index.html and leaves a note; the agent comes back a while later
            (proj / "index.html").write_text("<h1>by hand</h1>\n", encoding="utf-8")
            (job / "review" / "notes").mkdir(parents=True)
            (job / "review" / "notes" / "notes.json").write_text(json.dumps({"job": job.name, "notes": [
                {"id": "n1", "t": 2, "text": "the title is too small", "author": "person", "status": "open",
                 "updated": "2026-10-07T10:00:00.000Z"}]}), encoding="utf-8")
            time.sleep(1.3)
            env = dict(ENV, SHOWTIME_AWAY_MIN="0.01")                # 0.6 s counts as "away" here
            cp = showtime("job", "note", job.name, "--event", "resumed", env=env, cwd=base)
            hits = [ln for ln in (cp.stdout + cp.stderr).splitlines() if "since you last looked" in ln]
            self.assertEqual(hits, ["since you last looked: index.html edited by hand, 1 unread note -> showtime status %s"
                                    % job.name])
            self.assertEqual(cp.stderr.strip().splitlines()[-1], hits[0])   # the last line, on stderr
            cp = showtime("job", "note", job.name, "--event", "again", "--json", env=env, cwd=base)
            self.assertNotIn("since you last looked", cp.stderr)
            field = json.loads(cp.stdout)["since_last_looked"]
            self.assertEqual(field["count"], 2)
            self.assertEqual(field["notes"][0]["id"], "n1")
            # the Node commands' call: the same line, marks nothing
            foot = json.loads(showtime("job", "catchup", job.name, "--footer", "--json", env=env, cwd=base).stdout)
            self.assertEqual(foot["count"], 2)
            # another showtime command's own step (SHOWTIME_INTERNAL) never prints one
            cp = showtime("job", "note", job.name, "--event", "inner", env=dict(env, SHOWTIME_INTERNAL="1"), cwd=base)
            self.assertNotIn("since you last looked", cp.stdout + cp.stderr)
            cp = showtime("status", job.name, env=env, cwd=base)
            out = cp.stdout.splitlines()
            self.assertTrue(out[3].startswith("since you last looked (seen up to"), cp.stdout)
            self.assertIn("now marked seen", out[3])
            self.assertTrue(any(ln.strip().startswith("index.html edited") for ln in out))
            self.assertTrue(any("1 unread note from the person reviewing" in ln for ln in out))
            cp = showtime("status", job.name, env=env, cwd=base)
            self.assertEqual(len(cp.stdout.strip().splitlines()), 3, cp.stdout)
            st = json.loads(showtime("status", job.name, "--json", env=env, cwd=base).stdout)
            self.assertIsNone(st["since_last_looked"])
            cp = showtime("job", "note", job.name, "--event", "after", env=env, cwd=base)
            self.assertNotIn("since you last looked", cp.stdout + cp.stderr)
        finally:
            shutil.rmtree(str(base), ignore_errors=True)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a in ("-v", "--verbose")])
