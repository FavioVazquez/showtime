"""Cut the speaker out of a clip: a per-frame person matte on the CPU, with an open model.

    showtime footage cutout talk.mp4                      # -> talk.cutout.webm (VP9 + alpha) + talk.matte.mp4
    showtime footage cutout talk.mp4 --format prores      # ProRes 4444 .mov for an editor
    showtime footage cutout talk.mp4 --from 12 --to 18 --format png

Model: MODNet (trimap-free portrait matting, Zhanghan Ke et al., AAAI 2022; Apache-2.0, code and weights), its
portrait image-matting model as MODNet's own ONNX export (fp32, 26 MB; the copy Xenova publishes on Hugging
Face, Apache-2.0), setup/manifest.json item "modnet", fetched on first use and sha256-verified like every model.
It runs on onnxruntime's CPU provider, several small sessions side by side (one session with many threads
scales poorly on this network); no GPU.

Per frame: the frame is scaled so its short side is `short` px (512 by default, multiples of 32) for the
network; the matte that comes back is

1. smoothed over time (`Smoother`): an exponential moving average whose weight follows the picture's own
   motion, pixel by pixel (where the picture is still, the matte keeps most of its last value, so hair and
   edges stop shimmering; where something moves the new estimate wins at once), and reset at every cut
   (a jump in the picture, or a frame listed in `cuts`), so a matte never drags one shot into the next;
2. refined and upscaled with a fast guided filter (`refine`): the filter's coefficients are fitted at the
   network's size against the frame's luma and applied at the output size, so the edge follows the real
   hair and shoulder line of the full-size frame instead of a blurred low-resolution outline.

`flicker` is measured on the way: the share of the person's area whose matte jumps by more than 0.25
between two frames while the picture there barely changed (no motion to explain it), averaged over the
frames (cuts excluded). The cutout's report, the render report of a "behind" card, `edit check` and qa warn
above FLICKER_WARN.

`matte_stream` is the engine (the CLI and the "behind" card both use it); outputs are written by ffmpeg
from raw frames piped to it, so the colour of the original frames is never converted on the way.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import ff
from .. import platform as plat
from ..common import ShowtimeError, debug, info, ort_telemetry_off

MATTE_REV = 1
DEFAULT_SHORT = 512
FLICKER_WARN = 0.02           # 2 % of the person's area jumping per still frame reads as shimmering edges
CUT_JUMP = 0.11               # mean luma change (0..1) between two frames that counts as a cut
FORMATS = ("webm", "prores", "png")
MODEL_LABEL = "MODNet portrait matting (Apache-2.0), fp32 ONNX on the CPU"


# --------------------------------------------------------------------------------------------- model

def model_path(allow_download: bool = True) -> Path:
    from .asr_models import ensure
    return ensure("modnet", "cutting the speaker out (footage cutout, behind cards)", allow_download=allow_download)


def model_present() -> bool:
    from .asr_models import present
    return present("modnet")


def pool_size(threads: Optional[int] = None) -> Tuple[int, int]:
    """(sessions, threads per session) for this machine: small sessions side by side scale far better than
    one session with many threads (64 cores, 896x512: 16 x 2 threads 28 fps, 1 x 32 threads 5 fps; 6 cores:
    3 x 2 threads 7.0 inferences/s, 2 x 2 5.3, 1 x 6 6.4). Up to 8 cores every core runs the network (it is
    the slow part); bigger machines keep 2 cores for decoding, the edge filter and the encoders."""
    budget = int(threads or os.environ.get("SHOWTIME_THREADS") or 0) or plat.cpu_count()
    intra = 2 if budget >= 4 else 1
    spare = 2 if budget > 8 else 0
    return max(1, min(16, (budget - spare) // intra)), intra


def seek_for_frame(frame: int, fps: Any) -> float:
    """The input seek (s) whose first decoded frame is `frame` of a constant-rate file (half a frame early,
    so float rounding never skips it)."""
    return max(0.0, (int(frame) - 0.5) / eval_fps(fps)) if frame > 0 else 0.0


class Engine:
    """A pool of onnxruntime sessions of the matting model; `infer` is thread-safe."""

    def __init__(self, model: Optional[Path] = None, threads: Optional[int] = None) -> None:
        import onnxruntime as ort
        ort_telemetry_off(ort)
        model = Path(model) if model else model_path()
        self.sessions, intra = pool_size(threads)
        self.pool: "queue.Queue[Any]" = queue.Queue()
        for _ in range(self.sessions):
            so = ort.SessionOptions()
            so.intra_op_num_threads = intra
            so.inter_op_num_threads = 1
            so.log_severity_level = 3
            self.pool.put(ort.InferenceSession(str(model), sess_options=so, providers=["CPUExecutionProvider"]))
        s = self.pool.get()
        self.input = s.get_inputs()[0].name
        self.pool.put(s)
        self.executor = ThreadPoolExecutor(max_workers=self.sessions)

    def infer(self, rgb) -> Any:
        """uint8 RGB HxWx3 (H, W multiples of 32) -> float32 HxW matte in 0..1."""
        import numpy as np
        x = (rgb.astype(np.float32) * (1.0 / 127.5) - 1.0).transpose(2, 0, 1)[None]
        s = self.pool.get()
        try:
            return s.run(None, {self.input: x})[0][0, 0]
        finally:
            self.pool.put(s)

    def close(self) -> None:
        self.executor.shutdown(wait=True)


def infer_size(w: int, h: int, short: int = DEFAULT_SHORT) -> Tuple[int, int]:
    """The network's input size: short side `short` px (never above the frame's), both sides multiples of 32."""
    k = min(1.0, short / float(min(w, h)))
    return max(32, int(round(w * k / 32.0)) * 32), max(32, int(round(h * k / 32.0)) * 32)


# --------------------------------------------------------------------------------------------- temporal

class Smoother:
    """Motion-aware exponential smoothing of the matte, reset at cuts.

    new = a * raw + (1 - a) * previous, per pixel, with a = base where the picture is still and 1 where it
    moves by `motion` (luma 0..1, local mean) or more."""

    def __init__(self, base: float = 0.35, motion: float = 0.06) -> None:
        self.base = base
        self.motion = motion
        self.prev = None

    def __call__(self, raw, mot) -> Any:
        """The smoothed matte; `mot` is the local motion map, None at a cut (a new shot starts afresh)."""
        import numpy as np
        if mot is None or self.prev is None:
            out = raw
        else:
            a = np.clip(self.base + (1.0 - self.base) * (mot / self.motion), self.base, 1.0)
            out = a * raw + (1.0 - a) * self.prev
        self.prev = out
        return out


class Motion:
    """Local picture motion between consecutive frames (luma 0..1, 5x5 mean), and cuts: frame indices listed
    in `cuts`, or a jump of the mean luma over CUT_JUMP. Returns None for the first frame of a shot."""

    def __init__(self, cuts: Iterable[int] = ()) -> None:
        self.cuts = set(int(c) for c in cuts)
        self.prev = None
        self.n = 0

    def __call__(self, gray) -> Any:
        import cv2
        i = self.n
        self.n += 1
        prev, self.prev = self.prev, gray
        if prev is None or i in self.cuts:
            return None
        d = cv2.absdiff(gray, prev)
        if float(d.mean()) > CUT_JUMP:
            return None
        return cv2.blur(d, (5, 5))


def refine(m_lo, gray_lo, gray_hi, r: int = 2, eps: float = 1e-3):
    """Fast guided filter: fit q = a * I + b against the luma at the network's size, apply it at full size.
    Returns float32 HxW (the size of gray_hi) in 0..1. Outside the (dilated) soft region of the network's
    matte the result is pinned to it, so the filter never paints the background in."""
    import cv2
    import numpy as np
    k = (2 * r + 1, 2 * r + 1)
    mi = cv2.blur(gray_lo, k)
    mp = cv2.blur(m_lo, k)
    cov = cv2.blur(gray_lo * m_lo, k) - mi * mp
    var = cv2.blur(gray_lo * gray_lo, k) - mi * mi
    a = cov / (var + eps)
    b = mp - a * mi
    a = cv2.blur(a, k)
    b = cv2.blur(b, k)
    H, W = gray_hi.shape
    q = cv2.resize(a, (W, H), interpolation=cv2.INTER_LINEAR) * gray_hi + cv2.resize(b, (W, H), interpolation=cv2.INTER_LINEAR)
    up = cv2.resize(m_lo, (W, H), interpolation=cv2.INTER_LINEAR)
    soft = cv2.resize(((m_lo > 0.02) & (m_lo < 0.98)).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    grow = max(3, int(round(2.5 * (r + 1) * W / float(m_lo.shape[1]))) | 1)
    soft = cv2.dilate(soft, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
    out = np.where(soft > 0, q, up)
    return np.clip(out, 0.0, 1.0, out=out)


def flicker_of(m, prev, motion) -> Optional[float]:
    """Share of the person's area (matte > 0.5) whose matte moved by > 0.25 where the picture is still."""
    import numpy as np
    if prev is None or motion is None:
        return None
    area = float((m > 0.5).sum())
    if area < 64:
        return None
    jump = (np.abs(m - prev) > 0.25) & (motion < 0.012)
    return float(jump.sum()) / area


# --------------------------------------------------------------------------------------------- the stream

def _yuv_reader(src: Path, start: float, frames: Optional[int], W: int, H: int, fps: Optional[str]):
    """Raw yuv420p frames (bytes) of `src` from `start`, scaled to W x H (BT.709 kept as is)."""
    vf = ["scale=%d:%d:flags=bicubic" % (W, H)]
    if fps:
        vf.insert(0, "fps=%s" % fps)
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if start > 0:
        args += ["-ss", "%.6f" % start]
    args += ["-i", str(src), "-an", "-sn", "-vf", ",".join(vf + ["format=yuv420p"])]
    if frames:
        args += ["-frames:v", str(int(frames))]
    args += ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = W * H * 3 // 2
    try:
        while True:
            buf = p.stdout.read(size) if p.stdout else b""
            if len(buf) < size:
                break
            yield buf
    finally:
        if p.stdout:
            p.stdout.close()
        err = p.stderr.read().decode("utf-8", "replace") if p.stderr else ""
        if p.stderr:
            p.stderr.close()
        rc = p.wait()
        if rc not in (0, None) and rc > 0 and "Broken pipe" not in err:
            debug("cutout decode: ffmpeg rc %s: %s" % (rc, err.strip()[-400:]))


def frame_size(pr: Dict[str, Any], name: str = "the clip") -> Tuple[int, int]:
    """The display size of a probed video (square pixels), made even."""
    w0 = int(pr.get("display_width") or pr.get("width") or 0)
    h0 = int(pr.get("display_height") or pr.get("height") or 0)
    sar = str(pr.get("sar") or "1:1")
    if sar not in ("1:1", "0:1") and ":" in sar:
        n, d = sar.split(":")
        try:
            w0 = int(round(w0 * float(n) / float(d or 1)))
        except ValueError:
            pass
    if not (w0 and h0):
        raise ShowtimeError("%s has no video stream to cut out" % name)
    return w0 // 2 * 2, h0 // 2 * 2


def matte_stream(src: Path, *, start: float = 0.0, frames: Optional[int] = None, size: Optional[Tuple[int, int]] = None,
                 fps: Optional[str] = None, short: int = DEFAULT_SHORT, cuts: Sequence[int] = (), smooth: bool = True,
                 refine_edges: bool = True, engine: Optional[Engine] = None, threads: Optional[int] = None,
                 on_frame: Optional[Callable[[int, bytes, Any], None]] = None,
                 progress: Optional[str] = None) -> Dict[str, Any]:
    """Matte every frame of `src` from `start` (`frames` of them, else to the end) at `size` (W, H; default:
    the source's display size, made even). `on_frame(i, yuv420p bytes, matte uint8 HxW)` gets each frame in
    order. `cuts` are frame indices (from `start`) that begin a new shot. `fps` resamples the frame rate
    (None: the file's own frames, e.g. a render's intermediate; `seek_for_frame` gives a frame-exact start).
    Returns the stats."""
    import cv2
    import numpy as np
    from . import util as U
    src = Path(src)
    if size is None:
        size = frame_size(U.probe(src), src.name)
    W, H = int(size[0]) // 2 * 2, int(size[1]) // 2 * 2
    iw, ih = infer_size(W, H, short)
    own = engine is None
    eng = engine or Engine(threads=threads)
    sm = Smoother() if smooth else None
    mo = Motion(cuts)
    prev_m = None
    t0 = time.time()
    t_inf = [0.0]
    flick: List[float] = []
    cover: List[float] = []
    resets = 0
    n = 0
    window = 2 * eng.sessions + 2
    pending: "List[Tuple[int, bytes, Any, Any, Any]]" = []

    def prep(buf: bytes):
        yuv = np.frombuffer(buf, dtype=np.uint8).reshape(H * 3 // 2, W)
        rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)
        small = cv2.resize(rgb, (iw, ih), interpolation=cv2.INTER_AREA)
        return yuv, small

    def run_infer(small):
        a = time.time()
        m = eng.infer(small)
        t_inf[0] += time.time() - a
        return m

    def finish(i: int, buf: bytes, yuv, small, fut) -> None:
        nonlocal resets, prev_m
        raw = fut.result()
        gray_lo = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32) * (1.0 / 255.0)
        mot = mo(gray_lo)
        if mot is None and i:
            resets += 1
        m = sm(raw, mot) if sm is not None else raw
        f = flicker_of(m, prev_m, mot)
        if f is not None:
            flick.append(f)
        prev_m = m
        if refine_edges:
            gray_hi = yuv[:H].astype(np.float32) * (1.0 / 255.0)
            # the network's input was RGB-converted luma; the decode's own Y plane is (16..235): stretch it
            gray_hi = np.clip((gray_hi - 16.0 / 255.0) * (255.0 / 219.0), 0.0, 1.0)
            out = refine(m, gray_lo, gray_hi)
        else:
            out = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR)
        mu8 = (out * 255.0 + 0.5).astype(np.uint8)
        cover.append(float(m.mean()))
        if on_frame is not None:
            on_frame(i, buf, mu8)

    last_say = time.time()
    try:
        for buf in _yuv_reader(src, start, frames, W, H, fps):
            yuv, small = prep(buf)
            pending.append((n, buf, yuv, small, eng.executor.submit(run_infer, small)))
            n += 1
            while len(pending) >= window:
                finish(*pending.pop(0))
            if progress and time.time() - last_say > 10 and frames:
                info("%s: %d/%d frames (%.1f fps)" % (progress, n, frames, n / max(1e-6, time.time() - t0)))
                last_say = time.time()
        while pending:
            finish(*pending.pop(0))
    finally:
        if own:
            eng.close()
    if n == 0:
        raise ShowtimeError("no frames decoded from %s at %.2f s" % (src.name, start))
    el = time.time() - t0
    flick_mean = float(np.mean(flick)) if flick else 0.0
    return {"frames": n, "width": W, "height": H, "infer_size": [iw, ih], "seconds": round(el, 2),
            "fps": round(n / max(el, 1e-6), 2), "infer_ms_per_frame": round(1000.0 * t_inf[0] / n, 1),
            "sessions": eng.sessions, "smooth": bool(smooth), "refine": bool(refine_edges), "resets": resets,
            "flicker": round(flick_mean, 4), "flicker_p95": round(float(np.percentile(flick, 95)), 4) if flick else 0.0,
            "coverage": round(float(np.mean(cover)), 4) if cover else 0.0,
            "empty_frames": int(sum(1 for c in cover if c < 0.002))}


# --------------------------------------------------------------------------------------------- writers

class Pipe:
    """An ffmpeg encoder fed raw frames on stdin from a writer thread (the matting loop never waits on it)."""

    def __init__(self, args: List[str], label: str) -> None:
        self.label = label
        self.p = subprocess.Popen([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"] + args,
                                  stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=48)
        self.err = b""
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self) -> None:
        try:
            while True:
                b = self.q.get()
                if b is None:
                    break
                self.p.stdin.write(b)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                self.p.stdin.close()
            except OSError:
                pass

    def write(self, b: bytes) -> None:
        self.q.put(b)

    def close(self) -> None:
        self.q.put(None)
        self.t.join()
        self.err = self.p.stderr.read() if self.p.stderr else b""
        if self.p.stderr:
            self.p.stderr.close()
        if self.p.wait() != 0:
            raise ShowtimeError("could not write the %s: %s" % (self.label, self.err.decode("utf-8", "replace").strip()[-600:]))


def _tags(pr: Dict[str, Any]) -> List[str]:
    cs = str(pr.get("color_space") or "").lower()
    if cs in ("", "unknown", "bt709", "reserved") and (pr.get("height") or 0) >= 720:
        return list(ff.BT709_TAGS)
    return []


def matte_args(out: Path, W: int, H: int, fps: str, lossless: bool = False) -> List[str]:
    """Encoder args for a matte-only file from raw gray frames: H.264 (luma = matte) that plays anywhere, or
    FFV1 (lossless, for showtime's own composites)."""
    inp = ["-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (W, H), "-r", fps, "-i", "-"]
    if lossless:
        return inp + ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gray", "-f", "matroska", str(out)]
    return inp + ["-vf", "scale=out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                  "-color_range", "tv", "-movflags", "+faststart", str(out)]


def alpha_args(out: Path, fmt: str, W: int, H: int, fps: str, pr: Dict[str, Any], audio: Optional[Tuple[Path, float, float]]
               ) -> List[str]:
    """Encoder args for the cut-out from raw yuva420p frames (the frame's own Y/U/V + the matte as alpha)."""
    inp = ["-f", "rawvideo", "-pix_fmt", "yuva420p", "-s", "%dx%d" % (W, H), "-r", fps, "-i", "-"]
    aud: List[str] = []
    if audio and fmt != "png":
        a_src, a_start, a_dur = audio
        inp += ["-ss", "%.6f" % a_start, "-t", "%.6f" % a_dur, "-i", str(a_src)]
        aud = ["-map", "0:v", "-map", "1:a?"] + (["-c:a", "libopus", "-b:a", "128k"] if fmt == "webm"
                                                 else ["-c:a", "pcm_s16le"]) + ["-shortest"]
    tags = _tags(pr)
    if fmt == "webm":
        return inp + aud + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "28", "-row-mt", "1",
                            "-deadline", "good", "-cpu-used", "5", "-auto-alt-ref", "0", "-g", "%d" % max(1, round(float(eval_fps(fps)) * 2))
                            ] + tags + ["-f", "webm", str(out)]
    if fmt == "prores":
        return inp + aud + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16",
                            "-vendor", "apl0"] + tags + ["-f", "mov", str(out)]
    if fmt == "png":
        # raw frames carry no colour tags: say which matrix they use, or RGB comes out with BT.601's colours
        conv = ["-vf", "scale=in_color_matrix=bt709:in_range=tv"] if tags else []
        return inp + conv + ["-pix_fmt", "rgba", "-start_number", "0", str(out / "%06d.png")]
    raise ShowtimeError("unknown cutout format %r" % fmt, hint="use webm, prores or png")


def eval_fps(fps: str) -> float:
    if "/" in str(fps):
        a, b = str(fps).split("/", 1)
        return float(a) / float(b or 1)
    return float(fps)


def _sample(buf: bytes, m, W: int, H: int, width: int = 560) -> Tuple[Any, Any]:
    """A small RGB copy of a frame and its matte, for the contact sheet."""
    import cv2
    import numpy as np
    yuv = np.frombuffer(buf, dtype=np.uint8).reshape(H * 3 // 2, W)
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)
    h = max(2, int(round(H * width / float(W))))
    return (cv2.resize(bgr, (width, h), interpolation=cv2.INTER_AREA),
            cv2.resize(m, (width, h), interpolation=cv2.INTER_AREA))


def write_sheet(samples: Sequence[Tuple[Any, Any]], out: Path) -> Path:
    """A contact sheet to look at (a cut-out plays without its alpha in most viewers): each sampled frame cut
    out over a checkerboard, its matte under it (white = person)."""
    import cv2
    import numpy as np
    cols = []
    for bgr, m in samples:
        h, w = m.shape
        yy, xx = np.mgrid[0:h, 0:w]
        checker = np.where(((yy // 16) + (xx // 16)) % 2 == 0, 200, 140).astype(np.float32)[..., None]
        a = (m.astype(np.float32) / 255.0)[..., None]
        cut = (bgr.astype(np.float32) * a + checker * (1.0 - a)).astype(np.uint8)
        gap = np.full((6, w, 3), 24, np.uint8)
        cols.append(np.vstack([cut, gap, cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)]))
    sep = np.full((cols[0].shape[0], 6, 3), 24, np.uint8)
    img = cols[0]
    for c in cols[1:]:
        img = np.hstack([img, sep, c])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return out


def cutout_video(src: Path, *, out: Optional[Path] = None, matte_out: Optional[Path] = None, fmt: str = "webm",
                 start: float = 0.0, end: Optional[float] = None, short: int = DEFAULT_SHORT, smooth: bool = True,
                 refine_edges: bool = True, audio: bool = True, matte_only: bool = False,
                 threads: Optional[int] = None) -> Dict[str, Any]:
    """`showtime footage cutout`: the alpha video (unless matte_only) and the matte-only file."""
    from . import util as U
    src = Path(src)
    if not src.is_file():
        raise ShowtimeError("video not found: %s" % src)
    if fmt not in FORMATS:
        raise ShowtimeError("unknown format %r" % fmt, hint="webm (VP9 with alpha, plays in browsers and composites in "
                            "showtime), prores (ProRes 4444 for editors) or png (a numbered PNG sequence)")
    pr = U.probe(src)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src.name)
    dur = float(pr.get("video_duration") or pr.get("duration") or 0.0)
    a = max(0.0, float(start or 0.0))
    b = min(dur, float(end)) if end is not None else dur
    if not b > a:
        raise ShowtimeError("nothing to cut out: --from %.2f is not before --to %.2f (the clip is %.2f s)" % (a, b, dur))
    fps = U.fps_str(U.normalize_fps(float(pr.get("fps") or 30.0)))
    frames = max(1, int(round((b - a) * eval_fps(fps))))
    W, H = frame_size(pr, src.name)
    ext = {"webm": ".webm", "prores": ".mov", "png": ""}[fmt]
    if out is None:
        raise ShowtimeError("internal: no output path")
    out = Path(out)
    matte_out = Path(matte_out) if matte_out else out.with_name(out.name.split(".cutout")[0] + ".matte.mp4")
    if fmt == "png" and not matte_only:
        out.mkdir(parents=True, exist_ok=True)
    elif not matte_only and out.suffix.lower() != ext:
        out = out.with_suffix(ext)
    pipes: List[Pipe] = []
    mp = Pipe(matte_args(matte_out, W, H, fps), "matte")
    pipes.append(mp)
    ap = None
    if not matte_only:
        ap = Pipe(alpha_args(out, fmt, W, H, fps, pr, (src, a, b - a) if audio and pr.get("has_audio") else None),
                  "cut-out video")
        pipes.append(ap)

    picks = sorted({int(frames * k) for k in (0.15, 0.5, 0.85)})
    samples: List[Tuple[Any, Any]] = []

    def on_frame(i: int, buf: bytes, m) -> None:
        mb = m.tobytes()
        mp.write(mb)
        if ap is not None:
            ap.write(buf + mb)          # yuva420p: the frame's own Y, U, V planes, then the matte as A
        if i in picks:
            samples.append(_sample(buf, m, W, H))

    info("cutout: %s, %d frames at %dx%d (%s)" % (src.name, frames, W, H, "matte only" if matte_only else fmt))
    try:
        st = matte_stream(src, start=a, frames=frames, size=(W, H), fps=fps, short=short, smooth=smooth,
                          refine_edges=refine_edges, threads=threads, on_frame=on_frame, progress="cutout")
    except BaseException:
        for p in pipes:
            try:
                p.close()
            except ShowtimeError:
                pass
        raise
    for p in pipes:
        p.close()
    sheet = matte_out.with_name(matte_out.name.split(".matte")[0] + ".cutout-sheet.jpg")
    sheet = write_sheet(samples, sheet) if samples else None
    rep = dict(st, input=str(src), output=None if matte_only else str(out), matte=str(matte_out), format=None if matte_only else fmt,
               sheet=str(sheet) if sheet else None,
               start=round(a, 3), end=round(b, 3), fps_out=fps,
               per_1080p_frame_ms=round(1000.0 * st["seconds"] / st["frames"] * (1920 * 1080) / float(W * H), 1),
               seconds_per_minute=round(st["seconds"] / max(1e-6, (st["frames"] / eval_fps(fps))) * 60.0, 1),
               model=MODEL_LABEL)
    if st["flicker"] > FLICKER_WARN:
        rep["warning"] = ("the matte is unstable: %.1f %% of the person's area flickers per still frame (over %.0f %%): "
                          "a busy background or low light; try --size 640, or a cleaner shot" % (100 * st["flicker"], 100 * FLICKER_WARN))
    if st["empty_frames"] > 0.2 * st["frames"]:
        rep["warning_empty"] = "%d of %d frames found no person (the model cuts out people, not objects)" % (
            st["empty_frames"], st["frames"])
    return rep
