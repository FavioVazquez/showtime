#!/usr/bin/env python3
"""The speaker cutout (st.footage.cutout) and the behind card (st.footage.behind) (about a minute).

- the matte engine on a synthetic person-like figure (head, neck, shoulders on a textured wall): with a stub
  network (a colour key) the whole pipeline (decode, temporal smoothing, guided-filter refinement, writers)
  returns the figure's silhouette at full size; with MODNet (when installed: never fetched by the test) the
  drawn figure's torso comes out and the wall stays clear
- temporal smoothing: jitter on a still picture is damped; a cut (a jump in the picture, or an EDL cut)
  starts afresh, so a matte never drags one shot into the next; the flicker measure sees a matte that jumps
  on a still picture and not one that follows motion
- a frame-exact seek, `footage cutout`'s three formats (VP9 alpha, ProRes 4444, PNG) with the matte file and
  the contact sheet (stub engine, in-process)
- the behind card: spec validation, the layout (16:9 off-centre speaker: the word on the free side, its last
  letter half behind the head; 9:16 close-up: the speaker moves down and the plate becomes the ground),
  the hidden-text estimate and measure, the problems edit check lists
- the composite order: an edit render with a behind card (dim plate), a lower third at the same time and
  captions: the speaker covers the word and keeps the shot's own pixels, the plate darkens the rest, the
  lower third and the captions sit on top of the speaker; the report and qa carry the measures
- the model in the manifest: Apache-2.0, a pinned sha256 and size, its licence file, the mirror entry

usage: python tests/test_cutout.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

import numpy as np  # noqa: E402

from st import ff  # noqa: E402
from st.footage import behind as BH  # noqa: E402
from st.footage import cutout as CO  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="st-cutout-"))
W, H = 480, 270


def figure(w: int = W, h: int = H, cx: float = 0.62, shift: int = 0, wall=(120, 90, 70), shirt=(35, 30, 30)):
    """A drawn person on a textured wall: (BGR frame, silhouette mask). The figure's skin, hair and clothing are
    warmer than the cool wall, so the stub key can find them."""
    import cv2
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = wall
    xx = np.mgrid[0:h, 0:w][1]
    img = (img.astype(np.float32) * (0.7 + 0.3 * xx / w)[..., None]).astype(np.uint8)
    cv2.rectangle(img, (int(0.06 * w), int(0.1 * h)), (int(0.4 * w), int(0.55 * h)), (90, 60, 40), -1)
    mask = np.zeros((h, w), np.uint8)
    x = int(cx * w) + shift
    s = h / 360.0
    pts = (np.array([[-150, 360], [-120, 250], [-60, 215], [60, 215], [120, 250], [150, 360]]) * s).astype(np.int32)
    pts[:, 0] += x
    cv2.fillPoly(img, [pts], shirt)
    cv2.fillPoly(mask, [pts], 255)
    for (ox, oy, ax, ay, col) in ((0, 130, 52, 66, (150, 175, 215)), (0, 100, 56, 44, (30, 40, 60))):
        c = (x + int(ox * s), int(oy * s))
        cv2.ellipse(img, c, (int(ax * s), int(ay * s)), 0, 0 if col[0] > 100 else 180, 360, col, -1)
        cv2.ellipse(mask, c, (int(ax * s), int(ay * s)), 0, 0 if col[0] > 100 else 180, 360, 255, -1)
    cv2.rectangle(img, (x - int(22 * s), int(175 * s)), (x + int(22 * s), int(225 * s)), (150, 170, 205), -1)
    cv2.rectangle(mask, (x - int(22 * s), int(175 * s)), (x + int(22 * s), int(225 * s)), 255, -1)
    for dx in (-20, 20):
        cv2.circle(img, (x + int(dx * s), int(125 * s)), max(2, int(5 * s)), (20, 30, 40), -1)
    return img, mask > 127


class StubEngine:
    """The matting network's place in the pipeline, keyed on the figure's colours (skin, hair, clothing are
    darker or warmer than the cool wall): the pipeline around it is what these tests check."""

    def __init__(self, *a, **k):
        from concurrent.futures import ThreadPoolExecutor
        self.sessions = 2
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.calls = 0

    def infer(self, rgb):
        self.calls += 1
        r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
        wall = (b > r + 20)                                 # the wall and its frame are blue-ish in RGB
        return (~wall).astype(np.float32)

    def close(self):
        self.executor.shutdown(wait=True)


def write_clip(path: Path, frames, fps: int = 30) -> None:
    """Raw BGR frames -> an H.264 clip (BT.709 tagged, like a real source)."""
    import subprocess
    h, w = frames[0].shape[:2]
    p = subprocess.Popen([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                          "%dx%d" % (w, h), "-r", str(fps), "-i", "-", "-f", "lavfi", "-i",
                          "sine=frequency=220:sample_rate=48000", "-shortest", "-c:v", "libx264", "-crf", "12",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    assert p.wait() == 0


def gray_frames(path: Path, w: int, h: int, alpha: bool = False, codec=None):
    import subprocess
    args = [ff.ffmpeg_path(), "-v", "error"] + (["-c:v", codec] if codec else []) + ["-i", str(path)]
    args += ["-vf", ("alphaextract," if alpha else "") + "format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(args, stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w)


def iou(a, b) -> float:
    return float((a & b).sum()) / max(1.0, float((a | b).sum()))


class MatteTest(unittest.TestCase):
    LIGHT = (230, 200, 160)                                 # a second shot: another, brighter wall

    @classmethod
    def setUpClass(cls):
        # three shots: the figure, a jump cut (the same wall, the figure moved), a hard cut (another wall)
        frames = ([figure(shift=0)[0] for _ in range(12)] + [figure(cx=0.3)[0] for _ in range(12)]
                  + [figure(cx=0.5, wall=cls.LIGHT)[0] for _ in range(12)])
        cls.clip = TMP / "figure.mp4"
        write_clip(cls.clip, frames)
        got = []
        eng = StubEngine()
        cls.st = CO.matte_stream(cls.clip, frames=36, engine=eng, on_frame=lambda i, buf, m: got.append(m.copy()))
        eng.close()
        cls.got, cls.calls = got, eng.calls

    def test_pipeline_gives_the_silhouette(self):
        st, got = self.st, self.got
        self.assertEqual(st["frames"], 36)
        self.assertEqual(len(got), 36)
        self.assertEqual(got[0].shape, (H, W))
        _img, mask = figure()
        self.assertGreater(iou(got[5] > 127, mask), 0.9)
        _img, mask2 = figure(cx=0.3)
        self.assertGreater(iou(got[20] > 127, mask2), 0.9)
        self.assertEqual(st["resets"], 1, "the hard cut at frame 24 is found (a jump cut is left to the motion map)")
        self.assertLess(st["flicker"], 0.01)
        self.assertEqual(self.calls, 36)

    def test_cut_starts_afresh(self):
        """The first frame after a cut is the new shot's own matte, not a blend with the old one: at a jump
        cut through the motion map, at a hard cut through the reset."""
        for at, a, b in ((12, figure(), figure(cx=0.3)), (24, figure(cx=0.3), figure(cx=0.5, wall=self.LIGHT))):
            old, new = a[1], b[1]
            self.assertLess(float(self.got[at][old & ~new].mean()), 10.0, "no ghost of the old shot at frame %d" % at)
            self.assertGreater(float(self.got[at][new & ~old].mean()), 240.0)

    def test_smoother_damps_jitter_and_resets(self):
        rng = np.random.default_rng(3)
        sm = CO.Smoother()
        mo = CO.Motion(cuts=[20])
        still = np.full((36, 64), 0.4, np.float32)
        base = np.zeros((36, 64), np.float32)
        base[:, 32:] = 1.0
        outs, raws = [], []
        for i in range(30):
            raw = np.clip(base + rng.normal(0, 0.2, base.shape).astype(np.float32), 0, 1)
            raws.append(raw)
            outs.append(sm(raw, mo(still)))
        jitter_raw = float(np.std(np.diff(np.stack(raws[2:19]), axis=0)))
        jitter_out = float(np.std(np.diff(np.stack(outs[2:19]), axis=0)))
        self.assertLess(jitter_out, 0.6 * jitter_raw, "a still picture keeps a steady matte")
        np.testing.assert_array_equal(outs[0], raws[0])
        np.testing.assert_array_equal(outs[20], raws[20], "an EDL cut (frame 20) resets the smoothing")
        # motion lets the new estimate through at once
        sm2, mo2 = CO.Smoother(), CO.Motion()
        a = np.zeros((36, 64), np.float32)
        b = np.ones((36, 64), np.float32)
        sm2(a, mo2(still))
        moved = still.copy()
        moved[:, :] = 0.5                                 # +0.1 everywhere: under the cut jump, over the motion bar
        out = sm2(b, mo2(moved))
        self.assertGreater(float(out.mean()), 0.95)

    def test_flicker_measure(self):
        m = np.zeros((40, 40), np.float32)
        m[10:30, 10:30] = 1.0
        prev = m.copy()
        prev[10:12, 10:30] = 0.0                          # 10 % of the area jumped
        still = np.zeros_like(m)
        self.assertAlmostEqual(CO.flicker_of(m, prev, still), 0.1, places=3)
        moving = np.ones_like(m)
        self.assertEqual(CO.flicker_of(m, prev, moving), 0.0, "motion explains the change")
        self.assertIsNone(CO.flicker_of(m, prev, None), "no measure across a cut")

    def test_refine_follows_the_full_size_edge(self):
        import cv2
        img, mask = figure(w=960, h=540)
        lo = cv2.resize(mask.astype(np.float32), (240, 135), interpolation=cv2.INTER_AREA)
        g_lo = cv2.cvtColor(cv2.resize(img, (240, 135), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        g_hi = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        out = CO.refine(lo, g_lo, g_hi)
        plain = cv2.resize(lo, (960, 540), interpolation=cv2.INTER_LINEAR)
        self.assertEqual(out.shape, (540, 960))
        self.assertGreaterEqual(iou(out > 0.5, mask), iou(plain > 0.5, mask) - 0.005)
        self.assertLess(float(out[~mask].mean()), 0.05, "the filter never paints the background in")

    def test_seek_is_frame_exact(self):
        import subprocess
        p = TMP / "count.mp4"
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=black:s=64x36:r=30:d=3,geq=lum='16+3*N':cb=128:cr=128", "-c:v", "libx264", "-qp", "0",
                        "-pix_fmt", "yuv420p", "-g", "15", str(p)], check=True)
        for f0 in (0, 1, 17, 44):
            buf = list(CO._yuv_reader(p, CO.seek_for_frame(f0, 30), 1, 64, 36, None))[0]
            y = np.frombuffer(buf, np.uint8)[:64 * 36].astype(np.float32).mean()
            self.assertEqual(int(round((y - 16) / 3.0)), f0)

    def test_pool_size(self):
        self.assertEqual(CO.pool_size(6), (3, 2))
        self.assertEqual(CO.pool_size(64), (16, 2))
        self.assertEqual(CO.pool_size(2), (2, 1))
        self.assertEqual(CO.infer_size(1920, 1080, 512), (896, 512))
        self.assertEqual(CO.infer_size(1080, 1920, 512), (512, 896))

    def test_real_model_on_the_figure(self):
        if not CO.model_present():
            self.skipTest("MODNet is not installed (showtime setup --fetch modnet); the test never downloads it")
        import cv2
        img, mask = figure(w=640, h=360)
        eng = CO.Engine(threads=4)
        try:
            iw, ih = CO.infer_size(640, 360, 512)
            m = eng.infer(cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (iw, ih), interpolation=cv2.INTER_AREA))
        finally:
            eng.close()
        m = cv2.resize(m, (640, 360))
        torso = mask.copy()
        torso[:int(0.62 * 360)] = False
        self.assertGreater(float(m[torso].mean()), 0.85, "the drawn figure's torso is a person")
        self.assertLess(float(m[~mask].mean()), 0.05, "the wall stays clear")
        self.assertGreater(iou(m > 0.5, mask), 0.6)


class CutoutCommandTest(unittest.TestCase):
    def test_formats(self):
        frames = [figure(shift=i % 3)[0] for i in range(20)]
        clip = TMP / "talk.mp4"
        write_clip(clip, frames)
        old = CO.Engine
        CO.Engine = StubEngine
        try:
            reps = {}
            for fmt in ("webm", "prores", "png"):
                ext = {"webm": ".cutout.webm", "prores": ".cutout.mov", "png": ".cutout"}[fmt]
                out = TMP / ("out-%s" % fmt) / ("talk" + ext)
                out.parent.mkdir(exist_ok=True)
                reps[fmt] = CO.cutout_video(clip, out=out, fmt=fmt, start=0.1, end=0.5)
        finally:
            CO.Engine = old
        r = reps["webm"]
        self.assertEqual(r["frames"], 12)
        self.assertTrue(Path(r["output"]).is_file() and Path(r["matte"]).is_file() and Path(r["sheet"]).is_file())
        self.assertTrue(r["matte"].endswith("talk.matte.mp4"))
        from st.footage import util as U
        pr = U.probe(Path(r["output"]))
        self.assertTrue(pr.get("vp_alpha"), pr)              # what the EDL overlays read to decode its alpha
        a = gray_frames(Path(r["output"]), W, H, alpha=True, codec="libvpx-vp9")
        _img, mask = figure()
        self.assertEqual(len(a), 12)
        self.assertGreater(iou(a[0] > 127, mask), 0.85)
        m = gray_frames(Path(r["matte"]), W, H)
        self.assertGreater(iou(m[0] > 127, mask), 0.85)
        a = gray_frames(Path(reps["prores"]["output"]), W, H, alpha=True)
        self.assertGreater(iou(a[3] > 127, mask), 0.85)
        pngs = sorted(Path(reps["png"]["output"]).glob("*.png"))
        self.assertEqual(len(pngs), 12)
        from PIL import Image
        im = np.array(Image.open(pngs[0]))
        self.assertEqual(im.shape, (H, W, 4))
        self.assertGreater(iou(im[..., 3] > 127, mask), 0.85)
        # the person's own colours are kept (BT.709 in, BT.709 out): the wall pixels are there, transparent
        self.assertLess(abs(float(im[..., 2][mask].mean()) - float(frames[0][..., 0][mask].mean())), 12)


class BehindLayoutTest(unittest.TestCase):
    FACE = {"x": 0.69, "top": 0.08, "bottom": 0.5, "eyes": 0.32, "chin": 0.53}

    def test_spec_validation(self):
        from st.footage import cards as CD
        errs = []
        CD.normalize_specs([{"type": "behind", "say": "x", "background": "plaid"},
                            {"type": "text-behind", "say": "x", "color": "pink"},
                            {"type": "behind", "say": "x", "background": "missing.png"},
                            {"type": "quote", "say": "x", "background": "dim"},
                            {"type": "behind", "say": "x", "background": "#112233", "color": "accent", "side": "center"}],
                           errs, TMP)
        self.assertEqual(len(errs), 4, errs)
        self.assertTrue(any("plaid" in e for e in errs) and any("pink" in e or "color" in e for e in errs))
        self.assertTrue(any("image not found" in e for e in errs))
        self.assertTrue(any("belong to a behind card" in e for e in errs))

    def test_word_holds_to_the_cut_of_a_moved_speaker(self):
        # 9:16: the moved speaker's opaque plate is cut in and out with the card, so the word must not fade
        # before that cut (example 23 left two or three frames of bare plate)
        c = {"lines": ["FASTER"], "font": 0.12, "align": "center", "color_css": "#fff"}
        moved = BH.html(dict(c, moved=True), 3.0, "left:0", str)
        self.assertIn("--out:3.000s", moved)
        still = BH.html(dict(c, moved=False), 3.0, "left:0", str)
        self.assertIn("--out:2.600s", still, "over the shot the word fades out with the plate")

    def test_wide_off_centre_speaker(self):
        lay = BH.layout({"type": "behind", "text": "Faster", "index": 0}, 1920, 1080, self.FACE, "wide")
        self.assertEqual(lay["align"], "right")
        self.assertEqual(lay["side"], "left")
        b = lay["box"]
        near = self.FACE["x"] - BH.head_half_width(self.FACE, 1920, 1080)
        self.assertLess(b["x"], 0.07)
        letter = b["w"] / 6.0
        self.assertAlmostEqual(b["x"] + b["w"], near + BH.TUCK * letter, delta=0.01)   # half the last letter behind
        self.assertLessEqual(b["y"] + b["h"], self.FACE["chin"] + 1e-6, "the word's foot sits on the chin line")
        self.assertFalse(lay["moved"])
        self.assertLess(lay["est_hidden"], 0.2)
        mirror = BH.layout({"type": "behind", "text": "Faster", "index": 0}, 1920, 1080, dict(self.FACE, x=0.31), "wide")
        self.assertEqual(mirror["align"], "left")
        centred = BH.layout({"type": "behind", "text": "Faster", "index": 0}, 1920, 1080, dict(self.FACE, x=0.5), "wide")
        self.assertEqual(centred["align"], "center")

    def test_tall_close_up_moves_the_speaker(self):
        face = {"x": 0.5, "top": 0.09, "bottom": 0.5, "eyes": 0.32, "chin": 0.53}
        lay = BH.layout({"type": "behind", "text": "Faster", "index": 0, "background": "blur"}, 1080, 1920, face, "tall")
        self.assertTrue(lay["moved"])
        self.assertEqual(lay["plate"], "ground", "no shot above the moved speaker: the look's ground")
        self.assertTrue(lay.get("plate_note"))
        y0 = lay["speaker"]["y"]
        head = lay["face_moved"]["top"]
        b = lay["box"]
        self.assertGreater(head, b["y"] + 0.2 * b["h"])
        self.assertLess(head, b["y"] + b["h"], "the head's top overlaps the word")
        self.assertAlmostEqual(lay["speaker"]["h"], 1.0 - y0, places=3)
        keep = BH.layout({"type": "behind", "text": "Faster", "index": 0, "layout": "overlay"}, 1080, 1920, face, "tall")
        self.assertFalse(keep["moved"])
        low = BH.layout({"type": "behind", "text": "Go", "index": 0}, 1080, 1920, dict(face, top=0.4, chin=0.75), "tall")
        self.assertFalse(low["moved"], "room above the head: the speaker stays")

    def test_problems_and_estimates(self):
        c = {"type": "behind", "text": "Faster", "index": 2, "start": 1.0, "end": 3.0, "lines": ["Faster"],
             "est_hidden": 0.62, "est_run": 0.5}
        p = BH.problems(c)
        self.assertTrue(any("62 % hidden (estimated from the face" in x for x in p), p)
        p = BH.problems(dict(c, est_hidden=0.1, est_run=0.1), {"hidden": 0.08, "hidden_run": 0.1, "flicker": 0.05,
                                                               "coverage": 0.3})
        self.assertEqual(len(p), 1)
        self.assertIn("matte flickers", p[0])
        long = BH.problems(dict(c, lines=["Atmospherically speaking"], est_hidden=0.1, est_run=0.0))
        self.assertTrue(any("characters on a line" in x for x in long))
        mask = BH.person_mask(self.FACE, 1920, 1080)
        self.assertTrue(mask[int(0.3 * 90), int(0.69 * 160)], "the face is in the silhouette")
        self.assertFalse(mask[int(0.3 * 90), int(0.2 * 160)])

    def test_measure_hidden(self):
        """The reel's alpha (the word's ink) against the matte: half the word behind the speaker."""
        import subprocess
        w, h, n = 160, 90, 6
        word = np.zeros((h, w, 4), np.uint8)
        word[30:60, 20:140, :] = 255                       # a 120 px wide "word"
        reel = TMP / "reel.mov"
        p = subprocess.Popen([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
                              "%dx%d" % (w, h), "-r", "30", "-i", "-", "-c:v", "qtrle", str(reel)], stdin=subprocess.PIPE)
        for _ in range(n + 4):
            p.stdin.write(word.tobytes())
        p.stdin.close()
        self.assertEqual(p.wait(), 0)
        m = np.zeros((h, w), np.uint8)
        m[:, 80:] = 255                                    # the speaker covers the right half of the word
        matte = TMP / "matte.mkv"
        pipe = CO.Pipe(CO.matte_args(matte, w, h, "30", lossless=True), "matte")
        for _ in range(n):
            pipe.write(m.tobytes())
        pipe.close()
        r = BH.measure_hidden(matte, reel, 2, n, Fraction(30), w * 4, h * 4)
        self.assertAlmostEqual(r["hidden"], 0.5, delta=0.06)
        self.assertAlmostEqual(r["hidden_run"], 0.5, delta=0.08)
        self.assertEqual(r["frames_measured"], n)


class PlateGraphTest(unittest.TestCase):
    """Every plate's filter chain runs, frame-exact, with the speaker composited over it (no browser)."""

    def test_plates(self):
        import subprocess
        from types import SimpleNamespace
        from st.footage import render_edl as R
        w, h, n = 160, 90, 60
        base = TMP / "plate-base.mov"
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=%dx%d:rate=30:duration=2" % (w, h), "-c:v", "libx264", "-crf", "1",
                        "-pix_fmt", "yuv420p", "-video_track_timescale", "30000", str(base)], check=True)
        m = np.zeros((h, w), np.uint8)
        m[:, w // 2:] = 255                                # the "speaker": the right half
        matte = TMP / "plate-matte.mkv"
        pipe = CO.Pipe(CO.matte_args(matte, w, h, "30", lossless=True), "matte")
        for _ in range(30):
            pipe.write(m.tobytes())
        pipe.close()
        img = TMP / "plate.png"
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=64x36",
                        "-frames:v", "1", str(img)], check=True)
        c = {"index": 0, "start": 0.5, "end": 1.5, "moved": False}
        for kind, extra in (("ground", {}), ("color", {"background": "#ff0000"}), ("dim", {}), ("blur", {}),
                            ("image", {"background": str(img)})):
            card = dict(c, plate=kind, plate_spec=BH.plate_of(dict(c, **extra) if extra else {"background": kind}),
                        **extra)
            look = {"tokens": {"--bg": "#0000ff"}}
            plate = BH.plate_entry(card, 15, 45, Fraction(30), look)
            ovs = [plate, BH.person_entry(card, str(matte), 15, 45, Fraction(30))]
            ctx = SimpleNamespace(w=w, h=h, full_w=w, full_h=h, fps=Fraction(30), edl={"overlays": ovs})
            args, parts, cur = R._overlay_graph(ctx, 1)
            out = TMP / ("plate-%s.mkv" % kind)
            subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-i", str(base)] + args +
                           ["-filter_complex", ";".join(parts) + ";%sformat=yuv420p[vout]" % cur, "-map", "[vout]",
                            "-c:v", "ffv1", str(out)], check=True)
            got = gray_frames(out, w, h)
            src = gray_frames(base, w, h)
            self.assertEqual(len(got), n, kind)
            mid = 30                                        # frame 30: the plate fully in
            left = np.abs(got[mid][:, : w // 2 - 4].astype(int) - src[mid][:, : w // 2 - 4].astype(int)).mean()
            right = np.abs(got[mid][:, w // 2 + 4:].astype(int) - src[mid][:, w // 2 + 4:].astype(int)).mean()
            self.assertLess(right, 2.0, "%s: the speaker keeps the shot's own pixels" % kind)
            self.assertGreater(left, 6.0, "%s: the plate replaces or changes the rest" % kind)
            self.assertLess(np.abs(got[5].astype(int) - src[5].astype(int)).mean(), 1.0, "%s: before the card" % kind)
            self.assertLess(np.abs(got[55].astype(int) - src[55].astype(int)).mean(), 1.0, "%s: after the card" % kind)


class BehindRenderTest(unittest.TestCase):
    """An edit render with a behind card, with the matte network stubbed (the colour key above)."""

    WORDS = [("Hello", 0.2, 0.5), ("space", 0.6, 0.9), ("weather", 0.95, 1.3), ("is", 1.35, 1.5), ("fast,", 1.55, 1.9),
             ("faster", 2.0, 2.4), ("than", 2.45, 2.6), ("ever", 2.65, 2.9), ("before.", 2.95, 3.4)]

    def test_composite_order(self):
        from st.footage import render_edl as R
        from st.qa import video as QV
        import cv2
        n = 120
        red = (40, 40, 200)                                  # a red shirt: any card drawn over it shows
        frames = [figure(cx=0.3, shirt=red)[0] for _ in range(n)]
        clip = TMP / "speaker.mp4"
        write_clip(clip, frames)
        d = TMP / "job" / "edit"
        (d / "transcripts").mkdir(parents=True, exist_ok=True)
        (d / "transcripts" / "speaker.json").write_text(json.dumps({
            "source": str(clip), "duration": 4.0, "language": "en",
            "words": [{"id": "w%d" % i, "text": t, "start": a, "end": b, "type": "word"}
                      for i, (t, a, b) in enumerate(self.WORDS)]}), encoding="utf-8")
        edl = {"sources": {"a": str(clip)}, "transcripts": {"a": "transcripts/speaker.json"},
               "ranges": [{"source": "a", "start": 0.0, "end": 4.0}], "output": {"fps": 30},
               "look": "graphite", "captions": {"style": "clean"},
               "cards": [{"type": "behind", "say": "space weather", "text": "WORD", "background": "dim",
                          "side": "center", "dur": 2.6},
                         {"type": "lower-third", "say": "space weather", "name": "Ada Park", "role": "Engineer",
                          "dur": 3.0}]}
        p = d / "edl.json"
        p.write_text(json.dumps(edl), encoding="utf-8")
        old = CO.Engine
        CO.Engine = StubEngine
        try:
            rep = R.render(p, d / "out.mp4", preview=False)
        finally:
            CO.Engine = old
        self.assertTrue(rep["frames_ok"], rep.get("warnings"))
        beh = rep["cards"]["behind"]
        self.assertEqual(len(beh), 1)
        self.assertEqual(beh[0]["plate"], "dim")
        self.assertIsNotNone(beh[0]["hidden"])
        self.assertGreater(beh[0]["hidden"], 0.02, "the figure covers part of the centred word")
        self.assertLess(beh[0]["flicker"], 0.01)
        t = 2.2
        out = cv2.cvtColor(QV_frame(Path(rep["output"]), t), cv2.COLOR_RGB2BGR).astype(np.int16)
        src = frames[int(t * 30)].astype(np.int16)
        _img, mask = figure(cx=0.3, shirt=red)
        inner = cv2.erode(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        lt = rep["cards"]["items"][1]["box"]
        lt_area = np.zeros_like(mask)
        lt_area[int(lt["y"] * H):int((lt["y"] + lt["h"]) * H), int(lt["x"] * W):int((lt["x"] + lt["w"]) * W)] = True
        bb = rep["cards"]["items"][0]["box"]
        word_area = np.zeros_like(mask)
        word_area[int(bb["y"] * H):int((bb["y"] + bb["h"]) * H), int(bb["x"] * W):int((bb["x"] + bb["w"]) * W)] = True
        band = np.zeros_like(mask)
        band[int(0.75 * H):, :] = True                                     # the captions' band
        speaker = inner & ~lt_area & ~band
        diff = np.abs(out - src).max(axis=2)
        self.assertLess(float(np.percentile(diff[speaker], 99)), 24,
                        "the speaker is the shot's own pixels, over the plate and the word")
        self.assertGreater(float((diff[speaker & word_area] < 24).mean()), 0.97, "the word never shows on the speaker")
        bg = ~cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & ~word_area & ~lt_area & ~band
        ratio = out[bg].mean() / max(1.0, src[bg].mean())
        self.assertAlmostEqual(ratio, 1.0 - BH.DIM_ALPHA, delta=0.08)   # the dim plate behind the speaker
        word_pix = word_area & ~cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        self.assertGreater(float((diff[word_pix] > 60).mean()), 0.08, "the word shows beside the speaker")
        self.assertGreater(float((diff[inner & lt_area] > 40).mean()), 0.05, "the lower third is on top of the speaker")
        # the captions are on top of everything: some caption pixels over the speaker
        cap = inner & band
        self.assertTrue(cap.any())
        self.assertGreater(float((diff[cap] > 60).mean()), 0.01, "the captions sit over the speaker")
        F = QV.Findings()
        QV._check_cards(F, Path(rep["output"]))
        self.assertFalse(F.has("behind_hidden", "matte_flicker"), F.items)
        self.assertTrue(any("behind card" in x for x in F.passed), F.passed)
        rec = json.loads((d / "work" / "edl" / "cards" / "behind.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["cards"][0]["text"], "WORD")


def QV_frame(video: Path, t: float):
    import subprocess
    raw = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-ss", "%.4f" % t, "-i", str(video), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


class ManifestTest(unittest.TestCase):
    def test_model_is_pinned_with_its_licence(self):
        from st.footage import asr_models
        man = json.loads((SKILL / "setup" / "manifest.json").read_text(encoding="utf-8"))
        it = next(i for i in man["items"] if i["id"] == "modnet")
        self.assertEqual(it["license"], "Apache-2.0")
        self.assertEqual(it["tier"], "lazy")
        self.assertIn("github.com/ZHKKKe/MODNet", it["source"])
        self.assertIn("Apache-2.0", it["attribution"])
        dests = {f["dest"] for f in it["files"]}
        self.assertEqual(dests, {"models/matte/modnet.onnx", "models/matte/LICENSE"})
        for f in it["files"]:
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(int(f["size"]), 1000)
            self.assertRegex(f["url"], r"/(resolve|[0-9a-f]{40})/")     # a pinned revision, never "main"
            self.assertNotIn("/main/", f["url"])
        self.assertEqual(asr_models.ITEMS["modnet"]["item"], "modnet")
        self.assertEqual(asr_models.ITEMS["modnet"]["path"], "models/matte/modnet.onnx")
        from st import mirror
        files = {f["url"]: f for f in json.loads(mirror.MANIFEST.read_text(encoding="utf-8"))["files"]}
        for f in it["files"]:
            m = files.get(f["url"])
            self.assertIsNotNone(m, f["url"])
            self.assertEqual((m["sha256"], m["size"], m["license"]), (f["sha256"], f["size"], "Apache-2.0"))
        if CO.model_present():
            lic = (asr_models.location("modnet").parent / "LICENSE").read_text(encoding="utf-8", errors="replace")
            self.assertIn("Apache License", lic)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
