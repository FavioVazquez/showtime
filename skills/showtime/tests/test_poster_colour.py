#!/usr/bin/env python3
"""JPEG stills from a video come out in the video's colours.

A final is H.264 BT.709 tv range; a JPEG is read by every viewer as BT.601 full range. A still pulled from the
video straight into a JPEG (ffmpeg -frames:v 1 x.jpg) kept the 709 matrix under JPEG's 601 tag, so saturated
colours shifted: example 28's purple-to-orange poster came out ~6 levels darker than its frame (qa
poster_mismatch). Each patch of a known frame, encoded as showtime encodes finals, must come back within ~2 levels
of its source RGB through every path that writes a JPEG still: deliver poster (also the render's auto poster),
deliver thumb, qa's review frames, the render's own poster.jpg and snap. qa's poster_mismatch compares the poster
with the frame it was taken from (the same seek, not one rounded to 3 places).

usage: python tests/test_poster_colour.py [--fast] [-v]     (--fast skips the renders and snap: no browser)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

W, H, BAND = 180, 320, 64            # a 9:16 frame of five flat bands, 64 px each
PATCHES = [("purple", (122, 42, 213)), ("orange", (255, 122, 26)), ("grey", (128, 128, 128)),
           ("navy", (20, 24, 70)), ("green", (40, 200, 90))]
# levels off the source, means over each patch's inside: per channel (two 8-bit Y'CbCr hops, the video's BT.709
# tv range then the JPEG's BT.601 full range, cost up to 3 on a channel at 255; the video frame alone is 2 off)
# and in luma; the BT.709 frame in a JPEG unconverted was ~19 off in purple's green and ~6 in its luma
TOL, TOL_LUMA = 3.0, 2.0
# the render's own encode (scripts/render.mjs TO_709, TAG_709, TAGS_709)
FINAL_VF = ("scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p,"
            "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
FINAL_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def rgb_of(path: Path) -> bytes:
    """The picture as rgb24, W x H. A JPEG is read as a viewer reads one (BT.601 full range, whatever its tags);
    a PNG is RGB already."""
    jpeg = path.suffix.lower() in (".jpg", ".jpeg")
    vf = ("scale=%d:%d:in_color_matrix=bt601:in_range=pc:flags=accurate_rnd+full_chroma_int,format=rgb24" if jpeg
          else "scale=%d:%d,format=rgb24") % (W, H)
    cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
                         "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"], stdout=subprocess.PIPE, timeout=60)
    assert len(cp.stdout) == W * H * 3, "could not decode %s" % path
    return cp.stdout


def patch_means(buf: bytes):
    """{name: (r, g, b)} means over each band's inside (away from the edges chroma subsampling blurs)."""
    out = {}
    for k, (name, _) in enumerate(PATCHES):
        s, n = [0, 0, 0], 0
        for y in range(k * BAND + 16, k * BAND + BAND - 16):
            row = y * W * 3
            for x in range(30, W - 30):
                i = row + 3 * x
                s[0] += buf[i]
                s[1] += buf[i + 1]
                s[2] += buf[i + 2]
                n += 1
        out[name] = tuple(v / n for v in s)
    return out


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-poster-colour-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def assertPatches(self, image: Path, what: str):
        got = patch_means(rgb_of(image))
        luma = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]  # noqa: E731
        worst = max(abs(g - s) for name, src in PATCHES for g, s in zip(got[name], src))
        worst_y = max(abs(luma(got[name]) - luma(src)) for name, src in PATCHES)
        msg = "%s: %.1f levels off the source in a channel, %.1f in luma (%s)" % (what, worst, worst_y, ", ".join(
            "%s %s vs %s" % (n, tuple(round(v) for v in got[n]), s) for n, s in PATCHES))
        self.assertLessEqual(worst, TOL, msg)
        self.assertLessEqual(worst_y, TOL_LUMA, msg)
        return worst


class StillsFromAVideo(Tmp):
    """deliver poster, deliver thumb and qa's frames, from a final-like video."""

    def setUp(self):
        super().setUp()
        raw = self.tmp / "frame.rgb"
        raw.write_bytes(b"".join(bytes(rgb) * (W * BAND) for _, rgb in PATCHES))
        self.src = self.tmp / "frame.png"
        ff.run_ffmpeg(["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H), "-i", raw, "-frames:v", "1", self.src])
        self.video = self.tmp / "final.mp4"
        ff.run_ffmpeg(["-loop", "1", "-framerate", "30", "-t", "1", "-i", self.src, "-vf", FINAL_VF, "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p"] + FINAL_TAGS + [self.video])

    def test_the_source_and_the_video_frame(self):
        self.assertPatches(self.src, "source PNG")
        # the frame as showtime pulls a PNG still (ff.still_args): ffmpeg's default conversion out of 4:2:0 is
        # not exact and differs by CPU (its plain C path, used on arm64 builds, reads each patch 2-3 levels darker
        # than x86's SIMD path; with exact rounding both match)
        png = self.tmp / "frame-out.png"
        ff.run_ffmpeg(["-ss", "0.5", "-i", self.video, "-frames:v", "1"] + ff.still_args(png) + [png])
        self.assertPatches(png, "video frame as PNG")

    def test_deliver_poster_jpeg(self):
        out = self.tmp / "poster.jpg"
        showtime("deliver", "poster", self.video, "--at", "0.5", "--out", out)
        self.assertPatches(out, "deliver poster --out poster.jpg")

    def test_deliver_thumb_jpeg(self):
        out = self.tmp / "thumb.jpg"
        showtime("deliver", "thumb", self.video, "--at", "0.5", "--size", "%dx%d" % (W, H), "-o", out)
        self.assertPatches(out, "deliver thumb -o thumb.jpg")

    def test_qa_review_frames(self):
        from st.qa import media
        [jpg] = media.extract_frames(self.video, [0.5], self.tmp / "frames", duration=1.0, fps=30)
        self.assertEqual(jpg.suffix, ".jpg")
        self.assertPatches(jpg, "qa review frame")
        [(_, run)] = media.extract_run(self.video, 15, 1, 30, self.tmp / "run", duration=1.0)
        self.assertPatches(run, "qa cut frame")

    def test_gradient_stills_as_bright_as_the_source(self):
        """Example 28's purple-to-orange gradient: ffmpeg's default conversion out of 4:2:0 drew a PNG still
        1.5 levels darker than its source (exact rounding and full chroma interpolation: equal)."""
        from st.qa import media
        src, v = self.tmp / "grad.png", self.tmp / "grad.mp4"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "gradients=s=%dx%d:c0=0x7a2bd6:c1=0xff7a1a:x0=0:y0=0:x1=0:y1=%d:nb_colors=2,"
                       "format=rgb24" % (W, H, H), "-frames:v", "1", src])
        ff.run_ffmpeg(["-loop", "1", "-framerate", "30", "-t", "1", "-i", src, "-vf", FINAL_VF, "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p"] + FINAL_TAGS + [v])
        want = media.mean_luma(src)
        self.assertLess(abs(media.mean_luma(v, at=0.5) - want), 0.75)
        for name in ("poster.png", "poster.jpg"):
            showtime("deliver", "poster", v, "--at", "0.5", "--out", self.tmp / name)
        [frame] = media.extract_frames(v, [0.5], self.tmp / "frames", duration=1.0, fps=30)
        showtime("snap", v, "--at", "0.5", "-o", self.tmp / "snap.png")
        for p in (self.tmp / "poster.png", self.tmp / "poster.jpg", frame, self.tmp / "snap.png"):
            self.assertLess(abs(media.mean_luma(p) - want), 0.75, "%s: %.2f vs the source's %.2f" % (
                p.name, media.mean_luma(p), want))

    def test_qa_poster_match_compares_like_with_like(self):
        from st.qa import media
        out = self.tmp / "poster.jpg"
        showtime("deliver", "poster", self.video, "--at", "0.5", "--out", out)
        self.assertLess(abs(media.mean_luma(out) - media.mean_luma(self.video, at=0.5)), 1.0)
        (self.tmp / "render.json").write_text(json.dumps({"output": str(self.video), "duration": 1,
                                                          "poster": {"file": "poster.jpg", "time": 0.5}}), encoding="utf-8")
        q = json.loads(showtime("qa", self.video, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("poster_mismatch", [f["rule"] for f in q["findings"]])

    def test_qa_reads_the_poster_frame_not_the_next(self):
        """A render's poster time is frame/fps (2/30 = 0.0667 s); rounded to 0.067 the seek read frame 3."""
        from st.qa import media
        v = self.tmp / "steps.mp4"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x36:r=30:d=0.1[a];color=c=white:s=64x36:r=30:d=0.2[b];"
                       "[a][b]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p"] + FINAL_TAGS + [v])
        self.assertLess(media.mean_luma(v, at=2 / 30.0), 20)          # frame 2: black
        self.assertGreater(media.mean_luma(v, at=3 / 30.0), 230)      # frame 3: white


PAGE = ('<!doctype html><html><head><script src="/_st/stage.js"></script><style>body{margin:0}'
        '.b{position:absolute;left:0;width:%dpx;height:%dpx}</style></head><body>'
        '<section data-start="0" data-dur="1">%s</section></body></html>')


@unittest.skipIf(FAST, "renders with a browser (skipped with --fast)")
class StillsFromARender(Tmp):
    """The render's own poster.jpg (from a captured PNG frame, and the auto-picked one from the video) and snap."""

    def project(self, poster):
        proj = self.tmp / "proj"
        proj.mkdir(exist_ok=True)
        bands = "".join('<div class="b" style="top:%dpx;background:rgb(%d,%d,%d)"></div>' % ((k * BAND,) + rgb)
                        for k, (_, rgb) in enumerate(PATCHES))
        (proj / "index.html").write_text(PAGE % (W, BAND, bands), encoding="utf-8")
        cfg = {"title": "Bands", "width": W, "height": H, "fps": 30, "duration": 1}
        if poster is not None:
            cfg["poster"] = poster
        (proj / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        return proj

    def render(self, name, poster, *extra):
        out = self.tmp / name / "final.mp4"
        showtime("render", self.project(poster), "-o", out, "--no-audio", "--no-check", "-q", *extra, timeout=600)
        rep = json.loads((out.with_suffix(".work") / "render.json").read_text(encoding="utf-8"))
        return out, Path(rep["poster"]["file"]), rep["poster"]

    def test_render_poster_from_a_png_frame(self):
        v, poster, info = self.render("png", 0.5, "--format", "png")
        self.assertEqual(poster.name, "poster.jpg")
        self.assertPatches(poster, "render poster.jpg (PNG capture)")
        q = json.loads(showtime("qa", v, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("poster_mismatch", [f["rule"] for f in q["findings"]])

    def test_render_auto_poster_and_snap(self):
        v, poster, info = self.render("auto", None)
        self.assertEqual(info.get("method"), "auto")                  # deliver poster on the video
        self.assertPatches(poster, "render auto poster.jpg")
        q = json.loads(showtime("qa", v, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("poster_mismatch", [f["rule"] for f in q["findings"]])
        snap = self.tmp / "snap.jpg"
        showtime("snap", v, "--at", "0.5", "-o", snap)
        self.assertPatches(snap, "snap -o snap.jpg")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)
