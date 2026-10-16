#!/usr/bin/env python3
"""The line that made an X-ray: `showtime new xray` records xray.made, the live export embeds a prompt and
placeholder commands, and the site's X-ray page builds the live buttons, prompts and embed snippets.

  * new: xray.made = {mechanism, layout, theme} and nothing else (no paths, job names or regions)
  * export: --prompt (else showtime.json xray.made.prompt, else none) and commands with placeholders in the page's
    config; no absolute path anywhere in them; the report states what was embedded; FIGURE_CSP has no frame-ancestors
  * site: build_xray with a live entry writes "Play it live", the prompt with its copy mechanism, the Embed snippet
  * the page says how the events were measured ("xray".measured, else the detector: sound or a data stream) and
    lists showtime.json xray.made.commands when the project gives them; the export warns when the commands name a
    mechanism the library does not have, or carry a local path

Stdlib only (the site part needs markdown-it-py; the page check a browser, skipped with --fast).
usage: python tests/test_xray_made.py [--fast] [-v]
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
SKILL = TESTS_DIR.parent
REPO = SKILL.parents[1]
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-xray-made-"))
FAST = "--fast" in sys.argv
NODE = shutil.which("node", path=ENV.get("PATH"))
# the browser the page driver's openBrowser would start (stagehost: $SHOWTIME_CHROME, a system Chrome, Playwright's)
BROWSER = plat.find_chrome(ENV.get("PLAYWRIGHT_BROWSERS_PATH"))
NO_BROWSER = "--fast: no browser" if FAST else ("needs node" if not NODE else ("needs Chromium (showtime setup)"
                                                                               if not BROWSER else ""))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def live_config(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="xl-cfg">(.*?)</script>', html, re.S)
    assert m, "the page has no xl-cfg block"
    return json.loads(m.group(1))["live"]


@unittest.skipIf(not NODE, "needs node (the export is a node script)")
class TestMade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj = TMP / "proj-split"
        showtime("new", "xray", cls.proj, "--layout", "split", "--theme", "light")
        cls.cfg = json.loads((cls.proj / "showtime.json").read_text(encoding="utf-8"))

    def test_new_records_three_words(self):
        self.assertEqual(self.cfg["xray"]["made"], {"mechanism": "typewriter", "layout": "split", "theme": "light"})

    def test_mechanism_is_recorded(self):
        proj = TMP / "proj-box"
        showtime("new", "xray", proj, "--mechanism", "musicbox")
        made = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))["xray"]["made"]
        self.assertEqual(made, {"mechanism": "musicbox", "layout": "through", "theme": "dark"})
        self.assertNotIn(str(TMP), json.dumps(made))

    def test_export_embeds_the_prompt_and_placeholder_commands(self):
        out = TMP / "live-prompt.html"
        cp = showtime("export", "html", self.proj, "--interactive", "-o", out, "--json",
                      "--prompt", "X-ray this clip of my typewriter.")
        report = json.loads(cp.stdout)
        self.assertEqual(report["made"]["prompt"], "X-ray this clip of my typewriter.")
        made = live_config(out.read_text(encoding="utf-8"))["made"]
        self.assertEqual(made["prompt"], "X-ray this clip of my typewriter.")
        self.assertEqual(made["commands"], [
            "showtime xray analyze clip.mp4 --job xray-typewriter --track",  # the sample is tracked
            "showtime new xray xray-typewriter/project --mechanism typewriter --layout split --theme light",
            "showtime render xray-typewriter/project --job xray-typewriter",
            "showtime xray verify xray-typewriter"])
        for line in made["commands"]:
            self.assertNotIn(str(TMP), line)
            self.assertNotRegex(line, r"(^|\s)(/|[A-Za-z]:\\)")

    def test_mechanism_comes_from_the_project_when_made_is_absent(self):
        proj = TMP / "proj-nomade"
        showtime("new", "xray", proj, "--mechanism", "musicbox")
        p = proj / "showtime.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        del cfg["xray"]["made"]
        p.write_text(json.dumps(cfg), encoding="utf-8")
        out = TMP / "live-nomade.html"
        report = json.loads(showtime("export", "html", proj, "--interactive", "-o", out, "--json").stdout)
        made = live_config(out.read_text(encoding="utf-8"))["made"]
        self.assertIn("--mechanism musicbox", made["commands"][1])
        self.assertIn("xray-musicbox/project", made["commands"][1])
        self.assertFalse(made["guessed"])
        self.assertFalse([w for w in report["warnings"] if "names no mechanism" in w])
        mj = proj / "mechanism.js"  # a name that cannot be read: the typewriter is a guess, and the report says so
        mj.write_text(re.sub(r"name:\s*'[^']*'", "name: 'No Name'", mj.read_text(encoding="utf-8"), count=1), encoding="utf-8")
        out2 = TMP / "live-guess.html"
        report = json.loads(showtime("export", "html", proj, "--interactive", "-o", out2, "--json").stdout)
        self.assertTrue(live_config(out2.read_text(encoding="utf-8"))["made"]["guessed"])
        self.assertTrue([w for w in report["warnings"] if "names no mechanism" in w])

    def test_no_prompt_means_none_and_the_report_says_so(self):
        out = TMP / "live-none.html"
        cp = showtime("export", "html", self.proj, "--interactive", "-o", out)
        self.assertIn("no prompt is embedded", cp.stdout + cp.stderr)
        self.assertEqual(live_config(out.read_text(encoding="utf-8"))["made"]["prompt"], "")

    def test_prompt_from_showtime_json_and_never_from_job_json(self):
        proj = TMP / "proj-cfgprompt"
        shutil.copytree(self.proj, proj)
        p = proj / "showtime.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg["xray"]["made"]["prompt"] = "From the project file."
        p.write_text(json.dumps(cfg), encoding="utf-8")
        (TMP / "job.json").write_text(json.dumps({"request": "SECRET job request"}), encoding="utf-8")
        out = TMP / "live-cfg.html"
        showtime("export", "html", proj, "--interactive", "-o", out)
        html = out.read_text(encoding="utf-8")
        self.assertEqual(live_config(html)["made"]["prompt"], "From the project file.")
        self.assertNotIn("SECRET job request", html)

    def test_framing_is_not_blocked(self):
        fig = (SKILL / "scripts" / "lib" / "export" / "figure.mjs").read_text(encoding="utf-8")
        csp = re.search(r"FIGURE_CSP = \"([^\"]*)\"", fig).group(1)
        self.assertNotIn("frame-ancestors", csp)
        self.assertNotIn("frame-ancestors", (SKILL / "scripts" / "lib" / "export" / "xray.mjs").read_text(encoding="utf-8"))


def variant(base, name, xr=None, detector=None):
    """A copy of a project with showtime.json "xray" keys set (None removes one) and xray.json's detector changed."""
    proj = TMP / name
    shutil.copytree(base, proj)
    p = proj / "showtime.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for k, v in (xr or {}).items():
        if v is None:
            cfg["xray"].pop(k, None)
        else:
            cfg["xray"][k] = v
    p.write_text(json.dumps(cfg), encoding="utf-8")
    if detector:
        x = proj / "xray.json"
        doc = json.loads(x.read_text(encoding="utf-8"))
        doc["detector"] = detector
        x.write_text(json.dumps(doc), encoding="utf-8")
    return proj


DATA_DETECTOR = {"engine": "data", "min_gap": None, "sensitivity": None, "from": 0.0, "to": None,
                 "note": "written from peaks.csv (column t, 19 rows), not from the sound: film time = (t - (-0.14 s)) x 100",
                 "time_map": {"slow": 100, "t0": -0.14}}

PAGE_TEXT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true });
const out = {};
try {
  const pg = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
  await pg.goto(pathToFileURL(FILE).href);
  await pg.evaluate('xrayLive.ready');
  out.receipt = await pg.locator('.xl-receipt').textContent();
  out.drawn = await pg.locator('.xl-drawn').textContent();
  out.cmds = await pg.locator('.xl-cmds textarea').inputValue();
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
console.log(JSON.stringify(out));
"""


@unittest.skipIf(not NODE, "needs node (the export is a node script)")
class TestMeasuredAndCommands(unittest.TestCase):
    """The page states the method that measured the events and the steps that made it."""

    @classmethod
    def setUpClass(cls):
        cls.base = TMP / "proj-base"
        showtime("new", "xray", cls.base, "--layout", "split")

    def export(self, proj, name):
        out = TMP / name
        report = json.loads(showtime("export", "html", proj, "--interactive", "-o", out, "--json").stdout)
        return report, live_config(out.read_text(encoding="utf-8")), out

    def test_measured_from_the_project_and_from_the_detector(self):
        _, live, _ = self.export(variant(self.base, "m1", {"measured": "Red: each wave cycle, lit on its own frame."}), "m1.html")
        self.assertEqual(live["measured"], "Red: each wave cycle, lit on its own frame.")
        self.assertEqual(live["detector"]["engine"], "envelope")
        _, live, _ = self.export(variant(self.base, "m2", {"measured": None}, DATA_DETECTOR), "m2.html")
        self.assertEqual(live["measured"], "")
        self.assertEqual(live["detector"], {"engine": "data", "note": DATA_DETECTOR["note"]})
        self.assertEqual(live["made"]["commands"][0],
                         "showtime xray import events.csv --job xray-typewriter --time-map 100,-0.14 --source clip.mp4")
        js = (SKILL / "runtime" / "xray-live" / "live.js").read_text(encoding="utf-8")
        self.assertIn("var how = L.measured || (", js, "the sound wording is only the fallback")

    def test_made_commands_override_the_list(self):
        steps = ["showtime job init xray-gw", "showtime xray import peaks.csv --job <job> --time-map 100,-0.14",
                 "showtime new xray <job>/project --mechanism typewriter --layout split", "showtime render <job>/project --job <job>"]
        made = {"mechanism": "typewriter", "layout": "split", "theme": "dark", "commands": steps}
        report, live, _ = self.export(variant(self.base, "c1", {"made": made}), "c1.html")
        self.assertEqual(live["made"]["commands"], steps)
        self.assertEqual(report["made"]["commands"], steps)
        self.assertTrue(report["made"]["own"])
        self.assertEqual(report["made"]["unknown_mechanisms"], [])
        self.assertFalse([w for w in report["warnings"] if "library" in w or "local path" in w], report["warnings"])

    def test_a_mechanism_the_library_lacks_is_warned(self):
        made = {"mechanism": "binary", "layout": "split", "theme": "dark"}
        report, live, _ = self.export(variant(self.base, "u1", {"made": made}), "u1.html")
        self.assertIn("--mechanism binary", live["made"]["commands"][1])
        self.assertEqual(report["made"]["unknown_mechanisms"], ["binary"])
        self.assertTrue([w for w in report["warnings"] if "library" in w and "xray.made.commands" in w], report["warnings"])
        own = dict(made, commands=["showtime new xray <job>/project --mechanism binary", "cp /Users/someone/strain.csv <job>/"])
        report, _, _ = self.export(variant(self.base, "u2", {"made": own}), "u2.html")
        self.assertEqual(report["made"]["unknown_mechanisms"], ["binary"])
        self.assertTrue([w for w in report["warnings"] if "does not run" in w], report["warnings"])
        self.assertTrue([w for w in report["warnings"] if "local path" in w], report["warnings"])
        report, _, _ = self.export(variant(self.base, "u3", {"made": dict(made, mechanism="musicbox")}), "u3.html")
        self.assertEqual(report["made"]["unknown_mechanisms"], [])
        self.assertFalse([w for w in report["warnings"] if "library" in w], report["warnings"])

    def test_the_docs_say_the_commands_travel_and_what_the_export_checks(self):
        guide = (SKILL.parent.parent / "docs" / "guides" / "xray.md").read_text(encoding="utf-8")
        flow = (SKILL / "references" / "workflows" / "xray.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(guide.splitlines()), 90)
        self.assertNotIn("never your paths", guide)
        self.assertIn("only warns if one holds a local", " ".join(guide.split()))
        self.assertIn("showtime.json's `xray` block (`made.prompt` too, even with `--prompt`)", " ".join(guide.split()))
        self.assertIn("the prompt and the commands it shows", flow)
        self.assertIn("even when `--prompt` shows another prompt", flow)
        self.assertNotIn("never the project's own paths", flow)
        self.assertIn("only warns if one holds a local path", flow)

    @unittest.skipIf(not NODE, "needs node")
    def test_the_local_path_check_is_exact_and_linear(self):
        mod = (SKILL / "scripts" / "lib" / "export" / "xray.mjs").as_uri()
        js = ("import {localPathLines} from %r; const cmds = JSON.parse(process.argv[1]);"
              " const t = Date.now(); const bad = localPathLines({own: true, commands: cmds});"
              " console.log(JSON.stringify({bad, ms: Date.now() - t}));" % mod)
        cmds = ["showtime xray import events.csv --job <job>", "showtime new xray /Users/me/clip", "x --out=\"/tmp/a b\"",
                "open ~/clips/a.mp4", "ffmpeg -i C:\\Users\\me\\a.mp4", "see https://example.com/a/b", "a=//host/x", "=/" * 13000]
        cp = subprocess.run([NODE, "--input-type=module", "-e", js, json.dumps(cmds)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        res = json.loads(cp.stdout)
        self.assertEqual(res["bad"][:4], cmds[1:5])
        self.assertNotIn(cmds[0], res["bad"])
        self.assertNotIn(cmds[5], res["bad"])
        self.assertLess(res["ms"], 500)

    def test_the_sharing_note_does_not_depend_on_the_commands(self):
        src = (SKILL / "runtime" / "xray-live" / "live.js").read_text(encoding="utf-8")
        note = src.index("Sharing a live page shares what is in it")
        self.assertLess(note, src.index("if (made.prompt ||"))             # outside the "Make your own" box
        self.assertIn("the whole xray block of showtime.json (its made.prompt and made.commands travel with the page even when --prompt shows another prompt)", src)

    def test_the_config_prompt_travels_even_when_prompt_overrides_it(self):
        proj = variant(self.base, "ov", {"made": {"mechanism": "typewriter", "prompt": "config prompt zq81"}})
        out = TMP / "ov.html"
        rep = json.loads(showtime("export", "html", proj, "--interactive", "-o", out, "--json", "--prompt", "shown prompt").stdout)
        self.assertEqual(rep["made"]["prompt"], "shown prompt")
        self.assertIn("config prompt zq81", out.read_text(encoding="utf-8"), "showtime.json's xray block is packed whole")

    @unittest.skipIf(NO_BROWSER, NO_BROWSER)
    def test_the_page_says_it(self):
        steps = ["showtime xray import peaks.csv --job <job> --time-map 100,-0.14", "showtime render <job>/project --job <job>"]
        _, _, out = self.export(variant(self.base, "p1", {"measured": None, "made": {"mechanism": "typewriter", "commands": steps}},
                                        DATA_DETECTOR), "p1.html")
        drv = TMP / "page-text.mjs"
        drv.write_text(PAGE_TEXT, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(out)], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertIn("from a data stream, not from the sound (written from peaks.csv", r["drawn"])
        self.assertNotIn("clip’s own sound", r["drawn"])
        self.assertIn("measured from the data", r["receipt"])
        for line in steps:
            self.assertIn(line, r["cmds"])


try:
    import markdown_it  # noqa: F401
    _spec = importlib.util.spec_from_file_location("site_build", REPO / "site" / "build.py")
    build = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(build)
except ImportError:  # pragma: no cover
    build = None


class TestGuards(unittest.TestCase):
    def test_the_export_tests_skip_without_node(self):
        """On a machine with no node the export classes skip; they do not fail in setUpClass."""
        from unittest import mock
        spec = importlib.util.spec_from_file_location("xray_made_no_node", str(Path(__file__).resolve()))
        mod = importlib.util.module_from_spec(spec)
        with mock.patch("shutil.which", return_value=None):
            spec.loader.exec_module(mod)
        shutil.rmtree(mod.TMP, ignore_errors=True)
        self.assertIsNone(mod.NODE)
        for cls in (mod.TestMade, mod.TestMeasuredAndCommands):
            self.assertTrue(getattr(cls, "__unittest_skip__", False), cls.__name__)


@unittest.skipIf(build is None, "needs markdown-it-py (showtime's venv has it)")
class TestSite(unittest.TestCase):
    def test_xray_page_has_live_prompt_and_embed(self):
        out, media = TMP / "site", TMP / "media" / "examples" / "_xray"
        media.mkdir(parents=True)
        hero = build.XRAY["hero"]
        entry = next(e for e in build.XRAY["entries"] if e["id"] == hero)
        for name in (entry["video"], entry["poster"], entry["live"]):
            (media / name).write_bytes(b"x")
        site = build.Site(out, [TMP / "media"], "owner/repo", None, "main")
        build.build_xray(site)
        text = (out / build.XRAY_PAGE).read_text(encoding="utf-8")
        self.assertIn('class="btn primary xlive xlive-hero"', text)
        self.assertIn('data-live="../media/xray/%s"' % entry["live"], text)
        self.assertEqual(text.count("Play it live"), 1, "only entries whose live page is in this build get a button")
        self.assertIn('<p class="ask">“%s”</p>' % build.esc(entry["prompt"]), text)
        self.assertIn("Make your own with one line", text)
        self.assertIn("&lt;showtime-xray src=&quot;%smedia/xray/%s&quot;" % (build.site_url("owner/repo"), entry["live"]), text)
        self.assertIn("%smedia/xray/%s#embed" % (build.site_url("owner/repo"), entry["live"]), text)
        self.assertTrue((out / "media" / "xray" / entry["live"]).is_file())

    def test_credit_links_are_http_only(self):
        e = {"credit": "Clip", "license": "CC BY", "license_url": "javascript:alert(1)", "credit_url": " data:text/html,x", "author": "showtime"}
        text = build.xray_credit(e)
        self.assertNotIn("javascript:", text)
        self.assertNotIn("data:", text)
        self.assertNotIn("<a href", text.split("posted by")[0])
        self.assertIn('<a href="HTTPS://example.org/l">', build.xray_credit(dict(e, license_url="HTTPS://example.org/l")))

    def test_credit_links_the_clip_and_states_the_film_license(self):
        e = {"credit": "Clip: A & B", "license": "CC BY-SA 3.0", "license_url": "https://example.org/l",
             "credit_url": "https://commons.wikimedia.org/wiki/File:A_<b>.webm", "film_license": "This film is under the same license (share-alike).",
             "author": "showtime"}
        text = build.xray_credit(e)
        self.assertIn('<a href="https://commons.wikimedia.org/wiki/File:A_&lt;b&gt;.webm">Source</a>', text)
        self.assertIn("This film is under the same license (share-alike).", text)
        plain = build.xray_credit({"credit": "Clip: C", "license": "CC BY 3.0", "author": "showtime"})
        self.assertNotIn("Source", plain)

    def test_every_clip_is_linked_and_share_alike_ones_state_the_film_license(self):
        for e in build.XRAY["entries"]:
            self.assertTrue(e["credit_url"].startswith("https://commons.wikimedia.org/wiki/File:"), e["id"])
            self.assertEqual("BY-SA" in e["license"], bool(e.get("film_license")), e["id"])

    def test_embed_frame_has_room_for_the_controls(self):
        src = (REPO / "site" / "build.py").read_text(encoding="utf-8")
        self.assertIn('width="960" height="860"', src)
        self.assertIn('width="420" height="1067"', src)
        self.assertIn('allow="autoplay; clipboard-write"', src)

    def test_every_entry_names_its_live_page_and_one_prompt(self):
        for e in build.XRAY["entries"]:
            self.assertEqual(e["live"], e["id"] + "-live.html")
            self.assertTrue(e["prompt"].strip().endswith((".", "?")), e["id"])
            if e["aspect"] == "9:16":
                self.assertTrue(e["id"].endswith("9x16"), e["id"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])
