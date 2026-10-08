#!/usr/bin/env python3
"""Footage module smoke tests (about 1-2 minutes).

Builds a synthetic "talking" clip: speech with fillers (um/uh) synthesised
locally with Kokoro through `showtime voice say` (falls back to the voice
Python API, then to tone bursts with a synthetic transcript), over a test
pattern with two hard scene changes. Then drives the real CLI:

- transcribe (small.en): words, fillers kept, ids, timing vs Kokoro's exact
  word times; cache hit on re-run; silent track refused with a clear error
- pack -> takes_packed.md; scenes -> both cuts found
- edit cut (fillers + long pauses) -> EDL; edit check -> frame-exact plan
- edit render 9:16 preview with bold-pop captions: frame count == plan,
  duration, loudness -14 +-1 LUFS, true peak <= -1 (+0.3)
- edit render 16:9 with an alpha PNG overlay, auto grade + look, a music bed
  (ducked) and clean captions: same checks
- captions: every displayed word is on screen while spoken, groups never
  overlap, the caption font is a real TTF libass loads
- re-transcribe the 16:9 render (from the speech stem the render kept, since it
  has a music bed): no fillers left, word times match the EDL mapping (mean
  error < 120 ms)
- the default model (Parakeet v3, when already downloaded): fillers kept, timing
- unit checks: cut algebra, frame plan without drift at 29.97 fps, caption
  grouping rules, WOFF/WOFF2 -> TTF conversion

usage: python tests/test_footage.py [--fast] [-v]   (--fast skips the re-transcription QA)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TEXT = ("So, um, today I want to show you something new. [pause 0.9] Uh, it's a tool that edits video "
        "by reading the transcript. [pause 1.2] Um, the best part is that everything runs on your own computer. "
        "[pause 0.8] Uh, no cloud, and no accounts.")


def st(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def js(*args, **kw):
    cp = st(*args, **kw)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        raise AssertionError("not JSON from showtime %s:\n%s\n%s" % (" ".join(map(str, args)), cp.stdout[-2000:],
                                                                     cp.stderr[-2000:]))


def ffmpeg():
    from st import ff
    return ff.ffmpeg_path()


def ffrun(args):
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + [str(a) for a in args],
                   check=True)


def bare(t: str) -> str:
    return re.sub(r"\W", "", t.lower())


def match_words(ref, got):
    """In-order text matching (longest common subsequence blocks) -> list of (ref_word, got_word).

    A word only one side has (a filler one transcript keeps and the other drops) must not throw the
    rest out of step, which a greedy walk does when that word comes first."""
    import difflib
    a = [bare(w["text"]) for w in ref]
    b = [bare(w["text"]) for w in got]
    pairs = []
    for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        pairs += [(ref[i + k], got[j + k]) for k in range(n)]
    return pairs


class FootageTest(unittest.TestCase):
    tmp: Path
    speech_kind = "kokoro"

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-footage-"))
        cls.t0 = time.time()
        speech = cls.tmp / "speech.wav"
        cls.speech_words = None
        cp = st("voice", "say", TEXT, "-v", "am_michael", "-o", speech, "--json", check=False)
        if cp.returncode != 0 or not speech.is_file():
            try:
                from st.voice import tts
                tts.synthesize(TEXT, voice="am_michael").save(speech)
            except Exception as e:  # noqa: BLE001 - no Kokoro: tone bursts + synthetic transcript
                cls.speech_kind = "tones"
                print("note: Kokoro unavailable (%s); using tone bursts" % e, file=sys.stderr)
                cls._tone_speech(speech)
        side = speech.with_name("speech.words.json")
        if side.is_file():
            cls.speech_words = json.loads(side.read_text(encoding="utf-8"))["words"]
        dur = float(json.loads(st("footage", "probe", speech).stdout)["duration"])
        cls.duration = dur
        cls.video = cls.tmp / "talk.mp4"
        a = 5.0
        b = 5.0
        c = max(1.0, dur - a - b + 0.2)
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=%.3f" % a, "-f", "lavfi",
               "-i", "smptebars=s=640x360:r=30:d=%.3f" % b, "-f", "lavfi",
               "-i", "mandelbrot=s=640x360:r=30,trim=duration=%.3f" % c, "-i", speech,
               "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]", "-map", "[v]", "-map", "3:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "160k", "-shortest",
               cls.video])
        cls.edit = cls.tmp / "edit"

    @classmethod
    def _tone_speech(cls, path: Path):
        import numpy as np
        import soundfile as sf
        sr = 48000
        words, t, _out = [], 0.3, []
        rng = np.random.default_rng(3)
        for k, w in enumerate(re.sub(r"\[pause [\d.]+\]", "", TEXT).split()):
            d = 0.12 + 0.04 * len(w)
            words.append({"text": w, "start": round(t, 3), "end": round(t + d, 3), "type": "word"})
            t += d + (0.5 if w.endswith(".") else 0.08)
        x = np.zeros(int((t + 0.5) * sr), np.float32)
        for w in words:
            a, b = int(w["start"] * sr), int(w["end"] * sr)
            n = np.arange(b - a) / sr
            x[a:b] += 0.3 * np.sin(2 * np.pi * (140 + 60 * rng.random()) * n) * np.hanning(b - a)
        sf.write(str(path), x, sr)
        path.with_name("speech.words.json").write_text(json.dumps({"words": words}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        print("footage tests: %.1fs (speech: %s)" % (time.time() - cls.t0, cls.speech_kind), file=sys.stderr)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def transcript(self):
        p = self.edit / "transcripts" / "talk.json"
        if not p.is_file():
            if self.speech_kind == "tones":
                src = json.loads(self.tmp.joinpath("speech.words.json").read_text(encoding="utf-8"))
                doc = {"source": str(self.video), "duration": self.duration, "language": "en", "model": "synthetic",
                       "words": src["words"]}
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(doc), encoding="utf-8")
            else:
                st("transcribe", self.video, "--model", "small.en", "--no-events", "--edit-dir", self.edit)
        return json.loads(p.read_text(encoding="utf-8"))

    def check_render(self, rep, lufs=-14.0):
        self.assertTrue(rep["frames_ok"], "frame count %s != %s" % (rep["frames"], rep["expected_frames"]))
        self.assertEqual(rep["frames"], rep["expected_frames"])
        self.assertAlmostEqual(rep["video_duration"], rep["duration"], delta=1.0 / 30 + 1e-3)
        lo = rep["loudness"]
        self.assertAlmostEqual(lo["integrated_lufs"], lufs, delta=1.0, msg="loudness %s" % lo)
        self.assertLessEqual(lo["true_peak_dbtp"], -0.7, "true peak %s" % lo)

    # ------------------------------------------------------------------ tests
    def test_01_transcribe(self):
        if self.speech_kind == "tones":
            self.skipTest("no Kokoro speech on this machine")
        t0 = time.time()
        cp = st("transcribe", self.video, "--model", "small.en", "--no-events", "--json", "--force")
        res = json.loads(cp.stdout)
        # the fixed model-load cost is announced, then progress over seconds of audio (P6)
        self.assertRegex(cp.stderr, r"loading model small\.en \(first run can take ~\d+s\)")
        self.assertIn("transcribing (s of audio)", cp.stderr)
        self.assertGreaterEqual(res["words"], 30)
        self.assertGreaterEqual(res["fillers"], 3, "fillers must be kept verbatim")
        self.assertEqual(res["language"], "en")
        doc = self.transcript()
        words = [w for w in doc["words"] if w["type"] == "word"]
        self.assertTrue(all(w.get("id", "").startswith("w") for w in words))
        self.assertTrue(all(0 <= w["start"] < w["end"] <= doc["duration"] + 1e-3 for w in words))
        self.assertTrue(any(w["type"] == "spacing" for w in doc["words"]))
        if self.speech_words:
            pairs = match_words(self.speech_words, words)
            self.assertGreaterEqual(len(pairs), 0.85 * len(self.speech_words))
            mae = statistics.mean(abs(a["start"] - b["start"]) for a, b in pairs)
            print("transcribe: %d words, start MAE vs Kokoro %.0f ms, %.1fs" % (len(words), 1000 * mae,
                                                                                 time.time() - t0), file=sys.stderr)
            self.assertLess(mae, 0.15)
        # cached: second run is fast and identical
        t1 = time.time()
        res2 = js("transcribe", self.video, "--model", "small.en", "--no-events", "--json")
        self.assertEqual(res2["words"], res["words"])
        self.assertLess(time.time() - t1, 20)

    def test_01c_transcribe_default_parakeet(self):
        """The default model (Parakeet v3, verbatim) keeps the fillers and times words like Whisper does."""
        if self.speech_kind == "tones":
            self.skipTest("no Kokoro speech on this machine")
        from st.footage import asr_models
        if not asr_models.present("parakeet-v3"):
            self.skipTest("Parakeet v3 not downloaded here (fetched on first use; tests never download)")
        ed = self.tmp / "edit-pk"
        res = js("transcribe", self.video, "--no-events", "--json", "--edit-dir", ed, "--force")
        self.assertIn("parakeet-tdt-0.6b-v3", res["model"])
        self.assertGreaterEqual(res["words"], 30)
        self.assertGreaterEqual(res["fillers"], 3, "Parakeet writes um/uh as words")
        self.assertIsNotNone(res.get("filler_scan"))
        self.assertEqual(res["audio_from"], "source")
        self.assertFalse((res.get("separation") or {}).get("applied"), "clean speech is never separated")
        doc = json.loads(Path(res["transcript"]).read_text(encoding="utf-8"))
        words = [w for w in doc["words"] if w["type"] == "word"]
        if self.speech_words:
            pairs = match_words(self.speech_words, words)
            self.assertGreaterEqual(len(pairs), 0.85 * len(self.speech_words))
            mae = statistics.mean(abs(a["start"] - b["start"]) for a, b in pairs)
            print("parakeet: %d words, %d fillers, start MAE vs Kokoro %.0f ms" % (len(words), res["fillers"], 1000 * mae),
                  file=sys.stderr)
            self.assertLess(mae, 0.15)

    def test_01b_transcribe_range(self):
        if self.speech_kind == "tones":
            self.skipTest("no Kokoro speech on this machine")
        full = [w for w in self.transcript()["words"] if w["type"] == "word"]
        ed = self.tmp / "edit-range"
        a, b = 4.0, min(12.0, self.duration - 1.0)
        res = js("transcribe", self.video, "--model", "small.en", "--no-events", "--json", "--edit-dir", ed,
                 "--from", "0:04", "--to", "%g" % b)
        path = Path(res["transcript"])
        self.assertEqual(path.name, "talk.4-%s.json" % ("%.2f" % b).rstrip("0").rstrip("."))
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["range"][0], a)
        self.assertAlmostEqual(doc["range"][1], b, delta=0.05)
        self.assertAlmostEqual(doc["duration"], b, delta=0.05)   # the source's clock, not the range length
        words = [w for w in doc["words"] if w["type"] == "word"]
        self.assertGreaterEqual(len(words), 5)
        self.assertTrue(all(a - 0.05 <= w["start"] < w["end"] <= b + 0.05 for w in words), words[:3])
        # the same words at the same (offset) times as the whole-file transcript
        pairs = match_words([w for w in full if a - 0.5 <= w["start"] <= b + 0.5], words)
        self.assertGreaterEqual(len(pairs), 0.6 * len(words))
        self.assertLess(statistics.median(abs(x["start"] - y["start"]) for x, y in pairs), 0.15)
        # cached per range: the same range is instant, another range is a new transcript
        t1 = time.time()
        again = js("transcribe", self.video, "--model", "small.en", "--no-events", "--json", "--edit-dir", ed,
                   "--from", "4", "--to", "%g" % b)
        self.assertLess(time.time() - t1, 20)
        self.assertEqual(again["words"], res["words"])
        other = js("transcribe", self.video, "--model", "small.en", "--no-events", "--json", "--edit-dir", ed,
                   "--from", "1", "--to", "4")
        self.assertNotEqual(Path(other["transcript"]).name, path.name)
        self.assertLessEqual(max(w["end"] for w in json.loads(Path(other["transcript"]).read_text(encoding="utf-8"))["words"]
                                 if w["type"] == "word"), 4.05)
        pk = Path(js("pack", ed, "--json")["output"]).read_text(encoding="utf-8")
        self.assertIn("(part)", pk)
        # a plan from a range transcript keeps nothing outside the range
        from st.footage import cuts
        keep = cuts.plan_keep(doc)["keep"]
        self.assertGreaterEqual(keep[0][0], a - 0.3)
        self.assertLessEqual(keep[-1][1], b + 1e-3)
        bad = st("transcribe", self.video, "--model", "small.en", "--from", "5", "--to", "3", check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--from must be before --to", bad.stderr)

    def test_02_silent_refused(self):
        clip = self.tmp / "silent.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=160x120:r=10:d=2", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
               "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip])
        cp = st("transcribe", clip, "--model", "small.en", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("silent", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)

    def test_03_pack_and_scenes(self):
        self.transcript()
        out = js("pack", self.edit, "--json")
        text = Path(out["output"]).read_text(encoding="utf-8")
        self.assertRegex(text, r"\[\d{3}\.\d\d-\d{3}\.\d\d w\d+-w\d+\] S0 ")
        self.assertGreaterEqual(out["phrases"], 3)
        sc = js("footage", "scenes", self.video, "--json", "-o", self.tmp / "scenes")
        starts = [s["start"] for s in sc["scenes"]]
        self.assertTrue(any(abs(t - 5.0) < 0.2 for t in starts), starts)
        self.assertTrue(any(abs(t - 10.0) < 0.2 for t in starts), starts)
        self.assertTrue(Path(sc["sheet"]).is_file())

    def test_04_cut_and_render_vertical(self):
        tr = self.transcript()
        edl = self.edit / "edl.json"
        res = js("edit", "cut", self.edit / "transcripts" / "talk.json", "--max-pause", "0.5", "--captions",
                 "bold-pop", "--aspect", "9:16", "-o", edl, "--overwrite", "--json")
        self.assertLess(res["after"], res["before"] - 1.0)
        doc = json.loads(edl.read_text(encoding="utf-8"))
        fillers = [w for w in tr["words"] if w["type"] == "word" and bare(w["text"]) in ("um", "uh", "umm")]
        for f in fillers:        # no kept range may contain a filler's midpoint
            mid = (f["start"] + f["end"]) / 2
            self.assertFalse(any(r["start"] <= mid <= r["end"] for r in doc["ranges"]), f)
        chk = js("edit", "check", edl, "--json")
        self.assertEqual(len(chk["segments"]), len(doc["ranges"]))
        rep = js("edit", "render", edl, "--preview", "--json", "--overwrite")
        self.assertEqual((rep["width"], rep["height"]), (720, 1280))
        self.check_render(rep)
        self.assertEqual(rep["captions"]["style"], "bold-pop")
        self.assertEqual(rep["captions"]["timing"]["words_outside_group"], 0)
        self.assertEqual(rep["captions"]["timing"]["overlaps"], 0)
        self.assertTrue(Path(rep["captions"]["font_file"]).suffix.lower() in (".ttf", ".otf"))
        self.check_ass(Path(rep["captions"]["ass"]), edl, Path(rep["report"]))
        views = js("edit", "view", edl, "--video", rep["output"], "--json")
        self.assertTrue(views["pages"] and all(Path(p).is_file() for p in views["pages"]))

    def check_ass(self, ass: Path, edl: Path, report: Path):
        """Every displayed (non-filler) output word is on screen while it is spoken."""
        from st.footage import edl as E
        from st.footage import util as U
        text = ass.read_text(encoding="utf-8")
        self.assertIn("PlayResX:", text)
        ev = []
        for m in re.finditer(r"^Dialogue: \d+,(\d+):(\d\d):(\d\d\.\d\d),(\d+):(\d\d):(\d\d\.\d\d),", text, re.M):
            a = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            b = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6))
            ev.append((a, b))
        self.assertTrue(ev)
        ed = E.load(edl)
        rep = json.loads(report.read_text(encoding="utf-8"))
        segs = [dict(s, start=s["src_start"]) for s in rep["segments"]]
        words = [w for w in E.map_words(segs, E.load_transcripts(ed), include_events=False)
                 if not U.is_filler(w["text"])]
        missing = [w["text"] for w in words
                   if not any(a - 0.011 <= (w["start"] + w["end"]) / 2 <= b + 0.011 for a, b in ev)]
        self.assertFalse(missing, "words never on screen while spoken: %s" % missing)

    def test_05_render_landscape_overlay_music(self):
        self.transcript()
        from PIL import Image, ImageDraw
        logo = self.tmp / "logo.png"
        im = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle([4, 4, 196, 76], radius=16, fill=(255, 140, 0, 230))
        im.save(logo)
        bed = self.tmp / "bed.wav"
        ffrun(["-f", "lavfi", "-i", "aevalsrc=0.2*sin(2*PI*220*t)+0.15*sin(2*PI*277*t)+0.12*sin(2*PI*330*t):s=48000:d=30",
               "-ac", "2", bed])
        edl = self.edit / "edl169.json"
        st("edit", "cut", self.edit / "transcripts" / "talk.json", "--max-pause", "0.5", "--captions", "clean",
           "--grade", "auto", "--music", bed, "-o", edl, "--overwrite")
        doc = json.loads(edl.read_text(encoding="utf-8"))
        doc["output"] = {"aspect": "16:9", "height": 540}
        doc["grade"] = {"auto": True, "lut": "teal-orange", "strength": 0.5}
        doc["overlays"] = [{"file": str(logo), "start": 0.5, "duration": 3.0, "position": "top-right",
                            "width": "20%", "fade": 0.3}]
        doc["audio"]["music"] = {"file": str(bed), "gain_db": -6}
        edl.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        out = self.edit / "final169.mp4"
        rep = js("edit", "render", edl, "-o", out, "--json", "--overwrite")
        self.assertEqual((rep["width"], rep["height"]), (960, 540))
        self.check_render(rep)
        self.assertEqual(rep["warnings"], [])
        # logo visible (orange pixels in the top-right corner) at t = 1.5 s
        png = self.tmp / "frame.png"
        ffrun(["-ss", "1.5", "-i", out, "-frames:v", "1", png])
        px = Image.open(png).convert("RGB").getpixel((960 - 40, 45))
        self.assertTrue(px[0] > 180 and 60 < px[1] < 190 and px[2] < 110, px)
        # the final is fully tagged BT.709 (primaries and transfer too, not only the matrix)
        from st import ff as _ff
        vi = _ff.probe(out)
        self.assertEqual((vi.get("color_primaries"), vi.get("color_transfer")), ("bt709", "bt709"), vi)
        if rep["audio"].get("voice_to_music_db") is not None:
            self.assertGreater(rep["audio"]["voice_to_music_db"], 6)
        self.__class__.landscape = rep

    def test_06_output_matches_edl(self):
        if FAST or self.speech_kind == "tones":
            self.skipTest("--fast or no speech")
        rep = getattr(self.__class__, "landscape", None)
        if not rep:
            self.skipTest("landscape render missing")
        from st.footage import edl as E
        qa = self.tmp / "qa"
        st("transcribe", rep["output"], "--model", "small.en", "--no-events", "--edit-dir", qa, "--force")
        qdoc = json.loads((qa / "transcripts" / "final169.json").read_text(encoding="utf-8"))
        # the render has a music bed: transcription reads the speech stem the render kept, not the mix
        self.assertTrue(str(qdoc.get("audio_from", "")).endswith("program.wav"), qdoc.get("audio_from"))
        got = [w for w in qdoc["words"] if w["type"] == "word"]
        self.assertFalse([w["text"] for w in got if bare(w["text"]) in ("um", "uh", "umm", "uhm")],
                         "fillers left in the edit")
        ed = E.load(rep["edl"])
        segs = [dict(s, start=s["src_start"]) for s in rep["segments"]]
        mapped = [w for w in E.map_words(segs, E.load_transcripts(ed), include_events=False)
                  if bare(w["text"]) not in ("um", "uh", "umm", "uhm")]
        pairs = match_words(mapped, got)
        self.assertGreaterEqual(len(pairs), 0.9 * len(mapped))
        err = [b["start"] - a["start"] for a, b in pairs]
        mae = statistics.mean(abs(e) for e in err)
        print("edit QA: %d/%d words matched, start MAE %.0f ms" % (len(pairs), len(mapped), 1000 * mae),
              file=sys.stderr)
        self.assertLess(mae, 0.12)

    # ------------------------------------------------------------------ unit checks
    def test_07_units(self):
        from st.footage import captions as C
        from st.footage import cuts
        from st.footage import edl as E
        from st.footage import fontfiles as F
        words = []
        t = 0.0
        for i, w in enumerate("So um this is uh the plan. And then we ship it.".split()):
            words.append({"id": "w%d" % i, "text": w, "start": round(t, 3), "end": round(t + 0.25, 3), "type": "word"})
            t += 0.3 if w != "plan." else 1.6
        tr = {"duration": t + 0.5, "language": "en", "words": words}
        plan = cuts.plan_keep(tr, max_pause=0.5)
        kept_ids = {w["id"] for w in words if any(a <= (w["start"] + w["end"]) / 2 <= b for a, b in plan["keep"])}
        self.assertNotIn("w1", kept_ids)          # um
        self.assertNotIn("w4", kept_ids)          # uh
        self.assertIn("w2", kept_ids)
        self.assertEqual(len([r for r in plan["removed"] if r["why"] == "filler"]), 2)
        for a, b in plan["keep"]:                 # never cut inside a kept word
            for w in words:
                if w["id"] in kept_ids:
                    self.assertFalse(a < w["start"] < b < w["end"] or w["start"] < a < w["end"] < b, (a, b, w))
        # frame plan: 40 odd-length ranges at 29.97 fps never drift
        fps = Fraction(30000, 1001)
        ed = {"output": {"fps": fps}, "ranges": [{"source": "a", "start": i * 1.0, "end": i * 1.0 + 0.4567 + 0.01 * i}
                                                 for i in range(40)]}
        segs = E.plan(ed)
        total_frames = sum(s["frames"] for s in segs)
        self.assertAlmostEqual(segs[-1]["out_end"], float(Fraction(total_frames) / fps), places=9)
        self.assertEqual(sum(s["audio_samples"] for s in segs), int(round(float(Fraction(total_frames) / fps) * 48000)))
        # caption grouping: sentence end breaks, no group over the word cap, timing inside groups
        st_ = C.get_style("bold-pop")
        groups = C.group_words(C.display_words(words), st_, "portrait")
        self.assertTrue(all(len(g["words"]) <= 3 for g in groups))
        self.assertTrue(any(g["words"][-1]["text"] == "plan." for g in groups))
        chk = C.check_timing(groups, C.display_words(words))
        self.assertEqual((chk["words_outside_group"], chk["overlaps"], chk["words_missing"]), (0, 0, 0))
        # hallucination guards: text over silence and repetition loops are dropped
        import numpy as np
        from st.footage import transcribe as T
        sr = 16000
        audio = np.zeros(sr * 5, np.float32)
        audio[: sr * 2] = 0.3 * np.sin(2 * np.pi * 180 * np.arange(sr * 2) / sr)
        toks = [{"text": w, "start": 0.1 + 0.25 * i, "end": 0.3 + 0.25 * i, "type": "word", "seg": 0, "conf": 0.9}
                for i, w in enumerate(["the"] * 7)]
        toks.append({"text": "Thank you.", "start": 3.5, "end": 4.2, "type": "word", "seg": 1, "conf": 0.3})
        report = {"dropped": [], "warnings": [], "respread": 0}
        kept = T.guard(toks, audio, sr, 5.0, report)
        self.assertEqual([w["text"] for w in kept], ["the", "the"])
        self.assertEqual({d["reason"] for d in report["dropped"]},
                         {"repetition loop", "no speech energy"})
        # fonts: WOFF (zlib) and WOFF2 (brotli + glyf transform) become loadable TTFs
        from PIL import ImageFont
        for fam in ("anton", "inter"):
            f = F.find_font(fam)
            self.assertTrue(f.path.is_file() and f.family)
            ImageFont.truetype(str(f.path), 24).getbbox("Quick brown fox")


class CaptionRulesTest(unittest.TestCase):
    """S6: `showtime captions` writes what `showtime qa` accepts (shared limits in st.captions_rules), karaoke is one
    event per group, sidecars are called optional when the video already burns captions; P2 reframe upscale note."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-capr-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def words(step, text=None):
        text = text or ("Sunlight is a stream of photons, and solar panels turn them into electricity for your home. "
                        "Every rooftop installation can power a household, cutting bills at the same time.")
        out, t = [], 0.1
        for w in text.split():
            out.append({"text": w, "start": round(t, 3), "end": round(t + step * 0.8, 3), "type": "word"})
            t += step + (0.4 if w.endswith(".") else 0)
        return out, t

    def test_rules_match_qa(self):
        from st import captions_rules as R
        from st.qa import captions as Q
        srt = self.tmp / "r.srt"

        def rules(text, dur, w, h):
            srt.write_text("1\n00:00:00,000 --> %s\n%s\n" % ("00:00:%02d,%03d" % (int(dur), round(dur % 1 * 1000)), text),
                           encoding="utf-8")
            return {f["rule"] for f in Q.check(Q.parse(srt), 30, w, h)}
        for (w, h) in ((1080, 1920), (1920, 1080), (1080, 1350)):
            n = R.max_line_chars(w, h)
            self.assertEqual(n, 32 if h > w else 42)
            self.assertNotIn("caption_line_long", rules("ab " * (n // 3) + "x" * (n - 3 * (n // 3)), 5, w, h))
            self.assertIn("caption_line_long", rules("x" * (n + 1), 5, w, h))
        text = "one two three four five"          # 23 characters
        self.assertNotIn("caption_fast", rules(text, R.min_seconds(text), 1920, 1080))
        self.assertIn("caption_fast", rules(text, len(text) / (R.MAX_CPS + 1.5), 1920, 1080))
        self.assertFalse(R.too_fast("two words", 0.1))   # qa exempts 1-2 word flashes

    def test_captions_pass_qa(self):
        from st.footage import captions as C
        from st.qa import captions as Q
        bad = []
        for step in (0.22, 0.4):
            words, end = self.words(step)
            for style in C.STYLES:
                for (w, h) in ((1080, 1920), (1920, 1080), (1080, 1350)):
                    rep = C.build(words, self.tmp / "c.ass", style=style, width=w, height=h, srt=self.tmp / "c.srt",
                                  vtt=self.tmp / "c.vtt")
                    t = rep["timing"]
                    if t["words_missing"] or t["words_outside_group"] or t["overlaps"]:
                        bad.append((step, style, w, h, t))
                    for f in ("c.ass", "c.srt", "c.vtt"):
                        found = Q.check(Q.parse(self.tmp / f), end + 1, w, h)
                        # 4.5 words/s (step 0.22) cannot be read at 20 characters/s: an honest caption_fast is
                        # expected there; what must never happen is flashes (cues split into 1-word blinks)
                        if step < 0.3:
                            found = [x for x in found if x["rule"] != "caption_fast"]
                        if found:
                            bad.append((step, style, w, h, f, [x["message"] for x in found]))
        self.assertEqual(bad, [])

    def test_srt_keeps_cues_flashes_merge_and_cuts(self):
        """02/03/04/06: restyling a hand-balanced .srt keeps its cues and line breaks in the ASS and the
        sidecar alike; fast speech is never split into sub-flash cues; a cue that starts just after a cut
        starts on the cut; lines do not end on a function word."""
        from st.footage import captions as C
        from st.footage import util as U
        from st.qa import captions as Q
        src = self.tmp / "hand.srt"
        src.write_text("1\n00:00:01,000 --> 00:00:03,500\nThe refrigerant absorbs heat\nand turns into a gas.\n\n"
                       "2\n00:00:03,600 --> 00:00:05,000\nThen it is squeezed.\n", encoding="utf-8")
        tr = U.load_transcript(src)
        rep = C.build(tr["words"], self.tmp / "hand.ass", style="clean", width=1920, height=1080,
                      srt=self.tmp / "hand.out.srt", options={"fillers": True})
        self.assertTrue(rep.get("kept_cues"))
        self.assertEqual(rep["groups"], 2)
        out = Q.parse(self.tmp / "hand.out.srt")["cues"]
        self.assertEqual([(round(c["start"], 2), round(c["end"], 2)) for c in out], [(1.0, 3.5), (3.6, 5.0)])
        self.assertEqual(out[0]["lines"], ["The refrigerant absorbs heat", "and turns into a gas."])
        # fast speech: no cue under the flash limit in the sidecar or the clean burn-in
        words, end = self.words(0.16, "we really want to make sure that the thing you want is the thing you get today")
        rep = C.build(words, self.tmp / "f.ass", style="clean", width=1920, height=1080, srt=self.tmp / "f.srt")
        for f in ("f.ass", "f.srt"):
            cues = Q.parse(self.tmp / f)["cues"]
            self.assertGreaterEqual(min(c["end"] - c["start"] for c in cues), 0.4, (f, cues))
        # a cue starting 0.2 s after a cut starts on the cut; the previous one ends there
        g = [{"words": [{"text": "a", "start": 1.0, "end": 1.9}], "start": 1.0, "end": 2.3},
             {"words": [{"text": "b", "start": 2.25, "end": 2.8}], "start": 2.2, "end": 3.0}]
        self.assertEqual(C.snap_to_cuts(g, [2.0]), 1)
        self.assertEqual((g[0]["end"], g[1]["start"]), (2.0, 2.0))
        # "the" never ends a line when a better break exists
        texts = "We checked every panel on the roof before noon".split()
        rows = C.split_lines(texts, 42, 2)
        self.assertNotEqual(texts[rows[0][-1]].lower(), "the")

    def test_edl_caption_override_and_missing_subtitles(self):
        """06: `edit render --captions clean` on an EDL with bold-pop/middle starts from clean's own
        defaults (no mid-frame subtitles), and an EDL may name a subtitles file that is not written yet
        when loaded with check_files=False (render still requires it)."""
        from st.footage import edl as E
        clip = self.tmp / "ovr.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-pix_fmt", "yuv420p", clip])
        doc = {"sources": {"a": str(clip)}, "ranges": [{"source": "a", "start": 0, "end": 1.5}],
               "captions": {"style": "bold-pop", "position": "middle", "srt": True}, "subtitles": "later.ass"}
        ep = self.tmp / "ovr.edl.json"
        ep.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(Exception):
            E.load(ep)
        ed = E.load(ep, check_files=False)
        self.assertEqual(ed["captions"]["position"], "middle")
        ed = E.load(ep, check_files=False, overrides={"captions": {"style": "clean"}})
        self.assertEqual(ed["captions"]["style"], "clean")
        self.assertNotEqual(ed["captions"].get("position"), "middle")
        self.assertTrue(ed["captions"].get("srt"))

    def test_karaoke_one_event_per_group(self):
        from st import ff
        from st.footage import captions as C
        words, _ = self.words(0.4, "Sunlight is a stream of photons.")
        ass = self.tmp / "k.ass"
        rep = C.build(words, ass, style="bold-pop", width=360, height=640)
        events = [ln for ln in ass.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue:")]
        self.assertEqual(len(events), rep["groups"])
        self.assertTrue(any("\\t(" in e for e in events))
        # the highlight really moves: word 1 then word 2 of the first group is the yellow one
        g0 = C.group_words(C.display_words(words), dict(C.get_style("bold-pop"), chars=18), "portrait")[0]
        self.assertGreaterEqual(len(g0["words"]), 2)
        from PIL import Image
        xs = []
        for i, t in enumerate(((g0["words"][0]["start"] + g0["words"][0]["end"]) / 2,
                               (g0["words"][1]["start"] + g0["words"][1]["end"]) / 2)):
            png = self.tmp / ("k%d.png" % i)
            vf = "ass=filename=%s:fontsdir=%s" % (ff.filter_path(rep["ass"]), ff.filter_path(rep["fontsdir"]))
            ffrun(["-f", "lavfi", "-i", "color=c=0x202020:s=360x640:d=4", "-vf", vf, "-ss", "%.3f" % t, "-frames:v", "1", png])
            im = Image.open(png).convert("RGB")
            px = [(x, y) for y in range(0, 640, 2) for x in range(0, 360, 2)
                  if (lambda p: p[0] > 200 and p[1] > 180 and p[2] < 90)(im.getpixel((x, y)))]
            self.assertTrue(px, "no highlighted word at %.2fs" % t)
            xs.append(sum(x for x, _ in px) / len(px))
        self.assertGreater(xs[1], xs[0] + 10, xs)

    def test_burned_captions_note(self):
        from st.footage import captions as C
        job = self.tmp / "demo-20260926-120000"
        proj = job / "project"
        (proj / "voice").mkdir(parents=True)
        (job / "job.json").write_text(json.dumps({"slug": "demo", "pointers": {}}), encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 1080, "height": 1920, "duration": 5}), encoding="utf-8")
        (proj / "index.html").write_text('<div data-st="caption-karaoke" data-src="voice/vo.words.json"></div>',
                                         encoding="utf-8")
        words, _ = self.words(0.35, "Sunlight is photons from the sun.")
        tr = proj / "voice" / "vo.words.json"
        tr.write_text(json.dumps({"language": "en", "duration": 4, "words": words}), encoding="utf-8")
        cp = st("captions", tr, "-o", job / "captions.ass", "--srt", job / "final.srt", "--aspect", "9:16")
        self.assertIn("already burns captions", cp.stderr)
        self.assertIn("caption-karaoke", cp.stderr)
        self.assertIn("optional", cp.stderr)
        plain = self.tmp / "plain.words.json"      # a transcript unrelated to any burning project
        shutil.copy2(str(tr), str(plain))
        cp = st("captions", plain, "-o", self.tmp / "elsewhere.ass", "--aspect", "9:16")
        self.assertNotIn("already burns captions", cp.stderr)
        # the transcript alone (context) finds the project; intermediates under work/ never warn
        self.assertIn("caption-karaoke", C.burned_captions(tr) or "")
        rep = C.build(words, job / "work" / "x" / "captions.ass", style="clean", width=1080, height=1920)
        self.assertNotIn("burned_elsewhere", rep)
        rep = C.build(words, self.tmp / "y.ass", style="clean", width=1080, height=1920, context=[tr])
        self.assertIn("burned_elsewhere", rep)
        edl = self.tmp / "edl.json"
        edl.write_text(json.dumps({"sources": {}, "ranges": [], "captions": {"style": "bold-pop"}}), encoding="utf-8")
        self.assertIn("bold-pop", C.burned_captions(edl) or "")
        edl.write_text(json.dumps({"sources": {}, "ranges": [], "captions": None}), encoding="utf-8")
        self.assertIsNone(C.burned_captions(edl))

    def test_captions_cli_context_and_job_pointer(self):
        """ROUND3: `showtime captions` passes its inputs as context (the burned note fires with -o outside the job)
        and a sidecar written inside a job becomes the job's latest captions (what qa <job> checks)."""
        base = self.tmp / "ptr"
        base.mkdir()
        job = Path(js("job", "init", "capptr", "--base", base, "--json")["job"])
        proj = job / "project"
        (proj / "voice").mkdir(parents=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 1080, "height": 1920, "duration": 5}), encoding="utf-8")
        (proj / "index.html").write_text('<div data-st="caption-karaoke" data-src="voice/vo.words.json"></div>',
                                         encoding="utf-8")
        words, _ = self.words(0.35, "Sunlight is photons from the sun.")
        tr = proj / "voice" / "vo.words.json"
        tr.write_text(json.dumps({"language": "en", "duration": 4, "words": words}), encoding="utf-8")
        # -o outside the job: only the transcript (context) links the files to the burning project
        cp = st("captions", tr, "-o", self.tmp / "outside" / "subs.ass", "--aspect", "9:16")
        self.assertIn("already burns captions", cp.stderr)
        self.assertIn("sidecars optional", cp.stderr)
        rep = js("captions", tr, "-o", self.tmp / "outside" / "subs2.ass", "--aspect", "9:16", "--json")
        self.assertIn("caption-karaoke", rep.get("burned_elsewhere") or "")
        self.assertIsNone(rep.get("job"))
        # an .srt inside the job is recorded as the job's latest captions
        rep = js("captions", tr, "-o", job / "captions.ass", "--srt", job / "final.srt", "--aspect", "9:16", "--json")
        self.assertEqual(Path(rep["job"]).resolve(), job.resolve())
        outs = json.loads((job / "job.json").read_text(encoding="utf-8"))["outputs"]
        self.assertEqual(Path(outs["captions"]).resolve(), (job / "final.srt").resolve())
        # an .ass alone is not a sidecar for delivery: no pointer change
        js("captions", tr, "-o", job / "other.ass", "--aspect", "9:16", "--json")
        outs = json.loads((job / "job.json").read_text(encoding="utf-8"))["outputs"]
        self.assertEqual(Path(outs["captions"]).name, "final.srt")

    def test_captions_text_scale(self):
        """18: --text-scale multiplies the style's font size (the line cap shrinks with it) and is range-checked."""
        words, _ = self.words(0.3, "It was the beginning of the rout of civilisation.")
        tr = self.tmp / "scale.words.json"
        tr.write_text(json.dumps({"language": "en", "duration": 4, "words": words}), encoding="utf-8")

        def fontsize(ass):
            line = [l for l in Path(ass).read_text(encoding="utf-8").splitlines() if l.startswith("Style:")][0]
            return int(line.split(",")[2])
        js("captions", tr, "--style", "cinematic", "--size", "1920x1080", "-o", self.tmp / "s1.ass", "--json")
        js("captions", tr, "--style", "cinematic", "--size", "1920x1080", "--text-scale", "1.2",
           "-o", self.tmp / "s2.ass", "--json")
        a, b = fontsize(self.tmp / "s1.ass"), fontsize(self.tmp / "s2.ass")
        self.assertAlmostEqual(b / a, 1.2, delta=0.03)
        cp = st("captions", tr, "--text-scale", "9", "-o", self.tmp / "s3.ass", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("--text-scale", cp.stderr)

    def test_edl_render_reports_upscale_once(self):
        """ROUND3: render_edl asks plan_crop not to announce (its own _upscale_info reports the upscale into the
        render report), and the burn itself never triggers the burned-captions note."""
        src = (SKILL / "lib" / "st" / "footage" / "render_edl.py").read_text(encoding="utf-8")
        # every call (cover/reframe and the cards' panel framing, each with its no-tracking fallback) is quiet
        self.assertEqual(src.count("R.plan_crop("), 4)
        self.assertEqual(src.count("announce=False"), src.count("R.plan_crop("))
        self.assertIn("burned_note=False", src)

    def test_edit_check_near_contiguous_ranges(self):
        """06: two ranges of one source that overlap (or miss) by less than a frame are reported with the
        exact start to use."""
        from st.footage import edl as E
        segs = [{"i": 1, "source": "a", "start": 10.0, "src_end": 47.46}, {"i": 2, "source": "a", "start": 47.45, "src_end": 50.0},
                {"i": 3, "source": "a", "start": 50.02, "src_end": 52.0}, {"i": 4, "source": "b", "start": 0.0, "src_end": 1.0}]
        probs = E.join_problems(segs, 30)
        self.assertEqual(len(probs), 2)
        self.assertIn("overlap by 10 ms", probs[0])
        self.assertIn("start #2 at 47.460000", probs[0])
        self.assertIn("gap", probs[1])

    def test_punch_in_bounce_flagged(self):
        """Benchmark r1 (filler cut): zoom 1.12 on alternate ranges made the frame punch in and straight back
        out at every jump cut, and the viewer disliked it. `edit check` / `edit render` now say so; one held
        scale, a single punch-in, reframe-only splits and plain cuts stay quiet."""
        from st.footage import edl as E

        def segs(zooms, contiguous=False):
            out, t = [], 0.0
            for i, z in enumerate(zooms):
                start = t if contiguous else t + 0.5          # a gap = a jump cut (words removed)
                out.append({"i": i, "source": "a", "start": start, "src_end": start + 3.0, "zoom": z})
                t = start + 3.0
            return out
        bounce = E.punch_bounce(segs([1.0, 1.12, 1.0, 1.12, 1.0, 1.12, 1.0, 1.0, 1.12]), 30)
        self.assertEqual(len(bounce), 1)
        self.assertIn("bouncing zoom", bounce[0])
        self.assertIn("7 of 8 cuts", bounce[0])
        self.assertEqual(E.punch_bounce(segs([1.0] * 9), 30), [])                          # the default: no punch-ins
        self.assertEqual(E.punch_bounce(segs([1.0, 1.0, 1.0, 1.08, 1.08, 1.08, 1.08]), 30), [])  # one held change
        self.assertEqual(E.punch_bounce(segs([1.0, 1.15, 1.0, 1.15, 1.0], contiguous=True), 30), [])  # reframe splits
        src = (SKILL / "lib" / "st" / "footage" / "render_edl.py").read_text(encoding="utf-8")
        self.assertIn("E.punch_bounce(segs", src)                                           # render warns too

    def test_upscale_unavoidable_and_accepted(self):
        """06: 1080p -> 1080x1920 says the upscale is unavoidable (720x1280 is the standard size at 1.5x)
        instead of suggesting a non-platform size; output.allow_upscale accepts it (no warning)."""
        from types import SimpleNamespace
        from st.footage import render_edl as RE
        warns = []
        ctx = SimpleNamespace(full_w=1080, full_h=1920, edl={"output": {}}, warn=warns.append)
        info = RE._upscale_info({"source": "talk"}, "reframe", 1920, 1080, 1.1, ctx)
        self.assertGreater(info["factor"], 1.5)
        self.assertIn("unavoidable", info["fix"])
        self.assertIn("720", info["fix"])
        self.assertTrue(warns)
        warns.clear()
        ctx.edl = {"output": {"allow_upscale": True}}
        info = RE._upscale_info({"source": "talk"}, "reframe", 1920, 1080, 1.1, ctx)
        self.assertTrue(info.get("accepted"))
        self.assertEqual(warns, [])

    def test_reframe_upscale_note(self):
        from st.footage import reframe as RF
        # 06: the camera starts where the face settles (median of the first second), not at the first detection
        c = RF.smooth([(0.473, 0.4, 1.0)] + [(0.503, 0.4, 1.0)] * 40)
        self.assertAlmostEqual(c[20][0], 0.503, places=3)
        note = RF.upscale_note("talk.mp4", 1280, 720, 1080, 1920)
        self.assertIn("2.67x", note)
        self.assertIn("540x960", note)
        self.assertIn("720x1280", RF.upscale_note("a.mp4", 1920, 1080, 1080, 1920))
        self.assertIsNone(RF.upscale_note("a.mp4", 3840, 2160, 1080, 1920))
        self.assertIsNone(RF.upscale_note("a.mp4", 1920, 1080, 1280, 720))
        plan = RF.plan_crop("talk.mp4", 0, 0, 1280, 720, 1080, 1920, 30.0, 3, track=False, announce=False)
        self.assertAlmostEqual(plan["upscale"], 2.667, places=2)
        self.assertIn("soft", plan["warning"])
        plan = RF.plan_crop("big.mp4", 0, 0, 3840, 2160, 1080, 1920, 30.0, 3, track=False, announce=False)
        self.assertNotIn("warning", plan)


class LatestRenderTest(unittest.TestCase):
    """B3: re-cuts and re-renders never overwrite, print the file they wrote, and `edit view` follows the
    newest render (not a fixed final.mp4/preview.mp4); inside a job, job.json "outputs" tracks them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-footage-latest-")).resolve()
        cls.env = dict(ENV)
        cls.env.pop("SHOWTIME_OUT", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_st(self, *args, cwd=None, check=True):
        cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=self.env, cwd=str(cwd or self.tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        if check and cp.returncode != 0:
            raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                         cp.stdout[-2000:], cp.stderr[-2000:]))
        return cp

    def test_latest_render_and_pointers(self):
        clip = self.tmp / "clip.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=f=300:d=3:sample_rate=48000",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip])
        job = Path(json.loads(self.run_st("job", "init", "cut-latest", "--json").stdout)["job"])
        tdir = job / "edit" / "transcripts"
        tdir.mkdir(parents=True)
        words, t = [], 0.2
        for i, w in enumerate("hello um this is a test uh of cuts".split()):
            words.append({"id": "w%d" % i, "text": w, "start": round(t, 3), "end": round(t + 0.2, 3), "type": "word"})
            t += 0.3
        tr = tdir / "clip.json"
        tr.write_text(json.dumps({"source": str(clip), "duration": 3.0, "language": "en", "model": "synthetic",
                                  "words": words}), encoding="utf-8")
        edl = job / "edit" / "edl.json"
        # edit cut: a re-cut writes edl-2.json, says so, prints the path; --overwrite replaces edl.json
        self.run_st("edit", "cut", tr, "-o", edl)
        cp = self.run_st("edit", "cut", tr, "-o", edl)
        self.assertEqual(cp.stdout.strip(), str(job / "edit" / "edl-2.json"))
        self.assertIn("edl.json exists; writing edl-2.json", cp.stderr)
        self.assertIn("wrote %s" % (job / "edit" / "edl-2.json"), cp.stderr)
        led = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(led["outputs"]["edl"]).name, "edl-2.json")
        cp = self.run_st("edit", "cut", tr, "-o", edl, "--overwrite")
        self.assertEqual(cp.stdout.strip(), str(edl))
        self.assertFalse((job / "edit" / "edl-3.json").exists())
        # edit render <job name>: the job's latest EDL (edl.json again, after the --overwrite re-cut)
        cp = self.run_st("edit", "render", "cut-latest", "--preview")
        self.assertIn("using %s (latest edl)" % edl, cp.stderr)
        first = Path(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(first, job / "edit" / "preview.mp4")
        # a second preview never overwrites: preview-2.mp4, announced and printed
        cp = self.run_st("edit", "render", edl, "--preview")
        second = Path(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(second.name, "preview-2.mp4")
        self.assertIn("preview.mp4 exists; writing preview-2.mp4", cp.stderr)
        self.assertIn("--overwrite", cp.stderr)
        led = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(led["outputs"]["preview"]).name, "preview-2.mp4")
        # edit view <edl> follows the newest render, and says which
        cp = self.run_st("edit", "view", edl, "--json")
        self.assertIn("using %s (latest render of edl.json)" % second, cp.stderr)
        pages = json.loads(cp.stdout)["pages"]
        self.assertTrue(pages and all(Path(p).is_file() for p in pages))
        self.assertTrue(all("preview-2" in Path(p).name for p in pages), pages)
        # --overwrite re-renders preview.mp4 in place; now that is the newest render
        cp = self.run_st("edit", "render", edl, "--preview", "--overwrite")
        self.assertEqual(Path(cp.stdout.strip().splitlines()[-1]), first)
        self.assertFalse((job / "edit" / "preview-3.mp4").exists())
        cp = self.run_st("edit", "view", edl)
        self.assertIn("using %s (latest render" % first, cp.stderr)
        # no EDL at all: the newest edit render around the current folder (here: inside the job)
        cp = self.run_st("edit", "view", cwd=job)
        self.assertIn("using %s (latest render of edl.json)" % first, cp.stderr)
        cp = self.run_st("footage", "view", "--edl", edl)
        self.assertIn("(latest render of edl.json)", cp.stderr)
        # an explicit --video still wins
        cp = self.run_st("edit", "view", edl, "--video", second)
        self.assertNotIn("latest render", cp.stderr)
        # nothing rendered anywhere: a clear error, not a traceback
        empty = self.tmp / "empty"
        empty.mkdir()
        cp = self.run_st("edit", "view", cwd=empty, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no edit render found", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)

    def test_trim_and_scene_ranges(self):
        """05/06/10: `footage trim` cuts a range (frame-accurate) and makes seek-friendly proxies (--width,
        short GOP, --webm) without raw ffmpeg; `footage scenes --every` takes --from/--to and a file -o."""
        root = self.tmp / "trim"
        root.mkdir()
        clip = root / "clip.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=f=300:d=3:sample_rate=48000",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip])
        r = json.loads(self.run_st("footage", "trim", clip, "--from", "0.5", "--to", "2", "--width", "160",
                                   "-o", root / "cut.mp4", "--json").stdout)
        self.assertAlmostEqual(r["duration"], 1.5, delta=0.1)
        self.assertEqual(r["width"], 160)
        self.assertEqual(r["gop_frames"], 15)
        r = json.loads(self.run_st("footage", "trim", clip, "--webm", "--no-audio", "-o", root / "cut.webm", "--json").stdout)
        self.assertEqual(r["codec"], "vp9")
        self.assertTrue(Path(r["output"]).is_file())
        cp = self.run_st("footage", "scenes", clip, "--every", "0.25", "--from", "1", "--to", "2", "-o", root / "dense.png",
                         "--json")
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["sheet"]), root / "dense.png")
        self.assertEqual(rep["frames"], 4)
        self.assertAlmostEqual(rep["step"], 0.25, places=3)
        cp = self.run_st("footage", "scenes", clip, "--from", "1", check=False)
        self.assertNotEqual(cp.returncode, 0)

    def test_transcripts_default_to_a_job(self):
        """S8 (ROUND3): transcripts never go next to the user's footage without a yes: the default edit
        folder is <job>/edit (a new `<name>-edit` job when there is none), reused on the next call; the
        old <media folder>/edit/transcripts is still read; `pack` finds the job's edit folder."""
        root = self.tmp / "tjob"
        (root / "media").mkdir(parents=True)
        clip = root / "media" / "take1.mp4"
        clip.write_bytes(b"not decoded here")
        code = ("import sys; from st.footage import util as U; "
                "print(U.default_edit_dir(sys.argv[1], create_job=True)); print('\\n'.join(map(str, U.transcript_candidates(sys.argv[1]))))")
        runpy = lambda: subprocess.run([sys.executable, "-c", code, str(clip)], env=self.env, cwd=str(root),  # noqa: E731
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        cp = runpy()
        self.assertEqual(cp.returncode, 0, cp.stderr)
        lines = cp.stdout.strip().splitlines()
        ed = Path(lines[0])
        self.assertEqual(ed.name, "edit")
        self.assertEqual(ed.parent.parent, (root / "showtime-out").resolve())
        self.assertTrue((ed.parent / "job.json").is_file())
        self.assertIn("created job", cp.stderr)
        self.assertFalse((root / "media" / "edit").exists())
        self.assertIn(str(root.resolve() / "media" / "edit" / "transcripts" / "take1.json"), lines[1:])
        cp2 = runpy()
        self.assertEqual(Path(cp2.stdout.strip().splitlines()[0]), ed)   # the same edit job, not a new one
        # pack with no argument, from the project folder: the newest edit job's edit/
        (ed / "transcripts").mkdir(parents=True, exist_ok=True)
        (ed / "transcripts" / "take1.json").write_text(json.dumps({"source": "../../../../media/take1.mp4", "duration": 1.0,
            "words": [{"text": "hello", "start": 0.1, "end": 0.4, "type": "word"}]}), encoding="utf-8")
        cp = self.run_st("pack", cwd=root)
        self.assertTrue((ed / "takes_packed.md").is_file(), cp.stdout + cp.stderr)

    def test_job_aware_edit_tools(self):
        """S8: `footage scenes` writes into a job's work/scenes (never next to the source); `edit check <job>`;
        P2/P5: `edit render` warns on a > 1.5x upscale, prints its report path, and after a final points to the
        poster + qa step; qa of the job then reports the upscale."""
        root = self.tmp / "jobaware"
        (root / "media").mkdir(parents=True)
        clip = root / "media" / "clip.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=f=300:d=3:sample_rate=48000",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip])
        # no job anywhere: a fresh showtime-out/scenes-<ts>/ under the current folder, not media/edit/scenes
        cp = self.run_st("footage", "scenes", clip, "--every", "1", cwd=root)
        sheet = Path(cp.stdout.strip().splitlines()[-1])
        self.assertTrue(sheet.is_file())
        self.assertEqual(sheet.parent.parent.name, "showtime-out")
        self.assertTrue(sheet.parent.name.startswith("scenes-"))
        self.assertFalse((root / "media" / "edit").exists(), "scenes must not write next to the source")
        job = Path(json.loads(self.run_st("job", "init", "aware", "--json", cwd=root).stdout)["job"])
        # a job exists: its work/scenes (newest job from the project folder; the job itself from inside it)
        cp = self.run_st("footage", "scenes", clip, "--every", "1", cwd=root)
        self.assertEqual(Path(cp.stdout.strip().splitlines()[-1]).parent, job / "work" / "scenes")
        self.assertIn("writing into job %s" % job.name, cp.stderr)
        cp = self.run_st("footage", "scenes", clip, "--every", "1", "--job", job, "--json", cwd=root / "media")
        self.assertEqual(Path(json.loads(cp.stdout)["sheet"]).parent, job / "work" / "scenes")
        self.assertFalse((root / "media" / "edit").exists())
        # the other footage tools default to <job>/work/footage/ too
        cp = self.run_st("footage", "grade", clip, "--compare", "--at", "1", cwd=root)
        self.assertEqual(Path(cp.stdout.strip().splitlines()[-1]).parent, job / "work" / "footage")
        cp = self.run_st("footage", "view", clip, "--from", "0", "--to", "2", cwd=root)
        self.assertEqual(Path(cp.stdout.strip().splitlines()[-1]).parent, job / "work" / "footage" / "views")
        self.assertEqual(sorted(x.name for x in (root / "media").iterdir()), ["clip.mp4"])
        # an EDL in the job; edit check takes the job name
        tdir = job / "edit" / "transcripts"
        tdir.mkdir(parents=True)
        words = [{"id": "w%d" % i, "text": w, "start": round(0.2 + 0.3 * i, 3), "end": round(0.4 + 0.3 * i, 3), "type": "word"}
                 for i, w in enumerate("one two three four five six seven".split())]
        tr = tdir / "clip.json"
        tr.write_text(json.dumps({"source": str(clip), "duration": 3.0, "language": "en", "model": "synthetic",
                                  "words": words}), encoding="utf-8")
        self.run_st("edit", "cut", tr, "--aspect", "720p", "-o", job / "edit" / "edl.json", cwd=root)
        cp = self.run_st("edit", "check", "aware", cwd=root)
        self.assertIn("(latest edl)", cp.stderr)
        self.assertIn("EDL ok", cp.stdout)
        cp = self.run_st("edit", "check", cwd=job)   # no argument inside the job
        self.assertIn("EDL ok", cp.stdout)
        # final render: 320x180 -> 1280x720 is a 4x upscale; the report path and the next step are printed
        cp = self.run_st("edit", "render", "aware", "-o", job / "final.mp4", cwd=root)
        self.assertIn("enlarged 4.00x", cp.stderr)
        rp = job / "final.report.json"
        self.assertIn("report %s" % rp, cp.stderr)
        self.assertIn("next: showtime deliver poster aware", cp.stderr)
        self.assertIn("showtime qa aware", cp.stderr)
        rep = json.loads(rp.read_text(encoding="utf-8"))
        self.assertAlmostEqual(rep["segment_meta"][0]["upscale"]["factor"], 4.0, places=2)
        q = json.loads(self.run_st("qa", "aware", "--json", "--no-sheet", cwd=root, check=False).stdout)
        self.assertIn("upscale", [f["rule"] for f in q["findings"]])
        # a preview's next step is still edit view
        cp = self.run_st("edit", "render", "aware", "--preview", cwd=root)
        self.assertIn("next: showtime edit view", cp.stderr)


class Batch2FootageTest(unittest.TestCase):
    """Batch 2 frictions: caption line cap per line (13.7), one continuous boxed plate (14.1), --burn into a job
    becomes the latest final (14.12/18.3), sidecar in a job subfolder (16.8), --size-scale (22.16), grade
    --compare -o video name (14.9), denoise keeps channels/length and reports strength (16.5), VP9 alpha probe (20.13)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-foot-b2-")).resolve()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def words(text, step=0.5):
        out, t = [], 0.1
        for w in text.split():
            out.append({"text": w, "start": round(t, 3), "end": round(t + step * 0.8, 3), "type": "word"})
            t += step
        return out

    def test_line_cap_is_per_line(self):
        from st.footage import captions as C
        from st.qa import captions as Q
        # 25 + 27 + 18 characters: fits 84 in total but no balanced split keeps both lines under 42
        text = ("Anticonstitutionnellement intergouvernementalisations extraordinairement "
                "les abeilles dansent longtemps devant la ruche")
        self.assertFalse(C.fits_lines(["a" * 25, "b" * 27, "c" * 18], 42, 2))
        self.assertTrue(C.fits_lines(["a" * 20, "b" * 20], 42, 2))
        for style in ("clean", "boxed", "cinematic", "minimal"):
            for wh in ((1920, 1080), (1080, 1920)):
                # slow speech (1.3 s a word): the reading-speed split never hides the line problem
                C.build(self.words(text, 1.3), self.tmp / "l.ass", style=style, width=wh[0], height=wh[1],
                        srt=self.tmp / "l.srt")
                for f in ("l.ass", "l.srt"):
                    longs = [x for x in Q.check(Q.parse(self.tmp / f), 60, *wh) if x["rule"] == "caption_line_long"]
                    self.assertEqual(longs, [], (style, wh, f))

    def test_boxed_plate_is_continuous(self):
        from PIL import Image
        from st import ff
        from st.footage import captions as C
        text = "The lava flowed into the ocean near Kapoho for weeks after the fissure opened"
        ass = self.tmp / "boxed.ass"
        rep = C.build(self.words(text, 0.3), ass, style="boxed", width=720, height=1280)
        lines = [ln for ln in ass.read_text(encoding="utf-8").splitlines() if ln.startswith("Dialogue:")]
        self.assertEqual(len(lines), 2 * rep["groups"])    # one plate + one text event per caption
        self.assertTrue(all("\\p1" in ln for ln in lines[0::2]))
        png = self.tmp / "boxed.png"
        vf = "ass=filename=%s:fontsdir=%s" % (ff.filter_path(rep["ass"]), ff.filter_path(rep["fontsdir"]))
        ffrun(["-f", "lavfi", "-i", "color=c=0x808080:s=720x1280:d=6", "-vf", vf, "-ss", "3.5", "-frames:v", "1", png])
        im = Image.open(png).convert("L")
        vals = [im.getpixel((x, y)) for y in range(700, 1100) for x in range(0, 720)]
        plate = sum(1 for v in vals if 35 <= v <= 55)        # grey 128 under a 65 % black plate
        double = sum(1 for v in vals if v < 30)               # where two translucent boxes would overlap
        self.assertGreater(plate, 5000)
        self.assertEqual(double, 0)

    def test_burn_into_job_and_cli_flags(self):
        base = self.tmp / "burn"
        base.mkdir()
        job = Path(js("job", "init", "burnjob", "--base", base, "--json")["job"])
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=300:d=2:sample_rate=48000",
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", job / "final.mp4"])
        st("job", "note", job, "--output", "final=%s" % (job / "final.mp4"))
        tr = self.tmp / "b.words.json"
        tr.write_text(json.dumps({"language": "en", "duration": 2, "words": self.words("Hello from the lava field", 0.3)}),
                      encoding="utf-8")
        cp = st("captions", tr, "--style", "clean", "--burn", job / "final.mp4", "--size-scale", "1.3")
        burned = job / "final.captioned.mp4"
        self.assertTrue(burned.is_file())
        self.assertIn("latest final -> final.captioned.mp4", cp.stderr)
        outs = json.loads((job / "job.json").read_text(encoding="utf-8"))["outputs"]
        self.assertEqual(Path(outs["final"]).name, "final.captioned.mp4")
        # onto another clip: logged as a variant, the final stays
        shutil.copy2(str(job / "final.mp4"), str(job / "broll.mp4"))
        cp = st("captions", tr, "--style", "clean", "--burn", job / "broll.mp4")
        self.assertIn("logged as a variant", cp.stderr)
        outs = json.loads((job / "job.json").read_text(encoding="utf-8"))["outputs"]
        self.assertEqual(Path(outs["final"]).name, "final.captioned.mp4")
        # a sidecar in a job subfolder: the message says it is in the job, just not its root
        (job / "deliver").mkdir()
        cp = st("captions", tr, "-o", job / "deliver" / "c.ass", "--srt", job / "deliver" / "captions.en.srt")
        self.assertIn("is in a subfolder of job", cp.stderr)
        self.assertNotIn("not in the job folder", cp.stderr)
        # grade --compare writes a still: a video name for -o is refused with the fix
        cp = st("footage", "grade", job / "final.mp4", "--compare", "-o", self.tmp / "x.mp4", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("-o x.png", cp.stderr)
        self.assertFalse((self.tmp / "x.mp4").exists())

    def test_denoise_keeps_channels_and_length(self):
        import soundfile as sf
        from st.footage import denoise as D
        src = self.tmp / "st.wav"
        ffrun(["-f", "lavfi", "-i", "sine=f=300:d=2:sample_rate=48000", "-f", "lavfi", "-i", "anoisesrc=d=2:a=0.02:r=48000",
               "-filter_complex", "[0][1]amerge=inputs=2", "-ac", "2", src])
        n = sf.info(str(src)).frames
        methods = ["afftdn"] + (["deepfilter"] if D.available().get("deepfilter") else [])
        for m in methods:
            reps = []
            for k in (0.5, 1.0):
                r = js("footage", "denoise", src, "--method", m, "--strength", k, "-o", self.tmp / ("%s-%g.wav" % (m, k)), "--json")
                info = sf.info(r["output"])
                self.assertEqual((info.channels, info.frames), (2, n), m)
                reps.append(r)
            self.assertNotEqual(reps[0]["reduction_limit"], reps[1]["reduction_limit"])
            self.assertIsNotNone(reps[0]["removed_db"])
        cp = st("footage", "denoise", src, "--method", "afftdn", "--strength", "0.5", "-o", self.tmp / "t.wav")
        self.assertIn("strength 0.5", cp.stderr)

    # ------------------------------------------------------------------ edit loudness (mastered like every delivery)
    def _quiet_talk(self):
        """A 12 s clip of speech-like tone bursts at about -24 LUFS, with a matching transcript (two fillers)."""
        import numpy as np
        import soundfile as sf
        ed = self.tmp / "loud-edit"
        (ed / "transcripts").mkdir(parents=True, exist_ok=True)
        sr, words, t = 48000, [], 0.3
        x = np.zeros(int(12.5 * sr), np.float32)
        rng = np.random.default_rng(5)
        for w in "so um this is a quiet recording uh that still needs to come out at the delivery level".split():
            d = 0.25
            words.append({"text": w, "start": round(t, 3), "end": round(t + d, 3), "type": "word"})
            a, b = int(t * sr), int((t + d) * sr)
            n = np.arange(b - a) / sr
            x[a:b] += 0.06 * np.sin(2 * np.pi * (150 + 50 * rng.random()) * n) * np.hanning(b - a)
            t += d + 0.15
        wav = ed / "quiet.wav"
        sf.write(str(wav), x[: int((t + 0.4) * sr)], sr)
        vid = ed / "quiet.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=160x90:r=15:d=%.2f" % (t + 0.4), "-i", wav, "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "128k", "-shortest", vid])
        (ed / "transcripts" / "quiet.json").write_text(json.dumps(
            {"source": str(vid), "duration": t + 0.4, "language": "en", "model": "synthetic", "words": words}), encoding="utf-8")
        return ed, vid

    @staticmethod
    def _lufs(path):
        from st.audio import meter
        from st.qa import media
        return meter.measure(media.decode_audio(Path(path)))["integrated_lufs"]

    def test_edit_render_masters_to_delivery_loudness(self):
        ed, vid = self._quiet_talk()
        src_lufs = self._lufs(vid)
        self.assertLess(src_lufs, -19.0, "the source must be far from -14 for this test to mean anything")
        edl = ed / "edl.json"
        js("edit", "cut", ed / "transcripts" / "quiet.json", "-o", edl, "--overwrite", "--json")
        self.assertNotIn("loudness", json.loads(edl.read_text(encoding="utf-8")))     # the default lives in the renderer
        rep = js("edit", "render", edl, "--preview", "--json", "--overwrite")
        self.assertAlmostEqual(rep["loudness"]["integrated_lufs"], -14.0, delta=1.0, msg=rep["loudness"])
        self.assertLessEqual(rep["loudness"]["true_peak_dbtp"], -0.7)
        self.assertEqual(rep["loudness_target"], {"mode": "master", "lufs": -14.0, "tp": -1.0})
        # qa judges it against the same -14
        q = json.loads(st("qa", rep["output"], "--no-sheet", "--json", check=False).stdout)
        self.assertEqual(q["loudness"]["target_lufs"], -14.0)
        self.assertFalse([f for f in q["findings"] if f["rule"] == "loudness"], q["findings"])
        # asked for another level
        r2 = js("edit", "render", edl, "--preview", "--lufs", "-18", "--json", "--overwrite")
        self.assertAlmostEqual(r2["loudness"]["integrated_lufs"], -18.0, delta=1.0)
        self.assertEqual(r2["loudness_target"]["lufs"], -18.0)
        q2 = json.loads(st("qa", r2["output"], "--no-sheet", "--json", check=False).stdout)
        self.assertEqual(q2["loudness"]["target_lufs"], -18.0)      # the render's own target, nothing else named one
        self.assertFalse([f for f in q2["findings"] if f["rule"] == "loudness"], q2["findings"])
        # keep the source level: not mastered, said so in the report, noted (not failed) by qa
        r3 = js("edit", "render", edl, "--preview", "--keep-loudness", "--json", "--overwrite")
        self.assertEqual(r3["loudness_target"], {"mode": "source"})
        self.assertLess(r3["loudness"]["integrated_lufs"], -19.0, r3["loudness"])
        q3 = json.loads(st("qa", r3["output"], "--no-sheet", "--json", check=False).stdout)
        lf = [f for f in q3["findings"] if f["rule"] == "loudness"]
        self.assertEqual([f["severity"] for f in lf], ["INFO"], lf)
        self.assertIn("keeps the source level", lf[0]["message"])
        # the same choice can be made when cutting; the EDL says so
        edl2 = ed / "edl-keep.json"
        js("edit", "cut", ed / "transcripts" / "quiet.json", "--keep-loudness", "-o", edl2, "--overwrite", "--json")
        self.assertIs(json.loads(edl2.read_text(encoding="utf-8"))["loudness"], False)
        bad = st("edit", "render", edl, "--preview", "--keep-loudness", "--lufs", "-16", check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("contradict", bad.stderr)

    def test_edl_loudness_forms(self):
        from st.footage import edl as E
        clip = self.tmp / "a.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=1.5", "-f", "lavfi", "-i", "sine=f=300:d=1.5", "-shortest",
               "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", clip])
        base = {"sources": {"a": str(clip)}, "ranges": [{"source": "a", "start": 0, "end": 1}]}
        for val, want in ((None, {"lufs": -14.0, "tp": -1.0}), (-16, {"lufs": -16.0, "tp": -1.0}), (False, None),
                          ("source", None), ({"lufs": -12, "tp": -2}, {"lufs": -12.0, "tp": -2.0})):
            doc = dict(base) if val is None else dict(base, loudness=val)
            self.assertEqual(E.normalize(doc, self.tmp, "t", check_files=False)["loudness"], want, val)

    def test_probe_vp9_alpha(self):
        from st import ff
        if not ff.has_encoder("libvpx-vp9"):
            self.skipTest("no libvpx-vp9 encoder")
        webm = self.tmp / "a.webm"
        ffrun(["-f", "lavfi", "-i", "color=c=red@0.5:s=64x64:r=10:d=0.5,format=yuva420p", "-c:v", "libvpx-vp9",
               "-pix_fmt", "yuva420p", webm])
        pr = js("footage", "probe", webm)
        self.assertEqual(pr["pix_fmt"], "yuva420p")
        self.assertEqual(pr["pix_fmt_stream"], "yuv420p")
        self.assertIn("side channel", pr["alpha"])


class StabilizeFallbackTest(unittest.TestCase):
    """The deshake fallback, used when the ffmpeg build has no vid.stab: ffmpeg refuses a deshake
    search radius that is not a multiple of 16, which used to fail `footage stabilize` at most
    strengths and every EDL range with "stabilize": true. vid.stab is hidden from ff.has_filter so
    the fallback runs on any build."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-foot-stab-")).resolve()
        cls.clip = cls.tmp / "shaky.mp4"
        ffrun(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=f=300:d=2:sample_rate=48000",
               "-vf", "crop=288:162:16+12*sin(t*9):9+8*cos(t*7)", "-c:v", "libx264", "-preset", "veryfast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.clip])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def no_vidstab():
        from unittest import mock
        from st import ff
        real = ff.has_filter
        return mock.patch.object(ff, "has_filter", lambda name: not name.startswith("vidstab") and real(name))

    def test_deshake_radius_is_always_a_multiple_of_16(self):
        """The bug: int(round(16 + 32*s)) lands on values like 17, 33, 49 that ffmpeg's deshake
        refuses outright ("rx must be a multiple of 16"). deshake_filter must always snap to 16/32/48."""
        from st.footage import stabilize as S
        for i in range(21):
            s = i / 20.0
            m = re.search(r"^deshake=rx=(\d+):ry=(\d+)$", S.deshake_filter(s))
            self.assertIsNotNone(m, S.deshake_filter(s))
            rx, ry = int(m.group(1)), int(m.group(2))
            self.assertEqual(rx, ry, s)
            self.assertEqual(rx % 16, 0, "strength %g -> rx=%d is not a multiple of 16" % (s, rx))
            self.assertTrue(16 <= rx <= 48, (s, rx))

    def test_stabilize_deshake_every_strength(self):
        from st.footage import stabilize as S
        from st.footage import util as U
        for s in (0.0, 0.25, 0.7, 1.0):
            with self.no_vidstab():
                r = S.stabilize(self.clip, self.tmp / ("stab-%g.mp4" % s), strength=s, preview=True)
            self.assertEqual(r["method"], "deshake")
            self.assertAlmostEqual(U.probe(r["output"])["duration"], 2.0, delta=0.15, msg="strength %g" % s)

    def test_edl_range_stabilize_deshake(self):
        from st.footage import render_edl as R
        edl = self.tmp / "edl.json"
        edl.write_text(json.dumps({"sources": {"a": str(self.clip)}, "output": {"width": 288, "height": 162, "fps": 30},
                                   "ranges": [{"source": "a", "start": 0.2, "end": 1.6, "stabilize": True}],
                                   "captions": False, "loudness": False}), encoding="utf-8")
        with self.no_vidstab():
            rep = R.render(edl, self.tmp / "stable.mp4", preview=True, captions=False, jobs=1)
        self.assertEqual([m.get("stabilize") for m in rep["segment_meta"]], ["deshake"])
        self.assertTrue(rep["frames_ok"], rep)
        self.assertEqual(rep["frames"], 42)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
