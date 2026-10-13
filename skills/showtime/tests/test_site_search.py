#!/usr/bin/env python3
"""Companion site search (site/build.py, site/static/app.js).

Asserted: the index text and the typed query are normalised by one rule (pr-video, SHOWTIME_MCP_TOOLS and #t= find
the text they came from; app.js uses the same character class as build.py), every h2/h3 section of a page is
indexed with its anchor (text far past the old 14,000-character cut included), the build-time check flags an anchor
a page does not have, a page indexed twice and a page never built, the agent's own map is indexed once as
docs/index-claude.html, and a real build of the site passes its check with the late sections searchable.

usage: python tests/test_site_search.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent.parent.parent
SITE = REPO / "site"

spec = importlib.util.spec_from_file_location("site_build", SITE / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

# a real build reads the gallery: examples/ in the development checkout, or a clone of the examples repository next
# to this one (site/config.json "examples_dir"); the public plugin repository has neither, and the build test skips
try:
    build.find_examples()
    NO_EXAMPLES = ""
except SystemExit:
    NO_EXAMPLES = "needs the examples folder (examples/ here, or a clone of %s at %s)" % (
        build.CONFIG.get("examples_repo", "the examples repository"), build.CONFIG.get("examples_dir", "../"))


def norm_query(q: str) -> str:
    """app.js norm(), with the character class read from app.js itself."""
    js = (SITE / "static" / "app.js").read_text(encoding="utf-8")
    sep = re.search(r"var SEP = /(.+?)/g;", js).group(1)
    return re.sub(r"\s+", " ", re.sub(sep, " ", q.lower())).strip()


def rank(index_path: Path, query: str) -> list:
    """The pages app.js's search lists for a query, in order, run in Node over the built index: the search block of
    app.js with a stub page (null when node is missing)."""
    node = shutil.which("node")
    if not node:
        return None
    js = (SITE / "static" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("var input = document.querySelector('.search input')"):js.rindex("})();")]
    block = block.replace("if (!input) return;", "")
    harness = (
        "var window = {}; eval(require('fs').readFileSync(%s, 'utf8'));\n"
        "var handlers = {}, base = '', safeSrc = function (x) { return x; };\n"
        "var input = { value: %s, addEventListener: function (n, f) { handlers[n] = f; } };\n"
        "var box = { innerHTML: '', hidden: true, querySelectorAll: function () { return []; } };\n"
        "var document = { querySelector: function (q) { return q === '.results' ? box : input; }, addEventListener: function () {}, "
        "createElement: function () { return {}; }, head: { appendChild: function () {} } };\n"
        "(function () {\n%s\n handlers.input(); })();\n"
        "console.log(JSON.stringify((box.innerHTML.match(/href=\"[^\"]+\"/g) || []).map(function (h) { return h.slice(6, -1); })));"
        % (json.dumps(str(index_path)), json.dumps(query), block))
    cp = subprocess.run([node, "-e", harness], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr[-1500:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


class Normalise(unittest.TestCase):
    def test_one_rule_in_both_places(self):
        js = (SITE / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("var SEP = /%s/g;" % build.SEARCH_SEPARATORS, js, "app.js and build.py must share the rule")
        self.assertIn("SEARCH_SEPARATORS", js)

    def test_index_side(self):
        self.assertEqual(build.plain("Run `showtime pr-video` then **review-pack**"), "Run showtime pr video then review pack")
        self.assertEqual(build.plain("Set `SHOWTIME_MCP_TOOLS=all`."), "Set SHOWTIME MCP TOOLS=all .")
        self.assertEqual(build.plain("a range link, `video.html#t=1:05-1:20`"), "a range link, video.html t=1:05 1:20")
        self.assertEqual(build.plain("```\ncode-only\n```\n[the `question-beat`](components.md#question-beat)"),
                         "the question beat")

    def test_query_finds_index_text(self):
        text = build.plain("`showtime pr-video`, `showtime new --from-storyboard`, `SHOWTIME_MCP_TOOLS`, "
                           "`question-beat`, `video.html#t=10-20`, `showtime review-pack`").lower()
        for q in ("pr-video", "--from-storyboard", "SHOWTIME_MCP_TOOLS", "question-beat", "#t=", "review-pack",
                  "Review-Pack", "  pr - video "):
            nq = norm_query(q)
            self.assertTrue(nq)
            self.assertIn(nq, text, "%r (normalised %r) must find its text" % (q, nq))


class Sections(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-site-"))
        self.site = build.Site(self.tmp, [], "", None, "main")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_section_with_its_anchor(self):
        filler = "Plain words. " * 1500        # ~19,500 characters: past the old cut
        md = ("# Guide\n\nThe intro.\n\n## Essentials\n\nFirst part.\n\n### `review-pack` in short\n\nPack it.\n\n"
              "```\n## not a heading\n```\n\n## Later\n\n%s\n\n## Essentials\n\nThe last words: zebra crossing.\n" % filler)
        _, title, heads = self.site.render_md(md, REPO / "x.md", "docs/x.html")
        e = build.search_entry(self.site, title, "docs/x.html", md, heads)
        self.assertEqual(e["t"], "Guide")
        self.assertEqual([s[1] for s in e["s"]], ["", "essentials", "review-pack-in-short", "later", "essentials-1"])
        self.assertEqual(e["s"][0][2], "Guide The intro.")
        self.assertEqual(e["s"][2], ["review-pack in short", "review-pack-in-short", "Pack it."], "a fenced ## line is code, not a section")
        self.assertEqual(e["s"][4][2], "The last words: zebra crossing.")
        self.assertGreater(sum(len(s[2]) for s in e["s"]), 14000)

    def test_lead_goes_first(self):
        md = "# Ex\n\n## The request\n\nAsked.\n"
        _, _, heads = self.site.render_md(md, REPO / "x.md", "examples/x.html", drop_h1=True)
        e = build.search_entry(self.site, "Example 01: Ex", "examples/x.html", md, heads, lead="A prompt\nWhat it shows")
        self.assertEqual(e["s"][0], ["", "", "A prompt What it shows Ex"])
        self.assertEqual(e["s"][1], ["The request", "the-request", "Asked."])

    def test_check_flags_dead_anchors_twins_and_missing_pages(self):
        (self.tmp / "docs").mkdir()
        (self.tmp / "docs" / "a.html").write_text('<h2 id="here">Here</h2><p id="intro">x</p>', encoding="utf-8")
        self.site.search = [{"t": "A", "u": "docs/a.html", "s": [["", "", "x"], ["Here", "here", "y"]]}]
        self.assertEqual(build.check_search(self.site), [])
        self.site.search[0]["s"].append(["Gone", "story-and-craft", "z"])
        self.site.search.append({"t": "A again", "u": "docs/a.html", "s": [["", "", "x"]]})
        self.site.search.append({"t": "B", "u": "docs/b.html", "s": [["", "", "x"]]})
        problems = build.check_search(self.site)
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(any("docs/a.html#story-and-craft" in p and "no such anchor" in p for p in problems))
        self.assertTrue(any("twice" in p for p in problems))
        self.assertTrue(any("docs/b.html" in p and "not built" in p for p in problems))

    def test_agent_map_is_not_a_second_docs_index(self):
        pages = {page for src, page, _g in build.doc_sources()}
        self.assertNotIn("docs/index.html", pages)
        self.assertFalse(any(src.name == "index.md" and src.parent == build.REFS for src, _p, _g in build.doc_sources()))


class RealBuild(unittest.TestCase):
    """The whole site, without videos: the build's own check passes and long pages are searchable to the end."""

    @unittest.skipIf(bool(NO_EXAMPLES), NO_EXAMPLES)
    def test_build(self):
        out = Path(tempfile.mkdtemp(prefix="st-site-out-"))
        try:
            cp = subprocess.run([sys.executable, str(SITE / "build.py"), "--out", str(out), "--clean", "--no-previews",
                                 "--only", "99", "--max-html-mb", "0.01"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace", timeout=600)
            self.assertEqual(cp.returncode, 0, cp.stdout[-2000:] + cp.stderr[-2000:])
            raw = (out / "search-index.js").read_text(encoding="utf-8")
            index = json.loads(raw[len("window.SHOWTIME_SEARCH="):].rstrip().rstrip(";"))
            urls = [e["u"] for e in index]
            self.assertEqual(len(urls), len(set(urls)), "every page once")
            self.assertEqual([e["t"] for e in index if e["u"] == "docs/index.html"], ["Documentation map"])
            self.assertIn("docs/index-claude.html", urls)
            # the guides for people are searchable, section by section
            for g in sorted((REPO / "docs" / "guides").glob("*.md")):
                self.assertIn("docs/guides/%s.html" % ("index" if g.name == "README.md" else g.stem), urls)
            clips = next(e for e in index if e["u"] == "docs/guides/long-recording-to-clips.html")
            self.assertTrue(any(s[0] == "What happens" and s[1] and "edit moments" in s[2] for s in clips["s"]), clips["s"][:3])
            # the last section of review.md (long) is indexed and linked by its anchor
            review = next(e for e in index if e["u"] == "docs/review.html")
            src = (REPO / "skills/showtime/references/review.md").read_text(encoding="utf-8")
            last_words = build.plain(src.strip().splitlines()[-1])[-40:].lower()
            self.assertIn(last_words, review["s"][-1][2].lower())
            self.assertTrue(review["s"][-1][1])
            # the last release in the changelog is indexed too (it was cut at 14,000 characters)
            log = next(e for e in index if e["u"] == "docs/changelog.html")
            self.assertGreater(sum(len(s[2]) for s in log["s"]), 100000)
            self.assertTrue(any("0.1.0" in s[0] for s in log["s"]))
            # the landing and the gallery are searchable, and the changelog is weighed below the guides
            for page in ("index.html", "gallery.html"):
                self.assertIn(page, urls)
            land = next(e for e in index if e["u"] == "index.html")
            self.assertTrue(any("agent" in s[2].lower() for s in land["s"]))
            self.assertLess(log["w"], 1)
            # ranking, run through app.js: guides lead for a command, the changelog still wins a version number
            for q in ("doctor", "estimate"):
                hits = rank(out / "search-index.js", q)
                if hits is not None:
                    self.assertFalse(hits[0].startswith("docs/changelog.html"), (q, hits[:3]))
            hits = rank(out / "search-index.js", "0.4.0")
            if hits is not None:
                self.assertTrue(any(h.startswith("docs/changelog.html") for h in hits[:2]), hits[:4])
            # a landing hit links to its own section, not the install block that merely comes first
            anchors = {s[0]: s[1] for s in land["s"]}
            self.assertEqual(anchors.get("Now showing"), "showing")
            self.assertEqual(anchors.get("A crew, when you want one"), "crew")
            self.assertEqual(anchors.get("Everything renders on your machine"), "local")
            # no page opens on the YAML front matter of SKILL.md (it was one huge heading)
            skill = next(e for e in index if e["u"] == "docs/skill.html")
            self.assertFalse(any(s[0].startswith("name:") for s in skill["s"]), [s[0][:40] for s in skill["s"]][:3])
            self.assertNotRegex((out / "docs" / "skill.html").read_text(encoding="utf-8"), r'<h2 id="name-')
            # every docs page, the example pages and the docs map have Previous / Next to a page that was built
            for page in ["docs/index.html", "docs/agents.html", "docs/whats-new.html", "docs/faq.html", "docs/skill.html"] + [
                    u for u in urls if u.startswith("examples/")]:
                text = (out / page).read_text(encoding="utf-8")
                links = re.findall(r'<nav class="pager".*?</nav>', text, re.S)
                self.assertEqual(len(links), 1, page)
                for href in re.findall(r'href="([^"#]+)"', links[0]):
                    self.assertTrue((out / page).parent.joinpath(href).resolve().is_file(), (page, href))
            # one version: the footer and the landing's "New in" follow the repo
            ver = re.search(r'__version__\s*=\s*"([^"]+)"', (REPO / "skills/showtime/lib/st/__init__.py").read_text(encoding="utf-8")).group(1)
            self.assertIn("&nbsp; %s, MIT" % ver, (out / "index.html").read_text(encoding="utf-8"))
            # the docs proposal (0.4.2): Start here in four places, shelves, New in 0.4, act crumbs, See it done
            gallery = (out / "gallery.html").read_text(encoding="utf-8")
            if build.CONFIG.get("gallery_film") is None:   # null: the page opens on its intro, then the tabs
                self.assertNotIn('id="gallery-film"', gallery)
            self.assertNotIn("launch-film", gallery)
            tabs = re.findall(r'data-filter="([^"]+)"', gallery)
            self.assertEqual(tabs, ["all", "start-here", "explainers", "footage", "products", "code", "social", "looks", "new"])
            self.assertLess(gallery.index('id="shelf-start-here"'), gallery.index('id="shelf-explainers"'))
            start = gallery[gallery.index('id="shelf-start-here"'):gallery.index('id="shelf-explainers"')]
            self.assertEqual(re.findall(r"<h3><a [^>]*>([^<]+)</a></h3>", start), ["Launch video", "Narrated explainer", "Your footage, edited"])
            self.assertIn("Make a 20-second launch video", start, "the kind's name sits over the example's own request")
            self.assertEqual(gallery.count('<span class="badge">New in 0.4</span>'), 13)
            self.assertIn('<span class="spec">25 \u00b7 2:38</span>', gallery)
            self.assertIn("Thirty examples and five demos", gallery)
            landing = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn('<a class="btn primary" href="docs/guides/first-video.html">Get started</a>', landing)
            self.assertIn("<h3>New in 0.4</h3>", landing)
            self.assertIn('href="gallery.html#new"', landing)
            self.assertEqual(landing.count('<div class="new-films">'), 1)
            voice = (out / "docs" / "voice.html").read_text(encoding="utf-8")
            self.assertIn('<a href="../docs/index.html#act-iv--sound-and-voice">Act IV \u00b7 Sound and voice</a> / Voice</div>', voice)
            self.assertIn('<p class="see-it-done">See it done: <a href="../examples/02-explainer-heat-pump.html">', voice)
            self.assertIn("<h4>Start here</h4>", voice)
            # a page on a Choose your path card and in an act is named by its act
            self.assertIn("Act III \u00b7 Building the picture</a> / Components</div>",
                          (out / "docs" / "components.html").read_text(encoding="utf-8"))
            newest = re.search(r"^## (\d+\.\d+\.\d+)", (REPO / "docs" / "whats-new.md").read_text(encoding="utf-8"), re.M).group(1)
            self.assertIn("In %s: " % newest, landing, "the landing tile names the newest release in What's new")
            self.assertIn("House vocabulary", voice)
            h1 = re.search(r"^# (.+)$", (REPO / "CONTEXT.md").read_text(encoding="utf-8"), re.M).group(1)
            self.assertIn(h1, (out / "docs" / "house-vocabulary.html").read_text(encoding="utf-8"))
            self.assertIn('id="overture--start-here"', (out / "docs" / "index.html").read_text(encoding="utf-8"))
            self.assertIn('href="../docs/house-vocabulary.html"', (out / "docs" / "glossary.html").read_text(encoding="utf-8"))
            self.assertTrue((out / "docs" / "troubleshooting.html").is_file())
            # pinned answers: install, an error and the first video open on the page written for them
            for q, want in (("install", "docs/agents.html"), ("doctor", "docs/troubleshooting.html"),
                            ("first video", "docs/guides/first-video.html")):
                hits = rank(out / "search-index.js", q)
                if hits is not None:
                    self.assertTrue(hits[0].startswith(want), (q, hits[:3]))
            # ... and only those: "first look" is a showtime term, "start" is data-start and film.start
            for q in ("first look", "start", "setup"):
                hits = rank(out / "search-index.js", q)
                if hits is not None:
                    self.assertNotIn(hits[0], ("docs/guides/first-video.html", "docs/agents.html"), (q, hits[:3]))
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
