"""Draft a brand kit from what already exists: a repository or a captured website.

Everything here is a guess to be confirmed: brand.md lists what was inferred,
from where, and what to check. Nothing is fetched except (optionally) the
Fontsource catalog lookup that tells whether a font can be installed locally.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, read_json, skill_dir
from . import ROLES, luminance, palette, saturation, to_hex, warnings_for

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", ".next", ".nuxt", "vendor", "coverage", "__pycache__",
             ".venv", "venv", "showtime-out", "target", ".turbo", ".cache", "site-packages",
             # other people's colours and logos: demo projects and test fixtures are not the repo's brand
             "examples", "example", "fixtures", "__fixtures__"}
# folders whose brand.json is never the repo's own kit
NOT_OWN_KIT = SKIP_DIRS | {"tests", "test", "templates", "benchmarks"}
CSS_EXT = (".css", ".scss", ".sass", ".less", ".pcss", ".postcss")
TONE_WORDS = ("fast", "simple", "secure", "private", "open source", "open-source", "local", "lightweight", "powerful",
              "modern", "minimal", "friendly", "playful", "delightful", "reliable", "scalable", "beautiful", "elegant",
              "bold", "developer", "enterprise", "fun", "calm", "precise", "honest", "clean", "flexible", "intuitive",
              "blazing", "tiny", "robust", "accessible", "collaborative", "smart", "effortless", "trusted")
GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
                 "-apple-system", "blinkmacsystemfont", "segoe ui", "roboto", "helvetica", "helvetica neue", "arial",
                 "inherit", "initial", "var", "cursive", "fantasy", "emoji", "apple color emoji", "segoe ui emoji",
                 "noto color emoji", "menlo", "monaco", "consolas", "courier new", "sfmono-regular", "liberation mono",
                 "segoe ui symbol", "times new roman", "georgia", "ui-rounded"}


def _walk(root: Path, exts: Sequence[str], limit: int = 400, max_depth: int = 6) -> List[Path]:
    out: List[Path] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth]
        for fn in filenames:
            if fn.lower().endswith(tuple(exts)):
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size <= 1_500_000:
                        out.append(p)
                except OSError:
                    continue
                if len(out) >= limit:
                    return out
    return out


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ------------------------------------------------------------------ roles

_ROLE_HINTS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("bg", re.compile(r"(^|[-_])(bg|background|base|canvas|page|paper|backdrop|ground)($|[-_])")),
    ("surface", re.compile(r"(surface|card|panel|popover|elevated|raised)")),
    ("ink", re.compile(r"(^|[-_])(fg|foreground|text|ink|body|content)($|[-_])")),
    ("muted", re.compile(r"(muted|subtle|secondary-text|gray|grey|neutral|dim)")),
    ("accent", re.compile(r"(primary|brand|accent|main|key|highlight)")),
    ("accent2", re.compile(r"(secondary|tertiary|alt)")),
    ("border", re.compile(r"(border|stroke|outline|divider|ring|line)")),
    ("success", re.compile(r"(success|positive|green)")),
    ("warning", re.compile(r"(warning|caution|amber|yellow)")),
    ("danger", re.compile(r"(danger|error|destructive|negative|red)")),
]


def role_for(name: str) -> Optional[str]:
    n = name.lower().lstrip("-").replace("color-", "").replace("colour-", "")
    for role, rx in _ROLE_HINTS:
        if rx.search(n):
            return role
    return None


def assign_roles(colors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give each distinct colour a role from its name, then fill missing core roles by luminance/saturation."""
    taken: Dict[str, Dict[str, Any]] = {}
    # dark-theme blocks come second in most CSS; prefer the first (default) definition per role
    for c in colors:
        r = role_for(c.get("name", ""))
        if r and r not in taken:
            c["role"] = r
            taken[r] = c
    rest = [c for c in colors if not c.get("role")]
    uniq = {c["hex"]: c for c in colors}
    hexes = list(uniq)
    if hexes:
        named = {c["hex"] for c in taken.values()}   # a colour named for another role is never the ground
        if "bg" not in taken:
            cand = [h for h in hexes if saturation(h) < 0.25 and h not in named]
            if cand:
                bg = max(cand, key=lambda h: (abs(luminance(h) - 0.5), -hexes.index(h)))
                taken["bg"] = dict(uniq[bg], role="bg")
        if "ink" not in taken and "bg" in taken:
            bl = luminance(taken["bg"]["hex"])
            cand = [h for h in hexes if h != taken["bg"]["hex"] and saturation(h) < 0.3]
            if cand:
                ink = max(cand, key=lambda h: abs(luminance(h) - bl))
                taken["ink"] = dict(uniq[ink], role="ink")
        if "accent" not in taken:
            cand = [h for h in hexes if saturation(h) > 0.35 and 0.03 < luminance(h) < 0.85]
            if cand:
                acc = max(cand, key=lambda h: saturation(h))
                taken["accent"] = dict(uniq[acc], role="accent")
    out = [dict(v, role=k) for k, v in taken.items()]
    used = {c["hex"] for c in out}
    for c in rest:
        if c["hex"] not in used and len(out) < 16:
            out.append(dict(c, role="other"))
            used.add(c["hex"])
    order = {r: i for i, r in enumerate(ROLES)}
    out.sort(key=lambda c: order.get(c["role"], 99))
    return out


# ------------------------------------------------------------------ repo scanning

_VAR = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}{]+);")
_FAMILY = re.compile(r"font-family\s*:\s*([^;}{]+)[;}]", re.I)
_FACE = re.compile(r"@font-face\s*{[^}]*?font-family\s*:\s*['\"]?([^;'\"]+)", re.I | re.S)


def _first_family(decl: str) -> Optional[str]:
    for part in decl.split(","):
        f = part.strip().strip("'\"").strip()
        if not f or f.lower().startswith("var(") or f.lower() in GENERIC_FONTS:
            continue
        return f
    return None


def scan_css(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    colors: List[Dict[str, Any]] = []
    fonts: Dict[str, Dict[str, Any]] = {}
    seen = set()
    var_fonts: Dict[str, str] = {}
    for p in _walk(root, CSS_EXT + (".html", ".vue", ".svelte", ".astro")):
        txt = _read(p)
        rel = p.relative_to(root).as_posix()
        for m in _VAR.finditer(txt):
            name, val = m.group(1), m.group(2).strip()
            if re.search(r"font", name, re.I) and not to_hex(val):
                fam = _first_family(val)
                if fam:
                    var_fonts[name] = fam
                continue
            hx = to_hex(val)
            if hx and (name, hx) not in seen:
                seen.add((name, hx))
                line = txt.count("\n", 0, m.start()) + 1
                colors.append({"name": name, "hex": hx, "value": val[:40], "source": "%s:%d" % (rel, line)})
        for m in _FACE.finditer(txt):
            fam = m.group(1).strip()
            fonts.setdefault(fam, {"family": fam, "source": rel, "how": "@font-face"})
        for m in _FAMILY.finditer(txt):
            fam = _first_family(m.group(1))
            if fam:
                fonts.setdefault(fam, {"family": fam, "source": rel, "how": "font-family"})
    for name, fam in var_fonts.items():
        slot = "mono" if re.search(r"mono|code", name, re.I) else "display" if re.search(r"display|head|title", name, re.I) else "body"
        fonts.setdefault(fam, {"family": fam, "source": name, "how": "css variable", "slot": slot})
    return colors, fonts


_TW_COLOR = re.compile(r"['\"]?([A-Za-z][\w-]*)['\"]?\s*:\s*['\"](#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\))['\"]")
_TW_NEST = re.compile(r"['\"]?([A-Za-z][\w-]*)['\"]?\s*:\s*{")
_TW_FONT = re.compile(r"['\"]?(sans|serif|mono|display|heading|body|title)['\"]?\s*:\s*\[\s*['\"]([^'\"]+)['\"]")


def scan_tailwind(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    colors: List[Dict[str, Any]] = []
    fonts: Dict[str, Dict[str, Any]] = {}
    for name in ("tailwind.config.js", "tailwind.config.cjs", "tailwind.config.mjs", "tailwind.config.ts"):
        for p in [root / name] + [q for q in root.glob("*/" + name)][:3]:
            if not p.is_file():
                continue
            txt = _read(p)
            rel = p.relative_to(root).as_posix()
            # track the nearest enclosing key for nested palettes like primary: { DEFAULT: '#..', 500: '#..' }
            stack: List[Tuple[int, str]] = []
            depth = 0
            for m in re.finditer(r"[{}]|" + _TW_COLOR.pattern + "|" + _TW_NEST.pattern, txt):
                tok = m.group(0)
                if tok == "{":
                    depth += 1
                    continue
                if tok == "}":
                    depth -= 1
                    while stack and stack[-1][0] > depth:
                        stack.pop()
                    continue
                if m.group(1) and m.group(2):
                    parent = stack[-1][1] if stack else ""
                    key = m.group(1)
                    nm = parent if key.upper() == "DEFAULT" and parent else ("%s-%s" % (parent, key) if parent else key)
                    hx = to_hex(m.group(2))
                    if hx:
                        colors.append({"name": nm, "hex": hx, "value": m.group(2)[:40],
                                       "source": "%s:%d" % (rel, txt.count("\n", 0, m.start()) + 1)})
                elif m.group(3):
                    depth += 1
                    stack.append((depth, m.group(3)))
            for m in _TW_FONT.finditer(txt):
                fam = m.group(2).strip()
                if fam.lower() not in GENERIC_FONTS and not fam.startswith("var("):
                    slot = {"sans": "body", "body": "body", "serif": "body", "mono": "mono"}.get(m.group(1), "display")
                    fonts.setdefault(fam, {"family": fam, "source": rel, "how": "tailwind fontFamily", "slot": slot})
    # pick the 500/DEFAULT shade of numbered scales and drop the rest (they are ramps, not roles)
    keep: List[Dict[str, Any]] = []
    for c in colors:
        m = re.match(r"^(.*)-(\d{2,3})$", c["name"])
        if m and m.group(2) not in ("500", "600"):
            continue
        keep.append(dict(c, name=m.group(1) if m else c["name"]))
    return keep, fonts


_NEXT_FONT = re.compile(r"import\s*{([^}]+)}\s*from\s*['\"]next/font/google['\"]")


def scan_js_fonts(root: Path) -> Dict[str, Dict[str, Any]]:
    fonts: Dict[str, Dict[str, Any]] = {}
    for p in _walk(root, (".js", ".jsx", ".ts", ".tsx", ".mjs"), limit=300, max_depth=4):
        txt = _read(p)
        for m in _NEXT_FONT.finditer(txt):
            for name in m.group(1).split(","):
                fam = name.split(" as ")[0].strip().replace("_", " ")
                if fam:
                    fonts.setdefault(fam, {"family": fam, "source": p.relative_to(root).as_posix(), "how": "next/font"})
    return fonts


def find_logos(root: Path) -> List[str]:
    cands: List[Tuple[int, str]] = []
    for p in _walk(root, (".svg", ".png", ".webp"), limit=2000, max_depth=5):
        n = p.name.lower()
        rel = p.relative_to(root).as_posix()
        score = 0
        if "logo" in n:
            score += 10
        elif n in ("icon.svg", "favicon.svg", "mark.svg", "logomark.svg", "wordmark.svg", "brand.svg"):
            score += 6
        elif "brand" in rel.lower() and n.endswith(".svg"):
            score += 4
        else:
            continue
        if n.endswith(".svg"):
            score += 3
        if re.search(r"(^|/)(public|assets|static|docs|\.github|images|img|media|brand)(/|$)", rel):
            score += 2
        if re.search(r"(dark|white|light|inverse|mono)", n):
            score -= 1
        cands.append((score, rel))
    cands.sort(key=lambda x: (-x[0], len(x[1])))
    return [c[1] for c in cands[:8]]


def tone_words(text: str, n: int = 5) -> List[str]:
    t = text.lower()
    counts = []
    for w in TONE_WORDS:
        k = len(re.findall(r"(?<![a-z])%s(?![a-z])" % re.escape(w), t))
        if k:
            counts.append((k, w))
    counts.sort(key=lambda x: (-x[0], TONE_WORDS.index(x[1])))
    words = []
    for _, w in counts:
        w = "open source" if w == "open-source" else w
        if w not in words:
            words.append(w)
    return words[:n]


def _readme(root: Path) -> Tuple[Optional[str], Optional[str], str]:
    for name in ("README.md", "readme.md", "README.markdown", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            txt = _read(p)
            title = None
            m = re.search(r"^#\s+(.+)$", txt, re.M)
            if m:
                title = re.sub(r"[`*_\[\]<>]|!\[.*?\]\(.*?\)|\(.*?\)", "", m.group(1)).strip() or None
            tagline = None
            for para in re.split(r"\n\s*\n", txt):
                s = para.strip()
                if not s or s.startswith(("#", "!", "[!", "<", "```", "|", "-", "*", ">")) or len(s) < 25:
                    continue
                tagline = re.sub(r"\s+", " ", re.sub(r"[`*_]|\[([^\]]+)\]\([^)]*\)", r"\1", s))[:200]
                break
            return title, tagline, txt[:20000]
    return None, None, ""


def pronunciation_candidates(name: str, text: str) -> List[str]:
    """Words a TTS engine is likely to misread: the product name, CamelCase, ALLCAPS, words with digits."""
    cands: List[str] = []
    for w in [name] + re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", text[:8000]):
        if not w or len(w) < 2:
            continue
        odd = (w == name) or re.search(r"[a-z][A-Z]", w) or (w.isupper() and 2 <= len(w) <= 6) or re.search(r"\d", w)
        if odd and w not in cands and w.lower() not in ("i", "a", "ok", "id", "ui", "os", "js", "md", "http", "https", "readme"):
            cands.append(w)
        if len(cands) >= 10:
            break
    return cands


def resolve_fonts(fonts: Dict[str, Dict[str, Any]], lookup: bool = True) -> Dict[str, Dict[str, Any]]:
    """Slots display/body/mono -> {family, source, fontsource id, license, installed path}."""
    slots: Dict[str, Dict[str, Any]] = {}
    items = list(fonts.values())
    for f in items:
        slot = f.get("slot") or ("mono" if re.search(r"mono|code", f["family"], re.I) else None)
        if slot and slot not in slots:
            slots[slot] = f
    for f in items:
        if f in slots.values():
            continue
        for slot in ("body", "display"):
            if slot not in slots:
                slots[slot] = f
                break
    if "display" not in slots and "body" in slots:
        slots["display"] = dict(slots["body"])
    out: Dict[str, Dict[str, Any]] = {}
    for slot, f in slots.items():
        fam = re.sub(r"\s+Variable$", "", f["family"]).strip()
        rec: Dict[str, Any] = {"family": fam, "source": f.get("source"), "how": f.get("how")}
        if lookup and os.environ.get("SHOWTIME_OFFLINE") != "1":
            try:
                from ..assets import fonts as fontmod
                meta = fontmod.find(fam)
                rec["fontsource"] = meta.get("id")
                rec["license"] = meta.get("license")
                from . import font_status
                rec["installed"] = font_status(fam)[0]
                if not rec["installed"]:
                    rec["install"] = "showtime assets font \"%s\"" % meta.get("family", fam)
            except Exception as e:  # noqa: BLE001 - not on Fontsource, or offline
                rec["fontsource"] = None
                rec["note"] = "not found on Fontsource (%s): use a local OFL file or pick a theme font" % str(e).split("\n")[0][:80]
        out[slot] = rec
    return out


def existing_kit(root: Path, max_depth: int = 3) -> Optional[Path]:
    """The repo's own brand.json (shallowest first), outside examples/, tests/, fixtures, node_modules."""
    root = root.resolve()
    found: List[Tuple[int, str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        depth = len(rel.parts)
        dirnames[:] = [d for d in dirnames if d not in NOT_OWN_KIT and not d.startswith(".") and depth < max_depth]
        if "brand.json" in filenames:
            found.append((depth, str(rel), Path(dirpath) / "brand.json"))
    for _d, _r, p in sorted(found):
        data = read_json(p, None)
        if isinstance(data, dict) and (data.get("colors") or data.get("palette") or data.get("fonts")):
            return p
    return None


def adopt_kit(path: Path) -> Dict[str, Any]:
    """An existing brand.json as the draft (its paths made absolute, so they can be re-based)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent

    def absolute(v: Any) -> Any:
        # every relative path in the kit that points at a file beside it (logo, sounds, stings)
        if isinstance(v, dict):
            return {k: absolute(x) for k, x in v.items()}
        if isinstance(v, list):
            return [absolute(x) for x in v]
        if isinstance(v, str) and v and "://" not in v and not v.startswith("#") and len(v) < 400:
            try:
                q = Path(v)
                if not q.is_absolute() and (base / q).exists():
                    return str((base / q).resolve())
            except (OSError, ValueError):
                pass
        return v
    data = absolute(data)
    data["adopted_from"] = str(path)
    md = next((m for m in (base / "BRAND.md", base / "brand.md") if m.is_file()), None)
    if md is not None:
        data.setdefault("guide", str(md))
    return data


def from_repo(root: Path, lookup_fonts: bool = True) -> Dict[str, Any]:
    """Draft a kit from a repository. The repo's own brand.json (not one under examples/, tests/,
    fixtures or node_modules) wins and is adopted as it is; otherwise its CSS, Tailwind config,
    fonts, logos and README are scanned (examples/ and fixtures skipped)."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ShowtimeError("not a folder: %s" % root)
    own = existing_kit(root)
    if own is not None:
        return adopt_kit(own)
    pkg = read_json(root / "package.json", None) if (root / "package.json").is_file() else None
    pkg = pkg if isinstance(pkg, dict) else {}
    title, tagline, readme = _readme(root)
    name = pkg.get("name") or title or root.name
    if isinstance(name, str) and name.startswith("@") and "/" in name:
        name = name.split("/", 1)[1]
    py = _read(root / "pyproject.toml") if (root / "pyproject.toml").is_file() else ""
    if py and not pkg:
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', py, re.M)
        if m and not title:
            name = m.group(1)
        m = re.search(r'^\s*description\s*=\s*"([^"]+)"', py, re.M)
        if m and not tagline:
            tagline = m.group(1)
    colors, fonts = scan_css(root)
    tw_colors, tw_fonts = scan_tailwind(root)
    fonts = {**tw_fonts, **{k: v for k, v in fonts.items() if k not in tw_fonts}}
    for k, v in scan_js_fonts(root).items():
        fonts.setdefault(k, v)
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    for dep in deps:
        m = re.match(r"^@fontsource(?:-variable)?/(.+)$", dep)
        if m:
            fam = " ".join(w.capitalize() for w in m.group(1).split("-"))
            fonts.setdefault(fam, {"family": fam, "source": "package.json", "how": "fontsource dependency"})
    all_colors = colors + [c for c in tw_colors if (c["name"], c["hex"]) not in {(x["name"], x["hex"]) for x in colors}]
    logos = find_logos(root)
    text = " ".join(filter(None, [pkg.get("description"), tagline, readme]))
    kit = _assemble(name=str(name), tagline=pkg.get("description") or tagline, url=pkg.get("homepage"),
                    colors=assign_roles(all_colors), fonts=resolve_fonts(fonts, lookup_fonts),
                    logo=logos[0] if logos else None, logos=logos, tone=tone_words(text),
                    pron=pronunciation_candidates(str(name), text),
                    source={"kind": "repo", "path": str(root)},
                    other={"keywords": pkg.get("keywords") or [], "repository": _repo_url(pkg), "license": pkg.get("license")},
                    base=root)
    return kit


def _repo_url(pkg: Dict[str, Any]) -> Optional[str]:
    r = pkg.get("repository")
    if isinstance(r, dict):
        return r.get("url")
    return r if isinstance(r, str) else None


# ------------------------------------------------------------------ site capture

def find_capture(url: str, roots: Sequence[Path]) -> Optional[Path]:
    """An existing `showtime site capture` output (site.json) for this URL, or for a local folder
    (a `site capture --serve <dir>` records the folder in site.json "served"; its port is random)."""
    from urllib.parse import urlparse
    local: Optional[str] = None
    lp = Path(url).expanduser()
    if "://" not in url and lp.exists():
        local = os.path.normcase(str(lp.resolve()))
    host = "" if local else re.sub(r"^www\.", "", (urlparse(url if "://" in url else "https://" + url).hostname or "").lower())
    best: Optional[Tuple[float, Path]] = None
    for r in roots:
        if not r.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(r):
            depth = len(Path(dirpath).relative_to(r).parts)
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and depth < 4]
            if "site.json" in filenames:
                p = Path(dirpath) / "site.json"
                d = read_json(p, None)
                if not isinstance(d, dict) or d.get("blocked"):
                    continue
                u = str(d.get("finalUrl") or d.get("url") or "")
                h = re.sub(r"^www\.", "", (urlparse(u).hostname or "").lower())
                served = d.get("served")
                hit = (host and h == host and not served) if not local else \
                    (bool(served) and os.path.normcase(str(Path(str(served)).expanduser().resolve())) == local)
                if hit:
                    mt = p.stat().st_mtime
                    if best is None or mt > best[0]:
                        best = (mt, p)
    return best[1] if best else None


def capture(url: str, out_dir: Path) -> Path:
    """Run `showtime site capture <url> <out_dir>` and return its site.json."""
    launcher = skill_dir() / "lib" / "st" / "launcher.py"
    cp = subprocess.run([sys.executable, str(launcher), "site", "capture", url, str(out_dir), "--aspect", "16:9"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=600)
    sj = out_dir / "site.json"
    if cp.returncode == 3:
        raise ShowtimeError("the site blocked automated capture (see %s)" % (out_dir / "BLOCKED.md"),
                            hint="draft from the repo instead (--from <dir>), or give screenshots and colours by hand")
    if cp.returncode != 0 or not sj.is_file():
        raise ShowtimeError("site capture failed: %s" % (cp.stderr or cp.stdout).strip()[-400:])
    return sj


def from_site(site_json: Path, lookup_fonts: bool = True) -> Dict[str, Any]:
    d = read_json(site_json, None)
    if not isinstance(d, dict):
        raise ShowtimeError("%s is not a site capture report" % site_json)
    base = site_json.parent
    meta = d.get("meta") or {}
    roles = ((d.get("colors") or {}).get("roles") or {})
    mapping = {"background": "bg", "text": "ink", "primary": "accent", "accent": "accent2", "surface": "surface",
               "onPrimary": "on_accent", "themeColor": "other"}
    colors: List[Dict[str, Any]] = []
    used = set()
    for k, role in mapping.items():
        hx = to_hex(str(roles.get(k) or "")) if roles.get(k) else None
        if hx and (role, hx) not in used and not (role == "other" and hx in {c["hex"] for c in colors}):
            used.add((role, hx))
            colors.append({"role": role, "hex": hx, "name": k, "source": "site.json colors.roles.%s" % k})
    for p in ((d.get("colors") or {}).get("palette") or [])[:10]:
        hx = to_hex(str(p.get("hex") or ""))
        if hx and hx not in {c["hex"] for c in colors}:
            colors.append({"role": "other", "hex": hx, "name": p.get("role"), "source": "site.json palette"})
    fonts: Dict[str, Dict[str, Any]] = {}
    fr = (d.get("fonts") or {}).get("roles") or {}
    for key, slot in (("h1", "display"), ("body", "body"), ("code", "mono"), ("h2", "display")):
        v = fr.get(key)
        fam = _first_family(v.get("family", "")) if isinstance(v, dict) else None
        if fam and slot not in {f.get("slot") for f in fonts.values()}:
            fonts[fam + ":" + slot] = {"family": fam, "source": "site.json fonts.roles.%s" % key, "how": "computed style", "slot": slot}
    logos = []
    for a in d.get("assets") or []:
        if isinstance(a, dict) and a.get("kind") == "logo" and a.get("file"):
            logos.append(str((base / a["file"]).resolve()))
    logos.sort(key=lambda p: (not p.endswith(".svg"), len(p)))
    text = " ".join(filter(None, [meta.get("description"), meta.get("title"), str(d.get("text") or "")[:8000]]))
    name = meta.get("ogSiteName") or meta.get("siteName") or (meta.get("title") or "").split("|")[0].split(" - ")[0].strip() or "brand"
    kit = _assemble(name=name, tagline=meta.get("description"), url=d.get("finalUrl") or d.get("url"),
                    colors=colors, fonts=resolve_fonts({k: v for k, v in fonts.items()}, lookup_fonts),
                    logo=logos[0] if logos else None, logos=logos, tone=tone_words(text),
                    pron=pronunciation_candidates(name, text), source={"kind": "site", "path": str(site_json)},
                    other={"og_image": meta.get("ogImage") or meta.get("og:image")}, base=None)
    return kit


# ------------------------------------------------------------------ assembly

def _assemble(*, name: str, tagline: Optional[str], url: Optional[str], colors: List[Dict[str, Any]],
              fonts: Dict[str, Dict[str, Any]], logo: Optional[str], logos: List[str], tone: List[str],
              pron: List[str], source: Dict[str, Any], other: Dict[str, Any], base: Optional[Path]) -> Dict[str, Any]:
    def absp(p: Optional[str]) -> Optional[str]:
        if not p:
            return None
        return str((base / p).resolve()) if base and not Path(p).is_absolute() else p
    kit: Dict[str, Any] = {
        "schema": 1, "status": "draft", "drafted": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": name, "tagline": tagline, "url": url, "source": source,
        "logo": {"path": absp(logo), "candidates": [absp(x) for x in logos], "on_dark": None, "on_light": None},
        "colors": colors,
        "palette": {},
        "fonts": fonts,
        "voice": {"id": "af_heart", "speed": 1.0, "language": "en-us",
                  "note": "default suggestion; audition with `showtime voice list` and `showtime voice say`"},
        "pronunciations": {},
        "pronunciation_candidates": pron,
        "formats": ["16:9", "9:16"],
        "tone": tone,
        "other": {k: v for k, v in other.items() if v},
    }
    kit["palette"] = {c["role"]: c["hex"] for c in colors if c.get("role") and c["role"] != "other"}
    return kit


def relativize(kit: Dict[str, Any], dest_dir: Path) -> Dict[str, Any]:
    """Store file paths relative to brand.json where possible (portable across machines)."""
    def rel(p: Optional[str]) -> Optional[str]:
        if not p:
            return p
        try:
            return Path(os.path.relpath(p, dest_dir)).as_posix()
        except ValueError:  # another drive on Windows
            return p
    out = json.loads(json.dumps(kit))
    lg = out.get("logo") or {}
    for k in ("path", "on_dark", "on_light"):
        lg[k] = rel(lg.get(k))
    lg["candidates"] = [rel(x) for x in lg.get("candidates") or []]
    if isinstance(out.get("source"), dict) and out["source"].get("path"):
        out["source"]["path"] = rel(out["source"]["path"])

    def walk(v: Any) -> Any:
        # any other absolute path to an existing file (an adopted kit's sounds, stings, guide)
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and len(v) < 400 and Path(v).is_absolute() and Path(v).exists():
            return rel(v)
        return v
    return walk(out)


def brand_md(kit: Dict[str, Any], json_name: str = "brand.json") -> str:
    pal = palette(kit)
    L = ["# Brand kit: %s" % kit.get("name"), "",
         "Draft made by `showtime brand init` from %s `%s` on %s. **Everything here is inferred**: state it as "
         "assumptions (quick mode) or show it on the look board (studio), and edit %s to correct it (this file is "
         "the human summary)." % (
             (kit.get("source") or {}).get("kind"), (kit.get("source") or {}).get("path"), (kit.get("drafted") or "")[:10], json_name), ""]
    if kit.get("tagline"):
        L += ["Tagline: %s" % kit["tagline"], ""]
    L += ["## Logo", ""]
    lg = kit.get("logo") or {}
    L.append("- file: `%s`" % lg.get("path") if lg.get("path") else "- none found: add `logo.path` (SVG preferred)")
    for c in (lg.get("candidates") or [])[1:5]:
        L.append("- other candidate: `%s`" % c)
    L += ["", "## Colours", "", "| role | hex | from |", "|---|---|---|"]
    for c in kit.get("colors") or []:
        L.append("| %s | `%s` | %s %s |" % (c.get("role"), c.get("hex"), c.get("name") or "", c.get("source") or ""))
    L += ["", "## Fonts", ""]
    for slot, f in (kit.get("fonts") or {}).items():
        st = "installed" if f.get("installed") else ("install: `%s`" % f["install"] if f.get("install") else f.get("note") or "")
        L.append("- %s: **%s** (%s; %s) %s" % (slot, f.get("family"), f.get("how"), f.get("license") or "license unknown", st))
    if not kit.get("fonts"):
        L.append("- none found: the theme fonts will be used")
    v = kit.get("voice") or {}
    L += ["", "## Voice", "", "- `%s` at speed %s (%s)" % (v.get("id"), v.get("speed"), v.get("note", ""))]
    L += ["", "## Pronunciations", ""]
    if kit.get("pronunciations"):
        for w, say in kit["pronunciations"].items():
            L.append("- %s -> %s" % (w, say))
    L.append("Check how the voice reads these (`showtime voice say \"...\"`), then add entries such as "
             "`\"%s\": \"<respelling or /IPA/>\"`: %s" % (
                 (kit.get("pronunciation_candidates") or ["Name"])[0], ", ".join(kit.get("pronunciation_candidates") or []) or "(none)"))
    L += ["", "## Formats", "", ", ".join(kit.get("formats") or []), "", "## Tone words", "",
          ", ".join(kit.get("tone") or []) or "(none detected: add 3-5 words)", ""]
    warns = warnings_for(kit)
    if warns:
        L += ["## Check", ""] + ["- " + w for w in warns] + [""]
    L += ["## How showtime uses this", "",
          "Workflows look for brand.json in the project, then its parents (up to the repo root), or `$SHOWTIME_BRAND`. "
          "It sets default colours, fonts, logo, voice, pronunciations and formats. The user's request always wins. "
          "`showtime brand css` prints the palette as CSS variables for a page.", ""]
    _ = pal
    return "\n".join(L)
