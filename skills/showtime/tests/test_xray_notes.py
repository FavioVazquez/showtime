#!/usr/bin/env python3
"""`showtime xray notes` (lib/st/xray_music.py): the numpy port of basic-pitch's note creation against golden notes made
with the original package (two 4 s excerpts in tests/fixtures/xray_notes), synthetic tones at known pitches and times,
the tempo map on jittered onsets, quantizing, key, guitar strings and frets, the MIDI and MusicXML writers read back,
the missing-onnxruntime error and the command end to end on a tiny film.

usage: python tests/test_xray_notes.py [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import struct
import sys
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path
from unittest import mock

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
FIX = TESTS_DIR / "fixtures" / "xray_notes"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff, xray_music as xm  # noqa: E402
from st.common import ShowtimeError  # noqa: E402

SR = xm.SR


def tone(midi, dur=0.9):
    f = 440.0 * 2 ** ((midi - 69) / 12.0)
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(1.0, t / 0.005) * np.exp(-t / 0.5)
    return sum(a * np.sin(2 * np.pi * f * k * t) for k, a in enumerate([1, .5, .3, .2], 1)) * env * 0.25


def synth(spec, total):
    x = np.zeros(int(total * SR), np.float32)
    for m, on in spec:
        y = tone(m)
        a = int(on * SR)
        x[a:a + len(y)] += y
    return x


def note(t, end, pitch, vel=0.7, conf=0.9):
    return {"t": t, "end": end, "pitch": pitch, "velocity": vel, "confidence": conf}


class Golden(unittest.TestCase):
    def check(self, name):
        from st.audio import wav
        gold = json.loads((FIX / ("%s-excerpt.golden.json" % name)).read_text())["notes"]
        x = wav.load(FIX / ("%s-excerpt.ogg" % name), sr=SR, mono=True)
        notes = xm.detect_notes(np.asarray(x, np.float32))
        self.assertLessEqual(abs(len(notes) - len(gold)), max(1, round(0.02 * len(gold))), (len(notes), len(gold)))
        used = set()
        for g in gold:
            hit = [i for i, n in enumerate(notes) if i not in used and n["pitch"] == g["pitch"] and abs(n["t"] - g["t"]) <= xm.FRAME_S + 1e-6]
            self.assertTrue(hit, "no note for %r" % g)
            used.add(hit[0])

    def test_guitar_excerpt(self):
        self.check("fp4")

    def test_piano_excerpt(self):
        self.check("piano")


class Synthetic(unittest.TestCase):
    def test_pitches_and_onsets_come_back(self):
        spec = [(60, 0.5), (64, 1.5), (72, 2.5), (55, 3.5), (62, 4.5), (69, 5.5)]
        notes = xm.detect_notes(synth(spec, 7.0))
        for m, on in spec:
            self.assertTrue([n for n in notes if n["pitch"] == m and abs(n["t"] - on) <= 0.035], "missing %d at %g in %r" % (m, on, notes))
        strong = [n for n in notes if n["velocity"] > 0.5]
        self.assertEqual(sorted(n["pitch"] for n in strong), sorted(m for m, _ in spec))

    def test_silence_has_no_notes(self):
        self.assertEqual(xm.detect_notes(np.zeros(SR * 2, np.float32)), [])

    def test_a_few_milliseconds_of_audio_is_an_error(self):
        with self.assertRaises(ShowtimeError) as cm:
            xm.detect_notes(np.zeros(200, np.float32))
        self.assertIn("no usable audio", str(cm.exception))

    def test_missing_onnxruntime(self):
        with mock.patch.dict(sys.modules, {"onnxruntime": None}):
            with self.assertRaises(ShowtimeError) as cm:
                xm.detect_notes(np.zeros(SR, np.float32))
        self.assertIn("onnxruntime", str(cm.exception))
        self.assertTrue(cm.exception.hint)


class Tempo(unittest.TestCase):
    def test_smooth_on_jittered_onsets(self):
        rng = np.random.RandomState(3)
        true = np.arange(40) * 0.5                                    # 120 bpm, eighth notes
        on = true + rng.uniform(-0.015, 0.015, len(true))
        tm = xm.tempo_map(on)
        self.assertAlmostEqual(tm["bpm"], 120.0, delta=4.0)
        b = np.array(xm.beat_of(true, tm["map"]))
        self.assertLess(np.max(np.abs(b - true * 2.0)), 0.06)         # beats are quarter notes: 2 per second
        mt = np.array([k[0] for k in tm["map"]])
        mb = np.array([k[1] for k in tm["map"]])
        slope = np.diff(mb) / np.diff(mt)
        self.assertTrue(np.all(slope > 0))
        self.assertLess(np.max(np.abs(np.diff(slope[1:-1]))), 0.35)   # beats per second never jumps

    def test_follows_a_slowdown(self):
        t = np.cumsum(np.linspace(0.4, 0.6, 40))
        tm = xm.tempo_map(t)
        s = np.diff([k[1] for k in tm["map"]]) / np.diff([k[0] for k in tm["map"]])
        self.assertGreater(s[2], s[-3])

    def test_beat_time_roundtrip(self):
        tm = xm.tempo_map(np.arange(20) * 0.5)
        for t in (0.1, 2.3, 9.7, 12.0):
            self.assertAlmostEqual(xm.time_of(xm.beat_of(t, tm["map"]), tm["map"]), t, places=6)

    def test_quantize_to_eighths(self):
        tmap = [[0.0, 0.0], [10.0, 20.0]]                             # 2 beats per second
        q = xm.quantize([note(0.01, 0.52, 60), note(0.74, 1.76, 62), note(2.0, 2.05, 64)], tmap)
        self.assertEqual([(r["beat"], r["dur_beats"]) for r in q], [(0.0, 1.0), (1.5, 2.0), (4.0, 0.5)])


class Harmony(unittest.TestCase):
    def test_c_major_scale(self):
        sc = [60, 62, 64, 65, 67, 69, 71, 72]
        notes = [note(i * 0.5, i * 0.5 + 0.5, p) for i, p in enumerate(sc)]
        notes[-1]["end"] = 6.0
        self.assertEqual(xm.detect_key(notes), "C major")

    def test_a_minor(self):
        notes = [note(i * 0.5, i * 0.5 + 0.5, p) for i, p in enumerate([57, 59, 60, 62, 64, 65, 68, 69])]
        notes[0]["end"] = 3.0
        notes[-1]["end"] = 6.0
        self.assertEqual(xm.detect_key(notes), "A minor")

    def test_chords(self):
        tmap = [[0.0, 0.0], [10.0, 10.0]]
        ns = [note(0, 2, 48), note(0, 2, 52), note(0, 2, 55), note(2, 4, 43), note(2, 4, 47), note(2, 4, 50), note(2, 4, 53)]
        ch = xm.chords(ns, tmap)
        self.assertEqual([c["name"] for c in ch], ["C", "G7"])
        self.assertEqual((ch[0]["t"], ch[0]["end"]), (0.0, 2.0))

    def test_voices(self):
        ns = [note(0.0, 1, 72, 0.8), note(0.01, 1, 76, 0.5), note(0.0, 1, 48, 0.6), note(1.0, 2, 50, 0.6), note(1.0, 2, 67, 0.7, 0.2),
              note(2.0, 3, 69, 0.9)]
        v = xm.voices(ns)
        self.assertEqual(v["melody"], [0, 5])                   # loudest at each onset; the 0.2-confidence note is no melody
        self.assertEqual(v["bass"], [2, 3])


class Guitar(unittest.TestCase):
    def test_mapping(self):
        rows = xm.guitar_map([note(0, 0.5, 64), note(1, 1.5, 45), note(2, 2.5, 60), note(3, 3.5, 40), note(4, 4.5, 30)])
        by = {r["i"]: r for r in rows}
        self.assertEqual((by[0]["string"], by[0]["fret"], by[0]["finger"]), (1, 0, "a"))
        self.assertEqual((by[1]["string"], by[1]["fret"], by[1]["finger"]), (5, 0, "p"))
        self.assertEqual((by[2]["string"], by[2]["fret"]), (2, 1))
        self.assertEqual((by[3]["string"], by[3]["fret"]), (6, 0))
        self.assertNotIn(4, by)                                  # below the neck: left out

    def test_ringing_string_is_avoided(self):
        rows = xm.guitar_map([note(0, 2.0, 59), note(0.5, 1.0, 59)])
        self.assertNotEqual(rows[0]["string"], rows[1]["string"])


def read_midi(data: bytes):
    """A tiny reader: (ppq, tempo_us, [(start_tick, end_tick, pitch, velocity)])."""
    assert data[:4] == b"MThd"
    ln, fmt, ntrk, ppq = struct.unpack(">IHHH", data[4:14])
    assert (ln, fmt, ntrk) == (6, 0, 1)
    assert data[14:18] == b"MTrk"
    size = struct.unpack(">I", data[18:22])[0]
    trk = data[22:22 + size]
    assert len(trk) == size
    i, tick, tempo, on, out = 0, 0, None, {}, []
    while i < len(trk):
        d = 0
        while True:
            b = trk[i]
            i += 1
            d = (d << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        tick += d
        st = trk[i]
        if st == 0xFF:
            typ, n = trk[i + 1], trk[i + 2]
            if typ == 0x51:
                tempo = int.from_bytes(trk[i + 3:i + 6], "big")
            i += 3 + n
            if typ == 0x2F:
                break
        elif st & 0xF0 == 0x90:
            on[trk[i + 1]] = (tick, trk[i + 2])
            i += 3
        elif st & 0xF0 == 0x80:
            s, v = on.pop(trk[i + 1])
            out.append((s, tick, trk[i + 1], v))
            i += 3
        else:
            raise AssertionError("event %x" % st)
    assert not on
    return ppq, tempo, sorted(out)


class Writers(unittest.TestCase):
    NOTES = [note(0.0, 0.5, 60, 0.5), note(0.5, 1.0, 64, 0.8), note(1.0, 2.0, 67, 1.0), note(1.0, 2.0, 48, 0.25)]

    def test_midi_reads_back(self):
        ppq, tempo, ev = read_midi(xm.midi_bytes(self.NOTES, 120.0))
        self.assertEqual((ppq, tempo), (480, 500000))
        self.assertEqual([(s, e, p) for s, e, p, _ in ev], [(0, 480, 60), (480, 960, 64), (960, 1920, 48), (960, 1920, 67)])
        self.assertEqual([v for *_, v in ev], [64, 102, 32, 127])

    def test_musicxml(self):
        tmap = [[0.0, 0.0], [10.0, 20.0]]
        ns = self.NOTES + [note(2.0, 4.6, 72, 0.7)]                    # a long note: tied over the bar line
        q = xm.quantize(ns, tmap)
        for two in (False, True):
            xml = xm.musicxml(ns, q, 120.0, "C major", bass=[3], two_staves=two)
            dom = xml.encode("utf-8")
            doc = xml_parse(dom)
            pitched = [n for n in doc.getElementsByTagName("note") if n.getElementsByTagName("pitch")]
            tied_stops = [n for n in pitched if n.getElementsByTagName("tie") and n.getElementsByTagName("tie")[0].getAttribute("type") == "stop"]
            self.assertEqual(len(pitched) - len(tied_stops), len(ns))
            self.assertEqual(len(doc.getElementsByTagName("part")), 1)
            if two:
                self.assertEqual(doc.getElementsByTagName("staves")[0].firstChild.data, "2")
            for m in doc.getElementsByTagName("measure"):          # every staff fills its measure exactly
                tot = {}
                for n in m.getElementsByTagName("note"):
                    if n.getElementsByTagName("chord"):
                        continue
                    stf = n.getElementsByTagName("staff")
                    k = stf[0].firstChild.data if stf else "1"
                    tot[k] = tot.get(k, 0) + int(n.getElementsByTagName("duration")[0].firstChild.data)
                self.assertTrue(all(v == xm.MEASURE for v in tot.values()), tot)


def xml_parse(b: bytes):
    return xml.dom.minidom.parseString(b)


class Command(unittest.TestCase):
    def test_end_to_end(self):
        import soundfile as sf
        from st.launcher import build_env, showtime_home
        import subprocess
        spec = [(60, 0.4), (64, 0.9), (67, 1.4), (72, 1.9)]
        x = synth(spec, 3.0)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            sf.write(str(td / "a.wav"), x, SR, subtype="PCM_16")
            ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=160x90:r=30:d=3", "-i", str(td / "a.wav"), "-c:v", "libx264",
                           "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(td / "f.mp4")])
            job = td / "job"
            cp = subprocess.run([sys.executable, str(LAUNCHER), "xray", "notes", str(td / "f.mp4"), "--job", str(job), "--instrument", "guitar"],
                                env=build_env(showtime_home()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=600)
            self.assertEqual(cp.returncode, 0, cp.stderr[-1500:])
            d = job / "xray"
            doc = json.loads((d / "notes.json").read_text())
            self.assertEqual(doc["schema"], "showtime.xray.notes/1")
            self.assertEqual(doc["engine"], "basic-pitch-onnx")
            self.assertEqual(doc["source"]["fps"], 30)
            got = {(n["pitch"]) for n in doc["notes"] if n["velocity"] > 0.5}
            self.assertEqual(got, {60, 64, 67, 72})
            for n in doc["notes"]:
                self.assertEqual(n["frame"], int(np.floor(n["t"] * 30 + 1e-9)))
            self.assertEqual(len(doc["quantized"]), len(doc["notes"]))
            self.assertTrue(doc["guitar"])
            self.assertEqual(doc["key"].split()[1] in ("major", "minor"), True)
            read_midi((d / "notes.mid").read_bytes())
            xml_parse((d / "notes.musicxml").read_bytes())
            self.assertGreater((d / "check-notes.jpg").stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1, argv=[a for a in sys.argv if a not in ("-v", "--fast")])
