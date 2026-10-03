"""Brand first: one command that captures a product's brand and its real UI before a storyboard.

`showtime brand capture <url | repo folder>` writes a brand folder (by default `<job>/brand/`):

    brand.json   palette with roles, fonts, logo, the wordmark as the site sets it, the code-block look,
                 the product's own copy (tagline, headline, CTAs, install line, commands, features,
                 the latest release's notes), the real UI found (screens, or the terminal for a CLI)
    brand.md     the same for people and for the storyboard step: every line with its source
    capture/     the `showtime site capture` of the site (screens per aspect, sections, contact sheet)

A repo is scanned (`brand init --from`), its site folder (site/, docs/, public/, dist/ ... with an
index.html) is served and captured, and the two are merged: the rendered site's colours win for the
ground, the ink and the accent (they are what people see), the repo fills the rest. A URL is captured
directly. Inside a job the result is recorded in job.json ("brand"), and `showtime check` reads it; a
launch job without a brand kit records why with `showtime brand skip <job> --why "..."`.

Nothing here runs the product's own code: commands found in the README are listed for the director to
run on a sample (and save as evidence), never executed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, read_json, skill_dir
from . import contrast, luminance, palette

SITE_DIRS = ("site", "docs", "website", "www", "web", "public", "dist", "build", "out", "_site", "landing", "homepage")
INSTALL_RX = re.compile(r"^\s*(?:\$\s*)?((?:pip3?|pipx|uv(?:\s+tool)?|poetry|npm|pnpm|yarn|bun|npx|brew|cargo|go|gem|"
                        r"apt(?:-get)?|winget|scoop|choco|conda|docker|curl|composer|dotnet|nix-env|mix|deno|claude)\s+"
                        r"(?:install|add|i|tool install|run|pull|-g|-fsSL|plugin|require)\b[^\n#]*)", re.I)


# ------------------------------------------------------------------ the repo's own words

def _readme_text(root: Path) -> Tuple[Optional[Path], str]:
    for name in ("README.md", "readme.md", "README.markdown", "README.rst", "README.txt", "README"):
        p = root / name
        if p.is_file():
            try:
                return p, p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None, ""
    return None, ""


def _sections(md: str) -> List[Tuple[str, str, int]]:
    """(heading, body, line) for each markdown section (the text before the first heading is heading '')."""
    out: List[Tuple[str, str, int]] = []
    head, start, buf = "", 1, []
    in_code = False
    for i, line in enumerate(md.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if m:
            out.append((head, "\n".join(buf), start))
            head, start, buf = m.group(1).strip(), i, []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf), start))
    return out


def _code_lines(body: str, base_line: int) -> List[Tuple[str, int]]:
    """Lines inside fenced code blocks of a section, with their line numbers in the file."""
    out: List[Tuple[str, int]] = []
    in_code = False
    for i, line in enumerate(body.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code and line.strip():
            out.append((line.rstrip(), base_line + i))
    return out


def _split_comment(line: str) -> Tuple[str, Optional[str]]:
    """`quillsort a.txt --natural   # "file2" before "file10"` -> (command, comment)."""
    m = re.match(r"^(.*?\S)\s{2,}#\s*(.+)$", line) or re.match(r"^(.*?\S)\s+#\s+(.+)$", line)
    if m and m.group(1).count('"') % 2 == 0 and m.group(1).count("'") % 2 == 0:
        return m.group(1).strip(), m.group(2).strip()
    return line.strip(), None


def _masked(md: str) -> str:
    """The README with its fenced code blanked (same line count): a `# comment` in a shell block is not a heading."""
    out: List[str] = []
    in_code = False
    for line in md.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
            out.append("")
        else:
            out.append("" if in_code else line)
    return "\n".join(out)


def _plain(text: str) -> str:
    """Markdown/HTML as it reads: images, badges, comments and fine print (<sub>, <small>) dropped, links kept
    as their words, tags and emphasis removed."""
    t = re.sub(r"<!--.*?-->|<(sub|sup|small)\b[^>]*>.*?</\1\s*>", " ", text, flags=re.S | re.I)
    t = re.sub(r"<[^>]*>|!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    return re.sub(r"\s+", " ", re.sub(r"[`*_]", "", t)).strip()


def readme_title(md: str) -> Optional[Tuple[str, int, int]]:
    """The README's first H1 outside code (`# name`, `name` over `===`, or an HTML <h1>, which can span lines):
    (text, first line, last line). A deeper heading is never the title."""
    masked = _masked(md)
    found = []
    for rx in (r"^#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$",r"^(\S[^\n]*)\n=+[ \t]*$", r"<h1\b[^>]*>(.*?)</h1\s*>"):
        found += [(m.start(), m.end(), m.group(1)) for m in re.finditer(rx, masked, re.M | re.S | re.I)]
    for start, end, inner in sorted(found):
        text = _plain(inner)
        if text:
            return text, masked.count("\n", 0, start) + 1, masked.count("\n", 0, end) + 1
    return None


def readme_lead(md: str, after: int = 0) -> Optional[Tuple[str, int]]:
    """The first plain paragraph below line `after`: (text, line). Lines that are only a URL, and paragraphs
    that are only images, badges or fine print, are skipped; so are lists, quotes, tables, code and headings."""
    para: List[Tuple[str, int]] = []
    for i, line in enumerate(_masked(md).splitlines() + [""], 1):
        s = line.strip()
        if i <= after or re.match(r"^<?https?://\S+>?$", s):
            continue
        if s and not s.startswith("#"):
            para.append((s, i))
            continue
        text = _plain("\n".join(x for x, _ in para))
        first = next(((x, n) for x, n in para if _plain(x)), None)
        para = []
        if first and len(text) >= 20 and not re.match(r"^(>|\||[-*+]\s|\d+[.)]\s|\[!\w+\])", first[0]):
            return text, first[1]
    return None


def readme_copy(root: Path, name: str) -> Dict[str, Any]:
    """The product's own words from its README, each with file:line: the title, the one-line tagline,
    the install command, the usage commands and the feature bullets. Verbatim, never rephrased."""
    p, md = _readme_text(root)
    if not md:
        return {}
    rel = p.name if p else "README"
    out: Dict[str, Any] = {"source": rel}
    title = readme_title(md)
    if title:
        out["title"] = {"text": title[0], "source": "%s:%d" % (rel, title[1])}
    # tagline: the title's lead paragraph (the first plain one when there is no H1)
    lead = readme_lead(md, title[2] if title else 0)
    if lead:
        out["tagline"] = {"text": lead[0], "source": "%s:%d" % (rel, lead[1])}
    installs: List[Dict[str, Any]] = []
    commands: List[Dict[str, Any]] = []
    features: List[Dict[str, Any]] = []
    tool = (name or "").strip().lower()
    for head, body, start in _sections(md):
        h = head.lower()
        for line, ln in _code_lines(body, start):
            cmd, comment = _split_comment(line.lstrip("$ ").rstrip())
            item = {"command": cmd, "comment": comment, "line": line.strip(), "source": "%s:%d" % (rel, ln)}
            # in an install section any line counts, but a shell comment or a sentence (a prompt to type) does not
            if INSTALL_RX.match(cmd) or re.search(r"install|getting started|setup|quick ?start", h) and len(installs) < 3 \
                    and not (tool and cmd.lower().startswith(tool + " ")) and not re.match(r"^#|^[A-Z]\S*\s.*[.!?]$", cmd):
                if not any(x["command"] == cmd for x in installs):
                    installs.append(item)
            elif tool and re.search(r"(^|[\s|/])%s(\s|$)" % re.escape(tool), cmd.lower()):
                commands.append(item)
        if re.search(r"feature|highlights|why|what it does|what's inside", h):
            for i, line in enumerate(body.splitlines(), 1):
                m = re.match(r"^\s*[-*+]\s+(.+)$", line)
                if m:
                    features.append({"text": m.group(1).strip(), "source": "%s:%d" % (rel, start + i)})
    if installs:
        out["install"] = installs[0]
        if len(installs) > 1:
            out["install_other"] = installs[1:4]
    if commands:
        out["commands"] = commands[:12]
    if features:
        out["features"] = features[:12]
    return out


def changelog_copy(root: Path) -> Optional[Dict[str, Any]]:
    """The newest release in CHANGELOG/CHANGES/HISTORY/RELEASES: its version and its items, verbatim."""
    for name in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md", "RELEASES.md", "NEWS.md", "CHANGELOG", "CHANGES"):
        p = root / name
        if not p.is_file():
            continue
        try:
            md = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for head, body, start in _sections(md):
            m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?(?:[-+.][\w.]+)?)\b", head)
            if not m or re.search(r"unreleased", head, re.I):
                continue
            items = []
            for i, line in enumerate(body.splitlines(), 1):
                mm = re.match(r"^\s*[-*+]\s+(.+)$", line)
                if mm:
                    items.append({"text": mm.group(1).strip(), "source": "%s:%d" % (name, start + i)})
            return {"version": m.group(1), "heading": head, "source": "%s:%d" % (name, start), "items": items[:16]}
    return None


# ------------------------------------------------------------------ the real UI

def site_folders(root: Path) -> List[Path]:
    """Folders in the repo that are a site or an app build (they hold an index.html), best first."""
    found: List[Path] = []
    for d in SITE_DIRS:
        p = root / d
        if (p / "index.html").is_file():
            found.append(p)
    if (root / "index.html").is_file():
        found.append(root)
    return found


def dev_server_hint(root: Path) -> Optional[str]:
    pkg = read_json(root / "package.json", None) if (root / "package.json").is_file() else None
    scripts = (pkg or {}).get("scripts") or {} if isinstance(pkg, dict) else {}
    for key in ("dev", "start", "preview", "storybook"):
        if key in scripts:
            return ("the app runs with `npm run %s` (%s): start it, then run `showtime brand capture <repo> --url "
                    "http://localhost:<port>` so the real screens are captured" % (key, str(scripts[key])[:60]))
    return None


def _run_capture(target: str, serve: bool, out_dir: Path, aspects: str, timeout: float = 900) -> Tuple[Optional[Path], Optional[str]]:
    """`showtime site capture` into out_dir: (site.json, None) or (None, why)."""
    launcher = skill_dir() / "lib" / "st" / "launcher.py"
    args = [sys.executable, str(launcher), "site", "capture"]
    args += (["--serve", target, str(out_dir)] if serve else [target, str(out_dir)])
    args += ["--aspect", aspects]
    try:
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                            errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "site capture did not finish: %s" % e
    sj = out_dir / "site.json"
    if cp.returncode == 3:
        return None, "the site blocked automated capture (see %s)" % (out_dir / "BLOCKED.md")
    if cp.returncode != 0 or not sj.is_file():
        tail = (cp.stderr or cp.stdout or "").strip().splitlines()[-4:]
        return None, "site capture failed: %s" % " / ".join(tail)[-400:]
    return sj, None


def screens_of(cap_dir: Path) -> Dict[str, List[str]]:
    """The capture's screens per aspect (hero first) and its section shots."""
    out: Dict[str, List[str]] = {}
    shots = cap_dir / "shots"
    if shots.is_dir():
        for d in sorted(x for x in shots.iterdir() if x.is_dir()):
            files = sorted(str(f) for f in d.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
            if files:
                out[d.name.replace("x", ":")] = files
    secs = cap_dir / "sections"
    if secs.is_dir():
        files = sorted(str(f) for f in secs.iterdir() if f.suffix.lower() in (".png", ".jpg"))
        if files:
            out["sections"] = files
    return out


# ------------------------------------------------------------------ merge

def _nearest_role(hexv: Optional[str], pal: Dict[str, str]) -> Optional[str]:
    if not hexv:
        return None
    from . import rgb
    a = rgb(hexv)
    best = None
    for role, h in pal.items():
        try:
            b = rgb(h)
        except (ValueError, IndexError):
            continue
        d = sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
        if d < 24 and (best is None or d < best[0]):
            best = (d, role)
    return best[1] if best else None


def html_wordmark(index_html: Path) -> Optional[Dict[str, Any]]:
    """Without a browser: the first short <h1> of a site folder, split where a <span>/<em>/<b> starts
    (`<h1>quill<span>sort</span></h1>` -> quill + sort, the second run marked as the accent)."""
    try:
        html = index_html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", html, re.S | re.I)
    if not m:
        return None
    inner = m.group(1)
    if re.search(r"<(img|svg)\b", inner, re.I):
        return None
    runs: List[Dict[str, Any]] = []
    for mm in re.finditer(r"<(span|em|strong|b|i|mark)\b[^>]*>(.*?)</\1>|([^<]+)", inner, re.S | re.I):
        text = re.sub(r"<[^>]+>|\s+", " ", mm.group(2) if mm.group(1) else (mm.group(3) or "")).strip()
        if text:
            runs.append({"text": text, "role": "accent" if mm.group(1) else "ink"})
    text = "".join(r["text"] for r in runs)
    if not runs or len(text) > 28:
        return None
    return {"text": text, "runs": runs, "source": "%s <h1>" % index_html.name}


def merge_site(kit: Dict[str, Any], site_kit: Dict[str, Any], site: Dict[str, Any]) -> List[str]:
    """Fold a site capture into a repo kit. The rendered site wins for bg, ink and accent (what people
    see); the repo keeps the rest. Returns notes on what changed."""
    notes: List[str] = []
    colors = [c for c in kit.get("colors") or []]
    sbg = next((c["hex"] for c in site_kit.get("colors") or [] if c.get("role") == "bg"), None)
    for c in site_kit.get("colors") or []:
        role = c.get("role")
        if role == "ink" and sbg and contrast(c["hex"], sbg) < 4.5:
            # the most-used text colour can be a code block's (light text in a dark box on a light page)
            notes.append("the site's most-used text colour %s does not read on its ground %s (%.1f:1): kept the repo's ink" % (
                c["hex"], sbg, contrast(c["hex"], sbg)))
            continue
        if role in ("bg", "ink", "accent"):
            old = next((x for x in colors if x.get("role") == role), None)
            if old and old.get("hex") != c["hex"]:
                notes.append("%s: the site shows %s (the repo's CSS says %s from %s); using the site's" % (
                    role, c["hex"], old.get("hex"), old.get("source")))
                old["role"] = "other"
            if not old or old.get("hex") != c["hex"]:
                colors.insert(0, dict(c))
        elif role and role not in {x.get("role") for x in colors} and role != "other":
            colors.append(dict(c))
    kit["colors"] = colors
    kit["palette"] = {}
    for c in colors:
        if c.get("role") and c["role"] != "other" and c["role"] not in kit["palette"]:
            kit["palette"][c["role"]] = c["hex"]
    fonts = kit.get("fonts") or {}
    for slot, f in (site_kit.get("fonts") or {}).items():
        if slot not in fonts:
            fonts[slot] = f
    kit["fonts"] = fonts
    lg = kit.get("logo") or {}
    slg = site_kit.get("logo") or {}
    if not lg.get("path") and slg.get("path"):
        kit["logo"] = slg
    if not kit.get("url") and site_kit.get("url") and not re.match(r"^https?://(127\.|localhost|\[::1\])", str(site_kit["url"])):
        kit["url"] = site_kit["url"]
    return notes


def site_extras(kit: Dict[str, Any], site: Dict[str, Any], site_json: Path) -> None:
    """Wordmark, code-block look, headline, CTAs from a site capture into the kit."""
    pal = palette(kit)
    wm = site.get("wordmark")
    if isinstance(wm, dict) and wm.get("runs"):
        runs = []
        for r in wm["runs"]:
            role = _nearest_role(r.get("color"), pal) or "ink"
            runs.append({"text": r.get("text", ""), "color": r.get("color"), "role": role, "weight": r.get("weight")})
        kit["wordmark"] = {"text": wm.get("text"), "runs": runs, "font": wm.get("font"),
                           "source": "%s wordmark (%s)" % (site_json.name, wm.get("tag"))}
    code = site.get("code")
    if isinstance(code, dict) and code.get("bg"):
        kit["code"] = {"bg": code.get("bg"), "fg": code.get("fg"), "radius": code.get("radius"),
                       "source": "%s code block" % site_json.name}
    copy = kit.setdefault("copy", {})
    h1 = next((h for h in site.get("headings") or [] if h.get("level") == 1), None)
    if h1:
        copy.setdefault("headline", {"text": h1.get("text"), "source": "site h1"})
    ctas = [c for c in site.get("ctas") or [] if c.get("text")]
    if ctas:
        copy["ctas"] = [{"text": c["text"], "primary": bool(c.get("primary")), "source": "site CTA"} for c in ctas[:4]]
    meta = site.get("meta") or {}
    if meta.get("description"):
        copy.setdefault("site_description", {"text": meta["description"], "source": "site meta description"})
    tag = next((c for c in site.get("copy") or [] if isinstance(c, dict) and c.get("text")), None)
    if tag and not copy.get("tagline"):
        copy["tagline"] = {"text": tag["text"], "source": "site copy"}


# ------------------------------------------------------------------ the command

def capture(source: str, out_dir: Path, *, serve: Optional[str] = None, url: Optional[str] = None,
            aspects: str = "16:9,1:1,9:16", site: bool = True, lookup_fonts: bool = True,
            say=lambda m: None) -> Dict[str, Any]:
    """Draft the kit (repo and/or site), capture the real UI, collect the product's copy. Returns the kit
    (absolute paths) plus "notes"."""
    from . import draft
    notes: List[str] = []
    is_url = bool(re.match(r"^https?://", source, re.I))
    cap_dir = out_dir / "capture"
    kit: Dict[str, Any]
    real_ui: Dict[str, Any] = {}
    site_json: Optional[Path] = None
    if is_url:
        say("capturing %s (screens, copy, colours, fonts; about 15-60 s)" % source)
        site_json, why = _run_capture(source, False, cap_dir, aspects)
        if site_json is None:
            raise ShowtimeError("could not capture %s: %s" % (source, why),
                                hint="give the repo instead (showtime brand capture <folder>), or screenshots and "
                                     "colours by hand; then record the choice with `showtime brand skip <job> --why ...`")
        kit = draft.from_site(site_json, lookup_fonts)
        real_ui = {"kind": "web", "from": source}
    else:
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            raise ShowtimeError("not a folder or a URL: %s" % source,
                                hint="showtime brand capture <repo folder>  or  showtime brand capture https://example.com")
        say("scanning %s (CSS variables, Tailwind, fonts, logo, README, CHANGELOG)" % root)
        kit = draft.from_repo(root, lookup_fonts)
        name = str(kit.get("name") or root.name)
        copy = readme_copy(root, name)
        rel = changelog_copy(root)
        kit["copy"] = {k: v for k, v in copy.items() if k != "source"}
        if rel:
            kit["copy"]["release"] = rel
        target, how = None, None
        if url:
            target, how = url, False
        elif serve:
            target, how = str(Path(serve).expanduser().resolve()), True
        elif site:
            folders = site_folders(root)
            if folders:
                target, how = str(folders[0]), True
        if target and site:
            say("capturing the product's own %s: %s (%s)" % ("app" if url else "site", target, aspects))
            site_json, why = _run_capture(target, bool(how), cap_dir, aspects)
            if site_json is None:
                notes.append("the site capture failed (%s): the kit is from the repo only" % why)
            else:
                skit = draft.from_site(site_json, lookup_fonts)
                notes += merge_site(kit, skit, read_json(site_json, {}) or {})
        elif not site:
            notes.append("site capture skipped (--no-site)")
        if site_json is None and not kit.get("wordmark"):
            for folder in ([Path(target)] if target and how else []) + site_folders(root):
                wm = html_wordmark(folder / "index.html")
                if wm:
                    kit["wordmark"] = wm
                    break
        hint = dev_server_hint(root)
        cli_cmds = kit["copy"].get("commands") or []
        if url or (target and not cli_cmds):
            real_ui = {"kind": "web", "from": target}
        elif cli_cmds:
            real_ui = {"kind": "cli", "from": "README commands",
                       "note": "a command-line tool: its real UI is the terminal. Run the commands below on a small "
                               "sample and save command + output to <job>/work/evidence/<name>.txt; show those."}
        else:
            real_ui = {"kind": "unknown", "note": "no site folder, app build or README commands found"}
        if hint and not url:
            real_ui["dev_server"] = hint
            notes.append(hint)
        if cli_cmds and real_ui.get("kind") == "web":
            real_ui["cli"] = "the README also shows commands: the terminal is part of the real UI"
        if target and real_ui.get("kind") == "cli":
            real_ui["site"] = ("the product's site (%s) was captured for its look and words; the product itself is the "
                               "terminal" % Path(target).name if how else target)
    if site_json is not None:
        site = read_json(site_json, {}) or {}
        site_extras(kit, site, site_json)
        kit["capture"] = {"dir": str(cap_dir), "site_json": str(site_json),
                          "contact_sheet": str(cap_dir / "contact-sheet.jpg") if (cap_dir / "contact-sheet.jpg").is_file() else None,
                          "inventory": str(cap_dir / "inventory.md") if (cap_dir / "inventory.md").is_file() else None,
                          "screens": screens_of(cap_dir)}
    kit["real_ui"] = real_ui
    kit["notes"] = notes
    return kit


# ------------------------------------------------------------------ job ledger

def record_in_job(job: Path, entry: Dict[str, Any]) -> None:
    """job.json "brand": {"kit": path, ...} or {"none": why}; SHOWTIME.md shows it."""
    from ..job import ledger
    data = ledger.load(job)
    entry = dict(entry, at=ledger.now_iso())
    data["brand"] = entry
    if entry.get("kit"):
        data.setdefault("pointers", {})["brand"] = entry["kit"]
        ledger._add_item(data.setdefault("assumed", []), "brand kit (draft, from %s): %s" % (
            entry.get("source") or "?", entry.get("summary") or entry["kit"]), "brand")
        event = "brand kit captured: %s" % entry["kit"]
    else:
        data.get("pointers", {}).pop("brand", None)
        ledger._add_item(data.setdefault("assumed", []), "no brand kit: %s" % entry.get("none"), "brand")
        event = "no brand kit: %s" % entry.get("none")
    data.setdefault("history", []).append({"at": ledger.now_iso(), "event": event})
    ledger.save(job, data)


def job_brand(job: Optional[Path]) -> Optional[Dict[str, Any]]:
    if job is None:
        return None
    d = read_json(job / "job.json", {})
    b = d.get("brand") if isinstance(d, dict) else None
    return b if isinstance(b, dict) else None


# ------------------------------------------------------------------ brand.md for the storyboard

def _src(x: Any) -> str:
    return " (%s)" % x["source"] if isinstance(x, dict) and x.get("source") else ""


def storyboard_md(kit: Dict[str, Any], base_md: str) -> str:
    """brand.md: the drafted kit summary plus what the storyboard needs, verbatim with sources."""
    pal = palette(kit)
    L = [base_md.rstrip(), "", "## For the storyboard (brand first)", "",
         "Use these by default; the user's words win. Everything on screen comes from this list or from a run you saved.", ""]
    wm = kit.get("wordmark")
    if wm:
        parts = " + ".join("\"%s\" in %s%s" % (r["text"], r.get("role") or "ink",
                                                 " %s" % r["color"] if r.get("color") else "") for r in wm.get("runs") or [])
        L.append("- **Wordmark**: %s%s. Set the name this way on the end card." % (parts, _src(wm)))
    if pal:
        L.append("- **Ground and accent**: bg `%s`, ink `%s`, accent `%s`%s. One ground for the film, the accent on the "
                 "key word, the prompt and the result line only." % (pal.get("bg", "?"), pal.get("ink", "?"), pal.get("accent", "?"),
                                                                     ", muted `%s`" % pal["muted"] if pal.get("muted") else ""))
        if pal.get("bg") and pal.get("accent"):
            L.append("  Accent on bg: %.1f:1%s." % (contrast(pal["bg"], pal["accent"]),
                                                     "" if contrast(pal["bg"], pal["accent"]) >= 4.5 else
                                                     " (below 4.5:1: `brand apply` deepens it for text, keeping the hue)"))
    code = kit.get("code")
    if code and code.get("fg") and code.get("bg"):
        L.append("- **Terminal / code look**: `%s` text on `%s`%s. The product window uses it." % (
            code["fg"], code["bg"], _src(code)))
    fonts = kit.get("fonts") or {}
    if not fonts:
        L.append("- **Type**: the product uses a system font stack; the film uses the template's Geist + Geist Mono "
                 "(say so in the opening line).")
    copy = kit.get("copy") or {}
    L += ["", "### Copy (verbatim)", ""]
    for key, label in (("title", "Name"), ("tagline", "Tagline"), ("headline", "Site headline"),
                       ("site_description", "Site description")):
        if copy.get(key):
            L.append("- %s: \"%s\"%s" % (label, copy[key]["text"], _src(copy[key])))
    if copy.get("install"):
        L.append("- Install / CTA: `%s`%s" % (copy["install"]["command"], _src(copy["install"])))
    for c in copy.get("ctas") or []:
        L.append("- Button: \"%s\"%s%s" % (c["text"], " (primary)" if c.get("primary") else "", _src(c)))
    if copy.get("features"):
        L += ["", "Features:"] + ["- %s%s" % (f["text"], _src(f)) for f in copy["features"]]
    rel = copy.get("release")
    if rel:
        L += ["", "Latest release **%s**%s:" % (rel["version"], _src(rel))] + ["- %s%s" % (i["text"], _src(i)) for i in rel.get("items") or []]
    if copy.get("commands"):
        L += ["", "Commands the README shows (run them on a sample and save command + output as evidence; never type output from memory):"]
        L += ["- `%s`%s%s" % (c["command"], " # %s" % c["comment"] if c.get("comment") else "", _src(c)) for c in copy["commands"]]
    ui = kit.get("real_ui") or {}
    L += ["", "### Real UI", ""]
    if ui.get("kind") == "web":
        L.append("- Web: captured from %s." % ui.get("from"))
    elif ui.get("kind") == "cli":
        L.append("- " + ui.get("note", ""))
    else:
        L.append("- " + (ui.get("note") or "not found"))
    for k in ("site", "cli", "dev_server"):
        if ui.get(k):
            L.append("- " + ui[k])
    cap = kit.get("capture") or {}
    if cap:
        L.append("- Capture: `%s` (look at `contact-sheet.jpg` once; `inventory.md` lists copy, CTAs and colours)." % cap.get("dir"))
        for aspect, files in (cap.get("screens") or {}).items():
            L.append("- screens %s: %s" % (aspect, ", ".join("`%s`" % Path(f).name for f in files[:4])
                                           + (" +%d" % (len(files) - 4) if len(files) > 4 else "")))
    if kit.get("notes"):
        L += ["", "### Notes", ""] + ["- %s" % n for n in kit["notes"]]
    L += ["", "### Launch defaults from this kit", "",
          "`showtime new launch <job>/project` finds this kit (the job's `brand/` folder) and applies it: ground, ink, "
          "muted, accent, the window in the product's code colours, fonts when installable, and the end card's "
          "wordmark, value line and install command where the template still has SLOT text. "
          "`showtime brand apply <project>` does the same for a project made earlier.", ""]
    return "\n".join(L)


def summary_line(kit: Dict[str, Any]) -> str:
    pal = palette(kit)
    bits = ["%s %s" % (r, pal[r]) for r in ("bg", "ink", "accent") if pal.get(r)]
    wm = kit.get("wordmark")
    if wm:
        bits.append("wordmark %s" % "+".join(r["text"] for r in wm.get("runs") or []))
    ui = (kit.get("real_ui") or {}).get("kind")
    if ui:
        bits.append("real UI: %s" % ui)
    return ", ".join(bits)


def is_light(hexv: Optional[str]) -> bool:
    return bool(hexv) and luminance(str(hexv)) > 0.45


__all__ = ["capture", "readme_copy", "changelog_copy", "site_folders", "html_wordmark", "merge_site", "site_extras",
           "record_in_job", "job_brand", "storyboard_md", "summary_line", "is_light", "screens_of"]
