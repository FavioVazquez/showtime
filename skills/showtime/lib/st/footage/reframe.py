"""Face-tracked reframing (e.g. 16:9 -> 9:16 or 1:1) with OpenCV YuNet.

1. Decode the range at 8 fps / 480 px wide through ffmpeg (same rotation and
   seeking as the renderer), detect faces with YuNet (~230 KB ONNX model).
2. Pick the subject per frame (largest confident face, preferring the one
   nearest the previous pick), fill gaps, split the track at shot changes.
3. Smooth: median filter, dead zone (small moves do not pan), centred moving
   average (1 s), so the camera glides and never jitters.
4. Emit crop positions per output frame; the renderer drives ffmpeg's crop
   filter with them (sendcmd), so reframing costs no extra encode.

No face -> centre crop (or the range's "focus" point).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import ff
from ..common import ShowtimeError, debug, paths, warn

DET_FPS = 8.0
DET_WIDTH = 480
UPSCALE_WARN = 1.5          # warn when the crop enlarges source pixels more than this
_WARNED: set = set()


def upscale_note(src, src_w: int, src_h: int, out_w: int, out_h: int, zoom: float = 1.0) -> Optional[str]:
    """A warning when filling out_w x out_h from src_w x src_h scales the picture by more than
    UPSCALE_WARN (a soft, blurry result), with the output size that keeps it sharp; else None."""
    s = max(out_w / float(src_w), out_h / float(src_h)) * max(1.0, zoom)
    if s <= UPSCALE_WARN + 1e-6:
        return None
    # a standard smaller size of the same shape (2/3: 1080x1920 -> 720x1280, 1/2: -> 540x960)
    for f in (2 / 3.0, 0.5):
        sug_w, sug_h = int(round(out_w * f / 2)) * 2, int(round(out_h * f / 2)) * 2
        if s * f <= UPSCALE_WARN + 1e-6:
            break
    return ("reframe: %s (%dx%d) is enlarged %.2fx to fill %dx%d%s, so the picture will look soft; "
            "render at %dx%d (EDL output {\"width\": %d, \"height\": %d}) or use a higher-resolution source"
            % (Path(str(src)).name, src_w, src_h, s, out_w, out_h,
               " (zoom %.2f)" % zoom if zoom > 1.001 else "", sug_w, sug_h, sug_w, sug_h))


def model_path() -> Path:
    return paths()["yunet"] / "face_detection_yunet_2023mar.onnx"


def available() -> Tuple[bool, str]:
    if not model_path().is_file():
        return False, "YuNet model missing (%s)" % model_path()
    try:
        import cv2
        if not hasattr(cv2, "FaceDetectorYN"):
            return False, "this OpenCV build has no FaceDetectorYN"
    except ImportError as e:
        return False, "opencv not importable (%s)" % e
    return True, ""


def _frames(src, start: float, duration: float, width: int, height: int):
    """Yield BGR frames (numpy) at DET_FPS from ffmpeg."""
    import numpy as np
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", "%.3f" % start,
            "-t", "%.3f" % duration, "-i", str(src), "-an", "-sn",
            "-vf", "fps=%g,scale=%d:%d" % (DET_FPS, width, height), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width * height * 3
    try:
        while True:
            buf = p.stdout.read(size) if p.stdout else b""
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
    finally:
        if p.stdout:
            p.stdout.close()
        p.wait()


def detect_track(src, start: float, duration: float, display_w: int, display_h: int,
                 min_score: float = 0.6) -> List[Optional[Tuple[float, float, float]]]:
    """Per detection frame: (cx, cy, face_height) normalised to the frame, or None."""
    ok, why = available()
    if not ok:
        raise ShowtimeError("face tracking unavailable: %s" % why, hint="run `showtime setup` (core tier)")
    import cv2
    w = DET_WIDTH if display_w >= display_h else int(round(DET_WIDTH * display_w / display_h / 2) * 2)
    w = max(64, w)
    h = max(64, int(round(w * display_h / display_w / 2) * 2))
    det = cv2.FaceDetectorYN.create(str(model_path()), "", (w, h), min_score, 0.3, 50)
    out: List[Optional[Tuple[float, float, float]]] = []
    prev: Optional[Tuple[float, float]] = None
    for fr in _frames(src, start, duration, w, h):
        _, faces = det.detect(fr)
        pick = None
        if faces is not None and len(faces):
            best, best_score = None, -1.0
            for f in faces:
                x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
                cx, cy = (x + fw / 2) / w, (y + fh / 2) / h
                area = (fw * fh) / float(w * h)
                cont = 1.0
                if prev is not None:
                    d = ((cx - prev[0]) ** 2 + (cy - prev[1]) ** 2) ** 0.5
                    cont = 1.0 / (1.0 + 4.0 * d)
                s = score * (area ** 0.5) * cont
                if s > best_score:
                    best, best_score = (cx, cy, fh / float(h)), s
            pick = best
            prev = (best[0], best[1])
        out.append(pick)
    return out


def smooth(track: List[Optional[Tuple[float, float, float]]], fallback: Tuple[float, float] = (0.5, 0.45),
           deadzone: float = 0.035, window_s: float = 1.0, cut_jump: float = 0.22) -> List[Tuple[float, float]]:
    """Gap-fill + shot-aware dead-zone smoothing -> [(cx, cy)] per detection frame."""
    import numpy as np
    n = len(track)
    if n == 0:
        return []
    idx = [i for i, t in enumerate(track) if t is not None]
    if not idx:
        return [fallback] * n
    xs = np.interp(np.arange(n), idx, [track[i][0] for i in idx])
    ys = np.interp(np.arange(n), idx, [track[i][1] for i in idx])
    # shot boundaries: a big jump that persists
    bounds = [0]
    hold = int(DET_FPS * 0.5)
    for i in range(1, n):
        if abs(xs[i] - xs[i - 1]) > cut_jump or abs(ys[i] - ys[i - 1]) > cut_jump:
            j = min(n - 1, i + hold)
            if abs(xs[j] - xs[i - 1]) > cut_jump * 0.8 or abs(ys[j] - ys[i - 1]) > cut_jump * 0.8:
                bounds.append(i)
    bounds.append(n)
    outx, outy = np.zeros(n), np.zeros(n)
    k = max(1, int(round(window_s * DET_FPS)))
    for a, b in zip(bounds[:-1], bounds[1:]):
        for arr, out in ((xs, outx), (ys, outy)):
            seg = arr[a:b].copy()
            if len(seg) >= 5:   # median of 5 removes single-frame detector glitches
                pad = np.pad(seg, 2, mode="edge")
                seg = np.array([np.median(pad[i:i + 5]) for i in range(len(seg))])
            cam = np.empty_like(seg)
            # seed the camera at where the subject settles (median of the first second), not at the
            # first detection: an early lean otherwise holds the whole shot off-centre
            c = float(np.median(seg[: max(1, min(len(seg), int(DET_FPS * 1.0)))]))
            for i, v in enumerate(seg):
                if v - c > deadzone:
                    c = v - deadzone
                elif c - v > deadzone:
                    c = v + deadzone
                cam[i] = c
            if len(cam) > 1:
                kk = min(k, len(cam))
                padded = np.pad(cam, (kk // 2, kk - 1 - kk // 2), mode="edge")
                cam = np.convolve(padded, np.ones(kk) / kk, mode="valid")
            out[a:b] = cam
    return list(zip(outx.tolist(), outy.tolist()))


def crop_positions(centers: List[Tuple[float, float]], scaled_w: int, scaled_h: int, out_w: int, out_h: int,
                   frames: int, fps: float, headroom: float = 0.08) -> List[Tuple[int, int]]:
    """Top-left crop (x, y) in the scaled frame for each output frame."""
    import numpy as np
    if not centers:
        cx = [0.5]
        cy = [0.5]
    else:
        cx = [c[0] for c in centers]
        cy = [c[1] for c in centers]
    t_det = np.arange(len(cx)) / DET_FPS
    t_out = np.arange(frames) / float(fps)
    x = np.interp(t_out, t_det, cx) * scaled_w - out_w / 2.0
    # keep the face a little above centre when cropping vertically
    y = (np.interp(t_out, t_det, cy) - headroom) * scaled_h - out_h / 2.0
    x = np.clip(np.round(x), 0, max(0, scaled_w - out_w)).astype(int)
    y = np.clip(np.round(y), 0, max(0, scaled_h - out_h)).astype(int)
    return list(zip(x.tolist(), y.tolist()))


def sendcmd_file(path: Path, positions: List[Tuple[int, int]], fps: float, target: str = "crop@rf") -> Path:
    """Write an ffmpeg sendcmd script that moves `target` every frame it changes."""
    lines = []
    last = None
    for i, (x, y) in enumerate(positions):
        if last != (x, y):
            t = i / float(fps)
            lines.append("%.4f %s x %d, %s y %d;" % (t, target, x, target, y))
            last = (x, y)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plan_crop(src, start: float, duration: float, src_w: int, src_h: int, out_w: int, out_h: int, fps: float,
              frames: int, zoom: float = 1.0, focus: Optional[Dict[str, float]] = None,
              track: bool = True, announce: bool = True) -> Dict[str, Any]:
    """Scale size + per-frame crop positions for a cover/reframe fit.

    The result carries `upscale` (how much source pixels are enlarged) and, above
    UPSCALE_WARN (1.5x), a `warning` that is also printed once per source and size
    unless announce=False (callers that report it themselves)."""
    s = max(out_w / float(src_w), out_h / float(src_h)) * max(1.0, zoom)
    note = upscale_note(src, src_w, src_h, out_w, out_h, zoom)
    key = (str(src), out_w, out_h, round(zoom, 3))
    if note and announce and key not in _WARNED:
        _WARNED.add(key)
        warn(note)
    sw, sh = int(round(src_w * s / 2) * 2), int(round(src_h * s / 2) * 2)
    sw, sh = max(sw, out_w), max(sh, out_h)
    fb = (float((focus or {}).get("x", 0.5)), float((focus or {}).get("y", 0.5)))
    centers: List[Tuple[float, float]] = []
    faces = 0
    if track and (sw > out_w + 2 or sh > out_h + 2):
        tr = detect_track(src, start, duration, src_w, src_h)
        faces = sum(1 for t in tr if t is not None)
        if faces:
            # the dead zone is a fraction of the source frame: shrink it with the punch-in, so at 1.2x
            # a small drift still re-centres the face instead of sliding towards the crop edge
            centers = smooth(tr, fallback=fb, deadzone=0.035 / max(1.0, float(zoom)))
        debug("reframe: faces in %d/%d detection frames" % (faces, len(tr)))
    if not centers:
        centers = [(fb[0], fb[1] + 0.08)]  # cancel headroom for fixed focus points
    pos = crop_positions(centers, sw, sh, out_w, out_h, frames, fps)
    res = {"scale": (sw, sh), "positions": pos, "faces": faces, "static": len(set(pos)) == 1,
           "upscale": round(s, 3)}
    if note:
        res["warning"] = note
    return res
