"""Music-led cut plan: pick the excerpt of a produced track that fits a short film, and put the
scene changes on its phrase starts, with the biggest swell landing on the end card.

A launch, promo or trailer with a real recording under it feels edited *to* the music when (1) the
excerpt starts calm and has somewhere to go, (2) every scene change sits on a phrase start (a
4-bar boundary, where the harmony and the arrangement move) and (3) the track's lift arrives with
the name. This module does that from a `showtime.beats/1` analysis (st.audio.beats):

  bars     every 4th beat, the bar phase voted by the analysed downbeats (their spacing jitters;
           the beat grid does not)
  phrases  every 4th bar (2 when bars are long), the phrase phase chosen so the track's lifts sit on
           phrase starts
  lifts    points where the level rises >= 2.5 dB within ~2 s (a new section, an entry, a swell)
  window   [offset, offset + dur] scored for: a lift where the end card starts, dynamics (quiet
           before loud), a start that is neither silent nor the loudest moment, no dropouts, and
           an end on a phrase boundary
  cuts     one per scene change, on phrase starts (else bar starts) nearest the scene grammar's
           targets (hook ~16 %, even feature beats, end card from the lift)

For music without a reliable pulse (`pacing: phrase_flow`) the cuts go on lifts and energy changes.
The result is advice plus the numbers `showtime retime --cuts` and a mix track need; `apply()`
writes both into a project.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..common import ShowtimeError, home, log, read_json, warn, write_json

SCHEMA = "showtime.cutplan/1"


# ------------------------------------------------------------------------------------------ analysis
def analysis_for(path: Path) -> Dict[str, Any]:
    """The beats analysis of a track, cached by content (never written next to the user's file)."""
    import hashlib
    p = Path(path)
    st = p.stat()
    key = hashlib.sha1(("%s|%d|%d" % (p.resolve(), st.st_size, int(st.st_mtime))).encode("utf-8")).hexdigest()[:16]
    side = p.with_name(p.name + ".beats.json")          # a catalog track's own sidecar (st.audio.music)
    for c in (side, home() / "cache" / "beats" / (key + ".json")):
        if c.is_file():
            try:
                d = read_json(c)
                if d.get("schema") == "showtime.beats/1" and d.get("energy"):
                    return d
            except ShowtimeError:
                pass
    from . import beats
    log("analysing %s (beats, phrases, loudness; once per track)" % p.name)
    d = beats.analyze(p)
    try:
        write_json(home() / "cache" / "beats" / (key + ".json"), d, indent=None)
    except OSError:
        pass
    return d


def loudness_db(an: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """(times, level dB relative to the track's loudest 0.5 s), smoothed over ~1.5 s."""
    en = an.get("energy") or {}
    hop = float(en.get("hop") or 0.5)
    v = np.maximum(np.asarray(en.get("values") or [0.0], dtype=float), 1e-4)
    L = 20 * np.log10(v)
    k = max(1, int(round(1.5 / hop)))
    Ls = np.convolve(L, np.ones(k) / k, mode="same") if len(L) > k else L
    t = (np.arange(len(L)) + 0.5) * hop
    return t, Ls


def level_at(t: np.ndarray, L: np.ndarray, a: float, b: float) -> float:
    m = (t >= a) & (t < b)
    return float(L[m].mean()) if m.any() else float(L[np.argmin(np.abs(t - a))])


def lifts(an: Dict[str, Any], min_db: float = 2.5) -> List[Dict[str, float]]:
    """Moments where the level steps up: mean over the next 2 s vs the 3 s before, local maxima only."""
    t, L = loudness_db(an)
    if len(t) < 8:
        return []
    hop = float(t[1] - t[0])
    rise = np.zeros(len(t))
    for i in range(len(t)):
        a = level_at(t, L, t[i], t[i] + 2.0)
        b = level_at(t, L, t[i] - 3.0, t[i] - 0.25)
        rise[i] = a - b
    out = []
    w = max(1, int(round(2.0 / hop)))
    for i in range(len(t)):
        if rise[i] >= min_db and rise[i] == rise[max(0, i - w):i + w + 1].max():
            out.append({"t": round(float(t[i] - hop / 2), 3), "db": round(float(rise[i]), 2)})
    return out


def bar_grid(an: Dict[str, Any]) -> Optional[np.ndarray]:
    """Bar starts: every 4th tracked beat, the phase voted by the analysed downbeats per 32-beat block."""
    b = np.asarray(an.get("beats") or [], dtype=float)
    if len(b) < 16 or not an.get("bpm") or float(an.get("bpm_confidence") or 0) < 0.3:
        return None
    db = np.asarray(an.get("downbeats") or [], dtype=float)
    idx = np.searchsorted(b, db)
    idx = np.clip(idx, 0, len(b) - 1)
    near = np.where(np.abs(b[np.clip(idx - 1, 0, len(b) - 1)] - db) < np.abs(b[idx] - db), idx - 1, idx)
    phases = near % 4
    bars: List[float] = []
    block = 32
    for s in range(0, len(b), block):
        inb = (near >= s - 8) & (near < s + block + 8)
        ph = int(np.bincount(phases[inb], minlength=4).argmax()) if inb.any() else (bars and 0) or 0
        for i in range(s, min(len(b), s + block)):
            if i % 4 == ph:
                bars.append(float(b[i]))
    return np.asarray(sorted(set(round(x, 4) for x in bars)))


def phrase_grid(an: Dict[str, Any], bars: np.ndarray, lift_list: Sequence[Dict[str, float]]) -> Tuple[np.ndarray, int]:
    """Phrase starts (every n bars, n = 4, or 2 when a bar is longer than 3 s) whose phase puts the
    track's lifts on phrase starts."""
    bar = float(np.median(np.diff(bars))) if len(bars) > 2 else 2.0
    n = 2 if bar > 3.0 else 4
    best, best_score = 0, -1e9
    for ph in range(n):
        starts = bars[ph::n]
        score = 0.0
        for lf in lift_list:
            d = float(np.min(np.abs(starts - lf["t"]))) if len(starts) else 99
            score += lf["db"] * max(0.0, 1.0 - d / (0.5 * bar))
        if score > best_score:
            best, best_score = ph, score
    return bars[best::n], n


# ------------------------------------------------------------------------------------------ the plan
def targets(dur: float, scenes: int, end_card: float, hook: Optional[float] = None) -> List[float]:
    """Scene-change targets for the launch grammar: a hook of ~16 % (3.5-6 s), even middle scenes,
    the end card for the last `end_card` seconds."""
    if scenes <= 1:
        return []
    h = hook if hook else min(6.0, max(3.5, 0.16 * dur))
    e = dur - end_card
    if scenes == 2:
        return [e]
    mids = scenes - 2
    step = (e - h) / mids
    return [h + i * step for i in range(mids)] + [e]


def _choose(cands: List[Tuple[float, float]], tg: List[float], dur: float, min_len: float, hook_min: float) -> List[float]:
    """Pick one candidate per target, increasing, each scene >= min_len: DP over (time, penalty)."""
    n = len(tg)
    C = sorted(cands)
    INF = 1e18
    if not n:
        return []
    cost = [[INF] * len(C) for _ in range(n)]
    back = [[-1] * len(C) for _ in range(n)]
    for j, (c, pen) in enumerate(C):
        if c >= hook_min:
            cost[0][j] = abs(c - tg[0]) + pen
    for i in range(1, n):
        for j, (c, pen) in enumerate(C):
            best, arg = INF, -1
            for k2 in range(j):
                if cost[i - 1][k2] < INF and c - C[k2][0] >= min_len and cost[i - 1][k2] < best:
                    best, arg = cost[i - 1][k2], k2
            if arg >= 0:
                w = 1.6 if i == n - 1 else 0.5          # the end card start matters most; middle beats flex
                cost[i][j] = best + w * abs(c - tg[i]) + pen
                back[i][j] = arg
    last = [(cost[n - 1][j], j) for j in range(len(C)) if cost[n - 1][j] < INF and dur - C[j][0] >= min_len]
    if not last:
        return []
    j = min(last)[1]
    out = []
    for i in range(n - 1, -1, -1):
        out.append(C[j][0])
        j = back[i][j]
    return sorted(out)


def plan(an: Dict[str, Any], dur: float, scenes: int = 5, *, end_card: Optional[float] = None,
         offset: Optional[float] = None, hook: Optional[float] = None, min_scene: float = 2.8) -> Dict[str, Any]:
    """The excerpt and the cuts (see the module doc). `offset` fixes the excerpt start."""
    if dur <= 3:
        raise ShowtimeError("the film must be longer than 3 s (got %g)" % dur)
    track_dur = float(an.get("duration") or 0)
    if track_dur < dur:
        raise ShowtimeError("the track is %.1fs, shorter than the %gs film" % (track_dur, dur),
                            hint="pick a longer track (`showtime audio music pick --for launch --dur %g`) or loop it "
                                 "with {\"fit\": true} in the mix instead" % dur)
    ec = float(end_card) if end_card else round(min(7.0, max(4.0, 0.2 * dur)), 2)
    t, L = loudness_db(an)
    lift_list = lifts(an)
    bars = bar_grid(an)
    phrases: Optional[np.ndarray] = None
    per_phrase = 0
    if bars is not None and an.get("rhythmic", True):
        phrases, per_phrase = phrase_grid(an, bars, lift_list)
    bar = float(np.median(np.diff(bars))) if bars is not None and len(bars) > 2 else None
    notes: List[str] = []
    top = float(L.max())

    def window_score(o: float) -> Tuple[float, Dict[str, Any]]:
        e = o + dur
        win = (t >= o) & (t < e)
        if not win.any():
            return -1e9, {}
        Lw = L[win]
        rng = float(np.percentile(Lw, 90) - np.percentile(Lw, 10))
        opening = level_at(t, L, o, o + 3.0)
        med = float(np.median(Lw))
        wmax = float(Lw.max())
        s = 0.4 * min(rng, 10.0)
        s += 0.3 * float(np.clip(med - opening, -3.0, 6.0))
        if opening < wmax - 24 or level_at(t, L, o, o + 1.0) < top - 30:
            s -= 8.0                                           # silence under the hook
        body = (t >= o + 2.0) & (t < e - 2.5)
        if body.any() and float(L[body].min()) < wmax - 25:
            s -= 5.0                                           # a dropout inside the film
        ecs = e - ec
        lift = None
        for lf in lift_list:
            if ecs - 2.5 <= lf["t"] <= ecs + 1.5:
                sc = min(lf["db"], 9.0) * (1.0 - abs(lf["t"] - ecs) / 4.0)
                if lift is None or sc > lift[1]:
                    lift = (lf, sc)
        if lift:
            s += 1.5 * lift[1]
        if phrases is not None and len(phrases):
            d_end = float(np.min(np.abs(phrases - e)))
            s += 1.0 if d_end < 0.25 else 0.0
            n_in = int(((phrases > o + 1.0) & (phrases < e - 1.0)).sum())
            if n_in < min(scenes - 1, 2):
                s -= 2.0
        # the end card sits on the loud part (the name lands on the peak, not in a lull)
        s += 0.15 * float(np.clip(level_at(t, L, ecs, e) - med, -6.0, 6.0))
        s += 0.3 * float(np.clip(level_at(t, L, ecs, e) - top + 10.0, 0.0, 10.0))
        # a sparse intro (the whole excerpt far under the track's body) is not a launch bed
        if med - top < -14.0:
            s -= 0.8 * (-14.0 - (med - top))
        return s, {"range_db": round(rng, 2), "opening_db": round(opening - wmax, 2),
                   "lift": lift[0] if lift else None, "end_on_phrase": bool(phrases is not None and len(phrases)
                                                                            and float(np.min(np.abs(phrases - e))) < 0.25)}

    if offset is not None:
        if offset < 0 or offset + dur > track_dur + 1e-6:
            raise ShowtimeError("--offset %g does not leave %gs of the %.1fs track" % (offset, dur, track_dur))
        cand_offsets = [float(offset)]
    else:
        # the excerpt starts on a bar line (a phrase start scores a little more)
        base = bars if bars is not None and len(bars) else np.arange(0, track_dur, 0.5)
        cand_offsets = [float(x) for x in base if x + dur <= track_dur - 0.25] or [0.0]

    def scored_at(o: float) -> Tuple[float, Dict[str, Any]]:
        sc, inf = window_score(o)
        if phrases is not None and len(phrases) and float(np.min(np.abs(phrases - o))) < 0.12:
            sc += 0.5
        return sc, inf
    scored = sorted(((scored_at(o), o) for o in cand_offsets), key=lambda z: -z[0][0])
    (score, info), o = scored[0]
    # scene changes in film time
    tg = targets(dur, scenes, ec, hook)
    cands: List[Tuple[float, float]] = []
    halves: List[float] = []
    if phrases is not None:
        cands += [(float(x - o), 0.0) for x in phrases if o + 0.5 < x < o + dur - 1.0]
        if per_phrase >= 4 and bars is not None:
            # half-phrase starts (2 bars in): the next strongest boundary
            sel = set(np.round(phrases, 4))
            idx = [i for i, x in enumerate(bars) if round(float(x), 4) in sel]
            halves = [float(bars[i + per_phrase // 2]) for i in idx if i + per_phrase // 2 < len(bars)]
            cands += [(float(x - o), 0.25 * (bar or 2.0)) for x in halves if o + 0.5 < x < o + dur - 1.0]
    if bars is not None:
        cands += [(float(x - o), 0.6 * (bar or 2.0)) for x in bars if o + 0.5 < x < o + dur - 1.0]
    lift_t = info.get("lift", {}) and info["lift"]["t"] - o if info.get("lift") else None
    if lift_t is not None and lift_t > 0:
        cands.append((round(lift_t, 3), -0.8))                # the swell is the best end-card start
        tg[-1] = lift_t if tg else lift_t
    for lf in lift_list:
        if o + 0.5 < lf["t"] < o + dur - 1.0:
            cands.append((float(lf["t"] - o), 0.4))
    if not cands:
        cands = [(x, 1.0) for x in np.arange(1.0, dur - 1.0, 0.5)]
        notes.append("no reliable beat grid or lifts in this excerpt: the cuts follow the scene grammar alone")
    cands = sorted({round(c, 3): pen for c, pen in sorted(cands, key=lambda z: -z[1])}.items())
    cuts = _choose(cands, tg, dur, min_scene, hook_min=3.0) if scenes > 1 else []
    if scenes > 1 and not cuts:
        cuts = [round(x, 3) for x in tg]
        notes.append("the music's grid left no way to give every scene %.1fs; cuts follow the scene grammar" % min_scene)
    cuts = [round(c, 3) for c in cuts]
    on_phrase = sum(1 for c in cuts if phrases is not None and float(np.min(np.abs(phrases - (c + o)))) < 0.12)
    grid = list(phrases) + halves if phrases is not None else []
    on_half = sum(1 for c in cuts if grid and float(np.min(np.abs(np.asarray(grid) - (c + o)))) < 0.12)
    on_lift = sum(1 for c in cuts if any(abs(lf["t"] - (c + o)) < 0.3 for lf in lift_list))
    fade_out = 1.2 if info.get("end_on_phrase") else 2.0
    if phrases is None:
        notes.append("the track has no steady pulse (phrase_flow): cuts sit on its lifts and energy changes")
    if info.get("lift") is None:
        notes.append("no swell lands near the end card in this excerpt; the name lands on the loudest phrase instead")
    return {
        "schema": SCHEMA, "dur": round(dur, 3), "scenes": scenes, "offset": round(o, 3),
        "fade_in": 0.15, "fade_out": fade_out, "end_card": ec,
        "bpm": an.get("bpm"), "bar_s": round(bar, 3) if bar else None, "bars_per_phrase": per_phrase or None,
        "phrase_s": round(bar * per_phrase, 3) if bar and per_phrase else None,
        "cuts": cuts, "scene_starts": [0.0] + cuts,
        "cuts_on_phrase": on_phrase, "cuts_on_half_phrase": on_half - on_phrase, "cuts_on_lift": on_lift, "lift": round(lift_t, 3) if lift_t is not None else None,
        "lift_db": info["lift"]["db"] if info.get("lift") else None,
        "range_db": info.get("range_db"), "opening_db": info.get("opening_db"),
        "end_on_phrase": info.get("end_on_phrase"), "score": round(score, 2),
        "alternatives": [{"offset": round(oo, 3), "score": round(sc[0], 2)} for sc, oo in scored[1:4]],
        "notes": notes,
    }


def summary(p: Dict[str, Any], label: str = "") -> str:
    lines = ["%sexcerpt %.2f-%.2fs of the track (%gs), %s" % (
        (label + ": ") if label else "", p["offset"], p["offset"] + p["dur"], p["dur"],
        ("%s bpm, phrases of %s bars (%.2fs)" % (p["bpm"], p["bars_per_phrase"], p["phrase_s"])) if p.get("phrase_s")
        else "no steady phrase grid")]
    lines.append("scene starts: %s" % ", ".join("%.2f" % x for x in p["scene_starts"]))
    lines.append("  %d of %d scene changes on a phrase start, %d on a half-phrase, %d on a swell; %s" % (
        p["cuts_on_phrase"], len(p["cuts"]), p.get("cuts_on_half_phrase", 0), p.get("cuts_on_lift", 0),
        ("the swell (+%.1f dB) lands at %.2fs, the end card" % (p["lift_db"], p["lift"])) if p.get("lift") is not None
        else "no swell at the end card"))
    lines.append("  dynamics in the excerpt: %.1f dB (10th-90th percentile); the opening sits %.1f dB under its peak"
                 % (p.get("range_db") or 0, -(p.get("opening_db") or 0)))
    for n in p.get("notes") or []:
        lines.append("  note: " + n)
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------ apply
def music_track(p: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    tr = {"id": "music", "kind": "music"}
    tr.update(source)
    tr.update({"offset": p["offset"], "dur": p["dur"], "fade_in": p["fade_in"], "fade_out": p["fade_out"]})
    return tr


def apply(p: Dict[str, Any], project: Path, source: Dict[str, Any], credit_line: Optional[str] = None,
          dry_run: bool = False) -> Dict[str, Any]:
    """Retime the project's scenes to the cuts and put the excerpt in its audio mix as the music track
    (replacing the old music track; effects and voice stay). A page element with data-credit gets the
    music's short credit line."""
    from ..cli_core import cuts_plan, retime_project
    proj = Path(project)
    cfg_path = proj / "showtime.json"
    if not cfg_path.is_file():
        raise ShowtimeError("no showtime.json in %s" % proj)
    rep: Dict[str, Any] = {"project": str(proj), "changes": []}
    new, plan_ = cuts_plan(proj, p["cuts"], p["dur"])
    rt = retime_project(proj, new, dry_run=dry_run, plan=plan_)
    rep["retime"] = rt
    rep["changes"] += rt["changes"]
    cfg = read_json(cfg_path, {}) or {}
    audio = cfg.get("audio")
    mix_rel = audio if isinstance(audio, str) and audio.lower().endswith(".json") else "audio/mix.json"
    mp = proj / mix_rel
    spec = read_json(mp, {}) if mp.is_file() else {}
    spec = spec or {"sample_rate": 48000, "tracks": [], "master": {"lufs": -14, "true_peak": -1}}
    tracks = spec.get("tracks") or []
    new_tr = music_track(p, source)
    idx = next((i for i, tr in enumerate(tracks) if (tr.get("kind") or "") == "music"), None)
    if idx is None:
        tracks.insert(0, new_tr)
    else:
        old = tracks[idx]
        for k in ("duck", "gain_db", "gain_points", "level"):
            if k in old and k not in new_tr:
                new_tr[k] = old[k]
        tracks[idx] = new_tr
    spec["tracks"] = tracks
    spec.pop("duration", None)
    spec["_music_plan"] = {k: p[k] for k in ("offset", "cuts", "lift", "lift_db", "bpm", "phrase_s")}
    rep["changes"].append("%s: music -> %s from %.2fs, %gs, fade %.2f/%.2f" % (
        mix_rel, source.get("catalog") or source.get("file") or source.get("lib"), p["offset"], p["dur"],
        p["fade_in"], p["fade_out"]))
    if not dry_run:
        mp.parent.mkdir(parents=True, exist_ok=True)
        write_json(mp, spec)
        if not isinstance(audio, str):
            cfg["audio"] = mix_rel
            write_json(cfg_path, cfg)
    if credit_line:
        page = proj / str(cfg.get("page") or "index.html")
        if page.is_file():
            html = page.read_text(encoding="utf-8")
            out, n = re.subn(r"(<([a-zA-Z0-9]+)\b[^>]*\sdata-credit\b[^>]*>)(.*?)(</\2>)",
                             lambda m: m.group(1) + _esc(credit_line) + m.group(4), html, count=1, flags=re.S)
            if n and out != html:
                rep["changes"].append("%s: music credit on the end card" % page.name)
                if not dry_run:
                    page.write_text(out, encoding="utf-8")
    return rep


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
