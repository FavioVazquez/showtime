"""A storyboard from another tool -> a showtime project, one scene per shot (`showtime new <template> <dir>
--from-storyboard FILE`).

Input: a Markdown table, one row per shot (columns Shot | Length | Visual | Narration in any order, Chinese
headers too, extra columns such as On screen or Sound), pasted on stdin with `-`, or a storyboard.json (the
storyboard artist's rows: id, dur, visual, onscreen, vo). Output, next to the template's showtime.json:

- index.html: one <section> per shot, timed from the lengths, showing a brief card (the shot number, its
  length and the Visual text as written). The Visual is a brief for the agent, never on-screen copy, except
  the quoted words of a card or title ("Title card: \"Why ...\"") and text after "text:" or an On screen
  column, which are shown as written. Nothing else is invented.
- narration.md: the narration as a `showtime voice script`, one `## shot-N` line per narrated shot. Every
  line is pinned (`at`) where its shot starts, so after `voice script` and `retime --from-voice` the shots
  keep the storyboard's lengths wherever the voice fits, and grow where it does not.
- storyboard.json (the plan, read back by `retime --from-voice` to say where the voice outgrew it),
  storyboard.md (the same as a table, for the review pack) and audio/mix.json (a quiet bed on the shots).

Stdlib only: `showtime new` runs before the venv exists.
"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .common import ShowtimeError

GENERATOR = "showtime new --from-storyboard"
PAD = 0.3                     # picture before each shot's first word (retime --from-voice --pad)
GAP = 0.35                    # voice script's default pause after a line
TAIL = 0.6                    # voice script's default silence after the last line
DEFAULT_SHOT = 4.0            # a shot with no length and no narration
MIN_SHOT = 1.0
MAX_TOTAL = 3600.0
# planning budgets at a natural explainer read: English and other spaced languages in words/s (voice.md:
# 2.8-3.3 at speed 1.0); Chinese and Japanese in characters/s (Kokoro zf_xiaobei measured 3.1 chars/s
# on 39 characters; the understanding-ladder storyboard rule is 200 characters a minute)
WPS = 2.8
CPS = {"zh": 3.2, "ja": 3.2, "ko": 4.0}

# --------------------------------------------------------------------------- columns

# header words per role, compared after lower-casing and dropping punctuation and spaces
ROLES: Sequence[Tuple[str, Sequence[str]]] = (
    ("onscreen", ("onscreen", "onscreentext", "screentext", "text", "textonscreen", "title", "titles", "supers",
                  "lowerthird", "屏幕文字", "画面文字", "屏幕文本", "文字", "字卡", "标题")),
    ("narration", ("narration", "voiceover", "vo", "voice", "script", "spoken", "dialogue", "dialog", "speech",
                   "narrator", "words", "audionarration", "旁白", "解说", "解说词", "配音", "台词", "口播", "讲解",
                   "ナレーション", "내레이션")),
    ("sound", ("sound", "sounds", "sfx", "soundeffects", "music", "audio", "soundmusic", "musicsfx", "音效",
               "音乐", "声音", "配乐", "音频")),
    ("length", ("length", "duration", "dur", "time", "timing", "len", "seconds", "secs", "sec", "s", "runtime",
                "时长", "时间", "长度", "秒数", "秒", "時間", "길이")),
    ("shot", ("shot", "shots", "#", "no", "number", "scene", "panel", "beat", "id", "镜头", "镜号", "序号",
              "分镜", "场景", "编号", "カット", "샷")),
    ("visual", ("visual", "visuals", "picture", "image", "images", "video", "onscreenvisual", "description",
                "shotdescription", "whatwesee", "animation", "action", "画面", "视觉", "画面内容", "镜头内容",
                "动画", "画面描述", "映像", "화면")),
)
KEYS = ("shot", "length", "visual", "narration")      # the four columns of the reference format, in its order


def _norm_header(cell: str) -> str:
    s = re.sub(r"[*_`~]", "", cell or "").strip().lower()
    s = re.sub(r"\(.*?\)|（.*?）", "", s)               # "Length (s)", "时长（秒）"
    return re.sub(r"[\s\-./:：()（）]", "", s)


def column_roles(header: Sequence[str]) -> List[Optional[str]]:
    """The role of every column (shot, length, visual, narration, onscreen, sound) or None (kept as a note)."""
    out: List[Optional[str]] = []
    taken = set()
    for cell in header:
        h = _norm_header(cell)
        role = None
        for name, words in ROLES:
            if name not in taken and h in words:
                role = name
                break
        if role is None and h:
            # "Narration (EN)", "Visual idea", "画面说明": a known word at the start
            for name, words in ROLES:
                if name not in taken and any(len(w) > 2 and h.startswith(w) for w in words):
                    role = name
                    break
        if role:
            taken.add(role)
        out.append(role)
    if "narration" not in taken and "sound" in taken:
        # "Audio" next to Visual with no narration column: in a two-column AV script it is the voice
        i = out.index("sound")
        if _norm_header(header[i]) in ("audio", "音频"):
            out[i] = "narration"
    return out


# --------------------------------------------------------------------------- Markdown tables

_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _cells(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.replace("\\|", "|").strip() for p in parts]


def find_tables(text: str) -> List[Tuple[List[str], List[List[str]]]]:
    """Every Markdown table in `text` as (header cells, rows of cells)."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    i = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and _SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            header = _cells(lines[i])
            rows = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(_cells(lines[j]))
                j += 1
            out.append((header, rows))
            i = j
        else:
            i += 1
    return out


def _table_score(roles: Sequence[Optional[str]]) -> int:
    return (3 if "visual" in roles else 0) + (3 if "narration" in roles else 0) + \
        (1 if "length" in roles else 0) + (1 if "shot" in roles else 0)


_EMPTY = re.compile(r"^[\s.…·\-–—?？/]*$")


def _empty(cell: str) -> bool:
    return bool(_EMPTY.match(cell or "")) or (cell or "").strip().lower() in ("n/a", "na", "tbd", "none", "无", "无旁白")


def _md_inline(cell: str) -> str:
    """Table cell text without Markdown emphasis or <br>; code spans keep their text."""
    s = re.sub(r"<br\s*/?>", " ", cell or "", flags=re.I)
    s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\((?:[^)]*)\)", r"\1", s)
    return " ".join(s.split())


def parse_markdown(text: str) -> Dict[str, Any]:
    """The storyboard table of a Markdown document -> {"shots": [...], "columns": {...}, "notes": [...]}."""
    tables = find_tables(text)
    if not tables:
        raise ShowtimeError("no Markdown table found in the storyboard",
                            why="--from-storyboard reads a table with one row per shot",
                            hint="| Shot | Length | Visual | Narration |\n|---|---|---|---|\n| 1 | 5 s | Title card: \"...\" | ... |")
    best = None
    for header, rows in tables:
        roles = column_roles(header)
        score = _table_score(roles)
        if best is None or score > best[0] or (score == best[0] and len(rows) > len(best[2])):
            best = (score, header, rows, roles)
    score, header, rows, roles = best
    notes: List[str] = []
    if score < 3:
        if len(header) in (3, 4):
            # an unknown header (another language, made-up names): the reference order, Shot Length Visual Narration
            roles = list(KEYS[4 - len(header):])
            notes.append("columns not recognised (%s): read in the order %s" % (
                " | ".join(header), " | ".join(r.title() for r in roles)))
        else:
            raise ShowtimeError("the storyboard table has no Visual or Narration column (columns: %s)" % " | ".join(header),
                                hint="name the columns Shot | Length | Visual | Narration (镜头 | 时长 | 画面 | 旁白 also works)")
    shots = []
    for r in rows:
        cells = list(r) + [""] * (len(header) - len(r))
        if all(_empty(c) for c in cells):
            continue                                   # "| … | … | … | … |" placeholder rows
        rec: Dict[str, Any] = {"extra": {}}
        for cell, role, name in zip(cells, roles, header):
            v = _md_inline(cell)
            if role:
                rec[role] = "" if _empty(v) and role != "length" else v
            elif v and not _empty(v):
                rec["extra"][_md_inline(name) or "column %d" % (len(rec["extra"]) + 1)] = v
        if not any(rec.get(k) for k in ("visual", "narration", "onscreen")):
            continue
        shots.append(rec)
    if not shots:
        raise ShowtimeError("the storyboard table has no shots (every row is empty)")
    return {"shots": shots, "columns": {h: r or "note" for h, r in zip(header, roles)}, "notes": notes}


# --------------------------------------------------------------------------- storyboard.json

def _section_lines(text: str) -> Dict[str, str]:
    """`## id` sections of a voice script -> {id: spoken text} (comments and > notes left out)."""
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    text = re.sub(r"^\s*---\s*\n.*?\n---\s*\n", "", text, flags=re.S)
    out: Dict[str, str] = {}
    cur = None
    for ln in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*?)\s*(\{[^}]*\})?\s*$", ln)
        if m:
            cur = m.group(1).strip()
            out[cur] = ""
        elif cur is not None and ln.strip() and not ln.lstrip().startswith(">"):
            out[cur] = (out[cur] + " " + ln.strip()).strip()
    return out


def parse_json(data: Any, base: Optional[Path] = None) -> Dict[str, Any]:
    """storyboard.json (the storyboard artist's rows, a {"rows"|"shots"|"panels": [...]} or a bare list)."""
    rows = data
    if isinstance(data, dict):
        for k in ("rows", "shots", "panels", "storyboard", "scenes"):
            if isinstance(data.get(k), list):
                rows = data[k]
                break
    if not isinstance(rows, list) or not rows:
        raise ShowtimeError("the storyboard JSON has no rows",
                            hint='write {"rows": [{"id": "s1-hook", "dur": 5, "visual": "...", "vo": "..."}, ...]}')
    script: Optional[Dict[str, str]] = None
    notes: List[str] = []
    shots = []
    for i, r in enumerate(rows, 1):
        if isinstance(r, str):
            r = {"visual": r}
        if not isinstance(r, dict):
            raise ShowtimeError("storyboard row %d is not an object" % i)
        dur = next((r[k] for k in ("dur", "duration", "length", "len", "seconds") if r.get(k) not in (None, "")), "")
        on = r.get("onscreen", r.get("text", ""))
        vo = next((r[k] for k in ("narration", "vo", "voice", "voiceover", "script") if r.get(k)), "")
        if isinstance(vo, list):
            ids = [str(x) for x in vo]
            if ids and all(re.fullmatch(r"[\w.-]+", x) for x in ids):
                # the artist's vo: script line ids; the words live in the scriptwriter's script.md
                if script is None:
                    script = {}
                    for name in ("script.md", "narration.md"):
                        p = (base or Path(".")) / name
                        if p.is_file():
                            script = _section_lines(p.read_text(encoding="utf-8-sig"))
                            break
                found = [script[x] for x in ids if script.get(x)]
                if len(found) < len(ids):
                    notes.append("row %s: vo names line(s) %s that no script.md next to the storyboard holds" % (
                        r.get("id") or i, ", ".join(x for x in ids if not script.get(x))))
                vo = " ".join(found)
            else:
                vo = " ".join(ids)
        shots.append({"shot": str(r.get("shot") or r.get("id") or i), "id": r.get("id"),
                      "length": str(dur), "visual": str(r.get("visual") or r.get("description") or ""),
                      "narration": str(vo or ""),
                      "onscreen": " / ".join(map(str, on)) if isinstance(on, list) else str(on or ""),
                      "sound": "; ".join(map(str, r["cues"])) if isinstance(r.get("cues"), list) else str(r.get("sound") or ""),
                      "extra": {k: v for k, v in r.items() if k in ("note", "notes", "build", "transition_in")
                                and isinstance(v, (str, int, float))}})
    return {"shots": shots, "columns": {}, "notes": notes}


def load(source: str, stdin_text: Optional[str] = None) -> Dict[str, Any]:
    """Read a storyboard from a file (.md, .txt, .json) or from stdin ('-')."""
    base = None
    if source == "-":
        text = stdin_text if stdin_text is not None else ""
        name = "stdin"
        if not text.strip():
            raise ShowtimeError("no storyboard on stdin", hint="pipe the table in: showtime new dom my-video --from-storyboard - < storyboard.md")
    else:
        p = Path(source).expanduser()
        if p.is_dir():
            p = p / "storyboard.json" if (p / "storyboard.json").is_file() else p / "storyboard.md"
        if not p.is_file():
            raise ShowtimeError("storyboard not found: %s" % p, hint="give a Markdown file with the shot table, a storyboard.json, or - for stdin")
        text = p.read_text(encoding="utf-8-sig")
        name = str(p)
        base = p.parent
    if text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ShowtimeError("%s is not valid JSON: %s" % (name, e))
        out = parse_json(data, base)
    else:
        out = parse_markdown(text)
    out["source"] = name
    return out


# --------------------------------------------------------------------------- lengths, copy, language

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT_S = r"(?:s|sec|secs|second|seconds|seg|segundos?|秒|秒钟|秒鐘|초|″|\")"
_UNIT_M = r"(?:m|min|mins|minute|minutes|分|分钟|分鐘|분|′|')"


def parse_length(cell: Any) -> Optional[float]:
    """'5 s', '5s', '0:05', '1:05', '5-7 s' (the middle), '~6秒', '1 分 30 秒', '1.5 min', '800 ms' -> seconds;
    None when there is no length ('', '…', 'TBD')."""
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        return float(cell) if cell > 0 else None
    s = str(cell or "").strip().lower().replace("，", ",")
    if not s or _empty(s):
        return None
    s = s.replace("～", "~").replace("–", "-").replace("—", "-").replace("〜", "-").replace("至", "-").replace("到", "-")
    stamps = re.findall(r"(?:(\d+):)?(\d+):(\d{1,2}(?:\.\d+)?)", s)
    if len(stamps) == 2 and "-" in s:
        # "0:05-0:12": a start and an end time
        a, b = [int(h or 0) * 3600 + int(m_) * 60 + float(x) for h, m_, x in stamps]
        return (b - a) if b > a else None
    m = re.search(r"(\d+):(\d{1,2}(?:\.\d+)?)(?::(\d{1,2}(?:\.\d+)?))?", s)
    if m:
        if m.group(3) is not None:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        v = int(m.group(1)) * 60 + float(m.group(2))
        return v if v > 0 else None
    m = re.search(_NUM + r"\s*" + _UNIT_M + r"\s*" + _NUM + r"\s*" + _UNIT_S + "?", s)
    if m:
        return float(m.group(1).replace(",", ".")) * 60 + float(m.group(2).replace(",", "."))
    m = re.search(_NUM + r"\s*(?:" + _UNIT_S + r"|" + _UNIT_M + r"|ms)?\s*(?:-|to|~)\s*" + _NUM + r"\s*(ms|" + _UNIT_S
                  + r"|" + _UNIT_M + r")?(?![a-z])", s)
    if m:
        a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return _unit((a + b) / 2.0, m.group(3))
    m = re.search(_NUM + r"\s*(ms|" + _UNIT_S + r"|" + _UNIT_M + r")?(?![a-z])", s)
    if m:
        return _unit(float(m.group(1).replace(",", ".")), m.group(2))
    return None


def _unit(v: float, unit: Optional[str]) -> Optional[float]:
    if unit == "ms":
        v = v / 1000.0
    elif unit and re.fullmatch(_UNIT_M, unit):
        v = v * 60.0
    return v if v > 0 else None


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")


def detect_lang(texts: Sequence[str]) -> Optional[str]:
    """zh, ja or ko when the narration is mostly written in that script; None (English or another spaced language)."""
    t = " ".join(texts)
    letters = len(re.findall(r"\w", t))
    if not letters:
        return None
    han, kana, hangul = len(_CJK.findall(t)), len(_KANA.findall(t)), len(_HANGUL.findall(t))
    if hangul / letters > 0.3:
        return "ko"
    if (han + kana) / letters > 0.3:
        return "ja" if kana > 0.1 * (han + kana) else "zh"
    return None


def speech_units(text: str, lang: Optional[str]) -> int:
    """Words (spaced languages) or characters (zh/ja/ko) in a narration line, as the voice budgets count them."""
    if lang in CPS:
        dense = len(_CJK.findall(text)) + len(_KANA.findall(text)) + len(_HANGUL.findall(text))
        latin = len(re.findall(r"[A-Za-z0-9]+(?:['.][A-Za-z0-9]+)*", text))
        return dense + 2 * latin                        # a Latin word in Chinese speech takes about two syllables
    return len(re.findall(r"[^\W_]+(?:['’.-][^\W_]+)*", text))


def speech_seconds(text: str, lang: Optional[str]) -> float:
    n = speech_units(text, lang)
    return n / (CPS.get(lang or "", 0) or WPS)


_QUOTES = re.compile(r"\"([^\"]+)\"|“([^”]+)”|「([^」]+)」|『([^』]+)』|«([^»]+)»|‘([^’]+)’")
_COPY_WORDS = re.compile(r"\b(?:card|title|titles|headline|caption|super|lower third|text)\b|标题|卡|字幕|文字|字卡|タイトル|テロップ", re.I)
_TEXT_PREFIX = re.compile(r"^\s*(?:on[- ]screen(?: text)?|text|title|caption|headline|super|标题|文字|字幕|字卡)\s*[:：]\s*(.+)$", re.I)


def split_visual(visual: str) -> Tuple[List[str], str]:
    """(on-screen copy, the brief left) from a Visual cell. Only a card or title's quoted words and the text after
    "text:" are copy; everything else is a description of what to build."""
    v = (visual or "").strip()
    m = _TEXT_PREFIX.match(v)
    if m:
        body = m.group(1).strip()
        quoted = [next(g for g in q.groups() if g) for q in _QUOTES.finditer(body)]
        return (quoted or [body.strip(" \"'“”「」")]), ""
    if _COPY_WORDS.search(v):
        quoted = [next(g for g in q.groups() if g).strip() for q in _QUOTES.finditer(v)]
        quoted = [q for q in quoted if q]
        if quoted:
            rest = _QUOTES.sub("", v)
            rest = re.sub(r"[\s:：,，;；、]+$", "", re.sub(r"\s{2,}", " ", rest)).strip()
            return quoted, rest
    return [], v


# --------------------------------------------------------------------------- the plan

def plan(sb: Dict[str, Any], *, pad: float = PAD) -> Dict[str, Any]:
    """Shots with ids, planned starts and lengths (missing lengths estimated from the narration), copy and
    brief, and the narration fit per shot."""
    raw = sb["shots"]
    lang = detect_lang([s.get("narration", "") for s in raw] + [s.get("visual", "") for s in raw])
    shots: List[Dict[str, Any]] = []
    notes = list(sb.get("notes") or [])
    t = 0.0
    used = set()
    for i, s in enumerate(raw, 1):
        narration = (s.get("narration") or "").strip()
        copy, brief = split_visual(s.get("visual") or "")
        onscreen = (s.get("onscreen") or "").strip()
        if onscreen:
            copy = copy + [x.strip() for x in re.split(r"\s+/\s+|\s*<br>\s*", onscreen) if x.strip()]
        length = parse_length(s.get("length"))
        need = speech_seconds(narration, lang) if narration else 0.0
        estimated = length is None
        if estimated:
            length = max(3.0, math.ceil((pad + need + TAIL) * 2) / 2.0) if narration else DEFAULT_SHOT
        if length < MIN_SHOT:
            notes.append("shot %d: %g s is shorter than %g s; planned as %g s" % (i, length, MIN_SHOT, MIN_SHOT))
            length = MIN_SHOT
        length = round(length, 2)
        sid = "shot-%d" % i
        if s.get("id") and re.fullmatch(r"[A-Za-z][\w-]{0,39}", str(s["id"])) and str(s["id"]) not in used:
            sid = str(s["id"])                         # storyboard.json ids are the scene ids builders use
        used.add(sid)
        units = speech_units(narration, lang) if narration else 0
        rate = units / max(0.1, length - pad)
        shots.append({"n": i, "id": sid, "shot": str(s.get("shot") or i), "start": round(t, 2), "dur": length,
                      "estimated": estimated, "length_text": str(s.get("length") or ""),
                      "visual": (s.get("visual") or "").strip(), "brief": brief, "copy": copy,
                      "narration": narration, "sound": (s.get("sound") or "").strip(),
                      "extra": s.get("extra") or {}, "units": units, "need": round(need, 2),
                      "rate": round(rate, 2), "fits": (pad + need + GAP) <= length + 1e-6})
        t += length
    if t > MAX_TOTAL:
        raise ShowtimeError("the storyboard adds up to %.0f s; the limit is %g s" % (t, MAX_TOTAL))
    title = next((s["copy"][0] for s in shots if s["copy"] and re.search(r"(?i)title|标题|タイトル|제목", s["visual"])), None)
    return {"shots": shots, "lang": lang, "duration": round(t, 2), "pad": pad, "notes": notes, "title": title,
            "unit": "characters" if lang in CPS else "words", "budget": CPS.get(lang or "", WPS),
            "source": sb.get("source"), "columns": sb.get("columns") or {}}


def fit_lines(p: Dict[str, Any]) -> List[str]:
    """One line per shot whose narration needs more time than its length, at the planning budget."""
    out = []
    u, b = p["unit"], p["budget"]
    for s in p["shots"]:
        if s["narration"] and not s["fits"] and not s["estimated"]:
            cut = max(1, int(math.ceil(s["units"] - (s["dur"] - p["pad"] - GAP) * b)))
            out.append("%s: %d %s in %g s is %.1f %s/s (budget %.1f): about %.1f s of speech; cut about %d %s or "
                       "give the shot %.1f s" % (s["id"], s["units"], u, s["dur"], s["rate"], u[0] if u == "words" else "chars",
                                                b, s["need"], cut, u, math.ceil((s["need"] + p["pad"] + GAP) * 2) / 2.0))
    return out


# --------------------------------------------------------------------------- project files

def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


CSS = r"""
  /* storyboard scaffold: every colour and face is the theme's, so a brand kit or another theme restyles it */
  .stage { background: var(--bg); }
  .scene { --s-label: 2.4cqh; --s-copy: 8.6cqh; --s-copy-sm: 6cqh; --s-brief: 5cqh; --s-brief-sm: 3.1cqh;
           --s-note: 2.6cqh; font-family: var(--font-body, var(--font-display)); }
  .world { position: absolute; inset: 0; overflow: hidden; pointer-events: none;
           background: radial-gradient(70% 80% at 30% 35%, color-mix(in oklab, var(--accent) 9%, transparent), transparent 70%); }
  .cam { position: absolute; inset: 0; }
  .board { position: absolute; left: 8cqw; right: 8cqw; top: 50%; translate: 0 -50%; display: flex;
           flex-direction: column; gap: 3cqh; }
  .label { font: 500 var(--s-label)/1.3 var(--font-mono); letter-spacing: 0.12em; text-transform: uppercase;
           color: var(--muted); margin: 0; }
  .label b { color: var(--accent); font-weight: 600; }
  .copy { font: var(--weight-display, 700) var(--s-copy)/1.05 var(--font-display); letter-spacing: var(--tracking-display, -0.03em);
          color: var(--fg); margin: 0; max-width: 24em; text-wrap: balance; overflow-wrap: anywhere; }
  .copy.many { font-size: var(--s-copy-sm); }
  .brief { margin: 0; padding: 2.6cqh 3cqh; border-radius: 1.4cqh; max-width: 30em; align-self: flex-start;
           border: max(2px, 0.25cqh) dashed color-mix(in oklab, var(--fg) 45%, transparent);
           font: 450 var(--s-brief)/1.3 var(--font-body, var(--font-display)); color: var(--fg); overflow-wrap: anywhere; }
  .copy + .brief, .copy ~ .brief { font-size: var(--s-brief-sm); color: var(--muted); }
  .note { font: 450 var(--s-note)/1.35 var(--font-mono); color: var(--muted); margin: 0; max-width: 60em; }
  :lang(zh) .copy, :lang(zh) .brief, :lang(ja) .copy, :lang(ja) .brief, :lang(ko) .copy, :lang(ko) .brief {
    font-family: 'Noto Sans SC', 'Noto Sans KR', 'Noto Sans JP', sans-serif; letter-spacing: 0; }
  @keyframes rise { from { opacity: 0; transform: translateY(0.4em); } to { opacity: 1; transform: none; } }
  .board > * { animation: rise 0.6s cubic-bezier(0.16, 1, 0.3, 1) calc(0.1s + var(--i, 0) * 0.12s) both; }
  .scene:first-of-type .board > * { animation: none; }   /* the first frame is the poster: complete at t=0 */
  @container (max-aspect-ratio: 5/4) {
    .scene { --s-label: 2.6cqw; --s-copy: 9cqw; --s-copy-sm: 6.4cqw; --s-brief: 4.6cqw; --s-brief-sm: 3.6cqw; --s-note: 3cqw; }
    .board { left: 7cqw; right: 7cqw; }
  }
  @container (max-aspect-ratio: 3/4) {
    .scene { --s-label: 4.2cqw; --s-copy: 10cqw; --s-copy-sm: 7.4cqw; --s-brief: 5.4cqw; --s-brief-sm: 4.6cqw; --s-note: 4.2cqw; }
    .board { left: 9cqw; right: 16cqw; top: 42%; }
  }
"""


def _secs(v: float) -> str:
    return ("%.1f" % v).rstrip("0").rstrip(".")


def build_page(p: Dict[str, Any], *, title: str, theme: str = "/_st/themes/neutral.css",
               fonts: Sequence[str] = ()) -> str:
    lang = p["lang"] or "en"
    out: List[str] = []
    prev = None
    for s in p["shots"]:
        start = "0" if prev is None else "#" + prev
        silent = "" if s["narration"] else " data-silent"
        push = [{"at": 0, "zoom": 1}, {"at": 0.15, "dur": round(max(1.0, s["dur"] - 0.3), 2), "zoom": 1.06,
                                       "focus": [50, 50], "to": "stay", "ease": "linear"}]
        label = "Shot %s <b>&middot;</b> %s s%s <b>&middot;</b> to build" % (
            _e(s["shot"]), _secs(s["dur"]), " (estimated)" if s["estimated"] else "")
        out.append('  <section class="scene" id="%s" data-start="%s" data-dur="%.2f" data-storyboard-shot="%s"%s>'
                   % (s["id"], start, s["dur"], _e(s["shot"]), silent))
        out.append("    <div class=\"cam\" data-st=\"camera\" data-path='%s'>" % json.dumps(push))
        out.append('      <div class="board">')
        out.append('        <p class="label" style="--i:0">%s</p>' % label)
        i = 1
        for c in s["copy"]:
            out.append('        <p class="copy%s" style="--i:%d">%s</p>' % (" many" if len(s["copy"]) > 1 else "", i, _e(c)))
            i += 1
        if s["brief"]:
            # the Visual as written: a brief for whoever builds the shot, replaced by the real picture
            out.append('        <p class="brief" data-storyboard-brief style="--i:%d">%s</p>' % (i, _e(s["brief"])))
            i += 1
        if s["sound"]:
            out.append('        <p class="note" data-storyboard-brief style="--i:%d">Sound: %s</p>' % (i, _e(s["sound"])))
        out.append("      </div>\n    </div>\n  </section>")
        prev = s["id"]
    links = "".join('<link rel="stylesheet" href="%s">\n' % _e(f) for f in fonts)
    return ("<!doctype html>\n<html lang=\"%s\">\n<head>\n<meta charset=\"utf-8\">\n<title>%s</title>\n"
            "<script src=\"/_st/stage.js\"></script>\n<link rel=\"stylesheet\" href=\"%s\">\n%s"
            "<script type=\"module\" src=\"/_st/components/index.js\"></script>\n"
            "<!-- Written by `showtime new --from-storyboard` (%d shots, %s s planned). Each <section> is one shot of\n"
            "     storyboard.json, timed from its length. The dashed .brief is the storyboard's Visual as written: build\n"
            "     that shot's picture in its section and delete the brief (check warns while one is left). Words in\n"
            "     .copy are the storyboard's own card or on-screen text. data-silent marks a shot without narration.\n"
            "     After the voice (narration.md): showtime retime . --from-voice voice/timeline.json -->\n"
            "<style>%s</style>\n</head>\n<body>\n<div class=\"stage\">\n  <div class=\"world\" data-st-decor></div>\n%s\n"
            "</div>\n</body>\n</html>\n" % (
                _e(lang), _e(title), _e(theme), links, len(p["shots"]), _secs(p["duration"]), CSS, "\n".join(out)))


def narration_md(p: Dict[str, Any]) -> Optional[str]:
    """The voice script: one `## <shot id>` per narrated shot, pinned where its shot starts.

    `retime --from-voice` makes a narrated shot pad + its line's slot long (the slot runs to the next line's
    start), and keeps a silent shot's length, so pinning line k at the sum of (length - pad) of the narrated
    shots before it gives every shot its planned length when its speech fits; a longer line starts the next
    one late (voice script warns) and that shot grows."""
    narrated = [s for s in p["shots"] if s["narration"]]
    if not narrated:
        return None
    head = ["---"]
    if p["lang"]:
        head.append("lang: %s" % p["lang"])
    head += ["tail: %g" % TAIL, "---",
             "<!-- Written by `showtime new --from-storyboard` from %s: the Narration column, one line per shot, in"
             % (Path(str(p.get("source") or "the storyboard")).name),
             "     order. Each {at=...} pins a line where its shot starts in the voice timeline (the shot's start",
             "     minus %g s of picture per narrated shot before it), so the shots keep the storyboard's lengths"
             % p["pad"],
             "     where the voice fits. Edit the words freely; keep the headings (they name the scenes).",
             "     showtime voice script narration.md -o voice",
             "     showtime retime . --from-voice voice/timeline.json --total %s -->" % _secs(p["duration"]), ""]
    body = []
    at = 0.0
    for s in narrated:
        body.append("## %s {at=%s}" % (s["id"], ("%.2f" % at).rstrip("0").rstrip(".") or "0"))
        body.append(s["narration"])
        body.append("")
        at += s["dur"] - p["pad"]
    return "\n".join(head + body)


def storyboard_md(p: Dict[str, Any]) -> str:
    def cell(x: str) -> str:
        return (x or "").replace("|", "\\|").replace("\n", " ")
    rows = ["# Storyboard", "",
            "From %s (%d shots, %s s planned). The plan `showtime new --from-storyboard` built the project from;"
            " storyboard.json holds the same rows." % (Path(str(p.get("source") or "stdin")).name, len(p["shots"]),
                                                       _secs(p["duration"])), "",
            "| Shot | Scene | Time | Length | Visual | On screen | Narration |", "|---|---|---|---|---|---|---|"]
    for s in p["shots"]:
        rows.append("| %s | %s | %s | %s s%s | %s | %s | %s |" % (
            cell(s["shot"]), s["id"], _secs(s["start"]), _secs(s["dur"]), " (est.)" if s["estimated"] else "",
            cell(s["visual"]), cell(" / ".join(s["copy"])), cell(s["narration"])))
    return "\n".join(rows) + "\n"


def storyboard_json(p: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    for s in p["shots"]:
        row = {"id": s["id"], "shot": s["shot"], "start": s["start"], "dur": s["dur"], "visual": s["visual"],
               "brief": s["brief"], "onscreen": s["copy"], "vo": [s["id"]] if s["narration"] else [],
               "narration": s["narration"], "planned": {"dur": s["dur"], "estimated": s["estimated"],
                                                       "length": s["length_text"]},
               "speech": {p["unit"]: s["units"], "seconds": s["need"], "rate": s["rate"], "fits": s["fits"]}}
        if s["sound"]:
            row["sound"] = s["sound"]
        if s["extra"]:
            row["notes"] = s["extra"]
        rows.append(row)
    return {"_comment": "Written by `showtime new --from-storyboard`: the plan. Scene ids are the <section> ids in "
                        "index.html and the ## headings in narration.md. `showtime retime --from-voice` reads it to "
                        "say where the voice outgrew a shot's planned length.",
            "generator": GENERATOR, "source": p.get("source"), "lang": p["lang"], "pad": p["pad"],
            "duration": p["duration"], "budget": {p["unit"] + "_per_s": p["budget"]}, "rows": rows}


def build_mix(p: Dict[str, Any], seed: int = 11) -> Dict[str, Any]:
    starts = [s["start"] for s in p["shots"]]
    names = ["intro"] + ["verse"] * max(0, len(starts) - 2) + (["outro"] if len(starts) > 1 else [])
    sections = ",".join("%g:%s" % (t, n) for t, n in zip(starts, names))
    return {"_comment": "Written by `showtime new --from-storyboard`: a quiet documentary bed with a section on each "
                        "shot; the storyboard names no other sound (its Sound notes are in storyboard.json). `showtime "
                        "retime --from-voice` adds the voice lines and ducks the bed under them.",
            "sample_rate": 48000,
            "tracks": [{"id": "bed", "kind": "music", "compose": {"style": "underscore", "sections": sections, "seed": seed},
                        "gain_db": -4, "fade_out": 1.5}],
            "master": {"lufs": -14, "true_peak": -1}}


def theme_of(template_page: Path) -> str:
    """The theme stylesheet the template's page links (bold for dom/short, neutral for launch ...)."""
    try:
        m = re.search(r'href="(/_st/themes/[\w-]+\.css)"', template_page.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return "/_st/themes/neutral.css"


CJK_FONTS = {"zh": ("noto-sans-sc", "Noto Sans SC", "chinese-simplified"), "ko": ("noto-sans-kr", "Noto Sans KR", "korean")}


def cjk_fonts(dst: Path, lang: Optional[str], fonts_home: Optional[Path]) -> Tuple[List[str], List[str]]:
    """(stylesheets, notes) for Chinese, Japanese or Korean text. The bundled Noto Sans JP has the Japanese
    kanji only, so Chinese and Korean also need their own family: copied into the project when `showtime
    assets font` has installed it, else the command that does."""
    if lang not in CPS:
        return [], []
    links = ["/_st/themes/fonts/noto-sans-jp.css"]
    if lang not in CJK_FONTS:
        return links, []
    fid, fam, sub = CJK_FONTS[lang]
    src = Path(fonts_home) / fid if fonts_home else None
    if src is not None and (src / "font.css").is_file():
        import shutil
        shutil.copytree(str(src), str(Path(dst) / "fonts" / fid), dirs_exist_ok=True)
        return [("fonts/%s/font.css" % fid)] + links, []
    return links, ["the %s text needs %s (Noto Sans JP lacks many of its characters; check names them): "
                   "showtime assets font \"%s\" --subsets %s --copy-to %s, then add "
                   "<link rel=\"stylesheet\" href=\"fonts/%s/font.css\"> to index.html"
                   % (lang, fam, fam, sub, Path(dst) / "fonts", fid)]


def write_project(dst: Path, p: Dict[str, Any], *, title: str, theme: str,
                  fonts_home: Optional[Path] = None) -> List[str]:
    """index.html, narration.md, storyboard.json, storyboard.md and audio/mix.json; the written names. Font
    notes go to p["notes"]."""
    dst = Path(dst)
    (dst / "audio").mkdir(parents=True, exist_ok=True)
    written = []
    fonts, fnotes = cjk_fonts(dst, p["lang"], fonts_home)
    p["notes"] = list(p.get("notes") or []) + fnotes
    written += ["fonts/%s/ (OFL)" % f.split("/")[1] for f in fonts if f.startswith("fonts/")]

    def put(name: str, text: str) -> None:
        (dst / name).write_text(text, encoding="utf-8", newline="\n")
        written.append(name)

    put("index.html", build_page(p, title=title, theme=theme, fonts=fonts))
    nm = narration_md(p)
    if nm:
        put("narration.md", nm)
    put("storyboard.json", json.dumps(storyboard_json(p), indent=2, ensure_ascii=False) + "\n")
    put("storyboard.md", storyboard_md(p))
    put("audio/mix.json", json.dumps(build_mix(p), indent=2) + "\n")
    return written


# --------------------------------------------------------------------------- after the voice

def compare_voice(proj: Path, names: Sequence[str], plan_times: Sequence[Tuple[float, float]]) -> List[str]:
    """`retime --from-voice` notes: the shots whose new length differs from the storyboard's plan."""
    try:
        sb = json.loads((Path(proj) / "storyboard.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(sb, dict) or sb.get("generator") != GENERATOR:
        return []
    planned = {r.get("id"): r for r in sb.get("rows") or [] if isinstance(r, dict)}
    unit = next(iter(sb.get("budget") or {"words_per_s": WPS}))
    over, under = [], []
    for name, (a, b) in zip(names, plan_times):
        r = planned.get(name)
        if not r:
            continue
        want = float((r.get("planned") or {}).get("dur") or r.get("dur") or 0)
        got = b - a
        if got > want + 0.25:
            n = (r.get("speech") or {}).get(unit.split("_")[0], 0)
            over.append("%s %.1f s (planned %s s%s)" % (name, got, _secs(want),
                                                       ", %s %s" % (n, unit.split("_")[0]) if n else ""))
        elif got < want - 0.5:
            under.append("%s %.1f s (planned %s s)" % (name, got, _secs(want)))
    notes = []
    if over:
        notes.append("storyboard: the voice outgrew %d shot(s): %s. Cut words in narration.md and rerun the voice, or "
                     "keep the longer shots and build their pictures to the new lengths" % (len(over), "; ".join(over)))
    if under:
        notes.append("storyboard: %d shot(s) are shorter than planned: %s (the narration ends early; keep the {at=...} "
                     "pins in narration.md, or --total for the last shot)" % (len(under), "; ".join(under)))
    if plan_times:
        total = plan_times[-1][1]
        want = float(sb.get("duration") or 0)
        if want and abs(total - want) > 0.5:
            notes.append("storyboard: %.1f s long, the storyboard planned %s s" % (total, _secs(want)))
    return notes
