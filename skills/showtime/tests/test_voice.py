#!/usr/bin/env python3
"""Voice module smoke tests (about a minute; first run also fetches the 95 MB
English aligner unless SHOWTIME_OFFLINE=1).

Drives the real CLI (`showtime voice ...`) through the launcher and checks:

- text handling (markup, tokens, normalization) and the voice catalog
- `voice script` with 2 English lines + 1 Spanish line: per-line clips, vo.wav
  at 48 kHz and -16 +-0.5 LUFS, timeline.json with contiguous lines, word
  counts equal to the script, words monotonic and inside their line, SRT cues
- `voice say`: WAV + transcript-format .words.json, exact Kokoro timings,
  [pause] markup really inserts silence, cache hit on the second run
- `voice align`: CTC (English) and Kokoro-reference DTW (Spanish) word starts
  within 80 ms (mean) of Kokoro's own timings
- `voice master`: a raw TTS file and a quiet numpy tone land at -16 +-0.5 LUFS,
  true peak <= -1.4 dBTP
- `voice ipa` applies the lexicon; errors are one-line messages with hints

No platform-specific tools are used (no `say`, no shell): speech comes from
Kokoro, tones from numpy, so this runs the same on macOS, Windows and Linux.

usage: python tests/test_voice.py [--fast] [-v]
"""
from __future__ import annotations

import json
import math
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

from st.launcher import build_env, showtime_home  # noqa: E402
from st import platform as plat  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
VPY = str(plat.venv_python(showtime_home() / "venv"))
PY = VPY if Path(VPY).is_file() else sys.executable

EN1 = "Meet Showtime, the video studio that lives in your terminal."
EN2 = "Point it at any project, and get a polished launch film in minutes."
ES1 = "Te presentamos Showtime, el estudio de video que vive en tu terminal."

TONE = r"""
import sys, numpy as np, soundfile as sf
sr = 48000; t = np.arange(int(sr * 3.0)) / sr
x = 0.02 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.5 * t))
sf.write(sys.argv[1], x.astype("float32"), sr, subtype="PCM_16")
"""


def st(*args, check=True, timeout=600, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV,
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
    except ValueError:
        raise AssertionError("not JSON from showtime %s:\n%s\n%s" % (" ".join(map(str, args)), cp.stdout[-2000:],
                                                                      cp.stderr[-2000:]))


def py(code: str, *args) -> str:
    cp = subprocess.run([PY, "-c", code] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
    if cp.returncode != 0:
        raise AssertionError("python snippet failed:\n%s" % cp.stderr[-3000:])
    return cp.stdout


def wav_info(path) -> dict:
    return json.loads(py("import soundfile as sf, sys, json; i = sf.info(sys.argv[1]); "
                         "print(json.dumps({'sr': i.samplerate, 'ch': i.channels, 'dur': i.frames / i.samplerate}))",
                         path))


def start_mae(a, b) -> float:
    assert len(a) == len(b), (len(a), len(b))
    return sum(abs(x["start"] - y["start"]) for x, y in zip(a, b)) / len(a)


def n_words(text: str) -> int:
    return len(text.split())


class VoiceTests(unittest.TestCase):
    tmp: Path

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-voice-test-"))
        cls.t0 = time.time()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ------------------------------------------------------------------
    def test_00_text_and_catalog(self):
        out = py(r"""
import json, sys
from st.voice import textnorm as tn, voices
segs = tn.split_pauses("One two. [pause 0.4] Three <!-- note --> four [pause 250ms] five")
toks = tn.tokenize("Meet [Showtime](/ʃˈoʊtaɪm/), in 2026 at showtime.dev — e.g. v2.0 & 3.5x!")
tn.normalize_tokens(toks, "en")
spec = voices.resolve("af_heart:60+am_michael:40")
print(json.dumps({"segs": [[s.text, s.pause_after] for s in segs],
                  "toks": [[t.text, t.spoken, t.ipa] for t in toks],
                  "plain": tn.plain_text("Hi [pause] [SQL](sequel) there"),
                  "blend": spec.blend, "es": voices.resolve(None, "es").id,
                  "piper": voices.resolve("piper:es_MX-claude-high").engine}))
""")
        d = json.loads(out)
        # Spanish numbers: space/period grouping is one number, a decimal comma reads "coma"; the okina is silent
        es = json.loads(py(r"""
import json
from st.voice import textnorm as tn
toks = tn.tokenize("Unos 60 000 vecinos, 60.000 casas, 13,7 km y 1 234,5 m en Hawaiʻi.")
tn.normalize_tokens(toks, "es")
en = tn.tokenize("We had 60 000 users")
tn.normalize_tokens(en, "en")
print(json.dumps({"es": [[t.text, t.spoken] for t in toks], "en": len(en)}))
"""))
        sp = dict(es["es"])
        self.assertEqual(sp["60 000"], "60000")
        self.assertEqual(sp["60.000"], "60000")
        self.assertEqual(sp["13,7"], "13 coma 7")
        self.assertEqual(sp["1 234,5"], "1234 coma 5")
        self.assertEqual(sp["Hawaiʻi."], "Hawaii")
        self.assertEqual(es["en"], 5, "English keeps 60 and 000 apart (no space grouping rule)")
        self.assertEqual([s[1] for s in d["segs"]], [0.4, 0.25, 0.0])
        self.assertEqual(d["segs"][1][0], "Three four")
        spoken = {t[0].strip(",.!"): t[1] for t in d["toks"]}
        self.assertEqual(d["toks"][1][2], "ʃˈoʊtaɪm")
        self.assertEqual(spoken["2026"], "twenty twenty-six")
        self.assertEqual(spoken["showtime.dev —"] if "showtime.dev —" in spoken else spoken["showtime.dev"],
                         "showtime dot dev")
        self.assertIn("point", spoken["v2.0"])
        self.assertEqual(d["plain"], "Hi SQL there")
        self.assertAlmostEqual(sum(w for _, w in d["blend"]), 1.0, places=6)
        self.assertEqual(d["es"], "ef_dora")
        self.assertEqual(d["piper"], "piper")
        # the same word either side of a sentence break is heard as a stutter ("one one plus three")
        stut = json.loads(py(r"""
import json
from st.voice import script as S
print(json.dumps([bool(S.STUTTER_RE.search(t)) for t in (
    "One. One plus three is four.", "Look at it. It changes.", "One plus three is four. Plus five is nine.",
    "Look at this. Look closer: the corner.", "Add one. Then one more.")]))
"""))
        self.assertEqual(stut, [True, True, False, False, False])

        lst = js("voice", "list", "--json")
        kokoro = [v for v in lst["voices"] if v["engine"] == "kokoro"]
        self.assertEqual(len(kokoro), 54)
        self.assertTrue(all(v["installed"] for v in kokoro), "Kokoro model files missing")
        self.assertIn("es", {v["lang"] for v in kokoro})
        self.assertTrue(lst["status"]["kokoro_timestamped"], "timestamped Kokoro export not installed")

    def test_01_script(self):
        script = {"voice": "af_heart", "gap": 0.4, "lines": [
            {"id": "hook", "text": EN1},
            {"id": "demo", "text": EN2, "voice": "am_michael", "speed": 1.05, "pause_after": 0.7},
            {"id": "es", "text": ES1, "voice": "ef_dora"},
        ]}
        sp = self.tmp / "vo.json"
        sp.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "voice"
        t0 = time.time()
        tl = js("voice", "script", sp, "-o", out, "--json", timeout=900)
        build = time.time() - t0
        self.assertEqual(len(tl["lines"]), 3)
        info = wav_info(out / "vo.wav")
        self.assertEqual(info["sr"], 48000)
        self.assertAlmostEqual(info["dur"], tl["duration"], delta=0.01)
        self.assertIsNotNone(tl["loudness"])
        self.assertAlmostEqual(tl["loudness"], -16.0, delta=0.5)
        texts = [EN1, EN2, ES1]
        prev_end = 0.0
        for i, ln in enumerate(tl["lines"]):
            self.assertEqual(ln["timing"], "exact", ln["id"])
            self.assertEqual(len(ln["words"]), n_words(texts[i]), ln["id"])
            starts = [w["start"] for w in ln["words"]]
            self.assertEqual(starts, sorted(starts), "word starts not monotonic in %s" % ln["id"])
            for w in ln["words"]:
                self.assertLess(w["start"], w["end"])
                self.assertGreaterEqual(w["start"], ln["start"] - 1e-3)
                self.assertLessEqual(w["end"], ln["end"] + 1e-3)
            self.assertGreaterEqual(ln["start"], prev_end - 1e-3)
            if i:
                gap = ln["start"] - tl["lines"][i - 1]["end"]
                self.assertAlmostEqual(gap, tl["lines"][i - 1]["pause_after"], delta=0.002)
            prev_end = ln["end"]
            clip = out / ln["file"]
            self.assertTrue(clip.is_file(), clip)
            self.assertAlmostEqual(wav_info(clip)["dur"], ln["duration"], delta=0.02)
            self.assertGreater(ln["wps"], 1.5)
            self.assertLess(ln["wps"], 5.0)
        self.assertEqual(tl["lines"][2]["lang"], "es")
        self.assertEqual(len(tl["words"]), sum(n_words(t) for t in texts))
        tr = json.loads((out / "vo.words.json").read_text(encoding="utf-8"))
        self.assertEqual(len(tr["words"]), len(tl["words"]))
        self.assertTrue(all(w["type"] == "word" for w in tr["words"]))
        # sidecars carry paths relative to their own folder (voice/ folders get copied and published)
        self.assertEqual(tr["source"], "vo.wav")
        self.assertEqual(tl["file"], "vo.wav")
        self.assertEqual(tl["script"], "../vo.json")
        for f in [out / "timeline.json", out / "vo.words.json"] + sorted((out / "lines").glob("*.words.json")):
            txt = f.read_text(encoding="utf-8")
            for bad in (str(self.tmp), str(Path.home()), str(self.tmp.resolve())):
                self.assertNotIn(bad.replace("\\", "\\\\"), txt, "absolute path in %s" % f.name)
                self.assertNotIn(bad, txt, "absolute path in %s" % f.name)
        self.assertEqual(json.loads((out / "lines" / ("01-%s.words.json" % tl["lines"][0]["id"]))
                                    .read_text(encoding="utf-8"))["source"], tl["lines"][0]["file"].split("/")[-1])
        srt = (out / "vo.srt").read_text(encoding="utf-8")
        self.assertIn("-->", srt)
        self.assertTrue(all(len(c.splitlines()[2]) <= 42 for c in srt.strip().split("\n\n")))
        # unchanged script -> every line from the cache
        t1 = time.time()
        tl2 = js("voice", "script", sp, "-o", out, "--json")
        self.assertEqual(tl2["duration"], tl["duration"])
        type(self).script_out = out
        type(self).timeline = tl
        print("\n  script: 3 lines, %.2fs of audio, first build %.1fs, cached rebuild %.1fs, %.1f LUFS"
              % (tl["duration"], build, time.time() - t1, tl["loudness"]), file=sys.stderr)

    def test_02_say_markup_cache(self):
        out = self.tmp / "say.wav"
        text = "Ready? [pause 0.6] Set. Go!"
        d = js("voice", "say", text, "-o", out, "--json")
        self.assertTrue(out.is_file())
        self.assertEqual(wav_info(out)["sr"], 48000)
        words = json.loads((self.tmp / "say.words.json").read_text(encoding="utf-8"))
        self.assertEqual([w["text"] for w in words["words"]], ["Ready?", "Set.", "Go!"])
        self.assertEqual(words["timing"], "exact")
        gap = words["words"][1]["start"] - words["words"][0]["end"]
        self.assertGreater(gap, 0.55, "[pause 0.6] did not insert its silence (gap %.2fs)" % gap)
        self.assertAlmostEqual(d["loudness"]["lufs"], -16.0, delta=0.5)
        d2 = js("voice", "say", text, "-o", self.tmp / "say2.wav", "--json")
        self.assertTrue(d2["cached"])
        self.assertAlmostEqual(d2["duration"], d["duration"], places=3)

    def test_03_align_english_ctc(self):
        tl = getattr(self, "timeline", None)
        if tl is None:
            self.skipTest("needs test_01")
        offline = os.environ.get("SHOWTIME_OFFLINE") == "1"
        for ln in tl["lines"][:2]:
            clip = self.script_out / ln["file"]
            rel = [{"start": w["start"] - ln["start"]} for w in ln["words"]]
            method = "tts" if offline else "ctc"
            d = js("voice", "align", clip, ln["text"], "--method", method, "-o", self.tmp / (ln["id"] + ".al.json"),
                   "--json", timeout=900)
            self.assertEqual(d["method"], method)
            self.assertEqual([w["text"] for w in d["words"]], [w["text"] for w in ln["words"]])
            mae = start_mae(d["words"], rel)
            print("  align %-4s %-5s start MAE vs Kokoro: %.0f ms" % (method, ln["id"], mae * 1000), file=sys.stderr)
            self.assertLess(mae, 0.080, "%s alignment too far from Kokoro timings (%.0f ms)" % (method, mae * 1000))

    def test_04_align_spanish_tts_dtw(self):
        tl = getattr(self, "timeline", None)
        if tl is None:
            self.skipTest("needs test_01")
        ln = tl["lines"][2]
        clip = self.script_out / ln["file"]
        rel = [{"start": w["start"] - ln["start"]} for w in ln["words"]]
        # reference voice differs from the speaker (em_alex vs ef_dora): a real cross-voice warp
        d = js("voice", "align", clip, ln["text"], "--lang", "es", "--method", "tts", "--voice", "em_alex",
               "-o", self.tmp / "es.al.json", "--json")
        mae = start_mae(d["words"], rel)
        print("  align tts  es    start MAE vs Kokoro: %.0f ms" % (mae * 1000), file=sys.stderr)
        self.assertLess(mae, 0.080)

    def test_05_master(self):
        raw = self.tmp / "raw.wav"
        st("voice", "say", EN2, "-v", "bf_emma", "--raw", "-o", raw)
        self.assertEqual(wav_info(raw)["sr"], 24000)
        rep = js("voice", "master", raw, "-o", self.tmp / "raw.m.wav", "--json")
        self.assertLess(rep["before"]["lufs"], -17.0)
        self.assertAlmostEqual(rep["after"]["lufs"], -16.0, delta=0.5)
        self.assertLessEqual(rep["after"]["tp"], -1.4)
        tone = self.tmp / "tone.wav"
        py(TONE, tone)
        rep = js("voice", "master", tone, "-o", self.tmp / "tone.m.wav", "--json")
        self.assertAlmostEqual(rep["after"]["lufs"], -16.0, delta=0.5)
        self.assertLessEqual(rep["after"]["tp"], -1.4)
        info = wav_info(self.tmp / "tone.m.wav")
        self.assertEqual((info["sr"], info["ch"]), (48000, 1))

    def test_05b_supertonic_spanish(self):
        if FAST:
            self.skipTest("--fast")
        lst = js("voice", "list", "--engine", "supertonic", "--json")
        if not lst["status"]["supertonic"]:
            self.skipTest("Supertonic not installed (showtime setup --with supertonic)")
        d = js("voice", "say", ES1, "-v", "supertonic:F1", "--lang", "es", "-o", self.tmp / "st.wav", "--json")
        self.assertEqual(d["engine"], "supertonic")
        self.assertIn(d["timing"], ("tts", "whisper"))
        self.assertEqual(d["words"], n_words(ES1))
        ws = json.loads((self.tmp / "st.words.json").read_text(encoding="utf-8"))["words"]
        starts = [w["start"] for w in ws]
        self.assertEqual(starts, sorted(starts))
        self.assertLessEqual(ws[-1]["end"], d["duration"] + 1e-3)

    def test_06_ipa_and_errors(self):
        d = js("voice", "ipa", "Showtime ships", "--json")
        self.assertEqual(d["words"][0]["lexicon"], "ʃˈoʊtaɪm")
        self.assertTrue(d["words"][1]["espeak"])
        self.assertTrue(d["phrase"].startswith("ʃˈoʊtaɪm "), "the phrase line uses the lexicon: %s" % d["phrase"])
        # the project's lexicon.json is found (here: the one sub-folder of the current folder that has one)
        proj = self.tmp / "ipa-job" / "project"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "lexicon.json").write_text(json.dumps({"Kilauea": "kiːlɑːwˈeɪə", "GIF": {"say": "jiff"}}),
                                           encoding="utf-8")
        cp = subprocess.run([sys.executable, str(LAUNCHER), "voice", "ipa", "Kilauea GIF", "--json"], env=ENV,
                            cwd=str(proj.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                            timeout=120)
        d = json.loads(cp.stdout)
        self.assertEqual(d["words"][0]["lexicon"], "kiːlɑːwˈeɪə")
        self.assertEqual(d["words"][1]["spoken"], "jiff")
        self.assertTrue(d["phrase"].startswith("kiːlɑːwˈeɪə "), d["phrase"])
        d = js("voice", "ipa", "Kilauea", "--project", proj, "--json")
        self.assertEqual(d["words"][0]["lexicon"], "kiːlɑːwˈeɪə")
        cp = st("voice", "say", "hello", "-v", "xx_nobody", "-o", self.tmp / "bad.wav", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("unknown voice", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = st("voice", "say", "hi", "--speed", "3", "-o", self.tmp / "bad.wav", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("speed", cp.stderr)
        for sub in ("list", "say", "script", "align", "master", "ipa", "bench", "cache"):
            self.assertIn("usage:", st("voice", sub, "--help").stdout)

    def test_07_cache_cap(self):
        home = self.tmp / "cache-home"
        out = py(r"""
import json, os
os.environ["SHOWTIME_HOME"] = %r
import numpy as np
from st.voice import tts
for i in range(5):
    tts._cache_store("k%%d" %% i, np.zeros(48000, dtype=np.float32), 48000, {"i": i})
before = tts.cache_stats()
pr = tts.prune_cache(limit=500000)
after = tts.cache_stats()
cl = tts.prune_cache(clear=True)
print(json.dumps({"before": before["entries"], "pruned": pr["removed"], "after": after["entries"],
                  "bytes": after["bytes"], "cleared": tts.cache_stats()["entries"]}))
""" % str(home))
        d = json.loads(out)
        self.assertEqual(d["before"], 5)
        self.assertGreater(d["pruned"], 0)
        self.assertLessEqual(d["bytes"], 500000)
        self.assertEqual(d["cleared"], 0)

    def test_08_script_fit(self):
        """`voice script --fit S`: speed within 0.85-1.15x, then shorter pauses, then an exact word-cut report;
        a short script is padded to the target. vo.srt stays inside qa's caption limits on any aspect."""
        script = {"voice": "af_heart", "gap": 0.6, "lines": [
            {"id": "a", "text": "Sunlight is photons from the sun."},
            {"id": "b", "text": "Panels turn those photons into electricity, silently, all day long."},
            {"id": "c", "text": "Clean power, right on your roof."}]}
        sp = self.tmp / "fit.json"
        sp.write_text(json.dumps(script), encoding="utf-8")
        base = js("voice", "script", sp, "-o", self.tmp / "fit0", "--json")["duration"]
        # 1. a bit long -> faster speech lands on the target (vo.wav really is that long)
        target = round(base * 0.94, 2)
        cp = st("voice", "script", sp, "-o", self.tmp / "fit1", "--fit", target, "--json")
        tl = json.loads(cp.stdout)
        f = tl["fit"]
        self.assertIn("fit %.2fs" % target, cp.stderr)
        self.assertGreater(f["speed_factor"], 1.0)
        self.assertLessEqual(f["speed_factor"], 1.15)
        self.assertLessEqual(abs(tl["duration"] - target), f["tolerance"] + 1e-6, f)
        self.assertEqual(f["result"], tl["duration"])
        self.assertAlmostEqual(wav_info(self.tmp / "fit1" / "vo.wav")["dur"], tl["duration"], delta=0.01)
        self.assertEqual(f["cut_words"], 0)
        self.assertAlmostEqual(tl["duration"], target, delta=0.02)   # padded to the exact target
        # sidecars hold portable paths (relative to their folder), never this machine's absolute paths
        self.assertEqual(tl["script"], "../fit.json")
        self.assertEqual(json.loads((self.tmp / "fit1" / "vo.words.json").read_text(encoding="utf-8"))["source"], "vo.wav")
        self.assertTrue(all(x.startswith("showtime:") or not x.startswith("/") for x in tl.get("lexicon") or []), tl.get("lexicon"))
        # 2. far too long -> fastest natural speed, pauses at their floor, and how many words to cut
        target = round(base * 0.55, 2)
        cp = st("voice", "script", sp, "-o", self.tmp / "fit2", "--fit", target, "--json")
        tl = json.loads(cp.stdout)
        f = tl["fit"]
        self.assertEqual(f["speed_factor"], 1.15)
        self.assertGreater(f["pauses_trimmed"], 0)
        self.assertTrue(all(ln["pause_after"] >= 0.2 - 1e-6 for ln in tl["lines"]))
        self.assertGreaterEqual(tl["tail"], 0.3 - 1e-6)
        self.assertGreater(f["over"], 0)
        self.assertLessEqual(abs(f["cut_words"] - math.ceil(f["over"] * f["wps"])), 1, f)
        self.assertGreater(f["cut_words"], 0)
        self.assertRegex(cp.stderr, r"cut about %d words? \(of %d" % (f["cut_words"], f["words"]))
        self.assertTrue(f.get("fast"), f)                    # x1.15 is flagged as rushed, with words to cut at x1.0
        self.assertIn("sounds rushed", cp.stderr)
        # 3. short -> slower (>= 0.85x) and the tail padded so vo.wav lasts exactly the target
        target = round(base * 1.25, 2)
        tl = js("voice", "script", sp, "-o", self.tmp / "fit3", "--fit", target, "--json")
        f = tl["fit"]
        self.assertGreaterEqual(f["speed_factor"], 0.85)
        self.assertLess(f["speed_factor"], 1.0)
        self.assertAlmostEqual(tl["duration"], target, delta=0.02)
        self.assertGreater(f["tail_padded"], 0)
        # script-level "fit" key works like the flag
        script["fit"] = round(base * 0.94, 2)
        sp.write_text(json.dumps(script), encoding="utf-8")
        tl = js("voice", "script", sp, "-o", self.tmp / "fit4", "--json")
        self.assertIn("fit", tl)
        self.assertEqual(tl["fit"]["target"], script["fit"])
        # vo.srt: within qa's reading-speed and line-length limits, vertical and landscape
        out = py(r"""
import json, sys
from pathlib import Path
from st.qa import captions as Q
res = {}
for d in sys.argv[1:]:
    cap = Q.parse(Path(d) / "vo.srt")
    res[d] = [f["rule"] for f in Q.check(cap, 60, 1080, 1920) + Q.check(cap, 60, 1920, 1080)]
print(json.dumps(res))
""", *[self.tmp / n for n in ("fit0", "fit1", "fit2", "fit3")])
        for d, rules in json.loads(out).items():
            self.assertEqual(rules, [], d)
        self.assertIn("--fit", st("voice", "script", "--help").stdout)


    def test_09_windows_espeak_cleanup_is_quiet(self):
        """phonemizer's Windows exit hook fails when its DLL copy is still mapped (Windows on Arm): no
        traceback, the folder is remembered and the next run removes it; other temp folders are left alone."""
        out = py(r"""
import json, os, sys, tempfile
from pathlib import Path
os.environ["SHOWTIME_HOME"] = sys.argv[2]
sys.path.insert(0, sys.argv[1])
try:
    from phonemizer.backend.espeak import api
except Exception:
    print(json.dumps({"skip": True})); sys.exit(0)
from st import platform as plat
plat.IS_WINDOWS = True
from st.voice import espeak as E
calls = []
def locked(library, tempdir):
    calls.append(tempdir)
    raise PermissionError(13, "Access is denied", os.path.join(tempdir, "espeak-ng.dll"))
api.EspeakAPI._delete = staticmethod(locked)
E._guard_windows_cleanup()
tmp = tempfile.mkdtemp()
Path(tmp, "espeak-ng.dll").write_bytes(b"MZ")
obj = object.__new__(api.EspeakAPI)
obj._library, obj._tempdir = None, tmp
obj._delete_win32()                      # must not raise
recorded = E._leftovers_file().read_text(encoding="utf-8").split()
other = tempfile.mkdtemp()
Path(other, "notes.txt").write_text("keep")
E._leftovers_file().write_text("\n".join(recorded + [other]) + "\n", encoding="utf-8")
E._sweep_leftovers()
print(json.dumps({"calls": calls, "recorded": recorded, "tmp": tmp, "tmp_gone": not Path(tmp).exists(),
                  "other_kept": Path(other).exists(), "list_gone": not E._leftovers_file().exists()}))
import shutil; shutil.rmtree(other, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
""", SKILL / "lib", self.tmp / "home-espeak")
        d = json.loads(out.strip().splitlines()[-1])
        if d.get("skip"):
            self.skipTest("phonemizer is not installed in this Python")
        self.assertEqual(d["calls"], [d["tmp"]])
        self.assertEqual(d["recorded"], [d["tmp"]])
        self.assertTrue(d["tmp_gone"])
        self.assertTrue(d["other_kept"])
        self.assertTrue(d["list_gone"])

if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_voice: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
