"""`showtime edit clips`: picked moments -> finished short clips, rendered in parallel, each through qa, and one
contact sheet of them all.

Per moment (moments.json from `edit moments`, or hand-written: source/transcript, start, end, title; the agent may
set "pick": true, move start/end, rewrite the title, and list word ids to cut inside it, "remove": ["w12-w18"]):

- one EDL, <job>/edit/clips/<NN>-<slug>.json, cut with edit cut's rules (cuts.plan_keep): fillers out, pauses
  over 0.5 s down to 0.3 s, padded word edges snapped to the quietest point;
- a tight start on the first real word (a filler or a "Yeah," / "Well," lead-in goes) and a clean end after the
  last word; the outer edges never take a sliver of the words around the moment, and a laugh or applause right
  after the last word stays in;
- the output aspect (a wider source into 9:16 is the face-tracked reframe), captions (bold-pop in tall frames,
  clean in wide ones, kept off the face), optional cards (--cards: a title card with the moment's title and a
  data callout when the speaker says a number with a unit, from `edit cards suggest`);
- the render is the EDL renderer's (render_edl.render), qa is `showtime qa`'s (qa.video.run): nothing here draws
  or encodes on its own.

The clips go to <job>/clips/ (drafts with --preview to <job>/clips/preview/), with clips.json (what was made,
from which moment, each qa verdict) and sheet.jpg (a row of frames per clip, qa's colour on its border).
"""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import platform as plat
from ..common import ShowtimeError, info, read_json, slugify, warn, write_json
from . import util as U

GUARD = 0.04            # never closer than this to a word outside the clip
LEAD, TAIL = 0.15, 0.35  # breath kept before the first word and after the last
EVENT_TAIL = 2.5        # at most this much of a laugh or applause after the last word
EVENT_FADE = 1.5        # ... fading out over (at most) its last 1.5 s
LEAD_INS = {"yeah", "yes", "well", "okay", "ok", "oh", "alright", "right", "so", "um", "uh", "and", "but"}
SHEET_POINTS = (0.02, 0.25, 0.5, 0.75, 0.98)
TALL_CAPTION_SIZE = 0.09   # bold-pop text height in tall clips, a fraction of the width (the style's own: 0.105)
TALL_CAPTION_MIN = 0.08    # ... down to this when only that keeps the line under the chin in every stretch


# ------------------------------------------------------------------------------------------------ moments

def load_moments(path: Path) -> Dict[str, Any]:
    doc = read_json(path)
    if isinstance(doc, list):
        doc = {"moments": doc}
    if not isinstance(doc, dict) or not isinstance(doc.get("moments"), list):
        raise ShowtimeError("%s is not a moments file (no \"moments\" list)" % path,
                            hint="make one with `showtime edit moments <transcript>`")
    srcs = doc.get("sources") or {}
    out = []
    for i, m in enumerate(doc["moments"]):
        where = "moments[%d]" % i
        if not isinstance(m, dict):
            raise ShowtimeError("%s of %s must be an object" % (where, path.name))
        tp = m.get("transcript") or (srcs.get(m.get("source")) or {}).get("transcript")
        if not tp:
            raise ShowtimeError("%s (%s) names no transcript" % (where, m.get("id") or "?"),
                                hint="each moment needs \"transcript\" (or a \"source\" listed in \"sources\")")
        tpath = Path(str(tp)).expanduser()
        if not tpath.is_absolute():
            tpath = (path.parent / tpath).resolve()
        try:
            a, b = float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            raise ShowtimeError("%s (%s) needs numeric \"start\" and \"end\" (seconds on the source's clock)"
                                % (where, m.get("id") or "?"))
        if b <= a:
            raise ShowtimeError("%s (%s): end %.2f is not after start %.2f" % (where, m.get("id") or "?", b, a))
        out.append(dict(m, id=str(m.get("id") or "m%d" % (i + 1)), rank=int(m.get("rank") or i + 1),
                        transcript=str(tpath), start=a, end=b))
    return dict(doc, moments=out, path=str(path))


def choose(doc: Dict[str, Any], pick: Optional[str] = None, count: int = 3) -> List[Dict[str, Any]]:
    """The moments to make: --pick (ids or ranks, in that order), else the ones marked "pick": true, else the
    best `count` by rank."""
    ms = doc["moments"]
    if pick:
        out = []
        for tok in re.split(r"[,\s]+", pick.strip()):
            if not tok:
                continue
            m = next((x for x in ms if x["id"] == tok or (tok.isdigit() and x["rank"] == int(tok))), None)
            if m is None:
                raise ShowtimeError("--pick %s: no moment %s in %s" % (pick, tok, Path(doc["path"]).name),
                                    hint="ids: %s" % ", ".join(x["id"] for x in ms[:20]))
            if m not in out:
                out.append(m)
        return out
    marked = [m for m in ms if m.get("pick") is True]
    if marked:
        return marked
    return sorted(ms, key=lambda m: m["rank"])[:max(1, count)]


# ------------------------------------------------------------------------------------------------ one clip

def _rel(p: Path, base: Path) -> str:
    try:
        return os.path.relpath(str(p), str(base)).replace(os.sep, "/")
    except ValueError:  # another drive on Windows
        return str(p)


def edges(words: Sequence[Dict[str, Any]], first: int, last: int, events: Sequence[Dict[str, Any]] = ()
          ) -> Tuple[float, float, Optional[Dict[str, Any]], List[int]]:
    """(head, tail, kept event, words to drop) of a clip from words[first]..words[last]: LEAD s of breath before the
    first word and TAIL s after the last, never closer than GUARD to the words outside. A laugh, applause or cheering
    that starts within 4.5 s of the last word (the tagger places onsets up to ~2.5 s late) extends the tail by up to
    EVENT_TAIL s, still stopping before the next word; a trailing "So" or filler said into it is dropped."""
    from .moments import TRAILING
    ws, we = float(words[first]["start"]), float(words[last]["end"])
    prev_end = float(words[first - 1]["end"]) if first > 0 else 0.0
    next_start = float(words[last + 1]["start"]) if last + 1 < len(words) else we + 60.0
    head = max(ws - LEAD, min(ws, prev_end + GUARD)) if first > 0 else max(0.0, ws - LEAD)
    tail = min(we + TAIL, max(we, next_start - GUARD))
    kept, drop = None, []
    k = last + 1
    while k < len(words) and k - last <= 2 and (U.bare(words[k]["text"]) in TRAILING or U.is_filler(words[k]["text"])
                                                  or words[k].get("filler")):
        k += 1
    blocker = float(words[k]["start"]) if k < len(words) else we + 60.0
    for e in events:
        kind = str(e.get("text") or "").strip("()[] ").lower()
        if kind in ("laughter", "applause", "cheering") and we - 0.5 <= float(e["start"]) <= we + 4.5 and \
                float(e["start"]) < blocker:
            t = min(float(e["end"]), we + EVENT_TAIL, max(we, blocker - GUARD))
            if t > tail + 0.05:
                tail, kept = t, {"type": kind, "start": round(float(e["start"]), 2), "kept_to": round(t, 2)}
                drop = list(range(last + 1, k))
    return round(head, 3), round(tail, 3), kept, drop


def tighten(words: Sequence[Dict[str, Any]], first: int, last: int, lang: str) -> Tuple[int, int, List[str]]:
    """Move the start past fillers and an interjection lead-in ("Yeah," "Well," "So, um,"), and the end back past
    trailing fillers. Returns (first, last, the words dropped)."""
    dropped = []
    while first < last:
        t = str(words[first]["text"]).strip()
        b = U.bare(t)
        lead_in = b in LEAD_INS and (t.endswith(",") or U.is_filler(b, lang) or
                                     (first + 1 <= last and U.is_filler(words[first + 1]["text"], lang)))
        if U.is_filler(t, lang) or words[first].get("filler") or lead_in:
            dropped.append(t)
            first += 1
            continue
        break
    while last > first and (U.is_filler(words[last]["text"], lang) or words[last].get("filler")):
        dropped.append(str(words[last]["text"]).strip())
        last -= 1
    return first, last, dropped


def default_captions(width: int, height: int) -> str:
    return "clean" if width > height * 1.2 else "bold-pop"


ACCEPT_UPSCALE = 1920 / 1080.0   # a 9:16 crop of a 1080p 16:9 frame at the platform size (1080x1920)


def out_size(aspect: str, src_w: int, src_h: int) -> Dict[str, Any]:
    """The EDL "output" for a clip: the aspect's standard size, or a smaller one of the same shape when filling it
    would enlarge the source more than ACCEPT_UPSCALE (a 720p source renders 9:16 at 720x1280, not 1080x1920).
    Up to ACCEPT_UPSCALE the enlargement is accepted (allow_upscale: a 9:16 crop of 16:9 1080p footage at the
    platform size is always 1.78x); qa notes it, and the clips report says so."""
    from .edl import ASPECTS
    key = str(aspect).lower()
    if key not in ASPECTS:
        raise ShowtimeError("unknown aspect %r (use %s)" % (aspect, ", ".join(sorted(ASPECTS))))
    w, h = ASPECTS[key]
    o: Dict[str, Any] = {"aspect": aspect}
    if not src_w or not src_h:
        return o
    scale = max(w / float(src_w), h / float(src_h))       # what filling w x h (cover) enlarges the source by
    if scale > ACCEPT_UPSCALE + 0.01:
        f = ACCEPT_UPSCALE / scale
        o = {"width": max(2, int(round(w * f / 2)) * 2), "height": max(2, int(round(h * f / 2)) * 2)}
        scale = ACCEPT_UPSCALE
    if scale > 1.5 + 1e-6:
        o["allow_upscale"] = True
    return o


def plan_clip(m: Dict[str, Any], tr: Dict[str, Any], tpath: Path, *, edl_dir: Path, aspect: Optional[str],
              captions: Optional[str], fillers: bool = True, max_pause: float = 0.5, keep_pause: float = 0.3,
              snap: bool = True) -> Dict[str, Any]:
    """The EDL for one moment (not written). Returns {"doc", "first", "last", "dropped", "event", "notes"}."""
    from . import cuts as C
    from .moments import SENT_END, snap as snap_words, source_audio
    lang = str(tr.get("language") or "en").split("-")[0].lower()
    words = sorted((w for w in U.words_of(tr) if str(w.get("text", "")).strip()), key=lambda w: float(w["start"]))
    events = [w for w in tr.get("words", []) if w.get("type") == "audio_event"]
    src = Path(tr.get("source") or "")
    if not src.is_file():
        raise ShowtimeError("the source of %s is missing: %s" % (tpath.name, src or "(none)"),
                            hint="re-run `showtime transcribe` on the media, or fix \"source\" in the transcript")
    first, last = snap_words(words, float(m["start"]), float(m["end"]))
    notes = []
    if abs(float(words[first]["start"]) - float(m["start"])) > 0.05 or abs(float(words[last]["end"]) - float(m["end"])) > 0.05:
        notes.append("edges snapped to whole words: %.2f-%.2f s" % (float(words[first]["start"]), float(words[last]["end"])))
    if first > 0 and not SENT_END.search(str(words[first - 1]["text"]).strip()) and \
            float(words[first]["start"]) - float(words[first - 1]["end"]) < 0.6:
        notes.append("starts mid-sentence (after \"%s\")" % str(words[first - 1]["text"]).strip())
    if last + 1 < len(words) and not SENT_END.search(str(words[last]["text"]).strip()) and \
            float(words[last + 1]["start"]) - float(words[last]["end"]) < 0.6:
        notes.append("ends mid-sentence (before \"%s\")" % str(words[last + 1]["text"]).strip())
    f2, l2, dropped = tighten(words, first, last, lang) if fillers else (first, last, [])
    extra = m.get("remove") or []
    extra = [str(x) for x in (extra.split(",") if isinstance(extra, str) else extra) if str(x).strip()]
    cut_ids = C.parse_word_ids(extra, words) if extra else set()
    while f2 < l2 and words[f2].get("id") in cut_ids:      # words cut at the very start or end move the edge
        f2 += 1
    while l2 > f2 and words[l2].get("id") in cut_ids:
        l2 -= 1
    head, tail, kept, drop = edges(words, f2, l2, events)
    pr = U.probe(src)
    audio = None
    if snap:
        try:
            audio = source_audio(src, int(tr.get("audio_track") or 0))
        except Exception as e:  # noqa: BLE001 - snapping is a refinement
            notes.append("cut edges not snapped to the audio (%s)" % e)
    drop_ids = [words[k]["id"] for k in drop if words[k].get("id")]
    plan = C.plan_keep(tr, fillers=fillers, keep_times=[(head, tail)], max_pause=max_pause, keep_pause=keep_pause,
                       lead=LEAD, tail=TAIL, snap_audio=audio, remove_ids=drop_ids + extra)
    if drop_ids:
        dropped = dropped + [str(words[k]["text"]).strip() for k in drop]
    keep = [list(r) for r in plan["keep"] if r[1] > head + 1e-3 and r[0] < tail - 1e-3]
    if not keep:
        raise ShowtimeError("moment %s keeps no speech" % m.get("id"))
    keep[0][0] = max(keep[0][0], head)
    last_end = float(words[l2]["end"])
    if kept and drop:
        # the speech ends before the dropped words, then the laugh or applause goes on without them
        cut_from = max(last_end, float(words[drop[0]]["start"]) - GUARD)
        resume = float(words[drop[-1]]["end"]) + GUARD
        keep = [r for r in keep if r[0] < cut_from]
        keep[-1][1] = min(max(keep[-1][1], last_end), cut_from)
        if tail - resume > 0.3:
            keep.append([resume, tail])
    elif kept:
        keep[-1][1] = max(keep[-1][1], tail)
    else:
        keep[-1][1] = min(max(keep[-1][1], last_end), tail)
    keep = [r for r in keep if r[1] - r[0] > 0.02]
    key = U.bare(src.stem).replace(" ", "-") or "src"
    ranges = []
    for a, b in keep:
        said = [w["text"] for w in words if a <= (float(w["start"]) + float(w["end"])) / 2 <= b]
        ranges.append({"source": key, "start": round(a, 3), "end": round(b, 3),
                       "note": " ".join(said[:8]) + (" ..." if len(said) > 8 else "")})
    if kept:
        # the laugh or applause the clip ends on fades out instead of stopping dead on the last frame
        ranges[-1]["fade_out"] = round(max(0.4, min(EVENT_FADE, tail - last_end - 0.3)), 2)
    out: Dict[str, Any] = out_size(aspect, int(pr.get("display_width") or 0), int(pr.get("display_height") or 0)) \
        if aspect else {}
    doc: Dict[str, Any] = {
        "version": 1, "title": m.get("title") or "",
        "moment": {k: m.get(k) for k in ("id", "rank", "score", "start", "end", "title") if m.get(k) is not None},
        "sources": {key: _rel(src, edl_dir) if not tr.get("audio_track") else
                    {"file": _rel(src, edl_dir), "audio_track": int(tr["audio_track"])}},
        "transcripts": {key: _rel(tpath, edl_dir)},
        "ranges": ranges,
    }
    if out:
        doc["output"] = out
    if captions and captions != "none":
        doc["captions"] = {"style": captions}
        if out and _tall(out):
            doc["captions"]["avoid_face"] = True
            if captions == "bold-pop":
                # a little under the style's 0.105: in a close-up the line still fits under the chin, above the
                # platform's bottom UI, so it moves less often (and less far) off the face
                doc["captions"]["size"] = TALL_CAPTION_SIZE
    removed = [r for r in plan["removed"] if (r["why"] == "filler" and head <= float(r["start"]) <= tail) or
               (r["why"] == "word range" and r.get("id") in cut_ids)]
    doc["cut_summary"] = {"source_span": [round(head, 3), round(tail, 3)], "after_s": round(sum(b - a for a, b in keep), 3),
                          "segments": len(keep), "edge_words_dropped": dropped,
                          "removed": [{"id": r.get("id"), "text": r["text"], "at": r["start"], "why": r["why"]}
                                      for r in removed],
                          "kept_event": kept}
    return {"doc": doc, "first": f2, "last": l2, "dropped": dropped, "event": kept, "notes": notes,
            "words": words, "key": key}


def _tall(out: Dict[str, Any]) -> bool:
    from .edl import ASPECTS
    w, h = out.get("width"), out.get("height")
    if not (w and h):
        w, h = ASPECTS.get(str(out.get("aspect") or "").lower(), (0, 0))
    return bool(w and h and h > w * 1.2)


def fit_captions(edl_path: Path) -> Tuple[Optional[float], List[Tuple[float, float]]]:
    """Tall clips: the caption size (TALL_CAPTION_SIZE, else TALL_CAPTION_MIN) at which the face-avoiding plan keeps
    the line under the chin everywhere instead of moving it above the eyes for a stretch (a jump from the chest to
    the forehead and back). Returns (the size to set, or None to keep the EDL's; the stretches still above the eyes)."""
    from . import cards as CD
    from . import edl as E
    above: List[Tuple[float, float]] = []
    for size in (TALL_CAPTION_SIZE, TALL_CAPTION_MIN):
        ed = E.load(edl_path, overrides={"captions": {"size": size}})
        if not (ed.get("captions") or {}).get("avoid_face"):
            return None, []
        plan = CD.caption_plan(ed, E.plan(ed), ed["output"]["width"], ed["output"]["height"])
        stretches = [(round(z["start"], 2), round(z["end"], 2)) for z in plan["zones"] if z.get("align") == 2]
        if not stretches:
            return (size if size != TALL_CAPTION_SIZE else None), []
        if size == TALL_CAPTION_SIZE:
            above = stretches
    return None, above


def suggest_cards(edl_path: Path, title: str, first_id: Optional[str]) -> List[Dict[str, Any]]:
    """--cards: a title card with the moment's title on its first words, and a data callout when the speaker
    says a number with a unit and its label comes from their words (`edit cards suggest` on the clip)."""
    from . import card_suggest as S
    cards: List[Dict[str, Any]] = []
    if title and first_id:
        cards.append({"type": "title", "word": first_id, "title": title, "hold": 2.2})
    try:
        rep = S.from_edl(edl_path, audio=False, limit=3)
    except ShowtimeError:
        return cards
    for st in rep["suggestions"].get("stat") or []:
        c = st.get("card") or {}
        if c.get("label") not in (None, "", "?") and float(st["at"]) > 4.0:
            cards.append(c)
            break
    return cards


# ------------------------------------------------------------------------------------------------ the batch

def make(job: Path, moments_path: Path, *, pick: Optional[str] = None, count: int = 3, aspect: Optional[str] = "9:16",
         captions: Optional[str] = None, cards: bool = False, fillers: bool = True, max_pause: float = 0.5,
         preview: bool = False, parallel: Optional[int] = None, jobs: Optional[int] = None, qa: bool = True,
         platform: Optional[str] = None, overwrite: bool = False) -> Dict[str, Any]:
    """Plan, render and check every picked moment. Returns the clips report (also written as clips.json)."""
    from . import edl as E
    from . import render_edl as R
    t0 = time.time()
    doc = load_moments(moments_path)
    picked = choose(doc, pick, count)
    if not picked:
        raise ShowtimeError("%s has no moments" % moments_path.name, hint="run `showtime edit moments` again with "
                                                                         "a lower --min or a higher --max")
    edl_dir = job / "edit" / "clips"
    out_dir = job / "clips" / ("preview" if preview else "")
    out_dir.mkdir(parents=True, exist_ok=True)
    edl_dir.mkdir(parents=True, exist_ok=True)
    trs: Dict[str, Tuple[Dict[str, Any], Path]] = {}
    clips: List[Dict[str, Any]] = []
    for n, m in enumerate(picked, 1):
        tp = Path(m["transcript"])
        if str(tp) not in trs:
            trs[str(tp)] = (U.load_transcript(tp), tp)
        tr, _ = trs[str(tp)]
        pr = U.probe(Path(tr.get("source") or ""))
        cap = captions
        if cap is None:
            if aspect:
                from .edl import ASPECTS
                w, h = ASPECTS.get(aspect.lower(), (pr.get("display_width") or 1920, pr.get("display_height") or 1080))
            else:
                w, h = pr.get("display_width") or 1920, pr.get("display_height") or 1080
            cap = default_captions(int(w), int(h))
        p = plan_clip(m, tr, tp, edl_dir=edl_dir, aspect=aspect, captions=cap, fillers=fillers, max_pause=max_pause)
        slug = slugify(m.get("title") or m["id"], max_len=40, default=m["id"])
        name = "%02d-%s" % (n, slug)
        edl_path = _edl_file(edl_dir / (name + ".json"), p["doc"], overwrite)
        if (p["doc"].get("captions") or {}).get("size") == TALL_CAPTION_SIZE:
            size, above = fit_captions(edl_path)
            if size is not None:
                p["doc"]["captions"]["size"] = size
                p["notes"].append("captions at %g of the width: the size that keeps them under the chin" % size)
                edl_path = _edl_file(edl_path, p["doc"], True)
            elif above:
                p["notes"].append("captions move above the eyes at %s (no room under the chin above the platform's "
                                  "bottom zone)" % ", ".join("%.1f-%.1f s" % st for st in above))
        if cards:
            cl = suggest_cards(edl_path, m.get("title") or "", p["words"][p["first"]].get("id"))
            if cl:
                p["doc"]["cards"] = cl
                edl_path = _edl_file(edl_path, p["doc"], True)
        E.load(edl_path)          # validate (sources, ranges, cards) before any render
        clips.append({"n": n, "name": name, "moment": m, "edl": edl_path, "plan": p,
                      "video": _video_file(out_dir / (name + ".mp4"), overwrite)})
    workers = parallel or min(len(clips), max(1, plat.cpu_count() // 4))
    workers = max(1, min(len(clips), workers))
    info("rendering %d clip(s)%s, %d at a time: %s" % (
        len(clips), " (drafts)" if preview else "", workers,
        ", ".join("%s (%.0f s)" % (c["name"], c["plan"]["doc"]["cut_summary"]["after_s"]) for c in clips)))
    lock = threading.Lock()
    done = [0]

    def one(c: Dict[str, Any]) -> Dict[str, Any]:
        t1 = time.time()
        res: Dict[str, Any] = {}
        try:
            rep = R.render(c["edl"], c["video"], preview=preview, overwrite=overwrite, jobs=jobs)
            res["render"] = rep
            res["video"] = Path(rep["output"])
            res["render_seconds"] = round(time.time() - t1, 1)
            if qa:
                from ..qa import video as QA
                t2 = time.time()
                res["qa"] = QA.run(res["video"], platform=platform, quiet=True, record=False)
                res["qa_seconds"] = round(time.time() - t2, 1)
        except Exception as e:  # noqa: BLE001 - one clip failing never stops the others
            res["error"] = str(e) if isinstance(e, ShowtimeError) else "%s: %s" % (type(e).__name__, e)
        with lock:
            done[0] += 1
            q = res.get("qa") or {}
            info("clip %d/%d %s: %s in %.0f s" % (
                done[0], len(clips), c["name"], ("error: " + res["error"]) if res.get("error") else
                ("qa %s" % q.get("verdict") if q else "rendered"), time.time() - t1))
        return res

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(one, clips))
    else:
        results = [one(c) for c in clips]
    rows = []
    for c, res in zip(clips, results):
        rows.append(_row(c, res))
    sheet = None
    try:
        sheet = contact_sheet([r for r in rows if r.get("video")], out_dir / "sheet.jpg", overwrite)
    except Exception as e:  # noqa: BLE001 - the sheet is a convenience
        warn("no contact sheet: %s" % e)
    report = {"version": 1, "job": str(job), "moments": str(moments_path), "preview": preview, "aspect": aspect,
              "captions": rows[0]["captions"] if rows else None, "cards": cards, "platform": platform,
              "clips": rows, "sheet": str(sheet) if sheet else None, "parallel": workers,
              "seconds": round(time.time() - t0, 1), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    man = out_dir / "clips.json"
    if man.exists() and not overwrite:
        man = U.unique_path(man)
    write_json(man, report)
    report["manifest"] = str(man)
    _record(job, rows, preview, man)
    return report


def _doc_hash(doc: Dict[str, Any]) -> str:
    import hashlib
    import json
    body = {k: v for k, v in doc.items() if k != "generated"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _edl_file(path: Path, doc: Dict[str, Any], overwrite: bool) -> Path:
    """Write a clip's EDL with the hash of what was generated ("generated"). An EDL this command wrote and nobody
    edited since is updated in place (its name, and so its render cache, stays); one edited by hand is kept, and the
    new EDL goes to name-2.json (unless overwrite)."""
    doc = dict(doc, generated=_doc_hash(doc))
    while path.exists() and not overwrite:
        try:
            cur = read_json(path)
        except ShowtimeError:
            cur = None
        if isinstance(cur, dict) and cur.get("generated") == _doc_hash(cur):
            break                                   # untouched since it was generated: update it in place
        info("%s was edited by hand: kept; writing the new EDL beside it" % path.name)
        path = U.unique_path(path)
    write_json(path, doc)
    return path


def _video_file(path: Path, overwrite: bool) -> Path:
    return path if overwrite or not path.exists() else U.unique_path(path)


def _row(c: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    m, p = c["moment"], c["plan"]
    rep = res.get("render") or {}
    q = res.get("qa") or {}
    lo = q.get("loudness") or rep.get("loudness") or {}
    row: Dict[str, Any] = {
        "n": c["n"], "name": c["name"], "moment": m["id"], "title": m.get("title") or "",
        "source_range": p["doc"]["cut_summary"]["source_span"], "edl": str(c["edl"]),
        "video": str(res["video"]) if res.get("video") else None,
        "duration": rep.get("video_duration") or rep.get("duration"),
        "size": [rep.get("width"), rep.get("height")] if rep else None,
        "segments": len(p["doc"]["ranges"]), "cards": len(p["doc"].get("cards") or []),
        "captions": (p["doc"].get("captions") or {}).get("style"),
        "edge_words_dropped": p["dropped"], "kept_event": p["event"], "notes": p["notes"],
        "render_warnings": rep.get("warnings") or [], "render_seconds": res.get("render_seconds"),
    }
    if q:
        row["qa"] = {"verdict": q.get("verdict"), "fail": (q.get("summary") or {}).get("fail"),
                     "warn": (q.get("summary") or {}).get("warn"), "report": q.get("report"),
                     "lufs": lo.get("integrated_lufs"), "true_peak": lo.get("true_peak_dbtp"),
                     "findings": [{"severity": f["severity"], "rule": f["rule"], "message": f["message"],
                                   "t": f.get("t")} for f in q.get("findings") or [] if f["severity"] != "INFO"][:12],
                     "seconds": res.get("qa_seconds")}
    if res.get("error"):
        row["error"] = res["error"]
    return row


def _record(job: Path, rows: List[Dict[str, Any]], preview: bool, manifest: Optional[Path] = None) -> None:
    """The job ledger, from this one thread: one history line for the batch, a verified line per clip with its qa
    verdict, a pointer to the manifest. A clip is none of the job's latest pointers (final, preview, edl): the job's
    own final, if any, stays what qa and deliver use."""
    from ..job import ledger
    try:
        made = [r for r in rows if r.get("video")]
        verified = []
        for r in made:
            q = r.get("qa") or {}
            if q.get("verdict") in ("PASS", "WARN"):
                verified.append("qa %s on clip %s: %.1fs, %s LUFS, TP %s dBTP" % (
                    q["verdict"], Path(r["video"]).name, float(r.get("duration") or 0),
                    "%.1f" % q["lufs"] if q.get("lufs") is not None else "?",
                    "%.1f" % q["true_peak"] if q.get("true_peak") is not None else "?"))
        data = ledger.load(job)
        names = {Path(r["video"]).name for r in made}
        data["verified"] = [v for v in data.get("verified") or [] if not (
            str(v.get("text", "")).startswith("qa ") and any(" on clip %s:" % nm in str(v["text"]) for nm in names))]
        ledger.save(job, data)
        ledger.note(job, stage="preview" if preview else "render", verified=verified,
                    pointers=["clips=%s" % manifest] if manifest else [],
                    event="edit clips: %d clip(s)%s -> %s" % (len(made), " (drafts)" if preview else "",
                                                               ", ".join(Path(r["video"]).name for r in made)))
    except Exception as e:  # noqa: BLE001 - the ledger is a convenience
        from ..common import debug
        debug("could not update the job ledger: %s" % e)


def contact_sheet(rows: List[Dict[str, Any]], out: Path, overwrite: bool = False) -> Optional[Path]:
    """One row per clip: frames at SHEET_POINTS of its length, labelled with the clip and the time, the border in
    qa's colour when it did not pass."""
    from ..qa import media
    from ..qa import images
    if not rows:
        return None
    items = []
    frames_dir = out.parent / "work" / "sheet"
    for r in rows:
        v = Path(r["video"])
        dur = float(r.get("duration") or U.probe(v).get("duration") or 0.0)
        times = [min(max(0.0, dur - 0.05), max(0.0, dur * f)) for f in SHEET_POINTS]
        names = ["%s-%02d.jpg" % (r["name"], k) for k in range(len(times))]
        paths = media.extract_frames(v, times, frames_dir, width=360, duration=dur, names=names)
        verdict = (r.get("qa") or {}).get("verdict")
        for k, (t, pth) in enumerate(zip(times, paths)):
            items.append({"path": str(pth), "label": "%02d  %.1fs" % (r["n"], t) if k else "%02d  %s" % (
                r["n"], (r.get("title") or r["name"])[:17]),
                "sub": (verdict or "") if k == 0 else "", "mark": verdict if verdict in ("FAIL", "WARN") else None})
    if out.exists() and not overwrite:
        out = U.unique_path(out)
    return images.contact_sheet(items, out, cols=len(SHEET_POINTS), thumb=180,
                                title="%d clip(s): %s" % (len(rows), ", ".join(r["name"] for r in rows))[:150])


def format_text(rep: Dict[str, Any]) -> str:
    lines = ["%d clip(s)%s in %s (%d at a time):" % (len(rep["clips"]), " (drafts)" if rep["preview"] else "",
                                                     U.fmt_time(rep["seconds"]), rep["parallel"])]
    lines.append(" #  clip                                   length  qa     LUFS   TP     source         moment")
    for r in rep["clips"]:
        q = r.get("qa") or {}
        sr = r.get("source_range") or [0, 0]
        lines.append("%2d  %-38s %5.1f s  %-5s  %5s  %5s  %-14s %s" % (
            r["n"], (r["name"] + ".mp4")[:38], float(r.get("duration") or 0.0), q.get("verdict") or ("-" if not r.get("error") else "ERR"),
            "%.1f" % q["lufs"] if q.get("lufs") is not None else "-",
            "%.1f" % q["true_peak"] if q.get("true_peak") is not None else "-",
            "%s-%s" % (_mmss(sr[0]), _mmss(sr[1])), r["moment"]))
        for f in (q.get("findings") or [])[:4]:
            lines.append("      %s %s%s: %s" % (f["severity"], f["rule"], " at %.1fs" % f["t"] if f.get("t") is not None else "",
                                              f["message"][:110]))
        for w in (r.get("render_warnings") or [])[:2]:
            lines.append("      render warning: %s" % w[:140])
        for n_ in r.get("notes") or []:
            lines.append("      note: %s" % n_)
        if r.get("error"):
            lines.append("      error: %s" % r["error"][:300])
    if rep.get("sheet"):
        lines.append("sheet: %s" % rep["sheet"])
    lines.append("manifest: %s" % rep["manifest"])
    return "\n".join(lines)


def _mmss(t: float) -> str:
    m, s = divmod(max(0.0, float(t)), 60)
    return "%d:%04.1f" % (m, s)
