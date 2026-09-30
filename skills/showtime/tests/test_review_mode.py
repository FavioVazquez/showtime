#!/usr/bin/env python3
"""Review modes: quality (the default, the full review on every finished video) and lean (opt-in).

  * resolution order: --mode, the project's showtime.json "review_mode", SHOWTIME_MODE, the saved default
    (`showtime config mode`), quality; bad values are refused
  * `showtime config`: show, set, unset; other saved settings survive; runs without the render venv
  * `job init --mode lean|quality` (also studio,lean and repeated) records it in job.json, SHOWTIME.md and the
    history; `job note --mode` switches it; `status` (text and --json) and `doctor --json` name it
  * the review rule (st.job.review_state): pending with no answered round (pairwise against an earlier final
    when there is one), waiting for a critic or for review-verdict, "not ready" until a later round, done on a
    verdict, the three-round cap, lean never pending; the next command in status/SHOWTIME.md
  * `showtime qa <job>` prints "WARN review pending" in quality mode without touching the verdict or the exit
    code, nothing in lean, "review done" after a verdict; `deliver exports` and `job note --stage deliver` warn
  * receipts record the review mode and the critic round
  * `showtime new --mode lean` writes showtime.json "review_mode" and the job's mode
  * MCP: new_project takes mode; plugin settings keep a `showtime config` mode and follow the plugin option

Stdlib only. usage: python tests/test_review_mode.py [--fast] [-v]
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
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
SERVER = SKILL / "mcp" / "server.mjs"
CLIENT = TESTS_DIR / "fixtures" / "mcp_client.mjs"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402
from st import review_mode as rm  # noqa: E402
from st.job import ledger, receipt, review_state  # noqa: E402

NODE = shutil.which("node")
BASE_ENV = build_env(showtime_home())
for _k in ("SHOWTIME_OUT", "SHOWTIME_MODE", "SHOWTIME_TRANSCRIPT", "SHOWTIME_AGENT"):
    BASE_ENV.pop(_k, None)
BASE_ENV["SHOWTIME_OFFLINE"] = "1"


def have_ffmpeg() -> bool:
    try:
        from st import ff
        return bool(ff.ffmpeg_path()) and Path(ff.ffmpeg_path()).exists()
    except Exception:  # noqa: BLE001
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-rmode-"))
        self.settings = self.tmp / "settings.json"
        self.env = dict(BASE_ENV, SHOWTIME_SETTINGS=str(self.settings))
        self._old = {k: os.environ.get(k) for k in ("SHOWTIME_SETTINGS", "SHOWTIME_MODE")}
        os.environ["SHOWTIME_SETTINGS"] = str(self.settings)
        os.environ.pop("SHOWTIME_MODE", None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def st(self, *args, check=True, env=None, timeout=240):
        cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], cwd=str(self.tmp),
                            env=dict(self.env, **(env or {})), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=timeout)
        if check and cp.returncode != 0:
            raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
                " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
        return cp

    def job(self, *extra, env=None) -> Path:
        cp = self.st("job", "init", "clip", "--no-check", *extra, env=env)
        return Path(cp.stdout.strip().splitlines()[-1])

    def final(self, job: Path, name: str = "final.mp4") -> Path:
        """A stand-in final (the review rule reads files and the ledger, never the pixels)."""
        f = job / name
        f.write_bytes(b"\0" * 64)
        ledger.note(job, outputs=["final=%s" % f], stage="render")
        return f


# ------------------------------------------------------------------ resolution and config

class TestResolve(Base):
    def test_order(self):
        self.assertEqual(rm.default_mode(), ("quality", "default"))
        rm.save_setting(rm.SETTING, "lean")
        self.assertEqual(rm.default_mode(), ("lean", "config"))
        os.environ["SHOWTIME_MODE"] = "Quality "
        self.assertEqual(rm.default_mode(), ("quality", "env"))
        self.assertEqual(rm.resolve("lean"), ("lean", "flag"))
        os.environ["SHOWTIME_MODE"] = "${user_config.mode}"     # a host's unexpanded placeholder is no value
        self.assertEqual(rm.default_mode(), ("lean", "config"))
        os.environ["SHOWTIME_MODE"] = "fast"                    # an unknown value is ignored, not guessed
        self.assertEqual(rm.default_mode(), ("lean", "config"))
        proj = self.tmp / "p"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"review_mode": "quality"}), encoding="utf-8")
        self.assertEqual(rm.job_mode({"project": str(proj)}), ("quality", "project"))
        self.assertEqual(rm.job_mode({"project": str(proj), "review_mode": "lean"}), ("lean", "job"))
        self.assertIsNone(rm.normalize("quick"))

    def test_save_keeps_other_settings(self):
        self.settings.write_text(json.dumps({"voice": "am_michael", "_about": "x"}), encoding="utf-8")
        rm.save_setting(rm.SETTING, "lean")
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual((data["voice"], data["mode"]), ("am_michael", "lean"))
        rm.save_setting(rm.SETTING, None)
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertNotIn("mode", data)
        self.assertEqual(data["voice"], "am_michael")

    def test_config_command(self):
        out = self.st("config").stdout
        self.assertIn("review mode: quality (default)", out)
        self.assertIn("showtime config mode lean", out)
        self.st("config", "mode", "lean")
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["mode"], "lean")
        info = json.loads(self.st("config", "--json").stdout)
        self.assertEqual((info["mode"], info["source"]), ("lean", "config"))
        info = json.loads(self.st("config", "--json", env={"SHOWTIME_MODE": "quality"}).stdout)
        self.assertEqual((info["mode"], info["source"]), ("quality", "env"))
        bad = self.st("config", "mode", "fast", check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("quality (the default) or lean", bad.stderr)
        self.st("config", "mode", "--unset")
        self.assertNotIn("mode", json.loads(self.settings.read_text(encoding="utf-8")))
        helptext = self.st("config", "--help").stdout
        self.assertIn("lean", helptext)
        self.assertIn("critic round", helptext)

    def test_config_is_stdlib(self):
        from st import launcher
        self.assertIn("config", launcher.STDLIB_CLI)
        src = (SKILL / "lib" / "st" / "cli_config.py").read_text(encoding="utf-8") + \
            (SKILL / "lib" / "st" / "review_mode.py").read_text(encoding="utf-8")
        for mod in ("numpy", "PIL", "cv2", "requests"):
            self.assertNotIn("import %s" % mod, src)


# ------------------------------------------------------------------ job ledger

class TestJob(Base):
    def test_init_records_mode(self):
        j = self.job()
        d = ledger.load(j)
        self.assertEqual((d["mode"], d["review_mode"], d["review_mode_source"]), ("quick", "quality", "default"))
        self.assertIn("quality review", (j / "SHOWTIME.md").read_text(encoding="utf-8"))
        j2 = self.job("--mode", "studio,lean")
        d2 = ledger.load(j2)
        self.assertEqual((d2["mode"], d2["review_mode"], d2["review_mode_source"]), ("studio", "lean", "flag"))
        j3 = self.job("--mode", "lean", "--mode", "studio")
        self.assertEqual((ledger.load(j3)["mode"], ledger.load(j3)["review_mode"]), ("studio", "lean"))
        j4 = self.job(env={"SHOWTIME_MODE": "lean"})
        self.assertEqual((ledger.load(j4)["review_mode"], ledger.load(j4)["review_mode_source"]), ("lean", "env"))
        cp = self.st("job", "init", "x", "--no-check", "--mode", "fast", check=False)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("unknown mode", cp.stderr)
        js = json.loads(self.st("job", "init", "y", "--no-check", "--json").stdout)
        self.assertEqual(js["review_mode"]["mode"], "quality")
        err = self.st("job", "init", "z", "--no-check").stderr
        self.assertIn("review: quality (default)", err)
        self.assertIn("--help", self.st("job", "init", "--help").stdout)
        self.assertIn("lean skips the critic round", " ".join(self.st("job", "init", "--help").stdout.split()))

    def test_note_switches_and_status_names_it(self):
        j = self.job()
        self.st("job", "note", str(j), "--mode", "lean")
        d = ledger.load(j)
        self.assertEqual((d["review_mode"], d["review_mode_source"]), ("lean", "flag"))
        self.assertTrue(any("review mode quality -> lean" in h["event"] for h in d["history"]))
        self.assertIn("(quick, lean review)", self.st("status", str(j)).stdout)
        st = json.loads(self.st("status", str(j), "--json").stdout)
        self.assertEqual(st["review"]["mode"], "lean")
        self.assertEqual(st["mode"], "quick")
        self.st("job", "note", str(j), "--mode", "studio")          # the flow mode alone leaves the review mode
        self.assertEqual((ledger.load(j)["mode"], ledger.load(j)["review_mode"]), ("studio", "lean"))

    def test_status_without_jobs_names_the_default(self):
        out = self.st("status").stdout
        self.assertIn("review mode for new jobs: quality", out)


# ------------------------------------------------------------------ the review rule

class TestReviewState(Base):
    def round(self, job: Path, n: int, findings=None, video=None) -> Path:
        d = job / "review" / ("round-%d" % n)
        (d / "frames").mkdir(parents=True, exist_ok=True)
        (d / "CRITIC.md").write_text("# brief\n", encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps({"round": n, "video": str(video or "")}), encoding="utf-8")
        if findings is not None:
            (d / "FINDINGS.md").write_text(findings, encoding="utf-8")
        return d

    def test_parse_verdict(self):
        pv = review_state.parse_verdict
        self.assertEqual(pv("VERDICT: ship -- clean"), "ship")
        self.assertEqual(pv("**VERDICT:** ship after fixes -- two labels"), "ship after fixes")
        self.assertEqual(pv("SELF-REVIEW (no critic available)\nVERDICT: not ready - black frame"), "not ready")
        self.assertIsNone(pv("VERDICT: ship | ship after fixes | not ready  -- one line"))
        self.assertIsNone(pv("no verdict here"))

    def test_states(self):
        j = self.job()
        self.assertEqual(review_state.state(j)["status"], "no final")
        f1 = self.final(j)
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("pending", True))
        self.assertIn("showtime review-pack %s" % j.name, s["next"])
        self.assertNotIn("--against", s["next"])
        self.assertIn("review-pack", review_state.pending_line(s))
        # a fix after the first look: an earlier final exists, so the round is pairwise against it
        f2 = self.final(j, "final-2.mp4")
        s = review_state.state(j)
        self.assertIn("--against %s" % f1, s["next"])
        # SHOWTIME.md and status name the step before delivery
        data = ledger.load(j)
        data["qa"] = {"verdict": "PASS", "video": str(f2), "report": "qa.json"}
        ledger.save(j, data)
        nxt = ledger.suggest_next(j, ledger.load(j))
        self.assertIn("review-pack", nxt)
        self.assertIn("before delivery", nxt)
        self.assertIn("review pending", self.st("status", str(j)).stdout)
        # a pack waiting for its critic
        r1 = self.round(j, 1, video=f2)
        s = review_state.state(j)
        self.assertEqual(s["status"], "waiting")
        self.assertIn("CRITIC.md", s["next"])
        # a template left unfilled is no verdict; a real one is
        (r1 / "FINDINGS.md").write_text("VERDICT: ship | ship after fixes | not ready\n", encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("waiting", True))
        self.assertIn("VERDICT", s["next"])
        (r1 / "FINDINGS.md").write_text("VERDICT: not ready -- the hook is black\nBLOCKERS:\n- t=0.00s frames/a.jpg x\n",
                                        encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("not ready", True))
        self.assertIn("fix the blockers", s["next"])
        f3 = self.final(j, "final-3.mp4")
        s = review_state.state(j)
        self.assertIn("--against best", s["next"])
        self.assertIn(f3.name, s["message"])
        # round 2, pairwise: one order answered, both answered, decided
        r2 = j / "review" / "round-2"
        for k in (1, 2):
            (r2 / ("order-%d" % k)).mkdir(parents=True)
            (r2 / ("order-%d" % k) / "CRITIC.md").write_text("x", encoding="utf-8")
        keys = j / "review" / ".pairwise-keys"
        keys.mkdir(parents=True)
        (keys / "round-2.json").write_text(json.dumps({"new": {"label": "X", "video": str(f3)},
                                                       "old": {"label": "Y", "video": str(f2)}}), encoding="utf-8")
        self.assertEqual(review_state.state(j)["status"], "waiting")
        (r2 / "order-1" / "FINDINGS.md").write_text("PREFERENCE: X\n", encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual(s["status"], "waiting")
        self.assertIn("order-2", s["next"])
        (r2 / "order-2" / "FINDINGS.md").write_text("PREFERENCE: X\n", encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual(s["status"], "waiting")
        self.assertIn("review-verdict", s["next"])
        (r2 / "verdict.json").write_text(json.dumps({"improved": True, "best": str(f3), "would_post": {"answer": "yes"}}),
                                         encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("done", False))
        self.assertIn("new version wins", s["message"])
        self.assertIsNone(review_state.pending_line(s))
        self.assertNotIn("review-pack", ledger.suggest_next(j, ledger.load(j)))

    def test_ship_after_fixes_and_cap(self):
        j = self.job()
        f = self.final(j)
        self.round(j, 1, "VERDICT: ship after fixes -- the year label\nWOULD I POST THIS: yes -- clean\n", video=f)
        s = review_state.state(j)
        self.assertEqual(s["status"], "done")
        g = self.final(j, "final-2.mp4")
        s = review_state.state(j)
        self.assertEqual(s["status"], "done")           # fixes are proven with snap --compare, not a new round
        self.assertIn("--compare", s["next"])
        self.assertIn(str(g), s["next"])
        k = self.job()
        fk = self.final(k)
        for n in (1, 2, 3):
            self.round(k, n, "VERDICT: not ready -- still\n", video=fk)
        self.assertEqual(review_state.state(k)["status"], "cap")

    def test_poster_bake_is_the_same_render(self):
        j = self.job()
        f = self.final(j)
        self.round(j, 1, "VERDICT: not ready -- x\n", video=f)
        self.final(j, "final.poster.mp4")
        self.assertIn("fix the blockers", review_state.state(j)["next"])

    def test_parse_would_post(self):
        pw = review_state.parse_would_post
        self.assertEqual(pw("WOULD I POST THIS: no -- captions in stepped boxes"), {"": ("no", "captions in stepped boxes")})
        self.assertEqual(pw("**WOULD I POST THIS:** yes - clean and sharp"), {"": ("yes", "clean and sharp")})
        self.assertEqual(pw("WOULD I POST THIS: yes | no  -- one reason"), {})         # the template left as is
        self.assertEqual(pw("WOULD I POST X: no -- soft footage\nWOULD I POST Y: yes -- fine"),
                         {"X": ("no", "soft footage"), "Y": ("yes", "fine")})
        self.assertEqual(pw("VERDICT: ship -- ok"), {})

    def test_absolute_verdict_holds_delivery(self):
        j = self.job()
        f = self.final(j)
        r1 = self.round(j, 1, "VERDICT: ship -- fine\n", video=f)
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("waiting", True))    # the absolute line is required
        self.assertIn("WOULD I POST THIS", s["next"])
        (r1 / "FINDINGS.md").write_text("VERDICT: ship -- fine\nWOULD I POST THIS: no -- it looks cheap at full size\n",
                                        encoding="utf-8")
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("would not post", True))
        self.assertIn("looks cheap", s["message"])
        self.assertIn("WARN", review_state.pending_line(s))
        # a pairwise round the new version won, but a critic would not post it: still held
        k = self.job()
        fa = self.final(k)
        fb = self.final(k, "final-2.mp4")
        r = k / "review" / "round-1"
        for o in (1, 2):
            (r / ("order-%d" % o)).mkdir(parents=True)
            (r / ("order-%d" % o) / "FINDINGS.md").write_text("PREFERENCE: X\n", encoding="utf-8")
        (k / "review" / ".pairwise-keys").mkdir(parents=True)
        (k / "review" / ".pairwise-keys" / "round-1.json").write_text(json.dumps(
            {"new": {"label": "X", "video": str(fb)}, "old": {"label": "Y", "video": str(fa)}}), encoding="utf-8")
        (r / "verdict.json").write_text(json.dumps({"improved": True, "best": str(fb), "would_post": {
            "answer": "no", "reason": "player controls in the footage"}}), encoding="utf-8")
        s = review_state.state(k)
        self.assertEqual((s["status"], s["pending"]), ("would not post", True))
        self.assertIn("player controls", s["message"])
        # lean mode never holds on it
        m = self.job("--mode", "lean")
        fm = self.final(m)
        self.round(m, 1, "VERDICT: ship -- ok\nWOULD I POST THIS: no -- soft\n", video=fm)
        self.assertFalse(review_state.state(m)["pending"])

    def test_caption_should_fix_needs_an_answer(self):
        cs = review_state.caption_should_fixes
        text = ("VERDICT: ship after fixes -- captions\nWOULD I POST THIS: yes -- after the fix\nBLOCKERS:\n- none\n"
                "SHOULD-FIX:\n- t=4.00s frames/t0004.000s.jpg captions sit in two stepped boxes -> one plate\n"
                "- t=9.00s frames/t0009.000s.jpg the hook holds 3 s -> cut to 1.5 s\nPOLISH:\n- subtitles font -> Inter\n")
        self.assertEqual(len(cs(text)), 1)                                   # polish is not held
        self.assertTrue(review_state.resolves_captions("- fixed: the captions are one plate now"))
        self.assertTrue(review_state.resolves_captions("won't fix: the captions box style is the brand's"))
        self.assertFalse(review_state.resolves_captions("- not fixed: captions still stepped"))
        self.assertFalse(review_state.resolves_captions("won't fix: the hook"))       # names no captions
        j = self.job()
        f = self.final(j)
        r1 = self.round(j, 1, text, video=f)
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"]), ("caption fix open", True))
        self.assertIn("stepped boxes", s["message"])
        self.assertIn("RESPONSE.md", s["next"])
        # a later round that does not answer it keeps it open; "not fixed" is no answer
        g = self.final(j, "final-2.mp4")
        r2 = self.round(j, 2, "VERDICT: ship -- ok\nWOULD I POST THIS: yes -- ok\nPREVIOUS:\n- not fixed: captions\n",
                        video=g)
        self.assertEqual(review_state.state(j)["status"], "caption fix open")
        (r2 / "FINDINGS.md").write_text("VERDICT: ship -- ok\nWOULD I POST THIS: yes -- ok\nPREVIOUS:\n"
                                        "- fixed: captions in one plate\n", encoding="utf-8")
        self.assertEqual(review_state.state(j)["status"], "done")
        # the maker's explanation also closes it
        (r2 / "FINDINGS.md").write_text("VERDICT: ship -- ok\nWOULD I POST THIS: yes -- ok\n", encoding="utf-8")
        self.assertEqual(review_state.state(j)["status"], "caption fix open")
        (r1 / "RESPONSE.md").write_text("won't fix: the stepped caption boxes are the client's house style\n",
                                        encoding="utf-8")
        self.assertEqual(review_state.state(j)["status"], "done")
        # lean: a loud WARN, never pending
        m = self.job("--mode", "lean")
        fm = self.final(m)
        self.round(m, 1, text, video=fm)
        s = review_state.state(m)
        self.assertFalse(s["pending"])
        self.assertIn("caption should-fix", review_state.pending_line(s))

    def test_lean_is_never_pending(self):
        j = self.job("--mode", "lean")
        self.final(j)
        s = review_state.state(j)
        self.assertEqual((s["status"], s["pending"], s["required"]), ("lean", False, False))
        self.assertIsNone(review_state.pending_line(s))

    def test_deliver_note_warns(self):
        j = self.job()
        self.final(j)
        cp = self.st("job", "note", str(j), "--stage", "deliver", "--verified", "qa PASS")
        self.assertIn("WARN  review pending", cp.stderr)
        self.assertIn("delivered without the quality-mode critic round", cp.stderr)
        data = ledger.load(j)
        data["qa"] = {"verdict": "PASS", "video": str(j / "final.mp4"), "report": "qa.json"}
        self.assertIn("critic round is still open", ledger.suggest_next(j, data))
        k = self.job("--mode", "lean")
        self.final(k)
        self.assertNotIn("review pending", self.st("job", "note", str(k), "--stage", "deliver").stderr)

    def test_receipt_records_mode(self):
        j = self.job()
        self.final(j)
        rec = receipt.build(j)
        self.assertEqual(rec["review_mode"]["mode"], "quality")
        self.assertEqual(rec["review_mode"]["critic_round"], "pending")
        md = receipt.to_markdown(rec)
        self.assertIn("quick, quality review", md)
        self.assertIn("Critic round: review pending", md)
        k = self.job("--mode", "lean")
        self.final(k)
        rec = receipt.build(k)
        self.assertEqual((rec["review_mode"]["mode"], rec["review_mode"]["critic_round"]), ("lean", "lean"))
        self.assertIn("lean review", receipt.to_markdown(rec))


# ------------------------------------------------------------------ `showtime new --mode`

class TestNew(Base):
    def test_new_records_mode(self):
        j = self.job()
        proj = j / "project"
        self.st("new", "dom", str(proj), "--mode", "lean", "--duration", "4")
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["review_mode"], "lean")
        self.assertEqual(ledger.load(j)["review_mode"], "lean")
        # a job that records no mode of its own (a render made the folder) follows its project
        self.assertEqual(rm.job_mode({"project": str(proj)}), ("lean", "project"))


# ------------------------------------------------------------------ qa and deliver on a real file

@unittest.skipUnless(have_ffmpeg(), "ffmpeg is not installed (showtime setup)")
class TestQaLine(Base):
    @classmethod
    def setUpClass(cls):
        from st import ff
        cls.src_dir = Path(tempfile.mkdtemp(prefix="st-rmode-src-"))
        cls.src = cls.src_dir / "clip.mp4"
        cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                             "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=330:d=2",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.src)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        assert cp.returncode == 0, cp.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def job_with_final(self, *extra) -> Path:
        j = self.job(*extra)
        f = j / "final.mp4"
        shutil.copy2(self.src, f)
        ledger.note(j, outputs=["final=%s" % f], stage="render")
        return j

    def test_qa_says_review_pending(self):
        j = self.job_with_final()
        cp = self.st("qa", str(j), "--no-sheet", check=False)
        self.assertIn("WARN  review pending (quality mode)", cp.stdout)
        self.assertIn("showtime review-pack %s" % j.name, cp.stdout)
        rep = json.loads(self.st("qa", str(j), "--no-sheet", "--json", check=False).stdout)
        self.assertTrue(rep["review"]["pending"])
        verdict = rep["verdict"]
        self.assertEqual(cp.returncode, 1 if verdict == "FAIL" else 0, "review pending never changes qa's exit code")
        self.assertIn("VERDICT", cp.stdout.upper())
        # after a critic round with a verdict: no WARN line, a done line instead; the verdict is unchanged
        d = j / "review" / "round-1"
        d.mkdir(parents=True)
        (d / "FINDINGS.md").write_text("VERDICT: ship -- fine\nWOULD I POST THIS: yes -- fine\n", encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps({"video": str(j / "final.mp4")}), encoding="utf-8")
        out = self.st("qa", str(j), "--no-sheet", check=False).stdout
        self.assertNotIn("review pending", out)
        self.assertIn("review: review done: round-1 ship", out)
        self.assertEqual(json.loads(self.st("qa", str(j), "--no-sheet", "--json", check=False).stdout)["verdict"], verdict)

    def test_lean_and_loose_files_print_nothing(self):
        j = self.job_with_final("--mode", "lean")
        out = self.st("qa", str(j), "--no-sheet", check=False).stdout
        self.assertNotIn("review pending", out)
        self.assertNotIn("\nreview:", out)
        loose = self.tmp / "loose.mp4"
        shutil.copy2(self.src, loose)
        self.assertNotIn("review pending", self.st("qa", str(loose), "--no-sheet", check=False).stdout)

    def test_deliver_exports_warns(self):
        j = self.job_with_final()
        cp = self.st("deliver", "exports", str(j), "--targets", "chat", "--preview", check=False)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        self.assertIn("review pending", cp.stderr)
        self.assertIn("exported before the critic round", cp.stderr)


# ------------------------------------------------------------------ doctor and MCP

class TestSurfaces(Base):
    def test_doctor_json_names_mode(self):
        cp = self.st("doctor", "--quick", "--json", check=False, env={"SHOWTIME_MODE": "lean"})
        data = json.loads(cp.stdout)
        self.assertEqual((data["review_mode"]["mode"], data["review_mode"]["source"]), ("lean", "env"))

    def test_plugin_option(self):
        manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        opt = manifest["userConfig"]["mode"]
        self.assertEqual(opt["default"], "")
        self.assertIn("lean", opt["description"])
        self.assertEqual(manifest["mcpServers"]["showtime"]["env"]["SHOWTIME_OPT_MODE"], "${user_config.mode}")


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestMcp(Base):
    def mcp(self, steps, env):
        plan = {"server": str(SERVER), "cwd": str(self.tmp), "mode": "legacy", "env": env, "steps": steps}
        clean = {k: v for k, v in os.environ.items() if not k.startswith("SHOWTIME_OPT_") and k != "SHOWTIME_MODE"}
        cp = subprocess.run([NODE, str(CLIENT)], input=json.dumps(plan), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=240, env=clean)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        return json.loads(cp.stdout.strip().splitlines()[-1])

    def test_new_project_mode(self):
        env = {"SHOWTIME_SETTINGS": str(self.settings), "SHOWTIME_MCP_BASE": str(self.tmp)}
        out = self.mcp([{"method": "tools/list"},
                        {"method": "tools/call", "params": {"name": "new_project", "arguments": {
                            "template": "dom", "dir": "proj", "mode": "lean"}}, "timeout_ms": 120000},
                        {"method": "tools/call", "params": {"name": "new_project", "arguments": {
                            "template": "dom", "dir": "proj2", "mode": "cheap"}}, "timeout_ms": 120000}], env)
        tools = {t["name"]: t for t in out["results"][1]["response"]["result"]["tools"]}
        self.assertEqual(tools["new_project"]["inputSchema"]["properties"]["mode"]["enum"], ["quality", "lean"])
        self.assertIn("review pending", tools["qa"]["description"])
        self.assertIn("lean", tools["new_project"]["description"])
        cfg = json.loads((self.tmp / "proj" / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["review_mode"], "lean")
        bad = out["results"][3]["response"]
        self.assertTrue(bad.get("error") or (bad.get("result") or {}).get("isError"), bad)
        self.assertFalse((self.tmp / "proj2").exists())

    def test_settings_sync_keeps_config_mode(self):
        env = {"SHOWTIME_SETTINGS": str(self.settings), "SHOWTIME_MCP_BASE": str(self.tmp),
               "SHOWTIME_OPT_VOICE": "am_michael", "SHOWTIME_OPT_MODE": ""}
        rm.save_setting(rm.SETTING, "lean")                        # `showtime config mode lean`
        self.mcp([{"method": "ping"}], env)
        saved = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual((saved.get("voice"), saved.get("mode")), ("am_michael", "lean"))
        self.mcp([{"method": "ping"}], dict(env, SHOWTIME_OPT_MODE="quality"))   # the plugin option wins when set
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["mode"], "quality")
        self.mcp([{"method": "ping"}], env)                        # cleared in /config: the option's value goes
        self.assertNotIn("mode", json.loads(self.settings.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
