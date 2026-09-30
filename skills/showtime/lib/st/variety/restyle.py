"""A new project in a job with a style reference starts in the reference's look.

`showtime reference <video> --job <job>` writes `references/<name>/style.css`: the reference's sampled
palette, side margin and type sizes as CSS tokens, plus the theme tokens (--bg, --fg, --accent, --safe-x,
--grain, --glow) mapped onto them. `showtime new <template> <dir> --job <job>` copies it into the project as
`reference-style.css` and links it as the last stylesheet in <head>, so its tokens win over the theme's and
the template's own :root defaults, and sets showtime.json "background" to the reference's ground.

A brand kit applied to the project wins for colours (the brand is the user's): the style file is then not
linked and the log says where it is. `--no-reference-style` skips all of this.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from ..common import read_json, write_json

LINK = '<link rel="stylesheet" href="reference-style.css">'
FILE = "reference-style.css"


def latest_style(job: Path) -> Optional[Dict[str, Any]]:
    """The newest reference of the job that has a style.css: {title, dir, css, ground}."""
    from .guard import job_references
    best = None
    for r in job_references(Path(job)):
        css = Path(r["dir"]) / "style.css"
        if not css.is_file():
            continue
        data = read_json(Path(r["dir"]) / "reference.json", {}) or {}
        cand = {"title": r.get("title") or Path(r["dir"]).name, "dir": r["dir"], "css": str(css),
                "ground": (data.get("palette_roles") or {}).get("ground"),
                "flat": bool((data.get("palette_roles") or {}).get("flat")), "mtime": css.stat().st_mtime}
        if best is None or cand["mtime"] >= best["mtime"]:
            best = cand
    return best


def link_into(page: Path) -> bool:
    """Link reference-style.css as the last stylesheet in <head> (once). False when there is no <head>."""
    html = page.read_text(encoding="utf-8")
    if FILE in html:
        return True
    m = re.search(r"</head\s*>", html, re.I)
    if not m:
        return False
    html = html[:m.start()] + LINK + "\n" + html[m.start():]
    page.write_text(html, encoding="utf-8", newline="\n")
    return True


def apply_to_project(project: Path, job: Optional[Path], brand_applied: bool = False) -> Optional[Dict[str, Any]]:
    if job is None:
        return None
    ref = latest_style(Path(job))
    if ref is None:
        return None
    project = Path(project)
    out: Dict[str, Any] = {"reference": ref["title"], "style_css": ref["css"], "linked": False, "log": []}
    if brand_applied:
        out["log"].append("style reference \"%s\": the brand kit's colours win; its style tokens are in %s "
                          "(link them if the user wants the reference's colours)" % (ref["title"], ref["css"]))
        return out
    page = project / "index.html"
    if not page.is_file():
        out["log"].append("style reference \"%s\": no index.html to link %s into; use its colours and sizes "
                          "(reference.md)" % (ref["title"], ref["css"]))
        return out
    shutil.copyfile(ref["css"], str(project / FILE))
    if not link_into(page):
        out["log"].append("style reference \"%s\": copied %s; add %s to the page's <head>" % (ref["title"], FILE, LINK))
        return out
    out["linked"] = True
    cfg_path = project / "showtime.json"
    if ref.get("ground") and cfg_path.is_file():
        cfg = read_json(cfg_path, {}) or {}
        cfg["background"] = ref["ground"]
        write_json(cfg_path, cfg)
    out["log"].append("style reference \"%s\": linked %s (its palette, margin and type sizes win over the "
                      "template's)%s" % (ref["title"], FILE, "; background %s" % ref["ground"] if ref.get("ground") else ""))
    if ref.get("flat"):
        out["log"].append("  the reference uses flat fills: remove the template's gradients, glows and grids; keep only "
                          "what the reference has (reference.md)")
    return out
