#!/usr/bin/env python3
"""Pairwise review: `showtime review-pack <job> --against <old>` and `showtime review-verdict`.

Fixture renders are ffmpeg test patterns (no browser). What is checked:
  * the rule: the new render wins only when both orders prefer it; a split or a tie keeps the old one;
  * FINDINGS.md parsing: PREFERENCE (an unfilled "X | Y | tie" is not an answer), per-video verdicts,
    findings need a video, a time and a frame (the rest are listed as dropped);
  * the pack: X and Y with frames at the same times (a card past the end of the shorter one), both cut
    strips, loudness plots, qa and narration transcripts, side-by-side sheets in both orders, two briefs
    (order-1 shows X first, order-2 Y first) with no scores; blind: no file names of the renders anywhere
    in the pack, the key sits outside it;
  * review-verdict: VERDICT.md, best.json, open findings of the best version, a missing order is an error;
  * rounds: --against best and round-N, at most 3 rounds, then "ship the best with its open findings".

Stdlib + ffmpeg. usage: python tests/test_pairwise.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
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

ENV = build_env(showtime_home())


def showtime(*args, check=True, timeout=300, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def fixture(path, dur, pattern, words):
    """A test-pattern render with one hard cut (to colour bars at half time), a tone, and its own caption
    sidecar (the narration transcript source)."""
    h = dur / 2.0
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                         "%s=s=320x180:r=30:d=%s" % (pattern, h), "-f", "lavfi", "-i",
                         "smptebars=s=320x180:r=30:d=%s" % h, "-f", "lavfi", "-i", "sine=f=330:d=%s" % dur,
                         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-af", "volume=7dB",
                         "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    Path(path).with_suffix(".srt").write_text("1\n00:00:00,200 --> 00:00:01,800\n%s\n" % words, encoding="utf-8")
    return Path(path)


def findings(pref, a, b, extra=""):
    return ("PREFERENCE: %s  -- clearer\nVERDICT %s: ship after fixes\nVERDICT %s: ship\n"
            "WHAT WORKS (max 3 per video, so it is kept):\n- [%s] the colour\n"
            "BLOCKERS:\n- [%s] t=1.00s ../%s/frames/t0001.000s.jpg  title cut off -> move it 40 px up\n"
            "SHOULD-FIX:\n- [%s] t=2.50s ../%s/frames/t0002.500s.jpg  type 2.1 %% of the height -> 3.5 %%\n"
            "- [%s] the pacing is off\nPOLISH:\n- (none)\n%sDECLINED TO JUDGE:\n- audio quality\n"
            "BEST POSTER FRAME: [%s] t=0.50s because\n" % (pref, a, b, a, a, a, b, b, b, extra, b))


class PairwiseRule(unittest.TestCase):
    def test_rule(self):
        from st.qa import pairwise as pw
        self.assertTrue(pw.decide("X", "X", "X")[0])
        self.assertTrue(pw.decide("Y", "Y", "Y")[0])
        for p1, p2 in (("X", "Y"), ("Y", "X"), ("tie", "tie"), ("X", "tie"), ("tie", "X"), ("Y", "Y")):
            self.assertFalse(pw.decide(p1, p2, "X")[0], (p1, p2))
        self.assertIn("split", pw.decide("X", "Y", "X")[1])
        self.assertIn("old preferred in both", pw.decide("Y", "Y", "X")[1])

    def test_parse(self):
        from st.qa import pairwise as pw
        p = pw.parse_findings(findings("Y", "X", "Y"))
        self.assertEqual(p["preference"], "Y")
        self.assertEqual(p["verdicts"], {"X": "ship after fixes", "Y": "ship"})
        self.assertEqual([(f["severity"], f["video"], f["t"]) for f in p["findings"]],
                         [("blocker", "X", 1.0), ("should-fix", "Y", 2.5)])
        self.assertEqual(p["dropped"], ["[Y] the pacing is off"])          # no time, no frame
        self.assertFalse(p["self_review"])
        self.assertIsNone(pw.parse_findings("PREFERENCE: X | Y | tie  -- one line\n")["preference"])
        self.assertEqual(pw.parse_findings("PREFERENCE: **tie** - cannot choose\n")["preference"], "tie")
        # a numbered item, and the video read from the frame path when the [X] tag is missing
        q = pw.parse_findings("PREFERENCE: X\nSHOULD-FIX:\n1. t=3s ../Y/frames/t0003.000s.jpg small -> bigger\n")
        self.assertEqual([(f["video"], f["t"]) for f in q["findings"]], [("Y", 3.0)])
        self.assertTrue(pw.parse_findings("SELF-REVIEW (no critic available)\nPREFERENCE: X\n")["self_review"])


class PairwisePack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-pw-"))
        cls.base = cls.tmp / "work"
        cls.base.mkdir()
        cls.job = Path(json.loads(showtime("job", "init", "pair-probe", "--json", cwd=cls.base).stdout)["job"])
        fixture(cls.job / "final.mp4", 3, "testsrc2", "narration line one")
        time.sleep(1.1)
        fixture(cls.job / "final-2.mp4", 4, "testsrc", "narration line two")
        showtime("job", "note", cls.job, "--output", "final=%s" % (cls.job / "final-2.mp4"), cwd=cls.base)
        (cls.job / "brief.md").write_text("A 4 second test card.\n", encoding="utf-8")
        (cls.job / "work").mkdir(exist_ok=True)
        (cls.job / "work" / "feedback.md").write_text("## Round 1\n1. fixed the title\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def pack(self, *extra):
        cp = showtime("review-pack", "pair-probe", *extra, "--json", cwd=self.base)
        m = json.loads(cp.stdout)
        return m, json.loads(Path(m["key"]).read_text(encoding="utf-8"))

    def answer(self, pack, key, p1, p2):
        """Write both orders' FINDINGS.md; p1/p2 are "new", "old" or "tie"."""
        lab = lambda p: key[p]["label"] if p in ("new", "old") else "tie"  # noqa: E731
        (pack / "order-1" / "FINDINGS.md").write_text(findings(lab(p1), "X", "Y"), encoding="utf-8")
        (pack / "order-2" / "FINDINGS.md").write_text(findings(lab(p2), "Y", "X"), encoding="utf-8")

    def test_1_pack_is_matched_and_blind(self):
        errs = showtime("review-pack", "pair-probe", "--against", self.job / "final-2.mp4", cwd=self.base, check=False)
        self.assertEqual(errs.returncode, 1)
        self.assertIn("same file", errs.stderr)
        self.assertIn("no such video", showtime("review-pack", "pair-probe", "--against", "nope.mp4", cwd=self.base,
                                                check=False).stderr)
        m, key = self.pack("--against", self.job / "final.mp4")
        pack = Path(m["dir"])
        self.assertEqual(pack.name, "round-1")
        self.assertEqual(Path(key["new"]["video"]).name, "final-2.mp4")
        self.assertEqual(Path(key["old"]["video"]).name, "final.mp4")
        self.assertEqual({key["new"]["label"], key["old"]["label"]}, {"X", "Y"})
        self.assertNotIn(pack.resolve(), Path(m["key"]).resolve().parents)
        for lab in ("X", "Y"):
            for name in ("sheet.jpg", "cuts.jpg", "loudness.png", "qa.txt", "transcript.txt"):
                self.assertTrue((pack / lab / name).is_file(), "%s/%s" % (lab, name))
        for name in ("compare-XY.jpg", "compare-YX.jpg", "order-1/CRITIC.md", "order-2/CRITIC.md", "manifest.json",
                     "context/brief.md"):
            self.assertTrue((pack / name).is_file(), name)
        self.assertFalse((pack / "context" / "feedback.md").exists(), "the fix log would say which is newer")
        self.assertFalse((pack / "INCOMPLETE").exists())
        # the same moments in both, and a card past the end of the 3 s render (not its last frame again)
        fx = sorted(p.name for p in (pack / "X" / "frames").glob("t*.jpg"))
        fy = sorted(p.name for p in (pack / "Y" / "frames").glob("t*.jpg"))
        self.assertEqual(fx, fy)
        self.assertIn("t0000.000s.jpg", fx)
        short = key["old"]["label"]
        late = [f for f in m["sides"][short]["frames"] if f["t"] > 3.05]
        self.assertTrue(late, m["sides"][short]["frames"])
        from PIL import Image
        with Image.open(late[0]["path"]) as im:
            self.assertEqual(im.size[0], 320)
        # transcripts from each render's own captions
        self.assertIn("narration line two", (pack / key["new"]["label"] / "transcript.txt").read_text(encoding="utf-8"))
        self.assertIn("narration line one", (pack / key["old"]["label"] / "transcript.txt").read_text(encoding="utf-8"))
        # blind: nothing in the pack names the renders
        for f in pack.rglob("*"):
            if f.suffix in (".md", ".txt", ".json"):
                self.assertNotIn("final", f.read_text(encoding="utf-8"), f)
        b1 = (pack / "order-1" / "CRITIC.md").read_text(encoding="utf-8")
        b2 = (pack / "order-2" / "CRITIC.md").read_text(encoding="utf-8")
        self.assertLess(b1.index("## Video X"), b1.index("## Video Y"))
        self.assertLess(b2.index("## Video Y"), b2.index("## Video X"))
        self.assertIn("compare-XY.jpg", b1)
        self.assertIn("compare-YX.jpg", b2)
        for b in (b1, b2):
            for word in ("PREFERENCE", "Blocker", "Should-fix", "Polish", "No scores", "DECLINED TO JUDGE",
                         "type detail pass", "timestamp and a frame path", "transcript"):
                self.assertIn(word, b)
            self.assertNotIn("1-10", b)
            self.assertIn("`../X/frames/t0000.000s.jpg`", b)
            self.assertNotIn(str(self.job), b)
        # not answered yet: the next pack rebuilds round 1 (new random labels, same round)
        m2, _ = self.pack("--against", self.job / "final.mp4")
        self.assertEqual(Path(m2["dir"]).name, "round-1")
        cp = showtime("review-verdict", "pair-probe", cwd=self.base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no answer for order 1", cp.stderr)

    def test_2_verdict_both_orders(self):
        root = self.job / "review"
        pack = root / "round-1"
        key = json.loads((root / ".pairwise-keys" / "round-1.json").read_text(encoding="utf-8"))
        self.answer(pack, key, "new", "new")
        v = json.loads(showtime("review-verdict", "pair-probe", "--json", cwd=self.base).stdout)
        self.assertTrue(v["improved"])
        self.assertEqual(Path(v["best"]).name, "final-2.mp4")
        self.assertTrue(v["blind"])
        self.assertEqual({f["role"] for f in v["open_findings"]}, {"new"})
        self.assertEqual(sorted(f["severity"] for f in v["open_findings"]), ["blocker", "should-fix"])
        self.assertEqual(len(v["dropped"]), 2)
        self.assertTrue((pack / "VERDICT.md").is_file())
        self.assertEqual(Path(json.loads((root / "best.json").read_text(encoding="utf-8"))["video"]).name, "final-2.mp4")
        led = json.loads((self.job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(led["pointers"]["review_verdict"]).resolve(), (pack / "VERDICT.md").resolve())
        # the same critic answers flipped with the order: a split, not an improvement; the old one stays best
        self.answer(pack, key, "new", "old")
        cp = showtime("review-verdict", pack, cwd=self.base)
        self.assertIn("NOT AN IMPROVEMENT", cp.stdout)
        v = json.loads(showtime("review-verdict", pack, "--json", cwd=self.base).stdout)
        self.assertFalse(v["improved"])
        self.assertIn("split", v["reason"])
        self.assertEqual(Path(v["best"]).name, "final.mp4")
        self.assertEqual({f["role"] for f in v["open_findings"]}, {"old"})
        self.assertFalse(v["cap_reached"])
        (pack / "order-2" / "FINDINGS.md").write_text("PREFERENCE: X | Y | tie\n", encoding="utf-8")
        cp = showtime("review-verdict", pack, cwd=self.base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("PREFERENCE", cp.stderr)
        self.answer(pack, key, "tie", "tie")
        self.assertFalse(json.loads(showtime("review-verdict", pack, "--json", cwd=self.base).stdout)["improved"])

    def test_3_rounds_stop_at_three(self):
        root = self.job / "review"
        # round 2: a newer render against the best so far (final.mp4 after the tie)
        time.sleep(1.1)
        fixture(self.job / "final-3.mp4", 4, "testsrc2", "the third narration line")
        showtime("job", "note", self.job, "--output", "final=%s" % (self.job / "final-3.mp4"), cwd=self.base)
        m, key = self.pack("--against", "best")
        self.assertEqual(Path(m["dir"]).name, "round-2")
        self.assertEqual(Path(key["old"]["video"]).name, "final.mp4")
        self.assertEqual(Path(key["new"]["video"]).name, "final-3.mp4")
        self.answer(Path(m["dir"]), key, "new", "new")
        v = json.loads(showtime("review-verdict", "pair-probe", "--json", cwd=self.base).stdout)
        self.assertEqual((v["round"], v["improved"], Path(v["best"]).name), (2, True, "final-3.mp4"))
        # round 3: against round-2's video (the new one of that round)
        time.sleep(1.1)
        fixture(self.job / "final-4.mp4", 4, "testsrc", "the fourth narration line")
        showtime("job", "note", self.job, "--output", "final=%s" % (self.job / "final-4.mp4"), cwd=self.base)
        m, key = self.pack("--against", "round-2")
        self.assertEqual(Path(key["old"]["video"]).name, "final-3.mp4")
        self.answer(Path(m["dir"]), key, "old", "old")
        v = json.loads(showtime("review-verdict", "pair-probe", "--json", cwd=self.base).stdout)
        self.assertFalse(v["improved"])
        self.assertTrue(v["cap_reached"])
        self.assertEqual(Path(v["best"]).name, "final-3.mp4")
        self.assertIn("ship final-3.mp4 with its open findings", v["next"])
        self.assertIn("blockers are open", v["next"])
        best = json.loads((root / "best.json").read_text(encoding="utf-8"))
        self.assertEqual([h["round"] for h in best["history"]], [1, 2, 3])
        cp = showtime("review-pack", "pair-probe", "--against", "best", cwd=self.base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("stops at 3", cp.stderr)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped),
                                                      time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
