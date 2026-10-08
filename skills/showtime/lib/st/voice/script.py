"""`showtime voice script`: a narration script -> per-line clips, one
combined vo.wav and timeline.json, so scene lengths come from the real voice.

Input: JSON or Markdown (or plain text: one line per paragraph).

JSON:
    {"voice": "af_heart", "speed": 1.0, "style": "neutral", "gap": 0.35,
     "lead_in": 0.0, "tail": 0.6, "lufs": -16,
     "lines": [
        {"id": "hook", "text": "Meet Showtime. [pause 0.3] It lives in your terminal."},
        {"id": "demo", "text": "Point it at any project.", "voice": "am_michael",
         "speed": 1.05, "style": "upbeat", "pause_after": 0.8, "fit": 3.5, "at": 6.0}
     ]}
  (a bare list of such lines, or of strings, also works)

Markdown:
    ---
    voice: af_heart
    gap: 0.4
    ---
    ## hook
    Meet Showtime. [pause 0.3] It lives in your terminal.

    ## demo {voice=am_michael speed=1.05 pause_after=0.8}
    Point it at any project.

  Without headings every paragraph is a line. HTML comments and "> " quote
  lines are director's notes and are never spoken.

Per-line keys: id, text, voice, speed, style, lang, engine, pause_after
(seconds of silence after the line; default = gap), fit (target seconds:
the speed is adjusted, within 0.8-1.25x, to land near it), at (pin the line
to start at this absolute time; later lines follow it).

Whole-script fit (top-level "fit": 15, or `voice script --fit 15`): every line
speeds up or slows down together within 0.85-1.15x, then the pauses shrink
(never below 0.2 s; tail 0.3 s), then the report says how many words to cut.
A script that is short is padded with tail silence so vo.wav lasts exactly
the target. timeline.json gets a "fit" block with what was done.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .. import captions_rules as R
from ..common import ShowtimeError, info, portable_path, slugify, warn, write_json
from . import SAMPLE_RATE_OUT, TIMELINE_VERSION
from . import audio_io as aio
from . import lexicon as lexmod
from . import tts
from .textnorm import plain_text

PathLike = Union[str, "os.PathLike[str]"]
LINE_KEYS = {"id", "text", "voice", "speed", "style", "lang", "engine", "pause_after", "fit", "at", "notes"}
DEFAULTS = {"voice": None, "speed": 1.0, "style": "neutral", "lang": None, "engine": None, "gap": 0.35,
            "lead_in": 0.0, "tail": 0.6, "lufs": -16.0, "master": True, "lexicon": None, "fit": None}


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _coerce(v: str) -> Any:
    s = v.strip().strip('"').strip("'")
    if s.lower() in ("true", "yes", "on"):
        return True
    if s.lower() in ("false", "no", "off"):
        return False
    if s.lower() in ("null", "none", ""):
        return None
    try:
        return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else s
    except ValueError:
        return s


def _attrs(s: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for m in re.finditer(r"([A-Za-z_]+)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,}]+)", s):
        out[m.group(1)] = _coerce(m.group(2))
    return out


def parse_markdown(text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    text = re.sub(r"<!--.*?-->", " ", text.replace("\r\n", "\n"), flags=re.S)
    cfg: Dict[str, Any] = {}
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln and not ln.strip().startswith("#"):
                k, v = ln.split(":", 1)
                cfg[k.strip()] = _coerce(v)
        text = text[m.end():]
    lines: List[Dict[str, Any]] = []
    has_headings = bool(re.search(r"^#{1,6}\s+\S", text, re.M))
    cur: Optional[Dict[str, Any]] = None
    buf: List[str] = []

    def flush() -> None:
        nonlocal cur, buf
        body = " ".join(" ".join(buf).split())
        if cur is not None:
            if body:
                cur["text"] = body
                lines.append(cur)
        elif body:
            lines.append({"text": body})
        cur, buf = None, []

    for raw in text.split("\n"):
        ln = raw.rstrip()
        if ln.lstrip().startswith(">"):
            continue
        h = re.match(r"^#{1,6}\s+(.*?)\s*(\{[^}]*\})?\s*$", ln)
        if h:
            flush()
            title = h.group(1).strip()
            cur = {"id": slugify(title, 40, default="") or None, "title": title}
            if h.group(2):
                cur.update(_attrs(h.group(2)))
            continue
        if not ln.strip():
            if not has_headings:
                flush()
            continue
        buf.append(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln))
    flush()
    return cfg, lines


def load_script(path: PathLike) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    p = Path(path)
    if not p.is_file():
        raise ShowtimeError("script not found: %s" % p)
    raw = p.read_text(encoding="utf-8-sig")  # -sig: a BOM (Windows PowerShell 5.1, Notepad) would hide the first heading
    if p.suffix.lower() == ".json" or raw.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise ShowtimeError("invalid JSON in %s: %s" % (p, e))
        if isinstance(data, list):
            cfg, lines = {}, data
        elif isinstance(data, dict):
            cfg = {k: v for k, v in data.items() if k != "lines"}
            lines = data.get("lines") or []
        else:
            raise ShowtimeError("%s: expected an object with \"lines\" or a list of lines" % p)
        lines = [{"text": ln} if isinstance(ln, str) else dict(ln) for ln in lines]
    else:
        cfg, lines = parse_markdown(raw)
    return cfg, lines


# the same word either side of a sentence break ("One. One plus three is four.") sounds like a stutter
STUTTER_RE = re.compile(r"\b(\w+)[.!?;:]\s+\1\b", re.I | re.U)


def normalize(cfg: Dict[str, Any], lines: List[Dict[str, Any]], overrides: Dict[str, Any]
              ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    c = dict(DEFAULTS)
    c.update({k: v for k, v in cfg.items() if v is not None})
    c.update({k: v for k, v in overrides.items() if v is not None})
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, ln in enumerate(lines, 1):
        if not isinstance(ln, dict) or not str(ln.get("text", "")).strip():
            raise ShowtimeError("line %d has no text" % i)
        unknown = set(ln) - LINE_KEYS - {"title"}
        if unknown:
            warn("line %d: ignoring unknown keys %s" % (i, ", ".join(sorted(unknown))))
        lid = str(ln.get("id") or "line-%02d" % i)
        lid = slugify(lid, 40, default="line-%02d" % i)
        if lid in seen:
            lid = "%s-%d" % (lid, i)
        seen.add(lid)
        item = {"id": lid, "index": i, "text": str(ln["text"]).strip()}
        m = STUTTER_RE.search(item["text"])
        if m:
            warn("line %s: \"%s\" is heard as \"%s %s\" (the listener hears no full stop): say it once, or "
                 "change the second (\"Start with one. Add three: four.\")" % (lid, m.group(0), m.group(1), m.group(1)))
        for k in ("voice", "speed", "style", "lang", "engine"):
            item[k] = ln.get(k) if ln.get(k) is not None else c.get(k)
        item["speed"] = float(item["speed"] or 1.0)
        item["pause_after"] = float(ln["pause_after"]) if ln.get("pause_after") is not None else float(c["gap"])
        if ln.get("fit") is not None:
            item["fit"] = float(ln["fit"])
        if ln.get("at") is not None:
            item["at"] = float(ln["at"])
        out.append(item)
    if not out:
        raise ShowtimeError("the script has no lines to speak")
    return c, out



# --------------------------------------------------------------------------
# Synthesis, layout and whole-script fitting
# --------------------------------------------------------------------------

FIT_SPEED = (0.85, 1.15)     # natural delivery: never faster or slower than this (x each line's own speed)
FIT_MIN_PAUSE = 0.2          # a pause between lines is never trimmed below this (s)
FIT_MIN_TAIL = 0.3           # nor the tail after the last line
FIT_FAST = 1.1               # above this effective speed (line speed x fit factor) the fit warns: sounds rushed


def _synth_all(lines: List[Dict[str, Any]], lex, factor: float, quiet: bool = False
               ) -> List[Tuple[Dict[str, Any], "tts.Speech"]]:
    """Synthesize every line; lines without their own `fit` run at speed x factor."""
    clips: List[Tuple[Dict[str, Any], tts.Speech]] = []
    n = len(lines)
    for ln in lines:
        t0 = time.time()
        kw = dict(voice=ln["voice"], lang=ln["lang"], engine=ln["engine"], lexicon=lex, style=ln["style"])
        if "fit" in ln:
            speech = tts.fit_to(ln["text"], ln["fit"], speed=ln["speed"], **kw)
        else:
            speech = tts.synthesize(ln["text"], speed=round(ln["speed"] * factor, 3), **kw)
        if not quiet:
            info("line %d/%d %-14s %5.2fs  %s%s" % (
                ln["index"], n, ln["id"], speech.duration,
                "cached" if speech.cached else "%.1fs" % (time.time() - t0),
                ("  (fit %.2fs)" % ln["fit"]) if "fit" in ln else
                ("  (speed x%.2f)" % factor if abs(factor - 1.0) > 1e-3 else "")))
        clips.append((ln, speech))
    return clips


def _layout(clips: List[Tuple[Dict[str, Any], "tts.Speech"]], c: Dict[str, Any], warn_overlap: bool = True
            ) -> Tuple[List[Tuple[Dict[str, Any], "tts.Speech", float]], float]:
    """Place each clip (pauses, `at` pins). -> (placed [(line, speech, start)], total seconds)."""
    cursor = float(c["lead_in"])
    placed: List[Tuple[Dict[str, Any], tts.Speech, float]] = []
    for ln, speech in clips:
        if "at" in ln:
            if ln["at"] + 1e-6 < cursor and warn_overlap:
                warn("line %s: at=%.2fs overlaps the previous line (ends %.2fs); starting at %.2fs"
                     % (ln["id"], ln["at"], cursor, cursor))
            cursor = max(cursor, ln["at"])
        placed.append((ln, speech, cursor))
        cursor += speech.duration + ln["pause_after"]
    total = placed[-1][2] + placed[-1][1].duration + float(c["tail"])
    return placed, total


def _speech_words(clips) -> Tuple[int, float]:
    """(words, seconds of speech from each line's first word to its last)."""
    n, secs = 0, 0.0
    for _, sp in clips:
        if sp.words:
            n += len(sp.words)
            secs += max(0.0, sp.words[-1]["end"] - sp.words[0]["start"])
    return n, secs


def fit_total(lines: List[Dict[str, Any]], lex, clips, c: Dict[str, Any], target: float
              ) -> Tuple[List[Tuple[Dict[str, Any], "tts.Speech"]], Dict[str, Any]]:
    """Fit the whole narration to `target` seconds.

    1. scale every line's speed by one factor within FIT_SPEED (0.85-1.15x;
       lines with their own `fit` keep it), re-synthesizing until the total
       lands within max(0.1 s, 1 %) of the target;
    2. if still long, shorten the pauses between lines (never below
       FIT_MIN_PAUSE) and the tail (never below FIT_MIN_TAIL);
    3. if still long, report how many words to cut (at the measured words/s);
       if short, pad the tail so vo.wav lasts exactly `target` and report how
       many words would fill the gap.
    Mutates the lines' pause_after and c["tail"]. -> (clips, report)."""
    if target <= 0:
        raise ShowtimeError("--fit must be a positive number of seconds")
    tol = max(0.1, 0.01 * target)
    _, before = _layout(clips, c, warn_overlap=False)
    rep: Dict[str, Any] = {"target": round(target, 3), "before": round(before, 3), "speed_factor": 1.0,
                           "pauses_trimmed": 0.0, "tail_padded": 0.0, "over": 0.0, "under": 0.0,
                           "cut_words": 0, "add_words": 0, "tolerance": round(tol, 3)}
    # engine speed limits (e.g. Kokoro 0.5-2.0) on top of the natural range
    lo, hi = FIT_SPEED
    try:
        for ln in lines:
            if "fit" in ln:
                continue
            spec = tts.voices.resolve(ln["voice"], ln["lang"], ln["engine"])
            elo, ehi = tts.get_engine(spec.engine).speed_range
            lo = max(lo, elo / max(ln["speed"], 1e-3))
            hi = min(hi, ehi / max(ln["speed"], 1e-3))
    except Exception:  # noqa: BLE001 - limits are advisory; synthesis reports real engine errors
        pass
    free = [i for i, ln in enumerate(lines) if "fit" not in ln]
    factor = 1.0
    total = before
    if free and abs(total - target) > tol:
        for _ in range(4):
            speech_free = sum(clips[i][1].duration for i in free)
            other = total - speech_free
            need = target - other
            new = hi if need <= 0.05 else factor * speech_free / need
            new = round(min(max(new, lo), hi), 3)
            if abs(new - factor) < 0.004:
                break
            if factor == 1.0:
                info("fit %.2fs: narration is %.2fs, so the speed changes: all %d line%s re-synthesize at each "
                     "try (up to 4; each try's lines are cached)" % (target, total, len(free),
                                                                     "" if len(free) == 1 else "s"))
            factor = new
            info("fit %.2fs: narration is %.2fs; trying speed x%.2f" % (target, total, factor))
            clips = _synth_all(lines, lex, factor, quiet=True)
            _, total = _layout(clips, c, warn_overlap=False)
            if abs(total - target) <= tol:
                break
    rep["speed_factor"] = factor
    # 2. pauses (also for a small overshoot inside the tolerance: the result should be the target)
    if total > target + 0.005:
        pool = [(k, lines[k]["pause_after"], min(lines[k]["pause_after"], FIT_MIN_PAUSE))
                for k in range(len(lines) - 1)]
        slack = sum(p - f for _, p, f in pool)
        tail0 = float(c["tail"])
        tail_floor = min(tail0, FIT_MIN_TAIL)
        slack += tail0 - tail_floor
        if slack > 1e-3:
            r = min(1.0, (total - target) / slack)
            for k, p, f in pool:
                lines[k]["pause_after"] = round(p - (p - f) * r, 3)
            c["tail"] = round(tail0 - (tail0 - tail_floor) * r, 3)
            clips = [(ln, sp) for ln, (_, sp) in zip(lines, clips)]
            _, t2 = _layout(clips, c, warn_overlap=False)
            rep["pauses_trimmed"] = round(total - t2, 3)
            total = t2
    n_words, speech_s = _speech_words(clips)
    wps = n_words / max(speech_s, 1e-3)
    rep["words"] = n_words
    rep["wps"] = round(wps, 2)
    if total > target + tol:
        rep["over"] = round(total - target, 3)
        rep["cut_words"] = int(np.ceil(rep["over"] * wps))
    elif total < target - 0.005:
        # short (or inside the tolerance but short): pad the tail so vo.wav lasts exactly the target
        if total < target - tol:
            rep["under"] = round(target - total, 3)
            rep["add_words"] = int(rep["under"] * wps)
        rep["tail_padded"] = round(target - total, 3)
        c["tail"] = round(float(c["tail"]) + target - total, 3)
    # fitting by speed alone can make the voice rushed: say so, and how many words to cut instead
    eff = max([lines[i]["speed"] * factor for i in free] or [0.0])
    rep["max_speed"] = round(eff, 3)
    if eff > FIT_FAST + 1e-6:
        rep["fast"] = True
        rep["cut_words_at_1x"] = int(np.ceil(max(0.0, before - target) * wps))
    return clips, rep


def fit_message(rep: Dict[str, Any]) -> str:
    """One human line for a fit report (after build() filled in `result`)."""
    parts = []
    if abs(rep["speed_factor"] - 1.0) > 1e-3:
        parts.append("speed x%.2f" % rep["speed_factor"])
    if rep["pauses_trimmed"] > 0:
        parts.append("pauses -%.2fs" % rep["pauses_trimmed"])
    if rep["tail_padded"] > 0:
        parts.append("tail +%.2fs of silence" % rep["tail_padded"])
    how = ", ".join(parts) or "no change needed"
    msg = "fit %.2fs: %.2fs -> %.2fs (%s)" % (rep["target"], rep["before"], rep["result"], how)
    if rep["over"] > 0:
        msg += ("\n  still %.2fs over at the fastest natural speed (x%.2f) with pauses at their minimum:"
                " cut about %d word%s (of %d; the voice speaks %.1f words/s), then run it again"
                % (rep["over"], rep["speed_factor"], rep["cut_words"], "" if rep["cut_words"] == 1 else "s",
                   rep["words"], rep["wps"]))
    elif rep["under"] > 0 and rep["add_words"] > 0:
        msg += ("\n  the speech is %.2fs short even at x%.2f; the tail is padded with silence"
                " (about %d more word%s would fill it)" % (rep["under"], rep["speed_factor"], rep["add_words"],
                                                             "" if rep["add_words"] == 1 else "s"))
    if rep.get("fast"):
        msg += ("\n  the voice now speaks at x%.2f, which sounds rushed above about x%.2f (explainers and documentaries "
                "read best at x0.9-1.0): cut about %d word%s instead and fit again" % (
                    rep["max_speed"], FIT_FAST, rep["cut_words_at_1x"], "" if rep["cut_words_at_1x"] == 1 else "s"))
    return msg


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def caption_cues(words: List[Dict[str, Any]], max_chars: int = 42, max_gap: float = 0.8,
                 max_dur: float = 6.0) -> List[Dict[str, Any]]:
    """Group words into caption cues of <= max_chars.

    Words are first cut into phrases at sentence ends, long pauses and line
    changes; a phrase that is too long is split into the fewest cues that
    fit, balanced by length (preferring a break after a comma), so no cue
    ends with a one-word orphan.
    """
    phrases: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or w.get("line") != cur[-1].get("line")):
            phrases.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?…][\"”’)]*$", w["text"]):
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)

    def text_of(ws: List[Dict[str, Any]]) -> str:
        return " ".join(x["text"] for x in ws)

    cues: List[Dict[str, Any]] = []
    for ph in phrases:
        total = len(text_of(ph))
        dur = ph[-1]["end"] - ph[0]["start"]
        parts = max(int(np.ceil(total / float(max_chars))), int(np.ceil(dur / max_dur)), 1)
        groups: List[List[Dict[str, Any]]] = []
        rest = list(ph)
        for k in range(parts, 0, -1):
            if k == 1 or len(rest) <= 1:
                groups.append(rest)
                break
            target = len(text_of(rest)) / float(k)
            best, best_cost = 1, 1e9
            for j in range(1, len(rest)):
                head = len(text_of(rest[:j]))
                if head > max_chars:
                    break
                if len(text_of(rest[j:])) > (k - 1) * max_chars:
                    continue
                cost = abs(head - target) - (10 if rest[j - 1]["text"].endswith((",", ";", ":", "—")) else 0)
                if cost < best_cost:
                    best, best_cost = j, cost
            groups.append(rest[:best])
            rest = rest[best:]
        for g in groups:
            if g:
                cues.append({"start": g[0]["start"], "end": g[-1]["end"], "text": text_of(g), "words": g})
    return _readable_cues(cues)


def _readable_cues(cues: List[Dict[str, Any]], rounds: int = 6) -> List[Dict[str, Any]]:
    """Hold each cue long enough to read (st.captions_rules: <= 20 characters/s for 3+ words):
    borrow the silence after it (up to the next cue, or 1 s after the last word), then up to
    0.3 s before it; a cue that still reads too fast is split in two."""
    out = cues
    for _ in range(rounds):
        for i, cu in enumerate(out):
            need = R.min_seconds(cu["text"])
            if cu["end"] - cu["start"] >= need:
                continue
            limit = out[i + 1]["start"] if i + 1 < len(out) else cu["words"][-1]["end"] + 1.0
            cu["end"] = round(max(cu["end"], min(cu["start"] + need, limit)), 3)
            if cu["end"] - cu["start"] < need:
                floor = max(out[i - 1]["end"] if i else 0.0, cu["words"][0]["start"] - 0.3, 0.0)
                cu["start"] = round(min(cu["start"], max(cu["end"] - need, floor)), 3)
        nxt: List[Dict[str, Any]] = []
        split = False
        for cu in out:
            ws = cu["words"]
            if len(ws) >= R.CPS_MIN_WORDS and not R.readable(cu["text"], cu["end"] - cu["start"]):
                j = max(1, len(ws) // 2)
                for part in (ws[:j], ws[j:]):
                    nxt.append({"start": part[0]["start"], "end": part[-1]["end"],
                                "text": " ".join(x["text"] for x in part), "words": part})
                split = True
            else:
                nxt.append(cu)
        out = nxt
        if not split:
            break
    return [{"start": cu["start"], "end": cu["end"], "text": cu["text"]} for cu in out]


def wrap_cue(text: str, width: int = R.MAX_LINE_CHARS_VERTICAL) -> str:
    """Break a cue over two balanced lines when it is longer than `width` (32: fits vertical video too)."""
    if len(text) <= width or " " not in text:
        return text
    ws = text.split()
    best, cost = 1, None
    for j in range(1, len(ws)):
        a, b = len(" ".join(ws[:j])), len(" ".join(ws[j:]))
        c = abs(a - b) + (1000 if max(a, b) > width else 0)
        if cost is None or c < cost:
            best, cost = j, c
    return " ".join(ws[:best]) + "\n" + " ".join(ws[best:])


def write_srt(path: PathLike, cues: List[Dict[str, Any]]) -> Path:
    p = Path(path)
    body = []
    for i, c in enumerate(cues, 1):
        body.append("%d\n%s --> %s\n%s\n" % (i, _srt_time(c["start"]), _srt_time(c["end"]), wrap_cue(c["text"])))
    p.write_text("\n".join(body), encoding="utf-8")
    return p


def build(script_path: PathLike, out_dir: Optional[PathLike] = None, overrides: Optional[Dict[str, Any]] = None,
          lexicon_files: Tuple[str, ...] = (), fit: Optional[float] = None,
          readback: Optional[bool] = None) -> Dict[str, Any]:
    """Synthesize every line and write the voice folder. Returns the timeline.

    fit: target length of vo.wav in seconds (see fit_total).
    readback: hear every line again and compare it with the script (st.voice.readback; default on unless
    SHOWTIME_READBACK=0): readback.json, and timeline["readback"] with its summary."""
    sp = Path(script_path)
    cfg, raw_lines = load_script(sp)
    c, lines = normalize(cfg, raw_lines, overrides or {})
    out = Path(out_dir) if out_dir else sp.parent / "voice"
    (out / "lines").mkdir(parents=True, exist_ok=True)

    extra = list(lexicon_files)
    inline_lex = None
    if isinstance(c.get("lexicon"), str):
        lp = Path(c["lexicon"])
        extra.insert(0, str(lp if lp.is_absolute() else sp.parent / lp))
    elif isinstance(c.get("lexicon"), dict):
        inline_lex = c["lexicon"]
    lex = lexmod.load(extra, project_dir=sp.parent)
    if inline_lex:
        for w, e in inline_lex.items():
            lex.add(w, e)

    if fit is None and c.get("fit") is not None:
        fit = float(c["fit"])
    t_start = time.time()
    clips = _synth_all(lines, lex, 1.0)
    fit_report: Optional[Dict[str, Any]] = None
    if fit is not None:
        clips, fit_report = fit_total(lines, lex, clips, c, float(fit))

    # Assemble at the first clip's rate, then master to 48 kHz.
    sr = clips[0][1].sample_rate
    placed, total = _layout(clips, c)
    buf = np.zeros(int(round(total * sr)) + 1, dtype=np.float32)
    for ln, speech, start in placed:
        x = speech.audio if speech.sample_rate == sr else aio.resample(speech.audio, speech.sample_rate, sr)
        i0 = int(round(start * sr))
        buf[i0:i0 + len(x)] += x[: max(0, len(buf) - i0)]

    report: Dict[str, Any] = {}
    if c.get("master", True):
        from .master import master_array
        audio, out_sr, report = master_array(buf, sr, lufs=float(c["lufs"]), out_sr=SAMPLE_RATE_OUT)
    else:
        audio, out_sr = aio.resample(buf, sr, SAMPLE_RATE_OUT), SAMPLE_RATE_OUT
    audio = audio[: int(round(total * out_sr))]
    vo = out / "vo.wav"
    aio.write(vo, audio, out_sr, bits=24)

    tl_lines: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    for k, (ln, speech, start) in enumerate(placed):
        end = start + speech.duration
        nxt = placed[k + 1][2] if k + 1 < len(placed) else total
        rel = [dict(w) for w in speech.words]
        absw = [{"text": w["text"], "start": round(w["start"] + start, 3), "end": round(w["end"] + start, 3),
                 "line": ln["id"]} for w in rel]
        all_words += absw
        fname = "lines/%02d-%s.wav" % (ln["index"], ln["id"])
        seg = audio[int(round(start * out_sr)):int(round(end * out_sr))]
        aio.write(out / fname, aio.fade(seg, out_sr, 0.002, 0.01), out_sr, bits=24)
        rate = tts.measure_rate(speech)
        item = {"id": ln["id"], "index": ln["index"], "text": plain_text(ln["text"]), "source_text": ln["text"],
                "voice": speech.voice, "engine": speech.engine, "lang": speech.lang, "speed": speech.speed,
                "style": ln["style"], "start": round(start, 3), "end": round(end, 3),
                "duration": round(speech.duration, 3),
                "speech_start": absw[0]["start"] if absw else round(start, 3),
                "speech_end": absw[-1]["end"] if absw else round(end, 3),
                "pause_after": ln["pause_after"], "slot": {"start": round(start, 3), "end": round(nxt, 3),
                                                           "duration": round(nxt - start, 3)},
                "file": fname, "timing": speech.timing, "wps": rate["wps"], "words": absw}
        if "fit" in ln:
            item["fit"] = ln["fit"]
        if "at" in ln:
            item["at"] = ln["at"]          # pinned: retime --from-voice keeps it there past a data-silent scene
        tl_lines.append(item)
        write_json(out / ("lines/%02d-%s.words.json" % (ln["index"], ln["id"])), {
            "source": portable_path(out / fname, out / "lines"), "duration": round(speech.duration, 3),
            "language": speech.lang.split("-")[0], "model": speech.model or speech.engine,
            "words": [{"text": w["text"], "start": w["start"], "end": w["end"], "type": "word"} for w in rel]})

    # paths in sidecars are relative (to the file's folder): voice/ folders get copied and published
    transcript = {"source": portable_path(vo, out), "duration": round(total, 3),
                  "language": tl_lines[0]["lang"].split("-")[0], "model": "showtime-voice",
                  "words": [{"text": w["text"], "start": w["start"], "end": w["end"], "type": "word",
                             "line": w["line"]} for w in all_words]}
    write_json(out / "vo.words.json", transcript)
    cues = caption_cues(all_words)
    write_srt(out / "vo.srt", cues)
    timeline = {
        "version": TIMELINE_VERSION, "file": "vo.wav", "sample_rate": out_sr, "duration": round(total, 3),
        "lead_in": float(c["lead_in"]), "tail": float(c["tail"]),
        "loudness": report.get("after", {}).get("lufs") if report else None,
        "script": portable_path(sp, out), "lines": tl_lines,
        "words": all_words, "captions": {"srt": "vo.srt", "transcript": "vo.words.json", "cues": len(cues)},
        "build_seconds": round(time.time() - t_start, 2),
        "lexicon": [portable_path(x, out) for x in lex.sources],
    }
    if fit_report is not None:
        fit_report["result"] = round(total, 3)
        timeline["fit"] = fit_report
    from . import readback as rb
    if (rb.enabled() if readback is None else readback):
        t_rb = time.time()
        try:
            rep = rb.for_voice(out, tl_lines, [speech for _, speech, _ in placed], lex, project_dir=sp.parent)
        except Exception as e:  # noqa: BLE001 - hearing the voice back is a check, never a reason to fail
            rep = {"skipped": "the read-back failed (%s)" % (str(e).splitlines()[0][:120] if str(e) else type(e).__name__),
                   "suspects": []}
            rep["summary"] = rb.summary(rep)
        timeline["readback"] = {"file": rb.FILE, "summary": rep["summary"], "suspects": rep.get("suspects") or [],
                                "skipped": rep.get("skipped"), "seconds": round(time.time() - t_rb, 2)}
    write_json(out / "timeline.json", timeline)
    return timeline
