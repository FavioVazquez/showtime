#!/usr/bin/env python3
"""Caption cards read as phrases and stay in the safe band (caption-karaoke + burned ASS captions).

A 21 s voice-over transcript at ~2.6 words/s (a CLI release note, the kind of dense line a short
carries) is grouped by both caption writers:
  - runtime component (node): no card ends on a weak word ("before", "the", "is"...), no card is on
    screen under minShow, no one-word cards; weak words stay on a line with the word after them;
    the component's weak-word list is the Python one
  - footage captions (Python, ASS for `edit render` / `showtime captions`): no caption ends on a weak
    word in the two-line styles, at most one in 1-line bold-pop (where moving it would flash), none
    under min_show
  - in the browser at 1080x1920 (skipped with --fast): every card's top sits at >= 60 % of the height
    and its bottom at <= 75 % (two-line cards grow down, clear of the content above and the app UI
    below); bold-pop's spoken-word pop never crowds its neighbours; at most one emphasised word per
    card; clean-pop is sentence case.
usage: python tests/test_caption_cards.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
RUNTIME = SKILL / "runtime"
CAPTIONS_JS = RUNTIME / "components" / "captions.js"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.footage import captions as C  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

TEXT = ("tidylines 2.0 is here. Natural sort means file2 finally comes before file10. Add -i to edit in place, "
        "with a .old backup next to the original. And --strip-blank clears empty lines before sorting. Heads up. "
        "--unique now keeps the first copy of a duplicate, not the last. And Python 3.7 is no longer supported.")


def sample_words(rate=2.6):
    """Word times like a TTS voice: longer words take longer, pauses after sentences and commas."""
    raw, t = [], 0.3
    for w in TEXT.split():
        n = len(re.sub(r"[^\w]", "", w)) or 1
        d = 0.1 + 0.05 * n
        raw.append((w, t, t + d))
        t += d + 0.06
        if re.search(r"[.!?]$", w):
            t += 0.38
        elif w.endswith(","):
            t += 0.16
    k = (len(raw) / (raw[-1][2] - raw[0][1])) / rate
    return [{"text": w, "start": round(0.3 + (s - 0.3) * k, 3), "end": round(0.3 + (e - 0.3) * k, 3), "type": "word"}
            for w, s, e in raw]


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node")


def run_node(js):
    node = node_exe()
    if not node:
        raise unittest.SkipTest("node not found")
    cp = subprocess.run([node, "--input-type=module", "-e", js], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", env=ENV, timeout=120)
    if cp.returncode != 0:
        raise AssertionError(cp.stderr[-3000:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


class ComponentGrouping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = ("const m = await import(%s); const W = m.normalizeWords(%s);"
              "const run = (o) => m.groupWords(W.map((w) => ({ ...w })), o).map((g) => ({ words: g.words.map((w) => w.text),"
              "  weak: m.isWeak(g.words[g.words.length - 1].text), dur: g.out - g.in, join: m.lineJoins(g.words, 13) }));"
              "console.log(JSON.stringify({ bold: run({ maxWords: 4, maxChars: 26 }), clean: run({ maxWords: 5, target: 3.5, maxChars: 34 }),"
              "  weak: [...m.WEAK_WORDS] }));") % (json.dumps(CAPTIONS_JS.as_uri()), json.dumps(sample_words()))
        cls.R = run_node(js)

    def test_no_card_ends_on_a_weak_word(self):
        for style in ("bold", "clean"):
            cards = self.R[style]
            ends = [" ".join(c["words"]) for c in cards if c["weak"]]
            self.assertEqual(ends, [], "%s cards end on a weak word" % style)
            texts = [" ".join(c["words"]) for c in cards]
            # the cards the old grouping made from this line ("empty lines before" / "sorting.")
            for bad in ("sorting.", "copy of", "with a", "3.7 is"):
                self.assertNotIn(bad, texts, style)

    def test_no_flash_and_no_orphans(self):
        for style in ("bold", "clean"):
            cards = self.R[style]
            self.assertTrue(all(c["dur"] >= 0.4 - 1e-6 for c in cards), [(c["words"], c["dur"]) for c in cards])
            self.assertEqual([c["words"] for c in cards if len(c["words"]) == 1], [], style)
            # dense speech no longer forces 2-word cards: most cards carry 3-4 words
            sizes = [len(c["words"]) for c in cards]
            self.assertGreaterEqual(sum(1 for n in sizes if n >= 3) / len(sizes), 0.6, (style, sizes))

    def test_weak_words_hold_on_to_the_next_word_on_a_line(self):
        for c in self.R["clean"]:
            for i, w in enumerate(c["words"][:-1]):
                if c["join"][i] is False and w.lower() in ("the", "a", "to", "of"):
                    # released only when the glued run could not fit one line
                    self.assertGreater(len(" ".join(c["words"][i:])), 13, c)

    def test_weak_word_list_matches_the_ass_captions(self):
        self.assertEqual(set(self.R["weak"]), C.FUNCTION_WORDS)


class FootageGrouping(unittest.TestCase):
    def test_ass_groups_avoid_weak_endings(self):
        words = C.display_words(sample_words())
        for name, allowed in (("bold-pop", 1), ("clean", 0), ("boxed", 0), ("minimal", 0), ("cinematic", 0)):
            st = C.get_style(name)
            groups = C.group_words([dict(w) for w in words], st, "portrait")
            weak = [" ".join(w["text"] for w in g["words"]) for g in groups if C.is_weak(g["words"][-1]["text"])]
            self.assertLessEqual(len(weak), allowed, (name, weak))
            short = [g for g in groups if g["end"] - g["start"] < C.min_show(st) - 1e-6]
            self.assertEqual(short, [], name)
            self.assertEqual([w["text"] for g in groups for w in g["words"]], [w["text"] for w in words])

    def test_is_weak(self):
        self.assertTrue(C.is_weak("before"))
        self.assertTrue(C.is_weak("The"))
        self.assertFalse(C.is_weak("before,"))
        self.assertFalse(C.is_weak("sorting."))
        self.assertFalse(C.is_weak("backup"))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/bold.css">
<script>ST.config({"width": 1080, "height": 1920, "fps": 30, "duration": 22});</script>
<script type="module" src="/_st/components/index.js"></script>
</head><body><div class="stage">
<section class="scene" data-start="0" data-dur="22" style="background:#111"></section>
<div id="cap" data-st="caption-karaoke" data-src="words.json" data-style="%s"
     data-emphasis="2.0,natural,-i,.old,--strip-blank,--unique,first,3.7,tidylines"></div>
</div></body></html>"""

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const fs = await import('node:fs');
const words = JSON.parse(fs.readFileSync(path.join(dir, 'words.json'), 'utf8')).words;
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = {};
try {
  for (const style of ['clean-pop', 'bold-pop']) {
    const s = await openStage(b.browser, { url: server.url, page: style + '.html', config: {} });
    const rows = [];
    for (const w of words) for (const dt of [0.04, 0.09, 0.14, 0.3]) {
      await s.seek(w.start + dt);
      rows.push(await s.page.evaluate(() => {
        const el = document.querySelector('#cap');
        const card = [...el.querySelectorAll('.st-cap-card')].find((c) => c.style.display !== 'none');
        if (!card) return null;
        const line = card.querySelector('.st-cap-line');
        const lh = parseFloat(getComputedStyle(line).lineHeight);
        const r = line.getBoundingClientRect();
        const spans = [...card.querySelectorAll('.st-cap-w')].map((sp) => { const q = sp.getBoundingClientRect(); return [q.left, q.top, q.right, q.bottom]; });
        return { text: line.textContent, top: r.top, bottom: r.bottom, lines: Math.round(line.offsetHeight / lh),
          spans, emph: card.querySelectorAll('.st-cap-emph').length, transform: getComputedStyle(card.querySelector('.st-cap-w')).textTransform,
          H: document.querySelector('.stage').getBoundingClientRect().height, stageTop: document.querySelector('.stage').getBoundingClientRect().top };
      }));
    }
    R[style] = rows.filter(Boolean);
    await s.close();
  }
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


@unittest.skipIf(FAST, "needs a browser")
class ComponentLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-capcards-"))
        proj = cls.tmp / "proj"
        proj.mkdir()
        (proj / "words.json").write_text(json.dumps({"words": sample_words()}), encoding="utf-8")
        for style in ("clean-pop", "bold-pop"):
            (proj / (style + ".html")).write_text(PAGE % style, encoding="utf-8")
        (proj / "index.html").write_text(PAGE % "clean-pop", encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        node = node_exe()
        if not node:
            raise unittest.SkipTest("node not found")
        cp = subprocess.run([node, str(probe), str(SKILL), str(proj)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=500)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_cards_hang_below_the_content_and_above_the_app_ui(self):
        for style, rows in self.R.items():
            self.assertGreater(len(rows), 40, style)
            two = [r for r in rows if r["lines"] >= 2]
            self.assertTrue(two, "%s: the sample should give some two-line cards" % style)
            for r in rows:
                top = (r["top"] - r["stageTop"]) / r["H"]
                bottom = (r["bottom"] - r["stageTop"]) / r["H"]
                self.assertGreaterEqual(top, 0.60, (style, r["text"], top))
                self.assertLessEqual(bottom, 0.75, (style, r["text"], bottom))

    def test_active_pop_never_crowds_neighbours(self):
        # the old 1.08-1.14 pop left words glued ("NATURALSORT"): a visible gap of at least 0.15 of the
        # word height stays between neighbours on a line, at every sampled moment of the pop
        for style, rows in self.R.items():
            for r in rows:
                sp = r["spans"]
                for a, b in zip(sp, sp[1:]):
                    if abs(a[1] - b[1]) < 0.5 * (a[3] - a[1]):      # same line
                        self.assertGreaterEqual(b[0] - a[2], 0.15 * (a[3] - a[1]), (style, r["text"], a, b))

    def test_one_emphasis_per_card_and_sentence_case(self):
        for style, rows in self.R.items():
            self.assertTrue(all(r["emph"] <= 1 for r in rows), style)
        self.assertEqual({r["transform"] for r in self.R["clean-pop"]}, {"none"})
        self.assertEqual({r["transform"] for r in self.R["bold-pop"]}, {"uppercase"})


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
