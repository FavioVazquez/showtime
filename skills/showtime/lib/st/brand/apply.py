"""Apply a brand kit to a page project: the theme tokens, the fonts, and the product's own words where the
template still has SLOT text.

    from st.brand import apply
    res = apply.apply_project(project_dir, kit)     # writes <style id="st-brand"> into index.html

The block is idempotent (re-applying replaces it) and sits after the template's own style, so it only
sets tokens: `--bg --fg --muted --accent --accent-ink --surface`, the product window (`--win-*`, in the
product's code-block colours when the site shows commands that way), the world light (`--key-light`,
`--rim-*`, `--vignette`) and `--font-display` / `--font-mono`. Colours are adjusted only for legibility
(text >= 4.5:1, the ink >= 7:1 where it can be), and every adjustment is reported.
"""
from __future__ import annotations

import html
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import read_json, write_json
from . import contrast, font_status, luminance, palette, rgb, to_hex

BLOCK_RX = re.compile(r"\n?<!-- brand kit: .*? -->\n(?:<link [^>]*data-st-brand[^>]*>\n)*<style id=\"st-brand\">.*?</style>\n?", re.S)


def _hex(c: Tuple[float, float, float]) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def mix(a: str, b: str, t: float) -> str:
    """a mixed toward b by t (0 = a, 1 = b), in sRGB."""
    ra, rb = rgb(a), rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def ensure(color: str, ground: str, ratio: float, toward: Optional[str] = None) -> Tuple[str, bool]:
    """The colour moved toward black or white (or `toward`) just enough to reach `ratio` on `ground`."""
    if contrast(color, ground) >= ratio:
        return color, False
    target = toward or ("#000000" if luminance(ground) > 0.4 else "#ffffff")
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if contrast(mix(color, target, mid), ground) >= ratio:
            hi = mid
        else:
            lo = mid
    out = mix(color, target, hi)
    if contrast(out, ground) < ratio and toward:
        return ensure(out, ground, ratio)
    return out, True


TEXT_RATIO = 4.8   # 4.5:1 plus a margin: anti-aliased glyphs measure a little lower than their colour
MARK = 0.16        # the template marks a result line with the accent at 16 % over the window


def ensure_marked(color: str, ground: str, ratio: float = TEXT_RATIO) -> str:
    """An accent that reads on `ground` and on its own mark (the ground with MARK of the accent over it)."""
    target = "#000000" if luminance(ground) > 0.4 else "#ffffff"
    ok = lambda c: contrast(c, ground) >= ratio and contrast(c, mix(ground, c, MARK)) >= ratio  # noqa: E731
    if ok(color):
        return color
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if ok(mix(color, target, mid)):
            hi = mid
        else:
            lo = mid
    return mix(color, target, hi)


def _rgba(hexv: str, a: float) -> str:
    r, g, b = rgb(hexv)
    return "rgb(%d %d %d / %s)" % (r, g, b, ("%.2f" % a).rstrip("0").rstrip("."))


def tokens(kit: Dict[str, Any]) -> Tuple[Dict[str, str], List[str]]:
    """CSS custom properties for the launch template (and any page on the theme tokens) from a kit."""
    pal = palette(kit)
    notes: List[str] = []
    bg, ink = pal.get("bg"), pal.get("ink")
    if not bg or not ink:
        return {}, ["the kit has no bg/ink pair: the template's colours stay"]
    light = luminance(bg) > 0.45
    fg, moved = ensure(ink, bg, 7.0)
    if moved:
        notes.append("ink %s is %.1f:1 on %s; the film uses %s (7:1)" % (ink, contrast(ink, bg), bg, fg))
    muted = pal.get("muted") or mix(fg, bg, 0.38)
    # small muted labels also sit in the window's shadow and the key light: judge them on a slightly deeper ground
    muted2, moved = ensure(muted, mix(bg, fg, 0.15) if light else bg, TEXT_RATIO, toward=fg)
    if moved:
        notes.append("muted %s deepened to %s so small labels keep 4.8:1 where shadows and the key light fall (%.1f:1 on "
                     "the bare ground)" % (muted, muted2, contrast(muted, bg)))
    acc0 = pal.get("accent") or pal.get("accent2")
    t: Dict[str, str] = {"--bg": bg, "--fg": fg, "--muted": muted2}
    if acc0:
        acc, moved = ensure(acc0, bg, TEXT_RATIO)
        if moved:
            notes.append("accent %s is %.1f:1 on the ground; the words in the accent use %s (same hue, 4.8:1)" % (
                acc0, contrast(acc0, bg), acc))
        t["--accent"] = acc
        t["--accent-ink"] = "#ffffff" if contrast("#ffffff", acc) >= contrast("#000000", acc) else "#000000"
    else:
        acc = None
        notes.append("the kit has no accent: the template's accent stays")
    code = kit.get("code") if isinstance(kit.get("code"), dict) else {}
    cbg, cfg_ = to_hex(str(code.get("bg") or "")) if code.get("bg") else None, to_hex(str(code.get("fg") or "")) if code.get("fg") else None
    surface = pal.get("surface")
    if light:
        # a light product shows commands in a dark block (its code style, else its ink): the window is that block
        win = cbg if cbg and luminance(cbg) < 0.25 else (surface if surface and luminance(surface) < 0.2 else fg)
        wfg = cfg_ if cfg_ and contrast(cfg_, win) >= TEXT_RATIO else bg
    else:
        win = cbg if cbg and cbg != bg else (surface if surface and surface != bg else mix(bg, fg, 0.06))
        wfg = cfg_ if cfg_ and contrast(cfg_, win) >= TEXT_RATIO else fg
    wfg, _ = ensure(wfg, win, 7.0)
    wmuted, _ = ensure(mix(wfg, win, 0.36), win, TEXT_RATIO, toward=wfg)
    wacc = ensure_marked(acc0, win) if acc0 else None
    if acc0 and wacc != acc0:
        notes.append("in the product window the accent is %s (%s on %s is only %.1f:1)" % (wacc, acc0, win, contrast(acc0, win)))
    t.update({"--surface": surface or (mix(bg, fg, 0.04) if light else mix(bg, fg, 0.06)),
              "--win-bg": win, "--win-fg": wfg, "--win-muted": wmuted, "--win-line": _rgba(wfg, 0.10),
              "--chip-bg": win, "--chip-fg": wfg})
    if wacc:
        t["--win-accent"] = wacc
        t["--chip-accent"] = wacc
    if light:
        # one lit paper ground: a faint key light in the brand's accent drifting across it (white would vanish on
        # paper, and the drift is what keeps a settled scene alive), no second rim, a faint ink vignette, soft shadows
        t.update({"--line": _rgba(fg, 0.10), "--key-light": _rgba(acc0 or fg, 0.14),
                  "--rim-a": _rgba(acc0 or fg, 0.06), "--rim-b": "transparent", "--vignette": _rgba(fg, 0.10),
                  "--win-shadow": "0 3cqh 8cqh %s, 0 0.5cqh 1.4cqh %s" % (_rgba(fg, 0.22), _rgba(fg, 0.10)),
                  "--win-shadow-tall": "0 1.2cqh 3cqh %s" % _rgba(fg, 0.18), "color-scheme": "light"})
    else:
        t.update({"--line": _rgba(fg, 0.09), "color-scheme": "dark"})
    return t, notes


def _font_links(kit: Dict[str, Any], project: Path) -> Tuple[List[str], Dict[str, str], List[str]]:
    """<link> lines and --font-* values for the kit's fonts that are available here (installed or shipped)."""
    links: List[str] = []
    vals: Dict[str, str] = {}
    notes: List[str] = []
    fonts = kit.get("fonts") or {}
    want = {"--font-display": fonts.get("display") or fonts.get("body"), "--font-mono": fonts.get("mono")}
    for var, f in want.items():
        fam = (f.get("family") if isinstance(f, dict) else f) or ""
        if not fam:
            continue
        ok, where = font_status(str(fam))
        fid = re.sub(r"[^a-z0-9]+", "-", str(fam).lower()).strip("-")
        fallback = "'Geist Mono', monospace" if var == "--font-mono" else "'Geist', sans-serif"
        if not ok:
            notes.append("font %s is not installed here (%s): the template's font stays" % (fam, where))
            continue
        if where.startswith("installed"):
            from ..common import paths
            src = paths()["fonts"] / fid
            dst = project / "fonts" / fid
            if not dst.exists():
                shutil.copytree(str(src), str(dst))
            href = "fonts/%s/font.css" % fid
        else:
            href = "/_st/themes/fonts/%s.css" % fid
        line = '<link rel="stylesheet" href="%s" data-st-brand>' % href
        if line not in links:
            links.append(line)
        vals[var] = "'%s', %s" % (str(fam).replace("'", ""), fallback)
    return links, vals, notes


def wordmark_html(kit: Dict[str, Any]) -> Optional[str]:
    wm = kit.get("wordmark")
    if not isinstance(wm, dict) or not wm.get("runs"):
        return None
    out = []
    for r in wm["runs"]:
        t = html.escape(str(r.get("text") or ""))
        out.append('<span class="wm-accent">%s</span>' % t if r.get("role") in ("accent", "accent2") else t)
    return "".join(out)


def _fill_slots(page: str, kit: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Replace the launch template's end-card and label SLOTs with the kit's verbatim copy."""
    filled: List[str] = []
    copy = kit.get("copy") or {}
    name = str(kit.get("name") or "")
    rel = copy.get("release") or {}
    wm = wordmark_html(kit) or html.escape(name)

    def sub(rx: str, repl: str, what: str) -> None:
        nonlocal page
        new, n = re.subn(rx, lambda m: m.group(1) + repl + m.group(2), page, count=1)
        if n:
            page = new
            filled.append(what)
    if wm:
        sub(r'(<h2 class="name"[^>]*>)SLOT: name(<em>)', wm, "end card name (wordmark)")
        if rel.get("version"):
            sub(r'(<h2 class="name"[^>]*>.*?<em>)[^<]*(</em>)', html.escape(rel["version"]), "end card version (CHANGELOG %s)" % rel["version"])
    tag = copy.get("tagline") or {}
    if tag.get("text"):
        sub(r'(<p class="value"[^>]*>)SLOT: [^<]*(</p>)', html.escape(tag["text"]), "value line (%s)" % tag.get("source", "tagline"))
    inst = copy.get("install") or {}
    if inst.get("command"):
        sub(r'(<div class="cta"[^>]*><span class="ps">\$ </span>)SLOT: [^<]*(</div>)', html.escape(inst["command"]),
            "install command (%s)" % inst.get("source", "README"))
    url = kit.get("url") or ((kit.get("other") or {}).get("repository"))
    if url and not re.match(r"^https?://(127\.|localhost)", str(url)):
        short = re.sub(r"^(git\+)?https?://(www\.)?|\.git$|/$", "", str(url))
        sub(r'(<p class="url"[^>]*>)SLOT: [^<]*(</p>)', html.escape(short), "url")
    if name:
        label = html.escape(name) + ((" <b>&middot;</b> " + html.escape(rel["version"])) if rel.get("version") else "")
        sub(r'(<p class="label">)SLOT: product <b>&middot;</b> version(</p>)', label, "hook label")
    return page, filled


def apply_project(project: Path, kit: Dict[str, Any], *, page: str = "index.html", fill: bool = True) -> Dict[str, Any]:
    project = Path(project).resolve()
    idx = project / page
    text = idx.read_text(encoding="utf-8")
    t, notes = tokens(kit)
    links, fvals, fnotes = _font_links(kit, project)
    t.update(fvals)
    notes += fnotes
    text = BLOCK_RX.sub("\n", text)
    decl = "\n".join("    %s: %s;" % (k, v) for k, v in t.items())
    block = ("<!-- brand kit: %s (%s), applied by `showtime brand apply`; edit brand.json and re-apply, or edit here -->\n"
             "%s<style id=\"st-brand\">\n  :root {\n%s\n  }\n</style>\n") % (
        html.escape(str(kit.get("name") or "brand")), html.escape(Path(str(kit.get("_file") or "brand.json")).name),
        "".join(line + "\n" for line in links), decl)
    i = text.find("</head>")
    if i < 0:
        i = 0
    text = text[:i].rstrip("\n") + "\n" + block + text[i:]
    filled: List[str] = []
    if fill:
        text, filled = _fill_slots(text, kit)
    shots = copy_screens(project, kit)
    if shots:
        notes.append("the product's captured screens are in %s (use them in a browser-frame: data-src=\"%s\")" % (
            project / "shots" / "brand", shots[0]))
    idx.write_text(text, encoding="utf-8", newline="\n")
    cfgp = project / "showtime.json"
    if cfgp.is_file():
        cfg = read_json(cfgp, {}) or {}
        if t.get("--bg"):
            cfg["background"] = t["--bg"]
        tag = ((kit.get("copy") or {}).get("tagline") or {}).get("text")
        if fill and tag and str(cfg.get("subtitle", "")).startswith("SLOT"):
            cfg["subtitle"] = tag
        kf = kit.get("_file")
        if kf:
            try:
                kf = Path(os.path.relpath(str(kf), str(project))).as_posix()   # portable: relative to the project
            except ValueError:   # another drive on Windows
                pass
        cfg["brand"] = {"name": kit.get("name"), "file": kf, "accent": t.get("--accent"), "bg": t.get("--bg")}
        write_json(cfgp, cfg)
    return {"project": str(project), "tokens": t, "fonts": links, "filled": filled, "notes": notes,
            "brand": kit.get("_file"), "name": kit.get("name")}


def copy_screens(project: Path, kit: Dict[str, Any], per_aspect: int = 3) -> List[str]:
    """A web product's captured screens (hero first) copied into <project>/shots/brand/<aspect>/, so the page
    can show the real UI (the preview server serves the project folder only). Paths relative to the project."""
    if (kit.get("real_ui") or {}).get("kind") != "web":
        return []
    out: List[str] = []
    base = Path(str(kit.get("_file") or ".")).parent
    for aspect, files in ((kit.get("capture") or {}).get("screens") or {}).items():
        if aspect == "sections":
            continue
        dest = project / "shots" / "brand" / aspect.replace(":", "x")
        for f in files[:per_aspect]:
            src = Path(f) if Path(f).is_absolute() else base / f
            if src.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest / src.name))
                out.append((dest / src.name).relative_to(project).as_posix())
    return out


def is_applied(project: Path, page: str = "index.html") -> bool:
    try:
        return 'id="st-brand"' in (Path(project) / page).read_text(encoding="utf-8")
    except OSError:
        return False
