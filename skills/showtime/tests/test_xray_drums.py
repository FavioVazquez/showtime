#!/usr/bin/env python3
"""`showtime xray notes --instrument drums` (lib/st/xray_drums.py): a synthetic kit (kick = decaying 55 Hz sine with a click,
snare = noise burst + 190 Hz, closed/open hats and a crash = high-passed noise of different lengths, a tom = a 110 Hz tone
with a pitch drop) playing a known two-bar groove at 80..160 bpm -> the pieces and onsets come back. It is a classifier of
sound types: the accuracy here is on this synthetic kit, a hat under a (white-noise) snare is not seen and is not in the groove.

usage: python tests/test_xray_drums.py [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

import numpy as np
from scipy import signal

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))
sys.path.insert(0, str(TESTS_DIR))

from st import ff, xray_drums as xd, xray_music as xm  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from test_xray_notes import read_midi  # noqa: E402

SR = xd.SR


def _hp(x, fc):
    return signal.sosfilt(signal.butter(4, fc, "hp", fs=SR, output="sos"), x)


def kick():
    t = np.arange(int(.4 * SR)) / SR
    y = 0.8 * np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.12)
    n = int(.002 * SR)
    y[:n] += 0.3 * np.random.RandomState(1).randn(n)
    return y


def snare():
    t = np.arange(int(.3 * SR)) / SR
    return 0.4 * np.random.RandomState(2).randn(len(t)) * np.exp(-t / 0.06) + 0.3 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.08)


def noise_hit(tau, dur, amp=0.25, fc=6000, seed=3):
    t = np.arange(int(dur * SR)) / SR
    return amp * _hp(np.random.RandomState(seed).randn(len(t)), fc) * np.exp(-t / tau)


def tom(f=110):
    t = np.arange(int(.5 * SR)) / SR
    return 0.7 * np.sin(2 * np.pi * (f * (1 + 0.2 * np.exp(-t / 0.03))) * t) * np.exp(-t / 0.15)


SOUNDS = {"kick": kick, "snare": snare, "hihat_closed": lambda: noise_hit(0.015, 0.1), "hihat_open": lambda: noise_hit(0.12, 0.6),
          "crash": lambda: noise_hit(0.4, 1.4, 0.3), "tom": tom}


def groove(bpm=100):
    """Two bars on eighths plus a crash on the next downbeat: hats on every eighth except under the snare, an open hat on the
    last eighth of bar 1, a tom on the 6th eighth of bar 2."""
    e = 60.0 / bpm / 2
    truth = []

    def at(i, p):
        truth.append((0.4 + i * e, p))
    for i in range(16):
        if i not in (2, 6, 10, 14):
            at(i, "hihat_open" if i == 7 else "hihat_closed")
    for i in (0, 4, 6, 8, 12, 16):
        at(i, "kick")
    for i in (2, 6, 10, 14):
        at(i, "snare")
    at(16, "crash")
    at(13, "tom")
    return sorted(truth)


def render(truth, total, noise=0.003):
    x = np.zeros(int(total * SR))
    for t, p in truth:
        y = SOUNDS[p]()
        a = int(t * SR)
        x[a:a + len(y)] += y[:len(x) - a]
    return (x + np.random.RandomState(0).randn(len(x)) * noise).astype(np.float32)


def score(truth, hits, tol=0.03):
    got = [(h["t"], h["piece"]) for h in hits]
    used, tp = set(), 0
    for t, p in truth:
        m = [k for k, (a, b) in enumerate(got) if k not in used and b == p and abs(a - t) <= tol]
        if m:
            used.add(m[0])
            tp += 1
    return tp, len(truth), len(got) - tp


class Kit(unittest.TestCase):
    def test_groove_at_several_tempos(self):
        for bpm in (80, 100, 130, 160):
            truth = groove(bpm)
            hits = xd.detect_hits(render(truth, 0.4 + 16 * 60.0 / bpm / 2 + 2.5))
            tp, n, extra = score(truth, hits)
            self.assertGreaterEqual(tp, n - 1, "%d bpm: %d of %d" % (bpm, tp, n))      # at most one hit missed
            self.assertLessEqual(extra, 1, "%d bpm: %d extra" % (bpm, extra))

    def test_each_piece_found(self):
        truth = groove(100)
        pieces = {h["piece"] for h in xd.detect_hits(render(truth, 8.0))}
        self.assertEqual(pieces, {"kick", "snare", "hihat_closed", "hihat_open", "crash", "tom"})

    def test_kick_and_hat_on_one_onset_are_two_hits(self):
        truth = [(0.5, "kick"), (0.5, "hihat_closed"), (1.2, "hihat_closed"), (1.9, "kick")]
        hits = xd.detect_hits(render(truth, 3.0))
        at = sorted(h["piece"] for h in hits if abs(h["t"] - 0.5) < 0.03)
        self.assertEqual(at, ["hihat_closed", "kick"])

    def test_silence_has_no_hits(self):
        self.assertEqual(xd.detect_hits(np.zeros(SR * 2, np.float32)), [])


class Files(unittest.TestCase):
    def test_command_end_to_end(self):
        import soundfile as sf
        truth = groove(100)
        x = render(truth, 8.0)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            sf.write(str(td / "a.wav"), x, SR, subtype="PCM_16")
            ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=8", "-i", str(td / "a.wav"), "-c:v", "libx264",
                           "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(td / "d.mkv")])
            cp = subprocess.run([sys.executable, str(LAUNCHER), "xray", "notes", str(td / "d.mkv"), "--job", str(td / "job"), "--instrument", "drums"],
                                env=build_env(showtime_home()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=600)
            self.assertEqual(cp.returncode, 0, cp.stderr[-1500:])
            d = td / "job" / "xray"
            doc = json.loads((d / "notes.json").read_text())
            self.assertEqual(doc["instrument"], "drums")
            self.assertIn("classifier", doc["note"])
            self.assertEqual(doc["notes"], [])
            tp, n, extra = score(truth, [{"t": h["t"], "piece": h["piece"]} for h in doc["drums"]])
            self.assertGreaterEqual(tp, n - 1)
            for h in doc["drums"]:
                self.assertEqual(h["frame"], int(np.floor(h["t"] * 30 + 1e-9)))
            self.assertEqual(len(doc["quantized"]), len(doc["drums"]))
            self.assertAlmostEqual(doc["tempo"]["bpm"], 100.0, delta=8.0)
            # sixteenth grid: the groove is on eighths, from beat 0.5 on (the first hit sits at 0.4 s)
            b = sorted({q["beat"] for q in doc["quantized"]})
            self.assertTrue(all(abs(v * 2 - round(v * 2)) < 1e-9 for v in b), b)
            # MIDI: channel 10, the GM drum notes
            raw = (d / "notes.mid").read_bytes()
            ppq, tempo, ev = read_midi(raw.replace(b"\x99", b"\x90").replace(b"\x89", b"\x80"))
            self.assertIn(b"\x99", raw)
            self.assertEqual({p for *_, p, _v in ev}, {36, 38, 42, 46, 49, 45, 48, 50} & {h["gm"] for h in doc["drums"]})
            # MusicXML: well formed, a percussion staff, one unpitched note per hit
            dom = xml.dom.minidom.parseString((d / "notes.musicxml").read_bytes())
            self.assertEqual(dom.getElementsByTagName("sign")[-1].firstChild.data, "percussion")
            hits = [n for n in dom.getElementsByTagName("note") if n.getElementsByTagName("unpitched")]
            self.assertEqual(len(hits) - len([n for n in hits if n.getElementsByTagName("tie") and n.getElementsByTagName("tie")[0].getAttribute("type") == "stop"]),
                             len(doc["drums"]))
            self.assertTrue(any(n.getElementsByTagName("notehead") for n in hits))
            self.assertGreater((d / "check-notes.jpg").stat().st_size, 5000)


class Score(unittest.TestCase):
    def test_measures_are_full(self):
        hits = [{"i": 0, "piece": "kick", "gm": 36}, {"i": 1, "piece": "hihat_closed", "gm": 42}, {"i": 2, "piece": "snare", "gm": 38},
                {"i": 3, "piece": "tom", "gm": 48}]
        quant = [{"beat": 0.0}, {"beat": 0.0}, {"beat": 1.5}, {"beat": 5.25}]
        dom = xml.dom.minidom.parseString(xd.musicxml(hits, quant, 100.0).encode())
        for m in dom.getElementsByTagName("measure"):
            tot = sum(int(n.getElementsByTagName("duration")[0].firstChild.data) for n in m.getElementsByTagName("note")
                      if not n.getElementsByTagName("chord"))
            self.assertEqual(tot, xd.MEASURE)
        self.assertEqual(len(dom.getElementsByTagName("measure")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1, argv=[a for a in sys.argv if a != "-v"])
