#!/usr/bin/env python3
"""Build showtime's companion site (landing, gallery, crew, docs with search, example pages) into a folder
of static files with relative links: it works from GitHub Pages, any static host, or straight from disk.

    python3 site/build.py --media-from ../showtime-examples/examples/   # local build, videos from your checkout
    python3 site/build.py --examples _examples/examples --media-from _media --repo owner/name --out _site   # CI
    python3 site/build.py --only 05,20,22 --out /tmp/preview   # a small preview

The examples live in their own repository (site/config.json "examples_repo"). The build reads them from
--examples DIR, else from an examples/ folder in this checkout, else from a sibling checkout
("examples_dir" in site/config.json, ../showtime-examples/examples).

Needs Python 3.8+ and markdown-it-py (`pip install markdown-it-py`; showtime's own venv has it).
Videos over 10 MB are GitHub release assets (MEDIA.json in the examples folder), not files in git. --media-from names
folders to look in, by path under examples/ or by release asset name; CI downloads the release into one
(`gh release download`). A video that is not found is not copied: its card shows the preview loop and a
link to the release asset instead. No trackers, no external requests: fonts are self-hosted.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover
    sys.exit("site/build.py needs markdown-it-py: pip install markdown-it-py "
             "(or run it with showtime's venv: ~/.showtime/venv/bin/python site/build.py ...)")

SITE = Path(__file__).resolve().parent
REPO = SITE.parent
REFS = REPO / "skills" / "showtime" / "references"
CONFIG = json.loads((SITE / "config.json").read_text(encoding="utf-8"))
# The examples folder and its media manifest: set by configure_examples() (main). Pages keep calling example
# files by their path in the examples repository, "examples/<folder>/...", wherever the checkout is.
EXAMPLES = REPO / "examples"
EXAMPLES_REPO = ""   # owner/name of the examples repository when the examples are not in this checkout
MEDIA: dict = {"release": {}, "files": []}
ASSET_BY_PATH: Dict[str, str] = {}
PATH_BY_ASSET: Dict[str, str] = {}
IMG_EXT = {".svg", ".webp", ".png", ".jpg", ".jpeg", ".gif"}
PREVIEWS = json.loads((SITE / "content" / "previews.json").read_text(encoding="utf-8"))["previews"]


def _ffmpeg() -> Optional[str]:
    """showtime's own ffmpeg, else $SHOWTIME_FFMPEG, else one on PATH (CI installs it)."""
    env = os.environ.get("SHOWTIME_FFMPEG")
    home = Path(os.environ.get("SHOWTIME_HOME") or Path.home() / ".showtime") / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    for cand in (env, str(home) if home.is_file() else None, shutil.which("ffmpeg")):
        if cand:
            return cand
    return None


FFMPEG = _ffmpeg()


# ----------------------------------------------------------------------------------------------- helpers

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def slugify(text: str, seen: Dict[str, int]) -> str:
    """GitHub's heading anchors: lowercase, drop punctuation, spaces to hyphens, -1/-2 for repeats."""
    s = re.sub(r"<[^>]+>", "", text).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s).replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if not n else "%s-%d" % (s, n)


def find_examples(arg: str = "") -> Path:
    """The examples folder: --examples, else examples/ in this checkout, else the sibling checkout in config.json."""
    if arg:
        cands = [Path(arg)]
    else:
        cands = [REPO / "examples"] + ([REPO / CONFIG["examples_dir"]] if CONFIG.get("examples_dir") else [])
    for c in cands:
        if (c / "README.md").is_file() and (c / "MEDIA.json").is_file():
            return c.resolve()
    sys.exit("site/build.py: no examples folder at %s. Clone https://github.com/%s next to this checkout, or pass "
             "--examples DIR (the examples/ folder of that clone)." % (" or ".join(str(c) for c in cands),
                                                                        CONFIG.get("examples_repo", "owner/examples")))


def configure_examples(path: Path, examples_repo: str = "") -> None:
    global EXAMPLES, EXAMPLES_REPO, MEDIA, ASSET_BY_PATH, PATH_BY_ASSET
    EXAMPLES = path.resolve()
    inside = EXAMPLES == (REPO / "examples").resolve()
    EXAMPLES_REPO = "" if inside else (examples_repo or CONFIG.get("examples_repo", ""))
    MEDIA = json.loads((EXAMPLES / "MEDIA.json").read_text(encoding="utf-8"))
    ASSET_BY_PATH = {e["path"]: e["asset"] for e in MEDIA["files"]}
    PATH_BY_ASSET = {e["asset"]: e["path"] for e in MEDIA["files"]}


def src_path(repo_rel: str) -> Path:
    """A repository path to the file on disk: examples/... lives in the examples checkout."""
    if repo_rel == "examples":
        return EXAMPLES
    if repo_rel.startswith("examples/"):
        return EXAMPLES / repo_rel[len("examples/"):]
    return REPO / repo_rel


def repo_path(p: Path) -> Optional[str]:
    """A file on disk to its repository path (examples/... for the examples checkout); None when outside both."""
    p = p.resolve()
    try:
        r = p.relative_to(EXAMPLES).as_posix()
        return "examples" if r == "." else "examples/" + r
    except ValueError:
        pass
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return None


GH_FILE = re.compile(r"^https://github\.com/([^/]+/[^/#?]+)/(?:blob|tree|raw)/[^/]+/([^#?]*)(?:\?[^#]*)?(?:#(.*))?$")


def local_from_github(ref: str, repo: str) -> Optional[Tuple[Path, str]]:
    """A GitHub file or folder URL of this repository or the examples repository -> (file on disk, fragment),
    so the site links its own page instead of GitHub. None when it is another repository or not on disk."""
    m = GH_FILE.match(ref)
    if not m:
        return None
    owner_name, path, frag = m.group(1).lower(), m.group(2).rstrip("/"), m.group(3) or ""
    if EXAMPLES_REPO and owner_name == EXAMPLES_REPO.lower():
        target = src_path(path) if (path == "examples" or path.startswith("examples/")) else None
    elif owner_name in {x.lower() for x in (repo, CONFIG.get("repo", "")) if x}:
        target = REPO / path
    else:
        return None
    if target is None or not target.exists():
        return None
    return target, frag


def rel(from_page: str, to: str) -> str:
    """Relative URL from one output page (posix path under the site root) to another file."""
    up = from_page.count("/")
    return "../" * up + to


class Site:
    def __init__(self, out: Path, media_dirs: List[Path], repo: str, only: Optional[set], branch: str,
                 max_html: float = 0.0) -> None:
        self.out = out
        self.max_html = max_html
        self.all_previews = True
        self.media_dirs = media_dirs
        self.repo = repo
        self.only = only
        self.branch = branch
        self.pages: Dict[Path, str] = {}     # source .md (absolute) -> output page
        self.copied: Dict[str, str] = {}
        self.missing_media: List[str] = []
        self.search: List[dict] = []
        self.md = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")

    # -------------------------------------------------------------------------------- files and media
    def gh(self, repo_rel: str, is_dir: bool = False) -> Optional[str]:
        repo = self.repo
        if EXAMPLES_REPO and (repo_rel == "examples" or repo_rel.startswith("examples/")):
            repo = EXAMPLES_REPO
        if not repo:
            return None
        return "https://github.com/%s/%s/%s/%s" % (repo, "tree" if is_dir else "blob", self.branch, repo_rel)

    def release_url(self, asset: str) -> Optional[str]:
        """The media release lives in the examples repository (this one when the examples are here)."""
        repo = EXAMPLES_REPO or self.repo
        if not repo:
            return None
        return "https://github.com/%s/releases/download/%s/%s" % (repo, MEDIA["release"]["tag"], asset)

    def copy_asset(self, src: Path) -> str:
        """Copy a repo file (image, font, svg) into the site under a/<repo path>; return its site path."""
        r = repo_path(src)
        if r is None:
            raise ValueError("%s is outside the repository and the examples checkout" % src)
        dst = "a/" + r
        if dst not in self.copied:
            p = self.out / dst
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, p)
            self.copied[dst] = r
        return dst

    def find_media(self, repo_rel: str) -> Optional[Path]:
        """An example file by its repo path (examples/...), looked up in --media-from folders by path under
        examples/ or by release asset name, then in the checkout itself."""
        under = repo_rel[len("examples/"):] if repo_rel.startswith("examples/") else repo_rel
        asset = ASSET_BY_PATH.get(repo_rel)
        for d in self.media_dirs:
            for cand in (d / under, d / asset if asset else None, d / repo_rel):
                if cand and cand.is_file():
                    return cand
        p = src_path(repo_rel)
        return p if p.is_file() else None

    def media(self, repo_rel: str, folder: str) -> Tuple[Optional[str], Optional[str]]:
        """(site path, fallback URL) for an example video or HTML video. The site path is None when the file
        is not available to this build (or the example is outside --only)."""
        asset = ASSET_BY_PATH.get(repo_rel)
        fallback = self.release_url(asset) if asset else self.gh(repo_rel)
        is_html = repo_rel.endswith(".html")
        if self.only is not None and folder[:2] not in self.only and not is_html and folder != "_launch":
            return None, fallback
        src = self.find_media(repo_rel)
        if not src:
            self.missing_media.append(repo_rel)
            return None, fallback
        if is_html and self.max_html and src.stat().st_size > self.max_html * 1e6:
            return None, fallback
        dst = "media/" + repo_rel[len("examples/"):]
        if dst not in self.copied:
            p = self.out / dst
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, p)
            self.copied[dst] = repo_rel
        return dst, fallback

    def preview(self, folder: str, main: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(still, clip) site paths for the gallery: a 1280 px frame and a silent 4 s clip cut from the example's main
        video at the window in content/previews.json. Needs ffmpeg and the video; cached in site/_cache."""
        win = PREVIEWS.get(folder)
        if not (win and main and FFMPEG):
            return None, None
        if self.only is not None and folder[:2] not in self.only and not self.all_previews:
            return None, None
        src = self.find_media(main)
        if not src:
            return None, None
        key = "%s-%s-%s" % (folder, win["from"], win["dur"])
        cache = SITE / "_cache"
        cache.mkdir(exist_ok=True)
        clip, still = cache / (key + ".mp4"), cache / (key + "-%s.jpg" % win.get("still", "mid"))
        vf = ("scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos,"
              "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x0E0B09,setsar=1,format=yuv420p")
        try:
            if not clip.is_file():
                subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(win["from"]), "-i", str(src), "-t", str(win["dur"]), "-an",
                                "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-profile:v", "high",
                                "-movflags", "+faststart", str(clip)], check=True)
            if not still.is_file():
                subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(win["from"] + win.get("still", win["dur"] / 2)), "-i", str(src), "-frames:v", "1",
                                "-vf", vf.replace(",format=yuv420p", ""), "-q:v", "3", str(still)], check=True)
        except (subprocess.CalledProcessError, OSError):
            return None, None
        out = []
        for f, name in ((still, "poster.jpg"), (clip, "preview.mp4")):
            dst = "media/previews/%s-%s" % (folder, name)
            p = self.out / dst
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, p)
            out.append(dst)
        return out[0], out[1]

    # -------------------------------------------------------------------------------- links in content
    def resolve_ref(self, ref: str, src_dir: Path, page: str) -> Optional[str]:
        """Rewrite one relative href/src from a repo file into a site URL (None: drop the link)."""
        m = RELEASE_LINK.match(ref or "")
        if m and m.group(1) in PATH_BY_ASSET:
            ref = "{{RELEASE_URL}}/" + m.group(1)
        gh_local = local_from_github(ref or "", self.repo)
        if gh_local:
            target, frag = gh_local
            r = repo_path(target)
            ref = os.path.relpath(str(target), str(src_dir)).replace(os.sep, "/") + ("/" if target.is_dir() else "")
            ref += ("#" + frag) if frag else ""
        if not ref or re.match(r"^(https?:|mailto:|data:|#)", ref):
            return ref
        if ref.startswith("{{RELEASE_URL}}/"):
            asset = ref.split("/", 1)[1]
            path = PATH_BY_ASSET.get(asset)
            if path:
                folder = path.split("/")[1]
                local, fb = self.media(path, folder)
                if local:
                    return rel(page, local)
                return fb
            return None
        path, _, frag = ref.partition("#")
        target = (src_dir / path).resolve()
        r = repo_path(target)
        if r is None:
            return None
        if not target.exists():
            return None
        if target.is_dir():
            for readme in ("README.md", "index.md"):
                if (target / readme).resolve() in self.pages:
                    return rel(page, self.pages[(target / readme).resolve()]) + ("#" + frag if frag else "")
            if r.startswith("examples/") and r.count("/") == 1 and (target / "README.md").is_file():
                return rel(page, "examples/%s.html" % target.name)
            return self.gh(r, is_dir=True)
        if target in self.pages:
            return rel(page, self.pages[target]) + ("#" + frag if frag else "")
        if target.suffix.lower() in IMG_EXT:
            return rel(page, self.copy_asset(target))
        if target.suffix.lower() in (".mp4", ".html") and r.startswith("examples/"):
            local, fb = self.media(r, r.split("/")[1])
            return rel(page, local) if local else fb
        return self.gh(r)

    def rewrite(self, html_text: str, src: Path, page: str) -> str:
        src_dir = src.parent

        def attr(m):
            name, val = m.group(1), m.group(2)
            if name == "srcset":
                new = self.resolve_ref(val.strip().split(" ")[0], src_dir, page)
                return '%s="%s"' % (name, new) if new else m.group(0)
            new = self.resolve_ref(html.unescape(val), src_dir, page)
            if new is None:
                return 'data-dropped="%s"' % esc(val) if name == "href" else m.group(0)
            return '%s="%s"' % (name, esc(new))
        out = re.sub(r'\b(href|src|srcset)="([^"]*)"', attr, html_text)
        # links whose target is not part of the site and there is no repo URL yet: keep the text only
        out = re.sub(r'<a data-dropped="[^"]*"[^>]*>(.*?)</a>', r'<span class="nolink">\1</span>', out, flags=re.S)
        # theme-aware art from assets/readme: let the page's theme switch pick the variant
        out = re.sub(r'(<(?:img|source)\b[^>]*?(?:src|srcset)="[^"]*-(?:light|dark)\.svg")', r'\1 data-themed', out)
        return out

    def render_md(self, text: str, src: Path, page: str, drop_h1: bool = False) -> Tuple[str, str, List[Tuple[str, str, int]]]:
        """Markdown -> (html, title, headings[(text, id, level)])."""
        env: dict = {}
        tokens = self.md.parse(text, env)
        seen: Dict[str, int] = {}
        heads, title = [], ""
        for i, t in enumerate(tokens):
            if t.type == "heading_open":
                inline = tokens[i + 1]
                txt = "".join(c.content for c in inline.children or [] if c.type in ("text", "code_inline"))
                hid = slugify(inline.content, seen)
                t.attrSet("id", hid)
                lvl = int(t.tag[1])
                if lvl == 1 and not title:
                    title = txt
                heads.append((txt, hid, lvl))
        body = self.md.renderer.render(tokens, self.md.options, env)
        if drop_h1:
            body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.S)
        # anchors on h2/h3, GitHub alerts, mermaid left as code
        body = re.sub(r'<(h[23]) id="([^"]+)">(.*?)</\1>', r'<\1 id="\2">\3<a class="anchor" href="#\2" aria-label="Link to this section">#</a></\1>', body)
        body = re.sub(r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*",
                      lambda m: '<blockquote class="alert"><p class="alert-title">%s</p><p>' % m.group(1).title(), body)
        body = self.rewrite(body, src, page)
        return body, title, heads


# ----------------------------------------------------------------------------------------------- the shell

ICON_SUN = ('<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">'
            '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/></svg>'
            '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>')
ICON_MENU = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
ICON_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15l13-7.5z"/></svg>'
ICON_SOUND = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
              'aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11"/></svg>')
THEME_BOOT = ("<script>try{var t=localStorage.getItem('st-theme');if(t==='light'||t==='dark')"
              "document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>")


def site_url(repo: str) -> str:
    """The published site's address, ending in '/': config.json "site_url", else GitHub Pages for the repo
    (https://owner.github.io/name/), else '' (a local build keeps relative URLs)."""
    u = (CONFIG.get("site_url") or "").strip()
    if not u and repo and "/" in repo:
        owner, name = repo.split("/", 1)
        u = "https://%s.github.io/%s/" % (owner.lower(), name)
    return (u.rstrip("/") + "/") if u else ""


def shell(site: Site, page: str, title: str, body: str, active: str = "", desc: str = "") -> str:
    r = lambda p: rel(page, p)  # noqa: E731
    fav = site.copy_asset(REPO / "assets/brand/icon/favicon.svg")
    og = site.copy_asset(REPO / "assets/readme/social/launch-1280x640.jpg")
    touch = site.copy_asset(REPO / "assets/brand/icon/apple-touch-icon.png")
    nav = [("gallery.html", "Examples", "gallery"), ("crew.html", "Crew", "crew"), ("docs/index.html", "Docs", "docs")]
    links = "".join('<a href="%s"%s>%s</a>' % (r(h), ' aria-current="page"' if k == active else "", t) for h, t, k in nav)
    if site.repo:
        links += '<a href="https://github.com/%s">GitHub</a>' % esc(site.repo)
    full = title if title.startswith("showtime") else "%s \u00b7 showtime" % title
    d = desc or CONFIG.get("description", "")
    # link previews (Slack, X, iMessage ...) need absolute URLs: the published site's address + the page's path
    base = site_url(site.repo)
    og_abs = (base + og) if base else r(og)
    page_abs = (base + (page[:-len("index.html")] if page.endswith("index.html") else page)) if base else ""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{og_abs}">{og_url}
<meta property="og:image:width" content="1280">
<meta property="og:image:height" content="640">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{og_abs}">
<meta name="theme-color" content="#15100E" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#FBF6EE" media="(prefers-color-scheme: light)">
<link rel="icon" href="{fav}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{touch}">
<link rel="preload" href="{font}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{css}">
{boot}
</head>
<body data-root="{root}">
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
<a class="brand" href="{home}"><img src="{fav}" alt="" width="26" height="26"><span>showtime</span></a>
<nav class="nav" aria-label="Site">{links}</nav>
<button class="icon-btn theme-btn" type="button" aria-label="Switch theme">{sun}</button>
<button class="icon-btn menu-btn" type="button" aria-label="Menu" aria-expanded="false">{menu}</button>
</div></header>
<main id="main">
{body}
</main>
<footer class="site"><div class="wrap">
<span><span class="word">showtime</span>&nbsp; {version}, MIT licensed. A local video studio for Claude Code.</span>
<nav aria-label="Footer"><a href="{gallery}">Examples</a><a href="{crew}">Crew</a><a href="{docs}">Docs</a>{exrepo}</nav>
<span>No trackers, no cookies. Fonts are served from this site. Launch film music: \u201cWith These Hands\u201d by Scott Buckley, CC BY 4.0.</span>
</div></footer>
<script src="{js}"></script>
</body>
</html>
""".format(title=esc(full), desc=esc(d), og_abs=esc(og_abs),
           og_url=('\n<meta property="og:url" content="%s">' % esc(page_abs)) if page_abs else "", fav=r(fav), touch=r(touch), css=r("static/style.css"), boot=THEME_BOOT,
           root="../" * page.count("/"), home=r("index.html"), menu=ICON_MENU, links=links, sun=ICON_SUN, body=body,
           version=esc(CONFIG.get("version", "")), docs=r("docs/index.html"), gallery=r("gallery.html"), crew=r("crew.html"),
           js=r("static/app.js"), font=r("static/fonts/inter.woff2"),
           exrepo=('<a href="https://github.com/%s">%s</a>' % (esc(EXAMPLES_REPO), esc(EXAMPLES_REPO.split("/")[-1]))) if EXAMPLES_REPO else "")


def art(site: Site, page: str, name: str, alt: str, narrow: bool = True, max_width: str = "") -> str:
    """A theme-aware diagram from assets/readme (light/dark, wide/narrow)."""
    base = REPO / "assets" / "readme" / name
    wide_l = rel(page, site.copy_asset(Path(str(base) + "-light.svg")))
    site.copy_asset(Path(str(base) + "-dark.svg"))
    src = ""
    if narrow and Path(str(base) + "-narrow-light.svg").exists():
        nl = rel(page, site.copy_asset(Path(str(base) + "-narrow-light.svg")))
        site.copy_asset(Path(str(base) + "-narrow-dark.svg"))
        src = '<source media="(max-width: 700px)" srcset="%s" data-themed>' % nl
    style = ' style="max-width:%s"' % max_width if max_width else ""
    return '<picture class="art"%s>%s<img src="%s" alt="%s" data-themed loading="lazy"></picture>' % (style, src, wide_l, esc(alt))


# ----------------------------------------------------------------------------------------------- examples

def parse_examples() -> Tuple[List[Tuple[str, str]], List[dict]]:
    """Cards from examples/README.md (the single source of the gallery): groups, then examples."""
    txt = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    groups, exs, cur = [], {}, None
    order = []
    for block in re.split(r"(?=^## |<a id=\"ex-)", txt, flags=re.M):
        m = re.match(r"^## (.+)$", block, re.M)
        if block.startswith("## ") and m:
            name = m.group(1).strip()
            if name in ("Also here", "Rebuilding one", "About the previews"):
                cur = None
                continue
            cur = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            groups.append((cur, name))
            for n in re.findall(r'Also in this group: <a href="#ex-(\d\d)"', block):
                exs[n]["tags"].append(cur)
            continue
        m = re.match(r'<a id="ex-(\d\d)"></a>', block)
        if not m or not cur:
            continue
        n = m.group(1)
        folder = re.search(r'<a href="([^"/]+)/"><img', block).group(1)
        alt = html.unescape(re.search(r'<img src="[^"]+" width="100%" alt="([^"]*)"', block).group(1))
        meta = html.unescape(re.search(r"<sub>\d\d · (.+?)</sub><br>", block).group(1))
        title = html.unescape(re.search(r'<b><a href="[^"]+/">(.+?)</a></b>', block).group(1))
        prompt = html.unescape(re.search(r"<i>“(.*?)”</i>", block, re.S).group(1))
        what = html.unescape(re.search(r"WHAT IT SHOWS</sub><br>(.*?)</p>", block, re.S).group(1))
        line = re.search(r"<p>▶ (.*?)<br>", block, re.S).group(1)
        watch_part, _, html_part = line.partition("HTML video:")
        watch = re.findall(r'href="([^"]+)"', watch_part)
        hv = re.findall(r'href="([^"]+)"', html_part)
        tags = [cur]
        e = {"num": n, "folder": folder, "alt": alt, "meta": meta, "title": title, "prompt": prompt, "what": what,
             "watch": watch, "html": hv, "tags": tags}
        exs[n] = e
        order.append(n)
    for n in re.findall(r'Also in this group: <a href="#ex-(\d\d)"', txt):
        pass
    return groups, [exs[n] for n in sorted(order)]


RELEASE_LINK = re.compile(r"^(?:\{\{RELEASE_URL\}\}|https://github\.com/[^/]+/[^/]+/releases/download/[^/]+)/(.+)$")


def ex_path(ref: str) -> str:
    """Card link (relative to examples/, a release asset URL or {{RELEASE_URL}}/asset) -> repo path."""
    m = RELEASE_LINK.match(ref)
    if m and m.group(1) in PATH_BY_ASSET:
        return PATH_BY_ASSET[m.group(1)]
    return "examples/" + ref


def preview_assets(site: Site, page: str, e: dict) -> Tuple[str, Optional[str], Optional[str]]:
    """(still image, hover clip or None, full video or None) for an example, as URLs from `page`."""
    folder = e["folder"]
    main = ex_path(e["watch"][0]) if e["watch"] else None
    full, _ = site.media(main, folder) if main else (None, None)
    still, clip = site.preview(folder, main)
    if not still:
        still = site.copy_asset(REPO / "assets/readme/gallery/stills" / (folder + ".jpg"))
    if not clip:
        clip = site.copy_asset(REPO / "assets/readme/gallery" / (folder + ".webp"))
    return rel(page, still), rel(page, clip), (rel(page, full) if full else None)


def card(site: Site, page: str, e: dict, show_what: bool = True) -> str:
    folder = e["folder"]
    still, clip, full = preview_assets(site, page, e)
    story = rel(page, "examples/%s.html" % folder)
    clip_attr = ' data-clip="%s"' % clip
    if full:
        action = ('<button class="open" type="button" data-full="%s" aria-label="Play %s with sound"></button>'
                  '<span class="hint" aria-hidden="true">%s Play with sound</span>' % (full, esc(e["title"]), ICON_PLAY))
    else:
        action = ('<a class="open" href="%s" aria-label="%s: the story and the video"></a>'
                  '<span class="hint" aria-hidden="true">Open the example</span>' % (story, esc(e["title"])))
    links = ['<a href="%s">The story and commands</a>' % story]
    if not full:
        _, fb = site.media(ex_path(e["watch"][0]), folder) if e["watch"] else (None, None)
        if fb:
            links.append('<a href="%s">Watch the MP4</a>' % esc(fb))
    for h in e["html"]:
        hl, _ = site.media(ex_path(h), folder)
        if hl:
            links.append('<a href="%s">HTML video</a>' % rel(page, hl))
            break
    spec = e["meta"].split(" · ")[0]
    return ('<article class="film" data-tags="%s"><div class="frame"%s><img class="still" src="%s" alt="%s" loading="lazy" decoding="async">%s</div>'
            '<div class="meta"><h3><a href="%s">%s</a></h3><span class="spec">%s</span></div>'
            '<p class="ask">\u201c%s\u201d</p>%s<div class="links">%s</div></article>'
            % (" ".join(e["tags"]), clip_attr, still, esc(e["alt"]), action, story, esc(e["title"]), esc(spec), esc(e["prompt"]),
               ('<p class="shows">%s</p>' % esc(e["what"])) if show_what else "", "".join(links)))


def build_gallery(site: Site, groups, exs) -> None:
    page = "gallery.html"
    tabs = ['<button class="tab" type="button" data-filter="all" aria-pressed="true">All<span class="c">%d</span></button>' % len(exs)]
    for g, name in groups:
        n = sum(1 for e in exs if g in e["tags"])
        tabs.append('<button class="tab" type="button" data-filter="%s" aria-pressed="false">%s<span class="c">%d</span></button>' % (g, esc(name), n))
    cards = "".join(card(site, page, e) for e in exs)
    htmls, live = [], ""
    for e in exs:
        for h in e["html"]:
            hl, _ = site.media(ex_path(h), e["folder"])
            if hl:
                htmls.append('<li><a href="%s">%s</a><span>%s</span></li>' % (rel(page, hl), esc(e["title"]), esc(h.split("/")[-1])))
                if e["num"] == "02" and not live:
                    live = ('<div class="htmlvid"><iframe src="%s" title="HTML video: %s" loading="lazy" allow="fullscreen"></iframe></div>'
                            % (rel(page, hl), esc(e["title"])))
    body = """<div class="wrap">
<header class="room-head"><h1 class="title">Now showing</h1>
<p class="lede">Twenty-two videos, each made from a single request by an agent acting as a user. Hover to preview, press play for
the full video with sound, or open the story behind it.</p>{exrepo}
<div class="filters" role="group" aria-label="Filter by use case">{tabs}</div>
<p class="count" aria-live="polite"></p></header>
<div class="films">{cards}</div>
<section class="interactive" aria-labelledby="html-videos">
<div class="section-head"><h2 class="title" id="html-videos">Videos that are web pages</h2>
<p class="lede">Every project also exports as one HTML file that plays offline: the same frames as the MP4, chapters, keyboard
control and links to a moment. This one is live; click it and press <kbd>?</kbd>.</p></div>
{live}
<ul class="htmllist">{htmls}</ul>
</section>
</div>""".format(tabs="".join(tabs), cards=cards, live=live, exrepo=(
        '\n<p class="lede">All 22 examples, with their projects and full-quality videos, live in <a href="https://github.com/%s">%s</a>.</p>'
        % (esc(EXAMPLES_REPO), esc(EXAMPLES_REPO.split("/")[-1]))) if EXAMPLES_REPO else "",
                  htmls="".join(htmls) or "<li class='muted'>Not included in this build.</li>")
    write(site, page, shell(site, page, "Examples", body, "gallery", "Twenty-two videos made with showtime, from one sentence each."))


def build_example_pages(site: Site, exs) -> None:
    for e in exs:
        folder = e["folder"]
        page = "examples/%s.html" % folder
        src = EXAMPLES / folder / "README.md"
        text = src.read_text(encoding="utf-8")
        body_html, title, heads = site.render_md(text, src, page, drop_h1=True)
        players = []
        for w in e["watch"]:
            p = ex_path(w)
            local, fb = site.media(p, folder)
            name = p.split("/")[-1]
            if local:
                poster = EXAMPLES / folder / ("poster.jpg" if "9x16" not in name else "poster-9x16.jpg")
                pa = ' poster="%s"' % rel(page, site.copy_asset(poster)) if poster.is_file() else ""
                vtt = ""
                players.append('<figure><video controls playsinline preload="metadata"%s src="%s" aria-label="%s, %s"></video>'
                               '<figcaption>%s</figcaption></figure>'
                               % (pa, rel(page, local), esc(e["title"]), esc(name), esc(name)))
            elif fb:
                still, _, _ = preview_assets(site, page, e)
                players.append('<figure><a class="frame" href="%s"><img class="still" src="%s" alt="%s"><span class="hint" style="opacity:1;transform:none">'
                               '%s Watch %s</span></a><figcaption>A release asset, not included in this build.</figcaption></figure>'
                               % (esc(fb), still, esc(e["alt"]), ICON_PLAY, esc(name)))
            else:
                players.append('<p class="note"><code>%s</code> is a release asset and is not included in this build.</p>' % esc(name))
        embeds = []
        for h in e["html"]:
            hl, hfb = site.media(ex_path(h), folder)
            name = h.split("/")[-1]
            if hl:
                embeds.append('<h2 id="html-video" style="margin-top:0">The HTML video</h2><p><code>%s</code> is the single-file export, '
                              'playing right here. Click it, then press <kbd>?</kbd> for the keys, or <a href="%s">open it on its own</a>.</p>'
                              '<div class="htmlvid"><iframe src="%s" title="HTML video: %s" loading="lazy" allow="fullscreen"></iframe></div>'
                              % (esc(name), rel(page, hl), rel(page, hl), esc(e["title"])))
                break
        head = ('<div class="wrap"><div class="ex-head"><div class="crumbs"><a href="%s">Examples</a> / %s</div>'
                '<p class="spec">%s</p><h1 class="title">%s</h1><p class="ask">\u201c%s\u201d</p></div>'
                '<div class="players">%s</div></div>'
                % (rel(page, "gallery.html"), esc(e["num"]), esc(e["meta"]), esc(e["title"]), esc(e["prompt"]), "".join(players)))
        more = ""
        if site.repo:
            more = '<p class="edit"><a href="%s">The project files on GitHub</a></p>' % esc(site.gh("examples/" + folder, True))
        body = head + '<div class="wrap"><article class="prose" style="max-width:var(--read);margin:64px auto 120px">%s%s%s</article></div>' % (
            "".join(embeds), body_html, more)
        write(site, page, shell(site, page, e["title"], body, "gallery", e["what"]))
        site.search.append({"t": "Example %s: %s" % (e["num"], e["title"]), "u": page, "h": [h[0] for h in heads if h[2] >= 2],
                            "a": [h[1] for h in heads if h[2] >= 2], "x": plain(e["prompt"] + " " + e["what"] + " " + text)[:6000]})


# ----------------------------------------------------------------------------------------------- docs

def doc_sources() -> List[Tuple[Path, str, str]]:
    """(source, output page, sidebar group) for every doc page."""
    out = []
    for p in sorted(REFS.glob("*.md")):
        out.append((p, "docs/%s.html" % p.stem, ""))
    for p in sorted((REFS / "workflows").glob("*.md")):
        out.append((p, "docs/workflows/%s.html" % p.stem, "workflows"))
    for p in sorted((REFS / "crew").glob("*.md")):
        out.append((p, "docs/crew/%s.html" % p.stem, "crew"))
    extra = [(REPO / "CONTEXT.md", "docs/glossary.html"), (REPO / ".out-of-scope/README.md", "docs/out-of-scope.html"),
             (REPO / "skills/showtime/SKILL.md", "docs/skill.html"), (REPO / "assets/brand/BRAND.md", "docs/brand.html"),
             (REPO / "CONTRIBUTING.md", "docs/contributing.html"), (REPO / "CHANGELOG.md", "docs/changelog.html")]
    for p, o in extra:
        if p.is_file():
            out.append((p, o, "backstage"))
    return out


WORDS = {"api": "API", "mcp": "MCP", "qa": "QA", "html": "HTML", "vo": "VO"}


def human(slug: str) -> str:
    words = slug.replace("_", "-").split("-")
    out = [WORDS.get(w, w) for w in words]
    out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


def sidebar_groups(site: Site) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """Groups in the docs map's running order (docs/README.md), then the crew briefs and backstage pages."""
    txt = (REPO / "docs" / "README.md").read_text(encoding="utf-8")
    groups, cur = [], None
    for line in txt.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            name = m.group(1).strip()
            cur = None if name == "Backstage" else [name, []]
            if cur:
                groups.append(cur)
            continue
        if cur is None:
            continue
        for mm in re.finditer(r'(?:\]\(|href=")\.\./skills/showtime/references/([a-z/-]+)\.md', line):
            src = (REFS / (mm.group(1) + ".md")).resolve()
            if src in site.pages:
                label = human(mm.group(1).split("/")[-1])
                if (label, site.pages[src]) not in cur[1]:
                    cur[1].append((label, site.pages[src]))
    groups = [g for g in groups if g[1]]
    crew = [(human(p.stem), site.pages[p.resolve()]) for p in sorted((REFS / "crew").glob("*.md"))]
    groups.append(["The crew's briefs", crew])
    back = [("Glossary", "docs/glossary.html"), ("Out of scope", "docs/out-of-scope.html"), ("SKILL.md", "docs/skill.html"),
            ("Brand", "docs/brand.html"), ("Contributing", "docs/contributing.html"), ("Changelog", "docs/changelog.html"),
            ("Claude's own map", "docs/index-claude.html")]
    groups.append(["Backstage", [b for b in back if (site.out / b[1]).exists() or b[1] in site.pages.values()]])
    return [(g[0], g[1]) for g in groups]


def plain(md_text: str) -> str:
    t = re.sub(r"```.*?```", " ", md_text, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[`*_>|#-]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def docs_frame(site: Site, page: str, groups, content: str, heads, prev_next) -> str:
    side = ['<aside class="side" aria-label="Documentation"><div class="search" role="search"><label class="sr" for="q">Search the docs</label>',
            ICON_SEARCH, '<input id="q" type="search" placeholder="Search the docs" autocomplete="off"><span class="key" aria-hidden="true">/</span>',
            '<div class="results" hidden></div></div>',
            '<button class="side-toggle" type="button" aria-expanded="false"><span>Browse the guides</span><span aria-hidden="true">+</span></button>',
            '<div class="groups"><h4>Start</h4><ul><li><a href="%s"%s>The map</a></li></ul>' % (
                rel(page, "docs/index.html"), ' aria-current="page"' if page == "docs/index.html" else "")]
    for name, items in groups:
        side.append("<h4>%s</h4><ul>" % esc(name))
        for label, target in items:
            side.append('<li><a href="%s"%s>%s</a></li>' % (rel(page, target), ' aria-current="page"' if target == page else "", esc(label)))
        side.append("</ul>")
    side.append("</div></aside>")
    toc = [h for h in heads if h[2] == 2]
    toc_html = ""
    if len(toc) > 1:
        toc_html = '<nav class="toc" aria-label="On this page"><h4>On this page</h4>%s</nav>' % "".join(
            '<a href="#%s">%s</a>' % (h[1], esc(h[0])) for h in toc)
    pager = ""
    if prev_next:
        (pv, nx) = prev_next
        pager = '<nav class="pager" aria-label="Previous and next">%s%s</nav>' % (
            '<a href="%s"><small>Previous</small>%s</a>' % (rel(page, pv[1]), esc(pv[0])) if pv else "<span></span>",
            '<a class="next" href="%s"><small>Next</small>%s</a>' % (rel(page, nx[1]), esc(nx[0])) if nx else "")
    return '<div class="docs">%s<article class="prose">%s%s</article>%s</div>' % ("".join(side), content, pager, toc_html)


def build_docs(site: Site) -> None:
    sources = doc_sources()
    for src, page, _g in sources:
        site.pages[src.resolve()] = page
    site.pages[(REFS / "index.md").resolve()] = "docs/index-claude.html"
    site.pages[(REPO / "docs" / "README.md").resolve()] = "docs/index.html"
    site.pages[(REPO / "README.md").resolve()] = "index.html"
    site.pages[(EXAMPLES / "README.md").resolve()] = "gallery.html"
    for d in sorted(EXAMPLES.glob("[0-9][0-9]-*/README.md")):
        site.pages[d.resolve()] = "examples/%s.html" % d.parent.name
    groups = sidebar_groups(site)
    flat = [it for _, items in groups for it in items]
    rendered = []
    for src, page, _g in sources + [(REFS / "index.md", "docs/index-claude.html", "")]:
        if page == "docs/index-claude.html" and not src.is_file():
            continue
        text = src.read_text(encoding="utf-8")
        body, title, heads = site.render_md(text, src, page)
        title = title or src.stem
        repo_rel = src.resolve().relative_to(REPO).as_posix()
        crumbs = '<div class="crumbs"><a href="%s">Docs</a> / <code>%s</code></div>' % (rel(page, "docs/index.html"), esc(repo_rel))
        edit = ('<p class="edit"><a href="%s">View or edit this page on GitHub</a></p>' % esc(site.gh(repo_rel))) if site.repo else ""
        idx = next((i for i, it in enumerate(flat) if it[1] == page), None)
        pn = (flat[idx - 1] if idx else None, flat[idx + 1] if idx is not None and idx + 1 < len(flat) else None) if idx is not None else None
        html_page = docs_frame(site, page, groups, crumbs + body + edit, heads, pn)
        write(site, page, shell(site, page, title, html_page, "docs", first_line(text)))
        site.search.append({"t": title, "u": page, "h": [h[0] for h in heads if h[2] >= 2], "a": [h[1] for h in heads if h[2] >= 2],
                            "x": plain(text)[:14000]})
        rendered.append(page)
    # the map itself
    src = REPO / "docs" / "README.md"
    text = re.sub(r'^<p align="center">\s*<picture>.*?</picture>\s*</p>\s*', "", src.read_text(encoding="utf-8"), count=1, flags=re.S)
    body, title, heads = site.render_md(text, src, "docs/index.html")
    write(site, "docs/index.html", shell(site, "docs/index.html", "Documentation",
                                         docs_frame(site, "docs/index.html", groups, body, heads, None), "docs",
                                         "Every showtime guide, in running order."))
    site.search.append({"t": "Documentation map", "u": "docs/index.html", "h": [h[0] for h in heads if h[2] >= 2],
                        "a": [h[1] for h in heads if h[2] >= 2], "x": plain(src.read_text(encoding="utf-8"))[:6000]})


def first_line(md_text: str) -> str:
    for line in md_text.splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "<", "!", "|", ">", "-")):
            return plain(s)[:180]
    return ""


# ----------------------------------------------------------------------------------------------- crew page

def frontmatter(p: Path) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def build_crew(site: Site) -> None:
    page = "crew.html"
    roles = json.loads((SITE / "content" / "crew.json").read_text(encoding="utf-8"))["roles"]
    cards = []
    for r in roles:
        brief = REFS / "crew" / (r["id"] + ".md")
        fm = frontmatter(REPO / "agents" / (r["id"] + ".md"))
        job = ""
        if brief.is_file():
            m = re.search(r"^\*\*Your job[^\n]*(?:\n(?!\n)[^\n]*)*", brief.read_text(encoding="utf-8"), re.M)
            if m:
                job = site.md.renderInline(m.group(0).replace("\n", " "))
                job = site.rewrite(job, brief, page)
        model = fm.get("model", "")
        model = "your session's model" if model == "inherit" else "the %s model" % model.title()
        cards.append('<article class="role" id="%s"><h3>%s</h3><p class="when">%s, runs on %s</p><p class="one">%s</p>'
                     '<p class="job">%s</p><p class="call"><code>@agent-showtime:%s</code><a href="%s">The brief</a></p></article>'
                     % (esc(r["id"]), esc(r["name"]), esc(r["when"]), esc(model), esc(r["line"]), job, esc(r["id"]),
                        rel(page, site.pages.get(brief.resolve(), "docs/crew.html"))))
    body = """<div class="wrap">
<header class="room-head"><h1 class="title">Ten specialists, one director</h1>
<p class="lede">Claude directs every video. For studio work and videos you will publish, it can hand parts of the job to ten
sub-agents that ship with the plugin. They are optional: a quick video uses none of them, except a researcher and a critic when
it will be published, and scene builders for long videos.</p></header>
<div style="margin-top:48px">{cast}</div>
<section class="section" style="padding-bottom:0"><div class="section-head"><h2 class="title">Who hands what to whom</h2>
<p class="lede">Every brief and every result goes through the director. Members never talk to each other or to you, and fixes go
back to the member who made the part.</p></div>{handoff}</section>
<section class="section" style="padding-bottom:0"><div class="section-head"><h2 class="title">What each one does</h2>
<p class="lede">Each member reads its brief, works only in its own folder, never uploads, and reports back with a short status.</p></div>
<div class="roster">{cards}</div></section>
<section class="section"><div class="split" style="margin-top:0"><div><h2 class="title" style="font-size:clamp(1.9rem,3.4vw,2.75rem)">Casting</h2>
<p style="margin-top:16px">Let Claude cast the company: ask for options first and studio mode brings it in. Call one member by name
when you want just that job done. Or say "no crew" and Claude does everything in one session.</p>
<p><a class="link-arrow" href="{guide}">When each member is dispatched, and what it costs <span>→</span></a></p></div>
<div class="copy install"><pre><code># the whole company, in studio mode
Let's make a launch trailer for this repo. Show me options first.

# one member, by name
@agent-showtime:researcher check the claims in narration.md

# no crew at all
Make it quick, no crew.</code></pre></div></div></section>
</div>
""".format(cast=art(site, page, "crew/cast", "The crew as a cast of ten illustrated cards: " + "; ".join("%s: %s" % (r["name"], r["line"]) for r in roles)),
           handoff=art(site, page, "diagrams/crew-handoff", "How the crew hands work around: pitch, plan, build, review, deliver, all through the director."),
           cards="".join(cards), guide=rel(page, "docs/crew.html"))
    write(site, page, shell(site, page, "The crew", body, "crew", "Ten optional specialist sub-agents, one director."))


# ----------------------------------------------------------------------------------------------- landing

def build_landing(site: Site, exs) -> None:
    page = "index.html"
    hero_cfg = CONFIG.get("hero") or {}
    launch = hero_cfg.get("folder", "examples/_launch")
    poster = rel(page, site.copy_asset(REPO / "assets/readme/launch-poster-plain.jpg"))
    tmp4 = rel(page, site.copy_asset(src_path(launch + "/teaser-16x9.mp4")))
    twebm = rel(page, site.copy_asset(src_path(launch + "/teaser-16x9.webm")))
    film, film_fb = site.media(launch + "/" + hero_cfg.get("film", "launch-16x9.mp4"), "_launch")
    if film:
        watch = ('<button class="watch" type="button" data-film="%s" data-poster="%s">%s<span>Watch the film</span><em>0:40, sound on</em></button>'
                 % (rel(page, film), poster, ICON_PLAY))
    else:
        watch = ('<a class="watch" href="%s">%s<span>Watch the film</span><em>0:40, sound on</em></a>' % (esc(film_fb or "#"), ICON_PLAY))
    hero = ('<div class="screen lights"><video class="teaser" muted loop playsinline preload="auto" poster="%s" aria-hidden="true">'
            '<source src="%s" type="video/webm"><source src="%s" type="video/mp4"></video>%s</div>' % (poster, twebm, tmp4, watch))
    teaser = [e for e in exs if e["num"] in ("02", "12", "17", "19")]
    body = """<section class="house"><div class="wrap">
<div class="hero-head"><div><h1 class="title">Describe a video. Claude directs. Your machine renders.</h1>
<p class="lede">showtime is a local video studio for Claude Code: motion graphics, voice-over, music, captions and footage editing
from one sentence, with no cloud AI services, no API keys and no uploads.</p></div>
<div class="actions"><a class="btn primary" href="#start">Get started</a><a class="link-arrow" href="gallery.html">See the examples <span>→</span></a></div></div>
{hero}
<p class="credit">The launch film: every frame is from a real showtime example. Music: \u201cWith These Hands\u201d by Scott Buckley,
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>
</div></section>

<section class="section" id="start"><div class="wrap">
<div class="section-head"><h2 class="title">One sentence in, a finished video out</h2>
<p class="lede">Claude states its assumptions, shows you a first look, renders on your machine and checks the result before it
calls the video done.</p></div>
{pipeline}
<div class="split"><div><h3>Install it in Claude Code</h3>
<p>You need <a href="https://docs.astral.sh/uv/">uv</a> and <a href="https://nodejs.org">Node.js</a> 24 or 22 LTS (20 or newer works).
The first request checks what is missing and tells you the size and time, about 2.9 GB into <code>~/.showtime</code> and 3 to 11
minutes, then runs setup once you say yes.</p>
<p>Every request gets its own folder with <code>final.mp4</code>, a poster, captions, exports and share copy. Nothing is overwritten.</p></div>
<div class="copy install"><pre><code>/plugin marketplace add {market}
/plugin install showtime@showtime

Make a 20-second launch video for this repo, with a voice-over and upbeat music.</code></pre></div></div>
</div></section>

<section class="section"><div class="wrap">
<div class="section-head"><h2 class="title">Now showing</h2>
<p class="lede">Each of these came from one request. Hover to preview; play for sound.</p></div>
<div class="films">{teaser}</div>
<p class="more"><a class="link-arrow" href="gallery.html">All 22 examples <span>→</span></a></p>
</div></section>

<section class="section"><div class="wrap">
<div class="section-head"><h2 class="title">A crew, when you want one</h2>
<p class="lede">For studio work and videos you will publish, Claude can cast ten specialist sub-agents. Quick videos stay lean.</p></div>
{cast}
<p class="more"><a class="link-arrow" href="crew.html">Meet the crew <span>→</span></a></p>
</div></section>

<section class="section"><div class="wrap">
<div class="section-head"><h2 class="title">Everything renders on your machine</h2>
<p class="lede">showtime adds no cloud service of its own. Every model and tool is downloaded once; after that it goes online only
when you ask for something from the web.</p></div>
{runs}
<div class="facts"><div><h3>Every shape</h3><p>16:9, 1:1 and 9:16, with platform exports, posters, captions and README loops.</p></div>
<div><h3>Videos that are web pages</h3><p>One HTML file per video, with chapters and keyboard control, playing offline. <a href="gallery.html#html-videos">See one live</a>.</p></div>
<div><h3>Checked before it is done</h3><p><code>showtime qa</code> checks loudness, black or frozen frames, captions and platform specs.</p></div></div>
<p class="more"><a class="link-arrow" href="docs/index.html">Read the docs <span>→</span></a></p>
</div></section>
""".format(hero=hero, market=esc(site.repo or CONFIG.get("marketplace", "FavioVazquez/showtime")),
           pipeline=art(site, page, "diagrams/pipeline", "How showtime works: one sentence, Claude directs, a first look, a local render, showtime qa, an MP4 and an HTML video."),
           teaser="".join(card(site, page, e, show_what=False) for e in teaser),
           runs=art(site, page, "diagrams/runs-where", "What runs where: the director in your Claude Code session, the studio on your machine; the web only when you ask."),
           cast=art(site, page, "crew/cast", "The crew: ten illustrated cards, all optional."))
    write(site, page, shell(site, page, "showtime · a local video studio for Claude Code", body, "home"))


# ----------------------------------------------------------------------------------------------- main

def write(site: Site, page: str, text: str) -> None:
    p = site.out / page
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(SITE / "_site"), help="output folder (default site/_site)")
    ap.add_argument("--examples", default="", metavar="DIR",
                    help="the examples folder (default: examples/ here, else %s from site/config.json)" % CONFIG.get("examples_dir", "-"))
    ap.add_argument("--examples-repo", default="", metavar="OWNER/NAME",
                    help="the examples repository, for its links and media release (default: site/config.json examples_repo)")
    ap.add_argument("--media-from", action="append", default=[], metavar="DIR",
                    help="where to find example videos: a checkout's examples/ folder or a folder of release assets (repeatable; "
                         "the examples folder itself is always searched last)")
    ap.add_argument("--repo", default="", help="owner/name on GitHub, for source and release links (default: $GITHUB_REPOSITORY, "
                                               "then site/config.json)")
    ap.add_argument("--only", default="", help="comma list of example numbers whose MP4s are copied (a small preview build)")
    ap.add_argument("--max-html-mb", type=float, default=0.0, help="skip HTML videos bigger than this (default: copy them all)")
    ap.add_argument("--clean", action="store_true", help="empty the output folder first")
    ap.add_argument("--no-previews", action="store_true", help="skip the 4 s hover clips (the gallery uses the README loops)")
    a = ap.parse_args()
    configure_examples(find_examples(a.examples), a.examples_repo)
    repo = a.repo or os.environ.get("GITHUB_REPOSITORY", "") or CONFIG.get("repo", "")
    out = Path(a.out).resolve()
    if a.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    only = set(x.strip().zfill(2) for x in a.only.split(",") if x.strip()) or None
    site = Site(out, [Path(d).resolve() for d in a.media_from], repo, only, CONFIG.get("branch", "main"), a.max_html_mb)
    if a.no_previews:
        global FFMPEG
        FFMPEG = None
    shutil.copytree(SITE / "static", out / "static", dirs_exist_ok=True)
    (out / ".nojekyll").write_text("")
    groups, exs = parse_examples()
    build_docs(site)
    build_gallery(site, groups, exs)
    build_example_pages(site, exs)
    build_crew(site)
    build_landing(site, exs)
    (out / "search-index.js").write_text("window.SHOWTIME_SEARCH=" + json.dumps(site.search, ensure_ascii=False, separators=(",", ":")) + ";\n",
                                         encoding="utf-8")
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    nfiles = sum(1 for f in out.rglob("*") if f.is_file())
    print("site: %s  (%d files, %.1f MB)" % (out, nfiles, total / 1e6))
    print("examples: %s%s" % (EXAMPLES, (" (links: %s)" % EXAMPLES_REPO) if EXAMPLES_REPO else ""))
    print("repo: %s" % (repo or "(none: source links are plain text; set site/config.json \"repo\" or pass --repo)"))
    if site.missing_media:
        uniq = sorted(set(site.missing_media))
        print("videos not found in --media-from (their cards link to the release instead): %d" % len(uniq))
        for m in uniq[:40]:
            print("  " + m)


if __name__ == "__main__":
    main()
