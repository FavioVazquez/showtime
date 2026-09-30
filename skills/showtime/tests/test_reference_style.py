#!/usr/bin/env python3
""""Same style as this video": the reference's style reaches the brief, the project and the checks.

A generated poster-style reference (no fonts, no downloads): a word-per-beat run where the ground flips
paper/ink every 0.5 s, left-aligned cards on a 6 % margin, a vermilion panel that wipes left to right, an ink
end card; a 120 BPM kick on every beat with an off-beat tick and silence at the end. Checked:
  * `showtime reference`: the beat cuts stay separate (a beat run), the wipe is named with its colour and
    direction, the palette is sampled (ground, ink, accent close to the drawn colours, flat), the layout is
    left-aligned on the margin, the sound's build (kick on the beats, tick, silence at the end);
  * reference.md carries the style over (sampled colours kept, style.css) and still forbids the content;
    style.css maps the theme tokens;
  * `showtime new <template> --job` links the style last in <head> and sets the background;
    `--no-reference-style` does not;
  * the variety guard: repeats that follow the job's style reference are intended (info, no alternatives);
    a palette that is not the reference's still counts;
  * (browser, skipped with --fast) `showtime check`: a word-per-beat run is a `beat_words` note, not
    `short_text`; the same words too fast for the reading rate still are.

Stdlib + the showtime venv. usage: python tests/test_reference_style.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-refstyle-"))

PAPER, INK, ACCENT = (242, 238, 227), (20, 20, 20), (228, 65, 43)
W, H, FPS = 640, 360, 30
MARGIN = 40                      # 6.25 % of 640
DUR = 14.0


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def showtime(*args, check=True, timeout=600, cwd=None, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def _word(img, x, y, h, n, colour):
    """A 'word' of n glyph-like strokes: vertical bars with gaps (type-like edge texture, no font)."""
    sw = max(3, h // 5)
    for i in range(n):
        x0 = x + i * (sw * 2 + 2)
        img[y:y + h, x0:x0 + sw] = colour
        img[y:y + max(2, h // 6), x0:x0 + sw * 2] = colour
        img[y + h - max(2, h // 6):y + h, x0:x0 + sw * 2] = colour


def frame(t: float, alt: bool = False):
    """The reference's frame at t; alt=True: the same style with other 'words' (stroke counts and sizes)."""
    import numpy as np
    if alt:
        return _alt_frame(t)
    img = np.zeros((H, W, 3), np.uint8)
    if t < 3.0:                                      # word per beat, ground flips every beat
        k = int(t / 0.5)
        ground, ink = (PAPER, INK) if k % 2 == 0 else (INK, PAPER)
        img[:] = ground
        _word(img, MARGIN, 150, 64, 5 + k % 3, ink)
    elif t < 11.0:                                   # two cards on paper, left-aligned
        img[:] = PAPER
        card = 0 if t < 7.25 else 1
        _word(img, MARGIN, 90, 12, 4 + card, ACCENT)          # small accent label
        _word(img, MARGIN, 120, 44, 9 - card, INK)
        _word(img, MARGIN, 180, 44, 7 + card, INK)
        img[H - 8:H, 0:int(W * ((t - 3.0) % 4.25) / 4.25)] = ACCENT   # progress bar
        if 7.0 <= t < 7.5:                           # the accent panel wipes left to right
            p = (t - 7.0) / 0.5
            a, b = int((2 * p - 1) * W), int(2 * p * W)
            img[:, max(0, a):max(0, min(W, b))] = ACCENT
    else:                                            # ink end card, name in the accent
        img[:] = INK
        _word(img, MARGIN, 140, 56, 8, ACCENT)
        _word(img, MARGIN, 210, 14, 6, PAPER)
    return img


def _alt_frame(t: float):
    import numpy as np
    img = np.zeros((H, W, 3), np.uint8)
    if t < 3.0:
        k = int(t / 0.5)
        ground, ink = (PAPER, INK) if k % 2 == 0 else (INK, PAPER)
        img[:] = ground
        _word(img, MARGIN, 140 + 12 * (k % 2), 56, 3 + (k * 2) % 5, ink)
        _word(img, MARGIN + 200, 150, 40, 2, ink) if k % 3 == 0 else None
    elif t < 11.0:
        img[:] = PAPER
        card = 0 if t < 7.25 else 1
        _word(img, MARGIN, 96, 12, 7 - card, ACCENT)
        _word(img, MARGIN, 128, 44, 5 + 2 * card, INK)
        _word(img, MARGIN, 190, 44, 10 - card, INK)
        _word(img, MARGIN, 250, 20, 12, INK)
        img[H - 8:H, 0:int(W * ((t - 3.0) % 4.25) / 4.25)] = ACCENT
        if 7.0 <= t < 7.5:
            p = (t - 7.0) / 0.5
            a, b = int((2 * p - 1) * W), int(2 * p * W)
            img[:, max(0, a):max(0, min(W, b))] = ACCENT
    else:
        img[:] = INK
        _word(img, MARGIN, 120, 56, 5, ACCENT)
        _word(img, MARGIN, 190, 56, 6, ACCENT)
    return img


def reference_video(alt: bool = False) -> Path:
    out = TMP / ("poster-alt.mp4" if alt else "poster-ref.mp4")
    if out.is_file():
        return out
    import numpy as np
    sr = 48000
    n = int(DUR * sr)
    y = np.zeros(n, np.float32)
    kick_len = int(0.18 * sr)
    tk = np.arange(kick_len) / sr
    kick = (np.sin(2 * math.pi * (50 + 60 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 18)).astype(np.float32)
    tick_len = int(0.03 * sr)
    tt = np.arange(tick_len) / sr
    tick = (0.25 * np.sin(2 * math.pi * 6000 * tt) * np.exp(-tt * 150)).astype(np.float32)
    end_audio = DUR - 1.0                           # the last second is silent
    b = 0.0
    while b < end_audio:
        i = int(b * sr)
        seg = y[i:i + kick_len]
        seg += kick[:len(seg)] * (1.6 if abs(b - 11.0) < 1e-6 else 0.8)
        j = int((b + 0.25) * sr)
        if b + 0.25 < end_audio:
            seg2 = y[j:j + tick_len]
            seg2 += tick[:len(seg2)]
        b += 0.5
    wav_path = TMP / ("poster-alt.wav" if alt else "poster-ref.wav")
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 30000)) for v in y))
    p = subprocess.Popen([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", "%dx%d" % (W, H), "-r", str(FPS), "-i", "-", "-i", str(wav_path), "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                          "-shortest", str(out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for f in range(int(DUR * FPS)):
        p.stdin.write(frame(f / FPS, alt).tobytes())
    p.stdin.close()
    err = p.stderr.read().decode("utf-8", "replace")
    assert p.wait() == 0, err
    return out


def hexd(a: str, rgb) -> float:
    a = a.lstrip("#")
    return max(abs(int(a[i * 2:i * 2 + 2], 16) - rgb[i]) for i in range(3))


class TestReferenceStyle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from st.variety import reference
        cls.video = reference_video()
        cls.out = TMP / "ref-out"
        cls.rep = reference.analyze(str(cls.video), cls.out, title="Poster reel", target=20)

    def test_beat_run_stays_separate(self):
        from st.variety import reference
        early = [c for c in self.rep["scene_changes"] if c["t"] < 3.2]
        self.assertGreaterEqual(len(early), 5, self.rep["scene_changes"])
        self.assertTrue(all(c["kind"] == "cut" for c in early), early)
        runs = reference.fast_runs(self.rep["shots"])
        self.assertTrue(runs, self.rep["shots"])
        self.assertAlmostEqual(runs[0]["every"], 0.5, delta=0.1)

    def test_panel_wipe_named(self):
        wipes = [c for c in self.rep["scene_changes"] if c["kind"] == "wipe"]
        self.assertEqual(len(wipes), 1, self.rep["scene_changes"])
        self.assertAlmostEqual(wipes[0]["t"], 7.25, delta=0.5)
        self.assertEqual(wipes[0]["dir"], "left to right")
        self.assertLess(hexd(wipes[0]["panel"], ACCENT), 16, wipes[0])

    def test_palette_sampled_with_roles(self):
        roles = self.rep["palette_roles"]
        self.assertLess(hexd(roles["ground"], PAPER), 8, roles)
        self.assertLess(hexd(roles["ink"], INK), 8, roles)
        self.assertLess(hexd(roles["accent"], ACCENT), 12, roles)
        self.assertTrue(roles["flat"], roles)

    def test_layout_left_on_margin(self):
        lay = self.rep["layout"]
        self.assertEqual(lay["align"], "left", lay)
        self.assertAlmostEqual(lay["margin_x"], MARGIN / float(W), delta=0.03)
        self.assertGreaterEqual(len(lay["sizes"]), 2, lay)

    def test_sound_shape(self):
        snd = self.rep["sound"]
        self.assertAlmostEqual(float(snd["bpm"]), 120, delta=4)
        sh = snd["shape"]
        self.assertGreaterEqual(sh["kick_on_beats"], 0.7, sh)
        self.assertGreaterEqual(sh["offbeat_hits"], 0.5, sh)
        self.assertGreaterEqual(sh["tail_silence_s"], 0.5, sh)

    def test_brief_carries_style_over(self):
        md = (self.out / "reference.md").read_text(encoding="utf-8")
        roles = self.rep["palette_roles"]
        for s in ("**Carry over (the style):**", "**Never (content):**", "Beat run:", "colour panel wipes",
                  "A same-style video keeps these colours", roles["ground"], roles["accent"], "left-aligned",
                  "kick on every beat at 120 BPM", "`style.css`", "Style reference: Poster reel"):
            self.assertIn(s, md)
        self.assertNotIn("use your own or the brand's colours", md)
        self.assertNotIn("its exact colours", md)
        css = (self.out / "style.css").read_text(encoding="utf-8")
        for s in ("--ref-ground: %s;" % roles["ground"], "--ref-accent: %s;" % roles["accent"],
                  "--bg: var(--ref-ground);", "--fg: var(--ref-ink);", "--accent: var(--ref-accent);",
                  "--safe-x: var(--ref-margin-x);", "--grain: 0;"):
            self.assertIn(s, css)

    def test_new_links_style(self):
        base = TMP / "jobs"
        base.mkdir(exist_ok=True)
        showtime("job", "init", "poster", "--goal", "a plant swap in the style of a reel", cwd=base)
        job = sorted((base / "showtime-out").glob("poster-*"))[-1]
        showtime("reference", self.video, "--job", job, "--title", "Poster reel")
        cp = showtime("new", "dom", job / "project", "--job", job, "--duration", "14")
        self.assertIn("linked reference-style.css", cp.stderr + cp.stdout)
        page = (job / "project" / "index.html").read_text(encoding="utf-8")
        link = '<link rel="stylesheet" href="reference-style.css">'
        self.assertIn(link, page)
        self.assertLess(page.rindex("stylesheet"), page.index("</head>"))
        self.assertEqual(page.rindex("<link"), page.index(link), "the reference style is the last stylesheet")
        self.assertTrue((job / "project" / "reference-style.css").is_file())
        cfg = json.loads((job / "project" / "showtime.json").read_text(encoding="utf-8"))
        ground = json.loads((job / "references" / "poster-reel" / "reference.json").read_text(encoding="utf-8"))["palette_roles"]["ground"]
        self.assertEqual(cfg["background"], ground)
        showtime("new", "dom", job / "plain", "--job", job, "--no-reference-style")
        self.assertNotIn("reference-style.css", (job / "plain" / "index.html").read_text(encoding="utf-8"))
        self.assertFalse((job / "plain" / "reference-style.css").exists())


class TestSpecAndDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from st.variety import reference
        cls.ref = reference_video()
        cls.alt = reference_video(alt=True)
        cls.dir = TMP / "spec-ref"
        cls.rep = reference.analyze(str(cls.ref), cls.dir, title="Poster reel")

    def test_spec_in_frames(self):
        sp = self.rep["spec"]
        self.assertEqual(sp["fps"], 30)
        self.assertEqual(sp["frames"], 420)
        beats = [c["frame"] for c in sp["changes"] if c["frame"] < 95]
        self.assertEqual(beats[:5], [15, 30, 45, 60, 75], sp["changes"])
        wipe = [c for c in sp["changes"] if c["kind"] == "wipe"][0]
        self.assertAlmostEqual(wipe["frame"], 218, delta=6)
        self.assertEqual(sp["shots"][0]["frames"], 15)
        self.assertAlmostEqual(float(sp["sound"]["bpm"]), 120, delta=4)
        self.assertGreaterEqual(len(sp["sound"]["hits"]), 20)
        md = (self.dir / "reference.md").read_text(encoding="utf-8")
        for s in ("## Spec (the numbers a same-style video keeps)", "**KEEP:**", "**CHANGE:**", "f15 cut", "wipe #",
                  "Shot lengths (frames): 15 / 15", "a beat every 15 frames"):
            self.assertIn(s, md)

    def test_diff_itself_and_a_same_style_video(self):
        cp = showtime("reference", "diff", self.ref, "--against", self.dir, "--strict")
        self.assertIn("all KEEP items line up", cp.stdout)
        for what in ("cuts", "shots", "palette", "layout", "sound"):
            self.assertIn("ok   %s" % what, cp.stdout)
        # the same style with other words keeps timing, palette and sound
        res = json.loads(showtime("reference", "diff", self.alt, "--against", self.dir, "--json").stdout)
        got = {i["what"]: i for i in res["items"]}
        for what in ("cuts", "palette", "sound"):
            self.assertTrue(got[what]["ok"], got[what])

    def test_diff_reports_off_with_frames(self):
        from st.variety import spec
        ref = self.rep["spec"]
        bad = json.loads(json.dumps(ref))
        bad["changes"] = [c for c in bad["changes"] if c["kind"] != "wipe"] + [{"t": 5.0, "frame": 150, "kind": "cut"}]
        bad["palette"] = {"ground": "#123456", "ink": "#ffffff", "accent": "#00ff00", "flat": False}
        bad["sound"]["bpm"] = 90
        res = spec.diff(ref, bad)
        got = {i["what"]: i for i in res["items"]}
        self.assertFalse(res["ok"])
        self.assertFalse(got["cuts"]["ok"])
        self.assertIn("missing: wipe at f2", got["cuts"]["text"])
        self.assertIn("extra: cut at f150", got["cuts"]["text"])
        self.assertFalse(got["palette"]["ok"])
        self.assertIn("(off)", got["palette"]["text"])
        self.assertFalse(got["sound"]["ok"])
        # another length: reference times scale to the render
        half = json.loads(json.dumps(ref))
        half["duration"] = ref["duration"] / 2
        for c in half["changes"]:
            c["t"] /= 2
        half["sound"]["bpm"] = float(ref["sound"]["bpm"]) * 2
        half["sound"]["hits"] = [dict(h, t=h["t"] / 2) for h in ref["sound"]["hits"]]
        res = spec.diff(ref, half)
        got = {i["what"]: i for i in res["items"]}
        self.assertAlmostEqual(res["ratio"], 0.5)
        self.assertTrue(got["cuts"]["ok"], got["cuts"])
        self.assertTrue(got["sound"]["ok"], got["sound"])

    def test_guard_detail_passes_same_style_fails_copy(self):
        from st.variety import guard
        refs = [{"title": "Poster reel", "dir": str(self.dir), "fingerprint": str(self.dir / "fingerprint.npz"),
                 "video": str(self.ref)}]
        res = guard.check_video(self.alt, refs)[0]
        self.assertIn(res["verdict"], ("ok", "close"), res)
        copy = TMP / "poster-copy.mp4"
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-i", str(self.ref), "-vf",
                        "crop=iw*0.95:ih*0.95,scale=640:360,eq=brightness=0.04", "-c:v", "libx264", "-preset",
                        "veryfast", "-an", str(copy)], check=True)
        res = guard.check_video(copy, refs)[0]
        self.assertEqual(res["verdict"], "copy", res)
        self.assertGreater(res["detail"]["kept"], 0)


class TestGuardFollowsReference(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hist-", dir=str(TMP)))
        self.old = os.environ.get("SHOWTIME_HISTORY_DIR")
        os.environ["SHOWTIME_HISTORY_DIR"] = str(self.dir)
        os.environ.pop("SHOWTIME_HISTORY", None)
        self.job = Path(tempfile.mkdtemp(prefix="job-", dir=str(TMP)))
        ref = self.job / "references" / "poster"
        ref.mkdir(parents=True)
        (ref / "reference.json").write_text(json.dumps({
            "title": "Poster reel", "palette": [{"hex": "#f2eee3", "share": 0.6}, {"hex": "#141414", "share": 0.3},
                                                {"hex": "#e4412b", "share": 0.08}], "shots": [{}] * 7}), encoding="utf-8")

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SHOWTIME_HISTORY_DIR", None)
        else:
            os.environ["SHOWTIME_HISTORY_DIR"] = self.old

    def look(self, name, palette, job_path=None):
        return {"job": name, "job_path": str(job_path or (TMP / ("nojob-" + name))), "theme": "paper",
                "palette": palette, "type": ["Anton", "Inter"], "transitions": {"wipe": 3},
                "structure": {"scenes": 5, "durations": [4, 4, 4, 4, 4], "shape": "even"}}

    def test_reference_led_repeats_are_intended(self):
        from st.variety import history as h
        ref_pal = ["#f2eee3", "#141414", "#e4412b"]
        h.record(self.look("earlier", ref_pal))
        res = h.check(self.look("now", ref_pal, job_path=self.job))
        self.assertEqual(res["references"], ["Poster reel"])
        self.assertTrue(res["repeats"])
        for r in res["repeats"]:
            self.assertIn("follows the style reference \"Poster reel\"", r.get("intended") or "", r)
            self.assertEqual(r["alternatives"], [])
            self.assertFalse(r["strong"])
        self.assertEqual(res["level"], "info")
        self.assertIn("on purpose", res["message"])
        self.assertIn("kept: follows the style reference", h.format_text(res))
        # without the reference the same look is a warning with alternatives
        res2 = h.check(self.look("now", ref_pal))
        self.assertEqual(res2["level"], "warning")
        self.assertTrue(any(r["alternatives"] for r in res2["repeats"]))

    def test_palette_not_from_reference_still_counts(self):
        from st.variety import history as h
        other = ["#102a5c", "#a8e6cf", "#ffd400"]
        h.record(self.look("earlier", other))
        res = h.check(self.look("now", other, job_path=self.job))
        pal = [r for r in res["repeats"] if r["aspect"] == "palette"]
        self.assertEqual(len(pal), 1, res["repeats"])
        self.assertFalse(pal[0].get("intended"))
        self.assertTrue(pal[0]["strong"])
        self.assertEqual(res["level"], "warning")


WORDS_PAGE = """<!doctype html><html><head><script src="/_st/stage.js"></script>
<style>body{margin:0;background:#f2eee3}.s{position:absolute;inset:0;background:#f2eee3;color:#141414;
font:700 120px sans-serif;padding:60px 80px}</style></head><body>
%s
<section class="s" id="card" data-start="%g" data-dur="%g"><p style="font-size:60px">Swap a plant</p></section>
</body></html>"""


@unittest.skipIf(FAST, "browser check (skipped with --fast)")
class TestBeatWords(unittest.TestCase):
    def project(self, name, words, each):
        proj = TMP / name
        proj.mkdir(parents=True, exist_ok=True)
        secs = "\n".join('<section class="s" id="w%d" data-start="%g" data-dur="%g"><p>%s</p></section>' % (
            i, i * each, each, w) for i, w in enumerate(words))
        start = len(words) * each
        (proj / "index.html").write_text(WORDS_PAGE % (secs, start, 3.0), encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30,
                                                        "duration": start + 3.0}), encoding="utf-8")
        cp = showtime("check", proj, "--json", "--no-determinism", "--no-history", check=False)
        return json.loads(cp.stdout)

    def test_word_per_beat_is_a_note(self):
        rep = self.project("beat", ["BRING", "ONE.", "TAKE", "ONE."], 0.5)
        codes = [f["code"] for f in rep["findings"]]
        self.assertNotIn("short_text", codes, rep["findings"])
        self.assertIn("beat_words", codes, rep["findings"])

    def test_reference_pair_contrast_is_a_note(self):
        """Large accent text on the ground, both the style reference's colours (3.6:1): a note with the
        reference's style file linked, an error without it."""
        page = ("<!doctype html><html><head><script src=\"/_st/stage.js\"></script><style>body{margin:0;background:#ede9df}"
                ".s{position:absolute;inset:0;background:#ede9df;padding:80px 120px}"
                "p{margin:0;font:700 120px sans-serif;color:#df3e26}</style>%s</head><body>"
                "<section class=\"s\" data-start=\"0\" data-dur=\"3\"><p>Plant swap</p></section></body></html>")
        css = ":root {\n  --ref-ground: #ede9df;\n  --ref-ink: #0f1111;\n  --ref-accent: #df3e26;\n}\n"
        sev = {}
        for name, linked in (("pair-ref", True), ("pair-plain", False)):
            proj = TMP / name
            proj.mkdir(parents=True, exist_ok=True)
            (proj / "index.html").write_text(page % ('<link rel="stylesheet" href="reference-style.css">' if linked else ""), encoding="utf-8")
            (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3}), encoding="utf-8")
            if linked:
                (proj / "reference-style.css").write_text(css, encoding="utf-8")
            rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-history", check=False).stdout)
            sev[name] = [f["severity"] for f in rep["findings"] if f["code"] == "low_contrast"]
        self.assertEqual(sev["pair-ref"], ["info"], sev)
        self.assertEqual(sev["pair-plain"], ["error"], sev)

    def test_too_fast_still_short_text(self):
        rep = self.project("fast", ["BRING ONE", "TAKE ONE", "SPRING NOW", "COME OVER"], 0.4)
        codes = [f["code"] for f in rep["findings"]]
        self.assertIn("short_text", codes, rep["findings"])
        self.assertNotIn("beat_words", codes)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
