#!/usr/bin/env python3
"""Job ledger, status, clean, brand kit and bug-report tests (no browser; ffmpeg only for one qa run).

  * job init: fresh folder per call (never reused), self-ignoring showtime-out/ inside a git repo,
    job.json with versions/platform/ffmpeg, SHOWTIME.md with the six resume sections
  * job note: stage timings, verified moves an item out of assumed, answers close questions,
    pointers, "## Notes" text survives regeneration; status prints three lines for the newest job
  * qa of a video inside a job folder is recorded in the ledger
  * clean: shows sizes, refuses without confirmation off a TTY, removes only showtime intermediates
    (frames, scratch) and keeps deliverables and user files; refuses non-showtime folders
  * report: redacts home paths, user name, e-mails and tokens, never uploads
  * brand init from a repo (CSS variables, tailwind config, package.json, README, logo) + show/css/load

Stdlib only. usage: python tests/test_job.py [--fast] [-v]
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

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV["SHOWTIME_OFFLINE"] = "1"   # brand font lookups must not need the network in tests


def showtime(*args, check=True, cwd=None, timeout=180, stdin=None, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout, stdin=stdin if stdin is not None else subprocess.DEVNULL)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


class JobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-job-"))
        cls.repo = cls.tmp / "repo"
        (cls.repo / ".git").mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ------------------------------------------------------------------ ledger
    def test_01_init_and_resume_note(self):
        cp = showtime("job", "init", "Launch Teaser!", "--goal", "15 s teaser for v2", "--question", "9:16 or 16:9?",
                      "--assumed", "logo is assets/logo.svg", "--json", cwd=self.repo)
        info = json.loads(cp.stdout)
        job = Path(info["job"])
        self.assertTrue(job.is_dir())
        self.assertEqual(job.parent.name, "showtime-out")
        self.assertTrue(job.name.startswith("launch-teaser-"))
        gi = job.parent / ".gitignore"
        self.assertTrue(gi.is_file(), "showtime-out/ must ignore itself inside a git repo")
        self.assertIn("*", gi.read_text(encoding="utf-8").splitlines())
        self.assertTrue((job / "work" / "logs").is_dir())
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        for k in ("showtime", "os", "arch", "python", "ffmpeg", "browser"):
            self.assertIn(k, data["env"])
        self.assertTrue(data["env"]["ffmpeg"].get("version"))
        md = (job / "SHOWTIME.md").read_text(encoding="utf-8")
        for sec in ("## Goal", "## Where we are", "## Verified", "## Assumed", "## Open questions", "## Next command",
                    "## Pointers", "## Notes"):
            self.assertIn(sec, md)
        self.assertIn("15 s teaser for v2", md)
        self.assertIn("9:16 or 16:9?", md)
        # a second init in the same second never reuses the folder
        cp2 = showtime("job", "init", "Launch Teaser!", "--json", cwd=self.repo)
        job2 = Path(json.loads(cp2.stdout)["job"])
        self.assertNotEqual(job, job2)
        shutil.rmtree(str(job2))
        self.__class__.job = job

        # stage boundary with timing, assumption verified, question answered, pointer, notes kept
        showtime("job", "note", job.name, "--stage", "storyboard", "--status", "started", cwd=self.repo)
        time.sleep(1.1)
        with (job / "SHOWTIME.md").open("a", encoding="utf-8") as fh:
            fh.write("\nThe user prefers the blue logo.\n")
        showtime("job", "note", "--stage", "storyboard", "--verified", "logo is assets/logo.svg",
                 "--verified", "user approved storyboard v2", "--answer", "1:both", "--pointer", "brief=studio/brief.md",
                 "--next", "showtime render proj --preview", "--cache-hit", "3", cwd=self.repo)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        st = [s for s in data["stages"] if s["name"] == "storyboard"][-1]
        self.assertEqual(st["status"], "done")
        self.assertGreaterEqual(st["seconds"], 1.0)
        self.assertEqual(data["assumed"], [])
        self.assertEqual(len(data["verified"]), 2)
        self.assertEqual(data["questions"][0]["answer"], "both")
        self.assertEqual(data["pointers"]["brief"], "studio/brief.md")
        self.assertEqual(data["cache"]["hits"], 3)
        md = (job / "SHOWTIME.md").read_text(encoding="utf-8")
        self.assertIn("The user prefers the blue logo.", md)
        self.assertIn("showtime render proj --preview", md)
        self.assertIn("do not ask again", md)
        cp = showtime("job", "note", "--answer", "7:nope", cwd=self.repo, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertNotIn("Traceback", cp.stderr)

    def test_02_status(self):
        cp = showtime("status", cwd=self.repo)
        lines = cp.stdout.strip().splitlines()
        self.assertEqual(len(lines), 3, cp.stdout)
        self.assertIn("storyboard done", lines[0])
        self.assertIn("verified 2", lines[1])
        self.assertTrue(lines[2].startswith("next: showtime render proj --preview"))
        rep = json.loads(showtime("status", "--json", cwd=self.repo).stdout)
        self.assertEqual(rep["stage"], "storyboard")
        empty = self.tmp / "empty"
        empty.mkdir()
        cp = showtime("status", cwd=empty)
        self.assertIn("no showtime jobs", cp.stdout)
        cp = showtime("job", "list", cwd=self.repo)
        self.assertIn("launch-teaser", cp.stdout)

    def test_03_qa_recorded_in_ledger(self):
        job = self.__class__.job
        v = job / "final.mp4"
        cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2",
                             "-f", "lavfi", "-i", "sine=f=300:d=2:sample_rate=48000", "-af", "volume=7.8dB",
                             "-vf", "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709",
                             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                             "-movflags", "+faststart", str(v)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        cp = showtime("qa", v, "--json", check=False)
        rep = json.loads(cp.stdout)
        self.assertTrue(Path(rep["report"]).is_file())
        self.assertTrue(str(rep["report"]).startswith(str(job / "work" / "qa")))
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["qa"]["verdict"], rep["verdict"])
        self.assertEqual(data["stage"], "qa")
        if rep["verdict"] != "FAIL":
            self.assertTrue(any(x["text"].startswith("qa ") for x in data["verified"]))

    # ------------------------------------------------------------------ clean
    def test_04_clean(self):
        job = self.tmp / "out" / "showtime-out" / "demo-20260101-120000"
        (job / "work" / "frames").mkdir(parents=True)
        (job / "work" / "audio").mkdir()
        (job / "work" / "logs").mkdir()
        (job / "exports").mkdir()
        for i in range(20):
            (job / "work" / "frames" / ("f%04d.jpg" % i)).write_bytes(b"x" * 1000)
        (job / "work" / "audio" / "mix.wav").write_bytes(b"x" * 5000)
        (job / "work" / "logs" / "render.log").write_text("ok\n", encoding="utf-8")
        (job / "work" / "my-notes.txt").write_text("mine", encoding="utf-8")
        (job / "final.mp4").write_bytes(b"video")
        (job / "exports" / "final.reels.mp4").write_bytes(b"video")
        (job / "render.json").write_text(json.dumps({"output": str(job / "final.mp4")}), encoding="utf-8")
        cp = showtime("clean", job, "--dry-run")
        self.assertIn("work/frames", cp.stdout)
        self.assertIn("20.0 KB", cp.stdout)   # decimal units everywhere (20 x 1000 bytes)
        self.assertTrue((job / "work" / "frames").is_dir())
        cp = showtime("clean", job, check=False)   # stdin is not a terminal: must refuse
        self.assertEqual(cp.returncode, 1)
        self.assertIn("confirmation", cp.stderr)
        self.assertTrue((job / "work" / "frames").is_dir())
        showtime("clean", job, "--frames", "--yes")
        self.assertFalse((job / "work" / "frames").exists())
        self.assertTrue((job / "work" / "audio" / "mix.wav").is_file())
        showtime("clean", job, "--yes")
        self.assertFalse((job / "work" / "audio").exists())
        self.assertTrue((job / "work" / "logs" / "render.log").is_file())
        showtime("clean", job, "--all", "--yes")
        self.assertFalse((job / "work" / "logs").exists())
        for keep in ("final.mp4", "render.json", "exports/final.reels.mp4", "work/my-notes.txt"):
            self.assertTrue((job / keep).is_file(), keep)
        stranger = self.tmp / "not-a-job"
        (stranger / "work" / "frames").mkdir(parents=True)
        cp = showtime("clean", stranger, "--yes", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("not a showtime job", cp.stderr)
        self.assertTrue((stranger / "work" / "frames").is_dir())
        # a project: only its check/snap scratch
        proj = self.tmp / "proj"
        (proj / "work" / "check").mkdir(parents=True)
        (proj / "work" / "check" / "report.json").write_text("{}", encoding="utf-8")
        (proj / "showtime.json").write_text("{}", encoding="utf-8")
        (proj / "index.html").write_text("<p>", encoding="utf-8")
        showtime("clean", proj, "--yes")
        self.assertFalse((proj / "work" / "check").exists())
        self.assertTrue((proj / "index.html").is_file())

    # ------------------------------------------------------------------ report
    def test_05_redaction_and_report(self):
        from st.job import report
        home = str(Path.home())
        user = Path.home().name
        raw = ("path %s/projects/x token=ghp_%s mail someone@example.org Bearer abcdefghijklmnopqrstu "
               "key sk-%s https://me:secret@host.example/a?token=zzz123 user %s" % (home, "a" * 30, "b" * 24, user))
        red = report.redact(raw)
        self.assertNotIn(home, red)
        self.assertNotIn("ghp_", red)
        self.assertNotIn("someone@example.org", red)
        self.assertNotIn("secret@", red)
        self.assertNotIn("zzz123", red)
        if len(user) >= 2 and user.lower() not in ("root", "user", "admin", "home"):
            self.assertNotRegex(red, r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % user)
        self.assertEqual(report.audit(red), [])
        job = self.__class__.job
        (job / "work" / "logs" / "render.log").write_text(
            "frame 1\nERROR: failed at %s/x with token=ghp_%s for someone@example.org\n" % (home, "c" * 30), encoding="utf-8")
        cp = showtime("report", job.name, "--no-doctor", "--problem", "audio drifts after 10 s", "--json", cwd=self.repo)
        res = json.loads(cp.stdout)
        text = Path(res["path"]).read_text(encoding="utf-8")
        self.assertIn("audio drifts after 10 s", text)
        self.assertIn("render.log", text)
        self.assertNotIn(home, text)
        self.assertNotIn("someone@example.org", text)
        self.assertNotIn("ghp_", text)
        self.assertEqual(res["redactions_left"], [])
        self.assertIn("Nothing was uploaded", text)

    # ------------------------------------------------------------------ brand
    def test_06_brand_from_repo(self):
        r = self.tmp / "brandrepo"
        (r / "src").mkdir(parents=True)
        (r / "public").mkdir()
        (r / "node_modules" / "dep").mkdir(parents=True)
        (r / ".git").mkdir()
        (r / "package.json").write_text(json.dumps({
            "name": "@acme/nimbus", "description": "Nimbus is a fast, private notes app.",
            "homepage": "https://nimbus.example", "dependencies": {"@fontsource-variable/inter": "^5"}}), encoding="utf-8")
        (r / "tailwind.config.js").write_text(
            "module.exports={theme:{extend:{colors:{brand:{DEFAULT:'#5b5bd6',500:'#5b5bd6',100:'#eeeeff'}},"
            "fontFamily:{display:['Space Grotesk','sans-serif'],mono:['JetBrains Mono','monospace']}}}}", encoding="utf-8")
        (r / "src" / "app.css").write_text(":root{--background:#fbfbf8;--foreground:#0f1115;--primary:hsl(240 60% 60%);"
                                           "--muted:#6b7280}\nbody{font-family:Inter,system-ui,sans-serif}\n", encoding="utf-8")
        (r / "README.md").write_text("# Nimbus\n\nNimbus is a fast, private notes app. Simple by default and open source.\n",
                                     encoding="utf-8")
        (r / "public" / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        (r / "node_modules" / "dep" / "logo.svg").write_text("<svg/>", encoding="utf-8")
        cp = showtime("brand", "init", "--from", r, "-o", r / "brand.json", "--json")
        res = json.loads(cp.stdout)
        kit = json.loads((r / "brand.json").read_text(encoding="utf-8"))
        self.assertEqual(kit["name"], "nimbus")
        self.assertEqual(kit["palette"]["bg"], "#fbfbf8")
        self.assertEqual(kit["palette"]["ink"], "#0f1115")
        self.assertTrue(kit["palette"]["accent"].startswith("#5"))
        self.assertEqual(kit["logo"]["path"], "public/logo.svg")
        self.assertEqual(set(kit["fonts"]), {"body", "display", "mono"})
        self.assertEqual(kit["fonts"]["display"]["family"], "Space Grotesk")
        self.assertIn("fast", kit["tone"])
        self.assertIn("voice", kit)
        self.assertTrue(Path(res["notes"]).is_file())
        self.assertNotIn(str(Path.home()), (r / "brand.json").read_text(encoding="utf-8"))
        # refuses to overwrite without --force
        cp = showtime("brand", "init", "--from", r, "-o", r / "brand.json", check=False)
        self.assertEqual(cp.returncode, 1)
        # show / css / load from a subfolder (search walks up to the repo root)
        sub = r / "videos" / "launch"
        sub.mkdir(parents=True)
        self.assertIn("#fbfbf8", showtime("brand", "show", cwd=sub).stdout)
        css = showtime("brand", "css", cwd=sub).stdout
        self.assertIn("--brand-accent:", css)
        self.assertIn("--brand-font-display: 'Space Grotesk'", css)
        from st import brand
        k2 = brand.load(sub)
        self.assertTrue(Path(k2["logo"]["path"]).is_file())
        self.assertIsNone(brand.load(self.tmp / "empty"))
        # a site capture report works as a source too
        site = self.tmp / "cap" / "site.json"
        (site.parent / "assets" / "logos").mkdir(parents=True)
        (site.parent / "assets" / "logos" / "logo.svg").write_text("<svg/>", encoding="utf-8")
        site.write_text(json.dumps({
            "url": "https://nimbus.example/", "meta": {"title": "Nimbus | Notes", "description": "Fast notes."},
            "colors": {"roles": {"background": "#ffffff", "text": "#111827", "primary": "#6d28d9"}, "palette": []},
            "fonts": {"roles": {"h1": {"family": "\"Space Grotesk\", sans-serif"}, "body": {"family": "Inter, sans-serif"}}},
            "assets": [{"file": "assets/logos/logo.svg", "kind": "logo"}], "text": "Fast, simple notes."}), encoding="utf-8")
        out = self.tmp / "sitebrand" / "brand.json"
        showtime("brand", "init", "--site-json", site, "-o", out)
        kit = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(kit["name"], "Nimbus")
        self.assertEqual(kit["palette"]["accent"], "#6d28d9")
        self.assertEqual(kit["fonts"]["display"]["family"], "Space Grotesk")
        self.assertTrue(kit["logo"]["path"].endswith("logo.svg"))
        cp = showtime("brand", "init", "--url", "https://unknown.example", "--no-capture", "-o", self.tmp / "x.json",
                      cwd=self.tmp / "empty", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no site capture", cp.stderr)

    def test_07_help(self):
        for cmd in (["job"], ["job", "init"], ["job", "note"], ["status"], ["clean"], ["brand"], ["brand", "init"], ["report"]):
            cp = showtime(*(cmd + ["--help"]))
            self.assertIn("usage:", cp.stdout, cmd)
        note = showtime("job", "note", "--help").stdout
        self.assertIn("KIND", note)
        self.assertIn("--platform", note)

    # ------------------------------------------------------------------ which job, which file
    def test_08_job_resolution(self):
        """A bare slug is the newest <slug>-<timestamp>/ job; a shared prefix is an error listing candidates;
        a file or subfolder resolves to its job; with no argument the job the cwd is inside wins."""
        base = self.tmp / "resolve"
        base.mkdir()
        a1 = Path(json.loads(showtime("job", "init", "app-trailer", "--json", cwd=base).stdout)["job"])
        time.sleep(1.1)
        a2 = Path(json.loads(showtime("job", "init", "app-trailer", "--json", cwd=base).stdout)["job"])
        t1 = Path(json.loads(showtime("job", "init", "app-teaser", "--json", cwd=base).stdout)["job"])
        os.utime(str(a1 / "job.json"))  # touched last: still not "newest" (creation time wins)
        st = json.loads(showtime("status", "app-trailer", "--json", cwd=base).stdout)
        self.assertEqual(Path(st["job"]), a2)
        self.assertEqual(Path(json.loads(showtime("status", "app-tra", "--json", cwd=base).stdout)["job"]), a2)
        self.assertEqual(Path(json.loads(showtime("status", a1.name, "--json", cwd=base).stdout)["job"]), a1)
        cp = showtime("status", "app", cwd=base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("matches more than one job", cp.stderr)
        self.assertIn(a2.name, cp.stderr)
        self.assertIn(t1.name, cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = showtime("status", "nothing-like-this", cwd=base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no job named", cp.stderr)
        # a file or a nested folder inside a job resolves to the job
        (a1 / "exports").mkdir()
        (a1 / "exports" / "x.txt").write_text("x", encoding="utf-8")
        self.assertEqual(Path(json.loads(showtime("status", a1 / "exports" / "x.txt", "--json", cwd=base).stdout)["job"]), a1)
        # no argument inside a job folder: that job, not the newest one
        self.assertEqual(Path(json.loads(showtime("status", "--json", cwd=a1 / "exports").stdout)["job"]), a1)
        # a project folder named like the slug is not mistaken for the job
        (base / "app-teaser").mkdir()
        self.assertEqual(Path(json.loads(showtime("status", "app-teaser", "--json", cwd=base).stdout)["job"]), t1)
        # same rules in-process
        from st.job import ledger
        old = os.getcwd()
        os.chdir(str(base))
        try:
            self.assertEqual(ledger.resolve("app-trailer"), a2)
            self.assertEqual(ledger.slug_of("app-trailer-20260926-101500-2"), "app-trailer")
            self.assertEqual(ledger.enclosing_job(a1 / "work" / "logs"), a1)
            self.assertIsNone(ledger.enclosing_job(base))
        finally:
            os.chdir(old)

    def test_09_latest_pointers(self):
        """job.json "outputs" keeps the latest file of each kind; old list-style ledgers migrate."""
        from st.job import ledger
        base = self.tmp / "pointers"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "promo", "--platform", "reels", "--json", cwd=base).stdout)["job"])
        for name in ("final.mp4", "final-2.mp4", "preview.mp4", "poster.jpg", "credits.txt", "share.txt", "final.srt"):
            (job / name).write_bytes(b"x")
        (job / "edit").mkdir()
        (job / "edit" / "edl.json").write_text("{}", encoding="utf-8")
        showtime("job", "note", "promo", "--output", job / "final.mp4", "--output", job / "preview.mp4",
                 "--output", job / "poster.jpg", "--output", job / "credits.txt", "--output", job / "share.txt",
                 "--output", job / "final.srt", "--output", "edl=%s" % (job / "edit" / "edl.json"), cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["platform"], "reels")
        self.assertEqual({k: Path(v).name for k, v in data["outputs"].items()},
                         {"final": "final.mp4", "preview": "preview.mp4", "poster": "poster.jpg", "credits": "credits.txt",
                          "share": "share.txt", "captions": "final.srt", "edl": "edl.json"})
        self.assertEqual(len(data["output_log"]), 7)
        # a re-render moves the pointer; the explicit KIND= form wins over the name
        showtime("job", "note", "promo", "--output", "final=%s" % (job / "final-2.mp4"), cwd=base)
        st = json.loads(showtime("status", "promo", "--json", cwd=base).stdout)
        self.assertEqual(Path(st["outputs"]["final"]).name, "final-2.mp4")
        self.assertEqual(st["platform"], "reels")
        self.assertIn("latest final: `final-2.mp4`", (job / "SHOWTIME.md").read_text(encoding="utf-8"))
        # kind inference
        for name, kind in (("final.poster.mp4", "final"), ("draft.mp4", "preview"), ("preview-3.mp4", "preview"),
                           ("final-2.poster.jpg", "poster"), ("CREDITS.txt", "credits"), ("x.credits.txt", "credits"),
                           ("captions.vtt", "captions"), ("edl-2.json", "edl"), ("final.report.json", None),
                           ("share-copy.txt", "share"), ("notes.txt", None)):
            self.assertEqual(ledger.infer_kind(name), kind, name)
        self.assertEqual(ledger.parse_output("poster=a/b.jpg"), ("poster", "a/b.jpg"))
        # old ledgers (outputs as a list) migrate on load; pointers survive a missing file via fallback
        legacy = base / "showtime-out" / "legacy-20260101-120000"
        legacy.mkdir(parents=True)
        (legacy / "final.mp4").write_bytes(b"x")
        (legacy / "job.json").write_text(json.dumps({"schema": 1, "slug": "legacy", "mode": "quick", "outputs": [
            {"path": str(legacy / "final.mp4"), "at": "2026-01-01T12:00:00", "stage": "render"}]}), encoding="utf-8")
        d = ledger.load(legacy)
        self.assertEqual(Path(d["outputs"]["final"]).name, "final.mp4")
        self.assertEqual(len(d["output_log"]), 1)
        showtime("job", "note", legacy, "--verified", "migrated", cwd=base)
        d = json.loads((legacy / "job.json").read_text(encoding="utf-8"))
        self.assertIsInstance(d["outputs"], dict)
        self.assertEqual(d["verified"][0]["text"], "migrated")
        time.sleep(1.1)
        (legacy / "final-2.mp4").write_bytes(b"xx")  # no pointer for it: the newest file wins the fallback
        d["outputs"] = {}
        (legacy / "job.json").write_text(json.dumps(d), encoding="utf-8")
        self.assertEqual(ledger.latest_output(legacy, "final").name, "final-2.mp4")
        # media_arg: a job gives its latest; a stale explicit file is used but noted
        said = []
        f, j, from_ptr = ledger.media_arg(str(job), "video", say=said.append)
        self.assertEqual((f.name, j, from_ptr), ("final-2.mp4", job, True))
        self.assertIn("(latest final)", said[-1])
        os.utime(str(job / "final-2.mp4"))
        f, j, from_ptr = ledger.media_arg(str(job / "final.mp4"), "video", say=said.append)
        self.assertEqual((f.name, from_ptr), ("final.mp4", False))
        self.assertIn("not the latest final", said[-1])
        with self.assertRaises(Exception):
            ledger.media_arg(str(Path(json.loads(showtime("job", "init", "empty-job", "--json", cwd=base).stdout)["job"])), "video")

    # ------------------------------------------------------------------ round 3: project, next, animatic
    def test_10_project_pointer(self):
        """S7: the job records its project without a --pointer line: found in <job>/<dir>/showtime.json,
        set by job note --project, inferred from a recorded render's render.json; SHOWTIME.md never asks
        for --pointer."""
        from st.job import ledger
        base = self.tmp / "proj-ptr"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "proj-ptr", "--json", cwd=base).stdout)["job"])
        md = (job / "SHOWTIME.md").read_text(encoding="utf-8")
        self.assertNotIn("--pointer", md)
        self.assertIn("showtime new <template> %s" % (job / "project"), md)
        # `showtime new <t> <job>/project` (simulated): the ledger finds it on the next update
        (job / "project").mkdir()
        (job / "project" / "showtime.json").write_text('{"width": 320, "height": 180, "duration": 2}', encoding="utf-8")
        st = json.loads(showtime("status", "proj-ptr", "--json", cwd=base).stdout)
        self.assertIn("showtime check %s" % (job / "project"), st["next"])
        self.assertIn("--job %s" % job.name, st["next"])
        showtime("job", "note", "proj-ptr", "--stage", "build", cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["pointers"]["project"]), job / "project")
        self.assertEqual(Path(data["project"]), job / "project")
        self.assertNotIn("--pointer", (job / "SHOWTIME.md").read_text(encoding="utf-8"))
        # job note --project replaces it
        other = base / "elsewhere"
        other.mkdir()
        (other / "showtime.json").write_text("{}", encoding="utf-8")
        showtime("job", "note", "proj-ptr", "--project", other, cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["pointers"]["project"]), other.resolve())
        # a render recorded with --output final=... (what render --job does) names its project via render.json
        job2 = Path(json.loads(showtime("job", "init", "proj-render", "--json", cwd=base).stdout)["job"])
        (job2 / "final.mp4").write_bytes(b"x")
        (job2 / "final.work").mkdir()
        (job2 / "final.work" / "render.json").write_text(json.dumps({"output": str(job2 / "final.mp4"),
                                                                     "project": str(other)}), encoding="utf-8")
        showtime("job", "note", job2, "--stage", "render", "--output", "final=%s" % (job2 / "final.mp4"), cwd=base)
        data = json.loads((job2 / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["pointers"]["project"]), other.resolve())
        # attach_project (for `showtime new ... --job`): the job containing the folder, or the named job
        job3 = Path(json.loads(showtime("job", "init", "proj-attach", "--json", cwd=base).stdout)["job"])
        old = os.getcwd()
        os.chdir(str(base))
        try:
            self.assertEqual(ledger.attach_project(other, "proj-attach"), job3)
            self.assertIsNone(ledger.attach_project(other))  # not inside any job: nothing to record
            # a crew member's scratch project (style frames, a scene fragment) never becomes the job's project
            for sub in ("crew/pitch-cd/comps", "studio/comps/x"):
                scratch = job3 / sub
                scratch.mkdir(parents=True)
                self.assertIsNone(ledger.attach_project(scratch), sub)
        finally:
            os.chdir(old)
        self.assertEqual(Path(json.loads((job3 / "job.json").read_text(encoding="utf-8"))["project"]), other.resolve())

    def test_11_next_command_after_qa(self):
        """P11: after a qa WARN the next command is to fix and re-run (naming the rule and a tool), not exports;
        a PASS on the latest final suggests exports of the job; a newer render than the qa'd one asks for qa."""
        from st.job import ledger
        base = self.tmp / "next-cmd"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "next-cmd", "--json", cwd=base).stdout)["job"])
        (job / "project").mkdir()
        (job / "project" / "showtime.json").write_text("{}", encoding="utf-8")
        (job / "final.mp4").write_bytes(b"x")
        qa_dir = job / "work" / "qa" / "final"
        qa_dir.mkdir(parents=True)
        (qa_dir / "qa.json").write_text(json.dumps({"verdict": "WARN", "findings": [
            {"rule": "frozen", "severity": "WARN", "message": "still 4.2s", "t": 4.87},
            {"rule": "resolution", "severity": "WARN", "message": "small"}]}), encoding="utf-8")
        data = ledger.load(job)
        data["qa"] = {"verdict": "WARN", "report": str(qa_dir / "qa.json"), "video": str(job / "final.mp4")}
        ledger.save(job, data)
        nxt = ledger.suggest_next(job, ledger.load(job))
        self.assertNotIn("deliver exports", nxt.split("(export")[0])
        self.assertIn("frozen", nxt)
        self.assertIn("showtime check %s --find-first frozen" % (job / "project"), nxt)
        self.assertIn("showtime render %s --job %s" % (job / "project", job.name), nxt)
        self.assertIn("showtime qa %s" % job.name, nxt)
        md = (job / "SHOWTIME.md").read_text(encoding="utf-8")
        self.assertIn("--find-first frozen", md.split("## Next command")[1].split("##")[0])
        data = ledger.load(job)
        data["qa"]["verdict"] = "PASS"
        # quality mode (the default): the critic round comes before exports; lean goes straight to exports
        self.assertEqual(ledger.suggest_next(job, data).split()[:3], ["showtime", "review-pack", job.name + ","])
        data["review_mode"] = "lean"
        self.assertEqual(ledger.suggest_next(job, data).split()[:4], ["showtime", "deliver", "exports", job.name])
        time.sleep(1.1)
        (job / "final-2.mp4").write_bytes(b"xx")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final-2.mp4"), cwd=base)
        self.assertTrue(ledger.suggest_next(job, ledger.load(job)).startswith("showtime qa %s" % job.name))
        # a hand-set next is dropped by the next render (it named the old file) ...
        showtime("job", "note", job, "--next", "showtime deliver exports final.mp4 --targets x", cwd=base)
        self.assertIn("final.mp4 --targets x", ledger.suggest_next(job, ledger.load(job)))
        time.sleep(1.1)
        (job / "final-3.mp4").write_bytes(b"xxx")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final-3.mp4"), cwd=base)
        self.assertNotIn("final.mp4 --targets x", ledger.suggest_next(job, ledger.load(job)))
        # ... a discarded render leaves the job (moved, not deleted) and the pointer falls back
        out = json.loads(showtime("job", "discard", job, "final-3.mp4", "--json", cwd=base).stdout)
        self.assertFalse((job / "final-3.mp4").exists())
        self.assertTrue((job / "work" / "discarded" / "final-3.mp4").is_file())
        self.assertEqual(Path(out["outputs"]["final"]).name, "final-2.mp4")
        # a delivered job whose final passed qa is done
        data = ledger.load(job)
        data["qa"] = {"verdict": "PASS", "report": str(qa_dir / "qa.json"), "video": str(job / "final-2.mp4")}
        ledger.save(job, data)
        showtime("job", "note", job, "--stage", "deliver", cwd=base)
        data = ledger.load(job)
        data["qa"] = {"verdict": "PASS", "report": str(qa_dir / "qa.json"), "video": str(job / "final-2.mp4")}
        ledger.save(job, data)
        # quality mode (the default) without a critic round: delivered, but the round is still named
        self.assertIn("critic round is still open", ledger.suggest_next(job, ledger.load(job)))
        data = ledger.load(job)
        data["review_mode"] = "lean"
        ledger.save(job, data)
        self.assertTrue(ledger.suggest_next(job, ledger.load(job)).startswith("nothing required"))
        # job names resolve from inside the job folder too
        cp = showtime("job", "show", "next-cmd", "--json", cwd=job / "project")
        self.assertEqual(Path(json.loads(cp.stdout)["dir"]).resolve(), job.resolve())

    def test_12_studio_renders_are_animatics(self):
        """ROUND2: a render under <job>/studio/ is the job's animatic and never becomes its preview/final."""
        from st.job import ledger
        base = self.tmp / "animatic"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "trailer", "--mode", "studio", "--json", cwd=base).stdout)["job"])
        anim = job / "studio" / "media" / "animatic" / "a1.mp4"
        anim.parent.mkdir(parents=True)
        anim.write_bytes(b"x")
        # what `render -o <job>/studio/media/animatic/a1.mp4 --preview` records
        showtime("job", "note", job, "--stage", "preview", "--output", "preview=%s" % anim, cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["animatic"]), anim)
        self.assertNotIn("preview", data["outputs"])
        self.assertEqual(ledger.latest_video(job), (None, None))
        cp = showtime("qa", job, check=False, cwd=base)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("has no video", cp.stderr)
        # the explicit kind works too, and an old ledger whose preview points into studio/ is ignored
        showtime("job", "note", job, "--output", "animatic=%s" % anim, cwd=base)
        data["outputs"]["preview"] = str(anim)
        (job / "job.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(ledger.latest_output(job, "preview"))
        self.assertEqual(ledger.latest_output(job, "animatic"), anim)
        (job / "preview.mp4").write_bytes(b"x")
        self.assertEqual(ledger.latest_video(job)[0], job / "preview.mp4")
        # 09: an approval on rev 3 still stands at rev 5 (read from studio/feedback.json, not board.json)
        (job / "studio" / "board.json").write_text(json.dumps({"rev": 5, "phase": "review", "concepts": []}), encoding="utf-8")
        (job / "studio" / "feedback.json").write_text(json.dumps({"events": [
            {"id": "e1", "type": "pick", "target": "c2", "rev": 3}, {"id": "e2", "type": "approve", "target": "c2", "rev": 3}]}),
            encoding="utf-8")
        st = ledger.studio_state(job)
        self.assertEqual((st["rev"], st["approved"]["target"]), (5, "c2"))
        self.assertIn("approved", ledger.status_lines(job)[1] + ledger.status_lines(job)[0])
        self.assertNotIn("not approved", " ".join(ledger.status_lines(job)))

    def test_13_brand_wording_and_served_capture(self):
        """S13: brand init states the palette as assumptions (never "confirm with the user"); a capture of a
        served local folder is reused for `brand init --url <folder>`."""
        from st.brand import draft
        repo = self.tmp / "brandrepo-s13"
        repo.mkdir()
        (repo / "package.json").write_text('{"name": "acme-tool", "description": "Fast widgets"}', encoding="utf-8")
        (repo / "styles.css").write_text(":root { --brand: #3355ff; --bg: #ffffff; --ink: #111111; }", encoding="utf-8")
        cp = showtime("brand", "init", "--from", repo, "-o", repo / "brand.json", "--no-font-lookup", cwd=repo)
        self.assertIn("state these as assumptions", cp.stdout)
        self.assertNotIn("confirm the draft with the user", cp.stdout)
        self.assertNotIn("confirm it", (repo / "brand.md").read_text(encoding="utf-8"))
        site = self.tmp / "static-site"
        site.mkdir()
        cap = self.tmp / "caps" / "static-site-site-20260926-101500"
        cap.mkdir(parents=True)
        (cap / "site.json").write_text(json.dumps({"url": "http://127.0.0.1:53111/", "served": str(site)}), encoding="utf-8")
        cap2 = self.tmp / "caps" / "example-com-site-20260926-101500"
        cap2.mkdir()
        (cap2 / "site.json").write_text(json.dumps({"url": "https://www.example.com/", "served": None}), encoding="utf-8")
        self.assertEqual(draft.find_capture(str(site), [self.tmp / "caps"]), cap / "site.json")
        self.assertEqual(draft.find_capture("https://example.com", [self.tmp / "caps"]), cap2 / "site.json")
        self.assertIsNone(draft.find_capture(str(repo), [self.tmp / "caps"]))

    # ------------------------------------------------------------------ batch 2
    def test_14_tool_variants_and_discard_keeps_captions(self):
        """17.5/19.9/20.11: a tool-recorded alpha .webm, a bumper.mp4 or a second aspect named otherwise is
        logged as a variant (not the latest final); final*.mp4 and a derived copy of the current final are;
        an explicit job note still sets anything. 13.8: discard moves the render, keeps its captions."""
        base = self.tmp / "variants"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "variants", "--json", cwd=base).stdout)["job"])
        for name in ("final.mp4", "lt-kicker.webm", "bumper.mp4", "final-2.mp4", "launch.mp4", "launch.poster.mp4"):
            (job / name).write_bytes(b"v")
            time.sleep(0.02)
        (job / "pack").mkdir()
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.mp4"), "--auto", cwd=base)
        for name in ("lt-kicker.webm", "bumper.mp4"):
            cp = showtime("job", "note", job, "--output", "final=%s" % (job / name), "--auto", cwd=base)
            self.assertIn("logged as a variant", cp.stderr)
            self.assertIn("--output final=", cp.stderr)
            self.assertEqual(Path(json.loads((job / "job.json").read_text(encoding="utf-8"))["outputs"]["final"]).name,
                             "final.mp4")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final-2.mp4"), "--auto", cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["final"]).name, "final-2.mp4")
        self.assertTrue(any(o.get("variant") == "final" and Path(o["path"]).name == "bumper.mp4" for o in data["output_log"]))
        # explicit (no --auto): the user's word wins; then a derived copy of it follows it
        showtime("job", "note", job, "--output", "final=%s" % (job / "launch.mp4"), cwd=base)
        showtime("job", "note", job, "--output", "final=%s" % (job / "launch.poster.mp4"), "--auto", cwd=base)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["final"]).name, "launch.poster.mp4")
        # discard: the render goes, its caption files stay (and the output says so)
        (job / "final-2.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
        (job / "final-2.poster.jpg").write_bytes(b"j")
        cp = showtime("job", "discard", job, "final-2.mp4", cwd=base)
        self.assertFalse((job / "final-2.mp4").exists())
        self.assertFalse((job / "final-2.poster.jpg").exists())
        self.assertTrue((job / "final-2.srt").is_file())
        self.assertIn("kept    final-2.srt", cp.stdout)
        self.assertIn("moved   final-2.poster.jpg", cp.stdout)

    def test_15_clean_manim_brand_adopt_and_fonts(self):
        """22.10: clean frees a Manim project's build/ cache and out/ drafts (not its finals); 20.1: brand init
        --from adopts the repo's own brand.json (never one under examples/) and skips examples/ when scanning;
        20.2: brand show checks fonts live (setup's theme fonts count as installed)."""
        job = self.tmp / "out2" / "showtime-out" / "math-20260101-120000"
        mp = job / "manim"
        (mp / "build" / "cache").mkdir(parents=True)
        (mp / "out").mkdir()
        (mp / "manim.json").write_text("{}", encoding="utf-8")
        (mp / "scenes.py").write_text("# scenes\n", encoding="utf-8")
        (mp / "build" / "cache" / "s1.mp4").write_bytes(b"x" * 4000)
        (mp / "out" / "math-draft.mp4").write_bytes(b"x" * 3000)
        (mp / "out" / "math-draft-2.mp4").write_bytes(b"x" * 3000)
        (mp / "out" / "math.mp4").write_bytes(b"final")
        (job / "job.json").write_text(json.dumps({"slug": "math"}), encoding="utf-8")
        cp = showtime("clean", job, "--dry-run")
        self.assertIn("manim/build", cp.stdout)
        self.assertIn("manim scene cache", cp.stdout)
        self.assertIn("manim/out/math-draft.mp4", cp.stdout)
        showtime("clean", job, "--yes")
        self.assertFalse((mp / "build").exists())
        self.assertFalse((mp / "out" / "math-draft-2.mp4").exists())
        for keep in ("out/math.mp4", "scenes.py", "manim.json"):
            self.assertTrue((mp / keep).is_file(), keep)
        (mp / "build").mkdir()
        (mp / "build" / "x.log").write_text("log", encoding="utf-8")
        showtime("clean", mp, "--yes")   # a Manim project directly
        self.assertFalse((mp / "build").exists())
        # brand: the repo's own kit wins over scanning, and examples/ never leaks in
        r = self.tmp / "kitrepo"
        (r / ".git").mkdir(parents=True)
        (r / "assets" / "brand" / "logo").mkdir(parents=True)
        (r / "examples" / "demo").mkdir(parents=True)
        (r / "examples" / "demo" / "brand.json").write_text(json.dumps({"name": "demo", "colors": [
            {"role": "accent", "hex": "#0e8a8c"}]}), encoding="utf-8")
        (r / "examples" / "demo" / "style.css").write_text(":root{--primary:#0e8a8c}", encoding="utf-8")
        (r / "assets" / "brand" / "logo" / "mark.svg").write_text("<svg/>", encoding="utf-8")
        (r / "assets" / "brand" / "brand.json").write_text(json.dumps({
            "schema": 1, "status": "confirmed", "name": "curtain", "logo": {"path": "logo/mark.svg"},
            "colors": [{"role": "bg", "hex": "#15100E"}, {"role": "accent", "hex": "#E9B949"}],
            "fonts": {"display": {"family": "Fraunces"}, "body": {"family": "Inter"}}}), encoding="utf-8")
        out = self.tmp / "kitout" / "brand.json"
        cp = showtime("brand", "init", "--from", r, "-o", out)
        self.assertIn("already has a brand kit", cp.stderr)
        kit = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((kit["name"], kit["status"]), ("curtain", "confirmed"))
        self.assertEqual(kit["colors"][1]["hex"], "#E9B949")
        self.assertTrue((out.parent / kit["logo"]["path"]).resolve().samefile(r / "assets" / "brand" / "logo" / "mark.svg"))
        from st.brand import draft
        (r / "assets" / "brand" / "brand.json").unlink()
        kit = draft.from_repo(r, lookup_fonts=False)
        self.assertNotIn("#0e8a8c", json.dumps(kit))
        show = showtime("brand", "show", out).stdout
        self.assertNotIn("not installed", show)
        self.assertRegex(show, r"font body +Inter  \((installed: showtime assets font|ships with setup: themes/fonts/inter.css)\)")
        from st import brand
        self.assertTrue(brand.font_status("Fraunces")[0])
        ok, where = brand.font_status("Nosuch Display Zz")
        self.assertFalse(ok)
        self.assertIn('showtime assets font "Nosuch Display Zz"', where)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped), time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
