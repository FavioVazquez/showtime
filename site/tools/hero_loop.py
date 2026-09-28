#!/usr/bin/env python3
"""README hero loop: a tight, seamless animated WebP (plus a poster JPEG) from one film or a montage.

    # the launch film (when it exists): a window of it
    ~/.showtime/venv/bin/python site/tools/hero_loop.py --src launch-16x9.mp4 --from 3.2 --dur 7 -o assets/readme
    # the interim montage of example finals (segments in hero-montage.json)
    ~/.showtime/venv/bin/python site/tools/hero_loop.py --montage site/tools/hero-montage.json -o assets/readme \
        --method 5 --min-mb 6.4 --max-mb 7.6 --poster-at 0.5

Loop: the last shot dissolves into the first frame of the loop, so the WebP restarts without a jump.
Size: the encoder searches the quality until the file fits --max-mb (default 7.5); if nothing fits, use a
smaller --width or a shorter window.
Uses ~/.showtime/bin/ffmpeg (never a system ffmpeg) and Pillow's libwebp animation encoder.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FF = os.environ.get("SHOWTIME_FFMPEG") or str(Path(os.environ.get("SHOWTIME_HOME") or Path.home() / ".showtime") / "bin"
                                             / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))


def build_master(segs: list, fps: int, w: int, h: int, xf: float, out: Path) -> float:
    """Composite the segments with dissolves into a near-lossless master whose last dissolve lands on its
    own first frame. Returns the loop length in seconds."""
    args = [FF, "-v", "error", "-y"]
    for s in segs:
        args += ["-ss", "%.3f" % s["from"], "-t", "%.3f" % (s["dur"] + 0.2), "-i", s["file"]]
    # the first segment again, for the closing dissolve
    first = segs[0]
    args += ["-ss", "%.3f" % first["from"], "-t", "%.3f" % (xf + 0.2), "-i", first["file"]]
    n = len(segs)
    fc = []
    def norm(s):
        return ("scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s,"
                "setsar=1,fps=%d,format=yuv444p" % (w, h, w, h, s.get("pad", "0x15100E"), fps))
    for i in range(n + 1):
        d = segs[i]["dur"] if i < n else xf
        fc.append("[%d:v]%s,trim=duration=%.4f,setpts=PTS-STARTPTS[v%d]" % (i, norm(segs[i % n]), d, i))
    acc, t = "v0", segs[0]["dur"]
    for i in range(1, n + 1):
        d = segs[i]["dur"] if i < n else xf
        off = t - xf
        lab = "x%d" % i
        fc.append("[%s][v%d]xfade=transition=fade:duration=%.4f:offset=%.4f[%s]" % (acc, i, xf, off, lab))
        acc, t = lab, off + d
    # drop the first xf seconds: the output then starts where the closing dissolve ends
    total = t - xf
    fc.append("[%s]trim=start=%.4f:duration=%.4f,setpts=PTS-STARTPTS[out]" % (acc, xf, total))
    args += ["-filter_complex", ";".join(fc), "-map", "[out]", "-c:v", "libx264", "-preset", "slow", "-crf", "8",
             "-pix_fmt", "yuv444p", "-r", str(fps), str(out)]
    subprocess.run(args, check=True)
    return total


def frames(master: Path, w: int, h: int):
    from PIL import Image
    p = subprocess.run([FF, "-v", "error", "-i", str(master), "-vf", "scale=%d:%d:flags=lanczos" % (w, h),
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, stdout=subprocess.PIPE).stdout
    n = len(p) // (w * h * 3)
    return [Image.frombytes("RGB", (w, h), p[i * w * h * 3:(i + 1) * w * h * 3]) for i in range(n)]


def encode(imgs, fps: int, quality: int, method: int, out: Path) -> int:
    # 30 fps in whole milliseconds: 33, 33, 34, ... keeps the average exact
    durs, acc = [], 0.0
    for i in range(len(imgs)):
        nxt = round((i + 1) * 1000.0 / fps)
        durs.append(nxt - round(acc))
        acc = nxt
    imgs[0].save(str(out), "WEBP", save_all=True, append_images=imgs[1:], duration=durs, loop=0,
                 quality=quality, method=method, minimize_size=True, allow_mixed=False, kmin=9, kmax=17)
    return out.stat().st_size


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src")
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=7.0)
    ap.add_argument("--montage")
    ap.add_argument("-o", "--out-dir", required=True)
    ap.add_argument("--name", default="hero")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--xfade", type=float, default=0.3)
    ap.add_argument("--max-mb", type=float, default=7.5)
    ap.add_argument("--min-mb", type=float, default=5.5, help="stop searching upward once the file is at least this big")
    ap.add_argument("--method", type=int, default=4)
    ap.add_argument("--poster-at", type=float, default=None, help="seconds into the loop for poster.jpg")
    a = ap.parse_args()

    w = a.width
    h = int(round(w * 9 / 16 / 2)) * 2
    if a.montage:
        segs = json.loads(Path(a.montage).read_text())["segments"]
        base = Path(a.montage).parent
        for s in segs:
            s["file"] = str((base / s["file"]).resolve()) if not os.path.isabs(s["file"]) else s["file"]
    else:
        # one window of one film: the closing dissolve goes back to the window's start
        segs = [{"file": a.src, "from": a.start, "dur": a.dur}]
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        master = Path(td) / "master.mp4"
        t0 = time.time()
        total = build_master(segs, a.fps, 1920, 1080, a.xfade, master)
        print("master: %.2f s loop, built in %.0f s" % (total, time.time() - t0))
        imgs = frames(master, w, h)
        print("frames: %d at %dx%d" % (len(imgs), w, h))
        poster_t = a.poster_at if a.poster_at is not None else 0.0
        imgs[min(len(imgs) - 1, int(poster_t * a.fps))].save(str(out / (a.name + "-poster.jpg")), quality=88,
                                                             optimize=True, progressive=True)
        target = out / (a.name + ".webp")
        lo, hi, best = 30, 92, None
        q = 72
        tries = 0
        while lo <= hi and tries < 7:
            tries += 1
            t0 = time.time()
            size = encode(imgs, a.fps, q, a.method, Path(td) / "try.webp")
            print("  quality %d: %.2f MB (%.0f s)" % (q, size / 1e6, time.time() - t0))
            if size <= a.max_mb * 1e6:
                best = (q, size)
                os.replace(Path(td) / "try.webp", target)
                if size >= a.min_mb * 1e6:
                    break
                lo = q + 1
            else:
                hi = q - 1
            q = (lo + hi) // 2
        if not best:
            sys.exit("no quality fits %.1f MB at %d px; try --width 1120 or a shorter window" % (a.max_mb, w))
        print("%s: quality %d, %.2f MB, %d frames, %.2f s at %d fps" % (target, best[0], best[1] / 1e6, len(imgs),
                                                                        len(imgs) / a.fps, a.fps))


if __name__ == "__main__":
    main()
