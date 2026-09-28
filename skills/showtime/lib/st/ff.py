"""ffmpeg / ffprobe resolution, probing and encode presets.

Never call a bare `ffmpeg`: always go through `ffmpeg_path()` / `run_ffmpeg()`.

Resolution order (first that actually runs wins):
  1. $SHOWTIME_FFMPEG (and $SHOWTIME_FFPROBE, else the sibling ffprobe)
  2. ~/.showtime/bin/ffmpeg(.exe)            (installed by `showtime setup`)
  3. ffmpeg on PATH, only if `ffmpeg -version` exits 0
  4. imageio-ffmpeg's bundled binary          (no ffprobe: probe() falls back
                                               to parsing `ffmpeg -i`)

Stdlib only (imageio-ffmpeg is imported lazily when present) and Python
3.8+ compatible, so `showtime doctor` can use it before the venv exists.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from . import platform as plat
from .common import RunError, ShowtimeError, debug, home, read_json, run, write_json
from .platform import concat_list_path, filter_path, filter_value  # re-exported

PathLike = Union[str, "os.PathLike[str]"]

__all__ = [
    "FF", "resolve", "ffmpeg_path", "ffprobe_path", "run_ffmpeg", "probe", "capabilities",
    "has_filter", "has_encoder", "PRESETS", "Preset", "preset", "encode", "measure_loudness",
    "filter_path", "filter_value", "concat_list_path", "REQUIRED_FILTERS", "REQUIRED_ENCODERS",
    "RECOMMENDED_FILTERS", "AAC_BITRATE", "AAC_CODER", "TP_MARGIN_DB", "aac_args", "audio_levels", "ensure_true_peak",
]

# What showtime needs from ffmpeg. Missing "required" items fail doctor/setup;
# "recommended" ones only warn (features degrade gracefully).
REQUIRED_ENCODERS = ["libx264", "aac"]
REQUIRED_FILTERS = ["subtitles", "ass", "drawtext", "loudnorm", "ebur128", "xfade", "scale",
                    "overlay", "amix", "sidechaincompress", "silencedetect", "palettegen"]
RECOMMENDED_FILTERS = ["zscale", "vidstabdetect", "vidstabtransform", "arnndn", "lut3d",
                       "rubberband", "minterpolate", "afftdn"]
RECOMMENDED_ENCODERS = ["libvpx-vp9", "libopus", "prores_ks", "libmp3lame", "libwebp"]


@dataclass
class FF:
    ffmpeg: str
    ffprobe: Optional[str]
    source: str                 # env | showtime | system | imageio
    version: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe, "source": self.source,
                "version": self.version}


_lock = threading.Lock()
_cached: Optional[FF] = None


def _version_of(exe_path: str) -> Optional[str]:
    """First line of `-version` if the binary runs, else None."""
    try:
        cp = subprocess.run([exe_path, "-hide_banner", "-version"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    first = (cp.stdout or "").splitlines()[:1]
    m = re.search(r"version\s+(\S+)", first[0]) if first else None
    return m.group(1) if m else (first[0] if first else "unknown")


def _sibling(exe_path: str, name: str) -> Optional[str]:
    p = Path(exe_path).with_name(plat.exe(name))
    return str(p) if p.is_file() else None


def _system_candidates(name: str) -> List[str]:
    """Every `name` on PATH except ~/.showtime/bin (checked separately)."""
    ours = os.path.normcase(str(home() / "bin"))
    out = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or os.path.normcase(os.path.abspath(d)) == ours:
            continue
        p = shutil.which(name, path=d)
        if p and p not in out:
            out.append(p)
    return out


def resolve(refresh: bool = False) -> FF:
    """Find a working ffmpeg (and ffprobe). Raises ShowtimeError if none."""
    global _cached
    with _lock:
        if _cached is not None and not refresh:
            return _cached
        tried: List[str] = []

        env = os.environ.get("SHOWTIME_FFMPEG")
        if env:
            v = _version_of(env)
            tried.append("SHOWTIME_FFMPEG=%s" % env)
            if v:
                probe_env = os.environ.get("SHOWTIME_FFPROBE") or _sibling(env, "ffprobe")
                _cached = FF(env, probe_env if probe_env and _version_of(probe_env) else None, "env", v)
                return _cached
            raise ShowtimeError("SHOWTIME_FFMPEG=%s does not run" % env,
                                hint="unset it or point it at a working ffmpeg")

        ours = home() / "bin" / plat.exe("ffmpeg")
        tried.append(str(ours))
        if ours.is_file():
            v = _version_of(str(ours))
            if v:
                pr = _sibling(str(ours), "ffprobe")
                _cached = FF(str(ours), pr, "showtime", v)
                return _cached

        for cand in _system_candidates("ffmpeg"):
            tried.append(cand)
            v = _version_of(cand)
            if v:
                pr = _sibling(cand, "ffprobe")
                if pr is None:
                    for c in _system_candidates("ffprobe"):
                        if _version_of(c):
                            pr = c
                            break
                _cached = FF(cand, pr, "system", v)
                return _cached
            debug("ffmpeg at %s does not run; skipping" % cand)

        try:
            import imageio_ffmpeg  # type: ignore

            p = imageio_ffmpeg.get_ffmpeg_exe()
            tried.append(p)
            v = _version_of(p)
            if v:
                _cached = FF(p, None, "imageio", v)
                return _cached
        except Exception:  # noqa: BLE001 - optional dependency
            pass

        raise ShowtimeError("no working ffmpeg found (tried: %s)" % ", ".join(tried),
                            hint="run `showtime setup` to install a static ffmpeg into ~/.showtime/bin")


def ffmpeg_path() -> str:
    return resolve().ffmpeg


def ffprobe_path() -> Optional[str]:
    return resolve().ffprobe


def run_ffmpeg(args: Sequence[Union[str, PathLike]], *, overwrite: bool = True,
               loglevel: str = "error", check: bool = True, capture: bool = True,
               timeout: Optional[float] = None, cwd: Optional[PathLike] = None) -> subprocess.CompletedProcess:
    """Run ffmpeg with `args` (list). Adds -hide_banner, -nostdin, -loglevel, -y."""
    argv: List[str] = [ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", loglevel]
    if overwrite:
        argv.append("-y")
    argv += [os.fspath(a) for a in args]
    return run(argv, check=check, capture=capture, timeout=timeout, cwd=cwd)


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------

def _list_names(exe_path: str, what: str) -> List[str]:
    cp = subprocess.run([exe_path, "-hide_banner", "-" + what], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, timeout=60, encoding="utf-8", errors="replace")
    names = []
    for line in (cp.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        flags, name = parts[0], parts[1]
        if what == "filters":
            if re.match(r"^[TSC.|]{2,3}$", flags):
                names.append(name)
        elif re.match(r"^[VASFXBD.]{6}$", flags):
            names.append(name)
    return names


def capabilities(exe_path: Optional[str] = None, use_cache: bool = True) -> Dict[str, Any]:
    """{'filters': [...], 'encoders': [...], 'version': str}; cached per binary."""
    exe_path = exe_path or ffmpeg_path()
    try:
        st = os.stat(exe_path)
        key = "%s|%d|%d" % (os.path.realpath(exe_path), st.st_size, int(st.st_mtime))
    except OSError:
        key = exe_path
    cache_file = home() / "cache" / "ffcaps.json"
    cache: Dict[str, Any] = {}
    if use_cache and cache_file.is_file():
        try:
            cache = read_json(cache_file, {})
        except ShowtimeError:
            cache = {}
        if key in cache:
            return cache[key]
    caps = {
        "version": _version_of(exe_path) or "",
        "filters": _list_names(exe_path, "filters"),
        "encoders": _list_names(exe_path, "encoders"),
    }
    if use_cache and caps["filters"]:
        cache = {k: v for k, v in cache.items() if not k.startswith(os.path.realpath(exe_path) + "|")}
        cache[key] = caps
        try:
            write_json(cache_file, cache)
        except OSError:
            pass
    return caps


def has_filter(name: str) -> bool:
    return name in capabilities()["filters"]


def has_encoder(name: str) -> bool:
    return name in capabilities()["encoders"]


def check_capabilities(exe_path: Optional[str] = None) -> Dict[str, List[str]]:
    """Missing required/recommended filters and encoders for a binary."""
    caps = capabilities(exe_path)
    f, e = set(caps["filters"]), set(caps["encoders"])
    return {
        "missing_required": [x for x in REQUIRED_FILTERS if x not in f] + [x for x in REQUIRED_ENCODERS if x not in e],
        "missing_recommended": [x for x in RECOMMENDED_FILTERS if x not in f] + [x for x in RECOMMENDED_ENCODERS if x not in e],
    }


# --------------------------------------------------------------------------
# Probe
# --------------------------------------------------------------------------

def _frac(s: Optional[str]) -> Optional[float]:
    if not s or s in ("0/0", "N/A"):
        return None
    try:
        v = float(Fraction(s))
        return v if v > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _rotation(stream: Dict[str, Any]) -> int:
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(round(float(sd["rotation"]))) % 360
            except (TypeError, ValueError):
                pass
    tag = (stream.get("tags") or {}).get("rotate")
    if tag:
        try:
            return (-int(tag)) % 360  # legacy tag is clockwise
        except ValueError:
            pass
    return 0


def probe(path: PathLike) -> Dict[str, Any]:
    """Describe a media file.

    Returns: path, duration, size_bytes, format, bit_rate, has_video,
    width, height, rotation, display_width, display_height, fps, nb_frames,
    vcodec, pix_fmt, color_space, color_transfer, color_primaries,
    color_range, has_alpha, has_audio, audio_streams[{index, codec,
    sample_rate, channels, channel_layout, duration, language}], streams.
    """
    p = Path(path)
    if not p.exists():
        raise ShowtimeError("file not found: %s" % p)
    ff = resolve()
    if ff.ffprobe is None:
        return _probe_with_ffmpeg(p)
    cp = run([ff.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
             check=False)
    if cp.returncode != 0:
        raise ShowtimeError("ffprobe could not read %s: %s" % (p, (cp.stderr or "").strip()[-400:]))
    data = json.loads(cp.stdout or "{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    dur = _float(fmt.get("duration"))
    if dur is None:
        durs = [_float(s.get("duration")) for s in streams]
        durs = [d for d in durs if d]
        dur = max(durs) if durs else None
    out: Dict[str, Any] = {
        "path": str(p.resolve()),
        "duration": dur,
        "size_bytes": _int(fmt.get("size")) or p.stat().st_size,
        "format": fmt.get("format_name"),
        "bit_rate": _int(fmt.get("bit_rate")),
        "has_video": v is not None,
        "has_audio": bool(auds),
        "audio_streams": [{
            "index": s.get("index"),
            "codec": s.get("codec_name"),
            "sample_rate": _int(s.get("sample_rate")),
            "channels": s.get("channels"),
            "channel_layout": s.get("channel_layout"),
            "duration": _float(s.get("duration")),
            "language": (s.get("tags") or {}).get("language"),
        } for s in auds],
        "streams": len(streams),
    }
    if v is not None:
        w, h = v.get("width"), v.get("height")
        rot = _rotation(v)
        fps = _frac(v.get("avg_frame_rate")) or _frac(v.get("r_frame_rate"))
        pix = v.get("pix_fmt") or ""
        out.update({
            "width": w, "height": h, "rotation": rot,
            "display_width": h if rot in (90, 270) else w,
            "display_height": w if rot in (90, 270) else h,
            "fps": round(fps, 6) if fps else None,
            "nb_frames": _int(v.get("nb_frames")),
            "video_duration": _float(v.get("duration")),
            "vcodec": v.get("codec_name"),
            "pix_fmt": pix,
            "has_alpha": bool(re.search(r"(yuva|rgba|argb|bgra|abgr|gbrap|ya)", pix)),
            "color_space": v.get("color_space"),
            "color_transfer": v.get("color_transfer"),
            "color_primaries": v.get("color_primaries"),
            "color_range": v.get("color_range"),
            "sar": v.get("sample_aspect_ratio"),
        })
    return out


def _float(x: Any) -> Optional[float]:
    try:
        return float(x) if x not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def _int(x: Any) -> Optional[int]:
    try:
        return int(x) if x not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def _probe_with_ffmpeg(p: Path) -> Dict[str, Any]:
    """Minimal probe for builds without ffprobe (imageio-ffmpeg fallback)."""
    cp = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(p)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=60)
    txt = cp.stderr or ""
    out: Dict[str, Any] = {"path": str(p.resolve()), "size_bytes": p.stat().st_size, "streams": 0,
                           "has_video": False, "has_audio": False, "audio_streams": [],
                           "rotation": 0, "probe": "ffmpeg-fallback"}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    out["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    vm = re.search(r"Stream #\S+.*?Video:\s*(\w+)[^,]*,\s*([\w]+)?.*?(\d{2,5})x(\d{2,5})", txt)
    if vm:
        w, h = int(vm.group(3)), int(vm.group(4))
        fm = re.search(r"([\d.]+)\s*fps", txt)
        out.update({"has_video": True, "vcodec": vm.group(1), "pix_fmt": vm.group(2), "width": w,
                    "height": h, "display_width": w, "display_height": h,
                    "fps": float(fm.group(1)) if fm else None})
    for am in re.finditer(r"Stream #\d+:(\d+).*?Audio:\s*(\w+).*?(\d+) Hz,\s*([^,]+)", txt):
        out["has_audio"] = True
        out["audio_streams"].append({"index": int(am.group(1)), "codec": am.group(2),
                                     "sample_rate": int(am.group(3)), "channel_layout": am.group(4).strip()})
    return out


# --------------------------------------------------------------------------
# Encode presets
# --------------------------------------------------------------------------

BT709_VF = "scale=out_color_matrix=bt709:out_range=tv"
BT709_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
              "-color_range", "tv"]


@dataclass
class Preset:
    """Output options for one delivery flavour.

    vf_tail is appended to the caller's video filter chain (colour matrix
    conversion + pixel format); video/audio/container are output args.
    """
    name: str
    ext: str
    vf_tail: str
    video: List[str]
    audio: List[str]
    container: List[str] = field(default_factory=list)
    description: str = ""

    def output_args(self, fps: Optional[float] = None, crf: Optional[int] = None,
                    audio: bool = True) -> List[str]:
        v = list(self.video)
        if crf is not None:
            if "-crf" in v:
                v[v.index("-crf") + 1] = str(crf)
            else:
                v += ["-crf", str(crf)]
        if fps:
            v += ["-r", _fps_str(fps)]
        return v + (list(self.audio) if audio else ["-an"]) + list(self.container)


def _fps_str(fps: float) -> str:
    fr = Fraction(fps).limit_denominator(1001)
    return "%d/%d" % (fr.numerator, fr.denominator) if fr.denominator != 1 else str(fr.numerator)


# Final audio: AAC at 256 kb/s. ffmpeg's native AAC encoder at 192 kb/s (default
# coder) was measured producing a burst that pushed a heavily limited speech
# track from -1.5 to +3.9 dBTP; 256k and `-aac_coder fast` were clean. AAC also
# adds 0.2-0.4 dB of peak overshoot in general, so masters aim TP_MARGIN_DB
# under the delivery ceiling and encoders re-check the peak afterwards
# (ensure_true_peak).
AAC_BITRATE = "256k"
AAC_CODER = "fast"      # the same coder every other showtime AAC encode uses
TP_MARGIN_DB = 0.5


def aac_args(bitrate: str = AAC_BITRATE, coder: Optional[str] = "fast", sample_rate: int = 48000) -> List[str]:
    """Output args for AAC audio (optionally with `-aac_coder fast`)."""
    args = ["-c:a", "aac"]
    if coder:
        args += ["-aac_coder", coder]
    return args + ["-b:a", str(bitrate), "-ar", str(sample_rate)]


PRESETS: Dict[str, Preset] = {
    "final": Preset(
        "final", ".mp4", BT709_VF + ",format=yuv420p",
        ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high",
         "-pix_fmt", "yuv420p"] + BT709_TAGS,
        aac_args(AAC_BITRATE, coder=AAC_CODER),
        ["-movflags", "+faststart"],
        "H.264 High, CRF 16, BT.709 tv-range, AAC 256k fast coder (peak re-checked), +faststart"),
    "preview": Preset(
        "preview", ".mp4", BT709_VF + ",format=yuv420p",
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"] + BT709_TAGS,
        aac_args("128k", coder=AAC_CODER),
        ["-movflags", "+faststart"],
        "fast H.264 CRF 23 for review, AAC 128k"),
    "alpha_prores": Preset(
        "alpha_prores", ".mov", BT709_VF + ",format=yuva444p10le",
        ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0",
         "-alpha_bits", "16"] + BT709_TAGS,
        ["-c:a", "pcm_s16le", "-ar", "48000"],
        [],
        "ProRes 4444 with alpha (for NLE compositing)"),
    "alpha_webm": Preset(
        "alpha_webm", ".webm", BT709_VF + ",format=yuva420p",
        ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-row-mt", "1",
         "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "2"] + BT709_TAGS,
        ["-c:a", "libopus", "-b:a", "128k", "-ar", "48000"],
        [],
        "VP9 with alpha (for the web)"),
    "gif": Preset(
        "gif", ".gif", "",
        [], [], ["-loop", "0"],
        "palette-optimised GIF (use encode(); it builds the palette graph)"),
}


def preset(name: str) -> Preset:
    try:
        return PRESETS[name]
    except KeyError:
        raise ShowtimeError("unknown preset %r (choose from: %s)" % (name, ", ".join(PRESETS)))


def gif_filter(fps: float = 15, width: int = 720) -> str:
    return ("fps=%s,scale=%d:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" % (_fps_str(fps), width))


def encode(src: PathLike, dst: PathLike, preset_name: str = "final", vf: Optional[str] = None,
           af: Optional[str] = None, fps: Optional[float] = None, crf: Optional[int] = None,
           extra_input: Sequence[str] = (), extra_output: Sequence[str] = (),
           gif_width: int = 720, gif_fps: float = 15,
           true_peak: Union[float, str, None] = "auto") -> Path:
    """Transcode `src` to `dst` with a named preset; returns dst.

    true_peak: ceiling in dBTP re-checked after an AAC encode (see
    ensure_true_peak). "auto" (default) guards the final preset at -1 dBTP
    when the source itself was under that ceiling; None disables the check.
    """
    pr = preset(preset_name)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    args: List[str] = list(extra_input) + ["-i", os.fspath(src)]
    has_audio = False
    if pr.name == "gif":
        chain = ((vf + ",") if vf else "") + gif_filter(gif_fps, gif_width)
        args += ["-filter_complex", chain, "-an"] + pr.container
    else:
        chain = ",".join(x for x in (vf, pr.vf_tail) if x)
        if chain:
            args += ["-vf", chain]
        if af:
            args += ["-af", af]
        try:
            has_audio = probe(src).get("has_audio", False)
        except ShowtimeError:
            pass
        args += pr.output_args(fps=fps, crf=crf, audio=has_audio)
    args += list(extra_output) + [os.fspath(dst)]
    ceiling: Optional[float] = None
    if pr.name != "gif" and has_audio and "aac" in pr.audio and true_peak is not None:
        if true_peak == "auto":
            if pr.name == "final" and not af:
                src_tp = audio_levels(src).get("true_peak_dbtp")
                if src_tp is not None and src_tp <= -1.0 + 0.05:
                    ceiling = -1.0
        else:
            ceiling = float(true_peak)
    run_ffmpeg(args)
    if ceiling is not None:
        ensure_true_peak(dst, ceiling)   # re-encodes from dst's own audio (keeps any trim/filters)
    return dst


# --------------------------------------------------------------------------
# Loudness
# --------------------------------------------------------------------------

def measure_loudness(path: PathLike, target_i: float = -14.0, target_tp: float = -1.0,
                     target_lra: float = 11.0) -> Dict[str, float]:
    """Integrated loudness / true peak / LRA via loudnorm's analysis pass.

    Returns input_i, input_tp, input_lra, input_thresh, target_offset (the
    values a second loudnorm pass needs as measured_* options).
    """
    cp = run_ffmpeg(["-i", os.fspath(path), "-vn", "-af",
                     "loudnorm=I=%s:TP=%s:LRA=%s:print_format=json" % (target_i, target_tp, target_lra),
                     "-f", "null", "-"], loglevel="info", overwrite=False)
    txt = cp.stderr or ""
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    if not m:
        raise ShowtimeError("could not measure loudness of %s (no audio stream?)" % path)
    data = json.loads(m.group(0))
    out: Dict[str, float] = {}
    for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            out[k] = float(data[k])
        except (KeyError, ValueError):
            out[k] = float("nan")
    return out


def loudnorm_filter(measured: Dict[str, float], target_i: float = -14.0, target_tp: float = -1.0,
                    target_lra: float = 11.0) -> str:
    """Second-pass (linear) loudnorm filter string from measure_loudness()."""
    def f(x: float) -> str:
        return "%.2f" % x
    return ("loudnorm=I=%s:TP=%s:LRA=%s:measured_I=%s:measured_TP=%s:measured_LRA=%s:"
            "measured_thresh=%s:offset=%s:linear=true" % (
                target_i, target_tp, target_lra, f(measured["input_i"]), f(measured["input_tp"]),
                f(measured["input_lra"]), f(measured["input_thresh"]), f(measured["target_offset"])))


def audio_levels(path: PathLike) -> Dict[str, Optional[float]]:
    """Integrated loudness (LUFS) and true peak (dBTP) of the first audio stream.

    Uses ffmpeg's ebur128 filter with 4x-oversampled true peak, so it reads a
    few tenths of a dB low on hard-limited material; callers keep a margin
    (TP_MARGIN_DB). Values are None when there is no audio.
    """
    cp = run_ffmpeg(["-nostats", "-i", os.fspath(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                    loglevel="info", overwrite=False, check=False)
    txt = cp.stderr or ""
    summary = txt[txt.rfind("Summary:"):] if "Summary:" in txt else ""

    def grab(pat: str) -> Optional[float]:
        m = re.findall(pat, summary)
        if not m or m[-1] == "-inf":
            return None
        try:
            return float(m[-1])
        except ValueError:
            return None
    return {"integrated_lufs": grab(r"I:\s+(-?[\d.]+|-inf) LUFS"),
            "true_peak_dbtp": grab(r"Peak:\s+(-?[\d.]+|-inf) dBFS")}


def ensure_true_peak(path: PathLike, ceiling: float = -1.0, audio_source: Optional[PathLike] = None,
                     af: Optional[str] = None, bitrate: str = AAC_BITRATE, tolerance: float = 0.1,
                     audio_stream: int = 0) -> Dict[str, Any]:
    """Re-check an AAC file's true peak and repair it in place when over `ceiling`.

    Repairs keep the video stream (copied) and re-encode only the audio from
    `audio_source` (default: the file itself) through `af`, first with the
    other AAC coder (twoloop), then with the fast coder and extra gain reduction. Returns
    {"before", "after", "ceiling", "fixed", "attempts"} (dBTP values).
    """
    p = Path(path)
    before = audio_levels(p).get("true_peak_dbtp")
    rep: Dict[str, Any] = {"before": before, "after": before, "ceiling": ceiling, "fixed": False, "attempts": []}
    if before is None or before <= ceiling + tolerance:
        return rep
    src = Path(audio_source) if audio_source else p
    tmp_src: Optional[Path] = None
    if src.resolve() == p.resolve():
        tmp_src = p.with_name(p.stem + ".tpsrc" + p.suffix)
        shutil.copyfile(str(p), str(tmp_src))
        src = tmp_src
    over = before - ceiling
    try:
        # 1: the other coder at the same level, 2-3: fast coder with extra gain reduction
        for coder, gain in (("twoloop", 0.0), ("fast", over + 0.2), ("fast", over + 0.6)):
            chain = ",".join(x for x in (af, ("volume=%.2fdB" % -gain) if gain else None) if x)
            tmp = p.with_name(p.stem + ".tpfix" + p.suffix)
            args: List[str] = ["-i", os.fspath(p), "-i", os.fspath(src), "-map", "0:v?",
                               "-map", "1:a:%d" % audio_stream, "-c:v", "copy"]
            if chain:
                args += ["-af", chain]
            args += aac_args(bitrate, coder=coder) + ["-map_metadata", "0", "-movflags", "+faststart",
                                                      "-shortest", os.fspath(tmp)]
            run_ffmpeg(args)
            tp = audio_levels(tmp).get("true_peak_dbtp")
            rep["attempts"].append({"gain_db": round(-gain, 2), "coder": coder, "true_peak": tp})
            os.replace(str(tmp), str(p))
            rep["after"] = tp
            if tp is None or tp <= ceiling + tolerance:
                rep["fixed"] = True
                break
    finally:
        if tmp_src is not None:
            try:
                tmp_src.unlink()
            except OSError:
                pass
    if rep["fixed"]:
        debug("true peak %.2f -> %.2f dBTP (ceiling %.1f) in %s" % (before, rep["after"] or -99, ceiling, p.name))
    else:
        from .common import warn
        warn("%s: true peak %.2f dBTP is still above the %.1f dBTP ceiling after re-encoding"
             % (p.name, rep["after"] if rep["after"] is not None else before, ceiling))
    return rep


def is_ffmpeg_error(e: BaseException) -> bool:
    return isinstance(e, RunError)
