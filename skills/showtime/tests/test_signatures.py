#!/usr/bin/env python3
"""Look signatures (st.variety.signatures, `showtime new --look`, `showtime signature`).

Fast (no browser):
  * the catalog: 10-16 signatures, every font shipped, every text colour at accessible contrast (ink 7:1,
    muted and accent text 4.8:1, the ink on the accent 4.5:1) and the product window built from it too;
  * the pick: seeded and deterministic, away from the last picks and the look history's palettes, six new
    projects in a row get six different looks, history off records nothing;
  * `showtime new`: prints the pick and how to change it, --look <id> / template, a dark look refused on the
    data template and any look on a canvas template, a brand kit (found or applied) wins, `brand apply`
    replaces a signature, `showtime signature apply` swaps one (id, next, template);
  * the look history reads the signature, and two pages on one theme in different signatures do not
    repeat the theme.
Browser (skipped with --fast): every signature passes `showtime check` (contrast, text layout, phone
size) on a sample project; the templates take turns, so each is checked with three or more looks.

usage: python tests/test_signatures.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.brand import contrast  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.variety import signatures as S  # noqa: E402

FAST = "--fast" in sys.argv
TMP = Path(tempfile.mkdtemp(prefix="st-signatures-"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def env_for(hist: Path, **extra):
    return dict(build_env(showtime_home()), SHOWTIME_HISTORY_DIR=str(hist), **extra)


def showtime(*args, env, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def page(p: Path) -> str:
    return (p / "index.html").read_text(encoding="utf-8")


def cfg(p: Path) -> dict:
    return json.loads((p / "showtime.json").read_text(encoding="utf-8"))


class Catalog(unittest.TestCase):
    def test_size_ids_fonts(self):
        cat = S.catalog()
        self.assertTrue(10 <= len(cat) <= 16, len(cat))
        self.assertEqual(len({s["id"] for s in cat}), len(cat))
        self.assertEqual({s["polarity"] for s in cat}, {"dark", "light"})
        for s in cat:
            with self.subTest(s["id"]):
                self.assertIn(s["motion"], S.MOTION)
                self.assertIn(s["ground"], S.GROUND)
                for k in ("display", "body", "mono"):
                    f = S.FONT_FILES.get(s["type"][k])
                    self.assertTrue(f and (SKILL / "runtime" / "themes" / "fonts" / (f + ".css")).is_file(), s["type"][k])
        for t in S.TEMPLATES:
            self.assertGreaterEqual(len(S.compatible(t)), 5, t)
        self.assertEqual(S.compatible("film"), [])

    def test_contrast(self):
        for s in S.catalog():
            p = s["palette"]
            with self.subTest(s["id"]):
                self.assertGreaterEqual(contrast(p["fg"], p["bg"]), 7.0)
                self.assertGreaterEqual(contrast(p["fg"], p["surface-2"]), 7.0)
                self.assertGreaterEqual(contrast(p["muted"], p["bg"]), 4.8)
                self.assertGreaterEqual(contrast(p["muted"], p["surface"]), 4.5)
                self.assertGreaterEqual(contrast(p["accent"], p["bg"]), 4.8)
                self.assertGreaterEqual(contrast(p["accent"], p["surface"]), 4.5)
                self.assertGreaterEqual(contrast(p["accent-ink"], p["accent"]), 4.5)
                self.assertGreaterEqual(contrast(p["accent-2"], p["bg"]), 3.0)
                t = S.tokens(s)
                self.assertGreaterEqual(contrast(t["--fg"], t["--bg"]), 7.0)
                self.assertGreaterEqual(contrast(t["--win-fg"], t["--win-bg"]), 7.0)
                self.assertGreaterEqual(contrast(t["--win-muted"], t["--win-bg"]), 4.8)
                self.assertGreaterEqual(contrast(t["--win-accent"], t["--win-bg"]), 4.8)

    def test_block_and_strip(self):
        s = S.get("tidewater")
        b = S.block(s)
        self.assertIn('<style id="st-look">', b)
        self.assertIn("/_st/themes/fonts/space-grotesk.css", b)
        self.assertIn("--ground-glow: 1;", b)
        html = "<html><head><style>x</style>\n" + b + "</head><body></body></html>"
        self.assertEqual(S.strip(html).count("st-look"), 0)


class Picking(unittest.TestCase):
    def test_seeded(self):
        a = [s["id"] for s in S.rank("dom", "seed-1")]
        self.assertEqual(a, [s["id"] for s in S.rank("dom", "seed-1")])
        self.assertEqual(len(a), len(S.compatible("dom")))
        firsts = {S.rank("dom", "seed-%d" % i)[0]["id"] for i in range(12)}
        self.assertGreater(len(firsts), 3, "the seed spreads the first pick")

    def test_away_from_recent(self):
        top = S.rank("launch", "x")[0]
        picks = [{"id": top["id"]}]
        self.assertNotEqual(S.rank("launch", "x", picks)[0]["id"], top["id"])
        # a finished video in a look's palette (the look history): that look is not picked either
        pal = [top["palette"][k] for k in ("bg", "fg", "accent", "accent-2")]
        self.assertNotEqual(S.rank("launch", "x", [], [{"palette": pal, "type": ["Some Face"]}])[0]["id"], top["id"])
        # the last RECENT_PICKS picks all differ
        seen = []
        for i in range(S.RECENT_PICKS):
            nxt = S.rank("dom", "y%d" % i, [{"id": x} for x in reversed(seen)])[0]["id"]
            self.assertNotIn(nxt, seen)
            seen.append(nxt)


class NewProject(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sig-", dir=str(TMP)))
        self.env = env_for(self.dir / "hist")

    def test_new_rotates_and_says_so(self):
        got = []
        for n in range(4):
            p = self.dir / ("p%d" % n)
            cp = showtime("new", "dom", p, env=self.env)
            self.assertIn("look: ", cp.stderr)
            self.assertIn("showtime signature apply %s next" % p.resolve(), cp.stderr)
            got.append(cfg(p)["look"])
            self.assertIn('<!-- look signature: ', page(p))
            self.assertEqual(cfg(p)["background"], S.get(got[-1])["palette"]["bg"])
            self.assertEqual(S.applied(p), got[-1])
        self.assertEqual(len(set(got)), 4, got)
        picks = json.loads((self.dir / "hist" / "picks.json").read_text(encoding="utf-8"))["picks"]
        self.assertEqual([x["id"] for x in picks], got)
        # the signature block comes after the template's own style, before </head>
        html = page(self.dir / "p0")
        self.assertLess(html.rindex("</style>", 0, html.index("<!-- look signature")), html.index("<!-- look signature"))
        self.assertLess(html.index('<style id="st-look">'), html.index("</head>"))

    def test_seed_is_deterministic(self):
        a = showtime("new", "short", self.dir / "a", "--look-seed", "42", "--json", env=env_for(self.dir / "h1")).stdout
        b = showtime("new", "short", self.dir / "b", "--look-seed", "42", "--json", env=env_for(self.dir / "h2")).stdout
        self.assertEqual(json.loads(a)["look"]["id"], json.loads(b)["look"]["id"])

    def test_explicit_and_template(self):
        showtime("new", "dom", self.dir / "c", "--look", "cobalt", env=self.env)
        self.assertEqual(cfg(self.dir / "c")["look"], "cobalt")
        showtime("new", "dom", self.dir / "t", "--look", "template", env=self.env)
        self.assertNotIn("st-look", page(self.dir / "t"))
        self.assertNotIn("look", cfg(self.dir / "t"))
        showtime("new", "data", self.dir / "d", "--look", "paperback", env=self.env)
        cp = showtime("new", "data", self.dir / "e", "--look", "redline", env=self.env, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("light", cp.stderr)
        cp = showtime("new", "film", self.dir / "f", "--look", "sage", env=self.env, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("keeps its own look", cp.stderr)
        showtime("new", "film", self.dir / "g", env=self.env)            # auto on a canvas template: nothing, no error
        self.assertNotIn("look", cfg(self.dir / "g"))

    def test_brand_kit_wins(self):
        base = self.dir / "brand-site"
        base.mkdir()
        (base / "brand.json").write_text(json.dumps({"name": "Acme", "palette": {"bg": "#101418", "ink": "#f5f5f0", "accent": "#3fb68b"}}),
                                         encoding="utf-8")
        # launch applies the kit: no signature, and --look gives way with a warning
        cp = showtime("new", "launch", base / "l", "--look", "cobalt", env=self.env)
        self.assertIn("brand kit's colours win", cp.stderr)
        self.assertNotIn("st-look", page(base / "l"))
        self.assertIn('id="st-brand"', page(base / "l"))
        # dom does not apply kits by itself: a kit nearby still stops the automatic pick
        cp = showtime("new", "dom", base / "d", env=self.env)
        self.assertNotIn("st-look", page(base / "d"))
        self.assertIn("brand kit was found", cp.stderr)
        # a project wearing a signature, then the brand applied: the brand replaces it
        p = self.dir / "later"
        showtime("new", "dom", p, "--look", "sage", env=self.env)
        (p / "brand.json").write_text((base / "brand.json").read_text(encoding="utf-8"), encoding="utf-8")
        showtime("brand", "apply", p, env=self.env)
        self.assertNotIn("st-look", page(p))
        self.assertIn('id="st-brand"', page(p))
        self.assertNotIn("look", cfg(p))
        cp = showtime("signature", "apply", p, "cobalt", env=self.env, check=False)
        self.assertNotEqual(cp.returncode, 0)

    def test_signature_command(self):
        p = self.dir / "s"
        showtime("new", "launch", p, "--look", "graphite", env=self.env)
        res = json.loads(showtime("signature", "apply", p, "next", "--json", env=self.env).stdout)
        self.assertNotEqual(res["id"], "graphite")
        self.assertEqual(res["previous"], "graphite")
        self.assertEqual(page(p).count('<style id="st-look">'), 1, "one block, replaced")
        showtime("signature", "apply", p, "blush", env=self.env)
        self.assertEqual(cfg(p)["look"], "blush")
        showtime("signature", "apply", p, "template", env=self.env)
        self.assertNotIn("st-look", page(p))
        self.assertEqual(cfg(p)["background"], json.loads((SKILL / "templates" / "launch" / "showtime.json").read_text())["background"])
        lst = json.loads(showtime("signature", "list", "--template", "data", "--json", env=self.env).stdout)
        self.assertTrue(lst["signatures"] and all(s["polarity"] == "light" for s in lst["signatures"]))

    def test_history_off_records_nothing(self):
        env = env_for(self.dir / "hoff", SHOWTIME_HISTORY="off")
        showtime("new", "dom", self.dir / "o", env=env)
        self.assertIn("look", cfg(self.dir / "o"))
        self.assertFalse((self.dir / "hoff" / "picks.json").exists())

    def test_look_history_reads_the_signature(self):
        from st.variety import history, look
        a, b = self.dir / "la", self.dir / "lb"
        showtime("new", "dom", a, "--look", "nocturne", env=self.env)
        showtime("new", "dom", b, "--look", "tidewater", env=self.env)
        la, lb = look.project_look(a), look.project_look(b)
        self.assertEqual((la["signature"], la["theme"]), ("nocturne", "bold"))
        self.assertEqual(la["type"][0], "Fraunces")
        self.assertIn("#0f1020", la["palette"])
        self.assertNotIn("theme", {r["aspect"] for r in history.repeats(la, [dict(lb, job="b")])})
        self.assertIn("theme", {r["aspect"] for r in history.repeats(la, [dict(la, job="a2")])})


@unittest.skipIf(FAST, "--fast: needs a browser (check)")
class EverySignaturePassesCheck(unittest.TestCase):
    """Each signature on one sample project (the templates take turns): `showtime check` finds no error
    (contrast, text off the frame or clipped, overlaps, fonts) and the phone check passes."""

    def test_check(self):
        env = env_for(TMP / "check-hist")
        order = list(S.TEMPLATES)
        jobs = []
        for i, s in enumerate(S.catalog()):
            tpls = [t for t in order[i % len(order):] + order[:i % len(order)] if s["polarity"] in S.TEMPLATES[t]]
            jobs.append((s["id"], tpls[0]))

        def run(job):
            sid, tpl = job
            p = TMP / "check" / ("%s-%s" % (tpl, sid))
            showtime("new", tpl, p, "--look", sid, env=env)
            cp = showtime("check", p, "--no-history", "--json", env=env, check=False, timeout=900)
            return sid, tpl, json.loads(cp.stdout)

        with ThreadPoolExecutor(2) as ex:
            for sid, tpl, rep in ex.map(run, jobs):
                with self.subTest(signature=sid, template=tpl):
                    errs = [f for f in rep.get("findings", []) if f.get("severity") == "error"]
                    self.assertEqual(errs, [], "%s on %s: %s" % (sid, tpl, [(f["code"], f["message"][:120]) for f in errs]))
                    self.assertTrue((rep.get("phone") or {}).get("ok"), "phone check: %s" % {k: v for k, v in (rep.get("phone") or {}).items() if k in ("ok", "min_pt", "smallest")})
        self.assertEqual({t for _s, t in jobs}, set(S.TEMPLATES))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
