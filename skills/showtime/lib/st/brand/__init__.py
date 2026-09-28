"""Brand kit: an optional brand.json (+ brand.md) next to a project or at a repo root.

A soft dependency: every workflow works without one. When present, workflows
read it with `load(start_dir)` and use its palette, fonts, logo, voice,
pronunciations and formats as defaults (the user's words still win).

    from st import brand
    kit = brand.load(project_dir)          # dict or None
    css = brand.css_vars(kit)              # ":root{--brand-bg:...}" for pages
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..common import ShowtimeError

PathLike = Union[str, "os.PathLike[str]"]

FILE_NAME = "brand.json"
ROLES = ("bg", "surface", "ink", "muted", "accent", "accent2", "border", "success", "warning", "danger")


def find(start: Optional[PathLike] = None, max_up: int = 4) -> Optional[Path]:
    """brand.json from $SHOWTIME_BRAND, `start`, start/brand/, or up to `max_up` parents (stops at a repo root)."""
    env = os.environ.get("SHOWTIME_BRAND")
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            p = p / FILE_NAME
        return p if p.is_file() else None
    d = Path(start or Path.cwd()).expanduser().resolve()
    if d.is_file():
        d = d.parent
    for i, cur in enumerate([d] + list(d.parents)):
        if i > max_up:
            break
        for cand in (cur / FILE_NAME, cur / "brand" / FILE_NAME):
            if cand.is_file():
                return cand
        if (cur / ".git").exists():
            break
    return None


def load(start: Optional[PathLike] = None) -> Optional[Dict[str, Any]]:
    """The brand kit as a dict (paths made absolute), or None when there is none."""
    p = find(start)
    if p is None:
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ShowtimeError("%s is not valid JSON: %s" % (p, e), hint="fix it, or re-draft with: showtime brand init")
    if not isinstance(data, dict):
        raise ShowtimeError("%s must contain a JSON object" % p)
    data["_file"] = str(p)
    logo = data.get("logo") or {}
    if isinstance(logo, dict):
        for k in ("path", "on_dark", "on_light", "mark"):
            v = logo.get(k)
            if v and not Path(v).is_absolute():
                logo[k] = str((p.parent / v).resolve())
    return data


def palette(kit: Dict[str, Any]) -> Dict[str, str]:
    """role -> hex from either the `palette` shortcut or the `colors` list."""
    out: Dict[str, str] = {}
    for c in kit.get("colors") or []:
        if isinstance(c, dict) and c.get("role") and c.get("hex") and c["role"] != "other" and c["role"] not in out:
            out[c["role"]] = c["hex"]
    for k, v in (kit.get("palette") or {}).items():
        if isinstance(v, str) and k != "other":
            out[k] = v
    return out


def css_vars(kit: Optional[Dict[str, Any]]) -> str:
    """CSS custom properties for a page: --brand-<role>, --brand-font-<slot>."""
    if not kit:
        return ""
    lines = [":root {"]
    for role, hexv in palette(kit).items():
        lines.append("  --brand-%s: %s;" % (re.sub(r"[^a-z0-9-]", "-", role.lower()), hexv))
    for slot, f in (kit.get("fonts") or {}).items():
        fam = f.get("family") if isinstance(f, dict) else f
        if fam:
            lines.append("  --brand-font-%s: '%s';" % (re.sub(r"[^a-z0-9-]", "-", slot.lower()), str(fam).replace("'", "")))
    lines.append("}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ colour helpers

def to_hex(value: str) -> Optional[str]:
    """#rgb/#rrggbb/#rrggbbaa, rgb()/rgba(), hsl()/hsla() or a bare 'H S% L%' triplet -> #rrggbb."""
    v = value.strip().lower().rstrip(";").strip()
    m = re.fullmatch(r"#([0-9a-f]{3,8})", v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            return "#" + "".join(c * 2 for c in h[:3])
        if len(h) in (6, 8):
            return "#" + h[:6]
        return None
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*[\d.%]+)?\s*\)", v)
    if m:
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(float(x))))) for x in m.groups())
    m = re.fullmatch(r"(?:hsla?\(\s*)?([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%(?:\s*[,/]\s*[\d.%]+)?\s*\)?", v)
    if m:
        h, s, l = float(m.group(1)) % 360, float(m.group(2)) / 100, float(m.group(3)) / 100
        return "#%02x%02x%02x" % _hsl_rgb(h, s, l)
    return None


def _hsl_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(int(round((v + m) * 255)) for v in (r, g, b))  # type: ignore[return-value]


def rgb(hexv: str) -> Tuple[int, int, int]:
    h = hexv.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hexv: str) -> float:
    def f(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(hexv)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def saturation(hexv: str) -> float:
    r, g, b = [c / 255.0 for c in rgb(hexv)]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    l = (mx + mn) / 2
    return (mx - mn) / (1 - abs(2 * l - 1)) if l not in (0, 1) else 0.0


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def font_status(family: str) -> Tuple[bool, str]:
    """(usable, where) for a brand font: installed with `showtime assets font`, or one of the families
    setup ships for the page themes (runtime/themes/fonts/<id>.css) and captions. Checked live, so a
    font installed after `brand init` shows as installed."""
    fid = re.sub(r"[^a-z0-9]+", "-", str(family or "").strip().lower()).strip("-")
    if not fid:
        return False, "no family"
    try:
        from ..common import paths
        if (paths()["fonts"] / fid / "font.json").is_file():
            return True, "installed: showtime assets font"
    except Exception:  # noqa: BLE001 - no showtime home yet
        pass
    from ..common import skill_dir
    if (skill_dir() / "runtime" / "themes" / "fonts" / (fid + ".css")).is_file():
        return True, "ships with setup: themes/fonts/%s.css" % fid
    return False, "not installed: showtime assets font \"%s\"" % family


def warnings_for(kit: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    pal = palette(kit)
    if pal.get("bg") and pal.get("ink") and contrast(pal["bg"], pal["ink"]) < 4.5:
        out.append("ink %s on bg %s is only %.1f:1 (text needs 4.5:1)" % (pal["ink"], pal["bg"], contrast(pal["bg"], pal["ink"])))
    if pal.get("bg") and pal.get("accent") and contrast(pal["bg"], pal["accent"]) < 3:
        out.append("accent %s on bg %s is %.1f:1: fine for shapes, too weak for text" % (
            pal["accent"], pal["bg"], contrast(pal["bg"], pal["accent"])))
    logo = (kit.get("logo") or {}).get("path") if isinstance(kit.get("logo"), dict) else None
    if not logo:
        out.append("no logo file recorded")
    elif not Path(logo).is_file():
        out.append("logo file not found: %s" % logo)
    if not kit.get("fonts"):
        out.append("no fonts recorded (the theme defaults will be used)")
    return out
