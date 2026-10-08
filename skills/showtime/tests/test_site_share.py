#!/usr/bin/env python3
"""Site link previews and indexes (site/build.py), the benchmark bar's link to the newest rounds
(site/tools/benchmark_pages.py), and the example links and rebuild steps that point at the right place.

Asserted: page descriptions are whole sentences (never cut inside one) taken from a page's first paragraph; the
shell writes og:url and a canonical link with the same address; an HTML video copied into the site gets
link-preview tags for its address there, keeping an export's own description and absolute image; sitemap.xml,
robots.txt and llms.txt list what they should; the benchmark bar links rounds 5 and 6; the example-media links in
README.md and examples/README.md point at the repository MEDIA.json names; and every example's `showtime new` line
for a page template keeps the template's own look (`--look template`), as the examples were made before look
signatures.

usage: python tests/test_site_share.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parents[2]
SITE = REPO / "site"
EXAMPLES = REPO / "examples"

try:
    import markdown_it  # noqa: F401
    spec = importlib.util.spec_from_file_location("site_build_share", SITE / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
except (ImportError, FileNotFoundError):  # pragma: no cover
    build = None


@unittest.skipIf(build is None, "needs site/ and markdown-it-py (showtime's venv has it)")
class Descriptions(unittest.TestCase):
    def test_whole_sentences_up_to_the_limit(self):
        text = "First sentence here. Second one is a bit longer than that. Third sentence would not fit at all."
        self.assertEqual(build.describe(text, 60), "First sentence here. Second one is a bit longer than that.")
        self.assertEqual(build.describe(text, 30), "First sentence here.")

    def test_a_long_first_sentence_stays_whole(self):
        long = "One sentence that runs on " + "and on " * 40 + "until it stops. Then another."
        self.assertEqual(build.describe(long, 50), long[:-len(" Then another.")])

    def test_no_cut_after_an_abbreviation_or_a_lowercase_word(self):
        text = "Use a flag, e.g. Draft mode, for speed. It helps. version 0.4.0. and more."
        self.assertEqual(build.describe(text, 45), "Use a flag, e.g. Draft mode, for speed.")
        self.assertEqual(build.describe("Ends at x. then lowercase follows here and goes on.", 15),
                         "Ends at x. then lowercase follows here and goes on.")

    def test_text_without_an_end_is_kept_whole(self):
        self.assertEqual(build.describe("Site capture, app recording, SFX"), "Site capture, app recording, SFX")

    def test_first_paragraph_of_markdown(self):
        md = ("---\nname: x\ndescription: front matter\n---\n# Title\n\n<p align=\"center\"><img src=\"a.png\"></p>\n\n"
              "![art](b.png)\n\nRead this when you **build** a [page](x.md) with\n`showtime new`, wrapped over lines. "
              "Second sentence.\n\n## Next\n\nLater text.\n")
        self.assertEqual(build.md_description(md),
                         "Read this when you build a page with showtime new, wrapped over lines. Second sentence.")

    def test_every_docs_page_description_ends_a_sentence(self):
        for src, page, _g in build.doc_sources():
            d = build.md_description(src.read_text(encoding="utf-8"))
            self.assertTrue(d, page)
            self.assertLessEqual(len(d), 400, page)
            if len(d) > build.DESC_LIMIT:   # longer than the limit only when the first sentence is
                self.assertEqual(d, build.describe(d, 10), page)


@unittest.skipIf(build is None, "needs site/ and markdown-it-py (showtime's venv has it)")
class Tags(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-site-share-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def site(self):
        return build.Site(self.tmp, [], "owner/name", None, "main")

    def test_shell_has_canonical_and_og_url(self):
        site = self.site()
        out = build.shell(site, "docs/index.html", "Docs", "<p>x</p>", "docs", "A page. With two sentences.")
        base = build.site_url("owner/name")
        self.assertTrue(base.startswith("https://"))
        self.assertIn('<link rel="canonical" href="%sdocs/">' % base, out)
        self.assertIn('<meta property="og:url" content="%sdocs/">' % base, out)
        self.assertIn('<meta property="og:description" content="A page. With two sentences.">', out)
        self.assertEqual(site.described["docs/index.html"], ("Docs", "A page. With two sentences."))

    def test_html_video_gets_tags(self):
        page = ('<!doctype html><html><head><meta charset="utf-8"><title>Heat &amp; pump</title>'
                '<meta name="description" content="own"></head><body><script>var s="</head>";</script></body></html>')
        out = build.tag_html_video(page, "https://h.io/s/media/a.html", "What it shows.", "https://h.io/s/a/p.jpg")
        head = out[:out.index("</head>")]
        self.assertIn('<meta property="og:title" content="Heat &amp; pump">', head)
        self.assertIn('<meta property="og:description" content="What it shows.">', head)
        self.assertIn('<meta property="og:url" content="https://h.io/s/media/a.html">', head)
        self.assertIn('<meta property="og:image" content="https://h.io/s/a/p.jpg">', head)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', head)
        self.assertIn('<link rel="canonical" href="https://h.io/s/media/a.html">', head)
        self.assertIn('<meta name="description" content="own">', head)
        self.assertEqual(build.tag_html_video(out, "https://h.io/s/media/a.html", "What it shows.",
                                              "https://h.io/s/a/p.jpg"), out)      # a rebuild changes nothing
        self.assertTrue(out.endswith('<script>var s="</head>";</script></body></html>'))

    def test_export_tags_win_where_they_can(self):
        page = ('<html><head><title>T</title>\n<meta property="og:type" content="website">\n'
                '<meta property="og:title" content="Shared title">\n<meta property="og:description" content="Mine.">\n'
                '<meta property="og:url" content="https://old.example/x/">\n<meta property="og:image" content="https://cdn.example/c.jpg">\n'
                '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
                '<meta name="twitter:card" content="summary_large_image">\n</head><body></body></html>')
        out = build.tag_html_video(page, "https://h.io/s/media/b.html", "Site text.", "https://h.io/s/p.jpg")
        self.assertEqual(out.count('property="og:title"'), 1)
        self.assertIn('content="Shared title"', out)
        self.assertIn('<meta property="og:description" content="Mine.">', out)
        self.assertIn('<meta property="og:image" content="https://cdn.example/c.jpg">', out)
        self.assertIn('<meta property="og:image:width" content="1200">', out)
        self.assertIn('<meta property="og:url" content="https://h.io/s/media/b.html">', out)
        self.assertNotIn("old.example", out)
        rel = page.replace("https://cdn.example/c.jpg", "assets/poster.jpg")
        self.assertIn('<meta property="og:image" content="https://h.io/s/p.jpg">',
                      build.tag_html_video(rel, "https://h.io/s/media/b.html", "", "https://h.io/s/p.jpg"))

    def test_sitemap_robots_llms(self):
        site = self.site()
        site.written = ["docs/a.html", "index.html", "docs/index.html", "gallery.html"]
        for p, t, d in (("docs/a.html", "Guide A", "Read this when A."), ("docs/index.html", "Documentation", "Every guide."),
                        ("gallery.html", "Examples", "Videos."), ("docs/agents.html", "Agents", "Install it.")):
            site.described[p] = (t, d)
        site.doc_groups = [("Act I", [("A", "docs/a.html")]), ("Backstage", [("Changelog", "docs/changelog.html")])]
        n = build.write_sitemap(site, ["media/x/v.html"])
        base = build.site_url("owner/name")
        xml = (self.tmp / "sitemap.xml").read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        self.assertEqual(n, 5)
        self.assertEqual(locs[0], base)                                  # the home page first, as its folder
        self.assertIn(base + "docs/", locs)
        self.assertIn(base + "media/x/v.html", locs)
        build.write_robots(site)
        robots = (self.tmp / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *\nAllow: /\n", robots)
        self.assertIn("Sitemap: %ssitemap.xml" % base, robots)
        txt = build.llms_txt(site)
        self.assertTrue(txt.startswith("# showtime\n\n> "))
        self.assertIn("/plugin install showtime@showtime", txt)
        self.assertIn("npx skills add owner/name", txt)
        self.assertIn("- [Agents](%sdocs/agents.html): Install it." % base, txt)
        self.assertIn("- [Documentation map](%sdocs/): Every guide." % base, txt)
        self.assertIn("## Act I\n\n- [Guide A](%sdocs/a.html)\n" % base, txt)
        self.assertNotIn("## Backstage", txt)


@unittest.skipUnless((SITE / "tools" / "benchmark_pages.py").is_file(), "site/ not present")
class BenchmarkRounds(unittest.TestCase):
    def test_bar_links_the_newest_rounds(self):
        sys.path.insert(0, str(SITE / "tools"))
        import benchmark_pages as bp
        self.assertTrue((REPO / bp.LATEST_ROUNDS[0]).is_file(), bp.LATEST_ROUNDS[0])
        root = Path(tempfile.mkdtemp(prefix="st-bench-note-"))
        try:
            (root / "src" / "v0.3.0").mkdir(parents=True)
            (root / "src" / "v0.3.0" / "index.html").write_text("<html><head></head><body>r</body></html>", encoding="utf-8")
            bp.build(root / "src", root / "out", repo="o/r")
            for page in (root / "out" / "index.html", root / "out" / "v0.3.0" / "index.html"):
                html = page.read_text(encoding="utf-8")
                self.assertIn('href="https://github.com/o/r/blob/main/benchmarks/rounds/r5-allout.md"', html)
                self.assertIn("rounds 5 and 6", html)
            self.assertEqual(bp.rounds_link(""), "")
        finally:
            shutil.rmtree(root, ignore_errors=True)


@unittest.skipUnless((EXAMPLES / "MEDIA.json").is_file(), "the examples live in their own repository")
class ExampleLinks(unittest.TestCase):
    def test_media_links_point_at_the_release_repository(self):
        rl = json.loads((EXAMPLES / "MEDIA.json").read_text(encoding="utf-8"))["release"]
        want = "https://github.com/%s/releases/download/%s/" % (rl["repo"], rl["tag"])
        for f in (REPO / "README.md", EXAMPLES / "README.md"):
            links = re.findall(r"https://github\.com/[^/\s]+/[^/\s]+/releases/download/examples-media-[^\s\"')]+", f.read_text(encoding="utf-8"))
            self.assertTrue(links, f)
            self.assertEqual([u for u in links if not u.startswith(want)], [], f)

    def test_rebuild_steps_keep_the_template_look(self):
        lines = []
        for f in sorted(EXAMPLES.glob("[0-9][0-9]-*/README.md")):
            for ln in f.read_text(encoding="utf-8").splitlines():
                if re.match(r"^showtime new (dom|launch|short|data) <", ln):
                    lines.append((f.parent.name, ln))
        self.assertGreaterEqual(len(lines), 12)
        self.assertEqual([x for x in lines if "--look template" not in x[1]], [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
