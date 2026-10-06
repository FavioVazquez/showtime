#!/usr/bin/env python3
"""The hearing pass (st.qa.hearing): measurements on small synthetic mixes, qa's hearing WARNs at the right
times, and the review pack's hearing material.

The mix is built in numpy: a speech-like voice (band-passed noise in syllables, words 0.3 s long) and a
chord bed, 20 s, with planted problems:
  - line "clear" (1.0-4.7 s): the bed 16 dB under the voice                   -> fine
  - line "buried" (5.2-8.9 s): the bed only ~2 dB under it (it rose at 4.8 s) -> voice_masked at 5.2 s
  - 10.6-13.2 s: no voice, the bed at -44 dBFS (not silence: qa's silent_gap is under -50) -> quiet_stretch
  - the cut at 15.0 s: the bed jumps from -30 to -20 dB (no voice)            -> level_jump at 15.0 s
  - the bed plays at full level to the last frame                             -> abrupt_end
The render's narration stem (work/audio/mix.voice.wav, 16 kHz), its render.json, a mix report with an
effect and the project's voice/timeline.json sit where a showtime render leaves them.

Stdlib + the showtime venv (numpy, scipy). usage: python tests/test_hearing.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402

SR = 48000
DUR = 20.0
CUT = 15.0
LINES = [("clear", 1.0, "the clear line sits well over the music bed here", -30.0),
         ("buried", 5.2, "this line is buried under a loud music bed now", -18.0)]


def _db(v):
    return 10 ** (v / 20.0)


def make_mix(seed=7):
    """(programme stereo, voice mono, bed mono, timeline lines) at 48 kHz."""
    import numpy as np
    from scipy import signal
    rng = np.random.default_rng(seed)
    n = int(DUR * SR)
    t = np.arange(n) / SR
    sos = signal.butter(4, [250, 3500], btype="band", fs=SR, output="sos")
    voice = np.zeros(n)
    tl = []
    for lid, start, text, _ in LINES:
        words = []
        a = start
        for w in text.split():
            k0, k1 = int(a * SR), int((a + 0.3) * SR)
            env = np.sin(np.pi * np.arange(k1 - k0) / (k1 - k0)) ** 0.5
            voice[k0:k1] += signal.sosfilt(sos, rng.normal(0, 1, k1 - k0)) * env
            words.append({"text": w, "start": round(a, 3), "end": round(a + 0.3, 3)})
            a += 0.38
        tl.append({"id": lid, "text": text, "start": start, "end": words[-1]["end"], "speech_start": start,
                   "speech_end": words[-1]["end"], "words": words})
    act = np.abs(voice) > 0
    voice *= _db(-16) / np.sqrt((voice[act] ** 2).mean())          # the voice speaks at about -16 dBFS RMS
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6)) + 0.05 * rng.normal(0, 1, n)
    chord /= np.sqrt((chord ** 2).mean())
    # bed level (dBFS RMS) over time, with 50 ms ramps
    pts = [(0.0, -32.0), (4.8, -32.0), (4.95, -18.0), (9.0, -18.0), (9.2, -30.0), (10.6, -30.0), (10.65, -44.0),
           (13.2, -44.0), (13.25, -30.0), (CUT, -30.0), (CUT + 0.05, -20.0), (DUR, -20.0)]
    env = np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
    bed = chord * 10 ** (env / 20.0)
    prog = voice + bed
    return np.stack([prog, prog], axis=1).astype(np.float32), voice.astype(np.float32), bed.astype(np.float32), tl


def ffmpeg(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def build_render(root: Path, with_stem: bool = True):
    """A finished render as showtime leaves it: <out>/final.mp4, render.json, work/audio/ (stem, mix report),
    and the project with showtime.json (scenes) and voice/timeline.json. Returns (video, project)."""
    import numpy as np
    from scipy import signal
    from st.audio import wav
    prog, voice, _, tl = make_mix()
    proj, out = root / "project", root / "out"
    (proj / "voice").mkdir(parents=True)
    (out / "work" / "audio").mkdir(parents=True)
    (out / "work" / "logs").mkdir(parents=True)
    (proj / "showtime.json").write_text(json.dumps({"duration": DUR, "scenes": [0, 10, CUT]}), encoding="utf-8")
    (proj / "voice" / "timeline.json").write_text(json.dumps({"lines": tl}), encoding="utf-8")
    old = time.time() - 60
    os.utime(proj / "voice" / "timeline.json", (old, old))
    wav.save(root / "mix.wav", prog, sr=SR, bits=24)
    video = out / "final.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=%g" % DUR, "-i", root / "mix.wav", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-ar", "48000", "-shortest", "-movflags", "+faststart", video)
    log = out / "work" / "logs" / "render.log"
    log.write_text("", encoding="utf-8")
    (out / "render.json").write_text(json.dumps({"ok": True, "output": str(video), "project": str(proj), "log": str(log),
                                                 "duration": DUR, "range": [0, DUR]}), encoding="utf-8")
    if with_stem:
        v16 = signal.resample_poly(voice.astype(np.float64), 1, 3).astype(np.float32)
        wav.save(out / "work" / "audio" / "mix.voice.wav", v16, sr=16000, bits=16)
    (out / "work" / "audio" / "mix.report.json").write_text(json.dumps({
        "schema": "showtime.mix.report/1", "voice_to_music_db": 9.0,
        "tracks": [{"id": "bed", "kind": "music", "start": 0.0, "end": DUR, "catalog_id": "test-bed"},
                   {"id": "voice", "kind": "voice", "start": 0.0, "end": DUR},
                   {"id": "whoosh", "kind": "sfx", "synth": {"type": "whoosh"}, "aligned": {"at": 10.3, "align": "hit"},
                    "start": 10.1, "end": 10.6, "above_bed_db": -3.0}]}), encoding="utf-8")
    return video, proj


class HearingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-hearing-"))
        cls.video, cls.proj = build_render(cls.tmp / "stem")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_split_and_measure(self):
        """The stem splits voice from bed; the buried line is masked, the clear one is not; the silence, the
        jump at the cut and the cut-off ending are measured where they were planted."""
        from st.audio import wav
        from st.qa import hearing
        x = wav.load(self.video)
        blk = hearing.blocks(x, SR, self.video)
        self.assertTrue(blk.get("voice") and blk.get("bed"), blk.get("voice_note"))
        self.assertGreater(blk["fit"]["corr"], 0.5, blk["fit"])
        self.assertLess(abs(blk["fit"]["lag_ms"]), 5.0, blk["fit"])          # AAC keeps the voice in sync
        lines, src = hearing.speech_lines(self.video, self.proj)
        self.assertEqual(src, "the voice timeline")
        self.assertEqual([ln["id"] for ln in lines], ["clear", "buried"])
        h = hearing.measure(blk, DUR, lines=lines, lines_source=src, cuts=[10.0, CUT],
                            scenes=[(0, 10, "a"), (10, CUT, "b"), (CUT, DUR, "c")],
                            mix=hearing.mix_facts(json.loads((self.video.parent / "work" / "audio" / "mix.report.json")
                                                             .read_text(encoding="utf-8")), 0.0, DUR),
                            loud={"integrated_lufs": -17.0, "silent_gaps": []})
        by = {r["id"]: r for r in h["lines"]}
        self.assertEqual(by["clear"]["method"], "stem")
        self.assertGreater(by["clear"]["voice_over_bed_db"], 12.0, by["clear"])
        self.assertLess(by["buried"]["voice_over_bed_db"], 5.0, by["buried"])
        self.assertIn("masked", by["buried"]["flags"])
        self.assertNotIn("masked", by["clear"]["flags"])
        self.assertTrue(140 <= by["clear"]["wpm"] <= 170, by["clear"])         # 10 words in 3.72 s
        q = [s for s in h["quiet"] if not s["silent"]]
        self.assertEqual(len(q), 1, h["quiet"])
        self.assertAlmostEqual(q[0]["start"], 10.6, delta=0.25)
        self.assertAlmostEqual(q[0]["end"], 13.2, delta=0.25)
        jumps = {j["t"]: j for j in h["cuts"]}
        self.assertTrue(jumps[CUT]["flagged"], jumps[CUT])
        self.assertEqual(jumps[CUT]["kind"], "bed")
        self.assertAlmostEqual(jumps[CUT]["jump"], 10.0, delta=1.5)
        self.assertFalse(jumps[10.0]["flagged"], jumps[10.0])               # -30 -> -30 (the quiet starts at 10.6)
        self.assertTrue(h["ending"]["abrupt"], h["ending"])
        fx = h["sfx"][0]
        self.assertEqual(fx["t"], 10.3)
        self.assertIn("under the rest of the mix", fx["flags"])
        self.assertEqual(fx["nearest_cut"], 10.0)
        self.assertIn("0.30s after the cut at 10.00s", fx["flags"])

    def test_02_estimate_without_stem(self):
        """No stem: the bed is estimated from the pauses next to each line (marked estimate); qa never warns on it."""
        from st.audio import wav
        from st.qa import hearing
        video, proj = build_render(self.tmp / "nostem", with_stem=False)
        blk = hearing.blocks(wav.load(video), SR, video)
        self.assertNotIn("voice", blk)
        lines, src = hearing.speech_lines(video, proj)
        h = hearing.measure(blk, DUR, lines=lines, lines_source=src, cuts=[CUT], loud={"integrated_lufs": -17.0})
        by = {r["id"]: r for r in h["lines"]}
        self.assertEqual(by["buried"]["method"], "estimate")
        self.assertLess(by["buried"]["voice_over_bed_db"], 6.0, by["buried"])
        self.assertGreater(by["clear"]["voice_over_bed_db"], 10.0, by["clear"])

        class F:
            items = []

            def add(self, rule, sev, msg, **kw):
                self.items.append(rule)
        f = F()
        hearing.check(f, h)
        self.assertNotIn("voice_masked", f.items)
        self.assertIn("level_jump", f.items)          # like with like without a stem: no speech on either side

    def test_03_qa_warns_with_times(self):
        """`showtime qa` turns the hearing checks into WARNs at the planted times and keeps the block levels."""
        from st.qa import video as qa_video
        rep = qa_video.run(self.video, out_dir=self.tmp / "qa", sheet=False, quiet=True, record=False)
        got = {}
        for f in rep["findings"]:
            got.setdefault(f["rule"], []).append(f)
        self.assertIn("voice_masked", got, rep["findings"])
        self.assertEqual([round(f["t"], 1) for f in got["voice_masked"]], [5.2])
        self.assertIn("quiet_stretch", got, rep["findings"])
        self.assertAlmostEqual(got["quiet_stretch"][0]["t"], 10.6, delta=0.25)
        self.assertIn("level_jump", got, rep["findings"])
        self.assertEqual([f["t"] for f in got["level_jump"]], [CUT])
        self.assertIn("abrupt_end", got, rep["findings"])
        self.assertAlmostEqual(got["abrupt_end"][0]["t"], DUR - 0.25, delta=0.1)
        self.assertTrue(all(f["severity"] == "WARN" for r in ("voice_masked", "quiet_stretch", "level_jump", "abrupt_end")
                            for f in got[r]))
        self.assertIn("summary", rep["hearing"])
        lj = json.loads((self.tmp / "qa" / "loudness.json").read_text(encoding="utf-8"))
        self.assertEqual(len(lj["blocks"]["programme"]), int(DUR * 10))
        self.assertIn("bed", lj["blocks"])
        json.dumps(rep)                                    # no arrays left in the report

    def test_04_fades_and_steady_beds_stay_quiet(self):
        """A bed that fades out at the end and holds one level across its cuts raises none of the hearing WARNs."""
        import numpy as np
        from st.audio import wav
        from st.qa import video as qa_video
        d = self.tmp / "calm"
        d.mkdir()
        t = np.arange(int(8 * SR)) / SR
        bed = 0.2 * sum(np.sin(2 * np.pi * f * t) for f in (220.0, 330.0)) * np.clip((8 - t) / 1.2, 0, 1)
        wav.save(d / "bed.wav", np.stack([bed, bed], axis=1).astype(np.float32), sr=SR, bits=24)
        v = d / "calm.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=8", "-i", d / "bed.wav", "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", v)
        rep = qa_video.run(v, out_dir=d / "qa", sheet=False, quiet=True, record=False)
        rules = {f["rule"] for f in rep["findings"]}
        self.assertFalse(rules & {"voice_masked", "quiet_stretch", "level_jump", "abrupt_end"}, rep["findings"])
        self.assertFalse(rep["hearing"]["ending"]["abrupt"], rep["hearing"]["ending"])

    def test_04b_lines_where_the_mix_plays_them(self):
        """Timeline times are vo.wav times: a mix that plays each line's own file (or a vo-<id> track) somewhere
        else moves the line there, for the hearing pass and the pack's transcript alike."""
        from st.qa import hearing, review
        proj = self.tmp / "placed"
        (proj / "voice" / "lines").mkdir(parents=True)
        (proj / "audio").mkdir()
        (proj / "voice" / "lines" / "01-a.wav").write_bytes(b"")
        (proj / "showtime.json").write_text(json.dumps({"duration": 8, "audio": "audio/mix.json"}), encoding="utf-8")
        (proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [
            {"kind": "voice", "file": "../voice/lines/01-a.wav", "start": 3.0},
            {"kind": "voice", "id": "vo-b", "file": "../voice/lines/02-b.wav", "start": 6.0}]}), encoding="utf-8")
        (proj / "voice" / "timeline.json").write_text(json.dumps({"file": "vo.wav", "lines": [
            {"id": "a", "text": "one two three", "start": 0.5, "speech_start": 0.6, "speech_end": 1.4, "file": "lines/01-a.wav",
             "words": [{"text": "one", "start": 0.6, "end": 0.9}, {"text": "two", "start": 0.95, "end": 1.1},
                       {"text": "three", "start": 1.15, "end": 1.4}]},
            {"id": "b", "text": "four", "start": 2.0, "speech_start": 2.1, "speech_end": 2.5, "file": "lines/02-b.wav"}]}),
            encoding="utf-8")
        old = time.time() - 60
        os.utime(proj / "voice" / "timeline.json", (old, old))
        video = proj / "final.mp4"
        video.write_bytes(b"x")
        lines, _ = hearing.speech_lines(video, proj)
        self.assertEqual([(ln["id"], ln["start"], ln["end"]) for ln in lines], [("a", 3.1, 3.9), ("b", 6.1, 6.5)])
        self.assertAlmostEqual(lines[0]["spans"][0][0], 3.1)
        cues, _ = review.narration(video, proj)
        self.assertEqual([round(a, 3) for a, _, _ in cues], [3.1, 6.1])

    def test_05_review_pack_has_the_hearing_material(self):
        """review-pack writes audio.txt and hearing.png, CRITIC.md carries the hearing pass and asks for HEARING
        lines; the findings gate reads audio findings under the usual severities and skips the HEARING lines."""
        from st.job import findings
        from st.qa import review
        m = review.build(self.video, out=self.tmp / "review", quiet=True)
        pack = Path(m["dir"])
        txt = (pack / "audio.txt").read_text(encoding="utf-8")
        self.assertTrue((pack / "hearing.png").is_file())
        self.assertEqual(Path(m["hearing"]["text"]).name, "audio.txt")
        for want in ("buried", "masked", "JUMP", "STILL PLAYING", "whoosh", "the voice timeline",
                     "Voice and music measured apart"):
            self.assertIn(want, txt)
        brief = (pack / "CRITIC.md").read_text(encoding="utf-8")
        for want in ("Hearing pass", "`audio.txt`", "`hearing.png`", "cannot listen", "HEARING (", "DECLINED TO JUDGE"):
            self.assertIn(want, brief)
        # HEARING lines after the findings (a critic may reorder the sections): never counted as findings
        ans = ("VERDICT: ship after fixes -- the buried line\nWOULD I POST THIS: no -- the music drowns line 2\n"
               "BLOCKERS:\n- none\nSHOULD-FIX:\n- t=5.20s hearing.png  music masks the buried line (+2 dB) -> duck 15 dB\n"
               "HEARING (one line per check):\n- voice over music: problem -- buried +2 dB\n- pace: ok -- 160 wpm\n"
               "POLISH:\n- none\n")
        parsed = findings.parse(ans, "r1")
        self.assertEqual([(f["id"], f["severity"]) for f in parsed], [("r1-S1", "should-fix")])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped), time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
