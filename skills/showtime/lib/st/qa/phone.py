"""The phone check in `showtime qa`: one line that says whether the video's text is readable on a phone.

Four parts, all named in references/qa.md ("phone check"):

  type size     the smallest text as it lands on a phone (points at 390 pt wide)      from `showtime check`
  reading time  every text on screen long enough to read, at a speed per language      from `showtime check`
  UI zones      nothing readable under platform UI (9:16 rails, control strip, edges)  from `showtime check`
  captions      line length, reading speed, flashes and placement of caption sidecars  measured here, on the files

qa cannot read pixels back into text, so the first three come from the project's last `showtime check`
report (work/check/report.json, its "phone" block; the per-frame findings are in the same report). Without
one the line says PARTIAL and names what is missing; captions are always judged on the sidecar files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import read_json

# caption rules (st.qa.captions.check) that belong to the phone check
CAPTION_RULES = ("caption_lines", "caption_line_long", "caption_fast", "caption_flash", "caption_bounds")
CAPTION_WORDS = {"caption_lines": "more than two lines", "caption_line_long": "line too long", "caption_fast": "too fast to read",
                 "caption_flash": "on screen under 0.4 s", "caption_bounds": "outside the safe box"}
PART_RULE = {"size": "phone_size", "reading": "phone_reading", "zone": "phone_zone"}
PART_FIX = {
    "size": "enlarge the text (or cut it, or mark UI-mockup detail as decor), then showtime check",
    "reading": "hold it longer, shorten it, or mark it data-caption when the voice reads it; then showtime check",
    "zone": "move it inside the platform's safe box (references/platforms.md, vertical safe zones); then showtime check",
}


def _clock(t: Optional[float]) -> str:
    if t is None:
        return ""
    m, s = divmod(float(t), 60.0)
    return "%d:%04.1f" % (int(m), s)


def check_report(proj: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The project's last `showtime check` report with a phone block: {"phone", "width", "height", "path", "stale"}."""
    if not proj:
        return None
    rp = Path(proj) / "work" / "check" / "report.json"
    data = read_json(rp, None) if rp.is_file() else None
    if not isinstance(data, dict) or not isinstance(data.get("phone"), dict):
        return None
    newest = 0.0
    for p in Path(proj).iterdir():
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".mjs") and p.name != "showtime.json":
            newest = max(newest, p.stat().st_mtime)
    info = data.get("info") or {}
    return {"phone": data["phone"], "width": info.get("width"), "height": info.get("height"), "path": str(rp),
            "stale": rp.stat().st_mtime < newest}


def _aspect(w: Any, h: Any) -> Optional[str]:
    try:
        r = float(w) / float(h)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return "9:16" if r <= 0.62 else "4:5" if r <= 0.9 else "1:1" if r <= 1.1 else "16:9"


def _describe(it: Dict[str, Any]) -> str:
    """One failing item as a short phrase with its timestamp."""
    at = (" at " + _clock(it.get("t"))) if it.get("t") is not None else ""
    msg = it.get("message") or ""
    q = msg.split('"')[1] if msg.count('"') >= 2 else ""
    part = it.get("part")
    if part == "size":
        return ("type: %s texts under the minimum%s" % (it["count"], at)) if it.get("count") else 'type %s pt "%s"%s' % (it.get("pt", "?"), q, at)
    if part == "reading":
        return 'reading "%s" %ss of %ss%s' % (q, it.get("held", "?"), it.get("need", "?"), at)
    what = {"control_strip": "under the player controls", "edge_margin": "at the frame edge"}.get(it.get("code"), "under platform UI")
    return '%s "%s"%s' % (what, q, at)


def evaluate(F: Any, vpath: Path, proj: Optional[Path], W: int, H: int, cap_files: Sequence[Path],
             cap_items: Sequence[Dict[str, Any]], cap_stats: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Add the phone-check findings to `F` and return the summary for the report ({"verdict", "line", ...}).

    cap_items: the caption findings of this run (dicts with rule, severity, message, t); cap_stats: one
    st.qa.captions.stats() dict per caption file."""
    items: List[Dict[str, Any]] = []
    notes: List[str] = []
    cr = check_report(proj)
    ph = cr["phone"] if cr else None
    usable = False
    if ph is None:
        notes.append("type size, reading time and UI zones need `showtime check <project>` (no report with a phone block%s)" %
                     ("" if proj else "; no project found for this video"))
    elif _aspect(cr.get("width"), cr.get("height")) != _aspect(W, H):
        notes.append("the last showtime check ran at %sx%s but this video is %sx%s: check the project at this size" % (
            cr.get("width"), cr.get("height"), W, H))
    else:
        usable = True
        if cr["stale"]:
            notes.append("the last showtime check is older than the project sources: run it again")
        chk = ph.get("checked") or {}
        for it in ph.get("items") or []:
            part = it.get("part")
            items.append(it)
            F.add(PART_RULE.get(part, "phone_zone"), "WARN", it.get("message", ""), t=it.get("t"), fix=PART_FIX.get(part, ""),
                  source="showtime check")
        if not chk.get("reading", True):
            notes.append("reading time was not checked (showtime check ran with --no-timeline)")
    # captions: judged on the sidecar files (their findings are already in F under their own rule ids)
    cap_bad = [f for f in cap_items if f.get("rule") in CAPTION_RULES and f.get("severity") in ("WARN", "FAIL")]
    cap_line = ""
    if cap_files:
        cues = sum(s["cues"] for s in cap_stats)
        longest = max((s["longest_line"] for s in cap_stats), default=0)
        speeds = [s["max_cps"] for s in cap_stats if s.get("max_cps") is not None]
        cap_line = "captions: %d cues, longest line %d characters%s" % (
            cues, longest, (", fastest %.0f characters/s" % max(speeds)) if speeds else "")
    failing = [_describe(i) for i in items]
    for f in cap_bad:
        failing.append('caption %s%s' % (CAPTION_WORDS.get(f["rule"], f["rule"]),
                                          (" at " + _clock(f.get("t"))) if f.get("t") is not None else ""))
    if failing:
        verdict = "FAIL"
        shown = "; ".join(failing[:6]) + ("; and %d more" % (len(failing) - 6) if len(failing) > 6 else "")
        line = "phone check: FAIL - " + shown
        if notes:
            line += " (" + "; ".join(notes) + ")"
    else:
        good: List[str] = []
        if usable:
            sm = ph.get("smallest")
            good.append(("smallest text %s pt (minimum %s pt for %s)" % (sm["pt"], ph.get("min_pt"), ph.get("aspect")))
                        if sm else ("minimum %s pt for %s" % (ph.get("min_pt"), ph.get("aspect"))))
            rd = ph.get("reading") or {}
            if (ph.get("checked") or {}).get("reading", True):
                good.append("every text held to its reading time at %g characters/s%s (%s)" % (
                    rd.get("cps") or 0, (" or %g words/s" % rd["wps"]) if rd.get("wps") else "", ph.get("lang")))
            good.append("nothing under platform UI")
        if cap_line:
            good.append(cap_line)
        verdict = "PASS" if usable else "PARTIAL"
        line = "phone check: %s (%s)" % (verdict, "; ".join(good + notes)) if (good or notes) else "phone check: PARTIAL (nothing to verify)"
    if not usable:
        F.add("phone_unverified", "INFO", "the phone check could not verify: " + "; ".join(notes),
              fix="run showtime check <project> (at this video's size), then qa again")
    return {"verdict": verdict, "line": line, "items": items, "captions": cap_stats and {
        "files": [str(p) for p in cap_files], "bad": [f["rule"] for f in cap_bad]} or None,
            "check_report": cr["path"] if cr else None, "stale": bool(cr and cr["stale"]), "notes": notes}
