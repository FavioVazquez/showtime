"""Caption sidecars (SRT, WebVTT, ASS): parsing plus timing and placement checks.

Burned-in captions are pixels and cannot be read back without OCR; `showtime qa`
checks the sidecar that produced them (or the one shipped next to the video).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import captions_rules as R

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")


def _ts(s: str) -> Optional[float]:
    m = _TS.search(s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    frac = m.group(4)
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(frac) / (10 ** len(frac))


def _ass_ts(s: str) -> Optional[float]:
    m = re.match(r"\s*(\d+):(\d{1,2}):(\d{1,2})[.](\d{1,3})", s)
    if not m:
        return None
    frac = m.group(4)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(frac) / (10 ** len(frac))


def parse(path: Path) -> Dict[str, Any]:
    """-> {format, cues: [{start, end, text, lines, align, margin_v, margin_l, margin_r, pos}], play_res}"""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    ext = Path(path).suffix.lower()
    if ext == ".ass" or ext == ".ssa" or "[Script Info]" in text[:200]:
        return _parse_ass(text)
    cues: List[Dict[str, Any]] = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [ln.rstrip("\r") for ln in block.strip().splitlines()]
        for i, ln in enumerate(lines):
            if "-->" in ln:
                a, b = ln.split("-->", 1)
                s, e = _ts(a), _ts(b)
                if s is None or e is None:
                    break
                body = [re.sub(r"<[^>]+>", "", x).strip() for x in lines[i + 1:]]
                body = [x for x in body if x]
                align = None
                m = re.search(r"line:(-?\d+)%?", b)
                if m:
                    align = "top" if int(m.group(1)) < 50 and int(m.group(1)) >= 0 else "bottom"
                cues.append({"start": s, "end": e, "text": " ".join(body), "lines": body, "align": align,
                             "margin_v": None, "margin_l": None, "margin_r": None, "pos": None})
                break
    return {"format": "vtt" if ext == ".vtt" or text.startswith("WEBVTT") else "srt", "cues": cues, "play_res": None}


def _fields(line: str) -> List[str]:
    return [x.strip() for x in line.split(":", 1)[1].split(",")]


def _parse_ass(text: str) -> Dict[str, Any]:
    play = [None, None]
    styles: Dict[str, Dict[str, Any]] = {}
    sfmt: List[str] = []
    efmt: List[str] = []
    cues: List[Dict[str, Any]] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            section = line.lower()
            continue
        if line.lower().startswith("playresx:"):
            play[0] = _num(line.split(":", 1)[1])
        elif line.lower().startswith("playresy:"):
            play[1] = _num(line.split(":", 1)[1])
        elif line.lower().startswith("format:"):
            names = [x.lower() for x in _fields(line)]
            if "styles" in section:
                sfmt = names
            elif "events" in section:
                efmt = names
        elif line.lower().startswith("style:") and sfmt:
            vals = _fields(line)
            st = dict(zip(sfmt, vals + [""] * (len(sfmt) - len(vals))))
            styles[st.get("name", "Default")] = st
        elif line.lower().startswith("dialogue:") and efmt:
            body = line.split(":", 1)[1]
            parts = body.split(",", len(efmt) - 1)
            ev = dict(zip(efmt, [p.strip() for p in parts]))
            s, e = _ass_ts(ev.get("start", "")), _ass_ts(ev.get("end", ""))
            if s is None or e is None:
                continue
            st = styles.get(ev.get("style", ""), {})
            raw_text = ev.get("text", "")
            if re.search(r"\\p[1-9]", raw_text):
                continue  # a vector drawing (a caption plate), not text
            align = _num(st.get("alignment")) or 2
            m = re.search(r"\\an(\d)", raw_text)
            if m:
                align = int(m.group(1))
            pos = None
            m = re.search(r"\\pos\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", raw_text)
            if m:
                pos = (float(m.group(1)), float(m.group(2)))
            mv = _num(ev.get("marginv")) or _num(st.get("marginv")) or 0
            ml = _num(ev.get("marginl")) or _num(st.get("marginl")) or 0
            mr = _num(ev.get("marginr")) or _num(st.get("marginr")) or 0
            plain = re.sub(r"\{[^}]*\}", "", raw_text).replace("\\h", " ")
            lines = [x.strip() for x in re.split(r"\\[Nn]", plain) if x.strip()]
            cues.append({"start": s, "end": e, "text": " ".join(lines), "lines": lines, "align": int(align),
                         "margin_v": mv, "margin_l": ml, "margin_r": mr, "pos": pos,
                         "size": _num(st.get("fontsize"))})
    cues.sort(key=lambda c: c["start"])
    pr = (play[0], play[1]) if play[0] and play[1] else None
    return {"format": "ass", "cues": cues, "play_res": pr}


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def safe_box(width: int, height: int) -> Tuple[float, float, float, float]:
    """(left, top, right, bottom) in pixels where text is not covered by platform UI
    (the same box the caption writers use: st.captions_rules.safe_box)."""
    return R.safe_box(width, height)


def check(cap: Dict[str, Any], duration: Optional[float], width: Optional[int], height: Optional[int],
          source: str = "") -> List[Dict[str, Any]]:
    """Findings (dicts with rule, severity, t, message, fix) for one caption file."""
    out: List[Dict[str, Any]] = []
    cues = cap.get("cues") or []
    tag = " (%s)" % source if source else ""

    def add(rule: str, sev: str, t: Optional[float], msg: str, fix: str = "") -> None:
        out.append({"rule": rule, "severity": sev, "t": t, "message": msg + tag, "fix": fix})

    if not cues:
        add("captions_empty", "WARN", None, "the caption file has no cues", "re-export the captions")
        return out
    # one caption cut into pieces (an edit moves it where the frame's layout changes: a card's split, the face)
    # is read as one caption for its timing: same text, each piece starting where the one before ends
    whole: Dict[int, Tuple[float, float]] = {}
    i = 0
    while i < len(cues):
        j = i
        while j + 1 < len(cues) and cues[j + 1]["text"] == cues[i]["text"] and abs(cues[j + 1]["start"] - cues[j]["end"]) < 0.02:
            j += 1
        for k in range(i, j + 1):
            whole[k] = (cues[i]["start"], cues[j]["end"])
        i = j + 1
    vertical = R.is_vertical(width, height)
    max_chars = R.max_line_chars(width, height)
    seen = set()
    prev = None
    fast: List[Dict[str, Any]] = []
    long_cues: List[Tuple[Dict[str, Any], str]] = []
    for ci, c in enumerate(cues):
        s, e = c["start"], c["end"]
        if duration and (s >= duration or e > duration + 0.25) and "end" not in seen:
            seen.add("end")
            add("captions_past_end", "FAIL", s, "caption \"%s\" runs to %.2fs but the video ends at %.2fs" % (
                _snip(c["text"]), e, duration), "re-time the captions to the final edit (captions --edl)")
        if e - s <= 0 and "neg" not in seen:
            seen.add("neg")
            add("captions_timing", "FAIL", s, "caption \"%s\" ends before it starts" % _snip(c["text"]))
        if prev is not None and s < prev["end"] - 0.05 and "ov" not in seen and c.get("align") == prev.get("align") \
                and c.get("pos") == prev.get("pos"):
            seen.add("ov")
            add("captions_overlap", "WARN", s, "captions overlap at %.2fs (\"%s\" / \"%s\")" % (
                s, _snip(prev["text"], 20), _snip(c["text"], 20)), "end each cue before the next starts")
        lines = c.get("lines") or [c["text"]]
        if len(lines) > R.MAX_LINES and "lines" not in seen:
            seen.add("lines")
            add("caption_lines", "WARN", s, "caption at %.2fs has %d lines (max %d)" % (s, len(lines), R.MAX_LINES),
                "split it into two cues")
        long = [ln for ln in lines if len(ln) > max_chars]
        if long:
            long_cues.append((c, max(long, key=len)))
        ws_, we_ = whole.get(ci, (s, e))
        if R.too_fast(c["text"], max(1e-3, we_ - ws_)) and (ci == 0 or whole.get(ci - 1) != whole[ci]):   # one per caption
            fast.append(c)
        if width and height and "bounds" not in seen:
            problem = _placement(c, cap.get("play_res"), width, height)
            if problem:
                seen.add("bounds")
                add("caption_bounds", "WARN", s, "caption \"%s\" %s" % (_snip(c["text"]), problem),
                    "move the caption band inside the safe box (see platforms.md, vertical safe zones)")
        prev = c
    # every long line and every fast cue is listed (one finding each, up to LIST_MAX), so one qa run
    # shows all of them instead of one per run
    for i, (c, ln) in enumerate(long_cues[:LIST_MAX]):
        more = " (%d of %d long lines)" % (i + 1, len(long_cues)) if len(long_cues) > 1 else ""
        add("caption_line_long", "WARN", c["start"], "caption line of %d characters at %.2fs (max %d%s): \"%s\"%s" % (
            len(ln), c["start"], max_chars, " for vertical" if vertical else "", _snip(ln), more),
            "break the line earlier or shorten it" + (_rest(long_cues[LIST_MAX:]) if i == LIST_MAX - 1 else ""))
    for i, c in enumerate(fast[:LIST_MAX]):
        d = max(1e-3, c["end"] - c["start"])
        more = " (%d of %d fast cues)" % (i + 1, len(fast)) if len(fast) > 1 else ""
        add("caption_fast", "WARN", c["start"], "caption at %.2fs needs %.0f characters/s to read (max %g): \"%s\"%s" % (
            c["start"], R.cps(c["text"], d), R.MAX_CPS, _snip(c["text"]), more),
            "hold it longer or split it" + (_rest([(x, "") for x in fast[LIST_MAX:]]) if i == LIST_MAX - 1 else ""))
    # flashes: cues too short to read at all (a writer that splits fast speech into 1-word cues passes
    # the reading-speed rule by its exemption; this catches it)
    flashes = [c for k, c in enumerate(cues) if 0 < whole[k][1] - whole[k][0] < R.FLASH_S]
    if flashes:
        worst = min(flashes, key=lambda c: c["end"] - c["start"])
        add("caption_flash", "WARN", worst["start"], "%d cue(s) are on screen for less than %.1fs (shortest %.2fs at %.2fs: "
            "\"%s\")" % (len(flashes), R.FLASH_S, worst["end"] - worst["start"], worst["start"], _snip(worst["text"])),
            "merge each into a neighbour (showtime captions merges cues under 0.7 s by default)")
    return out


LIST_MAX = 12   # findings listed per rule and file; the rest are counted in the last one


def _rest(items: List[Any]) -> str:
    if not items:
        return ""
    ts = [x[0]["start"] if isinstance(x, tuple) else x["start"] for x in items]
    return " (and %d more at %s)" % (len(ts), ", ".join("%.2fs" % t for t in ts[:20]) + (" ..." if len(ts) > 20 else ""))


def summary(cap: Dict[str, Any]) -> Dict[str, Any]:
    """Cue count, shortest cue and the number under the flash limit (for the qa report)."""
    cues = cap.get("cues") or []
    durs = [c["end"] - c["start"] for c in cues if c["end"] > c["start"]]
    return {"cues": len(cues), "shortest_s": round(min(durs), 3) if durs else None,
            "under_flash": sum(1 for d in durs if d < R.FLASH_S)}


def stats(cap: Dict[str, Any]) -> Dict[str, Any]:
    """Longest line (characters), fastest reading speed (characters/s, cues the reading-speed rule covers)
    and shortest cue of a parsed caption file: the numbers the phone-check summary quotes."""
    cues = cap.get("cues") or []
    longest = max((len(ln) for c in cues for ln in (c.get("lines") or [c["text"]])), default=0)
    speeds = [R.cps(c["text"], c["end"] - c["start"]) for c in cues
              if c["end"] > c["start"] and len(c["text"].split()) >= R.CPS_MIN_WORDS]
    return {"cues": len(cues), "longest_line": longest, "max_cps": round(max(speeds), 1) if speeds else None,
            "shortest_s": summary(cap)["shortest_s"]}


def _placement(c: Dict[str, Any], play_res: Optional[Tuple[float, float]], W: int, H: int) -> Optional[str]:
    left, top, right, bottom = safe_box(W, H)
    sx = W / play_res[0] if play_res else 1.0
    sy = H / play_res[1] if play_res else 1.0
    align = c.get("align")
    if c.get("pos"):
        x, y = c["pos"][0] * sx, c["pos"][1] * sy
        if y > bottom + 2:
            return "is anchored at y=%d, below the safe line y=%d (platform UI covers it)" % (y, bottom)
        if y < top - 2:
            return "is anchored at y=%d, above the safe line y=%d" % (y, top)
        if x < left - 2 or x > right + 2:
            return "is anchored at x=%d, outside the safe band x=%d-%d" % (x, left, right)
        return None
    if isinstance(align, int) and c.get("margin_v") is not None:
        mv = float(c["margin_v"]) * sy
        if align in (1, 2, 3) and H - mv > bottom + 2:
            return "sits %dpx above the bottom edge; the safe line is %dpx up (platform UI covers it)" % (mv, H - bottom)
        if align in (7, 8, 9) and mv < top - 2:
            return "sits %dpx below the top edge; keep it at least %dpx down" % (mv, top)
    return None


def _snip(s: str, n: int = 36) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def find_sidecars(video: Path, project: Optional[Path] = None, extra: Sequence[str] = ()) -> List[Path]:
    """Caption files that belong to a video: <stem>.srt/.vtt/.ass beside it, captions/ in the job or project."""
    found: List[Path] = []
    for x in extra:
        p = Path(x)
        if p.is_file():
            found.append(p)
    exts = (".srt", ".vtt", ".ass")
    for ext in exts:
        for cand in (video.with_suffix(ext), video.parent / ("captions" + ext), video.parent / ("subs" + ext)):
            if cand.is_file():
                found.append(cand)
    for d in [video.parent / "captions"] + ([project / "captions", project] if project else []):
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in exts and p.is_file():
                    found.append(p)
    uniq: List[Path] = []
    for p in found:
        if p.resolve() not in [u.resolve() for u in uniq]:
            uniq.append(p)
    return uniq[:6]
