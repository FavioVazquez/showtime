#!/usr/bin/env python3
"""Heard on a phone: the speaker loudness (st.audio.meter.speaker_loudness), qa's speaker_loudness item and the
critic's material, and the mixer's speaker-safe step (st.audio.mix).

Two synthetic beds, 8 s at 48 kHz:
  - bass: a 55 Hz sine bass and a kick (a 120 -> 45 Hz sweep every 0.5 s), with a quiet pad at 600-1200 Hz
          -> a large gap (the mix above 300 Hz far under the full mix), like the 0.4.1 showreel preview
  - mids: a chord at 220-880 Hz, a 1-4 kHz shimmer and a quiet 55 Hz bass -> a small gap, like a posted film
The mixer must fix the first (a low shelf on the bed, the full mix back at -14 LUFS, the mix above 300 Hz louder)
and leave the second as it was (only the 40 Hz high-pass acts); the voice is never touched; two renders are the
same bytes; a sub drop alone on its hit is listed, one with a mid transient on it is not.

Stdlib + the showtime venv (numpy, scipy). usage: python tests/test_speaker.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import re
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

SR = 48000
DUR = 8.0


def beds():
    """{"bass": stereo, "mids": stereo, "voice": mono} float32 at 48 kHz, each about -20 dBFS RMS."""
    import numpy as np
    from scipy import signal
    rng = np.random.default_rng(3)
    n = int(DUR * SR)
    t = np.arange(n) / SR
    bass = 0.5 * np.sin(2 * np.pi * 55 * t)
    kick = np.zeros(n)
    k = int(0.5 * SR)
    tt = np.arange(k) / SR
    one = np.sin(2 * np.pi * np.cumsum(45 + 75 * np.exp(-tt / 0.04)) / SR) * np.exp(-tt / 0.18)
    for s in range(0, n - k + 1, k):
        kick[s:s + k] += one
    pad = sum(np.sin(2 * np.pi * f * t) for f in (600.0, 900.0, 1200.0)) * 0.05
    b = bass + 0.8 * kick + pad
    chord = sum(np.sin(2 * np.pi * f * t + i) for i, f in enumerate((220.0, 330.0, 440.0, 660.0, 880.0))) * 0.2
    shimmer = signal.sosfilt(signal.butter(4, [1000, 4000], btype="band", fs=SR, output="sos"), rng.normal(0, 0.15, n))
    m = chord + shimmer + 0.15 * np.sin(2 * np.pi * 55 * t)
    sos = signal.butter(4, [250, 3500], btype="band", fs=SR, output="sos")
    voice = np.zeros(n)
    for a in np.arange(0.5, DUR - 0.5, 0.4):
        k0, k1 = int(a * SR), int((a + 0.3) * SR)
        voice[k0:k1] += signal.sosfilt(sos, rng.normal(0, 1, k1 - k0)) * np.sin(np.pi * np.arange(k1 - k0) / (k1 - k0))
    out = {}
    for name, x in (("bass", b), ("mids", m)):
        x = x / np.sqrt((x ** 2).mean()) * 0.1
        out[name] = np.stack([x, x], axis=1).astype(np.float32)
    out["voice"] = (voice / np.sqrt((voice ** 2).mean()) * 0.1).astype(np.float32)
    return out


def ffmpeg_above(path: Path, fc: int) -> float:
    from st import ff
    cp = subprocess.run([ff.ffmpeg_path(), "-nostats", "-nostdin", "-i", str(path), "-vn", "-af",
                         "highpass=f=%d,highpass=f=%d,ebur128" % (fc, fc), "-f", "null", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    e = cp.stderr.decode("utf-8", "replace")
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", e[e.rfind("Summary:"):])[-1])


class Collect:
    """Stands in for st.qa.video.Findings."""

    def __init__(self):
        self.items = []

    def add(self, rule, sev, msg, **kw):
        self.items.append(dict(kw, rule=rule, severity=sev, message=msg))

    def ok(self, msg):
        pass


class SpeakerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from st.audio import wav
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-speaker-"))
        cls.b = beds()
        for name in ("bass", "mids"):
            wav.save(cls.tmp / ("%s.wav" % name), cls.b[name], sr=SR, bits=24)
        wav.save(cls.tmp / "voice.wav", cls.b["voice"], sr=SR, bits=24)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def mix(self, name, tracks, master=None, **kw):
        from st.audio import mix
        spec = {"duration": DUR, "tracks": tracks, "master": dict({"lufs": -14, "true_peak": -1}, **(master or {}))}
        out = self.tmp / ("%s.wav" % name)
        rep = mix.render(spec, out, root=self.tmp, report_path=self.tmp / ("%s.report.json" % name), **kw)
        return rep, out

    # ------------------------------------------------------------------ the measurement
    def test_01_speaker_loudness_matches_ffmpeg(self):
        """The bass bed sits far under itself above 300 Hz, the mid bed close; the numbers are ffmpeg's."""
        from st.audio import meter
        b = meter.speaker_loudness(self.b["bass"])
        m = meter.speaker_loudness(self.b["mids"])
        self.assertGreater(b["gap_300_lu"], 12, b)
        self.assertLess(m["gap_300_lu"], 5, m)
        self.assertGreater(b["gap_1k_lu"], b["gap_300_lu"])
        for name, r in (("bass", b), ("mids", m)):
            self.assertAlmostEqual(r["above_300_lufs"], ffmpeg_above(self.tmp / ("%s.wav" % name), 300), delta=0.3)
            self.assertAlmostEqual(r["above_1k_lufs"], ffmpeg_above(self.tmp / ("%s.wav" % name), 1000), delta=0.3)
        z = meter.speaker_loudness(self.b["bass"][:0])
        self.assertIsNone(z["gap_300_lu"])

    # ------------------------------------------------------------------ qa and the critic
    def test_02_qa_item_thresholds(self):
        """speaker_loudness: nothing at 8 LU, WARN at 13.6, FAIL over 18, INFO when the mix turned it off."""
        from st.qa import hearing
        th = hearing.thresholds()
        self.assertEqual((th["speaker_gap_lu"], th["speaker_gap_fail_lu"]), (10.0, 18.0))

        def run(gap, mix=None, **kw):
            F = Collect()
            sp = dict({"integrated_lufs": -14.0, "above_300_lufs": -14.0 - gap, "gap_300_lu": gap,
                       "above_1k_lufs": -20.0 - gap, "gap_1k_lu": gap + 6, "mix": mix}, **kw)
            hearing.check_speaker(F, {"thresholds": th, "speaker": sp})
            return F.items
        self.assertEqual(run(8.2), [])
        w = run(13.62)
        self.assertEqual([(i["rule"], i["severity"]) for i in w], [("speaker_loudness", "WARN")])
        self.assertIn("on a phone speaker: -27.6 LUFS, 13.6 LU under the mix", w[0]["message"])
        self.assertIn("about 9 dB quieter", w[0]["message"])
        self.assertIn("speaker-safe", w[0]["fix"])
        self.assertEqual(run(19.0)[0]["severity"], "FAIL")
        # a soundtrack showtime did not mix (the user's own song, a footage edit's sound): WARN, never a FAIL
        own = run(19.0, showtime_mix=False)
        self.assertEqual(own[0]["severity"], "WARN")
        self.assertIn("showtime did not mix this soundtrack", own[0]["message"])
        self.assertEqual(run(19.0, showtime_mix=True)[0]["severity"], "FAIL")
        off = run(13.6, {"on": False, "set_by": "the mix's master.speaker_safe"})
        self.assertEqual(off[0]["severity"], "INFO")
        capped = run(12.0, {"on": True, "set_by": "default", "capped": True, "shelf_db": -12.0})
        self.assertIn("already cut the bed's lows by 12 dB", capped[0]["fix"])

    def test_03_summary_audio_txt_and_brief(self):
        """The hearing summary line, review-pack's audio.txt and the critic's brief all carry the phone number."""
        from st.qa import hearing, review
        sp = {"integrated_lufs": -14.0, "above_300_lufs": -27.62, "gap_300_lu": 13.62, "above_1k_lufs": -34.01,
              "gap_1k_lu": 20.01}
        blk = {"hop": 0.1, "programme": [-14.0] * 80, "fine_hop": 0.02, "fine": [-14.0] * 400}
        mx = hearing.mix_facts({"tracks": [{"id": "drop", "kind": "sfx", "synth": {"type": "sub-drop"},
                                            "aligned": {"at": 3.0}, "speaker_gap_lu": 23.0, "speaker_alone": True}],
                                "speaker": {"on": True, "set_by": "default", "shelf_db": -12.0, "shelf_hz": 160.0,
                                            "capped": True, "shelved": ["music", "drop"], "gap_300_lu_before": 13.5,
                                            "sub_alone": ["drop"]}}, 0.0, DUR)
        h = hearing.measure(blk, DUR, mix=mx, loud={"integrated_lufs": -14.0}, speaker=sp)
        self.assertIn("on a phone speaker: -27.6 LUFS, 13.6 LU under the mix", hearing.summary(h))
        txt = hearing.text(h, plot=None)
        self.assertIn("Heard on a phone: on a phone speaker: -27.6 LUFS, 13.6 LU under the mix", txt)
        self.assertIn("TOO QUIET ON A PHONE", txt)
        self.assertIn("cut the bed's lows 12 dB at 160 Hz", txt)
        self.assertIn("sub only (23 LU under above 300 Hz)", txt)
        self.assertIn("Heard on a phone", review.hearing_brief("`audio.txt`"))
        self.assertIn("Over 10 LU under", review.hearing_brief("`audio.txt`"))
        crit = (SKILL / "references" / "crew" / "critic.md").read_text(encoding="utf-8")
        self.assertIn("on a phone speaker", crit)

    # ------------------------------------------------------------------ the mixer
    def test_04_mixer_fixes_a_bass_bed(self):
        """Speaker-safe (the default) shelves the bass bed until the mix is within 8 LU above 300 Hz; the full mix
        is still -14 LUFS, so the mix above 300 Hz comes up. Off (flag, mix master, showtime.json) leaves it."""
        tr = [{"id": "bed", "kind": "music", "file": "bass.wav", "level": "raw"}]
        on, _ = self.mix("bass-on", tr)
        off, _ = self.mix("bass-off", tr, speaker_safe_on=False)
        sp, so = on["speaker"], off["speaker"]
        self.assertTrue(sp["on"])
        self.assertEqual(sp["set_by"], "default")
        self.assertGreater(sp["gap_300_lu_before"], 10)
        self.assertLess(sp["shelf_db"], 0)
        self.assertEqual(sp["shelved"], ["music"])
        self.assertLessEqual(sp["gap_300_lu"], 8.6 if sp.get("capped") else 8.3)
        self.assertAlmostEqual(on["integrated_lufs"], -14.0, delta=0.15)
        self.assertGreater(sp["above_300_lufs"] - so["above_300_lufs"], 4.0)
        self.assertFalse(so["on"])
        self.assertGreater(so["gap_300_lu"], 10)
        self.assertTrue(any("on a phone or laptop speaker" in w and "is off" in w for w in off["warnings"]), off["warnings"])
        self.assertFalse(any("on a phone or laptop speaker" in w for w in on["warnings"]), on["warnings"])
        m, _ = self.mix("bass-master-off", tr, master={"speaker_safe": False})
        self.assertEqual((m["speaker"]["on"], m["speaker"]["set_by"]), (False, "the mix's master.speaker_safe"))
        proj = self.tmp / "proj"
        (proj / "audio").mkdir(parents=True, exist_ok=True)
        shutil.copy(self.tmp / "bass.wav", proj / "audio" / "bass.wav")
        (proj / "showtime.json").write_text(json.dumps({"duration": DUR, "master": {"speaker_safe": False}}), encoding="utf-8")
        (proj / "audio" / "mix.json").write_text(json.dumps({"tracks": [dict(tr[0], file="bass.wav")]}), encoding="utf-8")
        from st.audio import mix
        p = mix.render(proj / "audio" / "mix.json", proj / "audio" / "mix.wav")
        self.assertEqual((p["speaker"]["on"], p["speaker"]["set_by"]), (False, "showtime.json master.speaker_safe"))
        saved = json.loads((proj / "audio" / "mix.report.json").read_text(encoding="utf-8"))
        self.assertIn("gap_300_lu", saved["speaker"])

    def test_05_balanced_mix_is_left_alone(self):
        """A mid-rich bed under a voice: no shelf; only the 40 Hz high-pass acts, far under anything audible."""
        import numpy as np
        from st.audio import meter, wav
        tr = [{"id": "bed", "kind": "music", "file": "mids.wav", "gain_db": -6, "duck": {"under": "voice"}},
              {"id": "vo", "kind": "voice", "file": "voice.wav"}]
        on, f_on = self.mix("mids-on", tr)
        off, f_off = self.mix("mids-off", tr, speaker_safe_on=False)
        self.assertEqual(on["speaker"]["shelf_db"], 0.0)
        self.assertNotIn("shelved", on["speaker"])
        self.assertLess(on["speaker"]["gap_300_lu"], 6)
        self.assertAlmostEqual(on["speaker"]["above_300_lufs"], off["speaker"]["above_300_lufs"], delta=0.1)
        a, b = wav.load(f_off).astype(np.float64), wav.load(f_on).astype(np.float64)
        self.assertLess(meter.integrated(b - a), -14.0 - 25)   # the difference is over 25 LU under the mix

    def test_06_voice_untouched_and_deterministic(self):
        """The step never filters the voice bus, and the same spec gives the same bytes."""
        import numpy as np
        from st.audio import mix
        v = np.stack([self.b["voice"], self.b["voice"]], axis=1)
        buses = {"voice": v.copy(), "music": self.b["bass"].copy() * 10}
        rep = mix.speaker_safe(buses, None, [])
        self.assertLess(rep["shelf_db"], 0)
        self.assertTrue(np.array_equal(buses["voice"], v))
        tr = [{"id": "bed", "kind": "music", "file": "bass.wav", "level": "raw", "gain_db": -4},
              {"id": "vo", "kind": "voice", "file": "voice.wav"}]
        _, f1 = self.mix("det-1", tr)
        _, f2 = self.mix("det-2", tr)
        h = [hashlib.sha256(f.read_bytes()).hexdigest() for f in (f1, f2)]
        self.assertEqual(h[0], h[1])

    def test_07_sub_hit_alone_is_named(self):
        """A sub drop with only a riser ending on it is listed (sub_alone); a boom with a metal hit on it is not."""
        tr = [{"id": "bed", "kind": "music", "file": "mids.wav", "gain_db": -8},
              {"id": "riser", "kind": "sfx", "synth": {"type": "noise-riser", "dur": 1.0, "seed": 5}, "at": 2.0, "align": "hit"},
              {"id": "drop", "kind": "sfx", "synth": {"type": "sub-drop", "seed": 25}, "at": 2.0, "align": "hit"},
              {"id": "boom", "kind": "sfx", "synth": {"type": "boom", "dur": 2.0, "seed": 6}, "at": 5.0, "align": "hit"},
              {"id": "clang", "kind": "sfx", "synth": {"type": "metal-hit", "dur": 1.0, "seed": 2}, "at": 5.0,
               "align": "hit", "gain_db": -10}]
        rep, _ = self.mix("subs", tr)
        by = {t["id"]: t for t in rep["tracks"]}
        self.assertGreater(by["drop"]["speaker_gap_lu"], 15)
        self.assertGreater(by["boom"]["speaker_gap_lu"], 15)
        self.assertLess(by["riser"]["speaker_gap_lu"], 5)
        self.assertLess(by["clang"]["speaker_gap_lu"], 10)
        self.assertEqual(rep["speaker"]["sub_alone"], ["drop"])
        self.assertTrue(by["drop"].get("speaker_alone"))
        self.assertFalse(by["boom"].get("speaker_alone"))

    def test_08_cli_flag(self):
        """`showtime audio mix --no-speaker-safe` turns it off and the summary prints the phone number."""
        spec = {"duration": DUR, "tracks": [{"id": "bed", "kind": "music", "file": "bass.wav", "level": "raw"}]}
        (self.tmp / "cli.json").write_text(json.dumps(spec), encoding="utf-8")
        cp = subprocess.run([str(SKILL / "bin" / ("showtime.cmd" if sys.platform == "win32" else "showtime")), "audio",
                             "mix", str(self.tmp / "cli.json"), "-o", str(self.tmp / "cli.wav"), "--no-speaker-safe"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        out = cp.stdout.decode("utf-8", "replace")
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        self.assertIn("on a phone speaker (above 300 Hz)", out)
        self.assertIn("speaker-safe off", out)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_speaker: %.1fs" % (time.time() - t0))
    sys.exit(0 if prog.result.wasSuccessful() else 1)
