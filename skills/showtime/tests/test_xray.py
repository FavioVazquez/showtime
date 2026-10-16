#!/usr/bin/env python3
"""`showtime xray analyze` and `verify` (lib/st/xray.py, cli_xray.py): the onset detector on synthetic clicks (exact
event times and frames, min-gap merging and the dropped list, a click's precursor), analyze end to end on a tiny
film, verify against lavfi films with a 6x6 sync marker flashing on chosen frames (matched, missing, extra, one frame
off, no marker), the audio lag of a delayed copy, the scroll smoothness report (stalls and jumps), the receipt and qa
hooks, and the tracker on a synthetic moving texture (seeded, with a tolerance).

Everything is generated here (no fixtures, no browser, no downloads) and deterministic.

usage: python tests/test_xray.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff, xray  # noqa: E402
from st.common import ShowtimeError, write_json  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
SR = 48000
FPS = 30
W, H = 320, 180
CLICKS = [0.60, 1.23, 1.80, 2.55, 3.10, 3.97]          # seconds
LEVELS = [0.50, 0.30, 0.45, 0.20, 0.50, 0.35]


def click_wave(times, levels=None, dur=5.0, seed=7, noise=0.002, extra=()):
    """Mono float32 at 48 kHz: a low noise floor and a decaying noise burst (about 12 ms) at each time."""
    rng = np.random.RandomState(seed)
    x = rng.randn(int(dur * SR)) * noise
    levels = levels or [0.4] * len(times)
    for t, lv in list(zip(times, levels)) + list(extra):
        n = int(0.05 * SR)
        a = int(round(t * SR))
        env = np.exp(-np.arange(n) / (0.004 * SR))
        env[: int(0.0003 * SR)] *= np.linspace(0.2, 1.0, int(0.0003 * SR))
        x[a: a + n] += rng.randn(n)[: len(x[a: a + n])] * env[: len(x[a: a + n])] * lv
    return x.astype(np.float32)


def write_wav(path: Path, x) -> Path:
    import soundfile as sf
    sf.write(str(path), x, SR, subtype="PCM_16")
    return path


def st(*args, check=True):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=600)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                      cp.stdout[-2000:], cp.stderr[-2000:]))
    return cp


def make_film(path: Path, audio: Path, flashes, seconds=5.0, delay_ms=0.0, marker=True) -> Path:
    """320x180 black film at 30 fps with a 6x6 white square at (W-10, H-10) on the given frames, and `audio`."""
    vf = "format=yuv420p"
    if marker and flashes:
        enable = "+".join("eq(n,%d)" % f for f in flashes)
        vf = "drawbox=x=%d:y=%d:w=6:h=6:color=white:t=fill:enable='%s',format=yuv420p" % (W - 10, H - 10, enable)
    af = "adelay=%d|%d" % (round(delay_ms), round(delay_ms)) if delay_ms else "anull"
    ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%d:d=%g" % (W, H, FPS, seconds), "-i", str(audio),
                   "-vf", vf, "-af", af, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10",
                   "-c:a", "pcm_s16le", "-shortest", str(path)])
    return path


def make_scaled_film(path: Path, audio: Path, flashes, page_w: int, page_h: int, seconds=5.0) -> Path:
    """A page_w x page_h page with the 6x6 marker at (page_w - 10, page_h - 10) on the given frames, scaled down to
    the 320x180 film the way a --preview render is (bicubic, a draft encode)."""
    enable = "+".join("eq(n,%d)" % f for f in flashes)
    vf = "drawbox=x=%d:y=%d:w=6:h=6:color=white:t=fill:enable='%s',scale=%d:%d,format=yuv420p" % (
        page_w - 10, page_h - 10, enable, W, H)
    ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=0x101418:s=%dx%d:r=%d:d=%g" % (page_w, page_h, FPS, seconds), "-i", str(audio),
                   "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                   "-c:a", "pcm_s16le", "-shortest", str(path)])
    return path


def within(a, b, tol):
    return abs(a - b) <= tol


class Detector(unittest.TestCase):
    def test_frame_rule(self):
        self.assertEqual(xray.frame_of(2.183, 30), 65)
        self.assertEqual(xray.frame_of(1.0, 30), 30)
        self.assertEqual(xray.frame_of(0.1 * 3, 30), 9)          # 0.30000000000000004 * 30 must not tip over
        self.assertEqual(xray.frame_of(2.0, 29.97), 59)

    def test_clicks_found_at_their_times(self):
        x = click_wave(CLICKS, LEVELS)
        ev, dropped = xray.detect(x)
        self.assertEqual(len(ev), len(CLICKS), (ev, dropped))
        for e, t in zip(ev, CLICKS):
            self.assertTrue(within(e["t"], t, 0.003), (e, t))
            self.assertEqual(xray.frame_of(e["t"], FPS), xray.frame_of(t, FPS) if abs(e["t"] - t) < 0.0005 else
                             xray.frame_of(e["t"], FPS))
            self.assertEqual(e["band"], "high")
        self.assertEqual([e["i"] for e in ev], list(range(len(CLICKS))))
        strengths = [e["strength"] for e in ev]
        self.assertAlmostEqual(max(strengths), 1.0, places=3)
        self.assertTrue(strengths[3] < 0.6 < strengths[0], strengths)       # 0.2 vs 0.5 amplitude

    def test_deterministic(self):
        x = click_wave(CLICKS, LEVELS)
        self.assertEqual(xray.detect(x), xray.detect(x.copy()))

    def test_loudness_does_not_move_the_events(self):
        x = click_wave(CLICKS, LEVELS)
        a, _ = xray.detect(x)
        b, _ = xray.detect(x * 0.25)
        c, _ = xray.detect(np.clip(x * 1.8, -1, 1))
        self.assertEqual([e["t"] for e in a], [e["t"] for e in b])
        self.assertEqual([e["t"] for e in a], [e["t"] for e in c])

    def test_from_to_window(self):
        x = click_wave(CLICKS, LEVELS)
        ev, _ = xray.detect(x[int(1.0 * SR): int(3.2 * SR)], t_from=1.0, t_to=3.2)
        self.assertEqual([round(e["t"], 1) for e in ev], [1.2, 1.8, 2.6, 3.1])

    def test_min_gap_merge_keeps_the_first_and_says_so(self):
        x = click_wave([1.0, 1.08, 2.0], [0.5, 0.45, 0.5])
        ev, dropped = xray.detect(x, min_gap=0.12)
        self.assertEqual(len(ev), 2, ev)
        self.assertTrue(within(ev[0]["t"], 1.0, 0.003))
        d = [x for x in dropped if "min_gap" in x["why"]]
        self.assertEqual(len(d), 1, dropped)
        self.assertTrue(within(d[0]["t"], 1.08, 0.004), d)
        self.assertIn("event 0", d[0]["why"])
        ev2, _ = xray.detect(x, min_gap=0.05)
        self.assertEqual(len(ev2), 3, ev2)

    def test_precursor_before_a_louder_click_is_not_an_event(self):
        x = click_wave([1.0, 2.0], [0.5, 0.5], extra=[(1.95, 0.04)])     # a faint tick 50 ms before the click at 2.0
        ev, dropped = xray.detect(x)
        self.assertEqual(len(ev), 2, (ev, dropped))
        self.assertTrue(within(ev[1]["t"], 2.0, 0.003), ev)

    def test_quiet_noise_is_not_an_event(self):
        rng = np.random.RandomState(3)
        x = (rng.randn(3 * SR) * 0.003).astype(np.float32)
        ev, _ = xray.detect(x)
        self.assertLessEqual(len(ev), 2, ev)
        self.assertEqual(xray.detect(np.zeros(SR, dtype=np.float32))[0], [])

    def test_low_band(self):
        t = np.arange(int(0.2 * SR)) / SR
        thump = (np.sin(2 * np.pi * 90 * t) * np.exp(-t / 0.03) * 0.6).astype(np.float32)
        x = np.zeros(2 * SR, dtype=np.float32)
        x += np.random.RandomState(1).randn(len(x)).astype(np.float32) * 0.001
        x[SR: SR + len(thump)] += thump
        # the detector high-passes at 500 Hz to follow the attack; a thump's attack still reads as one event and its band is low
        ev, _ = xray.detect(x, sensitivity=0.8)
        self.assertTrue(ev, "the thump is detected as an event")
        self.assertEqual(ev[0]["band"], "low")


NOTE_TIMES = [round(0.5 + 0.12 * k, 3) for k in range(25)]


def chord_bed(times=NOTE_TIMES, dur=4.0, seed=2):
    """A steady three-note chord with a new plucked note entering at each time (every 120 ms): sustained, dense sound."""
    rng = np.random.RandomState(seed)
    t = np.arange(int(dur * SR)) / SR
    x = sum(0.12 * np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6)) + rng.randn(len(t)) * 0.003
    pitches = [880.0, 1046.5, 1318.5, 1568.0, 1174.7, 987.8]
    for k, tn in enumerate(times):
        a = int(round(tn * SR))
        u = np.arange(min(int(0.3 * SR), len(x) - a)) / SR
        x[a: a + len(u)] += 0.25 * np.sin(2 * np.pi * pitches[k % 6] * u) * np.minimum(u / 0.002, 1.0) * np.exp(-u / 0.12)
    return x.astype(np.float32)


def errors_ms(events, times):
    ts = np.array([e["t"] for e in events]) if events else np.array([9e3])
    return [float(np.min(np.abs(ts - t))) * 1000.0 for t in times]


class Flux(unittest.TestCase):
    """The flux engine on a sustained chord with a note entering every 120 ms (the envelope engine cannot see them):
    all 25 found, median error about 1 ms, worst under 10 ms (measured: 1 ms median, 9 ms worst, 3 extra events)."""

    def test_flux_finds_the_notes_and_envelope_does_not(self):
        x = chord_bed()
        ev, dropped = xray.detect_flux(x)
        err = errors_ms(ev, NOTE_TIMES)
        self.assertLess(max(err), 10.0, err)
        self.assertLessEqual(float(np.median(err)), 2.0, err)
        self.assertLessEqual(len(ev) - len(NOTE_TIMES), 4, [e["t"] for e in ev])
        self.assertEqual([e["i"] for e in ev], list(range(len(ev))))
        self.assertTrue(all(0.0 < e["strength"] <= 1.0 for e in ev))
        self.assertTrue(all(b["t"] - a["t"] >= 0.06 - 1e-6 for a, b in zip(ev, ev[1:])))
        env_ev, _ = xray.detect(x)
        self.assertLess(sum(1 for e in errors_ms(env_ev, NOTE_TIMES) if e < 10.0), 5, len(env_ev))
        self.assertTrue(xray.is_sustained(x))

    def test_flux_is_deterministic_and_respects_from_to(self):
        x = chord_bed()
        self.assertEqual(xray.detect_flux(x), xray.detect_flux(x.copy()))
        a, b = 1.0, 2.5
        ev, _ = xray.detect_flux(x[int(a * SR): int(b * SR)], t_from=a, t_to=b)
        self.assertTrue(ev and min(e["t"] for e in ev) >= a - 0.001 and max(e["t"] for e in ev) <= b)

    def test_auto_picks_flux_for_music_and_envelope_for_clicks(self):
        ran, mg, why, ev, _ = xray.pick_engine(chord_bed(), "auto")
        self.assertEqual((ran, mg), ("flux", 0.06))
        self.assertIn("spectral flux", why)
        self.assertGreaterEqual(len(ev), 25)
        ran, mg, why, ev, _ = xray.pick_engine(click_wave(CLICKS, LEVELS), "auto")
        self.assertEqual((ran, mg), ("envelope", 0.12))
        self.assertEqual(len(ev), len(CLICKS))
        self.assertEqual(xray.pick_engine(click_wave(CLICKS, LEVELS), "flux")[0], "flux")
        self.assertEqual(xray.pick_engine(chord_bed(), "envelope")[0], "envelope")
        with self.assertRaises(ShowtimeError):
            xray.pick_engine(chord_bed(), "magic")

    def test_analyze_records_the_engine_and_why(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        try:
            wav = write_wav(tmp / "bed.wav", chord_bed())
            clip = make_film(tmp / "bed.mkv", wav, [], seconds=4.0)
            doc = xray.analyze(clip, tmp / "o")
            self.assertEqual(doc["detector"]["engine"], "flux")
            self.assertEqual(doc["detector"]["min_gap"], 0.06)
            self.assertIn("auto", doc["detector"]["note"])
            self.assertGreaterEqual(len(doc["events"]), 25)
            self.assertEqual(xray.analyze(clip, tmp / "o2", engine="envelope")["detector"]["engine"], "envelope")
            cp = st("xray", "analyze", clip, "--job", tmp / "j", "--engine", "flux", "--json")
            self.assertEqual(json.loads(cp.stdout[cp.stdout.index("{"):])["detector"]["note"], "asked for flux")
        finally:
            shutil.rmtree(tmp, True)


class Vfr(unittest.TestCase):
    def test_vfr_rule(self):
        self.assertTrue(xray._is_vfr({"r_fps": 30.0, "avg_fps": 24.0}))
        self.assertFalse(xray._is_vfr({"r_fps": 30.0, "avg_fps": 29.97}))
        self.assertFalse(xray._is_vfr({"r_fps": None, "avg_fps": 30.0}))

    def test_source_info_and_message(self):
        from unittest import mock
        pr = {"has_video": True, "fps": 24.0, "r_fps": 30.0, "avg_fps": 24.0, "width": 8, "height": 8, "has_audio": True, "duration": 1.0}
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "c.mp4"
            clip.write_bytes(b"x")
            with mock.patch.object(xray.ff, "probe", return_value=pr):
                info = xray._source_info(clip)
        self.assertTrue(info["vfr"])
        self.assertIn("showtime footage trim", xray.VFR_WARNING)
        self.assertIn("--webm", xray.VFR_WARNING)


class TrackRow(unittest.TestCase):
    def test_a_failed_extraction_does_not_shift_the_pairing(self):
        from PIL import Image
        from unittest import mock
        from st.qa import media
        doc = {"source": {"fps": 30, "width": 64, "height": 36, "duration": 2.0}}
        n = 20
        Hs = [[1, 0, float(k), 0, 1, 0, 0, 0, 1] for k in range(n)]
        tr = {"region": [[2, 2], [30, 2], [30, 20], [2, 20]], "H": Hs}

        def fake(video, times, out_dir, names=None, width=None, **kw):
            out = []
            for nm in names:
                if nm == "f4.jpg":
                    continue                              # this one fails
                p = Path(out_dir) / nm
                Image.new("RGB", (width, int(width * 36 / 64)), (40, 40, 40)).save(str(p))
                out.append(p)
            return out
        img = Image.new("RGB", (600, 100))
        with mock.patch.object(media, "extract_frames", side_effect=fake):
            out = xray._with_track_row(img, Path("clip.mp4"), doc, tr)
        self.assertGreater(out.height, img.height)


class Analyze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        cls.wav = write_wav(cls.tmp / "clicks.wav", click_wave(CLICKS, LEVELS))
        cls.clip = make_film(cls.tmp / "clip.mkv", cls.wav, [])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_xray_json_and_check_sheet(self):
        out = self.tmp / "a1"
        doc = xray.analyze(self.clip, out)
        self.assertEqual(doc["schema"], "showtime.xray/1")
        src = doc["source"]
        self.assertEqual((src["file"], src["fps"], src["width"], src["height"]), ("clip.mkv", 30, W, H))
        self.assertEqual(len(src["sha256"]), 64)
        self.assertAlmostEqual(src["duration"], 5.0, delta=0.1)
        det = dict(doc["detector"])
        self.assertIn("envelope engine", det.pop("note"))
        self.assertEqual(det, {"engine": "envelope", "min_gap": 0.12, "sensitivity": 0.5, "from": 0.0, "to": None})
        self.assertEqual([e["frame"] for e in doc["events"]], [xray.frame_of(e["t"], 30) for e in doc["events"]])
        self.assertEqual(len(doc["events"]), len(CLICKS))
        self.assertEqual(set(doc["events"][0]), {"i", "t", "frame", "strength", "band"})
        self.assertIsNone(doc["track"])
        self.assertEqual(json.loads((out / "xray.json").read_text(encoding="utf-8")), doc)
        from PIL import Image
        with Image.open(str(out / "check.jpg")) as im:
            self.assertGreater(im.width, 1000)

    def test_cli_creates_a_job_and_prints_the_files(self):
        base = self.tmp / "cli"
        base.mkdir()
        job = base / "xjob"
        cp = st("xray", "analyze", self.clip, "--job", job, "--min-gap", "0.2", "--json")
        doc = json.loads(cp.stdout[cp.stdout.index("{"):])
        self.assertEqual(doc["detector"]["min_gap"], 0.2)
        self.assertTrue((job / "xray" / "xray.json").is_file())
        self.assertTrue((job / "xray" / "check.jpg").is_file())
        bad = st("xray", "analyze", self.clip, "--job", job, "--track", check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("--region", bad.stderr)
        self.assertEqual(st("xray", "analyze", self.clip, "--sensitivity", "3", check=False).returncode, 1)


class Refusals(unittest.TestCase):
    """A clip that cannot be analyzed is refused before anything is created for it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        cls.silent = cls.tmp / "silent.mkv"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.silent)])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_no_stray_job_or_output_for_a_bad_clip(self):
        for n, (cmd, clip) in enumerate((("analyze", self.tmp / "missing.mkv"), ("notes", self.tmp / "missing.mkv"),
                                         ("analyze", self.silent), ("notes", self.silent))):
            job = self.tmp / ("job%d" % n)
            cp = st("xray", cmd, clip, "--job", job, check=False)
            self.assertEqual(cp.returncode, 1, cp.stderr)
            self.assertFalse(job.exists(), "%s %s left %s" % (cmd, clip.name, job))
        out = self.tmp / "direct"
        with self.assertRaises(ShowtimeError):
            xray.analyze(self.silent, out)
        self.assertFalse(out.exists())


class Verify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        cls.wav = write_wav(cls.tmp / "clicks.wav", click_wave(CLICKS, LEVELS))
        cls.clip = make_film(cls.tmp / "clip.mkv", cls.wav, [])
        cls.frames = [xray.frame_of(t, FPS) for t in CLICKS]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def job(self, name, frames=None):
        """A job folder whose xray.json holds events on `frames` (default: the clicks' frames)."""
        j = self.tmp / name
        (j / "xray").mkdir(parents=True)
        fr = self.frames if frames is None else frames
        write_json(j / "job.json", {"schema": 1, "slug": name})
        write_json(j / "xray" / "xray.json", {
            "schema": "showtime.xray/1", "source": {"file": "clip.mkv", "sha256": "0" * 64, "fps": 30, "duration": 5.0,
                                                     "width": W, "height": H},
            "detector": {"engine": "envelope", "min_gap": 0.12, "sensitivity": 0.5, "from": 0.0, "to": None},
            "events": [{"i": i, "t": round(f / 30.0, 3), "frame": f, "strength": 1.0, "band": "high"} for i, f in enumerate(fr)],
            "dropped": [], "track": None})
        (j / "xray" / "source.path").write_text(str(self.clip), encoding="utf-8")
        return j

    def test_all_events_on_their_frame(self):
        j = self.job("ok")
        film = make_film(j / "final.mkv", self.wav, self.frames)
        r = xray.verify(j, film)
        self.assertTrue(r["marker"])
        self.assertEqual((r["events"], r["on_frame"], r["missing"], r["extra"]), (6, 6, [], []))
        self.assertEqual(r["status"], "PASS", r)
        self.assertLess(abs(r["audio_lag_ms"]), 2.0, r)
        self.assertEqual(r["line"].split(" · ")[0], "6 of 6 events on their frame")
        self.assertIn("ms from the original", r["line"])
        self.assertEqual(json.loads((j / "xray" / "verify.json").read_text(encoding="utf-8"))["on_frame"], 6)

    def test_missing_and_extra_fail(self):
        j = self.job("bad")
        flashes = [f for f in self.frames if f != self.frames[2]] + [140]
        film = make_film(j / "final.mkv", self.wav, flashes)
        r = xray.verify(j, film)
        self.assertEqual(r["missing"], [self.frames[2]])
        self.assertEqual(r["extra"], [140])
        self.assertEqual(r["on_frame"], 5)
        self.assertEqual(r["status"], "FAIL")
        self.assertEqual(r["line"].split(" · ")[0], "5 of 6 events on their frame")
        self.assertEqual(r["findings"][0]["rule"], "xray_sync")

    def test_one_frame_off_is_matched_with_its_offset_but_not_exact(self):
        j = self.job("off")
        flashes = list(self.frames)
        flashes[1] += 1
        film = make_film(j / "final.mkv", self.wav, flashes)
        r = xray.verify(j, film)
        self.assertEqual((r["on_frame"], r["missing"], r["extra"], r["max_offset"]), (5, [], [], 1))
        self.assertEqual(r["off_by"], [{"expected": self.frames[1], "on": self.frames[1] + 1, "offset": 1}])
        self.assertEqual(r["status"], "WARN")

    def test_offset_frames_shift_the_expectation(self):
        j = self.job("offs")
        film = make_film(j / "final.mkv", self.wav, [f + 15 for f in self.frames], seconds=6.0, delay_ms=500)
        r = xray.verify(j, film, offset_frames=15)
        self.assertEqual((r["events"], r["on_frame"], r["status"]), (6, 6, "PASS"), r)
        self.assertLess(abs(r["audio_lag_ms"]), 2.0, r)       # the film's sound is 15 frames late on purpose: not counted

    def test_offset_and_band_come_from_the_project_config(self):
        j = self.job("cfg")
        (j / "project").mkdir()
        write_json(j / "project" / "showtime.json", {"xray": {"marker": True, "offset_frames": 15, "band": [100, 140]}})
        film = make_film(j / "final.mkv", self.wav, [f + 15 for f in self.frames], seconds=6.0, delay_ms=500)
        r = xray.verify(j, film)                                   # no flags: qa calls it like this
        self.assertEqual((r["on_frame"], r["status"], r["offset_frames"]), (6, "PASS", 15), r)
        self.assertEqual(r["smoothness"]["frames"], r["film_frames"])           # the band rows 100..140, read from the config
        r2 = xray.verify(j, film, offset_frames=0)                 # a flag wins over the file
        self.assertEqual(r2["status"], "FAIL")
        self.assertEqual(xray.project_config(self.tmp / "nowhere"), {})

    def test_a_preview_render_is_read_at_the_films_scale(self):
        # --preview fits the film to 720p: a 1080p page's 6x6 marker is 4x4 there, 6.7 px from the corner, and blurred
        for page in ((480, 270), (640, 360)):                     # x 2/3 (1080p -> 720p) and x 1/2
            j = self.job("scaled-%d" % page[0])
            (j / "project").mkdir()
            write_json(j / "project" / "showtime.json", {"width": page[0], "height": page[1], "xray": {"marker": True}})
            film = make_scaled_film(j / "preview.mkv", self.wav, self.frames, *page)
            r = xray.verify(j, film)
            self.assertTrue(r["marker"], r)
            self.assertEqual((r["on_frame"], r["missing"], r["extra"], r["status"]), (6, [], [], "PASS"), r)
            self.assertAlmostEqual(r["marker_scale"], W / page[0], places=3)
            self.assertTrue(any("times the page's size" in n for n in r["notes"]), r["notes"])
        # a film the page was laid out for at its own size (another shape, --size) is read at the corner as drawn
        j = self.job("othershape")
        (j / "project").mkdir()
        write_json(j / "project" / "showtime.json", {"width": 1080, "height": 1920, "xray": {"marker": True}})
        r = xray.verify(j, make_film(j / "final.mkv", self.wav, self.frames))
        self.assertEqual((r["on_frame"], r["status"]), (6, "PASS"), r)
        self.assertNotIn("marker_scale", r)

    def test_marker_crop_stays_inside_the_scaled_square(self):
        self.assertEqual(xray.marker_crop(1920, 1080), (6, 6, 1910, 1070))      # the page's own size: the whole square
        for s in (2 / 3.0, 0.5, 2.0, 0.75):
            w, h, x, y = xray.marker_crop(1280, 720, s)
            x0, x1 = 1280 - 10 * s, 1280 - 4 * s                                 # the scaled square's left and right edges
            self.assertGreaterEqual(w, 2)
            self.assertTrue(x0 <= x and x + w <= x1 + 1e-9, (s, x, w, x0, x1))
            self.assertTrue(720 - 10 * s <= y and y + h <= 720 - 4 * s + 1e-9, (s, y, h))

    def test_skipped_events_carry_no_marker(self):
        j = self.job("skip")
        (j / "project").mkdir()
        write_json(j / "project" / "showtime.json", {"xray": {"marker": True, "skip": [0]}})
        film = make_film(j / "final.mkv", self.wav, self.frames[1:])
        r = xray.verify(j, film)
        self.assertEqual((r["events"], r["on_frame"], r["skipped"], r["status"]), (5, 5, 1, "PASS"), r)
        self.assertTrue(r["line"].startswith("5 of 5 events on their frame"), r["line"])
        film2 = make_film(j / "final2.mkv", self.wav, self.frames)      # a marker on the skipped event is extra
        r2 = xray.verify(j, film2)
        self.assertEqual((r2["extra"], r2["status"]), ([self.frames[0]], "FAIL"), r2)
        r3 = xray.verify(j, film2, skip=[])                              # a flag wins over the file
        self.assertEqual((r3["events"], r3["skipped"], r3["status"]), (6, 0, "PASS"), r3)

    def test_clip_fps_differs_from_the_film_fps(self):
        j = self.job("fps", [])
        doc = json.loads((j / "xray" / "xray.json").read_text(encoding="utf-8"))
        doc["source"]["fps"] = 29.97
        times = [0.60, 1.23, 2.55, 3.97]
        doc["events"] = [{"i": i, "t": t, "frame": int(t * 29.97), "strength": 1.0, "band": "high"} for i, t in enumerate(times)]
        write_json(j / "xray" / "xray.json", doc)
        film = make_film(j / "final.mkv", self.wav, [xray.frame_of(t, 30) for t in times])     # the 30 fps film's frames
        r = xray.verify(j, film)
        self.assertEqual((r["events"], r["on_frame"], r["missing"], r["extra"], r["status"]), (4, 4, [], [], "PASS"), r)
        self.assertNotEqual([int(t * 29.97) for t in times], [xray.frame_of(t, 30) for t in times])   # the fixture tells them apart
        self.assertTrue(any("floor(t * film fps)" in n for n in r["notes"]), r["notes"])

    def test_no_marker_is_unverified_warn(self):
        j = self.job("nomark")
        film = make_film(j / "final.mkv", self.wav, [], marker=False)
        r = xray.verify(j, film)
        self.assertFalse(r["marker"])
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["findings"][0]["rule"], "xray_unverified")
        self.assertIn("not verified", r["line"])

    def test_a_corner_that_is_always_bright_is_not_a_marker(self):
        j = self.job("bright")
        film = j / "final.mkv"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%d:d=5" % (W, H, FPS), "-i", str(self.wav),
                       "-vf", "drawbox=x=%d:y=%d:w=6:h=6:color=white:t=fill,format=yuv420p" % (W - 10, H - 10),
                       "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-c:a", "pcm_s16le", "-shortest", str(film)])
        r = xray.verify(j, film)
        self.assertFalse(r["marker"])
        self.assertEqual(r["findings"][0]["rule"], "xray_unverified")

    def test_the_source_is_looked_for_by_name_inside_the_job_only(self):
        j = self.job("find")
        (j / "xray" / "source.path").unlink()
        doc = {"source": {"file": "clip.mkv"}}
        self.assertIsNone(xray.find_source(j, doc))
        (j / "work").mkdir()
        shutil.copy(str(self.clip), str(j / "work" / "clip.mkv"))
        self.assertEqual(xray.find_source(j, doc), j / "work" / "clip.mkv")
        outside = self.tmp / "decoy.mkv"
        shutil.copy(str(self.clip), str(outside))
        for name in (str(outside), "../decoy.mkv", "..", "", "*"):          # absolute, up, nothing, a glob: never found outside
            self.assertIsNone(xray.find_source(j, {"source": {"file": name}}), name)

    def test_unmatched_audio_with_a_marker_warns(self):
        j = self.job("noaudio")
        other = write_wav(self.tmp / "other.wav", click_wave([0.9, 2.1, 3.3, 4.4], seed=99, noise=0.05))
        film = make_film(j / "final.mkv", other, self.frames)
        r = xray.verify(j, film)
        self.assertEqual(r["status"], "WARN", r)
        self.assertIn("xray_audio", [f["rule"] for f in r["findings"]])

    def test_bad_skip_entries_are_named(self):
        j = self.job("badskip")
        film = make_film(j / "final.mkv", self.wav, self.frames)
        r = xray.verify(j, film, skip=[99, "x"])
        self.assertTrue(any("99" in n and "'x'" in n for n in r["notes"]), r["notes"])
        self.assertEqual(r["skipped"], 0)

    def test_collided_frames_are_reported(self):
        fr = list(self.frames)
        fr[1] = fr[0]
        j = self.job("collide", frames=fr)
        film = make_film(j / "final.mkv", self.wav, fr)
        r = xray.verify(j, film)
        self.assertEqual(r["events"], 6)
        self.assertTrue(any("share a film frame" in n for n in r["notes"]), r["notes"])

    def test_delayed_audio_gives_its_lag(self):
        j = self.job("lag")
        film = make_film(j / "final.mkv", self.wav, self.frames, delay_ms=40)
        r = xray.verify(j, film)
        self.assertTrue(within(r["audio_lag_ms"], 40.0, 1.5), r)
        self.assertEqual(r["status"], "FAIL")
        self.assertTrue(any("ms from the original" in f["message"] for f in r["findings"]), r["findings"])
        film2 = make_film(j / "final2.mkv", self.wav, self.frames, delay_ms=12)
        self.assertTrue(within(xray.verify(j, film2)["audio_lag_ms"], 12.0, 1.5))

    def test_a_derived_sound_is_said_in_the_line_and_the_receipt(self):
        from st.job import receipt
        # the clip's sound is a rendering of data: the audio check passes against it, so the receipt says what it is
        j = self.job("derived")
        (j / "project").mkdir()
        write_json(j / "project" / "showtime.json", {"xray": {"marker": True, "credit": "Synthetic clicks, CC0.",
                                                              "derived": "the signal  slowed 100x on a 400 Hz carrier"}})
        r = xray.verify(j, make_film(j / "final.mkv", self.wav, self.frames))
        self.assertEqual(r["status"], "PASS", r)
        self.assertEqual(r["derived"], "the signal slowed 100x on a 400 Hz carrier")
        self.assertTrue(r["line"].endswith("ms from the rendered sound"), r["line"])
        self.assertNotIn("original", r["line"])
        self.assertTrue(any("not with the original data" in n for n in r["notes"]), r["notes"])
        late = xray.verify(j, make_film(j / "late.mkv", self.wav, self.frames, delay_ms=40))     # off: said the same way
        self.assertTrue(any("ms from the rendered sound (limit" in f["message"] for f in late["findings"]), late["findings"])
        xray.verify(j, make_film(j / "final.mkv", self.wav, self.frames))
        facts = receipt.card_facts({"xray": xray.receipt_section(j)})
        self.assertIn("X-ray sound: a rendering (the signal slowed 100x on a 400 Hz carrier); the audio check compares "
                      "the film with it, not with the original data", facts)
        # events imported from data (xray import): not measured from the sound, so not "from the original" either
        j2 = self.job("imported")
        doc = json.loads((j2 / "xray" / "xray.json").read_text(encoding="utf-8"))
        doc["detector"] = {"engine": "data", "min_gap": None, "sensitivity": None, "from": 0.0, "to": None, "note": "n",
                           "time_map": {"slow": 1.0, "t0": 0.0}, "input": {"file": "peaks.csv", "sha256": "0" * 64,
                                                                           "column": "t", "rows": 6}}
        write_json(j2 / "xray" / "xray.json", doc)
        r2 = xray.verify(j2, make_film(j2 / "final.mkv", self.wav, self.frames))
        self.assertEqual((r2["status"], r2["events_from"]), ("PASS", "data: peaks.csv"), r2)
        self.assertNotIn("derived", r2)
        self.assertTrue(r2["line"].endswith("ms from the source sound"), r2["line"])
        self.assertTrue(any("not from the sound" in n for n in r2["notes"]), r2["notes"])
        self.assertIn("X-ray events: from data: peaks.csv, not measured from the sound",
                      receipt.card_facts({"xray": xray.receipt_section(j2)}))
        nomark = xray.verify(j2, make_film(j2 / "plain.mkv", self.wav, [], marker=False))
        self.assertEqual(nomark["line"], "6 events from data (sync not verified: no marker in the film)")
        # a hand-edited detector that is not an object, or an input file name that is not a short string, is no crash
        for det in ("data", {"engine": "data", "input": "peaks.csv"}, {"engine": "data", "input": {"file": "x\n" * 400}}):
            doc["detector"] = det
            write_json(j2 / "xray" / "xray.json", doc)
            r4 = xray.verify(j2, make_film(j2 / "final.mkv", self.wav, self.frames))
            self.assertEqual(r4["status"], "PASS", r4)
            self.assertLessEqual(len(r4.get("events_from", "")), 130, r4.get("events_from"))
        # a clip measured from its own sound keeps "from the original" and no extra receipt line
        j3 = self.job("measured")
        r3 = xray.verify(j3, make_film(j3 / "final.mkv", self.wav, self.frames))
        self.assertTrue(r3["line"].endswith("ms from the original"), r3["line"])
        self.assertFalse(any(f.startswith("X-ray sound") or f.startswith("X-ray events")
                             for f in receipt.card_facts({"xray": xray.receipt_section(j3)})))

    def test_events_beyond_the_film_are_not_counted(self):
        j = self.job("short", self.frames + [900])
        film = make_film(j / "final.mkv", self.wav, self.frames)
        r = xray.verify(j, film)
        self.assertEqual((r["events"], r["outside_film"], r["status"]), (6, 1, "PASS"))

    def test_cli_exit_codes_and_receipt(self):
        j = self.job("cli", None)
        film = make_film(j / "final.mkv", self.wav, self.frames)
        cp = st("xray", "verify", j, "--video", film)
        self.assertIn("6 of 6 events on their frame", cp.stdout)
        rec = json.loads((j / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["xray"]["on_frame"], 6)
        self.assertEqual(rec["xray"]["marker"], True)
        self.assertIn("audio_lag_ms", rec["xray"])
        self.assertIn("X-ray: 6 of 6 events", __import__("st.job.receipt", fromlist=["x"]).card(rec))
        film2 = make_film(j / "bad.mkv", self.wav, self.frames[:-1])
        bad = st("xray", "verify", j, "--video", film2, check=False)
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("5 of 6", bad.stdout)

    def test_qa_runs_verify_when_the_job_has_xray_json(self):
        from st.qa import video as V
        j = self.job("qa")
        film = make_film(j / "final.mp4", self.wav, self.frames[:-1])
        rep = V.run(film, sheet=False, quiet=True, record=False)
        rules = {f["rule"]: f for f in rep["findings"]}
        self.assertIn("xray_sync", rules, [f["rule"] for f in rep["findings"]])
        self.assertEqual(rules["xray_sync"]["severity"], "FAIL")
        film2 = make_film(j / "final2.mp4", self.wav, [], marker=False)
        rules2 = {f["rule"]: f for f in V.run(film2, sheet=False, quiet=True, record=False)["findings"]}
        self.assertEqual(rules2["xray_unverified"]["severity"], "WARN")
        self.assertNotIn("xray_sync", rules2)
        for r in ("xray_sync", "xray_sync_off", "xray_unverified", "xray_choppy"):
            self.assertIn(r, V.RULES)

    def test_qa_wants_a_credit_for_the_clip(self):
        from st.qa import video as V
        j = self.job("credit")
        (j / "project").mkdir()
        cfg = j / "project" / "showtime.json"
        film = make_film(j / "final.mp4", self.wav, self.frames)
        write_json(cfg, {"xray": {"marker": True}})
        rep = V.run(film, sheet=False, quiet=True, record=False)
        miss = [f for f in rep["findings"] if f["rule"] == "xray_credit"]
        self.assertEqual([f["severity"] for f in miss], ["WARN"], rep["findings"])
        self.assertIn("xray.own: true", miss[0]["message"])
        self.assertFalse([p for p in rep["passed"] if "no attribution required" in p], rep["passed"])
        write_json(cfg, {"xray": {"credit": "Typewriter by Someone, CC BY 3.0, https://example.invalid/t " + "x" * 80}})
        rep = V.run(film, sheet=False, quiet=True, record=False)
        self.assertFalse([f for f in rep["findings"] if f["rule"] == "xray_credit"])
        self.assertTrue([p for p in rep["passed"] if p.startswith("clip credit: Typewriter by Someone")], rep["passed"])
        write_json(cfg, {"xray": {"own": True}})
        rep = V.run(film, sheet=False, quiet=True, record=False)
        self.assertFalse([f for f in rep["findings"] if f["rule"] == "xray_credit"])
        write_json(cfg, {"xray": {"credit": "Typewriter by Someone, CC BY 3.0"}})
        r = xray.verify(j, film)
        self.assertEqual(xray.receipt_section(j)["credit"], "Typewriter by Someone, CC BY 3.0")
        from st.job import receipt as RC
        self.assertIn("Clip credit: Typewriter by Someone", RC.card(dict(RC.build(j), xray=xray.receipt_section(j))))
        self.assertIn("xray_credit", V.RULES)

    def test_player_chrome_ignores_the_xray_sound_strip(self):
        from PIL import Image
        from st.qa import floor, video as V
        from test_floor import with_player

        class Fnd:
            def __init__(self):
                self.items = []

            def add(self, rule, severity, message, **extra):
                self.items.append(dict(extra, rule=rule, severity=severity, message=message))

        low = np.asarray(with_player(Image.new("L", (540, 960), 245)))            # a bar at 86 % of a portrait frame
        self.assertGreaterEqual(floor.player_strip(low)[0], 0.7 * 960)
        frames = [(1.5, low), (4.5, low), (7.5, low)]
        F = Fnd()
        floor.check(F, None, 9.0, 540, 960, frames=frames)
        self.assertEqual([f["rule"] for f in F.items if f["rule"] == "player_chrome"], ["player_chrome"])
        F = Fnd()
        out = floor.check(F, None, 9.0, 540, 960, frames=frames, xray_strip=True)
        self.assertFalse([f for f in F.items if f["rule"] == "player_chrome"], F.items)
        self.assertEqual(out["notes"], ["player_chrome skipped: the x-ray sound strip"])
        high = Image.new("L", (540, 960), 245)                                       # real chrome higher up still warns
        high.paste(with_player(Image.new("L", (540, 480), 245)), (0, 0))
        highs = np.asarray(high)
        self.assertLess(floor.player_strip(highs)[0], 0.7 * 960)
        F = Fnd()
        floor.check(F, None, 9.0, 540, 960, frames=[(1.5, highs), (4.5, highs), (7.5, highs)], xray_strip=True)
        self.assertEqual(len([f for f in F.items if f["rule"] == "player_chrome"]), 1, F.items)
        wide = np.asarray(with_player(Image.new("L", (960, 540), 245)))              # landscape: the bottom 12 % only
        F = Fnd()
        floor.check(F, None, 9.0, 960, 540, frames=[(1.5, wide), (4.5, wide), (7.5, wide)], xray_strip=True)
        self.assertEqual(len([f for f in F.items if f["rule"] == "player_chrome"]), 1, "bar at 86 % is above the 88 % line")
        # the project decides: template xray, or xray.json + an "xray" block
        j = self.job("strip")
        film = j / "final.mp4"
        self.assertTrue(V._xray_strip(None, film, {"template": "xray"}))
        self.assertTrue(V._xray_strip(None, film, {"xray": {"marker": True}}))
        self.assertFalse(V._xray_strip(None, film, {}))
        plain = self.tmp / "plainstrip"
        plain.mkdir()
        write_json(plain / "job.json", {"schema": 1, "slug": "p"})
        self.assertFalse(V._xray_strip(None, plain / "final.mp4", {"xray": {"marker": True}}))

    def test_qa_without_xray_json_is_untouched(self):
        from st.qa import video as V
        j = self.tmp / "plain"
        j.mkdir()
        write_json(j / "job.json", {"schema": 1, "slug": "plain"})
        film = make_film(j / "final.mp4", self.wav, [], marker=False)
        rep = V.run(film, sheet=False, quiet=True, record=False)
        self.assertFalse([f for f in rep["findings"] if f["rule"].startswith("xray")])
        self.assertNotIn("xray", rep)


def texture_strip(n, seed=5):
    rng = np.random.RandomState(seed)
    from scipy import ndimage
    return ndimage.gaussian_filter1d(rng.rand(n), 1.5) * 255.0


class Smoothness(unittest.TestCase):
    def profiles(self, steps, w=200):
        strip = texture_strip(w + int(sum(steps)) + 50)
        pos, out = 0.0, [strip[:w]]
        for s in steps:
            pos += s
            i = int(round(pos))
            out.append(strip[i: i + w])
        return np.array(out)

    def test_even_scroll_is_clean(self):
        r = xray.smoothness_of_profiles(self.profiles([4] * 60))
        self.assertEqual((r["stalls"], r["jumps"]), (0, 0), r)
        self.assertAlmostEqual(r["median_px"], 4.0, delta=0.3)

    def test_stalls_and_jumps_are_counted(self):
        steps = [4] * 60
        steps[20] = steps[21] = 0                  # two stalled frames
        for i in range(40, 60):
            steps[i] = 10                          # a sudden speed-up: one jump
        r = xray.smoothness_of_profiles(self.profiles(steps))
        self.assertEqual(r["stalls"], 2, r)
        self.assertEqual(r["jumps"], 1, r)
        self.assertEqual(r["stall_frames"], [21, 22])
        self.assertEqual(r["jump_frames"], [41])

    def test_a_band_that_barely_moves_has_no_stalls(self):
        r = xray.smoothness_of_profiles(self.profiles([0] * 30))
        self.assertEqual((r["stalls"], r["jumps"]), (0, 0))

    def test_band_of_a_film(self):
        w, h, n = 160, 24, 40
        strip = texture_strip(w + 6 * n + 20, seed=9)
        pos = 0
        raw = bytearray()
        for k in range(n):
            if k not in (10, 11):
                pos += 6
            raw += np.tile(strip[pos: pos + w], (h, 1)).clip(0, 255).astype(np.uint8).tobytes()
        film = Path(tempfile.mkdtemp(prefix="st-xray-test-")) / "scroll.mkv"
        subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                        "-s", "%dx%d" % (w, h), "-r", "30", "-i", "-", "-c:v", "ffv1", str(film)], input=bytes(raw), check=True)
        try:
            r = xray.smoothness(film, [0, 0, w, h])
            self.assertEqual(r["frames"], n)
            self.assertEqual(r["stalls"], 2, r)
            self.assertGreaterEqual(r["median_px"], 5.5)
            with self.assertRaises(ShowtimeError):
                xray.smoothness(film, [0, 0, 400, 10])
        finally:
            shutil.rmtree(film.parent, True)


def have_audio_stack():
    """numpy, soundfile and an ffmpeg that exists: what the audio-only and import tests build their inputs from."""
    import importlib.util
    try:
        return (importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("soundfile") is not None
                and Path(ff.ffmpeg_path()).exists())
    except Exception:  # noqa: BLE001 - no ffmpeg resolved: skip
        return False


def have_cv2():
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(have_cv2(), "opencv is not installed")
class Tracking(unittest.TestCase):
    N, REF = 36, 14

    @staticmethod
    def base():
        import cv2
        rng = np.random.RandomState(11)
        img = rng.rand(300, 400).astype(np.float32)
        img = cv2.GaussianBlur(img, (0, 0), 2.2)
        img = (img - img.min()) / (img.max() - img.min())
        return (img * 255).astype(np.uint8)

    @classmethod
    def affines(cls):
        """Ground truth: frame k = base warped by a drift of (1.6, 0.8) px per frame, a slow turn and a 0.1% zoom."""
        out = []
        for k in range(cls.N):
            ang = math.radians(0.12 * k)
            sc = 1.0 + 0.001 * k
            c, s = sc * math.cos(ang), sc * math.sin(ang)
            cx, cy = 200.0, 150.0
            A = np.array([[c, -s, cx - c * cx + s * cy + 1.6 * k], [s, c, cy - s * cx - c * cy + 0.8 * k], [0, 0, 1.0]])
            out.append(A)
        return out

    def frames(self):
        import cv2
        b = self.base()
        return [cv2.warpAffine(b, A[:2], (400, 300), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT) for A in self.affines()]

    def test_homographies_follow_the_texture(self):
        As = self.affines()
        region = np.array([[120, 80], [280, 85], [275, 215], [125, 210]], dtype=np.float64)
        hole = np.array([[190, 130], [220, 130], [220, 160], [190, 160]], dtype=np.float64)
        Hs = xray.track_frames(self.frames(), self.REF, region, [hole])
        self.assertEqual(len(Hs), self.N)
        self.assertTrue(np.allclose(Hs[self.REF], np.eye(3)))
        pts = np.hstack([region, np.ones((4, 1))])
        worst = 0.0
        for k in range(self.N):
            truth = (As[k] @ np.linalg.inv(As[self.REF]) @ pts.T).T
            got = (Hs[k] @ pts.T).T
            got = got[:, :2] / got[:, 2:3]
            worst = max(worst, float(np.abs(got - truth[:, :2]).max()))
        self.assertLess(worst, 1.5, "worst corner error %.2f px" % worst)

    def test_deterministic(self):
        region = np.array([[120, 80], [280, 85], [275, 215], [125, 210]], dtype=np.float64)
        fr = self.frames()
        a = xray.track_frames(fr, self.REF, region, [])
        b = xray.track_frames(fr, self.REF, region, [])
        self.assertTrue(all(np.array_equal(x, y) for x, y in zip(a, b)))

    def test_track_clip_writes_the_schema_object(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        try:
            raw = b"".join(f.tobytes() for f in self.frames())
            clip = tmp / "obj.mkv"
            subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                            "-s", "400x300", "-r", "30", "-i", "-", "-c:v", "ffv1", str(clip)], input=raw, check=True)
            src = {"width": 400, "height": 300, "fps": 30}
            region = [[120, 80], [280, 85], [275, 215], [125, 210]]
            tr = xray.track_clip(clip, src, region, self.REF / 30.0 + 0.001, [[[190, 130], [220, 130], [220, 160]]])
            self.assertEqual(tr["ref_frame"], self.REF)
            self.assertEqual(tr["region"], [[float(a), float(b)] for a, b in region])
            self.assertEqual(len(tr["H"]), self.N)
            self.assertEqual(len(tr["H"][0]), 9)
            self.assertEqual(len(tr["mask"]), 1)
            H = np.array(tr["H"][self.REF]).reshape(3, 3)
            self.assertTrue(np.allclose(H, np.eye(3), atol=1e-4))
            A = self.affines()
            truth = A[self.N - 1] @ np.linalg.inv(A[self.REF])
            Hl = np.array(tr["H"][self.N - 1]).reshape(3, 3)
            p = np.array([200.0, 150.0, 1.0])
            self.assertLess(float(np.abs((Hl @ p)[:2] / (Hl @ p)[2] - (truth @ p)[:2]).max()), 1.5)
        finally:
            shutil.rmtree(tmp, True)

    def test_a_clip_too_long_for_memory_is_refused_with_the_way_out(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        keep = xray.TRACK_MAX_BYTES
        try:
            raw = b"".join(f.tobytes() for f in self.frames())
            clip = tmp / "obj.mkv"
            subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                            "-s", "400x300", "-r", "30", "-i", "-", "-c:v", "ffv1", str(clip)], input=raw, check=True)
            xray.TRACK_MAX_BYTES = 400 * 300 * 5                       # room for a handful of frames only
            src = {"width": 400, "height": 300, "fps": 30, "duration": self.N / 30.0}
            with self.assertRaises(ShowtimeError) as cm:
                xray.track_clip(clip, src, [[120, 80], [280, 85], [275, 215], [125, 210]], 0.5, [])
            self.assertIn("footage trim", cm.exception.hint)
        finally:
            xray.TRACK_MAX_BYTES = keep
            shutil.rmtree(tmp, True)

    def test_bad_region_is_a_clear_error(self):
        with self.assertRaises(ShowtimeError):
            xray.parse_points("10,10 20,20")
        with self.assertRaises(ShowtimeError):
            xray.parse_points("10,10 a,b 30,30")
        self.assertEqual(xray.parse_points("1,2 3,4 5,6.5"), [[1.0, 2.0], [3.0, 4.0], [5.0, 6.5]])



@unittest.skipUnless(have_audio_stack(), "needs numpy, soundfile and ffmpeg")
class AudioOnly(unittest.TestCase):
    """A recording with no picture (a WAV, a sonified data stream) is a source: its events land on a frame grid of
    --fps (default 30) and the page draws the picture side."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        cls.wav = write_wav(cls.tmp / "clicks.wav", click_wave(CLICKS, LEVELS))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_analyze_a_wav(self):
        self.assertEqual(xray.validate_clip(self.wav), self.wav)
        doc = xray.analyze(self.wav, self.tmp / "a")
        src = doc["source"]
        self.assertEqual((src["file"], src["fps"], src["width"], src["height"], src["audio_only"]), ("clicks.wav", 30, 0, 0, True))
        self.assertNotIn("has_audio", src)
        self.assertEqual(len(doc["events"]), len(CLICKS))
        for e, t in zip(doc["events"], CLICKS):
            self.assertTrue(within(e["t"], t, 0.004), (e, t))
            self.assertEqual(e["frame"], xray.frame_of(e["t"], 30))
        self.assertTrue((self.tmp / "a" / "check.jpg").is_file())
        doc25 = xray.analyze(self.wav, self.tmp / "b", fps=25)
        self.assertEqual(doc25["source"]["fps"], 25)
        self.assertEqual([e["frame"] for e in doc25["events"]], [xray.frame_of(e["t"], 25) for e in doc25["events"]])

    def test_cli_and_its_refusals(self):
        job = self.tmp / "wjob"
        cp = st("xray", "analyze", self.wav, "--job", job, "--fps", "24", "--json")
        doc = json.loads(cp.stdout[cp.stdout.index("{"):])
        self.assertEqual(doc["source"]["fps"], 24)
        self.assertTrue((job / "xray" / "xray.json").is_file())
        bad = self.tmp / "tjob"
        cp = st("xray", "analyze", self.wav, "--job", bad, "--track", "--region", "1,1 9,1 9,9", "--ref-time", "0.5", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no picture to track", cp.stderr)
        self.assertFalse(bad.exists())
        clip = make_film(self.tmp / "clip.mkv", self.wav, [])
        cp = st("xray", "analyze", clip, "--job", bad, "--fps", "25", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("only for a recording with no picture", cp.stderr)
        self.assertFalse(bad.exists())

    def test_notes_read_a_wav_too(self):
        job = self.tmp / "njob"
        st("xray", "notes", self.wav, "--job", job, "--instrument", "drums")
        doc = json.loads((job / "xray" / "notes.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["source"]["audio_only"])
        self.assertTrue(doc["drums"])
        self.assertTrue((job / "xray" / "check-notes.jpg").is_file())


DATA_SLOW, DATA_T0 = 20.0, -0.15                       # film t = (t_data - T0) x SLOW


@unittest.skipUnless(have_audio_stack(), "needs numpy, soundfile and ffmpeg")
class Import(unittest.TestCase):
    """`xray import`: events from a data stream (CSV or JSON of times) through a time map, detector.engine "data",
    frames by frame_of, and a film made from them verifies."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))
        cls.wav = write_wav(cls.tmp / "sonified.wav", click_wave(CLICKS, LEVELS))     # the same time map as the events
        rows = ["t_data,h_sigma"] + ["%.6f,%g" % (t / DATA_SLOW + DATA_T0, 5 + k) for k, t in enumerate(CLICKS)]
        rows += ["%.6f,4" % (DATA_T0 - 0.01), "%.6f,4" % (6.0 / DATA_SLOW + DATA_T0)]   # before film 0; after the 5 s source
        cls.csv = cls.tmp / "peaks.csv"
        cls.csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_csv_with_a_source_and_a_time_map(self):
        out = self.tmp / "job1" / "xray"
        tm = xray.parse_time_map("slow=%g,t0=%g" % (DATA_SLOW, DATA_T0))
        self.assertEqual(tm, xray.parse_time_map("%g,%g" % (DATA_SLOW, DATA_T0)))
        doc = xray.import_events(self.csv, out, time_map=tm, source=self.wav, strength="h_sigma")
        self.assertEqual(doc["schema"], "showtime.xray/1")
        det = doc["detector"]
        self.assertEqual(det["engine"], "data")
        self.assertEqual(det["time_map"], {"slow": DATA_SLOW, "t0": DATA_T0})
        self.assertEqual((det["input"]["file"], det["input"]["column"], det["input"]["rows"]), ("peaks.csv", "t_data", 8))
        self.assertIn("not from the sound", det["note"])
        self.assertEqual(doc["source"]["file"], "sonified.wav")
        self.assertTrue(doc["source"]["audio_only"])
        self.assertEqual(len(doc["events"]), len(CLICKS))
        for e, t in zip(doc["events"], CLICKS):
            self.assertAlmostEqual(e["t"], t, places=3)
            self.assertEqual(e["frame"], xray.frame_of(e["t"], 30))
            self.assertIn("h_sigma", e)
        self.assertEqual(doc["events"][-1]["strength"], 1.0)
        self.assertEqual([d["why"].split(" (")[0] for d in doc["dropped"]], ["before film time 0", "after the end of the source"])
        self.assertTrue((out / "check.jpg").is_file())
        self.assertEqual(Path((out / "source.path").read_text(encoding="utf-8")), self.wav.resolve())

    def test_a_film_made_from_imported_events_verifies(self):
        job = self.tmp / "job2"
        doc = xray.import_events(self.csv, job / "xray", time_map={"slow": DATA_SLOW, "t0": DATA_T0}, source=self.wav)
        film = make_film(job / "final.mp4", self.wav, [e["frame"] for e in doc["events"]])
        res = xray.verify(job, film)
        self.assertEqual((res["on_frame"], res["events"], res["status"]), (len(CLICKS), len(CLICKS), "PASS"), res)
        self.assertLess(abs(res["audio_lag_ms"]), 2.0)

    def test_json_inputs_without_a_source(self):
        objs = self.tmp / "ev.json"
        objs.write_text(json.dumps({"events": [{"time": 1.5, "kind": "merger"}, {"time": 0.25}]}), encoding="utf-8")
        doc = xray.import_events(objs, self.tmp / "j1", fps=25)
        self.assertEqual([(e["t"], e["frame"]) for e in doc["events"]], [(0.25, 6), (1.5, 37)])
        self.assertEqual(doc["events"][1]["kind"], "merger")
        self.assertEqual((doc["source"]["file"], doc["source"]["fps"], doc["source"]["duration"]), (None, 25, None))
        nums = self.tmp / "ev2.json"
        nums.write_text("[0.1, 0.2]", encoding="utf-8")
        doc = xray.import_events(nums, self.tmp / "j2", note="peaks of the sensor log")
        self.assertEqual([e["frame"] for e in doc["events"]], [3, 6])
        self.assertEqual(doc["detector"]["note"], "peaks of the sensor log")

    def test_cli_and_its_refusals(self):
        job = self.tmp / "cli"
        cp = st("xray", "import", self.csv, "--job", job, "--time-map", "%g,%g" % (DATA_SLOW, DATA_T0), "--source", self.wav, "--json")
        self.assertEqual(len(json.loads(cp.stdout[cp.stdout.index("{"):])["events"]), len(CLICKS))
        self.assertTrue((job / "xray" / "xray.json").is_file())
        bad = self.tmp / "bad.csv"
        bad.write_text("t\n0.1\nsoon\n", encoding="utf-8")
        for n, args in enumerate(((self.csv, "--time-map", "0,1"), (self.csv, "--column", "nope"), (bad,),
                                  (self.tmp / "missing.csv",), (self.csv, "--source", self.tmp / "missing.wav"))):
            j = self.tmp / ("badjob%d" % n)
            cp = st("xray", "import", *args, "--job", j, check=False)
            self.assertEqual(cp.returncode, 1, (args, cp.stderr))
            self.assertNotIn("Traceback", cp.stderr)
            self.assertFalse(j.exists(), args)
        self.assertIn("'soon' is not a number", st("xray", "import", bad, check=False).stderr)

    def _csv(self, name, text):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def _refused(self, args, needle, name):
        j = self.tmp / ("r-" + name)
        cp = st("xray", "import", *args, "--job", j, check=False)
        self.assertEqual(cp.returncode, 1, (name, cp.stdout, cp.stderr))
        self.assertNotIn("Traceback", cp.stderr)
        self.assertIn(needle, cp.stderr, name)
        self.assertFalse(j.exists(), name)

    def test_more_refusals(self):
        self._refused([self._csv("empty.csv", "")], "has no events", "empty")
        self._refused([self._csv("notime.csv", "a,b\n1,2\n3,4\n")], "has no time column", "notime")
        self._refused([self._csv("early2.csv", "t\n0.1\n0.2\n"), "--time-map", "1,5"], "lands inside the film", "early2")
        self._refused([self._csv("bad.json", "[0.1, ")], "is not valid JSON", "badjson")
        self._refused([self.csv, "--source", self.wav, "--duration", "5"], "--duration is for an import without --source", "dur")
        self._refused([self.csv, "--fps", "0"], "--fps must be 1..240", "fps0")
        self._refused([self.csv, "--fps", "1000"], "--fps must be 1..240", "fps1000")

    def test_a_one_row_file(self):
        doc = xray.import_events(self._csv("one.csv", "t\n0.5\n"), self.tmp / "one")
        self.assertEqual([(e["t"], e["frame"]) for e in doc["events"]], [(0.5, 15)])
        self.assertTrue((self.tmp / "one" / "check.jpg").is_file())

    def test_a_strength_cell_that_is_not_a_number_is_refused(self):
        self._refused([self._csv("sg.csv", "t,h\n1,5\n2,loud\n3,7\n"), "--strength", "h"], "event 2: the h value 'loud' is not a number", "sg")

    def test_an_implicit_strength_column_takes_numbers_only(self):
        # a column named strength sizes the events without --strength: a word there was drawn at 1.0, silently
        self._refused([self._csv("isg.csv", "t,strength\n1,0.5\n2,loud\n3,0.7\n")],
                      "event 2: the strength value 'loud' is not a number", "isg")
        doc = xray.import_events(self._csv("isg2.csv", "t,strength\n1,0.5\n2,\n3,7\n"), self.tmp / "isg2")
        self.assertEqual([e["strength"] for e in doc["events"]], [0.5, 1.0, 1.0])       # blank: the default, clamped to 1

    def test_a_bad_strength_cell_is_refused_before_the_source_is_read(self):
        from st.audio import wav
        calls = []
        real = wav.load
        wav.load = lambda *a, **k: calls.append(a) or real(*a, **k)
        try:
            for name, text, flag in (("bs.csv", "t,h\n1,5\n2,loud\n", ["--strength", "h"]), ("bs2.csv", "t,strength\n1,x\n", [])):
                with self.assertRaises(ShowtimeError) as cm:
                    xray.build_import(self._csv(name, text), source=self.wav, strength=flag[1] if flag else None)
                self.assertIn("is not a number", str(cm.exception))
            self.assertEqual(calls, [], "the recording was decoded before the bad cell was refused")
            xray.build_import(self._csv("bs3.csv", "t,h\n1,5\n"), source=self.wav, strength="h")
            self.assertEqual(len(calls), 1, "a good file still reads its source")
        finally:
            wav.load = real

    def test_the_blank_count_leaves_out_dropped_rows(self):
        j = self.tmp / "sg-drop"
        # rows 1 and 2 are blank; row 1 falls before film time 0 (t0 = 1) and is dropped: one event has no value
        cp = st("xray", "import", self._csv("sg3.csv", "t,h\n0.5,\n2,\n3,4\n"), "--strength", "h", "--time-map", "1,1",
                "--job", j, check=False)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("1 event(s) have no h value: drawn at strength 0", cp.stderr)
        doc = json.loads((j / "xray" / "xray.json").read_text())
        self.assertEqual(([e["strength"] for e in doc["events"]], len(doc["dropped"])), ([0.0, 1.0], 1))

    def test_a_blank_strength_cell_is_zero_with_a_warning(self):
        j = self.tmp / "sg-blank"
        cp = st("xray", "import", self._csv("sg2.csv", "t,h\n1,5\n2,\n3, \n4,10\n"), "--strength", "h", "--job", j, check=False)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("2 event(s) have no h value: drawn at strength 0", cp.stderr)
        self.assertEqual(cp.stderr.count("have no h value"), 1)
        doc = json.loads((j / "xray" / "xray.json").read_text())
        self.assertEqual([e["strength"] for e in doc["events"]], [0.5, 0.0, 0.0, 1.0])

    def test_time_map_refuses_a_part_given_twice(self):
        for text in ("t0=5,2", "slow=2,slow=3", "2,slow=3"):
            with self.assertRaises(ShowtimeError) as cm:
                xray.parse_time_map(text)
            self.assertIn("twice", str(cm.exception), text)
        self.assertEqual(xray.parse_time_map("t0=5,slow=2"), {"slow": 2.0, "t0": 5.0})
        self._refused([self._csv("tw.csv", "t\n1\n"), "--time-map", "t0=5,2"], "sets t0 twice", "tw")

    def test_notes_help_says_a_recording_is_accepted(self):
        out = st("xray", "notes", "--help").stdout
        flat = " ".join(out.split())
        self.assertIn("WAV", flat)
        self.assertIn("no picture", flat)
        self.assertIn("the video you filmed (with its sound), or a WAV or other recording with no picture", flat)
        self.assertIn("the 30 fps grid", flat)                     # a recording with no picture has no frames of its own
        self.assertNotIn("floor(t * fps) of the clip", flat)

    def test_time_map_keeps_an_omitted_part(self):
        self.assertEqual(xray.parse_time_map(",5"), {"slow": 1.0, "t0": 5.0})
        self.assertEqual(xray.parse_time_map("100,"), {"slow": 100.0, "t0": 0.0})
        self.assertEqual(xray.parse_time_map(","), {"slow": 1.0, "t0": 0.0})
        self.assertEqual(xray.parse_time_map("slow=2,"), {"slow": 2.0, "t0": 0.0})
        with self.assertRaises(ShowtimeError):
            xray.parse_time_map("1,2,3")
        doc = xray.import_events(self._csv("tm.csv", "t\n5.5\n7\n"), self.tmp / "tm", time_map=xray.parse_time_map(",5"))
        self.assertEqual([e["t"] for e in doc["events"]], [0.5, 2.0])

    def test_size_and_count_caps(self):
        many = self._csv("many.csv", "t\n" + "\n".join(str(k / 1000.0) for k in range(xray.MAX_EVENTS + 1)) + "\n")
        self._refused([many], "more than %d events" % xray.MAX_EVENTS, "many")
        rows = [{"t": k / 1000.0} for k in range(xray.MAX_EVENTS + 1)]
        self._refused([self._csv("many.json", json.dumps(rows))], "up to %d events" % xray.MAX_EVENTS, "manyjson")
        old = xray.MAX_EVENTS_BYTES
        xray.MAX_EVENTS_BYTES = 10
        try:
            with self.assertRaises(ShowtimeError) as cm:
                xray.import_events(self.csv, self.tmp / "big")
            self.assertIn("an events file may be up to", str(cm.exception))
            self.assertFalse((self.tmp / "big").exists())
        finally:
            xray.MAX_EVENTS_BYTES = old
        edge = self._csv("edge.csv", "t\n" + "\n".join(str(k / 1000.0) for k in range(xray.MAX_EVENTS)) + "\n")
        self.assertEqual(len(xray.read_event_rows(edge)[0]), xray.MAX_EVENTS)

    def test_times_that_overflow_are_refused(self):
        self._refused([self._csv("huge.csv", "t\n1e308\n"), "--time-map", "1000,0"], "too large to hold", "huge")
        self._refused([self._csv("huge2.csv", "t\n1e308\n")], "too large to hold", "huge2")
        self._refused([self._csv("inf.json", "[1e999, 1]")], "an infinity", "inf")

    def test_nan_and_infinity_are_refused_or_dropped(self):
        self._refused([self._csv("nan.json", '[{"t": 1, "x": NaN}]')], "NaN is not allowed in JSON", "nan")
        self._refused([self._csv("inf2.json", '{"events": [{"t": 1, "x": Infinity}]}')], "Infinity is not allowed", "inf2")
        self._refused([self._csv("nested.json", '[{"t": 1, "x": {"y": [1e999]}}]')], "an infinity", "nested")
        # a CSV cell "nan" or "inf" is text, not a number: the event keeps it as a string and xray.json is valid JSON
        doc = xray.import_events(self._csv("cellnan.csv", "t,x,w\n0.5,nan,inf\n1,2,3\n"), self.tmp / "cn")
        text = (self.tmp / "cn" / "xray.json").read_text(encoding="utf-8")
        json.loads(text, parse_constant=lambda c: self.fail("bare %s in xray.json" % c))
        self.assertEqual(doc["events"][0]["x"], "nan")

    def test_columns_the_page_reads_cannot_break_it(self):
        doc = xray.import_events(self._csv("res.csv", "t,kind,ch,notes,pitches,label\n0.5,3,7,C4,60,a\n1,merger,x,D4,62,b\n"), self.tmp / "res")
        for e in doc["events"]:
            self.assertIsInstance(e["kind"], str)
            self.assertIsInstance(e["ch"], str)
            self.assertNotIn("notes", e)
            self.assertNotIn("pitches", e)
        self.assertEqual((doc["events"][0]["kind"], doc["events"][0]["ch"], doc["events"][0]["notes_data"]), ("3", "7", "C4"))
        self.assertEqual(doc["events"][0]["pitches_data"], 60)
        self.assertEqual(doc["events"][0]["label"], "a")
        js = self._csv("res.json", json.dumps([{"t": 1, "kind": {"a": 1}, "ch": 5, "notes": "C4"}]))
        e = xray.import_events(js, self.tmp / "resj")["events"][0]
        self.assertEqual((e["kind_data"], e["ch"], e["notes_data"]), ({"a": 1}, "5", "C4"))
        self.assertNotIn("kind", e)

    def test_the_auto_note_names_the_file_never_a_folder(self):
        deep = self.tmp / "private-folder" / "sub"
        deep.mkdir(parents=True)
        f = deep / "secret.csv"
        f.write_text("t\n0.5\n", encoding="utf-8")
        doc = xray.import_events(f, self.tmp / "leaf")
        blob = json.dumps(doc)
        self.assertIn("secret.csv", doc["detector"]["note"])
        self.assertNotIn("private-folder", blob)
        self.assertNotIn(str(self.tmp), blob)
        self.assertEqual(xray._leaf("a\\b\\c.csv"), "c.csv")

    def test_absurd_durations_and_times(self):
        for d in ("inf", "nan", "1e308", "-1", "100000"):
            self._refused([self.csv, "--duration", d], "--duration must be above 0", "dur" + d)
        self._refused([self._csv("day.csv", "t\n1e6\n")], "(24 h)", "day")
        # with a source, a late event is dropped, not a refusal
        doc = xray.import_events(self._csv("late.csv", "t\n1\n1e6\n"), self.tmp / "late", source=self.wav)
        self.assertEqual(len(doc["events"]), 1)
        self.assertEqual(len(doc["dropped"]), 1)
        # the backstop: no bare Infinity or NaN reaches xray.json
        doc = {"events": [{"t": float("inf")}]}
        with self.assertRaises(ShowtimeError):
            xray.write_import(doc, np.zeros(0, dtype=np.float32), self.csv, self.tmp / "inf", None)
        self.assertFalse((self.tmp / "inf" / "xray.json").exists())

    def test_a_source_is_read_once(self):
        from st import cli_xray
        calls = []
        real = xray.build_import
        xray.build_import = lambda *a, **k: calls.append(1) or real(*a, **k)
        try:
            args = cli_xray.argparse.Namespace(events=str(self.csv), job=str(self.tmp / "once"), out=None, json=True, time_map="20,-0.15",
                                               source=str(self.wav), fps=None, duration=None, column=None, strength=None, note=None)
            self.assertEqual(cli_xray.cmd_import(args), 0)
        finally:
            xray.build_import = real
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.tmp / "once" / "xray" / "xray.json").is_file())


class ReaderLimits(unittest.TestCase):
    """The events reader (no audio needed): caps while reading, JSON that cannot be held, the time map's messages."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-xray-test-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def f(self, name, text):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def refused(self, path, needle):
        with self.assertRaises(ShowtimeError) as cm:
            xray.read_event_rows(path)
        self.assertIn(needle, str(cm.exception))

    def test_csv_boundary_with_and_without_a_header(self):
        n = xray.MAX_EVENTS
        rows = [str(k / 1000.0) for k in range(n + 1)]
        self.assertEqual(len(xray.read_event_rows(self.f("h-ok.csv", "t\n" + "\n".join(rows[:n]) + "\n"))[0]), n)
        self.refused(self.f("h-over.csv", "t\n" + "\n".join(rows) + "\n"), "more than %d events" % n)
        self.assertEqual(len(xray.read_event_rows(self.f("n-ok.csv", "\n".join(rows[:n]) + "\n"))[0]), n)
        self.refused(self.f("n-over.csv", "\n".join(rows) + "\n"), "more than %d events" % n)

    def test_csv_is_read_line_by_line_and_every_line_counts(self):
        import csv as csvmod
        real, pulled = csvmod.reader, []

        def spy(lines, *a, **k):
            for row in real(lines, *a, **k):
                pulled.append(1)
                yield row
        old = xray.MAX_LINES
        xray.MAX_LINES = 50
        csvmod.reader = spy
        try:
            self.refused(self.f("blank.csv", "t\n" + "\n" * 20000 + "1\n"), "more than 50 lines")
            self.refused(self.f("comments.csv", "t\n" + "# note\n" * 20000 + "1\n"), "more than 50 lines")
            self.assertLess(len(pulled), 120)                        # not the 40,000 lines
        finally:
            csvmod.reader = real
            xray.MAX_LINES = old

    def test_a_small_file_of_empty_objects_is_refused_before_it_is_parsed(self):
        from unittest import mock
        hostile = self.f("objs.json", "[" + ",".join(["{}"] * (xray.MAX_CONTAINERS + 1)) + "]")
        with mock.patch.object(xray.json, "loads", side_effect=AssertionError("parsed")):
            self.refused(hostile, "too many lists or objects")
        # a legitimate file: the most events, each with an array of numbers, is read
        rows = ",".join('{"t":%d.5,"spectrum":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]}' % k for k in range(xray.MAX_EVENTS))
        self.assertEqual(len(xray.read_event_rows(self.f("spectra.json", "[" + rows + "]"))[0]), xray.MAX_EVENTS)

    def test_one_wide_object_is_refused_before_it_is_parsed(self):
        """One object with more keys than MAX_KEYS (a single container, fewer commas than MAX_VALUES) is refused before
        json parses it; the most events with 8 colons each (keys, times, URLs) stay well under the bound."""
        from unittest import mock
        # room for 16 colons an event at the most events (keys plus times and URLs inside strings: a realistic event
        # with a timestamp, a URL, a label and a note has about 8)
        self.assertGreaterEqual(xray.MAX_KEYS, 16 * xray.MAX_EVENTS)
        self.assertLess(xray.MAX_KEYS, xray.MAX_VALUES)
        wide = self.f("wide.json", "{" + ",".join('"k%d":0' % k for k in range(xray.MAX_KEYS + 1)) + "}")
        with mock.patch.object(xray.json, "loads", side_effect=AssertionError("parsed")):
            self.refused(wide, "too many object keys")
        # the most events, each with a timestamp, a URL, a label and a note (8 colons an event), are read
        row = '{"t":%d.5,"at":"2026-10-15T12:30:01","url":"https://data.example/run/7","label":"peak","note":"x"}'
        text = "[" + ",".join(row % k for k in range(xray.MAX_EVENTS)) + "]"
        self.assertEqual(text.count(":"), 8 * xray.MAX_EVENTS)
        self.assertEqual(len(xray.read_event_rows(self.f("realistic.json", text))[0]), xray.MAX_EVENTS)

    def test_a_huge_integer_is_refused_before_json_parses_it(self):
        from unittest import mock
        with mock.patch.object(xray.json, "loads", side_effect=AssertionError("parsed")):
            self.refused(self.f("digits.json", "[1" + "9" * 5000 + "]"), "too large to hold")
            self.refused(self.f("digits2.json", '{"events": [{"t": 1, "x": ' + "7" * 2000 + "}]}"), "too large to hold")

    def test_a_csv_cell_the_reader_cannot_take_is_a_refusal(self):
        self.refused(self.f("wide.csv", "t,note\n1," + "x" * 140000 + "\n"), "cannot read wide.csv as a CSV file")
        self.refused(self.f("zero-byte.csv", "t,note\n1,a\x00b\n"), "NUL byte")            # not "nul.csv": NUL is a device name on Windows
        u16 = Path(self.f("u16.csv", "")); u16.write_bytes("t\n1\n".encode("utf-16"))
        self.refused(u16, "NUL byte")
        self.refused(u16, "UTF-16")

    def test_a_first_row_with_a_huge_number_is_not_a_header(self):
        self.refused(self.f("big1.csv", "1" * 400 + ",2\n0.5,3\n"), "too large to hold")
        self.refused(self.f("big2.csv", "0.5," + "9" * 400 + "\n1,2\n"), "too large to hold")
        rows, cols = xray.read_event_rows(self.f("hdr.csv", "t,label\n1,a\n"))             # a real header is still a header
        self.assertEqual((cols, len(rows)), (["t", "label"], 1))

    def test_json_counts_every_kind_of_value_and_only_top_level_events(self):
        old = xray.MAX_VALUES
        xray.MAX_VALUES = 10
        try:
            self.refused(self.f("nulls.json", "[" + ",".join(["null"] * 50) + "]"), "too many values")
            self.refused(self.f("strs.json", json.dumps({"events": [{"t": 1, "s": "a"}] * 20})), "too many values")
        finally:
            xray.MAX_VALUES = old
        old = xray.MAX_EVENTS
        xray.MAX_EVENTS = 5
        try:
            nested = {"t": 1, "x": {chr(97 + k): {} for k in range(12)}}      # 13 objects inside ONE event
            self.assertEqual(len(xray.read_event_rows(self.f("nest.json", json.dumps([nested])))[0]), 1)
            self.refused(self.f("six.json", json.dumps([{"t": k} for k in range(6)])), "up to 5 events")
        finally:
            xray.MAX_EVENTS = old

    def test_huge_numbers_and_deep_nesting(self):
        for name, text in (("bigint.json", "[%s]" % ("9" * 400)), ("bigx.json", '[{"t": 1, "x": %s}]' % ("9" * 400)),
                           ("digits.json", "[%s]" % ("9" * 6000))):
            self.refused(self.f(name, text), "too large to hold")           # one message on every Python
        self.refused(self.f("deep.json", "[" * 100000 + "]" * 100000), "nested")
        self.refused(self.f("deep2.json", '[{"t": 1, "x": %s1%s}]' % ("[" * 40, "]" * 40)), "nested more than")
        rows, _ = xray.read_event_rows(self.f("bigcsv.csv", "t,x\n1,%s\n" % ("9" * 400)))     # a CSV cell stays text
        self.assertEqual(rows[0]["x"], "9" * 400)

    def test_time_map_names_the_bad_value(self):
        for text, needle in (("1,nan", "t0 must be a number"), ("nan,1", "slow must be a number above 0"),
                             ("0,1", "slow must be a number above 0"), ("1,inf", "t0 must be a number")):
            with self.assertRaises(ShowtimeError) as cm:
                xray.parse_time_map(text)
            self.assertIn(needle, str(cm.exception), text)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
