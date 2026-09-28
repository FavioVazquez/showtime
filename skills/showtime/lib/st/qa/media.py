"""ffmpeg-backed measurements used by `showtime qa` and `showtime review-pack`.

Every ffmpeg call goes through st.ff (the resolver), with argument lists only.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .. import ff
from ..common import ShowtimeError, debug

PathLike = Union[str, "os.PathLike[str]"]

Span = Tuple[float, float]


# ---------------------------------------------------------------- container

def faststart(path: PathLike) -> Optional[bool]:
    """True when the MP4/MOV index ('moov') comes before the media data ('mdat').

    Web players can start before the whole file arrives only in that case.
    None when the file is not an ISO-BMFF container or cannot be parsed.
    """
    p = Path(path)
    if p.suffix.lower() not in (".mp4", ".m4v", ".mov", ".m4a"):
        return None
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            pos = 0
            for _ in range(64):  # top-level boxes only
                if pos + 8 > size:
                    return None
                fh.seek(pos)
                head = fh.read(8)
                if len(head) < 8:
                    return None
                n, kind = struct.unpack(">I4s", head)
                if n == 1:
                    ext = fh.read(8)
                    if len(ext) < 8:
                        return None
                    n = struct.unpack(">Q", ext)[0]
                elif n == 0:
                    n = size - pos
                if kind == b"moov":
                    return True
                if kind == b"mdat":
                    return False
                if n < 8:
                    return None
                pos += n
    except OSError:
        return None
    return None


# ---------------------------------------------------------------- detectors

_BLACK = re.compile(r"black_start:\s*(-?[\d.]+)\s+black_end:\s*(-?[\d.]+)")
_FREEZE_S = re.compile(r"freeze_start:\s*(-?[\d.]+)")
_FREEZE_E = re.compile(r"freeze_end:\s*(-?[\d.]+)")


def detect(video: PathLike, duration: float, *, black_min: float = 0.04, freeze_min: float = 0.5,
           freeze_noise_db: float = -50.0, width: int = 320,
           crop: Optional[Sequence[int]] = None) -> Dict[str, List[Span]]:
    """One decode pass: black runs and frozen (unchanging) runs, in seconds.

    The picture is scaled down first: detection only needs coarse pixels and it
    keeps a long 4K file cheap. `crop` [x, y, w, h] limits it to the picture of a
    padded export. Returns {"black": [(s, e)], "freeze": [(s, e)]}.
    """
    pre = ("crop=%d:%d:%d:%d," % (int(crop[2]), int(crop[3]), int(crop[0]), int(crop[1]))) if crop else ""
    vf = (pre + "scale=%d:-2,blackdetect=d=%.3f:pic_th=0.98:pix_th=0.10,"
          "freezedetect=n=%gdB:d=%.3f" % (width, black_min, freeze_noise_db, freeze_min))
    cp = ff.run_ffmpeg(["-i", os.fspath(video), "-an", "-sn", "-vf", vf, "-f", "null", "-"],
                       loglevel="info", overwrite=False, check=False)
    err = cp.stderr or ""
    if cp.returncode != 0:
        raise ShowtimeError("could not decode %s: %s" % (video, err.strip()[-300:]),
                            why="the file is damaged, still being written, or not a video ffmpeg can read",
                            hint="play it once to check; if a render was interrupted, render it again")
    black = [(float(a), float(b)) for a, b in _BLACK.findall(err)]
    starts = [float(x) for x in _FREEZE_S.findall(err)]
    ends = [float(x) for x in _FREEZE_E.findall(err)]
    freeze: List[Span] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        freeze.append((s, e))
    return {"black": black, "freeze": freeze}


LIVE_FLOOR = 0.15      # median cell change (0-255 grey levels) that camera noise keeps everywhere
LIVE_LOCAL = 0.5       # how far the busiest cells (98th percentile) rise above that floor: lips, blinks, hands
LIVE_PAIRS = 0.5       # share of sampled frame pairs that must show both for a hold to count as live footage


def liveness(video: PathLike, start: float, end: float, *, crop: Optional[Sequence[int]] = None,
             fps: float = 5.0, max_pairs: int = 60, size: Tuple[int, int] = (160, 90), cell: int = 10
             ) -> Dict[str, Any]:
    """Is a held stretch live camera footage (a speaker holding still) or a frozen picture?

    freezedetect sees a talking head as a hold: the picture barely changes on average. Camera
    footage still has two things a frozen frame or a static motion-graphics card lacks at the
    same time: a noise floor in every part of the frame (sensor noise that survives compression)
    and local motion well above that floor in a few places (lips, blinks, hands). A grain overlay
    gives the floor without the local motion; typing or a moving line gives local change without
    the floor; a stalled or duplicated frame gives neither. Frames are sampled at up to `fps`
    (at most `max_pairs` pairs), shrunk to `size` grey and split into `cell`-pixel cells.
    -> {"pairs": n, "live_share": 0-1, "floor": median floor, "local": median local rise, "live": bool}
    """
    import subprocess
    import numpy as np
    span = max(0.0, float(end) - float(start))
    out: Dict[str, Any] = {"pairs": 0, "live_share": 0.0, "floor": 0.0, "local": 0.0, "live": False}
    if span < 0.5:
        return out
    rate = min(float(fps), max_pairs / span)
    w, h = size
    pre = ("crop=%d:%d:%d:%d," % (int(crop[2]), int(crop[3]), int(crop[0]), int(crop[1]))) if crop else ""
    try:
        cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error",
                             "-ss", "%.3f" % float(start), "-t", "%.3f" % span, "-i", os.fspath(video), "-an", "-sn",
                             "-vf", pre + "fps=%.4f,scale=%d:%d:flags=area,format=gray" % (rate, w, h),
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        debug("liveness: %s" % e)
        return out
    buf = cp.stdout or b""
    n = len(buf) // (w * h)
    if n < 3:
        return out
    a = np.frombuffer(buf[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    ch, cw = (h // cell) * cell, (w // cell) * cell
    floors, locals_, live = [], [], 0
    for i in range(1, n):
        d = np.abs(a[i, :ch, :cw] - a[i - 1, :ch, :cw])
        cells = d.reshape(ch // cell, cell, cw // cell, cell).mean(axis=(1, 3)).ravel()
        fl = float(np.median(cells))
        lo = float(np.percentile(cells, 98)) - fl
        floors.append(fl)
        locals_.append(lo)
        if fl >= LIVE_FLOOR and lo >= LIVE_LOCAL:
            live += 1
    k = n - 1
    out.update(pairs=k, live_share=round(live / k, 3), floor=round(float(np.median(floors)), 3),
               local=round(float(np.median(locals_)), 3))
    out["live"] = k >= 4 and live / k >= LIVE_PAIRS
    return out


_SHOWINFO_T = re.compile(r"pts_time:\s*([\d.]+)")


def scene_cuts(video: PathLike, threshold: float = 0.3, min_gap: float = 0.4, width: int = 320) -> List[float]:
    """Times where the picture changes abruptly (cuts and the start of fast transitions)."""
    vf = "scale=%d:-2,select='gt(scene\\,%g)',showinfo" % (width, threshold)
    cp = ff.run_ffmpeg(["-i", os.fspath(video), "-an", "-sn", "-vf", vf, "-f", "null", "-"],
                       loglevel="info", overwrite=False, check=False)
    times: List[float] = []
    for line in (cp.stderr or "").splitlines():
        if "Parsed_showinfo" not in line:
            continue
        m = _SHOWINFO_T.search(line)
        if m:
            t = float(m.group(1))
            if not times or t - times[-1] >= min_gap:
                times.append(t)
    return times


# ---------------------------------------------------------------- frames

def clamp_time(t: float, duration: Optional[float], fps: Optional[float]) -> float:
    fps = fps or 30.0
    if duration:
        t = min(t, max(0.0, duration - 1.0 / fps))
    return max(0.0, t)


def frame_name(t: float, ext: str = "jpg") -> str:
    return "t%08.3fs.%s" % (t, ext)


def extract_frames(video: PathLike, times: Sequence[float], out_dir: PathLike, *, width: Optional[int] = None,
                   duration: Optional[float] = None, fps: Optional[float] = None,
                   ext: str = "jpg", names: Optional[Sequence[str]] = None) -> List[Path]:
    """Write one image per time (accurate seek). Existing files are reused."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for i, t in enumerate(times):
        tt = clamp_time(float(t), duration, fps)
        dest = out / (names[i] if names else frame_name(tt, ext))
        if not dest.is_file():
            vf = "scale=%d:-2:flags=lanczos" % width if width else "null"
            args: List[str] = ["-ss", "%.6f" % tt, "-i", os.fspath(video), "-frames:v", "1", "-vf", vf]
            if dest.suffix.lower() in (".jpg", ".jpeg"):
                args += ["-q:v", "3"]
            cp = ff.run_ffmpeg(args + ["-update", "1", os.fspath(dest)], check=False)
            if cp.returncode != 0 or not dest.is_file():
                # accurate seek can land past the last decodable frame: step back once
                ff.run_ffmpeg(["-sseof", "-0.2", "-i", os.fspath(video), "-frames:v", "1", "-vf", vf,
                               "-update", "1", os.fspath(dest)], check=False)
        if dest.is_file():
            paths.append(dest)
        else:
            debug("no frame at %.3fs" % tt)
    return paths


def extract_run(video: PathLike, first_frame: int, count: int, fps: float, out_dir: PathLike, *,
                width: Optional[int] = None, duration: Optional[float] = None) -> List[Tuple[int, Path]]:
    """`count` consecutive frames starting at frame index `first_frame`, in one decode.
    -> [(frame index, image path)]."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fps = fps or 30.0
    last = int(duration * fps) - 1 if duration else None
    if last is not None:
        count = max(0, min(count, last - first_frame + 1))
    if count <= 0:
        return []
    stem = "f%06d" % first_frame
    vf = ("scale=%d:-2:flags=lanczos" % width) if width else "null"
    # seek a little before the first frame and select by frame number from there
    t0 = max(0.0, (first_frame - 0.5) / fps)
    pattern = out / (stem + "-%02d.jpg")
    ff.run_ffmpeg(["-ss", "%.6f" % t0, "-i", os.fspath(video), "-frames:v", str(count), "-vf", vf, "-q:v", "3",
                   "-start_number", "0", os.fspath(pattern)], check=False)
    res = []
    for i in range(count):
        p = out / ("%s-%02d.jpg" % (stem, i))
        if p.is_file():
            res.append((first_frame + i, p))
    return res


def opening_diffs(video: PathLike, n: int = 3, size: Tuple[int, int] = (64, 36)) -> List[float]:
    """Mean absolute grayscale differences (0-255, on tiny thumbnails) between the first n frames:
    [d(f0, f1), d(f1, f2), ...]. Empty when the frames cannot be decoded."""
    import subprocess
    w, h = size
    try:
        cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", os.fspath(video),
                             "-frames:v", str(n), "-vf", "scale=%d:%d:flags=area,format=gray" % (w, h),
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    buf = cp.stdout or b""
    k = w * h
    frames = [buf[i * k:(i + 1) * k] for i in range(len(buf) // k)]
    return [sum(abs(a - b) for a, b in zip(frames[i], frames[i + 1])) / float(k) for i in range(len(frames) - 1)]


def image_stats(path: PathLike) -> Dict[str, float]:
    """Mean/std/percentiles of luma (0-255) for a small copy of an image."""
    import numpy as np
    from PIL import Image
    im = Image.open(os.fspath(path)).convert("RGB")
    im.thumbnail((256, 256))
    a = np.asarray(im).astype("float32")
    y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    return {"mean": float(y.mean()), "std": float(y.std()), "p01": float(np.percentile(y, 1)),
            "p99": float(np.percentile(y, 99)),
            "chroma": float(np.abs(a - a.mean(axis=2, keepdims=True)).mean())}


# ---------------------------------------------------------------- audio

def decode_audio(video: PathLike, sr: int = 48000):
    """(n, 2) float32 samples of the first audio stream at `sr`, via st.audio.wav."""
    from ..audio import wav
    return wav.load(video, sr=sr)


def runs_below(levels_db: Sequence[float], hop: float, threshold_db: float, min_len: float) -> List[Span]:
    """Spans where a level curve stays below threshold for at least min_len seconds."""
    spans: List[Span] = []
    start = None
    for i, v in enumerate(list(levels_db) + [0.0]):
        quiet = i < len(levels_db) and v < threshold_db
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            s, e = start * hop, i * hop
            if e - s >= min_len - 1e-9:
                spans.append((round(s, 3), round(e, 3)))
            start = None
    return spans


def rms_curve(x, sr: int = 48000, hop: float = 0.05) -> List[float]:
    """Mono RMS in dBFS per hop window."""
    import numpy as np
    mono = x.mean(axis=1) if getattr(x, "ndim", 1) == 2 else x
    n = int(sr * hop)
    k = len(mono) // n
    if k == 0:
        return []
    seg = mono[: k * n].astype("float64").reshape(k, n)
    r = np.sqrt((seg ** 2).mean(axis=1))
    return [float(v) for v in 20 * np.log10(r + 1e-12)]


def clipped_runs(x, thresh: float = 0.995, min_run: int = 3, sr: int = 48000,
                 max_report: int = 20) -> Dict[str, Any]:
    """Runs of consecutive near-full-scale samples (a squared-off waveform).

    The threshold is slightly below 1.0 because the AAC round trip smears the
    flat tops of a clipped waveform by a few thousandths.
    """
    import numpy as np
    a = np.abs(x).max(axis=1) if getattr(x, "ndim", 1) == 2 else np.abs(x)
    hot = a >= thresh
    if not hot.any():
        return {"runs": 0, "samples": 0, "times": []}
    d = np.diff(np.concatenate([[0], hot.astype("int8"), [0]]))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    lens = ends - starts
    keep = lens >= min_run
    times = [round(float(s) / sr, 3) for s in starts[keep][:max_report]]
    return {"runs": int(keep.sum()), "samples": int(lens[keep].sum()), "times": times}
