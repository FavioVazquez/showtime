"""Look signatures: the curated looks a new project starts in, rotated away from this machine's recent videos.

A signature is a whole look, the way a film score is a whole sound: a palette (ground, ink, muted, surfaces,
two accents), a type pairing (display, body, mono, with the display's weight and tracking), a motion feel
(the theme's motion tokens: durations, staggers, eases) and a background treatment (how much key light,
grid and vignette the template paints on its ground). Each one is good on its own and passes the contrast
rules (ink >= 7:1, muted and accent text >= 4.8:1, the ink on the accent >= 4.5:1).

`showtime new` on a page template (dom, launch, short, data) picks one and writes it into the page as a
`<style id="st-look">` block of CSS tokens, after the template's own style (so it wins over the template and
its theme) and before a brand kit's block (so a brand kit wins over it). The pick is seeded (the project's
folder name, or --look-seed) and avoids the signatures and palettes of the last RECENT_PICKS projects
created here and the last RECENT finished videos (the look history), so three projects in a row get three
different looks. A brand kit, a job's style reference or an explicit --look always wins; --look template
keeps the template's own look. `showtime signature` lists them and swaps a project's.

The picks are kept next to the look history (<SHOWTIME_HOME>/history/picks.json, local only, the newest
MAX_PICKS); `showtime history off` stops recording them too.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import ShowtimeError, read_json, write_json

# the templates that draw from theme tokens; canvas templates (film, tutorial, series) keep their own looks
TEMPLATES = {"dom": ("dark", "light"), "launch": ("dark", "light"), "short": ("dark", "light"), "data": ("light",)}
RECENT_PICKS = 6
MAX_PICKS = 30

FONT_FILES = {
    "Inter": "inter", "Geist": "geist", "Geist Mono": "geist-mono", "JetBrains Mono": "jetbrains-mono",
    "Space Grotesk": "space-grotesk", "Instrument Serif": "instrument-serif", "Fraunces": "fraunces",
    "Anton": "anton", "Bebas Neue": "bebas-neue", "Bricolage Grotesque": "bricolage-grotesque",
    "IBM Plex Sans": "ibm-plex-sans", "IBM Plex Mono": "ibm-plex-mono", "Unbounded": "unbounded",
}
SERIF = {"Fraunces", "Instrument Serif"}

# motion feels: the theme's motion tokens (read by the motion components and the templates' CSS)
MOTION = {
    "snappy": {"--motion-energy": "high", "--dur-in": "0.45s", "--dur-out": "0.28s", "--dur-beat": "0.3s", "--stagger": "0.04s",
               "--ease-out": "cubic-bezier(0.16, 1, 0.3, 1)", "--ease-move": "cubic-bezier(0.65, 0, 0.35, 1)",
               "--ease-emph": "cubic-bezier(0.34, 1.4, 0.64, 1)"},
    "smooth": {"--motion-energy": "medium", "--dur-in": "0.6s", "--dur-out": "0.35s", "--dur-beat": "0.4s", "--stagger": "0.055s",
               "--ease-out": "cubic-bezier(0.22, 1, 0.36, 1)", "--ease-move": "cubic-bezier(0.65, 0, 0.35, 1)",
               "--ease-emph": "cubic-bezier(0.34, 1.2, 0.64, 1)"},
    "calm": {"--motion-energy": "low", "--dur-in": "0.8s", "--dur-out": "0.45s", "--dur-beat": "0.5s", "--stagger": "0.07s",
             "--ease-out": "cubic-bezier(0.2, 0, 0, 1)", "--ease-move": "cubic-bezier(0.37, 0, 0.63, 1)",
             "--ease-emph": "cubic-bezier(0.2, 0, 0, 1)"},
    "bouncy": {"--motion-energy": "high", "--dur-in": "0.5s", "--dur-out": "0.3s", "--dur-beat": "0.35s", "--stagger": "0.05s",
               "--ease-out": "cubic-bezier(0.16, 1, 0.3, 1)", "--ease-move": "cubic-bezier(0.65, 0, 0.35, 1)",
               "--ease-emph": "cubic-bezier(0.34, 1.56, 0.64, 1)"},
    "precise": {"--motion-energy": "medium", "--dur-in": "0.4s", "--dur-out": "0.25s", "--dur-beat": "0.3s", "--stagger": "0.03s",
                "--ease-out": "cubic-bezier(0.2, 0, 0, 1)", "--ease-move": "cubic-bezier(0.4, 0, 0.2, 1)",
                "--ease-emph": "cubic-bezier(0.2, 0, 0, 1)"},
}

# background treatments: multipliers on the key light / glows, the grid and the vignette the page templates
# paint (--ground-glow, --ground-grid, --ground-vignette; 1 = the template's own ground). Light grounds take a
# third of the vignette: a dark edge on paper reads as dirt.
GROUND = {
    "lit": {"glow": 1.0, "grid": 1.0, "vignette": 1.0, "about": "lit ground"},
    "soft": {"glow": 0.55, "grid": 0.5, "vignette": 0.7, "about": "soft light"},
    "flat": {"glow": 0.15, "grid": 0.0, "vignette": 0.5, "about": "flat ground"},
    "spot": {"glow": 1.35, "grid": 0.35, "vignette": 1.5, "about": "spotlit, deep edges"},
    "grid": {"glow": 0.5, "grid": 1.8, "vignette": 0.8, "about": "drafting grid"},
}

SIGNATURES: List[Dict[str, Any]] = [
    {"id": "nocturne", "name": "Nocturne", "about": "ink-blue night, lilac accent, a soft serif display",
     "palette": {"bg": "#0f1020", "fg": "#eef0fb", "muted": "#a4a9c6", "surface": "#1a1c31", "surface-2": "#24263f",
                 "accent": "#9d8cff", "accent-2": "#ff9e7a", "accent-ink": "#120f2a"},
     "type": {"display": "Fraunces", "body": "Inter", "mono": "JetBrains Mono", "weight": 600, "tracking": "-0.02em", "leading": 1.0},
     "motion": "smooth", "ground": "soft"},
    {"id": "tidewater", "name": "Tidewater", "about": "deep teal, coral accent, a crisp geometric grotesk",
     "palette": {"bg": "#0b1a1c", "fg": "#eaf4f1", "muted": "#9fbab4", "surface": "#13272a", "surface-2": "#1b3337",
                 "accent": "#ff7f61", "accent-2": "#6fd3c1", "accent-ink": "#1a0d08"},
     "type": {"display": "Space Grotesk", "body": "Inter", "mono": "Geist Mono", "weight": 700, "tracking": "-0.03em", "leading": 0.98},
     "motion": "snappy", "ground": "lit"},
    {"id": "graphite", "name": "Graphite", "about": "charcoal, acid-lime accent, one precise sans",
     "palette": {"bg": "#121212", "fg": "#f2f2ef", "muted": "#aaaaa4", "surface": "#1c1c1b", "surface-2": "#262625",
                 "accent": "#c8f135", "accent-2": "#7ab4ff", "accent-ink": "#141a02"},
     "type": {"display": "Geist", "body": "Geist", "mono": "Geist Mono", "weight": 650, "tracking": "-0.035em", "leading": 0.96},
     "motion": "precise", "ground": "flat"},
    {"id": "redline", "name": "Redline", "about": "warm black, signal red, a tall condensed headline face",
     "palette": {"bg": "#150d0d", "fg": "#fbf1ee", "muted": "#c8aea8", "surface": "#221615", "surface-2": "#2e1e1c",
                 "accent": "#ff5a47", "accent-2": "#ffd166", "accent-ink": "#1a0604"},
     "type": {"display": "Anton", "body": "Inter", "mono": "JetBrains Mono", "weight": 400, "tracking": "0.005em", "leading": 1.0,
              "case": "uppercase"},
     "motion": "snappy", "ground": "spot"},
    {"id": "evergreen", "name": "Evergreen", "about": "pine-dark ground, peach accent, an editorial serif",
     "palette": {"bg": "#0e1a13", "fg": "#eef5ec", "muted": "#a6bca8", "surface": "#16261c", "surface-2": "#1f3226",
                 "accent": "#ffb38a", "accent-2": "#9fd9a6", "accent-ink": "#1f0f06"},
     "type": {"display": "Instrument Serif", "body": "IBM Plex Sans", "mono": "IBM Plex Mono", "weight": 400, "tracking": "-0.01em", "leading": 1.0},
     "motion": "calm", "ground": "soft"},
    {"id": "cobalt", "name": "Cobalt", "about": "cobalt night, candy-pink accent, a wide rounded display",
     "palette": {"bg": "#0a1433", "fg": "#f0f4ff", "muted": "#a9b6d9", "surface": "#121f45", "surface-2": "#1a2a57",
                 "accent": "#ff8fb1", "accent-2": "#7fd6ff", "accent-ink": "#2a0614"},
     "type": {"display": "Unbounded", "body": "Space Grotesk", "mono": "JetBrains Mono", "weight": 600, "tracking": "-0.03em", "leading": 1.02},
     "motion": "bouncy", "ground": "lit",
     "not": ["short"]},     # the widest face: the vertical short's big type runs under the app's side rail
    {"id": "oxblood", "name": "Oxblood", "about": "wine-dark ground, mint accent, a heavy friendly grotesk",
     "palette": {"bg": "#1a0f14", "fg": "#f7ece9", "muted": "#c4a9ae", "surface": "#26161d", "surface-2": "#321e27",
                 "accent": "#8fe0c8", "accent-2": "#b5a1ff", "accent-ink": "#06201a"},
     "type": {"display": "Bricolage Grotesque", "body": "Inter", "mono": "Geist Mono", "weight": 760, "tracking": "-0.035em", "leading": 0.95},
     "motion": "smooth", "ground": "spot"},
    {"id": "paperback", "name": "Paperback", "about": "warm paper, burnt-orange accent, a bookish serif",
     "palette": {"bg": "#f6f0e4", "fg": "#1c1a17", "muted": "#59534a", "surface": "#ece4d4", "surface-2": "#e2d8c4",
                 "accent": "#b13d0b", "accent-2": "#1f5f8b", "accent-ink": "#fff8f0"},
     "type": {"display": "Fraunces", "body": "IBM Plex Sans", "mono": "IBM Plex Mono", "weight": 700, "tracking": "-0.025em", "leading": 0.98},
     "motion": "calm", "ground": "flat"},
    {"id": "gallery", "name": "Gallery", "about": "white wall, poster red, a condensed all-caps headline",
     "palette": {"bg": "#f3f3f0", "fg": "#111111", "muted": "#53534e", "surface": "#e7e7e3", "surface-2": "#dcdcd7",
                 "accent": "#bf2116", "accent-2": "#1d4ed8", "accent-ink": "#ffffff"},
     "type": {"display": "Bebas Neue", "body": "Inter", "mono": "JetBrains Mono", "weight": 400, "tracking": "0.01em", "leading": 0.95,
              "case": "uppercase"},
     "motion": "snappy", "ground": "flat"},
    {"id": "sage", "name": "Sage", "about": "pale sage, deep green accent, a warm grotesk",
     "palette": {"bg": "#e9efe7", "fg": "#16201a", "muted": "#4a5a4f", "surface": "#dde6da", "surface-2": "#d0dccc",
                 "accent": "#1b6f52", "accent-2": "#b5502f", "accent-ink": "#f2fbf6"},
     "type": {"display": "Bricolage Grotesque", "body": "Inter", "mono": "Geist Mono", "weight": 700, "tracking": "-0.03em", "leading": 0.96},
     "motion": "smooth", "ground": "soft"},
    {"id": "blush", "name": "Blush", "about": "rose paper, raspberry accent, an elegant serif with a clean sans",
     "palette": {"bg": "#f8ece8", "fg": "#2a1616", "muted": "#6a4a48", "surface": "#f0dfda", "surface-2": "#e7d1cb",
                 "accent": "#a8204f", "accent-2": "#2a6a8a", "accent-ink": "#fff5f8"},
     "type": {"display": "Instrument Serif", "body": "Geist", "mono": "Geist Mono", "weight": 400, "tracking": "-0.01em", "leading": 1.0},
     "motion": "calm", "ground": "soft"},
    {"id": "skyline", "name": "Skyline", "about": "cool blueprint paper, deep blue accent, a technical grotesk on a grid",
     "palette": {"bg": "#e9f0f8", "fg": "#0f1b2d", "muted": "#46566b", "surface": "#dce6f2", "surface-2": "#cfdcec",
                 "accent": "#0b5ccc", "accent-2": "#c84d1c", "accent-ink": "#ffffff"},
     "type": {"display": "Space Grotesk", "body": "IBM Plex Sans", "mono": "IBM Plex Mono", "weight": 700, "tracking": "-0.03em", "leading": 0.98},
     "motion": "precise", "ground": "grid"},
]
_BY_ID = {s["id"]: s for s in SIGNATURES}

BLOCK_RX = re.compile(r"\n?<!-- look signature: .*? -->\n(?:<link rel=\"stylesheet\" href=\"[^\"]*\" data-st-look>\n)*"
                      r"<style id=\"st-look\">.*?</style>\n?", re.S)


# ------------------------------------------------------------------ the catalog

def catalog() -> List[Dict[str, Any]]:
    return [dict(s, polarity=polarity(s)) for s in SIGNATURES]


def get(sig_id: str) -> Dict[str, Any]:
    s = _BY_ID.get(str(sig_id or "").strip().lower())
    if not s:
        raise ShowtimeError("unknown look signature %r" % sig_id, hint="known: %s (or auto, template)" % ", ".join(_BY_ID))
    return dict(s, polarity=polarity(s))


def polarity(sig: Dict[str, Any]) -> str:
    from ..brand import luminance
    return "light" if luminance(sig["palette"]["bg"]) > 0.4 else "dark"


def compatible(template: Optional[str]) -> List[Dict[str, Any]]:
    """The signatures a template can wear ([] for a template that keeps its own look)."""
    pols = TEMPLATES.get(str(template or ""))
    return [s for s in catalog() if s["polarity"] in pols and template not in s.get("not", ())] if pols else []


def describe(sig: Dict[str, Any]) -> str:
    t = sig["type"]
    pair = t["display"] if t["display"] == t["body"] else "%s + %s" % (t["display"], t["body"])
    return "%s: %s; %s, %s motion, %s" % (sig["name"], sig["about"], pair, sig["motion"], GROUND[sig["ground"]]["about"])


# ------------------------------------------------------------------ tokens and the page block

def _rgba(hexv: str, a: float) -> str:
    from ..brand import rgb
    r, g, b = rgb(hexv)
    return "rgb(%d %d %d / %s)" % (r, g, b, ("%.2f" % a).rstrip("0").rstrip("."))


def _family(name: str, kind: str) -> str:
    fb = {"display": "Georgia, serif" if name in SERIF else "'Inter', sans-serif",
          "body": "Georgia, serif" if name in SERIF else "'Inter', sans-serif", "mono": "ui-monospace, monospace"}[kind]
    return "'%s', %s" % (name, fb)


# The glows a template paints on screen where its text sits: (palette key, strength at the glow's peak), dark
# and light grounds apart (the launch template's key light is weaker on paper). dom and data put theirs off the
# frame's text. A signature's --ground-glow is lowered (not below the template's floor) until ink, muted and
# accent text keep GLOW_TEXT_RATIO on each glow; at the floor, muted and accent text move toward the ink extreme
# just enough instead (brand.apply.ensure). launch keeps at least GLOW_FLOOR: its drifting key light is the only
# motion on the end card.
GLOW_PATCHES = {
    "short": {"dark": [("accent-2", 0.34), ("accent", 0.38)], "light": [("accent-2", 0.34), ("accent", 0.38)]},
    "launch": {"dark": [("accent", 0.17)], "light": [("accent", 0.14)]},
}
GLOW_TEXT_RATIO = 4.8
GLOW_FLOOR = {"launch": 0.7}


def _patches(sig: Dict[str, Any], template: Optional[str]) -> List[Any]:
    return GLOW_PATCHES.get(str(template or ""), {}).get(polarity(sig), [])


def _glow_ok(pal: Dict[str, str], patches: Sequence[Any], x: float) -> bool:
    from ..brand import contrast
    from ..brand.apply import mix
    for key, s in patches:
        ground = mix(pal["bg"], pal[key], min(1.0, s * x))
        if any(contrast(pal[t], ground) < GLOW_TEXT_RATIO for t in ("fg", "muted", "accent")):
            return False
    return True


def glow_for(sig: Dict[str, Any], template: Optional[str]) -> float:
    """The --ground-glow a signature gets on a template: its ground's (at least the template's floor), lowered
    toward the floor while text would lose contrast on the template's glows."""
    p = sig["palette"]
    floor = GLOW_FLOOR.get(str(template or ""), 0.0)
    g = max(GROUND[sig["ground"]]["glow"], floor)
    patches = _patches(sig, template)
    if _glow_ok(p, patches, g):
        return g
    lo, hi = floor, g
    if not _glow_ok(p, patches, lo):
        return floor
    for _ in range(20):
        mid = (lo + hi) / 2
        if _glow_ok(p, patches, mid):
            lo = mid
        else:
            hi = mid
    return round(lo - 0.005, 2)


def text_colors(sig: Dict[str, Any], template: Optional[str], glow: float) -> Dict[str, str]:
    """muted and accent as the template's glows need them at this glow (unchanged when they already read)."""
    from ..brand.apply import ensure, mix
    p = dict(sig["palette"])
    for key, s in _patches(sig, template):
        ground = mix(p["bg"], p[key], min(1.0, s * glow))
        for t in ("muted", "accent"):
            p[t] = ensure(p[t], ground, GLOW_TEXT_RATIO)[0]
    return {"muted": p["muted"], "accent": p["accent"]}


def tokens(sig: Dict[str, Any], template: Optional[str] = None) -> Dict[str, str]:
    """CSS custom properties for the theme token contract (and the page templates' own tokens)."""
    p, ty = sig["palette"], sig["type"]
    light = polarity(sig) == "light"
    g = dict(GROUND[sig["ground"]], glow=glow_for(sig, template))
    p = dict(p, **text_colors(sig, template, g["glow"]))
    case = ty.get("case", "none")
    # the colours go through the brand kit's token builder: the same legibility rules for the product
    # window, its chips and the world light (text >= 4.8:1 on every ground it sits on, also on its accent mark)
    from ..brand.apply import tokens as brand_tokens
    t, _notes = brand_tokens({"palette": {"bg": p["bg"], "ink": p["fg"], "muted": p["muted"], "accent": p["accent"],
                                          "surface": p["surface"]}})
    t.update({
        "--surface": p["surface"], "--surface-2": p["surface-2"], "--border": _rgba(p["fg"], 0.14),
        "--accent-2": p["accent-2"], "--accent-ink": p["accent-ink"],
        "--font-display": _family(ty["display"], "display"), "--font-body": _family(ty["body"], "body"),
        "--font-mono": _family(ty["mono"], "mono"),
        "--weight-display": str(ty["weight"]), "--tracking-display": ty["tracking"], "--leading-display": str(ty["leading"]),
        "--case-display": case,
        "--cap-font": _family(ty["display"], "display"), "--cap-weight": str(ty["weight"]), "--cap-case": case,
        # captions: the ink with an outline in the ground (dark ink on paper, as the paper theme does)
        "--cap-ink": p["fg"], "--cap-outline": p["bg"] if light else "#000000",
        "--cap-accent": p["accent"], "--cap-active-ink": p["accent-ink"], "--cap-plate": _rgba(p["bg"], 0.94 if light else 0.8),
        "--ground-glow": "%g" % g["glow"], "--ground-grid": "%g" % g["grid"],
        "--ground-vignette": "%g" % round(g["vignette"] * (0.33 if light else 1.0), 3),
        "--grain": "0.03" if sig["ground"] in ("flat", "soft") else "0.04",
        "color-scheme": "light" if light else "dark",
    })
    t.update(MOTION[sig["motion"]])
    if light:
        # the launch template's world light and window: an accent-tinted key light, ink shadows (black ones are dirt on paper)
        t.update({"--rim-b": "transparent", "--key-light": _rgba(p["accent"], round(0.14 * g["glow"], 3)),
                  "--rim-a": _rgba(p["accent"], round(0.06 * g["glow"], 3)),
                  "--win-shadow": "0 3cqh 8cqh %s, 0 0.5cqh 1.4cqh %s" % (_rgba(p["fg"], 0.20), _rgba(p["fg"], 0.08)),
                  "--win-shadow-tall": "0 1.2cqh 3cqh %s" % _rgba(p["fg"], 0.16),
                  "--shadow": "0 3cqmin 9cqmin %s" % _rgba(p["fg"], 0.18)})
    else:
        t["--rim-b"] = _rgba(p["accent-2"], 0.07)
    return t


def font_links(sig: Dict[str, Any]) -> List[str]:
    ty = sig["type"]
    names = list(dict.fromkeys([ty["display"], ty["body"], ty["mono"]]))
    return ['<link rel="stylesheet" href="/_st/themes/fonts/%s.css" data-st-look>' % FONT_FILES[n] for n in names if n in FONT_FILES]


def block(sig: Dict[str, Any], template: Optional[str] = None) -> str:
    decl = "\n".join("    %s: %s;" % kv for kv in tokens(sig, template).items())
    return ("<!-- look signature: %s (%s), picked by `showtime new`; another: showtime signature apply <project> <id> -->\n"
            "%s<style id=\"st-look\">\n  :root {\n%s\n  }\n</style>\n") % (
        sig["name"], sig["id"], "".join(line + "\n" for line in font_links(sig)), decl)


def strip(text: str) -> str:
    return BLOCK_RX.sub("\n", text)


def write_block(page: Path, sig: Optional[Dict[str, Any]], template: Optional[str] = None) -> None:
    """Put the signature's block into the page (replacing an earlier one), or take it out (sig None). It goes
    before </head>, but before a brand kit's block and a style reference's link when the page has them, so
    those keep the last word."""
    text = strip(page.read_text(encoding="utf-8"))
    if sig is not None:
        b = block(sig, template)
        ends = [i for i in (text.find("<!-- brand kit:"), text.find('<link rel="stylesheet" href="reference-style.css">'),
                            text.find("</head>")) if i >= 0]
        if not ends:
            raise ShowtimeError("%s has no </head>" % page.name, hint="look signatures go into a page's <head>")
        i = min(ends)
        text = text[:i].rstrip("\n") + "\n" + b + text[i:]
    page.write_text(text, encoding="utf-8", newline="\n")


def applied(project: Path, page: str = "index.html") -> Optional[str]:
    try:
        m = re.search(r"<!-- look signature: .*? \(([\w-]+)\)", (Path(project) / page).read_text(encoding="utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


# ------------------------------------------------------------------ picking

def _picks_file() -> Path:
    from . import history
    return history.folder() / "picks.json"


def recent_picks(n: int = RECENT_PICKS) -> List[Dict[str, Any]]:
    d = read_json(_picks_file(), None) if _picks_file().is_file() else None
    rows = [x for x in (d or {}).get("picks", []) if isinstance(x, dict) and x.get("id")] if isinstance(d, dict) else []
    return rows[-n:][::-1]


def record_pick(sig_id: str, project: Path) -> None:
    from . import history
    if not history.enabled()[0]:
        return
    import time
    d = read_json(_picks_file(), None) if _picks_file().is_file() else None
    rows = [x for x in (d or {}).get("picks", []) if isinstance(x, dict)] if isinstance(d, dict) else []
    rows = [x for x in rows if x.get("project") != str(project)]
    rows.append({"id": sig_id, "project": str(project), "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    write_json(_picks_file(), {"about": "look signatures picked by `showtime new` (and `edit render` for cards) on this machine (local only)",
                               "picks": rows[-MAX_PICKS:]})


def _seed_int(seed: Any) -> int:
    return int(hashlib.sha1(str(seed).encode("utf-8")).hexdigest()[:8], 16)


def rank(template: str, seed: Any, picks: Sequence[Dict[str, Any]] = (), looks: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """The template's signatures, best first: the ones furthest from the recent picks and finished looks,
    ties in a seeded order. picks: [{id}] newest first; looks: look-history rows newest first."""
    from .history import palette_match
    cands = compatible(template)
    s = _seed_int(seed)
    pick_ids = [str(x.get("id")) for x in picks]
    out = []
    for c in cands:
        pal = [c["palette"][k] for k in ("bg", "fg", "accent", "accent-2")]
        pen = 0.0
        for i, pid in enumerate(pick_ids):
            if pid == c["id"]:
                pen += 100.0 / (1 + i)
        for i, lk in enumerate(looks):
            w = 1.0 / (1 + i)
            if lk.get("signature") == c["id"]:
                pen += 100.0 * w
            if palette_match(pal, lk.get("palette") or []):
                pen += 60.0 * w
            ty = lk.get("type") or []
            if ty and ty[0].lower() == c["type"]["display"].lower():
                pen += 15.0 * w
        # a recent pick with the same display face or ground polarity counts a little
        for i, pid in enumerate(pick_ids[:3]):
            o = _BY_ID.get(pid)
            if o and o["id"] != c["id"]:
                if o["type"]["display"] == c["type"]["display"]:
                    pen += 8.0 / (1 + i)
                if polarity(o) == c["polarity"]:
                    pen += 3.0 / (1 + i)
        tie = _seed_int("%d:%s" % (s, c["id"]))
        out.append((pen, tie, c))
    out.sort(key=lambda x: (x[0], x[1]))
    return [c for _p, _t, c in out]


def choose(template: str, seed: Any, use_history: bool = True) -> Optional[Dict[str, Any]]:
    looks: List[Dict[str, Any]] = []
    picks: List[Dict[str, Any]] = []
    if use_history:
        from . import history
        if history.enabled()[0]:
            looks = history.recent()
            picks = recent_picks()
    ranked = rank(template, seed, picks, looks)
    return ranked[0] if ranked else None


def apply_to_project(project: Path, template: str, choice: Optional[str] = "auto", seed: Any = None) -> Optional[Dict[str, Any]]:
    """Give a new project its signature. choice: auto (rotate), template (keep the template's look) or an id.
    Returns {id, name, describe, how, auto} or None when the template keeps its own look."""
    project = Path(project)
    choice = str(choice or "auto").strip().lower()
    if choice in ("template", "none", "off"):
        return None
    if choice == "auto":
        if template not in TEMPLATES:
            return None
        sig = choose(template, seed if seed is not None else project.name)
        if sig is None:
            return None
    else:
        sig = _checked(get(choice), template)
    _write(project, sig, template)
    record_pick(sig["id"], project.resolve())
    return {"id": sig["id"], "name": sig["name"], "polarity": sig["polarity"], "describe": describe(sig), "auto": choice == "auto"}


def _checked(sig: Dict[str, Any], template: str) -> Dict[str, Any]:
    if template not in TEMPLATES:
        raise ShowtimeError("the %s template keeps its own look" % (template or "project's"),
                            why="look signatures dress the page templates that draw from theme tokens: %s" % ", ".join(TEMPLATES))
    if template in sig.get("not", ()):
        raise ShowtimeError("look signature %s does not fit the %s template" % (sig["id"], template),
                            why="its display face is too wide for the template's type sizes",
                            hint="pick one of: %s" % ", ".join(s["id"] for s in compatible(template)))
    if sig["polarity"] not in TEMPLATES[template]:
        raise ShowtimeError("look signature %s is a %s look; the %s template is made for %s grounds" % (
            sig["id"], sig["polarity"], template, " and ".join(TEMPLATES[template])),
            hint="pick one of: %s" % ", ".join(s["id"] for s in compatible(template)))
    return sig


def _write(project: Path, sig: Optional[Dict[str, Any]], template: Optional[str] = None) -> None:
    page = project / "index.html"
    if not page.is_file():
        raise ShowtimeError("%s has no index.html" % project, hint="look signatures dress page projects (dom, launch, short, data)")
    write_block(page, sig, template)
    cfgp = project / "showtime.json"
    if cfgp.is_file():
        cfg = read_json(cfgp, {}) or {}
        if sig is None:
            cfg.pop("look", None)
        else:
            cfg["look"] = sig["id"]
            cfg["background"] = sig["palette"]["bg"]
        write_json(cfgp, cfg)


def set_project(project: Path, choice: str, seed: Any = None) -> Dict[str, Any]:
    """`showtime signature apply`: swap a project's signature (an id, auto/next for the next in rotation, or
    template to take it out). The template's own background comes back only from its showtime.json."""
    project = Path(project).expanduser().resolve()
    cfg = read_json(project / "showtime.json", {}) if (project / "showtime.json").is_file() else {}
    template = str((cfg or {}).get("template") or "")
    from ..brand.apply import is_applied
    if is_applied(project):
        raise ShowtimeError("%s wears its brand kit" % project.name, why="a brand kit's colours always win over a look signature",
                            hint="to drop the brand: remove the <style id=\"st-brand\"> block from index.html first")
    choice = str(choice or "").strip().lower()
    current = applied(project)
    if choice in ("template", "none", "off"):
        _write(project, None, template)
        tpl_cfg = _template_cfg(template)
        if tpl_cfg.get("background") and (project / "showtime.json").is_file():
            c2 = read_json(project / "showtime.json", {}) or {}
            c2["background"] = tpl_cfg["background"]
            write_json(project / "showtime.json", c2)
        return {"id": None, "previous": current, "describe": "the %s template's own look" % (template or "page")}
    if choice in ("auto", "next"):
        ranked = rank(template, seed if seed is not None else project.name, recent_picks(), _history_looks())
        ranked = [s for s in ranked if s["id"] != current] or ranked
        if not ranked:
            raise ShowtimeError("the %s template keeps its own look" % (template or "project's"),
                                hint="look signatures dress the page templates: %s" % ", ".join(TEMPLATES))
        sig = ranked[0]
    else:
        sig = _checked(get(choice), template)
    _write(project, sig, template)
    record_pick(sig["id"], project)
    return {"id": sig["id"], "name": sig["name"], "previous": current, "describe": describe(sig)}


def _history_looks() -> List[Dict[str, Any]]:
    from . import history
    return history.recent() if history.enabled()[0] else []


def _template_cfg(template: str) -> Dict[str, Any]:
    from ..common import skill_dir
    p = skill_dir() / "templates" / template / "showtime.json"
    return (read_json(p, {}) or {}) if template and p.is_file() else {}

