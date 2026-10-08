#!/usr/bin/env python3
"""Site build tests (site/build.py): raw HTML in the docs and the build check.

The docs Markdown is rendered with raw HTML on, for the README-style layout (pictures, centred paragraphs, the
example tables, keys, folding sections). A placeholder written in prose, such as "Style reference: <title>" or
`showtime render <project>`, must show as text: as HTML, <title> starts an element that swallows the rest of the
page in a browser and unknown tags vanish. Asserted: placeholders inline, at the start of a line and inside an
allowed HTML block render escaped; the allowlisted tags and comments pass through; code stays escaped; the build
check (one <title>, a <footer>, the h2 count of the source) catches a cut-off page and passes a whole one; and
every docs page of this checkout renders whole.

usage: python tests/test_site_build.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import importlib.util
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parents[2]
BUILD = REPO / "site" / "build.py"

try:
    import markdown_it  # noqa: F401
    spec = importlib.util.spec_from_file_location("site_build", BUILD)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
except ImportError:  # pragma: no cover
    build = None


def page(body: str, footer: bool = True) -> str:
    return ("<!doctype html><html><head><title>A page</title><script>var a='<b>';</script></head><body><main>%s</main>%s"
            "<script src=\"static/app.js\"></script></body></html>" % (body, "<footer>f</footer>" if footer else ""))


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class Escaping(unittest.TestCase):
    def setUp(self):
        self.md = build.markdown()

    def render(self, text: str) -> str:
        return self.md.render(text)

    def test_inline_placeholders_are_text(self):
        out = self.render('The credit "Style reference: <title>" goes into credits.txt.\n\nUse <Family> SemiBold.\n')
        self.assertIn("Style reference: &lt;title&gt;", out)
        self.assertIn("&lt;Family&gt; SemiBold", out)
        self.assertNotIn("<title>", out)
        self.assertNotIn("<Family>", out)

    def test_table_cell_placeholders_are_text(self):
        out = self.render("| Command | What |\n|---|---|\n| showtime retime <project> -d <seconds> | x |\n"
                          "| <video> in a page | y |\n")
        self.assertIn("showtime retime &lt;project&gt; -d &lt;seconds&gt;", out)
        self.assertIn("&lt;video&gt; in a page", out)
        self.assertNotIn("<project>", out)
        self.assertNotIn("<video>", out)

    def test_placeholder_at_line_start_is_not_an_html_block(self):
        # a list item whose continuation line starts with <title> (as in workflows/paper-explainer.md): <title> is a
        # CommonMark block tag, so it used to open a raw HTML block that broke the code span and swallowed the page
        text = ("- Every figure gets a sidecar: `{\"credit\": \"Figure 3 from <authors>,\n"
                "  <title> (arXiv:<id>), CC BY 4.0\"}`; then more text.\n\n## Next\n")
        out = self.render(text)
        self.assertNotIn("<title>", out)
        self.assertIn("<code>", out)
        self.assertIn("&lt;title&gt; (arXiv:&lt;id&gt;)", out)
        self.assertIn("<h2>Next</h2>", out)
        out = self.render("<title> and more\n\n## After\n")
        self.assertTrue(out.startswith("<p>&lt;title&gt; and more</p>"), out)

    def test_allowed_html_passes_through(self):
        text = ('<p align="center">\n  <picture>\n    <source media="(prefers-color-scheme: dark)" srcset="a-dark.svg">\n'
                '    <img src="a-light.svg" alt="x" width="100%">\n  </picture>\n</p>\n\n'
                '<details>\n<summary><b>Codex</b> · tested</summary>\n\nBody.\n\n</details>\n\n'
                'Press <kbd>?</kbd> for <sub>small</sub> <i>keys</i>.\n\n<!-- a comment -->\n\n'
                '<table>\n<tr>\n<td width="33%" valign="top"><a href="x/"><img src="y.webp"></a><br>text</td>\n</tr>\n</table>\n')
        out = self.render(text)
        for tag in ('<p align="center">', "<picture>", '<source media=', '<img src="a-light.svg"', "<details>",
                    "<summary><b>Codex</b>", "<kbd>?</kbd>", "<sub>small</sub>", "<i>keys</i>", "<!-- a comment -->",
                    '<td width="33%" valign="top">', "<br>"):
            self.assertIn(tag, out)
        self.assertNotIn("&lt;", out)

    def test_disallowed_tag_inside_an_allowed_block_is_escaped(self):
        out = self.render('<p align="center">Style reference: <title> <textarea></p>\n')
        self.assertIn('<p align="center">', out)
        self.assertIn("&lt;title> &lt;textarea></p>", out)   # an escaped "<" is enough: the browser shows the tag as text
        self.assertNotIn("<title>", out)
        self.assertNotIn("<textarea>", out)

    def test_code_stays_escaped(self):
        out = self.render("Write `<title>` here.\n\n```html\n<title>x</title>\n<textarea>\n```\n\n    <iframe>\n")
        self.assertIn("<code>&lt;title&gt;</code>", out)
        self.assertIn("&lt;title&gt;x&lt;/title&gt;", out)
        self.assertIn("&lt;textarea&gt;", out)
        self.assertIn("&lt;iframe&gt;", out)
        self.assertNotIn("<title>", out)

    def test_md_h2_count(self):
        self.assertEqual(build.md_h2_count("# T\n\n## A\n\n```\n## not a heading\n```\n\n## B\n\n### c\n"), 2)


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-site-"))

    def write(self, name: str, text: str) -> str:
        (self.tmp / name).write_text(text, encoding="utf-8")
        return name

    def test_whole_page_passes(self):
        p = self.write("ok.html", page("<h2>A</h2><p>x &lt;title&gt;</p><h2>B</h2><textarea><h2>no</h2></textarea>"))
        self.assertEqual(build.check_pages(self.tmp, [p], {p: ("ok.md", 2)}), [])

    def test_stray_title_is_caught(self):
        # what the browser sees: everything after the stray <title> is its text, footer and later headings included
        p = self.write("cut.html", page("<h2>A</h2><p>Style reference: <title></p><h2>B</h2>"))
        problems = build.check_pages(self.tmp, [p], {p: ("CHANGELOG.md", 2)})
        text = "\n".join(problems)
        self.assertEqual(len(problems), 3, text)
        self.assertIn("cut.html: 2 <title> elements", text)
        self.assertIn("cut.html: no <footer>", text)
        self.assertIn("cut.html: 1 h2 headings, CHANGELOG.md has 2", text)

    def test_title_inside_svg_or_math_is_not_the_pages(self):
        # an accessible inline icon names itself with <title>; only a title outside svg/math is a second page title
        p = self.write("icon.html", page('<svg viewBox="0 0 8 8"><title>icon</title><path d="M0 0h8"/></svg>'
                                        "<h2>A</h2><math><title>sum</title><mi>x</mi></math><svg/><p>after</p>"))
        self.assertEqual(build.check_pages(self.tmp, [p], {p: ("icon.md", 1)}), [])
        q = self.write("both.html", page("<svg><title>icon</title></svg><h2>A</h2><p>Style: <title></p>"))
        self.assertIn("both.html: 2 <title> elements", "\n".join(build.check_pages(self.tmp, [q], {})))

    def test_missing_footer_and_h2_mismatch(self):
        p = self.write("nofoot.html", page("<h2>A</h2>", footer=False))
        q = self.write("short.html", page("<h2>A</h2>"))
        r = self.write("landing.html", page("<h2>A</h2><h2>B</h2>"))
        problems = build.check_pages(self.tmp, [p, q, r], {q: ("short.md", 3)})
        self.assertEqual(problems[0], "nofoot.html: no <footer>: the page is cut off (look for a raw tag such as "
                                      "<title>, <textarea> or <iframe> in its source)")
        self.assertIn("short.html: 1 h2 headings, short.md has 3", problems[1])
        self.assertEqual(len(problems), 2)

    def test_every_docs_page_renders_whole(self):
        # the real docs of this checkout, through the site's Markdown and the check's browser-like scan
        md = build.markdown()
        sources = [s for s, _p, _g in build.doc_sources()] + [build.REFS / "index.md", REPO / "docs" / "README.md"]
        pages, expect = [], {}
        for i, src in enumerate(s for s in sources if s.is_file()):
            text = src.read_text(encoding="utf-8")
            name = "p%03d.html" % i
            self.write(name, page(md.render(text)))
            pages.append(name)
            expect[name] = (src.relative_to(REPO).as_posix(), build.md_h2_count(text))
        self.assertGreater(len(pages), 40)
        self.assertEqual(build.check_pages(self.tmp, pages, expect), [])


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class PeoplePages(unittest.TestCase):
    """The pages written for people (What's new, the FAQ), the counts, and links to examples without a card."""

    def test_counts_come_from_the_gallery(self):
        self.assertEqual([build.count_words(n) for n in (7, 22, 24, 30, 99, 100)],
                         ["Seven", "Twenty-two", "Twenty-four", "Thirty", "Ninety-nine", "100"])
        src = BUILD.read_text(encoding="utf-8")
        for stale in ("Twenty-two videos", "All 22 examples", "Twenty-three videos", "All 23 examples"):
            self.assertNotIn(stale, src)

    def test_whats_new_and_faq_are_doc_pages(self):
        pages = {p: s for s, p, _g in build.doc_sources()}
        self.assertEqual(pages.get("docs/whats-new.html"), REPO / "docs" / "whats-new.md")
        self.assertEqual(pages.get("docs/faq.html"), REPO / "docs" / "faq.md")
        start = [p for p, _label in build.START_PAGES]
        self.assertEqual(start[0], "docs/index.html")
        self.assertIn("docs/whats-new.html", start)
        self.assertIn("docs/faq.html", start)

    def test_example_without_a_card_links_to_github(self):
        # examples/<NN>-*/ folders that have no gallery card get no page; a link to one must not point at a missing page
        tmp = Path(tempfile.mkdtemp(prefix="st-site-"))
        site = build.Site(tmp, [], "owner/repo", None, "main")
        docs = REPO / "docs"
        folders = sorted(d.name for d in build.EXAMPLES.glob("[0-9][0-9]-*") if (d / "README.md").is_file())
        self.assertGreater(len(folders), 1)
        carded, other = folders[0], folders[-1]
        # build_docs gives a page only to the gallery's examples (site.gallery); resolve_ref links what was built
        site.pages[(build.EXAMPLES / carded / "README.md").resolve()] = "examples/%s.html" % carded
        self.assertEqual(site.resolve_ref("../examples/%s/" % carded, docs, "docs/x.html"), "../examples/%s.html" % carded)
        out = site.resolve_ref("../examples/%s/" % other, docs, "docs/x.html")
        self.assertTrue(out.startswith("https://github.com/owner/repo/"), out)


GUIDE_SECTIONS = ["Say this", "What happens", "What you get", "How long it takes", "Phrases that change it", "Limits",
                  "The example"]


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class Guides(unittest.TestCase):
    """docs/guides/: task guides for people, the docs sidebar's first group."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-guides-"))
        self.site = build.Site(self.tmp, [], "o/r", None, "main")
        for src, pg, _g in build.doc_sources():
            self.site.pages[src.resolve()] = pg

    def tearDown(self):
        import shutil
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def guides(self):
        return sorted(p for p in build.GUIDES.glob("*.md") if p.name != "README.md")

    def test_every_guide_is_a_docs_page(self):
        pages = {src.resolve(): (pg, g) for src, pg, g in build.doc_sources()}
        self.assertEqual(pages[(build.GUIDES / "README.md").resolve()], ("docs/guides/index.html", "guides"))
        self.assertGreaterEqual(len(self.guides()), 10)
        for p in self.guides():
            self.assertEqual(pages[p.resolve()], ("docs/guides/%s.html" % p.stem, "guides"), p.name)

    def test_guides_come_first_in_the_sidebar(self):
        groups = build.sidebar_groups(self.site)
        self.assertEqual(groups[0][0], "Guides")
        items = groups[0][1]
        self.assertEqual(items[0], ("All guides", "docs/guides/index.html"))
        index = (build.GUIDES / "README.md").read_text(encoding="utf-8")
        order = re.findall(r"\]\(([a-z0-9-]+)\.md\)", index)
        self.assertEqual([pg for _l, pg in items[1:]], ["docs/guides/%s.html" % s for s in order])
        self.assertEqual(sorted(order), [p.stem for p in self.guides()], "the index links every guide once")
        first = (build.GUIDES / (order[0] + ".md")).read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual("# " + items[1][0], first, "a guide's label is its h1")
        self.assertEqual(sum(1 for g in groups if g[0] == "Guides"), 1)

    def test_every_guide_has_the_same_shape(self):
        for p in self.guides():
            text = p.read_text(encoding="utf-8")
            n = len(text.rstrip("\n").splitlines())
            self.assertTrue(50 <= n <= 90, "%s: %d lines (50-90)" % (p.name, n))
            heads = re.findall(r"^## (.+)$", text, re.M)
            self.assertEqual([h for h in heads if h in GUIDE_SECTIONS], GUIDE_SECTIONS, p.name)
            self.assertRegex(text, r"(example|examples)/|<!-- example: \d\d -->", p.name)

    def test_an_example_without_a_page_links_to_github(self):
        # an example folder links to its page only when the gallery builds it; else to the folder on GitHub
        built = sorted(build.EXAMPLES.glob("[0-9][0-9]-*/README.md"))[0].parent
        self.site.pages[(built / "README.md").resolve()] = "examples/%s.html" % built.name
        page = "docs/guides/x.html"
        self.assertEqual(self.site.resolve_ref("../../examples/%s/" % built.name, build.GUIDES, page),
                         "../../examples/%s.html" % built.name)
        self.assertEqual(self.site.resolve_ref("../../examples/_looks/", build.GUIDES, page),
                         "https://github.com/o/r/tree/main/examples/_looks")


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_site_build: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)
