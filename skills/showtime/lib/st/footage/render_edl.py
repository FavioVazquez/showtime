"""Render an EDL to a finished video.

Pipeline (each step is cached, so changing one range re-renders one segment):

1. Validate the EDL and plan frame-exact segments (edl.plan).
2. Per range, one ffmpeg extract: accurate seek, HDR -> SDR tonemap (zscale),
   square pixels, frame-rate normalisation, fit to the output size (cover /
   contain / blur-pad / face-tracked reframe, optional punch-in zoom),
   stabilisation, grade, BT.709 conversion; audio resampled to 48 kHz stereo
   (silence for sources without audio), exactly the planned number of
   samples. Cuts get a 20 ms equal-power crossfade (audio.crossfade): the
   incoming segment fades in, and the outgoing source's next 20 ms (its
   "tail", written beside the segment) fades out over it; the first and last
   edges keep 30 ms fades. Segments keep PCM audio, so no AAC
   priming gap appears at cuts.
3. Lossless concat (-c copy) of all segments.
4. Offsets are recomputed from the frame counts actually written.
5. Audio: base + overlay audio, optional music/SFX bed through the audio
   module's mixer (ducked under speech), else two-pass loudnorm.
6. Final pass: overlays (position/scale/opacity/fades, alpha from PNG,
   ProRes 4444 or VP9) then captions LAST, one encode; or a stream copy when
   there is nothing to composite.
7. Verification: duration vs plan, integrated loudness / true peak, a JSON
   report next to the output.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import ff
from .. import platform as plat
from ..common import ShowtimeError, debug, ensure_dir, info, warn, write_json
from . import edl as E
from . import util as U

RENDER_REV = 6
HDR_TRC = ("smpte2084", "arib-std-b67")
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
FADE = 0.03

QUALITY = {
    # name: (preset, crf, audio kbps)
    "final": ("medium", 18, 256),
    "preview": ("veryfast", 26, 128),
    "intermediate": ("veryfast", 12, 0),
}


class Ctx:
    def __init__(self, edl: Dict[str, Any], out: Path, work: Path, preview: bool, shared: Optional[Path] = None):
        self.edl = edl
        self.out = out
        self.work = work                   # per-output intermediates (base, audio, captions)
        self.shared = shared or work       # per-EDL caches reused across outputs (segments, tracks)
        self.preview = preview
        o = edl["output"]
        self.full_w, self.full_h = o["width"], o["height"]
        if preview:
            f = min(1.0, 1280.0 / max(o["width"], o["height"]))
            self.w, self.h = E._even(o["width"] * f), E._even(o["height"] * f)
        else:
            self.w, self.h = o["width"], o["height"]
        self.fps: Fraction = o["fps"]
        self.grade_cache: Dict[str, str] = {}
        self.ground = "black"              # the panel layout's fill (the cards' look ground)
        self.warnings: List[str] = []
        self.lock = threading.Lock()

    def warn(self, msg: str) -> None:
        with self.lock:
            if msg not in self.warnings:
                self.warnings.append(msg)
                warn(msg)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _publish(tmp: Path, out: Path) -> None:
    """Move a finished temp file into place (clear error if the target is open elsewhere,
    e.g. in a video player on Windows)."""
    try:
        os.replace(str(tmp), str(out))
    except PermissionError:
        raise ShowtimeError("cannot write %s: the file is in use (open in a player?)" % out,
                            hint="close it, or render to another name with -o")


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _timescale(fps: Fraction) -> int:
    return fps.numerator * (1000 if fps.denominator == 1 else 1)


def _color_prefix(pr: Dict[str, Any], ctx: Ctx) -> str:
    """Tag untagged sources so every later RGB conversion uses the right matrix."""
    trc = (pr.get("color_transfer") or "").lower()
    if trc in HDR_TRC:
        if ff.has_filter("zscale"):
            return TONEMAP
        ctx.warn("an HDR source was found but this ffmpeg has no zscale filter: colours will look flat")
        return ""
    cs = (pr.get("color_space") or "").lower()
    full = str(pr.get("color_range") or "").lower() in ("pc", "jpeg") or "yuvj" in str(pr.get("pix_fmt") or "")
    unknown = ("", "unknown", "reserved", "none")
    prim_in = (pr.get("color_primaries") or "").lower()
    # a source tagged only partly (matrix known, primaries/transfer unknown, as some encoders write it)
    # is completed too: newer ffmpeg builds carry the frames' "unknown" into the output and ignore
    # -color_primaries/-color_trc, so the final would ship untagged
    if (cs in unknown or prim_in in unknown or trc in unknown) and ff.has_filter("setparams"):
        hd = (pr.get("height") or 0) >= 720 or (pr.get("width") or 0) >= 1280
        space = cs if cs not in unknown else ("bt709" if hd else "smpte170m")
        prim = prim_in if prim_in not in unknown else ("bt709" if hd else "smpte170m")
        tr = trc if trc not in unknown else ("bt709" if hd else "smpte170m")
        return "setparams=colorspace=%s:color_primaries=%s:color_trc=%s:range=%s" % (
            space, prim, tr, "pc" if full else "tv")
    return ""


def _decide_fit(r: Dict[str, Any], pr: Dict[str, Any], ctx: Ctx) -> str:
    fit = r.get("fit") or ctx.edl["output"]["fit"]
    if fit != "auto":
        return fit
    sw, sh = pr.get("display_width") or pr.get("width"), pr.get("display_height") or pr.get("height")
    src_ar, out_ar = sw / float(sh), ctx.w / float(ctx.h)
    if abs(src_ar - out_ar) / out_ar < 0.04:
        return "cover"
    if src_ar < out_ar:            # tall source into a wider frame: never crop heads off
        return "blur"
    from . import reframe as R
    return "reframe" if R.available()[0] else "cover"


# --------------------------------------------------------------------------
# preparation: denoise, stabilise, reframe, grade
# --------------------------------------------------------------------------

def _denoised_audio(key: str, ctx: Ctx) -> Optional[Path]:
    method = ctx.edl["audio"].get("denoise")
    if not method:
        return None
    src = ctx.edl["sources"][key]
    if not src["probe"].get("has_audio"):
        return None
    from . import denoise as D
    d = ensure_dir(ctx.shared / "denoise")
    out = d / ("%s-%s.wav" % (U.quick_hash(src["path"]), method))
    if not out.is_file():
        info("denoising %s (%s)" % (src["path"].name, method))
        try:
            rep = D.denoise(src["path"], out, method=method, audio_only=True, track=src.get("audio_track", 0))
        except ShowtimeError as e:
            ctx.warn("denoise skipped for %s: %s" % (src["path"].name, e))
            return None
        if rep.get("method") != method and method != "auto":
            ctx.warn("denoise: %s unavailable, used %s" % (method, rep.get("method")))
    return out


def _vidstab_detect(seg: Dict[str, Any], pre: str, ctx: Ctx) -> Optional[Path]:
    if not (ff.has_filter("vidstabdetect") and ff.has_filter("vidstabtransform")):
        return None
    src = ctx.edl["sources"][seg["source"]]
    trf = ensure_dir(ctx.shared / "stab") / ("%s.trf" % _hash([U.quick_hash(src["path"]), seg["start"], seg["frames"],
                                                             U.fps_str(ctx.fps), pre]))
    if trf.is_file():
        return trf
    vf = ",".join(x for x in (pre, "vidstabdetect=shakiness=6:accuracy=15:result=%s" % ff.filter_path(trf)) if x)
    ff.run_ffmpeg(["-ss", "%.6f" % seg["start"], "-t", "%.6f" % (seg["frames"] / float(ctx.fps) + 0.2),
                   "-i", str(src["path"]), "-an", "-vf", vf, "-frames:v", str(seg["frames"]), "-f", "null", "-"])
    return trf


def _video_graph(seg: Dict[str, Any], ctx: Ctx) -> Tuple[str, Optional[Path], Dict[str, Any]]:
    """Filtergraph for [0:v] -> [v] plus an optional sendcmd file."""
    src = ctx.edl["sources"][seg["source"]]
    pr = src["probe"]
    W, H = ctx.w, ctx.h
    fps = U.fps_str(ctx.fps)
    pre: List[str] = []
    cp = _color_prefix(pr, ctx)
    if cp:
        pre.append(cp)
    sar = pr.get("sar")
    if sar and sar not in ("1:1", "0:1"):
        pre.append("scale=trunc(iw*sar/2)*2:ih,setsar=1")
    # start_time=0: output frame 0 exists even when the first decoded frame lands a
    # fraction of a frame after the seek point (otherwise the segment starts at 1/fps)
    pre.append("fps=%s:start_time=0" % fps)
    held = int(seg.get("hold_frames") or 0)
    if held:
        # range "hold": the range's own frames, then its last frame frozen (tpad clone in post)
        pre.append("trim=end_frame=%d" % (seg["frames"] - held))
    meta: Dict[str, Any] = {}
    if seg.get("stabilize"):
        trf = _vidstab_detect(seg, ",".join(pre), ctx)
        if trf:
            pre.append("vidstabtransform=input=%s:smoothing=30:zoom=0:optzoom=1:interpol=bicubic,"
                       "unsharp=5:5:0.5:3:3:0.0" % ff.filter_path(trf))
            meta["stabilize"] = "vidstab"
        else:
            from . import stabilize as S
            # strength 0.5 like the vid.stab branch above (smoothing 30); deshake's radius must be a
            # multiple of 16, which a hard-coded rx=24:ry=24 is not (ffmpeg rejects it outright).
            pre.append(S.deshake_filter(0.5))
            meta["stabilize"] = "deshake"
    fit = _decide_fit(seg, pr, ctx)
    meta["fit"] = fit
    sw = pr.get("display_width") or pr.get("width")
    sh = pr.get("display_height") or pr.get("height")
    if sar and sar not in ("1:1", "0:1"):
        try:
            sw = int(round(sw * float(Fraction(sar.replace(":", "/")))))
        except (ValueError, ZeroDivisionError):
            pass
    zoom = float(seg.get("zoom") or 1.0)
    focus = seg.get("focus") if isinstance(seg.get("focus"), dict) else None
    grade = _grade_chain(seg, ctx)
    # after the BT.709 conversion, say so in the frames: the encoder's -color_* options alone are not
    # written when the frames carry other or unknown tags (newer ffmpeg), and qa checks all three
    tag709 = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv" if ff.has_filter("setparams") else ""
    post = [x for x in (grade, "tpad=stop_mode=clone:stop_duration=%g" % max(2.0, held / float(ctx.fps) + 1.0),
                        ff.BT709_VF, tag709, "format=yuv420p") if x]
    cmdfile = None
    bg = ctx.edl["output"].get("background") or "black"
    lay = seg.get("layout")
    if lay:
        # a side panel card covers this range: the speaker is framed (face-tracked) into their half and the
        # rest of the frame is the look's ground, which the panel card paints over (cards.panel_splits)
        from . import reframe as R
        sp = lay["speaker"]
        rw, rh = E._even(sp["w"] * W), E._even(sp["h"] * H)
        rx, ry = min(int(round(sp["x"] * W)), W - rw), min(int(round(sp["y"] * H)), H - rh)
        try:
            plan = R.plan_crop(src["path"], seg["start"], seg["frames"] / float(ctx.fps), sw, sh, rw, rh,
                               float(ctx.fps), seg["frames"], zoom=zoom, focus=focus, track=R.available()[0],
                               announce=False)
        except ShowtimeError as e:
            ctx.warn("panel framing: face tracking failed (%s); using a centre crop" % e)
            plan = R.plan_crop(src["path"], seg["start"], 0, sw, sh, rw, rh, float(ctx.fps), seg["frames"],
                               zoom=zoom, focus=focus, track=False, announce=False)
        (scw, sch), pos = plan["scale"], plan["positions"]
        label = "behind" if lay.get("card") == "behind" else "panel"
        meta.update(faces=plan["faces"], moving=not plan["static"], fit=label,
                    layout=dict(lay, region=[rx, ry, rw, rh]))
        x0, y0 = pos[0] if pos else (0, 0)
        chain = pre + ["scale=%d:%d:flags=lanczos" % (scw, sch)]
        if not plan["static"]:
            cmdfile = ensure_dir(ctx.shared / "reframe") / ("%s.cmd" % _hash([seg, rw, rh, fps, pos[:3], len(pos), "panel"]))
            R.sendcmd_file(cmdfile, pos, float(ctx.fps))
            chain.append("sendcmd=f=%s" % ff.filter_path(cmdfile))
        chain.append("crop@rf=%d:%d:%d:%d" % (rw, rh, x0, y0))
        chain.append("pad=%d:%d:%d:%d:color=%s" % (W, H, rx, ry, ctx.ground))
        graph = "[0:v]" + ",".join(chain + post) + "[v]"
        f = round(max(rw / float(sw), rh / float(sh)) * max(1.0, zoom) * (ctx.full_w / float(W)), 2)
        meta["upscale"] = {"factor": f, "detail": "%dx%d source -> %dx%d speaker %s" % (
            sw, sh, int(rw * ctx.full_w / W), int(rh * ctx.full_h / H),
            "region (behind card)" if label == "behind" else "half (panel)")}
        if f > UPSCALE_WARN and (ctx.edl.get("output") or {}).get("allow_upscale"):
            meta["upscale"]["accepted"] = True          # the user accepted it (qa reports it as a note)
        elif f > UPSCALE_WARN:
            ctx.warn("source '%s' is enlarged %.2fx in the %s layout: it will look soft" % (seg["source"], f, label))
        return graph, cmdfile, meta
    if fit in ("cover", "reframe"):
        from . import reframe as R
        track = (fit == "reframe" or (zoom > 1.001 and focus is None)) and R.available()[0]
        try:
            plan = R.plan_crop(src["path"], seg["start"], seg["frames"] / float(ctx.fps), sw, sh, W, H,
                               float(ctx.fps), seg["frames"], zoom=zoom, focus=focus, track=track,
                               announce=False)  # the upscale note is reported by _upscale_info below
        except ShowtimeError as e:
            ctx.warn("reframe tracking failed (%s); using a centre crop" % e)
            plan = R.plan_crop(src["path"], seg["start"], 0, sw, sh, W, H, float(ctx.fps), seg["frames"],
                               zoom=zoom, focus=focus, track=False, announce=False)
        (scw, sch), pos = plan["scale"], plan["positions"]
        meta.update(faces=plan["faces"], moving=not plan["static"])
        x0, y0 = pos[0] if pos else (0, 0)
        chain = pre + ["scale=%d:%d:flags=lanczos" % (scw, sch)]
        if not plan["static"]:
            cmdfile = ensure_dir(ctx.shared / "reframe") / ("%s.cmd" % _hash([seg, W, H, fps, pos[:3], len(pos)]))
            R.sendcmd_file(cmdfile, pos, float(ctx.fps))
            chain.append("sendcmd=f=%s" % ff.filter_path(cmdfile))
        chain.append("crop@rf=%d:%d:%d:%d" % (W, H, x0, y0))
        graph = "[0:v]" + ",".join(chain + post) + "[v]"
    elif fit == "contain":
        z = "" if zoom <= 1.001 else ",scale=iw*%.4f:ih*%.4f,crop=iw/%.4f:ih/%.4f" % (zoom, zoom, zoom, zoom)
        chain = pre + ["scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos%s" % (W, H, z),
                       "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s" % (W, H, bg)]
        graph = "[0:v]" + ",".join(chain + post) + "[v]"
    elif fit == "blur":
        graph = ("[0:v]%s,split=2[bgs][fgs];"
                 "[bgs]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,scale=iw/8:-2,"
                 "gblur=sigma=6,scale=%d:%d,eq=brightness=-0.06:saturation=0.85[bgb];"
                 "[fgs]scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos[fgo];"
                 "[bgb][fgo]overlay=(W-w)/2:(H-h)/2,%s[v]") % (
            ",".join(pre), W, H, W, H, W, H, W, H, ",".join(post))
    else:
        raise ShowtimeError("unknown fit %r" % fit)
    meta["upscale"] = _upscale_info(seg, fit, sw, sh, zoom, ctx)
    return graph, cmdfile, meta


UPSCALE_WARN = 1.5


def _upscale_info(seg: Dict[str, Any], fit: str, sw: float, sh: float, zoom: float, ctx: Ctx) -> Dict[str, Any]:
    """How much the source is enlarged in the FINAL frame (previews are judged at the final size).
    Warns once per source above 1.5x: enlarged footage looks soft."""
    W, H = ctx.full_w, ctx.full_h
    if not sw or not sh:
        return {"factor": None}
    if fit in ("cover", "reframe"):
        f = max(W / float(sw), H / float(sh)) * max(1.0, zoom)
    elif fit == "contain":
        f = min(W / float(sw), H / float(sh)) * max(1.0, zoom)
    else:  # blur: the foreground is contained
        f = min(W / float(sw), H / float(sh))
    f = round(f, 2)
    info_ = {"factor": f, "detail": "%dx%d source -> %dx%d frame, fit %s%s" % (
        sw, sh, W, H, fit, ", zoom %.2g" % zoom if zoom > 1.001 else "")}
    if f > UPSCALE_WARN:
        if (ctx.edl.get("output") or {}).get("allow_upscale"):
            # the user accepted it (qa reports it as a note)
            info_["accepted"] = True
            return info_
        k = UPSCALE_WARN / f
        sug_w, sug_h = E._even(W * k), E._even(H * k)
        vertical_std = (W, H) == (1080, 1920) and min(sw, sh) < 1280
        if vertical_std:
            # 1080p to 1080x1920 is ~1.8x whatever the crop; a 910x1618 frame is not a platform size
            fix = ('unavoidable at 1080x1920 from a %dp source: 720x1280 is the only standard vertical size at %.1fx or less '
                   '(EDL "output": {"width": 720, "height": 1280}); or accept it with "output": {"allow_upscale": true}'
                   % (min(sw, sh), UPSCALE_WARN))
        else:
            small = 'a smaller frame (EDL "output": {"width": %d, "height": %d} keeps it at %.1fx)' % (
                sug_w, sug_h, UPSCALE_WARN)
            fix = ("render %s, use --fit blur (the whole frame, not cropped), or a sharper source" % small) \
                if fit != "blur" else "render %s or use a sharper source" % small
            fix += '; or accept it with "output": {"allow_upscale": true}'
        info_["fix"] = fix
        ctx.warn("source '%s' is enlarged %.2fx (%s): it will look soft; %s" % (seg["source"], f, info_["detail"], fix))
    return info_


def _grade_chain(seg: Dict[str, Any], ctx: Ctx) -> str:
    from . import grade as G
    spec = seg.get("grade", ctx.edl.get("grade"))
    if spec in (None, "none", False, ""):
        return ""
    src = ctx.edl["sources"][seg["source"]]["path"]
    return G.build_filter(spec, src, seg["start"], seg["frames"] / float(ctx.fps), base_dir=ctx.edl["dir"],
                          cache=ctx.grade_cache)


# --------------------------------------------------------------------------
# segments
# --------------------------------------------------------------------------

def _segment(seg: Dict[str, Any], ctx: Ctx, quality: str, denoised: Dict[str, Optional[Path]]) -> Dict[str, Any]:
    src = ctx.edl["sources"][seg["source"]]
    pr = src["probe"]
    graph, cmdfile, meta = _video_graph(seg, ctx)
    preset, crf, _ = QUALITY[quality]
    n = seg["frames"]
    ns = seg["audio_samples"]
    dur_in = n / float(ctx.fps) + 0.5
    kd = {"rev": RENDER_REV, "src": U.quick_hash(src["path"]), "start": round(seg["start"], 6), "n": n,
          "ns": ns, "graph": graph, "cmd": cmdfile.read_text() if cmdfile else None, "q": quality,
          "den": str(denoised.get(seg["source"])), "vol": seg.get("volume_db"), "mute": seg.get("mute"),
          "track": src.get("audio_track", 0)}
    if seg.get("join_in") or seg.get("join_out"):  # only then, so every other segment keeps its cache key
        kd["joins"] = [bool(seg.get("join_in")), bool(seg.get("join_out"))]
    if seg.get("xf_in") or seg.get("xf_out"):
        kd["xf"] = [seg.get("xf_in") or 0.0, seg.get("xf_out") or 0.0]
    if seg.get("fade_out"):
        kd["fo"] = [float(seg["fade_out"]), "qua"]
    key = _hash(kd)
    out = ensure_dir(ctx.shared / "segments") / ("seg%03d-%s.mov" % (seg["i"], key))
    sidecar = out.with_suffix(".json")
    tail = out.with_name(out.stem + ".tail.wav") if seg.get("xf_out") else None
    if out.is_file() and sidecar.is_file() and (tail is None or tail.is_file()):
        try:
            m = json.loads(sidecar.read_text(encoding="utf-8"))
            return dict(m, meta=dict(m.get("meta") or {}, **meta), path=str(out), cached=True,
                        tail=str(tail) if tail else None)
        except ValueError:
            pass
    args: List[str] = ["-ss", "%.6f" % seg["start"], "-t", "%.6f" % dur_in, "-i", str(src["path"])]
    den = denoised.get(seg["source"])
    track = int(src.get("audio_track", 0))
    if den:
        args += ["-ss", "%.6f" % seg["start"], "-t", "%.6f" % dur_in, "-i", str(den)]
        a_in = "[1:a]"
    elif pr.get("has_audio") and track < len(pr.get("audio_streams") or []):
        a_in = "[0:a:%d]" % track
    else:
        args += ["-f", "lavfi", "-t", "%.6f" % dur_in, "-i", "anullsrc=r=48000:cl=stereo"]
        a_in = "[1:a]"
    fade = min(FADE, ns / 48000.0 / 4.0)
    dur_a = ns / 48000.0
    # a range that continues the same source where its neighbour stopped (a reframe-only split)
    # joins without the edge fade: a fade there would dip continuous sound for ~2 x 30 ms
    fin = 0.0 if seg.get("join_in") else fade
    fout = 0.0 if seg.get("join_out") else fade
    curve_in = "tri"
    if seg.get("xf_in"):
        fin, curve_in = min(float(seg["xf_in"]), dur_a / 4.0), "qsin"   # equal-power half of the crossfade
    if seg.get("xf_out"):
        fout = 0.0                                                      # the tail fades out over the next segment
    curve_out = ""
    if seg.get("fade_out"):
        # range "fade_out": a long fade at its end, quadratic so the last frames are quiet (no abrupt end)
        fout, curve_out = min(float(seg["fade_out"]), dur_a / 2.0), ":curve=qua"
    pre = ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo", "asetpts=PTS-STARTPTS"]
    held = int(seg.get("hold_frames") or 0)
    if held:
        # a held range: the source sound to the range's end (faded out over its last 0.25 s), then silence
        base = (n - held) / float(ctx.fps)
        pre += ["atrim=end_sample=%d" % int(round(base * 48000)),
                "afade=t=out:st=%.4f:d=%.4f" % (max(0.0, base - 0.25), min(0.25, base))]
    if seg.get("mute"):
        pre.append("volume=0")
    elif seg.get("volume_db"):
        pre.append("volume=%.2fdB" % seg["volume_db"])
    pre.append("apad")
    achain = ["atrim=end_sample=%d" % ns]
    if fin:
        achain.append("afade=t=in:st=0:d=%.4f:curve=%s" % (fin, curve_in))
    if fout:
        achain.append("afade=t=out:st=%.6f:d=%.4f%s" % (max(0.0, dur_a - fout), fout, curve_out))
    if tail is not None:
        nt = int(round(float(seg["xf_out"]) * 48000))
        graph_full = (graph + ";" + a_in + ",".join(pre) + ",asplit=2[am][at];[am]" + ",".join(achain) + "[a];"
                      "[at]atrim=start_sample=%d:end_sample=%d,asetpts=PTS-STARTPTS[t]" % (ns, ns + nt))
    else:
        graph_full = graph + ";" + a_in + ",".join(pre + achain) + "[a]"
    tmp = out.with_name(out.stem + ".part.mov")
    # the video stream ends itself after n frames (trim): with -frames:v, ffmpeg closes the file when the last
    # frame is written and drops the audio still queued (up to a frame of it), so the sound drifts ahead of the
    # picture at every such cut
    graph_full = graph_full.replace("[v]", "[vn];[vn]trim=end_frame=%d[v]" % n, 1)
    args += ["-filter_complex", graph_full, "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
             "-g", str(max(1, int(round(float(ctx.fps) * 2)))), "-bf", "2"] + ff.BT709_TAGS + [
             "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-video_track_timescale", str(_timescale(ctx.fps)),
             "-f", "mov", str(tmp)]
    if tail is not None:
        ttmp = tail.with_name(tail.stem + ".part.wav")
        args += ["-map", "[t]", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2", "-f", "wav", str(ttmp)]
    ff.run_ffmpeg(args)
    os.replace(str(tmp), str(out))
    if tail is not None:
        os.replace(str(ttmp), str(tail))
    got = _count_frames(out)
    m = {"i": seg["i"], "frames": got if got else n, "planned": n, "meta": meta}
    sidecar.write_text(json.dumps(m), encoding="utf-8")
    return dict(m, path=str(out), cached=False, tail=str(tail) if tail else None)


def _mark_crossfades(segs: List[Dict[str, Any]], xf: float) -> None:
    """Flag every cut (neighbours that are not a continuous join) for an `xf`-second crossfade (in place)."""
    if xf <= 0:
        return
    for a, b in zip(segs, segs[1:]):
        if a.get("join_out"):
            continue
        a["xf_out"] = b["xf_in"] = round(float(xf), 4)


def _apply_tails(program: Path, segs: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> int:
    """Mix each outgoing tail, faded out with a quarter cosine, over the start of the next segment.

    The incoming segment already fades in with a quarter sine, so the pair is an equal-power
    crossfade centred just after the cut; the program keeps its exact length. Returns tails mixed."""
    import numpy as np
    import soundfile as sf
    if not any(r.get("tail") for r in results):
        return 0
    x, sr = sf.read(str(program), dtype="float32", always_2d=True)
    pos, done = 0, 0
    for s, r in zip(segs, results):
        pos += int(s["audio_samples"])
        tp = r.get("tail")
        if not tp or not Path(tp).is_file() or pos >= len(x):
            continue
        t, _ = sf.read(str(tp), dtype="float32", always_2d=True)
        n = min(len(t), len(x) - pos)
        if n <= 0:
            continue
        ramp = np.cos(np.linspace(0.0, np.pi / 2, n, dtype=np.float32))[:, None]
        ch = min(t.shape[1], x.shape[1])
        x[pos:pos + n, :ch] += t[:n, :ch] * ramp
        done += 1
    sf.write(str(program), x, sr, subtype="FLOAT")
    return done


def _mark_joins(segs: List[Dict[str, Any]], fps: Any) -> None:
    """Flag neighbouring ranges that play one source continuously (the second starts where the first
    ends, within half a frame): typically one take split only to change the framing. Their audio
    joins without the 30 ms edge fades (in place)."""
    tol = 0.5 / float(fps)
    for a, b in zip(segs, segs[1:]):
        if (a["source"] == b["source"] and abs(a["src_end"] - b["start"]) <= tol
                and bool(a.get("mute")) == bool(b.get("mute")) and a.get("volume_db") == b.get("volume_db")):
            a["join_out"] = b["join_in"] = True


def _count_frames(path: Path) -> Optional[int]:
    exe = ff.ffprobe_path()
    if not exe:
        return None
    cp = ff.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                 "-of", "default=nw=1:nk=1", str(path)], check=False)
    try:
        return int((cp.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def _concat(parts: List[str], dst: Path) -> Path:
    lst = dst.with_suffix(".txt")
    lst.write_text("".join("file %s\n" % ff.concat_list_path(p) for p in parts), encoding="utf-8")
    ff.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0:v", "-map", "0:a", "-c", "copy",
                   "-f", "mov", str(dst)])
    return dst


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------

def _premix(base: Path, total: float, ctx: Ctx) -> Path:
    """Program audio (+ overlay audio) as 48 kHz stereo WAV."""
    out = ctx.work / "program.wav"
    ovs = [o for o in ctx.edl["overlays"] if o["audio"]]
    args = ["-i", str(base)]
    parts = ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"]
    for o in ovs:
        if o.get("duck_db") is not None:
            parts[0] += ",volume=enable='between(t,%.3f,%.3f)':volume=%.2fdB" % (
                o["start"], o["start"] + o["duration"], o["duck_db"])
    parts[0] += "[p0]"
    labels = ["[p0]"]
    for k, o in enumerate(ovs, 1):
        args += ["-ss", "%.6f" % o["offset"], "-t", "%.6f" % o["duration"], "-i", str(o["file"])]
        ms = int(round(o["start"] * 1000))
        parts.append("[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=%.2fdB,"
                     "afade=t=in:d=0.03,afade=t=out:st=%.4f:d=0.05,adelay=%d:all=1[p%d]"
                     % (k, o["volume_db"], max(0.0, o["duration"] - 0.05), ms, k))
        labels.append("[p%d]" % k)
    if len(labels) > 1:
        graph = ";".join(parts) + ";" + "".join(labels) + "amix=inputs=%d:normalize=0:duration=first[m]" % len(labels)
    else:
        graph = parts[0].replace("[p0]", "[m]")
    ff.run_ffmpeg(args + ["-filter_complex", graph, "-map", "[m]", "-t", "%.6f" % total, "-c:a", "pcm_f32le",
                          "-ar", "48000", str(out)])
    return out


def _bed_mix(program: Path, words: List[Dict[str, Any]], total: float, ctx: Ctx) -> Tuple[Path, Dict[str, Any]]:
    """Program + music/SFX tracks through the audio module's mixer (mastered)."""
    loud = _internal_target(ctx.edl["loudness"] or {"lufs": -14.0, "tp": -1.0})
    side = program.with_name(program.stem + ".words.json")
    write_json(side, {"words": [{"text": w["text"], "start": w["start"], "end": w["end"], "type": "word"}
                                for w in words if w.get("type", "word") == "word"]})
    spec = {"duration": round(total, 6), "sample_rate": 48000,
            "tracks": [{"kind": "voice", "id": "program", "file": str(program), "level": "raw", "start": 0}]
            + [dict(t) for t in ctx.edl["audio"]["tracks"]],
            "master": {"lufs": loud["lufs"], "true_peak": loud["tp"],
                       **({"engine": "none"} if ctx.edl["loudness"] is None else {})}}
    out = ctx.work / "mix.wav"
    try:
        from ..audio import mix as M
    except Exception as e:  # noqa: BLE001 - audio module optional
        ctx.warn("the audio module is unavailable (%s); mixing the music bed with ffmpeg" % e)
        return _bed_mix_ffmpeg(program, total, ctx), {"engine": "ffmpeg"}
    rep = M.render(spec, out, root=ctx.edl["dir"], report_path=ctx.work / "mix.report.json")
    return out, {"engine": "st.audio.mix", "integrated_lufs": rep.get("integrated_lufs"),
                 "true_peak_dbtp": rep.get("true_peak_dbtp"), "voice_to_music_db": rep.get("voice_to_music_db"),
                 "credits": rep.get("credits"), "credits_file": rep.get("credits_file"), "warnings": rep.get("warnings")}


def _bed_mix_ffmpeg(program: Path, total: float, ctx: Ctx) -> Path:
    """Fallback without the audio module: loop/trim each file track, gain,
    fades, sidechain-duck under the program audio, then amix."""
    out = ctx.work / "mix_ff.wav"
    tracks = [t for t in ctx.edl["audio"]["tracks"] if t.get("file")]
    if len(tracks) < len(ctx.edl["audio"]["tracks"]):
        ctx.warn("synth/compose/library tracks need the audio module; they were skipped")
    ducked = [t for t in tracks if t.get("duck")]
    args = ["-i", str(program)]
    keys = ["[key%d]" % i for i in range(len(ducked))]
    parts = ["[0:a]asplit=%d[prog]%s" % (len(keys) + 1, "".join(keys)) if keys else "[0:a]anull[prog]"]
    labels = ["[prog]"]
    kd = 0
    for k, t in enumerate(tracks, 1):
        args += (["-stream_loop", "-1"] if t.get("loop") else []) + ["-i", t["file"]]
        start = float(t.get("start", t.get("at", 0.0)) or 0.0)
        dur = max(0.05, total - start)
        gain = float(t.get("gain_db", 0.0)) - (0.0 if t.get("level") == "raw" else 18.0)
        chain = "[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:%.4f,volume=%.2fdB" % (
            k, dur, gain)
        if t.get("fade_in"):
            chain += ",afade=t=in:d=%.3f" % float(t["fade_in"])
        if t.get("fade_out"):
            chain += ",afade=t=out:st=%.3f:d=%.3f" % (max(0.0, dur - float(t["fade_out"])), float(t["fade_out"]))
        chain += ",adelay=%d:all=1" % int(round(start * 1000))
        if t.get("duck"):
            parts.append(chain + "[t%d]" % k)
            parts.append("[t%d]%ssidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[d%d]" % (k, keys[kd], k))
            kd += 1
        else:
            parts.append(chain + "[d%d]" % k)
        labels.append("[d%d]" % k)
    graph = ";".join(parts) + ";" + "".join(labels) + "amix=inputs=%d:normalize=0:duration=first[m]" % len(labels)
    ff.run_ffmpeg(args + ["-filter_complex", graph, "-map", "[m]", "-t", "%.6f" % total, "-c:a", "pcm_f32le",
                          "-ar", "48000", str(out)])
    return out


def _internal_target(loud: Dict[str, float]) -> Dict[str, float]:
    """Master 0.5 dB under the true-peak ceiling: the final AAC encode adds
    inter-sample overshoot (typically 0.2-0.4 dB)."""
    return {"lufs": loud["lufs"], "tp": loud["tp"] - 0.5}


def _loudnorm(src: Path, ctx: Ctx) -> Tuple[Path, Dict[str, Any]]:
    """Master the program to the EDL loudness target.

    Prefers the audio module's exact mastering (gain + look-ahead true-peak
    limiter, iterated to +-0.05 LU); falls back to ffmpeg two-pass loudnorm
    (one pass in preview mode)."""
    if not ctx.edl["loudness"]:
        return src, {"engine": "none"}
    loud = _internal_target(ctx.edl["loudness"])
    out = ctx.work / "program_norm.wav"
    try:
        from ..audio import master as AM
        rep = AM.master_file(src, out, lufs=loud["lufs"], tp=loud["tp"], preset="mix", engine="st")
        return out, {"engine": "st.audio.master", "output_lufs": (rep.get("after") or {}).get("integrated_lufs")}
    except ImportError as e:
        debug("audio module unavailable (%s); using ffmpeg loudnorm" % e)
    except ShowtimeError as e:
        ctx.warn("exact mastering failed (%s); using ffmpeg loudnorm" % e)
    if ctx.preview:
        ff.run_ffmpeg(["-i", str(src), "-af", "loudnorm=I=%s:TP=%s:LRA=11,aresample=48000" % (loud["lufs"], loud["tp"]),
                       "-c:a", "pcm_f32le", str(out)])
        return out, {"engine": "loudnorm-1pass"}
    m = ff.measure_loudness(src, loud["lufs"], loud["tp"])
    if not (m.get("input_i") == m.get("input_i")) or m.get("input_i", -99) < -70:
        ctx.warn("the program audio is (nearly) silent; loudness normalisation skipped")
        return src, {"engine": "none", "measured": m}
    af = ff.loudnorm_filter(m, loud["lufs"], loud["tp"]) + ",aresample=48000"
    ff.run_ffmpeg(["-i", str(src), "-af", af, "-c:a", "pcm_f32le", str(out)])
    return out, {"engine": "loudnorm-2pass", "measured_input_i": m.get("input_i")}


# --------------------------------------------------------------------------
# final composite
# --------------------------------------------------------------------------

def _pos(v: Any, full: int) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, dict):
        return str(int(round(v["pct"] * full)))
    return str(int(round(float(v))))


def _overlay_graph(ctx: Ctx, first_input: int) -> Tuple[List[str], List[str], str]:
    """(input args, filter parts, last video label). Overlays composite in list order; a behind card's layers
    (its plate, its word from the card reel, the speaker cut out of the base's own frames with the matte) come
    first, so every other overlay, card and the captions sit on top of the speaker."""
    W, H = ctx.w, ctx.h
    sx, sy = ctx.w / float(ctx.full_w), ctx.h / float(ctx.full_h)
    fps = U.fps_str(ctx.fps)
    args: List[str] = []
    parts: List[str] = []
    cur = "[0:v]"
    ovs = ctx.edl["overlays"]
    taps = sum(1 for o in ovs if o.get("kind") == "person" or (o.get("kind") == "plate" and o.get("plate") == "blur"))
    if taps:
        # the base itself feeds the speaker cut-outs (and a blurred plate): the same frames, so the speaker's
        # pixels are the shot's own
        parts.append("[0:v]split=%d[main]%s" % (taps + 1, "".join("[bb%d]" % i for i in range(taps))))
        cur = "[main]"
    tap = 0
    k = first_input
    for n, o in enumerate(ovs):
        kind = o.get("kind")
        if kind in ("person", "plate"):
            from . import behind as BH
            if kind == "person":
                args += ["-i", str(o["matte"])]
                parts += BH.person_graph(o, "[bb%d]" % tap, k, ctx.fps, "ov%d" % n)
                tap += 1
                k += 1
            else:
                src, img = "", None
                if o["plate"] == "blur":
                    src = "[bb%d]" % tap
                    tap += 1
                elif o["plate"] == "image":
                    args += ["-loop", "1", "-framerate", fps, "-t", "%.6f" % o["duration"], "-i", str(o["file"])]
                    img = k
                    k += 1
                parts.append(BH.plate_graph(o, src, W, H, ctx.fps, img) + "[ov%d]" % n)
            parts.append("%s[ov%d]overlay=x=0:y=0:eof_action=pass:enable='between(t,%.4f,%.4f)'[vo%d]"
                         % (cur, n, o["start"], o["start"] + o["duration"], n))
            cur = "[vo%d]" % n
            continue
        if o["image"]:
            args += ["-loop", "1", "-framerate", fps, "-t", "%.6f" % o["duration"], "-i", str(o["file"])]
        else:
            pr = o["probe"]
            if pr.get("vp_alpha"):
                args += ["-c:v", "libvpx-vp9" if pr.get("vcodec") == "vp9" else "libvpx"]
            args += ["-ss", "%.6f" % o["offset"], "-t", "%.6f" % o["duration"], "-i", str(o["file"])]
        chain = ["fps=%s" % fps, "format=rgba"]
        pos = o["position"].lower()
        margin = int(round((o["margin"] or 0.0) * min(W, H)))
        if pos == "full":
            if o["fit"] == "contain":
                chain.append("scale=%d:%d:force_original_aspect_ratio=decrease" % (W, H))
                xy = ("(W-w)/2", "(H-h)/2")
            else:
                chain.append("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (W, H, W, H))
                xy = ("0", "0")
        else:
            if o["width"] is not None:
                wv = o["width"]["pct"] * W if isinstance(o["width"], dict) else float(o["width"]) * sx
                chain.append("scale=%d:-2" % max(2, int(round(wv / 2) * 2)))
            elif o["height"] is not None:
                hv = o["height"]["pct"] * H if isinstance(o["height"], dict) else float(o["height"]) * sy
                chain.append("scale=-2:%d" % max(2, int(round(hv / 2) * 2)))
            elif o["scale"] is not None:
                chain.append("scale=trunc(iw*%.4f/2)*2:-2" % (o["scale"] * sx))
            else:
                chain.append("scale=%d:-2" % max(2, int(round(0.4 * W / 2) * 2)))
            xs = {"left": str(margin), "right": "W-w-%d" % margin}
            ys = {"top": str(margin), "bottom": "H-h-%d" % margin}
            x, y = "(W-w)/2", "(H-h)/2"
            for part in pos.replace("_", "-").split("-"):
                if part in xs:
                    x = xs[part]
                if part in ys:
                    y = ys[part]
            xy = (_pos(o["x"], W) or x, _pos(o["y"], H) or y)
        if o["opacity"] is not None and o["opacity"] < 0.999:
            chain.append("colorchannelmixer=aa=%.3f" % o["opacity"])
        if o["fade"] > 0:
            f = min(o["fade"], o["duration"] / 2)
            chain.append("fade=t=in:st=0:d=%.3f:alpha=1,fade=t=out:st=%.3f:d=%.3f:alpha=1"
                         % (f, max(0.0, o["duration"] - f), f))
        chain.append("trim=duration=%.6f,setpts=PTS-STARTPTS+%.6f/TB" % (o["duration"], o["start"]))
        parts.append("[%d:v]%s[ov%d]" % (k, ",".join(chain), n))
        parts.append("%s[ov%d]overlay=x=%s:y=%s:eof_action=pass:enable='between(t,%.4f,%.4f)'[vo%d]"
                     % (cur, n, xy[0], xy[1], o["start"], o["start"] + o["duration"], n))
        cur = "[vo%d]" % n
        k += 1
    return args, parts, cur


def _behind_layers(base: Path, cards: List[Dict[str, Any]], entries: List[Dict[str, Any]], reel: Path,
                   plan: List[Dict[str, Any]], segs: List[Dict[str, Any]], results: List[Dict[str, Any]], ctx: Ctx,
                   look: Optional[Dict[str, Any]], work: Path
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """For every behind card: the speaker's matte from the base (cached), what the speaker hides of the word,
    and the card's layers in compositing order (plate, the word's reel overlay, the cut-out speaker).
    Returns (layers, report rows, the other cards' overlays)."""
    from . import behind as BH
    from . import cutout as CO
    plan_by = {p["card"]["index"]: p for p in plan}
    by_card = {e["card"]: e for e in entries}
    wins = BH.windows(cards, ctx.fps)
    cuts = [float(s["out_start"]) for s in segs[1:]]     # the matte starts afresh at every segment boundary
    holder: Dict[str, Any] = {}

    class _Lazy:
        """One pool of model sessions for every card, made only when a matte is not cached."""

        def __getattr__(self, name: str) -> Any:
            if "eng" not in holder:
                holder["eng"] = CO.Engine()
            return getattr(holder["eng"], name)

    layers: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    done = set()
    try:
        for w in wins:
            c = w["card"]
            t0 = time.time()
            st = BH.matte_for(base, w, segs, results, ctx.fps, ctx.w, ctx.h, cuts, work, engine=_Lazy())
            p = plan_by[c["index"]]
            hid = BH.measure_hidden(Path(st["file"]), reel, p["offset_frames"], p["frames"], ctx.fps, ctx.w, ctx.h)
            plate = BH.plate_entry(c, w["f0"], w["f1"], ctx.fps, look, ctx.edl["dir"])
            layers += ([plate] if plate else []) + [by_card[c["index"]]] + [
                BH.person_entry(c, st["file"], w["f0"], w["f1"], ctx.fps)]
            done.add(c["index"])
            rows.append({"i": c["index"], "start": c["start"], "end": c["end"], "text": " ".join(c.get("lines") or []),
                         "plate": c.get("plate"), "moved": bool(c.get("moved")), "frames": st["frames"],
                         "flicker": st.get("flicker"), "flicker_p95": st.get("flicker_p95"),
                         "coverage": st.get("coverage"), "resets": st.get("resets"), "cached": st.get("cached"),
                         "matte_fps": st.get("fps"), "sessions": st.get("sessions"), "matte": st["file"],
                         "seconds": round(time.time() - t0, 2), **hid})
            info("behind card %d: %s, %s %% of the word behind the speaker, matte flicker %.2f %%%s" % (
                c["index"], "matte cached" if st.get("cached") else "matte %d frames at %.1f fps" % (st["frames"], st["fps"]),
                "?" if hid.get("hidden") is None else "%.0f" % (100 * hid["hidden"]), 100 * (st.get("flicker") or 0.0),
                "" if st.get("cached") else " (%d sessions)" % st.get("sessions", 0)))
    finally:
        if "eng" in holder:
            holder["eng"].close()
    return layers, rows, [e for e in entries if e["card"] not in done]


def _final(base: Path, audio: Path, total: float, ctx: Ctx, ass: Optional[Path], fontsdir: Optional[Path],
           out: Path) -> None:
    preset, crf, akbps = QUALITY["preview" if ctx.preview else "final"]
    need_video = bool(ctx.edl["overlays"]) or ass is not None
    args = ["-i", str(base), "-i", str(audio)]
    tmp = out.with_name("." + out.stem + ".part" + out.suffix)
    amap = ["-map", "1:a", "-c:a", "aac", "-aac_coder", "fast", "-b:a", "%dk" % akbps, "-ar", "48000", "-ac", "2"]
    common_tail = ["-t", "%.6f" % total, "-movflags", "+faststart", str(tmp)]
    if not need_video:
        ff.run_ffmpeg(args + ["-map", "0:v", "-c:v", "copy"] + amap + common_tail)
    else:
        in_args, parts, cur = _overlay_graph(ctx, 2)
        if ass is not None:
            sub = "ass=filename=%s" % ff.filter_path(ass)
            if fontsdir:
                sub += ":fontsdir=%s" % ff.filter_path(fontsdir)
            parts.append("%s%s,format=yuv420p[vout]" % (cur, sub))
        else:
            parts.append("%sformat=yuv420p[vout]" % cur)
        graph = ";".join(parts)
        ff.run_ffmpeg(args + in_args + ["-filter_complex", graph, "-map", "[vout]", "-c:v", "libx264",
                                        "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                                        "-profile:v", "high", "-g", str(max(1, int(round(float(ctx.fps) * 2)))),
                                        "-bf", "2"] + ff.BT709_TAGS + amap + common_tail)
    _publish(tmp, out)


def _measure(path: Path) -> Dict[str, Any]:
    try:
        from ..audio import meter
        return meter.ffmpeg_ebur128(path)
    except Exception:  # noqa: BLE001 - audio module optional
        try:
            m = ff.measure_loudness(path)
            return {"integrated_lufs": m.get("input_i"), "true_peak_dbtp": m.get("input_tp")}
        except ShowtimeError:
            return {}


def _reencode_audio(out: Path, audio: Path, total: float, ctx: Ctx, loud: Dict[str, Any], tp: float) -> Dict[str, Any]:
    """Safety net: ffmpeg's native AAC encoder occasionally emits a burst on
    heavily limited material (seen at 192 kb/s with the default coder). The
    mastered WAV is fine, so re-encode just the audio with other settings."""
    for opts in (["-aac_coder", "twoloop", "-b:a", "224k"], ["-aac_coder", "fast", "-b:a", "320k"], ["-b:a", "160k"]):
        tmp = out.with_name("." + out.stem + ".aac" + out.suffix)
        ff.run_ffmpeg(["-i", str(out), "-i", str(audio), "-map", "0:v", "-c:v", "copy", "-map", "1:a", "-c:a", "aac"]
                      + opts + ["-ar", "48000", "-ac", "2", "-t", "%.6f" % total, "-movflags", "+faststart", str(tmp)])
        m = _measure(tmp)
        if m.get("true_peak_dbtp") is not None and m["true_peak_dbtp"] <= tp + 0.5:
            _publish(tmp, out)
            ctx.warn("the AAC encoder overshot (%.1f dBTP); audio re-encoded with %s -> %.1f dBTP"
                     % (loud["true_peak_dbtp"], " ".join(opts), m["true_peak_dbtp"]))
            return m
        try:
            tmp.unlink()
        except OSError:
            pass
    return loud


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def render(edl_path, out=None, *, preview: bool = False, overwrite: bool = False, jobs: Optional[int] = None,
           captions: bool = True, keep_work: bool = True, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    t_start = time.time()
    edl_path = Path(edl_path).expanduser().resolve()
    edl = E.load(edl_path, overrides=overrides)
    segs = E.plan(edl)
    base_dir = edl["dir"]
    if out is None:
        out = base_dir / ("preview.mp4" if preview else "final.mp4")
    out = Path(out).expanduser()
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    if out.suffix.lower() not in (".mp4", ".mov", ".m4v", ".mkv"):
        raise ShowtimeError("output must be .mp4, .mov, .m4v or .mkv (got %s)" % out.name)
    if out.exists() and not overwrite:
        wanted = out
        out = U.unique_path(out)
        info("%s exists; writing %s (renders never overwrite; pass --overwrite to replace it)" % (wanted.name, out.name))
    elif out.exists():
        info("replacing %s (--overwrite)" % out.name)
    ensure_dir(out.parent)
    shared = ensure_dir(base_dir / "work" / edl_path.stem)
    work = ensure_dir(shared / out.stem)
    # captions and cards need transcripts: fail early, before any encode
    transcripts = E.load_transcripts(edl, required=bool(captions and edl["captions"]) or bool(edl.get("cards")))
    cards: List[Dict[str, Any]] = []
    look: Optional[Dict[str, Any]] = None
    avoid_face = (edl["captions"] or {}).get("avoid_face")
    if edl.get("cards") or (captions and ((edl["captions"] or {}).get("emphasis") or avoid_face)):
        from . import cards as CD
        look = CD.look_for(edl, shared / "cards") if edl.get("cards") or (edl["captions"] or {}).get("emphasis") else None
    if edl.get("cards"):
        cards = CD.resolve(edl, segs, E.map_words(segs, transcripts, include_events=False), transcripts, look=look)
        info("cards: %d placed (%s); %s" % (len(cards), ", ".join("%s %.1f-%.1fs%s" % (
            c["type"], c["start"], c["end"], " (split)" if c.get("split") else "") for c in cards if c["type"] != "ground"),
            look["about"]))
        if any(c.get("region") or c.get("speaker") for c in cards):
            edl = dict(edl, ranges=CD.panel_splits(edl["ranges"], segs, cards, edl["output"]["fps"]))
            segs = E.plan(edl)
    elif captions and edl["captions"] and avoid_face:
        edl = dict(edl, caption_plan=CD.caption_plan(edl, segs, edl["output"]["width"], edl["output"]["height"]))
    ctx = Ctx(edl, out, work, preview, shared)
    if look is not None:
        g = str((look.get("tokens") or {}).get("--bg") or "")
        if g.startswith("#") and len(g) == 7:
            ctx.ground = "0x" + g[1:]
    for p_ in E.punch_bounce(segs, edl["output"]["fps"]):
        ctx.warn(p_)
    total_planned = E.total_duration(segs)
    est = total_planned * (0.6 if preview else 2.0) + 3 * len(segs)
    info("rendering %s: %d segment(s), %s at %dx%d %s fps%s" % (
        edl_path.name, len(segs), U.fmt_time(total_planned), ctx.w, ctx.h, U.fps_str(ctx.fps),
        " (preview)" if preview else ""))
    if est > 30:
        info("estimated time: ~%s (cached segments are reused)" % U.fmt_time(est))

    need_composite = bool(edl["overlays"]) or bool(cards) or bool(captions and (edl["captions"] or edl["subtitles"]))
    quality = "intermediate" if need_composite else ("preview" if preview else "final")

    denoised = {k: _denoised_audio(k, ctx) for k in {s["source"] for s in segs}}
    _mark_joins(segs, ctx.fps)
    _mark_crossfades(segs, float(edl["audio"].get("crossfade", 0.02) or 0.0))
    jobs = jobs or max(1, min(3, plat.cpu_count() // 3))
    done = [0]
    t_seg = time.time()
    # the card reel renders (browser capture, cached) while the segments encode
    reel_box: Dict[str, Any] = {}
    reel_thread = None
    if cards:
        lang = (next(iter(transcripts.values())).get("language") or "en") if transcripts else "en"

        def reel_job() -> None:
            try:
                reel_box["reel"], reel_box["plan"] = CD.render_reel(cards, ctx.w, ctx.h, ctx.fps, look, shared / "cards",
                                                                    preview=preview, lang=lang)
            except Exception as e:  # noqa: BLE001 - raised after the segments
                reel_box["error"] = e
        reel_thread = threading.Thread(target=reel_job, daemon=True)
        reel_thread.start()

    def work_one(s: Dict[str, Any]) -> Dict[str, Any]:
        r = _segment(s, ctx, quality, denoised)
        with ctx.lock:
            done[0] += 1
            el = time.time() - t_seg
            eta = el / done[0] * (len(segs) - done[0])
            info("segment %d/%d%s%s" % (done[0], len(segs), " (cached)" if r.get("cached") else "",
                                        ", ETA %s" % U.fmt_time(eta) if len(segs) - done[0] and el > 5 else ""))
        return r

    if jobs > 1 and len(segs) > 1:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(work_one, segs))
    else:
        results = [work_one(s) for s in segs]
    actual = [r["frames"] for r in results]
    for s, r in zip(segs, results):
        if r["frames"] != s["frames"]:
            ctx.warn("segment %d wrote %d frames (planned %d); offsets follow the actual count"
                     % (s["i"], r["frames"], s["frames"]))
    segs = E.retime(segs, ctx.fps, actual)
    total = E.total_duration(segs)

    card_entries: List[Dict[str, Any]] = []
    if reel_thread is not None:
        reel_thread.join()
        if "error" in reel_box:
            raise reel_box["error"]
        card_entries = CD.overlays_for(reel_box["reel"], reel_box["plan"])
    base = _concat([r["path"] for r in results], work / "base.mov")
    behind_layers: List[Dict[str, Any]] = []
    behind_rows: List[Dict[str, Any]] = []
    if any(c["type"] == "behind" for c in cards):
        behind_layers, behind_rows, card_entries = _behind_layers(base, cards, card_entries, reel_box["reel"],
                                                                  reel_box["plan"], segs, results, ctx, look,
                                                                  shared / "cards")
    if card_entries or behind_layers:
        ctx.edl = dict(ctx.edl, overlays=behind_layers + list(ctx.edl["overlays"]) + card_entries)
    words = E.map_words(segs, transcripts, include_events=False) if transcripts else []

    # captions
    ass_path, fontsdir, cap_rep = None, None, None
    if captions and edl["captions"]:
        from . import captions as C
        copts = {k: v for k, v in edl["captions"].items() if k not in ("style", "srt", "vtt")}
        if copts.get("emphasis") and not copts.get("emphasis_color") and look is not None:
            acc = CD.accent_for_captions(look)
            if acc:
                copts["emphasis_color"] = acc
        if cards or edl.get("caption_plan"):
            zones = CD.caption_zones(cards, ctx.w, ctx.h, edl.get("caption_plan"))
            if zones:
                copts["zones"] = zones
        lang = next(iter(transcripts.values())).get("language", "en") if transcripts else "en"
        srt = out.with_suffix(".srt") if edl["captions"].get("srt", True) else None
        cap_rep = C.build(words, work / "captions.ass", style=edl["captions"]["style"], width=ctx.w, height=ctx.h,
                          lang=lang, options=copts, srt=srt, burned_note=False,   # this is the burn itself
                          cuts=E.cut_times(segs, ctx.fps))
        ass_path, fontsdir = Path(cap_rep["ass"]), Path(cap_rep["fontsdir"])
    elif captions and edl["subtitles"]:
        from . import captions as C
        subp = edl["subtitles"]
        if subp.suffix.lower() == ".ass":
            ass_path = subp
            from .fontfiles import find_font, fonts_dir
            fontsdir = fonts_dir([find_font("anton"), find_font("inter"), find_font("instrument-serif")])
        else:
            cap_rep = C.ass_from_subtitles(subp, work / "subtitles.ass", width=ctx.w, height=ctx.h)
            ass_path, fontsdir = Path(cap_rep["ass"]), Path(cap_rep["fontsdir"])

    # audio
    program = _premix(base, total, ctx)
    xfades = _apply_tails(program, segs, results)
    audio_rep: Dict[str, Any]
    if edl["audio"]["tracks"]:
        final_audio, audio_rep = _bed_mix(program, words, total, ctx)
        if audio_rep.get("engine") == "ffmpeg":
            final_audio, lr = _loudnorm(final_audio, ctx)
            audio_rep.update(lr)
    else:
        final_audio, audio_rep = _loudnorm(program, ctx)

    info("final encode%s" % (" (overlays/captions)" if need_composite else " (stream copy)"))
    _final(base, final_audio, total, ctx, ass_path, fontsdir, out)

    # verification
    pr = ff.probe(out)
    vdur = None
    try:
        exe = ff.ffprobe_path()
        if exe:
            cp = ff.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames,duration",
                         "-of", "json", str(out)], check=False)
            st = (json.loads(cp.stdout or "{}").get("streams") or [{}])[0]
            vdur = float(st.get("duration")) if st.get("duration") else None
            frames_out = int(st["nb_frames"]) if st.get("nb_frames") else None
        else:
            frames_out = None
    except (ValueError, KeyError):
        frames_out = None
    loud = _measure(out) if pr.get("has_audio") else {}
    if loud and edl["loudness"] and loud.get("true_peak_dbtp") is not None \
            and loud["true_peak_dbtp"] > edl["loudness"]["tp"] + 1.0:
        loud = _reencode_audio(out, final_audio, total, ctx, loud, edl["loudness"]["tp"])
    expected_frames = sum(actual)
    report = {
        "output": str(out), "edl": str(edl_path), "preview": preview, "width": ctx.w, "height": ctx.h,
        "fps": U.fps_str(ctx.fps), "duration": round(total, 4), "container_duration": pr.get("duration"),
        "video_duration": vdur, "frames": frames_out, "expected_frames": expected_frames,
        "frames_ok": frames_out is None or abs(frames_out - expected_frames) <= 1,
        "segments": E.summary(edl, segs)["segments"],
        "segment_meta": [r.get("meta") for r in results], "cached_segments": sum(1 for r in results if r.get("cached")),
        "captions": cap_rep, "audio": dict(audio_rep, crossfades=xfades,
                                           speech_stem=str(program) if edl["audio"]["tracks"] else None),
        "loudness": loud, "warnings": ctx.warnings,
        # what the program was mastered to (qa judges the render against it); "source" = level kept as asked
        "loudness_target": ({"mode": "master", "lufs": edl["loudness"]["lufs"], "tp": edl["loudness"]["tp"]}
                            if edl["loudness"] else {"mode": "source"}),
        "work": str(work), "seconds": round(time.time() - t_start, 1),
    }
    if cards:
        cprob = CD.problems(cards, edl, measured={r["i"]: r for r in behind_rows})
        for p_ in cprob:
            ctx.warn("cards: " + p_)
        if behind_rows:
            from . import behind as BH
            BH.record(shared / "cards", behind_rows, out, preview)
        report["cards"] = {"look": look["about"] if look else None, "reel": str(reel_box.get("reel")),
                           "items": CD.summary_rows(cards), "problems": cprob,
                           **({"behind": behind_rows} if behind_rows else {}),
                           "caption_band": CD.caption_band(edl["captions"], ctx.full_w, ctx.full_h) if edl["captions"] else None,
                           "caption_moves": len((edl.get("caption_plan") or {}).get("zones") or [])}
    elif edl.get("caption_plan"):
        cprob = [p["message"] for p in edl["caption_plan"].get("problems") or []]
        for p_ in cprob:
            ctx.warn(p_)
        report["caption_face"] = {"problems": cprob, "caption_moves": len(edl["caption_plan"].get("zones") or [])}
    if loud and edl["loudness"]:
        li, tp = loud.get("integrated_lufs"), loud.get("true_peak_dbtp")
        if li is not None and abs(li - edl["loudness"]["lufs"]) > 1.0:
            ctx.warn("final loudness %.1f LUFS differs from the %.1f target" % (li, edl["loudness"]["lufs"]))
        if tp is not None and tp > edl["loudness"]["tp"] + 0.5:
            ctx.warn("final true peak %.1f dBTP is above the %.1f ceiling" % (tp, edl["loudness"]["tp"]))
    if not report["frames_ok"]:
        ctx.warn("output has %s frames, expected %d" % (frames_out, expected_frames))
    rp = out.with_name(out.stem + ".report.json")
    write_json(rp, report)
    report["report"] = str(rp)
    if not keep_work:
        shutil.rmtree(shared / "segments", ignore_errors=True)
    info("wrote %s (%s, %d cut(s)%s) in %.1fs" % (out, U.fmt_time(total), len(E.cut_times(segs, ctx.fps)),
                                                   (", %.1f LUFS" % loud["integrated_lufs"]) if loud.get("integrated_lufs") is not None else "",
                                                   time.time() - t_start))
    return report
