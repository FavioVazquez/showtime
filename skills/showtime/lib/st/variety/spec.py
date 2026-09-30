"""The reference as numbers: a SPEC to keep, and `showtime reference diff` against a render.

`showtime reference` measures the reference; this module turns those measurements into a SPEC in frames
(reference.json "spec", the "Spec" section of reference.md) and compares a render with it on the same
measurements:

  cuts      every scene change with its frame and kind (cut, wipe with panel colour and direction, fast,
            move), the shot lengths in frames
  moves     element moves inside the shots, from the frame-difference curve: start frame, length in
            frames and easing (share of the move's change done by its middle: > 0.62 ease-out, < 0.38
            ease-in, else even / in-out)
  palette   ground, ink and accent sampled from the frames; flat or not
  layout    alignment, side margin and type sizes (the ink height of each line of type)
  sound     tempo, the beat grid, every sound hit (onset) with its frame and band, the build (kick on the
            beats, off-beat tick, last hit, silence at the end)

KEEP is what a same-style video keeps (timing, cuts, easing, beat, hits, layout, type sizes, palette unless a
brand kit or the user says otherwise); CHANGE is what it never keeps (words, subject and facts, logos,
pictures and footage, the music track). `diff` reports each KEEP item as ok or off, with frame numbers.
When the render and the reference differ in length, reference times are scaled to the render's length.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CUT_OK_FRAMES = 3          # a change within this many frames lines up
CUT_NEAR_FRAMES = 15       # beyond this it is missing (and a render change is extra)
MOVE_NEAR_FRAMES = 10
HIT_OK_S = 0.07            # a sound hit within 70 ms (2 frames at 30 fps) lines up
COLOUR_OK = 14             # max channel difference for "the same colour"
MARGIN_OK_PX = 40          # at 1920
TYPE_OK = 0.2              # relative difference of a type size


# ------------------------------------------------------------------ moves inside shots

def find_moves(mad: Sequence[float], fps: float, changes: Sequence[Dict[str, Any]], limit: int = 60
               ) -> List[Dict[str, Any]]:
    """Element moves: runs of 3-60 frames whose frame difference (smoothed over 3) is above max(0.8, 3x the
    video's median: its noise floor), away from scene changes (+-3 frames, and a wipe's length). Easing from
    the cumulative change at the move's middle."""
    import numpy as np
    m = np.asarray(mad, float)
    n = len(m)
    if n < 8 or not fps:
        return []
    sm = np.convolve(m, np.ones(3) / 3.0, mode="same")
    thr = max(0.8, 3.0 * float(np.median(sm)))
    block = np.zeros(n, bool)
    for c in changes:
        f0 = int(round(float(c["t"]) * fps))
        span = int(round(float(c.get("seconds") or 0) * fps / 2.0)) + 3
        block[max(0, f0 - span):min(n, f0 + span + 1)] = True
    hot = (sm > thr) & ~block
    out: List[Dict[str, Any]] = []
    i = 0
    while i < n and len(out) < limit:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        if 3 <= j - i <= 60:
            seg = m[i:j]
            cum = np.cumsum(seg) / (float(seg.sum()) or 1.0)
            half = float(cum[len(cum) // 2 - (1 if len(cum) % 2 == 0 else 0)])
            ease = "ease-out" if half > 0.62 else "ease-in" if half < 0.38 else "even"
            out.append({"t": round(i / fps, 3), "frame": i, "frames": j - i, "ease": ease,
                        "done_at_half": round(half, 2), "peak": round(float(seg.max()), 1)})
        i = j
    return out


# ------------------------------------------------------------------ the spec

def build(rep: Dict[str, Any]) -> Dict[str, Any]:
    fps = float(rep.get("fps") or 30.0)
    fr = lambda t: int(round(float(t) * fps))  # noqa: E731
    snd = rep.get("sound") or {}
    spec: Dict[str, Any] = {
        "fps": fps, "duration": rep.get("analysed_seconds"), "frames": fr(rep.get("analysed_seconds") or 0),
        "changes": [dict({k: v for k, v in c.items() if k in ("kind", "panel", "dir", "seconds")},
                         t=c["t"], frame=fr(c["t"])) for c in rep.get("scene_changes") or []],
        "shots": [{"i": s["i"], "frame": fr(s["start"]), "frames": max(1, fr(s["dur"])), "palette": [
            c["hex"] for c in s.get("palette") or []][:3], "motion": s.get("motion_label")} for s in rep.get("shots") or []],
        "moves": rep.get("moves") or [],
        "palette": rep.get("palette_roles") or {},
        "layout": {k: v for k, v in (rep.get("layout") or {}).items() if k in ("align", "margin_x", "margin_px_1920", "sizes", "top")},
        "sound": {k: v for k, v in snd.items() if k in ("bpm", "lufs", "silence_share", "cuts_on_beat", "shape")},
    }
    if snd.get("hits"):
        spec["sound"]["hits"] = [{"t": h["t"], "frame": fr(h["t"]), "band": h.get("band")} for h in snd["hits"]]
    if snd.get("beats"):
        spec["sound"]["beats"] = snd["beats"]
    return spec


def _fmt(t: float) -> str:
    t = max(0.0, float(t))
    return "%d:%04.1f" % (int(t // 60), t % 60)


def markdown(spec: Dict[str, Any]) -> List[str]:
    """The Spec section of reference.md: KEEP (numbers, in frames) and CHANGE."""
    fps = spec.get("fps") or 30
    ch = spec.get("changes") or []
    L = ["## Spec (the numbers a same-style video keeps)", "",
         "Frames at %g fps; %d frames in all. `showtime reference diff <job>` measures a render the same way and "
         "reports every KEEP item as ok or off, with frame numbers." % (fps, spec.get("frames") or 0), "",
         "**KEEP:**", ""]
    if ch:
        L.append("- Changes (frame kind): " + ", ".join(
            "f%d %s%s" % (c["frame"], c["kind"], " %s %s" % (c.get("panel"), c.get("dir")) if c["kind"] == "wipe" else "")
            for c in ch[:40]) + (" ..." if len(ch) > 40 else ""))
    shots = spec.get("shots") or []
    if shots:
        L.append("- Shot lengths (frames): " + " / ".join(str(s["frames"]) for s in shots[:40]) + (" ..." if len(shots) > 40 else ""))
    mv = spec.get("moves") or []
    if mv:
        L.append("- Element moves (start frame, length, easing): " + ", ".join(
            "f%d %df %s" % (m["frame"], m["frames"], m["ease"]) for m in mv[:24]) + (" ..." if len(mv) > 24 else ""))
    snd = spec.get("sound") or {}
    if snd.get("bpm"):
        hits = snd.get("hits") or []
        L.append("- Beat: %g BPM (a beat every %d frames); %d sound hits, first ones at %s" % (
            round(float(snd["bpm"])), int(round(60.0 / float(snd["bpm"]) * fps)), len(hits),
            ", ".join("f%d" % h["frame"] for h in hits[:12]) + (" ..." if len(hits) > 12 else "")))
    pal = spec.get("palette") or {}
    if pal:
        L.append("- Palette: %s%s (unless a brand kit or the user sets the colours)" % (
            ", ".join("%s %s" % (k, pal[k]) for k in ("ground", "ink", "accent") if pal.get(k)), ", flat" if pal.get("flat") else ""))
    lay = spec.get("layout") or {}
    if lay:
        L.append("- Layout: %s, margin %d px at 1920, type sizes %s px at 1080" % (
            lay.get("align"), lay.get("margin_px_1920") or 0, " / ".join(str(x["px_1080"]) for x in lay.get("sizes") or [])))
    L += ["", "**CHANGE:** the words and subject (the user's facts), logos, pictures and footage, and the music "
          "track (a new one with the same beat and hits). Scale the frame numbers when your video is another "
          "length.", ""]
    return L


# ------------------------------------------------------------------ diff

def _map(t: float, ratio: float) -> float:
    return float(t) * ratio


def _hexd(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    a, b = a.lstrip("#"), b.lstrip("#")
    return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (0, 2, 4))


def diff(ref: Dict[str, Any], got: Dict[str, Any]) -> Dict[str, Any]:
    """Compare a render's spec (`got`) with the reference's (`ref`). -> {ratio, items: [{what, ok, text}]}."""
    fps = float(got.get("fps") or 30.0)
    rd, gd = float(ref.get("duration") or 0), float(got.get("duration") or 0)
    ratio = gd / rd if rd and abs(gd - rd) > 0.5 else 1.0
    fr = lambda t: int(round(float(t) * fps))  # noqa: E731
    items: List[Dict[str, Any]] = []

    def item(what: str, ok: bool, text: str, **extra: Any) -> None:
        items.append(dict({"what": what, "ok": bool(ok), "text": text}, **extra))

    item("length", True,
         "%d vs %d frames%s" % (fr(gd), fr(rd), " (reference times scaled x%.3f)" % ratio if ratio != 1.0 else ""))
    # cuts and wipes
    rch = [dict(c, tm=_map(c["t"], ratio)) for c in ref.get("changes") or []]
    gch = list(got.get("changes") or [])
    used: set = set()
    missing, late, kind_off = [], [], []
    for c in rch:
        best = min(((abs(g["t"] - c["tm"]), k) for k, g in enumerate(gch) if k not in used), default=None)
        if best is None or best[0] * fps > CUT_NEAR_FRAMES:
            missing.append(c)
            continue
        k = best[1]
        used.add(k)
        off = int(round((gch[k]["t"] - c["tm"]) * fps))
        if abs(off) > CUT_OK_FRAMES:
            late.append((c, off))
        if gch[k]["kind"] != c["kind"] and "wipe" in (gch[k]["kind"], c["kind"]):
            kind_off.append((c, gch[k]["kind"]))
    extra = [g for k, g in enumerate(gch) if k not in used]
    lined = len(rch) - len(missing) - len(late)
    parts = ["%d of %d reference changes within %d frames" % (lined, len(rch), CUT_OK_FRAMES)]
    if missing:
        parts.append("missing: " + ", ".join("%s at f%d" % (c["kind"], fr(c["tm"])) for c in missing[:8]))
    if late:
        parts.append("off: " + ", ".join("f%d %+d frames" % (fr(c["tm"]), o) for c, o in late[:8]))
    if kind_off:
        parts.append("kind: " + ", ".join("f%d %s not %s" % (fr(c["tm"]), g, c["kind"]) for c, g in kind_off[:6]))
    if extra:
        parts.append("extra: " + ", ".join("%s at f%d" % (g["kind"], fr(g["t"])) for g in extra[:8]))
    item("cuts", not missing and not late and not kind_off and len(extra) <= max(1, len(rch) // 5), "; ".join(parts),
         missing=[fr(c["tm"]) for c in missing], extra=[fr(g["t"]) for g in extra], off=[[fr(c["tm"]), o] for c, o in late])
    # shots
    rs, gs = ref.get("shots") or [], got.get("shots") or []
    if rs and gs:
        import statistics
        rm = statistics.median([s["frames"] for s in rs]) * ratio
        gm = statistics.median([s["frames"] for s in gs])
        item("shots", abs(len(rs) - len(gs)) <= max(1, len(rs) // 6) and abs(gm - rm) <= max(3, 0.2 * rm),
             "%d vs %d shots, median %d vs %d frames" % (len(gs), len(rs), gm, rm))
    # moves
    rmv, gmv = ref.get("moves") or [], got.get("moves") or []
    if rmv:
        hit, ease_off, len_off = 0, [], []
        for m in rmv:
            tm = _map(m["t"], ratio)
            g = min(gmv, key=lambda x: abs(x["t"] - tm), default=None)
            if g is None or abs(g["t"] - tm) * fps > MOVE_NEAR_FRAMES:
                continue
            hit += 1
            if g["ease"] != m["ease"]:
                ease_off.append("f%d %s not %s" % (fr(tm), g["ease"], m["ease"]))
            if abs(g["frames"] - m["frames"]) > max(2, 0.3 * m["frames"]):
                len_off.append("f%d %d not %d frames" % (fr(tm), g["frames"], m["frames"]))
        txt = "%d of %d reference moves found within %d frames" % (hit, len(rmv), MOVE_NEAR_FRAMES)
        if ease_off:
            txt += "; easing: " + ", ".join(ease_off[:6])
        if len_off:
            txt += "; length: " + ", ".join(len_off[:6])
        item("moves", hit >= 0.6 * len(rmv) and len(ease_off) <= 0.3 * max(1, hit), txt)
    # palette
    rp, gp = ref.get("palette") or {}, got.get("palette") or {}
    if rp:
        rows, ok = [], True
        for k in ("ground", "ink", "accent"):
            if not rp.get(k):
                continue
            d = _hexd(rp.get(k), gp.get(k))
            ok = ok and d is not None and d <= COLOUR_OK
            rows.append("%s %s vs %s%s" % (k, gp.get(k) or "none", rp[k], "" if d is not None and d <= COLOUR_OK else " (off)"))
        if rp.get("flat") and not gp.get("flat"):
            ok = False
            rows.append("not flat (the reference is)")
        item("palette", ok, "; ".join(rows))
    # layout
    rl, gl = ref.get("layout") or {}, got.get("layout") or {}
    if rl:
        rows, ok = [], True
        if gl.get("align") != rl.get("align"):
            ok = False
        rows.append("%s vs %s" % (gl.get("align") or "?", rl.get("align")))
        if rl.get("align") != "centre" and gl:
            dm = abs((gl.get("margin_px_1920") or 0) - (rl.get("margin_px_1920") or 0))
            ok = ok and dm <= MARGIN_OK_PX
            rows.append("margin %d vs %d px" % (gl.get("margin_px_1920") or 0, rl.get("margin_px_1920") or 0))
        rsz = [x["px_1080"] for x in rl.get("sizes") or []]
        gsz = [x["px_1080"] for x in gl.get("sizes") or []]
        if rsz and gsz:
            small_r, small_g = min(rsz), min(gsz)
            if small_g < small_r * (1 - TYPE_OK):
                ok = False
                rows.append("smallest type %d px under the reference's %d" % (small_g, small_r))
            rows.append("type %s vs %s px" % ("/".join(map(str, gsz)), "/".join(map(str, rsz))))
        item("layout", ok, ", ".join(rows))
    # sound
    rsd, gsd = ref.get("sound") or {}, got.get("sound") or {}
    if rsd.get("bpm"):
        rows, ok = [], True
        if gsd.get("bpm"):
            dbpm = abs(float(gsd["bpm"]) - float(rsd["bpm"]) * (1.0 / ratio))
            ok = dbpm <= 3
            rows.append("%g vs %g BPM" % (round(float(gsd["bpm"])), round(float(rsd["bpm"]) / ratio)))
        else:
            ok = False
            rows.append("no steady beat (the reference has %g BPM)" % round(float(rsd["bpm"])))
        rh, gh = rsd.get("hits") or [], gsd.get("hits") or []
        if rh:
            gt = [h["t"] for h in gh]
            miss = [h for h in rh if not gt or min(abs(x - _map(h["t"], ratio)) for x in gt) > HIT_OK_S]
            share = 1 - len(miss) / float(len(rh))
            ok = ok and share >= 0.7
            rows.append("%d%% of %d hits within 2 frames%s" % (round(100 * share), len(rh),
                        " (missing f%s)" % ", f".join(str(fr(_map(h["t"], ratio))) for h in miss[:8]) if miss else ""))
        rs_, gs_ = rsd.get("shape") or {}, gsd.get("shape") or {}
        if rs_.get("kick_on_beats") is not None:
            ko = gs_.get("kick_on_beats") or 0
            if rs_["kick_on_beats"] >= 0.6 and ko < 0.6:
                ok = False
            rows.append("kick on beats %d%% vs %d%%" % (round(100 * ko), round(100 * rs_["kick_on_beats"])))
        if rs_.get("tail_silence_s"):
            rows.append("silence at the end %g vs %g s" % (gs_.get("tail_silence_s") or 0, rs_["tail_silence_s"]))
        item("sound", ok, "; ".join(rows))
    return {"ratio": ratio, "items": items, "ok": all(i["ok"] for i in items)}


def diff_text(res: Dict[str, Any], render: str, ref_title: str) -> str:
    lines = ["reference diff: %s vs \"%s\" (KEEP items; CHANGE items are yours by design)" % (render, ref_title)]
    for it in res["items"]:
        lines.append("  %-4s %-8s %s" % ("ok" if it["ok"] else "OFF", it["what"], it["text"]))
    lines.append("  %s" % ("all KEEP items line up" if res["ok"] else
                           "fix the OFF lines where the style should match; a deliberate change is fine, say why"))
    return "\n".join(lines)
