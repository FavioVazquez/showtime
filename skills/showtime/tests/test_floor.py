#!/usr/bin/env python3
"""The quality floor (st.qa.floor): each looks-cheap detector fires on a synthetic frame that has the
pattern and stays quiet on one that does not.

  * player_chrome   a progress bar with glyphs at both ends, inside a recorded page / a divider line alone
  * soft_footage    screen text upscaled 4x / the same text rendered crisp
  * caption_boxes   two stacked boxes of different widths / one plate for both lines
  * empty_borders   a 16:9 recording across a square frame with flat borders / a filled frame, and a title
                    on a flat ground (loose content, not a picture)
Then one encoded video through `showtime qa` (the hook, the time ranges, WARN only) and a clean one.

Stdlib + numpy + Pillow + ffmpeg (the showtime environment). usage: python tests/test_floor.py [--fast] [-v]
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

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.qa import floor  # noqa: E402

ENV = build_env(showtime_home())


def font(px):
    try:
        return ImageFont.load_default(size=max(6, int(px)))
    except TypeError:          # Pillow < 10.1: a fixed bitmap font
        return ImageFont.load_default()


def page(w, h, scale=1.0, ground=245, ink=30):
    """A recorded page: rows of code-like text and a panel outline (crisp at scale 1)."""
    im = Image.new("L", (w, h), ground)
    d = ImageDraw.Draw(im)
    f = font(22 * scale)
    for i in range(int(h / (34 * scale))):
        d.text((int(40 * scale), int((14 + i * 34) * scale)),
               "def step(batch_%02d): loss = model(batch_%02d).mean()  # %s" % (i, i, "x" * (3 + (i * 7) % 20)),
               fill=ink, font=f)
    d.rectangle([int(w * 0.62), int(h * 0.08), int(w * 0.95), int(h * 0.45)], outline=60, width=max(1, int(2 * scale)))
    return im


def with_player(im):
    """A web player's strip near the bottom of the recording: a thin bar, play and fullscreen glyphs."""
    w, h = im.size
    d = ImageDraw.Draw(im)
    y = int(h * 0.86)
    d.rectangle([0, y - int(h * 0.07), w, h], fill=20)                        # the dark control overlay
    x0, x1 = int(w * 0.06), int(w * 0.94)
    d.rectangle([x0, y, x1, y + 3], fill=110)                                 # the track
    d.rectangle([x0, y, int(w * 0.4), y + 3], fill=235)                       # the played part
    gy = y - int(h * 0.05)
    d.rectangle([x0 + 4, gy, x0 + 9, gy + 16], fill=235)                      # pause
    d.rectangle([x0 + 14, gy, x0 + 19, gy + 16], fill=235)
    d.text((x0 + 34, gy), "0:12 / 0:45", fill=235, font=font(16))
    for k in range(3):                                                        # volume, fullscreen, menu
        cx = x1 - 10 - k * 34
        d.rectangle([cx - 8, gy, cx + 8, gy + 16], outline=235, width=2)
    return im


def caption(im, lines, stepped, top_frac):
    """Burned captions: one box per line (stepped) or one plate for both."""
    w, h = im.size
    d = ImageDraw.Draw(im)
    f = font(h * 0.045)
    lh = int(h * 0.065)
    y = int(h * top_frac)
    widths = [int(d.textlength(t, font=f)) + int(w * 0.05) for t in lines]
    if not stepped:
        bw = max(widths)
        d.rectangle([(w - bw) // 2, y, (w + bw) // 2, y + lh * len(lines)], fill=45)
    for i, t in enumerate(lines):
        if stepped:
            d.rectangle([(w - widths[i]) // 2, y + i * lh, (w + widths[i]) // 2, y + (i + 1) * lh], fill=45)
        d.text(((w - widths[i]) // 2 + int(w * 0.025), y + i * lh + int(lh * 0.12)), t, fill=240, font=f)
    return im


def framed(size=720, rec=(640, 360), top=60, ground=12, player=False, lines=None, stepped=True):
    """A recording pasted into a square frame with flat borders, captions below it."""
    im = Image.new("L", (size, size), ground)
    r = page(*rec, scale=rec[0] / 1280.0 * 1.6)
    if player:
        r = with_player(r)
    im.paste(r, ((size - rec[0]) // 2, top))
    if lines:
        caption(im, lines, stepped, (top + rec[1] + 24) / float(size))
    return im


def arr(im):
    return np.asarray(im.convert("L"))


class Findings:
    def __init__(self):
        self.items = []

    def add(self, rule, severity, message, **extra):
        self.items.append(dict(extra, rule=rule, severity=severity, message=message))


class Detectors(unittest.TestCase):
    def test_player_chrome(self):
        rec = with_player(page(1280, 720))
        self.assertIsNotNone(floor.player_strip(arr(rec)))
        self.assertIsNone(floor.player_strip(arr(page(1280, 720))))
        line = page(1280, 720)
        ImageDraw.Draw(line).rectangle([100, 650, 1180, 652], fill=30)      # a divider alone: no glyphs at its ends
        ImageDraw.Draw(line).rectangle([0, 600, 1280, 720], fill=245)
        ImageDraw.Draw(line).rectangle([100, 650, 1180, 652], fill=30)
        self.assertIsNone(floor.player_strip(arr(line)))

    def test_soft_footage(self):
        crisp = arr(page(1280, 720))
        soft = arr(page(320, 180, scale=0.25).resize((1280, 720), Image.BICUBIC))
        self.assertFalse(floor.is_soft(crisp)[0], floor.sharpness(crisp))
        ok, s = floor.is_soft(soft)
        self.assertTrue(ok, s)
        self.assertLess(s["ratio"], floor.SOFT_RATIO)

    def test_caption_boxes(self):
        two = ["One sentence in,", "a finished video out, every time"]
        st = arr(caption(page(1280, 720, ground=90, ink=160), two, True, 0.7))
        self.assertTrue(floor.stepped(floor.caption_boxes(st), 1280), floor.caption_boxes(st))
        one = arr(caption(page(1280, 720, ground=90, ink=160), two, False, 0.7))
        self.assertFalse(floor.stepped(floor.caption_boxes(one), 1280), floor.caption_boxes(one))

    def test_empty_borders(self):
        b = floor.picture_box(arr(framed()))
        self.assertIsNotNone(b)
        self.assertLess((b[2] - b[0]) * (b[3] - b[1]), 0.7 * 720 * 720)
        self.assertIsNone(floor.picture_box(arr(page(1280, 720))))           # the recording fills the frame
        title = Image.new("L", (1280, 720), 12)
        ImageDraw.Draw(title).text((380, 300), "Describe a video.", fill=240, font=font(64))
        self.assertIsNone(floor.picture_box(arr(title)))                      # loose content, not a picture

    def test_check_needs_repeats(self):
        """One stray frame never warns; the same pattern across sampled frames does, with its time range."""
        bad = arr(framed(player=True, lines=["One sentence in,", "a finished video out"]))
        good = arr(page(720, 720))
        F = Findings()
        floor.check(F, None, 9.0, 720, 720, frames=[(1.5, bad), (4.5, good), (7.5, good)])
        self.assertEqual(F.items, [])
        F = Findings()
        out = floor.check(F, None, 9.0, 720, 720, frames=[(1.5, bad), (4.5, bad), (7.5, good)])
        rules = {f["rule"]: f for f in F.items}
        self.assertEqual(set(rules), {"player_chrome", "caption_boxes", "empty_borders"}, F.items)
        self.assertTrue(all(f["severity"] == "WARN" for f in F.items))
        self.assertEqual((rules["caption_boxes"]["t"], rules["caption_boxes"]["end"]), (1.5, 4.5))
        self.assertIn("1.5-4.5s", rules["player_chrome"]["message"])
        self.assertEqual(out["frames"], 3)
        # pure motion graphics (no footage): no player or border judgement, captions still judged
        F = Findings()
        floor.check(F, None, 9.0, 720, 720, footage=False, frames=[(1.5, bad), (4.5, bad), (7.5, good)])
        self.assertEqual({f["rule"] for f in F.items}, {"caption_boxes"})


def encode(frames, out, fps=2):
    h, w = frames[0].shape
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                         "-s", "%dx%d" % (w, h), "-r", str(fps), "-i", "-", "-f", "lavfi", "-i",
                         "sine=frequency=440:sample_rate=48000", "-shortest", "-c:v", "libx264", "-crf", "16",
                         "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(out)],
                        input=b"".join(f.tobytes() for f in frames), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


class QaRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-floor-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def qa(self, video):
        cp = subprocess.run([sys.executable, str(LAUNCHER), "qa", str(video), "--json"], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertIn(cp.returncode, (0, 1), cp.stderr[-2000:])
        return json.loads(cp.stdout)

    def test_cheap_clip_warns_clean_clip_does_not(self):
        bad = arr(framed(player=True, lines=["One sentence in,", "a finished video out"]))
        encode([bad] * 12, self.tmp / "cheap.mp4")
        rep = self.qa(self.tmp / "cheap.mp4")
        got = {f["rule"]: f for f in rep["findings"] if f["rule"] in floor.RULES}
        self.assertEqual(set(got), {"player_chrome", "caption_boxes", "empty_borders"}, rep["findings"])
        self.assertTrue(all(f["severity"] == "WARN" and f.get("end") is not None for f in got.values()))
        self.assertIn("fix", got["caption_boxes"])
        self.assertEqual(rep["floor"]["frames"], len(floor.sample_times(6.0)))  # 12 frames at 2 fps, one per 1.5 s
        clean = arr(caption(page(720, 720, ground=90, ink=160), ["One sentence in,", "a finished video out"], False, 0.75))
        encode([clean] * 12, self.tmp / "clean.mp4")
        rep = self.qa(self.tmp / "clean.mp4")
        self.assertEqual([f for f in rep["findings"] if f["rule"] in floor.RULES], [])

    def test_rules_are_documented(self):
        doc = (SKILL / "references" / "qa.md").read_text(encoding="utf-8")
        from st.qa import video as V
        for rule in floor.RULES:
            self.assertIn(rule, V.RULES)
            self.assertIn("`%s`" % rule, doc)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped),
                                                      time.time() - t0))
    sys.exit(0 if res.wasSuccessful() else 1)
