"""Versioned benchmark pages for the companion site.

Each benchmark report is a single self-contained HTML page kept out of this repository (it names the tools it
was compared with): it is the `index.html` asset of a release named `benchmark-report-vX.Y.Z`. The pages
workflow downloads every one of them into a folder per version and runs this script, which writes

    <out>/vX.Y.Z/index.html   every version, kept at its own address
    <out>/index.html          the latest version, served at /benchmark/ (links rewritten for that folder)
    <out>/versions.json       the list, newest first

and adds a small bar to the top of each page that names the version shown and links to the others, and to the
latest benchmark rounds written up in this repository (LATEST_ROUNDS: rounds 5 and 6 ran on 0.4.0 and have no
report page of their own).

usage: python site/tools/benchmark_pages.py --src _bench --out _site/benchmark [--site-root ../] [--repo owner/name]
       (_bench/<version>/index.html, e.g. _bench/v0.3.0/index.html)
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple

VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
LINK_RE = re.compile(r"""(\s(?:href|src)=)(["'])([^"']*)\2""", re.I)
BAR_MARK = "<!-- showtime benchmark versions -->"
# The newest rounds, a Markdown write-up in the repository (path, link text). The bar links it on every page.
LATEST_ROUNDS = ("benchmarks/rounds/r5-allout.md", "Newer: rounds 5 and 6 (0.4.0)")

BAR_CSS = """<style id="stbv-style">
.stbv{--stbv-bg:#FBF6EE;--stbv-ink:#1B1411;--stbv-muted:#6E5F56;--stbv-line:rgba(27,20,17,.14);--stbv-on:#1B1411;--stbv-on-ink:#FBF6EE;
  background:var(--stbv-bg);color:var(--stbv-ink);border-bottom:1px solid var(--stbv-line);
  font:500 14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;position:relative;z-index:60}
@media (prefers-color-scheme:dark){.stbv{--stbv-bg:#15100E;--stbv-ink:#F3EADD;--stbv-muted:#A99A8B;--stbv-line:rgba(243,234,221,.16);
  --stbv-on:#F3EADD;--stbv-on-ink:#15100E}}
.stbv-in{max-width:1080px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:12px;min-width:0}
.stbv a{color:inherit;text-decoration:none}
.stbv-home{font-weight:700;letter-spacing:-.01em;white-space:nowrap}
.stbv-lab{color:var(--stbv-muted);white-space:nowrap}
.stbv-list{display:flex;gap:6px;overflow-x:auto;min-width:0;scrollbar-width:none;margin-left:auto}
.stbv-list::-webkit-scrollbar{display:none}
.stbv-v{padding:4px 10px;border:1px solid var(--stbv-line);border-radius:999px;white-space:nowrap;font-variant-numeric:tabular-nums}
.stbv-v:hover,.stbv-v:focus-visible{border-color:var(--stbv-ink)}
.stbv-v[aria-current="page"]{background:var(--stbv-on);color:var(--stbv-on-ink);border-color:var(--stbv-on)}
.stbv-v small{font-weight:400;opacity:.75;margin-left:4px}
.stbv .stbv-note{white-space:nowrap;text-decoration:underline;text-underline-offset:3px;color:var(--stbv-muted)}
.stbv .stbv-note:hover,.stbv .stbv-note:focus-visible{color:var(--stbv-ink)}
@media (max-width:420px){.stbv-lab{display:none}}
@media (max-width:640px){.stbv-in{flex-wrap:wrap}.stbv-note{order:3;flex-basis:100%}}
</style>"""


def vkey(v: str) -> Tuple[int, int, int]:
    m = VERSION_RE.match(v)
    return tuple(int(x) for x in m.groups()) if m else (-1, -1, -1)


def versions(src: Path) -> List[str]:
    """Version folders with a report, newest first."""
    found = [d.name for d in src.iterdir() if d.is_dir() and VERSION_RE.match(d.name) and (d / "index.html").is_file()]
    return sorted(found, key=vkey, reverse=True)


def rounds_link(repo: str, branch: str = "main") -> str:
    """The bar's link to the newest rounds (LATEST_ROUNDS) on GitHub; '' without a repository."""
    if not repo:
        return ""
    path, text = LATEST_ROUNDS
    return ('<a class="stbv-note" href="%s" title="The write-up of the newest rounds: method, settings, results and limits">'
            '%s</a>' % (html.escape("https://github.com/%s/blob/%s/%s" % (repo, branch, path)), html.escape(text)))


def bar(current: str, all_v: List[str], prefix: str, site_root: str, note: str = "") -> str:
    """The version bar. `prefix` leads from the page's folder to /benchmark/ ("../" from a version folder); `note`
    is rounds_link()'s link, or ''."""
    items = []
    for i, v in enumerate(all_v):
        cur = ' aria-current="page"' if v == current else ""
        tag = "<small>latest</small>" if i == 0 else ""
        href = (prefix or "./") if i == 0 else "%s%s/" % (prefix, v)
        items.append('<a class="stbv-v" href="%s"%s>%s%s</a>' % (html.escape(href), cur, html.escape(v), tag))
    return ('%s<nav class="stbv" aria-label="Benchmark report versions"><div class="stbv-in">'
            '<a class="stbv-home" href="%s">showtime</a><span class="stbv-lab">Benchmark report</span>'
            '<div class="stbv-list">%s</div>%s</div></nav>' % (BAR_MARK, html.escape(site_root), "".join(items), note))


def document(page: str) -> str:
    """A report published as a page fragment (no <html>/<body>, e.g. an artifact page) gets a document around it:
    standards mode, UTF-8 and a phone viewport. Its <title>, <meta>, <link> and <style> still apply from <body>."""
    if re.search(r"<body[\s>]", page, re.I):
        return page
    head = '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
    if not re.search(r'<meta\s+name=["\']viewport', page, re.I):
        head += '<meta name="viewport" content="width=device-width,initial-scale=1">'
    return head + "</head><body>\n" + page + "\n</body></html>\n"


def inject(page: str, nav: str) -> str:
    """Put the bar's style in <head> and the bar first in <body>; a page built earlier gets its bar replaced."""
    page = document(re.sub(r'<style id="stbv-style">.*?</style>', "", page, flags=re.S))
    page = re.sub(re.escape(BAR_MARK) + r'<nav class="stbv".*?</nav>', "", page, flags=re.S)
    if re.search(r"</head>", page, re.I):
        page = re.sub(r"</head>", lambda m: BAR_CSS + m.group(0), page, count=1, flags=re.I)
    else:
        page = BAR_CSS + page
    m = re.search(r"<body[^>]*>", page, re.I)
    return page[:m.end()] + nav + page[m.end():]


def relink_for_parent(page: str, version: str) -> str:
    """Rewrite a version page's relative links so they still work one folder up (/benchmark/ instead of
    /benchmark/vX.Y.Z/): "../x" -> "x", "img.png" -> "vX.Y.Z/img.png". Anchors, absolute and data URLs stay."""
    def fix(m):
        url = m.group(3)
        if not url or url.startswith(("#", "/", "data:", "mailto:", "javascript:")) or re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
            return m.group(0)
        url = url[3:] if url.startswith("../") else "%s/%s" % (version, url[2:] if url.startswith("./") else url)
        return "%s%s%s%s" % (m.group(1), m.group(2), url, m.group(2))
    return LINK_RE.sub(fix, page)


def build(src: Path, out: Path, site_root: str = "../", repo: str = "") -> List[str]:
    all_v = versions(src)
    if not all_v:
        return []
    out.mkdir(parents=True, exist_ok=True)
    note = rounds_link(repo)
    for v in all_v:
        page = (src / v / "index.html").read_text(encoding="utf-8")
        (out / v).mkdir(parents=True, exist_ok=True)
        (out / v / "index.html").write_text(inject(page, bar(v, all_v, "../", "../" + site_root, note)), encoding="utf-8")
    latest = all_v[0]
    page = relink_for_parent((src / latest / "index.html").read_text(encoding="utf-8"), latest)
    (out / "index.html").write_text(inject(page, bar(latest, all_v, "", site_root, note)), encoding="utf-8")
    (out / "versions.json").write_text(json.dumps(
        [{"version": v, "path": "" if i == 0 else v + "/", "latest": i == 0} for i, v in enumerate(all_v)],
        indent=1) + "\n", encoding="utf-8")
    return all_v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="folder with one <version>/index.html per report")
    ap.add_argument("--out", required=True, type=Path, help="the site's benchmark folder, e.g. _site/benchmark")
    ap.add_argument("--site-root", default="../", help="the site's home, relative to /benchmark/ (default ../)")
    ap.add_argument("--repo", default="", help="owner/name for the link to the newest rounds (default: $GITHUB_REPOSITORY, "
                                               "then site/config.json repo)")
    a = ap.parse_args(argv)
    repo = a.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        try:
            repo = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8")).get("repo", "")
        except (OSError, ValueError):
            repo = ""
    if not a.src.is_dir():
        print("no benchmark reports (%s not found): /benchmark/ is not published" % a.src)
        return 0
    got = build(a.src, a.out, a.site_root, repo)
    print("benchmark pages: %s" % (", ".join(got) + " (latest %s)" % got[0] if got else "none found"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
