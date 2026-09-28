"""takes_packed.md: every transcript of a shoot as compact, phrase-level text.

This is what Claude reads to understand the material and pick ranges.
A phrase ends at a pause >= 0.5 s (configurable) or a speaker change.

    ## take1  (source: take1.mp4, 42.1 s, 12 phrases, speakers S0 S1, 5 fillers)
    [002.40-007.95 w0-w14] S0 So, um, today I want to show you something new.
    [009.10-015.30 w15-w31] S0 Uh, it's a tool that edits video (laughter) by reading the transcript.

Times are seconds in the source file; wN ids let an EDL or `edit cut
--remove w3-w5` refer to exact words.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import ShowtimeError, ensure_dir
from . import util as U

HEADER = """# Takes (packed transcripts)

Each line is one phrase: `[start-end wFirst-wLast] SPEAKER text`, times in seconds of that source file.
Phrases break at pauses >= {gap:.1f} s or on a speaker change. `(laughter)` etc. are audio events.
Fillers (um, uh ...) are kept verbatim: they are edit points, not errors. Use word ids with
`showtime edit cut --remove w12-w18`, or copy times into EDL ranges (pad cuts 50-150 ms).
"""


def phrases(words: List[Dict[str, Any]], gap: float = 0.5) -> List[Dict[str, Any]]:
    toks = [w for w in words if w.get("type", "word") in ("word", "audio_event")]
    toks.sort(key=lambda w: w["start"])
    out: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []
    for w in toks:
        if cur:
            prev = cur[-1]
            spk_change = (w.get("type") == "word" and prev.get("type") == "word" and w.get("speaker")
                          and prev.get("speaker") and w["speaker"] != prev["speaker"])
            if w["start"] - max(x["end"] for x in cur) >= gap or spk_change:
                out.append(_phrase(cur))
                cur = []
        cur.append(w)
    if cur:
        out.append(_phrase(cur))
    return out


def _phrase(ws: List[Dict[str, Any]]) -> Dict[str, Any]:
    text = " ".join(w["text"] if w.get("type") == "word" else ("(%s)" % w["text"].strip("()[] "))
                    for w in ws)
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    ids = [w.get("id") for w in ws if w.get("id")]
    spk = next((w.get("speaker") for w in ws if w.get("type") == "word" and w.get("speaker")), None)
    return {"start": ws[0]["start"], "end": max(w["end"] for w in ws), "text": text,
            "ids": (ids[0], ids[-1]) if ids else None, "speaker": spk}


def pack_one(tr: Dict[str, Any], name: str, gap: float = 0.5, ids: bool = True) -> str:
    ph = phrases(tr.get("words", []), gap)
    words = U.words_of(tr)
    lang = tr.get("language") or "en"
    fillers = sum(1 for w in words if U.is_filler(w["text"], lang))
    speakers = sorted({w.get("speaker") for w in words if w.get("speaker")})
    long_pauses = sum(1 for a, b in zip(ph, ph[1:]) if b["start"] - a["end"] >= 1.5)
    src = Path(tr.get("source") or name).name
    rng = tr.get("range")
    span = ("%.1f-%.1f s (part)" % (rng[0], rng[1])) if rng else "%.1f s" % float(tr.get("duration") or 0.0)
    head = "## %s  (source: %s, %s, %d phrases%s, %d fillers, %d pauses >= 1.5 s%s)" % (
        name, src, span, len(ph),
        (", speakers " + " ".join(speakers)) if len(speakers) > 1 else "", fillers, long_pauses,
        (", model " + str(tr.get("model"))) if tr.get("model") else "")
    lines = [head]
    warns = (tr.get("guards") or {}).get("warnings") or []
    for w in warns:
        lines.append("> warning: %s" % w)
    width = 3 if float(tr.get("duration") or 0) < 1000 else 4
    for p in ph:
        rng = "%0*.2f-%0*.2f" % (width + 3, p["start"], width + 3, p["end"])
        idp = (" %s-%s" % p["ids"]) if ids and p["ids"] else ""
        spk = (p["speaker"] + " ") if p["speaker"] else ""
        lines.append("[%s%s] %s%s" % (rng, idp, spk, p["text"]))
    return "\n".join(lines) + "\n"


def pack(edit_dir, out=None, gap: float = 0.5, ids: bool = True, files: Optional[Sequence] = None) -> Dict[str, Any]:
    ed = Path(edit_dir)
    if files:
        paths = [Path(f) for f in files]
    else:
        tdir = ed / "transcripts" if (ed / "transcripts").is_dir() else ed
        paths = sorted(p for p in tdir.glob("*.json") if not p.name.endswith((".words.json", ".report.json")))
    if not paths:
        raise ShowtimeError("no transcripts found in %s" % (ed / "transcripts"),
                            hint="run `showtime transcribe <media...>` first")
    parts = [HEADER.format(gap=gap)]
    total, n_ph = 0.0, 0
    for p in paths:
        tr = U.load_transcript(p)
        parts.append(pack_one(tr, p.stem, gap, ids))
        rng = tr.get("range")
        total += (float(rng[1]) - float(rng[0])) if rng else float(tr.get("duration") or 0.0)
        n_ph += len(phrases(tr.get("words", []), gap))
    text = "\n".join(parts)
    out = Path(out) if out else (ed if ed.is_dir() else ed.parent) / "takes_packed.md"
    ensure_dir(out.parent)
    out.write_text(text, encoding="utf-8")
    return {"output": str(out), "takes": len(paths), "phrases": n_ph, "seconds": round(total, 1),
            "chars": len(text)}
