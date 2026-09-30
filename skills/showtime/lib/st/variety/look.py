"""The look of a video project or job, read from its files (no render, no browser).

A look is what a viewer would call "the same style" across two videos:

  template     the showtime template the project came from (showtime.json "template"; older projects:
               inferred from their files)
  theme        the runtime theme the page loads (/_st/themes/<name>.css)
  palette      ground, text and accent colours (the page's :root tokens over its theme's; canvas films:
               their palette; a brand kit's colours when there is no page)
  type         the display and body families (--font-display / --font-body, loaded font files)
  transitions  scene handoffs by type, counted (a scene without data-transition is a cut)
  camera       camera verbs: push-in, pull-back, pan, drift, parallax, ken-burns, through, match
  music        each music track: catalog id (with its shelf and moods), composed style, file, synth score
  structure    scene count, scene lengths and their shape, aspect, total length
  tone         a tone preset named in the job's goal, assumptions or notes (references/tones.md)
  brand        the brand kit's name, so a series for one brand can share its palette on purpose

Everything is best effort: a field that cannot be read is left out, never guessed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import read_json, skill_dir

TONES = ("default", "polished", "playful", "deadpan", "chaotic", "cinematic", "app-store", "documentary",
         "retro", "corporate-parody", "minimal", "keynote", "technical")
GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "cursive", "fantasy", "ui-sans-serif",
                 "ui-serif", "ui-monospace", "ui-rounded", "georgia", "inherit", "initial"}
CAMERA_TRANSITIONS = {"through": "through", "match": "match", "pan": "pan", "zoom-through": "zoom-through",
                      "whip-pan": "whip-pan", "whip-blur": "whip-pan", "cross-zoom": "zoom-through"}
_SKIP_DIRS = {"media", "node_modules", "work", "fonts", "shots", "audio", "voice", "assets", "data", ".git"}
_MAX_READ = 3_000_000


def _read(p: Path) -> str:
    try:
        if p.stat().st_size > _MAX_READ:
            return p.read_text(encoding="utf-8", errors="replace")[:_MAX_READ]
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def norm_hex(c: Any) -> Optional[str]:
    """'#abc' / '#aabbcc' / '#aabbccdd' -> '#aabbcc' (lowercase); anything else -> None."""
    m = re.fullmatch(r"\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\s*", str(c or ""))
    if not m:
        return None
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return "#" + h[:6]


def hex_rgb(h: str) -> List[int]:
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def color_distance(a: str, b: str) -> float:
    """A perceptual-ish distance between two hex colours (weighted RGB, 0..~765)."""
    (r1, g1, b1), (r2, g2, b2) = hex_rgb(a), hex_rgb(b)
    rm = (r1 + r2) / 2.0
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def first_family(value: Optional[str]) -> Optional[str]:
    """First non-generic family of a CSS font-family list: "'Inter', sans-serif" -> "Inter"."""
    if not value:
        return None
    for part in str(value).split(","):
        name = part.strip().strip("'\"").strip()
        if name and name.lower() not in GENERIC_FONTS and not name.startswith("var("):
            return name
    return None


def root_vars(css: str) -> Dict[str, str]:
    """Custom properties declared in :root blocks (later declarations win)."""
    out: Dict[str, str] = {}
    for m in re.finditer(r":root[^{]*\{([^}]*)\}", css):
        for v in re.finditer(r"--([\w-]+)\s*:\s*([^;]+?)\s*(?:;|$)", m.group(1)):
            out[v.group(1)] = v.group(2).strip()
    return out


def themes_dir() -> Path:
    return skill_dir() / "runtime" / "themes"


def theme_names() -> List[str]:
    d = themes_dir()
    try:
        return sorted(p.stem for p in d.glob("*.css") if p.stem not in ("base", "fonts"))
    except OSError:
        return []


def theme_info(name: str) -> Dict[str, Any]:
    """{name, about, palette[bg, fg, accent, accent-2], type[display, body]} of a runtime theme."""
    p = themes_dir() / (name + ".css")
    text = _read(p)
    if not text:
        return {}
    v = root_vars(text)
    about = ""
    m = re.search(r"/\*\s*showtime theme:\s*[\w-]+\.\s*(.+?)(?:\n\s*Token contract|\*/)", text, re.S)
    if m:
        about = " ".join(m.group(1).split())
    pal = [norm_hex(v.get(k)) for k in ("bg", "fg", "accent", "accent-2")]
    typ = [first_family(v.get("font-display")), first_family(v.get("font-body"))]
    return {"name": name, "about": about, "palette": [c for c in pal if c], "type": [t for t in typ if t]}


def _project_texts(project: Path) -> Dict[str, str]:
    """The page (index.html) plus the project's own scripts and styles (not media, fonts or work)."""
    out: Dict[str, str] = {}
    try:
        entries = sorted(project.iterdir())
    except OSError:
        return out
    for p in entries:
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".mjs", ".css") and not p.name.endswith(".min.js"):
            out[p.name] = _read(p)
        elif p.is_dir() and p.name not in _SKIP_DIRS and not p.name.startswith("."):
            try:
                for q in sorted(p.iterdir())[:40]:
                    if q.is_file() and q.suffix.lower() in (".html", ".js", ".css"):
                        out["%s/%s" % (p.name, q.name)] = _read(q)
            except OSError:
                pass
        if len(out) > 60:
            break
    return out


def infer_template(project: Path, cfg: Dict[str, Any], texts: Dict[str, str]) -> Optional[str]:
    t = cfg.get("template")
    if isinstance(t, str) and t:
        return t
    names = set(texts) | {p.name for p in project.iterdir() if p.exists()} if project.is_dir() else set(texts)
    if "series.json" in names:
        return "series"
    if str(cfg.get("kind") or "").lower() == "launch":
        return "launch"
    if "words.json" in names:
        return "short"
    if "app.js" in names and "cues.js" in names:
        return "tutorial"
    if "scenes.js" in names or any("drawFilm" in v for v in texts.values()):
        return "film"
    if (project / "manim.json").is_file():
        return "manim"
    page = texts.get("index.html", "")
    if "/_st/themes/editorial.css" in page and ("data-st=\"chart\"" in page or "chart" in page):
        return "data"
    if page:
        return "dom"
    return None


def _transitions(texts: Dict[str, str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    def add(name: str) -> None:
        n = name.strip().lower()
        if n == "none":
            n = "cut"
        if n:
            counts[n] = counts.get(n, 0) + 1

    for name, t in texts.items():
        if name.endswith(".html"):
            scenes = re.findall(r"<(?:section|div)\b[^>]*\bclass=\"[^\"]*\bscene\b[^\"]*\"[^>]*>", t)
            for i, tag in enumerate(scenes):
                m = re.search(r"data-transition\s*=\s*[\"']\s*([a-z][\w-]*)", tag)
                if m:
                    add(m.group(1))
                elif i > 0 and "data-start" in tag:
                    add("cut")
            # transitions on elements that are not .scene sections
            for m in re.finditer(r"<(?![^>]*\bclass=\"[^\"]*\bscene\b)[^>]*data-transition\s*=\s*[\"']\s*([a-z][\w-]*)", t):
                add(m.group(1))
        for m in re.finditer(r"transition\(\s*\{[^}]*?\btype\s*:\s*['\"]([\w-]+)['\"]", t):
            add(m.group(1))
        # canvas films: F.sequence([... in: {type: 'wipe'} ... in: 'cut'])
        for m in re.finditer(r"\bin\s*:\s*(?:\{\s*type\s*:\s*)?['\"]([\w-]+)['\"]", t):
            add(m.group(1))
    return counts


def _camera(texts: Dict[str, str], transitions: Dict[str, int]) -> List[str]:
    verbs = set()
    for t in texts.values():
        for m in re.finditer(r"data-st\s*=\s*[\"']camera[\"'][^>]*", t):
            tag = m.group(0)
            zooms = [float(z) for z in re.findall(r"\"zoom\"\s*:\s*([\d.]+)", tag)]
            if len(zooms) >= 2:
                if max(zooms[1:]) > zooms[0] + 0.02:
                    verbs.add("push-in")
                if min(zooms[1:]) < max(zooms) - 0.02 and zooms[-1] < max(zooms):
                    verbs.add("pull-back")
            if re.search(r"\"focus\"\s*:", tag) and not zooms:
                verbs.add("pan")
            if "data-drift" in tag:
                verbs.add("drift")
        if re.search(r"data-st\s*=\s*[\"']camera", t) and not verbs & {"push-in", "pull-back", "pan"}:
            verbs.add("camera")
        if "data-depth" in t:
            verbs.add("parallax")
        if re.search(r"data-st\s*=\s*[\"']ken-burns", t) or "kenBurns" in t:
            verbs.add("ken-burns")
        if "withCamera" in t:
            zs = re.findall(r"zoom\s*:\s*F\.lerp\(\s*([\d.]+)\s*,\s*([\d.]+)", t)
            for a, b in zs:
                verbs.add("push-in" if float(b) > float(a) else "pull-back")
            if not zs:
                verbs.add("camera")
    for name in transitions:
        if name in CAMERA_TRANSITIONS:
            verbs.add(CAMERA_TRANSITIONS[name])
    return sorted(verbs)


def _fonts(texts: Dict[str, str], vars_: Dict[str, str]) -> List[str]:
    display = first_family(vars_.get("font-display"))
    body = first_family(vars_.get("font-body"))
    fams: List[str] = []
    for f in (display, body):
        if f and f not in fams:
            fams.append(f)
    if fams:
        return fams
    # canvas films and pages without tokens: loaded font files, then font-family declarations
    for t in texts.values():
        for m in re.finditer(r"@fontsource(?:-variable)?/([\w-]+)", t):
            n = m.group(1).replace("-", " ").title()
            if n not in fams:
                fams.append(n)
        for m in re.finditer(r"fonts/([\w-]+)/font\.css", t):
            n = m.group(1).replace("-", " ").title()
            if n not in fams:
                fams.append(n)
    if not fams:
        for t in texts.values():
            for m in re.finditer(r"font-family\s*:\s*([^;}\n]+)", t):
                n = first_family(m.group(1))
                if n and n not in fams:
                    fams.append(n)
    return fams[:3]


def _palette(texts: Dict[str, str], vars_: Dict[str, str], cfg: Dict[str, Any]) -> List[str]:
    pal: List[str] = []
    for k in ("bg", "fg", "accent", "accent-2"):
        c = norm_hex(vars_.get(k))
        if c and c not in pal:
            pal.append(c)
    bg = norm_hex(cfg.get("background"))
    if bg and bg not in pal:
        pal.insert(0, bg) if not pal else pal.append(bg)
    if len(pal) >= 3:
        return pal[:5]
    # canvas films: palette: { accent: '#..', ... }, else the most used colours in the page
    for t in texts.values():
        m = re.search(r"palette\s*:\s*\{([^}]*)\}", t)
        if m:
            for c in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", m.group(1)):
                h = norm_hex(c)
                if h and h not in pal:
                    pal.append(h)
    if len(pal) < 3:
        freq: Dict[str, int] = {}
        for t in texts.values():
            for c in re.findall(r"#[0-9a-fA-F]{6}\b", t):
                h = norm_hex(c)
                if h:
                    freq[h] = freq.get(h, 0) + 1
        for h, _n in sorted(freq.items(), key=lambda kv: -kv[1]):
            if h not in pal:
                pal.append(h)
            if len(pal) >= 4:
                break
    return pal[:5]


def _music(project: Path, cfg: Dict[str, Any], texts: Dict[str, str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    audio = cfg.get("audio")
    mix = None
    if isinstance(audio, str) and audio:
        mix = read_json(project / audio, None) if (project / audio).is_file() else None
    elif isinstance(audio, dict):
        mix = audio
    for tr in (mix or {}).get("tracks", []) if isinstance(mix, dict) else []:
        if not isinstance(tr, dict) or str(tr.get("kind") or "") != "music":
            continue
        if tr.get("catalog"):
            row: Dict[str, Any] = {"ref": "catalog:%s" % tr["catalog"]}
            try:
                from ..audio import music as mus
                t = mus.get(str(tr["catalog"]))
                row.update(shelf=t.get("shelf"), moods=t.get("moods") or [], title=t.get("title"))
            except Exception:  # noqa: BLE001 - an unknown id is still a repeatable fact
                pass
            out.append(row)
        elif isinstance(tr.get("compose"), dict):
            c = tr["compose"]
            out.append({"ref": "compose:%s" % (c.get("style") or "default"), "style": c.get("style")})
        elif tr.get("library") or tr.get("lib"):
            out.append({"ref": "library:%s" % (tr.get("library") or tr.get("lib"))})
        elif tr.get("file") or tr.get("src"):
            out.append({"ref": "file:%s" % Path(str(tr.get("file") or tr.get("src"))).name})
    if cfg.get("score"):
        bpm = None
        for t in texts.values():
            m = re.search(r"\bbpm\s*:\s*(\d+)", t)
            if m:
                bpm = int(m.group(1))
                break
        out.append({"ref": "score:synth", "bpm": bpm})
    return out


def _structure(texts: Dict[str, str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    durs: List[float] = []
    ids: List[str] = []
    page = texts.get("index.html", "")
    for tag in re.findall(r"<(?:section|div)\b[^>]*\bclass=\"[^\"]*\bscene\b[^\"]*\"[^>]*>", page):
        if "data-start" not in tag:
            continue
        m = re.search(r"data-dur\s*=\s*[\"']([\d.]+)", tag)
        if m:
            durs.append(float(m.group(1)))
        i = re.search(r"\bid\s*=\s*[\"']([\w-]+)", tag)
        ids.append(i.group(1) if i else "")
    if not durs:
        for t in texts.values():   # canvas films: F.sequence entries
            n = len(re.findall(r"\{\s*t0\s*:", t))
            if n:
                ids = [""] * n
                break
    W, H = int(cfg.get("width") or 0), int(cfg.get("height") or 0)
    st: Dict[str, Any] = {"scenes": len(ids) or None}
    if W and H:
        st["aspect"] = _aspect(W, H)
    if cfg.get("duration"):
        st["duration"] = round(float(cfg["duration"]), 2)
    if durs:
        st["durations"] = [round(d, 2) for d in durs]
        st["shape"] = shape_of(durs)
    if any(ids):
        st["ids"] = ids
    return st


def _aspect(W: int, H: int) -> str:
    r = W / float(H)
    for name, v in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8), ("21:9", 21 / 9), ("4:3", 4 / 3)):
        if abs(r - v) < 0.03:
            return name
    return "%dx%d" % (W, H)


def shape_of(durs: Sequence[float]) -> str:
    """How scene lengths run: even (a metronome of equal cards), building (shorter to longer),
    tightening (longer to shorter) or varied."""
    d = [float(x) for x in durs if x]
    if len(d) < 2:
        return "single"
    mean = sum(d) / len(d)
    spread = (max(d) - min(d)) / mean if mean else 0
    if spread < 0.35:
        return "even"
    half = len(d) // 2
    a, b = sum(d[:half]) / max(1, half), sum(d[-half:]) / max(1, half)
    if b > a * 1.3:
        return "building"
    if a > b * 1.3:
        return "tightening"
    return "varied"


def _tone(texts: Sequence[str]) -> Optional[str]:
    blob = " ".join(texts).lower()
    for t in TONES:
        if re.search(r"\btone\s*[:=]?\s*[\"']?%s\b" % re.escape(t), blob) or \
                re.search(r"\b%s\s+tone\b" % re.escape(t), blob) or re.search(r"\b%s\s+preset\b" % re.escape(t), blob):
            return t
    return None


def project_look(project: Path) -> Dict[str, Any]:
    """The look of one project folder (showtime.json + index.html + its scripts)."""
    project = Path(project)
    cfg = read_json(project / "showtime.json", {}) if (project / "showtime.json").is_file() else {}
    if not isinstance(cfg, dict):
        cfg = {}
    texts = _project_texts(project)
    page = texts.get("index.html", "")
    look: Dict[str, Any] = {"project": str(project.resolve())}
    tpl = infer_template(project, cfg, texts)
    if tpl:
        look["template"] = tpl
        look["template_source"] = "showtime.json" if cfg.get("template") else "inferred"
    m = re.search(r"/_st/themes/([\w-]+)\.css", page) or re.search(r"data-theme\s*=\s*[\"']([\w-]+)", page)
    theme = m.group(1) if m and m.group(1) not in ("base", "fonts") else None
    vars_: Dict[str, str] = {}
    if theme:
        look["theme"] = theme
        vars_.update(root_vars(_read(themes_dir() / (theme + ".css"))))
    for name, t in texts.items():
        if name.endswith((".html", ".css")):
            vars_.update(root_vars(t))
    pal = _palette(texts, vars_, cfg)
    if pal:
        look["palette"] = pal
    fonts = _fonts(texts, vars_)
    if fonts:
        look["type"] = fonts
    tr = _transitions(texts)
    if tr:
        look["transitions"] = tr
    cam = _camera(texts, tr)
    if cam:
        look["camera"] = cam
    mus = _music(project, cfg, texts)
    if mus:
        look["music"] = mus
    look["structure"] = _structure(texts, cfg)
    if cfg.get("kind"):
        look["kind"] = cfg["kind"]
    tone = _tone([json.dumps(cfg.get("tone") or ""), " ".join(v for k, v in texts.items() if k.endswith(".html"))[:20000]])
    if isinstance(cfg.get("tone"), str) and cfg["tone"].lower() in TONES:
        tone = cfg["tone"].lower()
    if tone:
        look["tone"] = tone
    return look


def _brand(job: Path) -> Optional[Dict[str, Any]]:
    for p in (job / "brand.json", job / "brand" / "brand.json"):
        if p.is_file():
            b = read_json(p, None)
            if isinstance(b, dict):
                return b
    return None


def _brand_palette(b: Dict[str, Any]) -> List[str]:
    cols = b.get("colors") or b.get("palette") or {}
    vals = list(cols.values()) if isinstance(cols, dict) else list(cols) if isinstance(cols, list) else []
    out: List[str] = []
    for v in vals:
        h = norm_hex(v if not isinstance(v, dict) else (v.get("hex") or v.get("value")))
        if h and h not in out:
            out.append(h)
    return out[:5]


def _brand_type(b: Dict[str, Any]) -> List[str]:
    f = b.get("fonts") or b.get("type") or b.get("typography") or {}
    out: List[str] = []
    vals = list(f.values()) if isinstance(f, dict) else list(f) if isinstance(f, list) else []
    for v in vals:
        n = first_family(v if isinstance(v, str) else (v.get("family") if isinstance(v, dict) else None))
        if n and n not in out:
            out.append(n)
    return out[:3]


def _plan_structure(job: Path) -> Optional[Dict[str, Any]]:
    """Scene count and lengths from a storyboard or plan in the job (when there is no project yet)."""
    for name in ("storyboard.md", "plan.md", "script.md"):
        p = job / name
        if not p.is_file():
            continue
        text = _read(p)
        heads = re.findall(r"(?m)^#{2,3}\s+(.+)$", text)
        rows = re.findall(r"(?m)^\|\s*\d+\s*\|", text)
        n = len(rows) or len([h for h in heads if re.search(r"scene|shot|beat|\d", h, re.I)])
        durs = [float(x) for x in re.findall(r"(?<![\d.])(\d{1,2}(?:\.\d+)?)\s*s\b", text)][:40]
        if n:
            st: Dict[str, Any] = {"scenes": n, "source": name}
            if len(durs) == n:
                st["durations"] = durs
                st["shape"] = shape_of(durs)
            return st
    return None


def job_look(job: Path) -> Dict[str, Any]:
    """The look of a job: its project's look, plus brand kit, tone and (without a project) the plan."""
    from ..job import ledger
    job = Path(job)
    data = ledger.load(job) if (job / "job.json").is_file() else {}
    proj = ledger.project_of(job, data) if data else (str(ledger.detect_project(job) or "") or None)
    look: Dict[str, Any] = {}
    if proj and Path(proj).is_dir():
        look = project_look(Path(proj))
    look["job"] = job.name
    look["job_path"] = str(job.resolve())
    b = _brand(job)
    if b:
        look["brand"] = str(b.get("name") or b.get("product") or "brand kit")
        if not look.get("palette"):
            bp = _brand_palette(b)
            if bp:
                look["palette"] = bp
        if not look.get("type"):
            bt = _brand_type(b)
            if bt:
                look["type"] = bt
    if not (look.get("structure") or {}).get("scenes"):
        ps = _plan_structure(job)
        if ps:
            look["structure"] = dict(look.get("structure") or {}, **ps)
    if not look.get("tone"):
        words = [str(data.get("goal") or "")]
        for k in ("assumed", "verified", "decisions"):
            for it in data.get(k) or []:
                words.append(str(it.get("text") if isinstance(it, dict) else it))
        for name in ("SHOWTIME.md", "brief.md", "storyboard.md", "plan.md"):
            if (job / name).is_file():
                words.append(_read(job / name)[:20000])
        t = _tone(words)
        if t:
            look["tone"] = t
    return look


def summary(look: Dict[str, Any]) -> str:
    """One line: template/theme, palette, type, primary transition, music."""
    parts = []
    if look.get("template") or look.get("theme"):
        parts.append("/".join(x for x in (look.get("template"), look.get("theme")) if x))
    if look.get("palette"):
        parts.append(" ".join(look["palette"][:4]))
    if look.get("type"):
        parts.append(" + ".join(look["type"][:2]))
    tr = look.get("transitions") or {}
    if tr:
        top = sorted(tr.items(), key=lambda kv: (-kv[1], kv[0]))
        parts.append(", ".join("%s x%d" % kv for kv in top[:3]))
    if look.get("camera"):
        parts.append("camera: " + ", ".join(look["camera"]))
    for m in look.get("music") or []:
        parts.append(m.get("ref", ""))
    st = look.get("structure") or {}
    if st.get("scenes"):
        parts.append("%s scenes%s" % (st["scenes"], (" " + st["shape"]) if st.get("shape") else ""))
    if look.get("tone"):
        parts.append("tone " + look["tone"])
    return "; ".join(p for p in parts if p)
