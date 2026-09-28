"""Theme for Manim scenes: colours from brand.json (or showtime's default dark look) plus fonts as files.

Stdlib only: the CLI resolves the theme once (installing a missing brand font as a file with the
font module), writes it into the run settings, and the scene kit reads it back. Outside a showtime
render (a plain `manim` call) the kit calls `resolve()` itself without installing anything.

Semantic hues: five hue angles picked to stay apart under the common colour-vision deficiencies
(blue, orange, teal, magenta, yellow-green). For each theme the lightness of every hue is moved until
it reads at 4.5:1 or more on the background, hues too close to the emphasis colour are dropped (the
emphasis colour must stay unique), and the brand's second accent goes first when it is text-safe.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# The default look when no brand kit is found: warm near-black, ember emphasis, grotesk display type.
DEFAULT = {
    "bg": "#0d0b0a", "surface": "#1c1715", "ink": "#fbf6f1", "muted": "#c9beb3",
    "accent": "#ff5a1f", "accent2": "#6f8cff",
}
DEFAULT_LIGHT = {
    "bg": "#f7f4ef", "surface": "#ffffff", "ink": "#16130f", "muted": "#5b534b",
    "accent": "#c2410c", "accent2": "#3552c9",
}
DEFAULT_FONTS = {"display": {"family": "Bricolage Grotesque", "weight": 800},
                 "body": {"family": "Inter", "weight": 400}}
HUE_ANGLES = (250.0, 62.0, 185.0, 335.0, 128.0)   # OKLCH hue angles: blue, orange, teal, magenta, yellow-green
HUE_CHROMA = 0.14
MIN_TEXT_CONTRAST = 4.5
MIN_EMPH_DISTANCE = 0.09                          # OKLab distance; below this a hue reads as the emphasis colour


# ------------------------------------------------------------------ colour maths (sRGB <-> OKLab)

def hex_rgb(h: str) -> Tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def rgb_hex(rgb: Tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c * 255)))) for c in rgb)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def to_oklab(h: str) -> Tuple[float, float, float]:
    r, g, b = (_lin(c) for c in hex_rgb(h))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklab_rgb(L: float, a: float, b: float) -> Tuple[float, float, float]:
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def oklch_hex(L: float, C: float, H: float) -> str:
    """OKLCH -> hex, reducing chroma until the colour fits in sRGB."""
    hr = math.radians(H)
    c = C
    for _ in range(40):
        rgb = _oklab_rgb(L, c * math.cos(hr), c * math.sin(hr))
        if all(-1e-4 <= v <= 1.0001 for v in rgb):
            return rgb_hex(tuple(_gam(min(1.0, max(0.0, v))) for v in rgb))  # type: ignore[arg-type]
        c *= 0.9
    return rgb_hex(tuple(_gam(min(1.0, max(0.0, v))) for v in _oklab_rgb(L, 0, 0)))  # type: ignore[arg-type]


def hue_angle(h: str) -> float:
    _, a, b = to_oklab(h)
    return math.degrees(math.atan2(b, a)) % 360


def distance(a: str, b: str) -> float:
    la, lb = to_oklab(a), to_oklab(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(la, lb)))


def luminance(h: str) -> float:
    r, g, b = (_lin(c) for c in hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """t=0 -> a, t=1 -> b (linear in sRGB, good enough for greys)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def is_dark(bg: str) -> bool:
    return luminance(bg) < 0.18


# ------------------------------------------------------------------ hue set

def hue_set(bg: str, emph: str, accent2: Optional[str] = None) -> List[str]:
    """Up to five semantic hues: text-safe on `bg`, distinct from `emph` (see the module doc)."""
    dark = is_dark(bg)
    out: List[str] = []
    taken: List[float] = []
    _, ea, eb = to_oklab(emph)
    if math.hypot(ea, eb) > 0.05:            # a coloured emphasis owns its hue
        taken.append(hue_angle(emph))
    if accent2 and contrast(accent2, bg) >= MIN_TEXT_CONTRAST and distance(accent2, emph) >= MIN_EMPH_DISTANCE:
        out.append(accent2.lower())
        taken.append(hue_angle(accent2))
    for h in HUE_ANGLES:
        if any(min(abs(h - t), 360 - abs(h - t)) < 35 for t in taken):
            continue   # the emphasis colour or the brand's second accent owns this hue
        L = 0.80 if dark else 0.50
        col = oklch_hex(L, HUE_CHROMA, h)
        for _ in range(30):
            if contrast(col, bg) >= MIN_TEXT_CONTRAST:
                break
            L = L + 0.015 if dark else L - 0.015
            L = min(0.97, max(0.2, L))
            col = oklch_hex(L, HUE_CHROMA, h)
        if contrast(col, bg) < MIN_TEXT_CONTRAST:
            continue
        if distance(col, emph) < MIN_EMPH_DISTANCE:
            continue
        if any(distance(col, o) < MIN_EMPH_DISTANCE for o in out):
            continue
        out.append(col)
    return out[:5]


# ------------------------------------------------------------------ theme

def _brand_palette(kit: Dict[str, Any]) -> Dict[str, str]:
    try:
        from st import brand as _brand
        return {k: v for k, v in _brand.palette(kit).items() if isinstance(v, str) and v.startswith("#")}
    except Exception:  # noqa: BLE001 - brand helpers are optional here
        return {k: v for k, v in (kit.get("palette") or {}).items() if isinstance(v, str) and v.startswith("#")}


def build(kit: Optional[Dict[str, Any]], light: bool = False,
          font_file: Optional[Callable[[str, int], Optional[str]]] = None) -> Dict[str, Any]:
    """The theme dict the scene kit reads.

    kit: a loaded brand.json (st.brand.load) or None. light: use the brand's light palette.
    font_file(family, weight) -> path of a .ttf (or None): how fonts are found as files.
    """
    notes: List[str] = []
    base = dict(DEFAULT_LIGHT if light else DEFAULT)
    source = "default"
    fonts = {k: dict(v) for k, v in DEFAULT_FONTS.items()}
    if kit:
        pal = _brand_palette(kit)
        if light and isinstance(kit.get("palette_light"), dict):
            pal = {k: v for k, v in kit["palette_light"].items() if isinstance(v, str) and v.startswith("#")}
        base.update({k: v for k, v in pal.items() if k in ("bg", "surface", "ink", "muted", "accent", "accent2")})
        source = "brand:%s" % kit.get("_file", "brand.json")
        for slot in ("display", "body"):
            f = (kit.get("fonts") or {}).get(slot)
            if isinstance(f, dict) and f.get("family"):
                fonts[slot] = {"family": f["family"], "weight": int(f.get("weight") or (800 if slot == "display" else 400))}
    bg, ink = base["bg"], base["ink"]
    emph = base["accent"]
    if contrast(emph, bg) < 3.0:
        notes.append("accent %s is only %.1f:1 on %s; the emphasis colour falls back to ink" % (emph, contrast(emph, bg), bg))
        emph = ink
    if contrast(ink, bg) < MIN_TEXT_CONTRAST:
        notes.append("ink %s is only %.1f:1 on %s (text needs 4.5:1)" % (ink, contrast(ink, bg), bg))
    muted = base.get("muted") or mix(ink, bg, 0.35)
    if contrast(muted, bg) < MIN_TEXT_CONTRAST:
        muted = mix(ink, bg, 0.25)
    theme = {
        "source": source,
        "dark": is_dark(bg),
        "bg": bg.lower(), "surface": base.get("surface", mix(bg, ink, 0.08)).lower(), "ink": ink.lower(),
        "muted": muted.lower(), "emph": emph.lower(),
        "accent2": (base.get("accent2") or "").lower() or None,
        "grid": mix(bg, muted, 0.45), "ghost": mix(bg, ink, 0.55),
        "hues": hue_set(bg, emph, base.get("accent2")),
        "fonts": {},
        "notes": notes,
    }
    if theme["accent2"] and contrast(theme["accent2"], bg) < MIN_TEXT_CONTRAST:
        notes.append("accent2 %s is not text-safe on %s (%.1f:1): used for fills only, never for text or tex"
                     % (theme["accent2"], bg, contrast(theme["accent2"], bg)))
    for slot, f in fonts.items():
        path = None
        if font_file is not None:
            try:
                path = font_file(f["family"], int(f["weight"]))
            except Exception as e:  # noqa: BLE001 - a missing font must not stop a render
                notes.append("font %s %s not available as a file (%s); Pango's default is used" % (f["family"], f["weight"], e))
        theme["fonts"][slot] = {"family": f["family"], "weight": int(f["weight"]), "file": str(path) if path else None}
    return theme


def installed_font_file(family: str, weight: int) -> Optional[str]:
    """A .ttf already installed under ~/.showtime/assets/fonts (never downloads)."""
    try:
        from st.assets import fonts as _fonts
        return str(_fonts.resolve(family, weight=weight, install_missing=False))
    except Exception:  # noqa: BLE001
        return None


def installing_font_file(family: str, weight: int) -> Optional[str]:
    """Like installed_font_file, but installs the family's files when missing (showtime assets font)."""
    from st.assets import fonts as _fonts
    return str(_fonts.resolve(family, weight=weight, install_missing=True))


def resolve(start: Optional[Path] = None, brand_file: Optional[Path] = None, light: bool = False,
            install_fonts: bool = False) -> Dict[str, Any]:
    """Theme for a project folder: brand.json from --brand, $SHOWTIME_BRAND or the folder (st.brand.find)."""
    kit = None
    try:
        from st import brand as _brand
        if brand_file is not None:
            import json
            p = Path(brand_file)
            if p.is_dir():
                p = p / "brand.json"
            kit = json.loads(p.read_text(encoding="utf-8"))
            kit["_file"] = str(p)
        else:
            kit = _brand.load(start)
    except Exception:  # noqa: BLE001 - the theme falls back to the default look
        if brand_file is not None:
            raise
        kit = None
    return build(kit, light=light, font_file=installing_font_file if install_fonts else installed_font_file)


def resolve_color(value: Any, theme: Dict[str, Any]) -> Optional[str]:
    """'hue1'..'hue5', a role ('emph', 'accent', 'ink', 'muted', ...) or a hex -> hex."""
    if not isinstance(value, str) or not value:
        return None
    v = value.strip()
    if v.startswith("#"):
        return v.lower()
    low = v.lower()
    if low.startswith("hue") and low[3:].isdigit():
        hues = theme.get("hues") or []
        i = int(low[3:]) - 1
        return hues[i % len(hues)] if hues else theme.get("ink")
    if low == "accent":
        low = "emph"
    return theme.get(low)
