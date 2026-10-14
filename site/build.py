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
import posixpath
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
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
GUIDES = REPO / "docs" / "guides"   # task guides for people (the sidebar's first group)
CONFIG = json.loads((SITE / "config.json").read_text(encoding="utf-8"))
# The examples folder and its media manifest: set by configure_examples() (main). Pages keep calling example
# files by their path in the examples repository, "examples/<folder>/...", wherever the checkout is.
EXAMPLES = REPO / "examples"
EXAMPLES_REPO = ""   # owner/name of the examples repository when the examples are not in this checkout
MEDIA: dict = {"release": {}, "files": []}
ASSET_BY_PATH: Dict[str, str] = {}
PATH_BY_ASSET: Dict[str, str] = {}
IMG_EXT = {".svg", ".webp", ".png", ".jpg", ".jpeg", ".gif"}

def repo_version() -> str:
    """The release the site documents: st.__version__, the same number scripts/check_release.py syncs everywhere
    (the footer, llms.txt and the landing's "New in" read it, so a release bump updates them). Falls back to
    config.json "version" in a copy without the library."""
    try:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', (REPO / "skills/showtime/lib/st/__init__.py").read_text(encoding="utf-8"))
    except OSError:
        m = None
    return m.group(1) if m else str(CONFIG.get("version", ""))


VERSION = repo_version()
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def strip_front_matter(text: str) -> str:
    """Markdown without its YAML front matter (SKILL.md has some): rendered as-is, the closing --- turns the front
    matter into one huge setext heading."""
    return FRONT_MATTER.sub("", text, count=1)


PREVIEWS = json.loads((SITE / "content" / "previews.json").read_text(encoding="utf-8"))["previews"]
# the gallery's shelves and their order, the "New in 0.4" set and the docs' "See it done" lines (the cards themselves
# come from examples/README.md, which lives in the examples repository)
GALLERY = json.loads((SITE / "content" / "gallery.json").read_text(encoding="utf-8"))


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


# ----------------------------------------------------------------------------------------------- raw HTML in Markdown

# The HTML tags the rendered Markdown uses on purpose: the README-style layout (centred paragraphs, theme-aware
# pictures, the example tables, the docs map's install block), small print, keys and folding sections. Any other tag in the text, such as a
# "<title>", "<project>" or "<url>" placeholder, is shown as text: passed through as HTML, <title> starts an element
# that swallows the rest of the page and an unknown tag vanishes. Comments pass through. Code spans and code blocks
# are always escaped.
HTML_TAGS = frozenset(
    "a b br code details div em h3 i img kbd p picture pre source span strong sub summary sup table tbody td th thead tr"
    .split())
TAG_START = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")


def tag_allowed(src: str, pos: int) -> bool:
    """True when the text at pos is not a tag (a comment, say) or is a tag on the allowlist."""
    m = TAG_START.match(src, pos)
    return not m or m.group(2).lower() in HTML_TAGS


def escape_tags(raw: str) -> str:
    """Raw HTML with every tag that is not on the allowlist turned into text."""
    return TAG_START.sub(lambda m: m.group(0) if m.group(2).lower() in HTML_TAGS else "&lt;" + m.group(0)[1:], raw)


def markdown() -> MarkdownIt:
    """The site's Markdown: CommonMark with tables, strikethrough and raw HTML limited to HTML_TAGS. A block or
    inline tag that is not on the list is not HTML to the parser, so it renders as text (escaped); inside an
    allowed HTML block such tags are escaped in place."""
    md = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")

    def guard(ruler, name: str, pos_of) -> None:
        rule = ruler.__rules__[ruler.__find__(name)]
        orig = rule.fn

        def fn(state, *args):
            src, pos = pos_of(state, *args)
            return orig(state, *args) if tag_allowed(src, pos) else False
        ruler.at(name, fn, {"alt": list(rule.alt)})

    guard(md.block.ruler, "html_block", lambda st, line, *_: (st.src, st.bMarks[line] + st.tShift[line]))
    guard(md.inline.ruler, "html_inline", lambda st, *_: (st.src, st.pos))

    def escape_blocks(state) -> None:
        for t in state.tokens:
            if t.type == "html_block":
                t.content = escape_tags(t.content)
    md.core.ruler.push("escape_html_blocks", escape_blocks)
    return md


def md_h2_count(md_text: str) -> int:
    """The h2 headings of a Markdown source, counted with raw HTML off (so it does not depend on HTML_TAGS)."""
    toks = MarkdownIt("commonmark").enable("table").parse(md_text)
    return sum(1 for t in toks if t.type == "heading_open" and t.tag == "h2")


class _PageScan(HTMLParser):
    """Counts <title>, <footer> and <h2> the way a browser sees them: the text of title, textarea, xmp, iframe,
    noembed and noframes is not markup, so a stray opening tag swallows the rest of the page."""
    CDATA_CONTENT_ELEMENTS = ("script", "style", "title", "textarea", "xmp", "iframe", "noembed", "noframes")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.counts = {"title": 0, "footer": 0, "h2": 0}
        self.foreign = 0          # inside inline <svg> or <math>, where <title> is an accessible name, not the page's

    def handle_starttag(self, tag, attrs) -> None:
        if tag in ("svg", "math"):
            self.foreign += 1
        elif tag in self.counts and not (tag == "title" and self.foreign):
            self.counts[tag] += 1

    def handle_endtag(self, tag) -> None:
        if tag in ("svg", "math") and self.foreign:
            self.foreign -= 1


def check_pages(out: Path, pages: List[str], h2_expect: Dict[str, Tuple[str, int]]) -> List[str]:
    """Problems in the written pages, one line each naming the page and the cause: not exactly one <title>, no
    <footer>, or (for a page rendered from one Markdown source) an h2 count that differs from the source's."""
    problems = []
    for page in pages:
        scan = _PageScan()
        scan.feed((out / page).read_text(encoding="utf-8"))
        scan.close()
        c = scan.counts
        if c["title"] != 1:
            problems.append("%s: %d <title> elements, expected 1 (a raw <title> in the text swallows the rest of the "
                            "page; write it in backticks or add the tag to HTML_TAGS if it is meant as HTML)" % (page, c["title"]))
        if not c["footer"]:
            problems.append("%s: no <footer>: the page is cut off (look for a raw tag such as <title>, <textarea> or "
                            "<iframe> in its source)" % page)
        if page in h2_expect:
            src, want = h2_expect[page]
            if c["h2"] != want:
                problems.append("%s: %d h2 headings, %s has %d: part of the page is missing or a heading is hidden "
                                "in raw HTML" % (page, c["h2"], src, want))
    return problems


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
        self.written: List[str] = []                       # every page write() wrote, for the build check
        self.h2_expect: Dict[str, Tuple[str, int]] = {}   # page rendered from one source -> (source, its h2 count)
        self.described: Dict[str, Tuple[str, str]] = {}  # page -> (title, description), for llms.txt
        self.doc_groups: List[Tuple[str, List[Tuple[str, str]]]] = []   # the docs sidebar, for llms.txt
        self.gallery: Optional[set] = None   # folders of the gallery's examples (the pages built); None: every NN-*
        self.md = markdown()

    # -------------------------------------------------------------------------------- files and media
    def gh(self, repo_rel: str, is_dir: bool = False) -> Optional[str]:
        repo = self.repo
        if EXAMPLES_REPO and (repo_rel == "examples" or repo_rel.startswith("examples/")):
            repo = EXAMPLES_REPO
        if not repo:
            return None
        return "https://github.com/%s/%s/%s/%s" % (repo, "tree" if is_dir else "blob", self.branch, repo_rel)

    def release_url(self, asset: str) -> Optional[str]:
        """The media release lives in the examples repository: the one the examples come from, else the one
        MEDIA.json names (its release.repo), else this one."""
        repo = EXAMPLES_REPO or MEDIA["release"].get("repo") or self.repo
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
        if self.only is not None and folder[:2] not in self.only and not is_html and not folder.startswith("_"):
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
            if is_html and src.name == "index.html" and (src.parent / "assets" / "vfs.js").is_file():
                # a folder export (export html --folder): index.html loads assets/ beside it, so copy the folder
                shutil.copytree(str(src.parent), str(p.parent), dirs_exist_ok=True)
            else:
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
            return self.gh(r, is_dir=True)   # an example with no page here (not in the gallery, or examples/_x)
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


def page_url(base: str, page: str) -> str:
    """A page's published address (a folder's index.html is the folder itself); '' without a base."""
    if not base:
        return ""
    return base + (page[:-len("index.html")] if page == "index.html" or page.endswith("/index.html") else page)


def shell(site: Site, page: str, title: str, body: str, active: str = "", desc: str = "", og_title: str = "",
          og_image: Optional[Path] = None, og_size: Tuple[int, int] = (1280, 640), head: str = "") -> str:
    """A site page: header, body, footer. og_title (also the <title>), og_image and og_size override the link preview;
    head is extra markup for <head> (a page's own stylesheet)."""
    r = lambda p: rel(page, p)  # noqa: E731
    fav = site.copy_asset(REPO / "assets/brand/icon/favicon.svg")
    og = site.copy_asset(og_image or REPO / "assets/brand/social/github-social-preview.png")
    touch = site.copy_asset(REPO / "assets/brand/icon/apple-touch-icon.png")
    nav = [("gallery.html", "Examples", "gallery"), (XRAY_PAGE, "X-ray", "xray"), ("crew.html", "Crew", "crew"),
           ("docs/index.html", "Docs", "docs")]
    links = "".join('<a href="%s"%s>%s</a>' % (r(h), ' aria-current="page"' if k == active else "", t) for h, t, k in nav)
    if site.repo:
        links += '<a href="https://github.com/%s">GitHub</a>' % esc(site.repo)
    full = og_title or (title if title.startswith("showtime") else "%s \u00b7 showtime" % title)
    d = desc or CONFIG.get("description", "")
    # link previews (Slack, X, iMessage ...) need absolute URLs: the published site's address + the page's path
    base = site_url(site.repo)
    og_abs = (base + og) if base else r(og)
    page_abs = page_url(base, page)
    site.described[page] = (title, d)
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
<meta property="og:image:width" content="{og_w}">
<meta property="og:image:height" content="{og_h}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{og_abs}">
<meta name="theme-color" content="#15100E" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#FBF6EE" media="(prefers-color-scheme: light)">
<link rel="icon" href="{fav}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{touch}">
<link rel="preload" href="{font}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{css}">{head}
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
<span><span class="word">showtime</span>&nbsp; {version}, MIT licensed. A local video studio for your coding agent.</span>
<nav aria-label="Footer"><a href="{gallery}">Examples</a><a href="{xray}">X-ray</a><a href="{crew}">Crew</a><a href="{docs}">Docs</a><a href="{harness}">How it\u2019s built</a>{exrepo}</nav>
<span>No trackers, no cookies. Fonts are served from this site. Film music by Scott Buckley, CC BY 4.0: \u201cSupernova\u201d (the showreel), \u201cArtemis\u201d (the crew film), \u201cWith These Hands\u201d ({hands}).</span>
</div></footer>
<script src="{js}"></script>
</body>
</html>
""".format(title=esc(full), desc=esc(d), og_abs=esc(og_abs),
           og_url=('\n<meta property="og:url" content="%s">\n<link rel="canonical" href="%s">' % (esc(page_abs), esc(page_abs)))
           if page_abs else "", fav=r(fav), touch=r(touch), css=r("static/style.css"), boot=THEME_BOOT,
           root="../" * page.count("/"), home=r("index.html"), menu=ICON_MENU, links=links, sun=ICON_SUN, body=body,
           version=esc(VERSION), docs=r("docs/index.html"), gallery=r("gallery.html"), crew=r("crew.html"), xray=r(XRAY_PAGE),
           harness=r(HARNESS_PAGE), og_w=og_size[0], og_h=og_size[1], head=("\n" + head) if head else "",
           js=r("static/app.js"), font=r("static/fonts/inter.woff2"),
           hands="the launch film and the recap demo" if CONFIG.get("gallery_film") else "the recap demo",
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

EX_ID = r"(\d\d|[a-z][a-z0-9-]*)"   # a numbered example (ex-07), or a named demo card (ex-looks: examples/_looks)
ALSO_RE = r'Also in this group: <a href="#ex-%s"' % EX_ID


def parse_examples() -> Tuple[List[Tuple[str, str]], List[dict]]:
    """Cards from examples/README.md (the single source of the gallery): groups, then examples. A card's id is its
    number, or a name for a demo folder (examples/_looks); demos sort after the numbered examples."""
    txt = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    groups, exs, cur = [], {}, None
    order, also = [], []     # also: (card, group) from "Also in this group" lines, applied once every card is read
    for block in re.split(r"(?=^## |<a id=\"ex-)", txt, flags=re.M):
        m = re.match(r"^## (.+)$", block, re.M)
        if block.startswith("## ") and m:
            name = m.group(1).strip()
            if name in ("Also here", "Rebuilding one", "About the previews"):
                cur = None
                continue
            cur = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            groups.append((cur, name))
            also += [(n, cur) for n in re.findall(ALSO_RE, block)]
            continue
        m = re.match(r'<a id="ex-%s"></a>' % EX_ID, block)
        if not m or not cur:
            continue
        n = m.group(1)
        folder = re.search(r'<a href="([^"/]+)/"><img', block).group(1)
        alt = html.unescape(re.search(r'<img src="[^"]+" width="100%" alt="([^"]*)"', block).group(1))
        meta = html.unescape(re.search(r"<sub>(?:\d\d|Demo) · (.+?)</sub><br>", block).group(1))
        title = html.unescape(re.search(r'<b><a href="[^"]+/">(.+?)</a></b>', block).group(1))
        prompt = html.unescape(re.search(r"<i>“(.*?)”</i>", block, re.S).group(1))
        what = html.unescape(re.search(r"WHAT IT SHOWS</sub><br>(.*?)</p>", block, re.S).group(1))
        line = re.search(r"<p>▶ (.*?)<br>", block, re.S).group(1)
        # after "HTML video:" (or "Live figures:", a diagram's --interactive exports) come the HTML files
        split = re.search(r"HTML video:|Live figures?:", line)
        watch_part, html_part = (line[:split.start()], line[split.end():]) if split else (line, "")
        watch = re.findall(r'href="([^"]+)"', watch_part)
        hv = re.findall(r'href="([^"]+)"', html_part)
        tags = [cur]
        e = {"num": n, "folder": folder, "alt": alt, "meta": meta, "title": title, "prompt": prompt, "what": what,
             "watch": watch, "html": hv, "tags": tags}
        exs[n] = e
        order.append(n)
        also += [(a, cur) for a in re.findall(ALSO_RE, block)]   # a line under this card, still in its group
    for n, g in also:
        if n in exs and g not in exs[n]["tags"]:
            exs[n]["tags"].append(g)
    return groups, [exs[n] for n in sorted(order)]


def ex_label(e: dict) -> str:
    """How a card is named in crumbs and search: its number (07), or Demo for a named demo card."""
    return e["num"] if e["num"].isdigit() else "Demo"


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


SECONDS = re.compile(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))? s\b")


def clock(spec: str) -> str:
    """A card's length in one format, minutes and seconds: "45 s" -> "0:45", "60 s + 64 s" -> "1:00 + 1:04",
    "3 clips, 22-46 s" -> "3 clips, 0:22-0:46"; "2:38", counts ("4 \u00d7") and words are kept."""
    def mmss(x: str) -> str:
        v = float(x)
        m, sec = divmod(v, 60)
        whole = sec == int(sec)
        return "%d:%s" % (m, ("%02d" % sec) if whole else ("%04.1f" % sec))
    return SECONDS.sub(lambda m: mmss(m.group(1)) + ("-" + mmss(m.group(2)) if m.group(2) else ""), spec)


def card_spec(e: dict) -> str:
    """The line beside a card's title: its number (Demo for a demo) and its length, "25 \u00b7 2:38"."""
    return "%s \u00b7 %s" % (ex_label(e), clock(e["meta"].split(" \u00b7 ")[0]))


NEW_IDS = set(GALLERY.get("new", {}).get("examples", []))
NEW_NAME = GALLERY.get("new", {}).get("name", "New in 0.4")


def card(site: Site, page: str, e: dict, show_what: bool = True, name: str = "", tags: Optional[List[str]] = None) -> str:
    """One film card. name: a title other than the example's (the Start here shelf names the kind of video);
    tags: the filters it answers to (default: its README groups)."""
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
            links.append('<a href="%s">%s</a>' % (rel(page, hl), "Live figure" if h.endswith("-figure.html") else "HTML video"))
            break
    badge = '<span class="badge">%s</span>' % esc(NEW_NAME) if e["num"] in NEW_IDS else ""
    return ('<article class="film" data-tags="%s" data-ex="%s"><div class="frame"%s><img class="still" src="%s" alt="%s" loading="lazy" decoding="async">%s%s</div>'
            '<div class="meta"><h3><a href="%s">%s</a></h3><span class="spec">%s</span></div>'
            '<p class="ask">\u201c%s\u201d</p>%s<div class="links">%s</div></article>'
            % (" ".join(e["tags"] if tags is None else tags), esc(e["num"]), clip_attr, still, esc(e["alt"]), badge, action, story,
               esc(name or e["title"]), esc(card_spec(e)), esc(e["prompt"]),
               ('<p class="shows">%s</p>' % esc(e["what"])) if show_what else "", "".join(links)))


def shelves(exs: List[dict]) -> List[dict]:
    """GALLERY's groups as shelves of cards, checked against the cards examples/README.md has: every card on exactly
    one group's shelf, and no id without a card. The build stops on a mismatch, naming the ids."""
    by = {e["num"]: e for e in exs}
    groups = GALLERY.get("groups", [])
    placed: Dict[str, List[str]] = {}
    for g in groups:
        for n in g["examples"]:
            placed.setdefault(n, []).append(g["id"])
    listed = list(placed) + [c["id"] for c in GALLERY.get("start_here", {}).get("cards", [])] + GALLERY.get("new", {}).get("examples", []) + [
        n for ids in GALLERY.get("see_it_done", {}).values() for n in ids]
    problems = ["%s is in site/content/gallery.json but examples/README.md has no card ex-%s" % (n, n)
                for n in dict.fromkeys(listed) if n not in by]
    problems += ["card ex-%s is on no shelf: add it to one group in site/content/gallery.json" % n for n in by if n not in placed]
    problems += ["card ex-%s is in two groups (%s): one shelf each" % (n, ", ".join(g)) for n, g in placed.items() if len(g) > 1]
    if problems:
        sys.exit("site/build.py: the gallery's groups do not match the cards:\n  " + "\n  ".join(problems))
    return [dict(g, cards=[by[n] for n in g["examples"]]) for g in groups]


def guide_link(site: Site, page: str, label: str, target: str, anchor: str = "") -> str:
    """A link to a docs page (and one of its headings) that this build wrote; the build stops on one it did not."""
    built = site.out / target
    if target not in site.pages.values() or not built.is_file():
        sys.exit("site/build.py: site/content/gallery.json links %s, which this build has no page for" % target)
    if anchor and ' id="%s"' % anchor not in built.read_text(encoding="utf-8"):
        sys.exit("site/build.py: site/content/gallery.json links %s#%s, a heading that page does not have" % (target, anchor))
    return '<a href="%s%s">%s</a>' % (rel(page, target), "#" + anchor if anchor else "", esc(label))


def gallery_film(site: Site, page: str) -> str:
    """An optional film above the gallery's tabs: config.json "gallery_film" names it (null: none, ""). This build
    plays it when it has the file, else links to the release asset."""
    gf = CONFIG.get("gallery_film")
    if not gf:
        return ""
    gfolder = gf["folder"]
    glabel, glen, lcredit = gf.get("label", "The film"), gf.get("length", ""), gf.get("credit", "")
    lfilm, lfilm_fb = site.media(gfolder + "/" + gf["film"], gfolder.split("/")[-1])
    lposter = src_path(gf.get("poster", gfolder + "/poster.jpg"))
    lpa = ' poster="%s"' % rel(page, site.copy_asset(lposter)) if lposter.is_file() else ""
    if lfilm:
        return ('<div class="players" id="gallery-film" style="grid-template-columns:1fr;scroll-margin-top:96px"><figure><video controls '
                'playsinline preload="metadata"%s src="%s" aria-label="%s"></video><figcaption>%s</figcaption>'
                '</figure></div>' % (lpa, rel(page, lfilm), esc(glabel), lcredit))
    return ('<p class="note" id="gallery-film" style="margin-top:24px"><a class="link-arrow" href="%s">Watch %s%s '
            '<span>\u2192</span></a> %s</p>' % (esc(lfilm_fb or "#"), esc(glabel[:1].lower() + glabel[1:] if glabel.startswith("The ") else glabel),
                                                " (%s)" % esc(glen) if glen else "", lcredit))


def build_gallery(site: Site, exs) -> None:
    """The gallery: a Start here shelf, then one shelf per group of site/content/gallery.json, each with its line and
    the guides behind it. The tabs filter the same cards (app.js); without script every shelf shows."""
    page = "gallery.html"
    by = {e["num"]: e for e in exs}
    start = GALLERY["start_here"]
    shelf_list = shelves(exs)
    new_n = sum(1 for e in exs if e["num"] in NEW_IDS)
    tabs = [("all", "All", len(exs)), ("start-here", start["name"], len(start["cards"]))]
    tabs += [(g["id"], g["name"], len(g["cards"])) for g in shelf_list] + [(GALLERY["new"]["id"], NEW_NAME, new_n)]
    tab_html = "".join('<button class="tab" type="button" data-filter="%s" aria-pressed="%s">%s<span class="c">%d</span></button>'
                       % (k, "true" if k == "all" else "false", esc(n), c) for k, n, c in tabs)

    def tags(e: dict, group: str) -> List[str]:
        return [group] + ([GALLERY["new"]["id"]] if e["num"] in NEW_IDS else [])
    label, target = start["next"]
    guide_link(site, page, label, target)   # stops the build when the page is not one this build wrote
    parts = ['<section class="shelf" id="shelf-start-here"><div class="shelf-head"><div><h2 class="title">%s</h2><p class="lede">%s</p></div>'
             '<a class="link-arrow" href="%s">%s <span>\u2192</span></a></div><div class="films three">%s</div></section>'
             % (esc(start["name"]), esc(start["line"]), rel(page, target), esc(label),
                "".join(card(site, page, by[c["id"]], name=c["name"], tags=["start-here"]) for c in start["cards"]))]
    for g in shelf_list:
        guides = " \u00b7 ".join(guide_link(site, page, *x) for x in g.get("guides", []))
        parts.append('<section class="shelf" id="shelf-%s"><div class="shelf-head"><div><h2 class="title">%s <span class="c">%d</span></h2>'
                     '<p class="lede">%s</p></div>%s</div><div class="films three">%s</div></section>'
                     % (esc(g["id"]), esc(g["name"]), len(g["cards"]), esc(g["line"]),
                        '<p class="guides">The guides behind these: %s</p>' % guides if guides else "",
                        "".join(card(site, page, e, tags=tags(e, g["id"])) for e in g["cards"])))
    htmls, live = [], ""
    for e in exs:
        for h in e["html"]:
            hl, _ = site.media(ex_path(h), e["folder"])
            if hl and not h.endswith("-figure.html"):   # a live figure is no video: its card and page link it
                htmls.append('<li><a href="%s">%s</a><span>%s</span></li>' % (rel(page, hl), esc(e["title"]), esc(h.split("/")[-1])))
                if e["num"] == "02" and not live:
                    live = ('<div class="htmlvid"><iframe src="%s" title="HTML video: %s" loading="lazy" allow="fullscreen"></iframe></div>'
                            % (rel(page, hl), esc(e["title"])))
    launch = gallery_film(site, page)
    nums = [e for e in exs if e["num"].isdigit()]
    count = "%s examples and %s demos" % (count_words(len(nums)), count_words(len(exs) - len(nums)).lower())
    body = """<div class="wrap">
<header class="room-head"><h1 class="title">Now showing</h1>
<p class="lede">{count}, each made from a single request by an agent acting as a user. Hover to preview, press play for
the full video with sound, or open the story behind it.</p>{exrepo}
{launch}
<div class="filters" role="group" aria-label="Filter by use case">{tabs}</div>
<p class="count" aria-live="polite"></p></header>
{shelves}
<section class="interactive" aria-labelledby="html-videos">
<div class="section-head"><h2 class="title" id="html-videos">Videos that are web pages</h2>
<p class="lede">Every project also exports as one HTML file that plays offline: the same frames as the MP4, chapters, keyboard
control and links to a moment. This one is live; click it and press <kbd>?</kbd>.</p></div>
{live}
<ul class="htmllist">{htmls}</ul>
</section>
</div>""".format(tabs=tab_html, shelves="\n".join(parts), live=live, launch=launch, count=count, exrepo=(
        '\n<p class="lede">All %d, with their projects and full-quality videos, live in <a href="https://github.com/%s">%s</a>.</p>'
        % (len(exs), esc(EXAMPLES_REPO), esc(EXAMPLES_REPO.split("/")[-1]))) if EXAMPLES_REPO else "",
                  htmls="".join(htmls) or "<li class='muted'>Not included in this build.</li>")
    write(site, page, shell(site, page, "Examples", body, "gallery", "%s made with showtime, from one sentence each." % count))


ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def count_words(n: int) -> str:
    """A count as it opens a sentence: 24 -> "Twenty-four" (digits from 100 on)."""
    if n < 0 or n >= 100:
        return str(n)
    w = ONES[n] if n < 20 else TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    return w[:1].upper() + w[1:]


def example_name(e: dict) -> str:
    """An example as its page title, the pager and the search name it: "Example 25: ...", or "Demo: ..."."""
    return ("Example %s: %s" if e["num"].isdigit() else "%s: %s") % (ex_label(e), e["title"])


def build_example_pages(site: Site, exs) -> None:
    # Previous / Next in gallery order; the gallery closes the row at both ends
    seq = [example_name(e) for e in exs]
    seq = [("All examples", "gallery.html")] + [(t, "examples/%s.html" % e["folder"]) for t, e in zip(seq, exs)] + [("All examples", "gallery.html")]
    for n, e in enumerate(exs, 1):
        folder = e["folder"]
        page = "examples/%s.html" % folder
        src = EXAMPLES / folder / "README.md"
        text = strip_front_matter(src.read_text(encoding="utf-8"))
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
        embeds, wide = [], []   # wide: a live figure, as wide as the page so it keeps its desktop layout (820 px and up)
        for h in e["html"]:
            hl, hfb = site.media(ex_path(h), folder)
            name = h.split("/")[-1]
            if hl and name.endswith("-figure.html"):
                # a live figure (export html --interactive): no player, a board people hover, step through and tune
                wide.append('<section class="figure-room"><div class="prose" style="max-width:var(--read);margin:0 auto"><h2 id="live-figure" style="margin-top:0">The live figure</h2><p><code>%s</code> is one offline file, '
                              'live right here: hover or tab to a part, pick a step, turn a knob. Arrow keys and 1-9 move between '
                              'the steps, <kbd>R</kbd> runs one again and <kbd>L</kbd> copies a link to what you see. '
                              '<a href="%s">Open it on its own</a>.</p></div>'
                              '<div class="htmlvid figure"><iframe src="%s" title="Live figure: %s" loading="lazy"></iframe></div></section>'
                              % (esc(name), rel(page, hl), rel(page, hl), esc(e["title"])))
                break
            if hl:
                folder_export = name == "index.html" and (src_path(ex_path(h)).parent / "assets" / "vfs.js").is_file()
                what = ("<code>%s/</code> is the folder export (<code>index.html</code> and <code>assets/</code>)" % esc(h.split("/")[-2])
                        if folder_export else "<code>%s</code> is the single-file export" % esc(name))
                embeds.append('<h2 id="html-video" style="margin-top:0">The HTML video</h2><p>%s, '
                              'playing right here. Click it, then press <kbd>?</kbd> for the keys, or <a href="%s">open it on its own</a>.</p>'
                              '<div class="htmlvid"><iframe src="%s" title="HTML video: %s" loading="lazy" allow="fullscreen"></iframe></div>'
                              % (what, rel(page, hl), rel(page, hl), esc(e["title"])))
                break
        head = ('<div class="wrap"><div class="ex-head"><div class="crumbs"><a href="%s">Examples</a> / %s</div>'
                '<p class="spec">%s</p><h1 class="title">%s</h1><p class="ask">\u201c%s\u201d</p></div>'
                '<div class="players">%s</div></div>'
                % (rel(page, "gallery.html"), esc(ex_label(e)), esc(clock(e["meta"])), esc(e["title"]), esc(e["prompt"]), "".join(players)))
        more = ""
        if site.repo:
            more = '<p class="edit"><a href="%s">The project files on GitHub</a></p>' % esc(site.gh("examples/" + folder, True))
        body = head + ('<div class="wrap">%s</div>' % "".join(wide) if wide else "") + (
            '<div class="wrap"><article class="prose" style="max-width:var(--read);margin:64px auto 120px">%s%s%s%s</article></div>' % (
                "".join(embeds), body_html, more, pager_html(page, (seq[n - 1], seq[n + 1]))))
        write(site, page, shell(site, page, example_name(e), body, "gallery", what_sentence(e)))
        site.h2_expect[page] = ("examples/%s/README.md" % folder, md_h2_count(text) + len(embeds) + len(wide))
        site.search.append(search_entry(site, example_name(e), page, text, heads,
                                        lead=e["prompt"] + "\n" + e["what"]))


# ----------------------------------------------------------------------------------------------- docs

def doc_sources() -> List[Tuple[Path, str, str]]:
    """(source, output page, sidebar group) for every doc page."""
    out = []
    for p in sorted(REFS.glob("*.md")):
        if p.name != "index.md":    # the agent's own map: build_docs renders it as docs/index-claude.html
            out.append((p, "docs/%s.html" % p.stem, ""))
    for p in sorted((REFS / "workflows").glob("*.md")):
        out.append((p, "docs/workflows/%s.html" % p.stem, "workflows"))
    for p in sorted((REFS / "crew").glob("*.md")):
        out.append((p, "docs/crew/%s.html" % p.stem, "crew"))
    for p in sorted(GUIDES.glob("*.md")):
        out.append((p, "docs/guides/%s.html" % ("index" if p.name == "README.md" else p.stem), "guides"))
    # docs/glossary.md is the reader's glossary; CONTEXT.md, the house vocabulary for whoever writes showtime, has its own page
    extra = [(REPO / "CONTEXT.md", "docs/house-vocabulary.html"), (REPO / ".out-of-scope/README.md", "docs/out-of-scope.html"),
             (REPO / "skills/showtime/SKILL.md", "docs/skill.html"), (REPO / "assets/brand/BRAND.md", "docs/brand.html"),
             (REPO / "CONTRIBUTING.md", "docs/contributing.html"), (REPO / "CHANGELOG.md", "docs/changelog.html"),
             (REPO / "docs" / "agents.md", "docs/agents.html"),
             (REPO / "docs" / "github-action.md", "docs/github-action.html"),
             (REPO / "docs" / "whats-new.md", "docs/whats-new.html"), (REPO / "docs" / "faq.md", "docs/faq.html"),
             (REPO / "docs" / "troubleshooting.md", "docs/troubleshooting.html"), (REPO / "docs" / "glossary.md", "docs/glossary.html")]
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


def guide_items(site: Site) -> List[Tuple[str, str]]:
    """The Guides group: the guides' index, then each guide in the order the index links them, labelled with its
    h1 (guides the index does not link come last, by name). A guide in Start here (the first video) is listed there only."""
    index = GUIDES / "README.md"
    if index.resolve() not in site.pages:
        return []
    order = re.findall(r"\]\(([a-z0-9-]+)\.md\)", index.read_text(encoding="utf-8"))
    rest = sorted(p.stem for p in GUIDES.glob("*.md") if p.name != "README.md" and p.stem not in order)
    items = [("All guides", site.pages[index.resolve()])]
    for stem in dict.fromkeys(order + rest):
        src = (GUIDES / (stem + ".md")).resolve()
        if src in site.pages and site.pages[src] not in {t for t, _l in START_PAGES}:
            h1 = re.search(r"^# (.+)$", src.read_text(encoding="utf-8"), re.M)
            items.append((h1.group(1).strip() if h1 else human(stem), site.pages[src]))
    return items


def sidebar_groups(site: Site) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """The guides first, then groups in the docs map's running order (docs/README.md), then the crew briefs and
    backstage pages."""
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
    guides = guide_items(site)
    for g in [g for g in groups if g[0] == "Guides"]:   # a "## Guides" heading in the map joins the guides' group
        guides += [it for it in g[1] if it not in guides]
        groups.remove(g)
    groups = ([["Guides", guides]] if guides else []) + [g for g in groups if g[1]]
    crew = [(human(p.stem), site.pages[p.resolve()]) for p in sorted((REFS / "crew").glob("*.md"))]
    groups.append(["The crew's briefs", crew])
    back = [("House vocabulary", "docs/house-vocabulary.html"), ("Out of scope", "docs/out-of-scope.html"), ("SKILL.md", "docs/skill.html"),
            ("Brand", "docs/brand.html"), ("Contributing", "docs/contributing.html"), ("Changelog", "docs/changelog.html"),
            ("The GitHub Action", "docs/github-action.html"), ("The agent's own map", "docs/index-claude.html")]
    groups.append(["Backstage", [b for b in back if (site.out / b[1]).exists() or b[1] in site.pages.values()]])
    return [(g[0], g[1]) for g in groups]


# The search's one normalisation rule, shared with norm() in site/static/app.js (change both together): runs of
# ` * _ > | # - become one space and whitespace collapses, in the index text here and in the typed query there, so
# pr-video, SHOWTIME_MCP_TOOLS and #t= find the text they came from. tests/test_site_search.py checks both use it.
SEARCH_SEPARATORS = r"[`*_>|#-]+"


def plain(md_text: str) -> str:
    t = re.sub(r"```.*?```", " ", md_text, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(SEARCH_SEPARATORS, " ", t)
    return re.sub(r"\s+", " ", t).strip()


def search_entry(site: Site, title: str, page: str, text: str, heads, lead: str = "") -> dict:
    """One page of the search index: {"t": title, "u": page, "s": [[heading, anchor, text], ...]}, one section per h2
    and h3 (the first, with no heading or anchor, is the text above them, after `lead`), so every part of a long page
    can be found and a hit links to its section. heads are render_md's headings for the same text, in order."""
    lines = text.split("\n")
    starts = [t.map[0] for t in site.md.parse(text, {}) if t.type == "heading_open"]
    if len(starts) != len(heads):
        raise RuntimeError("%s: %d headings parsed, %d rendered" % (page, len(starts), len(heads)))
    cuts = [(ln, h) for ln, h in zip(starts, heads) if h[2] in (2, 3)]
    secs = [["", "", plain(lead + "\n" + "\n".join(lines[:cuts[0][0] if cuts else len(lines)]))]]
    for i, (ln, h) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(lines)
        secs.append([h[0], h[1], plain("\n".join(lines[ln + 1:end]))])
    return {"t": title, "u": page, "s": secs}


def built_page_entry(site: Site, title: str, page: str) -> dict:
    """A search entry for a page that is built from code, not Markdown (the landing, the gallery): its text above the
    first h2/h3, then one section per heading, linked by the heading's id or else the nearest id before it."""
    raw = (site.out / page).read_text(encoding="utf-8")
    main = re.search(r'<main id="main">(.*?)</main>', raw, re.S)
    main = re.sub(r"<(script|style|svg|video|iframe)\b.*?</\1>", " ", main.group(1) if main else "", flags=re.S)
    parts = re.split(r"(<h[23]\b[^>]*>.*?</h[23]>)", main, flags=re.S)

    def text(x: str) -> str:
        return plain(html.unescape(re.sub(r"<[^>]+>", " ", x)))
    secs, seen = [["", "", text(parts[0])]], parts[0]
    for head, body in zip(parts[1::2], parts[2::2]):
        own = re.search(r'\sid="([^"]+)"', head)
        sec = []   # the sections still open at this heading: a closed one is not where the heading is
        for m in re.finditer(r'<section\b([^>]*)>|</section>', seen):
            if m.group(1) is None:
                sec = sec[:-1]
            else:
                sec.append((re.search(r'\sid="([^"]+)"', m.group(1)) or [None, ""])[1])
        sec = [x for x in sec if x]
        seen += head + body
        anchor = own.group(1) if own else (sec[-1] if sec else "")
        if anchor:
            secs.append([text(head), anchor, text(body)])
        else:
            secs[-1][2] += " " + text(head) + " " + text(body)
    return {"t": title, "u": page, "s": secs}


def check_search(site: Site) -> List[str]:
    """Problems in the search index: a page indexed twice, a page not built, an anchor the page does not have."""
    problems, seen = [], set()
    for e in site.search:
        if e["u"] in seen:
            problems.append("%s is in the search index twice" % e["u"])
        seen.add(e["u"])
        p = site.out / e["u"]
        if not p.is_file():
            problems.append("%s (%s) is in the search index but was not built" % (e["u"], e["t"]))
            continue
        ids = set(re.findall(r'\sid="([^"]+)"', p.read_text(encoding="utf-8")))
        problems += ["%s#%s (%s) is in the search index but the page has no such anchor" % (e["u"], s[1], s[0])
                     for s in e["s"] if s[1] and s[1] not in ids]
    return problems


# the sidebar's first group, on every docs page, and the start of the reading order (Previous / Next)
START_NAME = "Start here"
START_PAGES = [("docs/guides/first-video.html", "Your first video"), ("docs/index.html", "The map"),
               ("docs/troubleshooting.html", "When something goes wrong"), ("docs/faq.html", "Questions people ask"),
               ("docs/glossary.html", "Glossary"), ("docs/agents.html", "Works with your agent"), ("docs/whats-new.html", "What's new")]


def pager_html(page: str, prev_next) -> str:
    """The Previous / Next links under a page: prev_next is ((label, page) or None, (label, page) or None)."""
    pv, nx = prev_next
    return '<nav class="pager" aria-label="Previous and next">%s%s</nav>' % (
        '<a href="%s"><small>Previous</small>%s</a>' % (rel(page, pv[1]), esc(pv[0])) if pv else "<span></span>",
        '<a class="next" href="%s"><small>Next</small>%s</a>' % (rel(page, nx[1]), esc(nx[0])) if nx else "")


def neighbours(seq, page: str):
    """((label, page) before, (label, page) after) for a page in a reading order, or None when it is not in it."""
    idx = next((i for i, it in enumerate(seq) if it[1] == page), None)
    if idx is None:
        return None
    return (seq[idx - 1] if idx else None, seq[idx + 1] if idx + 1 < len(seq) else None)


def docs_frame(site: Site, page: str, groups, content: str, heads, prev_next) -> str:
    side = ['<aside class="side" aria-label="Documentation"><div class="search" role="search"><label class="sr" for="q">Search the docs</label>',
            ICON_SEARCH, '<input id="q" type="search" placeholder="Search the docs" autocomplete="off"><span class="key" aria-hidden="true">/</span>',
            '<div class="results" hidden></div></div>',
            '<button class="side-toggle" type="button" aria-expanded="false"><span>Browse the guides</span><span aria-hidden="true">+</span></button>',
            '<div class="groups"><h4>%s</h4><ul>' % START_NAME]
    chip = '<span class="chip">%s</span>' % esc(latest_release()[0])   # the newest released version (the page itself shows the whole file)
    for target, label in START_PAGES:
        side.append('<li><a href="%s"%s>%s%s</a></li>' % (rel(page, target), ' aria-current="page"' if page == target else "", esc(label),
                                                          chip if target == "docs/whats-new.html" else ""))
    side.append("</ul>")
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
    pager = pager_html(page, prev_next) if prev_next else ""
    return '<div class="docs">%s<article class="prose">%s%s</article>%s</div>' % ("".join(side), content, pager, toc_html)


def map_anchors(site: Site) -> Dict[str, str]:
    """The docs map's h2 headings (docs/README.md) -> their ids on docs/index.html, as render_md gives them."""
    toks = site.md.parse((REPO / "docs" / "README.md").read_text(encoding="utf-8"), {})
    seen: Dict[str, int] = {}
    out = {}
    for i, t in enumerate(toks):
        if t.type == "heading_open":
            hid = slugify(toks[i + 1].content, seen)
            if t.tag == "h2":
                out.setdefault(toks[i + 1].content.strip(), hid)
    return out


def crumbs_html(page: str, group: str, label: str, anchors: Dict[str, str]) -> str:
    """Docs / the page's group (its act on the map when the map has that heading) / the page."""
    href = None
    if group == "Guides":
        href = rel(page, "docs/guides/index.html")
    else:
        hid = anchors.get(group) or next((v for k, v in anchors.items() if k.endswith(" \u00b7 " + group)), None)
        href = rel(page, "docs/index.html") + "#" + hid if hid else None
    mid = '<a href="%s">%s</a>' % (href, esc(group)) if href else esc(group)
    return '<div class="crumbs"><a href="%s">Docs</a> / %s / %s</div>' % (rel(page, "docs/index.html"), mid, esc(label))


def see_it_done(page: str, exs: List[dict]) -> str:
    """The "See it done" line under a page's lede: the examples site/content/gallery.json names for it."""
    by = {e["num"]: e for e in exs}
    ids = [n for n in GALLERY.get("see_it_done", {}).get(page, []) if n in by]
    if not ids:
        return ""
    return '<p class="see-it-done">See it done: %s</p>' % " \u00b7 ".join(
        '<a href="%s">%s %s</a>' % (rel(page, "examples/%s.html" % by[n]["folder"]), esc(ex_label(by[n])), esc(by[n]["title"])) for n in ids)


def build_docs(site: Site, exs: Optional[List[dict]] = None) -> None:
    sources = doc_sources()
    for src, page, _g in sources:
        site.pages[src.resolve()] = page
    site.pages[(REFS / "index.md").resolve()] = "docs/index-claude.html"
    site.pages[(REPO / "docs" / "README.md").resolve()] = "docs/index.html"
    site.pages[(REPO / "README.md").resolve()] = "index.html"
    site.pages[(EXAMPLES / "README.md").resolve()] = "gallery.html"
    for d in sorted(EXAMPLES.glob("[0-9][0-9]-*/README.md")):
        if site.gallery is None or d.parent.name in site.gallery:   # only examples whose page is built
            site.pages[d.resolve()] = "examples/%s.html" % d.parent.name
    groups = sidebar_groups(site)
    site.doc_groups = groups
    # reading order: the Start pages (the map first), then each group; a page in both is read once, where it comes first
    flat = []
    for label, target in [(l, t) for t, l in START_PAGES] + [it for _, items in groups for it in items]:
        if all(it[1] != target for it in flat):
            flat.append((label, target))
    # where each page sits, for its crumbs: Start here, else its act (components is also a Choose your path card),
    # else the first group that lists it
    where: Dict[str, Tuple[str, str]] = {}
    acts = [g for g in groups if re.match(r"(Act |Finale)", g[0])]
    for name, items in [(START_NAME, [(l, t) for t, l in START_PAGES])] + acts + [g for g in groups if g not in acts]:
        for label, target in items:
            where.setdefault(target, (name, label))
    anchors = map_anchors(site)
    rendered = []
    for src, page, _g in sources + [(REFS / "index.md", "docs/index-claude.html", "")]:
        if page == "docs/index-claude.html" and not src.is_file():
            continue
        text = strip_front_matter(src.read_text(encoding="utf-8"))
        body, title, heads = site.render_md(text, src, page)
        title = title or src.stem
        repo_rel = src.resolve().relative_to(REPO).as_posix()
        group, label = where.get(page, ("Backstage", title))
        crumbs = crumbs_html(page, group, label, anchors)
        done = see_it_done(page, exs or [])
        if done:   # under the lede: the first paragraph after the h1
            body, n = re.subn(r"(</h1>\s*<p>.*?</p>)", lambda m: m.group(1) + done, body, count=1, flags=re.S)
            if not n:
                sys.exit("site/build.py: %s has no paragraph right after its h1 for the \"See it done\" line that "
                         "site/content/gallery.json gives it" % page)
        edit = ('<p class="edit"><a href="%s">View or edit <code>%s</code> on GitHub</a></p>' % (esc(site.gh(repo_rel)), esc(repo_rel))) if site.repo else ""
        html_page = docs_frame(site, page, groups, crumbs + body + edit, heads, neighbours(flat, page))
        write(site, page, shell(site, page, title, html_page, "docs", md_description(text)))
        site.h2_expect[page] = (repo_rel, md_h2_count(text))
        site.search.append(search_entry(site, title, page, text, heads))
        rendered.append(page)
    unknown = sorted(set(GALLERY.get("see_it_done", {})) - set(rendered))
    if unknown and exs is not None:
        sys.exit("site/build.py: site/content/gallery.json \"see_it_done\" names pages this build has no page for: "
                 + ", ".join(unknown))
    # the map itself
    src = REPO / "docs" / "README.md"
    text = re.sub(r'^<p align="center">\s*<picture>.*?</picture>\s*</p>\s*', "", src.read_text(encoding="utf-8"), count=1, flags=re.S)
    body, title, heads = site.render_md(text, src, "docs/index.html")
    write(site, "docs/index.html", shell(site, "docs/index.html", "Documentation",
                                         docs_frame(site, "docs/index.html", groups, body, heads, neighbours(flat, "docs/index.html")), "docs",
                                         "Every showtime guide, in running order."))
    site.h2_expect["docs/index.html"] = ("docs/README.md", md_h2_count(text))
    site.search.append(search_entry(site, "Documentation map", "docs/index.html", text, heads))


DESC_LIMIT = 200   # characters a link preview's description aims for; whole sentences only
NOT_ENDS = {"e.g", "i.e", "vs", "cf", "approx", "etc"}   # a period after these does not end the sentence


def describe(text: str, limit: int = DESC_LIMIT) -> str:
    """A page description in whole sentences: as many as fit in `limit` characters, at least the first one, so a
    link preview never stops mid-sentence. Text without a sentence end is kept whole."""
    t = re.sub(r"\s+", " ", text or "").strip()
    ends = []
    for m in re.finditer(r"[.!?][\"”’')\]]*(?= |$)", t):
        word = re.search(r"([\w.]+)[.!?]$", t[:m.start() + 1])
        if t[m.start()] == "." and word and word.group(1).lower() in NOT_ENDS:
            continue
        nxt = t[m.end() + 1:m.end() + 2]
        if nxt and not re.match(r"[A-Z0-9\"“(\[`*_]", nxt):
            continue
        ends.append(m.end())
    if not ends or ends[-1] != len(t):
        ends.append(len(t))
    fit = [e for e in ends if e <= limit]
    return t[:(fit[-1] if fit else ends[0])].strip()


def what_sentence(e: dict) -> str:
    """An example's "what it shows" line (a list of features) as one sentence."""
    w = e["what"].strip()
    return w if re.search(r"[.!?]$", w) else w + "."


def md_description(md_text: str) -> str:
    """The description of a Markdown page: its first top-level paragraph as plain text (links keep their text;
    images, raw HTML and front matter are dropped), cut at a sentence end by describe()."""
    text = strip_front_matter(md_text)
    toks = MarkdownIt("commonmark", {"html": True}).enable("table").parse(text)
    for i, t in enumerate(toks):
        if t.type != "paragraph_open" or t.level != 0:
            continue
        words = []
        for c in toks[i + 1].children or []:
            if c.type in ("text", "code_inline"):
                words.append(c.content)
            elif c.type in ("softbreak", "hardbreak"):
                words.append(" ")
        s = re.sub(r"\s+", " ", "".join(words)).strip()
        if len(s) > 1:
            return describe(s)
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
    # the crew film (examples/_crew): plays here when this build has it, else links to the release asset
    film, film_fb = site.media("examples/_crew/crew-16x9.mp4", "_crew")
    cposter = src_path("examples/_crew/poster.jpg")
    pa = ' poster="%s"' % rel(page, site.copy_asset(cposter)) if cposter.is_file() else ""
    credit = ('The crew at work, 45 seconds, made with showtime. Music: \u201cArtemis\u201d by Scott Buckley, '
              '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Bee footage in the example 13 frames: '
              'Su et al. 2008, PLOS ONE, CC BY 3.0.')
    if film:
        crew_film = ('<div class="players" id="film" style="grid-template-columns:1fr;scroll-margin-top:96px"><figure><video controls playsinline preload="metadata"%s src="%s" '
                     'aria-label="The crew film"></video><figcaption>%s</figcaption></figure></div>' % (pa, rel(page, film), credit))
    else:
        crew_film = ('<p class="note"><a class="link-arrow" href="%s">Watch the crew film (45 s) <span>\u2192</span></a> %s</p>'
                     % (esc(film_fb or "#"), credit))
    body = """<div class="wrap">
<header class="room-head"><h1 class="title">Ten specialists, one director</h1>
<p class="lede">Your agent directs every video and can hand parts of the job to ten sub-agents that ship with the plugin. Every
finished video gets a critic by default (quality mode); say "lean" to skip it (a video you will publish still gets one). A
researcher joins when the video states facts or will be published, scene builders when it is long, and the rest with studio mode.</p></header>
{crew_film}
<div style="margin-top:48px">{cast}</div>
<section class="section" style="padding-bottom:0"><div class="section-head"><h2 class="title">Who hands what to whom</h2>
<p class="lede">Every brief and every result goes through the director. Members never talk to each other or to you, and fixes go
back to the member who made the part.</p></div>{handoff}</section>
<section class="section" style="padding-bottom:0"><div class="section-head"><h2 class="title">What each one does</h2>
<p class="lede">Each member reads its brief, works only in its own folder, never uploads, and reports back with a short status.</p></div>
<div class="roster">{cards}</div></section>
<section class="section"><div class="split" style="margin-top:0"><div><h2 class="title" style="font-size:clamp(1.9rem,3.4vw,2.75rem)">Casting</h2>
<p style="margin-top:16px">Let your agent cast the company: ask for options first and studio mode brings it in. Call one member by name
when you want just that job done. Or say "no crew" and your agent does everything in one session.</p>
<p><a class="link-arrow" href="{guide}">When each member is dispatched, and what it costs <span>→</span></a></p></div>
<div class="copy install"><pre><code># the whole company, in studio mode
Let's make a launch trailer for this repo. Show me options first.

# one member, by name
@agent-showtime:researcher check the claims in narration.md

# no crew at all
Make it quick, no crew.</code></pre></div></div></section>
</div>
""".format(crew_film=crew_film, cast=art(site, page, "crew/cast", "The crew as a cast of ten illustrated cards: " + "; ".join("%s: %s" % (r["name"], r["line"]) for r in roles)),
           handoff=art(site, page, "diagrams/crew-handoff", "How the crew hands work around: pitch, plan, build, review, deliver, all through the director."),
           cards="".join(cards), guide=rel(page, "docs/crew.html"))
    write(site, page, shell(site, page, "The crew", body, "crew", "Ten optional specialist sub-agents, one director."))


# ----------------------------------------------------------------------------------------------- x-ray

XRAY_PAGE = "xray/index.html"
XRAY = json.loads((SITE / "content" / "xray.json").read_text(encoding="utf-8"))
XRAY_SRC = "examples/_xray"   # where an entry's video and poster are looked up (the examples tree, or a --media-from folder)
XRAY_LIBRARY = REPO / "skills" / "showtime" / "library" / "xray"
ICON_CHECK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>')


def xray_media(site: Site, name: str) -> Optional[str]:
    """An X-ray entry's video or poster, copied to media/xray/NAME; None when this build cannot find it."""
    if not name:
        return None
    dst = "media/xray/" + name
    if dst in site.copied:
        return dst
    src = site.find_media("%s/%s" % (XRAY_SRC, name))
    if not src:
        return None
    p = site.out / dst
    p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, p)
    site.copied[dst] = "%s/%s" % (XRAY_SRC, name)
    return dst


def xray_entries() -> List[dict]:
    """The gallery's entries, checked: unique ids, a known kind, a hero that exists. A finished entry (one with a
    receipt) needs its credit, license and commands: nothing appears as finished without them."""
    entries = XRAY.get("entries", [])
    kinds = {k["id"] for k in XRAY.get("kinds", [])}
    problems, seen = [], set()
    for e in entries:
        if e["id"] in seen:
            problems.append("%s is listed twice" % e["id"])
        seen.add(e["id"])
        if e.get("kind") not in kinds:
            problems.append("%s: kind %r is not one of %s" % (e["id"], e.get("kind"), ", ".join(sorted(kinds))))
        if e.get("theme") not in ("dark", "light"):
            problems.append("%s: theme must be dark or light" % e["id"])
        if e.get("receipt"):
            missing = [k for k in ("credit", "license", "commands") if not e.get(k)]
            if missing:
                problems.append("%s has a receipt but no %s" % (e["id"], " or ".join(missing)))
    if XRAY.get("hero") not in seen:
        problems.append("hero %r is not an entry" % XRAY.get("hero"))
    if problems:
        sys.exit("site/build.py: site/content/xray.json:\n  " + "\n  ".join(problems))
    return entries


def xray_receipt(line: str) -> str:
    """A receipt line, its parts kept whole on a narrow screen ("19 of 19 events on their frame" \u00b7 "audio 0.0 ms ...")."""
    return '<span>%s</span>' % " \u00b7 ".join('<span class="w">%s</span>' % esc(x) for x in line.split(" \u00b7 "))


def xray_cmds(lines: List[str]) -> str:
    """Commands for a copy block, one per line; a long one wraps at its spaces with a hanging indent (CSS .xl)."""
    return '<div class="copy install xcmds"><pre><code>%s</code></pre></div>' % "".join(
        '<span class="xl">%s</span>' % " ".join('<span class="w">%s</span>' % esc(w) for w in c.split(" ")) for c in lines)


def xray_blank(e: dict) -> str:
    """The neutral card where an entry has no poster in this build: its object, drawn as a plate."""
    return ('<div class="xblank" aria-hidden="true"><span class="xblank-mark">X-ray</span><span class="xblank-obj">%s</span></div>'
            % esc(e.get("object", "")))


def http_url(u: object) -> str:
    """A link target for an href: http(s) only, else empty (no javascript: or data: from a community entry)."""
    u = str(u or "").strip()
    return u if re.match(r"^https?://", u, re.I) else ""


def xray_credit(e: dict, posted: bool = True) -> str:
    """The clip's credit and license, then who posted the entry (ours: showtime; a community one: its GitHub handle)."""
    lic = esc(e.get("license", ""))
    if http_url(e.get("license_url")):
        lic = '<a href="%s">%s</a>' % (esc(http_url(e["license_url"])), lic)
    who = e.get("author", "showtime")
    if who.startswith("@"):
        who = '<a href="https://github.com/%s">%s</a>' % (esc(who[1:]), esc(who))
    else:
        who = esc(who)
    src = ' \u00b7 <a href="%s">Source</a>' % esc(http_url(e["credit_url"])) if http_url(e.get("credit_url")) else ""
    film = (" \u00b7 " + esc(e["film_license"])) if e.get("film_license") else ""
    return '%s, %s%s%s%s' % (esc(e.get("credit", "")), lic, src, film, (" \u00b7 posted by " + who) if posted else "")


def xray_card(site: Site, page: str, e: dict) -> str:
    layouts = XRAY.get("layouts", {})
    kinds = {k["id"]: k["name"] for k in XRAY.get("kinds", [])}
    done = bool(e.get("receipt"))
    video = xray_media(site, e.get("video", "")) if done else None
    poster = xray_media(site, e.get("poster", ""))
    tall = e.get("aspect") == "9:16"
    label = "%s, %s" % (e["title"], layouts.get(e.get("layout", ""), e.get("layout", "")))
    pic = ('<img class="still" src="%s" alt="%s" loading="lazy" decoding="async">' % (rel(page, poster), esc(label))
           if poster else xray_blank(e))
    action, clip, links = "", "", []
    if video:
        clip = ' data-clip="%s"' % rel(page, video)
        action = ('<button class="open" type="button" data-full="%s" aria-label="Play %s with sound"></button>'
                  '<span class="hint" aria-hidden="true">%s Play with sound</span>' % (rel(page, video), esc(e["title"]), ICON_PLAY))
    elif done:
        asset = ASSET_BY_PATH.get("%s/%s" % (XRAY_SRC, e.get("video", "")))
        fb = site.release_url(asset) if asset else None
        if fb:
            links.append('<a href="%s">Watch the MP4</a>' % esc(fb))
    badge = "" if done else '<span class="badge xpending">In the works</span>'
    spec = " · ".join(x for x in (kinds.get(e["kind"], ""), layouts.get(e.get("layout", ""), ""), e.get("theme", ""), e.get("aspect", "")) if x)
    mech = e.get("mechanism", "")
    if mech and (XRAY_LIBRARY / mech).is_dir():
        url = site.gh("skills/showtime/library/xray/" + mech, is_dir=True)
        links.append(('<a href="%s">The mechanism: <code>%s</code></a>' % (esc(url), esc(mech))) if url
                     else '<span>The mechanism: <code>%s</code> in the library</span>' % esc(mech))
    elif mech:
        links.append('<span class="muted">The <code>%s</code> mechanism joins the library with its film</span>' % esc(mech))
    live = xray_media(site, e.get("live", "")) if done else None
    ratio = "9/16" if tall else "16/9"
    if done:
        rows = ['<p class="xreceipt">%s%s</p>' % (ICON_CHECK, xray_receipt(e["receipt"])),
                '<p class="xcredit">%s</p>' % xray_credit(e)]
        if live:
            rows.insert(0, '<div class="xacts"><button class="btn primary xlive" type="button" data-live="%s" data-ratio="%s" '
                           'data-title="%s" aria-pressed="false">Play it live</button></div>' % (rel(page, live), ratio, esc(e["title"])))
        if e.get("prompt"):
            rows.append('<div class="xline"><h4>Make your own with one line</h4><p class="ask">\u201c%s\u201d</p></div>' % esc(e["prompt"]))
        rows.append('<details class="xmake"><summary>Make your own</summary>%s</details>' % xray_cmds(e["commands"]))
        if live:
            rows.append('<p class="xembed-note">Sharing a live page shares what is in it: the prompt and the commands it shows, the whole xray block of showtime.json (its made.prompt and made.commands travel with the page even when --prompt shows another prompt), the source recording’s file name and fingerprint (sha256) and, for a film made from data, the events file’s name and fingerprint with its column names, labels and values.</p>')
        base = site_url(site.repo)
        if live and base:
            src = base + live
            ptag = (' poster="%s"' % esc(base + poster)) if poster else ""
            tag = ('<script src="%sxray/embed.js"></script>\n<showtime-xray src="%s" ratio="%s" title="%s"%s></showtime-xray>'
                   % (base, src, ratio, esc(e["title"]), ptag))
            # the film's own height at that width (420 x 16/9 = 747 and 960 x 9/16 = 540) plus about 320 px of controls
            size = 'width="420" height="1067"' if tall else 'width="960" height="860"'
            frame = '<iframe src="%s#embed" title="%s" %s allow="autoplay; clipboard-write" loading="lazy" style="border:0;max-width:100%%"></iframe>' % (src, esc(e["title"]), size)
            blocks = lambda t: '<div class="copy"><pre><code>%s</code></pre></div>' % esc(t)  # noqa: E731
            rows.append('<details class="xmake xembed"><summary>Embed</summary><p class="xembed-note">On a page of yours, with the script:</p>%s'
                        '<p class="xembed-note">Or as a plain frame:</p>%s</details>' % (blocks(tag), blocks(frame)))
    else:
        rows = ['<p class="xcredit">The film is made; it appears here with its receipt and its clip credit.</p>']
    return ('<article class="film xcard%s" data-kind="%s" data-xtheme="%s" id="x-%s"><div class="frame xframe%s"%s>%s%s%s</div>'
            '<div class="meta"><h3>%s</h3><span class="spec">%s</span></div><p class="shows">%s</p>%s<div class="links">%s</div></article>'
            % ("" if done else " pending", esc(e["kind"]), esc(e["theme"]), esc(e["id"]), " tall" if tall else "", clip, pic, badge, action,
               esc(e["title"]), esc(spec), esc(e.get("what", "")), "".join(rows), "".join(links)))


def touch_card(site: Site, page: str, e: dict) -> str:
    """A living diagram people touch (site/content/xray.json "touch"): no clip, one live figure (`showtime export html
    <project> --interactive`), played in place like an X-ray's live page, with the line that made it and an embed."""
    live = xray_media(site, e.get("figure", ""))
    poster = xray_media(site, e.get("poster", ""))
    pic = ('<img class="still" src="%s" alt="%s" loading="lazy" decoding="async">' % (rel(page, poster), esc(e["title"]))
           if poster else '<div class="xblank" aria-hidden="true"><span class="xblank-mark">Live figure</span><span class="xblank-obj">%s</span></div>' % esc(e["title"]))
    rows = []
    if live:
        rows.append('<div class="xacts"><button class="btn primary xlive" type="button" data-live="%s" data-ratio="16/9" data-title="%s" '
                    'aria-pressed="false">%s</button></div>' % (rel(page, live), esc(e["title"]), esc(e.get("verb", "Touch it live"))))
    if e.get("prompt"):
        rows.append('<div class="xline"><h4>Make your own with one line</h4><p class="ask">\u201c%s\u201d</p></div>' % esc(e["prompt"]))
    if e.get("commands"):
        rows.append('<details class="xmake"><summary>Make your own</summary>%s</details>' % xray_cmds(e["commands"]))
    base = site_url(site.repo)
    if live and base:
        tag = ('<script src="%sxray/embed.js"></script>\n<showtime-xray src="%s" ratio="16/9" title="%s"%s></showtime-xray>'
               % (base, base + live, esc(e["title"]), (' poster="%s"' % esc(base + poster)) if poster else ""))
        rows.append('<details class="xmake xembed"><summary>Embed</summary><p class="xembed-note">On a page of yours, with the script:</p>'
                    '<div class="copy"><pre><code>%s</code></pre></div></details>' % esc(tag))
    return ('<article class="film xcard xtouch" id="t-%s"><div class="frame xframe">%s</div><div class="meta"><h3>%s</h3>'
            '<span class="spec">%s</span></div><p class="shows">%s</p>%s</article>'
            % (esc(e["id"]), pic, esc(e["title"]), esc(e.get("spec", "living diagram · live figure")), esc(e.get("what", "")), "".join(rows)))


def build_xray(site: Site) -> None:
    """xray/: the X-ray page. A hero (the flagship film looping, muted, its receipt under it), how it works in three
    steps with the real commands, the gallery from site/content/xray.json with a filter by kind and by theme, and
    Lane 2: how anyone adds an X-ray or a mechanism, what is checked before it appears."""
    page = XRAY_PAGE
    entries = xray_entries()
    hero = next(e for e in entries if e["id"] == XRAY["hero"])
    # the hero loops a silent cut when the entry names one ("loop"), else the film itself, muted
    hvideo = xray_media(site, hero.get("loop", "")) or xray_media(site, hero.get("video", ""))
    hposter = xray_media(site, hero.get("poster", ""))
    if hvideo:
        screen = ('<video class="teaser" muted loop playsinline preload="auto"%s aria-label="%s, muted"><source src="%s" type="video/mp4"></video>'
                  % (' poster="%s"' % rel(page, hposter) if hposter else "", esc(hero["title"]), rel(page, hvideo)))
    elif hposter:
        screen = '<img src="%s" alt="%s">' % (rel(page, hposter), esc(hero["title"]))
    else:
        screen = xray_blank(hero)
    hlive = xray_media(site, hero.get("live", "")) if hero.get("receipt") else None
    hero_live = ('<button class="btn primary xlive xlive-hero" type="button" data-live="%s" data-ratio="%s" data-title="%s" aria-pressed="false">Try it live</button>'
                 % (rel(page, hlive), "9/16" if hero.get("aspect") == "9:16" else "16/9", esc(hero["title"]))) if hlive else ""
    embed_src = REPO / "skills" / "showtime" / "runtime" / "xray-live" / "embed.js"
    embed_tag = ""
    if embed_src.is_file():
        ed = site.out / "xray" / "embed.js"
        ed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(embed_src, ed)
        embed_tag = '<script src="%s" defer></script>' % rel(page, "xray/embed.js")
    guide = "docs/guides/xray.html"
    guide_href = rel(page, guide) if guide in site.pages.values() else rel(page, "docs/workflows/xray.html")
    repo = site.repo
    form = ("https://github.com/%s/issues/new?template=xray-gallery.yml" % esc(repo)) if repo else ""
    contrib = rel(page, "docs/contributing.html") + "#add-an-x-ray-mechanism"
    library = site.gh("skills/showtime/library/xray", is_dir=True)
    kinds = XRAY.get("kinds", [])
    n_done = sum(1 for e in entries if e.get("receipt"))

    def tabs(group: str, label: str, items: List[Tuple[str, str]]) -> str:
        return ('<div class="filters xfilter" role="group" aria-label="%s">%s</div>' % (esc(label), "".join(
            '<button class="tab xtab" type="button" data-xgroup="%s" data-x="%s" aria-pressed="%s">%s<span class="c">%d</span></button>'
            % (group, k, "true" if k == "all" else "false", esc(n),
               len(entries) if k == "all" else sum(1 for e in entries if e.get(group) == k))
            for k, n in items)))
    filters = (tabs("kind", "Filter by kind", [("all", "All")] + [(k["id"], k["name"]) for k in kinds])
               + tabs("theme", "Filter by theme", [("all", "Any theme"), ("dark", "Dark"), ("light", "Light")]))
    cards = "".join(xray_card(site, page, e) for e in entries)
    touches = XRAY.get("touch", [])
    touch = ("""<section class="section" id="touch"><div class="wrap">
<div class="section-head"><h2 class="title" id="touch-a-living-diagram">No clip? Touch a living diagram</h2>
<p class="lede">The same drawings, with no video: a living diagram you type on, press and drag. Each one is a single
offline file made by <code>showtime export html --interactive</code>, live right here.</p></div>
<div class="films three xgrid">%s</div></div></section>
""" % "".join(touch_card(site, page, e) for e in touches)) if touches else ""
    body = """<section class="house xhero"><div class="wrap">
<div class="hero-head"><div><p class="xkicker">X-ray</p><h1 class="title">See inside a real thing, in time with its own sound.</h1>
<p class="lede">Film something doing its thing. showtime finds every event in the clip's sound, draws the inside moving on those
exact frames, on the object as the camera moves or beside it, and proves it with a receipt.</p></div>
<div class="actions">{hero_live}<a class="btn {make_cls}" href="#how">Make your own</a><a class="link-arrow" href="#gallery">The gallery <span>→</span></a></div></div>
<div class="screen lights xscreen">{screen}</div>
<p class="xreceipt xreceipt-hero">{check}{receipt}</p>
<p class="credit">{title}. {credit}. The receipt is <code>showtime xray verify</code> reading the finished film: the sync marker
on every frame against the events, and its audio against the original clip.</p>
</div></section>

<section class="section" id="how"><div class="wrap">
<div class="section-head"><h2 class="title" id="how-it-works">How it works</h2>
<p class="lede">Three commands, or one sentence to your agent: “X-ray this clip of my typewriter, drawn on the machine.”
It runs these for you, looks at the frames and tells you what it measured and what it drew.</p></div>
<ol class="xsteps">
<li><span class="xn">1</span><h3>Film it, then measure it</h3><p>A real thing doing its thing, with its sound: a typewriter typing, a
music box playing. A phone is fine. Every event in the sound gets its time and its frame; <code>--track</code> follows the object as
the camera moves.</p>{cmd1}</li>
<li><span class="xn">2</span><h3>Draw the inside</h3><p>Pick a mechanism from the library and a look: see-through on the object,
beside the clip, or a living diagram; dark like a radiograph or light like a blueprint. Each strike peaks on its event's frame.</p>
{cmd2}</li>
<li><span class="xn">3</span><h3>Verify it</h3><p>The finished film is read back frame by frame and its sound is matched to the
clip's. The line it prints goes on the end card and under the film wherever you post it.</p>
{cmd3}</li>
</ol>
<div class="facts xfacts"><div><h3>See-through</h3><p>The inside drawn on the object itself, inside its outline, as the camera moves. Objects only, never people.</p></div>
<div><h3>Beside it, or as a diagram</h3><p>When the object will not hold still, the inside sits beside the clip, or as an isometric living diagram.</p></div>
<div><h3>Music from the sound</h3><p>Pitches, key and tempo from an instrument's sound: a score for a piano, a tab for a guitar, a drum sheet for a kit.</p></div>
<div><h3>Honest about what is drawn</h3><p>On screen: what was measured (event times, counts, what the clip shows) and what was drawn (a generic mechanism of that kind).</p></div></div>
</div></section>

<section class="section" id="gallery"><div class="wrap">
<div class="section-head"><h2 class="title" id="the-gallery">The gallery</h2>
<p class="lede">Ours and yours. Every finished film carries its receipt, and every one can be copied: the commands are under it and
its mechanism is in the library.</p></div>
<div class="xfilters">{filters}</div>
<p class="count xcount" aria-live="polite">{n} films</p>
<div class="films three xgrid">{cards}</div>
<p class="note xnote">{n_done} finished, {n_pending} in the works. A film that is not here yet shows its poster or a plain card until its
receipt and its credit are in.</p>
</div></section>

{touch}<section class="section" id="lane-2"><div class="wrap">
<div class="section-head"><h2 class="title" id="add-yours">Lane 2: add yours</h2>
<p class="lede">The library grows with every verified X-ray. Post a film to the gallery, or add a mechanism so everyone can draw
that object; we post ours the same way, and every entry is there to copy.</p></div>
<div class="split xlane" style="margin-top:0">
<div><h3>Post your X-ray</h3>
<p>Make it with the three commands above, on a clip you filmed yourself or one under a Creative Commons license. Then open the
gallery form with the film's link, the object, the mechanism you used (or the new one you wrote), the verify line pasted as
it printed, and the clip's credit and license.</p>
<p>{form_link}</p></div>
<div><h3>Add a mechanism</h3>
<p>A new object starts as a copy of the closest entry in the {library_link}. Open a pull request that adds one folder:</p>
<pre class="xtree"><code>skills/showtime/library/xray/&lt;object&gt;/
  mechanism.js   # its parts, four anchors, draw(k)
  diagram.js     # optional: the living-diagram scene
  README.md      # parts, what an event moves, measured vs drawn,
                 # "Verified on" + the receipt + the clip credit</code></pre>
<p><a class="link-arrow" href="{contrib}">The pull request checklist <span>→</span></a></p></div></div>
<div class="facts xchecks"><div><h3>The receipt</h3><p>We run <code>showtime xray verify</code> on the film: every event on its frame and the audio
within 20 ms of the clip. A film without its line does not appear.</p></div>
<div><h3>The credit</h3><p>Your own footage, or a clip with a license that allows it (CC0, CC BY, CC BY-SA) and its credit line. No license
found, no entry.</p></div>
<div><h3>Objects only</h3><p>An inside is drawn over machines and instruments, never over people. A person in the frame gets the
beside-the-clip layout.</p></div>
<div><h3>Copyable</h3><p>Each entry lists the commands that made it and links its mechanism, so anyone can make their own from
it with <code>showtime new xray &lt;dir&gt; --mechanism &lt;object&gt;</code>.</p></div></div>
<p class="more"><a class="link-arrow" href="{guide}">The X-ray guide: film it, pick a mechanism, music and drums, verify, share <span>→</span></a></p>
</div></section>
{embed_tag}
""".format(screen=screen, check=ICON_CHECK, hero_live=hero_live, make_cls="ghost" if hero_live else "primary", embed_tag=embed_tag, receipt=xray_receipt(hero["receipt"]), title=esc(hero["title"]), credit=xray_credit(hero, posted=False),
           cmd1=xray_cmds(["showtime xray analyze clip.mp4 --job xray-typewriter"]),
           cmd2=xray_cmds(["showtime new xray xray-typewriter/project --mechanism typewriter --theme dark",
                           "showtime render xray-typewriter/project --job xray-typewriter"]),
           cmd3=xray_cmds(["showtime xray verify xray-typewriter"]),
           filters=filters, cards=cards, n=len(entries), n_done=count_words(n_done), n_pending=count_words(len(entries) - n_done).lower(),
           form_link=('<a class="btn primary" href="%s">Post an X-ray to the gallery</a>' % form) if form
           else "The gallery form: <code>.github/ISSUE_TEMPLATE/xray-gallery.yml</code> in the repository.",
           library_link=('<a href="%s">mechanism library</a>' % esc(library)) if library else "mechanism library (<code>skills/showtime/library/xray/</code>)",
           contrib=contrib, guide=guide_href, touch=touch)
    missing = [e["id"] for e in entries if e.get("receipt") and not xray_media(site, e.get("video", ""))]
    write(site, page, shell(site, page, "X-ray", body, "xray",
                            "Film a real thing doing its thing: showtime draws its inside moving on the exact frames its own sound "
                            "says, and proves it with a receipt. A gallery of verified X-rays, and how to add yours."))
    site.search.append(built_page_entry(site, "X-ray", page))
    print("x-ray: %d entries (%d finished); films not found in this build, shown as posters or plain cards: %s"
          % (len(entries), n_done, ", ".join(missing) or "none"))


# ----------------------------------------------------------------------------------------------- landing

def released(text: Optional[str] = None, version: str = "") -> List[Tuple[str, str, str]]:
    """The RELEASED versions in docs/whats-new.md, newest first, as (version, its heading's id on the page, its text):
    every "## X.Y.Z" heading that is not marked unreleased and is not newer than `version` (the repo's). This feeds the
    landing's "New in" tile and the sidebar chip only: the What's new page renders the whole file, so notes written
    ahead of a release reach the public main together with the version bump."""
    version = version or VERSION
    if text is None:
        path = REPO / "docs" / "whats-new.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""

    def key(v: str):
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    out = []
    for m in re.finditer(r"^## (\d+\.\d+\.\d+)([^\n]*)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        if "unreleased" in m.group(2).lower() or (re.match(r"\d+\.\d+\.\d+", version) and key(m.group(1)) > key(version)):
            continue
        out.append((m.group(1), slugify(m.group(1) + m.group(2), {}), m.group(3)))
    return out


def latest_release(limit: int = 5, text: Optional[str] = None, version: str = "") -> Tuple[str, str]:
    """(version, blurb) of the newest released version in docs/whats-new.md (released()), so the landing's "New in"
    box follows the page it links to: the titles of its "###" sections."""
    for ver, _hid, body in released(text, version):
        titles = re.findall(r"^### (.+)$", body, re.M)
        return ver, "; ".join(titles[:limit]) + ("; and more." if len(titles) > limit else ".")
    return version or VERSION, "See what changed."


def release_series(vers: Optional[List[Tuple[str, str, str]]] = None) -> str:
    """The major.minor of the newest released version in docs/whats-new.md ("0.4"): what "New in" means."""
    vers = released() if vers is None else vers
    return ".".join((vers[0][0] if vers else VERSION).split(".")[:2])


def new_name_problem(name: str, series: str) -> str:
    """Why gallery.json's "New in" name (the badges, the last tab, the landing tile's link) does not match the
    release series the tile is titled with, or "" when it does. After a release such as 0.5.0 the two would disagree
    with nothing failing: the build stops instead, until gallery.json's "new" block names the new release's examples."""
    if name.endswith(" " + series):
        return ""
    return ('site/content/gallery.json "new" is named %r, but the newest release in docs/whats-new.md is %s: rename it '
            '"New in %s" and list that series\' examples (its "examples" and "landing"), or the landing tile and the '
            'gallery\'s badges would name different releases' % (name, series, series))


def new_tile(site: Site, page: str, exs, blurb: str) -> str:
    """The landing's "New in 0.4" tile, low on the page: the newest release's features in one line, links to each
    released 0.4.x section of What's new and to the gallery's New tab, and a few of the new examples as proof."""
    vers = released()
    series = release_series(vers)
    mine = [(v, hid) for v, hid, _b in vers if v.startswith(series + ".")]
    notes = " and ".join('<a href="docs/whats-new.html#%s">%s</a>' % (hid, esc(v)) for v, hid in mine)
    by = {e["num"]: e for e in exs}
    picks = [by[n] for n in GALLERY.get("new", {}).get("landing", []) if n in by]
    thumbs = "".join('<a href="%s"><img src="%s" alt="%s" loading="lazy" decoding="async"><span><span class="n">%s</span> \u00b7 %s</span></a>'
                     % (rel(page, "examples/%s.html" % e["folder"]), preview_assets(site, page, e)[0], esc(e["alt"]), esc(ex_label(e)), esc(e["title"]))
                     for e in picks)
    n_new = sum(1 for e in exs if e["num"] in NEW_IDS)
    return ('<div class="new"><div class="new-head"><h3>New in %s</h3><p>What\u2019s new in %s \u00b7 '
            '<a href="gallery.html#%s">All %s new examples <span aria-hidden="true">\u2192</span></a></p></div><p>%s</p>%s</div>'
            % (esc(series), notes or '<a href="docs/whats-new.html">%s</a>' % esc(series), esc(GALLERY.get("new", {}).get("id", "new")),
               count_words(n_new).lower(), esc(("In %s: %s" % (vers[0][0], blurb)) if vers else blurb), '<div class="new-films">%s</div>' % thumbs if thumbs else ""))


# ----------------------------------------------------------------------------------------------- how it's built

HARNESS_PAGE = "harness/index.html"
HARNESS_SRC = SITE / "content" / "harness.html"   # the page's body; its first line sets ARTICLE_URL
HARNESS_MEDIA = "examples/_harness"               # loops, posters, the 0.4.3 film and the link-preview card
HARNESS_TITLE = "Many hands, one yes: a guide to harness engineering"
ARTICLE_URL = re.compile(r"\A<!--\s*ARTICLE_URL=(\S+)\s*-->\n")


def build_harness(site: Site) -> None:
    """harness/: the harness manual, the crew's operating manual in its own design (static/harness.css, scoped to
    .harness, and static/harness.js) inside the site's header and footer. Its media come from the examples tree,
    like the hero teaser: media/NAME in the source is examples/_harness/NAME."""
    page = HARNESS_PAGE
    text = HARNESS_SRC.read_text(encoding="utf-8")
    m = ARTICLE_URL.match(text)
    if not m:
        sys.exit("site/build.py: %s must start with <!-- ARTICLE_URL=https://... -->" % HARNESS_SRC.relative_to(REPO))
    body = re.sub(r"\A\s*<!--.*?-->\s*", "", text[m.end():], count=1, flags=re.S)   # the note for editors
    body = body.replace("{{ARTICLE_URL}}", esc(m.group(1)))

    def media(mo: "re.Match[str]") -> str:
        src = src_path("%s/%s" % (HARNESS_MEDIA, mo.group(2)))
        if not src.is_file():
            sys.exit("site/build.py: the harness page needs %s/%s" % (HARNESS_MEDIA, mo.group(2)))
        return '%s="%s"' % (mo.group(1), rel(page, site.copy_asset(src)))
    body = re.sub(r'\b(src|poster)="media/([^"/]+)"', media, body)
    if "{{" in body or 'media/' in re.sub(r'="\.\./a/[^"]*"', "", body):
        sys.exit("site/build.py: %s has a placeholder or media reference the build did not fill" % HARNESS_SRC.name)
    desc = ("How Favio V\u00e1zquez and a crew of AI agents build and ship showtime, an open-source video studio for coding "
            "agents: the studio map, the crew, the gates, one day replayed, and the scars that wrote the rules.")
    body += '<script src="%s" defer></script>\n' % rel(page, "static/harness.js")
    write(site, page, shell(site, page, HARNESS_TITLE, body, desc=desc, og_title=HARNESS_TITLE,
                            og_image=src_path(HARNESS_MEDIA + "/cover-1200x630.jpg"), og_size=(1200, 630),
                            head='<link rel="stylesheet" href="%s">' % rel(page, "static/harness.css")))
    site.search.append(built_page_entry(site, HARNESS_TITLE, page))   # its static text: the sections' heads and prose


def build_landing(site: Site, exs) -> None:
    page = "index.html"
    hero_cfg = CONFIG.get("hero") or {}
    launch = hero_cfg.get("folder", "examples/_launch")
    poster = rel(page, site.copy_asset(src_path(hero_cfg.get("poster", "assets/readme/launch-poster-plain.jpg"))))
    tmp4 = rel(page, site.copy_asset(src_path(launch + "/teaser-16x9.mp4")))
    twebm = rel(page, site.copy_asset(src_path(launch + "/teaser-16x9.webm")))
    film, film_fb = site.media(launch + "/" + hero_cfg.get("film", "launch-16x9.mp4"), launch.split("/")[-1])
    length = esc(hero_cfg.get("length", "0:40"))
    if film:
        watch = ('<button class="watch" type="button" data-film="%s" data-poster="%s" data-label="%s">%s<span>Watch the film</span><em>%s, sound on</em></button>'
                 % (rel(page, film), poster, esc(hero_cfg.get("label", "The showtime launch film")), ICON_PLAY, length))
    else:
        watch = ('<a class="watch" href="%s">%s<span>Watch the film</span><em>%s, sound on</em></a>' % (esc(film_fb or "#"), ICON_PLAY, length))
    credit = hero_cfg.get("credit") or ('The launch film: every frame is from a real showtime example. Music: \u201cWith These Hands\u201d by '
                                        'Scott Buckley, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.')
    hero = ('<div class="screen lights"><video class="teaser" muted loop playsinline preload="auto" poster="%s" aria-hidden="true">'
            '<source src="%s" type="video/webm"><source src="%s" type="video/mp4"></video>%s</div>' % (poster, twebm, tmp4, watch))
    teaser = [e for e in exs if e["num"] in ("02", "12", "17", "19")]
    _new_ver, new_text = latest_release()
    new = new_tile(site, page, exs, new_text)
    # X-ray: the flagship's poster (copied by build_xray), its receipt and a way to the page
    xhero = next(e for e in xray_entries() if e["id"] == XRAY["hero"])
    xposter = xray_media(site, xhero.get("poster", ""))
    xpic = ('<img src="%s" alt="%s" loading="lazy" decoding="async">' % (rel(page, xposter), esc(xhero["title"]))
            if xposter else xray_blank(xhero))
    body = """<section class="house"><div class="wrap">
<div class="hero-head"><div><h1 class="title">Describe a video. Your agent directs. Your machine renders.</h1>
<p class="lede">showtime is a local video studio for your coding agent: motion graphics, voice-over, music, captions and footage editing
from one sentence, with no cloud AI services, no API keys and no uploads. It works in Claude Code, Codex, Cursor, Devin and OpenCode,
and in any agent that supports <a href="https://agentskills.io">Agent Skills</a>.</p></div>
<div class="actions"><a class="btn primary" href="docs/guides/first-video.html">Get started</a><a class="link-arrow" href="gallery.html">See the examples <span>→</span></a></div></div>
{hero}
<p class="credit">{credit}</p>
</div></section>

<section class="section" id="start"><div class="wrap">
<div class="section-head"><h2 class="title">One sentence in, a finished video out</h2>
<p class="lede">Your agent states its assumptions, shows you a first look, renders on your machine and checks the result before it
calls the video done.</p></div>
{pipeline}
<div class="split" id="works-with"><div><h3>Install it in your agent</h3>
<p>You need <a href="https://docs.astral.sh/uv/">uv</a> and <a href="https://nodejs.org">Node.js</a> 24 or 22 LTS (20 or newer works).
The first request checks what is missing and tells you the size and time, about 0.5 to 0.75 GB to download (1.4 to 1.8 GB in
<code>~/.showtime</code> once installed) and 2 to 6 minutes, then runs setup once you say yes. Bigger pieces, like the transcription model (Parakeet), come the first time a video needs them.</p>
<p>Every request gets its own folder with <code>final.mp4</code>, a poster, captions, exports and share copy. Nothing is overwritten.</p>
<p><a class="link-arrow" href="docs/agents.html">Exact steps for Claude Code, Codex, Cursor, Devin, OpenCode and more <span>→</span></a></p></div>
<div class="copy install"><pre><code># Claude Code
/plugin marketplace add {market}
/plugin install showtime@showtime

# any agent that supports Agent Skills
npx skills add {market}

Make a 20-second launch video for this repo, with a voice-over and upbeat music.</code></pre></div></div>
</div></section>

<section class="section" id="showing"><div class="wrap">
<div class="section-head"><h2 class="title">Now showing</h2>
<p class="lede">Each of these came from one request. Hover to preview; play for sound.</p></div>
<div class="films">{teaser}</div>
<p class="more"><a class="link-arrow" href="gallery.html">All {nexs} examples <span>→</span></a></p>
</div></section>

<section class="section" id="xray"><div class="wrap">
<div class="xland"><a class="xland-film" href="{xpage}" aria-label="The X-ray page">{xpic}</a>
<div><p class="xkicker">X-ray</p><h2 class="title">See inside a real thing, in time with its own sound</h2>
<p class="lede">Film a typewriter typing or a music box playing. showtime draws its inside moving on the exact frames the clip's sound
says, on the object as the camera moves or beside it, and proves it with a receipt.</p>
<p class="xreceipt">{xcheck}{xreceipt}</p>
<p class="more" style="margin-top:24px"><a class="link-arrow" href="{xpage}">The X-ray gallery, and how to add yours <span>→</span></a></p></div></div>
</div></section>

<section class="section" id="crew"><div class="wrap">
<div class="section-head"><h2 class="title">A crew, when you want one</h2>
<p class="lede">Your agent can cast ten specialist sub-agents. Every finished video gets a critic by default; say "lean" to skip it (a video you will publish still gets one).
Studio work brings in the whole company.</p></div>
{cast}
<p class="more"><a class="link-arrow" href="crew.html">Meet the crew <span>→</span></a></p>
</div></section>

<section class="section" id="local"><div class="wrap">
<div class="section-head"><h2 class="title">Everything renders on your machine</h2>
<p class="lede">showtime adds no cloud service of its own. Every model and tool is downloaded once; after that it goes online only
when you ask for something from the web.</p></div>
{runs}
<div class="facts"><div><h3>Every shape</h3><p>16:9, 1:1 and 9:16, with platform exports, posters, captions and README loops.</p></div>
<div><h3>Videos that are web pages</h3><p>One HTML file per video, playing offline, with chapters, keyboard control, questions that
pause and ask, and range links like <code>#t=10-20</code>. <a href="gallery.html#html-videos">See one live</a>.</p></div>
<div><h3>Checked before it is done</h3><p><code>showtime qa</code> checks loudness, black or frozen frames, captions and platform specs.
A hearing pass flags music over the voice, long silences, level jumps at cuts and sound cut off at the end.</p></div>
<div><h3>Notes on the finished video</h3><p><code>showtime review open</code> plays the render on a local page. Click a spot on the
frame and type a note; your agent reads it, fixes and replies. <a href="docs/review.html#6-notes-on-the-finished-video">How it works</a>.</p></div>
<div><h3>Systems that explain themselves</h3><p><code>showtime new diagram</code> draws how something works as a figure that
builds over time: parts arrive in order, flows and labels move through them. <a href="docs/workflows/diagram.html">The guide</a>.</p></div>
<div><h3>Figures people poke</h3><p>The same diagram exports as one offline page with no player: hover a part, pick a step, turn
a knob and the numbers answer. <a href="examples/_diagram.html#live-figure">Try one live</a>.</p></div>
<div><h3>A film of your agent's session</h3><p><code>showtime recap</code> turns a Claude Code session into a short film of what
the agent did, from allow-listed facts only. <a href="examples/_recap.html">See one</a>.</p></div>
<div><h3>A failing test, as a video</h3><p><code>showtime repro</code> turns a failing Playwright test into a narrated
bug-report video and a summary for the issue. <a href="examples/_repro.html">See one</a>.</p></div>
{new}</div>
<p class="more"><a class="link-arrow" href="docs/index.html">Read the docs <span>→</span></a></p>
</div></section>
""".format(hero=hero, credit=credit, new=new, market=esc(site.repo or CONFIG.get("marketplace", "FavioVazquez/showtime")),
           pipeline=art(site, page, "diagrams/pipeline", "How showtime works: one sentence, your agent directs, a first look, a local render, showtime qa, an MP4 and an HTML video."),
           teaser="".join(card(site, page, e, show_what=False) for e in teaser), nexs=len(exs),
           runs=art(site, page, "diagrams/runs-where", "What runs where: the director in your coding agent, the studio on your machine; the web only when you ask."),
           cast=art(site, page, "crew/cast", "The crew: ten illustrated cards, all optional."),
           xpage=rel(page, XRAY_PAGE), xpic=xpic, xcheck=ICON_CHECK, xreceipt=xray_receipt(xhero["receipt"]))
    write(site, page, shell(site, page, "showtime · a local video studio for your coding agent", body, "home"))


# ----------------------------------------------------------------------------------------------- share tags, sitemap, llms.txt

SOCIAL_IMAGE = "assets/brand/social/github-social-preview.png"
SHARE_TAG = re.compile(r'<meta\s+(?:property|name)="(?:og|twitter):[^"]*"\s+content="[^"]*"\s*/?>\s*'
                       r'|<link\s+rel="canonical"\s+href="[^"]*"\s*/?>\s*', re.I)


def share_tags(title: str, desc: str, url: str, image: str, size: Optional[Tuple[int, int]] = None) -> str:
    """Link-preview tags in the export's own form (shareMeta in skills/showtime/scripts/lib/export/share.mjs), and a
    canonical link when the address is known."""
    def m(k: str, v: str, attr: str = "property") -> str:
        return '<meta %s="%s" content="%s">' % (attr, k, esc(v))
    out = [m("og:type", "website"), m("og:title", title)]
    if desc:
        out.append(m("og:description", desc))
    if url:
        out.append(m("og:url", url))
    if image:
        out.append(m("og:image", image))
        if size:
            out += [m("og:image:width", str(size[0])), m("og:image:height", str(size[1]))]
        out.append(m("og:image:alt", title))
    out.append(m("twitter:card", "summary_large_image" if image else "summary", "name"))
    if url:
        out.append('<link rel="canonical" href="%s">' % esc(url))
    return "\n".join(out) + "\n"


def tag_html_video(text: str, url: str, desc: str, image: str, size: Optional[Tuple[int, int]] = None) -> str:
    """An HTML video page with link-preview tags for its address on the site. What its export already wrote wins
    where it can (a description, an absolute image); og:url and the canonical link are always the site's."""
    end = text.find("</head>")
    if end < 0:
        return text
    head = text[:end]
    have = {k.lower(): html.unescape(v) for k, v in
            re.findall(r'<meta\s+(?:property|name)="((?:og|twitter):[^"]*)"\s+content="([^"]*)"', head, re.I)}
    head = SHARE_TAG.sub("", head)
    tm = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    title = have.get("og:title") or (html.unescape(tm.group(1)).strip() if tm else "") or "showtime"
    if re.match(r"^https?://", have.get("og:image", "")):
        image = have["og:image"]
        w, h = have.get("og:image:width", ""), have.get("og:image:height", "")
        size = (int(w), int(h)) if w.isdigit() and h.isdigit() else None
    return head + share_tags(title, have.get("og:description") or desc, url, image, size) + text[end:]


def tag_html_videos(site: Site, exs: List[dict]) -> List[str]:
    """Link-preview tags on every HTML video the site copied under media/: the example's description and poster
    (else the page's own description and the site's social image), at the page's address on the site. The
    exports in the media release predate the export's own share tags (showtime.json "share")."""
    base = site_url(site.repo)
    by_folder = {e["folder"]: e for e in exs}
    done = []
    for dst, repo_rel in sorted(site.copied.items()):
        if not (dst.startswith("media/") and dst.endswith(".html")):
            continue
        parts = repo_rel.split("/")
        folder = parts[1] if len(parts) > 2 else ""
        p = site.out / dst
        text = p.read_text(encoding="utf-8", errors="surrogateescape")
        own = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', text[:max(text.find("</head>"), 0)], re.I)
        e = by_folder.get(folder)
        board = "studio-board" in dst
        if e:
            desc = describe("%s made with showtime, %s. %s" % (
                "The studio board of a video job, one HTML file," if board else "An interactive HTML video",
                ("example " + e["num"]) if e["num"].isdigit() else "a demo", what_sentence(e)))
        else:
            desc = describe(html.unescape(own.group(1))) if own else "An interactive HTML video made with showtime."
        # the poster beside the page's source (a series episode has its own), else the example's
        posters = [src_path(posixpath.join(posixpath.dirname(repo_rel), "poster.jpg"))]
        posters += [src_path("examples/%s/poster.jpg" % folder)] if folder else []
        poster = next((x for x in posters if x.is_file()), None)
        if poster is not None:
            img, size = site.copy_asset(poster), None
        else:
            img, size = site.copy_asset(REPO / SOCIAL_IMAGE), (1280, 640)
        p.write_text(tag_html_video(text, page_url(base, dst), desc, (base + img) if base else rel(dst, img), size),
                     encoding="utf-8", errors="surrogateescape")
        done.append(dst)
    return done


def write_sitemap(site: Site, extra: List[str]) -> int:
    """sitemap.xml: every page this build wrote, then the HTML videos (absolute URLs; none without a base URL)."""
    base = site_url(site.repo)
    pages = ["index.html"] + [p for p in site.written + extra if p != "index.html"]
    urls = list(dict.fromkeys(page_url(base, p) for p in pages)) if base else []
    (site.out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join("<url><loc>%s</loc></url>\n" % esc(u) for u in urls) + "</urlset>\n", encoding="utf-8")
    return len(urls)


def write_robots(site: Site) -> None:
    base = site_url(site.repo)
    (site.out / "robots.txt").write_text("User-agent: *\nAllow: /\n" + ("\nSitemap: %ssitemap.xml\n" % base if base else ""),
                                         encoding="utf-8")


def llms_txt(site: Site) -> str:
    """llms.txt (https://llmstxt.org): a short Markdown index for agents: what showtime is, how to install it, the key
    pages with one sentence each, and every guide by title, in the docs map's order (the agent's own map says which
    guide answers what)."""
    base = site_url(site.repo)
    market = site.repo or CONFIG.get("marketplace", "FavioVazquez/showtime")
    gh = "https://github.com/%s" % market

    def link(page: str, title: str = "", say: bool = True) -> str:
        t, d = site.described.get(page, (title or page, ""))
        return "- [%s](%s)%s" % (title or t, page_url(base, page) or page, (": " + d) if d and say else "")
    lines = ["# showtime", "", "> " + CONFIG.get("description", ""), "",
             "showtime %s is a local video studio for coding agents: motion graphics, voice-over, music, captions and "
             "footage editing from one sentence, rendered on the user's machine. It is an Agent Skill with an MCP "
             "server and a `showtime` command line. Every page below is rendered from Markdown in the repository, %s "
             "(the guides from `skills/showtime/references/`)." % (VERSION, gh), "",
             "## Install", "",
             "- Claude Code: `/plugin marketplace add %s`, then `/plugin install showtime@showtime`." % market,
             "- Any agent that supports Agent Skills: `npx skills add %s`." % market,
             link("docs/agents.html"),
             "- [llms-install.md](%s/blob/%s/llms-install.md): installing the MCP server, step by step, written for "
             "an agent." % (gh, site.branch), "",
             "## Start here", "",
             link("docs/guides/first-video.html", "Your first video"),
             link("docs/index.html", "Documentation map"),
             link("docs/troubleshooting.html", "When something goes wrong"),
             link("docs/glossary.html", "Glossary"),
             link("docs/whats-new.html", "What's new"),
             link("docs/faq.html", "Questions people ask"),
             link("docs/index-claude.html", "The agent's own map (the reference index)"),
             link("docs/skill.html", "SKILL.md"),
             link("gallery.html", "Examples"),
             link(XRAY_PAGE, "X-ray: a real clip with its inside drawn in sync, and the gallery")]
    skip = {"The crew's briefs", "Backstage"}
    listed = {"docs/index.html", "docs/index-claude.html", "docs/skill.html", "docs/agents.html", "docs/whats-new.html",
              "docs/faq.html", "docs/guides/first-video.html", "docs/troubleshooting.html", "docs/glossary.html"}
    for name, items in site.doc_groups:
        rows = [link(p, say=False) for _label, p in items if p not in listed and p in site.described]
        listed.update(p for _label, p in items)
        if rows and name not in skip:
            lines += ["", "## " + name, ""] + rows
    lines += ["", "## Optional", "", link("crew.html", "The crew"), link(HARNESS_PAGE, HARNESS_TITLE), link("docs/house-vocabulary.html", "House vocabulary (CONTEXT.md)"),
              link("docs/changelog.html"), link("docs/contributing.html")]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- main

def write(site: Site, page: str, text: str) -> None:
    p = site.out / page
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if page not in site.written:   # list each page once, however often it is written
        site.written.append(page)


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
    _groups, exs = parse_examples()   # the README's own groups are its page's; the site's are site/content/gallery.json
    problem = new_name_problem(NEW_NAME, release_series())
    if problem:
        sys.exit("site/build.py: " + problem)
    site.gallery = {e["folder"] for e in exs}
    build_docs(site, exs)
    build_gallery(site, exs)
    build_example_pages(site, exs)
    build_crew(site)
    build_harness(site)
    build_xray(site)
    build_landing(site, exs)
    videos = tag_html_videos(site, exs)
    nurls = write_sitemap(site, videos)
    write_robots(site)
    (out / "llms.txt").write_text(llms_txt(site), encoding="utf-8")
    site.search += [built_page_entry(site, "showtime", "index.html"), built_page_entry(site, "Examples", "gallery.html")]
    for e in site.search:   # the changelog is every change ever made: its many sections must not outrank the guides
        if e["u"] == "docs/changelog.html":
            e["w"] = 0.5
    (out / "search-index.js").write_text("window.SHOWTIME_SEARCH=" + json.dumps(site.search, ensure_ascii=False, separators=(",", ":")) + ";\n",
                                         encoding="utf-8")
    problems = check_search(site)
    if problems:
        sys.exit("site/build.py: the search index points at pages or anchors that do not exist:\n  " + "\n  ".join(problems))
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    nfiles = sum(1 for f in out.rglob("*") if f.is_file())
    print("site: %s  (%d files, %.1f MB)" % (out, nfiles, total / 1e6))
    print("examples: %s%s" % (EXAMPLES, (" (links: %s)" % EXAMPLES_REPO) if EXAMPLES_REPO else ""))
    print("repo: %s" % (repo or "(none: source links are plain text; set site/config.json \"repo\" or pass --repo)"))
    print("share: %s; link-preview tags on %d HTML video(s); sitemap.xml lists %d URL(s); robots.txt, llms.txt"
          % (site_url(repo) or "(no site_url: og:url, canonical links and the sitemap are left out)", len(videos), nurls))
    if site.missing_media:
        uniq = sorted(set(site.missing_media))
        print("videos not found in --media-from (their cards link to the release instead): %d" % len(uniq))
        for m in uniq[:40]:
            print("  " + m)
    problems = check_pages(out, site.written, site.h2_expect)
    if problems:
        sys.stdout.flush()
        for line in problems:
            print("site check: " + line, file=sys.stderr)
        sys.exit("site/build.py: the build check failed on %d page(s) (above)" % len({p.split(":")[0] for p in problems}))
    print("check: %d pages, each with one <title>, a footer and the h2 headings of its source" % len(site.written))


if __name__ == "__main__":
    main()
